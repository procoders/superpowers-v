# Compound V

**Give Claude Code a senior engineer's habits: it interviews the client first and proves the work before it says done.**

![Compound V](assets/compound-v-squad.png)

## The loop that gets you blamed

You prompt, Claude builds, you click through the happy path, it works, you ship. A week later the client calls:
the session didn't end on logout, someone booked 24 fake appointments, a mangled cookie crashes the page, a customer's
name is rejected, and staff still can't change a price without you. The client doesn't blame Claude. They blame you.

We measured that loop. Plain Claude Code got the full requirements, and a developer tested it the way a busy
developer does and sent fixes until they were happy to hand over ($2.27 of Claude, two rounds). **They found one
bug. Blind judges then found every defect above in the same build.** Your own happy-path check can't see them,
because you check what you built, not what you forgot.

## Compound V works both ends, and the middle

- **Before the code: the questions nobody asked.** The brainstorm interviews you (or your client) one question at a
  time: who runs it day to day, what the operator changes without a developer, the country's privacy rules, every
  form and who could abuse it, the edge cases on purpose. Given just these answers, even a plain build nearly doubled
  the edge cases it handled (37 → 63).
- **In the middle: it picks up a live project.** On existing code the builder reads before it writes. It maps every
  rule, every operation and every guard the change touches, so a new feature goes through the existing validation
  instead of beside it. Added to a running app, recurring bookings scored 85 and 93. Plain Claude Code's attempt
  made an existing staff delete crash, and was capped in 5 of 6 judgements.
- **At handover: acceptance you can't fake.** The project's tests, a real browser submitting real forms, an
  independent reviewer attacking an isolated copy (logout, other users' data, abuse from many networks, production
  start with example secrets), and a look at its own screenshots against the project's `DESIGN.md`. Each check is a
  signed receipt bound to the exact code. No green receipts, no "done".

## What reaches the client

One salon-booking brief, one model (Claude Opus), one machine. On the left, the realistic loop: plain Claude Code got
the full requirements, and a developer checked it and sent fixes until they would hand it over. Every build was judged
**blind**: Codex ran the code and attacked it, and a PM-plus-designer panel reviewed the screens.

| | Claude Code + you iterating | **Compound V** |
|---|---|---|
| Security holes the client would hit | session survives logout · 24 fake bookings from one source · a mangled cookie crashes the page | **none critical:** sessions revoked, CSRF, throttling, no personal data in confirmations |
| Staff can change services and prices without you | no | **yes** |
| Edge cases and user mistakes handled¹ | 39 | **73 (~2×)** |
| Product judges | send back: the salon can't manage its own services and prices | *"The only version that looks like a real boutique salon brand"* |
| Product quality, blind run-based score (/100) | 61 | **80–84** |
| UX, blind PM + designer score (/100)² | ~62: a wall of 27 date buttons on the phone, errors far from their fields | **83:** guided booking, errors beside each field, the salon's brand and contacts on every page |
| Claude spend · machine time | **$2.27 · ~7 min** | ~$11 · ~35 min |
| Your manual work | two rounds of testing it yourself and writing fix prompts | **zero rounds:** answer the questions, approve the spec, then fully hands-off |

**What the score means.** The judges check every requirement by running it, then try to break it. ~60 = the happy path
works and the holes above are open: the client finds them in week one. 80+ = a demanding reviewer would hand it over.
One critical defect caps any build at 50. The scale isn't linear: the last 20 points are exactly the bugs that bounce
a delivery.

<sub>¹ Capability census, same blind set. ² UX: Codex panel; a Gemini panel gave 63–74 vs 100. A single plain prompt
with no iteration: $1.31, 3.5 min, 60 · 50. Judges move ±10 points on the same build, so read ranges, not single runs.
Full tables and method: [benchmark-summary.md](docs/v4/benchmark-summary.md).</sub>

It isn't one lucky app. On a team-expenses app (TypeScript, Fastify, Drizzle, Zod) plain Claude Code scored 52 (59 with
the owner's answers) and Compound V 80, all uncapped, with ~82 edge cases handled against 44–52.

**Is ~$10 worth it?** That's less than ten minutes of a developer's time, and far less than one bounced delivery.

## Is it for you?

**Yes**, if you build things other people will use: client work, internal tools, SaaS features, anything with
logins, personal data, money or a real operator behind it. Those are the places where one missed case costs more
than the $10.

**No**, for prototypes, spikes, throwaway scripts or a tight edit-run loop. There, plain Claude Code is the right
tool, and Compound V gets out of the way: typos, copy and config changes go straight to a light check.

