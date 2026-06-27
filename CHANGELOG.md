# Changelog

All notable changes to **superpowers-v (Compound V)** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses semantic versioning.

## [1.1.0] — Unreleased

### Added — Antigravity backend adapter (promoted from 1.0 stub)

- **Antigravity (`agy`) is now a real backend, not a stub.** A Bash-spawned `agy --print` worker (`scripts/compound-v-run-antigravity-worker.sh`) that mirrors the Codex worker: runs one file-scoped job inside a dedicated `$TMPDIR` git worktree at HEAD, then emits the canonical `job_result`. Same CLI shape as the codex worker (`--run-id/--job-id/--repo/--prompt-file/--model/--write-allowed/--timeout-sec/[--read-only]/[--network]/[--output-schema]`), same id-safety + timeout-int guards, same delegation to the deterministic scope gate `scripts/compound-v-scope-check.py` for git-derived enforcement (baseline SHA captured **before** `worktree add` so an in-worktree commit can't hide changes), and the same fail-closed status + `failure_class`/`retry_after_seconds` emit. Verified live against **agy 1.0.13**: `cd "$WT" && agy --dangerously-skip-permissions --add-dir "$WT" --print-timeout "<sec>s" [--model …] --print "<prompt>"` — **flag order is load-bearing (`--print` MUST be last; its value is the prompt)**. Summary comes from agy's printed stdout; `session_id` is `""` (agy exposes no resumable session UUID). `--model` is optional (omitted when empty); `--read-only`/`--network`/`--output-schema` are accepted for CLI parity but advisory/ignored (agy has no kernel sandbox toggle or output-schema flag); `agy models` **hangs** and is never called (curated model map).
- **⚠️ Lower-trust, opt-in backend (documented loudly).** Unlike Codex's `--sandbox workspace-write` (a kernel-level write-confinement root), `agy` has **NO kernel write-confinement**, and headless writes **require** `--dangerously-skip-permissions` — which lets the agent run arbitrary shell and write **outside** the worktree. The worktree + post-hoc `git diff` gate enforces file-scope **inside** the worktree (detection) but **cannot prevent** an out-of-worktree write/shell side-effect. So Antigravity is **opt-in / lower-trust — prefer Codex (kernel-sandboxed) for untrusted / high-stakes work.**
- **`antigravity ⇒ worktree` invariant** added to `scripts/compound-v-validate-manifest.py` (mirrors `codex ⇒ worktree`): an external worker with no kernel sandbox must be worktree-isolated. New self-test: `antigravity` + `isolation: direct` → INVALID.
- **Failure classifier** (`scripts/compound-v-classify-failure.py`) gains an `antigravity` backend with Gemini/agy error rules (priority-ordered): `out_of_credits` (quota/billing/usage-limit) is checked **before** `rate_limited`, because Gemini reuses `RESOURCE_EXHAUSTED` for **both** quota exhaustion and throttling — quota wording wins. Also `auth` (permission_denied/401/403), `context_length`, `overloaded` (503/500/unavailable), `network`. New self-tests (agy quota → out_of_credits; permission_denied → auth).
- **Model resolver** (`scripts/compound-v-resolve-model.py`) carries a curated antigravity map (`deep → Gemini 3.1 Pro (High)`, `standard → Gemini 3.1 Pro`, `light → Gemini 3.1 Flash`) — illustrative, to be verified against `agy models` when usable; the worker omits `--model` if the resolved value is empty. New self-test for `antigravity/deep`.
- **Docs:** `skills/backend-launcher/adapter-antigravity.md` replaced the stub with the real adapter runbook (6 load-bearing steps, verified `agy` invocation + flag order, worktree + git-diff scope gate, no resume, and a prominent **Safety** section); `skills/backend-launcher/SKILL.md` updated (real adapter, lower-trust caveat); `skills/compound-v/routing-policy.md` lists antigravity as a selectable alternative for `large_isolated` (env-aware: only when `agy` is installed) with the `antigravity ⇒ worktree` invariant and the prefer-Codex safety note; `commands/v-init.md` detects `agy` and records it as a lower-trust backend.

### Added — adaptive routing (worker scorecards)

- **Worker scorecards — a data-driven routing signal from measured outcomes** (PRD §8). Routing was a *static guess* (a task-type → a fixed backend/tier, applied the same in every repo); scorecards make it **adaptive**. `scripts/compound-v-scorecard.py` deterministically aggregates `docs/superpowers/memory/task-outcomes.jsonl` into `docs/superpowers/memory/worker-performance.jsonl` — one row per `(backend, type)` with `{total, success, blocked, error, timeout, avg_rework, block_rate, error_rate, success_rate, health}`, where `health ∈ {insufficient_data, healthy, watch, unhealthy}` (a cell needs **≥5 samples** to be judged; below that it stays `insufficient_data`). CLI: `--update [--outcomes P] [--out P]` regenerates the file; `--query --backend B --type T` prints one cell's stats + health. Before assigning a task-type's static-default backend, the router queries the measured health of that `(backend × task-type)` **in this repo** and acts on it: `unhealthy` → prefer the routing alternative or escalate a tier (Opus is the safe escalation) with a one-line justification; `watch` → keep the default but note it; `healthy`/`insufficient_data` → static default unchanged. Scorecards are a **hint layered on the static policy, not a replacement**, and only ever make routing **more conservative** (escalate), never weaker — the HARD invariants (reviewers⇒opus, Codex⇒worktree, unclear⇒planning, sensitive surfaces⇒deep) are untouched. The scorecard **never** modifies the human-curated `routing-lessons.md` and emits **no** cost/token metrics (anti-ruflo). `worker-performance.jsonl` is **machine-generated**, regenerated each run by `compound-v-scorecard.py --update` after the dispatcher appends fresh outcomes — never hand-edited. Wired into `agents/parallel-dispatcher.md` (post-run memory step + per-job routing query), `skills/compound-v/routing-policy.md` (§Scorecard-aware routing), and `skills/compound-v/SKILL.md` (memory layout).

## [1.0.0] — 2026-06-26

Compound V graduates from a description-driven skill-pack into a **lightweight execution orchestrator**. The three pre-flights and `/v:archaeology` are behaviourally unchanged; the orchestrator extends the *tail* of the flow (manifest → dispatch → scope-gate → collect → review → memory) with multi-backend execution, per-job isolation, and crash-resume. No daemon, no MCP server, no vector DB, and **no fabricated token-cost metrics** (the anti-ruflo charter). Built by dogfooding the Compound V pipeline on this repo.

### Added — the orchestrator delta

- **Execution manifest** (`skills/compound-v/execution-manifest.md`, `examples/manifest.example.yaml`). A machine-readable `manifest.yaml` of file-scoped jobs — backend · optional `tier`/`effort` · isolation · `write_allowed`/`read_allowed` · per-job and feature-level acceptance criteria — materialized from the verified Partition Map immediately after `writing-plans`. A job carries an optional `tier` + `effort`; `model` becomes an optional **override**. A job MUST have `model` **or** `tier` (backward-compatible: existing explicit-`model` jobs stay valid); reviewer jobs must resolve to `tier=deep` **or** `model=opus`. This is the contract between planner and executors.
- **Backend Launcher** sub-skill (`skills/backend-launcher/`). One `job_spec → job_result` contract (`schemas/job_result.schema.json`) that every adapter implements; the orchestrator speaks only this contract and never sees backend-specific flags. Adapters: `adapter-claude.md` (Task-based, model override, `maxTurns: 15`), `adapter-codex.md` (headless `codex exec` in a git worktree), `adapter-antigravity.md` (stub — see dispositions below).
- **Headless Codex worker** (`scripts/compound-v-run-codex-worker.sh`). Runs one file-scoped job on `codex exec` inside a dedicated `$TMPDIR` git worktree, then emits the canonical `job_result`. Verified against `codex-cli 0.130`: the flag set is `--cd / --sandbox / --skip-git-repo-check / --model / --output-last-message / -c sandbox_workspace_write.network_access` (plus optional `--output-schema`). **`--ask-for-approval never` is invalid for `codex exec` and is omitted** — `exec` already defaults to `approval: never`. Resume is `codex exec resume <uuid>`. The cosmetic `[features].codex_hooks is deprecated` stderr is suppressed.
- **Scope gate** (`scripts/compound-v-scope-check.py`). The deterministic authority behind the prose `SCOPE LOCK`. After every job it unions `git diff --name-only <baseline>` with `git ls-files --others --exclude-standard` *and* the gitignored set (`git ls-files --others --ignored --exclude-standard -- .`) and tests each changed path against `write_allowed`. A violation is **BLOCKED** — the job never merges and the run halts. Enforcement fields (`files_changed` / `violations` / `blocked`) are **git-derived, never model-self-reported**.
- **Manifest validator** (`scripts/compound-v-validate-manifest.py`). A deterministic invariant gate the `partition-reviewer` runs: disjoint `write_allowed`, Codex⇒worktree, reviewers⇒Opus/deep, shared resources in the serial Task 0. Extended for the model-broker: `tier ∈ {deep,standard,light}` and `effort ∈ {low,medium,high}` when present, and every job must carry `model` **or** `tier`.
- **State machine + crash-resume** (`skills/compound-v/state-machine.md`). A lightweight `state.json` (not an FSM engine) tracks phase + per-job status under `docs/superpowers/execution/<run-id>/`. `/v:resume` reconciles `state.json` against git reality (**git-wins** tie-break) and re-dispatches only `pending`/`failed`/`blocked` jobs. Resume lives in Engine A so it survives a hard crash.
- **Result collector + lean memory** (`scripts/compound-v-collect-results.py`, `scripts/compound-v-update-memory.py`, `docs/superpowers/memory/routing-lessons.md`). Normalizes heterogeneous worker output into schema-conforming `job_result`s, folds in the scope verdict, and appends one line per job to `task-outcomes.jsonl`. `routing-lessons.md` is human-curated. No semantic search, no scorecards in 1.0.
- **Routing policy** (`skills/compound-v/routing-policy.md`). task-type → **(tier, effort)** + backend/isolation (no concrete model strings in the table). **Balanced** default; **Conservative** and **Cost-aware** stances; **env-aware Claude-only fallback** when Codex is absent. Documents the config `models` map, the resolver, and `/v:models`. Cites `routing-lessons.md` as a consulted input.
- **`/v:init`** (`commands/v-init.md`). Detects Codex CLI / Context7 MCP / required skills, walks through any missing installs one at a time, re-probes the Codex flag set against `codex exec --help`, sets the routing stance, and saves config: project `.claude/compound-v.json` (stance + a **seeded default `models` map** so routing works out of the box — mentions `/v:models` for refresh/customization) + user `~/.claude/compound-v-capabilities.json` (capability cache).
- **New commands** `/v:orchestrate`, `/v:collect`, `/v:status`, `/v:resume`, `/v:models` (`commands/`).
- **Skill escalation policy** (`skills/compound-v/skill-escalation.md`). Gated pull-in of deep-research / playground / avoid-ai-writing, plus forced Context7 — only when genuinely needed, each logged in the run's reasoning.
- **Strict `job_result` schema** (`schemas/job_result.schema.json`) and committed fixtures (`examples/`) so CI validates real data.
- New CI gates in `validate.yml`: schema validity, manifest-invariant check, collector schema-conformance, and a no-fabricated-cost-metric grep.
- **Cross-model plan review** (optional, gated). A different model family (Codex/GPT) adversarially reviews a high-stakes plan/manifest *before* dispatch — the value is **error decorrelation** (a second Opus shares Opus's blind spots; Codex has different priors). Policy in `skills/compound-v/cross-model-review.md`; the read-only reviewer is `scripts/compound-v-codex-review.sh`, emitting findings against `schemas/plan-review.schema.json`. **Advisory only — the orchestrator arbitrates every finding; Codex is never the authority.** Gated by stakes (security/auth/payments/migrations/shared data model, large/coupled partition, architectural change, or human request); skipped for small/mechanical plans. Wired in after the `partition-reviewer` PASS in `phase-3` and surfaced by the `partition-reviewer` agent; manually triggerable via the new **`/v:review-plan`** command.
- **Graceful backend-failure handling** (classify → retry / reroute / halt). When a dispatched job returns non-success, the dispatcher runs a deterministic two-stage pipeline instead of guessing or blindly retrying. `scripts/compound-v-classify-failure.py` classifies the failure from exit code + stderr (codex) or the stream-json `api_retry.error` enum (claude) into one of `{out_of_credits, rate_limited, overloaded, auth, context_length, timeout, network, other, none}` — by error **TYPE**, not HTTP status (OpenAI `insufficient_quota` and a throttle are both 429; the Anthropic credit error is a **400/402, not 429**). `scripts/compound-v-failure-policy.py` is the static decision table: `out_of_credits`/`auth` **never retry** (`out_of_credits` circuit-breaks the backend for the run and re-routes the remaining jobs via the env-aware **codex→claude** rewrite — the SAME runtime rewrite, not just `/v:init`; `auth` halts for re-auth); transient classes **retry the same backend** with exponential backoff + jitter (honoring `retry-after`), capped **per-class AND** by a run-level `max_total_retries` (anti retry-storm); `context_length` re-routes with `escalate_tier` (bigger tier, or split the job). `job_result` gains a `failure_class` field (Codex worker emits it; `null` on success/blocked). The "circuit breaker" is `state.json` fields read at batch boundaries (**no daemon**): `attempts` / `cooldowns` / `circuit_open` / `total_retries` / `max_total_retries`; a transient failure only **deprioritizes** (short cooldown, probed half-open next batch) while a confirmed `out_of_credits`/`auth` opens the breaker for the run. A failed job past its retry budget is marked `failed` and the **batch continues** (ralph-tui-style — independent jobs don't die because a sibling 429'd); the run halts only when the last viable backend is exhausted (→ `/v:resume` after top-up). Every re-route/circuit-break is **loud** — surfaced in `/v:status` and the run summary with the cost direction; never a silent cheap→expensive swap. Policy in `skills/compound-v/failure-policy.md`; wired into `agents/parallel-dispatcher.md` (Step 2c), `phase-3`, `state-machine.md`, `routing-policy.md`, `commands/v-status.md`, and the backend-launcher contract. claude has no further local fallback in 1.0 (antigravity is 1.1), so an `out_of_credits`/`auth` on claude halts rather than re-routes.

### Security / Fixed — independent Codex review hardening (round 2)

A second independent Codex review went deeper and surfaced eight more findings — including a critical enforcement bypass and two regressions introduced by round 1; all are fixed:

- **Commit-inside-worktree bypass of the scope gate (CRITICAL).** The gate keyed off uncommitted `git diff HEAD` ∪ untracked, so an executor that COMMITTED its changes inside its worktree left a clean tree and slipped past enforcement. `compound-v-run-codex-worker.sh` now captures the baseline SHA with `git rev-parse HEAD` BEFORE `git worktree add` and passes `--baseline <sha>` (not `HEAD`) to `compound-v-scope-check.py`, so a `git diff <baseline-sha>` still includes the committed change and BLOCKS it. New scope-gate self-test: a file committed inside a worktree, outside `write_allowed`, must block.
- **Timeout argv-injection guard.** `--timeout-sec` is interpolated unquoted into the `timeout` argv in both bash wrappers; a crafted value like `5; touch /tmp/PWNED` injected argv. Both `compound-v-run-codex-worker.sh` and `compound-v-codex-review.sh` now reject any non-`^[0-9]+$` value with `die`.
- **macOS-symlink-safe containment (REGRESSION fix).** Round 1's containment assertion compared a canonical (`pwd -P`) parent against a raw `$WT` prefix; on macOS `$TMPDIR` is `/var/folders/...` while its canonical form is `/private/var/folders/...`, so the prefix check falsely rejected every valid run. The worker now canonicalizes BOTH sides before comparing; the id-character regex (no `/`, no `..`) remains the real traversal defense.
- **Direct-mode pre-existing snapshot (REGRESSION fix).** Round 1's gitignored/untracked union made direct-mode checks flag PRE-EXISTING untracked/ignored files a job never created. `compound-v-scope-check.py` gains `--preexisting <file>` (paths present before the job, one per line) that are excluded from the changed/violation set; `parallel-dispatcher.md` documents the dispatcher snapshotting pre-existing untracked+ignored for a direct job and passing `--baseline <sha> --preexisting <snapshot>`. New self-test: a snapshotted pre-existing file is not flagged, while a new out-of-scope file still BLOCKS. (Worktree mode is unaffected — a fresh `worktree add HEAD` has no pre-existing untracked.)
- **Backend enum aligned to `antigravity`.** `compound-v-validate-manifest.py` accepted an undocumented `none` and rejected the documented stub backend `antigravity`. The job-backend enum is now `{claude, codex, antigravity}` (`none` is the routing "return to planning" sentinel, never a dispatched job); `execution-manifest.md` and `routing-policy.md` wording matches.
- **Validator requires the remaining top-level fields.** `compound-v-validate-manifest.py` now also requires top-level `spec_path`, `plan_path`, and `audits` (joining the round-1 `run_id`/`feature`/`acceptance_criteria`/`routing_stance`/`max_parallel` set); `examples/manifest.example.yaml` still validates.
- **Collector job-id traversal guard.** `compound-v-collect-results.py` builds `<run-dir>/results/<job-id>.json`; `--job-id` is now validated against `^[A-Za-z0-9._-]+$` (rejecting `.`/`..`) before any path is built, exiting non-zero on a bad id (same class as the round-1 worker guard, previously missed here).
- **Empty write-scope allowed for review jobs.** `compound-v-run-codex-worker.sh` no longer `die`s on an empty `--write-allowed`; an empty allow-list means NO writes are permitted, so the gate treats any changed path as a violation. `adapter-codex.md` documents empty write-scope = read-only/review job.

### Hardened — backend-failure round 2 (fail-closed + health-aware reroute + deepest-tier guard)

A second hardening pass on the graceful backend-failure feature, tightening the executable behavior and the docs that describe it:

- **Fail-closed enforcement faults.** A worker `error`/`timeout` status can no longer carry `failure_class: none` — a genuine failure can't masquerade as success and skip the policy loop.
- **Fallback-health-aware reroute.** `compound-v-failure-policy.py` gained `--fallback-open`: an `out_of_credits` whose only fallback is itself circuit-open now returns **`halt`** (both causes surfaced) instead of a doomed reroute. The dispatcher passes it when `circuit_open[<fallback-backend>].open` is true.
- **Deepest-tier context guard.** The policy gained `--current-tier {deep|standard|light}`: a `context_length` failure escalates a tier **unless already at the deepest tier** (`deep`), where it halts and the job is split (back to planning) rather than escalating into a model that doesn't exist.
- **Real claude enum parsing.** The classifier now **parses** the claude stream-json `api_retry.error` enum and maps the exact value (`billing_error` → `out_of_credits`, etc.); the claude substring needles are a narrow fallback used only when the output isn't JSON (no bare `context`/`invalid_request`, which would mis-escalate). Run the adapter with `--output-format stream-json`.
- **`Retry-After` honored.** The classifier extracts the provider wait; `job_result` carries it as `retry_after_seconds` (int), which the dispatcher passes as `--retry-after` so a retry sleeps the provider's stated time instead of synthetic backoff.
- **Circuit breaker is a reconciled object.** `state.json` `circuit_open` is now `{ "<backend>": { "open", "reason": "out_of_credits|auth", "opened_at", "cleared_by" } }` (not a bare bool). `/v:resume` reconciles it by `reason` — `out_of_credits` stays open until a top-up or a liveness probe, `auth` until re-auth (`/v:init`) — and **never silently re-dispatches** to a still-open breaker.
- **Per-(job, class) attempts.** `state.json` `attempts` is keyed `{ "<job>": { "<failure-class>": n } }`, so a budget consumed by one class doesn't starve another; the counter resets/forks on a backend re-route or class change. The dispatcher passes `attempts[job][class]` as `--attempts`.

Docs updated to match the scripts (no behavior is encoded in prose that the scripts don't enforce): `skills/compound-v/failure-policy.md`, `skills/compound-v/state-machine.md`, `agents/parallel-dispatcher.md`, `commands/v-resume.md`, `skills/backend-launcher/adapter-claude.md`.

### Hardened — backend-failure round 3 (collector parity + breaker wiring)

A third pass closing what a cross-model review of the round-2 code surfaced:

- **Collector parity (critical regression fix).** `compound-v-collect-results.py` now emits the new required `failure_class` + `retry_after_seconds` fields, so a normalized `claude`/`direct` `job_result` satisfies `job_result.schema.json` (its hand-rolled conformance checker now also handles nullable `["string","null"]` types).
- **Auth opens the breaker.** Opening `circuit_open[<backend>]` is keyed on the policy's `circuit_break: true` — true for `auth` as well as `out_of_credits` — not only the out_of_credits reroute path.
- **Retries write a cooldown timestamp.** The `retry` action records `cooldowns[<backend>] = now + backoff_seconds` *before* sleeping, so the resume/half-open logic has a real timestamp to probe.
- **Mid-batch circuit-break is check-before-launch.** Before launching each job the dispatcher checks `circuit_open[backend]`; in-flight jobs on a newly-broken backend complete and fail-fast (a no-daemon dispatcher can't un-launch them).
- **Codex 5xx → overloaded.** `server_error` / `5xx` from codex now classify as `overloaded` (retryable), not `other`.

### Fixed / Documented — independent Codex review hardening (round 3)

A third independent Codex review pass (0 critical, 3 high, 5 medium) produced quick real fixes plus honest documentation of inherent limits:

- **`model: haiku` execution-layer override rejected.** The never-Haiku policy was only checked in frontmatter (`lint-frontmatter.py`), but a manifest job could pin `model: haiku` (or `claude-haiku-...`) as an execution-layer override and slip through. `compound-v-validate-manifest.py` now flags ANY job whose explicit `model` contains "haiku" (case-insensitive) as a violation. New self-test: a job with `model: haiku` is INVALID.
- **`depends_on` graph validated (refs + cycles).** `compound-v-validate-manifest.py` now validates each job's `depends_on`: every referenced id must exist among the manifest job ids (a dangling ref is a violation), and the dependency graph must be acyclic (cycle detection via DFS, naming the jobs on the cycle). New self-tests: dangling ref INVALID, cycle INVALID, valid DAG OK.
- **Manifest structural type-checks.** Required fields are now type-checked, not just presence-checked: `jobs` non-empty list, `acceptance_criteria` list, `audits` mapping, `max_parallel` int, `run_id`/`feature`/`spec_path`/`plan_path` strings, and per-job `write_allowed`/`read_allowed`/`acceptance` lists. A wrong-typed field is its own specific violation; `examples/manifest.example.yaml` still validates.
- **NUL-safe scope-gate path handling.** `compound-v-scope-check.py` switched all three git probes to NUL-delimited output (`git diff --name-only -z`, `git ls-files --others --exclude-standard -z`, and the `-z` ignored variant) and splits on `\0`, so a filename containing a newline cannot smuggle additional paths past the gate. New self-test: an unusual filename (a name with a space, and a name with a literal newline where the FS allows) is attributed as a single path and BLOCKS correctly.
- **Documented inherent limit: `read_allowed` is advisory.** Only `write_allowed` is git-enforced; git cannot track reads, so `read_allowed` documents intent and scopes the prompt but is NOT a hard boundary. Stated plainly in `execution-manifest.md`, `backend-launcher/SKILL.md`, `adapter-codex.md`, and `adapter-claude.md`.
- **Documented inherent limit: `direct`-mode dirty-tree caveat → prefer `worktree`.** `isolation: direct` gates against a baseline minus a pre-existing untracked/ignored snapshot, so a job that MODIFIES a pre-existing untracked/ignored file is not flagged. `worktree` (a fresh checkout with no pre-existing files) is the exact-gate safe default for anything untrusted or on a dirty tree; `direct` stays serial-only and is for trusted, clean-tree jobs. Documented in `execution-manifest.md` and `routing-policy.md`.
- **Stale merge-back instructions corrected.** Removed the remaining `git diff HEAD | git apply` (drops untracked additions) merge-back forms in `adapter-claude.md`, `phase-3-parallel-opus-dispatch.md`, `compound-v/SKILL.md`, and this CHANGELOG's model-broker note, replacing them with the index-based patch (`git add -A && git diff --cached --binary HEAD | git apply --index`) used everywhere else.
- **Clarified deliberate design: agent-driven flow, deterministic enforcement.** Added a note in `phase-3-parallel-opus-dispatch.md` that the orchestration flow is intentionally agent-driven (Engine A, anti-ruflo: no daemon) while enforcement lives in deterministic scripts (scope-check / validate-manifest) — the safety guarantees are in the scripts, not the flow.

### Security / Fixed — independent Codex review hardening

A pass of an independent Codex code review surfaced eight correctness/security findings in the orchestrator scripts and docs; all are fixed:

- **Path-traversal guard on `run_id` / `job_id` (CRITICAL).** `compound-v-run-codex-worker.sh` built a worktree path from these ids and ran `git worktree remove -f || rm -rf` on it — a `../` in an id could escape `$TMPDIR` and delete arbitrary directories. Ids are now validated against `^[A-Za-z0-9._-]+$` (rejecting `.`/`..`) before any path is built, and the worktree path is asserted to live strictly under `$TMPDIR/compound-v/` before any removal. `compound-v-validate-manifest.py` rejects the same unsafe ids (and `run_id`) so a malicious manifest never reaches dispatch.
- **Worker delegates enforcement to the Python gate.** The worker previously derived `violations`/`files_changed`/`status` with a bash `case`-glob matcher that was *weaker* than the Python authority (bash `*` matches `/`) and diverged from it. The bash matcher is deleted; after the codex run the worker now calls `compound-v-scope-check.py` (parsed with `jq`) as the single source of truth, layering timeout/error exit codes on top.
- **Scope gate now sees gitignored writes.** `compound-v-scope-check.py` only probed `git ls-files --others --exclude-standard`, which excludes ignored files — a worker could write a gitignored path (`dist/`, `.env`) undetected. It now also unions `git ls-files --others --ignored --exclude-standard -- .`, so any ignored write outside `write_allowed` is reported and BLOCKS (covered by a new self-test).
- **Allowed new files survive merge-back.** The documented merge-back `git diff HEAD | git apply` silently dropped untracked (new) files — an allowed new file passed the gate but was lost. Replaced everywhere with an index-based patch that includes additions (`git add -A && git diff --cached --binary HEAD | git apply --index`) across `backend-launcher/SKILL.md`, `adapter-codex.md`, `parallel-dispatcher.md`, and the PRD/plan.
- **Direct-mode scope check requires `--baseline`.** A `--repo` (direct) job's baseline must be the recorded pre-dispatch commit, not a defaulted (possibly-moved) HEAD; the gate now errors if `--baseline` is omitted in direct mode. Worktree mode keeps the HEAD default (worktrees are fresh from HEAD).
- **Validator enforces all required fields + `parallel ⇒ worktree`.** `compound-v-validate-manifest.py` now validates every required top-level and per-job field and their enums (`backend`/`isolation`/`run`/`routing_stance`/`tier`/`effort`) before the invariant checks, and rejects any `run: parallel` + `isolation: direct` job (per-job scope attribution requires worktree isolation). The example manifest's parallel claude jobs moved to `isolation: worktree`; `execution-manifest.md` and `routing-policy.md` state the rule crisply (parallel ⇒ worktree; direct ⇒ serial).
- **Collector can no longer override the scope verdict.** In `compound-v-collect-results.py` the `--files-changed` / `--violations` / `--blocked` flags are now **additive-only** when a scope verdict is present: `blocked` = scope OR flag, `violations`/`files_changed` = union(scope, flag). A flag may force a block or add entries but can never clear a scope-gate block or drop a scope violation.

### Fixed

- **`validate-manifest.py` `globs_overlap` soundness fix.** The manifest validator's write-glob overlap test (rule 1, disjoint writes) had a soundness bug — caught on the first real cross-model review run when Codex read the repo and flagged it. Hardened so overlapping `write_allowed` globs are reliably detected.

### Added — the model-broker delta

Stops hardcoding model strings. Jobs route by **intent**, not by a literal model name, so the plugin survives model churn and gains Codex's reasoning-effort dimension.

- **Tier + effort vocabulary** — a stable routing vocabulary that never changes when models churn. `tier ∈ {deep, standard, light}` (deep = strongest reasoning: architecture, security/auth/payments, designing tests, external APIs, **all** reviewers, the shared-foundation Task 0; standard = bounded core/feature build incl. large isolated Codex work; light = mechanical single-file / docs / i18n). `effort ∈ {low, medium, high}` is an orthogonal hint with a sensible default pairing (deep→high, standard→medium, light→low) that stays independently tunable per task-type.
- **Refreshable config model-map** — `.claude/compound-v.json` gains a `models` map (`claude` / `codex` / `antigravity`, each `deep`/`standard`/`light` → a concrete model). The map is **not** committed in the repo — it is documented and seeded by `/v:init`, then refreshed via `/v:models`. Claude uses native tier aliases (`opus`/`sonnet`), Codex is a curated+user-overridable list (it has no `models` list command), and Antigravity values are illustrative placeholders refreshed by `agy models`. **Never `haiku`, anywhere.**
- **Model resolver** (`scripts/compound-v-resolve-model.py`). Generic — no backend-specific Codex/Antigravity logic baked into routing. CLI: `--backend {claude|codex|antigravity} --tier {deep|standard|light} [--effort {low|medium|high}] [--config PATH] [--explicit-model M]`. Carries a **built-in default map** so it resolves with no config file; a `models.<backend>.<tier>` entry in `--config` overrides the default; `--explicit-model` (a manifest override) always wins. Emits one JSON object on stdout — `{ "backend", "tier", "model", "effort" }` — and exits non-zero when a tier can't be resolved. Python 3.9-safe, stdlib only.
- **Codex `--effort`** — `scripts/compound-v-run-codex-worker.sh` gains an optional `--effort {low|medium|high}` arg that appends `-c model_reasoning_effort=<effort>` to **both** `codex exec` invocations (with and without `--output-schema`). Everything already there is preserved: the `</dev/null` stdin redirect, stdout capture, scratch-outside-worktree handling, no `--ask-for-approval never`, bash 3.2 safety, shellcheck-clean.
- **`/v:models`** (`commands/v-models.md`). Discovers available models per backend — `agy models` for Antigravity (when present), a curated list for Codex, native tiers for Claude — shows them, lets the user assign tier→model, and **writes** the `models` map into `.claude/compound-v.json`. This is the "skill picks the models and offers you options" surface.

### Changed

- **`plugin.json` + `marketplace.json` → `1.0.0`** in lockstep; added the `orchestrator` keyword.
- **`SKILL.md`** evolved to orchestrator-as-default — the description now mentions manifest materialization and the scope-enforced, resumable pipeline, **without weakening the auto-fire triggers** (every existing `evals.json` case still passes).
- **`/v:dispatch`** evolved to be manifest-aware **backward-compatibly**: it accepts a bare plan path (auto-materializing a manifest), a manifest, or a run-id. The 0.1.x plan-path flow — and the `plan-saved-nudge` hook — keep working.
- **Agents evolved:** `parallel-dispatcher` is manifest-driven and multi-backend — for each job it runs `compound-v-resolve-model.py` with `(backend, tier, effort, config)` **before** dispatch to get the concrete model, passes `--model <resolved>` (+ `--effort` for Codex) to the worker, then calls `scope-check.py` after every job and HALTS on BLOCKED (an explicit manifest `model` skips resolution); `partition-reviewer` runs `validate-manifest.py` as its deterministic backing gate; `spec-reviewer` runs the three-pass Review Gate (spec acceptance criteria · quality/no-regression/no-fabricated-metrics · final integration). All reviewers remain `model: opus`. The agent's own `model: opus` frontmatter is unrelated to execution-layer resolution; resolved manifest models (`gpt-5.5`, etc.) are execution-layer data and **never** appear in frontmatter.
- **Phases evolved:** `phase-2` emits `manifest.yaml` (not only prose); `phase-3` is manifest-driven multi-backend dispatch with per-job isolation and the scope gate.
- **Hooks evolved:** `session-banner.sh` adds a `/v:init` hint when `.claude/compound-v.json` is absent; `plan-saved-nudge.sh` mentions `/v:orchestrate` alongside the existing dispatch path. Both keep all three platform JSON branches and stay `shellcheck`-clean.

### Explicit dispositions

- **Antigravity adapter = stub, deferred to 1.1.** Assessed, not assumed. Google's official `agy` CLI fits the contract, but two blockers keep it out of 1.0: headless `agy --print` returns empty stdout when piped/redirected ([#408](https://github.com/google-antigravity/antigravity-cli/issues/408), [#318](https://github.com/google-antigravity/antigravity-cli/issues/318)) and there is no non-interactive auth ([#223](https://github.com/google-antigravity/antigravity-cli/issues/223)). `adapter-antigravity.md` ships as a stub returning `unsupported`; the 1.1 spike targets the Antigravity Python SDK first.
- **Workflows accelerator = kept in 1.0 as opt-in (Engine C).** `skills/compound-v/workflows-accelerator.md` is a capability-probed fast-path for large parallel batches (16-wide) that **auto-falls-back to Engine A's batched `Task` dispatch** when Workflows is absent or disabled. The scope gate and `state.json` resume **stay in Engine A** even when C runs, so file-scope enforcement and crash-resume never regress. Engine B (`claude -p` shell-out) was rejected (rate-limit cascades + third-party-orchestrator policy).

### Notes

- All helper scripts — including the new `compound-v-resolve-model.py` — target stock-macOS **bash 3.2** and **python 3.9** (stdlib only; pyyaml optional with an embedded-subset fallback) and are `shellcheck`-clean and executable.
- The `models` map is **documentation + seeded config**, never committed in the repo. `compound-v-resolve-model.py` ships with a built-in default map so routing works even with no config file present.
- Worktrees live in `$TMPDIR/compound-v/<run-id>/<job-id>`; merge-back on PASS is an index-based patch that includes new files (`git -C <wt> add -A && git -C <wt> diff --cached --binary HEAD | (cd <repo> && git apply --index)`) into the main tree — a plain `git diff HEAD | git apply` would drop allowed untracked additions.
- Honestly **not** auto-tested (documented + manually verified, no CI gate): the worker-prompt pre-emptive STOP behaviour (only the post-hoc scope-check is gated), Codex-session resume re-attachment, the `/v:init` flag-probe, capability-cache staleness, and the Workflows probe-fails→fallback path.

## [0.1.3] — 2026-05-18

### Changed
- Marketplace name renamed from `superpowers-v-marketplace` to `procoders`. End-user install command is now `/plugin install superpowers-v@procoders` (was the awkward `superpowers-v@superpowers-v-marketplace`). The `procoders` name is also future-proof — additional procoders plugins can ship via the same marketplace.
- README install section trimmed to one path at the top; local-clone / `--plugin-dir` dev flows moved to a new **Development** section lower in the doc.

## [0.1.2] — 2026-05-18

### Fixed (critical)
- **Install instructions in README were wrong.** Claimed `/plugin install <github-url>` works directly; it does not. Real path is the documented two-step: `/plugin marketplace add <url-or-path>` first, then `/plugin install <plugin>@<marketplace-name>`. Reported by user trying to install v0.1.1 from GitHub and getting "Marketplace not found."

### Changed
- Marketplace name renamed from `superpowers-v-dev` to `superpowers-v-marketplace` (mirrors the upstream `obra/superpowers` → `superpowers-marketplace` naming convention; cleaner for end-user-facing install command).
- README install section now shows three install paths: marketplace + GitHub, marketplace + local clone, and `--plugin-dir` live-edit mode.

## [0.1.1] — 2026-05-18

Honesty pass after an independent verification audit caught several fabricated CLI/env-var references that I had baked into hooks and docs without verifying against the official Claude Code documentation.

### Fixed (critical — load-bearing)
- **Hook scripts no longer read fabricated environment variables.** Rewrote `session-banner.sh` and `plan-saved-nudge.sh` to follow the documented Claude Code hook interface: input read from JSON on stdin (via `jq`), output emitted as JSON for `additionalContext` context injection. Pattern adapted from upstream `obra/superpowers v5.1.0` reference hooks. Previous scripts read `$CLAUDE_HOOK_MATCHER` and `$CLAUDE_TOOL_INPUT_FILE_PATH`, neither of which exists in the official hook spec — the hooks were technically running but always silently no-op'd.
- **SessionStart matcher corrected** from `*` to the documented pattern `startup|clear|compact` (matches upstream superpowers).

### Removed
- `compound-v:doctor` agent + `/v:doctor` slash command — clutter for typical sessions; manual debug instructions in TROUBLESHOOTING.md cover the same ground.
- `SubagentStop` hook configuration + `sidekick-nudge.sh` script — the `SubagentStop` event is not in the official Claude Code hooks reference and the reference plugin `obra/superpowers` does not use it. Replaced with description-based auto-fire (which was always the primary mechanism) plus the `PostToolUse(Write)` plan-saved nudge.
- `gemini-extension.json` — manifest schema was not verifiable against official Gemini CLI docs; removed rather than ship a fabricated config.

### Changed
- **Multi-harness shims (AGENTS.md, GEMINI.md) marked 🧪 experimental / untested.** Previous wording implied verified support; honest reality is the shims are based on documentation patterns but were not exercised on a real Codex or Gemini install. The README compatibility table now reflects this.
- README install steps: removed fictional `/mcp add context7` command; correct install path is `/plugin install context7@claude-plugins-official` or manual `~/.claude.json` MCP config. Context7 demoted from step 1 to step 3 (recommended, not required).
- Phase 3 dispatcher announce string toned down (was "going Supe"; now neutral "dispatching N implementers").
- SKILL.md auto-fire caveat rewritten honestly: skill invocation is description-driven; hooks provide reminders but do NOT enforce the trigger.
- `.github/workflows/validate.yml` no longer validates `gemini-extension.json` (file removed).

### Added
- Hard citation-rigor rules in `agents/domain-expert.md`: ≥10 distinct community posts OR 1 official source for consensus claims; isolated reports flagged explicitly; no fabricated URLs; verbatim quotes only; empty section > padded section.

### Notes on the honesty audit
The verifier could not find official documentation for several Task tool parameters used throughout the plugin (`subagent_type: "<plugin>:<agent>"` plugin-namespaced syntax, `maxTurns`, `run_in_background: true`). These remain in the plugin's prompts and docs because they are observably functional in Claude Code as of v0.1.1, but should be revisited if they break in a future CC version. Tracked for future verification.

## [0.1.0] — 2026-05-18

Initial public release.

### Added

**Core skill (`skills/compound-v/`):**
- Three-trigger interceptor for Superpowers transitions (after brainstorming, inside writing-plans, before execution)
- Phase 1A: code-archaeology pre-flight (five-phase audit of existing-code reality)
- Phase 1B: domain-expert advisor with three-layer parallel WebSearch (official docs, practitioner channels, audience/persona forums)
- Phase 1C: library/doc validator via Context7 MCP (catches stale deps, abandoned libraries, outdated API signatures)
- Phase 2: Disjoint File Partition Map enforcement inside writing-plans
- Phase 3: batched parallel Opus dispatch with strict scope locks; `model: opus` by default, `model: sonnet` only when a task ticks every box of the strict 8-box junior-task taxonomy

**6 first-class agents (`agents/`)** — invokable as `subagent_type: "compound-v:<name>"`:
- `code-archaeologist`, `domain-expert`, `doc-validator`, `partition-reviewer`, `parallel-dispatcher`, `spec-reviewer`

**2 slash commands (`commands/`):**
- `/v:archaeology <topic>`, `/v:dispatch <plan-path>`

**Hooks (`hooks/`)** — sidekick auto-fire (text-printer only, no side effects):
- `SessionStart` banner reminding parent Claude that Compound V is loaded
- `PostToolUse matcher=Write` nudges when a plan or spec is saved

**Operational:**
- `.github/workflows/validate.yml` — JSON schema, agent frontmatter (with no-Haiku project policy), dead-link scan, shellcheck on hooks
- `scripts/lint-frontmatter.py` — Python frontmatter linter for local pre-commit
- `evals/evals.json` — 8 trigger eval test cases (3 positive, 2 negative, 3 edge) for the compound-v skill
- `.cclintrc.json` — config for [`@felixgeelhaar/cclint`](https://github.com/felixgeelhaar/cclint)
- `TROUBLESHOOTING.md` — common issues
- All code blocks tagged with explicit language

**Realistic concurrency limits documented:** 4-6 foreground / 5-10 background Task calls per message; batched dispatch for larger plans; `maxTurns: 15` cap; `run_in_background: true` recommended for implementer batch.

**Output convention:** `docs/superpowers/{archaeology,expert,library-audit}/` with `_knowledge-base/` subdirectories for cross-feature knowledge persistence.

## [0.1.0] — 2026-05-18

Initial public release.

### Added

**Core skill (`skills/compound-v/`):**
- Three-trigger interceptor for Superpowers transitions (after brainstorming, inside writing-plans, before execution)
- Phase 1A: code-archaeology pre-flight (five-phase audit of existing-code reality)
- Phase 1B: domain-expert advisor with three-layer parallel WebSearch (official docs, practitioner channels, audience/persona forums)
- Phase 1C: library/doc validator via Context7 MCP (catches stale deps, abandoned libraries, outdated API signatures)
- Phase 2: Disjoint File Partition Map enforcement inside writing-plans
- Phase 3: batched parallel Opus dispatch with strict scope locks; `model: opus` by default, `model: sonnet` only when a task ticks every box of the strict 8-box junior-task taxonomy

**6 first-class agents (`agents/`)** — invokable as `subagent_type: "compound-v:<name>"`:
- `code-archaeologist`, `domain-expert`, `doc-validator`, `partition-reviewer`, `parallel-dispatcher`, `spec-reviewer`

**2 slash commands (`commands/`):**
- `/v:archaeology <topic>`, `/v:dispatch <plan-path>`

**Hooks (`hooks/`)** — sidekick auto-fire (text-printer only, no side effects):
- `SessionStart` banner reminding parent Claude that Compound V is loaded
- `SubagentStop matcher=brainstorming|writing-plans` nudges with next-step dispatch
- `PostToolUse matcher=Write` nudges when a plan or spec is saved

**Multi-harness compatibility shims (experimental):**
- `AGENTS.md` (Codex CLI)
- `GEMINI.md` + `gemini-extension.json` (Gemini CLI)

**Operational:**
- `.github/workflows/validate.yml` — JSON schema, agent frontmatter (with no-Haiku project policy), dead-link scan, shellcheck on hooks
- `scripts/lint-frontmatter.py` — Python frontmatter linter for local pre-commit
- `evals/evals.json` — 8 trigger eval test cases (3 positive, 2 negative, 3 edge) for the compound-v skill
- `.cclintrc.json` — config for [`@felixgeelhaar/cclint`](https://github.com/felixgeelhaar/cclint) (silences CLAUDE.md-specific false-positives)
- `TROUBLESHOOTING.md` — 11 documented common issues
- All code blocks tagged with explicit language (`plaintext`, `markdown`, etc.)

**Realistic concurrency limits documented:** 4-6 foreground / 5-10 background Task calls per message; batched dispatch for larger plans; `maxTurns: 15` cap; `run_in_background: true` recommended for implementer batch.

**Output convention:** `docs/superpowers/{archaeology,expert,library-audit}/` with `_knowledge-base/` subdirectories for cross-feature knowledge persistence.
