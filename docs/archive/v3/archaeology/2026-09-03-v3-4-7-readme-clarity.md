# v3.4.7 README clarity — Code Archaeology

Spec: `docs/superpowers/specs/2026-09-03-v3.4.7-readme-clarity-design.md`. This is a
docs-only feature (`README.md`, `docs/routing.svg`, `commands/v-init.md`,
`TROUBLESHOOTING.md`, `docs/superpowers/dogfood/README.md`), so "existing code" here
means: the scripts/hooks whose real behavior the prose must describe truthfully, and
the CI gates that will (or will not) catch a lie.

## Step 0 — V-memory

Three queries run (`README clarity rewrite length`, `routing.svg baseRef worktree`,
`lane guard ambient cost measurement`). All three returned near-exclusively **this
feature's own spec and a plan that already exists**:
`docs/superpowers/plans/2026-09-03-v3.4.7-readme-clarity.md` (already written, with a
Partition Map: Task 0 `index-refresh` → Task A `readme` (depends on 0) → Task B
`routing-svg` → Task C `init-baseref`). No prior archaeology audit or ADR touches this
exact ground. The most load-bearing hits were **dogfood review files, not prose docs**
— `2026-09-02-v3.4-native-first-review-6/7/8.md` (the lane-guard cost's own
measurement history) and `CHANGELOG.md` (findings 60 and 89, the `baseRef` mechanism's
full history) — both read in full below, since a recalled claim is evidence, not
authority, and the plan already drafted treats the spec as settled; I did not.

## 1. Matrix

**Dimension: which routing model a piece of prose/diagram describes, vs. what Engine C
(the default dispatcher since 3.0, the only one since 3.4 native-first) actually runs.**

| Model described | Vocabulary | Where it lives today | Matches Engine C's default path? |
|---|---|---|---|
| Pre-Evaluation → **fast path** vs. full pipeline → Orchestrator/Router → **full Opus / Sonnet solo / Sonnet+advisor** | "fast path", "advisor", "Codex / Opus (read-only · opt-in)" | `docs/routing.svg` (current, in full below) + README.md:59-67 ("How it routes the work") | Partially. The advisor box is real code (`skills/backend-launcher/adapter-advisor.md`) but README's own current text already admits "it is wired only on the residual `Task` dispatch path: Engine C ... emits no consult step, so on a default run the advisor does not fire." |
| **Triage-tier** model: `DIRECT` / `SCOPED` (`scoped_plus` flavor) / `FULL` | `compound-v-preeval.py`'s `DECISION_TO_TIER`, `/v:triage`, the `UserPromptSubmit` hook, the `Stop` triage gate | `hooks/triage-prompt-nudge.sh`, `hooks/epic-goal-stop.sh`, `commands/v-triage.md`, `skills/compound-v/routing-policy.md` | **Yes** — this is what scores every prompt in every session today (`triage-prompt-nudge.sh` runs the same scorer `/v:triage` does, once per session, and the `Stop` hook enforces coverage of it). |

`DECISION_FASTPATH` ("FASTPATH_ELIGIBLE") maps 1:1 to tier `DIRECT`
(`scripts/compound-v-preeval.py:144-155`) — "fast path" was not deleted, it was
**renamed and folded into the 3-tier vocabulary**. This is exactly why AC3 forbids the
words "fast path" and "advisor" on the redrawn SVG: not because the mechanisms are
gone, but because the diagram must stop presenting a *different, largely-inert-by-default*
model as if it were the current one. **New code (Task A/B) needs to handle this; the
current diagram and README prose do not** — they describe the pre-triage-tier world.

**Dimension: does a tier get a model-routing assignment at all (relevant to Task B's
"each box, which model")?**

