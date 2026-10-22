# Task A — the pre-flight result names its knowledge-base files; v-dispatch commits them

Compound V run `2026-09-03-v3.4.9-preflight-kb-paths-and-retries-schema`, job `preflight-kb`.

Implement Task A of docs/superpowers/plans/2026-09-03-v3.4.9-preflight-kb-paths-and-retries-schema.md. grep the 1A/1C prompt templates and the result-building post-processing in scripts/compound-v-emit-preflight.py; read only those ranges. Touch only scripts/compound-v-emit-preflight.py and commands/v-orchestrate.md (NOT v-dispatch.md — pre-flight 1A: it has no audit-commit step; v-orchestrate.md Step 8 does). Read the pre-flight audits named in this manifest's audits block first. Tests first. Python 3.9 syntax. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-emit-preflight.py`
- `commands/v-orchestrate.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The emitted pre-flight script asks each auditor for `kb_files` BY NAME in the wrapper prompt text, `RESULT_SCHEMA['properties']` carries it, the result object carries `kb_files` per audit and de-duplicated at the top level, and the three bypass branches (skipped / null / catch) default it to []; `compound-v-emit-preflight.py --selftest` asserts all of that on the emitted text. commands/v-orchestrate.md Step 8 (the existing audit commit) stages the three _knowledge-base directories (archaeology, expert, library-audit) and the pre-flight result's `kb_files`, with the reason (finding 100); commands/v-dispatch.md is untouched. 1A has no KB-write step today, so its kb_files is expected empty — say so in the prompt text, do not invent one.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
