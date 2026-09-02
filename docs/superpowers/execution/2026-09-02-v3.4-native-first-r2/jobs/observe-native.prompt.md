# dashboard serve → /workflows; the scorecard reads results/*.json; update-memory removed

Compound V run `2026-09-02-v3.4-native-first-r2`, job `observe-native`.

Task C of docs/superpowers/plans/2026-09-02-v3.4-native-first.md — read the spec WS3a
and WS3b first, then execute C1–C4 exactly as written. You own only the files in
write_allowed. Run the emit-workflow selftest with /usr/bin/python3 (it needs PyYAML).

C1 scripts/compound-v-dashboard.py: delete _ReadOnlyHandler, _make_handler,
_build_server, cmd_serve, _FakeServer, _invoke_handler, the `serve` argparse branch, the
http.server/socketserver imports and every serve selftest; emit and resume unchanged
(`python3 scripts/compound-v-dashboard.py resume --execution-root
docs/superpowers/execution` still prints the resume line). commands/v-dashboard.md: the
serve paragraph and the description line → "a live run is watched natively: /workflows
(the progress tree Engine C populates through phase()/log()) and /tasks; emit is the
static snapshot of past runs." Also delete the dashboard's marathon/watch panel
(reads autonomy.watch / watcher_registry / resume_count, which job A removes from
epic-state.py) together with its selftest fixture (1A §2d).
C2 scripts/compound-v-scorecard.py: add --from-runs <execution-root> (default
docs/superpowers/execution) to --update: for every <run>/manifest.yaml job that has a
<run>/results/<id>.json, one record {run_id, type, backend, model, status, blocked,
rework_rounds} — model from the manifest job's `model` when present else its resolved
tier name; rework_rounds = number of results/attempts/<id>.*.json files. Legacy
task-outcomes.jsonl lines are still read and unioned (dedup key run_id+type+backend+
status). --query unchanged. Selftest with a sandbox run dir. Do NOT delete or edit
scripts/compound-v-update-memory.py — the 1A audit found its append_line is imported by
compound-v-triage-outcomes.py and compound-v-preferences.py; it stays as a library module
and only the PROSE that told agents to run it goes (C4).
C3 scripts/compound-v-emit-workflow.py cmd_finalize_wave: after a successful wave
commit, run `<python> <scripts>/compound-v-scorecard.py --update --from-runs
<execution-root>` best-effort (never fatal; stderr note on failure). One selftest: a
finalized wave leaves docs/superpowers/memory/worker-performance.jsonl refreshed.
C4 prose: agents/parallel-dispatcher.md post-run memory step, commands/v-collect.md,
skills/compound-v/routing-policy.md §Where the scorecard comes from,
skills/compound-v/memory.md: the scorecard is regenerated from run results; no
task-outcomes.jsonl append instruction remains; `grep -rn update-memory commands skills
agents` returns nothing. Do not touch README.md, CHANGELOG.md or SKILL.md.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-dashboard.py`
- `scripts/compound-v-scorecard.py`
- `scripts/compound-v-emit-workflow.py`
- `commands/v-dashboard.md`
- `commands/v-collect.md`
- `agents/parallel-dispatcher.md`
- `skills/compound-v/routing-policy.md`
- `skills/compound-v/memory.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md`
- `docs/superpowers/plans/2026-09-02-v3.4-native-first.md`
- `docs/superpowers/execution/2026-09-02-df27-full-pass/**`
- `schemas/job_result.schema.json`

## Acceptance (your definition of done)

- python3 scripts/compound-v-dashboard.py --selftest is green; the file has no http.server import and no serve subcommand; `resume` and `emit` still work.
- python3 scripts/compound-v-scorecard.py --update --from-runs docs/superpowers/execution regenerates docs/superpowers/memory/worker-performance.jsonl from manifest jobs × results/*.json, unioned with legacy task-outcomes.jsonl; --selftest covers a sandbox run dir.
- scripts/compound-v-update-memory.py is UNTOUCHED (it is imported by triage-outcomes.py and preferences.py); grep -rn update-memory commands skills agents returns nothing; /usr/bin/python3 scripts/compound-v-preferences.py --selftest and scripts/compound-v-triage-outcomes.py --selftest are green.
- /usr/bin/python3 scripts/compound-v-emit-workflow.py --selftest is green and cmd_finalize_wave runs the scorecard update best-effort after a successful wave commit.
- commands/v-dashboard.md and commands/v-collect.md, agents/parallel-dispatcher.md, skills/compound-v/routing-policy.md, skills/compound-v/memory.md describe the scorecard as regenerated from run results and name /workflows + /tasks for a live view.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
