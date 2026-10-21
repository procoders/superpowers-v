### 1. Wrong or Premature Verdicts (Ranked)

1. **[`scripts/compound-v-codex-review.sh`] — Table says `ПЕРЕНОСИМ` (Row 75, "основа исполняемого ревью") → Should be `МЕНЯЕМ`.**
   [`compound-v-codex-review.sh`] is hardwired to review a **plan** (`--plan-file`, prompt `--- PLAN UNDER REVIEW ---`, schema [`schemas/plan-review.schema.json`]) and launches `codex exec` with `--sandbox read-only` ([L154]). It never calls [`scripts/compound-v-sandbox-checkout.sh`] and cannot start a server, run tests, or reproduce runtime defects as required by Row 31 / В3.

2. **[`tests/test-epic-goal-stop.sh`] & [`tests/test-sandbox-checkout.sh`] — Table says `УДАЛЯЕМ вместе с кодом` (Row 95) → Should be `МЕНЯЕМ` and `ПЕРЕНОСИМ`.**
   [`tests/test-epic-goal-stop.sh`] has not tested epics since v3.4.0; it guards the fail-open `exit 0` invariant and triage gate of [`hooks/epic-goal-stop.sh`], which Row 34 keeps (`МЕНЯЕМ`). [`scripts/compound-v-sandbox-checkout.sh`] is kept as-is in Row 75 (`ПЕРЕНОСИМ`), so deleting [`tests/test-sandbox-checkout.sh`] leaves kept code untested.

3. **[`scripts/compound-v-cochange.py`] & [`scripts/compound-v-churn.py`] — Table says `УДАЛЯЕМ` (Rows 44, 68) while keeping "co-change как вход для археологии" (Rows 26, 68) and marking [`scripts/compound-v-onboard.py`] `ПЕРЕНОСИМ` (Row 87) → Should be `МЕНЯЕМ`.**
   If `cochange.py` is deleted, nothing computes co-change for [`agents/code-archaeologist.md`]. Furthermore, [`compound-v-cochange.py`] hard-imports `compound-v-churn.py` (`_load_sibling("compound-v-churn.py")`), and [`compound-v-onboard.py`] (`draft_churn_summary` and its `--selftest` at [L1990]) imports `churn.py` and `validate-manifest.py`.

4. **[`scripts/compound-v-preeval.py`] + [`localize.py`] + [`taxonomy.py`] + [`validate-taxonomy.py`] — Table keeps ~6.2k lines (`МЕНЯЕМ`, Row 42) → Should be `УДАЛЯЕМ` (replace with a ~150-line classifier inside [`hooks/triage-prompt-nudge.sh`]).**
   Finding В5 only proved that `UserPromptSubmit` auto-nudging starts brainstorming without slash commands. It did not validate the 3×3 difficulty/impact taxonomy, `.intent.json`/`.localization.json`/`.taxonomy-snapshot.yaml` artifacts, or digest sealing, whose main consumer (`validate-manifest.py --require-triage`) is being deleted.

5. **[`scripts/compound-v-fastpath-run.py`] — Table says `УДАЛЯЕМ` (Row 58) → Should be `МЕНЯЕМ` (extract `test-floor` + receipt sealing, or strip `--test-contract-file` from workers).**
   Kept workers ([`scripts/compound-v-run-codex-worker.sh`], [`scripts/compound-v-run-opencode-worker.sh`]) consume the `--test-contract-file` JSON produced by `fastpath-run.py resolve-tests`, and `accept-review` already implements the diff-bound review receipt that Row 59 proposes to rewrite.

---

### 2. What Is Missing from the Table

* **Unlisted repository files:**
  * **Scripts:** [`scripts/compound-v-emit-preflight.py`] (1,317 lines; emits the 1A/1B/1C workflow AND renders recall blocks for [`hooks/brainstorm-trigger0-nudge.sh`]), [`scripts/compound-v-project-config.py`] (imported by `preeval.py` and `resolve-model.py`), [`scripts/compound-v-update-memory.py`], [`scripts/compound-v-dogfood-index.sh`], [`scripts/lint-frontmatter.py`].
  * **Metadata & commands:** [`.claude-plugin/plugin.json`] and [`.claude-plugin/marketplace.json`] (renaming `superpowers-v` → `compound-v`), [`commands/v-triage.md`] and all `commands/v-*.md` files, [`skills/backend-launcher/SKILL.md`] + adapters, [`agents/code-archaeologist.md`], [`agents/domain-expert.md`], [`agents/doc-validator.md`], [`hooks/memory-refresh.sh`], and 4 schemas in `schemas/`.
  * **8 omitted test files:** [`tests/test-agent-memory.sh`], [`tests/test-agent-recall.sh`], [`tests/test-codex-review-schema-default.sh`], [`tests/test-doc-validator-tools.sh`], [`tests/test-dogfood-index.sh`], [`tests/test-memory-install.sh`], [`tests/test-memory-recall-bench.sh`], [`tests/test-onboard-rules.sh`].
