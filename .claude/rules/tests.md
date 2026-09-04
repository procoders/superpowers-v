---
paths:
  - "tests/**"
---

# Tests

Sourced from `CONVENTIONS.md` §"Tests live under `tests/`, and the sweep must never match zero".
  (`CONVENTIONS.md:26-34`)

- Discovery is **recursive** over `.sh` and `.py`, so a new file — a nested directory included — is
  picked up with no registration step. (`.github/workflows/validate.yml:367-368`)
- The job always runs: no `paths:` filter and no `if:` guard, because GitHub reports a
  conditionally-skipped required check as `Success`. (`.github/workflows/validate.yml:333-335`)
- The sweep **fails when it discovers nothing** — a guard that silently matches zero files is a false
  green, which is how 25 of 29 selftests stopped running in v2.14.
  (`.github/workflows/validate.yml:369-372`)
- A `.sh` file is run with `bash` and a `.py` file with `python3`, both under `LANG=C`; a non-zero
  exit is the only failure signal, and every test still runs after one fails.
  (`.github/workflows/validate.yml:353-354`, `.github/workflows/validate.yml:358-366`)
- Python 3.9 is the interpreter floor these tests are run against.
  (`.github/workflows/validate.yml:342-346`)
- Write no bytecode: the sweep exports `PYTHONDONTWRITEBYTECODE=1`, because a `.pyc` left beside a
  script is an untracked file the scope gate unions into a job's changed set and BLOCKS the job that
  ran its own tests. (`.github/workflows/validate.yml:353-357`)
