# Research-Grounded Brainstorm (v2.7.0) — Design

**Status:** approved in conversation 2026-07-10 (Oleg)
**Driver:** user complaint — "Brainstorm недостаточно придумывает задачу" (brainstorm doesn't
develop the task deeply enough). Evidence today arrives only *after* the spec (pre-flights
1A/1B/1C) — too late to improve the quality of the brainstorm's own questions and approaches.

## Goal

Make `superpowers:brainstorming` produce deeper, better-grounded specs **without modifying
the upstream skill**, via two additions to Compound V:

1. **Trigger 0 — pre-brainstorm recon.** Intercept the transition *into* brainstorming
   (symmetric to how Compound V already intercepts the transition *out of* it) and, when the
   topic is unfamiliar, run a bounded research pass whose output the brainstorm reads before
   asking its first question.
2. **Batched elicitation guidance.** When several *independent* questions accumulate during
   a brainstorm, batch them into one Visual Companion form screen (the browser playground
   that `superpowers:brainstorming` already ships) instead of a long one-at-a-time chain.

## Non-goals (explicit)

- **No modification of any upstream Superpowers file.** Both features are description-driven
  guidance the parent agent follows — the same mechanism (and the same reliability caveat) as
  Compound V's existing auto-fire.
- **No new server, daemon, or playground of our own.** The elicitation surface is upstream's
  Visual Companion server, reused as-is.
- **No unconditional deep-research.** Recon is gated (knowledge-base hit → skip; config
  `ask|auto|off`; plumbing topics → skip) because it costs tokens and wall-clock.
- **No new agents.** Trigger 0 runs in the parent (or via the bundled `deep-research` skill,
  which manages its own subagents). No new `agents/*.md`, so no frontmatter/model-policy surface.
- **No replacement of 1A/1B/1C.** Recon is reconnaissance before the battle; the pre-flights
  remain the full audit. Recon output *feeds* them (they read it first and don't repeat its
  searches).

## Feature 1 — Trigger 0: pre-brainstorm recon

### When it fires

Description-driven, added to `skills/compound-v/SKILL.md`'s `description`: fires when
`superpowers:brainstorming` is about to begin on a feature topic.

### Gate order (checked in this order, first match wins)

1. **Skip rule — plumbing:** topic is pure internal plumbing (build config, lint rules,
   dev tooling, trivial copy edit) → skip recon entirely.
2. **Knowledge-base hit:** run `/v:remember <topic>` (V-memory). A strong hit in
   `docs/superpowers/**` prose (prior recon, expert KB, library KB on the same domain) →
   skip recon, hand the recalled docs to the brainstorm as evidence instead.
3. **Config:** `.claude/compound-v.json` → `brainstorm.deep_research`:
   - `"ask"` (default) — offer the recon to the user (one AskUserQuestion), run on yes.
     The offer states cost/time **honestly and qualitatively, never a token number**
     (1B audit: real cost variance is ~200×): bounded scope (one deep-research pass OR ≤6
     web searches), order-of-magnitude wall-clock ("couple of minutes; deep research can run
     several minutes and spawn subagents"), and an **external-web-search/egress note** (the
     topic text leaves the machine — this is a confidentiality consent point, not only cost).
     Offer options include a scope-narrowing path (the user can refine the topic in the same
     turn — mirrors the ChatGPT/Gemini/Perplexity deep-research norm and reduces anchoring);
   - `"auto"` — run without asking (the anti-anchoring output rules still apply in full);
   - `"off"` — a **hard, honored kill-switch** (cost *and* egress/confidentiality).

### Engine selection (degrade-safe, like Context7 in 1C)

