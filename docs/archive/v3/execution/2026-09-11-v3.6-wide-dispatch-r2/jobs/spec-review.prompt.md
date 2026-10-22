# Review Gate — three passes against the spec and the nine acceptance criteria

Compound V run `2026-09-11-v3.6-wide-dispatch-r2`, job `spec-review`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it within a HARD BUDGET of 60 tool calls; FIRST action after Step 0: create docs/superpowers/dogfood/2026-09-11-v3.6-wide-dispatch-review.md with the section skeleton and fill it as you verify. Review the WHOLE 3.6.0 change against docs/superpowers/specs/2026-09-11-v3.6-wide-dispatch-design.md. It landed across two runs: waves 1 and 2 of 2026-09-11-v3.6-wide-dispatch (eight jobs, commits 7309b8f and 58087b5), one orchestrator fix for a crash that run found (91139e5), and the three documentation jobs of this run. Your baseline for the merged diff is 3509f76. The first run HALTED at its documentation wave — its implementer hit the 80-turn cap three times, the gate failed closed, and Record crashed on a latent unbound name; that is why the docs are three jobs here. Judge the release and this manifest's nine acceptance criteria — run each AC's commands on the merged tree and quote the output. Pay particular attention to: the scope gate was not relaxed (no new RUN_DIR_EXEMPT_BY_NAME entry; provisioning subtracted only through --preexisting); every behavioural change has a planted-failure selftest row; the disclosure line for the advisor-assisted second look is present verbatim wherever that rung is rendered; no document still names the bare memory path. Your memory directory for this run is .claude/agent-memory/superpowers-v-spec-reviewer/ — it is inside your lane; the bare path is not. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: docs-core, docs-skills, docs-backend.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-11-v3.6-wide-dispatch-review.md`
- `.claude/agent-memory/superpowers-v-spec-reviewer/**`

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

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review file exists with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict; every acceptance criterion AC-1..AC-9 is run on the merged tree with the command and its output quoted (AC-2 by writing a temporary manifest in a temporary repo; AC-3 by a temporary repo that gitignores docs/); the verdict is APPROVED or ISSUES with a numbered list. A learning worth keeping is written under .claude/agent-memory/superpowers-v-spec-reviewer/ and nowhere else.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
