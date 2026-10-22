# Compound V v4 vs plain Claude Code — benchmark summary (2026-10-22)

Two unrelated product briefs, built from scratch, plus changes to existing code. Same model (Claude Opus 5.5), same
machine and sandbox, headless `claude -p`. Every product was judged **blind** by Codex (gpt-6-astra), which ran the
code and its own probes; labels were shuffled and each build was judged at least twice. Full data and method:
`~/Dev/cv-salon-e2e-kit/V4-RESULTS.md` and `v4-protocol.md`; earlier history in `docs/v4/salon-report.md`.

**How to read the scores.** *Rubric* (0–100): requirements verified by running, correctness under the judge's own
edge-case probes, product thinking, security & privacy, code & tests, operability. A demonstrated critical defect
caps the total at 50. *Capabilities*: the judge lists every user-facing capability any build has (or a real customer
would expect) and grades each 0–3; **considered** = handled edge cases and user mistakes (level ≥ 2). Cost is the
CLI's own estimate of Claude spend; time is machine time (the simulated owner answered instantly).

## 1. Salon booking app (greenfield) — same blind sets

| | Plain Claude Code | **Compound V v4** | Comment |
|---|---|---|---|
| Cost | $1.31 | **$10.6–11.1** | ~8× the spend; earlier rounds measured $8.1–9.2 on a bench that, by mistake, denied the builder reads of the plugin's own checklists |
| Time | 3.5 min | ~33–35 min | plain asks nothing and stops after one pass |
| Rubric (blind ×4) | 61, 61, 57, 61 → **60** | 83, 86, 90, 87, 76, 84 → **84** | +24 points |
| Capabilities present | ~41 | ~80 | v4 builds about twice as much product |
| Capabilities considered | ~25 | ~71 | ~3× the edge cases and user mistakes handled |
| Security & privacy (judges) | 1/5: session survives logout, no login or spam throttling, past slots bookable on a UTC host | 4–5/5: fail-closed config, session revocation, CSRF, throttling, PII-free confirmations | the plain build would go to a client with these holes |
| Product depth | basic booking + staff list | staff breaks and days off, walk-ins, editable services and prices, salon time zone, retention and erasure, backups | v4's brainstorm asked the owner what the plain run never asked |
| Verification | its own unit tests | tests + real-browser test + independent review + scope check, all bound to the final code | v4 cannot report "done" without them |

## 1b. Salon: plain Claude with a developer iterating, and the product/UX view

A developer agent built with plain Claude Code from the PRD **plus the owner's answers**, then checked the app the way a
busy developer does before handover and sent fixes (1–2 problems per round) until it would hand over.

| | Plain, one prompt | Plain + requirements + developer rounds | Compound V v4 | v4 + design skill |
|---|---|---|---|---|
| Cost | $1.31 | $2.27, ~7 min machine time, 2 developer rounds | $8.1–11.1 | $10.60 |
| Rubric (blind) | 60 | 61, 61 | 74–84 | 80, 84 |
| Capabilities considered | ~25 | ~39 | ~73 | — |
| Security & privacy | 1/5 | 1/5 | 4–5/5 | 4–5/5 |
| Product & UX, Codex judges | 50, 50, 50 | 63, 63, 60 | 77, 74, 74, 65; 77 without design skill, same bench | **83, 83** |
| Product & UX, Gemini judge | 35, 35, 42 | 74, 63 | 82, 77, 77; 80 without design skill | **100, 100** |

The developer found one problem (a per-phone limit bypass) and handed over; the judges then found what that check
missed: the session survives logout, 24 fake bookings from one source, a 500 on a malformed cookie, names with
joiners rejected, no service or price management. The product judges (a PM and a designer, blind, from screenshots
and flows) sent the one-prompt build back at once: "staff cannot even log a walk-in or block a lunch break". The design
skill (`DESIGN.md`, shared components, a screenshot check) added about **+13 UX points** against the same plugin
without it, in the same sets, at no measurable extra cost.

## 2. Team expenses app (greenfield, another domain; TypeScript, Fastify, Drizzle, Zod) — brief incl. the owner's requirements

| | Plain, PRD only | Plain, PRD + owner's answers | **Compound V v4** | Comment |
|---|---|---|---|---|
| Cost | $2.62 | $3.25 | **$12.22** | 4–5× the spend |
| Time | 9 min | 11 min | ~38 min | |
| Rubric uncapped (×2) | 58, 46 → **52** | 69, 49 → **59** | 90, 70 → **80** | +21 to +28 points |
| Rubric final (×2) | 52 | 50, 49 → 49.5 | 90, 50 → 70 | one v4 cap: `tsc` failed on a Fastify type (the app ran via tsx) — now a rule: the type-checker is part of the tests |
| Capabilities considered | ~44 | ~52 | **~82** | second approval > €500, deputies, deactivation, retired categories, 10-year retention |
| Library versions | latest majors | latest majors | latest majors, pinned exactly | all used Fastify 5, Drizzle 0.45, Zod 4, TypeScript 7 |

## 3. Changing existing code

| Task | Plain / manual reference | **Compound V v4** | Comment |
|---|---|---|---|
| Self-service cancel/move + no-shows on an existing salon app | light flow (one agent + checklists + self-review) $5.30, 15 min: 78, 75, 75, 78 | $7.3–9.1, ~22–26 min: **93, 93, 93, 93, 78, 90** | the original v3 pipeline scored 69, 69 here at $15.77 |
| Recurring bookings on an app v4 itself built | plain Claude $3.59, 9 min: capped in 5 of 6 judgements (a staff delete crashes after a series; erased bookings still lead to a sibling's name) | $8.56, 25 min: **85, 93**, no cap | v4 reads the code first and maps every rule, operation and guard the change touches |

## 4. Against the previous Compound V (v3.9, full orchestration engine)
Salon: v3 cost $31.71 and 49 min and scored 62–72 in the sets where the light flow scored 94–99; v4 now matches or
beats the light flow. Existing-code change: v3 69 / 69 at $15.77; v4 84–93 at $7–9.

## What this means
Compound V spends **4–8× more Claude money** and **~3–9× more machine time** than a single plain prompt, and in return
the product: is **~25 points higher** on blind, run-based judging in both domains; covers **about twice the
capabilities and ~2–3× the considered edge cases**; and ships far fewer of the defects that bounce a delivery back from
a client (open sessions after logout, no abuse limits, wrong time zone, access kept after a role change, crashes on
ordinary operations), because it asks the owner first, builds against a checklist grounded in OWASP ASVS / WSTG,
RFC 9110 and WCAG, and cannot call the work done until tests, a real browser, an independent reviewer and a scope check
pass on the final code.

## Caveats (stated, not hidden)
- One or two builds per condition; the same build moves about ±10 points between judges, so read means, not single runs.
- The product owner was simulated by an agent answering from a fixed answers file; real owners answer differently.
- One developer-iteration run (§1b) closed a small part of the gap (UX, not security); one run is not a distribution.
- The design-skill rounds are one build each; Gemini's 100s are generous, Codex's +6 to +13 is the safer reading.
- Critical-defect caps are noisy between judges; uncapped and capped totals are both reported where they differ.
- Costs are the CLI's estimates, not invoices; Codex review time is not included in Compound V's cost.
