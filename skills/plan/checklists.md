# Checklists

The plan answers **every item** for this product: `applies → A<n>`, naming the acceptance row that checks it, or `n.a. — <why>`. An item that applies and has no row is a gap. The reviewer receives this file and the plan's answers, and judges against both.

These are the checklists that won the salon benchmark: plain Claude Code plus these four lists and one review/fix pass beat the full v3 pipeline on every blind judgement (`docs/v4/salon-report.md`). Adapted from `docs/v4/light-flow.md`.

## J. Jurisdiction and domain (from the domain pre-flight)
- J1 Every row of the domain pre-flight's requirement table is an acceptance row, or is marked out of scope with the spec's agreement.
- J2 Privacy notice contents, access and erasure rights, and retention, as the jurisdiction requires.
- J3 Price and tax display, consumer-protection notices (complaints, dispute resolution) where they apply.
- J4 Accessibility expectations for the jurisdiction and audience.
- J5 Stack and deployment traps: deleted data left on disk, in backups or in logs; timezone and DST; reverse proxy and HTTPS headers.
- J6 Each owner fact the pre-flight left open: the assumption the plan makes, written down.

## D. Data lifecycle: the operator, not a developer
- D1 For every entity: how it is created, changed, **retired without losing history**, and deleted. Past records keep the values they had (a price change must not rewrite past confirmations).
- D2 What the operator configures without a code change: locale (timezone, currency, language), contact details, business data (hours, staff, services).
- D3 A person's request to see or erase their data: the operator can act on it, and erasure reaches every copy (related rows, notes, files, backups, logs) or the spec says what is kept and why.
- D4 Backup and restore: what it is, how it is run, and a tested restore.
- D5 Persisted state survives a restart. Tests check the stored state, not only status codes.

## P. Every page and state
- P1 Each page's empty state.
- P2 An error state for each user mistake, with a message saying what to do.
- P3 "No longer valid" states: cancelled, expired, already used, moved. Revisiting an old link later shows the right one.
- P4 Keyboard use and screen-reader labels on every control; small screens.
- P5 The business's contact details wherever a customer needs them (confirmations, errors, the privacy page).

## F. Every form and endpoint
- F1 Authentication **fails closed** when unconfigured: no default or placeholder secret works, in any environment.
- F2 Sessions expire, and are revoked on logout and on credential change, server-side.
- F3 CSRF protection on every state-changing form, and **tested in a real browser**. An Origin check that rejects `null` breaks every form under `Referrer-Policy: no-referrer`, and only a real browser shows it.
- F4 Output escaping everywhere user input is shown.
- F5 Input and body-size limits, with the correct status codes.
- F6 Rate limits on login, on public submissions, and on lookups of codes or tokens.
- F7 No personal data in pages, URLs or responses that a third party could see, cache or index.
- F8 Malformed input never yields a 500.
- F9 Concurrency: two requests for the same last slot, or a double submit, leave exactly one result.

## O. Operations
- O1 First run: setup steps, and a clear error when something is missing.
- O2 Configuration is validated at startup; production refuses to start with missing or placeholder values.
- O3 Logs carry no personal data.
- O4 A health check.
- O5 Deployment behind HTTPS and a proxy (trusted proxy headers, secure cookies).
- O6 Upgrade path: migrations, and keeping data across versions.
- O7 An operator guide: setup, configuration, routine changes, retirement, backup/restore, data requests.

## T. Tests that prove the rows
- T1 Negative paths for every form and endpoint (wrong, missing, oversized, replayed, expired input).
- T2 State transitions, including the forbidden ones (a cancelled booking cannot be confirmed).
- T3 Restart, missing config and concurrency, wherever a row depends on them.
- T4 Web projects: a real-browser test (Playwright Test) submits each main form against the running app and checks the resulting state. This test is the plan's `live_cmd`.
