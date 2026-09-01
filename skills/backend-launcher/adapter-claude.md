# Adapter: claude-subagent

> *"A-Train runs the same track everyone else does — he just runs it in-harness. No new process, no worktree unless you ask, same finish-line check on the way back."*

Read the contract first: [`SKILL.md`](SKILL.md) (the `job_spec → job_result` shape, the git-derived enforcement rule, the worker-prompt lock). This file is the **claude** adapter — it maps a `job_spec` to an in-harness agent and normalizes the return to the canonical `job_result`. It speaks the same contract as [`adapter-codex.md`](adapter-codex.md); the only differences are the launch mechanism (an in-harness agent, not a Bash-spawned process) and that isolation is `direct` by default.

**Which engine launches it (v3.0).** A claude job runs as one **Engine C** `agent()` stage — Engine C being the native Workflow runtime, the name already used across this plugin's shipped docs. Engine C is the primary and default way jobs execute in 3.0, not an opt-in accelerator beside our own loop. The **residual subagent path** — the same in-harness `Task` call this adapter has always described — is retained only for contexts that physically cannot launch a workflow (a subagent has no Workflow tool). Both paths hand the job to an in-harness Claude agent with a resolved model and a turn cap, and both end in the *same* git-derived scope gate, which is why one adapter covers them.

One thing this adapter is **not** allowed to say, because it is wrong: that the residual `Task` path is an "engine" beside Engine C. It is a reduced fallback. The engine letter for the claude path is **C**, and no other letter belongs in this file — the intermediate `claude -p` shell-out design that once carried its own letter was rejected and never shipped.

