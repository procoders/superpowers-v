# Compound V

A Claude Code plugin that asks before it builds and proves before it says done.

You describe what you want. Compound V asks about it one question at a time, researches the domain,
writes a plan with an acceptance table, lets Claude Code build it, and then verifies the result with
real commands: the project's tests, a real browser, a scope check and a review by a second model in
an isolated copy. Each check writes a receipt bound to the exact working tree. "Done" means every
required receipt is current and passing, nothing less.

Version 4 is a standalone plugin (`compound-v`). It no longer needs Superpowers and no longer has its
own orchestration engine: Claude Code orchestrates itself, and Compound V supplies the questions,
the checklists and the proof.

## The cycle

1. **Brainstorm** (`/compound-v:brainstorm`). One question per message: the product and its users,
   the data lifecycle (create, change, retire, delete), jurisdiction and deployment, security and
   every form, operations, and edge cases on purpose. Prior decisions in `docs/compound-v/` are looked
   up first. Output: a spec in `docs/compound-v/specs/`, checked by a fresh builder and approved by you.
2. **Pre-flights**, in parallel. Domain research always (a few searches, each requirement with its
   source and a check). Code archaeology when the repo already has code. A library audit when the
   spec brings in dependencies. Output: `docs/compound-v/preflight/`.
3. **Plan** (`/compound-v:plan`). Tasks with their tests, an **acceptance table** (behaviour → check),
   four checklists answered item by item (data lifecycle, every page and state, every form and
   endpoint, operations), and a task → model table.
4. **Build** (`/compound-v:build`). Native Claude Code: one agent by default, tests written with the
   code.
5. **Verify** (`/compound-v:verify`). The steps below, then one report.

Small changes (a typo, copy, a config value) skip straight to verify as a **light** run. You do not
have to call any of this by name: in a set-up project a hook reads each plain request and points
Claude at brainstorm or verify.

## Install

```bash
claude plugin marketplace add procoders/superpowers-v
claude plugin install compound-v@procoders
```

The marketplace is called `procoders` and lives in the GitHub repo `procoders/superpowers-v`. Then,
in each project:

```
/compound-v:init
```

Init probes git, Python, Codex, a browser runner and Superpowers, and proposes
`.claude/compound-v.json` (reviewer, test command, budget) plus two native project settings. Every
write is shown as a diff and applied only on your yes.

**Needs:** Claude Code, git, a repository with at least one commit, and Python 3.9 or newer.
**Optional:** `codex` as the reviewer (otherwise a fresh Claude Opus subagent reviews), and Playwright
for web projects' browser checks (the project's dependency, not the plugin's).

## The verification bar

| Step | What runs |
|---|---|
| tests | The project's own test command |
| live | A real browser submits real forms and checks the stored result (Playwright); for non-web projects the binary or API runs its main flows |
| scope | The run's diff against the files the plan declared |
| review | A second model reviews an isolated copy of the tree against your original request and the acceptance table, runs things, and reports structured findings. At most two rounds, so one fix round |

Each step writes a signed receipt bound to the working tree. Edit a file afterwards and the receipt is
stale. A run ends in exactly one outcome:

- **verified** — every required receipt is current and passing. Only this is reported as done.
- **incomplete** — a step could not run: no browser, a timeout, the budget hit, or the second review
  still has blocker or high findings. The report names the step and the reason.
- **failed** — a step ran and failed, and no review round is left.

Claude cannot argue its way past this: if it tries to stop on an unverified run, the Stop hook refuses
once with the reason. The second stop goes through and the run is recorded as incomplete or failed.
The session is never trapped. A browser check can be waived only by you, in chat, and the waiver is
quoted in the receipt.

## Light and full

| Tier | Receipts required |
|---|---|
| light (typo, copy, config) | tests, scope, plus live when a page or form changed |
| full (the default for features) | tests, review, live, scope |

The tier follows the diff's content, not its file names. A "small fix" that touches auth, sessions,
payments, personal data, new endpoints or forms, or a big or binary diff, becomes a full run, and its
earlier receipts are cleared.

## Parallel lanes

