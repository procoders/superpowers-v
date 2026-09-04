---
name: backend-launcher
description: Use when Compound V's dispatcher needs to run one file-scoped job on a chosen backend (Claude subagent, headless Codex worker, headless Antigravity worker, headless Cursor worker, or headless opencode worker) and get back a canonical job_result. The single job_spec → job_result contract every adapter implements; the orchestrator speaks only this contract and never sees backend-specific flags.
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
  "backend": "codex",                  // claude | codex | antigravity | cursor | opencode
  "prompt": "…",                       // the worker prompt (opens with the planner/executor lock, below)
  "tier": "standard",                  // frontier | deep | standard | light — the routing INTENT (stable across model churn)
  "effort": "medium",                  // low | medium | high | xhigh — orthogonal reasoning-effort hint (optional; xhigh is codex-only)
  "model": "gpt-5.6-sol",                  // OPTIONAL explicit override; when present it skips resolution.
                                       //   execution-layer data — NEVER appears in any frontmatter
  "cwd": "/repo",                      // absolute repo root
  "write_allowed": ["src/features/sequences/components/**"],
  "read_only": false,                  // true ⇒ sandbox read-only, no merge
  "timeout_sec": 900,
  "network": false,                    // maps to sandbox_workspace_write.network_access
  "output_schema": "/abs/schemas/job_result.schema.json", // optional
  "test_contract": {                   // optional (v3.0 Feature B3) — the RESOLVED test contract
    "scope": "impacted",               //   full | impacted | floor_only | impacted+referencing (the job's test_scope; the last is 3.4.1's SCOPED/DIRECT unmapped-path resolution)
    "floor_command": "bash tests/run-floor.sh",
    "full_command":  "bash tests/run-all.sh",
    "resolved_commands": [             //   caller-resolved, ordered, deduped; the floor is first
      "bash tests/run-floor.sh",
      "python3 scripts/compound-v-preeval.py --selftest"
    ]
  }
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
  "exit_code": 0,
  "tests": {                           // optional, MEASURED-ONLY (v3.0 B3) — absent when no tests ran
    "command": "bash tests/run-floor.sh\npython3 scripts/compound-v-preeval.py --selftest",
    "exit_code": 0,
    "scope": "impacted",
    "selected_count": 2,
    "duration_ms": 8412,               //   measured-only: ABSENT rather than estimated
    "failures": []                     //   measured-only: the identifiers that failed
  },
  "gate_receipt": { … }                // optional (v3.0 D1) — one scope-gate run, bound to two commits
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

## The test contract is an ARGUMENT, never prompt prose (v3.0, Feature B3)

Before 3.0 there was no transport at all: every worker takes `--prompt-file`, and the `job_spec` had
no test field — so a job's `test_scope` could only reach an external worker as a sentence inside a
prompt, hoping the model noticed it. A value a model has to notice is not a contract. It is the same
failure the triage block exists to remove, one layer down.

**The slice.** `job_spec.test_contract` is the **resolved** contract for exactly one job:

```jsonc
"test_contract": {
  "scope": "impacted",                    // full | impacted | floor_only | impacted+referencing — the job's test_scope
  "floor_command": "bash tests/run-floor.sh",   // optional, informational: what the floor was
  "full_command":  "bash tests/run-all.sh",     // optional, informational: what full would have been
  "resolved_commands": ["bash tests/run-floor.sh", "python3 scripts/compound-v-preeval.py --selftest"]
}
```

Only `scope` and `resolved_commands` are required; `floor_command`, `full_command` and (3.4.1) an
integer `selected_count` are the only optional keys — anything else is rejected, so a
`resolved_command` typo cannot pass silently as "nothing to run".

**Resolution belongs to the CALLER, execution to the worker.** The caller turns the manifest's
`test_contract` (`floor_command` / `full_command` / `impacted_map`) plus the job's `test_scope` into
the ordered, deduped `resolved_commands` list, applying the rules in
[`execution-manifest.md`](../compound-v/execution-manifest.md): the floor always runs and comes
first; overlapping `when` globs **union**; a changed path matching no `when` glob resolves to
`full_command` at tier FULL and, since 3.4.1 (decision 4), to at most five tests that REFERENCE
the changed module — else the floor alone — at SCOPED and DIRECT (label `impacted+referencing`); `floor_only` means *only the floor*, never nothing. That glob matching stays in the
caller's Python for the same reason the scope gate does — a second, weaker matcher written in bash
five times over would diverge from the authority, and a divergence here silently *drops* tests.
The worker never re-derives the set; it executes exactly the list it was handed.

