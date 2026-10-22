# The env offer says what the setting does; the implementer cap agrees with the docs; CHANGELOG and spec carry Codex round 4 and the eighth pass

Compound V run `2026-09-02-v3.4-native-first-r12`, job `records`.

You have a developer's shell; run Python with -B; register your lane with a LITERAL --cwd (run `pwd`
first; the clamp refuses "$PWD"). Do not add verification beyond the acceptance commands; run a listed
command at most once. The Codex findings are in docs/superpowers/reviews/2026-09-03-codex-round-4-gate-changes.json
(read it — every item below cites its evidence), the eighth pass is docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-8.md.

Items: eighth pass #1 and #5, and the records for this final cycle (CHANGELOG, spec amendment,
native-mechanisms row, audit). Match the length of written documents to what the task needs.
Report per item: file, change, command, exit code.

## Write-allowed (your lane — anything else is a scope violation)

- `commands/v-init.md`
- `agents/implementer.md`
- `CHANGELOG.md`
- `docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md`
- `docs/superpowers/architecture/native-mechanisms.md`
- `docs/superpowers/architecture/2026-09-02-viability-audit.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/reviews/2026-09-03-codex-round-4-gate-changes.json`
- `docs/superpowers/reviews/2026-09-03-codex-round-4-brief.md`
- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-8.md`

## Acceptance (your definition of done)

- Eighth pass #1: commands/v-init.md, CHANGELOG.md and the spec state CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT's semantics as the binary has them — "0" turns the SIMPLE (short) system prompt off, i.e. selects the long preset with the anti-verbosity rules; "1" selects the short one — and the offer recommends "0" for that reason, with the source note (community claim, binary-verified name, no measurement).
- Eighth pass #5: agents/implementer.md maxTurns is 80, matching execution-manifest.md's deep default.
- CHANGELOG 3.4.0 gains '### Cross-model round 4 (Codex, 2026-09-03)' listing the nine findings by severity and the run (r12) that closes them, and '### Changed — the merge applies a sealed per-job patch; the manifest is digest-bound'; the spec gains 'After the eighth review pass and Codex round 4 (2026-09-03)'; native-mechanisms.md's 'Доказательство, что изменилось' row notes the sealed artifact; the viability audit's §7 row 2 (ledger) and the review-loop note are current.
- /usr/bin/python3 -B scripts/lint-frontmatter.py . is clean; every intra-repo markdown link you add resolves.

Turn cap: 30 (default for tier light; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
