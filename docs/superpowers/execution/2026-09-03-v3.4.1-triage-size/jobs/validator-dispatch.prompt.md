# Task E — the validator and the dispatch tail: triage.flavor scoped_plus, the deep-review rule, the cross-model receipt, the docs

Compound V run `2026-09-03-v3.4.1-triage-size`, job `validator-dispatch`.

Implement plan Task E against spec §WS-E and pre-flight amendments 3 and 5 (a NEW flat schemas/cross-model-receipt.schema.json validated by the existing _schema_lite(); TRIAGE_ALLOWED_KEYS for the unknown-key walk). Selftests first. `triage.flavor` is the only new key and `scoped_plus` its only value; unknown keys stay rejected. Reuse the receipt-schema loading pattern for schemas/plan-review.schema.json. The finalizer advances the phase since stage 1 (fix(finalize) commit f0dfc30) — say so in step 9 instead of the by-hand write. Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-validate-manifest.py`
- `schemas/cross-model-receipt.schema.json`
- `commands/v-dispatch.md`
- `commands/v-orchestrate.md`
- `skills/compound-v/phase-preeval.md`
- `skills/compound-v/cross-model-review.md`
- `skills/compound-v/SKILL.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- /usr/bin/python3 -B scripts/compound-v-validate-manifest.py --selftest is green and carries the five cases of plan Task E Step 1 (grep for "scoped_plus" and "cross-model-receipt"); every committed docs/superpowers/execution/*/manifest.yaml still validates mode-lessly.
- Under --require-triage a scoped_plus manifest without a type review job with tier deep and backend claude is rejected with a message naming the rule; --require-cross-model-receipt PATH verifies schema + run_id + pre_eval_id + diff_digest.
- commands/v-dispatch.md step 8 describes the scoped_plus receipt and step 9 no longer instructs writing phase MERGED by hand; phase-preeval.md, cross-model-review.md (SCOPED+ row yes, mandatory) and SKILL.md Stage −1 describe SCOPED+ and the T3 demotion.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
