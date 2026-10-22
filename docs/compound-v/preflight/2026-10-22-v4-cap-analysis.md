The main failure is **testing individual operations while missing the invariants connecting them**. Some acceptance rows are absent; others exist but their tests prove a weaker—or contradictory—claim. Independent review often repeats those same assumptions.

The supplied list contains census reports and uncapped verdicts. After deduplication, actual caps concern **seven pipeline builds**. This is a selected sample, so it cannot establish an overall cap rate.

| Pipeline build | Capped defect and judge’s reproduction |
|---|---|
| **cv-v4-run-V1** | `HEAD /manage` → **500**, process survives. Also, authenticated `HEAD` to cancellation without CSRF cancels the booking. Judge explicitly bases the cap on the 500. Verdict (`~/Dev/cv-salon-e2e-kit/bv4-brown-2/codex-out.md:50`) |
| **cv-v4-run-G7** | Submit the same default **“Any stylist”** form simultaneously: two appointments, different stylists, same client/time. Verdict (`~/Dev/cv-salon-e2e-kit/bv4-r3-g2/codex-out.md:39`) |
| **cv-v4-run-G8** | Start under `umask 022`: database/backups become **0644**, exposing PII to other local users where parent directories permit traversal. Verdict (`~/Dev/cv-salon-e2e-kit/bv4-r4-g1/codex-out.md:70`) |
| **cv-r-run-R4** | Erase one occurrence, or expire only older occurrences: cleared name/phone remain reidentifiable through `series_id` and retained siblings, including public links. Verdict (`~/Dev/cv-salon-e2e-kit/bv4-r7-rec1/codex-out.md:53`) |
| **cv-r-run-R5** | Valid preview → staff deletes unused service → unchanged confirmation: **200 → 303 → 500**, FK failure, zero bookings. Verdict (`~/Dev/cv-salon-e2e-kit/bv4-r6-rec1/codex-out.md:42`) |
| **cv-v4-run-E1** | Replace/demote manager, log in afresh: another employee’s expense and receipt still return **200**. Verdict (`~/Dev/cv-salon-e2e-kit/bexp-r1/codex-out.md:45`) |
| **cv-v4-run-E1** | Distinct employees sharing a name, owed €10/€20, become one **€30 employee subtotal**. Grand total remains correct. Verdict (`~/Dev/cv-salon-e2e-kit/bexp-r2/codex-out.md:76`) |
| **cv-v4-run-E2** | Replace/demote former manager, fresh login: historical assignment/action still grants another employee’s expense and receipt, **200/200**. Verdict (`~/Dev/cv-salon-e2e-kit/bexp-r2/codex-out.md:38`) |

The causal clusters and missed gates are:

| Root cause | Where it should have been caught; what actually happened |
|---|---|
| **Historical association treated as current authority — E1/E2** | **Acceptance → tests → reviewer.** E1 A47 explicitly requires immediate access loss; its named test deliberately permits historical reads and checks only action denial/new-record isolation. **Contradictory assertion.** E2 tests static roles and pending reassignment, omitting demotion plus historical reads. Review summaries report ordinary IDOR/session checks, not that transition. E1 plan (`~/Dev/cv-v4-run-E1/docs/compound-v/plans/2026-10-22-team-expenses.md:158`), test (`~/Dev/cv-v4-run-E1/tests/visibility.test.ts:90`) |
| **Display label substituted for identity — E1 totals** | **Plan fixtures → builder tests → reviewer.** Per-employee totals were planned, but fixtures had distinct names; arithmetic/CSV agreement cannot detect incorrect grouping. **Missing collision case.** E2’s reviewer caught this same defect and it was fixed—evidence that probe selection matters. E1 tests (`~/Dev/cv-v4-run-E1/tests/finance.test.ts:25`), E2 finding (`~/Dev/cv-v4-run-E2/docs/compound-v/runs/20261022-130039-build-the-team-expenses-review-1.json:17`) |
| **Resource exclusivity mistaken for request idempotency — G7** | **Acceptance composition → tests → reviewer.** Concurrency and “Any stylist” had separate rows. Race tests used different people and a fixed stylist, proving slot exclusivity. Reviewer reports the same one-winner result. **Wrong partition tested.** Plan (`~/Dev/cv-v4-run-G7/docs/compound-v/plans/2026-10-22-salon-booking.md:53`), test (`~/Dev/cv-v4-run-G7/test/http.test.js:14`) |
| **Privacy reduced to clearing columns — R4** | **Spec first**, then acceptance/tests/review. Spec assumes a series without personal columns cannot affect erasure. Tests erase/expire **all siblings**, masking identification through retained siblings. **Wrong model and fixture.** Spec (`~/Dev/cv-r-run-R4/docs/compound-v/specs/2026-10-22-recurring-bookings.md:50`), test (`~/Dev/cv-r-run-R4/test/series.test.js:260`) |
| **Validation checked in isolated operations, not between steps — R5** | **Plan → interleaving tests → reviewer.** Tests cover retired service at preview and deletion after booking, never deletion between preview/confirm. Shared validation runs **after the FK insert**. **Sequence omitted.** Plan (`~/Dev/cv-r-run-R5/docs/compound-v/plans/2026-10-22-recurring-booking.md:69`), write path (`~/Dev/cv-r-run-R5/src/booking.js:318`) |
| **Protection scoped to expected request method — V1** | **Plan/tests → method probes.** S18 requires CSRF for “manage POSTs”; tests mirror that restriction. Router admits HEAD, handlers interpret non-GET as mutation. Reviewer investigated limiter eviction instead. **Method invariant omitted.** Plan (`~/Dev/cv-v4-run-V1/docs/compound-v/plans/2026-10-22-self-service-and-no-shows.md:55`), review (`~/Dev/cv-v4-run-V1/docs/compound-v/runs/20261022-032357-clients-should-be-able-t-review-1.json:3`) |
| **Storage boundary omitted from privacy model — G8** | **Plan/operations tests → reviewer.** Erasure, backup contents and restoration were checked; OS permissions were absent from acceptance/tests and unreported by review. Backup tests (`~/Dev/cv-v4-run-G8/tests/backup.test.js:10`) |

