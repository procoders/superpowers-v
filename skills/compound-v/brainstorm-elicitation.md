# Brainstorm Elicitation — batched independent questions, sequential everything else

> *"You can ask the team five things at once — but only if no answer changes what the other four questions mean."*

This doc governs how clarifying questions are asked while `superpowers:brainstorming` runs
with Compound V present. The default is, and stays, **upstream's one-at-a-time terminal
interview** — correct and practitioner-backed for dependent, exploratory questioning. The
one narrow exception: when **≥3 genuinely independent** questions pile up, they may batch
into **ONE Visual Companion form screen** instead of three-plus serial turns. The exception
is gated (three conditions below), bounded (≤5 groups, never a grid), and biased toward the
default: **when unsure → sequential.**

---

## The classification rule — dependent chain vs independent batch

- **Dependent chain:** an earlier answer changes what a later question means, which options
  it offers, or whether it should be asked at all. These stay **one-at-a-time in the
  terminal**, upstream-style. A batched dependent question is half-stale the moment an
  earlier answer would have rewritten it.
- **Independent batch:** every question can be answered in any order and no answer affects
  any other. Only these are batch-eligible.

**The operational test is *answer interaction*, not surface topic:** could any answer
change, contradict, or over-subscribe another — including through a shared constraint the
form never displays (a scope, time, or effort budget)? If yes, the questions are dependent.
Two questions about unrelated-looking topics can interact; two questions about the same
topic can be independent. Judge the answers, not the subject line.

**Tiebreak — when unsure → sequential.** The costs are asymmetric: a dependent question
misread as independent yields a half-stale form and a revision cycle; an independent one
misread as dependent costs a single extra terminal turn. Take the cheap miss.

### Looks independent, actually dependent (from the 1B domain audit)

Verbatim from the [expert audit §4](../../docs/superpowers/expert/2026-07-10-research-grounded-brainstorm.md):

1. **Name vs identifier.** "What do we call the feature?" + "What's the CLI command prefix?"
   — if the name becomes the command, the second answer is constrained by the first.
2. **Format vs validation.** "Output JSON or YAML?" + "Validate against a schema?" — schema
   tooling and feasibility differ by format.
3. **Ranking vs MVP.** "Rank features A/B/C" + "Which is the MVP?" — the ranking *is* the
   MVP answer; asking both in one form invites self-contradiction.
4. **The subtle systemic one — toggles coupled by an unshown budget.** "Enable X?"
   "Enable Y?" "Enable Z?" look independent, but if an unstated scope/time budget can't
   afford all three, the answers interact through a constraint the form never displays. This
   is the case the tiebreak must catch: **if the answers could ever contradict or
   over-subscribe a shared budget, they are not independent — ask sequentially.**

Order/carryover/priming effects are documented questionnaire reality — an early
problem-framed question colors later answers regardless of topic — which is why
independence is judged on answer interaction, never on surface topic.

---

## The batch gate — all three conditions, or stay sequential

1. **≥3 independent questions are pending, AND the batch fits in ≤5 groups on one screen.**
   Below the floor, batching saves nothing; above the ceiling, the screen degrades into the
   survey-matrix anti-pattern (higher dropout, straight-lining). More than 5 → split into
   screens or continue one-at-a-time. **Never render a matrix/grid.**
2. **The user already accepted the Visual Companion this session** — via upstream's own
   just-in-time offer, made for a genuinely visual question. Batching is never a reason to
   offer or open the companion; this condition exists precisely to preserve upstream's offer
   etiquette (see the override section below).
3. **`brainstorm.batch_elicitation != false`** in `.claude/compound-v.json`. Readers default
   the key to `true` when the `brainstorm` block is absent (pre-v2.7 configs); `false` is an
   honored kill-switch — the user gets upstream's sequential behavior, always.

Form-shape rules for a batch that clears the gate:

- Groups must be **answerable in any order** and share **no rating scale or common stem**
  (a shared scale is a matrix wearing a costume).
- Every group carries an **open-ended escape hatch** — an "other / none of these — tell me
  in the terminal" option — so the listed choices never frame out the true answer.
