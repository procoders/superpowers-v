# Task B' — /v:status --live resolves and degrades (issue 5), /v:dispatch's watch advice as its own step (issue 8), CHANGELOG note

Compound V run `2026-09-03-v3.4.2-transcript-watch-r2`, job `docs-wiring`.

Read docs/superpowers/dogfood/2026-09-03-v3.4.2-transcript-watch-review-1.md issues 5 and 8 and the archaeology audit §7.7/§7.8 (docs/superpowers/archaeology/2026-09-03-v3-4-2-transcript-watch.md). Fix them inside your lane. Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `commands/v-status.md`
- `commands/v-dispatch.md`
- `CHANGELOG.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- commands/v-status.md step 1 strips a leading `--live` from the argument and the --live section carries the file's standard degrade line (no watcher script ⇒ say so, never a traceback); commands/v-dispatch.md presents the background watch as its own numbered step (or records, in one sentence, why archaeology §7.7 was overruled).
- CHANGELOG.md's 3.4.2 section gains one short paragraph naming review-1's detector fixes (no fabricated metrics); /usr/bin/python3 -B scripts/lint-frontmatter.py . is green.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
