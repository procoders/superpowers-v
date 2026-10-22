# Compound V Orchestrator — Product Requirements Document

| | |
|---|---|
| **Status** | Draft for review |
| **Target version** | **1.0.0** (major bump from 0.1.3) |
| **Date** | 2026-06-26 |
| **Author** | Oleg (with Claude / Opus 4.8) |
| **Supersedes** | Description-driven Compound V (0.1.x) — extends, does not discard |

---

## 0. TL;DR

Compound V graduates from a **description-driven skill-pack** into a **lightweight execution orchestration layer**. After brainstorming and the three pre-flights, it materializes a **manifest** of file-scoped jobs, **routes** each to the right backend (Opus / Sonnet / Codex), **dispatches them in parallel**, **enforces** that every worker wrote only its allowed files (`git diff` gate), **reviews** the result, and delivers against the spec's **Acceptance Criteria** — running **autonomously with guardrails** and **resumable after a crash**. It adds **no daemon, no MCP server, no swarm, no vector DB, and no fabricated metrics**. The orchestrator is the default path; the existing transparent pre-flights are unchanged.

The whole thing is **contracts + small deterministic scripts + the agent you already have** — the explicit anti-pattern to ruflo-style "swarm theater."

---

## 1. Problem & Motivation

### 1.1 Where 0.1.x stands

Compound V today is **prose**. The "orchestration" is the parent agent reading `SKILL.md` and issuing `Task` calls itself. Concretely, today's plugin has:

- No **manifest** — the partition map is prose; nothing machine-readable drives dispatch.
- No **enforcement** — `SCOPE LOCK` is text a subagent can ignore; nothing checks it.
- No **state / resume** — interrupt a parallel run and it's lost.
- No **multi-backend** — Opus/Sonnet via `Task` only; no headless Codex worker.
- No **outcome memory** — every feature starts cold on routing decisions.
- No **capability awareness** — assumes Context7 is present; no setup path.

### 1.2 The gap

The value of parallel-on-Opus dispatch is real, but it lives entirely in the agent's discretion. The moment a worker drifts outside its files, or a run is interrupted, or we want a cheaper headless worker for a big isolated job, the prose model has no answer. We need the **small, predictable dispatcher** layer the prose only describes — and a hard **planner/executor separation** so an executor (especially a non-Claude one like Codex) cannot silently change the plan or stomp shared files.

### 1.3 What we are explicitly *not* doing (the anti-ruflo charter)

Research into ruflo (`ruvnet/ruflo`, ~61k★) found an independent audit reporting **~290 of 300+ MCP tools are stubs**, a "neural" model that always predicts `coder`, and cost-savings numbers that are literally hardcoded (`baseline = 1000`) — net **+15–25k tokens/session of overhead** for mostly-theatrical capability. **The lesson is the inverse:** keep the executable surface small, deterministic, and auditable. No daemon, no MCP server, no WASM swarm, no self-reported benchmarks, no fabricated cost meters.

---

## 2. Goals & Non-Goals

### 2.1 Goals (v1.0.0)

1. **Manifest-driven dispatch.** A `manifest.yaml` of file-scoped jobs is the contract between planner and executors.
2. **Enforced file-scope.** Every job passes a post-hoc `git diff --name-only` gate against its `write_allowed` list. Violations BLOCK, they don't merge.
3. **Multi-backend execution** via one reusable **Backend Launcher sub-skill**: `claude-subagent`, `codex` (now), `antigravity` (stubbed for later).
4. **Autonomous-with-guardrails** end-to-end execution, delivering against the spec's **feature-level Acceptance Criteria**.
5. **Crash-resumable** runs via a lightweight state machine (`state.json` + re-dispatch of incomplete jobs).
6. **Environment-aware routing** (Balanced default; Claude-only when Codex absent), set at init and saved to config.
7. **Lean outcome memory** that closes a routing-learning loop.
8. **Setup / capability awareness** via `/v:init` (detect + walk through installs).
9. **Gated skill escalation** (deep-research / playground / writing-style) — pulled in only when genuinely needed.

### 2.2 Non-Goals (v1.0.0)

