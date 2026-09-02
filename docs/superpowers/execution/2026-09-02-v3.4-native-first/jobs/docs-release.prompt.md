# README, SKILL.md, native-mechanisms, audit, CHANGELOG 3.4.0, version bump

Compound V run `2026-09-02-v3.4-native-first`, job `docs-release`.

Task D of docs/superpowers/plans/2026-09-02-v3.4-native-first.md — runs after A, B and C
have merged, in the main checkout. Read the spec, then `git log --stat -3` and the
three merged jobs' changes, so what you document is what landed, not what was planned.
Execute D1–D5 exactly as written; you own only the files in write_allowed.
D1 README: Marathon / Auto-Resurrection / Headless bullets → one "Epic autonomy" bullet
naming /goal, /loop, /schedule and the honesty boundary (a /loop shares the session's
fate; /schedule is the machine-off path with its own auth); /v:dashboard row → emit only
+ native /workflows; the triage paragraph: the UserPromptSubmit hook now scores the first
change request of a session and writes the record (committed at bind).
D2 SKILL.md: Stage −1 — the record's producers are the hook and /v:triage; directory
conventions — worker-performance.jsonl is derived from execution/*/results,
task-outcomes.jsonl is legacy input.
D3 native-mechanisms.md: rows "Продолжение по цели", "Авто-воскрешение эпика", "Триаж
на приходе запроса" (⚠ → ✅ with the reason), event table PostToolUseFailure ❌ (removed
3.4.0); recompute the summary counts from the table; audit §7 rows 1, 2, 3, 4, 8, 10 →
done in 3.4.0 (row 5 stays open by decision; 6, 7, 9 stay open).
D4 CHANGELOG [3.4.0] — 2026-09-02 entry in the file's style (what changed, what was
found live, what was removed and why); bump "version" to 3.4.0 in
.claude-plugin/plugin.json and .claude-plugin/marketplace.json.
D5 /usr/bin/python3 scripts/lint-frontmatter.py . must be clean; every intra-repo
markdown link you add must resolve.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: epic-native, triage-hook, observe-native.

## Write-allowed (your lane — anything else is a scope violation)

- `README.md`
- `CHANGELOG.md`
- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`
- `skills/compound-v/SKILL.md`
- `docs/superpowers/architecture/native-mechanisms.md`
- `docs/superpowers/architecture/2026-09-02-viability-audit.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md`
- `docs/superpowers/plans/2026-09-02-v3.4-native-first.md`
- `commands/**`
- `hooks/**`
- `skills/**`

## Acceptance (your definition of done)

- README has one Epic-autonomy bullet naming /goal, /loop, /schedule and no Marathon/Auto-Resurrection/Headless tier text; the /v:dashboard row says emit only; the triage paragraph says the UserPromptSubmit hook scores the first change request of a session.
- SKILL.md Stage −1 names the hook and /v:triage as the record's producers; the directory conventions say worker-performance.jsonl is derived from execution/*/results.
- native-mechanisms.md rows for the goal, resurrection and triage are updated, PostToolUseFailure is ❌ removed 3.4.0, and the summary counts are recomputed from the table; the audit's §7 rows 1, 2, 3, 4, 8, 10 are marked done.
- CHANGELOG has a [3.4.0] entry and both plugin manifests say 3.4.0; python3 scripts/lint-frontmatter.py . is clean (use /usr/bin/python3).

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
