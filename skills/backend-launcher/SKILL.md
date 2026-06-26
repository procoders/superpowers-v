---
name: backend-launcher
description: Use when Compound V's dispatcher needs to run one file-scoped job on a chosen backend (Claude subagent, headless Codex worker, or Antigravity stub) and get back a canonical job_result. The single job_spec → job_result contract every adapter implements; the orchestrator speaks only this contract and never sees backend-specific flags.
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
  "backend": "codex",                  // claude | codex | antigravity
  "prompt": "…",                       // the worker prompt (opens with the planner/executor lock, below)
  "tier": "standard",                  // deep | standard | light — the routing INTENT (stable across model churn)
  "effort": "medium",                  // low | medium | high — orthogonal reasoning-effort hint (optional)
  "model": "gpt-5.5",                  // OPTIONAL explicit override; when present it skips resolution.
                                       //   execution-layer data — NEVER appears in any frontmatter
  "cwd": "/repo",                      // absolute repo root
  "write_allowed": ["src/features/sequences/components/**"],
  "read_only": false,                  // true ⇒ sandbox read-only, no merge
  "timeout_sec": 900,
  "network": false,                    // maps to sandbox_workspace_write.network_access
  "output_schema": "/abs/schemas/job_result.schema.json"  // optional
}
```

**`tier` + `effort` + `model` — intent over hardcoded strings.** A `job_spec` carries the routing **intent** (`tier`, and optional `effort`), not a hardcoded model. The concrete `model` is **resolved before dispatch** by [`scripts/compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) from `(backend, tier, effort, config)` — so the plugin survives model churn (refresh the config `models` map via `/v:models`, never the call sites). A job MUST carry `model` OR `tier`; an explicit `model` override skips resolution and always wins. `effort` is passed through to the worker: for `codex` it becomes `-c model_reasoning_effort=<effort>`; for `claude` it is advisory (the `Task` path has no separate effort flag). `tier`/`effort`/`model` are execution-layer values and never appear in any frontmatter. See [`skills/compound-v/execution-manifest.md`](../compound-v/execution-manifest.md) for the tier vocabulary, the config `models` map shape, and the reviewer ⇒ deep rule.

### OUTPUT — `job_result` (canonical, identical across backends)

Defined and validated by [`schemas/job_result.schema.json`](../../schemas/job_result.schema.json). Worked instance: [`examples/job_result.example.json`](../../examples/job_result.example.json).

```jsonc
{
  "status": "success",                 // success | blocked | timeout | error
  "blocked": false,                    // true if any file outside write_allowed changed
  "files_changed": ["src/features/sequences/components/Editor.tsx"],
  "violations": [],                    // files written but NOT allowed ⇒ blocked
  "summary": "Added step editor with create/edit/delete.",
  "session_id": "uuid",                // codex exec resume <uuid>
  "worktree": "/tmp/compound-v/<run-id>/task-1-editor-ui",
  "exit_code": 0
}
```

---

## Git-derived enforcement rule (non-negotiable)

The enforcement fields — `blocked`, `files_changed`, `violations` — are **git-derived by the caller**, never self-reported by the worker model. Compute them inside the worktree (or against a baseline commit for `direct` jobs):

```bash
files_changed=$(git -C "$WT" diff --name-only; git -C "$WT" ls-files --others --exclude-standard)
```

Both halves are required: `diff --name-only` catches edits to tracked files; `ls-files --others --exclude-standard` catches brand-new untracked files the diff would miss. Anything in `files_changed` that does not match `write_allowed` becomes a `violation` ⇒ `blocked: true`, `status: "blocked"`, and the caller **must not merge** — it halts the run and surfaces the offending paths. The model's `--output-last-message` text feeds only the human `summary`; never trust it to report what it changed.

