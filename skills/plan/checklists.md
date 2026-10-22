# Checklists

The plan answers **every item** below for this product: `applies → A<n>`, naming the acceptance row that checks it, or
`n.a. — <why>`. An item that applies and has no row is a gap. The reviewer receives this file with the plan's answers.

Universal for web applications, capped at 25 so that each one gets a real answer. Every item names its source:
`A` = OWASP ASVS 5.0, `WSTG` = OWASP Web Security Testing Guide, `CS` = OWASP Cheat Sheet, `SC` = WCAG 2.2 success
criterion. Evidence and the full mapping: `docs/compound-v/preflight/2026-10-22-v4-webapp-qa-practice.md`.

## R. The request
- **R1** Every stated rule is its own acceptance row, in the request's words. "Same rules as X" becomes one row per check
  X enforces. When two stated rules conflict, or one is ambiguous, the owner decides (one question); a call only fills
  what the request leaves silent. *A 2.1.3, 2.3.2; WSTG-BUSL-01*
- **R2** Every number and time rule has rows at just inside, exact and just outside, with the comparison written (`<` or
  `≤`), in the rule's own unit at full precision and in the time zone that governs it. Read the phrase: "up to N before"
  allows the action while at least N remains (exactly N is allowed); "at least N" is ≥; "within N" is ≤; "more/less than"
  are strict. *Hendrickson Boundaries; A 2.2.1*
- **R3** Extend, don't fork: each rule is enforced in one place, and new behaviour goes through it (the existing validation
  and write path) instead of copying it. Every existing operation on what the change touches (edit, delete, retire,
  erase, export, list, migrate, background jobs) has a row for the new data, state or relation, and the existing tests
  pass unchanged. *WSTG-BUSL-06; DRY*
- **R4** No restriction beyond the request. A protective limit is marked as the builder's call, throttles abuse, and never
  refuses use the stated rules allow. *A 6.1.1*
- **R5** The jurisdiction's duties for this audience (privacy notice, consumer notices, accessibility) are each a row, or
  out of scope with the owner's agreement. Each research row (`DR#`) is a row. *GDPR 13; 2011/83/EU Art. 6; 2019/882*

## D. Data and state
- **D1** Each entity can be created, changed, retired and deleted. Past records keep the values they had at the time.
  Business data the operator changes in normal operation (catalogue, prices, schedules, contact details, settings) is
  editable by an authorised operator without a code change or restart. *Hendrickson CRUD, Follow the Data*
- **D2** A state table per entity, with the forbidden transitions and the step order. Revisiting an old link shows the
  current state. *A 2.3.1; WSTG-BUSL-06*
- **D3** A limited resource, or the same form submitted twice (double click, back and resubmit, an "any" / auto-assign
  choice), yields exactly one result, also under concurrency; an operation commits whole or not at all. Use a one-time
  token per rendered form. *A 2.3.3, 2.3.4, 15.4.2; Idempotency-Key draft*
- **D4** Identifiers (email, phone, username, codes) are canonicalised once: a valid value is stored unchanged in meaning,
  and two spellings of one identity collide. *A 1.1.1*
- **D5** Times: instants in UTC; a future local event as wall time plus an IANA zone id; rows for DST gaps and overlaps
  wherever a rule crosses one. *W3C time-zone note; RFC 9557*

## V. Personal data
- **V1** An inventory: each personal field, its purpose and its retention. *GDPR 5(1)(c),(e), 30; A 14.1.1, 14.2.7*
- **V2** Access and erasure reach every copy: related rows, files, logs, exports and backups. A backup is restored in a
  test, and the restore re-applies erasures. *GDPR 15, 17, 32(1)(c),(d)*
- **V3** No personal data in URLs, logs or third-party calls; pages with personal data send `Cache-Control: no-store`;
  data files and backups are not world-readable. *A 14.2.1, 14.2.3, 14.3.2, 16.2.5; CWE-732*

