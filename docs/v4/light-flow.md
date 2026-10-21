# Light flow — build instructions (domain-agnostic)

Before writing code, do steps 1–2 and write the result to `CONSTRAINTS.md`. Then build (step 3).

## 1. Jurisdiction and domain obligations (one bounded research pass)
Using the confirmed location, the kind of data handled and the kind of business, find the obligations and failure modes
that would change THIS build: privacy-notice contents, data-subject rights (access, erasure), retention, price/tax
display, consumer-protection notices (complaints, dispute resolution), accessibility expectations, and known storage or
deployment traps for the chosen stack (deleted data left on disk, unsafe backups, timezone/DST, reverse proxies).
Use web search; prefer primary sources. Write each as: requirement → source → acceptance check. Mark what needs a
fact from the owner. Keep agreed out-of-scope items out.

## 2. Checklists — answer each item for this product (applies / not applicable + why)
**Data lifecycle (the operator, not a developer):** for every entity (e.g. services, people, prices, schedules,
records), how is it created, changed, retired without losing history, and deleted? What is configurable without a
code change (locale: timezone, currency, contact details; business data)? What does a backup/restore look like, and is
it tested? Can the operator act on a person's request to see or erase their data?
**Every page and state:** for each page — the empty state, the error state for each user mistake (with a clear
message), the "no longer valid" states (cancelled, expired, already used), revisiting a link later, keyboard and
screen-reader labels, small screens. Show the business's contact details where a customer needs them.
**Every form and endpoint:** authentication fails closed when unconfigured (no default or placeholder secret works);
sessions expire and are revoked on logout and on credential change; CSRF on every state-changing form; output
escaping; input and body-size limits with correct status codes; rate limits on login, submissions and lookups of
codes/tokens; no personal data in pages a third party could see, cache or index; malformed input never yields a 500.
**Operations:** first run, configuration validation at startup (refuse to start in production with missing or
placeholder values), logs without personal data, health check, deployment behind HTTPS/proxy, upgrade path.

## 3. Build
Turn the brief, the owner's answers and `CONSTRAINTS.md` into a short acceptance table. Implement each row and show its
observable result with a test: negative paths and state transitions (replay, concurrency, restart, missing config),
and verify persistent state, not only status codes. Deliver an operator guide (setup, configuration, routine changes,
retirement, backup/restore, data requests). Report any row left unmet or untested.
