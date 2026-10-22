# v3.6 Wide Dispatch Code Archaeology

Spec: `docs/superpowers/specs/2026-09-11-v3.6-wide-dispatch-design.md`. A plan and a manifest
already exist (`docs/superpowers/plans/2026-09-11-v3.6-wide-dispatch.md`,
`docs/superpowers/execution/2026-09-11-v3.6-wide-dispatch/manifest.yaml`) and name this file as
their archaeology audit — the manifest's ten jobs are cited below wherever they bear on a finding.
Line numbers are current HEAD (`ce4cb19` or later); the spec's own `~:NNNN` approximations are
stale by 100–150 lines in most places, so every citation below was re-read from the file, not
copied from the spec.

## Step 0 — V-memory

`python3 -B scripts/compound-v-memory.py search "wide dispatch multi-provider register-lane" --intent planning --top 8`
and a second query on `"direct mode isolation preexisting snapshot lane guard"` returned prior
archaeology on this exact subsystem: `docs/superpowers/archaeology/2026-09-03-v3-4-2-transcript-watch.md`
(the `isolation`/register-lane shared-state pattern), `2026-09-03-v3-4-9-preflight-kb-paths-and-retries-schema.md`
(direct-vs-worktree matrix precedent), and `2026-09-03-v3-4-3-codex-sandbox-checkout.md` (confirms
`hooks/lane-guard.sh:765`/`:882`/`:1536` as the lane-map read sites — consistent with what this
audit found independently at the current line numbers below). No hit named provisioning, the
finalizer's `-f` gap, or the `reviewer_backend` const/enum distinction — those are new to this
audit. Nothing recalled is stale enough to contradict; where a recalled line number differs from
today's it is because the file has grown, not because the claim changed.

## 1. Matrix

**Dimension: isolation × pipeline stage, for the pre-existing-dirt exemption (F1).**

| isolation | register-lane snapshot? | gate-receipt reads `--preexisting`? | scope-check.py itself branches on mode? |
|---|---|---|---|
| `direct` | Yes — `cmd_register_lane` :5636 `if (args.isolation or "direct") != "worktree":` | Yes — `cmd_gate_receipt` :3782 `if args.mode != "worktree":` | **No.** `changed_files()` (`compound-v-scope-check.py:242`) and the `--preexisting` argparse entry (`:542-550`) take the file unconditionally in both `--worktree` and `--repo` mode. |
| `worktree` (today) | **No** — the `!=` test at :5636 is false, so the whole snapshot block is skipped | **No** — same test at :3782 is false, so `_run_scope_check(..., preexisting=pre)` is called with `pre=None` | (same — no branch) |
| `worktree` (F1 target) | Must become Yes, gated on provisioning having run first | Must become Yes | No change needed here |

New code does not need to handle `direct` (already correct) or the scope-check primitive (already
mode-agnostic). It needs to handle exactly the two `worktree`-mode gates in
`compound-v-emit-workflow.py`, and both are currently hard-wired OFF for worktree, not merely
"unverified" as the spec's parenthetical implies (see §7, item 1).

**Dimension: which git-add call stages run-directory artefacts (F2).**