## How it works

```
you ─▶ brainstorm ─▶ build ─▶ verify ─▶ done (only if every receipt is green)
       questions     one builder:         tests · real browser ·
       one at a      research → plan →    second-model review ·
       time          code + tests         scope check
```

1. **Brainstorm.** One question per message: who uses it, the data lifecycle (what the operator changes without a
   developer), jurisdiction and privacy, every form and who can abuse it, operations, and the edge cases on purpose.
   If it's a new project with a UI, one more question: the name, contacts and look. You approve a written spec.
2. **Build.** One fresh builder agent researches the domain (sourced requirements, not vibes), reads the code it will
   touch and maps every rule, operation and guard it must respect, checks current library APIs, and then writes a plan
   with an acceptance table and builds it with tests. For UI it keeps a `DESIGN.md`
   ([Google's format](https://github.com/google-labs-code/design.md)) and shared components instead of copy-paste, and
   looks at its own screenshots before calling it finished.
3. **Verify.** The project's tests, a real browser submitting real forms, a scope check, and an independent reviewer
   (Codex or a fresh Claude) that attacks an isolated copy with probes that found real bugs before: boundaries,
   cross-user access, session replay, abuse from rotating networks, production start with example secrets. It gets at
   most one fix round.

Each check writes a **signed receipt bound to the exact working tree**. Edit a file and the receipt goes stale. The
outcome is `verified`, `incomplete` or `failed`, and Claude can't talk its way to "done": the Stop hook refuses once,
with the reason.

## Install

```bash
claude plugin marketplace add procoders/superpowers-v
claude plugin install compound-v@procoders
```

Then, once per project:

```
/compound-v:init
```

Needs Claude Code, git with at least one commit, and Python 3.9+. Optional: `codex` as the second-model reviewer
(otherwise a fresh Claude Opus reviews), and Playwright in web projects for the browser check. Init shows every change
as a diff and writes nothing without your yes.

## Commands

You rarely type them: in a set-up project a hook reads each request and sends it to brainstorm or straight to a light
verify.

| Command | When |
|---|---|
| `/compound-v:init` | Once per project, and again after installing Codex or Playwright |
| `/compound-v:brainstorm` | Anything bigger than a typo: a feature, a page, a flow, a new app |
| `/compound-v:verify` | After any change, to get it to `verified` |
| `/compound-v:onboard` | Build a citation-checked knowledge base of an existing repo (`--refresh` when stale) |
| `/compound-v:pr-review` | Deep review of a PR, a commit range or a local diff. Never edits code |

`plan`, `build` and `design` are the builder's own playbook; brainstorm hands off to them. Everything the plugin
writes in your project lives in `docs/compound-v/`.

## Light and full

| Run | For | Must pass |
|---|---|---|
| light | typo, copy, config | tests, scope, plus the browser when a page changed |
| full | features | tests, browser, review, scope |

The tier follows the diff's content, not the file names. A "small fix" that touches auth, sessions, payments,
personal data or a new endpoint becomes a full run on its own.

## Coming from v3

v4 is a new plugin id (`compound-v`). It doesn't need Superpowers and has no orchestration engine: Claude Code
orchestrates itself, and Compound V brings the questions, the checklists and the proof. The `/v:…` commands are gone,
along with dispatch, epic, resume, status, lessons and remember. [CHANGELOG.md](CHANGELOG.md) says why. v3 stays
installable as `superpowers-v@procoders` from the `v3` branch; finish open v3 runs there. If both brainstorms fire,
`/compound-v:init` offers to switch Superpowers off for the project. The
[Compound V Academy](https://amiainative.dev/compound-v) teaches the v3 pipeline; the ideas carry over.

## More

[TROUBLESHOOTING.md](TROUBLESHOOTING.md) for when something stalls · [AGENTS.md](AGENTS.md) for the CLI, hooks and
file map · [docs/v4/](docs/v4/) for the evidence.

Brainstorm prose adapted in part from [Superpowers](https://github.com/obra/superpowers) (MIT, Jesse Vincent). Design
ideas from [Impeccable](https://github.com/pbakaus/impeccable) (Apache-2.0),
[Vercel's Web Interface Guidelines](https://github.com/vercel-labs/web-interface-guidelines) (MIT), Anthropic's
`frontend-design` skill (Apache-2.0) and [DESIGN.md](https://github.com/google-labs-code/design.md) (Apache-2.0).

MIT. See [LICENSE](LICENSE).