| Tier | Manifest produced? | Model-routing table applies? | Source |
|---|---|---|---|
| `DIRECT` | **No** — "no manifest at DIRECT" | **No.** `routing-policy.md:444-448`: *"A `DIRECT` decision produces no manifest, so it never reaches this table — the steps below run for `SCOPED` and `FULL` only."* It is "an ordinary `git commit`" by whichever model is already running the session (`commands/v-triage.md:43-49`). | `skills/compound-v/routing-policy.md:444-448`, `commands/v-triage.md:43-49` |
| `SCOPED` (+ `scoped_plus` flavor) | Yes — manifest, run dir, scope gate, ONE combined review; recon + 3 pre-flights skipped | Yes | `scripts/compound-v-preeval.py` header comment |
| `FULL` | Yes — unchanged full pipeline | Yes | same |

**A box in the redrawn SVG that assigns DIRECT a specific model (Opus/Sonnet/Codex) is
fabricating a routing decision the code never makes.** Word it as "whichever model is
already in your session," not as a router output.

**Dimension: is a backend's adapter live-verified vs. actually dispatched in a real run
in this repo?**

| Backend | Adapter exists | CLI/flags live-verified (`/v:init` Step 1a-*) | `backend: <x>` ever appears in a committed `manifest.yaml` under `docs/superpowers/execution/` |
|---|---|---|---|
| `claude` | — (native) | n/a | 94 files, hundreds of hits |
| `codex` | `adapter-codex.md` | Yes (`codex exec --help` flag assertion) | Yes — stage 4 of the verification program (3.4.3, `backend: codex` on Engine C) |
| `antigravity` | `adapter-antigravity.md` | Yes (`agy models` probed live) | **Zero** hits for `backend: antigravity` anywhere in `docs/superpowers/execution/**/manifest.yaml` |
| `cursor` | `adapter-cursor.md` | Yes (`cursor-agent status`, `.result`/`.session_id` verified) | **Zero** hits for `backend: cursor` |
| `devin` | `adapter-devin.md` | Partial — flag/help surface live-verified; **task-execution behavior is "DOC-CLAIMED, unverified"** (`commands/v-init.md:144`) | Zero |
| `opencode` | `adapter-opencode.md` | Partial — auth path live-observed; worker behavior not run in this repo | Zero |

