# Research-Grounded Brainstorm (v2.7.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Under Compound V this plan dispatches via the execution manifest.

**Goal:** Add Trigger 0 (pre-brainstorm recon) and batched-elicitation guidance to Compound V, with config/capability wiring, a CHANGELOG↔manifest CI guard, and version 2.7.0 — all as description-driven guidance, zero upstream edits, zero new servers/agents.

**Architecture:** Docs + config + CI feature. Two new reference docs under `skills/compound-v/`, edits to the central SKILL.md and its satellites (hooks, v-init, 1B/1C phase docs, AGENTS/README), one new CI step, three version-string bumps.

**Tech Stack:** Markdown guidance docs, bash hooks, GitHub Actions YAML, jq/grep.

**Spec:** `docs/superpowers/specs/2026-07-10-research-grounded-brainstorm-design.md` (ACs 1–13 govern the review gate).
**Audits (read before implementing your task):**
- `docs/superpowers/archaeology/2026-07-10-research-grounded-brainstorm.md` (line-precise slots)
- `docs/superpowers/expert/2026-07-10-research-grounded-brainstorm.md` (12 UX constraints §7)
- `docs/superpowers/library-audit/2026-07-10-research-grounded-brainstorm.md` (verified contracts §7)

## Global Constraints

- Version moves in THREE places together: `plugin.json`, `marketplace.json`, `CHANGELOG.md` top heading → **2.7.0**.
- `skills/compound-v/SKILL.md` `description:` frontmatter MUST stay **≤500 chars** total (410 used; CI hard-fails).
- No token/cost numbers anywhere (anti-ruflo CI gate greps for them).
- No new `agents/*.md`, no upstream Superpowers file edits, no new servers.
- Committed policy vs machine-local capability split (v2.6.2): `brainstorm.*` keys → `.claude/compound-v.json` (Step 4a); `deep_research` presence → `~/.claude/compound-v-capabilities.json` (Step 4b).
- Readers own config defaults: `deep_research` → `"ask"`, `batch_elicitation` → `true` (pre-v2.7 configs have no `brainstorm` block; nothing validates that file).
- Recon is EVIDENCE, never a routing input. Gate-2 recall uses `compound-v-memory.py search`, never `recall-check`.
- Markdown links from SKILL.md to the two new docs are CI-dead-link-checked — all land in this same branch.

## Shared Interface Contract (all tasks — exact names)

- New files: `skills/compound-v/phase-0-recon.md`, `skills/compound-v/brainstorm-elicitation.md`.
- Config keys: `brainstorm.deep_research` = `"ask"|"auto"|"off"` (default `"ask"`), `brainstorm.batch_elicitation` = `true|false` (default `true`).
- Capability key: `"deep_research": true|false` in `~/.claude/compound-v-capabilities.json` — **advisory hint only**; the runtime contract is a live available-skills-listing check at fire time.
- Recon output: `docs/superpowers/recon/YYYY-MM-DD-<topic>.md`, ≤150 lines, section order: anti-anchoring header → QUESTIONS TO ASK (mistakes-to-avoid framing) → FACTS / CONSTRAINTS → SUGGESTED DIRECTIONS (≥2–3 divergent, non-exhaustive, single recommendation forbidden, never suppressed) → SOURCES.
- Gate order (Trigger 0): 1 plumbing-skip (reuse 1B/SKILL skip wording) → 2 KB-hit (`python3 scripts/compound-v-memory.py search "<topic>" --top 8 --json`, from repo root) → 3 config (`ask|auto|off`).
- Engine ladder: A `deep-research` via skill/slash interface (never `Workflow({...})` hardcode, never a version gate) → B ≤6 parallel WebSearch in one message → C skip with explicit notice. Non-blocking always.
- Batch gate (elicitation): (1) ≥3 independent questions AND ≤5 groups/screen, (2) companion already accepted this session, (3) `batch_elicitation != false`. Tiebreak: **when unsure → sequential**; independence = answer interaction, not surface topic.
- Anti-anchoring header template (verbatim, used by Task 1; referenced by Task 3):
  > *This recon is evidence to widen the brainstorm's questions, not a conclusion to converge on. Treat FACTS/CONSTRAINTS as binding; treat SUGGESTED DIRECTIONS as some of several possibilities — generate alternatives that ignore them.*
