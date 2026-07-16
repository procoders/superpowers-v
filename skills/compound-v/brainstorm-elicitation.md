# Brainstorm Elicitation — batched independent questions, sequential everything else

> *"You can ask the team five things at once — but only if no answer changes what the other four questions mean."*

This doc governs how clarifying questions are asked while `superpowers:brainstorming` runs
with Compound V present. The default is, and stays, **upstream's one-at-a-time terminal
interview** — correct and practitioner-backed for dependent, exploratory questioning. The
one narrow exception: when a checkpoint yields **≥3 genuinely independent** questions, they
may batch onto **one structured surface** instead of three-plus serial turns. Three separate
decisions, taken in order and never conflated: the **checkpoint algorithm** finds the
batchable set, the **batch gate** decides whether that set batches at all, the **surface
ladder** decides where a gated batch renders. Bias throughout: **when unsure → sequential.**

---

## The checkpoint algorithm — when batching is even evaluated

Questions never "pile up" in a one-at-a-time interview, so the batch question is evaluated
at each **design checkpoint**: every moment the interviewer plans its next question(s) —
the only well-defined evaluation moment. At each checkpoint:

1. **List** the candidate questions currently worth asking.
2. **Build the pairwise dependency graph.** Draw an edge between two questions when either:
   - **answer interaction** — either answer can change the other's wording, options, or
     necessity, or both draw on a shared budget (scope, time, effort) the form never
     displays; or
   - **psychological co-presence** — seeing one group's framing on the same screen could
     plausibly shift the other answer (priming, order, carryover effects), even with zero
     logical interaction between the answers.
3. **Batch-eligible = isolated nodes only.** A question with at least one edge stays
   sequential. A "mostly independent" cluster is not independent.
4. **Recompute after every sequential answer.** Answers create edges, delete candidates,
   and spawn new questions; the graph is stale the moment anything is answered. The next
   checkpoint starts again from step 1.

## The classification rule — dependent chain vs independent batch

- **Dependent chain:** an earlier answer changes what a later question means, which options
  it offers, or whether it should be asked at all. These stay **one-at-a-time in the
  terminal**, upstream-style — a batched dependent question is half-stale the moment an
  earlier answer would have rewritten it.
- **Independent batch:** every question can be answered in any order, no answer affects any
  other, and no group's on-screen framing plausibly primes another answer. Only these
  batch.

**The operational test is *answer interaction*, not surface topic:** could any answer
change, contradict, or over-subscribe another — including through a shared constraint the
form never displays? Two questions about unrelated-looking topics can interact; two
questions about the same topic can be independent. Judge the answers, not the subject line.
The co-presence edge is the second, softer test: even logically independent answers can be
skewed by sharing a screen (an early problem-framed question colors later answers regardless
of topic — documented questionnaire reality). If co-presence could skew, the pair stays
sequential.

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

---

## The batch gate — independence + count + config decide batching

Exactly three conditions decide whether an eligible set BATCHES. The companion appears in
none of them — acceptance gates only the companion SURFACE (next section), never batching.

1. **Independence:** every question in the set is an isolated node in this checkpoint's
   dependency graph.
2. **Count:** **≥3** eligible questions (below the floor, batching saves nothing), and at
   most the **first 5** eligible batch at one checkpoint. Overflow beyond 5 continues
   **one-at-a-time**; **never a second batch from the same checkpoint** — the next
   checkpoint may batch again, after a full recompute. **Never render a matrix/grid**
   (the survey-matrix anti-pattern: higher dropout, straight-lining).
3. **Config:** `brainstorm.batch_elicitation` in `.claude/compound-v.json` is not `false`.
   Fail-closed rule, verbatim from the shared contract: Missing file or key → the
   documented defaults (`deep_research: "ask"`, `batch_elicitation: true`). Malformed JSON,
   wrong type, or unknown value → warn once, then use `deep_research=ask` and
   `batch_elicitation=false` for this session; never treat an invalid value as `auto`.
   `false` — configured or fail-closed — is an honored kill-switch: the user gets
   upstream's sequential behavior, always.

Form-shape rules for any batch, on any surface:

- Groups must be **answerable in any order** and share **no rating scale or common stem**
  (a shared scale is a matrix wearing a costume).
- Every group carries an **open-ended escape hatch** — an "other / none of these — tell me
  in the terminal" option — so the listed choices never frame out the true answer.
- One screen (or call) per batch; answering is never mandatory — the terminal reply wins.

## Decision-preference recall — annotate the about-to-render fork (PULL, not a rung)