**Transport.** Every worker script takes the resolved slice as a real argument:

```bash
scripts/compound-v-run-<backend>-worker.sh … \
  --test-contract-file /abs/run-dir/jobs/<job-id>.test-contract.json \
  [--test-timeout-sec 900]
```

`--test-contract-file` is an absolute path to a JSON file holding exactly the slice above. It is
**structurally validated before the model runs**, and a malformed contract is a usage fault (`exit 2`)
rather than a test failure — failing after an hour of model time would teach the run nothing. A
blank resolved command is rejected there too: `bash -c "   "` exits 0, and a silent zero is a
fabricated pass. Omit the flag and the worker runs no tests and reports no `tests` object.

**Ordering is load-bearing.** Tests run **after** the git-derived scope gate and only when the job
would otherwise be `success`:

1. the executor runs, 2. the gate computes `files_changed` / `violations`, 3. *then* the resolved
commands run inside the worktree.

Running them before the gate would let a coverage file or a cache directory a test wrote become a
false `violation`. The flip side is real and is the caller's problem: **anything a test creates after
the gate is outside the gate's authority and must not be merged** — see Merge-back below. A blocked,
timed-out or errored job never reaches step 3, and then `tests` is **absent**; absent is honest,
an invented zero is not.

**Who fills `tests`.** The worker that ran the commands, from what it measured — never the executor
model. This is the same rule as `blocked` / `files_changed` / `violations`, for the same reason:
asking the constrained party to report on its own constraint is the fabricated-evidence pattern.
`duration_ms` and `failures[]` are measured-only and absent rather than estimated; `failures[]`
carries the exact commands that exited non-zero, which is what makes the next run's
*previously-failing* set computable at all. On the `claude` path there is no external process to
carry the argument, so the caller runs the same resolved commands itself after the gate and fills
`tests` from what it measured — see [`adapter-claude.md`](adapter-claude.md).

**What the floor is, said without varnish.** The floor is an **early-feedback optimization. It does
not restore what the full suite guaranteed, and CI does.** Impacted ∪ previously-failing ∪
newly-added structurally omits every existing, previously-passing test the declared map fails to
select. Never write, here or anywhere, that the floor preserves pre-merge safety.

**A non-zero `tests.exit_code` does not change `status`.** `status` and `failure_class` describe the
*backend's* disposition, and re-labelling a red test suite as a backend `error` would send it into
the retry/reroute policy, which cannot fix a failing test. The worker reports; the **caller must not
merge** a job whose `tests.exit_code` is non-zero, and the review gate FAILs a job that reports no
test command at all.

---

## `gate_receipt` — the receipt, not the authority (v3.0, Feature D1)

A job result may carry a `gate_receipt`: one run of the scope gate, bound to `baseline_commit`,
`realised_commit` and a `diff_digest`, with the gate's verbatim stdout and exit code. It exists so
integration can be *refused* until every original job has one.

