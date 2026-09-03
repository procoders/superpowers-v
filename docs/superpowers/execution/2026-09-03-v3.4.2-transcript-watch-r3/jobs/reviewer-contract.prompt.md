# Task B'' — agents/spec-reviewer.md §3.3: the FULL row follows the derived-default rule (review-2 issue 3)

Compound V run `2026-09-03-v3.4.2-transcript-watch-r3`, job `reviewer-contract`.

Read review-2 issue 3 and skills/compound-v/execution-manifest.md 'The derived default' (the maintainer's 2026-09-02 rule: running the whole project is a decision, not a default). Rewrite the FULL row of §3.3 and its surrounding sentence so the reviewer contract agrees with the resolver; change nothing else. Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `agents/spec-reviewer.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- agents/spec-reviewer.md §3.3's FULL row says what skills/compound-v/execution-manifest.md's derived-default table says: a declared impacted_map is honoured at every tier (impacted ∪ previously-failing ∪ newly-added, plus full_command for an unmapped path at FULL), and the reviewer checks the tier's obligation against resolved_commands; /usr/bin/python3 -B scripts/lint-frontmatter.py . is green.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
