# Task A — withRetry around every agent() call; reviewer lift; honest failure_class; CFG.retry

Compound V run `2026-09-03-v3.4.8-workflow-retry`, job `emitter-retry`.

BUDGET: scripts/compound-v-emit-workflow.py is 6,000+ lines and five implementers ran out of turns reading it. At most 20 tool calls of reading in total: `grep -n` for each named symbol first, then `sed -n` only the ranges you need; never Read the whole file; then edit; then run `--selftest` ONCE. Implement Task A of docs/superpowers/plans/2026-09-03-v3.4.8-workflow-retry.md (spec docs/superpowers/specs/2026-09-03-v3.4.8-workflow-retry-design.md). The spec's 'Decisions forced by pre-flight' section overrides the earlier text: the trigger is a NULL resolution; no Date/Math.random; setTimeout is confirmed to work (live probe). Symbols to grep: `async function gateStage`, the implement/record/finalize stage functions, `opts.model`, `CFG.` (how the JS config object is emitted), `def cmd_record`, `failure_class`. Touch only scripts/compound-v-emit-workflow.py. Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind). Tests first. Python 3.9 syntax. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not. Also grep `FORBIDDEN_PATTERNS`, `CLAUDE_ESCALATION`, `escalate_claude_model`, `isAgentTypeMissing`, `def cmd_gate_receipt`.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-emit-workflow.py`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- Per the plan's Task A as amended: withRetry triggers on null OR throw, deterministic backoff via setTimeout only, every stage's agent( wrapped, isAgentTypeMissing fallback composed inside, retries[] carried into the result, exhaustion ⇒ today's null path + failure_class other + the stated reason, reviewer lift via the emitted CLAUDE_ESCALATION map once with --escalated-from on gate-receipt and escalated_from on the result, CFG.retry from the manifest with defaults 3/true, selftests as listed, `--selftest` green, no forbidden pattern in the emitted script, Python 3.9.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
