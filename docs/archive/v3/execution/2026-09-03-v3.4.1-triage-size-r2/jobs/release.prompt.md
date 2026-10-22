# Task F — release 3.4.1: CHANGELOG, versions, README triage paragraph, native-mechanisms row

Compound V run `2026-09-03-v3.4.1-triage-size-r2`, job `release`.

Implement plan Task F. Read the merged tree (Tasks A, B, D and E landed in commit 028b264 of the first run and Task C lands in this run's first wave — all are in HEAD by the time you run). Write the CHANGELOG from what actually landed — read the diffs of the five jobs' files against the run's baseline — never from the plan's promises. No fabricated metrics; the probe timings (5.5 s / 8.0 s) are measured and may be quoted as such. Run python with -B; register your lane with a literal --cwd.
 The CHANGELOG's [Unreleased] section already holds the stage-1 and stage-2 orchestrator fixes (phase advance, open-jobs hook window, run locks, PyYAML validator, partial-wave bookkeeping); keep them under the 3.4.1 heading and add the feature sections from the merged diffs: git diff 20ed725..HEAD -- <the five jobs' files>.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: test-scope.

## Write-allowed (your lane — anything else is a scope violation)

- `CHANGELOG.md`
- `README.md`
- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`
- `docs/superpowers/architecture/native-mechanisms.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- CHANGELOG.md's top heading is "## [3.4.1] - 2026-09-03" (the [Unreleased] section renamed, the stage-2 sections appended), plugin.json and marketplace.json both say 3.4.1, and /usr/bin/python3 -B scripts/lint-frontmatter.py . is green.
- README.md's triage paragraph names the three tiers and SCOPED+ in one sentence; native-mechanisms.md has a row for the headless one-shot classify.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
