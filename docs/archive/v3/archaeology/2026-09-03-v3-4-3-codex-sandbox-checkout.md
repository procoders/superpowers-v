# v3.4.3 Codex Sandbox-Checkout — Code Archaeology

Spec under audit: `docs/superpowers/specs/2026-09-03-v3.4.3-codex-sandbox-checkout-design.md`.
Scope: the new helper (`scripts/compound-v-sandbox-checkout.sh` + `tests/test-sandbox-checkout.sh`,
Task A) and what it is claimed to make testable (Task B's note in `agents/spec-reviewer.md`).

> **This file could not be written to its intended path,
> `docs/superpowers/archaeology/2026-09-03-v3-4-3-codex-sandbox-checkout.md`.** See the blocking
> environment finding at the end of this document. This copy lives in the session scratchpad instead.

## Step 0 — V-memory recall

Five queries run (`compound-v-memory.py search … --intent planning --top 6..8`). Every result carried
the same header: **`V-memory: index is 94 new / 0 removed docs behind the repo`** — the FTS5 index has not
been refreshed since a large batch of recent docs landed, so recall is stale by construction for
anything written in the last day (which includes the spec, plan, and every v3.4.1–v3.4.2 dogfood record
this audit relies on). Every claim below that came from a recalled snippet was **re-verified against the
live file**, per the instruction that recall is evidence, not authority. Two prior archaeology audits
touch this exact subsystem and were read in full before this one was written:

- `docs/superpowers/archaeology/2026-07-11-session-aware-workers.md` — the Codex worker's `--json`
  session-id capture, worktree lifecycle, `job_result.schema.json` fields. Nothing in that audit is
  stale for this feature: the worker script it describes (`compound-v-run-codex-worker.sh`) is unchanged
  in the relevant sections (re-read in full below).
- The three most recent v3.4.x archaeology/dogfood records (`2026-09-02-v3-4-native-first.md`,
  `2026-09-03-v3-4-1-triage-size.md`, `2026-09-03-v3-4-2-transcript-watch-review-*.md`) — not directly
  cited below, but they establish that this run is Stage 4 of a deliberate five-cycle verification
  program (per `AGENTS.md` MEMORY note "v3.4 stage verification"), which is why a run directory for
  *this exact feature* already exists (see §9).

No V-memory hit named `.claude/compound-v.json`'s per-plugin-repo exclusion, the CI shellcheck scope, or
the `lane-map.json` git-tracking status — the three findings below that carry the most design weight were
found by reading code, not by recall.

## 1. Matrix

The helper takes three independent flags. Two structural facts hold for **every** combination and are not
flags at all: **(a)** `.claude/compound-v.json` never exists in any sandbox this helper can produce from
this repository (§2), and **(b)** `docs/superpowers/execution/<run>/lane-map.json` never exists in any
sandbox this helper can produce, `--keep-execution` or not (§2). Those two constants gate which hook/
mechanism a sandbox can actually be used to probe:

| `--keep-execution` | `--empty-pre-eval` | `--taxonomy-from` | `triage-prompt-nudge.sh` (UserPromptSubmit) usable? | `epic-goal-stop.sh` rule 1/2 (Stop) usable? | `hooks/lane-guard.sh` "resolved lane" usable? |
|---|---|---|---|---|---|
| absent | absent | absent | **Yes** — real repo's pre-eval history rides along; a *fresh* session id still isn't "covered" by it, so gate 6 still passes. `_has_active_run` sees no execution dir → not-active → hook can fire. | **No** — `.claude/compound-v.json` absent ⇒ `_triage_rule`/`_enforcement_rule` both `return 1` unconditionally (`hooks/epic-goal-stop.sh:343`, `:535`). | **No** — `lane-map.json` never copies (gitignored); `hooks/lane-guard.sh:882 live_lane_map` never sees a lane, so the checkout always reads as *unresolved*, keep-execution or not. |
| present | absent | absent | **Yes**, and this is the one combo that can reproduce "active run": if the copied `state.json` shows an open job within 6h, `_has_active_run` → active → hook stays silent by design (df12's own use case). | **No** (same reason — the config file, not the execution dir, is what's missing). | **No** (same reason — lane-map.json, not state.json, is what lane-guard reads). |
| absent | present | absent | Yes, same as row 1; the emptied pre-eval dir just removes real historical records from the copy (hygiene, not a functional requirement — see below). | No | No |
| present | present | absent | Yes, same as row 2, with the pre-eval dir cleared. | No | No |
| any × any | any | given | Deliberately **not** byte-identical for `.claude/compound-v-impact-taxonomy.yaml` — this is the documented escape hatch for a counterfactual probe (exactly what the reviewer already hand-built once, see `docs/superpowers/dogfood/2026-09-03-v3.4.1-triage-size-review-1.md:279-284`, which appended `content_scan_exclude` entries by hand because no such flag existed yet). | No | No |

**The two "No" columns are not a bug in the helper — they are a scope fact the spec's framing blurs.**
The spec's own line ("finding 64 called it worth a helper someday… to drive the triage hook on a
checkout with an active run") and the plan's Task B note ("to drive the triage hook on a checkout that
has a live run, use the helper") both say *"the triage hook"*, singular, but this repo has **two** hooks
that description could mean, and only one of them is reachable through any sandbox this helper builds.
The manifest already dispatched for this run (`docs/superpowers/execution/2026-09-03-v3.4.3-codex-
sandbox-checkout/manifest.yaml:19`) is precise about which one: its own acceptance criterion says
"`hooks/triage-prompt-nudge.sh` driven inside that sandbox … returns a TIER line" — `epic-goal-stop.sh`
is not named anywhere in that manifest's acceptance criteria. So the manifest itself already narrowed the
claim correctly; **the risk is in Task B's doc-note**, which if written from the spec's looser "the triage
hook" language rather than the manifest's precise one, will over-promise what agents/spec-reviewer.md
readers can expect the helper to do.

## 2. Shared State

### `.claude/compound-v.json` presence inside any sandbox this helper builds

- **Read by:** `hooks/epic-goal-stop.sh:342-343` (`_triage_rule`, hard `[ -f "$cfg" ] || return 1`) and
  `:534-535` (`_enforcement_rule`, same hard gate). Also read by `hooks/triage-prompt-nudge.sh:534`, but
  there it is one of *two* alternatives (`docs/superpowers/` OR the config file) — `docs/superpowers/`
  being tracked and always present makes that gate irrelevant to this file's absence.
- **Set in this repo:** never. `commands/v-init.md:482` states it in so many words: *"project-local;
  committed in YOUR project, never in the plugin repo."* This repository (`superpowers-v` itself, the
  plugin's own source) is exactly "the plugin repo" that sentence excludes. Confirmed on disk: `.claude/`
  contains only `settings.json`, `compound-v-impact-taxonomy.yaml`, and
  `compound-v-impact-taxonomy.example.yaml` (no `compound-v.json`, `Glob .claude/*` result).
- **NOT set when:** always, in this repository, forever, by policy — not a transient gap, a permanent one.
- **Consequence for `git ls-files`:** the new helper's whole mechanism is "copy every `git ls-files` path."
  A file that is never tracked in the source repo can never appear in the sandbox by that mechanism,
  regardless of which of the three flags are passed. None of the three flags names this file, so there is
  no way to opt into carrying it across either.
- **Gap:** if Task B's doc-note (or any future reader of `agents/spec-reviewer.md` §3.3) assumes the
  helper can be used to probe `hooks/epic-goal-stop.sh`'s triage gate or bypass rule, that assumption is
  false for every sandbox this helper can produce from this repository, silently — both rules just
  `return 1` (no log line, no error; `set -o pipefail` only, no `set -e`, and the whole file fails open by
  design) and the Stop hook prints nothing, which looks identical to "the rule correctly found nothing to
  flag."

### `docs/superpowers/execution/<run-id>/lane-map.json` presence

- **Read by:** `hooks/lane-guard.sh:765` (candidate list `("lane-map.json", "state.json")`) and
  `:882 live_lane_map(path)` / `:1536` — this is the file that answers "is this checkout claimed by a live
  run," the exact question `AGENTS.md`'s own measurement-methodology section describes getting wrong once
  ("a checkout that a live run's lane map claims measures the resolved path... which is exactly how the
  first attempt at this round produced a 247 ms 'unresolved' figure").
- **Set in the real repo:** by `register-lane`, while a run is live; retired (deleted) at MERGED/BLOCKED
  (`.gitignore:77`, "finding 68"), and `hooks/lane-guard.sh:725-742 run_is_terminal()` was added as a
  second, independent defence for maps committed *before* the finalizer started deleting them —
  see the live-reproduced defect in §9, which is exactly the failure mode this function's own docstring
  says it was written to close.
- **Gitignore status:** `.gitignore:78` — `lane-map.json` is explicitly ignored, repo-wide, unconditionally.
  It is therefore **never** a `git ls-files` path, in this repo or any fork of it, live run or not.
- **Consequence:** `--keep-execution` copies whatever of `docs/superpowers/execution/<run>/**` is
  git-tracked (`manifest.yaml`, `state.json`, `results/*.json`, `receipts/*.json` — the committed audit
  trail per `.gitignore:8-13`) but **can never** copy `lane-map.json`. A sandbox built with
  `--keep-execution` therefore always reads to `hooks/lane-guard.sh` as *unresolved*, exactly like one
  built without it. This is a **good** property for `AGENTS.md`'s own measurement recipe (it structurally
  cannot reproduce the false-"resolved" incident it warns about) but it means `--keep-execution` is useful
  for probing `_has_active_run`/pre-eval coverage (state.json-keyed) and **useless** for probing
  `hooks/lane-guard.sh`'s resolved-lane path (lane-map.json-keyed) — two different mechanisms, keyed off
  two files with two different git-tracking fates, easy to conflate under the single word "active run."

### `WRITE_ALLOWED` / codex job routing (verifying spec item 4, marked "to be verified live")

- **Read by:** `scripts/compound-v-resolve-model.py:266 resolve()`. `load_config_models(config_path)`
  (`:202-230`) returns `{}` when `config_path` is falsy or the file doesn't exist — **not** an error.
  `resolve()` then falls through to `DEFAULT_MODELS_BY_STANCE[stance][backend][tier]` (`:304-306`).
- **Verified for this cell:** `_CODEX = {"standard": "gpt-5.6-terra", ...}` (`:91-92`);
  `DEFAULT_EFFORT_FOR_TIER["standard"] = "medium"` (`:175-176`). So `backend=codex, tier=standard` resolves
  to `gpt-5.6-terra` at `medium` effort with **zero** dependency on `.claude/compound-v.json` existing —
  confirming spec §Decisions 4's claim exactly. This is **not** a gap; it is a verified fact, and the
  `manifest.yaml` already dispatched for this run (`jobs.sandbox-helper: {backend: codex, tier: standard,
  effort: medium}`) matches it precisely.

## 3. Sibling Code

### `scripts/compound-v-run-codex-worker.sh` (the Codex adapter the new helper will run *inside*, not a
copy target for the new script's own logic — but it establishes every convention Task A must match)

Read in full (751 lines). Relevant to a new bash-3.2 script written by a job running through this worker:

- **Portability floor is enforced by precedent, not by a lint rule that would catch a violation**: the
  file's own header states "stock-macOS bash 3.2.57 (NO associative arrays / mapfile / `${var,,}`)" and
  the body honors it throughout (`set --` instead of arrays at `:337-340`, `case` instead of regex
  matching). Nothing mechanically checks a *new* script for this — `shellcheck` does not flag bash-4-isms
  used in valid bash-3.2-compatible ways, and CI's shellcheck step doesn't even reach `scripts/*.sh` (§5).
  Compliance here is convention-only.
- **Worktree isolation, baseline SHA captured before `git worktree add`, then diffed against that pinned
  SHA rather than `HEAD`** (`:397-409`) — irrelevant to the new script's own logic (it is not itself run
  as a worktree job's payload script; it is the *file the job writes*), but it is the exact mechanism that
  will diff the new script's own two files (`scripts/compound-v-sandbox-checkout.sh`,
  `tests/test-sandbox-checkout.sh`) against baseline when the job's result is gated.
