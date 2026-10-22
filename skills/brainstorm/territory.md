# Territory

This is ground to cover, not a script. Never read these bullets out. Ask about the area that would change the build most and that the conversation has not reached yet, in the user's own words, one question at a time. An area is **covered** when the user has answered it, when you have made a call and marked it as yours, or when it does not apply and you can say why.

In the salon benchmark, the answers to these areas nearly doubled the capabilities a build considered, and the plain runs never asked. They are the cheapest depth there is.

## 1. The product and its users
- Who uses it, in what moment, and what makes it worth building now.
- What success looks like to the owner, and what would make it a failure even if it works (anti-goals).
- What exists today: current tools, paper, spreadsheets, a site to replace, prior art they liked or hated.
- Questions that work: "Walk me through the last time a customer did this." "If it could do only one thing well, which one?"

## 2. Data lifecycle: the operator, not a developer
For every entity (services, people, prices, schedules, bookings, records):
- how it is **created**, **changed**, **retired without losing history** (a retired price must not rewrite past confirmations), and **deleted**;
- what the operator changes without a developer: hours, staff, prices, contact details, timezone, currency, texts;
- what a person can ask for (see their data, erase it) and how the operator acts on it;
- backup and restore: who does it, how often, and whether a restore has ever been tried.
- A question that works: "When a stylist leaves, what should happen to their future bookings and their past ones?"

## 3. Jurisdiction, data and deployment
- Where the business and its users are (this decides privacy, consumer and tax rules), and which languages and currency.
- What data it handles: names, phones and emails; payments; health; children's data.
- Where it runs: a laptop, a small VPS, a platform, behind a proxy or HTTPS; who operates it.
- A question that works: "Which country is the business in, and where are most of its customers?"

## 4. Security and every form
- Who logs in, with what, and what each role may do; what happens when a secret is missing or still a placeholder.
- Every form and public link: who can submit it, how often, and what abuse looks like (fake bookings, code guessing, scraping).
- What a third party must never see: personal data in URLs, pages, caches and logs.
- A question that works: "Who besides you should be able to change a booking?"

## 5. Operations
- First run and setup; configuration the owner fills in; refusing to start with missing or placeholder values in production.
- Logs without personal data, a health check, upgrades, and who gets told when something breaks.
- A question that works: "Who will install and update this, and how comfortable are they with a terminal?"

## 6. Edge cases: their own topic
Ask about them on purpose. They will not come up by themselves.
- Time: timezones and DST, cutoffs ("2 hours before" measured how), same-day changes, holidays, closures.
- State: cancelled, expired, already used, moved, no-show; revisiting an old link; a double submit; two people booking the same slot.
- Limits: per person, per day, per phone; what happens at the limit.
- Mistakes: a wrong phone, a typo in a name, the owner deleting something by accident.
- A question that works: "What should happen when two people try to book the last slot at the same moment?"

## 7. How it gets made
- Which choices the owner wants to make (stack, hosting, libraries) and which they leave to you. When there is existing code, build on what it already uses.
- Say your defaults out loud in plain words. A default they never heard is one they could not reject. Mark each in the spec as your call.

## Done when
Every area above is covered or marked n.a., and you could hand the spec to a builder who cannot ask the owner anything. Then write the spec.