| Call site | Pathspec restricted? | Uses `-f`? | Reached by a normal wave? |
|---|---|---|---|
| `_stage_paths` (`compound-v-emit-workflow.py:4052`) | Yes, per-path | No | Yes — via `merge_back` (:4143, worktree fallback) and `_commit_paths` (:4981, the wave's sealed-patch commit) |
| `build_sealed_patch`'s tmp-index add (`:575`) | Yes, per approved job path | No | Yes — sealing a job's patch in `gate-receipt` |
| `_compute_diff_digest_local`'s tmp-index add (`:696`) | **No** — bare `git add -A`, whole tree | No | Yes — computing the receipt's `diff_digest` |
| **The run-directory bookkeeping commit** (`cmd_finalize_wave:5556`) | Whole run dir, one pathspec (`_bk_rel`) | **No** | **Yes — this is the ONLY call that ever stages `results/`, `receipts/`, `state.json` for commit** |

None of the job's changed files (`approved`/`unique`, fed to `_commit_paths` → `_stage_paths`) are
run-directory artefacts — a job's `write_allowed` almost never targets its own run directory, and
`results/<id>.json`/`receipts/<id>.gate.json` are written by Record and Gate, not by the worker.
So `_stage_paths` is NOT the code path AC-3 exercises in production; see §7, item 2 — this is the
audit's most consequential correction to the spec's assumption.

**Dimension: `reviewer_backend` — two unrelated checks share one field name (F7).**

| Receipt kind | Schema/check | Current constraint | Location |
|---|---|---|---|
| Fast-path / post-review receipt (DIRECT-tier second look, CR5-5) | `verify_sealed_receipt` / `_validate_receipt` | `reviewer_backend` must equal `"claude"` (a **same-family** in-harness Opus review is what this one wants) | `compound-v-validate-manifest.py:1407-1409`, docstring at `:1450` |
| SCOPED+ cross-model receipt (the one F7 touches) | `schemas/cross-model-receipt.schema.json` + `_validate_cross_model_receipt` | `reviewer_backend` is a JSON-Schema **`const: "codex"`**, not an enum | `schemas/cross-model-receipt.schema.json:32-35`; checked via `_schema_lite` in `compound-v-validate-manifest.py:2057-2075` |

New code touches only the second row. The first row's `"claude"` requirement is a different,
pre-existing gate for a different receipt and must not be widened by anyone touching this area —
worth stating explicitly because both live in the same file under a name that greps identically.

## 2. Shared State

**`args.isolation` / `args.mode`, `compound-v-emit-workflow.py` (register-lane, gate-receipt).**
Set from the manifest (`register-lane --isolation`, required, `choices=["direct","worktree"]`,
:5588) and from the caller's `--mode` on `gate-receipt` (:3679, default `"worktree"`). Both are
read straight off the emitted workflow script, never re-derived. F1's new `provision_command` step
must run **inside** the existing `if args.isolation != "worktree":`-style gates, using the SAME
`args.isolation`/`args.mode` values — there is no third value and no risk of the provisioning step
seeing a value the rest of the function does not already branch on.

**`pre` (the resolved `--preexisting` file path), `cmd_gate_receipt`.**
Set at `:3781` (`pre = None`), only assigned a real path inside `if args.mode != "worktree":`
(:3782-3844). Read once, at `:3846` (`_run_scope_check(..., preexisting=pre)`). Gap: for a
worktree job, `pre` reaches `_run_scope_check` as `None` unconditionally — not because no file
exists, but because the `if` above it never runs for that mode. This is exactly the F1 gap; there
is no other reader of `pre` to update.

**`out["manifest_digest"]`, `cmd_gate_receipt` — DOES NOT EXIST.**
`GATE_SCHEMA` (`:2293-2320`) is `additionalProperties: false` with an enumerated `properties` set
(`job_id`, `verdict`, `source`, `receipt_path`, `baseline_commit`, `realised_commit`,
`diff_digest`, `exit_code`, `raw_stdout`, `reason`, `worktree`, `tests`) — **no `manifest_digest`
key**. The `out` dict built through `cmd_gate_receipt` (:3709 initial value, through :3920 where
`escalated_from` is conditionally added) never sets one either. F3 requires the receipt to "carry
this run's `manifest_digest` when the run has one" as part of validity test (iii) — that value
(`args.manifest_digest`, already an argument to `cmd_gate_receipt`, :3686-3689) is available but
unused for this purpose today. Two things must change together or the Gate agent's own structured
output becomes schema-invalid: `out["manifest_digest"] = args.manifest_digest` (or similar) in
`cmd_gate_receipt`, AND a new `"manifest_digest": {"type": "string"}` entry in `GATE_SCHEMA`'s
`properties` (:2293-2320). Neither is mentioned in the manifest's `e1-finalizer-record` acceptance
list, which only says "carries the run's manifest_digest when both exist" as a property to check —
not as a schema/emitter change to make. Flagged in §7.

**`verdict` (the record command's local, `cmd_record`).**
Read from `--verdict-file` (json.load, :4643) or `--verdict-json` (:4659). Mutated TODAY at
:4648-4652 and :4653-4657 into `{"verdict": "error", "reason": "...the receipt was rewritten
between Gate and Record"}` on any `--expect-verdict`/`--expect-diff-digest` mismatch — this is the
exact wording F3 wants deleted, confirmed present nowhere else in the repo (`grep -rn "receipt was
rewritten between Gate and Record" tests/ scripts/ docs/ skills/ commands/` returns only these two
lines), so no other test string needs updating for its removal. **New validations F3 requires that
do not exist today:** the code never checks that `verdict.get("job_id") == job_id`, i.e. validity
condition (ii) — "carries this job_id" — is unenforced; a `--verdict-file` for a different job's
receipt is accepted as-is today. This is new code, not a verification of existing code.

**`state_job["worktree"]`, `cmd_record`.** Set from `verdict.get("worktree")` (:4742, :4826-4829) —
unaffected by F3; still governed by the existing no-work/locator-fault branch at :4744-4825. No
change needed there.

**`job.get("isolation")` in `cmd_finalize_wave`.** Not the manifest's raw value alone — corrected
at :5283 via `_gate_mode_from_receipt(gate_doc) or isolation`. This already reads `raw_stdout`'s
embedded `mode` (:5068-5083), which is unaffected by adding `manifest_digest` to `GATE_SCHEMA`
(additive field, and `_gate_mode_from_receipt` only reads `.get("mode")`).

**`records()`/`live_lane_map()`/`map_files()` ordering, `hooks/lane-guard.sh`.** See §3.

## 3. Sibling Code

**The register-lane snapshot block is the sibling F1's worktree path must become (`:5627-5653`).**
Entry condition: `if (args.isolation or "direct") != "worktree":` — literally excludes the case F1
adds. Reads: `args.repo_root`, `sys.executable`. Edge cases already handled: one-shot (refuses to
re-snapshot on a second `register-lane` call for the same job, :5641-5649), fail-open into a
stricter gate on exception (:5650-5653). Latent property, not a bug: the snapshot is rooted at
`args.repo_root` for direct mode; for worktree mode it must be rooted at the **worktree** (`args.cwd`),
after `provision_command` has run there — `_preexisting_snapshot(root, python_bin)` (`:3548-3573`)
already takes `root` as a parameter and has no direct-mode assumption baked into its git plumbing
(three `git` probes against whatever `root` is given), so the sibling function is reusable
unchanged; only the caller's gate and the `root` argument need to change.

**The `_run_scope_check`/`read_preexisting_unchanged` sibling read path (`:3782-3844`) is the one
F1's worktree gate-receipt read must become.** Read carefully: `read_preexisting_unchanged`
(`compound-v-emit-workflow.py:3430-3480`) is digest-bound and mode-agnostic itself; the run-dir
"owned by name" walk at :3800-3814 computes `run_rel` as the run directory's path relative to
`root` — for a worktree job the run directory normally sits OUTSIDE the worktree entirely (the
`_rel.startswith("..")` guard at :3802 already handles that by skipping the by-name walk, leaving
only the digest-bound `read_preexisting_unchanged` paths). This means enabling the read for
worktree mode does not require touching the by-name-ownership walk at all — it will correctly
no-op for an out-of-tree run directory, which is the normal worktree layout. Known latent
property, not a bug introduced by this change: if a future worktree layout ever nested the run
directory INSIDE the worktree, the by-name walk would start firing there too; today it does not,
because `_run_dir_lock`/`register-lane`/etc. all place run directories under
`docs/superpowers/execution/` in the **project** checkout, never inside `.claude/worktrees/*`.

**The four worker scripts are near-identical siblings of each other (F1, worker half).** Argument
parsing blocks: `compound-v-run-codex-worker.sh:265-292`, `-cursor-worker.sh:274-299`,
`-antigravity-worker.sh:270-296`, `-opencode-worker.sh:312-341` — all four use the same `while [ $#
-gt 0 ]; do case "$1" in ... esac; done` shape with `--write-allowed`, `--test-contract-file`,
`--test-timeout-sec` parsed identically (confirmed byte-similar option names and shift patterns
across all four `grep` hits). Each of the four runs its own `compound-v-scope-check.py` invocation
later (`codex:606`, `cursor:471`, `antigravity:522`, `opencode:806`), all passing `--write-allowed`
built from the same manifest field. A new `--provision-command`/`--provision-timeout-sec` pair
belongs in the SAME case block in all four, immediately after `git worktree add` and before the
scope-check call, exactly where the manifest's `scope-workers-provision` job body already says to
put it — confirmed consistent with the actual code shape, not merely plausible.

**`_stage_paths` (`:4052-4073`) is NOT a sibling of the bookkeeping-commit `git add`.** They look
alike (both `git add -A -- <pathspec>`) but are two independent call sites; see Matrix and §7. A
fix applied only to `_stage_paths` — which is what the spec's F2 text literally describes — passes
the manifest's own planned selftest (which calls `_stage_paths` directly, per
`e1-finalizer-record`'s acceptance item (a)) while leaving the actual AC-3 failure mode
(`cmd_finalize_wave:5556`) unpatched.

**`record_unresolved`/the unresolved-identity loop (`hooks/lane-guard.sh:906-991`, caller
`:1540-1561`) is the sibling F4 extends.** Entry condition: `agent_worktree_root(cwd)` is truthy
AND `resolve_job(...)` returned `None`. Today's loop (`:1546-1561`):
```
for path in maps:
    if not live_lane_map(path):
        continue
    first = record_unresolved(path, agent_id, cwd, tool)
    ...
    return 0
```
`maps = map_files(cwd)` (:1538) is already sorted newest-run-first (`dirs.sort(key=_mtime,
reverse=True)`, :762) restricted to non-terminal directories, so in the common case the loop
already records against the newest live run — but it does so **incidentally**, by stopping at the
first live map it meets, and it builds no `candidate_runs` list and inspects no other live map.
F4's `candidate_runs` field is net-new data, not an existing value being renamed. The `why` text
being replaced (":941-943", `"...register-lane missing, ran late, or its entry was lost)"`) is
exactly the "old three-cause wording" F4 names, confirmed verbatim.

**Known latent gap in the sibling, not fixed by F4 unless explicitly handled:** nothing today
recognises a `register-lane` bootstrap call at all. `WORKER_RE` (`:1153`,
`compound-v-run-[A-Za-z0-9_.-]+-worker\.sh`) matches only the four EXTERNAL worker scripts
(exempted at `:1530-1533`, "D5.2"). A Claude-backend job's own `register-lane` Bash call — its
documented "FIRST COMMAND" — has no such exemption, so TODAY every worktree job's first
`register-lane` call, made before its own worktree entry exists in the lane map, falls into the
unresolved-identity branch and is recorded + announced via `open_notice` (:1554-1560). This is a
real, reproducible noise source in the current build, not a hypothetical one; F4's bootstrap
exemption fixes it as a side effect of closing the AC-5 gap.

## 4. External APIs (via context7)

No third-party SDK is introduced, but `resolve-library-id`/`query-docs` were run (not skipped) on
`Claude Code` — `/websites/code_claude` — for the advisor tool and `/skill-doctor`, since both are
checkable claims and the base rule is docs-first, not memory-first, even for a first-party surface.
Confirmed current, and consistent with the spec's own live-probe: "The advisor tool allows Claude
to consult a second, typically stronger model at critical junctures... server-side on Anthropic's
infrastructure... requires the Anthropic API; ... unavailable on Amazon Bedrock, Claude Platform on
AWS, Google Cloud's Agent Platform, or Microsoft Foundry" (`code.claude.com/docs/en/advisor`);
"`advisorModel`... commonly configured via the `/advisor` command and saved to
`~/.claude/settings.json`... has no effect on Amazon Bedrock, Google Cloud's Agent Platform, or
Microsoft Foundry" (`settings-reference`); and, notably for F4's neighborhood: "The advisor tool is
an API-level server tool rather than a tool implemented directly by Claude Code, so it cannot be
named in permission rules or hook matchers" (`tools-reference`) — confirms `hooks/lane-guard.sh`
could never gate the advisor tool itself even if someone were tempted to. The doc excerpt names
`~/.claude/settings.json` as the *common* path for `advisorModel`, not the *only* legal one; whether
the PROJECT `.claude/settings.json` scope the spec uses is equally valid is a domain/settings
question for Phase 1B/1C, not this code audit — this audit only confirms `_worktree_base_is_head`
(§7 item 11) does not care which scope wrote the file. `commands/v-init.md` has no existing
`/skill-doctor` or `advisorModel` reference to reconcile against (confirmed absent by grep), so
F6/F7 are additions, not migrations of existing wrong code.

**Verified, not assumed: the third git probe's pathspec form.** `_preexisting_snapshot`
(`compound-v-emit-workflow.py:3571`) runs `ls-files --others --ignored --exclude-standard -z --`
with a trailing bare `--` and no pathspec argument after it, while `compound-v-scope-check.py:288`
runs the same probe with an explicit `-- .`, and that file's own comment (`:284-285`) says the
pathspec is required "so git lists ignored paths under the tree rather than nothing" — a plausible
live bug in the sibling if true, since F1 reuses `_preexisting_snapshot` for the exact
gitignored-`node_modules/` case AC-2 tests. Reproduced directly rather than inferred: a scratch repo
with a gitignored directory returns the identical result (`ignored/a.txt`) for all three of
`-- .`, bare trailing `--`, and no `--` at all, under this environment's git. Not a bug on this git
version; kept here as a one-line note for the implementer to keep in mind if the two probes are ever
consolidated, not as a MUST-fix.

## 5. Regression Surface

- **`cmd_register_lane` worktree branch** (F1): today's behaviour for every existing worktree job
  is "no snapshot, no exemption list" — correct today because a fresh worktree starts clean. Adding
  a snapshot unconditionally for worktree jobs (even with no `provision_command`) would change
  nothing observable IF the snapshot is empty, but a bug that snapshots the WRONG root (e.g.
  `repo_root` instead of the worktree) would silently exempt files in the wrong tree for every
  existing worktree job in the fleet. Impact if broken: false negatives in the scope gate for every
  worktree job, repo-wide — the highest-blast-radius risk in this feature.
- **`cmd_gate_receipt`'s existing digest-exclusion comment at `:3871-3877`** ("It is the ONLY
  exclusion") becomes literally false once F1 lands, because a worktree job's `preexisting` paths
  are then ALSO excluded from the changed-set the way direct mode's are — the comment must be
  updated in the same change or it will mislead the next reader into thinking direct mode's
  run-dir exclusion is still the only one.
- **`_stage_paths` behavior change to add `-f`** (F2, if applied): every existing caller
  (`merge_back` at :4143, `_commit_paths` at :4981) starts force-adding. For `merge_back` (staging
  a job's own `write_allowed` files inside a worktree) and `_commit_paths` (staging the same set of
  approved paths in the main repo before commit), those paths are virtually never gitignored in
  practice (a job's lane is source code), so `-f` should be a no-op for every existing run — but it
  is a real behavior widening (force-add can stage a path a human deliberately gitignored inside
  their own lane) and belongs only on the run-directory pathspec per F2's own wording ("for any
  path under the run directory"), not blanket on `_stage_paths` for every caller. See §7.
- **`cmd_finalize_wave:5556`'s bookkeeping `git add -A`** (F2, real fix site): currently silent on
  a gitignored `docs/` prefix — the failure mode is not a crash, it is "the bookkeeping commit
  never happens" (`_rc_q` from `git diff --cached --quiet` returns 0 because nothing got staged,
  so the whole `if _rc_q != 0:` body at :5564 is skipped). Every existing run where `docs/` is NOT
  gitignored (this repo, and presumably every downstream project using the default layout) is
  unaffected either way.
- **`cmd_record`'s verdict-mismatch handling** (F3): today ANY `--expect-verdict` mismatch becomes
  `error` unconditionally. Changing this so a `pass`/`blocked` disagreement instead keeps the
  receipt's own verdict is a real behavior change for any run that previously relied on (or merely
  tolerated) the fail-to-error behavior — e.g. a flaky workflow race that used to hard-fail now
  proceeds with whatever the receipt says, so a badly-timed race could newly succeed at recording
  a stale receipt's verdict. Mitigated by the new (ii)/(iii) identity checks (job_id, manifest_digest)
  this audit found are currently absent — see §2 — which is why those checks are load-bearing for
  F3's safety, not merely nice-to-have.
- **`cmd_record`'s `if/elif` ordering** (`:4646-4657`): verdict is checked first, digest only in the
  `elif` — so a receipt that disagrees on BOTH fields today is reported only as a verdict mismatch,
  never a digest one. F3 requires digest to stay a hard `error` while verdict becomes a soft
  `verdict_disagreement`; if the digest check stays second (or `elif`), a both-mismatch receipt
  would incorrectly take the soft path and never surface the harder forgery signal. See §7 item 5.
- **The two memory-stream `git add` calls right below the bookkeeping commit**
  (`cmd_finalize_wave:5559-5562`, `git add -- <stream>` for
  `docs/superpowers/memory/{triage-outcomes,worker-performance}.jsonl`) share F2's defect class but
  are worse under a gitignored `docs/`: naming an exact ignored file to `git add` without `-f`
  **errors** (rather than silently skipping, the way a directory pathspec does), and `_run`'s return
  value is discarded here, so the error is swallowed. Not the AC-3 scenario itself (that's the
  `_bk_rel` line above), but the same class of defect one line away — worth the same `-f` if `:5556`
  gets it, for symmetry rather than because a selftest currently demands it.
- **`hooks/lane-guard.sh`'s register-lane exemption** (F4): a new substring/regex match against
  Bash commands containing `compound-v-emit-workflow.py register-lane` must not accidentally match
  a command that merely *mentions* register-lane in a comment or a grep — the existing
  `_UnparseableCommand`/quote-aware tokenizer discipline (`:1153-1199`) is the precedent to reuse
  rather than a bare substring test, or a job could grep its own past commands and suppress
  legitimate unresolved-identity recording for an unrelated write in the same Bash call.
- **`tests/test-agent-memory.sh`'s `MEM_GLOB`/`MEM_FILE`** (F5): currently bare-form
  (`.claude/agent-memory/spec-reviewer/**`, `:34-35`) and the `for a in spec-reviewer
  partition-reviewer code-archaeologist domain-expert doc-validator` loop at `:54` asserting each
  agent's `.md` names `.claude/agent-memory/$a/` — this loop's assertion will need the namespaced
  prefix too, or it silently keeps passing against the OLD (soon-to-be-wrong) bare strings while
  the agents' prose has already moved to the namespaced form, producing a false-green test.
- **`GATE_SCHEMA`/`schemas/cross-model-receipt.schema.json` additive changes** (F3, F7): both are
  `additionalProperties: false`. Every EXISTING receipt/result that lacks the new optional field
  stays valid (optional keys are fine under `additionalProperties:false` as long as they're not
  required); the risk is only in the reverse direction — a producer that starts emitting the new
  key before the schema/consumer accepts it. Sequencing this correctly is exactly why the manifest
  chains `e2-provision-engine-c` after `validate-keys-advisories` via `depends_on` (already done in
  the existing manifest, confirmed at `manifest.yaml:284-287`).

## 6. DRY Findings

- **Digest-bound exemption machinery already exists and is fully reusable for F1.**
  `write_preexisting`/`read_preexisting_unchanged`/`_preexisting_snapshot`
  (`compound-v-emit-workflow.py:3385-3573`) is generic over `root` and needs no forking — F1 is a
  matter of calling it from a second gate (worktree), not writing a second implementation. Do not
  let an implementer write a parallel "worktree preexisting" helper; the manifest's own job body
  for `scope-workers-provision` already says as much ("Keep the subtraction code in changed_files
  unchanged if it already applies in both modes").
- **The quote-aware Bash tokenizer (`hooks/lane-guard.sh:1120-1506`) is the only sanctioned way to
  recognise a substring/subcommand inside a Bash command in this file** — `WORKER_RE`'s plain
  `re.search` (:1153, :1530) is the one exception, already precedented for exactly this kind of
  "recognise one script name anywhere in the command" check. F4's `register-lane` bootstrap
  detector should copy the `WORKER_RE` pattern (a `re.compile` + `.search`), not invent tokenizer
  integration — `register-lane`'s own invocation has no quoting complexity that the tokenizer would
  need to help with (it is always `<python> -B compound-v-emit-workflow.py register-lane ...`,
  the same shape `WORKER_RE` already matches by name).
- **No third `reviewer_backend` concept should be added.** F7 must extend the EXISTING
  `cross-model-receipt.schema.json` const→enum (§1 Matrix) and must not touch or generalize the
  unrelated `"claude"`-only CR5-5 check (`compound-v-validate-manifest.py:1407-1409`) that a
  same-named grep would also surface.
- **`_job_result_from`/`apply_retry_meta` is the existing, sole pattern for adding evidence fields
  to a job result without a new schema-level top-level key** (`compound-v-emit-workflow.py:4859-4882`,
  comment: "the schema does allow it"). F3's `verdict_disagreement` belongs in the ack and
  `state.json` only, per the spec's own text, and should not be threaded into
  `job_result.schema.json` as a new top-level key — consistent with the existing `retries`/
  `escalated_from` precedent of using `summary` text for anything that does not have a dedicated
  schema slot.
- **Usage extraction's per-message-id dedup (`compound-v-usage-extract.py:664-1019`,
  `_pick_snapshot`/`_fold`) is the only sanctioned way to count anything from a workflow transcript
  once per logical message.** F7's `usage.advisor_calls` must reuse this machinery (walk the same
  `msg.get("content")` list already being visited inside `scan_transcript`'s loop, count
  `server_tool_use`/`name=="advisor"` blocks per message id, and let existing per-id dedup do the
  work) rather than writing a second, ad hoc transcript scanner — a second scanner would double-open
  and double-parse every `.jsonl` this job already reads.