- **The scope gate is delegated to `scripts/compound-v-scope-check.py`, never re-implemented in bash**
  (`:572-577`, stated explicitly as a design rule: "a weaker `case`-glob matcher would DIVERGE from the
  Python authority"). This is the DRY precedent Task A's own script must not violate if it ever needs to
  match paths — it does not (`git ls-files` enumerates paths; no glob-authority duplication is needed for
  the sandbox-checkout script itself) — noted only because it is the standing rule in this codebase for
  any future extension of the helper (e.g., an exclude-glob flag).
- **Known-latent risk carried over, not introduced by this feature**: `run_codex()` interpolates
  `$EFFORT_FLAG` unquoted on purpose (`:479-501`, commented "word-split intentionally") — not touched by
  this feature, noted only because it is the kind of intentional-looking-fragile pattern a reviewer must
  not "fix" by reflex if it appears near code this feature's diff touches.

### `hooks/triage-prompt-nudge.sh` (706 lines, read in full) — the actual probe target

Entry conditions (7 numbered fire conditions, `:77-95`), all must hold. The two load-bearing for a
sandbox built by the new helper:

- **Condition 4** (`:534`): `[ -d "${proj}/docs/superpowers" ] || [ -f "${proj}/.claude/compound-v.json" ]`.
  `docs/superpowers/` is always present and tracked (dozens of `.md` files under it), so this condition is
  always satisfied in any sandbox this helper builds — independent of `.claude/compound-v.json`.
- **Condition 7** (`_has_active_run`, `:297-314`): shells out to `compound-v-dashboard.py resume
  --open-jobs --max-age-hours 6 --execution-root "${proj}/docs/superpowers/execution"`. Reads **only**
  `state.json`'s `status`/`state_jobs[*].status` fields and a **recorded** timestamp (`_age_hours`,
  `compound-v-dashboard.py:1254`) — never a file mtime. This is exactly why the helper's fresh `git init`
  (which resets every file's mtime to copy-time) does not break this check: the dashboard was already
  built (v2.19, per `AGENTS.md` MEMORY) to be mtime-independent, for the unrelated reason that git itself
  rewrites mtimes on clone/checkout. The new helper inherits that robustness for free — it did not have to
  design around mtimes, because the consumer already doesn't care about them.
- **Latent bug class already fixed upstream, not present here**: `_has_active_run`'s own comment
  (`:303-309`) documents a real incident ("five superseded runs of one night and a BLOCKED one kept the
  banner's answer 'yes' for three days") that was the *reason* `--open-jobs --max-age-hours 6` exists
  instead of a bare "any unfinished run" check. Nothing in the new feature touches this function; it is
  cited here so a reviewer recognizes that if a sandbox test ever reports "hook silent when I expected it
  active" or vice versa, the bug (if any) is almost certainly in test data staleness against the 6h window,
  not in the helper.
- **Not exercised by this feature at all, but sits in the same file and is easy to conflate**: the
  headless T3 classify path (`_classify_headless`, `:377-418`) spawns a *second* process (`claude -p` or
  codex) with its own ~15s budget. A synthetic probe against a sandboxed checkout that hits `needs_t3`
  will therefore take up to ~18s and spawn a real model call *from inside the sandbox's copied
  `.claude/compound-v-impact-taxonomy.yaml`* — worth knowing before assuming a hook probe is instant.

### `hooks/epic-goal-stop.sh` (683 lines, read in full) — the hook the sandbox is claimed useful for but is not tested for

- **Rule precedence** (`:658-673`): `_triage_rule` first, `_enforcement_rule` second, only one block per
  event. Both gated on `.claude/compound-v.json` (see §2) — in a sandbox from this repo, execution never
  reaches past `[ -f "$cfg" ] || return 1` for either rule, so `hook_main` always falls through to `return
  1` (silent, no block) regardless of what changed or what pre-eval records exist.
- **Fail-open discipline is real and load-bearing**: no `set -e`, no `set -u`, an `EXIT` trap forcing
  status 0 on every path, and the file's own header explains why in detail (`:19-44`) — a non-zero exit
  from a Stop hook *is* a block, so any bash failure would wedge a session. This is the single
  highest-blast-radius file in the plugin per its own comment (`:12-17`); the new feature does not modify
  it, but any future change that *does* add a "carry `.claude/compound-v.json` into the sandbox too" flag
  to the new helper would need to respect this same fail-open contract when constructing a synthetic
  config for probing — a malformed synthetic `compound-v.json` must degrade to "rule silent," never to a
  hang or a spurious block.

## 4. External APIs (via context7)

None. The spec is explicit (§Decisions 1: "Bash 3.2 + git only; no python") and confirmed by reading the
sibling scripts and the plan (`tests/test-sandbox-checkout.sh` and `scripts/compound-v-sandbox-checkout.sh`
use only `git`, `cp`, `mkdir`, `find`-adjacent shell builtins). No third-party library, SaaS API, or SDK is
touched by this feature. Phase 1C (library/doc validator) has nothing to validate here beyond git's own
CLI surface (`git ls-files -z`, `git init`, `git commit`), which is not a versioned external dependency in
the sense Context7 tracks.

## 5. Regression Surface

- **`.github/workflows/validate.yml:227-230`** — the "Lint hook scripts with shellcheck" step runs
  `shellcheck hooks/*.sh` only. `scripts/*.sh` (where the new file lands) and `tests/*.sh` are never passed
  to `shellcheck` by CI. *If this regresses*: nothing regresses today — this is a pre-existing gap, not
  something the new feature breaks — but it means the plan's own acceptance bar ("shellcheck
  scripts/compound-v-sandbox-checkout.sh is clean") is enforced **only** by this run's manifest
  `impacted_map` rule (`manifest.yaml:25-26`, `when: scripts/compound-v-*.sh → shellcheck {path}`) at
  merge time, and by nothing at all for any future edit to this file made outside a Compound V dispatch
  (a direct commit, a hand-applied patch). A shellcheck regression introduced that way would ship silently.
- **`.github/workflows/validate.yml:344-361`** ("Run every test under tests/") — recursively discovers and
  runs every `*.sh`/`*.py` under `tests/`, fails loud if it discovers zero files. *If this regresses*:
  nothing to guard here — `tests/test-sandbox-checkout.sh` will be picked up automatically the moment it
  exists, no wiring required, and the "discovers zero" trip-wire (`:362-365`, written specifically because
  of the v2.14 incident where "25 of 29 selftests never ran") already protects against a future refactor
  silently dropping this file from the sweep.
- **`hooks/triage-prompt-nudge.sh` and `hooks/epic-goal-stop.sh` production behavior on the *real*
  checkout** — the new helper only reads (`git ls-files`, file copies); it never touches either hook file,
  the real `docs/superpowers/pre-eval/`, or the real `docs/superpowers/execution/`. *If the new script has
  a bug*: worst case is a malformed or partial sandbox at the caller's `<dest>` (outside the repo, per its
  own contract — "never writes outside `<dest>`; refuses a non-empty `<dest>`"), never a change to
  production hook behavior for real users. The blast radius of a defect in this feature is confined to
  whoever runs the helper by hand.
- **`agents/spec-reviewer.md` §3.3** — Task B adds one sentence inside the existing "evidence notes" prose
  that follows the "Read the evidence from the job result" table (`:184-192`). *If the sentence is wrong or
  overclaims* (see §1's precision gap): every future reviewer reading §3.3 for guidance on how to probe a
  live-run checkout inherits that overclaim, and may spend time trying to drive `hooks/epic-goal-stop.sh`
  in a sandbox that structurally cannot exercise it. Low blast radius (advisory prose, not enforcement),
  but a real, first-order cost: a future reviewer's time.
- **`CHANGELOG.md` / `.claude-plugin/plugin.json` / `.claude-plugin/marketplace.json`** — pure version-bump
  edits, same pattern as every prior release (`3.4.2` confirmed current in both JSON files). No regression
  surface beyond the ordinary "two parallel jobs both bump the version string" hazard, which the Partition
  Map already avoids by giving Task B exclusive `write_allowed` on all three files (no overlap with Task A).

## 6. DRY Findings

- **No existing script already does "copy every git-tracked file to a fresh location."** Searched
  repo-wide for `git ls-files` usage (59 hits) — every hit is either documentation/prose describing the
  *concept* (this spec, this plan, `AGENTS.md`, `skills/compound-v/execution-manifest.md`,
  `skills/compound-v/memory.md` describing the scope gate's *own* separate `git ls-files --others` use for
  untracked-file detection) or a **dogfood record of the same maintainer hand-building this exact recipe
  by hand three separate times** (`docs/superpowers/dogfood/2026-09-03-v3.4.1-triage-size-review-1.md:
  219-224`, `docs/superpowers/execution/2026-09-03-v3.4.1-triage-size-r3/jobs/spec-review.patch:431`, and
  the r4 patch's near-identical line). No script under `scripts/` implements it. This is a genuine gap, not
  a duplication risk — the spec is right that this is worth extracting, and there is nothing to refactor
  instead of adding.
- **The worktree-creation pattern in `compound-v-run-codex-worker.sh:397-409`** (capture baseline SHA,
  `git worktree add <path> HEAD`) is a *different* mechanism from what this feature builds (a worktree is
  a live, linked checkout sharing the same `.git`; the new helper's sandbox is a **fresh, independent**
  repository via `git init`, explicitly *not* a worktree — the spec is precise about this: "runs `git
  init` + one commit there"). Do not conflate the two; nothing here should be refactored to share code with
  the worktree path, because they solve different problems (isolation-for-execution vs.
  isolation-for-probing-hooks-that-themselves-look-for-a-worktree/lane-map's absence).
- **Existing bash-3.2 test files to match conventions against**: `tests/test-lane-guard.sh` (synthetic
  `PreToolUse` stdin against a sandboxed project tree — same *shape* of test as what
  `tests/test-sandbox-checkout.sh` needs, a temp dir + `mkdir -p` scaffold + `mktemp -d` + `trap 'rm -rf ...'
  EXIT`, `pass`/`fail`/`ok`/`bad`/`check` counters). No shared harness file exists to import from (each
  `tests/test-*.sh` is self-contained, confirmed by grep — no `source`/`.` of a common lib across the ten
  files in `tests/*.sh`), so writing `tests/test-sandbox-checkout.sh` self-contained matches every existing
  sibling rather than being a missed refactor opportunity.

## 7. Design constraints for the spec

- **The helper can never produce a sandbox where `.claude/compound-v.json` exists**, because that file is
  policy-committed "never in the plugin repo" (`commands/v-init.md:482`) and is therefore never a
  `git ls-files` path here. Consequently the helper **cannot** be used to probe either rule of
  `hooks/epic-goal-stop.sh` (the Stop-time triage gate or the pipeline-bypass rule) — only
  `hooks/triage-prompt-nudge.sh` (the UserPromptSubmit hook) is reachable. Task B's doc-note in
  `agents/spec-reviewer.md` §3.3 MUST name `hooks/triage-prompt-nudge.sh` specifically, not "the triage
  hook" generically — the manifest already dispatched for this run gets this right in its acceptance
  criteria; the doc-note must match it, not the spec's looser prose.
- **`--keep-execution` reproduces the "active run" signal `_has_active_run`/`compound-v-dashboard.py
  resume` reads (state.json, git-tracked), but can never reproduce the "resolved lane" signal
  `hooks/lane-guard.sh` reads (`lane-map.json`, permanently gitignored)** — these are two different
  mechanisms with two different git-tracking fates. If any future use of this helper is offered as a way to
  test `hooks/lane-guard.sh`'s enforcement path, that claim would be false; the spec and Task B's note
  should not imply the helper covers lane-guard probing.
- **Symlink handling under `cp -p` was not verified live** — this session's Bash access is clamped to only
  the V-memory script invocation (`bashCommandClamp`), which blocked running `git ls-files -s | awk
  '$1=="120000"'` to check for tracked symlinks in this repository. If any git-tracked symlink exists, GNU
  and BSD `cp -p` both follow it by default (copy the target's *content*, not a symlink), which would
  silently break the "byte-identical" contract for that one path. This is a genuine unknown, not a
  hand-waved one — the implementer or reviewer should run that check before treating "byte-identical" as
  proven for every path.
- **CI's shellcheck coverage does not extend to `scripts/*.sh` or `tests/*.sh`** (`.github/workflows/
  validate.yml:227-230` covers `hooks/*.sh` only). This run's own `manifest.yaml` `impacted_map` rule
  (`shellcheck {path}` when `scripts/compound-v-*.sh` changes) covers the new file *for this dispatch*, but
  a future direct edit to `scripts/compound-v-sandbox-checkout.sh` made outside Compound V would not be
  caught by CI. Not this feature's bug to fix, but worth the plan/spec author knowing the acceptance bar
  ("shellcheck clean") is a one-time gate, not a standing one.
- **`--taxonomy-from` is a deliberate, documented exception to "byte-identical"** — the spec already says
  so ("copies one file over `.claude/compound-v-impact-taxonomy.yaml`"), and this audit confirms it matches
  the real prior manual workflow (`docs/superpowers/dogfood/2026-09-03-v3.4.1-triage-size-review-1.md:
  279-284`, the counterfactual `content_scan_exclude` edit). No further constraint here beyond keeping the
  documentation honest that this one file is the sanctioned divergence, not a bug.
- **`docs/superpowers/execution/*/logs/*.jsonl` is gitignored** (`.gitignore:32`) — even `--keep-execution`
  will never carry a run's live Codex/Workflow event-stream JSONL into the sandbox. A probe that expects to
  find `logs/<job>.events.jsonl` inside a `--keep-execution` sandbox will not find it; only the committed
  audit trail (`manifest.yaml`, `state.json`, `results/*.json`, `receipts/*.json`) rides along.

## 8. File Touch Map

| File | Task | Change | Notes |
|---|---|---|---|
| `scripts/compound-v-sandbox-checkout.sh` | A (codex) | New | Bash 3.2, no third-party deps. Not a SHARED RESOURCE — new, single-owner file. |
| `tests/test-sandbox-checkout.sh` | A (codex) | New | Auto-discovered by CI's recursive `tests/` sweep (`.github/workflows/validate.yml:344-361`) — no wiring needed. Not shared. |
| `agents/spec-reviewer.md` | B (claude) | Edit — one sentence in §3.3's evidence-notes prose (`:184-192` area) | **SHARED RESOURCE**: an agent-instruction file read by every future review-gate job in this plugin; malformed frontmatter or a broken cross-ref here is caught by `lint-frontmatter.py` and the CI dead-link scan (`.github/workflows/validate.yml:234-267`), both of which run repo-wide, not scoped to this diff. |
| `CHANGELOG.md` | B (claude) | Edit — append `## [3.4.3] - 2026-09-03` | **SHARED RESOURCE**: append-only project history, single top-of-file insertion point every release touches; order matters (newest-first) though no other job in this manifest writes it concurrently. |
| `.claude-plugin/plugin.json` | B (claude) | Edit — `"version": "3.4.2"` → `"3.4.3"` | **SHARED RESOURCE**: single version registry read by the marketplace/install surface; validated by the manifest's own `impacted_map` rule (`jq empty`). |
| `.claude-plugin/marketplace.json` | B (claude) | Edit — same version bump | **SHARED RESOURCE**: same reasoning as `plugin.json`; the two must agree (both currently `3.4.2`, confirmed live). |

No file appears in two tasks' `write_allowed` (confirmed against `manifest.yaml:47-49` and `:64-68` —
disjoint, as the Partition Map requires).

## 9. Note on run state at time of audit, AND a live-reproduced blocking defect this audit ran into

A run directory for this exact feature already exists at `docs/superpowers/execution/2026-09-03-v3.4.3-
codex-sandbox-checkout/` (`manifest.yaml`, `state.json` at phase `PARTITION_VERIFIED`, all three jobs
`pending`, no worktree or session_id recorded yet — nothing has been dispatched). This audit was written
independently of that manifest's contents where the two could conflict; where they agree (the codex/
standard/gpt-5.6-terra resolution, the acceptance criterion naming `triage-prompt-nudge.sh` specifically)
it is noted as independent confirmation, not assumed correct because the manifest already says it.

**Blocking defect, reproduced live while trying to publish this audit to its intended repo path.**
Writing `docs/superpowers/archaeology/2026-09-03-v3-4-3-codex-sandbox-checkout.md` was denied by the
`Compound V lane guard` PreToolUse hook: *"job 'spec-review' is not allowed to write '…'. Its write_allowed
lane is: docs/superpowers/dogfood/2026-09-03-v3.4.2-transcript-watch-review-1.md. Resolved via
cwd->worktree."* That job/lane belongs to an **unrelated, already-BLOCKED prior run**
(`docs/superpowers/execution/2026-09-03-v3.4.2-transcript-watch/`, `state.json` `"phase": "BLOCKED"`,
`blocked_at: 2026-09-03T05:34:05Z`) — not this session, not this feature, not any job this session was
ever dispatched as.

Root-caused by reading both the resolver and the two candidate copies of the guard:

1. `hooks/lane-guard.sh:814-835 resolve_job()` has no `agent_id` match for this session (never
   `register-lane`d), so it falls to the `cwd->worktree` branch: it matches whichever `worktrees{}` entry
   my cwd is a subpath of. The stale run's `lane-map.json` records
   `"worktrees": {"/Users/oleg/Dev/superpowers-v": "spec-review"}` — the **bare project root**, because
   `spec-review` there was a `direct`-isolation job, and a direct job's recorded "worktree" is the checkout
   itself (`hooks/lane-guard.sh:884-885`'s own comment: *"a direct job's 'worktree' is the checkout, which
   always exists"*). Every possible cwd in this repository is a subpath of the project root, so this
   match is unconditional once selected.
2. `hooks/lane-guard.sh:725-742 run_is_terminal()` — read in full — exists **specifically** to filter out
   exactly this case: its own docstring names the prior incident *("both pre-flight auditors of the NEXT
   feature were denied their writes as 'job spec-review-3' of a run that had been MERGED for an hour
   (stage-3, finding 68)")* and its logic is `TERMINAL_PHASES = ("MERGED", "BLOCKED")` (`:722`) — and the
   stale run's own `state.json` phase is literally `"BLOCKED"`. **By the checked-out repo's own current
   source, `map_files()` should skip this directory entirely.** It did not.
3. Comparing the checked-out repo's `hooks/lane-guard.sh` against the installed plugin cache at
   `/Users/oleg/.claude/plugins/cache/superpowers-v-dev/superpowers-v/3.4.1/hooks/lane-guard.sh` (the path
   this agent's own system prompt names as the fallback location when the plugin is installed rather than
   checked out) settles it: **`grep -n "TERMINAL_PHASES|run_is_terminal"` against the 3.4.1 cached copy
   returns zero matches.** The terminal-phase filter — the fix for finding 68 — does not exist in that
   cached version at all. The PreToolUse hook actually enforcing on this live session is consistent with
   running the **older, cached 3.4.1 copy**, not the current checked-out repo's `hooks/lane-guard.sh`
   (which is past 3.4.2 and includes the fix). This reproduces the *same class* of bug finding 68 already
   named and fixed once in-repo — except this time the fix exists in the repo and simply is not the code
   actually running.
4. Consequence, stated precisely: **for as long as this session's hooks are served from a plugin cache
   older than the fix, and that stale BLOCKED run's `lane-map.json` is the most-recently-modified
   non-terminal-looking candidate under `docs/superpowers/execution/`, every Write/Edit call in this
   entire repository from this session is denied**, regardless of target path — the resolved lane
   (`/Users/oleg/Dev/superpowers-v` → `spec-review`) covers the whole checkout, and the one path it
   nominally allows (`docs/superpowers/dogfood/2026-09-03-v3.4.2-transcript-watch-review-1.md`) belongs to
   a different, already-finished feature. This is a genuine, reproducible, currently-active defect in the
   plugin-cache/checkout consistency story, not a false alarm and not something the archaeology agent
   caused or can fix by writing around it (the correct response, per the guard's own message, is to *"stop
   and report it rather than widen the lane"*).

**What this means for the deliverable.** The audit above is complete and stands on its own evidence; it
could not be placed at `docs/superpowers/archaeology/2026-09-03-v3-4-3-codex-sandbox-checkout.md` because
of this environment defect, not because of anything about the v3.4.3 feature itself. A full copy is saved
at the session scratchpad and handed to the user directly. Once the plugin cache is refreshed to a version
carrying the `run_is_terminal()` fix (or the stale `docs/superpowers/execution/2026-09-03-v3.4.2-
transcript-watch/lane-map.json` is retired by hand), the write should succeed unmodified.