It is **not** the authority. A gate stage inside a workflow can be narrowed so it can do nothing but
run the check — and it still cannot be forced to *report* honestly, because a clamp limits what an
agent can do, not what it returns, and a schema proves shape, not execution. So the verification
layer's integration postcondition wins: where a receipt is **missing, `null`, or disagrees with the
tree**, the verification layer runs [`compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py)
itself and that verdict stands. Emit the object only when all six fields are genuinely known — a
partial receipt is a missing receipt, and a missing one is re-derived rather than trusted.

**The receipt also seals a patch (v3.4.0).** Engine C's `gate-receipt` writes `jobs/<id>.patch` —
`git diff --cached --binary <baseline>` over the approved paths only — and records that file's
sha256 in `receipts/<id>.gate.json`. The integration authority refuses a receipt whose artifact is
missing or no longer hashes to the recorded value, and the wave finalizer applies **that file**
rather than a fresh diff of the worktree. The six-field `gate_receipt` inside `job_result` is
unchanged: `schemas/job_result.schema.json` pins it with `additionalProperties: false`, so the
seal lives in the gate's own document and the two are bound — a pair that disagrees about
`diff_digest` or `baseline_commit` is refused.

**And the manifest is digest-bound.** `emit` bakes `sha256(manifest.yaml)` into the workflow
script; every stage carries it back as `--manifest-digest` and refuses a mismatch. The manifest
declares every job's `write_allowed`, so a lane map that changed after review is refused rather
than enforced.

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
| `adapter-claude.md` | Claude subagent | in-harness `Task` (model override, `maxTurns` = the tier default (`light` 30, `standard` 50, `deep`/`frontier` 80)) | `direct` or optional `worktree` | same caller scope gate on return | ships v1.0 |
| `adapter-codex.md` | headless Codex | Bash-spawned `codex exec` (own process, own worktree) | `worktree` (mandatory) | git-diff scope gate | ships v1.0 |
| `adapter-antigravity.md` | headless Antigravity | Bash-spawned `agy --print` (own process, own worktree) | `worktree` (mandatory) | git-diff scope gate | ships 1.1 — **lower-trust / opt-in (no kernel sandbox)** |
| `adapter-cursor.md` | headless Cursor | Bash-spawned `cursor-agent -p -f` (own process, own worktree) | `worktree` (mandatory) | git-diff scope gate | ships 2.1 — **lower-trust / opt-in (no kernel sandbox)** |
| `adapter-opencode.md` | headless opencode | Bash-spawned `opencode run` (own process, own worktree) | `worktree` (mandatory) | git-diff scope gate | **lower-trust / opt-in, WORKER-ONLY** (no kernel sandbox; multi-provider `provider/model` router — excluded from any arbiter panel until family-dedup keys on the resolved model) |

- **claude-subagent** — reuses today's `Task`-based dispatch with a `model` override and `maxTurns` = the tier default (`light` 30, `standard` 50, `deep`/`frontier` 80), optionally inside a worktree, and runs the **same** scope gate on return so enforcement is identical to Codex. Direct writes are gated against a baseline commit.
- **codex** — a Bash-spawned `codex exec` worker in its own process and its own worktree (never an `agents/` entry, never the experimental `openai-codex` app-server broker, which is single-flight and can't fan out). Pinned flag set below.
- **antigravity** — a Bash-spawned `agy --print` worker in its own process and its own worktree, mirroring Codex (worktree + git-diff scope gate, normalize → `job_result`). **Lower-trust / opt-in:** `agy` has **no kernel write-confinement** like Codex's `--sandbox workspace-write`, and headless writes require `--dangerously-skip-permissions` (arbitrary shell + out-of-worktree writes possible). The git-diff gate enforces file-scope *inside* the worktree but cannot *prevent* an out-of-worktree side-effect — so **prefer Codex for untrusted / high-stakes work**, and route to Antigravity only when the prompt/surface is trusted. Available only when `agy` is installed (env-aware routing). Runbook: [`adapter-antigravity.md`](adapter-antigravity.md); worker: [`scripts/compound-v-run-antigravity-worker.sh`](../../scripts/compound-v-run-antigravity-worker.sh).
- **cursor** — a Bash-spawned `cursor-agent -p -f` worker in its own process and its own worktree, mirroring Antigravity (worktree + git-diff scope gate, normalize → `job_result`). **Lower-trust / opt-in (same tier as Antigravity):** cursor-agent has **no kernel write-confinement**, and a headless run **requires `-f`** (an untrusted dir is otherwise refused) which also grants arbitrary write+shell. Verified live (success + BLOCKED paths). Output is one JSON object — `.result` → summary, `.session_id` (a real UUID) → resumable via `cursor-agent --resume`. **Prefer Codex for untrusted / high-stakes work**; route to Cursor only when the prompt/surface is trusted (its editing models suit isolated build/UI work). Available only when `cursor-agent` is installed AND authenticated (env-aware routing). Runbook: [`adapter-cursor.md`](adapter-cursor.md); worker: [`scripts/compound-v-run-cursor-worker.sh`](../../scripts/compound-v-run-cursor-worker.sh).
- **opencode** — a Bash-spawned `opencode run` worker in its own process and its own worktree, mirroring Antigravity/Cursor (worktree + git-diff scope gate, normalize → `job_result`). **Lower-trust / opt-in, WORKER-ONLY (v1):** opencode has **no kernel write-confinement at all** and, per its own docs, defaults to allowing all operations without explicit approval — the opposite default posture from Cursor/Antigravity's refuse-until-unlocked stance. opencode is **provider-agnostic** — every resolved model is a `provider/model` string, and the provider may differ per tier — so it is **excluded from any cross-model arbiter/review panel** until family-dedup keys on the resolved model. **Load-bearing safety caveat:** opencode can authenticate purely from inherited provider env vars (live-observed: it completed a real request with zero stored credentials via an ambient `ANTHROPIC_BASE_URL`) — the worker MUST scrub the dispatcher's own provider env vars rather than blindly inherit them (see the adapter). Available only when `opencode` is installed AND a provider is configured (stored credentials or an intentional env var). Runbook: [`adapter-opencode.md`](adapter-opencode.md); worker: [`scripts/compound-v-run-opencode-worker.sh`](../../scripts/compound-v-run-opencode-worker.sh) — built, but **auth-pending / coverage-unverified** (env-scrub credential-leak mitigation not yet live-verified end-to-end; re-probe the churning flag set at `/v:init`).

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

> **Engine C does not do this any more, and the reason is worth carrying into any adapter.** Since
> v3.4.0 the gate *seals* the slice it approved as `jobs/<id>.patch` and the wave finalizer applies
> that artifact. The recipe below re-reads the worktree at merge time, so everything that happened
> to it between the gate and the merge rides along: a revert (whose empty diff read as "already
> landed", and whose worktree was then pruned — the only copy of the work), a post-gate edit to an
> in-lane file, a byproduct the pathspec happens not to exclude. It remains correct for a backend
> that has no sealed artifact, and it is what Engine C falls back to for receipts written before
> sealing existed. Prefer the sealed artifact wherever there is one, and prove the result from git
> — `HEAD:<path>` must equal the artifact's post-image — before removing any worktree.

On **PASS**: apply the worktree's changes — **including new (untracked) files** — into the main tree, then `git worktree remove -f`. A plain `git diff HEAD | git apply` would silently DROP added files (an allowed new file passes the gate but never lands), so use an index-based patch:

```bash
# Stage ONLY the paths the gate saw and approved (job_result.files_changed), so a file a
# test command wrote into the worktree AFTER the gate cannot ride into the main tree
# unreviewed. `git add -A` with no pathspec would carry it.
# NUL-delimited, because a path may legitimately contain a newline (the workers keep
# files_changed newline-safe on purpose — do not undo that here).
printf '%s' "$JOB_RESULT" | jq -j '.files_changed[] | (., "\u0000")' \
  | while IFS= read -r -d '' p; do git -C "$WT" add -A -- "$p"; done
git -C "$WT" diff --cached --binary "$BASELINE_SHA" | (cd "$REPO" && git apply --index)
git -C "$REPO" worktree remove -f "$WT"
```

Two details are load-bearing:

- **Diff against the pinned `$BASELINE_SHA`** — the SHA captured *before* `git worktree add`, which is
  what the gate itself was given. `--cached HEAD` agrees with it only while the executor never
  commits; an executor that *did* commit inside its worktree leaves a HEAD past the baseline, and
  the committed half of its work would silently not land.
- **Stage by gate-approved path, never a bare `git add -A`** — tests run after the gate (see the test
  contract section above), so a coverage file, a `.pytest_cache/`, or any other byproduct exists in
  the worktree by merge time and is outside the gate's authority. Restricting the pathspec to
  `files_changed` is what keeps "only what the gate approved gets merged" true. Workers export
  `PYTHONDONTWRITEBYTECODE=1` for the test step, which removes the commonest byproduct but not the
  general case.

On **BLOCKED**: leave the worktree for inspection, do **not** merge. Worktrees live under `$TMPDIR/compound-v/<run-id>/<job-id>` (outside the repo — no `.gitignore` change needed). This loses per-job commit attribution, which is acceptable for disjoint file sets.
