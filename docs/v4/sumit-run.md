# Sumit's salon brief on Compound V 4.0.0 — clean headless run (2026-10-27)

Sumit's own job post and client answers (Dhaka salon, 4 stylists, Next.js + TypeScript + Tailwind + SQLite/Prisma), run
once through Compound V 4.0.0 in an isolated `claude -p` session with nothing else installed. A separate agent played
the owner and answered only from Sumit's answer sheet ("your call" for anything the sheet does not cover). Logs, the
answers we gave and the transcripts are kept; paths at the end.

## Setup

| | |
|---|---|
| Claude Code | 2.1.306, headless `claude -p --resume` one turn per owner message, `--permission-mode acceptEdits`, sandbox on, no `--dangerously-skip-permissions` |
| Plugin | compound-v 4.0.0 at tag `v4.0.0` (62cd10f), loaded with `--plugin-dir`, `--setting-sources project,local`, `--strict-mcp-config` (no other plugins, no MCP) |
| Model | `claude-opus-5-5`, effort default |
| Project config | `default_tier: full`, `reviewer: claude` (no Codex), `test_cmd: npm test`, `budget_usd: 7` |
| Account | Max plan (quota read with the desktop app's usage tool) |

A first attempt was stopped and discarded: the bench's permission rules denied the builder reads of the plugin's own
checklists (the same bench mistake noted in `benchmark-summary.md`). The rule was fixed and the run started again
from an empty repo; the builder's transcript then shows the checklists read 7 times and no denials.

## What happened

| Time (UTC) | Step |
|---|---|
| 16:19:45 | Job post pasted (turn 1) |
| 16:19–16:24 | Brainstorm: 11 owner messages: 4 facts from the sheet, "Standard." for the depth, 4 × "your call", 2 × "yes, go ahead" (the last one approves the spec) |
| 16:22:51 | Run 1 started (full tier) |
| 17:15:10 | **Run 1 verified**: tests, real-browser test, scope, independent review all pass |
| 17:15–17:38 | Run 2 took on run 1's review findings (five medium, one low); its own review found one medium left; verified. Runs 1 and 2 committed together as `aeb7dc8` (17:39) |
| 17:39–17:43 | Run 3: fixed run 2's one medium finding (500 on a malformed server-action body); verified, committed as `fa92a2c` |
| 17:43:57 | Done, nothing asked of the owner after the spec |

The build was one long turn: the agent chose on its own to spend runs 2 and 3 on medium review findings. Run 3's
review left two medium findings open (hand-crafted garbled server-action bodies still get a 500); the agent stopped
there because fixing them means working around Next.js internals. Final state: 78/78 tests, 18/18 browser tests on a
phone-sized screen.

## Numbers

| Figure | Value | Source |
|---|---|---|
| Time to the first verified app | **55 min** | run 1 record vs the first prompt |
| Time to the end | **84 min** | `wall.txt` |
| Cost, whole session | **$32.14** | Claude Code's `total_cost_usd` (API-price estimate, not an invoice) |
| Cost to the first verified app | **≈ $19** (estimate) | 60% of the session's tokens, weighted by Anthropic's published price ratios (cache write 1.25×, cache read 0.1×, output 5× input), are timestamped before 17:15:10 |
| Tokens | 57.1M cache read, 2.26M cache write, 786 input, 447K output (95K of it thinking), Opus 5.5 | Claude Code's `modelUsage` in the last turn's result; plus $0.06 of Haiku that Claude Code itself uses for web search |
| Max quota | 5-hour window 4% → 9%, weekly 3% → 5% | usage tool at 16:19 and ≈17:45 (after the run ended); includes the supervising session, so an upper bound |

Our earlier v4 salon runs on our own brief cost $10.6–11.1 and took 33–35 min (`benchmark-summary.md`). This brief
made a bigger product (Dhaka privacy rules, retention, backups and restore, erasure log) and the agent added two
follow-up runs; both push the cost up.

**On Pro (estimate, not a measurement).** Anthropic publishes no token or dollar figures for Pro limits. The best
public measurement we found (wokey.ai, week of 2026-10-19, 103 Pro accounts, priced at API rates) puts one Pro
5-hour window at about $11 and a Pro week at about $157 ($142–170). By that yardstick the whole session is about
**three Pro 5-hour windows and about 20% of a Pro week**; the first verified app alone is about 1.7 windows. Our Max
quota moved less than the dollar figure suggests, which hints that the limits weigh cache reads below API price, so
treat the Pro figure as an upper estimate. On Pro the run may hit the 5-hour limit (an estimate; nothing was measured on Pro).

## Sumit's three security checks (production build, `next start`, run by us)

| Check | Result |
|---|---|
| Session after logout | **Refused.** The cookie copied before sign-out, replayed from another address: `/admin` and `/admin/settings` redirect to the login page, `/admin/export` answers 401 |
| Repeated fake bookings, one source | **Limited.** 10 bookings per network per 10 minutes, then "We received many booking attempts from your connection". A spoofed earlier `X-Forwarded-For` entry does not give a new identity; a customer from another network books normally. Limits are in memory, so a restart resets them; one source can still take about 60 slots an hour (a stylist's whole day in about 20 minutes) |
| A bad cookie | **Refused, no 500.** Garbage, empty, 4 KB, tampered, reversed and non-ASCII cookies on five admin routes, and a tampered cookie on an admin form submit: all sent to login (export 401), no 5xx |

Not yet done: the same three checks against a plain Claude Code build of this brief.

## Defects we found that the run did not

- **`npm run db:seed` ignores `.env`.** `scripts/migrate.ts` loads `.env`, `prisma/seed.ts` does not, so on a fresh
  server the documented install (`DEPLOY.md` §1) fails at the seed step with "Cannot open database because the
  directory does not exist". Workaround: export the `.env` values first.
- **Compound V's budget did not see the spending.** The run record shows $0.63 for run 1 against the $7 budget and
  nothing for runs 2 and 3. Cause: the CLI reads cost from the `cost-state` entry Claude Code writes at the end of a
  turn, and the whole build was one turn. Fix in progress in the plugin.

## Where everything is

- App repo: `~/Dev/cv-v4-run-sumit` (spec and plan under `docs/compound-v/`, three run records with their reviews).
- Owner messages, per-turn output and wall times: `~/Dev/cv-salon-e2e-kit/logs/cv-v4-run-sumit/`.
- Full transcripts (main session plus 7 subagents): `~/.claude/projects/-Users-oleg-Dev-cv-v4-run-sumit/749e0b35-3a12-434e-b531-db2a4744182d*`.
- The answer sheet and job post as given: `~/Dev/cv-salon-e2e-kit/answers-sumit.md`, `job-post-sumit.txt`.
