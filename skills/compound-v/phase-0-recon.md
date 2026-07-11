# Phase 0 — Pre-Brainstorm Recon (Trigger 0)

**When this fires:** `superpowers:brainstorming` is **about to begin** on a feature topic — evaluated before EVERY feature brainstorm, BEFORE the first question (Trigger 0, upstream of Trigger 1's pre-flights). Gates 1–3 below are the **complete** eligibility test; there is no separate "grounding" or "session familiarity" judgment.

**Goal:** Hand the brainstorm a small, honest evidence base — verified facts, unverified leads clearly labeled, and sharper questions — so it starts grounded instead of guessing. Recon is a scout report, not a plan.

> Think of Trigger 0 as sending A-Train around the block before the Seven storm the tower: fast intel on what's actually out there. He reports back. He doesn't pick the plan.

---

## 1. Purpose and Honesty Boundary

Recon exists because a brainstorm that starts cold on an unfamiliar topic asks shallow questions and takes the field's constraints for granted. A bounded research pass before the first question fixes that — **if and only if** its output widens the question space instead of narrowing it.

- **Recon is evidence to widen the brainstorm's questions.** The Phase 1B domain audit behind this feature (2026-07-10) documents the failure mode: front-loaded research *anchors* ideation (design fixation in humans, measurable anchoring bias in LLMs). Every rule in §4's output contract exists to counter this.
- **Directions-late protocol (structural anti-anchoring, binding on the brainstorm):** the brainstorm first works from **VERIFIED FACTS / CONSTRAINTS + QUESTIONS TO ASK only**; it produces **≥3 first-principles proposals, including one that deliberately rejects the recon's framing**; only then does it read SUGGESTED DIRECTIONS — as a coverage/novelty check, not a menu. Residual risk, stated plainly: the same context that synthesized the recon also brainstorms, so directions-late reduces anchoring but cannot eliminate it.
- **Recon is never an approach-selector.** It must not conclude, recommend a single solution, or pre-decide what the brainstorm should converge on.
- **Recon is never a routing input.** Same boundary as V-memory ([memory.md](memory.md)): findings inform the brainstorm's questions and later the plan's constraints; they never touch model or backend selection. The recon-outcomes stream (§6) inherits this boundary.

**Reliability, stated plainly:** Trigger 0 is **description-driven**, with one backstop: the `hooks/brainstorm-trigger0-nudge.sh` hook injects a one-line reminder ("run the Trigger 0 gates from phase-0-recon.md if not already done") when the Skill tool invokes `superpowers:brainstorming`. That is a **reminder, not enforcement** — the model can still skip it, so Trigger 0 remains weaker than Triggers 1–3. Do not overclaim its reliability; a missed Trigger 0 degrades to plain upstream brainstorming, and nothing breaks.

---

## 2. Gate Order — Three Gates, Always in This Order

Recon is gated, not fire-by-default (the same philosophy as [skill-escalation.md](skill-escalation.md)). Evaluate the gates in order; the first gate that says "skip" ends the check, emits the one-line log, and appends exactly one terminal event to the outcomes stream (§6). **Announce Phase 0 (`💉 Compound V — pre-brainstorm recon (gated).`) only when the gates decide to RUN** — a skip gets the log line and its event, no announcement:

```
RECON fired — gates: plumbing=pass, KB=weak, config=ask→accepted (scope narrowed). Engine: deep-research.
RECON skipped (kb_skip) — strong hit: docs/superpowers/expert/2026-05-02-oauth.md (same task class, fresh); handed to the brainstorm.
```

### Gate 1 — Plumbing skip

Skip **only** when the change cannot alter a shipped artifact, runtime behavior, release semantics, security/compliance posture, availability, or user-observable performance. **Tool choices, migrations, and version/compatibility questions are NOT plumbing** — bundler swaps, test-runner choices, and SDK upgrades are exactly where live research pays. Pure lint-config or internal-rename topics skip (→ `plumbing_skip`). When in doubt, proceed to gate 2.

### Gate 2 — Knowledge-base hit (V-memory)

Before searching the web, check what the repo already knows. From the **repo root** (agent bash cwd resets between calls — `cd` explicitly or use an absolute script path):

```bash
python3 scripts/compound-v-memory.py search "<topic>" --top 8 --json
```

- **If the output warns the index is behind** ("index is N new / M removed docs behind the repo") → run `python3 scripts/compound-v-memory.py refresh` first, then re-run the search; otherwise recent recon docs false-miss.
- **Exclude `doc_type: "memory"` rows** (jsonl telemetry noise) before judging; then **open and read the top remaining results**. The JSON has **no score field** — numeric thresholds are impossible; **rank alone never suffices**.
- **Strong hit** = ALL of: same product/domain, AND same task class, AND written under the current framework/runtime constraints, AND **fresh** — volatile material (libraries, APIs, regulations, availability, best practices) **older than ~30 days degrades to partial**: still evidence for the brainstorm, no longer skip-authority.
- **Epic rule:** a sibling feature's recon inside the same epic is **partial by default**; strong only if it covers this feature's specific delta (actors, workflow, external systems, constraints, currentness).
- Strong hit → skip recon (→ `kb_skip`) and hand those docs to the brainstorm instead. Weak or partial hits do not stop recon: pass them along AND continue to gate 3. **When unsure, it is a weak hit** — continue.
- **Failure transition:** memory command missing, nonzero exit, or invalid JSON → treat as `KB=unavailable`, warn once, continue to gate 3. **Never infer a hit from a failed lookup.**
- Use `search`, never `recall-check` — `recall-check` is the routing-tighten bridge, a different contract, and recon must stay out of routing entirely.

### Gate 3 — Config: `brainstorm.deep_research` = `ask` | `auto` | `off`

Read from `.claude/compound-v.json`. **Fail-closed rule:** Missing file or key → the documented defaults (`deep_research: "ask"`, `batch_elicitation: true`). Malformed JSON, wrong type, or unknown value → warn once, then use `deep_research=ask` and `batch_elicitation=false` for this session; never treat an invalid value as `auto`.

- **`ask` (default):** run the §3 presence check FIRST, then present **one blocking choice** built from the engines actually available — never promise an engine the machine lacks:

  > "I can run a quick research pass before we brainstorm — [one deep-research pass (usually several minutes, spawns subagents), or] up to 6 parallel web searches (usually under a couple of minutes). Note: this sends the topic text to external search services."

  The bracketed clause appears only when deep-research is present. Options (omit unavailable engines): **deep-research pass** / **quick search pass** / **either, with narrowed scope** (the user refines the topic in one line — the human narrows, which reduces anchoring) / **skip**. Semantics, all binding:
  - Exactly one ask per brainstorm; never re-ask after a decline.
  - Cancel, timeout, empty reply, or an unrelated next message = skip (→ `declined`).
  - **Declining deep-research while accepting the quick pass is a RUN with Engine B**, not a decline.
  - Narrowed scope requires nonblank text: if missing, ask once for the one line; still blank → skip (→ `declined`).
  - Cost is stated qualitatively — wall-clock bands and what gets spawned — never as a fabricated number.
- **`auto`:** run without asking — same engine ladder, same output contract. The anti-anchoring header (§4) applies in every mode.
- **`off`:** a **hard kill-switch for external recon, honored absolutely** (→ `off`) — for cost AND confidentiality: recon sends topic text (and, via deep-research, derived queries) to external services. No engine runs, no nagging. **Stated limit:** `off` disables external recon only — gate 2's local V-memory recall may still surface repo-internal docs, and that is by design (nothing leaves the machine).

---

## 3. Engine Ladder

One engine runs per recon, chosen top-down. Recon imposes a **bounded delay** on the brainstorm's first question — bounded by per-rung timeouts, never indefinite. **At most one engine COMPLETES per recon** (the one-completion budget): a failed rung A may fall to rung B, with **both attempts recorded** in the log line and the outcomes stream's `engine` field reflecting the completer.

**A — `deep-research` (bundled skill), if present.**

- The presence check is a **live look at the available-skills listing at fire time**. The `/v:init` capability flag (`deep_research` in `~/.claude/compound-v-capabilities.json`) is an **advisory hint only** — it can go stale (e.g. `disableBundledSkills`); the listing is the contract.
- Invoke through the **skill/slash interface** (its available-skills entry / `/deep-research`). **Never** hard-code a `Workflow({...})` call — the Workflow tool may be absent for a plain subagent — and **never** gate on a Claude Code version number.
- **Timeout: cancel rung A if it has not completed within ~15 minutes**, then fall to rung B. Output of an incomplete A is **discarded** — unless specific claims are individually sourced, which may be kept and the doc labeled **PARTIAL** (title suffix `— PARTIAL`, real reason in the announcement).
- **deep-research returns its report as a MESSAGE and writes no files.** The caller captures the returned report, trims it to the recon format (§4 — five sections, ≤150 lines), and writes + commits the doc itself. Do not assume the native report shape matches the recon contract; the trim is the caller's job.

**B — parallel WebSearch, if deep-research is absent, declined, or failed.**

- **3–6 WebSearch calls in ONE message** (the Phase 1B search pattern: one message, concurrent calls — covering official docs, common pitfalls, hard constraints, recent changes, alternatives). The caller synthesizes the results into the §4 format. Cancel stragglers past ~3 minutes and synthesize from what returned.
- **Permission denial or quota exhaustion: do NOT retry.** If some searches succeeded, synthesize from those only (sourced claims only) and label the doc **PARTIAL**. **Report the real reason** — "WebSearch denied by permission settings", "quota exhausted" — never "no engine available".

**C — skip with explicit notice.**

- No engine available (or every rung failed): announce plainly with the **real reason** — *"recon skipped: <actual failure>"* — mirroring 1C's Context7 degrade notice (→ `no_engine`). Never silently pretend recon ran; never stall waiting for an engine. The brainstorm continues.

---

## 4. Output Contract

**Path:** `docs/superpowers/recon/YYYY-MM-DD-<slug>.md` — ≤150 lines, an anti-anchoring header (a non-section italic line, NOT a heading), then **exactly these five `##` sections in this order**:

```markdown
# Recon — <topic> (YYYY-MM-DD)

*This recon is evidence to widen the brainstorm's questions, not a conclusion to converge on. VERIFIED FACTS / CONSTRAINTS are provisionally binding (1B/1C revalidate); UNVERIFIED LEADS are questions until validated; SUGGESTED DIRECTIONS are read last (directions-late) and are some of several possibilities — generate alternatives that ignore them.*

## QUESTIONS TO ASK
<mistakes-to-avoid framing — empirically stronger than a flat question list>
- Don't ask the user to pick a provider before eliciting the offline-support constraint (leading question; preference before requirement).

## VERIFIED FACTS / CONSTRAINTS
<claims checked against a cited primary source — provisionally binding; 1B/1C revalidate>
- Device-flow user codes expire in 15 minutes [F1].

## UNVERIFIED LEADS
<everything else — must become QUESTIONS until 1B/1C validate; never treated as constraints>
- Vendor X reportedly deprecates API v2 next quarter [F3] — verify in 1C.

## SUGGESTED DIRECTIONS
*Non-exhaustive — these are N of many possible framings; the brainstorm generates alternatives that ignore them.*
<at least 2, prefer 3, materially divergent options>

## SOURCES
- [F1] https://example.com/docs/auth — accessed 2026-07-11 — "user_code expires after 15 minutes"
- [F2] verified manually on 2026-07-11 against <the exact artifact: file, version, command output>
```

Rules, all binding:

1. **The anti-anchoring header is verbatim and mandatory** — the exact italic line above, as one line, in every recon doc, in every mode (`ask` and `auto` alike). It is not a section; the section count stays five.
2. **QUESTIONS lead**, framed as **mistakes-to-avoid**, not a flat question list.
3. **Epistemic split:** VERIFIED = a claim checked against a cited primary source — provisionally binding (1B/1C revalidate). UNVERIFIED LEADS = everything else; leads must become questions until validated. A confidently mislabeled constraint is the most dangerous anchor — when in doubt, it is a lead.
4. **Every claim maps to a source id:** `[F1]`-style ids; each SOURCES entry carries a link (or "verified manually on <date>" **naming the artifact**), the accessed date, and the exact claim it supports.
5. **Directions: at least 2, prefer 3, materially divergent** (small topics can't always yield 3), and explicitly non-exhaustive — the italic template line above is mandatory. **A single recommended approach is forbidden.** The section is **never suppressed** — for compliance-heavy topics the binding rules belong under VERIFIED; the divergence stays.
6. **Slug rule:** derive from the **effective scope** (the narrowed one-line text if given, else the topic): lowercase → unicode-normalize → every non-alphanumeric run → `-` → trim to ≤60 chars; if empty after that, use a short hash of the raw topic. Date = the repo machine's local date.
7. **Create `docs/superpowers/recon/` if absent. Never overwrite:** an existing file at the target path gets a unique suffix (`-2`, `-3`, …) on the new doc.
8. **No YAML front-matter.** The doc starts at the `#` title. **≤150 lines** — a scout report; if it doesn't fit, it's trying to be the audit (that's 1B/1C's job).
9. **No cost numbers.** State findings; never print a fabricated metric (the anti-ruflo rule binds recon output too).
10. **Write, then commit immediately — two separate commands, no `&&`, no editor:**

    ```bash
    git add -- docs/superpowers/recon/<file>.md docs/superpowers/memory/recon-outcomes.jsonl
    git commit -m "docs(recon): <topic>" -- docs/superpowers/recon/<file>.md docs/superpowers/memory/recon-outcomes.jsonl
    ```

    Check each exit code. This is the v2.6.4 discipline — an uncommitted recon doc vanishes on worktree cleanup and never indexes into V-memory (the FTS5 lane indexes **git-tracked** prose), so gate 2 can never hit on it.
11. **On commit failure:** announce *"recon written but not committed: <reason>"* and continue the brainstorm — never claim the doc is committed or indexed when it isn't.

When the doc is committed, announce: *"💉 Compound V — recon saved at `docs/superpowers/recon/<file>.md`. Starting the brainstorm with it (directions-late)."* The brainstorm consumes it per the §1 directions-late protocol and the `consumed` event is appended (§6).

---

## 5. Path Handoff — Exact Path, Not Fuzzy Matching

The caller that ran Trigger 0 **stores the exact recon path in the brainstorm's working state**, and the brainstorm **records that path in the spec's metadata** when it writes one. Every downstream reader (1B, 1C, planning) receives the exact path from its caller. **Scanning `docs/superpowers/recon/` for a matching topic is fallback-only** — used when the handed-off path is missing — and matches on the §4 slug, never on free-text similarity.

---

## 6. recon-outcomes Stream — Append-Only Event Machine

`docs/superpowers/memory/recon-outcomes.jsonl` — one JSON line per EVENT: `{ts, topic, outcome, engine?, path?}`.

```json
{"ts": "2026-07-11T14:02:09Z", "topic": "oauth-device-flow", "outcome": "fired", "engine": "deep-research"}
{"ts": "2026-07-11T14:11:40Z", "topic": "oauth-device-flow", "outcome": "saved", "engine": "deep-research", "path": "docs/superpowers/recon/2026-07-11-oauth-device-flow.md"}
{"ts": "2026-07-11T14:12:05Z", "topic": "oauth-device-flow", "outcome": "consumed", "path": "docs/superpowers/recon/2026-07-11-oauth-device-flow.md"}
```

- **Vocabulary:** terminal gate events `plumbing_skip | kb_skip | off | declined | no_engine`; engine-run events `fired`, `saved`, `consumed`.
- **An evaluation that stops at a gate appends exactly one terminal event.** A run that starts an engine appends `fired`, then `saved` when the doc is committed (with `path`), then `consumed` when the brainstorm reads it — **three separate appended events, never a mutated line**. There is no `consumed` boolean field; consumption IS an event.
- **Writer discipline:** append whole lines only; never rewrite, sort, or dedupe the file. `topic` is the §4 slug; `engine`/`path` appear only when known.
- **Commit:** the `saved` event rides the same commit as the recon doc (§4 rule 10 stages both paths). Gate-skip events with no doc are loss-tolerant telemetry — include them in the next natural commit; never block the brainstorm on this file.
- **NEVER a routing input.** Same boundary as §1: routing stays the deterministic order; the routing scorecard stays implementation-only.

---

## 7. Recon ≠ Pre-Flight — Relationship to 1B/1C

Recon is **reconnaissance**; the pre-flights are the **audit**. Different jobs, different rigor — both run:

| | Phase 0 recon | Phase 1B/1C pre-flights |
|---|---|---|
| When | before the brainstorm's first question | after the brainstorm produces a spec |
| Input | a topic (no spec exists yet) | the full spec |
| Depth | bounded scout pass, ≤150 lines | full domain / library audit with KB persistence |
| Claims | VERIFIED (provisional) + UNVERIFIED LEADS, honestly split | verified against live sources |

- **1B and 1C read the recon doc first** — at the exact path handed to them (§5) — and **deepen** its queries rather than repeating them: VERIFIED facts get revalidated; UNVERIFIED LEADS are leads to verify, not settled facts. See [phase-1b-domain-expert.md](phase-1b-domain-expert.md) and [phase-1c-documentation-validation.md](phase-1c-documentation-validation.md).
- **Recon never substitutes for either pre-flight.** A topic that had recon still gets the full Trigger 1 treatment; a recon doc existing is not a skip justification for 1B or 1C.
- deep-research can ALSO fire **mid-pipeline** as a gated escalation past 1B/1C — that path keeps its own rules in [skill-escalation.md](skill-escalation.md). Two different doors into the same skill, each with its own gate; neither loosens the other.