- `ask`-mode offer copy skeleton (verbatim band, no token numbers): *"I can run a quick research pass before we brainstorm — either one deep-research pass (usually several minutes, spawns subagents) or up to 6 parallel web searches (usually under a couple of minutes). Note: this sends the topic text to external search services."* Options: run full / run with narrowed scope (user refines topic) / skip.

## Partition Map (disjoint write sets — verified)

| Task | Files (write-allowed) |
|---|---|
| 0 (serial) | `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `CHANGELOG.md`, `.github/workflows/validate.yml`, `.gitignore` |
| 1 | `skills/compound-v/phase-0-recon.md` (create), `skills/compound-v/skill-escalation.md` |
| 2 | `skills/compound-v/brainstorm-elicitation.md` (create) |
| 3 | `skills/compound-v/SKILL.md`, `hooks/session-banner.sh`, `hooks/plan-saved-nudge.sh` |
| 4 | `commands/v-init.md` |
| 5 | `skills/compound-v/phase-1b-domain-expert.md`, `skills/compound-v/phase-1c-documentation-validation.md`, `AGENTS.md`, `README.md` |

No file appears twice. Tasks 1–5 run in parallel after Task 0.

---

### Task 0: Version lockstep + CHANGELOG + CI guard (serial shared foundation)

**Files:** Modify `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `CHANGELOG.md`, `.github/workflows/validate.yml`, `.gitignore`

**Interfaces — Produces:** version `2.7.0` in all three places; the CHANGELOG guard other tasks' CI runs will pass through.

- [ ] **Step 1:** Bump `"version": "2.6.4"` → `"2.7.0"` in `.claude-plugin/plugin.json` and in `.claude-plugin/marketplace.json` (the `plugins[0].version` field).
- [ ] **Step 2:** Add the CHANGELOG entry ABOVE the `[2.6.4]` heading, matching the existing heading format exactly (separator is an em-dash `—`, U+2014):

```markdown
## [2.7.0] — 2026-07-10

### Added
- **Trigger 0 — pre-brainstorm recon** (`skills/compound-v/phase-0-recon.md`): when a brainstorm is about to begin on an unfamiliar topic, a gated, bounded research pass (bundled `deep-research` if present, ≤6 parallel WebSearch otherwise, skip-with-notice if neither) writes an anti-anchoring recon doc to `docs/superpowers/recon/` that the brainstorm — and later pre-flights 1B/1C — read first. Gate order: plumbing-skip → V-memory KB hit → `brainstorm.deep_research` config (`ask` default / `auto` / `off` hard kill-switch). Recon is evidence, never a routing input. Description-driven with zero hook backstop — weaker than Triggers 1–3, documented as such.
- **Batched elicitation** (`skills/compound-v/brainstorm-elicitation.md`): ≥3 *independent* questions (≤5 groups/screen, never a grid) may batch into ONE Visual Companion form screen — reusing upstream's companion server as-is, only if the user already accepted it this session. Independence is judged on answer interaction; when unsure → sequential. Deliberately overrides upstream's "text questions → terminal" rule for this narrow case, and says so.
- **`/v:init`**: `brainstorm.deep_research` + `brainstorm.batch_elicitation` policy keys (committed config) and a `deep_research` presence probe (machine-local capabilities cache, advisory only — fire-time listing check is the contract).
- **CI guard:** CHANGELOG top version must equal `plugin.json` version — closes the bug class where v2.6.4 shipped with both manifests still at 2.6.3 (the bump was written but never committed, and manifest-vs-manifest lockstep can't see it).

### Fixed
- Pre-flight phase docs 1B/1C now read `docs/superpowers/recon/` before opening new searches (deepen, don't repeat).
- `skills/compound-v/skill-escalation.md` reconciled with Trigger 0's earlier deep-research use (previously claimed deep-research fires only past 1B/1C).
```

