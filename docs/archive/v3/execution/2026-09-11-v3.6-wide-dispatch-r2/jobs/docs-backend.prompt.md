# Task J-DOCS/3 — the backend adapters and the native-mechanisms audit

Compound V run `2026-09-11-v3.6-wide-dispatch-r2`, job `docs-backend`.

Implement the backend and audit half of Task J-DOCS in docs/superpowers/plans/2026-09-11-v3.6-wide-dispatch.md (spec F8). THE ONE RULE (Oleg, 2026-09-03): documentation must be clear and simple. Plain words, short sentences, one idea per paragraph, every claim true of the code in HEAD. native-mechanisms.md is written in RUSSIAN in the existing rows — match the language and the column shape of the table you are adding to, and keep every claim sourced from the installed binary or a live probe, never from a version number. WHY THIS JOB IS SMALL: the first attempt gave all eleven documents to one implementer and it hit its 80-turn cap three times. Yours is three files. Read one worker script region to get the flag spelling right, not all four. Touch only your lane. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `skills/backend-launcher/SKILL.md`
- `skills/backend-launcher/adapter-codex.md`
- `docs/superpowers/architecture/native-mechanisms.md`

## Global constraints (binding on every job)

Project-wide, and binding on EVERY job in this run including yours.
Copied verbatim from the plan — do not reinterpret, relax or widen
them.

- Python 3.9 syntax, stdlib only; every script run as /usr/bin/python3 -B; bash passes shellcheck
- Never Haiku; no agent frontmatter names Fable; Fable enters only through advisorModel
- Never relax the scope gate; no new entry in RUN_DIR_EXEMPT_BY_NAME; provisioning is subtracted only through the existing --preexisting snapshot path
- No fabricated metrics; every behavioural change ships a selftest row that fails when the change is reverted
- Docs: plain words, one idea per paragraph, no line over 200 characters outside code/tables, every claim true of the code in HEAD
- Lane discipline: touch only your write_allowed; register-lane first, with a literal --cwd
- Field and flag names are fixed by the plan's Interfaces: provision_command, provision_timeout_s, --provision-command, --provision-timeout-sec, preexisting.txt, verdict_disagreement, candidate_runs, MEMORY_LANE_UNNAMESPACED, SECOND_OPINION_SAME_FAMILY, claude-advisor, usage.advisor_calls
- Not in any job: CHANGELOG entry, version bump, release, generated architecture docs

## Interfaces (your only view of the neighbours)

You see only your own job. This block is the ONLY view you get of the
names and signatures neighbouring jobs rely on — implement exactly
these, and do not rename or re-shape them.

consumes (what earlier jobs give you):

- the two worker flags --provision-command and --provision-timeout-sec as the four worker scripts accept them in HEAD

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- backend-launcher/SKILL.md and adapter-codex.md document the two worker flags: their exact spelling, that the command runs through /bin/bash -c after git worktree add and before the before-image snapshot, the default timeout, and that a failing provision emits a status error job_result and launches no worker.
- native-mechanisms.md gains two rows in the existing table shape and language: the advisor tool (native, used since 3.6.0) and skill usage accounting via /skill-doctor (native, used from /v:init since 3.6.0, report only).
- lint-frontmatter and rules-lint green; every relative link resolves.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
