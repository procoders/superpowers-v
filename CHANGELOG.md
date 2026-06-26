# Changelog

All notable changes to **superpowers-v (Compound V)** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses semantic versioning.

## [1.0.0] — 2026-06-26

Compound V graduates from a description-driven skill-pack into a **lightweight execution orchestrator**. The three pre-flights and `/v:archaeology` are behaviourally unchanged; the orchestrator extends the *tail* of the flow (manifest → dispatch → scope-gate → collect → review → memory) with multi-backend execution, per-job isolation, and crash-resume. No daemon, no MCP server, no vector DB, and **no fabricated token-cost metrics** (the anti-ruflo charter). Built by dogfooding the Compound V pipeline on this repo.

### Added — the orchestrator delta

- **Execution manifest** (`skills/compound-v/execution-manifest.md`, `examples/manifest.example.yaml`). A machine-readable `manifest.yaml` of file-scoped jobs — backend · optional `tier`/`effort` · isolation · `write_allowed`/`read_allowed` · per-job and feature-level acceptance criteria — materialized from the verified Partition Map immediately after `writing-plans`. A job carries an optional `tier` + `effort`; `model` becomes an optional **override**. A job MUST have `model` **or** `tier` (backward-compatible: existing explicit-`model` jobs stay valid); reviewer jobs must resolve to `tier=deep` **or** `model=opus`. This is the contract between planner and executors.
- **Backend Launcher** sub-skill (`skills/backend-launcher/`). One `job_spec → job_result` contract (`schemas/job_result.schema.json`) that every adapter implements; the orchestrator speaks only this contract and never sees backend-specific flags. Adapters: `adapter-claude.md` (Task-based, model override, `maxTurns: 15`), `adapter-codex.md` (headless `codex exec` in a git worktree), `adapter-antigravity.md` (stub — see dispositions below).
- **Headless Codex worker** (`scripts/compound-v-run-codex-worker.sh`). Runs one file-scoped job on `codex exec` inside a dedicated `$TMPDIR` git worktree, then emits the canonical `job_result`. Verified against `codex-cli 0.130`: the flag set is `--cd / --sandbox / --skip-git-repo-check / --model / --output-last-message / -c sandbox_workspace_write.network_access` (plus optional `--output-schema`). **`--ask-for-approval never` is invalid for `codex exec` and is omitted** — `exec` already defaults to `approval: never`. Resume is `codex exec resume <uuid>`. The cosmetic `[features].codex_hooks is deprecated` stderr is suppressed.
- **Scope gate** (`scripts/compound-v-scope-check.py`). The deterministic authority behind the prose `SCOPE LOCK`. After every job it unions `git diff --name-only HEAD` with `git ls-files --others --exclude-standard` and tests each changed path against `write_allowed`. A violation is **BLOCKED** — the job never merges and the run halts. Enforcement fields (`files_changed` / `violations` / `blocked`) are **git-derived, never model-self-reported**.
- **Manifest validator** (`scripts/compound-v-validate-manifest.py`). A deterministic invariant gate the `partition-reviewer` runs: disjoint `write_allowed`, Codex⇒worktree, reviewers⇒Opus/deep, shared resources in the serial Task 0. Extended for the model-broker: `tier ∈ {deep,standard,light}` and `effort ∈ {low,medium,high}` when present, and every job must carry `model` **or** `tier`.
- **State machine + crash-resume** (`skills/compound-v/state-machine.md`). A lightweight `state.json` (not an FSM engine) tracks phase + per-job status under `docs/superpowers/execution/<run-id>/`. `/v:resume` reconciles `state.json` against git reality (**git-wins** tie-break) and re-dispatches only `pending`/`failed`/`blocked` jobs. Resume lives in Engine A so it survives a hard crash.
- **Result collector + lean memory** (`scripts/compound-v-collect-results.py`, `scripts/compound-v-update-memory.py`, `docs/superpowers/memory/routing-lessons.md`). Normalizes heterogeneous worker output into schema-conforming `job_result`s, folds in the scope verdict, and appends one line per job to `task-outcomes.jsonl`. `routing-lessons.md` is human-curated. No semantic search, no scorecards in 1.0.
- **Routing policy** (`skills/compound-v/routing-policy.md`). task-type → **(tier, effort)** + backend/isolation (no concrete model strings in the table). **Balanced** default; **Conservative** and **Cost-aware** stances; **env-aware Claude-only fallback** when Codex is absent. Documents the config `models` map, the resolver, and `/v:models`. Cites `routing-lessons.md` as a consulted input.
- **`/v:init`** (`commands/v-init.md`). Detects Codex CLI / Context7 MCP / required skills, walks through any missing installs one at a time, re-probes the Codex flag set against `codex exec --help`, sets the routing stance, and saves config: project `.claude/compound-v.json` (stance + a **seeded default `models` map** so routing works out of the box — mentions `/v:models` for refresh/customization) + user `~/.claude/compound-v-capabilities.json` (capability cache).
- **New commands** `/v:orchestrate`, `/v:collect`, `/v:status`, `/v:resume`, `/v:models` (`commands/`).
- **Skill escalation policy** (`skills/compound-v/skill-escalation.md`). Gated pull-in of deep-research / playground / avoid-ai-writing, plus forced Context7 — only when genuinely needed, each logged in the run's reasoning.
- **Strict `job_result` schema** (`schemas/job_result.schema.json`) and committed fixtures (`examples/`) so CI validates real data.
- New CI gates in `validate.yml`: schema validity, manifest-invariant check, collector schema-conformance, and a no-fabricated-cost-metric grep.

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
- Worktrees live in `$TMPDIR/compound-v/<run-id>/<job-id>`; merge-back on PASS is `git -C <wt> diff HEAD | git apply` into the main tree.
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