- [ ] **Step 3:** In `.github/workflows/validate.yml`, directly after the existing "Verify plugin.json and marketplace.json versions match" step (L43-52), add:

```yaml
      - name: Verify CHANGELOG top version matches plugin.json (lockstep guard)
        run: |
          PLUGIN_VERSION=$(jq -r .version .claude-plugin/plugin.json)
          CHANGELOG_VERSION=$(grep -m1 -oE '^## \[[0-9]+\.[0-9]+\.[0-9]+\]' CHANGELOG.md | tr -d '#[] ')
          if [ "$PLUGIN_VERSION" != "$CHANGELOG_VERSION" ]; then
            echo "::error::CHANGELOG top entry ($CHANGELOG_VERSION) != plugin.json version ($PLUGIN_VERSION). Bump plugin.json, marketplace.json AND the CHANGELOG heading together."
            exit 1
          fi
```

  (Deliberately matches only the `## [x.y.z]` prefix — never the date separator — so the em-dash cannot bite; first match top-down = newest entry.)
- [ ] **Step 4:** In `.gitignore`, after `!docs/superpowers/memory/`, add the parity line `!docs/superpowers/recon/` with the same one-line comment style used by its neighbors (defense-in-depth; recon docs must stay visible to the scope gate).
- [ ] **Step 5:** Verify locally:

```bash
jq -r .version .claude-plugin/plugin.json                       # → 2.7.0
jq -r '.plugins[0].version' .claude-plugin/marketplace.json      # → 2.7.0
grep -m1 -oE '^## \[[0-9]+\.[0-9]+\.[0-9]+\]' CHANGELOG.md | tr -d '#[] '  # → 2.7.0
```

- [ ] **Step 6:** Commit: `release(v2.7.0): version lockstep + CHANGELOG + CHANGELOG↔manifest CI guard`.

---

### Task 1: `phase-0-recon.md` (create) + `skill-escalation.md` reconcile

**Files:** Create `skills/compound-v/phase-0-recon.md` · Modify `skills/compound-v/skill-escalation.md`

**Interfaces — Consumes:** Shared Interface Contract (gate order, engine ladder, recon doc template, offer copy). **Produces:** the authority doc Task 3's SKILL.md links to as `[phase-0-recon.md](phase-0-recon.md)`.

- [ ] **Step 1:** Author `skills/compound-v/phase-0-recon.md` (~120–170 lines) with these sections, in order:
  1. **Purpose + honesty boundary** — recon grounds the brainstorm; it is *evidence to widen questions*, never an approach-selector, never a routing input. State plainly: description-driven, **zero hook backstop** (fires before any file exists), weaker than Triggers 1–3.
  2. **Gate order** — the three gates verbatim from the contract, each with its skip behavior. Gate 1 reuses the existing plumbing classification wording (quote from SKILL.md skip rules); gate 2 shows the exact shell-out `python3 scripts/compound-v-memory.py search "<topic>" --top 8 --json` run from the repo root, with the strong-hit rule (a hit whose doc covers the same domain/topic ⇒ hand those docs to the brainstorm instead of running recon); gate 3 documents `ask|auto|off` incl. the verbatim offer copy from the contract (qualitative cost, egress note, scope-narrowing option) and `off` as a hard kill-switch honored for cost AND confidentiality.
  3. **Engine ladder** — A: `deep-research` through the skill/slash interface only (never a hardcoded `Workflow({...})` call, never a version gate; live listing check at fire time is the contract; the `/v:init` capability flag is an advisory hint). Explicitly: deep-research returns its report **as a message and writes no files** — the caller trims to the recon format and writes the doc. B: ≤6 parallel WebSearch in ONE message. C: skip with explicit notice. Never block or delay the brainstorm's first question.
  4. **Output contract** — path `docs/superpowers/recon/YYYY-MM-DD-<topic>.md`; the five-section template INCLUDING the verbatim anti-anchoring header from the contract; ≥2–3 divergent directions, single recommendation forbidden, DIRECTIONS never suppressed; QUESTIONS framed as mistakes-to-avoid; ≤150 lines; NO token/cost numbers; **write then `git add` + `git commit` immediately** (v2.6.4 discipline — uncommitted recon vanishes on worktree cleanup and never indexes into V-memory).
  5. **Relationship to 1B/1C** — recon is reconnaissance, pre-flights are the audit; they read recon first and deepen, never repeat. Recon never substitutes for either.
