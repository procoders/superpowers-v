# v4 reviewer yield: what the independent reviewer found, missed, and cost (2026-10-22)

Sources: the 60 findings in `cv-v4-run-*/docs/compound-v/runs/*-review-*.json` plus run records; 18 Codex verdicts
`cv-salon-e2e-kit/bv4-*/codex-out.md` via `*-mapping.txt` (deduped per run dir, counted when ≥1 judge run reproduced it;
census judges c1–c4 only where a row names a concrete failure); the four light-flow `REVIEW.md`; 21 reviewer transcripts
(G2 wrote no findings). V3 was never judged.

## A. Reviewer finding categories (60)

"Real" = fixed with a test, or the same defect was confirmed by a judge. "Noise" = low-value, theoretical, inferred, or
self-inflicted churn.

| # | Category | n | Max sev | Example title | Real / noise |
|---|---|---:|---|---|---|
| 1 | Shipped example/placeholder config accepted in production | 6 | high | G3 "README's copy-paste STAFF_PASSWORD accepted" | 6 / 0 |
| 2 | Password/secret strength heuristics (follow-up tail) | 8 | medium | G5 "Weak but non-placeholder secrets are accepted" | 0 / 8 (incl. a denylist the reviewer pushed for, which then refused random secrets) |
| 3 | Server-side session lifecycle (logout, rotation, expiry) | 5 | medium | G4 "cookie valid after logout and password rotation" | 5 / 0 |
| 4 | Private pages cacheable (no `no-store`) | 1 | medium | G1 r2 F1 | 1 / 0 (left open; 4 judge runs confirm) |
| 5 | Phone identity normalisation (limit/erasure bypass) | 9 | high | G4 "limit still bypassed with '+00'" | 6 / 3 |
| 6 | Name/Unicode validation | 6 | medium | G3 "Names with ZWNJ/ZWJ are refused" | 2 / 4 (invisible-char taxonomy) |
| 7 | Limiter eviction / oracles / unthrottled endpoint | 6 | medium | V4 "lock evicted by flooding the 20,000-key limiter" | 1 / 5 (never tested by any judge) |
| 8 | Erasure/retention misses a copy | 4 | medium | H4 "membership number survives erasure" | 4 / 0 |
| 9 | Malformed input → 500 | 3 | medium | G1 "malformed %-encoding returns 500" | 3 / 0 |
| 10 | New-path rule semantics (move, no-show history) | 7 | low | V4 "past no-shows counts later ones" | 3 / 4 (same-slot "moved" message ×3) |
| 11 | UI/doc promise not backed by behaviour | 2 | low | V3 "texts promise a staff move that does not exist" | 1 / 1 |
| 12 | Origin/CSRF mechanics | 2 | high | G1 "behind nginx every POST 403 (inferred)" | 1 / 1 (inferred) |
| 13 | Test drift | 1 | low | H4 "expiry test no longer tests expiry" | 1 / 0 |
| | **Total** | **60** | | | **34 / 26** |

Two severity misses matter more than the counts. **G4 fix r2 F2** (leading-zero stripping) was logged *low*; judges r3/r4
called it data-corrupting, correctness 1/5 (`02079460958` → `2079460958`), and it came from the reviewer's own three-round
prefix chase. **G3 r2 F3** (no server-side session lifetime) was logged *low*; judges r1/r2 scored security 2/5 and census c1/c2 rated it 1 and 0 of 3, and
the cookie also survived a password change.

## B. Material defects that survived review (judge-found)

