# Task B — collect-results validates retries[] items like usage

Compound V run `2026-09-03-v3.4.9-preflight-kb-paths-and-retries-schema`, job `retries-schema`.

Implement Task B of docs/superpowers/plans/2026-09-03-v3.4.9-preflight-kb-paths-and-retries-schema.md. grep the comment 'schema-INVALID usage payload' and the retries check near it; read only those ranges. Touch only scripts/compound-v-collect-results.py. Read the pre-flight audits named in this manifest's audits block first. Tests first. Python 3.9 syntax. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not. Reuse _usage_conformance_errors' type-map pattern and ADD the required-field check it lacks; index every violation; hard-block like usage.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-collect-results.py`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- compound-v-collect-results.py validates each retries[] item (required stage:str and attempt:int≥1 not bool; optional job:str, wait_ms:int≥0, escalated_from/model:str|null; no other keys) with a violation naming the index and key, hard-blocking like usage; `--selftest` covers good / unknown key / missing stage / string attempt; schemas/job_result.schema.json untouched.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
