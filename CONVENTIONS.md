# Conventions

The few rules that hold everywhere in this repository. Each one names the file that enforces or
states it.

## No fabricated metrics

- Never print a cost, time, token or savings number that was not measured. Every number in a doc
  names its source; the salon numbers come only from `docs/v4/salon-report.md`.
- Dollar figures come from the Claude Code CLI's own cost record (`cost-state` entries in the
  session transcript) and are labelled "the CLI's estimate". (`scripts/cvcore/usage.py:15-35`)
- The CLI writes `cost-state` only when a turn ends, so the API responses after the last one (main
  thread and `subagents/agent-*.jsonl`) are priced at the list prices cited in
  `scripts/cvcore/prices.json` and the figure is labelled an estimate (`basis: "estimate"`, `~$`)
  until the next `cost-state` replaces it. (`scripts/cvcore/usage.py:55-71`)
- Absent stays absent: when any session's cost is unknown, or a response's model is not in the
  price list, the run's cost is `null`, never a substituted zero. (`scripts/cvcore/usage.py:126-130`)
- CI greps `scripts/` and `docs/` for claimed-savings phrasing and fails on a hit.

## Model policy

- Opus by default: building, judging, reviewing (`agents/reviewer.md` is `model: opus`).
- Sonnet only for mechanical work with nothing to decide, chosen per task at dispatch time, never in
  agent frontmatter. (`scripts/lint-frontmatter.py:41-45`)
- **Never Haiku**, with one exception: the read-only `v-memory` docs search, whose tools must stay
  `Read, Grep, Glob`. (`agents/v-memory.md:4-5`, `scripts/lint-frontmatter.py:46-47`)
- Fable only when the user chooses it, never in frontmatter.
- `scripts/lint-frontmatter.py` enforces this and CI runs it.

## Enforcement is written by the CLI, never by the model

- Receipts, outcomes, scope verdicts and usage are written by `scripts/compound-v.py` from real
  command results. Receipts are HMAC-signed with a machine key. (`scripts/cvcore/receipts.py:21`)
- Run records under `docs/compound-v/runs/` are never edited by hand; the guard hook denies
  Write/Edit there. (`scripts/cvcore/hooks.py:291`)
- Command output kept in a receipt is capped at the last 20 lines. (`scripts/cvcore/receipts.py:138-139`)

## Hooks fail open

- Every hook script starts with `trap 'exit 0' EXIT` and prints a decision only on success.
  (`hooks/stop.sh:2`)
- Every registration carries `"shell": "bash"`, a `timeout` of at most 10 s, and a `|| true` suffix,
  so a parse error before the trap still cannot block a stop or reject a prompt. (`hooks/hooks.json:2`)
- A hook may refuse a stop **once** per tree and stage, never forever. (`scripts/cvcore/hooks.py:89-95`)
- Hooks are thin: all logic is in `scripts/cvcore/hooks.py`, called through `scripts/compound-v.py hook <event>`.

## Where state lives

- Project state: `docs/compound-v/` only (specs, plans, pre-flights, runs, receipts, the triage log).
  (`scripts/cvcore/run.py:15`)
- Per-clone state: `.git/compound-v/` only (the receipt key; the sandbox lets commands write there, not to `~/.claude`). (`scripts/cvcore/receipts.py:23,36-42`)
- Per-session hook markers (refused-once, nudge count) are scratch files in the system temp dir, or
  `CV_STATE_DIR`. (`scripts/cvcore/hooks.py:41-45`)
- Nothing is ever written under `${CLAUDE_PLUGIN_ROOT}`.

## Python

- Standard library only, Python 3.9 floor. (`skills/init/SKILL.md:20`)
- No bytecode next to the scripts: the entry point sets `sys.dont_write_bytecode`, and hooks run
  Python with `-I -B`. (`scripts/compound-v.py:7-8`, `hooks/stop.sh:5`)
- The one named exception is CI tooling: `scripts/lint-frontmatter.py` imports PyYAML.
  (`scripts/lint-frontmatter.py:36`)
- The new core (`scripts/compound-v.py`, `scripts/cvcore/*.py`, `hooks/*.sh`, `hooks/run-band.tsx`)
  stays at or under 2550 lines; CI prints the count.

## Skills, not commands

- Every user-facing entry point is `skills/<name>/SKILL.md`, which Claude Code exposes as
  `/compound-v:<name>`. There is no `commands/` directory.
- Subagents live in `agents/*.md`; each needs `name`, `description` and `model` in its frontmatter.

## Tests

- Core: `python3 -m unittest discover -s tests/core -v`. Hooks, skills, band and onboard:
  `for t in tests/hooks/*.sh; do bash "$t"; done`.
- Tests build throwaway git repos in a temp dir and point `HOME` and the receipt key there, never at
  this checkout or the real home. (`tests/hooks/test-hooks.sh:4-6`, `tests/core/helpers.py:49-54`)

## Versioning

- `plugin.json`, `marketplace.json` and the top `## [x.y.z]` heading of `CHANGELOG.md` carry the same
  version; CI fails on drift.
- The GitHub release is cut by CI when that version lands on `main`. Its title comes from a
  `<!-- title: ... -->` line under the version heading (else the heading text after the dash, if not a date).
