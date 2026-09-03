# Task B (claude) — the reviewer note, CHANGELOG 3.4.3, versions

Compound V run `2026-09-03-v3.4.3-codex-sandbox-checkout-r2`, job `docs-note`.

Implement plan Task B. You will not see Task A's script (it runs in parallel on the codex backend); describe the CLI exactly as the spec fixes it (§Decisions 1). Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `agents/spec-reviewer.md`
- `CHANGELOG.md`
- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- agents/spec-reviewer.md §3.3 evidence notes carry one sentence naming scripts/compound-v-sandbox-checkout.sh <dest> --empty-pre-eval for probing hooks/triage-prompt-nudge.sh (the UserPromptSubmit hook — the Stop hook needs .claude/compound-v.json, which a sandbox never has) on a checkout with a live run; CHANGELOG top heading is ## [3.4.3] - 2026-09-03 with one Added section that says the helper was built by a Codex worker on Engine C (no fabricated metrics); plugin.json and marketplace.json say 3.4.3; /usr/bin/python3 -B scripts/lint-frontmatter.py . is green.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
