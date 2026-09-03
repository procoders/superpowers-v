# Task A' — the watcher's detectors made precise and tick-safe (review-1 issues 1, 2, 2b, 3, 4, 6, 7, 10)

Compound V run `2026-09-03-v3.4.2-transcript-watch-r2`, job `watch-script`.

Review pass 1 (docs/superpowers/dogfood/2026-09-03-v3.4.2-transcript-watch-review-1.md) found ISSUES (10) on the watcher; read it in full first — its section per issue names the exact lines. Fix issues 1, 2, 2b, 3, 4, 6, 7 and 10 inside your lane (the script and its test), TEST FIRST: one fixture per false-positive class before the detector changes. Do not weaken a detector to make a fixture pass — anchor it (issue 2's rule). Issue 9 (the job ran `impacted` under tier FULL) is NOT yours and is not a defect: the derived default honours a declared impacted_map at every tier by the maintainer's 2026-09-02 rule; the reviewer's note is answered in the review-2 job. Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-transcript-watch.py`
- `tests/test-transcript-watch.sh`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- bash tests/test-transcript-watch.sh is green and now carries one fixture per false-positive class of review-1 (a Bash `2>/dev/null` redirect and a non-repo path produce NO out-of-lane; a tool_result that merely QUOTES the deny literal produces NO denied; a register-lane split across two ticks keeps the agent registered; a missing repo root does not raise) plus a discovery test that resolves the session root through CLAUDE_CONFIG_DIR; /usr/bin/python3 -B scripts/compound-v-transcript-watch.py --selftest is green.
- A path with no repo-relative form is never reported out-of-lane; `denied` and the error patterns anchor to the tool_result of a refused call (is_error / the literal at the start of a line), and the evidence rendered is the MATCHING line, not the first; the pending tool_use table (id → name, parsed register-lane) is persisted in the state file across ticks; no advisory path raises (a falsy repo root is guarded); the dead `except … pass` in save_state is gone.
- The per-tick summary carries a one-line-per-agent roster (`<agent8> <job|(unregistered)> <status>`), which is what acceptance criterion 2 of r1 meant by 'names every agent of the run with its job'.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