1. If the bundled **`deep-research`** appears in the agent's available-skills listing →
   invoke it **through the skill/slash interface** with a bounded prompt (topic + "domain
   constraints, current library landscape, common pitfalls, prior art"). Never hard-code
   `Workflow({...})` (the Workflow tool may be absent in a plain subagent — 1C audit), and
   never gate on a Claude Code version number: the **live listing re-check at fire time is
   the contract**; the `/v:init` capability flag is an advisory hint only (it can go stale
   via `disableBundledSkills`).
2. Else → **3–6 parallel WebSearch** calls in one message (the existing Phase 1B pattern).
3. No network / both unavailable → skip with an explicit notice. Never block the brainstorm.

### Bounds (anti-over-engineering)

- One deep-research invocation OR ≤6 WebSearch calls per topic. No loops.
- Output document target ≤ ~150 lines: findings + "questions the brainstorm should ask" +
  "constraints the spec must respect" + sources.

### Output contract

- `docs/superpowers/recon/YYYY-MM-DD-<topic>.md`, committed (same write-then-commit
  discipline as every other Compound V artifact — v2.6.4 lesson).
- **The caller writes the file.** Verified (1C audit): the bundled `deep-research` is a
  builtin Workflow that returns its report **as a message and never writes files** — Trigger 0
  captures the report, trims it to the recon format below, then writes + commits.
- **Anti-anchoring structure is mandatory** (1B audit: the headline risk is that a research
  dossier *narrows* the idea space — design fixation / LLM anchoring). The doc, in order:
  1. an **anti-anchoring header** (verbatim template in `phase-0-recon.md`): evidence to widen
     questions, not a conclusion to converge on;
  2. **QUESTIONS TO ASK** — framed as *mistakes-to-avoid*, the empirically stronger form
     (arXiv 2507.02858);
  3. **FACTS / CONSTRAINTS** — anchor-safe: regulatory rules, API signatures, hard limits;
  4. **SUGGESTED DIRECTIONS** — anchor-unsafe: **≥2–3 divergent options, explicitly
     non-exhaustive; a single recommended approach is forbidden**; never suppressed;
  5. **SOURCES**. ≤150 lines total; no token/cost numbers (anti-ruflo).
- **1B and 1C read it first**: their phase docs gain a step — check
  `docs/superpowers/recon/` for a matching topic before opening new searches; don't repeat
  recon's queries, deepen them. (1C has no existing KB-first step — new step, not a one-liner.)
- V-memory indexes `docs/superpowers/**` prose, so recon docs become recallable via
  `/v:remember` automatically — future brainstorms in the same domain hit gate 2 and skip.

## Feature 2 — Batched elicitation via the Visual Companion

### The classification rule (the core of the feature)

Brainstorm questions come in two kinds:

- **Dependent chain** — the answer changes the next question (architecture, scope,
  approach). These stay **one-at-a-time in the terminal**, exactly as upstream mandates.
  A static questionnaire cannot branch; batching these produces half-stale forms.
- **Independent batch** — answers don't affect each other (preference toggles, naming,
  styling directions, feature checkboxes, priority ranking). These MAY be batched.

### When to batch

All three must hold:
1. ≥ 3 independent questions have accumulated — **and ≤ 5 distinct question groups per
   screen** (1B audit: survey evidence — small chunked batches beat both one-per-page and
   dense grids; a matrix/grid layout is forbidden; beyond 5, paginate or stay sequential);
2. the user has already accepted the Visual Companion for this session (upstream's own
   just-in-time offer etiquette is respected — we never force-open the browser);
3. `brainstorm.batch_elicitation` is not `false` in `.claude/compound-v.json` (default: enabled).

Then: render ONE companion form screen (options / `data-multiselect` groups, upstream's
frame classes), read answers from `$STATE_DIR/events` merged with the user's terminal reply.
Form rules (1B): groups answerable in any order, no shared rating scale/common stem, and
every group carries an open-ended "other / none of these" escape hatch.

**Independence is judged on answer interaction, not surface topic:** could any answer
change, contradict, or over-subscribe another (including via an unshown shared budget)?
**When unsure → sequential.** `brainstorm-elicitation.md` ships ≥3 concrete
looks-independent-but-actually-dependent examples (1B audit §4).