## S. Security (for every new route or step too: it carries the same protections as its nearest existing sibling)
- **S1** Fails closed: no default, example or placeholder secret, account or contact detail works in production, which
  refuses to start without real ones. Debug off. *A 13.2.3, 6.3.2, 15.2.3, 13.4.2, 16.5.3*
- **S2** Authorization is checked server-side on every object, field and function: deny by default; one user can never read
  or change another's records by id; only allow-listed fields are writable. *A 8.2.1–8.2.3, 15.3.3; API1, API3, API5*
- **S3** Sessions: a new id at login; server-side invalidation on logout, credential change and account disable; idle and
  absolute timeouts; `Secure`, `HttpOnly`, `SameSite` cookies. *A 7.2.4, 7.3.1, 7.3.2, 7.4.1–7.4.3, 3.3.1–3.3.4*
- **S4** Safe methods (GET, HEAD, OPTIONS) never change state. An unsupported method gets 405 (or 501), never a 500.
  *RFC 9110 §9.2.1, §9.1; A 3.5.3, 4.1.4*
- **S5** Every state-changing request, public and login forms included, carries an anti-forgery token, or passes a
  `Sec-Fetch-Site` check with an `Origin` fallback; `Origin: null` is never trusted. Proved in a real browser under the
  deployed `Referrer-Policy`. *A 3.5.1; CSRF CS*
- **S6** Abuse limits on login, every public create and every code or token lookup, keyed by source network (an IPv6 /64,
  not one address) and by target; the client IP is read only from a trusted proxy. *A 2.4.1, 6.3.1, 4.1.3, 15.3.4; API6*
- **S7** Input validated server-side for type, length and range, with size limits answered 413/414/431; malformed input
  gets a 4xx with a generic message, never a 500; free text accepts every script (joiners and combining marks included)
  and rejects only control characters. *A 2.2.1, 2.2.2, 16.5.1, 16.5.4; Input Validation CS*
- **S8** Output encoded for its context; queries parameterised. *A 1.2.1, 1.2.4, 3.2.2*

## U. Pages
- **U1** Every page has an empty state, an error state and a "no longer valid" state (expired, used, cancelled); back,
  refresh and bookmarks land on the right one. *Hendrickson Count, Navigation*
- **U2** Form errors: validated on submit, an error summary that takes focus, an inline message saying how to fix it,
  input kept, `Error:` in the title. *GOV.UK validation; SC 3.3.1, 3.3.3, 4.1.3*
- **U3** Keyboard, labels, name/role/value, visible focus, 24 px targets, reflow at 320 px, no re-entry, login without a
  cognitive test. *SC 2.1.1, 1.3.1, 4.1.2, 2.4.7, 2.5.8, 1.4.10, 3.3.7, 3.3.8*
- **U4** What the interface says is true: notices, privacy text and query-string messages match the stored state, and a
  confirmation step commits exactly what the user saw and approved — if anything changed since, it shows the difference
  instead of committing something else. Anything can change between steps (a referenced record deleted, a slot taken,
  a price changed): the commit step re-validates everything inside its transaction, before any write, and answers with a
  4xx and a fresh preview, never a 500. From every step, the failure of its precondition included, the user can reach
  the alternatives. *HICCUPS Claims; GDPR 12; Hendrickson Interrupt*

How a row is proven is the pipeline's job, not another item: each row's test asserts stored state, and a real-browser
test of the main forms is the plan's `live_cmd`.

## Thorough only (load when the depth is `thorough`)
Open redirect (A 3.7.2) · account and code enumeration (A 6.3.8) · security header baseline (A 3.4.1–3.4.6) · unbounded
lists and expensive endpoints (API4) · CSV/formula injection (A 1.2.10) · dependency audit (A 15.2.1) · file upload
(A 5.2–5.4) · user password rules (A 6.2.x) · logout visible on every page (A 7.4.4) · operator guide, health check,
migrations (practice) · an SFDIPOT pass and Hendrickson Interrupt / Starve / Multi-User / Sequences on the main flow.
