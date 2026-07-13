---
name: backend-launcher
description: Use when Compound V's dispatcher needs to run one file-scoped job on a chosen backend (Claude subagent, headless Codex worker, headless Antigravity worker, headless Cursor worker, headless Devin worker, or headless opencode worker) and get back a canonical job_result. The single job_spec → job_result contract every adapter implements; the orchestrator speaks only this contract and never sees backend-specific flags.
---

# Backend Launcher

> *"Same syringe, different supes. The dispatcher doesn't care who's holding it — it cares what comes back."*

A reusable sub-skill (a sibling directory under `skills/`, pulled in by prose "read this file and apply"). It exposes **one contract**. The orchestrator hands a `job_spec` to whichever adapter the manifest's `backend` names, and gets back a canonical `job_result` — identical shape across every backend. Enforcement is uniform because it lives in the *caller's* scope gate, not in the backend.

There is no skill-import API: an adapter is a sibling doc (`adapter-codex.md`, `adapter-claude.md`, `adapter-antigravity.md`) that says "read the contract in this file, then do the backend-specific steps." Adapters are built by downstream tasks; this file is the contract they implement.

---

## The contract

### INPUT — `job_spec`

```jsonc
{
  "backend": "codex",                  // claude | codex | antigravity | cursor | devin | opencode
  "prompt": "…",                       // the worker prompt (opens with the planner/executor lock, below)
  "tier": "standard",                  // deep | standard | light — the routing INTENT (stable across model churn)
  "effort": "medium",                  // low | medium | high | xhigh — orthogonal reasoning-effort hint (optional; xhigh is codex-only)
  "model": "gpt-5.6-sol",                  // OPTIONAL explicit override; when present it skips resolution.
                                       //   execution-layer data — NEVER appears in any frontmatter
  "cwd": "/repo",                      // absolute repo root
  "write_allowed": ["src/features/sequences/components/**"],
  "read_only": false,                  // true ⇒ sandbox read-only, no merge
  "timeout_sec": 900,
  "network": false,                    // maps to sandbox_workspace_write.network_access
  "output_schema": "/abs/schemas/job_result.schema.json"  // optional
}
```

**`tier` + `effort` + `model` — intent over hardcoded strings.** A `job_spec` carries the routing **intent** (`tier`, and optional `effort`), not a hardcoded model. The concrete `model` is **resolved before dispatch** by [`scripts/compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) from `(backend, tier, effort, config)` — so the plugin survives model churn (refresh the config `models` map via `/v:models`, never the call sites). A job MUST carry `model` OR `tier`; an explicit `model` override skips resolution and always wins. `effort` is passed through to the worker: for `codex` it becomes `-c model_reasoning_effort=<effort>`; for `claude` it is advisory (the `Task` path has no separate effort flag). `xhigh` is valid **iff** `backend: codex`; every other backend rejects it with a clear error naming the rule (use `high` instead) — the resolver and the manifest validator both enforce this. `tier`/`effort`/`model` are execution-layer values and never appear in any frontmatter. See [`skills/compound-v/execution-manifest.md`](../compound-v/execution-manifest.md) for the tier vocabulary, the config `models` map shape, and the reviewer ⇒ deep rule.

### OUTPUT — `job_result` (canonical, identical across backends)

Defined and validated by [`schemas/job_result.schema.json`](../../schemas/job_result.schema.json). Worked instance: [`examples/job_result.example.json`](../../examples/job_result.example.json).

```jsonc
{
  "status": "success",                 // success | blocked | timeout | error
  "blocked": false,                    // true if any file outside write_allowed changed
  "files_changed": ["src/features/sequences/components/Editor.tsx"],
  "violations": [],                    // files written but NOT allowed ⇒ blocked
  "summary": "Added step editor with create/edit/delete.",
  "failure_class": null,               // null on success/blocked; else the classified backend failure
  "session_id": "uuid",                // codex exec resume <uuid>
  "worktree": "/tmp/compound-v/<run-id>/task-1-editor-ui",
  "exit_code": 0
}
```

**`failure_class` — the graceful-failure hook.** On a non-success backend *failure* (not a scope-gate `blocked`), the result carries a `failure_class` ∈ `{out_of_credits, rate_limited, overloaded, auth, context_length, timeout, network, other}` (the Codex worker emits it; `null` on success/blocked). The dispatcher feeds it to the deterministic **classify → policy → act** flow — [`scripts/compound-v-classify-failure.py`](../../scripts/compound-v-classify-failure.py) then [`scripts/compound-v-failure-policy.py`](../../scripts/compound-v-failure-policy.py) → **retry** (same backend, backoff), **reroute** (out_of_credits → circuit-break + env-aware codex→claude rewrite; context_length → bigger tier), or **halt** (resumable). A `claude` job whose result lacks the field is classified by re-reading the stream-json `api_retry.error` enum (`--backend claude`). Full policy: [`skills/compound-v/failure-policy.md`](../compound-v/failure-policy.md).

---

## Git-derived enforcement rule (non-negotiable)

The enforcement fields — `blocked`, `files_changed`, `violations` — are **git-derived by the caller**, never self-reported by the worker model. Compute them inside the worktree (or against a baseline commit for `direct` jobs):

```bash
files_changed=$(git -C "$WT" diff --name-only; git -C "$WT" ls-files --others --exclude-standard)
```

Both halves are required: `diff --name-only` catches edits to tracked files; `ls-files --others --exclude-standard` catches brand-new untracked files the diff would miss. Anything in `files_changed` that does not match `write_allowed` becomes a `violation` ⇒ `blocked: true`, `status: "blocked"`, and the caller **must not merge** — it halts the run and surfaces the offending paths. The model's `--output-last-message` text feeds only the human `summary`; never trust it to report what it changed.

The deterministic authority is [`scripts/compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py) (built downstream). This file states the rule; that script is what the dispatcher actually calls after every job.

