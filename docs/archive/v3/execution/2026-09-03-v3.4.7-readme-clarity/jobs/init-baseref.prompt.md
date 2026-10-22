# Task C — /v:init offers the baseRef setting; TROUBLESHOOTING entry

Compound V run `2026-09-03-v3.4.7-readme-clarity`, job `init-baseref`.

BASEREF FACTS (pre-flight 1C): `worktree.baseRef` is a NATIVE Claude Code project setting in .claude/settings.json (values: `fresh` or `head`, nothing else); `head` makes every worktree in the repo — interactive --worktree sessions and every isolation:worktree subagent — branch from the current HEAD instead of the default 'fresh' (which auto-refreshes from origin/HEAD daily). Compound V needs `head` so a job that depends on another gets a worktree that contains the previous wave (finding 60). Disclose that scope in one sentence wherever the setting is offered. Codex floor: ≥ 0.144.6 (not 0.143). Never copy CLI version pins (cursor-agent, agy) into README — they live in the adapter docs. Keep the Context7 install line exactly `/plugin install context7@claude-plugins-official`. THE ONE RULE (Oleg, 2026-09-03): documentation must be clear and simple. Plain words, short sentences, one idea per paragraph, every claim true of the code in HEAD; anything measured, historical or defensive is linked (AGENTS.md, CHANGELOG.md, TROUBLESHOOTING.md), never repeated. Implement Task C of docs/superpowers/plans/2026-09-03-v3.4.7-readme-clarity.md. Match the surrounding style of commands/v-init.md (its Step 4c is the model: offer, exact JSONC, why, never write silently). Touch only commands/v-init.md and TROUBLESHOOTING.md. Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind). Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not. The offer must say the file is .claude/settings.json (NOT .claude/compound-v.json), merge-preserve every unrelated key a real project's settings.json carries (permissions, hooks, env), and disclose the project-wide scope. While in commands/v-init.md, fix the stale sentence at ~lines 605-607 about an 'armed epic goal rule' in hooks/epic-goal-stop.sh — that rule was removed in 3.4.0; the hook has two gates (triage_gate, pipeline_bypass) per its own header. For TROUBLESHOOTING.md, verify the CURRENT no-baseRef failure mode in scripts/compound-v-emit-workflow.py (`_worktree_base_is_head` and the agent_isolation decision, finding 60/89) and write the symptom you can prove (e.g. the dependent job's worktree lacks the previous wave and its patch is refused at integration), not a guess.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `commands/v-init.md`
- `TROUBLESHOOTING.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- commands/v-init.md has a new step, in the command's existing offer-never-write style (see its Step 4c for the shape), that OFFERS to merge {"worktree": {"baseRef": "head"}} into the project's .claude/settings.json (create the file if absent, merge if present, never overwrite other keys, never without a yes) with one sentence why (a job that depends on another needs its worktree branched from HEAD, not the default ref, or its patch never integrates — finding 60); TROUBLESHOOTING.md has an entry 'A job with depends_on never merges / its worktree lacks the previous wave' pointing at the setting and the offer; lint-frontmatter green. The offer names .claude/settings.json, preserves unrelated keys, discloses the project-wide scope and the two legal values; the stale 'armed epic goal rule' sentence is gone; the TROUBLESHOOTING symptom is the one the emitter's code produces.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
