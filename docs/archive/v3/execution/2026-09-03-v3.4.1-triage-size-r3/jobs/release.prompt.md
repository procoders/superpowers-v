# Task F — release 3.4.1: CHANGELOG, versions, README triage paragraph, native-mechanisms row

Compound V run `2026-09-03-v3.4.1-triage-size-r3`, job `release`.

Task F — release 3.4.1. In run r2 this job was done in the MAIN checkout by mistake of the emitter (finding 60), so its edits could not be merged; the diff was kept as docs/superpowers/execution/2026-09-03-v3.4.1-triage-size-r3/jobs/release.draft.patch (repo-relative, from the repository root). You are in your OWN worktree: `git apply --index docs/superpowers/execution/2026-09-03-v3.4.1-triage-size-r3/jobs/release.draft.patch` from the worktree root, then VERIFY it against the merged tree you are in — HEAD now also carries the orchestrator's stage-2 fixes (fix(finalize) ×3, fix(validator), fix(preeval) flavor, fix(emit) finding 60) whose CHANGELOG lines live under [Unreleased]; keep every one of them under the 3.4.1 heading and add anything the draft missed by reading `git log --oneline 20ed725..HEAD` and the diffs of the five feature jobs. No fabricated metrics (the probe timings 5.5 s / 8.0 s are measured). Own the result: the acceptance below is yours, not the draft's. Run python with -B; register your lane with a literal --cwd.

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
