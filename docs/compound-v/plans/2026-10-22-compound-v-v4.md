# Compound V v4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the v3 orchestration engine with a standalone plugin `compound-v` 4.0.0 whose cycle is brainstorm → conditional pre-flights → plan → native build → verification with tree-bound receipts. It must beat A5 on the salon benchmark at ≤ $7 of Claude spend.

**Architecture:** The judgment lives in four prose skills: brainstorm, plan, build and verify. Everything that must not be self-reported lives in one small stdlib Python CLI, `scripts/compound-v.py` over the package `scripts/cvcore/`: snapshot, run record, receipts, scope, escalation, lanes, usage and HUD. Four bash hooks (prompt, stop, session, receipt-guard) and the band mod are thin readers of that CLI. Claude Code does the orchestration natively.

**Tech Stack:** Python 3.9+ stdlib (unittest), bash, git ≥ 2.30, a Claude Code mod in tsx (≥ 2.1.287), codex-cli 0.162+ (optional reviewer), and Playwright for web projects' browser checks (the project's dependency, not ours).

**Spec:** `docs/compound-v/specs/2026-10-22-compound-v-v4-design.md`. Pre-flights: `docs/compound-v/preflight/2026-10-22-v4-{archaeology,platform-audit,domain}.md`.

## Global Constraints

- Model policy: Opus by default, Sonnet for mechanical execution and lookups, **never Haiku** (also `claude plugin eval --judge-model sonnet`). Fable only by explicit choice.
- Python stdlib only, 3.9 floor; hooks in bash with `"shell": "bash"`. Every hook is registered `"<script>" || true`, has `timeout` ≤ 10 s, starts with `trap 'exit 0' EXIT`, and prints a decision only on success.
- Mutable state lives only in `docs/compound-v/` (project) or `~/.claude/compound-v/` (machine), never under `${CLAUDE_PLUGIN_ROOT}`.
- Enforcement fields (receipts, outcomes, scope verdicts, usage) are written by `scripts/compound-v.py` from real command results, never by the model.
- No unmeasured numbers in docs or output; dollar figures only from a dated price table.
- No personal data in logs. Command output tails stored in receipts are capped at 20 lines.
- Skills, not `commands/`: `skills/<name>/SKILL.md` gives `/compound-v:<name>`.
- New core size: `scripts/compound-v.py` + `scripts/cvcore/*.py` + `hooks/*.sh` + `hooks/run-band.tsx` ≤ 2500 lines (CI guard; target ~2k).
- Run stages, in order: `brainstorm, preflight, plan, build, verify, done`. Tiers: `light, full`. Outcomes: `verified, incomplete, failed` (or `null` while open). Steps: `tests, review, live, scope`.
- Required steps: full = `tests, review, live, scope`; light = `tests, scope`, plus `live` when the diff touches UI. At most 2 review rounds.

## Review Focus

1. **Two Claude sessions or two open runs in one repo.** The hooks must act on the run bound to *this* session (`sessions` list), not on the newest file. Tests are in Task 2 (`test_active_prefers_session_binding`) and Task 7 (`test_stop_ignores_other_sessions_run`).
2. **Not a git repo, no first commit, detached HEAD.** Every hook must exit 0 silently, and the CLI must exit 2 with one plain line. Tests are in Task 1 (`test_snapshot_requires_commit`) and Task 7 (`test_hooks_silent_outside_git`).
3. **Large transcripts or repos.** The Stop hook must return within its budget and mark usage `partial` rather than hang. Tests are in Task 5 (`test_measure_respects_deadline`) and Task 7 (`test_stop_hook_under_budget_with_big_transcript`).
4. **Paths with spaces, non-ASCII names (Bangla) or newlines.** The snapshot, scope check and checkout must agree on them, and a newline path is never exempt. Tests are in Task 1 (`test_snapshot_unicode_and_space_paths`) and Task 3 (`test_scope_unicode_paths`).
5. **A verified, closed run followed by manual edits.** Later stops must never be refused, and a new request starts a new run. The test is in Task 7 (`test_stop_after_done_never_blocks`).

---

## File structure

| Path | Responsibility |
|---|---|
| `scripts/compound-v.py` | Entry: puts its own dir on `sys.path`, `sys.dont_write_bytecode = True`, calls `cvcore.cli.main()` |
| `scripts/cvcore/gitio.py` | `git(repo, *args, env=None, input=None, check=True) -> bytes`, `repo_root(path) -> Path`, `GitError` |
| `scripts/cvcore/snapshot.py` | Canonical tree hash, ignored-env digest, materialized checkout |
| `scripts/cvcore/run.py` | Run record: create, load/save, active-run lookup, stages, plan block |
| `scripts/cvcore/scope.py` | Changed files vs base, glob match, symlink escape |
| `scripts/cvcore/escalate.py` | Diff content predicates → tier; prompt classifier |
| `scripts/cvcore/receipts.py` | Step runner, HMAC-signed receipts, waivers, review recording, status |
| `scripts/cvcore/review.py` | Codex executable review runner |
| `scripts/cvcore/usage.py` | Transcript token measurement, price table, cost |
| `scripts/cvcore/lanes.py` | Parallel writer worktrees: start / finish (scope + merge + tests) |
| `scripts/cvcore/hud.py` | Band JSON, one-line brief, co-change lookup |
| `scripts/cvcore/hooks.py` | `stop_hook(payload)`, `prompt_hook(payload)`, `guard_hook(payload)` decisions |
| `scripts/cvcore/cli.py` | argparse wiring of all subcommands |
| `scripts/prices.json` | `{source, checked, models: {id: {input, cache_write, cache_read, output}}}` USD per Mtok |
| `schemas/review-findings.schema.json` | Reviewer output shape (Codex `--output-schema` and Claude reviewer) |
| `hooks/{prompt,stop,session,guard}.sh`, `hooks/hooks.json`, `hooks/run-band.tsx` | Thin hook wrappers and the band |
| `skills/{brainstorm,plan,build,verify,init,onboard,pr-review}/` | The prose |
| `agents/{v-memory,code-archaeologist,doc-validator,domain-expert,reviewer}.md` | Subagents |
| `tests/core/test_*.py`, `tests/core/helpers.py`, `tests/hooks/test-*.sh` | Tests |

Carried as-is: `scripts/compound-v-run-with-timeout.py`, `scripts/lint-frontmatter.py` (edited), `scripts/compound-v-onboard.py` (decoupled), `skills/pr-review/`.

## Task → model

| Task | Model | Why |
|---|---|---|
| 0, 11 | Sonnet | git and file moves, deletions |
| 1–10, 12–14 | Opus | design-bearing code, prose, verification |

---

### Task 0: Freeze v3 on a `v3` branch

**Files:** none on `v4-design`. The pending change in `scripts/compound-v-emit-preflight.py` (greenfield `_NON_SOURCE_DIRS` fix plus its selftest fixture) moves to `v3`.

