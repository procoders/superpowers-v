# Task J-DOCS/1 — the four root documents

Compound V run `2026-09-11-v3.6-wide-dispatch-r2`, job `docs-core`.

Implement the four root documents of Task J-DOCS in docs/superpowers/plans/2026-09-11-v3.6-wide-dispatch.md (spec F8). THE ONE RULE (Oleg, 2026-09-03): documentation must be clear and simple. Plain words, short sentences, one idea per paragraph, every claim true of the code in HEAD; anything measured, historical or defensive is linked (AGENTS.md, CHANGELOG.md, TROUBLESHOOTING.md), never repeated. WHY THIS JOB IS SMALL: the first attempt gave all eleven documents to one implementer and it hit its 80-turn cap three times without returning. Yours is four files. Budget your turns: read the merged diff ONCE with a single targeted command (git log --oneline 3509f76..HEAD and git diff --stat 3509f76..HEAD, then grep for the specific names you need), not file by file. Do not read the whole emitter. Read the pre-flight audits named in this manifest audits block only if you need a specific fact; their §7 MUSTs bind. Touch only your lane. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `README.md`
- `AGENTS.md`
- `CLAUDE.md`
- `TROUBLESHOOTING.md`

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

- every name the ten wave-1 and wave-2 jobs shipped: provision_command, provision_timeout_s, --provision-command, --provision-timeout-sec, preexisting.txt, verdict_disagreement, candidate_runs, MEMORY_LANE_UNNAMESPACED, SECOND_OPINION_SAME_FAMILY, claude-advisor, cross_model, usage.advisor_calls, /v:init Steps 1f and 4e, the memory-path sentence, the disclosure line — read them from HEAD, never from memory

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- README.md gains three lines (worktree provisioning, the advisor, the namespaced memory path), stays at or under 130 lines, and has no line over 200 characters outside code blocks and tables.
- AGENTS.md names the namespaced memory lane at the spec-reviewer bullet, says the model policy now includes an advisor, and names provision_command in the orchestrator surface.
- CLAUDE.md model-policy line names the advisor.
- TROUBLESHOOTING.md gains three entries: a worktree job BLOCKED with node_modules violations points at provision_command; Record reporting a verdict disagreement explains what the two values mean and that neither is a proven cause; a line in lane-guard-unresolved.jsonl explains the bootstrap suppression and what a record now means.
- lint-frontmatter green; every relative link resolves; no claim that is not true of HEAD.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