**Only `write_allowed` is enforced; `read_allowed` is advisory.** The gate is git-derived, and git tracks writes, not reads. `write_allowed` is the hard boundary — any changed path outside it is a `violation` ⇒ `blocked`. `read_allowed` (in the `job_spec`) is **advisory only**: it scopes the worker prompt and documents intent, but git cannot detect an out-of-scope read, so there is no deterministic gate behind it. Never present `read_allowed` as enforced.

---

## External-CLI launch — supervisor + closed stdin (non-negotiable)

**Every** external-CLI invocation — a dispatched worker (codex/cursor/agy) OR an orchestrator-level call (the cross-model plan review [`scripts/compound-v-codex-review.sh`](../../scripts/compound-v-codex-review.sh), any ad-hoc verification) — MUST run **through the process-group timeout supervisor** [`scripts/compound-v-run-with-timeout.py`](../../scripts/compound-v-run-with-timeout.py) with **`stdin </dev/null`**:

```bash
python3 scripts/compound-v-run-with-timeout.py --timeout <sec> --grace 3 -- <cli> … </dev/null
```

- **`</dev/null`** — `codex`/`cursor`/`agy` read stdin when it is not a TTY and **hang on `Reading additional input from stdin…`** in a background/non-interactive run. (This exact bug once left an ad-hoc codex review hung for 44 minutes at 0% CPU.) The redirect makes stdin an immediate EOF; the supervisor also forces `stdin=DEVNULL` on the child.
- **The supervisor** guarantees a hard cap even when no `timeout`/`gtimeout` binary is installed, and `killpg`s the **whole process group** on expiry (a bare `timeout` prefix signals only the direct child, leaking orphaned tool children past the scope gate) → exit `124` → the `timeout` failure class.

**A bare `codex`/`cursor`/`agy` call — no supervisor, or no `</dev/null` — is a bug.** The dispatcher's [liveness sweep](../compound-v/state-machine.md) *detects* a hang after the fact; this launch rule *prevents* it. (All three worker scripts already comply; `compound-v-codex-review.sh` was brought under the supervisor in v2.5.0.)

## Worktree git-base fixes — the CALLER's job, never the worker's (non-negotiable)

