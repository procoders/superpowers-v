# Close the fourth review pass: no scope-gate carve-outs, no bytecode written, no bookkeeping between gate and authority

Compound V run `2026-09-02-v3.4-native-first-r8`, job `gate-strict`.

Read docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-4.md, items 1–4. The decision,
taken by the orchestrator and recorded in the spec amendment you will write: the scope gate keeps
NO carve-outs. Both between-pass exemptions (bytecode by extension; the two pipeline outcome
streams) are withdrawn. The honest cases they served are handled upstream instead.

1. scripts/compound-v-scope-check.py — delete is_bytecode_noise and PIPELINE_BOOKKEEPING and their
   use in the changed set; restore the three-term formula in the docstring; keep the selftests
   that plant scripts/__pycache__/x.cpython-314.pyc, __pycache__/payload.py and id_rsa and make ALL
   of them BLOCK outside the lane; delete the bookkeeping selftests.
2. Nobody writes bytecode. In scripts/compound-v-emit-workflow.py: every python command string the
   emitted script runs (register-lane, gate-receipt, record, finalize-wave, test floors it
   composes) and every clamp rule that admits them carry `-B` right after the interpreter
   (`<python> -B <script> …`) — rules and commands must keep matching each other. The Implement
   prompt (render_worker_prompt) gains two sentences: run Python with -B or
   PYTHONDONTWRITEBYTECODE=1 (a stray .pyc outside your lane blocks your job), and keep every
   admitted command on ONE line — the clamp matches a literal prefix and a backslash-newline
   continuation was denied in a real run. Same -B in compound-v-emit-preflight.py's clamp. Add
   `sys.dont_write_bytecode = True` at the top of scope-check, integration-gate and emit-workflow
   (before sibling imports). Selftests pin: the -B in commands and rules; the two prompt sentences.
3. Loaders never read an in-tree cache. hooks/lane-guard.sh: replace the export block at :159-162
   with PYTHONDONTWRITEBYTECODE=1 plus PYTHONPYCACHEPREFIX set to a private directory under
   ${TMPDIR:-/tmp} (created with mkdir -p; if it cannot be created, fall through — the guard fails
   open by contract), and a comment saying WHY: a forged .pyc beside the matcher would otherwise be
   executed by this loader (fourth pass, item 1). scripts/compound-v-integration-gate.py: the
   importlib loader of the matcher (~:638-650) sets sys.pycache_prefix to the same kind of private
   directory before exec_module. Add a lane-guard test (tests/test-lane-guard.sh) that plants a
   bogus scripts/__pycache__/compound-v-scope-check.cpython-<ver>.pyc beside a copy of the matcher
   and shows the guard still denies an out-of-lane write.
4. Bookkeeping after the authority. Move the merge_pending `actual` append
   (_maybe_append_run_actual, called from cmd_record) into cmd_finalize_wave, AFTER the
   integration authority has run over the wave and BEFORE the commit. Delete the digest exclusion
   of PIPELINE_BOOKKEEPING in integration-gate.py and emit-workflow.py (keep the run-directory
   exclusion). Selftest: a direct-mode job finalized after a Record leaves its receipt neither
   forged nor contradicted. Note worker-performance.jsonl is refreshed after the commit already.
5. Records: .gitignore's bytecode comment; scope-check's docstring; the CHANGELOG 3.4.0 entry
   "### Changed — the scope gate drops interpreter bytecode…" rewritten to "### Changed — the scope
   gate keeps no carve-outs; the pipeline writes no bytecode and no bookkeeping between gate and
   authority"; the spec gets a section "After the fourth review pass (2026-09-02)" naming the two
   withdrawn carve-outs and the reason (a forged .pyc executes through the lane guard's loader; a
   worker's rewrite of triage-outcomes.jsonl would ride the next by-name commit).
6. Run the acceptance commands; report per item what changed, the command, its exit code.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-scope-check.py`
- `scripts/compound-v-integration-gate.py`
- `scripts/compound-v-emit-workflow.py`
- `scripts/compound-v-emit-preflight.py`
- `hooks/lane-guard.sh`
- `tests/test-lane-guard.sh`
- `tests/test-integration-gate.sh`
- `tests/test-engine-c-contract.sh`
- `.gitignore`
- `CHANGELOG.md`
- `docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-4.md`
- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-3.md`
- `hooks/triage-prompt-nudge.sh`

## Acceptance (your definition of done)

- scripts/compound-v-scope-check.py has NO bytecode exemption and NO PIPELINE_BOOKKEEPING: a planted scripts/__pycache__/x.cpython-314.pyc outside the lane BLOCKS (selftest), and grep -rn PIPELINE_BOOKKEEPING scripts hooks tests returns nothing.
- Every python command the emitter writes into a workflow script or a clamp rule carries -B (`<python> -B <script> …`), and the Implement prompt tells the worker to run Python with -B / PYTHONDONTWRITEBYTECODE=1 and to keep every admitted command on ONE line; selftests pin all three.
- scripts/compound-v-scope-check.py, scripts/compound-v-integration-gate.py and scripts/compound-v-emit-workflow.py set sys.dont_write_bytecode = True before any import of a sibling module; hooks/lane-guard.sh and the authority's importlib loader of the matcher run with PYTHONPYCACHEPREFIX pointing at a private temp directory so an in-tree __pycache__ is never read; lane-guard.sh's comment says why (the fourth pass's item 3).
- The merge_pending `actual` is appended by finalize-wave AFTER the integration authority has run over the wave (never by Record), so nothing the pipeline writes lands between a direct-mode job's gate and its re-derivation; the digest exclusions in integration-gate.py and emit-workflow.py cover the run directory only; a selftest proves a direct-mode job's receipt is neither forged nor contradicted across a finalize.
- .gitignore's bytecode comment, scope-check's docstring formula and the CHANGELOG 3.4.0 entry describe exactly this gate; the spec gains an amendment 'After the fourth review pass' saying the two carve-outs were withdrawn and why.
- bash tests/test-lane-guard.sh, bash tests/test-integration-gate.sh, bash tests/test-engine-c-contract.sh exit 0; /usr/bin/python3 -B <script> --selftest is green for the three scripts and compound-v-emit-preflight.py.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
