# Task A — scripts/compound-v-transcript-watch.py and tests/test-transcript-watch.sh: five signals, discovery by run-dir path, read-only

Compound V run `2026-09-03-v3.4.2-transcript-watch`, job `watch-script`.

Implement plan Task A against the spec (docs/superpowers/specs/2026-09-03-v3.4.2-transcript-watch-design.md §Decisions 1–4, §Pre-flight amendments 1–6, §Testing). Write the failing test first, then the script. Python 3.9 stdlib only. The path matcher comes from scripts/compound-v-scope-check.py by importlib path import — never a second glob matcher. The script must never write into the run directory or the repository (its --state file defaults under the OS temp dir). Read the archaeology audit named in the manifest before writing. Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-transcript-watch.py`
- `tests/test-transcript-watch.sh`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- bash tests/test-transcript-watch.sh is green and asserts exactly the signal set of plan Task A Step 1 (grep the test for out-of-lane, wrong-cwd, error, denied, stall, and for the no-signal in-lane write); /usr/bin/python3 -B scripts/compound-v-transcript-watch.py --selftest is green.
- The script imports the matcher from scripts/compound-v-scope-check.py by path, keeps per-agent offsets in --state so --once twice emits no repeated signal, emits --json objects with ts/job/agent/signal/evidence/line, and exits 0 on every advisory path.
- Discovery: with no --wf, the script finds the workflow directory whose agent transcripts mention the run directory's absolute path, newest first; --transcripts and --wf override.
- The script imports load_yaml from scripts/compound-v-validate-manifest.py by path (no PyYAML import of its own), reads meta.json with .get(), matches the denied signal on the literal `Compound V lane guard: job '` only, and prints a non-crashing 'no transcripts found' line when discovery matches nothing.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
