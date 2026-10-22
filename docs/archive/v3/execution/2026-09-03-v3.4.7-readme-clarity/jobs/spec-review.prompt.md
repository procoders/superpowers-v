# Review Gate — three passes against the spec and the feature acceptance criteria

Compound V run `2026-09-03-v3.4.7-readme-clarity`, job `spec-review`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it within a HARD BUDGET of 50 tool calls; FIRST action after Step 0: create docs/superpowers/dogfood/2026-09-03-v3.4.7-readme-clarity-review.md with the section skeleton and fill it as you verify. THE ONE RULE (Oleg, 2026-09-03): documentation must be clear and simple. Plain words, short sentences, one idea per paragraph, every claim true of the code in HEAD; anything measured, historical or defensive is linked (AGENTS.md, CHANGELOG.md, TROUBLESHOOTING.md), never repeated. Review the four jobs against docs/superpowers/specs/2026-09-03-v3.4.7-readme-clarity-design.md and this manifest's five acceptance criteria — run each AC's commands (the dead-link replica: for every markdown link in README.md, after dropping fenced blocks and inline code spans, the target must exist relative to the file's directory). Perform the reader test yourself and quote what you wrote down. Judge clarity as a newcomer would: if a sentence needs the CHANGELOG to be understood, it is an ISSUE. Run python with -B; register your lane with a literal --cwd. Pre-flight 1A/1C MUSTs to verify explicitly: DIRECT has no model in prose or SVG; backend honesty wording; Codex ≥ 0.144.6; baseRef disclosed as native/project-wide with values fresh|head; no CLI pins in README; the essay exists once (AGENTS.md); the SVG title/desc rewritten; v-init.md's stale 'armed epic goal rule' sentence gone.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: index-refresh, readme, routing-svg, init-baseref.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.7-readme-clarity-review.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review file exists with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict; every acceptance criterion is run on the merged tree with the command and output; the reader test is performed and quoted; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