**This deliberately overrides upstream's "text questions → terminal" rule** for the
independent-batch case; `brainstorm-elicitation.md` must say so explicitly and quote the
upstream rule it supersedes (same description-driven override mechanism and reliability
caveat as Compound V's other interceptions).

### Fallbacks

- Companion declined or not running → `AskUserQuestion` (caps verified 1C: ≤4 questions/call,
  2–4 options each, headers ≤12 chars, `multiSelect` supported) for the independent batch;
  overflow continues one-at-a-time.
- No interactive surface at all → one-at-a-time in the terminal (upstream default).

## Config & capability surfaces (v2.6.2 discipline)

- **Committed policy** (`.claude/compound-v.json`):
  ```json
  "brainstorm": { "deep_research": "ask", "batch_elicitation": true }
  ```
- **Machine-local capability** (`~/.claude/compound-v-capabilities.json`, never committed):
  whether the bundled `deep-research` skill is present on this install (version-dependent).
  `/v:init` detects it (presence in the available-skills listing) and records it alongside
  the existing Codex/Context7 checks.

## Bundled fix — CHANGELOG↔manifest CI guard

Found while starting this release: v2.6.4 shipped with both manifests still at 2.6.3 (the
bump was written but never committed); CI's lockstep check only compares the two manifests
against each other. Add a guard to the existing CI lint step: the newest `CHANGELOG.md`
version heading must equal `plugin.json`'s `version`. Closes the bug class.

## Acceptance Criteria

1. `skills/compound-v/SKILL.md`: description names the new trigger ("when
   superpowers:brainstorming is about to begin"); body documents Trigger 0 (gate order,
   engine selection + degrade, bounds, output path); overrides table gains the two new rows;
   directory-conventions tree gains `recon/`.
2. New `skills/compound-v/phase-0-recon.md`: full Trigger 0 procedure incl. gate order,
   engine selection, bounds, output format, the recon≠pre-flight rule, and the 1B/1C reuse
   contract.
3. New `skills/compound-v/brainstorm-elicitation.md`: dependent-vs-independent rule, the
   3-condition batch gate, companion reuse (never our own server), events-file reading,
   full fallback ladder.
4. `commands/v-init.md`: deep-research capability detection → capabilities file
   (machine-local); `brainstorm.*` policy questions → committed config; defaults documented.
5. Phase 1B and 1C docs: one added step — read `docs/superpowers/recon/` for the topic
   before searching.
6. Version lockstep 2.7.0 (plugin.json + marketplace.json) + `CHANGELOG.md` entry +
   CI guard (CHANGELOG top version == plugin.json version) wired into the existing lint/CI
   path.
7. `AGENTS.md` + `README.md`: interception points updated (Trigger 0 + elicitation),
   accurately described as 🧪 description-driven.
8. Invariants hold: no upstream file edits; no new servers/daemons; no new agents; no
   fabricated cost/token metrics; recon is evidence for brainstorm/planning, **never a
   routing input** (same boundary as V-memory; load-bearing *because* of the anchoring
   risk — recon silently driving approach selection would *be* the premature-convergence
   failure).
9. `skills/compound-v/skill-escalation.md` reconciled: it currently asserts deep-research
   fires only "past 1B/1C" — Trigger 0 is an earlier, gated use; extend the doc so the two
   don't contradict (1A audit §6.1). No silent third path.
10. `skills/compound-v/SKILL.md` `description` stays **≤500 chars** after the Trigger-0
    clause (`lint-frontmatter.py` hard-fails CI above it; 410 used today).
11. The CHANGELOG CI guard matches the real heading format `^## \[x.y.z\] — …` (separator is
    an **em-dash U+2014**, first match top-down = newest) and compares to `plugin.json
    .version`, attached beside the existing lockstep step in `validate.yml`.
12. Trigger 0's documentation never implies hook reinforcement exists for it — it has
    **zero hook backstop** (fires before any file is written); banner text
    (`hooks/session-banner.sh`) updated without overclaiming. Optional: a
    `plan-saved-nudge.sh` arm for `recon/*.md` ("recon saved → start the brainstorm with
    it") — reinforces *after* recon, does not close the pre-fire gap, and must not claim to.
13. Recon docs and both new phase docs contain no token/cost numbers (anti-ruflo CI gate).
