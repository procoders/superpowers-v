# Task A — the scorer: broad-glob breadth, T3 demotion, SCOPED+, new_file, content-scan exclusion, the record schema, this repo's taxonomy

Compound V run `2026-09-03-v3.4.1-triage-size`, job `scorer`.

Implement plan Task A (docs/superpowers/plans/2026-09-03-v3.4.1-triage-size.md) against spec §WS-A, §WS-B amendments and pre-flight amendments 2, 4 and 6 (retain per-path match rows; the demotion branch before override #4's elif; the DIRECT predicate tests confidence == exact by name; no lane-guard entry in the taxonomy) (docs/superpowers/specs/2026-09-03-v3.4.1-triage-size-design.md). Read both first, then the archaeology audit named in the manifest. Write the failing selftest cells first, then the code. Keep the engine T3-agnostic: it never calls a model. Keep `_verdict` the only place a verdict is built (add a `flavor` kwarg). Add `content_scan_incomplete` to `_IMPACT_RAISING_FLAGS`. Do not touch scripts/compound-v-localize.py (Task B owns it) — feed `new_file` localizations by hand in your selftest. Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-preeval.py`
- `scripts/compound-v-taxonomy.py`
- `scripts/compound-v-validate-taxonomy.py`
- `schemas/pre-eval-record.schema.json`
- `.claude/compound-v-impact-taxonomy.yaml`
- `.claude/compound-v-impact-taxonomy.example.yaml`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- /usr/bin/python3 -B scripts/compound-v-preeval.py --selftest, scripts/compound-v-taxonomy.py --selftest and scripts/compound-v-validate-taxonomy.py --selftest are green and each carries the new cells named in plan Task A Step 1 (grep the selftest source for "scoped_plus", "demotion", "new_file", "content_scan_exclude", "NEVER_DEMOTE").
- The three committed records under docs/superpowers/pre-eval/*.json still validate against the amended schema (jsonschema if installed, else the engine's own validator).
- match_path returns broad per matched row; classify honours content_scan_exclude; score() returns t3_reason on needs_t3 and flavor/t3_demotion on verdicts; _verdict remains the single construction point.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