## 7. Design constraints for the spec (MUST-HANDLE)

1. **F1 register-lane/gate-receipt gates are hard OFF for worktree today, not merely
   "unverified."** `cmd_register_lane:5636` (`if (args.isolation or "direct") != "worktree":`) and
   `cmd_gate_receipt:3782` (`if args.mode != "worktree":`) must both be changed to also run for
   worktree jobs (the former after `provision_command`, rooted at the worktree; the latter reading
   the same verified-subset file). `compound-v-scope-check.py` itself needs NO functional change —
   its `--preexisting` handling (`:242-267`, `:542-550`) is already mode-agnostic; only its
   docstring's stale claim ("Worktree mode passes nothing", `:266`) needs correcting, and so does
   `compound-v-emit-workflow.py`'s own stale rationale comment at `:3776-3780` ("Never in worktree
   mode — a worktree starts clean") which becomes false the moment provisioning can dirty a
   worktree on purpose.
2. **`_stage_paths` is the wrong fix site for F2's actual AC-3 failure.** The run-directory
   bookkeeping commit that lands `results/`, `receipts/`, `state.json` is a SEPARATE, direct
   `_run(["git", "-C", repo_root, "add", "-A", "--", _bk_rel])` call inside `cmd_finalize_wave` at
   `compound-v-emit-workflow.py:5556` — it never calls `_stage_paths`. A fix that only teaches
   `_stage_paths` to force-add (as the spec's F2 text literally describes) leaves this call site,
   and therefore AC-3 itself, unpatched in a real gitignored-`docs/` repository. The fix must touch
   `:5556` (add `-f`, or route this commit through a shared force-adding helper) in addition to, or
   instead of, `_stage_paths`. `build_sealed_patch`'s tmp-index add (`:575`, per-job-lane paths) and
   `_compute_diff_digest_local`'s tmp-index add (`:696`, whole-tree, no pathspec) are the two other
   `git add -A` sites the manifest's own job body asks the implementer to check; neither currently
   stages run-directory artefacts, so neither strictly needs `-f` for AC-3, but `:696`'s bare
   `add -A` will also silently drop gitignored paths from the receipt's `diff_digest` computation —
   worth a one-line comment either way, per the manifest's own instruction to the implementer.
3. **`GATE_SCHEMA` has no `manifest_digest` property and `cmd_gate_receipt` never sets one.** F3's
   validity condition (iii) — "carries this run's `manifest_digest` when the run has one" — requires
   BOTH a new `out["manifest_digest"]` assignment in `cmd_gate_receipt` (`:3664-4018`, the value is
   already available as `args.manifest_digest`) AND a new property in `GATE_SCHEMA`
   (`:2293-2320`, currently `additionalProperties: false`) or the Gate agent's own structured
   output becomes schema-invalid the first time it includes the field.
4. **F3 needs two new validity checks that do not exist today.** `cmd_record`'s `--verdict-file`
   path (`:4642-4657`) never checks `verdict.get("job_id") == job_id` (condition ii) and never
   checks a `manifest_digest` match (condition iii, blocked on finding 3 above) — both must be
   added, not merely "verified"; only the `diff_digest` comparison (condition using
   `--expect-diff-digest`) already exists.
5. **`schemas/cross-model-receipt.schema.json`'s `reviewer_backend` is a `const: "codex"`, not an
   enum** (`:32-35`). Widening it to `enum: ["codex", "claude-advisor"]` also changes the
   `_schema_lite_value` error text from `"...must be 'codex' (got ...)"` to `"...must be one of
   [...] (got ...)"` (`compound-v-validate-manifest.py:1285-1288`). The existing selftest assertion
   `any("reviewer_backend must be 'codex'" in p for p in _r_fam)` at
   `compound-v-validate-manifest.py:5320` asserts the OLD const-shaped substring and will FAIL once
   the schema changes to an enum — it must be updated in the same change (its underlying behavior,
   "a plain `claude` reviewer is still refused," stays correct; only the message text changes). Do
   not confuse this with the unrelated `reviewer_backend == "claude"` (CR5-5) check for the
   fast-path receipt at `:1407-1409` — that check is untouched by F7 and must stay untouched.
6. **`hooks/lane-guard.sh` has no `register-lane`-bootstrap exemption today**, and this is a live,
   reproducible false-positive for most, but not all, of the jobs in this very run's wave 1. The
   precise shape: `record_unresolved` only fires when `live_lane_map(path)` is True (`:1547-1549`),
   which requires the run's `worktrees` map to already name at least one worktree that exists on
   disk (`:887-903`). At the instant the **first** job in a fresh wave issues its own `register-lane`
   call, the run's lane map has ZERO worktree entries yet (no job has completed registering), so
   `live_lane_map` is False and that call falls through **silently allowed, unrecorded** — the
   ordinary-human-session branch, not the unresolved-identity one. Only once job 1's registration
   has completed (and the map has one worktree) does the SAME bootstrap pattern for jobs 2..N become
   "recorded as unresolved + `open_notice`". So the accurate claim is: every worktree job's
   `register-lane` bootstrap call is recorded **except the first job to register in a given run**,
   which this run's own nine-parallel-job wave 1 (`manifest.yaml:77-224`) will actually exercise —
   nine simultaneous `register-lane` calls landing in close succession, of which the very first to
   reach the hook sees an empty map. F4's fix (recognise the bootstrap command text directly, rather
   than relying on `live_lane_map`) closes BOTH the "recorded + noisy" case for jobs 2..N and this
   silent first-job case, uniformly. The new detector should be a `WORKER_RE`-style
   `re.compile(...).search(command)` check (precedent at `:1153`, `:1530`), not new tokenizer
   integration.
