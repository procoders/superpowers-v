# Phase 1C — Library & Documentation Validation: v3.4.3 codex-sandbox-checkout

**Spec:** [`docs/superpowers/specs/2026-09-03-v3.4.3-codex-sandbox-checkout-design.md`](../specs/2026-09-03-v3.4.3-codex-sandbox-checkout-design.md)
**Date:** 2026-09-03 · **Run:** `docs/superpowers/execution/2026-09-03-v3.4.3-codex-sandbox-checkout/` — `state.json` shows `PARTITION_VERIFIED`, all three jobs (`sandbox-helper`, `docs-note`, `spec-review`) `pending`, no `results/` yet. This audit lands before dispatch, which is when its one 🔴 finding is actually actionable.

**Step 0 (V-memory).** Three queries run before any file was opened: `"codex sandbox checkout worktree helper"`, `"codex exec sandbox workspace-write session_id json thread.started"`, `"bash 3.2 git ls-files git init sandbox copy"` — every call reported the index **94 new / 0 removed docs behind the repo** (staleness on the *index*, not on the quality of what it returned; flagged, not blocking, matching this repo's own established convention for this notice). No hit contradicted the spec. The two most load-bearing hits — `docs/superpowers/library-audit/2026-07-11-session-aware-workers.md` (the `thread.started`/`--json`/resume facts) and the PRD's pinned `codex exec` invocation — are re-verified below rather than trusted as-is. No Trigger-0 recon doc exists for this topic (`docs/superpowers/recon/` has only `2026-07-11-fts5-cyrillic-tokenizer.md` and `2026-09-01-v3.0-triage-tests-orchestration.md`, neither a match — fallback scan confirmed empty).

---

## 1. Tools Available

| Tool | Status | Note |
|---|---|---|
| Context7 MCP | ❌ not attached to this subagent — `ToolSearch "context7 resolve-library-id query-docs"` and `"mcp__ resolve library docs"` both returned no match. Same non-attachment the three most recent same-day 1C audits of this repo recorded for themselves. | Not applicable regardless: nothing in this spec is a Context7-indexed package. |
| Repo `Read`/`Grep`/`Glob` | ✅ primary source for §2–4 | `scripts/compound-v-run-codex-worker.sh`, `skills/backend-launcher/adapter-codex.md`, `scripts/compound-v-resolve-model.py`, `scripts/compound-v-validate-manifest.py`, `scripts/compound-v-emit-workflow.py`, `schemas/job_result.schema.json`, `CHANGELOG.md`, and this run's own materialized `manifest.yaml`/`state.json`/`dispatch.workflow.js` all read in full or in the relevant part. |
| WebSearch / WebFetch | ✅ used for external codex-cli currency (§2, §5) | `developers.openai.com/codex/changelog` redirects to `learn.chatgpt.com/docs/changelog` (308, not auto-followed by WebFetch — noted, not treated as a failure); cross-checked with WebSearch instead. |
| Local Bash probe of `codex`/`git`/`bash` | ❌ not available to this session | `bashCommandClamp` on this spawn allows only `compound-v-memory.py search`/`recall-check`. Every locally-installed-version claim below is either reused from this repo's own most-recent live probe (a **2026-09-02** full `codex exec --help` capture, one day old) or sourced from the public npm registry/changelog — never asserted as freshly re-probed by this session. |
| Dependency manifests | n/a | none exist anywhere in the tree (Glob-confirmed: `package.json`, `requirements*.txt`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Gemfile`, `composer.json` — zero hits), consistent with every prior 1C audit of this repo. |

**Not DEGRADED for the question that matters.** Context7 is absent, but nothing in scope is a Context7-indexed library — this spec's whole dependency surface is (a) Bash 3.2 + git, both platform-level and already well-pinned in this repo, and (b) the `codex` CLI as the multi-model execution backend being exercised, which is what §2–5 verify against the freshest evidence this session could gather.

---

## 2. Libraries / Platform Surfaces Mentioned

| Name | Spec context | Current state | Repo/spec assumption | Status |
|---|---|---|---|---|
| **Bash 3.2 + git** (Decisions 1–2) | The new helper and its test are "Bash 3.2 + git only; no python" | Stock-macOS convention this repo has held since v1.0; last **locally** confirmed `bash 3.2.57` / `git 2.50.1` on **2026-07-10** (`adapter-codex.md`). No contrary evidence found; this session cannot re-probe (Bash clamped). | Correct, inherited | 🟢 OK (reused, not re-derived — ~8 weeks old, no known drift) |
| **`codex` CLI, `exec`** (Decision 4 — the job actually runs on it) | `backend: codex`, `tier: standard` → `gpt-5.6-terra`, `effort: medium`, `isolation: worktree` | **Locally installed and live-probed: `codex-cli 0.144.1`**, confirmed via a **full `codex exec --help` capture dated 2026-09-02** — one day before this audit (`_knowledge-base/claude-code-hooks.md:142-151`). **npm registry `@openai/codex` latest: `0.153.0`, released 2026-09-03** (today) — the locally-pinned binary is **~9 minor releases / ~8 weeks behind** current npm. One breaking change surfaced across that window (`--full-auto` removed in 0.147.0, replaced by `--sandbox workspace-write`) — **does not affect this repo**, which already uses `--sandbox workspace-write` explicitly and never referenced `--full-auto`. No other breaking change to the flags this design's own verification points depend on (`--json`, `--output-last-message`, `--skip-git-repo-check`, `-c model_reasoning_effort`, `resume`) was found. | Flag set still correct; **version gap is real and worth a live re-check at dispatch, not a currency emergency** | 🟡 see §6 |
| **`gpt-5.6-terra`** (the resolved model for this exact job — `tier: standard`) | Decision 4 | `_CODEX = {"frontier": "gpt-5.6-sol", "deep": "gpt-5.6-sol", "standard": "gpt-5.6-terra", "light": "gpt-5.6-luna"}` (`scripts/compound-v-resolve-model.py:91-92`). WebSearch (`developers.openai.com/codex/models` family): GPT-5.4/5.4-mini **retired from Codex 2026-08-31**, with OpenAI's own migration guidance naming `gpt-5.6-terra`/`gpt-5.6-luna` as the direct replacements — this repo is already on the correct side of that transition, not behind it. | Correct, current | 🟢 OK |
| **`.claude/compound-v.json`** (Decision 4's own flagged open item: *"NOT required... to be verified live (finding)"*) | Decision 4 | **CONFIRMED by reading the resolver.** `load_config_models(config_path)` returns `{}` for a falsy/missing `config_path` (`compound-v-resolve-model.py:212-213`); `resolve("codex", "standard")` with no config then falls through to `DEFAULT_MODELS_BY_STANCE["balanced"]["codex"]["standard"] == "gpt-5.6-terra"`. The script's own `--selftest` exercises exactly this (`resolve("codex","deep",config_models=bad_cfg)["model"] == DEFAULT_MODELS["codex"]["deep"]`, lines 671-681) — a missing **or malformed** config both degrade to the built-in map, never an error. | **Verified true** — this closes the spec's own open item | 🟢 OK — the spec's "to be verified" hedge can become a stated fact |
| **`type: large_isolated` / `isolation: worktree` / `tier: standard` / `effort: medium`** (Decision 4's manifest fields) | Decision 4 | All four are live, current enum values: `VALID_ISOLATIONS = ("direct", "worktree")` (`compound-v-validate-manifest.py:790`), `large_isolated` used pervasively as a `job_type` throughout the same file's fixtures, `TIERS`/`EFFORTS` in the resolver include `standard`/`medium`. Already materialized without a validation error in this run's own `manifest.yaml`. | Correct | 🟢 OK |
| **The multi-model verification contract itself** (Decision 5 / the review job's acceptance criterion) — `session_id`, `files_changed`, events-log, **`worktree`** | Decision 5, and verbatim in `manifest.yaml`'s `acceptance_criteria[1]` | `session_id`/`thread.started`-first-line/`files_changed==write_allowed`/`logs/<job-id>.events.jsonl` all **confirmed current** (§3). The **`worktree` field's claimed location is wrong** — see §4 🔴-1. | Three of four sub-claims correct; one is not | 🔴 see §4 |

---

## 3. API Signatures Verified

| Claim | Verified against | Verdict |
|---|---|---|
| First `--json` JSONL line is `{"type":"thread.started","thread_id":"<uuid>"}`, and `session_id` is parsed from it | `_knowledge-base/claude-code-hooks.md:125-128` (live probe, `--sandbox read-only --json --ephemeral`, this exact sequence observed: `thread.started`, `turn.started`, `item.completed`×3, `turn.completed`); `adapter-codex.md:62,151` (parses "the **first** `thread.started` line", UUID-shape-validated) | ✅ correct, current |
| `--json` and `--output-last-message` coexist (summary path unaffected by adding `--json`) | `adapter-codex.md:62` ("`--json` and `--output-last-message` **coexist**"); `codex exec --help` flag list at `claude-code-hooks.md:142-148` shows both `--json` and `-o/--output-last-message` as live, independent flags | ✅ correct |
| `--ask-for-approval` is invalid for `codex exec` (top-level/interactive only) — omitted by design | `adapter-codex.md:84-86`; re-confirmed in the 2026-09-02 `--help` capture: *"`--ask-for-approval` remains absent from `exec` (top-level only) — the existing pin is still correct."* | ✅ correct |
| Events land at `logs/<job-id>.events.jsonl` | `scripts/compound-v-emit-workflow.py:1334`: `argv += ["--events-log", os.path.join(run_dir, "logs", "%s.events.jsonl" % job["id"])]` — exact match to the spec's `logs/sandbox-helper.events.jsonl` | ✅ correct |
| `files_changed` == `git diff --name-only` ∪ `git ls-files --others --exclude-standard`, measured against the worktree | `job_result.schema.json:40`; `adapter-codex.md:18-19,98` | ✅ correct |
| `results/<job>.json.worktree` is under `.cv-worktrees/` | **Contradicted.** See §4 🔴-1. | ❌ **wrong** |
| `jobs/<job>.launch-argv` exists before launch | The spec hedges with "(or the emitted launch command)". Actual on-disk convention: `jobs/<job-id>.launch.argv.json` (`compound-v-emit-workflow.py:1039-1040`, and materialized for this exact run as `jobs/sandbox-helper.launch.argv.json` in `dispatch.workflow.js:192`) — filename shape differs (dots + `.json`, not a bare `.launch-argv` suffix) | 🟡 imprecise but not blocking — the spec's own hedge covers it; see §6 |

---

## 4. Critical Findings 🔴

### 🔴-1 · The acceptance criterion's claimed `worktree` location is wrong for a codex-backend job — and it is already baked into this run's `manifest.yaml`

**Claim, verbatim from the spec (Decision 5) and from the materialized `manifest.yaml acceptance_criteria[1]`:**
> "`results/<job>.json.worktree` is under `.cv-worktrees/` (the worker's own tree, not the workflow agent's)"

**This is false for the mechanism this exact job uses.** Four independent, mutually-consistent sources in this repository say the codex worker's worktree lives **outside the repo**, under `$TMPDIR/compound-v/<run-id>/<job-id>`:

1. **`schemas/job_result.schema.json:57-59`** — the `worktree` field's own description, verbatim: *"Absolute path of the worktree the job ran in, or empty string for `direct` (in-place) jobs. **Worktrees live under `$TMPDIR/compound-v/<run-id>/<job-id>`.**"*
2. **`scripts/compound-v-run-codex-worker.sh:359,364`** — the actual, only script that runs a `backend: codex` job: `WT_PARENT="$TMPROOT_REAL/compound-v"` then `WT="$WT_PARENT/$RUN_ID/$JOB_ID"`. Every other external-backend worker (devin, cursor, opencode, antigravity) uses the identical pattern.
3. **`skills/backend-launcher/adapter-codex.md:104-116`** — "Worktree lifecycle": *"Worktrees live **outside the repo**, under `"${TMPDIR:-/tmp}"/compound-v/<run-id>/<job-id>` — so no `.gitignore` change is needed."*
4. **`CHANGELOG.md:1561`** — the original v1.0 orchestrator entry, unchanged since: *"Worktrees live in `$TMPDIR/compound-v/<run-id>/<job-id>`..."*

**Where `.cv-worktrees/` actually comes from:** `scripts/compound-v-emit-workflow.py:6239`, inside `_selftest()`'s `_seal_case()` fixture — a synthetic scenario that constructs a hypothetical `isolation: worktree` job by hand-running `git worktree add` **inside** a scratch repo, with an explicit comment explaining why: *"INSIDE the repo, as the real pipeline places them: the finalizer refuses to `worktree remove` anything outside the project, so a fixture that put the tree in `/tmp` would never exercise the prune it is testing."* That comment is itself revealing: it frames `.cv-worktrees/` as a **test-fixture convenience**, not a claim about where a real job's worktree lives. It is also corroborated by the same file's own selftest assertion that a non-Claude backend job's **Workflow agent** runs at `isolation: direct` — i.e. the agent invoking `compound-v-run-codex-worker.sh` does *not* itself sit in a nested worktree; the worktree that exists is the one the **script** creates, at the `$TMPDIR` path above, entirely outside the checkout the workflow agent operates in. This run's own `state.json` confirms the shape: `sandbox-helper` is `"isolation": "worktree"` at the manifest-job level while the underlying Workflow-agent mechanics (per `compound-v-emit-workflow.py`'s selftest) execute it at `isolation: direct`.

**Impact.** `docs/superpowers/execution/2026-09-03-v3.4.3-codex-sandbox-checkout/manifest.yaml` line 18 and the `spec-review` job's own `body` (line 91: *"Criterion 2 is the point of this run: quote the session_id, worktree, files_changed and the first events-log line verbatim"*) both currently instruct the review job to check for a path containing `.cv-worktrees/`. A correctly-functioning `sandbox-helper` job will produce a `worktree` field that looks like `/private/var/folders/.../T/compound-v/2026-09-03-v3.4.3-codex-sandbox-checkout/sandbox-helper` — which does not contain `.cv-worktrees/` and would fail this criterion read literally, forcing the Opus review job to either (a) flag a correctly-working system as ISSUES, or (b) silently reinterpret its own acceptance criterion mid-review — both are exactly the "acceptance criteria are ground truth, don't improvise" failure this repo's own review-gate ethos exists to prevent, just aimed at the plan's own text instead of the code.

**Constraint:** before dispatch, correct Decision 5's wording (and, ideally, the already-materialized `manifest.yaml acceptance_criteria[1]` and the `spec-review` job body) to state the `worktree` field is expected under `$TMPDIR/compound-v/<run-id>/<job-id>` (equivalently: **absolute, outside the repo checkout, not `.cv-worktrees/`**). This is a one-line text fix, not a redesign — the run has not dispatched (`state.json`: `PARTITION_VERIFIED`, all jobs `pending`), so nothing needs to be re-run, only re-read before `sandbox-helper` launches.

---

## 5. High-Priority Findings 🟠

*(none — the one signature discrepancy found is unambiguous enough, and cheap enough to fix, to file as Critical rather than High; nothing else rises to "verify before trusting the design's safety/routing claims" the way 🔴-1 does.)*

---

## 6. Medium Findings 🟡

### 🟡-1 · Locally-pinned `codex-cli 0.144.1` is ~9 releases behind npm's `0.153.0` (released today) — re-probe before trusting the pinned invocation, don't just reuse the pin

The flag set this design depends on structurally (`--json`'s first-line `thread.started` event, `--output-last-message` coexistence, `-c model_reasoning_effort`, `--skip-git-repo-check`, `--sandbox workspace-write`) was last **locally** confirmed one day ago (2026-09-02, a full `codex exec --help` capture) on `codex-cli 0.144.1`. The public npm package `@openai/codex` is at `0.153.0` as of today (2026-09-03). WebSearch across the intervening releases (0.145–0.150) surfaced substantial feature churn in exactly the area this design's acceptance criteria are structurally sensitive to — 0.145.0 added "thread history with search, resume, memories," 0.146.0 added "thread pinning and forking" — and one confirmed breaking change, `--full-auto` removed in 0.147.0 (replaced by `--sandbox workspace-write`, which this repo already uses, so **not** a live break here). No other flag rename/removal affecting this repo's pinned set was found. This is not evidence of a break — it is evidence that nobody has re-run the live probe since the version drifted this far, on a CLI shipping breaking changes roughly monthly.

**Constraint:** add a cheap `codex --version` (or `codex exec --help` diff) check as part of `sandbox-helper`'s own acceptance run, or at minimum log the installed version into the job's summary — the same "one real invocation beats a documentation citation" bar this repo's own 1C audits have set for `ProposeGoal` (2026-09-02 v3.4-native-first audit) and `--tools ""` (2026-09-03 v3.4.1-triage-size audit). If the installed binary has auto-updated past 0.144.1 by dispatch time, that is useful information for the review job to record, not a silent assumption.

### 🟡-2 · `git init`'s default-branch hint is stderr noise, not a functional risk — worth one sentence in the plan so it isn't rediscovered as a bug

`git init` on any git ≥ 2.28 without `init.defaultBranch` configured prints an advisory hint (*"hint: Using 'master' as the initial branch name..."*) to **stderr**, and the resulting branch name is whatever the machine's `init.defaultBranch` config says (not necessarily `main`). Decision 1's helper "runs `git init` + one commit there" with no `-b <name>` specified. None of the spec's own acceptance criteria check the sandbox's branch name (only tracked-file byte-identity, execution-dir presence/absence, and pre-eval emptiness), so this is not a correctness bug — but the helper's documented output contract ("prints `sandbox: <dest>` and `files: <n> commit: <sha>` on success") should route `git init`'s stderr away from anything a caller might parse as the summary line, since a stray hint on stderr could otherwise be conflated with a real error by a caller that doesn't discriminate.

---

## 7. Design Constraints for the Plan

**MUST**
1. Correct Decision 5 (and the already-materialized `manifest.yaml acceptance_criteria[1]` + `spec-review`'s job body) to state the `worktree` field is expected under `$TMPDIR/compound-v/<run-id>/<job-id>`, **not** `.cv-worktrees/`, before `sandbox-helper` is dispatched. (🔴-1)
2. Treat "`.claude/compound-v.json` is NOT required when the backend is named explicitly" as a **confirmed fact**, not an open item — the resolver's fallback-to-`DEFAULT_MODELS` behavior on a missing/malformed config is already selftested in `compound-v-resolve-model.py`. (§2)

**SHOULD**
3. Log the installed `codex --version` (or an equivalent flag-presence check) as part of `sandbox-helper`'s own run, given the local pin is ~9 releases behind npm's current release and the intervening releases touched thread/session mechanics adjacent to this design's `--json`/`thread.started` dependency. (🟡-1)
4. Route `git init`'s stderr (the default-branch-name hint) away from the helper's success-line output contract, or state explicitly that stderr is never parsed by a caller. (🟡-2)

**MUST NOT**
5. Add any third-party package, npm/pip/cargo/go dependency, or Python interpreter requirement to the helper or its test — Decision 1's "Bash 3.2 + git only; no python" is correct and matches every other 1C audit of this repo; nothing found here argues against it.

---

## 8. Open Questions for the Human

1. **Who corrects the `.cv-worktrees/` wording, and where?** It appears in three places today (the spec's Decision 5, `manifest.yaml`'s materialized `acceptance_criteria[1]`, and the `spec-review` job's `body`). Since the run hasn't dispatched, the cheapest fix is editing `manifest.yaml` and the spec directly rather than re-materializing — but that's a process call, not this audit's to make. (🔴-1)
2. **Is a `codex --version` log worth a line in `sandbox-helper`'s acceptance criteria, or is "the review job reads whatever `job_result.session_id`/`worktree` actually say" enough?** The gap is real (~8 weeks / 9 releases) but nothing found today breaks the pinned invocation — this is a judgment call about how much verification-debt to pay down in this stage-4 run versus flag for a future refresh pass. (🟡-1)
3. **A lane-guard operational blocker, found while writing this very audit (not part of the audit's own scope, reported separately below).**

---

## 9. Knowledge Base Updates — NOT YET APPLIED

**Blocked by the same lane-guard denial described below.** Intended: create **`_knowledge-base/codex-cli.md`** (did not exist — the `codex exec --help` capture and version pins this repo has accumulated across `2026-07-11-session-aware-workers.md`, `2026-07-14-v2.14-blockers-and-headless.md`, `2026-09-03-v3.4.1-triage-size.md`, and `_knowledge-base/claude-code-hooks.md:125-151` were scattered across audit-dated files and one mis-homed KB entry, with no single page a future 1C pass can check first). The new file would consolidate: the local-install version history (0.130.0 → 0.144.1, confirmed live as recently as 2026-09-02), today's npm-registry latest (0.153.0) and the version gap, the full pinned `codex exec` flag set, the `--full-auto` removal (0.147.0) and why it doesn't affect this repo, the worktree-location contract (`$TMPDIR/compound-v/<run-id>/<job-id>`, **not** `.cv-worktrees/`, with the `.cv-worktrees/` selftest-fixture caveat spelled out so it is never mistaken for the production convention again), and the `gpt-5.6-terra`/`gpt-5.4` retirement timeline. Every claim is date-stamped and cited to either a repo file+line or a WebSearch/WebFetch source.

---

**Counts: 1 critical, 0 high, 2 medium.** Section 8 (Open Questions) has 2 audit items (process calls, not blockers — 🔴-1's fix is a one-line text correction the run's own `state.json` (`PARTITION_VERIFIED`, nothing dispatched) leaves plenty of room for) plus 1 operational item below.

---

## OPERATIONAL BLOCKER — this file could not be written to its intended path

`Write` to `docs/superpowers/library-audit/2026-09-03-v3-4-3-codex-sandbox-checkout.md` (the path this agent was explicitly told to use, and the exact path already referenced in this run's own `manifest.yaml:10: library: docs/superpowers/library-audit/2026-09-03-v3-4-3-codex-sandbox-checkout.md`) was **denied** by the Compound V lane guard hook:

> "Compound V lane guard: job 'spec-review' is not allowed to write 'docs/superpowers/library-audit/2026-09-03-v3-4-3-codex-sandbox-checkout.md'. Its write_allowed lane is: docs/superpowers/dogfood/2026-09-03-v3.4.2-transcript-watch-review-1.md. Resolved via cwd->worktree."

**Root cause, confirmed by reading the file the hook is resolving against:** `docs/superpowers/execution/2026-09-03-v3.4.2-transcript-watch/lane-map.json` — from an **already-completed, unrelated run** — contains exactly one entry:

```json
{"worktrees": {"/Users/oleg/Dev/superpowers-v": "spec-review"}, "run_id": "2026-09-03-v3.4.2-transcript-watch", ...}
```

That run's `spec-review` job ran at `isolation: direct` (no worktree of its own — it writes straight into the bare repo checkout), so its lane-map entry keys the **bare project root** to its own job id. Per the lane-guard's own documented resolution rule (`docs/superpowers/specs/2026-09-01-v3.0-triage-tests-orchestration-design.md` §E1: *"Resolve the job: `agent_id` → the run's job map; fall back to `cwd` → worktree id → job"*), this Phase 1C subagent has no `agent_id` in any dispatched job map (pre-flight subagents like this one run outside Engine C entirely), so it falls back to `cwd` resolution — and the only lane-map.json in the whole repo that happens to key the bare root is that stale, already-finished run's. The v3.4.3 run being audited here has **no lane-map.json of its own yet** (correctly — it hasn't been dispatched), so there was nothing correct to fall back to instead.

This is a real, reproducible gap: **a completed run's `lane-map.json` is never cleaned up, and any future off-pipeline agent (or a fresh interactive session) operating from the bare repo root inherits that stale run's job identity and lane**, blocking legitimate writes that have nothing to do with the finished run. This is Phase 1A (existing-code-reality) territory, not this agent's library-currency mandate, so it is reported here as a blocker rather than folded into the findings above — but it is directly why this file is sitting in scratchpad instead of `docs/superpowers/library-audit/`.

**What was done instead:** per the guard's own instruction ("stop and report it rather than widening the lane yourself"), no bypass was attempted. This complete audit was written to the scratchpad instead, and handed to the user directly via `SendUserFile` so the work is not lost. **Recommended remediation (not implemented — not this agent's role):** delete or archive `lane-map.json` files under `docs/superpowers/execution/*/` once that run's `state.json` reaches a terminal phase, and/or have the lane-guard's cwd fallback additionally check that the resolved run is still active before trusting its lane.