At the **pre-fork checkpoint** — after the batch gate has decided *what* renders but before the
surface ladder decides *where* — an optional PULL surfaces the maker's **own dated past reasoning**
for the fork about to be shown, and always pairs it with a divergent challenge. This is a memory aid,
not a nudge; the full authority is [decision-preferences.md](decision-preferences.md). It runs at the
**checkpoint seam**, is **surface-agnostic**, and **adds no rung** — it annotates whatever the ladder
renders and survives a runtime rung-drop unchanged.

- **Gate it on `brainstorm.preferences`** (`.claude/compound-v.json`, resolved by
  `resolve_brainstorm` in `scripts/compound-v-project-config.py`; default `on-demand`). **`off` ⇒ do
  nothing** — no pull, no annotation. Independent of `batch_elicitation`: recall runs whether the fork
  renders as a batch, a single question, or a terminal turn.
- **Suppress where recon widens.** On a **recon-touched** or **high-novelty** fork, do not pull — pass
  `--recon-touched` when Phase-0 recon touched this fork ([phase-0-recon.md](phase-0-recon.md)); the
  spine also self-suppresses low-similarity/novel forks. `recall` returning `shown:false` (any
  `suppressed_reason`) ⇒ render nothing. Recon-widen and preference-narrow never co-fire on one fork.
- **The pull:** `compound-v-preferences.py recall --question … --option … --mode <mode>`. On
  `shown:true` it returns dated `evidence` + a mandatory `challenge` (and, in `marked` mode only, a
  `marked_option` label). Annotate the about-to-render options with it:
  - **ALWAYS render the `challenge`** alongside the evidence — a recall without its divergent
    counter-move never appears (the spine already enforces this by suppressing `no-challenge`).
  - In **`marked`** mode, place the `marked_option.badge` (`↩ your past pick: N/M · date`) beside its
    **NEUTRAL** option — a soft, low-urgency label, **never a pre-selected control**. In
    `on-demand`/`off`, `marked_option` is `null`; surface evidence-only (or nothing).
  - **NEVER pre-select, never pre-tick, never add or reorder a ladder rung.** The badge is an
    annotation on an option the human still picks from a neutral state; the challenge and badge always
    render together.
- **The inviolable human gate still holds** — verbatim from the batch gate above:
  *"answering is never mandatory — the terminal reply wins."* A mark or an evidence line is input, never
  an answer; the terminal reply overrides every annotation exactly as it overrides every click.

## The surface ladder — where a gated batch renders

A batch that clears the gate renders on the highest available rung:

1. **Visual Companion** — available only under the observable-acceptance rule below; one
   form screen per the transactional protocol. Reference the companion by its stable
   contract (state dir, events file, frame classes), never a version pin.
2. **The harness's structured-question equivalent** (on Claude Code: `AskUserQuestion`) —
   **ONE call**, sized to its caps: **≤4 questions per call, 2–4 options per question,
   headers ≤12 chars**, `multiSelect: true` for checkbox-style groups (its automatic
   "Other" free-text option is the escape hatch). A 5-group batch puts 4 in the call and
   the fifth sequential; a question with more than 4 choices is restructured with
   `multiSelect` or split; **never a second call from the same checkpoint.** No such tool
   on this harness ⇒ rung 3.
3. **One-at-a-time in the terminal** — upstream's default.

The ladder only ever steps **down**: no rung re-offers the companion, no rung upgrades a
terminal conversation into a form, and a **runtime failure descends immediately** — server
dead, screen push fails, `$STATE_DIR/events` unreadable or unparseable ⇒ this batch drops a
rung; answers already reconciled stand, unresolved groups are re-asked on the lower rung.
On every rung the hard rule holds: **dependent questions NEVER enter any batch surface.**

### Observable acceptance — when the companion counts as available

"Companion accepted this session" requires BOTH observable facts:

1. The user said an **explicit yes in THIS conversation** to upstream's own just-in-time
   companion offer, made for a genuinely visual question — batching is never a reason to
   make (or repeat) the offer.
2. A **`state_dir` is recorded** in this conversation's working state (from the companion
   server's startup JSON / `$STATE_DIR/server-info`).

Either fact unknown or unverifiable ⇒ **companion unavailable** — use rung 2. A server
left over from an earlier session, a config flag, or a remembered acceptance proves nothing.

## Transactional answer protocol — companion batches only

The companion's events file (`$STATE_DIR/events` — JSONL, one object per line, e.g.
`{"type":"click","choice":"naming:b","text":"Option B - verb-first","timestamp":1706000101}`)
is **cleared automatically on each new screen push** and carries no group identity of its
own — two hazards for a multi-group form that this protocol neutralizes.

**Authoring:**

- **Namespaced choices:** every option's `data-choice` is `"group:option"` (`"naming:a"`,
  `"scope:cli-only"`), and every id is **globally unique across the screen** — a bare
  `"a"` repeated in two groups makes events unattributable.
