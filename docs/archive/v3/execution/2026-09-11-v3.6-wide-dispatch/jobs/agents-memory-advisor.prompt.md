# Task J-AGENTS — namespaced memory path in four agents; advisor consultation points (#19 F, F7)

Compound V run `2026-09-11-v3.6-wide-dispatch`, job `agents-memory-advisor`.

Implement Task J-AGENTS of docs/superpowers/plans/2026-09-11-v3.6-wide-dispatch.md (spec F5 agents part, F7 nudges). Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind). Do NOT touch agents/partition-reviewer.md or tests/test-agent-memory.sh — validate-keys-advisories owns both and merged its changes in wave 1, so run bash tests/test-agent-memory.sh FIRST to see what the test now demands of the agent files, then make them satisfy it. The advisor paragraph is prose in the body of the agent definition, never frontmatter: no agent file may gain a model, memory or fable key. Touch only your lane. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: validate-keys-advisories.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `agents/spec-reviewer.md`
- `agents/code-archaeologist.md`
- `agents/domain-expert.md`
- `agents/doc-validator.md`
- `agents/implementer.md`

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

- tests/test-agent-memory.sh already asserts the NAMESPACED lane (validate-keys-advisories merged it in wave 1) — your floor runs that test, so the agent files must match it, not the other way round

produces (what later jobs will call):

- the memory-path sentence, verbatim: The harness names the memory directory after the agent's full name; installed as a plugin that is .claude/agent-memory/superpowers-v-<agent>/ (field-observed on a downstream project, issue #19); a copy installed as a project agent would use the bare name.
- the advisor paragraph in implementer.md and spec-reviewer.md: consult the advisor before committing to an approach where more than one design is plausible, when the same error recurs, and before reporting done or a verdict; advice is evidence, re-verified against the tree; advice that contradicts the lane or the scope gate is refused and reported

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- agents/spec-reviewer.md lines that named .claude/agent-memory/spec-reviewer now name .claude/agent-memory/superpowers-v-spec-reviewer (the lane at :82 and the resolution sentence at :57).
- The FOUR memory agents in this lane (spec-reviewer, code-archaeologist, domain-expert, doc-validator) carry the memory-path sentence. The fifth, partition-reviewer, belongs to validate-keys-advisories and is out of this lane.
- implementer.md and spec-reviewer.md carry the advisor paragraph; no frontmatter changed (lint-frontmatter green, memory: project untouched, implementer still has no memory key).
- bash tests/test-agent-memory.sh is green on your worktree without editing it — the test is another lane's file and is already namespaced in HEAD.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