**Never ask an external worker (Codex/Antigravity/Cursor) to fix its own worktree's git base** (rebase, reset, fetch, or any other repair of the worktree's git plumbing). If a worktree's base is wrong — stale relative to a merged prerequisite, or otherwise needs correcting — that is resolved by the **caller** recreating the worktree, never by instructing the worker to patch it mid-run.

Two independent reasons this must stay caller-side, not worker-side:
- **Every external worker already recreates its worktree fresh at current HEAD on every invocation** (each adapter's create step: remove any stale worktree at that path, then `git worktree add <WT> HEAD` — "idempotent on resume", documented per-backend in `adapter-codex.md` / `adapter-cursor.md` / `adapter-antigravity.md`). A job that needs a different base — e.g. it depends on another job's *already-merged* output — needs that modeled as `depends_on` in the manifest so the caller dispatches it in the right order, not patched after the fact. **But `depends_on` alone is not enough — the caller MUST commit the prerequisite's merged output before creating the dependent job's worktree.** Merge-back (`git apply --index`) only *stages* a job's changes into the caller's tree; it does **not** commit, so `HEAD` does not move. `git worktree add <WT> HEAD` checks out the last **commit**, not the caller's currently-staged/uncommitted state — so if the prerequisite's work is only staged, not committed, the dependent job's "fresh worktree at HEAD" will **not** contain it. Always commit a prerequisite's merge-back result before dispatching anything that `depends_on` it (see `parallel-dispatcher.md` Step 1→2).
- **Codex specifically cannot do it even if asked**, under the documented pinned invocation (`--sandbox workspace-write --cd "$WT"`, no sandbox-bypass flag). A git worktree's `.git` is a *file* pointing at `<main-repo>/.git/worktrees/<name>/`, where the actual per-worktree git metadata (`HEAD`, index, etc.) physically lives — **outside** the worktree directory itself. Codex's sandbox confines writes to `$WT` only, so any git operation touching that metadata falls outside the sandbox root; combined with `approval_policy: never` (no one to ask for escalation — see the launch rule above), the operation is simply not permitted under that invocation. This is a **sandbox limitation, not a code one** — dropping worktree isolation to work around it is not a fix, it removes the only file-scope enforcement Codex has (`codex ⇒ worktree` is a hard invariant in `compound-v-validate-manifest.py`, precisely because Codex can only be confined to a *directory*, never to a file allow-list).

If a job ever appears to need a git-base fix mid-run, that is a signal the run's dependency ordering is wrong (missing `depends_on`, or a prerequisite's merge-back was never committed) or a retry skipped the worker's normal create step — fix the manifest/commit the prerequisite or re-dispatch through the full lifecycle; never patch the worker's worktree by hand or delegate the patch to the worker itself.

---

## Worker prompt lock (planner/executor separation)

Every dispatched `prompt` opens with this lock, verbatim-in-spirit:

> You are an implementation worker, NOT the planner. Do not change architecture. Do not write outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report BLOCKED.

This is the *instructed* half. The git-diff scope gate above is the *enforced* half. An executor — especially a non-Claude one like Codex — cannot silently change the plan or stomp shared files because the gate catches it regardless of what the prompt did or didn't constrain.

---

## The adapters (contract level)

| Adapter | Backend | Mechanism | Isolation | Enforcement | Status |
|---|---|---|---|---|---|
| `adapter-claude.md` | Claude subagent | in-harness `Task` (model override, `maxTurns: 15`) | `direct` or optional `worktree` | same caller scope gate on return | ships v1.0 |
| `adapter-codex.md` | headless Codex | Bash-spawned `codex exec` (own process, own worktree) | `worktree` (mandatory) | git-diff scope gate | ships v1.0 |
| `adapter-antigravity.md` | headless Antigravity | Bash-spawned `agy --print` (own process, own worktree) | `worktree` (mandatory) | git-diff scope gate | ships 1.1 — **lower-trust / opt-in (no kernel sandbox)** |
| `adapter-cursor.md` | headless Cursor | Bash-spawned `cursor-agent -p -f` (own process, own worktree) | `worktree` (mandatory) | git-diff scope gate | ships 2.1 — **lower-trust / opt-in (no kernel sandbox)** |
| `adapter-devin.md` | headless Devin | Bash-spawned `devin -p` (own process, own worktree) | `worktree` (mandatory) | git-diff scope gate | **lower-trust / opt-in, WORKER-ONLY** (Research-Preview `--sandbox`, unverified coverage; multi-vendor model broker — excluded from any arbiter panel) |
| `adapter-opencode.md` | headless opencode | Bash-spawned `opencode run` (own process, own worktree) | `worktree` (mandatory) | git-diff scope gate | **lower-trust / opt-in, WORKER-ONLY** (no kernel sandbox; multi-provider `provider/model` router — excluded from any arbiter panel until family-dedup keys on the resolved model) |