| Cluster | v4 runs where it survived | Reviewer findings in this cluster |
|---|---|---|
| **Time rules truncated to the minute / wrong at the exact boundary** (59 s late accepted, exact 120 min refused, and, interpretation-dependent, "two days" = 50–51 h vs a judge's 48 h) | G1, G5, V2, V5, H4 (G4 likely, r4) | 0 |
| **Volume abuse with invented identities** (12–25 fake bookings per IP, IPv6 /64 rotation, unthrottled code lookups) | G1, G3, G4, G5, G6, V5 | 0 (6 on eviction theory instead) |
| **"Same rules as X" not enumerated** (move skips the per-phone cap; closure ignores a later-added stylist; break over an in-progress booking) | V1, V2, V5, G1, G5, G6 | 0 (V2's summary asserts parity) |
| **Non-form methods / malformed input** (**V1: `HEAD` cancels a booking without CSRF**, score capped at 50; malformed URI, 250 params, JSON login → 500) | V1, G3, G5 | 1 (G1, fixed; same bug survived in G3) |
| **Erasure vs copies and privacy copy** (backup restore resurrects erased PII; `no_show_at` kept despite the privacy copy; WAL bytes) | H4, G3, V1, G6 | 4 found in H4, but not restore |
| **Normaliser corrupts or validator accepts junk** (`02079…` loses its zero; `12+34567`, `912++345678` accepted) | G4, G3, H4 | reviewer-induced in G4 |
| **First-run placeholder contact shown/accepted in production** | G4, G5, G6 | found and fixed in G1, G3 only |
| **State/copy lies** (`?msg=cancelled` shown for an active booking; error-path slots use the old duration) | V2, V4 | V2 found only the prototype-key cosmetic variant; V4 F4 left open |
| Session residual, private-page caching, umask 0644 DB | G3; G1, H4; G3, G6 | G3 downgraded; G1 left open; 0 |

Brownfield is starkest: V1, V2 and V5 reviewers returned 7 lows; judges found 2–4 material defects in each.

## C. Self-review (same session) vs independent reviewer

| Category | Self-review caught | Self-review missed |
|---|---|---|
| Time boundaries | L1 R3 (notice drops seconds; judges confirm fixed) | A5 (5 judge runs); C-light lists "exactly 120 min allowed, 119 refused" as *checked OK*, testing in its own minute units, while judges got a change through 59 s late; HL 54–55 h lapse |
| Volume abuse | A5 R4/R5 (5 successes/IP/day, IPv6 /64), L1 R5 | L1 IPv6 /64 login |
| Rule parity / state | L1 R4 (break over active booking), C-light R13 (no-show frees cells), R15 (later no-shows), R17 (same-slot "moved"), HL R3 (purge with open reservation) | A5 closure vs later-added stylist |
| Phone/name input | A5 R3 (canonical phone), R6 (ZWNJ) | L1 ZWNJ; HL `+000000000` |
| Config / deploy | A5 R1 **Origin: null → every POST 403** (critical), R11/L1 R6/HL R6 proxy trust, L1 R1 placeholder contact, A5 R9/L1 R2 umask | A5 README example password refused |
| Methods / malformed | none | A5 HEAD 500, A5/L1 DB-busy 500, HL multibyte CSRF 500 |
| Erasure / privacy copy | HL R4/R5: erasure replayed after a restore (judges confirm; H4 resurrected PII), log line after commit | L1 restore resurrects PII, L1 WAL bytes, C-light no-show note |
| Sessions | all four verified revocation; census rates A5 and L1 3/3 | none |

Self-review caught about as many real issues as the reviewer, including the volume-abuse class the reviewer never
found. The independent reviewer adds value where an executing outsider is needed: starting the app with the README's own
example values (cat. 1), replaying a cookie (cat. 3), sending bytes no form sends (cat. 9), and re-verifying fixes (G4
"+00", G5 "+351 0"). Both missed the same classes: boundaries in the request's units, "same rules as X" rule by rule,
non-form methods, privacy copy vs stored columns, and backup restore.

## D. Cost vs yield

| Run | Passes (turns) | Cache-read | Real high/medium |
|---|---|---:|---:|
| G1 | r1 15, r2 12 | 1.63M | 4 (+1 inferred) |
| G3 | r1 32, r2 17 | 3.30M | 5 |
| G4 | build 26, fix r1 17, fix r2 9 | 3.02M | 2 |
| G5 | r1 31, r2 20, fu r1 15, fu r2 14 | 4.70M | 4 |
| G6 | r1 56 | 4.81M | 1 |
| H4 | r1 26, fu 19 | 3.07M | 2 |
| V1 / V2 / V5 | 18 / 24 / 25 | 1.51 / 1.72 / 1.56M | 0 / 0 / 0 |
| V3 | r1 30, fu 5 | 2.11M | 0 (not judged) |
| V4 | r1 36, fu 22 | 3.97M | 0 (2 theoretical) |
| **Σ** | **21 passes** | **31.4M** | **18** |

Turns and cache-read are summed from the `usage` fields of each `compound-v:reviewer` transcript. Turns do not predict
yield (G1 r1: 15 turns, 2 highs; V4 r1: 36 turns, 0). Old-prompt round-1 median: 26 turns / 1.9M. The "4.8M / 56 steps"
headline is G6 alone, and by transcript grep it is the only reviewer whose prompt had the new "full precision" / HEAD
lines: it swept every rule and route of a build the judges rate clean on those axes (r5, r6, c4). Five greenfield/holdout
round-1 passes (9.4M) produced 14 of the 18 real findings; seven brownfield passes (10.9M) produced none a judge
confirmed. Fix runs (G4, G5, H4, V3, V4) each re-triggered review; the G4/G5 phone chain alone took 7 passes.

## E. Proposal: a sharp reviewer

**Probes, in yield order**, derived from the request text before touching the app and batched into probe scripts:

1. **Every time or number rule at −1 s / exact / +1 s** in the business timezone and in the request's own unit ("2 hours"
   = 7200 s, "2 days" = 48 h). Survived in 6 v4 runs and 3 light runs; reviewer yield so far: 0.
2. **"Same rules as X", rule by rule.** List every check X's code enforces (caps, closures, breaks, in-progress bookings,
   retries) and run each one against the new path. Survived in 6 runs.
