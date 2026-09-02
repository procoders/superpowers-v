# Epic goal and resurrection go native: /goal, /loop, /schedule replace Feature A and the schedulers

Compound V run `2026-09-02-v3.4-native-first`, job `epic-native`.

Task A of docs/superpowers/plans/2026-09-02-v3.4-native-first.md — read the spec
(docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md) WS1 first, then execute
A1–A7 exactly as written. You own only the files in write_allowed.

A1 hooks/epic-goal-stop.sh: delete `_goal_rule`, `_discover_state`, `_locate_cli` and the
`_goal_rule` call in `hook_main`; the order becomes `_triage_rule` → `_enforcement_rule`.
Rewrite the header: Feature A paragraphs, decision-table rows about the goal, INVARIANT 2
become one line saying the goal rule was removed in 3.4.0 because the native /goal covers it.
Keep both fail-open mechanisms, `_bounded_capture`, the markers and the store. shellcheck
-S warning must stay clean.
A2 tests/test-epic-goal-stop.sh: delete the `arm`/`slot_dir`/`statefile` helpers, the
`--goal-status` fixture guard, and every goal check (armed/unmet, counter, re-arm, two
projects, goal met, terminal-not-met, store loss, discovery, the two "GOAL rule outranks"
precedence checks). Keep enforcement, triage-gate, bounded-check, shadow, registration and
mechanism (a)/(b) sections. `bash tests/test-epic-goal-stop.sh` must exit 0.
A3 scripts/compound-v-epic-state.py: remove the goal surface (--arm-goal, --disarm-goal,
--goal-status, --replace-arm, --condition, --max-continues, the goal_arm record) and the
watch surface (--watch, --max-resume-count, --reset-resume-count, --record-watcher-armed,
--record-watcher-disarmed, --list-watchers, --liveness, --claim-resume, --renew-lease,
--stale-after-min, --provider, --task-id, watcher_registry, resume_count, lease) with
their selftests and docstring paragraphs. `--init --stance marathon`, the marathon loop,
arbiter, breakers and --stats stay byte-identical. --selftest green.
A4 git rm scripts/compound-v-epic-watch.py scripts/compound-v-headless-shim.py; delete
their two selftest steps in .github/workflows/validate.yml and reword "quartet" to "pair";
drop "epic-watch / headless-shim" from CONVENTIONS.md line 17.
A5 commands/v-epic.md: replace §0c with "Resurrection" and §0d with "Goal" per spec WS1
"Replace": offer, never silent; `/loop 30m /v:epic <epic-id>` (this session; the model may
invoke the `loop` skill only after the user says yes) or a `/schedule` routine (cloud,
machine-off); ProposeGoal with ask_user: true and the verbatim condition shape
"epic `<epic-id>`: `python3 scripts/compound-v-epic-state.py --stats --state <path>`
reports every feature `done` or the epic terminal", else print it as a `/goal` line;
when the epic is terminal print "epic terminal — stop the loop" and stop it
(ScheduleWakeup stop in dynamic mode; CronDelete on the /loop entry CronList shows).
Remove every --claim-resume/--renew-lease/--record-watcher-*/--list-watchers/--liveness/
--arm-goal instruction. Steps 1–7 and the marathon loop text otherwise unchanged.
A6 skills/compound-v/epic-mode.md: delete the "Auto-resurrection watch" and "Armed goal
condition" sections; add "Goal and resurrection are native (3.4.0)" with the honesty
boundary from the spec. commands/v-init.md: delete Step 1d-ter; replace 3c's
`epic.autonomy.watch` bullet with two sentences on /loop and /schedule; drop `watch` from
the 4a template. commands/v-onboard.md: delete the headless-shim paragraph.
commands/v-status.md: drop the --goal-status mentions. docs/superpowers/loops.md: rows
03/04 name /loop and /schedule.
A7 verify with the acceptance greps and commands, then stop. Do not touch README.md,
CHANGELOG.md or SKILL.md — another job owns them.

## Write-allowed (your lane — anything else is a scope violation)

- `hooks/epic-goal-stop.sh`
- `tests/test-epic-goal-stop.sh`
- `scripts/compound-v-epic-state.py`
- `scripts/compound-v-epic-watch.py`
- `scripts/compound-v-headless-shim.py`
- `commands/v-epic.md`
- `commands/v-init.md`
- `commands/v-onboard.md`
- `commands/v-status.md`
- `skills/compound-v/epic-mode.md`
- `docs/superpowers/loops.md`
- `.github/workflows/validate.yml`
- `CONVENTIONS.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md`
- `docs/superpowers/plans/2026-09-02-v3.4-native-first.md`
- `docs/superpowers/architecture/native-mechanisms.md`
- `README.md`

## Acceptance (your definition of done)

- bash tests/test-epic-goal-stop.sh exits 0 and the file contains no goal-arm helper or goal check.
- python3 scripts/compound-v-epic-state.py --selftest is green and --help mentions no goal, watch, lease or resume-count flag.
- scripts/compound-v-epic-watch.py and scripts/compound-v-headless-shim.py no longer exist; validate.yml has no step for them.
- commands/v-epic.md §0c offers /loop or /schedule and §0d offers ProposeGoal or a /goal line, never arming silently; termination stops the loop.
- grep -rnE 'epic-watch|headless-shim|goal_arm|--goal-status|--arm-goal|autonomy\.watch|record-watcher' over the files in write_allowed returns nothing.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