- [ ] **Step 1:** `git diff scripts/compound-v-emit-preflight.py > "$SCRATCH/greenfield.patch"`. Then create a worktree off main: `git worktree add ../superpowers-v-v3 -b v3 main`.
- [ ] **Step 2:** In `../superpowers-v-v3`, run `git apply "$SCRATCH/greenfield.patch"`, then `python3 scripts/compound-v-emit-preflight.py --selftest`. Expected: exit 0.
- [ ] **Step 3:** Commit on `v3`: `fix(preflight): docs/superpowers records never count as app source on greenfield`. No version bump and no push; pushing `v3` waits for Oleg at release (Task 14).
- [ ] **Step 4:** On `v4-design`, run `git checkout -- scripts/compound-v-emit-preflight.py`. Expected: `git status --short` shows only the moved spec and plan.

### Task 1: Snapshot and materialized checkout

**Files:** Create `scripts/compound-v.py`, `scripts/cvcore/__init__.py`, `gitio.py`, `snapshot.py`, `cli.py` (subcommands `snapshot`, `checkout`). Test: `tests/core/helpers.py`, `tests/core/test_snapshot.py`.

**Interfaces — Produces:**
- `helpers.make_repo(tmp: Path, files: dict[str, str|bytes] = {}, commit=True) -> Path` and `helpers.cli(repo, *args) -> subprocess.CompletedProcess`.
- `snapshot.EVIDENCE_EXCLUDES = ("docs/compound-v/runs",)`.
- `snapshot.tree(repo: Path) -> str`. This is the 40-hex tree id from a private `GIT_INDEX_FILE` in a temp dir, built with `git -c core.autocrlf=false -c core.fileMode=true -c core.excludesFile=/dev/null add -A -- . ':(exclude)docs/compound-v/runs'` and then `write-tree`. The user's index is never touched.
- `snapshot.ignored_env_digest(repo) -> str`. A sha256 over sorted `(path, sha256(content))` of ignored files whose basename matches `.env*`, `*.env` or `*.local.*` (files ≤ 1 MiB; larger ones by size+mtime). The literal `"none"` when there are none.
- `snapshot.materialize(repo, tree_id, dest: Path) -> str`. It runs `git archive <tree_id> | tar -x -C dest`, then re-hashes `dest` with a throwaway `--git-dir`, and raises `SnapshotMismatch` unless it equals `tree_id`. Returns `tree_id`.
- CLI: `compound-v.py snapshot [--repo R]` prints `{"tree": ..., "ignored_env": ...}`. `compound-v.py checkout --dest D` prints `{"tree": ..., "dest": ...}`. Exit 2 with one line on `GitError`.

- [ ] **Step 1: Write the failing tests** in `tests/core/test_snapshot.py`:
  - `test_untracked_file_changes_tree`: adding the untracked `new.txt` makes `tree()` change.
  - `test_deletion_and_mode_change_tree`: `git rm --cached`-free deletion of a tracked file changes the tree, and `chmod 755` changes it again.
  - `test_user_index_untouched`: `git diff --cached --name-only` is byte-identical before and after `tree()`.
  - `test_evidence_dir_excluded`: writing `docs/compound-v/runs/x.json` leaves `tree()` unchanged, while writing `docs/compound-v/plans/p.md` changes it.
  - `test_crlf_config_independent`: `tree()` with `git config core.autocrlf true` in the repo equals the tree without it.
  - `test_ignored_env_digest`: with `.gitignore` = `.env`, editing `.env` changes `ignored_env_digest` and leaves `tree()` unchanged.
  - `test_materialize_roundtrip_and_tamper`: materializing returns the same id; a materialize where a test hook flips one byte in `dest` before re-hash raises `SnapshotMismatch` (inject via the `_after_extract` callback parameter).
  - `test_snapshot_unicode_and_space_paths`: files `a b.txt` and `বুকিং.txt` survive materialize with the same id.
  - `test_snapshot_requires_commit`: in `git init` with no commit, the CLI exits 2 and its stderr contains `no commit`.
- [ ] **Step 2:** Run `python3 -m unittest discover -s tests/core -p 'test_snapshot.py' -v`. Expected: FAIL (`ModuleNotFoundError: cvcore`).
- [ ] **Step 3:** Implement the interfaces above. `git()` sets `LC_ALL=C` and `GIT_OPTIONAL_LOCKS=0`, and passes paths with `-z` wherever it lists them.
- [ ] **Step 4:** Rerun. Expected: 9 tests OK.
- [ ] **Step 5:** Commit: `feat(core): canonical working-tree snapshot and verified checkout`.

### Task 2: Run record and plan block

**Files:** Create `scripts/cvcore/run.py`; extend `cli.py` with `run start|stage|plan|show|bind`. Test: `tests/core/test_run.py`.

