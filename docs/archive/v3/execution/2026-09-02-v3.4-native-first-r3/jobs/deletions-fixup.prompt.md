# The three deletions jobs A and B were denied by the clamp, plus one wrong sentence

Compound V run `2026-09-02-v3.4-native-first-r3`, job `deletions-fixup`.

Run 2026-09-02-v3.4-native-first-r2 merged jobs A, B and C, but their implementers' shell
was clamped to three command forms, so three `git rm` deletions never happened. You have a
developer's shell now. Do exactly this, in your worktree:

1. `git rm scripts/compound-v-epic-watch.py scripts/compound-v-headless-shim.py hooks/tool-failure-ledger.sh`
   (all three still exist; the manifests and hooks.json already stopped referencing them).
2. `grep -nE 'epic-watch|headless-shim|tool-failure-ledger' .github/workflows/validate.yml CONVENTIONS.md tests/test-native-points.sh`
   — remove any remaining live reference (a CI step, a citation, a test section that runs the
   ledger). A purely historical mention inside a comment may stay. Re-verify CONVENTIONS.md's
   cited validate.yml line range matches the file after the deletions.
3. skills/compound-v/phase-preeval.md: the "Reliability" bullet says an uncommitted record is
   "invisible to --require-triage and to the Stop-time gate". Correct it: hooks/epic-goal-stop.sh
   reads the pre-eval records off disk (jq over docs/superpowers/pre-eval/*.json), so an
   uncommitted record DOES cover its declared paths for the Stop-time gate; what needs the
   commit is --require-triage's durability across `git worktree remove` and any other clone.
4. Verify: `bash tests/test-native-points.sh` exits 0; `python3 -m json.tool hooks/hooks.json`
   parses (read-only check). Report exactly which files you deleted and which lines you changed.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-epic-watch.py`
- `scripts/compound-v-headless-shim.py`
- `hooks/tool-failure-ledger.sh`
- `tests/test-native-points.sh`
- `skills/compound-v/phase-preeval.md`
- `.github/workflows/validate.yml`
- `CONVENTIONS.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md`
- `docs/superpowers/plans/2026-09-02-v3.4-native-first.md`
- `hooks/epic-goal-stop.sh`
- `hooks/hooks.json`

## Acceptance (your definition of done)

- scripts/compound-v-epic-watch.py, scripts/compound-v-headless-shim.py and hooks/tool-failure-ledger.sh no longer exist (git rm).
- grep -rnE 'epic-watch|headless-shim|tool-failure-ledger' .github/workflows/validate.yml CONVENTIONS.md tests/test-native-points.sh returns nothing except a historical mention in a comment, and bash tests/test-native-points.sh exits 0.
- skills/compound-v/phase-preeval.md no longer claims an uncommitted record is invisible to the Stop-time gate: the gate reads records off disk; only --require-triage and `git worktree remove` care about the commit.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