3. **Every mutating route with HEAD/OPTIONS/GET**, plus malformed %-encoding, multibyte tokens, a wrong content type and
   a few hundred params. Any 500 is a finding; a mutation is a blocker (V1).
4. **Volume abuse with rotating identity**: N successes from one IP with invented phones, addresses within one IPv6 /64,
   and one code guessed from many IPs. Survived in 6 runs; 0 found.
5. **Sessions**: replay after logout, after a password change, and after expiry with the clock advanced. Severity floor:
   medium.
6. **Production start with every value from `.env.example`, README and operator docs**, plus placeholder contact details.
7. **Erasure vs every copy**: each column the privacy copy names, the WAL, backup → restore, and logs.
8. **Normaliser round-trip**: valid foreign and leading-zero inputs survive unchanged; two spellings of one identity
   collide. Stop at the first bypass.
9. **Visible copy and query-driven notices vs stored state** (`?msg=`, "call us", "staff can move").
10. **`no-store` on PII pages, and the DB/backup file mode.**

**Skip or spot-check once.** Acceptance rows the builder's tests cover (confirm the test exists, run one); races (every
judge race passed in every build); basic CSRF/XSS (all passed). Never chase: password-denylist quality, invisible-Unicode
taxonomy (keep one probe: ZWNJ/ZWJ names accepted), limiter-eviction theory, prefix variants after the first bypass,
README wording, same-slot "moved" notices. These hold 25 of the 26 noise findings.

**Budget** (proposed, not measured): round 1 ≤20 turns (`maxTurns` 25), one probe script per probe group; fix
verification ≤10 turns.

**Round 2.** It earned its cost only as fix verification: it caught the G4 "+00" and G5 "+351 0" incomplete fixes at 9–20
turns. Its open exploration produced most of the noise tail (password, Unicode, prefix) and rubber-stamped G3's session
residual. Keep round 2 limited to re-checking round-1 fixes, each with one regression probe, and no new exploration. A
round-1 security or data finding may not be downgraded without a regression test in the tree. A follow-up fix run gets
that same verify-only pass, not a fresh two-round review.

**Severity rules to add.** Any normaliser that rewrites a valid stored value is at least high. A session that survives
logout, rotation or expiry is at least medium. A state change via HEAD/GET is a blocker.
