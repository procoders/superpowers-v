# Task J-VALIDATE — provision_command keys; MEMORY_LANE_UNNAMESPACED; claude-advisor receipts (#19 F, F1, F7)

Compound V run `2026-09-11-v3.6-wide-dispatch`, job `validate-keys-advisories`.

Implement Task J-VALIDATE of docs/superpowers/plans/2026-09-11-v3.6-wide-dispatch.md (spec F1 validator part, F5, F7 receipt part). Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind). THIS LANE OWNS tests/test-agent-memory.sh, examples/manifest.example.yaml and the validator TOGETHER, on purpose: that test reads the example and runs the validator, so flipping any one of the three alone turns the test red and blocks the job. Flip all three in one commit. Two traps the archaeology audit found and you must handle: (1) reviewer_backend in schemas/cross-model-receipt.schema.json is a JSON-Schema const, not an enum — widening it changes the validator's own error text, and there is an existing selftest assertion around scripts/compound-v-validate-manifest.py:5320 that pins that text; update the assertion rather than weakening the check. (2) tests/test-agent-memory.sh already asserts that the shipped example raises NO advisory (an empty warnings list) — your new advisory must not fire on the example you are also fixing. Tests first: write the selftest rows, run and see them fail, then implement. The five memory agents are spec-reviewer, partition-reviewer, code-archaeologist, domain-expert, doc-validator; the bare form is .claude/agent-memory/<bare>/…, the namespaced form is .claude/agent-memory/superpowers-v-<bare>/…. The memory-path sentence, verbatim, for agents/partition-reviewer.md: The harness names the memory directory after the agent's full name; installed as a plugin that is .claude/agent-memory/superpowers-v-<agent>/ (field-observed on a downstream project, issue #19); a copy installed as a project agent would use the bare name. Type and range checks only for the provisioning keys — no heuristic that guesses whether a floor needs provisioning. Touch only your lane. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-validate-manifest.py`
- `examples/manifest.example.yaml`
- `agents/partition-reviewer.md`
- `schemas/cross-model-receipt.schema.json`
- `tests/test-agent-memory.sh`

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

- manifest top-level keys provision_command (string, non-empty, no newline) and provision_timeout_s (int 1..1800, default 600 when absent)
- advisory code MEMORY_LANE_UNNAMESPACED whose text names the namespaced form .claude/agent-memory/superpowers-v-<agent>/**; MEMORY_ONLY_LANE recognises both the bare and the namespaced form
- schemas/cross-model-receipt.schema.json reviewer_backend accepts claude-advisor beside codex and gains a required boolean cross_model (true for codex, false for claude-advisor); the validator accepts it, refuses a receipt whose cross_model disagrees with its reviewer_backend, and prints WARN SECOND_OPINION_SAME_FAMILY on a false one
- tests/test-agent-memory.sh asserts the namespaced lane and the new advisory (this job owns the test because it is a fixture OVER the validator and the shipped example: the three files must flip together or the wave blocks itself)

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- Validator selftest rows pass: provision_command 3 is FAIL, "" is FAIL, provision_timeout_s 0 is FAIL, a valid pair is PASS; a review job lane .claude/agent-memory/spec-reviewer/** (also ./-prefixed and file forms) yields advisory MEMORY_LANE_UNNAMESPACED, the namespaced lane does not, MEMORY_ONLY_LANE fires for both forms; a receipt with reviewer_backend claude-advisor and cross_model false is accepted with the WARN, the same backend with cross_model true is REFUSED, and an unknown backend is refused.
- examples/manifest.example.yaml validates, carries provision_command "npm ci" with a comment (runs once per fresh worktree before the before-image; idempotent; must not modify tracked files) and the review lane .claude/agent-memory/superpowers-v-spec-reviewer/**.
- agents/partition-reviewer.md lists the two new WARN rows (MEMORY_LANE_UNNAMESPACED, SECOND_OPINION_SAME_FAMILY), carries the memory-path sentence (it is the fifth memory agent and no other lane may touch it), and its Step 4 stance text no longer says that under the balanced stance standard routes to opus — routing-policy.md has routed claude.standard to sonnet since 3.0.5.
- tests/test-agent-memory.sh uses MEM_GLOB=.claude/agent-memory/superpowers-v-spec-reviewer/** and a MEM_FILE under it, adds a row asserting the bare form raises MEMORY_LANE_UNNAMESPACED, and EVERY pre-existing row in the file still passes — including the shipped-example row that asserts an empty warnings list.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
