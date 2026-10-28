# Compound V — agent instructions

Portable instructions for any agent working on this repository (Claude Code reads them through
`CLAUDE.md`; Codex and other harnesses read this file directly). Compound V 4.0 is a Claude Code
plugin, id `compound-v`. Its skills and hooks assume Claude Code; other harnesses can read the
skill prose but get none of the hooks.

## What the plugin does

One cycle, in this order. Each step is a skill (`/compound-v:<name>`):

1. **brainstorm** — one question per message about the product, data lifecycle, jurisdiction,
   forms, operations and edge cases; writes the spec to `docs/compound-v/specs/` and starts the run
   record.
2. **build** — one fresh `builder` subagent does, in its own context: domain research (≤ 4
   searches), a reading of the code it touches when git tracks code, a library check when a
   dependency changes, then the **plan** (following the `plan` skill: an acceptance table, the
   checklists answered, tasks with tests, the `compound-v-plan` block that `run plan` attaches),
   then the code with its tests. Every fix goes back to the same builder by `SendMessage`. Parallel
   work only for large independent parts (the Workflow tool only with `Parallel: yes (owner)` in the
   spec), with lanes merged through `lane finish`.
3. **verify** — tests, a real-browser (or main-flow) check, a scope check and, for full runs, an
   executable review in an isolated checkout with at most one fix round. Each step writes a signed
   receipt bound to the working tree. Outcome: `verified`, `incomplete` or `failed`.

When the change has a user interface, the builder also follows **design**: the project's `DESIGN.md` (Google's
format) as the one source of the look, shared components instead of copies, a craft floor and a screenshot check.
Projects with no UI never load it.

Small changes (typo, copy, config) skip straight to **verify** as a light run. Around the cycle:
**init** (per-project setup), **onboard** (citation-verified knowledge base for an existing repo)
and **pr-review** (review-only, never edits).

## Tiers and the verification bar

| Tier | Required receipts |
|---|---|
| light | `tests`, `scope`, plus `live` when the diff touches UI |
| full | `tests`, `review`, `live`, `scope` |

The CLI reclassifies every diff by content (auth, sessions, payments, personal data, new endpoints or
forms, big or binary diffs); a light run that trips one becomes full and its receipts are cleared.
Only `live` can be waived, and only on the user's words in chat. At most two review rounds.

## The CLI

Everything that must not be self-reported lives in `scripts/compound-v.py` over `scripts/cvcore/`.
Exit 2 with one line on any error.

| Subcommand | Does |
|---|---|
| `run start --tier light\|full --request-file - [--spec] [--base] [--change-set]` | Create a run record |
| `run stage --to <stage>` · `run plan --plan <path>` · `run show` · `run bind --session` | Move stage, attach the plan block, print, bind to a session |
| `receipt tests\|live\|scope` | Run the step, write a signed receipt (exit 1 unless pass) |
| `checkout --dest <dir>` | Materialize the current tree snapshot for the Claude reviewer |
| `review codex` · `review record --findings <f> --reviewer claude` · `review codex-plan --plan <p>` | Record an executable review; optional advisory plan review |
| `waive live --reason "<user's words>"` | Record a browser-check waiver |
| `status` | Outcome; exit 0 verified, 3 pending, 4 incomplete, 5 failed |
| `scope` · `escalate` · `classify-request` | Diff vs change set and lanes; diff tier; prompt tier |
| `lane finish --task <t> --branch <b>` | Scope-check, merge and test one parallel lane |
| `usage --session --transcript` · `hud [--brief]` · `cochange --path` | Run cost from the CLI's record; band JSON; co-change lookup |
| `snapshot` | Print the canonical tree hash |

Stages: `brainstorm, preflight, plan, build, verify, done`. Outcomes: `verified, incomplete, failed`
(or `null` while open).

## Hooks (`hooks/hooks.json`)

| Event | Script | Does |
|---|---|---|
| `UserPromptSubmit` | `prompt.sh` | Classifies a plain request and points at brainstorm (full) or verify (light); one "run /compound-v:init" line in a project that is not set up |
| `Stop` | `stop.sh` | Refuses the first stop of an unverified run, once, with the reason; records usage |
| `SessionStart` | `session.sh` | One-line brief of the open run; onboard doc staleness |
| `PreToolUse` (Write/Edit) | `guard.sh` | Denies hand edits under `docs/compound-v/runs/` |
| `SubagentStop` | `subagent.sh` | Records that the `reviewer` subagent ran |

Plus the band mod `hooks/run-band.tsx` (stage, receipts, run cost, quota footer). All hooks fail open.

## File map

| Path | Responsibility |
|---|---|
| `scripts/compound-v.py` | Entry point; calls `cvcore.cli.main()` |
| `scripts/cvcore/gitio.py` | git wrapper, repo root, `GitError` |
| `scripts/cvcore/snapshot.py` | Canonical tree hash, ignored-env digest, materialized checkout |
| `scripts/cvcore/run.py` | Run record: create, load/save, active run, stages, plan block |
| `scripts/cvcore/scope.py` | Changed files vs base, glob match, symlink escape |
| `scripts/cvcore/escalate.py` | Diff content predicates → tier; prompt classifier |
| `scripts/cvcore/receipts.py` | Step runner, signed receipts, waivers, review recording, status |
| `scripts/cvcore/review.py` | Codex executable review and plan review |
| `scripts/cvcore/usage.py` | Run cost from the CLI's `cost-state` transcript entries |
| `scripts/cvcore/lanes.py` | Lane gate for native worktree writers |
| `scripts/cvcore/hud.py` | Band JSON, one-line brief, co-change lookup |
| `scripts/cvcore/hooks.py` | Stop, prompt, session, guard and subagent decisions |
| `scripts/cvcore/cli.py` | argparse wiring |
| `scripts/compound-v-run-with-timeout.py` | Process-group timeout supervisor for every step |
| `scripts/compound-v-onboard.py` | onboard's deterministic gates |
| `scripts/lint-frontmatter.py` | Agent/skill frontmatter and model-policy lint |
| `schemas/review-findings.schema.json` | Reviewer output shape |
| `hooks/*.sh`, `hooks/hooks.json`, `hooks/run-band.tsx` | Hook wrappers and the band |
| `skills/{brainstorm,plan,build,design,verify,init,onboard,pr-review}/` | The prose |
| `agents/{v-memory,builder,reviewer}.md` | Subagents |
| `tests/core/`, `tests/hooks/` | Tests |

## Agents and model policy

- `builder` — Opus, 200 turns. Research, plan and build for one run; takes every fix.
- `reviewer` — Opus, 25 turns. The sharp executable reviewer in an isolated checkout (a fixed probe
  list, a skip list, severity floors; round 2 re-checks fixes only).
- `v-memory` — Haiku, tools `Read, Grep, Glob` only. Read-only search over `docs/compound-v/`.

Opus for every agent; Sonnet chosen per task at dispatch for mechanical work; **never Haiku** except `v-memory`; Fable only
by explicit choice. `scripts/lint-frontmatter.py` enforces it.

## Rules for changes here

See [CONVENTIONS.md](CONVENTIONS.md). In short: no unmeasured numbers, stdlib Python 3.9, hooks fail
open, state only in `docs/compound-v/` or `.git/compound-v/`, skills not commands, core ≤ 2550
lines.

## Tests

```bash
python3 -m unittest discover -s tests/core -v
for t in tests/hooks/*.sh; do bash "$t"; done
python3 scripts/lint-frontmatter.py .
shellcheck hooks/*.sh
```

v3 (`superpowers-v`) lives on the `v3` branch; its docs are archived under `docs/archive/v3/`.
