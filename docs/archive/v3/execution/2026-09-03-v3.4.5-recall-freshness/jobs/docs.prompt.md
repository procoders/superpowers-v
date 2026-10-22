# Task B — memory.md, v-remember.md, CHANGELOG

Compound V run `2026-09-03-v3.4.5-recall-freshness`, job `docs`.

Implement Task B of docs/superpowers/plans/2026-09-03-v3.4.5-recall-freshness.md; the spec is docs/superpowers/specs/2026-09-03-v3.4.5-recall-freshness-design.md. Describe the engine behaviour as the spec defines it (Task A implements it in parallel — do not wait for it, do not read its worktree). Touch only the three files in your lane. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `skills/compound-v/memory.md`
- `commands/v-remember.md`
- `CHANGELOG.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- memory.md CLI row for search carries --no-refresh and the sentence that the FTS5 lane is fresh by construction at every search while the dense lane refreshes only on /v:memory-refresh --with-embeddings; v-remember.md no longer says to run /v:memory-refresh before a search and says a first search builds the index; CHANGELOG [Unreleased] has the finding-98 entry with the 118-files-behind observation, the 0.38 s measurement and the opt-out; lint-frontmatter green. memory.md also states the documented side effect: with embeddings on and bootstrapped, a search-triggered refresh re-chunks a changed file WITHOUT vectors until the next /v:memory-refresh --with-embeddings (dense degrades to FTS5 for that file, never breaks).

Turn cap: 30 (default for tier light; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
