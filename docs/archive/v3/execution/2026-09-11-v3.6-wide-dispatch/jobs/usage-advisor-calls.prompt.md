# Task J-USAGE — usage.advisor_calls measured from transcripts (F7)

Compound V run `2026-09-11-v3.6-wide-dispatch`, job `usage-advisor-calls`.

Implement Task J-USAGE of docs/superpowers/plans/2026-09-11-v3.6-wide-dispatch.md (spec F7 measured usage). Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind; the library audit confirms the block names the API uses). Tests first. Keep _INVARIANT_KEYS semantics unchanged (the advisor count is not a token invariant). A live transcript shape is available at ~/.claude/projects/-private-tmp-claude-501--Users-oleg-Dev-superpowers-v-e619cb38-ebe3-4b45-a1f4-c3007616291d-scratchpad-advprobe/*/subagents/*.jsonl if you want to see real blocks; do not copy it into the repo — build a minimal fixture. Touch only your lane. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-usage-extract.py`
- `scripts/compound-v-usage-aggregate.py`
- `schemas/job_result.schema.json`
- `commands/v-status.md`
- `tests/test-usage-workflow.sh`

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

produces (what later jobs will call):

- usage.advisor_calls: integer or null — the count of assistant content blocks {type: server_tool_use, name: advisor} for the job, deduplicated by message id exactly like the token counts; null when the job was not measured
- compound-v-usage-aggregate.py renders adv=N after the token fields when N > 0

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- tests/test-usage-workflow.sh rows pass: a planted transcript with two assistant messages carrying {"type":"server_tool_use","name":"advisor","input":{}} plus one advisor_tool_result and one duplicated message id yields advisor_calls 2; a transcript without yields 0; an unmeasured job yields null; the aggregate line shows adv=2. schemas/job_result.schema.json usage gains advisor_calls (integer|null) with a description; bash tests/test-engine-c-contract.sh green; both usage scripts selftest green; commands/v-status.md says in one sentence that adv=N is the measured advisor-call count.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