The deterministic authority is [`scripts/compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py) (built downstream). This file states the rule; that script is what the dispatcher actually calls after every job.

---

## Worker prompt lock (planner/executor separation)

Every dispatched `prompt` opens with this lock, verbatim-in-spirit:

> You are an implementation worker, NOT the planner. Do not change architecture. Do not write outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report BLOCKED.

This is the *instructed* half. The git-diff scope gate above is the *enforced* half. An executor — especially a non-Claude one like Codex — cannot silently change the plan or stomp shared files because the gate catches it regardless of what the prompt did or didn't constrain.

---

## The three adapters (contract level)

| Adapter | Backend | Mechanism | Isolation | Enforcement | Status |
|---|---|---|---|---|---|
| `adapter-claude.md` | Claude subagent | in-harness `Task` (model override, `maxTurns: 15`) | `direct` or optional `worktree` | same caller scope gate on return | ships v1.0 |
| `adapter-codex.md` | headless Codex | Bash-spawned `codex exec` (own process, own worktree) | `worktree` (mandatory) | git-diff scope gate | ships v1.0 |
| `adapter-antigravity.md` | Antigravity | stub returning `unsupported` | — | — | stub (1.1) |

- **claude-subagent** — reuses today's `Task`-based dispatch with a `model` override and `maxTurns: 15`, optionally inside a worktree, and runs the **same** scope gate on return so enforcement is identical to Codex. Direct writes are gated against a baseline commit.
- **codex** — a Bash-spawned `codex exec` worker in its own process and its own worktree (never an `agents/` entry, never the experimental `openai-codex` app-server broker, which is single-flight and can't fan out). Pinned flag set below.
- **antigravity** — a stub that returns `{"status":"error","blocked":false,...,"summary":"unsupported"}`. Google's `agy` CLI fits this contract on paper but `agy --print` returns empty stdout when piped (#408/#318) and has no non-interactive auth (#223); deferred to 1.1, with the Antigravity Python SDK as the likelier target.

---

## Pinned `codex exec` flag set (verified live against codex-cli 0.130)

The codex adapter MUST use exactly this flag set:

```bash
timeout "$timeout_sec" codex exec \
  --cd "$WT" \
  --sandbox "$([ "$read_only" = true ] && echo read-only || echo workspace-write)" \
  --skip-git-repo-check \
  --model "$model" \
  ${output_schema:+--output-schema "$output_schema"} \
  --output-last-message "$WT/.job_result.txt" \
  -c "sandbox_workspace_write.network_access=$network" \
  "$prompt"
```

Pinned facts (do not re-derive):

- **`--ask-for-approval never` is INVALID for `codex exec`.** It is a top-level/interactive flag, absent from `codex exec --help`; `exec` already defaults to `approval: never`. Passing it fails every Codex job. **Omit it.** If a non-default policy is ever needed: `-c approval_policy=never`.
- **Resume** is `codex exec resume <SESSION_ID> [PROMPT]` (UUID printed in the run banner) or `--last`. There is **no `--session-id` flag**. Capture the UUID from the banner/output into `session_id`.
- **`git worktree diff` does not exist.** Use plain `git -C "$WT" diff --name-only` + `git -C "$WT" ls-files --others --exclude-standard`.
- Codex emits a cosmetic `[features].codex_hooks is deprecated` stderr warning — the worker script suppresses/ignores it so it doesn't pollute captured output.
- `--output-schema` accepts a strict JSON Schema (`additionalProperties:false` + `required`) — point it at `job_result.schema.json` when a schema'd summary is wanted. The schema drives only the human summary; enforcement stays git-derived.

---

## Merge-back

On **PASS**: `git -C "$WT" diff HEAD | git apply` into the main tree, then `git worktree remove -f`. On **BLOCKED**: leave the worktree for inspection, do **not** merge. Worktrees live under `$TMPDIR/compound-v/<run-id>/<job-id>` (outside the repo — no `.gitignore` change needed). This loses per-job commit attribution, which is acceptable for disjoint file sets.
