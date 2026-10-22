# Task A — README.md rewritten for a five-minute read

Compound V run `2026-09-03-v3.4.7-readme-clarity`, job `readme`.

SHARED TIER SENTENCES (use these words in prose and in the diagram, so they cannot disagree): DIRECT — a trivial, unambiguous edit: one worker edits, tests the floor, commits; no model routing happens (it is an ordinary commit by whichever model is already in the session). SCOPED — a bounded change: only the tests that reference what changed run, not the whole suite; the Opus reviewer still gates done. SCOPED+ — a small edit on a sensitive path: SCOPED plus a mandatory deep review and a cross-model (Codex) second opinion, with the human accepting. FULL — anything real: recon, three pre-flights (code archaeology, domain expert, library check), plan, manifest, parallel dispatch in isolated worktrees, a three-pass review. MODELS — Opus plans, judges and reviews; Sonnet executes junior slices and the two scanning agents; Codex is an opt-in worker (kernel-sandboxed) and the second opinion; Antigravity and Cursor are opt-in lower-trust workers. BACKEND HONESTY (pre-flight 1A): Codex — dogfooded in this repository; Antigravity and Cursor — CLI invocation verified live, never dispatched here; opencode and Devin — experimental, adapters exist, execution unverified. Say exactly that. BASEREF FACTS (pre-flight 1C): `worktree.baseRef` is a NATIVE Claude Code project setting in .claude/settings.json (values: `fresh` or `head`, nothing else); `head` makes every worktree in the repo — interactive --worktree sessions and every isolation:worktree subagent — branch from the current HEAD instead of the default 'fresh' (which auto-refreshes from origin/HEAD daily). Compound V needs `head` so a job that depends on another gets a worktree that contains the previous wave (finding 60). Disclose that scope in one sentence wherever the setting is offered. Codex floor: ≥ 0.144.6 (not 0.143). Never copy CLI version pins (cursor-agent, agy) into README — they live in the adapter docs. Keep the Context7 install line exactly `/plugin install context7@claude-plugins-official`. THE ONE RULE (Oleg, 2026-09-03): documentation must be clear and simple. Plain words, short sentences, one idea per paragraph, every claim true of the code in HEAD; anything measured, historical or defensive is linked (AGENTS.md, CHANGELOG.md, TROUBLESHOOTING.md), never repeated. Rewrite README.md per Task A of docs/superpowers/plans/2026-09-03-v3.4.7-readme-clarity.md and the spec docs/superpowers/specs/2026-09-03-v3.4.7-readme-clarity-design.md. Verify each claim against HEAD (commands/, hooks/hooks.json, skills/backend-launcher/adapter-*.md, scripts/compound-v-preeval.py, .claude/settings.json) before you write it; delete what you cannot verify. Self-check with the acceptance criteria's commands before returning. Touch only README.md. Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind). Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not. Hard-wrap: no physical line over 200 characters outside code blocks and tables. The 130-line budget is tight (153 today): the measurement essay leaves (one link to AGENTS.md), the Academy block shrinks to two lines, 'Good to know' is four bullets. Read the dogfood index footer from HEAD after index-refresh merged, never from memory.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: index-refresh.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `README.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- README.md follows the plan's outline in order; ≤130 lines; no line >200 chars outside code/tables; no ## section >30 lines; the measurement essay is gone from README (it stays in AGENTS.md, linked); Requirements = floor + one-line lane-guard cost + the baseRef setting; Install has the exact baseRef JSON and Codex ≥ 0.143; the three tiers with the models; backends incl. opencode/Devin marked experimental; V-memory fresh by construction; co-change 'when the partition reviewer runs'; the 16-command table; the hook table matching hooks/hooks.json; the eight stages in one sentence each; the two numbers equal the footer in HEAD (index-refresh ran first); every claim verified against HEAD before writing; the dead-link replica in the spec exits 0; lint green. DIRECT is never assigned a model; the backend section uses the pre-flight's honesty wording; Codex ≥ 0.144.6; the baseRef line discloses it is a native project-wide setting (fresh|head); no CLI version pins.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
