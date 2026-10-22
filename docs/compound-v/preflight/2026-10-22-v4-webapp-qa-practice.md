# v4 web-app QA practice: our lists against recognised sources (2026-10-22)

Inputs: `skills/plan/checklists.md` (42 items), `skills/verify/review-prompt.md` (probes 0–10), the yield report
`2026-10-22-v4-reviewer-yield.md`. Every count below comes from that yield report; every ranking not backed by it is
marked **(judgement)**.

Sources: **ASVS 5.0.0** (stable tag, 2025-05-30), cited as `A x.y.z`. WSTG ids from the master checklist. OWASP Cheat
Sheets (CS). API Top 10 2023. OWASP Automated Threats (`OAT`). RFC 9110. WCAG 2.2 (`SC`). GOV.UK Design System.
Idempotency-Key draft-07 (**expired, not an RFC**: 422 for a different payload, 409 while in flight). Stripe
idempotency docs. W3C *Working with Time and Timezones* (draft note, 2025). GDPR. The Hendrickson *Test Heuristics
Cheat Sheet*. Bach HTSM.

## A. Mapping

Status: ✓ backed · ◐ partly / our tuning · S salon-shaped wording · — no external backing (practice or process).

| Item | Source | St. | Note |
|---|---|---|---|
| R1 rule→row, "same as X" expanded | A 2.1.3, 2.3.2; WSTG-BUSL-01 | ✓ | |
| R2 boundary rows, phrase→comparison | Hendrickson Boundaries/Goldilocks; A 2.2.1 | ◐ | phrase semantics are ours |
| R3 existing rules on new path | WSTG-BUSL-06; HICCUPS History/Product | ✓ | |
| R4 no invented restriction | A 6.1.1 ("prevent malicious account lockout"); GOV.UK names | ◐ | |
| J1, J6 research rows, assumptions | — | — | pipeline process |
| J2 privacy notice/rights/retention | GDPR Art. 5(1)(e), 13, 15, 17 | ✓ | |
| J3 price/tax, complaints | Directive 2011/83/EU Art. 6 | ◐ | commerce only |
| J4 accessibility | WCAG 2.2 AA; Directive (EU) 2019/882 | ✓ | |
| J5 stack traps (copies, tz, proxy) | GDPR 17; W3C tz note; A 4.1.3, 15.3.4 | ✓ | three classes in one row |
| D1 lifecycle, history keeps values | Hendrickson CRUD, Follow the Data | ◐ | |
| D2 operator config | W3C tz (locale) | S | "hours, staff, services" |
| D3 access/erasure every copy | GDPR 15, 17; A 14.2.7 | ✓ | |
| D4 backup + tested restore | GDPR 32(1)(c),(d) | ✓ | |
| D5 survives restart | HTSM Operations; Hendrickson Interrupt | ◐ | |
| P1 empty state | Hendrickson Count (zero) | ✓ | |
| P2 error says what to do | SC 3.3.1, 3.3.3; GOV.UK error message | ✓ | |
| P3 no-longer-valid states | A 6.5.1, 6.5.5; Hendrickson Navigation | ✓ | |
| P4 keyboard, labels, small screens | SC 2.1.1, 1.3.1, 4.1.2, 1.4.10, 2.5.8 | ✓ | |
| P5 business contact details | Directive 2000/31/EC Art. 5 | S | |
| P6 every script, ZWJ/ZWNJ | Input Validation CS (free-form Unicode); W3C personal names | ✓ | ZWJ detail narrow |
| F1 auth fails closed | A 13.2.3, 6.3.2, 16.5.3; WSTG-ATHN-02 | ✓ | |
| F2 session expiry/revocation | A 7.3.1, 7.3.2, 7.4.1, 7.4.3; WSTG-SESS-06/07 | ✓ | credential-change revocation is stricter than 7.4.3's "option" |
| F3 CSRF incl. public forms, real browser | A 3.5.1; CSRF CS; WSTG-SESS-05 | ✓ | CS: never allowlist `Origin: null`. Fix = token or `Sec-Fetch-Site`, not accepting `null` |
| F4 output escaping | A 1.2.1, 3.2.2; WSTG-INPV-01/02 | ✓ | |
| F5 size limits, codes | A 2.2.1, 5.2.1; API4; RFC 9110 §15.5.14 | ✓ | |
| F6 rate limits per target | A 2.4.1, 6.3.1; API6; OAT-002/008/019/021 | ◐ | per-/64 keying = practice, no standard |
| F7 no PII in URLs/caches | A 14.2.1, 14.2.3, 14.3.2 | ✓ | |
| F8 no 500, any method | A 16.5.1, 16.5.4, 4.1.4; RFC 9110 §9.1, §15.5.6 | ✓ | RFC: unknown method → **501**; 405 carries `Allow` |
| F9 one result (race, resubmit) | A 2.3.3, 2.3.4, 15.4.2; Idempotency-Key-07 | ✓ | backed by the standards, **not by our data**: races passed in every build (yield §E). "Any/auto-assign" is salon wording |
| O1 first run | — | — | |
| O2 config validated at start | A 13.2.3, 16.5.3 | ✓ | |
| O3 no PII in logs | A 16.2.5; Logging CS; GDPR 5(1)(c) | ✓ | |
| O3b mode 0600, WAL | CWE-732 | ◐ | the mode and the WAL are our stack call |
| O4 health check, O6 migrations | — | — | practice |
| O5 HTTPS behind proxy | A 3.3.1, 4.1.3, 15.3.4 | ✓ | |
| O7 operator guide | GDPR 5(2) (partial) | — | |
| T1 negative paths | A 6.5.1 (replay) | ✓ | |
| T2 forbidden transitions | A 2.3.1; WSTG-BUSL-06; HTSM | ✓ | |
| T3 restart/config/concurrency | Hendrickson Interrupt, Multi-User | ✓ | |
| T4 real-browser test | — | — | our harness |
| Probe 0 completeness | ToB spec-to-code-compliance (method) | ◐ | |
| Probe 1 −1/exact/+1 in unit and zone | Hendrickson Boundaries; W3C tz | ✓ | |
| Probe 2 "same rules as X" | WSTG-BUSL-06 | ✓ | |
| Probe 3 methods, malformed, CSRF, double submit | RFC 9110 §9.2.1; A 3.5.3, 3.5.1, 15.3.7; WSTG-CONF-06, SESS-05, ERRH-01, INPV-04 | ✓ | |
| Probe 4 rotating identity | A 2.4.1; API6; OAT-019/021/002 | ◐ | "phones", /64 |
| Probe 5 session replay | A 7.4.1, 7.3.x; WSTG-SESS-06/07 | ✓ | |
| Probe 6 production start on doc values | A 13.2.3, 6.3.2, 15.2.3; WSTG-ATHN-02 | ✓ | "placeholder contact" = S |
| Probe 7 erasure every copy | GDPR 17; A 14.2.7 | ✓ | WAL is stack-specific |
| Probe 8 normalisers | A 1.1.1 | ◐ | "leading zero" is phone-shaped |
| Probe 9 text vs stored state | HICCUPS Claims; GDPR 12–13 | ◐ | "call us", "staff can move" = S |
| Probe 10 no-store, file mode | A 14.3.2; WSTG-ATHN-06; CWE-732 | ✓ | |
| Floor: state change via GET/HEAD = blocker | RFC 9110 §9.2.1; A 3.5.3 (L1) | ✓ | |
| Floor: normaliser rewrites valid value ≥ high | GDPR 5(1)(d) (accuracy) | ✓ | |
| Floor: session survives ≥ medium | A 7.4.1 (L1) | ✓ | L1 suggests high (see C) |
| Skip: password denylist quality | conflicts with A 6.2.4 (L1, user passwords) | ◐ | keep the skip for **operator secrets**; user passwords → thorough |

