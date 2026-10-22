# Task J-DOCS — documentation of what landed (F8)

Compound V run `2026-09-11-v3.6-wide-dispatch`, job `docs-landed`.

Implement Task J-DOCS of docs/superpowers/plans/2026-09-11-v3.6-wide-dispatch.md (spec F8). THE ONE RULE (Oleg, 2026-09-03): documentation must be clear and simple. Plain words, short sentences, one idea per paragraph, every claim true of the code in HEAD; anything measured, historical or defensive is linked (AGENTS.md, CHANGELOG.md, TROUBLESHOOTING.md), never repeated. Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind), then the merged diff of this run (git log -p from the run baseline in state.json to HEAD) before writing a word. Verify every flag, key and step number against the merged code. Touch only your lane. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: scope-workers-provision, validate-keys-advisories, laneguard-unresolved, agents-memory-advisor, vinit-skilldoctor-advisor, second-opinion-ladder, usage-advisor-calls, emitter-19.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `README.md`
- `AGENTS.md`
- `TROUBLESHOOTING.md`
- `CLAUDE.md`
- `skills/compound-v/execution-manifest.md`
- `skills/compound-v/SKILL.md`
- `skills/compound-v/routing-policy.md`
- `commands/v-orchestrate.md`
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

- every name produced by the wave-1 and wave-2 jobs: provision_command, provision_timeout_s, --provision-command, --provision-timeout-sec, verdict_disagreement, candidate_runs, MEMORY_LANE_UNNAMESPACED, SECOND_OPINION_SAME_FAMILY, claude-advisor, usage.advisor_calls, Steps 1f/4e, the memory-path sentence, the disclosure line — read them from HEAD (git log -p since the run baseline), never from memory

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- README.md: three lines (provisioning, advisor, memory path), still ≤ 130 lines, no line over 200 chars outside code/tables. AGENTS.md: memory path at the spec-reviewer bullet, model policy names the advisor, orchestrator surface names provision_command. CLAUDE.md model-policy line names the advisor. routing-policy.md has an advisor section (Fable 5.1 where available, else Opus; subagents inherit; frontmatter never names Fable; the Sonnet carve-out unchanged). execution-manifest.md documents provision_command and provision_timeout_s (idempotent; must not modify tracked files) and the namespaced memory lane. SKILL.md and v-orchestrate.md name the namespaced lane. backend-launcher SKILL.md and adapter-codex.md document the two worker flags. TROUBLESHOOTING.md has three entries: BLOCKED with node_modules violations → provision_command; Record reports a verdict disagreement; what a line in lane-guard-unresolved.jsonl now means. native-mechanisms.md has two rows (advisor; skill-doctor). lint-frontmatter, rules-lint and the CI dead-link rule green; no committed document names the bare .claude/agent-memory/spec-reviewer/** except as a named counter-example.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