Spec item 3 says "opencode and Devin (experimental: adapters and workers exist, not
dogfooded)" but does not apply that caveat to Antigravity/Cursor. **The grep result is
identical for all four non-Claude/Codex backends: zero real dispatched jobs in this
repo's own history.** The distinction that *is* real is depth of live verification —
Antigravity/Cursor's CLI invocation shape is confirmed live; Devin/opencode's
*execution* behavior is explicitly marked unverified in `v-init.md` itself. If the
rewritten "Backends" section keeps "not dogfooded" as a distinguishing phrase for only
two of the four, that phrasing should be deliberate, not an oversight — the underlying
fact (never used as a real job's `backend:` in this repo) doesn't distinguish them.

## 2. Shared State

**`worktree.baseRef` (read by `scripts/compound-v-emit-workflow.py:_worktree_base_is_head`, lines 1379-1398, called at 1516 and 3803):**
- Set in: `<repo_root>/.claude/settings.json` → `{"worktree": {"baseRef": "head"}}`. THIS repo's own `.claude/settings.json` already carries it (read in full: exactly that one key).
- NOT the same file as `.claude/compound-v.json` (Compound V's own project config, written by `/v:init` Step 4a) — two separate JSON files, same directory. A new `/v:init` step must read-merge-write `.claude/settings.json`, a file `/v:init` has never programmatically touched before (its only prior mention of that file, Step 4c, is a prose *offer* to edit the user's own `~/.claude/settings.json` — a different, home-directory file, for an unrelated key). **No sibling code in this repo already does a JSON merge-write into a project-local `.claude/settings.json`** — Task C is writing the first one.
- Also NOT the same field as `baseRefName` in `skills/pr-review/SKILL.md:64` (a `gh pr view` JSON field naming a PR's base branch) — coincidental name collision, unrelated concept. Worth a one-line disambiguation if both terms could appear near each other in TROUBLESHOOTING.md.
- Effect when **absent** (current default, and the default for every project that hasn't run the new `/v:init` step): a job with `depends_on` and `isolation: worktree` gets `agent_isolation: None` → its agent runs **direct**, in the shared main checkout, not an isolated worktree (`compound-v-emit-workflow.py:1513-1517`).
- Effect when **`"head"`**: such a job gets a real worktree (`agent_isolation: "worktree"`), consistent with the manifest's declared isolation.

**Whether "absent" actually means "never merges" at current HEAD is not settled by
reading the code alone — flag this before it is asserted in `TROUBLESHOOTING.md`:**
- **Finding 60** (stage-2 r2, already shipped): before this fix, a dependent job ran
  direct (3.0.5 rule) but the **finalizer read the manifest's `isolation: worktree`
  label** and refused with "resolves to no worktree." The fix made the finalizer trust
  the **gate receipt** instead of the manifest label, specifically so the no-`baseRef`
  path would stop refusing.
- **Finding 89** (already shipped in 3.4.6 = current HEAD, per `plugin.json`): a
  *different* bug, found *after* finding 60 — even **with** `baseRef: head` set (so the
  job legitimately ran in a real worktree), three components (Record, the authority,
  the finalizer) still carried a hardcoded "dependent ⇒ direct" assumption, wrote an
  empty worktree into state, recomputed an empty diff ("forged"), and the finalizer
  refused anyway. Finding 89's fix: "**All three now read the gate receipt first —
  the emitter's own `--mode` and `--worktree`, digest-bound — with the baseRef-aware
  rule as the fallback**" (`CHANGELOG.md:190`).
- Read literally, finding 89's fix makes the receipt authoritative on **both** paths
  (with or without `baseRef`), which suggests a dependent job may now integrate either
  way — the concrete cost of leaving `baseRef` unset may be **loss of worktree
  isolation for that job** (it edits the shared checkout directly, alongside whatever
  else is running in the same wave) rather than a hard "never merges." No dogfood file
  reproduces the no-`baseRef` case post-finding-89 (searched `docs/superpowers/dogfood/`
  for `baseRef` — zero hits). **Verify the actual current failure mode (integration
  refusal vs. silent isolation loss vs. a wave-concurrency race between multiple
  direct-mode dependent jobs) before writing `TROUBLESHOOTING.md`'s symptom line**,
  rather than repeating finding 60's pre-finding-89 description verbatim.

**Dogfood index numbers (`docs/superpowers/dogfood/README.md`'s footer, read by
spec AC2 and README's "Verification program" section):**
- Set by: `scripts/compound-v-dogfood-index.sh`, scanning `docs/superpowers/dogfood/*review*.md` (glob per the script's own filename pattern, not a naive substring match).
- Current committed footer: `Reviews: 36 · APPROVED: 5 · ISSUES: 26 · other: 5`, last row dated `2026-09-03 | v3.4.2-transcript-watch | 3 | APPROVED`.
- **This footer is already stale relative to the directory it indexes.** A `Glob` over `docs/superpowers/dogfood/*review*.md` returns files the committed index does not list at all: `v3.4.3-codex-sandbox-checkout-review-{1,2}.md`, `epic-vi-review-index-review-{1,2}.md`, `epic-vi-readme-section-review-{1,2}.md`, `epic-vi-integration-review.md`, `v3.4.5-recall-freshness-review-{1,2}.md`, `v3.4.6-triage-test-scoping-fixes-review-{1,2}.md` — twelve additional review files, at least four of them independently confirmed `APPROVED` by filename/content already read (`epic-vi-integration-review.md`, `epic-vi-readme-section-review-2.md`, `epic-vi-review-index-review-2.md`, `v3.4.3-codex-sandbox-checkout-review-2.md`).
- This is exactly the self-referential staleness the epic's own `readme-section.md` spec already named: "*every review file lands in `docs/superpowers/dogfood/` after the index that counts it, so the committed footer is always one behind the last review — regenerate with the script rather than trust the number*." **Confirmed, concretely, not just in principle: the drift right now is at least 12 files / several APPROVED counts, not a rounding error.** Task 0 (`index-refresh`) is not a formality; the numbers Task A writes will differ substantially from what this very audit (or a careless implementer eyeballing HEAD) would type from memory.
- Gap risk for the plan: **Task A must read the *regenerated* footer at write time**, and must not hardcode any number seen in this archaeology report either — by the time Task A's worker runs, Task 0 will have added still more rows (v3.4.6 and any review this very v3.4.7 feature itself accumulates before Task A's job commits).

**Stop hook's actual gate set (read by spec item 8's "hooks that run in every session" table):**
- `hooks/epic-goal-stop.sh`'s own header states plainly: "*The armed-epic-goal rule that used to run first in this file was REMOVED in 3.4.0, because Claude Code's own `/goal` covers it ... `commands/v-epic.md` §0d now offers that native goal instead of arming one here.*" The hook's live decision table (read in full) is now exactly two gates: (1) `triage_gate` (on by default, 3.2.0+), (2) `pipeline_bypass` (off by default). No epic-goal rule remains in this file.
- **`commands/v-init.md:605-607` (Step 4a documentation) has not caught up**: it still reads "*The armed **epic goal** rule in the same hook is not configured here — it is armed per-epic by `/v:epic` §0d and lives in `epic-state.json`*," which describes the **pre-3.4.0** hook (three gates), not the current one (two gates). This is a real, independently-discovered staleness in a file the README rewrite is *also* touching (Task C) — worth fixing in the same pass, or at minimum not copying this stale sentence into the new README hooks table. **The README's "Stop → triage gate" row is accurate on its own terms but should not describe the same hook as doing three things when the shipped code does two.**

## 3. Sibling Code

**`skills/compound-v/routing-policy.md` — the table Task B's "which model" column must be drawn from.** Entry condition: reached only for `SCOPED`/`FULL` manifests (a `DIRECT` decision "never reaches this table," line 444-448, quoted above). Inputs: job `type`, `tier`, sensitivity of the touched path. Edge case already flagged in the file itself, line 449, as a live naming hazard: "*the scorecard's ... vocabulary collision*" between the tier-scorer's own internal terms and this table's — read the surrounding paragraph before summarizing the routing table in one sentence, since a naive one-liner risks reproducing that exact collision. Latent staleness: line 564 still uses **pre-tier-rename vocabulary** — "a fast-path Claude worker (a job the pre-eval offered as `FASTPATH_ELIGIBLE`)" — i.e. `routing-policy.md` itself has not been fully migrated off "fast-path" language, which is direct evidence the SVG/README aren't the only stale artifacts describing this mechanism; do not treat `routing-policy.md`'s current wording as automatically authoritative phrasing to copy verbatim.

**`.github/workflows/validate.yml`'s "Check for dead intra-plugin cross-refs" step — the sibling AC2's "dead-link gate replica exits 0" must actually replicate.** Entry condition: runs on every push/PR, as the FINAL CI step (deliberately last, "so cross-refs to files authored by later batches resolve at integration time"). It is **not** a naive `grep -oE '\]\([^)]+\)'`: (a) it strips fenced code blocks and inline code spans **first** (finding 95, already fixed — a prior version without this step false-failed on nine quoted `[x](path)` examples inside review prose); (b) it only checks `.md/.py/.sh/.json/.yml/.yaml` link targets — **`.svg` is not in the pattern**, so a broken `docs/routing.svg` reference would **not** be caught by this gate, only by AC3's own XML-validity check; (c) it accumulates failures into a temp **file**, not a shell variable, specifically because the inner loop runs in a subshell (a documented historical bug: assigning `fail=1` inside the subshell silently never propagated). A reviewer hand-rolling a "replica" of this check as a quick grep one-liner will reproduce the exact bug this step was hardened against unless they read it first.

**`commands/v-init.md`'s Step 4c — the only existing precedent for "offer, never write silently" on a settings file.** Entry condition: user opts in explicitly ("Shall I show you the edit?"). It edits `~/.claude/settings.json` (global, user-level), not a project file, and it is pure prose — no merge algorithm exists in this codebase to point at. Task C's new baseRef-offer step is materially different (project-local `.claude/settings.json`, needs read-merge-write logic that preserves unrelated keys like `permissions`/`hooks`/`env` a real project may already have) and has **no working sibling implementation to copy** — the nearest analog (`/v:init` Step 4a, writing `.claude/compound-v.json`) is a different file and, per its own text, is documented as *never* adding fields that could look machine-local (v2.6.2 lesson) — a caution worth carrying into the new step even though it targets a different file.

**`docs/routing.svg` (current) — read in full, since Task B redraws it.** It is not a stale copy of the new model; it is a **complete, self-consistent diagram of a different model** (Pre-Evaluation → Fast path / Orchestrator+Router → Full Opus / Sonnet solo / Sonnet+advisor), including an accessibility `<title>`/`<desc>` pair (lines 2-3) that also needs rewriting — AC3's "text nodes name DIRECT, SCOPED, SCOPED+, FULL, Opus, Sonnet, Codex" plainly includes these two elements, not only the visible `<text>` glyphs, since a naive XML-text-content check (`xmllint`/`ElementTree`, per AC3's own wording) would read `<desc>` too.

## 4. External APIs

None. This feature touches no third-party service, SDK, or library — it edits Markdown, one SVG, and a command doc, and reads two local scripts' behavior. Phase 1C (doc-validator / Context7) has nothing to verify here; I confirmed this by finding zero library/API surface in the spec's "Files" list and zero new imports/dependencies implied by any of the ten "What changes" items.

## 5. Regression Surface

| Existing path | Breaks if... | Who is affected |
|---|---|---|
| CI "Verify plugin.json and marketplace.json versions match" + CHANGELOG lockstep guard (`validate.yml:43-81`) | This feature ships without a paired version bump / CHANGELOG entry, *if* it is tagged as a release rather than folded into an unreleased batch. Repo convention (git log: `release: vX.Y.Z` as its own commit, separate from feature commits) suggests this is handled by a later, separate commit — the plan's own Partition Map has no version-bump task, consistent with that convention. Flag, do not block. | Anyone merging to `main` |
| `scripts/lint-frontmatter.py` CLASS_COMMAND gate on `commands/v-init.md` | Task C adds body content only (no frontmatter touched); frontmatter presence/validity is unaffected. Low risk, confirmed by reading the linter's rules (commands are exempt from `name`/`description`, only need a valid frontmatter block, already present). | CI |
| CI dead-link gate | A new/edited relative link in README.md, TROUBLESHOOTING.md, or `commands/v-init.md` that doesn't resolve, **and** is not a leading-slash link (leading-slash links are silently exempt — the epic's own `readme-section.md` spec flags this explicitly and pins "root-relative without a leading slash" as an acceptance criterion for its own link; the same trap applies to any new link this feature adds). | Every future contributor relying on the gate being exhaustive |
| `docs/superpowers/dogfood/README.md`'s committed content | Task 0 regenerates it; if Task A's job runs on a stale read (before Task 0's commit is visible to it) the two numbers it writes into README.md will already be wrong at merge time. The Partition Map already encodes `A depends_on 0` — confirmed necessary, not optional, given the 12-file drift measured above. | Every reader of the Verification program section until the next regeneration |
| `hooks/triage-prompt-nudge.sh` / `hooks/epic-goal-stop.sh` real behavior vs. README's new one-line "how to turn it off" | If the new hooks table or off-switch line is copied from `commands/v-init.md`'s Step 4a prose (which itself has the epic-goal staleness noted above) rather than re-derived from the current hook source, the README ships the same staleness one file earlier in the reading order. | Every new user's first read of README |
| Nothing runtime-facing. This is the whole feature: docs, one diagram, one opt-in prompt-time offer. No hook, script, or manifest schema is edited. | — | — |

## 6. DRY Findings

- **README.md and AGENTS.md currently carry a byte-identical ~950-word "measurement essay"** (README.md lines 16-29 vs. the equivalent block in `AGENTS.md`, compared verbatim — same sentences, same numbers, same bash reproduction snippet). Spec item 1 already directs the fix: cut it from README.md, keep AGENTS.md as the sole canonical copy, link instead of duplicate. Confirmed real, confirmed the fix direction is correct — no further decision needed here.
- **No prior script or command already read-merges `.claude/settings.json`** (see Sibling Code above) — Task C is not duplicating an existing merge-writer; it's the first one. Nothing to refactor, just something to write carefully (test against a settings.json that already has `permissions`/`hooks` keys, not just the empty-or-minimal case this repo's own `.claude/settings.json` happens to be).
- **Tasks A (`readme`) and B (`routing-svg`) both independently derive the same DIRECT/SCOPED/SCOPED+/FULL model from `scripts/compound-v-preeval.py`, dispatched in parallel with no `depends_on` between them.** This is not a file-write duplication (the manifest partitioning is fine — disjoint files) but a **content-consistency risk**: two different workers, reading the same source independently, describing the same three-tier model in prose (Task A) and in diagram labels (Task B), with no shared draft between them. A mismatch (e.g., Task A's prose says SCOPED+'s cross-model review is "recommended" while Task B's diagram legend implies "mandatory," or vice versa — it genuinely is mandatory per `_needs_cross_model_review`'s docstring in `compound-v-preeval.py`) would ship two documents that disagree with each other, not just with the code. Not a code duplication in the traditional DRY sense, but the same failure mode: two independent restatements of one truth, parallel-dispatched, with nothing forcing them to agree.

## 7. Design constraints for the spec

- **DIRECT gets no model-routing entry.** `routing-policy.md:444-448` is explicit that a `DIRECT` decision never reaches the model-routing table; it's "an ordinary `git commit`" by whichever model is already in the session. The redrawn SVG/prose must not invent a DIRECT→<model> assignment.
- **"Fast path" and "advisor" are not deleted mechanisms — they are superseded framings.** `DECISION_FASTPATH` *is* tier `DIRECT` under the hood; the advisor pattern still exists in code (`adapter-advisor.md`) but doesn't fire on Engine C's default path. Word the change as "the current default path is described in DIRECT/SCOPED/FULL terms, not fast-path/advisor terms" — not as "these features were removed."
- **Verify the current (post-finding-89) no-`baseRef` failure mode before writing `TROUBLESHOOTING.md`'s symptom sentence.** The code and CHANGELOG evidence gathered above supports "loses worktree isolation" at least as plausibly as "never merges" for the current HEAD state; reproduce it (or find an existing reproduction) rather than carry forward finding 60's pre-finding-89 description.
- **Task A must read the dogfood index footer *after* Task 0 has actually committed, not trust any number seen during planning or archaeology** — the drift measured here (36→48+ files, 5→9+ APPROVED, at minimum) is real and current, and will keep moving as this very feature's own dogfood reviews land.
- **`.claude/settings.json` and `.claude/compound-v.json` are two different files; the new `/v:init` step targets the former (`worktree.baseRef`), the existing Step 4a targets the latter.** Any merge-write into `.claude/settings.json` must preserve unrelated keys (`permissions`, `hooks`, `env`, etc.) that a real project's file may already carry — this repo's own copy (just the one key) is not a representative test fixture.
- **`docs/routing.svg`'s `<title>`/`<desc>` need rewriting too, not just the visible `<text>` elements** — AC3's XML-text-node check will read them.
- **`commands/v-init.md:605-607`'s epic-goal-rule description is stale against the current `hooks/epic-goal-stop.sh` (post-3.4.0).** Since Task C already edits this file, this is a low-cost opportunity to fix it in the same pass rather than let the new hooks table (spec item 8) risk copying the stale three-gate description.
- **Give Tasks A and B (parallel, both deriving the tier model independently) one shared, literal source sentence per tier** (e.g. lift the exact SCOPED+ mandatory-review wording from `compound-v-preeval.py`'s own docstring) so the prose and the diagram cannot silently disagree on a detail like SCOPED+'s review being mandatory vs. advisory.
- **The line-length AC (no line over 200 chars) is not free-standing prose advice — it requires actual hard-wrapping.** The current README's long paragraphs (e.g. the measurement essay, ~950-1400+ characters per physical line with no wrapping) are exactly the shape this check exists to catch; every paragraph the rewrite keeps must be wrapped, not merely shortened in word count.
- **The ≤130-line budget is tight against the net new content required**, not just the essay removal. Current file: 153 lines. Essay removal (~16 lines → ~3) frees roughly 13 lines. Spec items 2, 3, 7, 8, 9 each add genuinely new material not present today: a hooks table (new, ~6-10 rows), an 8-stage one-sentence list (new), 2 more named backends + an experimental caveat (new), the `baseRef` JSON block (new), a triage-tier description replacing the fast-path one (net new prose, old prose removed). Budget every addition against a concrete cut; do not assume the essay's removal alone buys the room.
- **`.svg` targets are exempt from the CI dead-link gate** (only `.md/.py/.sh/.json/.yml/.yaml` are checked) — AC3's own XML-validity check is the *only* automated guard on `docs/routing.svg` actually existing and parsing; treat it as load-bearing, not a formality.

## 8. File Touch Map

| File | Nature | Notes |
|---|---|---|
| `README.md` | Hand-authored prose | Depends on `docs/superpowers/dogfood/README.md` being regenerated first (numbers). Also implicitly depends on `docs/routing.svg`'s *content* agreeing with its own "How it routes the work" prose (see DRY finding above) even though the two are file-disjoint. |
| `docs/routing.svg` | Hand-authored diagram (not codegen) | Not a SHARED RESOURCE in the generated-file sense, but its accessibility text (`<title>`/`<desc>`) is in scope for AC3 same as the visible glyphs. `.svg` links are invisible to the CI dead-link gate. |
| `commands/v-init.md` | Command doc, frontmatter-gated (`CLASS_COMMAND` in `lint-frontmatter.py`) | Frontmatter itself untouched by the planned change (body-only edit). Also carries the independently-discovered stale epic-goal-rule sentence at lines 605-607 (not required by this spec, but same file, cheap to fix in the same pass). |
| `TROUBLESHOOTING.md` | Plain prose, no frontmatter gate | New entry only; no existing entry to reconcile/replace. |
| `docs/superpowers/dogfood/README.md` | **SHARED RESOURCE — generated file.** Regenerated by `scripts/compound-v-dogfood-index.sh`, idempotent (F1's own acceptance criterion: byte-identical on a second run). Must run and commit before `README.md` (Task A) reads its footer — the Partition Map's `depends_on` here is load-bearing, confirmed by the measured ~12-file drift, not a defensive formality. |

No manifest schema, hook registration, or script logic changes in this feature — the
File Touch Map is exactly the five files/dirs above, all in `docs/` (plus one
`commands/` doc), with the one real ordering dependency (dogfood index → README) and
one soft consistency dependency (routing.svg content ↔ README prose) that a disjoint
Partition Map cannot express structurally and the plan should call out explicitly.