One agent builds by default. When the plan has large, independent tasks that write disjoint files, it
can declare **lanes**: each task gets exclusive file globs and runs as a native Claude Code subagent
in its own worktree. Nothing merges on trust: `compound-v.py lane finish` checks that the lane stayed
in its globs, merges it, and runs the tests on the merged tree, or refuses with the reason (outside the
lane, interrupted worker, conflict, failing tests, dirty main tree). In the salon brownfield run, v3's
parallel waves added nothing at that size, so the plan skill uses lanes only when the work is large.

## Why v4: the salon evidence

v4 was designed from a set of experiments on Compound V 3.9.1, not from a v4 run. A small salon booking
app was built from the same brief, under the same model and sandbox, and judged blind by Codex running
the code. All numbers below come from [docs/v4/salon-report.md](docs/v4/salon-report.md); costs are
the Claude Code CLI's own estimate.

| Build | Agent time | CLI cost | Rubric (2 judgements) | Capabilities "considered" (2 judgements) |
|---|---|---|---|---|
| Light flow (A5): owner answers + domain research + checklists + one review/fix pass | ~17.5 min | ~$8.1 | 94 / 99 | 72 / 79 |
| Compound V 3.9.1 full pipeline incl. fix round (B) | ~49 min | ~$87 | 62 / 72 | 52 / 65 |
| Owner answers + one review/fix pass, no checklists (A4) | ~11 min | ~$3.8 | 45 / 49 (critical defect) | 45 / 34 |

On an existing codebase (one feature on A5's code), the light flow scored 75 / 78 against the full
v3 pipeline's 69 / 69, at ~15.5 min and ~$8.8 against ~28 min and ~$17.8.

What the runs showed, and what v4 keeps:

- **Questions before code** carry the most depth for the least money: a plain build given the
  owner's brainstorm answers went from 37 to 63 considered capabilities in 7 minutes for ~$2.
- **Domain research and checklists** add the production depth (GDPR, sessions, CSRF, limits).
- **An executable review with a fix round** catches what reading misses. A4 and A5 both built a form
  check that rejected every real browser POST; in-process tests could not catch it, and A5's review
  found it only by checking the Fetch spec. That is why v4 adds a real-browser step.
- **The custom engine added nothing** at this size, at roughly ten times the cost.

The judges move about 10 points between runs on the same build, so every comparison above uses two
judgements.

## v4 benchmark

Pending — results will be added after the acceptance run.

The release gate is fixed before any v4 run: on the same salon brief, v4 must reach at least A5's mean
rubric and mean "considered" score at a mean Claude spend of $7 or less (the CLI's estimate), and match
the light flow on the brownfield feature without breaking the base tests. Until that run has happened,
nothing here claims v4 is better than A5.

## Skills

| Skill | Use |
|---|---|
| `/compound-v:init` | Set up a project (once, and again after installing Codex or Playwright) |
| `/compound-v:brainstorm` | Start anything non-trivial |
| `/compound-v:plan` · `/compound-v:build` | Normally reached from the previous step |
| `/compound-v:verify` | After a build, or after any small change |
| `/compound-v:onboard` | Build a citation-verified knowledge base for an existing repo; `--refresh` when docs go stale |
| `/compound-v:pr-review` | Deep review of a PR, a range or a local diff; never edits code |

Everything Compound V writes in a project lives under `docs/compound-v/`. Run records in
`docs/compound-v/runs/` are written by the CLI only. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) when
something stalls, and [AGENTS.md](AGENTS.md) for the CLI and file map.

## Coming from v3

- **A separate plugin id.** v4 is `compound-v`; v3 was `superpowers-v`. Commands move from `/v:…`
  to `/compound-v:…`, and dispatch, orchestrate, resume, status, epic, lessons, remember and models
  are gone. [CHANGELOG.md](CHANGELOG.md) lists what was removed and why.
- **v3 stays installable** as `superpowers-v@procoders`, pinned to the `v3` branch:
  `claude plugin install superpowers-v@procoders`.
- **Finish unfinished v3 runs with v3.** v4 cannot read v3's `state.json` or manifests. v3's docs now
  live under `docs/archive/v3/` in this repo.
- **Disable Superpowers per project if both brainstorms fire.** v4 does not need it.
  `/compound-v:init` offers to set `"enabledPlugins": {"superpowers@claude-plugins-official": false}`
  in the project's `.claude/settings.json`.
- Run `/compound-v:init` in each project again. It merges its v4 keys into the existing
  `.claude/compound-v.json` and shows the diff first.

## License

MIT. See [LICENSE](LICENSE).