**Receipts cannot repair these omissions.** Final runs have passing receipts, but command success proves only the selected assertions. V1’s “live” check was even fetch-based HTTP, not a browser. The current CLI checks exit status and review coverage declarations, not whether assertions entail acceptance promises. V1 plan (`~/Dev/cv-v4-run-V1/docs/compound-v/plans/2026-10-22-self-service-and-no-shows.md:112`), receipt implementation (`scripts/cvcore/receipts.py:170`)

**Smaller surface explains some control results, not all.** Expense capability counts are E1 **98**, E2 **92**, EP **67**, EL **93**. EP omits substantial operational flows, but also passes the demotion-access probe; equally broad EL shares the access defect and cap. Salon A is much narrower, whereas A5 has **85** capabilities versus G10’s **83** and G11’s **82**. RP is capped despite its smaller recurring implementation. “Plain Claude is safer” is unsupported. Expense census (`~/Dev/cv-salon-e2e-kit/bexp-c2/codex-out.md:164`), salon census (`~/Dev/cv-salon-e2e-kit/bv4-r5-c2/codex-out.md:160`)

The highest-leverage changes are:

1. **Audit acceptance-to-assertion meaning**, especially negative/security promises. Require the reviewer to inspect actual assertions, not test names or green results. Prevents E1’s direct contradiction.
2. **Generate tests from changed relationships and sequences:** permission change → reread; partial erasure → traverse; preview → dependency change → commit. Covers E1/E2/R4/R5.
3. **Use adversarial fixture pairs:** same label/different IDs; same request/different available resources. Covers E1 totals/G7.
4. **Reserve review capacity for boundary probes and retain executable evidence:** methods, production file permissions, and changed-flow interactions. Missing required evidence means incomplete. Covers V1/G8 and untested sequences.

Several rules already entered the instructions during these rounds, including interleaving and current-state permissions. Enforce their evidence; **do not add another long checklist**, blanket extra review rounds, or more repetitive malformed-input tests.

**Split the benchmark into raw product score plus an explicit release gate.** Cap application is noisy: G8’s 0644 exposure was documented at **82 uncapped**, then capped at **50**. R4’s later cap reflects newly discovered evidence, a different issue. Meanwhile R5’s zero-write 500 caps an otherwise 82-point build, while R4’s unapproved-date substitutions merely deduct points. Uncapped G8 (`~/Dev/cv-salon-e2e-kit/bv4-r3-g2/codex-out.md:50`)

Retain hard gates for demonstrated unauthorized access/mutation, consequential corruption, and unusable core flows. Define actor, reachability, impact and recovery explicitly; distinguish request errors from process crashes. Publish both scores and run the same mandatory cap probes across candidates.

Read-only analysis of saved evidence; reproductions were not rerun.