- Each group is a `.section` with a `.label`; choices live in an `.options` container of
  `.option` elements wired `data-choice="…" onclick="toggleSelect(this)"`. Groups with
  checkbox semantics put the bare `data-multiselect` attribute on their `.options`
  container (the helper reads `container.dataset.multiselect` and toggles).

**Reading:**

- **Completion barrier — read before any push.** The user's terminal reply is the signal
  that the form is done. Only after it arrives: read and parse `$STATE_DIR/events`,
  reconcile per group (below) — and only then may any new screen be pushed. Pushing first
  clears the file and races a still-clicking user; a screen with unread events is never
  replaced.
- **Absent events file ⇒ the user did not interact** — the terminal text is everything.
- **Multiselect groups resolve by toggle-replay:** replay that group's click events in
  timestamp order, toggling each choice's membership per click; the surviving set is the
  answer. Single-select groups: the group's last click wins.

**Per-group reconciliation** — the terminal text is primary; the form is an input surface,
never an authority. Resolve each group independently:

| The terminal reply… | That group's answer is… |
|---|---|
| Explicitly addresses the group | The terminal answer — it overrides that group's clicks |
| Doesn't mention the group; events have a value | The event value |
| Is a bare acknowledgement ("ok", "done", "looks right") | The event values — **acknowledgements override nothing** |
| Is ambiguous for the group (unclear which option; contradicts the clicks unclearly) | **Re-ask that group, sequentially** |
| Group has no events and no terminal mention | **Never infer a default** — ask it sequentially, or record it as explicitly deferred with the user's consent |

### Capture the resolved decision (memory, not authority)

Reconciliation is the one place the resolved answer is **authoritative**, so it is where — and only
where — a preference fork is captured. Gate on `brainstorm.preferences` (`off` ⇒ skip entirely); skip
too on the recon-touched / high-novelty forks where recall was suppressed. For a resolved
preference-eligible group:

- **Prompt the UNPROMPTED `why` FIRST** — free text, or an explicit skip (`--why` omitted ⇒ stored
  `null`). Candidate rationales may be offered only *after* the human's own attempt and are stored
  `--why-class borrowed` (weighted down, excluded from "your reasoning"). Never infer a rationale.
- **Capture** with `compound-v-preferences.py capture --question … --chosen <resolved> --option …`,
  recording whether the resolved `chosen` **matched the recalled `marked_option`**: if the human
  landed on a *different* option than their own past pattern, pass `--changed-after-recall` (the clean
  drift signal). Also pass `--recall-shown` / `--challenged` to reflect what was surfaced at the fork.
- This appends to the LOCAL raw log only; the in-repo distillate is refreshed by `distill`
  (`/v:preferences`). See [decision-preferences.md](decision-preferences.md) for the full contract.

## The upstream override, stated honestly

Upstream routes text questions to the terminal. Verbatim, from the
`superpowers:brainstorming` SKILL.md: *"Per-question decision: … **Use the terminal** for
content that is text — requirements questions, conceptual choices, tradeoff lists, A/B/C/D
text options, scope decisions."* **This doc deliberately overrides that rule for exactly
one case:** a gated batch of independent text-ish questions. The mechanism is the same
description-driven override as Compound V's other interceptions, with the same reliability
caveat (nothing enforces it — see SKILL.md's auto-fire caveat). Not overridden:

- **The just-in-time offer etiquette is inviolable.** Upstream: *"Offer … just-in-time —
  NOT upfront … If no visual question ever arises, never offer it."* Compound V never
  force-opens the browser and never makes the offer on batching's behalf — the
  observable-acceptance rule exists for exactly this.
- **Dependent and exploratory questions stay in the terminal, one at a time** — upstream's
  default and the practitioner counter-signal agree, and this doc keeps them both.

## Cross-references

- The main skill (overrides table + auto-fire caveat): [SKILL.md](SKILL.md)
- The sibling surface, pre-brainstorm recon: [phase-0-recon.md](phase-0-recon.md)
- Decision-preference recall/capture (memory + challenge) authority: [decision-preferences.md](decision-preferences.md)
- Config key `brainstorm.batch_elicitation`: [/v:init](../../commands/v-init.md)
- Misclassification evidence + batching thresholds: [2026-07-10 expert audit](../../docs/superpowers/expert/2026-07-10-research-grounded-brainstorm.md)
- Checkpoint + transactional hardening evidence (C1 21–27, C2 6–7): [2026-07-11 expert audit](../../docs/superpowers/expert/2026-07-11-v2-8-hardening.md)
- Verified companion/`AskUserQuestion` contracts: [library audit](../../docs/superpowers/library-audit/2026-07-10-research-grounded-brainstorm.md)