* **Unprovided v4 capabilities:**
  1. **Real-browser verification tool (Row 32, В6):** Row 32 equates *"реальный браузер / curl по живому серверу"*. `curl` **cannot** catch the A4/A5 `Referrer-Policy: no-referrer` + `Origin: null` bug ([`docs/v4/salon-report.md`]) because `curl` does not strip `Origin` on form `POST` navigation. v4 needs a headless browser script (Playwright or Chrome DevTools MCP) that submits real DOM forms.
  2. **Mechanical receipt producers for the Stop hook (Row 34, В7):** For [`hooks/epic-goal-stop.sh`] to check *"ревью сделано? scope gate пройден? браузер проверен?"* within its 800 ms budget, those steps must write diff-bound receipts (`sha256` of working tree state). Prose instructions without deterministic receipt writers recreate the skippable-prose bug (В7).
  3. **Plan-table extractor for lanes and routing (Rows 28, 30, 33, 79):** [`scripts/compound-v-scope-check.py`] requires `--allow` globs and a `--baseline` SHA, not a Markdown table. Nothing parses the prose plan to feed `scope-check.py` or subagent `model` selection.

---

### 3. Riskiest Migration Parts & CI-Safe Sequence

* **Silent breakages from hidden sibling imports:**
  * Deleting [`scripts/compound-v-validate-manifest.py`] breaks [`scripts/compound-v-taxonomy.py`]: `load_yaml` loses its stdlib `_mini_yaml` fallback (failing closed to `FULL` whenever PyYAML is absent), and `glob_match` falls back to inline regex ([L109-L126]) where `**/*.md` compiles to `(?s:.*/[^/]*\.md)\Z`—failing to match root-level files like `README.md`.
  * Deleting [`scripts/compound-v-dashboard.py`] makes `_has_active_run` in [`hooks/triage-prompt-nudge.sh`] return `0` ("cannot tell ⇒ ACTIVE"), **silently disabling triage on every prompt**.
  * [`scripts/compound-v-onboard.py`] top-level imports [`scripts/compound-v-memory.py`] (`SECRET_RE`, `PEM_RE`), plus `churn.py` ([L942]) and `validate-manifest.py` ([L1162], [L1906]).
* **Lost safety property:** Deleting [`hooks/lane-guard.sh`] (Row 57) drops pre-write confinement (`PreToolUse` deny) in favor of post-build `scope-check.py`. If parallel Claude subagents run without worktrees, they can overwrite each other's files mid-run before the post-build check fires.
* **Sequence to keep [`.github/workflows/validate.yml`] green:**
  1. **Decouple sibling imports first:** Inline `_mini_yaml` and [`compound-v-scope-check.py`]'s `glob_to_regex` into `taxonomy.py`/`onboard.py`; remove `dashboard.py`, `churn.py`, `triage-outcomes.py`, and `classify-request.py` calls from `triage-prompt-nudge.sh`, `preeval.py`, and `onboard.py`.
  2. **Add v4 skills, executable review mode, browser probe, and Stop-hook receipts** alongside [`tests/test-epic-goal-stop.sh`] updates.
  3. **Archive `docs/superpowers/execution/` → `docs/archive/` and update `validate.yml`** (drop manifest/state/epic steps; keep frontmatter lint, shellcheck, anti-ruflo, dead-link scan, `--selftest` sweep, and `tests/` sweep).
  4. **Atomically delete Engine C/epic scripts, docs, and their tests** in one commit so `validate.yml`'s repo-wide dead-link check ([L237-L278]) never trips.
  5. **Rename `superpowers-v` → `compound-v`** across `.claude-plugin/*.json`, `CHANGELOG.md`, commands, and `.claude/agent-memory/` paths in lockstep ([L43-L81]).

---

### 4. Sufficiency of Evidence & One Cheap Experiment

* **Sufficient:** Deleting Engine C (`emit-workflow.py`, `manifest.yaml`, `collect-results.py`) for single-agent builds is backed by a **10× cost** ($8.1 vs $87) and **2.8× wall-time** (17.5m vs 49m) gap that is immune to judge noise, plus A5 beating B across all 4 blind runs (94/99 vs 62/72). Deleting epics, `lessons.py`, `scorecard.py`, `triage-outcomes.py`, and unused workers is justified by 98 dogfood runs of near-zero usage.
* **Insufficient:**
  1. **Brownfield C-light vs C-full (75/78 vs 69/69):** A 7.5-point delta is inside the **±10 pt judge noise**, tested on n=1 small greenfield codebase written minutes earlier—not a legacy repo with hidden coupling where 1A `code-archaeologist` and `cochange.py` matter.
  2. **C-full's failure mode was spec drift** ([`docs/v4/salon-report.md`]: the spec itself dropped per-phone limits on move and kept no-show slots occupied). Checking code against the spec's acceptance table will not catch a spec that contradicts the user's prompt unless the reviewer grades against the raw prompt.
  3. **Prose-table parallelism without `validate-manifest.py` or `lane-guard.sh` (Rows 28, 30, 57):** Zero runs.
* **Demand one cheap experiment (~$15, ~30 min):** On a real multi-module brownfield repo (e.g., this repo), run one feature touching 2 coupled modules + 1 shared contract under **(a) 1-agent `light-flow.md` with 1A archaeology** vs **(b) 2-subagent prose-table parallel build without manifest validation or `lane-guard.sh`**. Measure deterministically (zero judge noise): out-of-lane write collisions, existing-suite regressions, and wall time. If prose-table parallelism collides or saves <20% wall time, remove parallel subagent instructions from v4 core and require worktrees whenever >1 writer runs.
