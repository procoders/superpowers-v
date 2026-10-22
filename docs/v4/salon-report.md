# Salon run — Compound V 3.9.1 vs plain Claude Code (2026-10-21)

> **Cost correction (2026-10-22, before v4's benchmark).** `total_cost_usd` in `claude -p --output-format json` is
> cumulative for the session when a turn resumes it (verified: A5 turn 2's `modelUsage` output tokens = turn 1 + turn 2).
> Earlier figures summed it across turns and so overstated every multi-turn run. Corrected = the last turn's value per
> session: A $1.31, A2 $1.42, A3 $2.03, A5 **$4.82** (was ~$8.1), B **$31.71** incl. the fix round (was ~$87; the
> before/after-fix split is not recomputed), C-light **$5.30** (was ~$8.8), C-full **$15.77** (was ~$17.8), parallel
> $4.56 / single $3.60. A4's logs hold one session, $1.77 / 4.3 min; the ~$3.8 / 11 min below included work outside
> those logs and is unverified. Quality scores and times are unaffected. Costs in the tables below are corrected.

Same `prd.md` (our stand-in brief), same model (Claude Opus 5.5), same machine, headless `claude -p`, Claude Code
sandbox (no network except package registries, no writes outside the repo), user settings excluded
(`--setting-sources project,local`), no MCP servers. Only the plugins differ.

| Run | Plugins | Wall / agent time | Tokens (cache read / cache write / output) | CLI cost estimate | Tests | Blind score (Gemini 4 Argon) |
|---|---|---|---|---|---|---|
| A  | none | 3.5 min, 1 turn, asked no questions | 0.83 M / 78 k / 26 k | ~$1.3 | 15 | 6.0 (vs B) · 7.0 (3-way) |
| A2 | none, plan mode first, then live curl checks | 4 min | 1.17 M / 80 k / 27 k | $1.42 | 19 + curl | 6.5 (3-way) |
| B  | Superpowers + Compound V (cost-aware, lightweight) | ~37 min agent time (49 min wall incl. answering 4 brainstorm rounds) | Opus 33.9 M / 1.40 M / 105 k · Sonnet 0.88 M / 0.36 M / 24 k | see note | 109 | 9.0 (vs A) · 8.5 (3-way) |

Account quota during B (Max plan, other sessions active, so an upper bound): weekly 43% → 45%, Fable 3% → 3%.
Before any app code (brainstorm + spec + pre-flights + plan): ≤ 1% weekly, 0% Fable. Sumit reported 5% + 3% Fable.

Blind verdict (both comparisons): only the Compound V build would be handed to a real salon. It has stylist
breaks/days off, phone/walk-in bookings, salon timezone, CSRF, rate limits, per-phone cap, GDPR retention. Both plain
builds pass the literal PRD checks but lack abuse protection and day-to-day salon operations. Main defect found in
B (also by its own final review): a `dev-password` fallback outside `NODE_ENV=production`.

Part of B's advantage came from the brainstorm answers (breaks, phone cap, privacy, Portugal/GDPR) — the questions
the plain runs never asked. That is the difference Sumit asked for.

## Final comparison — finished product, rubric judged by Codex (gpt-6-astra), blind, ran the code

B continued with the fix round its own final review proposed (all 7 findings confirmed and fixed, incl. the
`dev-password` fallback; 12 min; cost split not recomputed). Rubric (`blind6/RUBRIC.md`): PRD conformance verified by running (30),
correctness under real use with the judge's own probes (20), product thinking (20), security & privacy (15),
code & tests (10), operability (5); anchored 1–5 scales; a critical defect caps the total at 50.

| Run | Agent time | CLI cost | Tests | Codex total |
|---|---|---|---|---|
| B — Compound V incl. fix round | ~49 min | $31.71 | 119 | **79** (PRD 4, correctness 3, product 4, security 4, code 5, ops 5) |
| A — plain | 3.5 min | ~$1.3 | 15 | 61 (PRD 5, correctness 2, product 3, security 1, code 3, ops 2) |
| A2 — plain, plan + live curl | 4 min | ~$2 | 19 | 54 (PRD 4, correctness 2, product 2, security 2, code 3, ops 2) |

B tokens incl. fix round: Opus 46.9 M cache read / 2.20 M cache write / 137 k output; Sonnet 1.18 M / 0.50 M / 38 k.
Defects Codex reproduced in the plain builds: staff session survives logout and its 12 h lifetime; no login or
fake-booking throttling; host-timezone scheduling (past Lisbon slots bookable on a UTC host); price edits rewrite past
confirmations. Left in B: working hours not shown in the client flow, 60-min notice rounded to the minute, no 45-min
services. Before the fix round the same rubric capped B at 50 (69 uncapped) for the `dev-password` default.
Judge disagreement: Gemini 4 Argon, same rubric but reading only, scored the pre-fix B 100 and missed that defect —
running-based judging is the one to trust.

## Where the depth comes from (A3 = plain Claude Code + the owner's brainstorm answers), Codex blind, 4 builds

| Run | Agent time | CLI cost | Census present / considered / production / sum (103-ish capabilities) | Rubric |
|---|---|---|---|---|
| B — Compound V incl. fix round | ~49 min | $31.71 | 85 / 80 / 18 / 183 | 84 |
| A3 — plain + owner answers | 7 min | ~$2 | 77 / 63 / 4 / 144 | 73 |
| A — plain | 3.5 min | ~$1.3 | 55 / 37 / 4 / 96 | 65 |
| A2 — plain, plan + live curl | 4 min | ~$2 | 52 / 32 / 4 / 88 | 57 |

Reading: roughly half of B's lead comes from the answers its brainstorm collected (cheap — a plain build implements
them in 7 min for ~$2); the other half, mostly production-grade depth (server-side logout, CSRF, abuse limits, salon
timezone, erasure, config validation, ops docs), comes from the pipeline's pre-flights, review and fix round, at ~15×
the cost. Direction for v4: a light mode (brainstorm → one build agent → one review/fix pass) to test next (A4).

## A4 / A5 — the light flow, judged blind ×2 (census) and ×2 (rubric) by Codex

A4 = A3 + one review/fix pass (same reviewer prompt as A5). A5 = plain Claude Code + owner answers + `light-flow.md`
(jurisdiction research, four checklists: data lifecycle, every page/state, every form/endpoint, operations; acceptance
table) + the same review/fix pass.

| Run | Agent time | CLI cost | Considered (census ×2) | Sum (census ×2) | Rubric (×2) |
|---|---|---|---|---|---|
| **A5** | ~17.5 min | $4.82 | **72 / 79** | **153 / 171** | **94 / 99** |
| B — Compound V incl. fix | ~49 min | $31.71 | 52 / 65 | 120 / 144 | 62 / 72 |
| A4 | ~11 min | $1.77 (see note) | 45 / 34 | 110 / 108 | 45 / 49 (critical) |

A4's critical defect (found in both rubric runs, missed by the earlier single run): `Referrer-Policy: no-referrer`
plus an Origin check that rejects `null` → every real browser form POST gets 403. A5 had the same bug; its review
found it by checking the Fetch spec. Lesson: in-process tests cannot catch it — a real-browser check belongs in the
flow. Judge noise: the same build moves ~10 points between runs; use ≥2 runs per comparison.
Conclusion: the light flow with checklists beat the full pipeline on every blind judgement at ~15% of the cost.

## Brownfield check — one feature on A5's existing code (self-service cancel/move by code + phone, 2 h cutoff, no-shows)

| Run | Agent time | CLI cost | Tests | Codex blind (×2, labels swapped) |
|---|---|---|---|---|
| C-light — read code first + light-flow checklists + one review/fix pass | ~15.5 min | $5.30 | 77 | **75 / 78** |
| C-full — Compound V 3.9.1 (brainstorm → spec → pre-flights → plan → 3 jobs in 2 waves → review) | ~28 min | $15.77 | 88 | 69 / 69 |

Both: no regressions (BASE's 58 tests pass), same security of the new surface, no double booking under races.
C-full lost on its own spec decisions that departed from the request: a move skips the per-phone limit, existing
bookings can't be marked no-show, a no-show keeps its slot occupied and still reads "confirmed". C-light lost on a
false privacy promise (no-show note survives erasure). Both: the 2 h cutoff is late by up to 59 s (seconds dropped).
The light flow wins brownfield too, at half the time and cost; the parallel waves added nothing at this size.

## What the run exposed in Compound V (for 3.9.2 / v4)
- `finalize-wave` on a relaunch re-gated a fully integrated wave → `stale` → halt (the model patched the run's script).
- Headless `-p` ends the process with the turn, killing a background Workflow (interactive sessions are unaffected).
- `/v:init` does not resolve; only `/superpowers-v:v-init` does → v4 renames the plugin to `compound-v`.
- The sandbox write-protects `.claude/` configs: `/v:init` writes need a user approval.
- Greenfield 1A skip was defeated by our own `docs/superpowers/*.json` (fixed locally).
- Triage journal defaulted to the plugin directory instead of the project.
- Cost: ~25× the corrected CLI cost and ~10× the time of plain Claude Code; Pro fit not established.

Raw data: `logs/cv-salon-run-{A,A2,B}/` (per-turn JSON, wall.txt, usage-*.json), `blind/`, `blind3/` (verdicts,
mappings in `blind-mapping.txt`, `blind3-mapping.txt`).

## v4 rounds G14–G15 and P1 — product/UX judges (2026-10-22; data: kit `V4-RESULTS.md`, sets ux-r1…r7, bv4-r8-g1, bv4-r9-g1)

Costs are the CLI's estimate (last turn per session). UX = `RUBRIC-ux.md`, blind PM + designer judging screenshots and flows.

| Build | Cost | Rubric | UX Codex | UX Gemini |
|---|---|---|---|---|
| A, plain one prompt | $1.31 | 60 | 50, 50, 50, 50 | 35, 35, 42 |
| P1, plain + requirements + developer rounds | $2.27 | 61, 61 | 63, 63, 60 | 74, 63 |
| G13, v4 (bench denied reads of the plugin's checklists) | $8.1–9.2 | 74–83, 79 | 77, 74, 74, 65 | 82, 77, 77 |
| G15, v4 at 873709c, reads allowed | $11.13 | 83 | 77 | 80 |
| G14, v4 + design skill (893b541), reads allowed | $10.60 | 84, 80 | 83, 83 | 100, 100 |

G14 vs G15 in the same sets: +6 (Codex) and +20 (Gemini) UX, rubric level, cost within noise. A judging finding
became the S6 lockout rule: in bv4-r9 the build that locked out the correct login after failures from many networks
was G15 (security 2/5; G14 3/5). The product quote "the only version that looks like a real boutique salon brand" is
Gemini's on G14 (ux-r5).

Plain vs v4 head-to-head (kit sets bfin-s and the release-gate set): plain A rubric 61 / 61, 57 / 61; considered
capabilities 20 / 30, 23 / 25 (~25). v4 G10, G12, G13 considered 66 / 85, 61 / 76, 70 / 72 (~71). The judges' security
dimension: plain 1/5 in every set; v4 4–5/5.
