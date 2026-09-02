# Close the Review Gate's ISSUES 1–8 from docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review.md

Compound V run `2026-09-02-v3.4-native-first-r5`, job `review-fixes`.

Read docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review.md — its section "What to fix
before DONE" lists eight items with file:line evidence. Close every one of them in your worktree,
then run the commands the acceptance criteria name. You have a developer's shell (tests,
selftests, shellcheck, git rm are admitted); use /usr/bin/python3 for scripts that need PyYAML.

ISSUE 1  commands/v-status.md:109,118 — delete the --serve heading fragment and bullet; point at
         /workflows and /tasks as commands/v-dashboard.md:19 already does.
ISSUE 2  scripts/compound-v-preeval.py — give run_preeval a real `binding=None` parameter threaded
         to its build_record call; delete the globals()["build_record"] patch in triage_request;
         keep byte-identical records for every existing caller when binding is absent (the
         selftest must show it). Keep the triage subcommand's JSON shape.
ISSUE 3  scripts/compound-v-scorecard.py:228-230 — rework_rounds = number of
         results/attempts/<id>.*.json files for that job (0 when the directory is absent); add a
         selftest with one job that has two attempt files.
ISSUE 4  RESOLVED BY SPEC AMENDMENT: the once-per-session marker STAYS (see the spec WS2, amended
         2026-09-02: the record answers "already sized", the marker answers "already tried"). Make
         hooks/triage-prompt-nudge.sh's header, skills/compound-v/phase-preeval.md and any test
         text agree with that rationale; do not remove the marker.
ISSUE 5  hooks/triage-prompt-nudge.sh:57-58 and :502 (the emitted message) — the Stop-time gate
         reads pre-eval records OFF DISK (hooks/epic-goal-stop.sh runs jq over
         docs/superpowers/pre-eval/*.json), so an uncommitted record DOES cover its declared
         paths. What the commit buys is durability: --require-triage on another clone, and
         survival of `git worktree remove`. Say exactly that, matching phase-preeval.md:14.
ISSUE 6  docs/superpowers/architecture/2026-09-02-viability-audit.md:116,124 — §7 row 4 is
         done-with-scope-change (attended DIRECT = ordinary commit; Phase L kept for unattended
         landings), not cut. Fix the row and the recommendation line.
ISSUE 7  docs/superpowers/architecture/native-mechanisms.md:176,183-193 — the `Stop` event row
         should no longer say `цель` (the goal rule is gone); the paragraph "Почему именно эти две
         добавлены" now justifies ONE remaining addition (PreCompact) since PostToolUseFailure was
         removed in 3.4.0 — rewrite it accordingly.
ISSUE 8  scripts/compound-v-emit-workflow.py:~2620 — `tests.scope` in the recorded block must be
         the scope the resolver actually selected for the tier (full | impacted | floor_only), not
         "impacted whenever impacted_map is non-empty"; keep the mirror comment about
         compound-v-fastpath-run.py:default_scope_for in sync, and add a selftest for a job whose
         tier resolved to `full` while the contract has an impacted_map.

Report per issue: file, what changed, the command you ran and its exit code.

## Write-allowed (your lane — anything else is a scope violation)

- `commands/v-status.md`
- `scripts/compound-v-preeval.py`
- `scripts/compound-v-scorecard.py`
- `hooks/triage-prompt-nudge.sh`
- `tests/test-native-points.sh`
- `scripts/compound-v-emit-workflow.py`
- `docs/superpowers/architecture/2026-09-02-viability-audit.md`
- `docs/superpowers/architecture/native-mechanisms.md`
- `skills/compound-v/phase-preeval.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review.md`
- `docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md`
- `hooks/epic-goal-stop.sh`
- `commands/v-triage.md`

## Acceptance (your definition of done)

- commands/v-status.md mentions no --serve and no dashboard serve subcommand.
- run_preeval(..., binding=None) exists and is threaded to build_record; no globals()['build_record'] patch remains; /usr/bin/python3 scripts/compound-v-preeval.py --selftest passes and the triage subcommand's JSON still carries session_id/base_commit/declared_paths.
- scripts/compound-v-scorecard.py --from-runs counts results/attempts/<id>.*.json into rework_rounds, with a selftest.
- hooks/triage-prompt-nudge.sh's header and emitted message no longer claim an uncommitted record is invisible to the Stop-time gate; they say the gate reads records off disk and that the commit is for durability (--require-triage on another clone, git worktree remove). The once-per-session marker stays, with the spec's rationale (amended 2026-09-02). bash tests/test-native-points.sh exits 0.
- docs/superpowers/architecture/2026-09-02-viability-audit.md §7 row 4 reads done-with-scope-change (Phase L kept for unattended landings), not cut; native-mechanisms.md's Stop row no longer mentions the goal and the 'why these two' paragraph justifies the one hook event that remains after PostToolUseFailure's removal.
- scripts/compound-v-emit-workflow.py's tests block resolves `scope` against the tier's resolution (full | impacted | floor_only as the resolver actually selected), not only against impacted_map presence; /usr/bin/python3 scripts/compound-v-emit-workflow.py --selftest passes.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
