# Task B — memory.md, v-init.md, CHANGELOG

Compound V run `2026-09-03-v3.4.10-recall-to-action`, job `docs`.

Implement Task B of docs/superpowers/plans/2026-09-03-v3.4.10-recall-to-action.md; describe the behaviour as the spec defines it (Task A implements it in parallel). Touch only your three files. Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind). Tests first. Python 3.9 syntax. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `skills/compound-v/memory.md`
- `commands/v-init.md`
- `CHANGELOG.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- memory.md's recall→action section describes the two real actions (prompt evidence always; tier rung + review re-check under auto_tighten), --no-recall, and the zsh word-split note; v-init.md Step 3b's auto_tighten sentence names the real action; CHANGELOG [Unreleased] has '### Added — the recall→action bridge acts at emit time (stage 5b, finding 130)' with the 7-of-27 measurement and no other number; lint green. memory.md also states where the verdict is recorded (emitted job entry + state.json via register-lane) and that cost is measured per job (recall_check_ms), never assumed.

Turn cap: 30 (default for tier light; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
