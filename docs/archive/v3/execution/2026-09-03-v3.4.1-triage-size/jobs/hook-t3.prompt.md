# Task D — the hook finishes T3: a headless one-shot classify (Claude light, then Codex), never a reminder on needs_t3

Compound V run `2026-09-03-v3.4.1-triage-size`, job `hook-t3`.

Implement plan Task D against spec §WS-D and pre-flight amendments 1 and 7 (classify cap 15 s + 3 s grace; hooks/hooks.json UserPromptSubmit timeout 25; the selftest pins the argv). Tests first: the hook test plants a fake `claude` (and a fake `codex`) on PATH via CV_CLASSIFY_CLAUDE_BIN / CV_CLASSIFY_CODEX_BIN and drives the hook with synthetic UserPromptSubmit stdin. GNU timeout does not exist on macOS: every external process runs under scripts/compound-v-run-with-timeout.py. `claude -p --bare` loses the login — never use --bare. Never Haiku. The hook must stay fail-open and within its budget: a hanging classify ends in the reminder, exit 0. Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `hooks/triage-prompt-nudge.sh`
- `hooks/hooks.json`
- `scripts/compound-v-classify-request.py`
- `tests/test-native-points.sh`
- `commands/v-triage.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- bash tests/test-native-points.sh is green and carries the four cases of plan Task D Step 1 (grep for "classify-headless" and "--bare"); shellcheck hooks/triage-prompt-nudge.sh is clean; /usr/bin/python3 -B scripts/compound-v-classify-request.py --selftest is green.
- compound-v-classify-request.py --classify-headless exists, never passes --bare, resolves the Claude light model through compound-v-resolve-model.py (never Haiku), runs under compound-v-run-with-timeout.py with stdin closed, and falls back to the codex route then to unknown.
- The hook's needs_t3 branch re-invokes the triage subcommand with --t3-category and no longer emits the reminder except on engine failure; the SCOPED+ tier line exists; commands/v-triage.md documents the headless route as the default.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