## B. Gaps, ranked by expected breakage in LLM-built apps

| # | Missing check | Source | Basis | Goes to |
|---|---|---|---|---|
| 1 | **Object- and function-level authorization**: user A reads or changes B's record by id; a lower role reaches an operator route | A 8.2.1, 8.2.2, 8.3.1; API1, API5; WSTG-ATHZ-02/04 | (judgement): the benchmark had one operator role, so there is no data; it is the #1 API risk | default |
| 2 | **Client IP taken from a spoofable header**, which makes every per-source limit ineffective | A 4.1.3, 15.3.4 | partly data: proxy trust appears in self-review A5 R11, L1 R6, HL R6 | default (abuse probe) |
| 3 | **One-time codes and links**: single use, expiry, entropy, throttled lookup | A 6.4.1, 6.5.1, 6.5.4, 6.5.5; OAT-002 | data: unthrottled code lookups survived (yield §B) | default |
| 4 | Mass assignment / field-level write | A 15.3.3, 8.2.3; API3 | (judgement) | default (inside #1) |
| 5 | New session id at login, cookie flags | A 7.2.4, 3.3.1–3.3.4; WSTG-SESS-02/03 | (judgement) | default (sessions item) |
| 6 | Debug mode or stack traces in production | A 13.4.2, 16.5.1; WSTG-ERRH-02 | (judgement) | default (fail-closed item) |
| 7 | Partial failure leaves half a change | A 2.3.3 | (judgement) | default (one-result item) |
| 8 | Open redirect via `next=` | A 3.7.2 | (judgement) | thorough |
| 9 | Account / record enumeration | A 6.3.8; WSTG-IDNT-04 | (judgement) | thorough |
| 10 | Header baseline: CSP + frame-ancestors, nosniff, HSTS, Referrer-Policy | A 3.4.1–3.4.6; WSTG-CONF-07/12/14 | (judgement); no judge flagged it | thorough |
| 11 | Unbounded lists, expensive endpoints | API4; A 15.2.2 | (judgement) | thorough |
| 12 | CSV/formula injection in exports | A 1.2.10 | (judgement) | thorough |
| 13 | Known-vulnerable dependencies | A 15.2.1 | (judgement) | thorough |
| 14 | File upload type/size/path/execution | A 5.2.1–5.3.2; WSTG-BUSL-08/09 | conditional | thorough |
| 15 | User password rules (≥ 8, no composition rules, paste allowed, breached check) | A 6.2.1, 6.2.4, 6.2.5, 6.2.7 | (judgement) | thorough |
| 16 | WCAG 2.2 additions: redundant entry, accessible authentication, target size | SC 3.3.7, 3.3.8, 2.5.8 | (judgement) | default (a11y item) |

## C. Universal rewrite (caps: builder ≤ 25, probes ≤ 10)

The items are grouped by theme. Whether an item is in the default list was decided by the yield report first, then by
judgement. Each item is answered with `applies → A<n>` or `n.a. — why`.

### Builder checklist (25)

**R. The request**
1. Every stated rule is its own acceptance row in the request's words. "Same rules as X" becomes one row per check that X enforces. *A 2.1.3, 2.3.2; WSTG-BUSL-01*
2. Every number and time rule has rows at just inside, exact and just outside. Each row writes the comparison (`<`/`≤`) and works in the request's unit at full precision, in the time zone that governs the rule. *Hendrickson Boundaries; A 2.2.1*
3. A change to existing code: every rule the old path enforces is listed and has a row on the new path, and the existing tests pass unchanged. *WSTG-BUSL-06*
4. No restriction beyond the request. A protective limit is marked as the builder's call, throttles abuse, and never refuses use the rules allow. *A 6.1.1*
5. Legal duties for the jurisdiction and audience (privacy notice, consumer notices, accessibility) are each a row, or out of scope with the owner's agreement. *GDPR 13; 2011/83/EU Art. 6; 2019/882*

**D. Data and state**
6. Each entity has a defined way to be created, changed, retired and deleted. Past records keep the values they had at the time. *Hendrickson CRUD, Follow the Data*
7. A state table for each entity, with the forbidden transitions and the step order. Revisiting an old link shows the current state. *A 2.3.1; WSTG-BUSL-06; HTSM*
8. A limited resource or a resubmitted form produces exactly one result, also under concurrency. All of an operation commits or none of it does. *A 2.3.3, 2.3.4, 15.4.2; Idempotency-Key-07*
9. Identifiers (email, phone, username, codes) are canonicalised once. A valid value is stored unchanged in meaning, and two spellings of one identity collide. *A 1.1.1*
10. Times: instants are stored in UTC. A future local event is stored as wall time plus an IANA zone id. Rows cover DST gaps and overlaps wherever a rule crosses one. *W3C tz note; RFC 9557*

**V. Personal data**
11. Inventory: each personal field, its purpose and its retention. *GDPR 5(1)(c),(e), 30; A 14.1.1, 14.2.7*
12. Access and erasure reach every copy: related rows, files, logs, exports and backups. Backups are restored in a test, and the restore re-applies erasures. *GDPR 15, 17, 32(1)(c),(d)*
13. No personal data in URLs, logs or third-party calls. Pages with personal data send `Cache-Control: no-store`, and data files and backups are not world-readable. *A 14.2.1, 14.2.3, 14.3.2, 16.2.5; CWE-732*

**S. Security**
14. Fails closed: no default, example or placeholder secret, account or contact detail works in production, which refuses to start without them. Debug mode is off. *A 13.2.3, 6.3.2, 15.2.3, 13.4.2, 16.5.3*
15. Authorization is checked server-side on every object, field and function. Access is denied by default, and only allow-listed fields are writable. *A 8.2.1–8.2.3, 15.3.3; API1, API3, API5*
16. Sessions: a new id at login; server-side invalidation on logout, credential change and account disable; idle and absolute timeouts; `Secure`, `HttpOnly` and `SameSite` cookies. *A 7.2.4, 7.3.1, 7.3.2, 7.4.1–7.4.3, 3.3.1–3.3.4*
17. Safe methods (GET, HEAD, OPTIONS) never change state. An unsupported method gets 405 (or 501), never a 500. *RFC 9110 §9.2.1, §9.1; A 3.5.3, 4.1.4*
18. Every state-changing request, including public and login forms, carries an anti-forgery token, or passes a `Sec-Fetch-Site` check with an `Origin` fallback. `Origin: null` is never trusted. This is proved in a real browser under the deployed `Referrer-Policy`. *A 3.5.1; CSRF CS*
19. Abuse limits cover login, every public create, and every code or token lookup. They are keyed by source network and by target, and the client IP is read only from a trusted proxy. *A 2.4.1, 6.3.1, 4.1.3, 15.3.4; API6; OAT-002/019/021*
20. Input is validated server-side for type, length and range, with size limits answered by 413/414/431. Malformed input gets a 4xx with a generic message, never a 500. Free text accepts every script and rejects only control characters. *A 2.2.1, 2.2.2, 16.5.1, 16.5.4; Input Validation CS*
21. Output is encoded for its context, and queries are parameterised. *A 1.2.1, 1.2.4, 3.2.2*

**U. Pages**
22. Every page has an empty state, an error state and a "no longer valid" state (expired, used, cancelled). Back, refresh and bookmarks land on the right one. *Hendrickson Count, Navigation*
23. Form errors: validated on submit, with an error summary that takes focus, an inline message saying how to fix it, input kept, and `Error:` in the title. *GOV.UK validation; SC 3.3.1, 3.3.3, 4.1.3*
24. Keyboard, labels, name/role/value, visible focus, 24 px targets, reflow at 320 px, no re-entry, and login without a cognitive test. *SC 2.1.1, 1.3.1, 4.1.2, 2.4.7, 2.5.8, 1.4.10, 3.3.7, 3.3.8*
25. Every claim the interface, notices or privacy text makes (including query-string notices) is true of the stored state. *HICCUPS Claims; GDPR 12*

How a row is proven is pipeline mechanics, not another check. Each row's test asserts stored state, and a real-browser
test of the main forms is the `live_cmd`.

### Reviewer probes (10): yield order, with the judgement probe last

| # | Probe | How to run | Source |
|---|---|---|---|
| 0 | Completeness (reading, ≤ 2 turns) | Map each requirement, owner decision and builder call to a row and a check. A requirement with no row, or a row with no check, is a finding | traceability; ToB spec-to-code-compliance |
| 1 | Boundaries | Every number or time rule at −1 unit / exact / +1 unit, in the request's unit and its governing zone. Add a DST-crossing case where one exists | Hendrickson; W3C tz |
| 2 | Rule parity | For each "same as X" or reused flow, list X's checks from the code and run each one on the new path | WSTG-BUSL-06 |
| 3 | Abuse with rotating identity | N creates from one source with invented identifiers; one IPv6 /64; a spoofed `X-Forwarded-For`; one code guessed from many sources | A 2.4.1, 4.1.3; API6; OAT-019/021/002 |
| 4 | Method and byte sweep | Every route × GET/HEAD/OPTIONS/unknown verb; bad %-encoding, multibyte tokens, wrong content type, hundreds of parameters, an oversized body. Then each state-changing form: a cross-site POST without its token, and a double submit | RFC 9110 §9.2.1; A 3.5.1, 16.5.4, 15.3.7; WSTG-CONF-06, SESS-05 |
| 5 | Production start on documented values | Start with every value from the example config, README and operator docs. The app must refuse to start. Read the default, not the flag name | A 13.2.3, 6.3.2; ToB insecure-defaults |
| 6 | Session replay | Replay the cookie after logout, after a credential change, and after expiry with the clock advanced. Check the id changes at login | A 7.4.1, 7.2.4; WSTG-SESS-03/06/07 |
| 7 | Personal data copies | Erase, then search every copy: each field the privacy text names, files, logs, DB journal, backup → restore. Check `no-store` on private pages and the mode of data files | GDPR 17; A 14.2.7, 14.3.2 |
| 8 | Normalisers and claims | Valid foreign, mixed-case and leading-zero identifiers survive; two spellings collide (stop at the first bypass). Names in any script are accepted. Visible and query-driven notices match the stored state | A 1.1.1; GDPR 5(1)(d); HICCUPS Claims |
| 9 | Cross-user access (judgement) | As user A, fetch and change B's objects by id; send extra fields; call operator routes as a lower role and unauthenticated | A 8.2.2, 15.3.3; API1/3/5; WSTG-ATHZ-04 |

**Severity floors.** *blocker*: a state change through a safe method (RFC 9110 §9.2.1); access to or change of
another user's data (A 8.2.2, L1). *high*: an example or placeholder secret accepted in production (yield cat. 1: 6
real, 0 noise); a normaliser that rewrites a valid value (GDPR 5(1)(d); yield §A, G4); a session that survives logout or a credential
change (A 7.4.1 is L1; judges scored G3 security 2/5). *medium*: a session that survives expiry; any 500 from client
input; a public create or lookup with no limit at all; erasure that misses a copy (raise to high where the privacy text
promises erasure).