- One screen per batch; answering is never mandatory — the terminal reply always wins.

---

## The upstream override, stated honestly

Upstream routes text questions to the terminal. Verbatim, from the `superpowers:brainstorming`
SKILL.md and its `visual-companion.md`:

> *"Per-question decision: Even after the user accepts, decide FOR EACH QUESTION whether to
> use the browser or the terminal … **Use the terminal** for content that is text —
> requirements questions, conceptual choices, tradeoff lists, A/B/C/D text options, scope
> decisions."*

> *"Use the terminal when the content is text or tabular: Requirements and scope questions …
> Conceptual A/B/C choices … Tradeoff lists … Clarifying questions — anything where the
> answer is words, not a visual preference."*

**This doc deliberately overrides that rule for exactly one case:** a batch of independent
text-ish questions (preference toggles, naming, styling directions, feature checkboxes)
that clears the three-condition gate. The mechanism is the same **description-driven
override** as Compound V's other interceptions — and it carries the same reliability caveat
(nothing enforces it; a weaker model may miss it — see SKILL.md's auto-fire caveat).

What is **not** overridden:

- **The just-in-time offer etiquette is inviolable.** Upstream: *"Offer … just-in-time —
  NOT upfront … This offer MUST be its own message … If no visual question ever arises,
  never offer it."* Compound V never force-opens the browser and never makes the offer on
  batching's behalf — condition 2 exists for exactly this.
- **Dependent and exploratory questions stay in the terminal, one at a time** — upstream's
  default and the practitioner counter-signal agree, and this doc keeps them both.

---

## Rendering contract — the companion by its stable contract, not a version pin

Reference the companion by the surfaces below (stable across upstream releases), never by a
version string:

- **One form screen per batch.** Each group is a `.section` with a `.label`; choices live in
  an `.options` container of `.option` elements wired `data-choice="…"
  onclick="toggleSelect(this)"` (`.letter`/`.content` for the option body, `.selected` marks
  the choice). Where a group has checkbox semantics ("pick all that apply"), put the bare
  **`data-multiselect`** attribute on that group's `.options` container — the companion's
  helper reads `container.dataset.multiselect` and toggles instead of replacing.
- **Answers come from `$STATE_DIR/events`** — JSONL, one object per line, e.g.
  `{"type":"click","choice":"a","text":"Option A - Simple Layout","timestamp":1706000101}`.
  The file is **cleared automatically on each new screen push**; **absent ⇒ the user did not
  interact** (use the terminal text only).
- **Merge events with the user's terminal reply; the terminal text is primary.** A terminal
  answer that contradicts a click wins — the form is an input surface, never an authority.

---

## Fallback ladder

1. **Companion accepted this session** → one form screen per the rendering contract above.
2. **Companion declined or absent** → **ONE `AskUserQuestion` call**, sized to its caps:
   **≤4 questions per call, 2–4 options per question, headers ≤12 chars**, with
   `multiSelect: true` for checkbox-style groups (its automatic "Other" free-text option is
   the escape hatch). A question with more than 4 choices can't list them all — restructure
   with `multiSelect` or split it. **Overflow beyond 4 questions → continue one-at-a-time**;
   never chain a second batched call to squeeze the rest in.
3. **No interactive surface at all** → one-at-a-time in the terminal, upstream's default.

The ladder only ever steps **down** — no rung re-offers the companion, and no rung upgrades
a terminal conversation into a form. And on every rung, the hard rule holds: **dependent
questions NEVER enter any batch surface.**

---

## Cross-references

- The main skill (overrides table + auto-fire caveat): [SKILL.md](SKILL.md)
- The sibling v2.7.0 surface, pre-brainstorm recon: [phase-0-recon.md](phase-0-recon.md)
- Config key `brainstorm.batch_elicitation`: [/v:init](../../commands/v-init.md)
- Misclassification evidence + batching thresholds: [expert audit](../../docs/superpowers/expert/2026-07-10-research-grounded-brainstorm.md)
- Verified companion/`AskUserQuestion` contracts: [library audit](../../docs/superpowers/library-audit/2026-07-10-research-grounded-brainstorm.md)
