# The UserPromptSubmit hook runs the scorer; attended DIRECT is an ordinary commit; the failure ledger is removed

Compound V run `2026-09-02-v3.4-native-first-r2`, job `triage-hook`.

Task B of docs/superpowers/plans/2026-09-02-v3.4-native-first.md — read the spec WS2,
WS3c and WS4 first, then execute B1–B7 exactly as written. You own only the files in
write_allowed.

B1 scripts/compound-v-preeval.py: add a `triage` subcommand implementing today's
commands/v-triage.md T2 block: --request-file F | --request-env VAR, --repo, --session-id,
--t3-category, --json. It binds session_id/base_commit/declared_paths through
build_record's kwarg exactly as T2 does, runs run_preeval, evaluates predicates 1–6, and
prints the human report or, with --json, {pre_eval_id, tier, decision, needs_t3,
t3_prompt?, record_ref, predicates:[{n,name,pass,why}], declared_paths}. It never runs git.
Its docstring names both callers (commands/v-triage.md and hooks/triage-prompt-nudge.sh).
Per the 1A audit §7.2/7.6/7.7: give run_preeval() a real `binding=None` parameter threaded
to its build_record call (no monkey-patching); move `is_test_path` (predicate 6) and the
`match_auto_route` call pattern (predicates 4–5) out of the prose into importable functions
in this file; dispatch the subcommand on `argv[1] == "triage"` BEFORE the flat argparse
parser (the --selftest precedent) so the four existing flag-only callers
(compound-v-fastpath-run.py, skills/compound-v/cross-model-review.md,
skills/backend-launcher/SKILL.md, tests/v2.9-e2e/) keep working unmodified.
Selftests: sandbox repo + the example taxonomy → JSON shape; needs_t3 shape; refused
declared paths warned, not stored. --selftest stays green.
B2 commands/v-triage.md T2: replace the inline python with the one-line call
`python3 scripts/compound-v-preeval.py triage --request-env V_TRIAGE_REQUEST --repo .
--session-id "$CLAUDE_CODE_SESSION_ID"` (+ --t3-category on re-entry). T3 unchanged.
B3 hooks/triage-prompt-nudge.sh: keep the name, registration and every gate it has
(event, not a slash command, not a short question, session id present, repo has
.claude/compound-v.json or docs/superpowers, no covering record for this session, no
active run). Then, instead of the reminder: write the prompt to a private temp file
(umask 077), run `python3 <plugin>/scripts/compound-v-preeval.py triage --request-file
<tmp> --repo <proj> --session-id <sid> --json` bounded to 8000 ms (copy the Stop hook's
_bounded_capture pattern), unlink the file. On a record: additionalContext with tier,
pre_eval_id, bands, override if any, predicates 1–6, and the sentence "record written, not
committed: /v:orchestrate commits it at bind; for a DIRECT change include
docs/superpowers/pre-eval/<id>.* in your commit." On needs_t3: the T3 prompt with "run
/v:triage to finish — one light Task." On failure/timeout: today's reminder text
unchanged. Never block, never commit, never exit non-zero. No marker file any more — the
record is the marker. shellcheck -S warning clean. Resolve the plugin root the way the
other hooks do (CLAUDE_PLUGIN_ROOT, else the hook's own directory's parent). REWRITE the
hook's header prose: its current central claim "THIS HOOK NEVER WRITES A RECORD" becomes
false by design — state the new behaviour and the accepted tradeoff (a scored record and a
`predicted` event for the first non-slash, non-question prompt of a session, uncommitted
until bound; off via pre_eval.enabled: false). Rewrite hooks/hooks.json's
`$comment_native_points` sentence about this hook in the same way.
B4 git rm hooks/tool-failure-ledger.sh; delete the PostToolUseFailure block from
hooks/hooks.json — it is the LAST key, so also drop the trailing comma after the PreCompact
block, and validate the file with `python3 -m json.tool hooks/hooks.json`; delete the
ledger section of tests/test-native-points.sh.
B5 tests/test-native-points.sh triage section: change request → record + tier in
context; question → silent, no record; slash → silent; second request → silent;
pre_eval.enabled:false → silent, no record; planted engine failure (unreadable engine
path) → reminder text, exit 0. bash tests/test-native-points.sh exits 0.
B6 commands/v-triage.md T4 has TWO DIRECT bullets (1A §7.9): the "IN the auto-route
candidate class … run `/v:triage --land`" bullet becomes the UNATTENDED-only instruction
(name the unattended contexts); the "DIRECT, but NOT auto-routable" bullet → "Implement, run
the floor, commit on the current branch — include docs/superpowers/pre-eval/<id>.* in the
commit". Phase L's
heading → "Phase L — unattended landings only" (a /loop- or /schedule-driven session, or
--permission-mode dontAsk); Phase L otherwise unchanged. commands/v-orchestrate.md 0a:
DIRECT's next step is the commit, not --land. skills/compound-v/phase-preeval.md §1
invariant 4: add one sentence — an attended DIRECT change is human-accepted by the human
who reviews the diff and commits; the auto-route class (predicates 7–9) applies to
unattended landings. bash tests/test-triage-landing.sh still exits 0.
B7 live probe from your worktree root: drive the hook with synthetic stdin
(hook_event_name UserPromptSubmit, session_id probe-<random>, cwd $PWD, prompt "rename
the heading in docs/superpowers/loops.md") → a record appears under
docs/superpowers/pre-eval/ bound to that session and stdout carries additionalContext
with a tier; then delete the probe record files and the triage-outcomes line it appended
(git checkout -- docs/superpowers/memory/triage-outcomes.jsonl). Report the observed tier
and elapsed time in your summary. Do not touch README.md, CHANGELOG.md or SKILL.md.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-preeval.py`
- `hooks/triage-prompt-nudge.sh`
- `hooks/tool-failure-ledger.sh`
- `hooks/hooks.json`
- `tests/test-native-points.sh`
- `commands/v-triage.md`
- `commands/v-orchestrate.md`
- `skills/compound-v/phase-preeval.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md`
- `docs/superpowers/plans/2026-09-02-v3.4-native-first.md`
- `hooks/epic-goal-stop.sh`
- `scripts/compound-v-taxonomy.py`
- `.claude/compound-v-impact-taxonomy.example.yaml`

## Acceptance (your definition of done)

- python3 scripts/compound-v-preeval.py triage --request-env X --repo . --session-id S --json prints {pre_eval_id, tier, decision, needs_t3, record_ref, predicates, declared_paths}; its docstring names both callers.
- commands/v-triage.md T2 is a one-line call to that subcommand.
- Driven with synthetic UserPromptSubmit stdin in a sandbox repo, hooks/triage-prompt-nudge.sh writes a record bound to the stdin session_id and prints additionalContext naming the tier; a question, a slash command, a second request, and pre_eval.enabled:false all stay silent with no record; a planted engine failure yields the reminder text and exit 0.
- hooks/tool-failure-ledger.sh is gone, hooks/hooks.json is valid JSON with no PostToolUseFailure block, and bash tests/test-native-points.sh exits 0.
- commands/v-triage.md documents attended DIRECT as an ordinary commit and Phase L as unattended-only; bash tests/test-triage-landing.sh exits 0.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
