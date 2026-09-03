# The merge applies a sealed per-job patch; the manifest is digest-bound; state is a cache; enforcement imports cannot be shadowed

Compound V run `2026-09-02-v3.4-native-first-r12`, job `patch-artifact`.

You have a developer's shell; run Python with -B; register your lane with a LITERAL --cwd (run `pwd`
first; the clamp refuses "$PWD"). Do not add verification beyond the acceptance commands; run a listed
command at most once. The Codex findings are in docs/superpowers/reviews/2026-09-03-codex-round-4-gate-changes.json
(read it — every item below cites its evidence), the eighth pass is docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-8.md.

Design (decided by the orchestrator; implement it, do not re-argue it): the Gate produces a SEALED per-job
artifact — jobs/<id>.patch + its sha256 in the receipt. The authority validates the artifact (digest and
that it applies cleanly onto the baseline), finalize applies exactly it, then proves from git that HEAD's
version of every path in the artifact equals the artifact's post-image, and only then prunes. Nothing
downstream of the Gate ever re-reads the live worktree as evidence. The manifest is bound the same way: a
digest baked into the emitted script's CFG, checked by every command. sys.path hygiene closes the import
shadowing; a pycache prefix that cannot be created means no importlib load.
Items: Codex C1, C2, C3, C4, H1, H2, H4 (read their evidence lines and reproductions); eighth pass #2, #4,
#5. Keep every existing guarantee (fail-open contract, Python 3.9, bash 3.2). Update the four docs in your
lane so they describe the sealed-patch merge and the manifest digest. Report per item: file, change,
command, exit code.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-emit-workflow.py`
- `scripts/compound-v-integration-gate.py`
- `tests/test-integration-gate.sh`
- `tests/test-engine-c-contract.sh`
- `skills/compound-v/workflows-accelerator.md`
- `skills/compound-v/state-machine.md`
- `skills/compound-v/execution-manifest.md`
- `skills/backend-launcher/SKILL.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/reviews/2026-09-03-codex-round-4-gate-changes.json`
- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-8.md`
- `schemas/job_result.schema.json`

## Acceptance (your definition of done)

- Codex C3/H1/H4/C4: gate-receipt writes jobs/<id>.patch (git diff --cached --binary <baseline>, the worker's approved paths only) and records its sha256 in the receipt; the authority validates the artifact against that digest and refuses a receipt whose artifact is missing or mismatched; finalize-wave applies EXACTLY that artifact (never a fresh diff of the live tree), proves after the commit that the job's files in HEAD equal the artifact's post-image before pruning the worktree, and on the idempotent branch requires that proof from git (state.json is a cache, never authority). Selftests: (a) a worktree reverted to baseline after the gate is refused, not pruned; (b) ignored test byproducts (.pytest_cache/**) created after the gate do not make the authority contradict the receipt, because the authority validates the artifact; (c) a state.json forged to integrated:true with no git proof is not skipped.
- Codex C1: emit bakes sha256(manifest.yaml) into CFG.manifest_digest; gate-receipt, record, finalize-wave and the authority verify the manifest on disk against it (flag --manifest-digest, from CFG) and refuse on mismatch; selftest plants a widened manifest after emit and shows the gate refuses.
- Codex C2/H2: scripts/compound-v-emit-workflow.py and scripts/compound-v-integration-gate.py remove their own directory (sys.path[0]) and the cwd from sys.path before any non-stdlib import, set sys.dont_write_bytecode before those imports, and when the private pycache prefix cannot be created they do NOT importlib-load the matcher (authority: fail closed with a reason; emitter's loader: refuse); selftests plant scripts/yaml.py in a sandbox and show the manifest is not widened, and force mkdtemp failure with a planted cache and show no exec.
- Eighth pass #2: agent_role_for matches reviewer types exactly (review, spec_review, quality_review, integration_review) and returns a reason when it declines; review_fix gets the implementer role. #4: a malformed manifest max_turns degrades to the tier default WITH a note in the rendered prompt and the emit output. #5: execution-manifest.md and the rendered 'Turn cap' agree with agents/implementer.md (deep = 80).
- /usr/bin/python3 -B --selftest green for both scripts; bash tests/test-integration-gate.sh and bash tests/test-engine-c-contract.sh exit 0; workflows-accelerator.md, state-machine.md, execution-manifest.md and backend-launcher/SKILL.md describe the sealed-patch merge and the manifest digest.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