**Interfaces — Consumes:** `snapshot.tree`, `gitio.git`. **Produces:**
- `run.RUNS = "docs/compound-v/runs"`, `run.STAGES`, `run.TIERS`.
- `run.start(repo, *, tier, request: str, spec: str|None = None, base: str = "HEAD", change_set: list[str] = [], session_id: str|None = None) -> dict`. It writes `<RUNS>/<id>.json`, where id is `YYYYMMDD-HHMMSS-<slug of request, ≤24 chars>`. The stage is `brainstorm` for full and `build` for light. `base_commit` is the resolved sha. It also sets `review_round: 0`, `receipts: {}`, `waivers: {}`, `stop_refusals: []`, `sessions: [session_id] if given`, `usage: {}`, `usage_by_stage: {}`, `escalations: []`, `lane_state: {}`, `external: {}`, `outcome: null`, and `test_cmd`, `budget_usd` and `reviewer` read from `.claude/compound-v.json` when present.
- `run.load(repo, run_id) -> dict`. `run.save(repo, rec) -> None` writes atomically (temp + `os.replace`).
- `run.active(repo, session_id: str|None = None) -> dict|None`. It returns the newest open run (`outcome is null`) whose `sessions` contains `session_id`, else the newest open run with an empty `sessions`, else `None`. It never returns a run bound only to other sessions.
- `run.bind(repo, rec, session_id) -> dict` appends the session if absent.
- `run.set_stage(repo, rec, stage) -> dict`. Only forward moves are allowed, plus `verify → build` for fix rounds; anything else raises `RunError`.
- `run.attach_plan(repo, rec, plan_path) -> dict`. It parses the single fenced block tagged `compound-v-plan` (JSON) in the plan. Required keys are `test_cmd: str`, `change_set: [glob]` and `is_web: bool`, plus `live_cmd: str` (a browser test when `is_web`, the main-flow run otherwise). Optional keys: `setup_cmd`, `lanes: {task: [glob]}`, `budget_usd` (default 7), `budget_split` (default `{"before_build": 0.25, "build": 0.45, "verify": 0.30}`; verification's share is reserved, so build may spend only its own share), `test_globs` (default `["**/test*/**", "**/*test*.*", "**/*.spec.*"]`) and `timeout_s` (default 900). It sets `acceptance_rev` = sha256 of the text from the `## Acceptance` heading to the next `## ` heading, and `test_files` = `{path: sha256}` for the files matching `test_globs` at attach time. A missing key or a missing acceptance section raises `RunError` naming it.
- CLI: `run start --tier T --request-file F [--spec S] [--base B] [--change-set G]...`, `run stage --to S`, `run plan --plan P`, `run show [--id]`, `run bind --session S`. All print the record JSON.

- [ ] **Step 1: Write the failing tests:**
  - `test_start_full_and_light_stages`: full gives `stage == "brainstorm"`, light gives `"build"`, and `base_commit` is the HEAD sha.
  - `test_stage_forward_only`: `brainstorm → plan` is allowed (skipping is fine), `plan → brainstorm` raises `RunError`, and `verify → build` is allowed.
  - `test_attach_plan_parses_block_and_acceptance_rev`: editing a line inside `## Acceptance` changes `acceptance_rev`; editing outside it does not.
  - `test_attach_plan_missing_key`: without `live_cmd`, the message contains `live_cmd`.
  - `test_active_prefers_session_binding`: runs A (sessions `[s1]`) and B (sessions `[s2]`, newer). `active(repo, "s1")` is A; `active(repo, "s3")` is None; a run C with no sessions is returned for `"s3"`.
  - `test_closed_run_not_active`: `outcome = "verified"` gives None.
- [ ] **Step 2:** Run `python3 -m unittest tests/core/test_run.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun. Expected: 6 OK.
- [ ] **Step 5:** Commit: `feat(core): run record with stages, session binding and plan block`.

### Task 3: Scope check and escalation

**Files:** Create `scripts/cvcore/scope.py`, `scripts/cvcore/escalate.py`; CLI `scope`, `escalate`, `classify-request`. Test: `tests/core/test_scope.py`, `tests/core/test_escalate.py`.

**Interfaces — Produces:**
- `scope.changed(repo, base) -> list[str]`. The union of `git diff --name-only -z base` (the working tree vs base, renames as both sides) and `git ls-files --others --exclude-standard -z`, minus `docs/compound-v/**`. Gitignored files are out of scope, the same as for the snapshot.
- `scope.matches(path, globs) -> bool`. `**` spans directories, `*` stays within one segment, and the match is exact otherwise. A path containing `\n` never matches.
- `scope.check(repo, base, allow: list[str]) -> {"verdict": "pass"|"blocked", "changed": [...], "violations": [...]}`. A changed path that is a symlink resolving outside the repo is a violation even when it matches.
- `escalate.PREDICATES: list[tuple[str, re.Pattern]]`. Applied to **added lines** of `git diff -U0 base` plus the full content of untracked text files. The names are `auth` (password|passwd|login|logout|session|jwt|bearer|oauth|csrf|cookie), `payments` (payment|stripe|paypal|invoice|card_number|iban|checkout), `personal_data` (email|phone|address|birth|passport|ssn|gdpr|erase|retention), `endpoint` (Express/Koa `\.(get|post|put|patch|delete)\(\s*['"]/`, Flask/FastAPI `@\w+\.(route|get|post|put|delete)\(`, Django `path\(`, Next `export (async )?function (GET|POST|PUT|PATCH|DELETE)`, Rails `^\s*(get|post|resources)\s`), `form` (`<form\b`, `method=["']post`, `<input\b`), `schema` (`CREATE TABLE|ALTER TABLE|migration`), `crypto` (hash|bcrypt|argon|hmac|encrypt|secret) and `upload` (multipart|upload). Case-insensitive.
- `escalate.UI_PATHS` globs (`**/*.html`, `**/*.css`, `**/*.{tsx,jsx,vue,svelte}`, `**/templates/**`, `**/views/**`, `**/pages/**`, `**/public/**`).
- `escalate.classify_diff(repo, base) -> {"tier": "light"|"full", "reasons": [str], "touches_ui": bool}`. Full when any predicate hits, when more than 300 changed lines, or on binary/unreadable changes (reason `unclassifiable`).
- `escalate.classify_request(text: str) -> "light"|"full"|None`. Light when `len ≤ 300`, the text matches `typo|опечат|rename|переимен|wording|copy|текст|readme|comment|коммент|bump|version|config value` and no predicate word hits. Full when any predicate word, or `add|implement|build|create|feature|добав|сделай|реализ`, hits. None otherwise; callers treat None as full.

- [ ] **Step 1: Write the failing tests:**
  - `test_scope_pass_and_block`: allow `src/**` with a changed `src/a.js` passes; a changed `README.md` is blocked with `violations == ["README.md"]`.
  - `test_scope_untracked_counted_ignored_not`: an untracked `x.txt` is a violation; an ignored `node_modules/a.js` is not.
  - `test_scope_symlink_escape`: `src/l -> /etc/hosts` is a violation.
  - `test_scope_unicode_paths`: allow `docs/**`, changed `docs/বুকিং নোট.md` passes.
  - `test_scope_evidence_exempt`: a changed `docs/compound-v/runs/r.json` never appears in `changed`.
  - `test_escalate_auth_in_innocent_file`: added `utils/helpers.js` with `res.cookie('sid', token)` gives full with `auth` in the reasons.
  - `test_escalate_copy_change_light`: a one-word change in `README.md` gives light with `touches_ui == False`.
  - `test_escalate_ui_flag`: a changed `public/index.html` text-only gives light with `touches_ui == True`.
  - `test_escalate_binary_full`: a changed `logo.png` gives full with `unclassifiable`.
  - `test_classify_request`: `"fix typo in README"` gives light; `"add login"` gives full; `"hmm"` gives None; `"исправь опечатку в README"` gives light.
- [ ] **Step 2:** Run both files. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun. Expected: 10 OK.
- [ ] **Step 5:** Commit: `feat(core): scope check and content-based escalation`.

### Task 4: Receipts, review recording, waivers, status, Codex review

**Files:** Create `scripts/cvcore/receipts.py`, `scripts/cvcore/review.py`, `schemas/review-findings.schema.json`, `skills/verify/review-prompt.md` (the reviewer prompt template, shared by Codex and the Claude reviewer). CLI `receipt tests|live|scope`, `review codex`, `review record`, `waive`, `status`. Test: `tests/core/test_receipts.py`, `tests/core/test_review.py`.

**Interfaces — Consumes:** `snapshot.tree`, `snapshot.ignored_env_digest`, `snapshot.materialize`, `run.*`, `scope.check`, `escalate.classify_diff`, and `scripts/compound-v-run-with-timeout.py` (subprocess, exit 124 = timeout). **Produces:**
- `receipts.KEY_PATH = ~/.claude/compound-v/receipt.key`: 32 random bytes, created 0600 on first use.
- `receipts.required(rec, repo) -> list[str]`. For light: `["tests", "scope"]`, plus `"live"` if `classify_diff(...).touches_ui`. For full: all four. If `classify_diff` says full while the run is light, the run is escalated: tier becomes full, `receipts` is cleared, and `escalations` gets `{at, reasons}`.
- `receipts.run_step(repo, rec, step: "tests"|"live"|"scope") -> dict`. tests/live run `test_cmd`/`live_cmd` through run-with-timeout (`timeout_s`, cwd = repo); scope runs `scope.check(base_commit, change_set ∪ lanes)`. It writes `rec["receipts"][step] = {step, result: "pass"|"fail"|"error", exit, cmd, snapshot, ignored_env, acceptance_rev, tier, at, duration_s, tail}` plus `mac` = HMAC-SHA256(key, canonical JSON without `mac`). The tests step also compares `test_files`: any plan-time test file now missing gives `result: "fail"` and `reason: "tests removed: …"`. A step command that is missing for a required step gives `result: "error"` and `reason: "no live_cmd"`.
- `receipts.record_review(repo, rec, findings_path, reviewer: "codex"|"claude") -> dict`. It validates the findings JSON against the schema's required keys (`snapshot`, `findings[] {id, severity: blocker|high|medium|low, title, evidence, reproduce}`, `summary`). Then:
  - `snapshot` must equal the current `tree()`, else `result: "error"` (`reason: "stale review"`).
  - If `review_round` is already 2, it raises `RunError("review rounds exhausted")`. A second review that still has blocker or high findings makes the run outcome incomplete; there is no third review (spec §4.5).
  - Otherwise `review_round` goes up by 1. The result is pass iff no blocker/high findings; findings are stored in full.
- `receipts.waive(repo, rec, step, reason: str) -> dict` records `{reason, at, by: "user-in-chat (not machine-verifiable)"}`. Allowed only for `live`.
- `receipts.status(repo, rec) -> {"outcome": "verified"|"incomplete"|"failed"|"pending", "missing": [], "stale": [], "failed": [], "waived": [], "budget": {"limit": x, "spent": y|null, "exceeded": bool}}`. A receipt is stale if its `snapshot`, `ignored_env`, `acceptance_rev` or `tier` differs from the current state, or if its `mac` does not verify. "verified" requires every required step to have a pass receipt that is current (or a waiver for `live`). "failed" means some current receipt has a fail result and no round is left to fix it. "incomplete" covers a set outcome, an exceeded budget, rounds exhausted with findings open, or an `error` receipt. "pending" covers everything else.
- Findings files always live at `docs/compound-v/runs/<id>-review-<n>.json`, which is evidence-excluded. Anywhere else would change the snapshot and stale the receipts that the review itself produced.
- `review.codex_plan(repo, plan_path, out_path, *, model="gpt-6-astra", timeout_s=900) -> Path` is the optional plan review. It runs with `-s read-only`, against the same schema, and is advisory only: it writes no receipt.
- `review.codex(repo, rec, out_path, *, model="gpt-6-astra", timeout_s=1200) -> Path`. It materializes the snapshot into a temp dir, runs `setup_cmd` there if set (our process, network allowed), then runs `codex exec -s workspace-write -C <dest> --skip-git-repo-check --ephemeral --output-schema <schema> -o <out_path> -c sandbox_workspace_write.network_access=false -m <model> -` with the filled `review-prompt.md` on stdin, under run-with-timeout. A non-zero rc or an unparsable output raises `ReviewError` (never a pass from a stale file). The out JSON gets `snapshot` set to the materialized tree before `record_review` reads it.
- CLI: `status` exits 0 when verified, 3 when pending, 4 when incomplete, 5 when failed, and prints the status JSON.

- [ ] **Step 1: Write the failing tests** (fixture: a repo plus a plan whose `test_cmd` is `python3 -c "import sys; sys.exit(0)"` and whose `live_cmd` is controllable through an env file):
  - `test_pass_receipts_verify_full`: run tests, live and scope, record a clean review; the outcome is `verified`.
  - `test_edit_after_receipt_goes_stale`: after all pass, appending to `src/a.js` puts every receipt in `stale` and makes the outcome `pending`.
  - `test_hand_written_receipt_rejected`: editing `receipts.tests.result` in the JSON from fail to pass makes `stale` contain `tests` (MAC failure).
  - `test_failed_browser_form_refused`: a `live_cmd` exiting 1 gives `result: "fail"` and an outcome that is not `verified`.
  - `test_skipped_review_refused`: full with tests, live and scope passing but no review gives `missing == ["review"]`.
  - `test_review_rounds_bounded`: two recorded reviews with high findings, then a third raises `RunError`; status is `incomplete`, and fixing the tree afterwards still never yields `verified`.
  - `test_second_review_pass_verifies`: review 1 high, then a fix, then review 2 clean, plus current tests, live and scope, gives `verified`.
  - `test_stale_review_rejected`: a findings `snapshot` different from the current tree gives `result: "error"` and `stale review`.
  - `test_tests_removed_flagged`: deleting a plan-time `tests/test_a.py` makes the tests receipt `fail` with `tests removed`.
  - `test_light_escalates_on_auth_diff`: a light run with an added `login()` becomes full when `required()` is computed, and its receipts are cleared.
  - `test_live_waiver`: an `is_web` run with `waive live` and everything else passing is `verified`, with `waived == ["live"]`.
  - `test_ignored_env_change_stales`: editing an ignored `.env` makes receipts stale.
  - `test_codex_failure_is_error` (`test_review.py`): with a fake `codex` on `PATH` that writes a valid-looking file and exits 124, `review.codex` raises `ReviewError`.
  - `test_codex_checkout_has_untracked` (`test_review.py`): a fake `codex` that lists `-C` into the out file includes the untracked `src/new.js`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Write `review-prompt.md` with the slots `{request}`, `{acceptance}`, `{checklists}`, `{snapshot}` and `{setup_cmd}`. It says: judge against the original request, not the plan; run the app and the tests; every finding needs `reproduce` (a command) or `evidence` (file:line); do not edit source files; write only the findings JSON.
- [ ] **Step 4:** Rerun. Expected: 13 OK.
- [ ] **Step 5:** Commit: `feat(core): signed tree-bound receipts, bounded review, outcomes`.

### Task 5: Usage, prices, HUD, co-change

**Files:** Create `scripts/cvcore/usage.py`, `scripts/cvcore/hud.py`, `scripts/prices.json`; CLI `usage`, `hud [--brief]`, `cochange --path P...`. Test: `tests/core/test_usage.py`, `tests/core/test_hud.py`.

**Interfaces — Produces:**
- `usage.transcripts_for(main: Path) -> list[Path]` returns `[main] + sorted(main.parent / main.stem / "subagents" / "*.jsonl")`, following the salon `session-usage.py` method.
- `usage.measure(paths, deadline: float) -> {"per_model": {model: {"input", "cache_write", "cache_read", "output"}}, "messages": n, "partial": bool}`. It counts each assistant `message.id` once across files and skips `<synthetic>` and lines without `usage`. Past the deadline it sets `partial: true` and returns what it has.
- `usage.cost_usd(per_model, prices) -> float|None`. Returns None if any model with tokens has no price.
- `usage.record(repo, rec, session_id, transcript_path, deadline) -> dict` stores `rec["usage"][session_id]` and the run total, and adds the delta since the last record to `rec["usage_by_stage"][<stage>]` (`brainstorm`, `preflight` and `plan` count as `before_build`). `receipts.status()["budget"]` gains `{"by_stage": {...}, "stage_exceeded": [stage]}`: a stage over `budget_split[stage] × budget_usd` is listed, and a run total over `budget_usd` makes the outcome incomplete. With no price, `spent` is null and the budget is reported as "unknown", never as passed.
- `review.codex` also appends `{duration_s, at}` to `rec["external"]["codex"]`. Codex is recorded, not counted in the Claude budget. `prices.json` is filled from the official Anthropic pricing page with `source` and `checked`; a model whose price is not on that page is left out. **Do not type a price from memory.**
- `hud.band(repo, session_id=None) -> dict` returns `{run, stage, tier, steps: {step: "pass"|"fail"|"stale"|"missing"|"waived"}, review_round, outcome, tokens, cost_usd}`, or `{}` with no active run.
- `hud.brief(repo, session_id=None) -> str`, for example `Compound V run 20261022-…-salon: stage verify (full); missing review, live; next: /compound-v:verify`, or `""`.
- `hud.cochange(repo, paths, max_commits=500, top=10) -> list[{"path", "count"}]` comes from `git log --name-only -z -n max_commits`.

- [ ] **Step 1: Write the failing tests:**
  - `test_measure_dedupes_across_files`: the same `message.id` in the main and subagent files is counted once.
  - `test_measure_skips_synthetic`.
  - `test_measure_respects_deadline`: a 200k-line file with `deadline = now` gives `partial == True` within 1 s.
  - `test_cost_none_when_price_missing`.
  - `test_usage_by_stage_and_budget`: records at stage `plan` then `build` split the deltas; build spend over 0.45 × budget lists `build` in `stage_exceeded`; total over budget → status outcome `incomplete`.
  - `test_brief_names_missing_steps`.
  - `test_band_empty_without_run`.
  - `test_cochange_counts`: three commits touching `a` and `b` together give `cochange([a])[0] == {"path": "b", "count": 3}`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Fetch the pricing page (WebFetch), fill `prices.json` for the models it lists, and record its URL and today's date.
- [ ] **Step 4:** Rerun. Expected: 7 OK.
- [ ] **Step 5:** Commit: `feat(core): transcript usage with dated prices, hud and co-change`.

### Task 6: Lanes for parallel writers

**Files:** Create `scripts/cvcore/lanes.py`; CLI `lane start --task T`, `lane finish --task T`. Test: `tests/core/test_lanes.py`.

**Interfaces — Consumes:** `run.*`, `scope.check`, and the run's `test_cmd`. **Produces:**
- `lanes.start(repo, rec, task) -> Path`. It requires `task in rec["lanes"]` and runs `git worktree add -b cv/<run>/<task> .claude/worktrees/cv-<run>-<task> HEAD`. Starting from the current HEAD is deliberate: the native `isolation: worktree` branches from the default branch. It records `rec["lane_state"][task] = {base, path, status: "open"}` and returns the path.
- `lanes.finish(repo, rec, task) -> {"status": "merged"|"refused", "reason": str, "violations": [...]}`. It refuses, without touching the main tree:
  - when the worktree is dirty (`interrupted: uncommitted changes`) or has no commits beyond base (`no commits`);
  - when `scope.check(base, lanes[task])` inside the worktree is blocked.
  Otherwise it runs `git merge --no-ff --no-commit cv/<run>/<task>`. On a conflict it runs `git merge --abort` and refuses with `conflict`. It then runs `test_cmd` on the merged tree: on failure, `git merge --abort` and refuse with `tests failed`; on success it commits `merge lane <task>`. Never `reset --hard`.

- [ ] **Step 1: Write the failing tests:**
  - `test_lane_from_head`: an uncommitted-free HEAD on a feature branch (not main) is the base of the new worktree.
  - `test_write_outside_lane_refused`: lane `src/a/**` committing `src/b/x.js` is `refused` with violations `["src/b/x.js"]`, and main's HEAD is unchanged.
  - `test_interrupted_worker_refused`: a dirty worktree is refused (`interrupted`).
  - `test_tests_fail_aborts_merge`: `test_cmd = "false"` is refused (`tests failed`), and `git status --porcelain` on main is empty.
  - `test_clean_lane_merges`.
  - `test_dirty_main_refused`: uncommitted user changes in the main tree give `refused` (`main tree dirty`), with the user's changes untouched.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun. Expected: 5 OK.
- [ ] **Step 5:** Commit: `feat(core): lane worktrees from HEAD with scope, merge and test gate`.

### Task 7: Hooks

**Files:** Create `scripts/cvcore/hooks.py`, `hooks/prompt.sh`, `hooks/stop.sh`, `hooks/session.sh`, `hooks/guard.sh`; replace `hooks/hooks.json`; extend `cli.py` with `hook <stop|prompt|session|guard>`. Test: `tests/core/test_hooks.py`, `tests/hooks/test-hooks.sh`.

**Interfaces — Consumes:** `run.active`, `run.bind`, `receipts.status`, `receipts.required`, `usage.record`, `hud.brief`, `escalate.classify_request`. **Produces:**
- `hooks.stop_hook(payload: dict, repo: Path, budget_s=6.0) -> dict|None`:
  1. If `hook_event_name != "Stop"` → None.
  2. Find `rec = run.active(repo, session_id)`. If it is None: when `state_dir/change-<session>` exists (set by `prompt_hook`) and no `bypass-refused-<session>` marker exists yet, write that marker and block with "This session got a change request but no Compound V run was started. Start one with the compound-v skills, or say that no files changed and stop again." Otherwise return None.
  3. Bind the session, then `usage.record` with the remaining budget.
  4. `stop_hook_active` true → None.
  5. Stage not in (`build`, `verify`) → None.
  6. `s = status(...)`. Verified → set `outcome = "verified"`, `stage = "done"`, save, None.
  7. Otherwise, with key = `f"{snapshot}:{stage}"`: if key ∉ `stop_refusals`, append it and return `{"decision": "block", "reason": <missing/stale/failed list + "Continue with /compound-v:verify, or, if you are waiting on the user or a step cannot run, say so and stop again — the run will be recorded incomplete.">}`.
  8. Else set `outcome = "failed" if s["failed"] else "incomplete"` and return None.
  Any exception → None.
- `hooks.prompt_hook(payload, repo, state_dir: Path) -> str|None`. It returns the additionalContext text, or None. On every call it first binds the newest **unbound** open run to this `session_id` (`run.bind`); skills cannot see the session id, so the hook does the binding. When it classifies a change request (light or full) and no open run is bound, it writes `state_dir/change-<session>`. It appends one line per decision to `docs/compound-v/runs/triage.log` (evidence-excluded): `{at, session, tier, reason, prompt_chars}`, never the prompt text. It ports v3's filters: slash command, a short question (≤ 200 chars ending `?`), a short read instruction (≤ 80 chars starting `read|show me|explain|summarize|look at|cat`), and the closed greeting list from `triage-prompt-nudge.sh:578`. It keeps v3's per-session markers and counters under `state_dir` (`_MAX_ATTEMPTS = 3` nudges per session). An open run for this session gets `brief()` instead of a nudge. Otherwise the tier comes from `classify_request`, with None meaning full:
  - full → "Compound V: this is a change request (full). Start with the compound-v:brainstorm skill."
  - light → "Compound V: small change (light). Make it, then run the compound-v:verify skill."
- `hooks.guard_hook(payload) -> dict|None`. For `Write|Edit|MultiEdit|NotebookEdit` whose `file_path` resolves under `docs/compound-v/runs/`, it returns `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "Run records are written by scripts/compound-v.py only."}}`.
- Shell wrappers: each script starts with `trap 'exit 0' EXIT`. It resolves `python3`, runs `python3 -I -B "$CLAUDE_PLUGIN_ROOT/scripts/compound-v.py" hook <stop|prompt|session|guard>` with the payload on stdin, and prints the output only when the exit is 0.
  - `prompt.sh` first checks set-up (a `.claude/compound-v.json` in `$CLAUDE_PROJECT_DIR`). When it is missing, it prints the one-time `Compound V is installed but not set up here — run /compound-v:init.` (marker per session) and stops.
  - `session.sh` (SessionStart, matcher `startup|resume|clear|compact`) prints `brief()` and, if `docs/compound-v/architecture/.onboard-manifest.json` exists, the onboard staleness line (`compound-v-onboard.py staleness`).
- `hooks.json`: Stop → stop.sh (timeout 10), UserPromptSubmit → prompt.sh (10), SessionStart → session.sh (10), PreToolUse `Write|Edit|MultiEdit|NotebookEdit` → guard.sh (5), and `"modules": ["./run-band.tsx"]`. Each is `"<path>" || true`, with `"shell": "bash"`.

- [ ] **Step 1: Write the failing tests** (`test_hooks.py` calls the functions directly; `test-hooks.sh` drives the wrappers with JSON on stdin):
  - `test_stop_blocks_once_then_incomplete`: the first stop blocks, the second stop on the same snapshot returns None, and `outcome == "incomplete"`.
  - `test_stop_reblocks_after_new_edit`: after an edit, the new snapshot blocks once more.
  - `test_stop_hook_active_never_blocks`.
  - `test_stop_verified_closes_run`.
  - `test_stop_after_done_never_blocks`: a verified, done run plus an edit plus a stop gives None.
  - `test_stop_ignores_other_sessions_run`.
  - `test_stop_brainstorm_stage_never_blocks`.
  - `test_stop_hook_under_budget_with_big_transcript`: a 200k-line transcript returns within 7 s.
  - `test_stop_blocks_once_when_change_request_but_no_run`: `prompt_hook("add a booking page")` with no run, then a stop, blocks once; the second stop gives None.
  - `test_prompt_binds_unbound_run`: a run started without a session gets the payload's `session_id` on the next prompt.
  - `test_triage_log_has_no_prompt_text`.
  - `test_prompt_filters`: `"hi"`, `"/compound-v:init"` and `"what is this?"` give None; `"add a booking page"` gives the full text; `"fix typo in README"` gives light.
  - `test_guard_denies_run_record_edit`, plus `test_guard_allows_other_paths`.
  - `test-hooks.sh`: `test_hooks_silent_outside_git` (each wrapper in a non-git temp dir exits 0 with empty stdout); `test_broken_python_fails_open` (with `PATH` holding a `python3` that exits 1, stop.sh exits 0 with empty stdout); `test_not_set_up_notice_once`.
- [ ] **Step 2:** Run `python3 -m unittest tests/core/test_hooks.py -v && bash tests/hooks/test-hooks.sh`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun. Expected: all OK.
- [ ] **Step 5:** Commit: `feat(hooks): refuse-once stop, prompt engagement, session brief, receipt guard`.

### Task 8: Band

**Files:** Rewrite `hooks/run-band.tsx`, `hooks/run-band.test.tsx`; create `tests/hooks/test-band.sh` (runs `claude plugin validate .` + `claude plugin test .`, skips with a notice when `claude` is absent); `types/index.d.ts` (state key `plugin: "compound-v"`).

**Interfaces — Consumes:** `compound-v.py hud` (JSON from `hud.band`).

The band has one header line: `V <run> · <stage> (<tier>) · tests ● review ○ live ✕ scope ● · round 1/2 · <tokens> tok · $<cost or ?>`. A second line appears only with an outcome or waivers. The quota footer stays as is (`$.session.usage().rateLimits` diff per run), labelled "account quota". It polls `hud` every 5 s only while the mtime of `docs/compound-v/runs` moved, and every 30 s otherwise, and draws nothing without a run. Palette and marks are the same as v3 (● pass, ○ missing, ◐ stale, ✕ fail, ◇ waived).

- [ ] **Step 1:** Write `run-band.test.tsx` cases: `renders nothing without a run`, `shows missing steps`, `shows ? when cost is null`, and `quota footer labelled account quota`.
- [ ] **Step 2:** Run `claude plugin test .`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `claude plugin test . && claude plugin validate .`. Expected: pass.
- [ ] **Step 5:** Commit: `feat(band): cycle stage, receipts and run cost from the run record`.

### Task 9: Cycle skills and agents

**Files:** Create `skills/brainstorm/SKILL.md`, `skills/brainstorm/territory.md`, `skills/plan/SKILL.md`, `skills/plan/checklists.md` (from `docs/v4/light-flow.md` §1–2, adapted), `skills/build/SKILL.md`, `skills/verify/SKILL.md`, `agents/v-memory.md`, `agents/reviewer.md`; rewrite `agents/{code-archaeologist,doc-validator,domain-expert}.md`; edit `scripts/lint-frontmatter.py`. Test: `tests/hooks/test-skills.sh`.

Content decisions, each one a requirement for the prose:
- **brainstorm:**
  - Open with one line offering to skip the questions, then one open question; one question per message after that.
  - Cover `territory.md` as ground, not a script: product and users, data lifecycle (create / change / retire with history / delete, operator changes without a developer), jurisdiction + data + deployment, security and every form, operations, edge cases.
  - For work bigger than a small change, ask "how deep" (quick / standard / thorough). Depth adds pre-flights and checks and never removes the tier minimum.
  - Before the first question, dispatch `compound-v:v-memory` (Sonnet, read-only) over `docs/compound-v/` and show its hits as evidence.
  - Write `docs/compound-v/specs/YYYY-MM-DD-<topic>.md`, run `compound-v.py run start --tier full --request-file <tmp with the user's original words> --spec <path>`, and get the user's approval of the spec before going on.
  - Then `run stage --to preflight` and dispatch, in one message: domain-expert always (≤ 4 searches); code-archaeologist when `git ls-files` has source outside `docs/`, `.claude/` and images; doc-validator when the spec names a dependency. Each writes `docs/compound-v/preflight/<date>-<topic>-<kind>.md`.
- **plan:**
  - Write `docs/compound-v/plans/<date>-<topic>.md` with `## Acceptance` (rows: behaviour → check), `## Tasks`, `## Task → model`, and `## Lanes` only when parallel. Apply `checklists.md`, answering every item "applies / n.a. + why".
  - End with the fenced `compound-v-plan` JSON block (keys as in Task 2). For web projects, `live_cmd` is a real-browser test (Playwright Test against the running app), and the plan includes that test as a task.
  - Run `compound-v.py run plan --plan <path>` and fix any `RunError`, then `run stage --to build`.
  - Optional plan review: for a high-stakes plan with Codex installed, offer `compound-v.py review codex-plan --plan <path>`. It is advisory, and its findings are arbitrated in the plan.
- **build:**
  - One agent by default, with tests written alongside the code (negative paths, state transitions, persisted state, missing config).
  - Parallel only when the plan has `## Lanes`: for each task, `compound-v.py lane start`, then a native subagent with `model` from the table, working in that path and committing there; then `lane finish`. A refusal is fixed or reported, never forced.
  - At each task boundary, read the `status` budget. If `build` is in `stage_exceeded`, stop adding scope, finish the current task and go to verify: verification's share is reserved.
  - Then `run stage --to verify` and invoke verify.
- **verify:**
  - The order is `receipt tests`, `receipt live` (if required), `receipt scope`, then review.
  - Review: when `reviewer` = codex, `review codex`. Otherwise run `checkout --dest <tmp>` and dispatch `compound-v:reviewer` (Opus) with that path, `review-prompt.md` filled and the findings path; then `review record`.
  - On a failed first review: `run stage --to build`, fix, re-run tests, live and scope, then do the second review. If the second review still fails, report incomplete with its findings. Never a third review, and never "fixed" without a review.
  - Finish with `status` and report the outcome, the missing/failed steps, waivers and usage. Say "done" only when the outcome is verified.
  - When no browser can run, ask the user whether to waive; only on their yes, `waive live --reason "<their words>"`.
  - A light run with no run record starts one: `run start --tier light --request-file … --change-set <globs of the intended files>`.
- **agents:** `v-memory` (the V-memory layer: grep + read over `docs/compound-v/`, no index), `code-archaeologist`, `doc-validator` and `domain-expert` are `model: sonnet` with `maxTurns: 25` and no `memory`. `reviewer` is `model: opus` with `maxTurns: 60`; it may run commands but edits nothing outside its checkout and writes only the findings file. Delete each agent's Step 0 V-memory recall and the `superpowers-v` cache lookups.
- **lint-frontmatter.py:** `SONNET_ELIGIBLE_AGENTS = {"v-memory", "code-archaeologist", "doc-validator", "domain-expert"}`, `MEMORYLESS_AGENTS` = all agents. Every other agent must be `model: opus`. Haiku stays rejected everywhere.

- [ ] **Step 1:** Write `tests/hooks/test-skills.sh`. It asserts:
  - each of the four skills exists with `name` + `description`;
  - `brainstorm` mentions `territory.md`, `run start` and `how deep`;
  - `plan` mentions `compound-v-plan` and `## Acceptance`;
  - `verify` mentions `review record`, `waive live` and `status`;
  - `python3 scripts/lint-frontmatter.py .` exits 0;
  - `grep -ri haiku agents skills` matches nothing except a policy line.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Write the skills and agents. Keep each `SKILL.md` ≤ 150 lines; the detail goes in the sibling files.
- [ ] **Step 4:** Run the test and `claude plugin validate .`. Expected: pass.
- [ ] **Step 5:** Commit: `feat(skills): brainstorm, plan, build, verify and the five agents`.

### Task 10: init, onboard, pr-review

**Files:** Create `skills/init/SKILL.md`; move `skills/compound-v/onboarding.md` → `skills/onboard/SKILL.md` (edited); keep `skills/pr-review/` (drop `commands/v-pr-review.md`); edit `scripts/compound-v-onboard.py`. Test: adapt `tests/test-onboard-rules.sh` → `tests/hooks/test-onboard.sh`.

- **init** probes:
  - a git repo with a first commit, and `python3 ≥ 3.9`;
  - `codex --version` (→ `reviewer: codex|claude`);
  - a browser runner: `npx --no-install playwright --version`, or a Playwright/Chrome DevTools MCP in `claude mcp list`. When none is found, it offers `claude mcp add playwright npx @playwright/mcp@0.0.83 -- --headless` and says Playwright Test will be added per project.
  - Superpowers enabled (`claude plugin list`): if so, it offers `{"enabledPlugins": {"superpowers@claude-plugins-official": false}}` in `.claude/settings.json`.
  - It writes `.claude/compound-v.json` = `{version: 4, stance: "standard"|"cost-aware", default_tier: "full", reviewer, test_cmd (detected from package.json/pyproject/Makefile, confirmed by the user), budget_usd: 7, models: {"build": "opus", "mechanical": "sonnet", "review": "opus"}}`.
  - Every config write is shown as a diff and confirmed. `models` (old `/v:models`) folds into init; `adr` is not carried into 4.0.
- **onboard:**
  - Replace the module-load import of `compound-v-memory.py` (`compound-v-onboard.py:6-9`) with local `SECRET_RE`, `PEM_RE` and `file_sha` (copied verbatim from `compound-v-memory.py`).
  - Delete the `draft-taxonomy` subcommand and its churn call, and the `_mini_yaml` soft import.
  - Change output paths `docs/superpowers/architecture` → `docs/compound-v/architecture`; Step 9's `/v:memory-refresh` is removed.
- **pr-review:** replace `docs/superpowers/specs` with `docs/compound-v/specs` (`SKILL.md:128`).

- [ ] **Step 1:** Adapt the onboard test to the new paths and add `test_onboard_imports_without_memory_module` (`python3 -I scripts/compound-v-onboard.py --help` succeeds with `compound-v-memory.py` absent from a temp copy of `scripts/`).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `bash tests/hooks/test-onboard.sh && python3 scripts/compound-v-onboard.py rules-lint --help`. Expected: pass.
- [ ] **Step 5:** Commit: `feat(init,onboard): v4 probes and config; onboard decoupled from V-memory`.

### Task 11: Remove v3, rename, CI

**Files:**
- Delete: every `scripts/*` not in this plan's file table (incl. `cv_emit/`, `cv_validate/`, `__pycache__/`), `hooks/{epic-goal-stop,triage-prompt-nudge,lane-guard,memory-refresh,plan-saved-nudge,brainstorm-trigger0-nudge,precompact-snapshot,postcompact-resume,session-banner}.sh`, `skills/{compound-v,backend-launcher}/`, `commands/`, `agents/{implementer,parallel-dispatcher,partition-reviewer,spec-reviewer,transport}.md`, `schemas/*` except `review-findings`, `examples/`, `evals/`, and every `tests/*` not created by this plan.
- Move: `docs/superpowers/` → `docs/archive/v3/` (`git mv`).
- Modify: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.github/workflows/validate.yml`.

- **plugin.json:** `name: "compound-v"`, `version: "4.0.0"`, a one-sentence description of the cycle, keywords without `superpowers`/`orchestrator`, and `types`.
- **marketplace.json:** `plugins: [{"name": "compound-v", "source": "./"}, {"name": "superpowers-v", "source": {"source": "github", "repo": "procoders/superpowers-v", "ref": "v3"}}]`.
- **validate.yml** keeps the JSON validity checks, version lockstep (select `.name == "compound-v"`), CHANGELOG lockstep, no-Haiku, `lint-frontmatter.py`, shellcheck on `hooks/*.sh`, and the dead-link scan (excluding `docs/archive/**`). The anti-fabrication grep covers `scripts`, `skills`, `hooks` and `docs`, exempting `docs/archive/**` and `docs/compound-v/{specs,plans,preflight}/**`.
- **validate.yml** adds `python3 -m unittest discover -s tests/core -v`, `for t in tests/hooks/*.sh; do bash "$t"; done`, `claude`-free mod type-check if the existing job has one, and the size guard: `cat scripts/compound-v.py scripts/cvcore/*.py hooks/*.sh hooks/run-band.tsx | wc -l` must be ≤ 2500 (print the number).
- **validate.yml** drops the manifest gate, the state.json gate, the epic, job_result and example steps, the all-selftests sweep and `pip install jsonschema`.

- [ ] **Step 1:** Do the deletions and the move, then `grep -rn --exclude-dir=archive -e 'superpowers-v' -e '/v:' -e 'docs/superpowers' -- . ':!docs/archive' ':!CHANGELOG.md' ':!docs/v4'`. Expected: hits only in the v3 marketplace entry and in README migration text (Task 12).
- [ ] **Step 2:** Run `claude plugin validate . --strict`. Expected: pass. Run every CI step locally (`python3 -m unittest discover -s tests/core`, `tests/hooks/*.sh`, `scripts/lint-frontmatter.py .`, shellcheck, size guard). Expected: all pass. Line count printed and ≤ 2500.
- [ ] **Step 3:** Commit: `refactor!: remove the v3 engine; plugin is compound-v 4.0.0`.

### Task 12: Docs

**Files:** Rewrite `README.md`, `AGENTS.md`, `CLAUDE.md`, `CONVENTIONS.md`, `TROUBLESHOOTING.md`; prepend `CHANGELOG.md` `## [4.0.0]`.

- **README:**
  - What v4 does in the cycle's order, install (`claude plugin install compound-v@procoders`), then `/compound-v:init`.
  - The verification bar and what "verified / incomplete / failed" mean.
  - The salon evidence, with numbers only from `docs/v4/salon-report.md`.
  - A "Coming from v3" section: separate plugin id; v3 stays installable as `superpowers-v@procoders` (pinned to branch `v3`); finish unfinished v3 runs with v3; disable Superpowers per project if both brainstorms fire.
- **CHANGELOG 4.0.0:** what was removed (engine, epics, V-memory, workers, adr, models command) and why, in one line each, linking `docs/v4/transition.md`.
- **AGENTS.md / CLAUDE.md:** model policy, the CLI surface, the file table above.

- [ ] **Step 1:** Write them. Run the anti-fabrication grep and the dead-link scan locally. Expected: clean.
- [ ] **Step 2:** Commit: `docs: v4 README, changelog and agent instructions`.

### Task 13: Local end-to-end and platform checks

No code unless a check fails. Each failure becomes a fix with a test in the owning task's files, then this task reruns.

- [ ] **Step 1: Platform facts the pre-flight left unverified:**
  - (a) In a temp marketplace, `claude plugin marketplace add <tmp>` then `claude plugin install superpowers-v@procoders` installs from `ref: v3`. This needs the `v3` branch reachable: use a local file-URL clone of this repo as `repo`.
  - (b) Project-level `enabledPlugins: {"superpowers@claude-plugins-official": false}` disables Superpowers in that project (`claude plugin list` inside it).
  - (c) A Stop hook that exits 1 does not block (a broken `stop.sh` copy in a scratch plugin).
  - (e) a sandboxed `npx playwright test` in a throwaway repo launches Chromium from the cache `setup.sh` filled, with the kit's `allowedDomains` unchanged; (d) `$.session.usage().cost`: read its declared type in the installed CLI's `types/claude-code.d.ts`. Record the facts in `docs/compound-v/preflight/2026-10-22-v4-platform-audit.md` under "Verified in Task 13".
- [ ] **Step 2: Light path, headless,** in a throwaway repo with the salon kit's sandbox settings. Never against this repo; no `--dangerously-skip-permissions`. Run `claude -p` with `--plugin-dir <this repo>` and "fix the typo in README". Expected: a run record with tier light, outcome verified, and receipts tests + scope.
- [ ] **Step 3: Full path, headless:** a tiny web feature (one form) in a throwaway Node repo, with scripted answers through the kit's `turn.sh`. Expected:
  - stages brainstorm → done;
  - a spec, at least one pre-flight file and a plan with a `compound-v-plan` block;
  - a Playwright `live` receipt, a review receipt from the Claude reviewer, and outcome verified;
  - the band shows the steps in an interactive session.
- [ ] **Step 4: Seeded failures** on the same repo: break the form (`live` fail → not verified); edit after verification of an open run (stale → refused once); delete a test (tests removed). Expected: each one refused, as Task 4 claims.
- [ ] **Step 5:** Commit any fixes; record the run ids and costs (from `total_cost_usd`) in `docs/compound-v/preflight/2026-10-22-v4-smoke.md`.

### Task 14: Acceptance benchmark (release gate)

**Files:** Create `~/Dev/cv-salon-e2e-kit/v4-protocol.md`, `~/Dev/cv-salon-e2e-kit/holdout-prd.md`, `~/Dev/cv-salon-e2e-kit/answers-salon.md` (the A3–A5 owner answers, verbatim from their runs) and `answers-holdout.md`; append the results to `REPORT.md` and `docs/v4/salon-report.md`.

- [ ] **Step 1: Freeze the protocol** before any v4 run:
  - same `prd.md`, model `claude-opus-5-5`, `run-settings.json` sandbox, `--setting-sources project,local` and no MCP except Playwright headless;
  - the plugin is `--plugin-dir` of the commit under test (sha recorded);
  - no Superpowers; reviewer = Claude subagent (binding configuration);
  - answers from `answers-salon.md`, given only to questions the run asks;
  - cost = the sum of `total_cost_usd` over turns. This is the gate's authority; the run record's `cost_usd` is advisory, and Task 13 records the delta between the two once.
  - Playwright browsers are pre-installed by `setup.sh` outside the sandbox (`npx playwright install chromium` into the default cache) for every condition. The sandbox's `allowedDomains` stay as they are; Task 13 checks that a sandboxed `npx playwright test` can launch from that cache;
  - judging: Codex `gpt-6-astra` with the existing `blind6/RUBRIC.md` and the census prompt, twice each, with labels swapped.
  The holdout is a small "community tool library" app (members, items, loans with due dates, overdue list, staff admin), with `answers-holdout.md` written once before any run.
- [ ] **Step 2: Runs:**
  - greenfield v4 ×2 and brownfield v4 ×2 (on A5's base with `feature-C.txt`);
  - holdout: v4 ×1 and light-flow ×1 (the A5 method);
  - also v4 with the Codex reviewer ×1 greenfield, recorded but not gated.
- [ ] **Step 3: Judge blind,** following the protocol.
- [ ] **Step 4: Pass rule** (spec §7): greenfield mean rubric ≥ 96.5, mean census "considered" ≥ 75.5 and mean cost ≤ $7; brownfield mean rubric ≥ 76.5 with BASE's tests passing. A miss blocks 4.0.0: go back to the owning skill with the judges' findings, then rerun Steps 2–4.
- [ ] **Step 5:** On a pass, write the results table and ask Oleg to approve: merge `v4-design` → main, push `v3`, and release 4.0.0. Pushes and the release happen only after his yes.
