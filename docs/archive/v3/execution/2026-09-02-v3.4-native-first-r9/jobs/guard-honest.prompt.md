# Close the fifth review pass: a lane guard that actually enforces, a register-lane the clamp accepts, and honest acceptance greps

Compound V run `2026-09-02-v3.4-native-first-r9`, job `guard-honest`.

Read docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-5.md, items 1–3, with its
reproduction table (the r5 manifest under default PATH: FAILED OPEN; under
CV_PYTHON=/usr/bin/python3: deny). Close all three in your worktree; you have a developer's shell.
Run Python with -B. To register your lane, run `pwd` first and pass the printed path as a LITERAL
--cwd value — the clamp refuses "$PWD".

ITEM 1 — the lane guard must read every manifest.
  a. hooks/lane-guard.sh interpreter pick (~:191-195): CV_PYTHON if set; else the first candidate
     among /usr/bin/python3 and `command -v python3` (then python3.12/3.11/3.10/3.9 if present)
     for which `<py> -c 'import yaml'` succeeds; else the first candidate that exists, AND a log
     line naming the chosen path and that it lacks PyYAML. Keep the fail-open contract.
  b. scripts/compound-v-validate-manifest.py load_yaml/_mini_yaml (~:138-144): (i) `_mini_yaml`
     handles a plain scalar folded across lines — a continuation line indented deeper than its
     key that is not a `key:` and not a `- ` item joins the previous value with a space (this is
     what yaml.safe_dump(width=100) writes for a long `feature:`); (ii) when the source text has a
     top-level `jobs:` key and the parse yields no jobs, raise ValueError("manifest parse produced
     no jobs — refusing a silent empty parse") rather than returning jobs: []; (iii) load_yaml
     records which loader ran (e.g. a module-level LAST_LOADER = 'pyyaml'|'fallback') so callers
     and tests can tell. Selftests: a fixture produced by yaml.safe_dump(width=100) with a long
     feature string parses to the same jobs under both loaders; a text with `jobs:` and a broken
     body raises.
  c. tests/test-lane-guard.sh: add a case whose sandbox manifest has a folded top-level scalar
     (write it with a long `feature:` through python's yaml.safe_dump(width=100) when PyYAML is
     present, else a hand-folded equivalent) and assert DENY for an out-of-lane write with
     CV_PYTHON unset AND with CV_PYTHON=/usr/bin/python3.
ITEM 2 — register-lane and the four records.
  d. scripts/compound-v-emit-workflow.py ~:1302: stop emitting `--cwd "$PWD"`. Emit the command
     with `--cwd <ABSOLUTE PATH YOU PRINTED WITH pwd>` as a placeholder and a sentence right above
     it: "Run `pwd` first (it is admitted) and paste its output as a literal path: the clamp
     refuses shell substitution such as \"$PWD\" or $(...) — the first tool call of every worker
     in run r8 was denied for exactly this." Rewrite the comment at ~:1291-1300 and the Implement
     prompt sentences at ~:1313-1317 to name substitution, delete the ONE-line rule (external
     launches use _shell_join continuations by design), fix the selftest at ~:4448-4450 to pin the
     new sentence and the absence of "$PWD" in the rendered prompt, and correct the CHANGELOG
     sentence that blamed a continuation.
ITEM 3 — honest greps.
  e. scripts/compound-v-scope-check.py ~:773-776 and tests/test-integration-gate.sh ~:483-486:
     replace the split literals with the plain symbol (in a comment or an assertion message), and
     make the assertion definition-scoped: it must fail only if a line matching
     ^PIPELINE_BOOKKEEPING\s*= exists in scripts/ or hooks/.
RECORDS — CHANGELOG 3.4.0: add "### Fixed — the lane guard read no manifest written with a folded
scalar" (what failed, the blast radius the review measured: 6 of 45 manifests, r3–r8, every run
of this feature; what changed). Spec: append "After the fifth review pass (2026-09-02)" with the
three items and their resolutions.
Then run the acceptance commands and report per item: file, change, command, exit code.

## Write-allowed (your lane — anything else is a scope violation)

- `hooks/lane-guard.sh`
- `tests/test-lane-guard.sh`
- `scripts/compound-v-validate-manifest.py`
- `scripts/compound-v-emit-workflow.py`
- `scripts/compound-v-scope-check.py`
- `tests/test-integration-gate.sh`
- `CHANGELOG.md`
- `docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-5.md`
- `docs/superpowers/execution/2026-09-02-v3.4-native-first-r5/manifest.yaml`

## Acceptance (your definition of done)

- hooks/lane-guard.sh prefers an interpreter that can `import yaml` (CV_PYTHON first, then the first of /usr/bin/python3, python3 that imports yaml, else the first found) and logs, by path, when the chosen one has no PyYAML; driven with the r5 manifest (a folded `feature:` scalar) and default PATH, an out-of-lane write is DENIED, not failed open.
- scripts/compound-v-validate-manifest.py: the PyYAML fallback is not silent — `_mini_yaml` parses a plain scalar folded across lines (as yaml.safe_dump width=100 writes), and a parse of text containing a top-level `jobs:` that yields no jobs raises a clear error instead of returning []; both pinned by selftests using a safe_dump-folded fixture.
- tests/test-lane-guard.sh has a case with a folded top-level scalar in the manifest and asserts DENY under both the fallback parser and a PyYAML interpreter.
- scripts/compound-v-emit-workflow.py no longer emits `--cwd "$PWD"`: the Implement prompt tells the worker to run `pwd` (admitted) and pass the printed path as a literal `--cwd /abs/path`, because the clamp refuses shell substitution ("$PWD", $(...)) — and the comment at ~:1291, the prompt sentences, the selftest and CHANGELOG say substitution, not backslash-newline continuation; the ONE-line rule is dropped (external launches legitimately use _shell_join continuations). Selftest pins the literal-cwd instruction and the absence of "$PWD" in the rendered prompt.
- The split literals are gone: scripts/compound-v-scope-check.py and tests/test-integration-gate.sh spell the symbol plainly where they must mention it, and the acceptance grep is definition-scoped: grep -rnE '^PIPELINE_BOOKKEEPING\s*=' scripts hooks returns nothing.
- CHANGELOG 3.4.0 gains '### Fixed — the lane guard read no manifest written with a folded scalar' and the spec gains 'After the fifth review pass (2026-09-02)'; bash tests/test-lane-guard.sh, bash tests/test-integration-gate.sh exit 0; /usr/bin/python3 -B --selftest is green for validate-manifest, emit-workflow and scope-check.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