- [ ] **Step 2:** In `skills/compound-v/skill-escalation.md`, extend the deep-research guidance (around L21/L49/L62 — see archaeology §6.1): add a short "Trigger 0 recon" note that recon is a *second, earlier, gated* deep-research use (pre-brainstorm, before 1B/1C exist) with its own gates and logging in `phase-0-recon.md`; reword the "escalates past 1B/1C, not instead of them" sentence so it applies to the *mid-pipeline escalation* path specifically and no longer contradicts Trigger 0. Do not weaken the mid-pipeline rule itself.
- [ ] **Step 3:** Verify: `grep -n "recon" skills/compound-v/skill-escalation.md` shows the reconcile; `wc -l skills/compound-v/phase-0-recon.md` ≤ ~180; `grep -inE "token|cost \$|budget_tokens" skills/compound-v/phase-0-recon.md` shows no cost claims.
- [ ] **Step 4:** Commit: `feat(recon): phase-0-recon.md — Trigger 0 procedure + skill-escalation reconcile`.

---

### Task 2: `brainstorm-elicitation.md` (create)

**Files:** Create `skills/compound-v/brainstorm-elicitation.md`

**Interfaces — Consumes:** Shared Interface Contract (batch gate, tiebreak, fallback ladder). **Produces:** the doc Task 3's SKILL.md links to as `[brainstorm-elicitation.md](brainstorm-elicitation.md)`.