**Skip or spot-check once** (yield §E, 25 of the 26 noise findings): strength of operator secrets, invisible-Unicode
taxonomy, limiter-eviction theory, variants after the first bypass, README wording, cosmetic notice variants. Spot-check
races, basic XSS and basic CSRF once each.

### Appendix: thorough only

Open redirect (A 3.7.2) · enumeration (A 6.3.8) · header baseline (A 3.4.1–3.4.6) · unbounded lists and expensive
endpoints (API4) · CSV injection (A 1.2.10) · dependency audit (A 15.2.1) · file upload (A 5.2–5.4) · user password
rules (A 6.2.1/4/5/7) · logout visible on every page (A 7.4.4) · an operator guide (setup, routine changes, data
requests), a health check and migrations (practice) · HTSM
SFDIPOT pass and Hendrickson Interrupt/Starve/Multi-User/Sequences on the main flow.

## D. GitHub skills

| Repo / file | Borrow | Licence |
|---|---|---|
| [anthropics/skills `skills/webapp-testing/SKILL.md`](https://github.com/anthropics/skills/tree/main/skills/webapp-testing) | `with_server.py` server lifecycle; recon-then-act; wait for `networkidle` before reading the DOM. Fits our `live_cmd` | Apache-2.0 (skill-level `LICENSE.txt`; the repo root has none) |
| [trailofbits/skills `plugins/insecure-defaults`](https://github.com/trailofbits/skills/tree/main/plugins/insecure-defaults) | "Read the default, not the flag name"; fallback secrets, fail-open switches, debug leakage → probe 5 | CC-BY-SA-4.0: **ideas only**; copying text makes ours share-alike |
| trailofbits `plugins/fp-check` | the rationalisation table ("pattern recognition is not analysis"); restate the claim before judging → finding bar | CC-BY-SA-4.0, ideas only |
| trailofbits `plugins/property-based-testing` (normaliser-idempotence eval) | normaliser round-trip/idempotence as a property test → item 9, probe 8 | CC-BY-SA-4.0, ideas only |
| trailofbits `plugins/spec-to-code-compliance` | one row per requirement; every gap is either a bug or a doc fix → probe 0 | CC-BY-SA-4.0, ideas only |
| [cosai-oasis/project-codeguard `sources/rules/owasp/codeguard-0-authorization-testing-automation.md`](https://github.com/cosai-oasis/project-codeguard) | role × route → expected status matrix → probe 9 | CC-BY-4.0 (`LICENSE.md`) |
| [petrkindlmann/qa-skills `skills/exploratory-testing`](https://github.com/petrkindlmann/qa-skills) | HICCUPS oracles (Claims, History, Product, Standards) as names for probes 2 and 8 | MIT |
| [obra/superpowers](https://github.com/obra/superpowers) `verification-before-completion`, `test-driven-development/writing-good-tests.md` | already used: evidence before claims; tests that assert behaviour, not mocks | MIT |
| [lackeyjb/playwright-skill](https://github.com/lackeyjb/playwright-skill) | a general Playwright driver, if `webapp-testing` is too thin | MIT |

**Do not borrow.** [anthropics/claude-code-security-review](https://github.com/anthropics/claude-code-security-review)
(MIT) `claudecode/prompts.py` excludes "DoS" and "rate limiting… services do not need to implement rate limiting".
That is the class that survived in 6 of our runs (yield §B). Its >0.8 confidence filter is fine. Also skip the SBTM
45–90 minute session ritual from qa-skills (a human cadence, and our turn budget already bounds a session) and
"Never and Always" (it is not on the Hendrickson sheet).