The defining property: **enforcement is identical to Codex.** The Claude subagent runs the same `git diff` scope gate on return ([`scripts/compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py)), so a Claude job that drifts outside its `write_allowed` is caught and BLOCKED exactly as a Codex job would be. The model is trusted to write code, never trusted to self-report what it changed.

---

## The mapping: `job_spec` → one in-harness agent call

The dispatcher already holds the `job_spec` (from the manifest). This adapter turns it into one agent invocation — an Engine C `agent()` stage, or the identical `Task` call on the residual subagent path:

| `job_spec` field | Where it goes in the `Task` call |
|---|---|
| `prompt` | The agent prompt, prefixed with the worker-prompt lock (below) and the rendered `write_allowed` / `read_allowed` lists |
| `tier` | The routing **intent** (`deep` \| `standard` \| `light`). Resolved to a concrete model **before** dispatch via [`scripts/compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) `--backend claude --tier <tier> --stance <routing_stance>` → `models.claude.<tier>` (native aliases: `deep`/`standard` → `opus` (`standard` → `sonnet` under the `cost-aware` stance), `light` → `sonnet`; **never `haiku`**). The resolver call carries `--stance` from the manifest's `routing_stance` (default `balanced`). The resolved model becomes the subagent's `model` override. |
| `effort` | Advisory only on the Task path (`low` \| `medium` \| `high`). Unlike codex (which surfaces it as `-c model_reasoning_effort`), an in-harness `Task` has **no separate effort flag** — record it, optionally reflect it in the prompt's framing, but do not fabricate a knob that does not exist. |
| `model` | The subagent's model override — the **resolved** `tier`→model value (`opus` or `sonnet`), or an explicit manifest `model` that skips resolution. From routing policy; **never `haiku`**. |
| `cwd` | The directory the subagent operates in: the repo root for `direct`, the worktree path for `worktree` |
| `write_allowed` | Rendered into the prompt as the SCOPE LOCK list, **and** handed to the scope gate on return (the enforced half) |
| `read_allowed` | Rendered into the prompt as the read scope (auto-includes Task 0 outputs + the three audits per the manifest rules) |
| `read_only` | When `true`, the prompt forbids writes and the scope gate expects an empty `files_changed` |
| `timeout_sec` | Advisory only — a `Task` call has no hard timeout knob; long jobs are batched, not time-boxed. Record it; do not fabricate enforcement. |
| `network` | Not a subagent concern (no sandbox flag); ignored for claude, relevant only to codex |
| `output_schema` | Not used to constrain a subagent; the canonical `job_result` is assembled by the caller, not emitted by the subagent. On the Engine C path an Implement stage returns a raw implement result, **never** a `job_result` — `blocked`/`files_changed`/`violations` are git-derived by the caller, and asking the constrained party to fill in its own enforcement fields is the fabricated-evidence pattern with extra steps |
| `test_contract` | The resolved test slice (v3.0 Feature B3). There is no external process here to hand a `--test-contract-file` to, so it is **not** rendered into the prompt: the caller runs the resolved commands itself after the gate and fills `tests` from what it measured. See the test-contract section below |

**Fixed agent parameters** every claude job sets (the `Task` names below; an Engine C `agent()` stage carries the same values as stage options):

- **`subagent`** — the dispatcher's worker subagent (the `Task`-based dispatch reused from 0.1.x). The manifest's `backend: claude` selects this adapter; `model` selects the override.
- **`model`** — the **resolved** `tier`→model value (or an explicit `job_spec.model` override that skips resolution). `claude` resolves `tier` to a native alias via [`scripts/compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py): `deep`/`standard` → `opus` (`standard` → `sonnet` under the `cost-aware` stance), `light` → `sonnet` (the clearly-junior mechanical slices the routing policy marks — bounded CRUD, mechanical refactor, docs/i18n). The resolver call carries `--stance` from the manifest's `routing_stance` (default `balanced`). Resolution happens **before** dispatch so the call site passes a concrete model to the `Task`. No Haiku, ever. `job_spec.effort` is advisory here — the `Task` path has no effort flag, so it is not passed through to any backend call (contrast the codex adapter, which maps `effort` → `-c model_reasoning_effort`).
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
  # on PASS: index-based patch so NEW (untracked) allowed files also land.
  # A plain `git diff HEAD | git apply` would silently DROP added files.
  git -C "$WT" add -A
  git -C "$WT" diff --cached --binary HEAD | (cd "$REPO" && git apply --index)
  git -C "$REPO" worktree remove -f "$WT"
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

**Only `write_allowed` is enforced; `read_allowed` is advisory.** The gate is a git diff, and git tracks writes, not reads. `write_allowed` is the hard boundary; `read_allowed` is rendered into the prompt to scope what the subagent *should* read and documents intent, but there is no git-derived gate that catches an out-of-scope read. Never present `read_allowed` as enforced.

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
| `session_id` | `""` — an in-harness agent has no resumable backend session. Cross-session recovery belongs to the **verification layer** (`state.json` + `/v:resume`), which re-dispatches the job; it never re-attaches a session, and the native runtime's own resume is same-session-only |
| `worktree` | the absolute worktree path for `worktree` jobs; `""` for `direct` jobs |
| `exit_code` | `0` on a clean Task return; non-zero on a Task error |
| `tests` | MEASURED by the caller after the gate (v3.0 B3) — the resolved commands it ran, their exit code, the scope and the count. **Absent** when the job ran no tests. Never the agent's account of what it ran: an agent that says "tests pass" is a summary, not evidence |
| `gate_receipt` | OPTIONAL (v3.0 D1) — the receipt for this job's gate run. Defence in depth and an early exit; the verification layer's integration postcondition is the authority and re-runs the gate itself on a missing, `null` or disagreeing receipt |

On `blocked`: the caller **must not merge** — it halts the run and surfaces the offending paths (worktree jobs leave `$WT` for inspection). On `success`: worktree jobs merge via `git apply`; direct jobs are already in the tree.

---

## Classifying a claude failure (the `failure_class` for the policy loop)

When a claude job returns non-success (errored, hit `maxTurns` without finishing, or the API surfaced a retry error), the dispatcher needs a `failure_class` to drive the [failure policy](../compound-v/failure-policy.md). Unlike the Codex worker — which captures stderr and **emits `failure_class` in its `job_result`** — an in-harness `Task` does not hand back a raw error enum on the canonical result. So for claude, the class is computed by **parsing the stream-json `api_retry.error` enum exactly** — not by scanning prose. Run the adapter/worker with **`--output-format stream-json`** and feed the captured JSONL to the classifier with `--backend claude`:

```bash
# claude path: run with --output-format stream-json so the api_retry event is captured.
#   claude ... --output-format stream-json > "$STREAM_JSON" 2>&1
# The classifier PARSES the JSONL, selects the api_retry event, and maps the EXACT
# api_retry.error enum value — it does NOT substring-scan free text on the JSON path.
python3 scripts/compound-v-classify-failure.py --backend claude \
  --exit-code "$EXIT" --stderr-file "$STREAM_JSON"   # → {failure_class, retryable, matched, retry_after}
```

`--backend claude` selects the Anthropic enum map (exact `api_retry.error` value → class): `billing_error` ⇒ `out_of_credits` (note this is a **400/402, not a 429**), `authentication_failed`/`authentication_error`/`oauth_org_not_allowed`/`permission_error` ⇒ `auth`, `overloaded_error`/`server_error` ⇒ `overloaded`, `rate_limit` ⇒ `rate_limited`, `max_output_tokens` ⇒ `context_length`, and the too-generic `invalid_request`/`model_not_found`/`unknown` ⇒ `other` (deliberately **not** `context_length`, so they don't wrongly trigger a tier escalation). The classifier **only** falls back to a deliberately **narrow** substring match when the captured output isn't JSON; it never scans bare `context`/`invalid_request` text. It also extracts `retry_after` (a `Retry-After` value), which the dispatcher carries as `retry_after_seconds` into the policy. The resulting class flows into [`compound-v-failure-policy.py`](../../scripts/compound-v-failure-policy.py) exactly as a Codex failure does.

**claude has no further local fallback in 1.0.** The fallback chain is `codex → claude → none`: an `out_of_credits` or `auth` failure **on claude** has no backend to re-route to, so the policy returns **`halt`** (circuit-break + resumable) rather than `reroute` — the human tops up / re-auths, then `/v:resume`. Antigravity is the candidate second fallback but ships as a stub deferred to **1.1** (see [`adapter-antigravity.md`](adapter-antigravity.md)). Transient claude failures (rate_limited/overloaded/network/timeout) still **retry on claude** with backoff, capped per-class and by `max_total_retries`.

## Why this adapter is the simple one

No process spawn, no sandbox flags, no `--output-last-message` parsing, no `codex_hooks` stderr to suppress, no session UUID to capture. The subagent runs inside the harness with a model override and a turn cap. The contract holds anyway because **enforcement does not live in the backend** — it lives in the caller's git-diff scope gate, which is identical whether the worker was an in-harness `Task` or a Bash-spawned `codex exec`. Same syringe, same finish-line check.

---

## The test contract on the claude path (v3.0, Feature B3)

Read [`SKILL.md`](SKILL.md) for the contract itself. The other five adapters hand the resolved slice
to a worker script as `--test-contract-file`, precisely so it is not prose a model has to notice.
There is **no external process here**, so this adapter does the honest equivalent rather than
inventing a flag that does not exist:

- The resolved commands are **not** rendered into the agent's prompt. An agent asked to run tests and
  report the result is self-reporting, which is the same defect as asking it for `files_changed`.
- The **caller** — the workflow stage or the verification layer that owns this job — runs the
  resolved commands itself, in the job's worktree (or the repo for a `direct` job), **after** the
  scope gate and only when the job would otherwise be `success`, and fills `job_result.tests` from
  what it measured: `command` (what actually ran, newline-separated when several), `exit_code`
  (0 iff every command exited 0), `scope`, `selected_count`, plus measured-only `duration_ms` and
  `failures[]`. When it runs nothing, `tests` is **absent** — never an invented zero.
- Same ordering rule, same consequence: a file a test writes after the gate is outside the gate's
  authority, so merge-back stages by the gate's `files_changed`, never a bare `git add -A`.
- A non-zero `tests.exit_code` does not change `status`; the caller must not merge, and the review
  gate FAILs a job that reports no test command at all.
