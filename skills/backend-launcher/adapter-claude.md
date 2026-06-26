# Adapter: claude-subagent

> *"A-Train runs the same track everyone else does — he just runs it in-harness. No new process, no worktree unless you ask, same finish-line check on the way back."*

Read the contract first: [`SKILL.md`](SKILL.md) (the `job_spec → job_result` shape, the git-derived enforcement rule, the worker-prompt lock). This file is the **claude** adapter — it maps a `job_spec` to an in-harness `Task` call and normalizes the return to the canonical `job_result`. It speaks the same contract as [`adapter-codex.md`](adapter-codex.md); the only differences are the launch mechanism (a `Task` tool call, not a Bash-spawned process) and that isolation is `direct` by default.

The defining property: **enforcement is identical to Codex.** The Claude subagent runs the same `git diff` scope gate on return ([`scripts/compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py)), so a Claude job that drifts outside its `write_allowed` is caught and BLOCKED exactly as a Codex job would be. The model is trusted to write code, never trusted to self-report what it changed.

---

## The mapping: `job_spec` → `Task` call

The dispatcher already holds the `job_spec` (from the manifest). This adapter turns it into one `Task` invocation:

| `job_spec` field | Where it goes in the `Task` call |
|---|---|
| `prompt` | The Task prompt, prefixed with the worker-prompt lock (below) and the rendered `write_allowed` / `read_allowed` lists |
| `model` | The subagent's model override (`opus` or `sonnet` — from routing policy; **never `haiku`**) |
| `cwd` | The directory the subagent operates in: the repo root for `direct`, the worktree path for `worktree` |
| `write_allowed` | Rendered into the prompt as the SCOPE LOCK list, **and** handed to the scope gate on return (the enforced half) |
| `read_allowed` | Rendered into the prompt as the read scope (auto-includes Task 0 outputs + the three audits per the manifest rules) |
| `read_only` | When `true`, the prompt forbids writes and the scope gate expects an empty `files_changed` |
| `timeout_sec` | Advisory only — a `Task` call has no hard timeout knob; long jobs are batched, not time-boxed. Record it; do not fabricate enforcement. |
| `network` | Not a subagent concern (no sandbox flag); ignored for claude, relevant only to codex |
| `output_schema` | Not used to constrain a subagent; the canonical `job_result` is assembled by the caller, not emitted by the subagent |

**Fixed Task parameters** every claude job sets:

- **`subagent`** — the dispatcher's worker subagent (the `Task`-based dispatch reused from 0.1.x). The manifest's `backend: claude` selects this adapter; `model` selects the override.
- **`model`** — the override from `job_spec.model`. Opus by default; Sonnet only for the clearly-junior mechanical slices the routing policy marks (bounded CRUD, mechanical refactor, docs/i18n). No Haiku, ever.
- **`maxTurns: 15`** — the standard ceiling for a scoped implementation slice. Enough turns to write + self-check a partitioned file set; small enough that a runaway job ends rather than churns.
- **`run_in_background`** — set `true` for jobs the manifest schedules into a background batch (`run: parallel` beyond the foreground 4–6 ceiling); `false` for foreground/serial jobs. When background, **pass `cwd` and every path as absolute** (background subagents do not inherit the foreground cwd reliably — the same caveat the dispatch phase pins).

The dispatcher fans out a batch of these `Task` calls (foreground 4–6, background up to 5–10) per [`phase-3-parallel-opus-dispatch.md`](../compound-v/phase-3-parallel-opus-dispatch.md), respects `depends_on`, and collects each return through the steps below.

---

## Worker prompt lock (prepended to every dispatched prompt)

Verbatim-in-spirit, opening the prompt before the task body — the same lock the codex adapter uses, so the *instructed* half of planner/executor separation is uniform across backends:

> You are an implementation worker, NOT the planner. Do not change architecture. Do not write outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report BLOCKED.

Then the rendered SCOPE LOCK (the `write_allowed` globs), the read scope, the acceptance items for this job, and the task body from `job_spec.prompt`. The lock is the instructed half; the scope gate below is the enforced half — a subagent that ignores the prose is still caught by git.

---

## Isolation: `direct` (default) or `worktree` (optional)

Isolation is per-job, set by the planner in the manifest — not a global mode.

- **`direct`** (default for claude) — the subagent writes in place against the main tree. Fast, no worktree setup. The scope gate runs against a **baseline commit** captured *before* dispatch, so the diff still reflects only this job's writes. Use when the planner is confident the file set is disjoint from siblings.
- **`worktree`** (optional) — for any Claude job the planner judges overlap-prone (or that touches risky surfaces). Add the worktree before dispatch, point the subagent's `cwd` at it, and merge back on PASS exactly as the codex adapter does:

  ```bash
  WT="$TMPDIR/compound-v/<run-id>/<job-id>"
  git worktree add "$WT" HEAD            # before dispatch
  # … run the Task with cwd=$WT …
  # on PASS:
  git -C "$WT" diff HEAD | git apply     # merge into main tree
  git worktree remove -f "$WT"
  # on BLOCKED: leave $WT for inspection, do NOT merge
  ```

  Direct Claude jobs and worktree jobs in the same batch must not collide at merge — the disjoint-`write_allowed` invariant (checked by `partition-reviewer`) is what guarantees that.

Either way, **the `git diff` scope gate is the constant; the worktree is the escalation.**

---

## The SAME scope gate on return (the enforced half)

When the `Task` returns, the dispatcher runs the identical git-derived gate from [`SKILL.md`](SKILL.md) — never trusting the subagent's own account of what it touched. Compute the changed set inside the worktree (or against the pre-dispatch baseline commit for `direct` jobs):

```bash
# worktree job:
files_changed=$(git -C "$WT" diff --name-only; git -C "$WT" ls-files --others --exclude-standard)

# direct job (baseline = the commit captured before dispatch):
files_changed=$(git diff --name-only "$BASELINE"; git ls-files --others --exclude-standard)
```

Both halves are required: `diff --name-only` catches edits to tracked files; `ls-files --others --exclude-standard` catches brand-new untracked files. Anything in `files_changed` not matching `write_allowed` is a `violation`. The deterministic authority is [`scripts/compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py); this adapter calls it after every job. If `read_only` was set, any non-empty `files_changed` is itself a violation.

---

## Normalize → canonical `job_result`

Assemble the [canonical `job_result`](../../schemas/job_result.schema.json) from git-derived facts plus the subagent's text. The caller builds this — the subagent does not emit it:

| Field | Source |
|---|---|
| `files_changed` | git-derived (the union above) — **never** the subagent's self-report |
| `violations` | subset of `files_changed` outside `write_allowed` (from the scope-check) |
| `blocked` | `true` iff `violations` is non-empty |
| `status` | `blocked` if `blocked`; else `error` if the Task errored / hit `maxTurns` without finishing; else `success` |
| `summary` | the subagent's final message — **informational only**, never used for enforcement |
| `session_id` | `""` — an in-harness `Task` has no resumable backend session (resume re-dispatches the job via Engine A; it does not re-attach a session) |
| `worktree` | the absolute worktree path for `worktree` jobs; `""` for `direct` jobs |
| `exit_code` | `0` on a clean Task return; non-zero on a Task error |

On `blocked`: the caller **must not merge** — it halts the run and surfaces the offending paths (worktree jobs leave `$WT` for inspection). On `success`: worktree jobs merge via `git apply`; direct jobs are already in the tree.

---

## Why this adapter is the simple one

No process spawn, no sandbox flags, no `--output-last-message` parsing, no `codex_hooks` stderr to suppress, no session UUID to capture. The subagent runs inside the harness with a model override and a turn cap. The contract holds anyway because **enforcement does not live in the backend** — it lives in the caller's git-diff scope gate, which is identical whether the worker was an in-harness `Task` or a Bash-spawned `codex exec`. Same syringe, same finish-line check.
