# Recording Sumit's salon run: the kit

How to repeat our run on camera so the numbers can be compared. Our own run and its results: `sumit-run.md`.

## 0. Before recording

- An empty folder with `git init` and a first commit (`git commit --allow-empty -m init`): Compound V pins every run
  to a base commit, and `/compound-v:init` stops without one. Nothing else in it. One terminal; close every other Claude session on the account
  (quota is account-wide, so anything else running moves it too).
- Write down the versions: `claude --version`, the Compound V version (`claude plugin list`), the model and effort
  (`/model`, `/status`). Ours: Claude Code 2.1.306, compound-v 4.0.0, `claude-opus-5-5`, effort default.
- Optional: install the Codex CLI if the reviewer should be a second model. Without Codex, Compound V's own Claude
  reviewer runs instead (that is what we ran).
- Note the clock time and both quota windows (`/status`: 5-hour and weekly percent).
- On Pro the run may hit the 5-hour limit (an estimate, `sumit-run.md`, "On Pro"). If it pauses, leave the session
  open, continue after the reset, and note the pause on screen so the time is read correctly.

## 1. Commands, in order (typed on camera)

```bash
claude plugin marketplace add procoders/superpowers-v
claude plugin install compound-v@procoders
claude
```

Inside Claude Code:

1. `/compound-v:init`, and approve the diffs it shows. To match our run, make `.claude/compound-v.json` read
   `{"version": 4, "stance": "standard", "default_tier": "full", "reviewer": "claude", "test_cmd": "npm test", "budget_usd": 7}`
   (choose these values when init asks, or edit the file and commit it). On an empty repo init finds no test command;
   `npm test` is what the build sets up.
2. Paste the job post exactly as written (title and body), nothing else.
3. Answer each brainstorm question **only** from the client's answer sheet; if the sheet does not cover it, answer
   "your call". One answer per message, the way the client would. Our run took 11 owner messages, approvals included.
4. Approve the spec when asked ("yes, go ahead").
5. Hands off: the build runs on its own. Approve permission prompts only.
6. Stop the clock at the first `verified` report (ours: 55 min), and note it again if the agent carries on with
   follow-up runs for review findings (ours ended at 84 min).

We drove the run headless (`claude -p`, one turn per answer) so that every message is logged. We did not run
`/compound-v:init`: the bench committed the config above and `.claude/settings.json` (`{"worktree": {"baseRef":
"head"}}`, which init also writes) before turn 1, and turn 1 was the job post. From step 2 on, the steps are the same.

## 2. Video beats

| # | On screen | What the viewer learns |
|---|---|---|
| 1 | The job post pasted | Same brief as a real client job |
| 2 | Brainstorm questions and the answers | It asks what a senior developer would ask before writing code |
| 3 | The spec it wrote | Requirements on paper before code |
| 4 | Build (time-lapse) | One builder: research, plan, code, tests |
| 5 | Verify: tests, real-browser check, scope, review, and the band above the prompt | "Done" is a check the CLI signs, not a claim |
| 6 | The app on a phone: book, a double-booking attempt, the desk view, the export with a Bangla name | It works for the client |
| 7 | The three security checks, v4 vs plain Claude Code | The difference a client never sees but pays for later |
| 8 | Numbers card: time, cost, quota | What it costs to get there |

## 3. The three security checks (run against both builds)

Start each build in production (`npm run build`, then `npm start`) with its own example config filled in.

1. **Session after logout.** Sign in as admin, copy the session cookie, sign out, replay the cookie on admin pages
   from another browser or `curl -b '<name>=<value>' http://localhost:3000/admin`. Expected: refused.
2. **Repeated fake bookings.** 25–50 bookings from one source with invented names and numbers in a loop. Expected:
   limited after a few; a customer from another network still books.
3. **A bad cookie.** A garbled, tampered, empty and very long admin cookie on admin pages and on an admin form.
   Expected: refused, no 500.

Our results for the v4 build are in `sumit-run.md`.

## 4. What gets measured, and how

| Figure | Source | Note |
|---|---|---|
| Time | Clock from the first prompt to `verified` | Includes the time spent answering questions |
| Cost (USD) | Claude Code's `/cost` at the end | API-price estimate, not an invoice |
| Tokens | `/cost` or the session transcript | Cache read, cache write, input, output |
| Quota | `/status` before and after | Plan-specific; say which plan |
| Pro share (estimate) | Cost ÷ the measured Pro allowance | Method and source in `sumit-run.md` |

## 5. What we send back

- The app repo and the full session transcript, including the brainstorm.
- `sumit-run.md`: versions, times, cost, tokens, our Max quota and the Pro estimate with its source.
- The blind scoring report (`salon-report.md`, `benchmark-summary.md`) and whether its numbers may be quoted.