- No background daemon, MCP server, or long-lived broker.
- No vector / semantic memory (roadmap 1.2).
- No worker performance scorecards (roadmap 1.1).
- No "epic mode" multi-plan autonomous builds (roadmap 1.1).
- No fabricated token-cost accounting (we will not print numbers we can't measure).
- No parallel headless `claude -p` shell-out (Engine B) — rejected; see §3.
- No **Antigravity backend** in v1.0 — assessed and deferred to 1.1; the headless `agy` CLI is currently unusable for scripted capture (see §5.2).
- No replacement of the existing pre-flights — they are reused unchanged.

### 2.3 Scope boundary on autonomy (honesty clause)

v1.0 autonomously executes **one well-partitioned plan** end-to-end — which can be a substantial app or game **given a real spec**. It is **not** "build anything from one vague sentence." It is bounded by spec + partition quality, runs large work in **batches** (concurrency ceiling), and treats a multi-feature product as **multiple runs**. We will not market beyond this.

---

## 3. Grounding research

Two decisions required evidence rather than taste. Both were researched (Opus subagents, web + local source inspection) and both converge on the same enforcement keystone: **git worktree + `git diff --name-only`**.

### 3.1 Execution engine

| Engine | Stability | Determinism | Token cost | Parallelism | Crash-resume | Portability | Plugin floor? |
|---|---|---|---|---|---|---|---|
| **A — agent + helper scripts** | High | Med | **Low–Med** | 4–6 fg / 5–10 bg | **Yes (state.json)** | **Best** | ✅ everyone |
| **C — native Workflows** | High *when present* | **Highest** | High | **16 / 1000** | ❌ same-session only | None (CC-only) | ❌ gated, Pro-excluded |
| **B — `claude -p` shell-out** | Low–Med (429 cascades) | Med | **Highest** | ~3–5 throttled | Med | Codex-only | ⚠️ anti-third-party policy |

**Decision:** **Engine A is the floor** (works for every user; resume lives here). **Engine C (Workflows) is an opt-in accelerator** for large parallel batches — capability-probed, auto-fallback to A — but **never the resume mechanism** (its resume is same-session-only and "starts fresh" after a Claude Code exit, failing the crash case by design). **Engine B is rejected** (rate-limit cascades + Anthropic's policy pushing subscription users off third-party orchestrators; Codex doesn't need it).

### 3.2 Codex as a scoped worker

| Strategy | Stability | File-scope | Parallelism | Reusable (Antigravity) | Verdict |
|---|---|---|---|---|---|
| (a) reuse openai-codex broker | Low (experimental app-server) | Weak | **1 — single-flight** | None | ❌ can't fan out |
| (b) raw `codex exec` shell-out | High (public API) | Manual/call | Good | Low | OK primitive, no boundary |
| **(c) own backend-launcher sub-skill** | High | **Strong (worktree+diff)** | **Best** | **High** | ✅ **build this** |

**Two ground-truth facts** (from `codex-cli 0.130.0 --help` on this machine):

1. The draft `codex --session-id "X" "$(cat prompt)"` **does not work** — there is no `--session-id` flag, and bare `codex` opens the TUI. The headless form is `codex exec …`; resume is `codex exec resume <uuid>`.
2. Codex's sandbox **cannot restrict writes to a file allow-list** — only to a *directory*. The only way to enforce an exact file list is **git worktree (kernel-isolates blast radius) + `git diff --name-only` (detects & rejects anything outside the list).**

The installed `openai-codex` plugin drives codex through the **experimental `app-server` JSON-RPC broker**, which is **single-flight** (returns "busy" mid-turn) — unusable for parallel fan-out. We build our own launcher on the stable `codex exec` surface.

---

## 4. Architecture

### 4.1 The unified pipeline (orchestrator-as-default)

The orchestrator **extends the tail** of the existing Superpowers flow. Everything above the ★ line is unchanged from 0.1.x.

```
brainstorm ─► spec  (carries feature-level Acceptance Criteria)
   │
   ▼  auto-fire (unchanged)
[1A archaeology ∥ 1B domain ∥ 1C library]  ──► 3 audits  ─┐
   │                                                       │ 🔴 critical finding → HALT
   ▼  writing-plans + Phase 2 Partition Map                │
   │   └─ planner sets per job: backend · model · isolation · write/read scope · acceptance
   ▼
★ MANIFEST materialized   docs/superpowers/execution/<run-id>/manifest.yaml
   │                                                        partition FAIL → HALT
   ▼  DISPATCH  — Engine A batched Task (4–6) ∥ Codex via Backend Launcher
   │   └─ each job: worktree | direct (per manifest);  Workflows accelerator if available+opted-in
   ▼
★ COLLECT + SCOPE GATE   git diff --name-only vs write_allowed   ── violation → BLOCKED → HALT
   │
   ▼  REVIEW   spec-reviewer + quality + final integration (Opus)   ── unfixable ISSUES → HALT
   │   └─ final review gates on feature-level Acceptance Criteria
   ▼  MEMORY   append task-outcomes.jsonl + routing-lessons.md
   │
   ▼  finishing-a-development-branch
                          state.json updated after every phase ──► /v:status · /v:resume
```

**Skip rules unchanged:** greenfield single-file, pure plumbing, or impossible-to-partition refactors fall back to default Superpowers (documented in the plan header).

### 4.2 Component inventory

| # | Component | What it is | Status |
|---|---|---|---|
| 1 | **Execution Manifest** | `manifest.yaml` — jobs with backend/model/isolation/scope/acceptance + feature-level AC | NEW |
| 2 | **Backend Launcher** (sub-skill) | One `job_spec → job_result` contract; adapters: `claude-subagent`, `codex`, `antigravity`(stub) | NEW |
| 3 | **Scope Gate** | `scope-check` script: `git diff --name-only` vs `write_allowed` → pass/BLOCKED | NEW |
| 4 | **Routing Policy** | task-type → backend/model/isolation; Balanced default; env-aware; config-saved | NEW |
| 5 | **State Machine + run dir** | `SPEC_READY → … → MERGED/BLOCKED`; `state.json`; resume | NEW (lightweight) |
| 6 | **Result Collector** | Normalizes heterogeneous worker output → canonical `job_result` | NEW |
| 7 | **Review Gate** | spec + quality + final integration, AC-gated | EVOLVED |
| 8 | **Memory** | `task-outcomes.jsonl` + `routing-lessons.md` | NEW (lean) |
| 9 | **Init / Setup** | `/v:init` — detect capabilities, walk through installs, save config | NEW |
| 10 | **Skill Escalation Policy** | gated deep-research / playground / writing-style + forced Context7 | NEW |
| 11 | **Workflows accelerator** | opt-in Engine C fast-path for big batches; capability-probe + fallback | NEW (opt-in) |
| 12 | **Commands** | `/v:orchestrate · /v:dispatch · /v:collect · /v:status · /v:resume · /v:init` | NEW/EVOLVED |

---

## 5. Component specifications

### 5.1 Execution Manifest

Materialized from the verified Partition Map + Routing Policy, immediately after `writing-plans`. One per run, at `docs/superpowers/execution/<run-id>/manifest.yaml`.

```yaml
run_id: 2026-06-26-linkedin-sequence-editor
feature: "LinkedIn outreach sequence editor"
spec_path: docs/superpowers/specs/2026-06-26-linkedin-sequence.md
plan_path: docs/superpowers/plans/2026-06-26-linkedin-sequence.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-linkedin-sequence.md
  domain:      docs/superpowers/expert/2026-06-26-linkedin-sequence.md
  library:     docs/superpowers/library-audit/2026-06-26-linkedin-sequence.md

# Feature-level Acceptance Criteria — final integration review gates DONE on these.
acceptance_criteria:
  - "User can create / edit / delete sequence steps"
  - "Sequence persists across reload"
  - "No write outside the partitioned file sets"

routing_stance: balanced            # balanced | conservative | cost-aware | claude-only
max_parallel: 5                      # batch ceiling (phase-3 concurrency reality)

jobs:
  - id: task-0-schema
    title: "DB schema + migration + shared types"
    type: shared_foundation
    backend: claude
    model: opus
    isolation: direct                # serial pre-phase; no sibling can race it
    run: serial
    write_allowed: [db/migrations/*, src/db/schema.ts, src/types/sequence.ts]
    read_allowed:  [src/db/**]
    acceptance: ["migration applies cleanly", "types exported"]

  - id: task-1-editor-ui
    title: "Sequence editor UI slice"
    type: large_isolated
    backend: codex
    model: gpt-5.5
    isolation: worktree              # Codex ⇒ always worktree
    run: parallel
    depends_on: [task-0-schema]
    write_allowed: [src/features/sequences/components/**]
    read_allowed:  [src/features/sequences/**, src/shared/ui/**, src/types/sequence.ts]
    acceptance: ["create/edit/delete steps", "no writes outside components/**"]

  - id: task-2-api
    title: "Sequence CRUD API slice"
    type: bounded_crud
    backend: claude
    model: sonnet
    isolation: direct
    run: parallel
    depends_on: [task-0-schema]
    write_allowed: [src/features/sequences/api/**]
    read_allowed:  [src/server/**, src/types/sequence.ts]
    acceptance: ["CRUD endpoints", "input validation"]
```

**Rules:** every file in exactly one job's `write_allowed` (disjoint, enforced by `partition-reviewer`); shared resources live in a `shared_foundation` serial job; `read_allowed` auto-includes Task 0 outputs + the three audits.

### 5.2 Backend Launcher (the "под-skill")

A reusable sub-skill (`skills/backend-launcher/`) exposing **one contract**. The orchestrator speaks only this contract; it never sees backend-specific flags. Adapters: `claude-subagent` (in-harness `Task`), `codex` (headless), `antigravity` (stub returning `unsupported` until 1.1).

```jsonc
// INPUT job_spec
{ "backend":"codex", "prompt":"…", "model":"gpt-5.5", "cwd":"/repo",
  "write_allowed":["src/features/sequences/components/**"],
  "read_only":false, "timeout_sec":900, "network":false,
  "output_schema":"/schemas/job_result.schema.json" }

// OUTPUT job_result (canonical, identical across backends)
{ "status":"success",          // success | blocked | timeout | error
  "blocked":false,             // true if any file outside write_allowed changed
  "files_changed":["src/features/sequences/components/Editor.tsx"],
  "violations":[],             // files written but NOT allowed ⇒ blocked
  "summary":"Added step editor with create/edit/delete.",
  "session_id":"uuid",         // codex exec resume <uuid>
  "worktree":"/repo/.worktrees/task-1-editor-ui",
  "exit_code":0 }
```

**Codex adapter — the 6 load-bearing steps** (verified against `codex-cli 0.130`):

```bash
# 1. isolate (kernel-bounds blast radius + clean diff baseline)
git worktree add "$WT" HEAD
# 2. run headless (codex exec defaults to approval: never), sandboxed to the worktree
timeout "$timeout_sec" codex exec \
  --cd "$WT" \
  --sandbox "$([ "$read_only" = true ] && echo read-only || echo workspace-write)" \
  --skip-git-repo-check \
  --model "$model" \
  ${output_schema:+--output-schema "$output_schema"} \
  --output-last-message "$WT/.job_result.txt" \
  -c "sandbox_workspace_write.network_access=$network" \
  "$prompt"
# 3. observe
files_changed=$(git -C "$WT" diff --name-only; git -C "$WT" ls-files --others --exclude-standard)
# 4. ENFORCE — anything outside write_allowed ⇒ blocked, do NOT merge
# 5. normalize  → job_result (summary from .job_result.txt or schema'd JSON)
# 6. caller decides: merge worktree diff into main tree, or discard
```

**Verified against `codex-cli 0.130` (2026-06-26, live run).** `--ask-for-approval never` is **invalid for `codex exec`** (top-level/interactive flag only) and is omitted — `exec` already defaults to `approval: never`; use `-c approval_policy=never` if a non-default is ever needed. Enforcement fields (`files_changed`, `violations`, `blocked`) are **git-derived**, never model-self-reported; `--output-last-message` text feeds only the human `summary`. Helper scripts target stock-macOS **bash 3.2 + python 3.9** (no bash-4 / py-3.10 features) and suppress codex's cosmetic `[features].codex_hooks is deprecated` stderr. Worktrees live in `$TMPDIR`; merge-back on PASS is an index-based patch that includes new files (`git -C "$WT" add -A && git -C "$WT" diff --cached --binary HEAD | (cd "$REPO" && git apply --index)`) — a plain `git diff HEAD | git apply` would drop allowed untracked additions. The headless invocation also redirects **stdin from `/dev/null`** (`codex exec` otherwise blocks reading stdin in a non-TTY context) and **captures codex's stdout** (its final message) so the worker emits only the `job_result` JSON — both caught and fixed by the v1.0 end-to-end smoke test. Full task-by-task plan: [v1.0 implementation plan](../plans/2026-06-26-compound-v-orchestrator-v1-plan.md).

The **worker prompt** opens with the planner/executor lock: *"You are an implementation worker, NOT the planner. Do not change architecture. Do not write outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report BLOCKED."*

`claude-subagent` adapter reuses today's `Task`-based dispatch (model override, `maxTurns: 15`), optionally in a worktree, and runs the **same** scope gate on return — so enforcement is uniform across backends.

**Backends assessed for v1.0.** `claude-subagent` and `codex` ship. **Antigravity is deferred to 1.1 — verified, not assumed.** Google's official `agy` CLI exists (Go, v1.0.12) and its headless shape already matches this contract (`agy --print --sandbox --model … --add-dir <worktree> < prompt > result`), so the adapter is a ~1-day port *once it works*. It does not work headlessly yet: `agy --print` returns **empty stdout (exit 0) when output is piped or redirected** — exactly how an adapter captures results ([#408](https://github.com/google-antigravity/antigravity-cli/issues/408), [#318](https://github.com/google-antigravity/antigravity-cli/issues/318)) — and there is **no non-interactive auth** (interactive Google OAuth only; API keys ignored — [#223](https://github.com/google-antigravity/antigravity-cli/issues/223)). It is also preview-grade (399+ open issues, no license). File-scope would use the same worktree + `git diff` approach as Codex. The more promising 1.1 target is the **Antigravity Python SDK** (programmatic output over WebSockets, sidesteps the TTY-stdout bug). The `antigravity` adapter ships in v1.0 as a stub returning `unsupported`.

### 5.3 Scope Gate

`scripts/compound-v-scope-check.{sh,py}` — the **authority** behind `SCOPE LOCK` prose. Input: a job's `write_allowed` globs + its worktree (or the repo + a baseline commit for `direct` jobs). Output: `pass` or `BLOCKED` with the offending paths. Runs on **every** job regardless of isolation. A BLOCKED job never merges; the run halts and surfaces the violation.

### 5.4 Isolation model (per-job, planner-decided)

Isolation is **not** a global mode — the planner assigns it per job by risk, recorded as `isolation:` in the manifest:

- **`worktree`** — Codex/external workers (mandatory), and any Claude job the planner judges overlap-prone. Kernel-isolated; merged back on pass.
- **`direct`** — Claude jobs the planner is confident are disjoint. Fast (no worktree setup). Still gated by `git diff` on return.

The `git diff` scope gate is the constant; the worktree is the escalation.

### 5.5 Routing Policy

task-type → backend / model / isolation / run. Ships as `routing-policy.yaml`, tunable via the `/v:init` stance walkthrough (a standalone HTML configurator is available as an optional dev tool — not a shipped runtime surface). **Balanced** is the default stance; the active stance is chosen at init and saved to config (§5.9).

**Balanced default (shipped):**

| Job type | Backend·Model | Isolation | Run |
|---|---|---|---|
| Shared foundation (Task 0) | claude · opus | direct | serial |
| Security / auth / payments / PII / a11y | claude · opus | worktree | parallel |
| Core feature slice (design judgment) | claude · opus | worktree | parallel |
| Bounded CRUD (8-box junior) | claude · sonnet | direct | parallel |
| Large isolated build | **codex · gpt-5.5** | worktree | parallel |
| Mechanical refactor / rename / format | claude · sonnet | direct | parallel |
| Docs / i18n strings | claude · sonnet | direct | parallel |
| Tests — designing new | claude · opus | direct | parallel |
| External API integration | claude · opus | worktree | parallel |
| Review — spec / quality / integration | claude · opus | direct | parallel/serial |
| Unclear scope | **none → return to planning** | — | — |

**Invariants enforced by `compound-v-validate-manifest.py` (deterministic) and `partition-reviewer`:** reviewers are always Opus; Codex always implies worktree; unclear scope never dispatches. **Env-aware fallback:** if Codex is absent, the stance collapses to **Claude-only** (large-isolated → opus/worktree). Other stances available: **Conservative** (Opus-heavy, no Codex) and **Cost-aware** (more Sonnet/Codex).

### 5.6 State machine & resume

Lightweight — a `state.json`, not an FSM engine. States: `SPEC_READY → PREFLIGHT_DONE → PARTITION_VERIFIED → DISPATCHED → COLLECTED → REVIEWED → MERGED` (plus terminal `BLOCKED`). The run directory is the execution substrate:

```
docs/superpowers/execution/<run-id>/
├── manifest.yaml         # the contract
├── state.json            # phase + per-job status {pending|running|done|blocked|failed}
├── jobs/<id>.prompt.md   # dispatched prompt (for re-dispatch on resume)
└── results/<id>.json     # normalized job_result
```

**Resume** (`/v:resume <run-id>`): re-read `state.json`, reconcile against reality with `git diff` (what actually landed), then **re-dispatch only `pending`/`failed`/`blocked` jobs**. Survives a hard crash — which is precisely why resume lives in Engine A and **not** in Workflows.

### 5.7 Autonomy & Acceptance Criteria

**Autonomous-with-guardrails.** The pipeline runs end-to-end without pausing. It **halts only** on a hard event:

- Scope-gate **BLOCKED** (worker wrote outside its files)
- Partition **FAIL** (`partition-reviewer` rejects the map)
- 🔴 **critical pre-flight finding** (abandoned library, regulatory blocker)
- Reviewer **ISSUES** that the per-task fix loop cannot resolve

**AC-gated delivery.** The manifest carries the spec's **feature-level Acceptance Criteria**; the final integration review will not declare DONE until the composite change satisfies them. This is the contract behind "delivers a finished result per Acceptance Criteria."

### 5.8 Memory (lean)

Project-local, committed, reviewable:

```
docs/superpowers/memory/
├── task-outcomes.jsonl   # one line per job: {run_id, type, backend, model, status, blocked, rework_rounds}
└── routing-lessons.md    # human-curated: "type X on backend Y → outcome Z; prefer …"
```

`task-outcomes.jsonl` is appended automatically by the collector. `routing-lessons.md` is updated when a pattern emerges (e.g., "large_isolated on Codex blocked twice on barrel files → add barrels to Task 0"). The existing `_knowledge-base/` (domain, library) is untouched. **No semantic search, no scorecards** in v1.0.

### 5.9 Initialization & setup

`/v:init` (plus a light SessionStart capability hint when config is absent):

1. **Detect** — `codex` CLI, `antigravity` CLI (future), Context7 MCP, required skills/agents.
2. **Walk through installs** — for anything missing, guide the user step-by-step (e.g. `brew install` / `npm i -g @openai/codex`, `/plugin install context7@claude-plugins-official`), confirming after each.
3. **Set routing stance** — Balanced if Codex present, else Claude-only; offer Conservative/Cost-aware.
4. **Save config** — capabilities cached user-level; stance saved project-level so different repos can differ:
   ```
   .claude/compound-v.json   →  { "stance": "balanced", "backends": ["claude","codex"], "checked_at": "2026-06-26" }
   ```

### 5.10 Skill Escalation Policy

Gated, not every-run — the same philosophy as the forced-Context7 rule. A short policy doc the planning phase consults:

| Skill | Trigger (escalate ONLY when…) |
|---|---|
| **Context7** (forced, exists) | any library/SDK/API is named or implied — validate currency |
| **deep-research** | a **load-bearing** planning decision is genuinely uncertain or sources conflict, beyond what 1B/1C resolved |
| **playground** | a decision is **config-heavy or visual** and benefits from user input (routing stance, design/tradeoff matrix) |
| **avoid-ai-writing / elements-of-style** | the system generates **user-facing copy or docs** — clean the prose before delivery |

The bar is "genuinely needed," not "might be nice." Each escalation is logged in the run's reasoning, not fired by default.

### 5.11 Commands

| Command | Purpose |
|---|---|
| `/v:init` | Detect capabilities, walk through installs, set + save routing stance |
| `/v:orchestrate <plan>` | Materialize a manifest from a plan + routing policy |
| `/v:dispatch <manifest\|run-id>` | Run the autonomous pipeline (partition-review → dispatch → collect → review) |
| `/v:collect <run-id>` | Re-run collect + scope-gate + review on an existing run |
| `/v:status [run-id]` | Render `state.json` — phase + per-job status |
| `/v:resume <run-id>` | Reconcile + re-dispatch incomplete jobs after interruption |
| `/v:archaeology <topic>` | (unchanged) Phase 1A only |

In default operation the agent flows through orchestrate→dispatch→collect itself; the explicit commands are for manual control, resume, and inspection.

### 5.12 Observability (minimal)

The run directory (§5.6) *is* the record — `state.json` + `results/` are both execution substrate and audit trail. **No separate `run.log` / `timeline.md` / `cost-estimate.md`.** A final run summary is printed in-response. We deliberately do **not** print token-cost numbers we cannot measure (the ruflo anti-pattern).

### 5.13 Workflows accelerator (opt-in Engine C)

For large parallel batches, when the user has Dynamic Workflows available and opts in: capability-probe → emit a Workflow that runs the same partitioned jobs with `schema`-validated `job_result`s at the 16-wide cap → **fall back to Engine A's batched `Task` dispatch** when absent or disabled. **The scope gate and `state.json` resume stay in Engine A's layer even when C runs** — so file-scope enforcement and crash-resume never regress to C's weaker guarantees.

---

## 6. Enforcement & safety model

| Gate | Mechanism | Authority |
|---|---|---|
| No write outside allowed files | `git diff --name-only` scope gate per job | **Enforced (script)** |
| Codex blast-radius bounded | git worktree + kernel sandbox (`-s workspace-write`) | **Enforced (OS)** |
| Disjoint partition before dispatch | `partition-reviewer` PASS required | **Enforced (gate)** |
| Planner/executor separation | worker prompt lock + scope gate | Enforced + instructed |
| No migration without serial Task 0 | shared resources → `shared_foundation` job | Enforced (partition rule) |
| No dependency add without library audit | Phase 1C precondition | Instructed |
| No secrets written into `docs/superpowers/` | review checklist | Instructed |
| No auto-merge without final review | AC-gated final integration review | Enforced (pipeline) |

---

## 7. Plugin structure (delta)

```
superpowers-v/
├── .claude-plugin/plugin.json            # version → 1.0.0; keywords += orchestrator
├── skills/
│   ├── compound-v/
│   │   ├── SKILL.md                       # EVOLVED: orchestrator-as-default flow
│   │   ├── phase-2-disjoint-partitioning.md   # EVOLVED: emits manifest
│   │   ├── phase-3-parallel-opus-dispatch.md  # EVOLVED: manifest-driven, multi-backend
│   │   ├── execution-manifest.md          # NEW: schema + rules
│   │   ├── routing-policy.md              # NEW: stances + env-aware + Balanced default
│   │   ├── state-machine.md               # NEW: states + run dir + resume
│   │   ├── skill-escalation.md            # NEW: gated deep-research/playground/style
│   │   └── (existing phase-1a/1b/1c, rationalization-table)  # unchanged
│   └── backend-launcher/                  # NEW sub-skill ("под-skill")
│       ├── SKILL.md                       # the job_spec/job_result contract
│       ├── adapter-codex.md               # codex exec + worktree + diff
│       ├── adapter-claude.md              # Task-based
│       └── adapter-antigravity.md         # stub (1.1)
├── agents/                                # 6 existing; evolve dispatcher + reviewers for manifest
├── commands/
│   ├── v-init.md  v-orchestrate.md  v-collect.md  v-status.md  v-resume.md   # NEW
│   ├── v-dispatch.md                      # EVOLVED (manifest-aware)
│   └── v-archaeology.md                   # unchanged
├── scripts/
│   ├── compound-v-scope-check.py          # NEW: git-diff gate
│   ├── compound-v-run-codex-worker.sh     # NEW: codex adapter
│   ├── compound-v-collect-results.py      # NEW: normalize → job_result
│   ├── compound-v-update-memory.py        # NEW: append task-outcomes.jsonl
│   └── lint-frontmatter.py                # unchanged
├── hooks/                                 # SessionStart hint when no config; PostToolUse nudge (existing)
└── schemas/job_result.schema.json         # NEW: codex --output-schema target
```

---

## 8. Versioning & roadmap

### v1.0.0 — this PRD
Manifest · Backend Launcher (claude+codex) · scope gate · per-job isolation · Balanced/env-aware routing · state+resume · autonomous-with-guardrails + AC delivery · lean memory · `/v:init` with install walk-through · skill escalation · opt-in Workflows accelerator.

### v1.1 — autonomy & adaptiveness
- **Antigravity adapter** — the launcher's reuse payoff. The official `agy` CLI already fits the contract, but two blockers keep it out of v1.0: headless `agy --print` returns empty stdout when piped ([#408](https://github.com/google-antigravity/antigravity-cli/issues/408)/[#318](https://github.com/google-antigravity/antigravity-cli/issues/318)) and there's no non-interactive auth ([#223](https://github.com/google-antigravity/antigravity-cli/issues/223)). Unblocks when those close; **spike the Antigravity Python SDK first** (programmatic output sidesteps the TTY bug) as the likelier target.
- **Epic mode** — chain multiple plan-runs into one autonomous multi-feature build.
- **Worker scorecards** (`worker-performance.jsonl`) — routing adapts from measured success/block/rework rates.
- Workflows-accelerator hardening + capability auto-detect polish.

### v1.2 — memory & intelligence
- **Semantic memory search** over `docs/superpowers/**`.
- **Automatic routing suggestions** from past outcomes (data-driven, not rules).
- Optional **MCP bridge** + **team policy config** (shared stance/routing for a team).

---

## 9. Success criteria

1. A partitioned feature runs end-to-end autonomously, delivers against its Acceptance Criteria, and merges — with zero manual dispatch.
2. A worker that writes outside its `write_allowed` is **caught and blocked** before merge, every time (scope-gate test).
3. A Codex job runs headless in a worktree, returns a normalized `job_result`, and merges on pass.
4. Killing a run mid-batch and `/v:resume`-ing re-dispatches only the unfinished jobs and completes.
5. With Codex absent, `/v:init` sets Claude-only and the pipeline runs unchanged.
6. Net new executable surface stays small: a handful of scripts + prose — **no daemon, no MCP server, no fabricated metrics**.

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Concurrency ceiling (4–6) bottlenecks big plans | Batch in the manifest; opt-in Workflows accelerator for 16-wide |
| Codex `exec` behavior drifts across versions | Pin tested flags in the codex adapter; version-probe in `/v:init` |
| Workflows accelerator unstable / unavailable | Opt-in + capability-probe + automatic fallback to Engine A |
| Scope gate misses untracked files | Gate checks `git diff` **and** `ls-files --others` |
| Memory rots / misleads routing | Keep it lean; `routing-lessons.md` is human-curated, date-stamped |
| Over-engineering creep | Anti-ruflo charter in §1.3 is a standing non-goal; weight ledger reviewed each minor |

## 11. Open questions

*All four resolved during planning (see the v1.0 plan §4):*
1. **Naming** — ✅ keep `/v:*` + "Compound V Orchestrator"; sub-skill stays the literal `backend-launcher`.
2. **Config location** — ✅ `.claude/compound-v.json` (project stance) + `~/.claude/compound-v-capabilities.json` (user capability cache).
3. **Merge strategy** — ✅ on PASS, an **index-based patch that includes new files** (`git -C <wt> add -A && git -C <wt> diff --cached --binary HEAD | (cd <repo> && git apply --index)`) into the main tree, then `git worktree remove -f`; worktrees in `$TMPDIR`. (A plain `git diff HEAD | git apply` drops untracked additions — an allowed new file would pass the gate but never land.)
4. **Workflows probe** — ✅ default **off**; attempt-and-catch behind a capability probe, automatic fallback to Engine A.

*Surfaced + resolved by the dogfood pre-flight:* Codex adapter flag fix (drop `--ask-for-approval never`); resume tie-break = git-wins; codex `job_result` enforcement = git-derived; worktree storage = `$TMPDIR`; bash 3.2 / python 3.9 script portability.

## 12. Decision log

| Decision | Choice | Why |
|---|---|---|
| Version | **1.0.0** | Orchestrator is the real product; major bump |
| Mode | **Orchestrator-as-default** | One unified, observable, resumable pipeline |
| Engine | **A floor + opt-in C; B rejected** | A works for everyone & resumes; C gated/no-crash-resume; B rate-limited + policy-risky |
| Codex | **Own backend-launcher sub-skill** | openai-codex broker is single-flight/experimental; own = parallel + reusable for Antigravity |
| File-scope | **worktree + git-diff gate** | Codex sandbox can't do file-level; only prevention+detection combo can |
| Isolation | **Per-job, planner-decided** | Worktree where risky/external; direct where disjoint; gate always runs |
| Routing | **Balanced default, env-aware** | Best speed/cost/quality split; Claude-only when Codex absent |
| Resume | **state.json in Engine A** | Workflows resume is same-session-only; fails the crash case |
| Autonomy | **Autonomous w/ guardrails + AC-gated** | End-to-end speed; halts only on hard events; delivers per AC |
| Memory | **Lean: outcomes + routing-lessons** | Closes the learning loop cheaply; defer scorecards/vectors |
| Observability | **Minimal, no fake cost** | Honest > fabricated metrics (anti-ruflo) |
| Init | **Detect + walk through installs** | Codex/Context7/Antigravity onboarding; sets + saves stance |
| Skill escalation | **Context7 + deep-research + playground + style, gated** | High-value skills only when genuinely needed |
| Workflows accelerator | **Kept in v1.0 (opt-in)** | User chose power; gated + fallback keeps it safe |
| Antigravity backend | **Deferred to 1.1 (stub)** | `agy` CLI fits the contract, but headless stdout is broken when piped (#408/#318) and there's no non-interactive auth (#223); preview-grade. Won't ship a backend we can't verify — Python SDK is the 1.1 spike target |

---

*End of PRD. Reviewer: please confirm §11 open questions and flag any section before this becomes an implementation plan.*
