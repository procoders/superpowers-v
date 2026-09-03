# Task B — the localizer: identifiers only, trailing punctuation, new_file, exact-by-name with an incomplete content scan

Compound V run `2026-09-03-v3.4.1-triage-size`, job `localizer`.

Implement plan Task B against spec §WS-B and its amendments. Fixtures first, then the code. A literal path is exact by name even when its content scan is incomplete: add the flag `content_scan_incomplete` instead of degrading confidence (the scorer, Task A, treats that flag as impact-raising). Strip a trailing period/`?`/`!` from a candidate path, never an inner one. Keep every containment rule (`_contained_regular_file`) for the new_file branch's parent directory. Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-localize.py`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- /usr/bin/python3 -B scripts/compound-v-localize.py --selftest is green and carries the ten fixtures of plan Task B Steps 1 and 1b (grep the selftest source for "new_file", "trailing", "content_scan_incomplete", "plain word").
- extract_query_tokens returns no plain word for "change the button colour to red" and the fake search backend is not invoked for it (confidence failed).
- localize() returns confidence new_file with fan_out 1 for scripts/new-thing.py when scripts/ exists and the file does not; failed for nonexistent-dir/x.py.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
