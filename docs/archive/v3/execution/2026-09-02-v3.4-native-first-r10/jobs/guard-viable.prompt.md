# Close the sixth review pass: viability-checked interpreter pick, re-measured hook cost, honest counts, behavioural assertions

Compound V run `2026-09-02-v3.4-native-first-r10`, job `guard-viable`.

Read docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-6.md, items 1–4. Close all four
in your worktree; you have a developer's shell; run Python with -B; register your lane with a
LITERAL --cwd (run `pwd` first; the clamp refuses "$PWD").

ITEM 1 hooks/lane-guard.sh ~:245-251 — pick the interpreter by VIABILITY, not by [ -x ]: iterate
  the candidates (CV_PYTHON first if set, then /usr/bin/python3, `command -v python3`,
  python3.12/3.11/3.10/3.9 if present) and take the first for which `<py> -B -c 'import yaml'`
  exits 0; if none, the first for which `<py> -B -c pass` exits 0, plus a stderr log line naming
  the path and that it lacks PyYAML (the fallback parser will run); if none can run, a log line
  saying the guard could not find a working interpreter and is failing open. Keep the fail-open
  contract and the 1.5 s budget: the probes are two tiny -c calls; measure that they do not add
  more than a few ms (see ITEM 3). Test in tests/test-lane-guard.sh: put an executable shell
  script named python3 that exits 1 first on PATH (and unset CV_PYTHON) → the guard must still
  DENY an out-of-lane write and its log must name the interpreter it used; a second case with NO
  working interpreter at all → exit 0, no decision, and a log line saying so.
ITEM 2 CHANGELOG.md ~:53 — count the manifests under docs/superpowers/execution/*/manifest.yaml
  yourself and state that number; state the fallback-vs-PyYAML comparison as you measure it
  (jobs identical N/N; where the two loaders differ, name the field — the sixth pass found only
  `body`).
ITEM 3 — re-measure the ambient cost with the README recipe (50 invocations of the unresolved
  path, `time`, from the repo root) under the interpreter the hook now selects; report the
  numbers you got and put the measured figure + method + date into README.md's "One ambient
  cost" paragraph, AGENTS.md's copy of it, and the CHANGELOG line that carried 47 ms forward.
  Never publish a number you did not measure.
ITEM 4 tests/test-lane-guard.sh ~:678-682 — the two assertions that grep the hook's source for a
  variable name / a comment: replace each with a behavioural case (drive the hook) or delete it
  if the behaviour is already covered by the cases above it; say which in your report.
RECORDS — spec: append "After the sixth review pass (2026-09-02)" with the four items and their
  resolutions. Run the acceptance commands; report per item: file, change, command, exit code.

## Write-allowed (your lane — anything else is a scope violation)

- `hooks/lane-guard.sh`
- `tests/test-lane-guard.sh`
- `CHANGELOG.md`
- `README.md`
- `AGENTS.md`
- `docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-6.md`
- `docs/superpowers/execution/`

## Acceptance (your definition of done)

- hooks/lane-guard.sh picks the first candidate interpreter for which `<py> -c 'import yaml'` exits 0; if none, the first for which `<py> -c pass` exits 0 plus a log line naming it and its missing PyYAML; if none can run, a log line saying so — never a silent no-decision exit. tests/test-lane-guard.sh proves it with an executable-but-broken `python3` first on PATH: the guard still DENIES an out-of-lane write and logs which interpreter it used.
- CHANGELOG.md's manifest count says 46 (measured over every manifest under docs/superpowers/execution/ at the time of the job — state the number you counted), with the fallback-vs-PyYAML result stated as measured (jobs identical N/N; divergences confined to `body`).
- The hook's ambient cost is re-measured on this machine with the README recipe (50 invocations, unresolved path) under the interpreter the hook now picks, and README.md, AGENTS.md and the CHANGELOG carry the measured figure and method, not the 47 ms carried forward.
- tests/test-lane-guard.sh has no assertion that greps the hook's source for a variable name or a comment as a stand-in for behaviour; the two at ~:678-682 are replaced by behavioural cases or removed; bash tests/test-lane-guard.sh exits 0.
- The spec gains 'After the sixth review pass (2026-09-02)'; shellcheck -S warning hooks/lane-guard.sh is clean.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