- **claude-subagent** — reuses today's `Task`-based dispatch with a `model` override and `maxTurns: 15`, optionally inside a worktree, and runs the **same** scope gate on return so enforcement is identical to Codex. Direct writes are gated against a baseline commit.
- **codex** — a Bash-spawned `codex exec` worker in its own process and its own worktree (never an `agents/` entry, never the experimental `openai-codex` app-server broker, which is single-flight and can't fan out). Pinned flag set below.
- **antigravity** — a Bash-spawned `agy --print` worker in its own process and its own worktree, mirroring Codex (worktree + git-diff scope gate, normalize → `job_result`). **Lower-trust / opt-in:** `agy` has **no kernel write-confinement** like Codex's `--sandbox workspace-write`, and headless writes require `--dangerously-skip-permissions` (arbitrary shell + out-of-worktree writes possible). The git-diff gate enforces file-scope *inside* the worktree but cannot *prevent* an out-of-worktree side-effect — so **prefer Codex for untrusted / high-stakes work**, and route to Antigravity only when the prompt/surface is trusted. Available only when `agy` is installed (env-aware routing). Runbook: [`adapter-antigravity.md`](adapter-antigravity.md); worker: [`scripts/compound-v-run-antigravity-worker.sh`](../../scripts/compound-v-run-antigravity-worker.sh).
- **cursor** — a Bash-spawned `cursor-agent -p -f` worker in its own process and its own worktree, mirroring Antigravity (worktree + git-diff scope gate, normalize → `job_result`). **Lower-trust / opt-in (same tier as Antigravity):** cursor-agent has **no kernel write-confinement**, and a headless run **requires `-f`** (an untrusted dir is otherwise refused) which also grants arbitrary write+shell. Verified live (success + BLOCKED paths). Output is one JSON object — `.result` → summary, `.session_id` (a real UUID) → resumable via `cursor-agent --resume`. **Prefer Codex for untrusted / high-stakes work**; route to Cursor only when the prompt/surface is trusted (its editing models suit isolated build/UI work). Available only when `cursor-agent` is installed AND authenticated (env-aware routing). Runbook: [`adapter-cursor.md`](adapter-cursor.md); worker: [`scripts/compound-v-run-cursor-worker.sh`](../../scripts/compound-v-run-cursor-worker.sh).
- **devin** — a Bash-spawned `devin -p` worker in its own process and its own worktree, mirroring Antigravity/Cursor (worktree + git-diff scope gate, normalize → `job_result`). **Lower-trust / opt-in, WORKER-ONLY (v1):** Devin has a real, live-confirmed kernel `--sandbox` flag (macOS Seatbelt / Linux bwrap+seccomp) — a genuine differentiator — but it is labelled "[Research Preview]" by Cognition, its coverage is scoped to "exec-tool processes" (non-shell tool coverage unverified), and network filtering is admitted-unstable, so this plugin treats it as no-confinement for v1 and relies on the worktree + git-diff gate exactly like Antigravity/Cursor. Devin is also a **multi-vendor model broker** (`--model` spans Claude/GPT/Gemini/Devin's own SWE family) — its resolved model family is data-dependent, so it is **excluded from any cross-model arbiter/review panel** until family-dedup keys on the resolved model rather than the backend name. Available only when `devin` is installed AND authenticated (`devin auth login` / `COGNITION_API_KEY`). Runbook: [`adapter-devin.md`](adapter-devin.md); worker script: draft only, not yet built (see the adapter for the pinned invocation).
- **opencode** — a Bash-spawned `opencode run` worker in its own process and its own worktree, mirroring Antigravity/Cursor (worktree + git-diff scope gate, normalize → `job_result`). **Lower-trust / opt-in, WORKER-ONLY (v1):** opencode has **no kernel write-confinement at all** and, per its own docs, defaults to allowing all operations without explicit approval — the opposite default posture from Cursor/Antigravity's refuse-until-unlocked stance. opencode is **provider-agnostic** — every resolved model is a `provider/model` string, and the provider may differ per tier — so, like Devin, it is **excluded from any cross-model arbiter/review panel** until family-dedup keys on the resolved model. **Load-bearing safety caveat:** opencode can authenticate purely from inherited provider env vars (live-observed: it completed a real request with zero stored credentials via an ambient `ANTHROPIC_BASE_URL`) — the worker MUST scrub the dispatcher's own provider env vars rather than blindly inherit them (see the adapter). Available only when `opencode` is installed AND a provider is configured (stored credentials or an intentional env var). Runbook: [`adapter-opencode.md`](adapter-opencode.md); worker script: draft only, not yet built (see the adapter for the pinned invocation).

---

## Pinned `codex exec` flag set (verified live against codex-cli 0.144.1)

The codex adapter MUST use exactly this flag set, launched **under the process-group supervisor with `stdin </dev/null`** per the non-negotiable rule above (never a bare `timeout … codex exec`):

```bash
python3 scripts/compound-v-run-with-timeout.py --timeout "$timeout_sec" -- codex exec \
  --cd "$WT" \
  --sandbox "$([ "$read_only" = true ] && echo read-only || echo workspace-write)" \
  --skip-git-repo-check \
  --model "$model" \
  --json \
  ${output_schema:+--output-schema "$output_schema"} \
  --output-last-message "$WT/.job_result.txt" \
  -c "sandbox_workspace_write.network_access=$network" \
  "$prompt" </dev/null >"$events_log"
```

`--json` streams JSONL events to stdout (redirected by the worker's own shell to
`$events_log`, an absolute run-dir path); the worker parses the first `thread.started`
event's `thread_id` (UUID-validated) into `job_result.session_id`, and liveness reads the
same stream. `--output-last-message` still yields the canonical result (the two coexist).

Pinned facts (do not re-derive):

- **`--ask-for-approval never` is INVALID for `codex exec`.** It is a top-level/interactive flag, absent from `codex exec --help`; `exec` already defaults to `approval: never`. Passing it fails every Codex job. **Omit it.** If a non-default policy is ever needed: `-c approval_policy=never`.
- **Resume** is `codex exec resume <SESSION_ID> [PROMPT]` (the captured `thread_id` UUID) or `--last`. There is **no `--session-id` flag** and no launch-time thread naming. Capture the UUID from the first `--json` `thread.started` event into `session_id` (UUID-validated); resume only under the resume-eligibility rule.
- **`git worktree diff` does not exist.** Use plain `git -C "$WT" diff --name-only` + `git -C "$WT" ls-files --others --exclude-standard`.
- Codex emits a cosmetic `[features].codex_hooks is deprecated` stderr warning — the worker script suppresses/ignores it so it doesn't pollute captured output.
- `--output-schema` accepts a strict JSON Schema (`additionalProperties:false` + `required`) — point it at `job_result.schema.json` when a schema'd summary is wanted. The schema drives only the human summary; enforcement stays git-derived.

---

## Merge-back

On **PASS**: apply the worktree's changes — **including new (untracked) files** — into the main tree, then `git worktree remove -f`. A plain `git diff HEAD | git apply` would silently DROP added files (an allowed new file passes the gate but never lands), so use an index-based patch:

```bash
git -C "$WT" add -A
git -C "$WT" diff --cached --binary HEAD | (cd "$REPO" && git apply --index)
git -C "$REPO" worktree remove -f "$WT"
```

On **BLOCKED**: leave the worktree for inspection, do **not** merge. Worktrees live under `$TMPDIR/compound-v/<run-id>/<job-id>` (outside the repo — no `.gitignore` change needed). This loses per-job commit attribution, which is acceptable for disjoint file sets.