7. **`record_unresolved`'s current entry never lists `candidate_runs`, and the loop that calls it
   (`:1546-1561`) stops at the FIRST live map in `map_files(cwd)`'s already-newest-first order** —
   it happens to usually pick the newest run today, but builds no evidence of the other live runs
   it skipped. F4 must add the `candidate_runs` list explicitly (iterate the full `maps` list,
   filter by `live_lane_map`, record the filtered list, and pick — as `map_files` already orders it —
   the first/newest for `why`'s target run).
8. **`AGENT_MEMORY_ROOTS`/`is_agent_memory_glob` (`compound-v-validate-manifest.py:2856-2874`)
   already matches BOTH the bare and namespaced forms** (it only tests the `.claude/agent-memory`/
   `-local` root prefix, never the specific agent-name segment) — so "`MEMORY_ONLY_LANE` recognises
   both forms" needs NO code change. `MEMORY_LANE_UNNAMESPACED` is entirely new: it needs a new
   check that inspects the specific path segment after the root against the five bare memory-agent
   names (`spec-reviewer`, `partition-reviewer`, `code-archaeologist`, `domain-expert`,
   `doc-validator` — confirmed the closed list via `grep -l "memory: project" agents/*.md`).
9. **Every place in the repo that names the bare memory path today** (confirmed by grep, excluding
   `docs/superpowers/execution|dogfood|archaeology|expert|research|library-audit`, which are
   historical/generated and out of this change's scope): `README.md:127`, `AGENTS.md:102`,
   `agents/domain-expert.md:53`, `agents/code-archaeologist.md:53`, `agents/partition-reviewer.md:37,288`,
   `agents/doc-validator.md:53`, `agents/spec-reviewer.md:57,82`, `examples/manifest.example.yaml:204`,
   `commands/v-orchestrate.md:76`, `skills/compound-v/execution-manifest.md:67-68`,
   `skills/compound-v/SKILL.md:202`, plus the test fixture strings in
   `scripts/lint-frontmatter.py:388` and `scripts/compound-v-validate-manifest.py:5671-5694` (those
   two are the validator's OWN advisory selftests and use the bare form intentionally as fixture
   input — check each one individually before changing it, since some exist specifically to prove
   the bare form still triggers `MEMORY_LANE_UNNAMESPACED`). `docs/superpowers/architecture/architecture.md:261`
   is generated prose and is refreshed by `/v:onboard --refresh` per F8, not by a job in this run.
10. **`build_launch_argv(job, entry, run_id, repo_root, run_dir, model)`
    (`compound-v-emit-workflow.py:1746-1783`) does not receive the manifest**, only a per-job
    dict and a resolved `entry`. Because F1's `provision_command`/`provision_timeout_s` are
    TOP-LEVEL manifest keys (spec F1, "Manifest gains two optional top-level keys"), threading them
    into the external launch argv means resolving them at the `entry`-construction call site
    (`:2032-2150`, where `entry["test_contract_file"]`/`entry["test_contract_timeout_s"]` are
    already resolved the same way, :2127-2136) into new `entry["provision_command"]`/
    `entry["provision_timeout_s"]` keys, then reading THOSE inside `build_launch_argv` — mirroring
    the existing `test_contract_file` precedent exactly, not adding a new manifest parameter to the
    function.
11. **`.claude/settings.json`'s only existing reader, `_worktree_base_is_head`
    (`compound-v-emit-workflow.py:1794-1813`), reads only `cfg.get("worktree")`** — adding a
    sibling top-level `advisorModel` key is confirmed harmless to it and to every other reader (no
    other script in `scripts/*.py` opens `.claude/settings.json`, confirmed by grep). No hidden
    coupling here.
12. **`tests/test-agent-memory.sh`'s `MEM_GLOB`/`MEM_FILE` (bare form, `:34-35`) and its `for a in
    spec-reviewer partition-reviewer code-archaeologist domain-expert doc-validator` assertion loop
    (`:54`, asserting each agent file names the BARE `.claude/agent-memory/$a/`) must move to the
    namespaced form in the SAME change that edits the agents** (F5), or the test keeps passing
    against strings the agents no longer contain, which is a silent regression in test coverage
    rather than a visible failure.
13. **`agents/partition-reviewer.md` has two bare-path occurrences that neither manifest job is
    charged with fixing.** `:37` is its own memory-path resolution sentence (identical boilerplate to
    the other four agents), and `:288` is the `.claude/agent-memory/spec-reviewer/**` example
    embedded in its `MEMORY_ONLY_LANE` WARN sample output — the exact bare string AC-6 forbids in a
    committed document. The manifest gives this file's `write_allowed` to `validate-keys-advisories`
    (whose acceptance only requires "agents/partition-reviewer.md lists the two new WARN rows") and
    explicitly tells `agents-memory-advisor` **not** to touch this file ("another lane owns it"). As
    written, no job's acceptance criteria mentions fixing `:37`/`:288`, so AC-6 would fail on a file
    every job leaves alone. `validate-keys-advisories` must also apply the memory-path sentence and
    correct the `:288` example, in addition to adding the two new WARN rows.
14. **`_pick_snapshot`'s two-rule dedup (`compound-v-usage-extract.py:945-983`) has no rule for
    counting discrete content blocks, only for summing/maxing numeric token fields** — `output_tokens`
    is treated as monotonically growing across a message's streamed snapshots (`max`), while the
    other three token fields are treated as invariant (`first`, refused on disagreement). An advisor
    `server_tool_use` block inside `msg.content` is neither: it is unverified from a static read
    whether a streamed message's later snapshots repeat the SAME content list (invariant, like the
    three token fields) or accumulate additional blocks as more of the message arrives (growing, like
    `output_tokens`). Counting it the wrong way over- or under-reports `usage.advisor_calls`, which is
    exactly the anti-ruflo failure mode (a confidently wrong measured number, not an honest `null`).
    The implementer must inspect a real transcript before choosing — the manifest already points at
    one (`~/.claude/projects/.../subagents/*.jsonl`, `usage-advisor-calls` job body) — and should
    reuse the SAME per-message-id grouping `_fold`/`_pick_snapshot` already builds rather than write
    a second, independently-reasoned scan.
15. **`cmd_record`'s comparison order must put `diff_digest` before `verdict`, not after.**
    Today's `if _exp_v ... elif _exp_d ...` (`:4646-4657`) is a strict if/elif: when a receipt
    disagrees on BOTH fields, only the verdict branch ever fires. F3 keeps the digest mismatch as a
    hard `error` (the forgery-detection axis) while turning the verdict mismatch into a soft
    `verdict_disagreement`; if the digest check stays second (or `elif`) a both-mismatch receipt would
    take the soft path and the harder signal would never surface. The digest check must run
    independently of (and be evaluated no later than) the verdict check.

## 8. File Touch Map

Cross-checked against the manifest's own `write_allowed` lanes
(`docs/superpowers/execution/2026-09-11-v3.6-wide-dispatch/manifest.yaml`); all ten jobs' lanes are
disjoint except the two noted as SHARED RESOURCE below, which the manifest already serializes via
`depends_on` rather than concurrent `write_allowed` overlap.

- `scripts/compound-v-emit-workflow.py` — **SHARED RESOURCE.** Touched by two jobs in the existing
  manifest (`e1-finalizer-record`, wave 1; `e2-provision-engine-c`, wave 2, `depends_on:
  [e1-finalizer-record, scope-workers-provision, validate-keys-advisories]`). 8000+ lines; grep for
  the named symbols in this audit rather than reading linearly.
- `scripts/compound-v-scope-check.py` — docstring/`--help` correction per finding 1 (no functional
  change to `changed_files`/`--preexisting` expected), PLUS a new `--selftest` row per the
  manifest's `scope-workers-provision` acceptance criteria (a worktree repo with a gitignored
  `node_modules/` present and listed in `--preexisting` passes; the same repo without the listing
  is a violation) — the file changes even though its core logic does not.
- `scripts/compound-v-run-codex-worker.sh`, `-cursor-worker.sh`, `-antigravity-worker.sh`,
  `-opencode-worker.sh` — near-identical sibling edits (finding, §3); same case-block shape in all
  four.
- `tests/test-worker-path-transport.sh` — gains the provisioning row; read first to reuse its
  existing stub-worker fixture.
- `scripts/compound-v-validate-manifest.py` — provisioning key validation, `MEMORY_LANE_UNNAMESPACED`,
  and the `reviewer_backend` enum widening all land here; also touches the pre-existing selftest at
  `:5320` (finding 5).
- `examples/manifest.example.yaml` — SHARED RESOURCE class (generated/reference example validated
  by CI, `.github/workflows/validate.yml:120-134`); gains `provision_command` and the namespaced
  memory lane.
- `agents/partition-reviewer.md` — new WARN rows only; this job explicitly must NOT touch the other
  four agent files (owned by `agents-memory-advisor`).
- `schemas/cross-model-receipt.schema.json` — SHARED RESOURCE (schema other tooling/tests read);
  const→enum widening (finding 5).
- `hooks/lane-guard.sh` + `tests/test-lane-guard.sh` — register-lane bootstrap exemption,
  `candidate_runs`, `why` text (findings 6-7). `shellcheck hooks/*.sh` must stay clean.
- `agents/spec-reviewer.md`, `agents/code-archaeologist.md`, `agents/domain-expert.md`,
  `agents/doc-validator.md`, `agents/implementer.md` + `tests/test-agent-memory.sh` — namespaced
  path + advisor-consultation prose (findings 9, 12). Does not touch `agents/partition-reviewer.md`
  (owned by the sibling job above) — the manifest's own job body already says so.
- `commands/v-init.md` + `.claude/settings.json` — Steps 1f/4e (new subsections after the existing
  1e at `commands/v-init.md:225-233` and 4d at `:684-714`); `.claude/settings.json` is also read by
  `_worktree_base_is_head` (finding 11, confirmed harmless) and by CI's own `impacted_map` row
  (`manifest.yaml:70-71`, which asserts `worktree.baseRef == "head"` after the edit — the new
  `advisorModel` key must be added, never replacing the existing `worktree` key).
- `commands/v-review-plan.md`, `skills/compound-v/cross-model-review.md`, `commands/v-dispatch.md`,
  `skills/compound-v/phase-3-parallel-opus-dispatch.md` — the second-opinion ladder prose; only the
  named regions of the shared command files change (both `v-dispatch.md` and phase-3 are otherwise
  large, multi-purpose documents).
- `scripts/compound-v-usage-extract.py`, `scripts/compound-v-usage-aggregate.py`,
  `schemas/job_result.schema.json`, `commands/v-status.md`, `tests/test-usage-workflow.sh` —
  `usage.advisor_calls`, reusing the existing per-message-id dedup (§6); `job_result.schema.json`
  is a SHARED RESOURCE (also touched by `tests/test-engine-c-contract.sh` assertions, none of which
  reference `usage` today per `grep -n "job_result\[|status\|files_changed" tests/test-engine-c-contract.sh`,
  so the new optional key is additive and safe).
- `README.md`, `AGENTS.md`, `TROUBLESHOOTING.md`, `CLAUDE.md`,
  `skills/compound-v/execution-manifest.md`, `skills/compound-v/SKILL.md`,
  `skills/compound-v/routing-policy.md`, `commands/v-orchestrate.md`,
  `skills/backend-launcher/SKILL.md`, `skills/backend-launcher/adapter-codex.md`,
  `docs/superpowers/architecture/native-mechanisms.md` — the documentation wave (F8), depends on
  every implementation job; must read the merged diff from the run baseline rather than from
  memory, per the manifest's own job body.
- `docs/superpowers/architecture/architecture.md` — NOT in this run's write_allowed anywhere;
  refreshed later by `/v:onboard --refresh`, out of scope here (confirmed against finding 9's bare
  memory-path citation there).
