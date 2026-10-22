# Task B — /v:status --live, /v:dispatch step 6 advice, CHANGELOG 3.4.2, versions, README sentence

Compound V run `2026-09-03-v3.4.2-transcript-watch`, job `docs-release`.

Implement plan Task B against the spec §Decisions 5 and the CLI contract of §Decisions 1 (you will not see Task A's script — it runs in parallel; describe the CLI exactly as the spec fixes it). No fabricated metrics. Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `commands/v-status.md`
- `commands/v-dispatch.md`
- `CHANGELOG.md`
- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`
- `README.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- commands/v-status.md has a --live section that runs the watch --once and prints its lines after the state table; commands/v-dispatch.md step 6 documents the background --every 120 watch and names out-of-lane and wrong-cwd as the signals that justify TaskStop + re-orchestrate.
- CHANGELOG.md's top heading is ## [3.4.2] - 2026-09-03 with one Added section naming the five signals and the discovery rule; plugin.json and marketplace.json both say 3.4.2; README has one sentence under the orchestrator surface; /usr/bin/python3 -B scripts/lint-frontmatter.py . is green.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
