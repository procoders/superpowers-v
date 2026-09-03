# The lane guard's probes are bounded, its loaders never import without a safe cache prefix, its imports cannot be shadowed, its tests discriminate

Compound V run `2026-09-02-v3.4-native-first-r12`, job `guard-hardening`.

You have a developer's shell; run Python with -B; register your lane with a LITERAL --cwd (run `pwd`
first; the clamp refuses "$PWD"). Do not add verification beyond the acceptance commands; run a listed
command at most once. The Codex findings are in docs/superpowers/reviews/2026-09-03-codex-round-4-gate-changes.json
(read it — every item below cites its evidence), the eighth pass is docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-8.md.

Items: Codex H3, H2 (the hook half), C2 (scope-check + validate-manifest), L1; eighth pass #3, #6. The hook is
the highest-blast-radius file in the plugin: keep its two fail-open mechanisms, the 1.5 s Stop budget
semantics do not apply here but the PreToolUse registration must now carry a timeout — choose a value that
covers the measured cost and say why in hooks.json's $comment. Report per item: file, change, command,
exit code.

## Write-allowed (your lane — anything else is a scope violation)

- `hooks/lane-guard.sh`
- `hooks/hooks.json`
- `tests/test-lane-guard.sh`
- `scripts/compound-v-scope-check.py`
- `scripts/compound-v-validate-manifest.py`
- `README.md`
- `AGENTS.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/reviews/2026-09-03-codex-round-4-gate-changes.json`
- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-8.md`

## Acceptance (your definition of done)

- Codex H3: every interpreter probe in hooks/lane-guard.sh runs under the hook's own bounded-capture pattern (sub-second budget) and the delegated parse is bounded; hooks.json's PreToolUse lane-guard registration carries a timeout; on a probe timeout the hook emits one fail-open notice and stops probing. Test: a candidate wrapper that sleeps 30 s first on PATH → the hook returns within its budget with the notice.
- Codex H2: when the private pycache prefix cannot be created, hooks/lane-guard.sh emits the fail-open notice and does NOT run the loader; test forces mkdir failure with a planted forged cache beside the matcher and shows no import happened.
- Codex C2: scripts/compound-v-scope-check.py and scripts/compound-v-validate-manifest.py drop their own directory and the cwd from sys.path before any non-stdlib import; a selftest plants a hostile yaml.py beside the script (sandbox) and shows the parse is unaffected. Codex L1: compound-v-scope-check.py's docstring/exemption comments name the actual exemption classes (or the emitter's — coordinate by describing what the gate exempts by name today).
- Eighth pass #3: tests/test-lane-guard.sh asserts the interpreter log line on the HEALTHY path (nothing passed over) and a planted restoration of the old conditional makes that assertion red. #6: the interpreter is logged ONCE per session (a marker in the hook's store) rather than per call, and the COST paragraph in README.md/AGENTS.md/the hook header says so with the measured line count.
- bash tests/test-lane-guard.sh exits 0; shellcheck -S warning hooks/lane-guard.sh clean; python3 -m json.tool hooks/hooks.json parses; /usr/bin/python3 -B --selftest green for scope-check and validate-manifest.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