- [ ] **Step 1:** Author `skills/compound-v/brainstorm-elicitation.md` (~100–150 lines):
  1. **The classification rule** — dependent chain vs independent batch; independence judged on *answer interaction* (could any answer change, contradict, or over-subscribe another — including via an unshown shared budget?), not surface topic; **when unsure → sequential**. Include ≥3 verbatim misclassification examples from the 1B audit §4 list (name-vs-CLI-prefix, format-vs-schema, the coupled-toggles budget case at minimum).
  2. **The 3-condition batch gate** — from the contract, incl. the ≤5 groups/screen ceiling, no matrix/grid ever, groups answerable in any order with no shared rating scale, an open-ended "other / none of these" escape hatch per group.
  3. **The upstream override, stated honestly** — quote upstream's rule (*"Use the terminal for content that is text — requirements questions, conceptual choices, tradeoff lists…"*, from superpowers brainstorming SKILL.md / visual-companion.md) and state this doc deliberately overrides it for the independent-batch case only, via the same description-driven mechanism (same reliability caveat) as Compound V's other interceptions. Never force-open the browser; upstream's just-in-time offer etiquette is inviolable (condition 2 exists for exactly this).
  4. **Rendering contract** — reference the companion by its stable contract, not a version pin: one form screen per batch; `.options` container with `data-multiselect` where checkbox-semantics apply; `data-choice` + `onclick="toggleSelect(this)"`; answers read from `$STATE_DIR/events` (JSONL, cleared per screen push, absent ⇒ user didn't interact) merged with the user's terminal reply, terminal text primary.
  5. **Fallback ladder** — companion declined/absent → ONE `AskUserQuestion` call sized to its caps (≤4 questions, 2–4 options each, headers ≤12 chars, `multiSelect: true` for checkbox groups); overflow beyond 4 → continue one-at-a-time; no interactive surface → one-at-a-time terminal (upstream default). Dependent questions NEVER enter any batch surface.
- [ ] **Step 2:** Verify: file exists, `grep -c "when unsure" skills/compound-v/brainstorm-elicitation.md` ≥ 1, no token/cost numbers.
- [ ] **Step 3:** Commit: `feat(elicitation): brainstorm-elicitation.md — independent-batch companion forms with sequential default`.

---

### Task 3: SKILL.md wiring + hooks

**Files:** Modify `skills/compound-v/SKILL.md`, `hooks/session-banner.sh`, `hooks/plan-saved-nudge.sh`

**Interfaces — Consumes:** file names `phase-0-recon.md` / `brainstorm-elicitation.md` (Tasks 1–2 create them; links are valid at merge). **Produces:** the description clause that makes Trigger 0 discoverable.

- [ ] **Step 1:** SKILL.md `description:` (L3) — add the Trigger-0 clause while keeping **total ≤500 chars**. Recommended rewrite of the opening (saves chars, adds the trigger): `Use when superpowers:brainstorming is about to begin (pre-brainstorm recon), OR has produced a spec, OR when superpowers:writing-plans has produced a plan, OR when about to invoke superpowers:subagent-driven-development or superpowers:executing-plans. Sidekick that intercepts these four Superpowers transitions — …` Verify with `python3 scripts/lint-frontmatter.py` (must pass) before committing.
- [ ] **Step 2:** SKILL.md body edits (slots per archaeology §3a):
  - "When This Skill Fires": new **Trigger 0** subsection ABOVE Trigger 1 (~L75): fires when a brainstorm is about to begin; gate order one-liner; link `[phase-0-recon.md](phase-0-recon.md)`; the honesty note (description-driven, zero hook backstop, weaker than Triggers 1–3). Add an upstream node to the mermaid graph (`Z[recon (Trigger 0)] --> A`).
  - Overrides table (~L97): two new rows — `Brainstorm starts cold on unfamiliar topics` → `Trigger 0: gated, bounded recon doc read before the first question`; `Clarifying questions strictly one-at-a-time` → `≥3 independent questions may batch into one Visual Companion form (dependent chains stay sequential) — see brainstorm-elicitation.md`.
  - Output Directory Conventions tree (~L179-203): add `recon/` node with one-line comment (`# Trigger 0 output — evidence for the brainstorm, read by 1B/1C first`).
  - Integration table row `superpowers:brainstorming` (L234): now reads that Trigger 0 fires *before* it starts (gated recon), the skill itself still runs unchanged, and on completion Trigger 1 fires.
  - Auto-fire caveat (L46): extend with one sentence — Trigger 0 shares the description-driven mechanism but has NO hook reinforcement at all (nothing is written before a brainstorm), so it is the weakest link; do not overclaim.
  - Phase announcements block: add `Phase 0: "💉 Compound V — pre-brainstorm recon (gated)."`
- [ ] **Step 3:** `hooks/session-banner.sh` L15 — update the pipeline string to include recon, e.g. `Auto-fires before brainstorming (gated recon) and after it (pre-flights). Phases: recon → code-archaeologist + domain-expert + doc-validator → …` Keep it one line, no hook-backstop claims for recon.
- [ ] **Step 4:** `hooks/plan-saved-nudge.sh` — add a third arm matching `*/docs/superpowers/recon/*.md`: nudge text `💉 Compound V — recon saved at $FILE. Start the brainstorm with it: read it before the first question; treat DIRECTIONS as non-exhaustive.` (Reinforces after recon; must not claim to backstop the pre-fire gap.)
- [ ] **Step 5:** Verify: `python3 scripts/lint-frontmatter.py` passes; `bash -n hooks/session-banner.sh hooks/plan-saved-nudge.sh` clean; SKILL.md links resolve (`ls skills/compound-v/phase-0-recon.md skills/compound-v/brainstorm-elicitation.md` — at merge).
- [ ] **Step 6:** Commit: `feat(skill): Trigger 0 wiring — description, fire rules, overrides, dir tree, hooks`.

---

### Task 4: `/v:init` config + capability wiring

**Files:** Modify `commands/v-init.md`

**Interfaces — Consumes:** config key names + defaults from the contract. **Produces:** the documented JSON shapes `phase-0-recon.md` / `brainstorm-elicitation.md` readers rely on.

- [ ] **Step 1:** Step 1 (capability detection): add a `deep-research` probe — check whether `deep-research` appears in the agent's available-skills listing (NOT a version check, NOT a `Workflow` call). Record result for Step 4b.
- [ ] **Step 2:** Step 3 (stance/policy questions): add one question — brainstorm recon mode, options `ask` (default, recommended) / `auto` / `off`, with the honest one-line cost/egress description from the contract; and one toggle — batched elicitation on/off (default on).
- [ ] **Step 3:** Step 4a committed-policy JSON (L273-293): add the block, preserving surrounding keys:

```json
"brainstorm": {
  "deep_research": "ask",
  "batch_elicitation": true
}
```

- [ ] **Step 4:** Step 4b machine-local capabilities JSON (L341-350): add `"deep_research": true` alongside `context7`/`workflows`, with the note that it is an advisory hint — Trigger 0 re-checks the live listing at fire time (it can go stale via `disableBundledSkills`).
- [ ] **Step 5:** Add one sentence where the config keys are documented: readers default `deep_research` to `"ask"` and `batch_elicitation` to `true` when the `brainstorm` block is absent (pre-v2.7 configs).
- [ ] **Step 6:** Verify both JSON snippets in the doc are valid JSON fragments (paste into `jq` with a wrapper). Commit: `feat(v-init): deep-research capability probe + brainstorm policy keys (4a/4b split preserved)`.

---

### Task 5: 1B/1C recon-read + AGENTS.md + README.md

**Files:** Modify `skills/compound-v/phase-1b-domain-expert.md`, `skills/compound-v/phase-1c-documentation-validation.md`, `AGENTS.md`, `README.md`

**Interfaces — Consumes:** recon output path convention.

- [ ] **Step 1:** `phase-1b-domain-expert.md` — between the KB-first step (L53) and the web-search step (L54), insert a step: check `docs/superpowers/recon/` for a doc matching this topic; if present, read it first and *deepen* its queries rather than repeating them; treat its DIRECTIONS as non-exhaustive.
- [ ] **Step 2:** `phase-1c-documentation-validation.md` — 1C has NO existing KB-first step (archaeology §3c): insert a NEW first step before the current step 1 (L46): check `docs/superpowers/recon/` for the topic; reuse its library findings as leads to verify (recon is unverified reconnaissance — 1C still validates every claim against live docs); then proceed to extraction.
- [ ] **Step 3:** `AGENTS.md` — L7 "intercepts the three Superpowers phase transitions" → four (adds pre-brainstorm recon); L9 list gains item 0: gated pre-brainstorm recon (deep-research if present, WebSearch fallback) writing an anti-anchoring recon doc to `docs/superpowers/recon/`; mention batched elicitation in one line. Mark both 🧪 description-driven.
- [ ] **Step 4:** `README.md` — update the "start brainstorming as usual" line (~L66) to mention the gated recon offer + recon doc; one line under features for batched elicitation. Keep marketing-free, honest ("gated, bounded, off by one config key").
- [ ] **Step 5:** Verify: `grep -n "recon" skills/compound-v/phase-1b-domain-expert.md skills/compound-v/phase-1c-documentation-validation.md AGENTS.md README.md` shows all four landed. Commit: `feat(integration): 1B/1C read recon first + AGENTS/README four-trigger reality`.

---

## Execution Handoff

Compound V manifest-driven dispatch (`/v:orchestrate` → partition review → dispatch): Task 0 serial, Tasks 1–5 parallel, all `claude · opus · direct` (disjoint docs jobs; no Codex worker — prose guidance with tight cross-references, not an isolated build). Scope gate after every job; three-pass Review Gate against spec ACs 1–13; then Codex cross-model review rounds (user-mandated) before any push.
