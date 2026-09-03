# Changelog

All notable changes to **superpowers-v (Compound V)** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses semantic versioning.

## [Unreleased]

### Fixed — `search` refreshes the FTS5 lane inline instead of just warning stale (finding 98)

Every reviewer in the 2026-09-03 epic ran Step 0 faithfully and every one of them recalled
against an index **110–118 files behind** the repository — the engine printed the staleness
itself, and the reviewers wrote "treat the empty result as nothing indexed on this." Nothing in
the pipeline refreshed the index automatically: `refresh` was only ever called by
`/v:memory-refresh`, `/v:init` and `/v:adr`. A full FTS5-only refresh of the 128 stale files
found during the probe took **0.38 s** (`--quick` refused it because 128 > 20) — freshness cost
nothing; the only reason it was missing is that nobody wired it. `search` now checks staleness
before it queries and, unless `--no-refresh` is passed, refreshes the FTS5 lane inline first
(one stderr line: `V-memory: refreshed N stale doc(s) before recall (FTS5 lane)`); a repo with
no index yet builds one on the first search. The inline refresh is FTS5-only — it never applies
the `--quick` cap and never touches embeddings, so a file it re-chunks loses its vector until
the next `/v:memory-refresh --with-embeddings`, degrading that file to FTS5-only in the
meantime, never breaking it.

## [3.4.4] - 2026-09-03

Stage 5 of the post-3.4.0 verification program: the first epic Compound V has ever run end to end —
two docs features on one branch, each through triage → pre-flight → manifest → Engine C → review,
in dependency order, under the checkpoint stance. F1's review pass 1 found a real latent bug in a
60-line script that its own tests had not (finding 90); F2's pre-flight measured the committed index
one row stale before a false number could be published (finding 92).

### Added — `scripts/compound-v-dogfood-index.sh` and the generated `docs/superpowers/dogfood/README.md` (epic F1)

A bash-3.2 generator that indexes every `<date>-<feature>-review[-N].md` under `docs/superpowers/dogfood/`
(never an `-impl.md`) into one table — date, feature, pass, verdict, file — with a footer
`Reviews: N · APPROVED: A · ISSUES: I · other: O`, N == A+I+O, idempotent on re-run. The verdict is the
token the anchored `(APPROVED|ISSUES)` alternation matched, not a substring of the line (review-1's
issue 1: `VERDICT: ISSUES — the earlier pass was approved` used to index APPROVED). `tests/test-dogfood-index.sh`
carries the fixtures the review asked for: `## VERDICT: **ISSUES** (4)`, a mid-sentence-only verdict (unknown),
and a lowercase `verdict: approved`. Known, recorded, not fixed: a review file that quotes an earlier pass's
verdict at column 0 above its own is indexed with the quoted value (`grep -m1` takes the first anchored match);
no committed file does that today.

### Added — README "Verification program" section (epic F2)

Three sentences before "Under the hood": what the program is, a root-relative link to the generated index (a
leading-slash link is exempt from the dead-link CI gate, so the form is pinned in the run's acceptance criteria),
and the two counts read from the index footer at the time of writing. The numbers are "as of this writing" by
construction: every review file lands in `docs/superpowers/dogfood/` *after* the index that counts it, so the
committed footer is always one behind the last review — regenerate with the script rather than trust the number.

The eight stages the section refers to, since this is their only citable list: (1) DIRECT attended — one file,
ordinary commit, silent Stop gate; (2) SCOPED — the 3.4.1 triage-size feature run through the SCOPED path itself;
(3) FULL with zero manual interventions — 3.4.2 transcript watch; (4) multi-model — a `backend: codex` job on
Engine C, 3.4.3; (5) the first epic — this release; (5a/5b) V-memory recall real, recall→action; (6) a foreign
repository from `/v:init`; (7) death and resurrection; (8) a perfect pass with a stopwatch.

### Fixed — the index generator's row froze at the FIRST verdict in a file (finding 96)

F1's review pass 2 called this a hazard "not live today": a pass-2 section that quotes pass 1's verdict at
column 0 above its own would be indexed with the quoted value, because the generator took the first anchored
match. The epic's own integration review made it live the same day — pass 1 `ISSUES`, pass 2 `PASS`, row `ISSUES`.
The last anchored match now wins (a review file's final verdict is its last one), and `PASS` — the word
`/v:epic`'s integration review emits — reads as `APPROVED`, since with only the two-token enum the last *matching*
line of that file was still pass 1's `ISSUES`. Two fixtures cover both.

### Fixed — the dead-link CI gate read quoted `[x](path)` examples as links (finding 95)

The epic's final cross-feature integration review — the first ever run — found the composite red on the
dead-link gate with nine "dead links", every one a quoted link example inside a code span or a fenced grep
output in the pre-flight audits, a job prompt and both F2 review files; the reviewer hit the same trap while
quoting the offender. Both features had passed their own three-pass reviews: a per-feature review cannot see
a gate that only reds on the composite, which is what the final review is for. The gate now drops fenced
blocks and strips inline code spans before extracting links. Proven with a replica: nine to zero at HEAD, and
a planted real dead link outside a code span still fails while a quoted one does not.

### Changed — CI shellcheck now covers `scripts/compound-v-*.sh`, not only `hooks/*.sh`

F1's review pass 1 noticed the new generator's shellcheck clause was a one-time check: `validate.yml` linted the
hooks only. All nine `scripts/compound-v-*.sh` are clean under shellcheck 0.11, so the step is widened rather than
a per-test `shellcheck` line added.

### Fixed — a dependent job that ran in a real worktree was recorded, judged and merged as if it had run in the checkout (finding 89)

Finding 60 gave a dependent job a real worktree under `worktree.baseRef: head`, but three other places still carried the 3.0.5 assumption: Record hard-coded "dependent ⇒ direct" and wrote an empty worktree into state; the authority chose its root from state and recomputed an empty diff over the checkout ("forged"); the finalizer looked for the worktree in result/state and refused "resolves to no worktree". All three now read the gate receipt first — the emitter's own `--mode` and `--worktree`, digest-bound — with the baseRef-aware rule as the fallback. Emitter selftest 419/419; authority 82/82.

### Fixed — a running epic was invisible to the banner and to the triage hook (finding 87)

`epic-state.json` carried no timestamp, and the dashboard ages a record by its recorded time only (never an mtime), so the first epic ever run was "age unknown" and never listed as unfinished — and the hook kept sizing unrelated prompts as if nothing were running. Every epic-state write now stamps `updated_at`; the banner names the running epic, and the hook's `--open-jobs` question treats it as active. Selftest 367/367.

### Fixed — a request that names new files beside an existing one no longer sizes as the existing one alone (finding 86)

"Implement F1 per <spec.md>: scripts/new.sh with tests/new.sh" resolved to the spec alone — one docs path, low/low — and was tiered DIRECT for a new script under `scripts/**`. The localizer now collects new-file candidates in the literal-path branch too; any new path makes the confidence `new_file` (never DIRECT) and carries its directory's bands, and several new files are several paths.

### Fixed — `/v:epic`'s documented `spec_path` form refused to init (finding 85)

`compound-v-epic-state.py --init --require-specs` resolved `spec_path` relative to the epic directory only, while `commands/v-epic.md` writes it repo-relative (`docs/superpowers/execution/epics/<id>/specs/<f>.md`); the first epic ever initialised failed on its own documented example. Both forms are accepted now, and a path must still resolve inside the epic directory. Selftest 366/366.

## [3.4.3] - 2026-09-03

Stage 4 of the post-3.4.0 verification program: the first feature dispatched across two backends on
Engine C in one run — a Codex worker builds the deliverable, Claude writes the docs and does the
review. Run r3 proved the multi-model contract's isolation half: the Codex job's worktree sat
outside the repository, the scope gate measured that worker's own tree, and exactly that lane
merged. r3's `state.json` still recorded that job's `session_id` as empty, though — the UUID sat
unread in its events log — so the session-id half is proven separately, by r5's read of the same
job's `thread.started` line (finding 81), not by r3 itself.

### Added — `scripts/compound-v-sandbox-checkout.sh`, built by a Codex worker on Engine C

A byte-identical, git-only checkout helper (`<dest> [--keep-execution] [--empty-pre-eval] [--taxonomy-from <path>]`)
that copies every `git ls-files` path of the current repository into `<dest>`, drops
`docs/superpowers/execution/**` unless asked to keep it, and can empty `docs/superpowers/pre-eval/` —
so a reviewer can drive `hooks/triage-prompt-nudge.sh` (the UserPromptSubmit hook) against a clean sandbox
without touching a run's own working tree, instead of hand-building one. `tests/test-sandbox-checkout.sh`
covers byte identity, dropped/kept execution history, the emptied pre-eval dir, and the refusal on a
non-empty destination. Implemented by a `codex exec` worker (`gpt-5.6-terra`) in its own worktree under
`$TMPDIR/compound-v/<run>/<job>`, gated by the git-derived scope check against that same tree — no
timing or token figures are claimed here; none were measured for this job.

### Fixed — an external worker is told it is unattended, and the authority reads a stricter receipt as honest (findings 82, 83)

The Codex fix job of stage 4 ended its turn by asking for confirmation — nobody answers a headless `codex exec` — and the gate correctly refused the empty diff as an absent implementation; every external worker's prompt file now carries a "You are unattended" section. The authority then filed that honest refusal as `forged` (raw `pass` vs receipt `blocked`, compared without direction) and, once direction was fixed, as `contradicted` (its scope-only re-derivation did not know the gate's absent-implementation rule). A receipt stricter than its raw evidence is the gate refusing itself; the re-derivation now applies the same rule and answers `blocked`. Authority selftest 81/81; emitter 417/417.

### Fixed — the lane guard no longer denies read-only git commands that name a path after `--`

`git show <sha> -- <path>`, `git log -- <path>` and `git diff -- <path>` write nothing; the guard's `--` rule now applies to the writing subcommands only (`checkout`, `restore`, `reset`, `clean`, `add`, `apply`, `stash`, …). The stage-4 reviewer had been denied reading the very commit it was reviewing. Decision table: three cases.

### Fixed — an external worker's thread id reaches state and the result (finding 81)

The wrapper agent returns only status, worktree and summary, so nothing on Engine C carried the Codex worker's `job_result.session_id` into `state.json` — the review of the first merged Codex job found `session_id: ""` beside an events log that held the UUID. Record now reads the `thread.started` line of the events log the worker wrote (UUID-validated) into the job's state and result; `/v:resume` can name it to `codex exec resume`.

### Fixed — an external job's gate measures the worker's worktree, and its wrapper never claims the checkout (findings 78, 79)

The first Codex job that actually ran on Engine C (gpt-5.6-terra, its own worktree under `$TMPDIR/compound-v/<run>/<job>`, a UUID thread id, 22/22 tests) was still refused twice over: the emitted gate ran in direct mode against the checkout — the wrapper's cwd — and charged the job with the run's own bookkeeping files; and `register-lane` had recorded the checkout as the wrapper's "worktree", which the lane guard's first-match cwd fallback then used to attribute the sibling Claude worktree job to the wrapper and deny its writes. Now an external job's gate runs in worktree mode at the tree the wrapper returned; a wrapper is listed under `wrappers` and never claims a worktree; and `hooks/lane-guard.sh` resolves a cwd by the LONGEST matching worktree prefix (decision table: a root claim no longer shadows a nested worktree's job).

### Fixed — an external job's wrapper agent is spawned as a Claude model, not as the backend's (finding 77)

The first non-Claude job ever run on Engine C died before its first tool call: the emitter wired the job's resolved model into `agent()` for every job, so the Claude wrapper that runs the `codex` launch command was asked to be `gpt-5.6-terra`, which the harness refused. The wrapper is now spawned as the Claude light model (`agent_model`, never Haiku) and the backend's model reaches the launch argv only. Emitter selftest 413/413.

### Fixed — an external worker's cap fits inside the harness Bash ceiling, and the wrapper is told to wait (finding 75)

The emitted prompt for a `codex`/`antigravity`/`cursor`/`opencode`/`devin` job now tells the wrapper agent to call Bash with `timeout: 600000` — the harness maximum — and `build_launch_argv` caps the worker's `--timeout-sec` at 480 so the worker plus its own test floor finish inside it. Before this a `timeout_sec: 900` job would have been killed from outside with nothing recorded, and the default 120 s would have detached the worker to the background. Found by reading the emitted stage-4 script before launch.

## [3.4.2] - 2026-09-03

Stage 3 of the post-3.4.0 verification program: a FULL normal task, run through the pipeline with zero
manual interventions. The feature is the mechanism the maintainer endorsed after using it by hand
through five runs of 3.4.1 — reading a live worker's transcript surfaces a problem minutes before the
gate records it.

### Fixed — the Record stage passed the gate receipt inline in argv, and the harness clamp refused it (finding 69)

Stage-3 dogfood: the review job's Record command carried the receipt as `--verdict-json '<json>'`; once the receipt quoted a test checker with `; do … done` or a backtick, the per-spawn `bashCommandClamp` refused the command as "structure the clamp cannot verify", the transport agent reported honestly, and the wave halted with the review written but unrecorded. `record` now takes `--verdict-file <receipt path>` bound by `--expect-verdict` and `--expect-diff-digest` (a rewritten receipt is recorded as an error, never as success); the emitted script uses the file form whenever the gate wrote a receipt and keeps the inline form only for a receipt-less gate failure. Emitter selftest 410/410.

### Added — read the workers' transcripts before their results (`compound-v-transcript-watch.py`)

A read-only, advisory script watches a run's live Workflow agent transcripts and reports five mechanical
signals, one line each, with no model in the loop: **`out-of-lane`** (a Write/Edit or Bash redirect
outside the job's `write_allowed`), **`wrong-cwd`** (a `register-lane` whose isolation or cwd disagrees
with the manifest), **`error`** (a Bash result carrying a traceback, permission denial, or a non-zero
exit), **`stall`** (no tool activity past a threshold on an agent that has not returned), and
**`denied`** (a lane-guard `PreToolUse` denial). It never writes into the run directory, never acts on a
signal, and exits 0 on every advisory path. Discovery needs no new state: it scans the session's
Workflow transcripts for the run directory's own absolute path — every worker's `register-lane` call
carries it — and the newest matching workflow wins, so `--wf`/`--transcripts` are overrides, not
requirements. `/v:status --live` runs it once after the state table; `/v:dispatch` runs it every
two minutes in the background as its own step and treats `out-of-lane`/`wrong-cwd` as reason enough to
`TaskStop` and re-orchestrate early.

### Fixed — review-1's ten findings against the watcher (detector precision, tick-safety, wiring)

A first review pass against the watcher's own real transcripts (`docs/superpowers/dogfood/2026-09-03-v3.4.2-transcript-watch-review-1.md`)
found ten issues, closed in a second wave: `out-of-lane` no longer fires on a Bash redirect or a path
outside the repository (issue 1); `denied` and `error` now anchor to the matching transcript line
instead of a generic substring match, so quoting the lane-guard's deny text or the word `BLOCKED` in
documentation no longer trips a false positive (issues 2, 2b); `register-lane` resolution survives a
poll landing between the tool call and its result instead of leaving the agent permanently
`(unregistered)` (issue 3); default transcript discovery degrades to an explicit no-match message
instead of a traceback when the run directory sits outside a git checkout (issue 4); the test suite
gained one fixture per false-positive class plus a discovery test exercising the untested default path
(issue 6); `/v:dispatch`'s background-watch guidance moved out of step 6's prose into its own numbered
step, keeping step 6 narrowly scoped as the archaeology audit required (issue 8); and dead code in the
state-save path was removed (issue 10). `/v:status --live` gained explicit
`{{args}}` flag-parsing prose and the same degrade-to-one-line contract every other optional section in
that file already carries (issue 5).

### Fixed — a finished run's lane map claimed the checkout forever (finding 68)

A direct job registers the repository root as its "worktree"; the lane guard's liveness test was "does a named worktree still exist" — always true for the root — so every historical run with a direct review job kept claiming the checkout, and on 2026-09-03 the live guard denied both pre-flight auditors of the next feature as `spec-review-3` of a run MERGED an hour earlier. The guard now skips runs whose `state.json` phase is MERGED or BLOCKED, the finalizer deletes `lane-map.json` at a terminal phase, and the file is gitignored (runtime state; the receipts hold the durable cwd). `tests/test-lane-guard.sh` pins both directions.

## [3.4.1] - 2026-09-03

Stage verification, cycles 1 and 2 (DIRECT attended, then SCOPED as the feature below), 2026-09-03 — the first real request after 3.4.0 got no triage at all, and the fixes under "Fixed" further down came out of those two cycles.

The size of a code change reaches the tier. An eight-request probe of the 3.4 scorer found that any
change under `scripts/**` was FULL by taxonomy glob regardless of size, a README typo was FULL from
content-pattern noise on ordinary prose, and free-text localization scanned hundreds of files for
common words. This release answers with four maintainer decisions plus one finding from stage-2 prep,
landed as five parallel jobs (A/B/C/D/E) and reviewed against the spec's feature-level acceptance
criteria.

### Added — T3 may demote a broad-glob FULL to SCOPED (`compound-v-preeval.py`, decision 1)

`match_path` now returns `broad: bool` per row (true for a glob containing `**` or ending in `/*`, no
file-counting). When every T1 row that produced the bands is broad, no resolved path is sensitive, and
no content override fired, the scorer runs one light T3 classify even though T1 already banded:
`plumbing`/`user-facing-minor` with `fan_out ≤ 2` demotes the bands to `(medium, medium)` → SCOPED;
`user-facing-major`/`unknown` leaves FULL unchanged. DIRECT for code stays unreachable. The record
carries `t3_demotion: {from, category, applied}` beside the decision either way, so the demotion is
auditable evidence, not a silent reclassification.

### Added — SCOPED+ for small edits on sensitive paths (decision 3)

A sensitive path with an `exact` localization, `fan_out ≤ 2`, and a `plumbing`/`user-facing-minor` T3
category now resolves to `SCOPED_PIPELINE` with `flavor: "scoped_plus"` instead of a flat FULL — bands
`(medium, medium)`, `override_fired: null`. Any other sensitive case is still FULL, and `.pem`/`.key`/
`.env` and `.github/**` are on a hard `NEVER_DEMOTE_GLOBS` list that is never demoted. This
repository's own taxonomy now marks the enforcement chain itself sensitive — `compound-v-scope-check.py`,
`compound-v-integration-gate.py`, `compound-v-validate-manifest.py`, `compound-v-emit-workflow.py`,
`compound-v-emit-preflight.py`, `compound-v-preeval.py`, and `hooks/**` — so a small edit there is
SCOPED+ (mandatory deep review + a cross-model second opinion + the human accept), while a small edit
to any other script (the scorecard renderer, say) is plain SCOPED. `compound-v-validate-manifest.py
--require-triage` now rejects a `scoped_plus` manifest without a `type: review`/`tier: deep`/
`backend: claude` job, and a new `--require-cross-model-receipt <path>` validates the receipt against
the new `schemas/cross-model-receipt.schema.json` (`run_id`, `pre_eval_id`, and a `diff_digest` that
must equal the sealed patch's own sha256) — `/v:dispatch` step 8 runs the Codex review and writes it for
`scoped_plus` waves before the review gate. `cross_model_review_for` gains a `flavor` parameter
(archaeology constraint 11): a `scoped_plus` record or manifest gets a mandatory second opinion
regardless of the tier it maps to, so `/v:dispatch` never reads "no by default" for the one SCOPED
shape the flavor exists to review harder; `skills/compound-v/cross-model-review.md`'s CLI example
threads it.

### Fixed — prose no longer counts as impact, and a plain word is never searched (decision 2, the README/free-text finding)

The taxonomy gains an optional `content_scan_exclude` glob list (this repo sets `["**/*.md", "**/*.py", "**/*.sh"]` — source too, after review-1 showed `%s` and `timeout` in 42 of 44 scripts vetoing the demotion; config files stay scanned): a path
matching it skips content-pattern matching entirely, so a README mentioning "consent" or "timeout" in
the course of documenting a consent gate no longer scores `impact: high` from the word alone — the
path rows and `sensitive_path_list` still apply in full. On the localizer side, `extract_query_tokens`
now keeps only identifier-shaped candidates (path-like, backticked/quoted, `snake_case`, `CamelCase`,
dotted, CSS-ish); a request with no such token is `failed` immediately, with no repository scan. A
named file that does not exist but whose parent directory does now resolves `confidence: "new_file"`
(T1 runs on the directory's glob; Layer B's DIRECT predicate still requires `exact`, so a new file is
never DIRECT). Two more defects the stage-2 request itself exposed while writing this: a literal path
followed by sentence punctuation (`hooks/triage-prompt-nudge.sh.`) wasn't resolved — the strip set now
drops a trailing `.`/`?`/`!` (never an inner one) — and a literal path whose file exceeds
`MAX_FILE_READ_BYTES` used to turn the whole localization `ambiguous` (FULL by override #1 regardless
of size); it now stays `exact` by name and adds a `content_scan_incomplete` flag that the scorer treats
as impact-raising instead — fail-closed on impact, not on localization.

### Added — a SCOPED job runs the tests that reference what changed, never the whole suite (`compound-v-fastpath-run.py`, decision 4)

`resolve_test_commands` gains `tier` and `referencing` parameters: for `scope == "impacted"`, an
unmapped path now resolves to `full_command` only when `tier` is FULL or absent; at SCOPED or DIRECT it
resolves to `referencing_tests(repo, changed_paths, cap=5)` — test files under `tests/`, `test/`,
`spec/`, `__tests__/`, `*_test.*`/`test_*.*`/`*.spec.*` whose first bytes mention the changed path's
basename or module name, language-agnostic, bounded read, sorted, capped at 5 beyond the impacted set.
None found → the floor only, with an explicit `unmapped: referencing tests found none — floor only at
tier SCOPED` note rather than a silent full run. `resolve_from_manifest` now threads the manifest's
`triage.tier` and computes `referencing` from the worktree; FULL is unaffected. `execution-manifest.md`
and `agents/spec-reviewer.md` §3.3 now say what a SCOPED job owes in tests.

### Added — T3 finishes headlessly, inside the hook (`compound-v-classify-request.py`, `triage-prompt-nudge.sh`, finding 50)

`compound-v-classify-request.py --classify-headless` runs one nested `claude -p --model <resolved
light> --tools ""` (Never Haiku — the model is resolved through `compound-v-resolve-model.py --backend
claude --tier light`) under the timeout supervisor, stdin closed, capped at 15 s + 3 s grace; on any
failure it falls back to the existing read-only Codex classify route, else `unknown`. The `hooks.json`
registration for `UserPromptSubmit` — and only that event — rises from `timeout: 10` to `timeout: 25`
to fit the classify's own budget; the hook only pays it on `needs_t3`, so the ordinary prompt keeps its
~1 s path. On `needs_t3` the hook now runs the classify and re-invokes triage with `--t3-category
<enum>` (or `unknown`, recorded as FULL) instead of degrading to a printed reminder; the reminder
remains only for an engine failure. `/v:triage` documents the headless route as the default and the
Task route as the fallback. (Implementation note: `--tools` is a variadic CLI flag that swallows a
trailing positional, so the prompt must come immediately after `-p`, before `--tools ""` — the argv
builder and its selftest pin the order.)

### Fixed — every consumer of the test slice knows the 3.4.1 label (three review passes)

Three review passes over the feature found the same defect on three seams: a producer's new field (`scope: impacted+referencing`, `selected_count`) that a consumer did not know. The five external workers' `tc_validate` refused it as malformed before the model ran (pass 2); `schemas/job_result.schema.json`'s `tests.scope` enum did not name it and the native emitter's `TESTS_SCOPES` filter silently downgraded it to `impacted` (pass 3); the backend-launcher skill, the five adapter docs and four "unmapped ⇒ full_command" sentences still described the old rule. All closed; `tests/test-engine-c-contract.sh` pins each worker's validator against the real slice and reds on the previous code, and the emitter's selftest pins the label surviving translation verbatim. The cycle cap was three passes: these were closed by the orchestrator with tests, not by a fourth pass.

### Fixed — the phase advance to MERGED was a prose step; fourteen finished runs silenced the triage hook

`finalize-wave` integrated, committed and pruned, but never touched `state.json.phase`; only `/v:dispatch` step 9 (a human step) wrote `MERGED`. Every run of the 3.4.0 night sat at `PARTITION_VERIFIED` after a successful merge, the dashboard's `resume` named fourteen "unfinished" runs for 72 hours, and `triage-prompt-nudge.sh` stayed silent for the whole repository. The finalizer now moves a run to `DISPATCHED` while waves remain and to `MERGED` once every manifest job is integrated (`merged_at` recorded), and commits the run's own record in a second, plain commit — never folded into the wave commit the authority proves. Sixteen historical runs whose every wave integrated are retro-marked `MERGED` with a note.

### Changed — the triage hook asks a narrower question than the banner

`compound-v-dashboard.py resume --open-jobs` lists only runs the pipeline may still move by itself — a pending/running job, not `BLOCKED`; the hook asks with it and a 6-hour window, the SessionStart banner keeps its 72-hour "anything unfinished" semantics. A superseded or halted run no longer blocks sizing of a new request.

### Fixed — `.run.lock` had been committed in 26 run directories

The per-run mutex is gitignored and untracked; the finalizer's bookkeeping commit resets it explicitly.

### Fixed — a dependent worktree job could never integrate on Engine C

A 3.0.5 rule ran any job with `depends_on` in the main checkout (worktrees then branched from the default ref) while the manifest kept `isolation: worktree`; the prompt said "you are in your own worktree", `register-lane` said `direct`, the gate ran direct, and the finalizer — reading the manifest's label — refused with "resolves to no worktree". Never seen before because every earlier dependent job was manifest-direct. Now: with `worktree.baseRef: head` (3.4.0) a dependent job gets a real worktree; without it the three layers say the same thing, and the finalizer takes the mode from the emitter-authored gate receipt. Stage-2 r2, finding 60.

### Fixed — a halted run is marked BLOCKED, not left PARTITION_VERIFIED with jobs pending

When a wave is refused (by the authority, or because a job did not reach `success`) the workflow halts; the finalizer now writes `phase: BLOCKED` with the reason and time. The banner still lists the run as unfinished; the triage hook's `--open-jobs` question excludes it, so a halted run no longer silences the sizing of the follow-up that repairs it.

### Fixed — a partially merged wave now commits its own record

Stage-2 r1 merged four jobs and refused one: HEAD moved, but the finalizer's bookkeeping commit was gated on `integrated`, so state, receipts and results stayed untracked — the audit-trail gate reds on push. The bookkeeping commit now follows every wave that produced a commit.

### Fixed — the validator said "valid" for a manifest PyYAML refuses

Stage-2 dogfood: the run's own manifest carried an unquoted `title:` with an inner `": "`; PyYAML rejected it, the validator announced the rejection on stderr and then consulted the embedded subset parser, which accepted it, and reported the document valid. A document the reference parser refuses is not a valid manifest: when PyYAML is importable and rejects, `validate_text` now returns that as a violation (`ManifestParseError`), and the subset parser is used only on the machine without PyYAML. Selftest added.

### CI

The fifth review record reproduced the anti-ruflo grep pattern literally and tripped the gate on 0d751b1 while the release workflow, sharing only a push event, published v3.4.0 anyway. The record is fixed and the release job now waits for "Validate Plugin" on the same commit and refuses to publish on red.

## [3.4.0] - 2026-09-02

Native-first: the cut list from [`2026-09-02-viability-audit.md`](docs/superpowers/architecture/2026-09-02-viability-audit.md) §7, decided by the maintainer through four structured questions and shipped through [`docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md`](docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md). The constraint: the functionality stays, but leans as far as possible on Claude Code's own mechanisms.

### Removed — three schedulers and a goal engine, for `/goal` + `/loop` + `/schedule`

`hooks/epic-goal-stop.sh` Feature A (the armed goal condition, its counter, `stop_hook_active` handling), `scripts/compound-v-epic-watch.py`, and `scripts/compound-v-headless-shim.py` are deleted — ~2 000 lines, none of which had ever fired, because no epic in this repository's history has run. `scripts/compound-v-epic-state.py` drops the goal surface (`--arm-goal`, `--goal-status`, …) and the watch surface (`--watch`, `--claim-resume`, `--liveness`, the watcher registry, …); the marathon loop, arbiter, and breakers are untouched. `/v:epic` now *offers*, never arms silently: `/loop 30m /v:epic <epic-id>` to keep resuming in this session, or a `/schedule` routine for the cloud, plus `ProposeGoal` (or a printed `/goal <condition>` where the tool is absent from the listing) for the harness's own goal evaluator. `/v:epic` is re-entrant, so every firing is a plain resume, and it stops its own loop/schedule once the epic is terminal.

### Removed — `tool-failure-ledger` and its `PostToolUseFailure` registration

Registered in 3.3.0, read by nothing since. `hooks/tool-failure-ledger.sh` and the `PostToolUseFailure` entry in `hooks/hooks.json` are gone; `native-mechanisms.md`'s event table drops from 8/10 to 7/10 documented events, with the row kept and marked "removed 3.4.0 — re-register when a consumer exists."

### Removed — `/v:dashboard serve`

The HTTP server, its rebinding guard, and every serve selftest are gone. A live run is watched natively — `/workflows` and `/tasks` — and `emit`'s static snapshot is unchanged.

### Changed — `UserPromptSubmit` now runs the triage scorer, not just a reminder

`scripts/compound-v-preeval.py` gains a `triage` subcommand — the body of `/v:triage` T2, now importable and callable without a monkey-patch (`run_preeval` takes a real `binding=None` parameter). `hooks/triage-prompt-nudge.sh` calls it, bounded, on the first non-slash, non-question prompt of a session, writes the scored record (uncommitted — `/v:orchestrate` commits it at bind, a DIRECT commit includes it by hand), and injects the tier and predicates into context; on any failure or timeout it falls back to today's reminder text, unchanged. `/v:triage` stays for the T3 escalation path and manual runs. The once-per-session marker is retired — the record itself is the marker.

### Changed — attended DIRECT is an ordinary commit

`/v:triage` T4's DIRECT path is now: implement, run the floor, commit on the current branch, including `docs/superpowers/pre-eval/<id>.*` for the Stop gate to see. Phase L (`--land`, the CAS/lock-ref/throwaway-index machinery) is retitled "unattended landings only" and scoped to `/loop`- or `/schedule`-driven sessions and `--permission-mode dontAsk` — where no human sees the diff before it lands.

### Changed — the scorecard reads run results, not a jsonl the engine never wrote

`compound-v-scorecard.py --update` gains `--from-runs <execution-root>`, building one record per `<run>/results/<id>.json` (Engine C's real output) instead of relying solely on `task-outcomes.jsonl`, which Engine C has never appended to. Legacy `task-outcomes.jsonl` lines are still read and unioned in. `finalize-wave` runs the update after every successful wave, best-effort, never fatal. `compound-v-update-memory.py` is **not** deleted — the pre-flight audit found `append_line` imported by `compound-v-triage-outcomes.py` and `compound-v-preferences.py` at module load; only its prose role as the task-outcomes appender goes.

### Changed — the scope gate keeps no carve-outs; the pipeline writes no bytecode and no bookkeeping between gate and authority

Two exemptions were added to `scripts/compound-v-scope-check.py`'s changed set during this release's development and both are **withdrawn**. The fourth review pass demonstrated the first end to end: an unchecked hash-based `.pyc` (CPython never validates one against its source) planted at `scripts/__pycache__/compound-v-scope-check.<tag>.pyc` is invisible to `git status` by `.gitignore` and — under the extension exemption — invisible to the gate, and it is then **executed in place** by `hooks/lane-guard.sh`'s loader on every `Write`/`Edit`/`Bash` call and by `compound-v-integration-gate.py`'s importer of the same module, returning an `is_allowed` that approves every out-of-lane write. The second exemption forgave `docs/superpowers/memory/triage-outcomes.jsonl` and `worker-performance.jsonl` by name, on the ground that neither lands through merge-back — true, and the wrong door: the pipeline commits the first **by name** in three documented steps, so a worker's unreported rewrite rode the next such commit into a stream that resolves last-writer-wins and feeds the Tier-2 precision gate.

The changed set is now three union terms minus only the direct-mode `preexisting` snapshot. Nothing is forgiven by extension and nothing by name. The two honest cases the exemptions served are handled upstream instead:

- **Nobody writes bytecode.** Every python command the emitter writes into a workflow script, a clamp rule or a prompt carries `-B` right after the interpreter (rule and command must match literally, or a clamp that admits a prefix denies the one command a stage may run); `compound-v-scope-check.py`, `compound-v-integration-gate.py` and `compound-v-emit-workflow.py` set `sys.dont_write_bytecode` before any sibling import; and the Implement prompt tells the worker to use `-B`/`PYTHONDONTWRITEBYTECODE=1`.
- **Nobody reads an in-tree cache.** `-B` and `PYTHONDONTWRITEBYTECODE` stop Python *writing* a cache, never *reading* one, so the two loaders that import the matcher redirect the lookup itself: `hooks/lane-guard.sh` exports `PYTHONPYCACHEPREFIX` into a private per-invocation directory (falling through without it if that cannot be created — the guard fails open by contract), and the authority sets `sys.pycache_prefix` around `exec_module`.
- **No bookkeeping between a gate and its re-derivation.** The `merge_pending` `actual` is appended by `finalize-wave` once the integration authority has run over the wave — run, not permitted, so a refused wave still records an outcome — and before the pathspec-restricted commit, which never sweeps it in. `record` writes nothing outside the run directory. The digest exclusions in `compound-v-integration-gate.py` and `compound-v-emit-workflow.py` now cover the run directory and nothing else.

Pinned by tests, not by comments: `compound-v-scope-check.py --selftest` plants `scripts/__pycache__/x.cpython-314.pyc`, a `payload.py` and an `id_rsa` under `__pycache__/`, and both outcome streams, and requires **all** of them to BLOCK outside the lane; `tests/test-lane-guard.sh` forges a real unchecked hash-based `.pyc`, asserts it *would* execute without the redirection, and then shows the guard still denying an out-of-lane write; `compound-v-emit-workflow.py --selftest` drives register-lane → gate-receipt → record → the real authority → finalize-wave over a direct-mode job and requires the receipt to come back neither forged nor contradicted.

### Changed — implementers arrive as a role with a turn cap and the official Opus 5 conciseness guidance

Every Claude implementation job is now spawned as `agents/implementer.md` (`agentType: <plugin>:implementer`); `type: review` still spawns `spec-reviewer`, and the other reviewer-ish types stay anonymous rather than being told to write inside a lane. Until now an implementer arrived with no role at all: the whole of its contract was whatever the emitted prompt restated inline, it inherited the session's own turn budget, and nothing carried the model's own guidance on scope, narration or deliverable length.

Arriving as a role is also **the only native way a workflow job gets a turn cap**. `maxTurns` is a field of an agent *definition*; the workflow `agent()` options are `label`, `phase`, `schema`, `model`, `effort`, `isolation`, `agentType` plus `disallowedTools` and `bashCommandClamp` — there is no equivalent. `implementer` declares `maxTurns: 80`, `spec-reviewer` `maxTurns: 80`, and `scripts/lint-frontmatter.py` now rejects a malformed `maxTurns` (a string, a float, a bool, anything below 1), because the runtime ignores one silently and the agent then runs uncapped while its file says otherwise. The inline-definition fallback — the path taken when the plugin is not registered in the session — carries the definition body verbatim so the guidance survives, and **logs that the cap is lost on that path**, since an inline spawn is not a definition and `agent()` cannot re-impose it.

Three things follow from Anthropic's Opus 5 guidance, and each is a subtraction:

- `agents/implementer.md` carries the official scope, cadence and deliverables snippets verbatim. Effort buys *thinking*, not output length, so length is asked for explicitly instead of hoped for.
- `render_worker_prompt` adds **no** "verify", "re-check" or "report per item" imperative of its own. Explicit verification instructions make this model verify more than the task needs, and the Gate re-derives every enforcement fact from git after the worker is gone. The task's own `body` may ask for whatever it likes; the template asks for the lanes, the acceptance list and the cap.
- The worker prompt states the job's turn cap — `max_turns` from the manifest, else the tier default (`light` 30, `standard` 50, `deep`/`frontier` 80). For an external worker that is a budget it is *told*, not a ceiling any runtime imposes, and it says so. The manifest validator already accepts the key: it rejects no unknown per-job key by design (verified against `examples/manifest.example.yaml` + `max_turns: 40` → `valid`).

**Effort is now a policy, by job kind** (`routing-policy.md` § Effort by job kind, `execution-manifest.md`, `commands/v-orchestrate.md` step 4): new code and design decisions `deep`·`high`; a **fix job minted from a review finding** `medium`, because the finding already names the file, the defect and the bar and high effort there re-derives a conclusion the job was handed; a reviewer `high` on its first pass and `medium` on a re-pass over the same diff; the pipeline's own transports `low`.

`/v:init` gains one **offer** (never a write): `CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT=0` in the user's own `~/.claude/settings.json` `env` block — the variable is a binary-verified toggle between the harness's two built-in system prompts (`"1"` selects the SIMPLE/short one; `"0"` turns it off and selects the long preset that carries the anti-verbosity rules), so the offer recommends `"0"`. Sourced honestly beyond that: whether the long preset actually helps is a **community claim**, this project has measured **no** before/after difference in length, latency or cost, and it publishes no number for it.

### Fixed — the lane guard's PATH case could not fail, and the published cost had been measured on the wrong path

Two items from the seventh review pass, both about evidence rather than behaviour.

**The `PATH` case proved nothing.** `tests/test-lane-guard.sh` asserted that an executable-but-broken `python3` first on `PATH` still produces a DENY — and it would have, under the plain ordering the viability ladder replaced, because `/usr/bin/python3` is probed *first* and the broken one is never a candidate the ladder has to step over. The case that discriminates is the one the hook's header actually claims: `PATH`'s python3 imports yaml and the OS one does not, so the **probe** and not the order decides. It cannot be produced by editing `PATH` alone, so the suite now drives a copy of the hook whose OS candidate is the dead interpreter, asserts the log **names the interpreter it used** and the one it passed over, and then plants the pre-change order (`_cv_can_yaml() { return 0; }`) and asserts the same write sails through in complete silence. That is the third check in three passes found to be incapable of failing. The hook now logs its chosen interpreter on **every** path, not only the fallback ones — the pick was otherwise unobservable on the one path where it matters.

**One probe on the healthy machine, and the cost re-measured for both populations.** The `-c pass` probe moved out of the `import yaml` loop into its own, entered only when nothing on the list has PyYAML. Stated precisely, because the tempting claim is wrong: this changes **nothing** for the ordinary machine (it already broke out on its first candidate) and nothing for a machine with no PyYAML anywhere (still three probes); it removes one probe from the machine whose **second** candidate has PyYAML, 3 → 2.

Re-measured 2026-09-03, 50 invocations per cell, **two** qualifying rounds (floor 25.6/25.9 ms opening, 26.2/26.3 ms closing), macOS 26.5.2 / arm64, `/usr/bin/python3` 3.9.6, against a sandbox project carrying copies of this repository's 48 run directories:

| path | probes | measured |
|---|---|---|
| unresolved, first candidate has PyYAML | 1 | **149 ms** |
| unresolved, second candidate has PyYAML | 2 | ≈175 ms (**derived**, not timed end to end) |
| unresolved, no candidate has PyYAML | 3 | **200 ms** |
| resolved, write in lane | 1 | **240 ms** |

The 167/245 ms published one entry ago is **superseded as noisy, not withdrawn as wrong** — same protocol, same code on both paths, ordinary round-to-round variation on a shared machine. What *was* wrong is a method error worth naming: the first attempt at this round drove the "unresolved" loop from the checkout itself, which a **live** run's lane map claims, and produced 247 ms — the *resolved* path wearing the wrong label. Measure the unresolved path somewhere actually unresolved, and read `CV_LANE_GUARD_LOG` back to confirm which one you hit. `README.md`, `AGENTS.md` and the hook's own COST header all carry the table, the method and the date.

### Fixed — the lane guard read no manifest written with a folded scalar

The `PreToolUse` lane guard reads the acting job's `write_allowed` out of the run's `manifest.yaml`. Without PyYAML it falls back to the embedded subset parser in `compound-v-validate-manifest.py`, and that parser could not read the two shapes `yaml.safe_dump` emits for **every manifest this pipeline writes**: a scalar folded across lines at the dump width, and a block sequence sitting at its parent key's own indentation. The parse stopped at the first of either and every later key was dropped silently — `jobs:` included. Driven with run r5's real manifest on a machine whose `command -v python3` was a Homebrew build with no PyYAML (while `/usr/bin/python3`, which ships it, sat right beside it), the guard resolved the job, found no jobs in the manifest, logged `ALLOW (guard degraded)` and **let the out-of-lane write through**. A guard that fails open on the ordinary output of the tool that writes its own input is not a guard.

Three changes, each pinned by a test that fails against the old code:

- **The subset parser reads what `safe_dump` writes.** Folded plain and quoted scalars are rejoined; a block sequence at its parent key's own indent is parsed; a block scalar (`key: |`) is consumed and flattened onto one line — lossy, and said so — instead of ending the document. Measured, not asserted: over **all 47 manifests under `docs/superpowers/execution/`** — one per run directory, counted at commit `3b0550e`, where the sentence that stood here said 35 and the sixth review pass, reading an earlier commit, counted 46 — both parsers read every file without raising, and the **only** field they disagree on anywhere is `jobs[].body` — the block scalars the subset parser flattens. Set `body` aside and the **jobs lists are identical 47/47**, as is every other key in the document; include it and 12/47 match byte for byte. `write_allowed`, which is the field the guard reads, is among the ones that never diverge.
- **A truncated parse raises instead of returning nothing.** A document containing a top-level `jobs:` that yields no jobs is a parse failure, not a manifest with no work: every consumer spells that read `.get("jobs") or []`, so the two were indistinguishable downstream. `_mini_yaml` now raises with the reason and the remedy.
- **The guard prefers an interpreter that can `import yaml`.** `CV_PYTHON` is honoured verbatim; otherwise `/usr/bin/python3` is tried before the one on `PATH`, and if the running interpreter has no PyYAML the manifest read is handed to the first candidate that does — announced **by path** in the log. This release resolved that preference lazily and declined to probe; **the sixth review pass overturned that** — see below.

`tests/test-lane-guard.sh` gains a run whose manifest carries a folded top-level scalar and a folded acceptance item, and requires the same DENY under the fallback parser (driven through an interpreter with PyYAML blocked on `PYTHONPATH`), under a PyYAML interpreter, and under the default `PATH`.

### Fixed — the lane guard chose its interpreter by guessing, and could choose one that cannot run

The fix above picked the guard's interpreter by **ordering** the candidates and hoping: take the first path that is executable, and discover `import yaml` later, inside the payload. `-x` is not "can run". A wrapper script, a stale shim, a virtualenv whose framework moved — every one of them is executable and exits non-zero on anything. Picked as *the* interpreter, the payload never runs, the wrapper discards its empty output, and `hooks/lane-guard.sh` **produces no decision at all**: a silent no-op that is indistinguishable, from the outside, from an allow. That is the exact failure mode the fifth pass had just spent a section closing, re-introduced one layer up.

The pick is now a **viability ladder**, resolved before anything else runs: the first candidate for which `<py> -c 'import yaml'` exits 0; failing that, the first for which `<py> -c pass` exits 0, logged by path with its missing PyYAML named; failing that, a log line saying the guard is **INERT for this call** and the write was not checked. Fail-open remains the contract — it is never silent. `CV_PYTHON` is still the only candidate when set, and is now put through the same ladder: obeying an override is not the same as pretending a dead interpreter works. `/usr/bin/python3` is still tried before `PATH`'s, but only as a **cost** heuristic (which candidate answers first), never as a correctness claim — the probe decides.

`tests/test-lane-guard.sh` proves it behaviourally: an executable-but-broken `python3` first on `PATH` and, separately, first in the candidate list, still produce a DENY, with the log naming the interpreter used and the one passed over; a list with nothing runnable on it produces no output, exit 0, and the INERT line; and a planted mutation that neuters the probe (`_cv_can_yaml() { return 0; }`) makes the same out-of-lane write pass **in complete silence**, which is what the assertion is for. The two checks that used to stand here grepped the hook's own source for a variable name and for the words `RESOLVED LAZILY` — a rewrite of the mechanism would have kept both green — and are gone.

**The subset-parser claim is now measured.** Over all **47** manifests under `docs/superpowers/execution/` — one per run directory, counted at commit `3b0550e`; the review that asked for this counted 46 at an earlier commit — both parsers read every file without raising, and the only field they disagree on anywhere is `jobs[].body` — the block scalars the subset parser flattens. With `body` set aside, the **jobs lists are identical 47/47**, `write_allowed` included; counting `body`, 12/47 match exactly.

**And the ambient cost is re-measured, because it had stopped being true.** 50 invocations per path, old hook and new interleaved in one round, macOS 26.5.2 / arm64, `/usr/bin/python3` 3.9.6, against a project carrying copies of this repository's 47 run directories, bare-interpreter floor 30 ms taken in the same round:

| path | before | after |
|---|---|---|
| unresolved (ordinary human session) | 120 ms | **167 ms** |
| resolved, write in lane | 202 ms | **245 ms** |
| resolved, write out of lane (deny) | 201 ms | ≈ the allow |

Those rows are **one** qualifying round — the machine spent the rest of the evening running this dogfood's other jobs, and every later attempt was discarded for a floor above ~31 ms rather than published. The `+45 ms` is the probe, corroborated on its own (~44 ms measured standalone) and by a second quiet round of the old hook alone, and it is the price of a guard that cannot silently no-op. The **47–81 ms this changelog and `README.md` published two entries ago is withdrawn**: the *unchanged* hook measures 120 ms on the path that published 47. The cause is this release's own `PYTHONPYCACHEPREFIX` defence, added by the fourth review pass after that measurement and never re-measured — a redirected bytecode-cache lookup that `PYTHONDONTWRITEBYTECODE` forbids populating recompiles every stdlib module from source on every invocation (31 ms plain → 90 ms with both, measured directly). It is worth its ~59 ms; it was not free, and the numbers that stayed in three files said it was. A number measured before a change is not a number about the code after it.

### Fixed — the register-lane command the emitter wrote could not be run

The Implement prompt handed every worker `--cwd "$PWD"`. The per-spawn bash clamp matches a literal command prefix and refuses a command whose structure it cannot verify, so a shell substitution is denied outright — and in run r9 the **first command of the job** was denied for it, which is the one denial that leaves the job unregistered and the lane guard with nothing to resolve for the rest of its life. The prompt now tells the worker to run `pwd` (an admitted form) and write the printed path literally in place of `<ABSOLUTE_CWD>`, the same placeholder convention the Gate command already used.

The prompt's "keep every admitted command on ONE line" rule is **retired** with it. It blamed a backslash-newline continuation for a denial that substitution caused, and it contradicted this emitter's own external launch commands, which `_shell_join` renders with ` \` continuations on purpose. The selftest pins the literal-`--cwd` instruction and the absence of any shell substitution from the rendered prompt.

### Fixed — an acceptance grep that was checking the wrong thing

`scripts/compound-v-scope-check.py` and `tests/test-integration-gate.sh` spelled the withdrawn carve-out constants as split literals (`"PIPELINE_" + "BOOKKEEPING"`) so that a bare `grep -rn` for the name would come up empty. That made the two tests which *prove* the carve-outs are gone unreadable in order to protect an acceptance check that matched any mention rather than a definition. Both names are spelled plainly now, and the acceptance check is definition-scoped: `grep -rnE '^PIPELINE_BOOKKEEPING\s*=' scripts hooks` returns nothing.

### Found live, 2026-09-02

Probed from the top-level session (`ProposeGoal` and `ScheduleWakeup` are main-session tools, invisible to subagents): `ScheduleWakeup` is present in the tool listing; `ProposeGoal` is **absent** — the `@internal` setting was not enabled on this install. `/v:epic`'s printed `/goal <condition>` fallback is therefore the path that must always work, not a rare corner case.

### Documented

`native-mechanisms.md`: the goal, resurrection and triage rows move from ⚠/❌ to ✅, with the 3.4.0 reason recorded in each; the event table's registered-event count drops to 7/10. The viability audit's §7 table gets a Status column — rows 1, 2, 3, 4, 8 and 10 (variant A) are marked done in 3.4.0; row 5 (`preferences`) is closed by decision to keep it as-is; rows 6, 7 and 9 stay open.

### Cross-model round 4 (Codex, 2026-09-03)

`docs/superpowers/reviews/2026-09-03-codex-round-4-gate-changes.json` — nine findings against the merge and lane-guard changes above, closed by run `2026-09-02-v3.4-native-first-r12`:

- **C1** critical — an unsealed `manifest.yaml` let a lower-trust worker widen its own lane after `cmd_gate_receipt` re-read it live, and both gates would accept the widened result. Closed: the manifest is digest-bound (below).
- **C2** critical — the enforcement CLIs remained shadowable by a planted module or a stale `.pyc` loaded before the cache controls took effect. Closed: every enforcement entry point drops its own directory and the cwd from `sys.path` and sets `sys.dont_write_bytecode` before any non-stdlib import.
- **C3** critical — the authority verified the live tree, but Finalize staged that tree again afterward, so a post-authority mutation could land unverified, or a worktree whose patch never landed could still be pruned. Closed: the sealed per-job patch (below).
- **C4** critical — worker-writable `state.json` could forge the idempotence marker and make Finalize skip a real merge permanently. Closed: state is a cache, never authority — the idempotent branch now requires git proof of the sealed patch.
- **H1** high — ordinary test-generated files could turn an honest scope pass into an authority contradiction. Closed: the authority validates the sealed artifact captured at Gate time, not a live re-scan that a test run may have touched.
- **H2** high — when a private pycache prefix could not be created, both the hook and the authority's loader silently proceeded with an unsafe import instead of refusing. Closed: a failed cache-prefix creation is now a fail-open notice (hook) or a fail-closed refusal (authority) — never a load.
- **H3** high — the lane guard's interpreter-viability probes had no watchdog and could stall a tool call indefinitely rather than fail open on schedule. Closed: every probe runs under a sub-second bounded-capture pattern, and the `PreToolUse` registration in `hooks/hooks.json` now carries an explicit timeout.
- **H4** high — resuming after a pruned worktree accepted a commit on pathname overlap alone (`any(...)` over touched paths), which is not proof that job's patch actually merged. Closed after the ninth review pass reproduced it still open in r12 (orchestrator fix, r13): resume verification binds to the sealed per-job patch digest, not to any ancestor commit that happens to touch a matching path.
- **L1** low — the run-directory exemption docstring claimed an "EXACT, CLOSED LIST" of three files while the implementation exempted more (receipts, results). Closed after the ninth review pass (orchestrator fix, r13; the list is now one constant and a table-driven test): the docstring and comments now enumerate the actual exemption classes, backed by a table-driven test generated from the same canonical list.

**Tenth review pass (r13, review-only, ISSUES 7) — closed by the orchestrator, not by an eleventh pass.** The cycle cap the maintainer set was exhausted, so the six actionable items were fixed directly and are verified by selftests rather than by another reviewer run: (1) CRITICAL — the r13 fix itself regressed C2 by importing `json`, `subprocess`, `tempfile` and `shutil` above `_harden_sys_path()` in `scripts/compound-v-integration-gate.py`; the imports are gone and a selftest now reads the source and asserts nothing but `os` and `sys` precedes the hardening call. (2) HIGH — a zero-byte sealed patch with the empty-string sha256 in its receipt bought a vacuous pass on the pruned-worktree branch; an empty artifact or an empty post-image is now "not proof", with a zero-byte-patch selftest. (3) the selftest gap that let (1) read 78/78 — covered by the same source-order test. (4) `native-mechanisms.md` no longer credits r12's finalize with closing H4. (5) the last "three self-referential run-dir files" comment in `compound-v-scope-check.py` names the closed list. (6) the orphan-probe check in `tests/test-lane-guard.sh` greps for a per-run unique sleep instead of a machine-global `sleep 30`. Item 7 (the compat branch) is carried forward as documented.

Eighth review pass, closed in the same run: **#2** `agent_role_for` now matches reviewer types exactly (`review`, `spec_review`, `quality_review`, `integration_review`) and returns a reason on decline, with `review_fix` mapped to the implementer role; **#4** a malformed manifest `max_turns` degrades to the tier default with a note in both the rendered prompt and the emit output; **#5** `execution-manifest.md`'s rendered "Turn cap" now agrees with `agents/implementer.md` — deep is 80, not 60 (see below); **#3** `tests/test-lane-guard.sh` asserts the interpreter log line on the healthy path, discriminating against a planted restoration of the old conditional; **#6** the interpreter is logged once per session, not per call, with the COST paragraph updated to say so; **#1** (this file) states `CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT`'s real semantics.

### Changed — the merge applies a sealed per-job patch; the manifest is digest-bound

Two authority gaps Codex round 4 found (C1, C3, C4, H1, H4 above) shared one root cause: everything downstream of the Gate kept re-reading mutable state — the live worktree, the live `manifest.yaml`, the worker-writable `state.json` — instead of a record fixed at the moment scope was actually checked.

**The Gate now produces a sealed artifact.** `cmd_gate_receipt` captures `git diff --cached --binary <baseline>` restricted to the job's approved paths as `jobs/<id>.patch`, and records its sha256 in the receipt. The authority validates that digest and that the artifact applies cleanly onto the baseline; `finalize-wave` applies **exactly that artifact**, never a fresh diff of the live tree, then proves from git that HEAD's version of every path in the artifact equals the artifact's post-image — and only then prunes the worktree. A worktree reverted to baseline after the Gate is refused, not pruned; ignored test byproducts created after the Gate (`.pytest_cache/**` and the like) cannot make the authority contradict the receipt, because the authority validates the artifact, not the tree. On the idempotent resume branch, `state.json` is treated as a cache: a forged `integrated: true` with no git proof of the sealed patch is not skipped.

**The manifest is bound the same way.** `emit` bakes `sha256(manifest.yaml)` into the emitted script's `CFG.manifest_digest` at materialize time; `gate-receipt`, `record`, `finalize-wave` and the authority all re-verify the manifest on disk against that digest (`--manifest-digest`, sourced from `CFG`) and refuse on mismatch. A manifest widened after emit — a lane added, a check removed — is refused at the Gate, not merged and caught later.

**Import shadowing is closed at the source.** `compound-v-emit-workflow.py`, `compound-v-integration-gate.py`, `compound-v-scope-check.py` and `compound-v-validate-manifest.py` all remove their own directory (`sys.path[0]`) and the cwd from `sys.path`, and set `sys.dont_write_bytecode`, before any non-stdlib import — a planted `scripts/yaml.py` no longer reaches the parser. Where a private pycache prefix cannot be created, the loader does not fall through to an unredirected import: the hook emits its fail-open notice and skips the load, and the authority fails closed with a reason.

Pinned by tests: `tests/test-integration-gate.sh` and `tests/test-engine-c-contract.sh` cover a reverted-but-not-pruned worktree, ignored post-Gate byproducts, a forged `state.json`, a widened manifest after emit, a planted shadow module, and a forced cache-prefix failure; `tests/test-lane-guard.sh` covers the same shadow-module and cache-prefix cases for the hook, plus a 30-second-sleeping interpreter candidate returning within the hook's own bounded budget.

## [3.3.7] - 2026-09-02

A viability audit, asked for by the maintainer in one sentence: *check what is redundant, duplicates Claude Code, or is over-engineered; whether agents are routed by task complexity correctly; whether the task tier and the short-vs-full flow are decided correctly; and what is declared but is in fact a stub.* The answer is [`docs/superpowers/architecture/2026-09-02-viability-audit.md`](docs/superpowers/architecture/2026-09-02-viability-audit.md). This release ships the fixes that needed no decision; the cut list in that document does.

### The numbers the audit is built on

58 395 lines of Python and shell, grouped by whether anything has ever exercised them: **21 236** in the spine that 37 runs, 27 dogfoods and three cross-model rounds hardened; **12 996** in epic mode, which has produced zero `epic-state.json` files in this repository's history; **11 843** in the triage engine, which has produced one pre-eval record, zero `bind` events, and no `triage` block on any of the 37 manifests; **12 320** elsewhere, most of it with no caller on the default engine.

### Fixed — the flagship skill still described the 1.x dispatch

`skills/compound-v/SKILL.md` — the document every session loads — told the model to dispatch Phase 3 as *"N concurrent Task calls, `model: "opus"`"* and Phase 1 as *"three concurrent Task calls"*. Engine C has been the default since 3.0 and the Phase 1 workflow emitter shipped in 3.3.5, and **no markdown file referenced `compound-v-emit-preflight.py` at all** — the feature the maintainer asked for two releases ago had no caller. Phase 1 and Phase 3 now point at the emitters and `Workflow({ scriptPath })`, with the `Task` form named as the residual path; the Stage −1 paragraph now says the triage record has exactly one producer, `/v:triage`; the override table, the Sonnet red flag and the one-sentence summary carry the execution-vs-judgment policy instead of "Opus by default, Sonnet for junior tasks".

### Fixed — the plan-saved nudge pointed at the residual path

`hooks/plan-saved-nudge.sh` told the model to *"invoke partition-reviewer, then parallel-dispatcher"* — the subagent path `/v:dispatch` explicitly says not to use — and mentioned `/v:dispatch` as a shortcut. It now names `/v:dispatch` as the path and the dispatcher as the fallback for a session with no Workflow tool.

### Fixed — three documents still said `standard` resolves to Opus

`routing-policy.md` §Resolution, and `phase-3-parallel-opus-dispatch.md` in three places, described the pre-3.0.5 map (`standard` → opus under `balanced`, sonnet only under `cost-aware`). They now match the resolver: `standard` → sonnet everywhere except `conservative`, `frontier` → fable, capped at opus under `cost-aware`. The "tick ALL boxes or it is Opus" paragraph now says what the boxes decide — `standard`/`light` versus `deep` — and that a failed attempt escalates one rung.

### Added — `interface_design` job type → `frontier`

The maintainer's policy places interface design on Fable, and the routing tables had no type that reached `frontier` — a planner had to know to assign the tier by hand. All three stance tables now carry an `interface_design` row (`frontier · high`, worktree; `cost-aware` caps it at opus as it caps every `frontier`).

### Fixed — README overclaimed advisor mode

*"This is wired today for the Claude-executor case"* described the residual `Task` path; Engine C emits no consult step. The README now says so.

### Documented — three more native mechanisms we duplicate or ignore

`native-mechanisms.md` gains `/goal` (the binary carries a native goal with an evaluator and check-ins; our Stop hook's Feature A re-implements it for an epic that has never run), `/loop` + `/schedule` (three schedulers of ours — session cron, `scheduled-tasks` MCP, a launchd/cron shim — for one native line), and the static `Edit(path/**)` permission rules (exist, do not cover a per-job lane; `lane-guard.sh` stays). The recount: 7 with no native mechanism, 4 where the native one does not cover, **15** where it exists and we did not use it or duplicated it.

## [3.3.6] - 2026-09-02

Cross-model review round 3, on everything the 26 live runs produced. Eight defects: one critical, two high, three medium, two low. Every one real, and two of them were comments in this repo asserting a property the code did not have.

### Fixed — CRITICAL: a direct worker could widen its own lane and get the write committed

The chain, as the review walked it:

1. The worker writes `X`, outside its `write_allowed`.
2. It edits `manifest.yaml` to add `X` to `write_allowed`.
3. It appends a **bare** `manifest.yaml` path to `preexisting/<id>.txt`.
4. `read_preexisting_unchanged` accepted that as a *legacy* line — no digest required.
5. The manifest is now exempt, so the closed by-name list never gets a say.
6. The gate loads the **widened** manifest and sees `X` as in-lane.
7. The digest excludes the run directory, so both forgeries are invisible.
8. The authority reloads the same widened manifest and independently derives the same false pass.
9. `finalize-wave` commits `X`.

The hole was backward compatibility for a format that shipped **the same day**. A line without a digest is now dropped, with a message on stderr: an old snapshot exempts nothing, which blocks loudly rather than passing quietly.

### Fixed — HIGH: a recorded merge is a claim, and `state.json` is worker-writable

The retired-worktree branch read `merged.integrated` and `merged.commit` from `state.json` — a file on the by-name exempt list — and returned `pass` **before** receipt, baseline, digest, result or scope were checked. The commit did not have to exist.

It must now exist, be an ancestor of `HEAD`, and touch this job's declared lanes: three answers that come from git rather than from us, and none of them forgeable by editing JSON. The lane check uses the scope gate's **own** matcher, because a verifier that matches differently from the gate can disagree with it for reasons neither is about. Anything short of all three is `unverifiable`.

### Fixed — HIGH: the pre-flight auditors had arbitrary shell and arbitrary writes

`compound-v-emit-preflight.py` shipped yesterday with no `disallowedTools` and no clamp, while its own docstring said each auditor "writes ONE document into its own directory". `agentType` selects instructions; it enforces nothing.

The review named the confusion exactly: *not removing the network* is not the same as *not narrowing at all*. The network stays — this is the research phase, and two of the three auditors are network-dependent by definition. What goes is the authority to change anything else: `Task` and `Agent` (an auditor that spawns is not an auditor), `SlashCommand`, `NotebookEdit`. `Bash` is admitted through a clamp for exactly one command — the recall query dogfood 24 proved is denied without one.

### Fixed — the smaller four, each with a probe behind it

**`_json_escape` emitted invalid JSON.** It deleted every control byte *except* LF and CR — the two that matter inside a JSON string. Probed byte-for-byte by the reviewer; the comment claiming control characters were handled was false. `python3` now serializes it, and it is already a hard dependency of this hook's own query.

**`{"status": "blocked", "blocked": false}`.** A red test floor moved `status` but left the schema's required boolean reading the gate verdict it started from. The finalizer reads `status` and refused correctly; every other consumer got the opposite conclusion.

**The busiest repositories got the wrong answer.** `head -n` closed the pipe, upstream `jq` died of SIGPIPE, `pipefail` reported 141, and the failure handler cleared every id — but only when there were *more* active runs than the display limit. The limit now lives inside `jq`.

**A real spec could vanish from recall because of its pathname.** 3.3.2 excluded every `<run>/spec.md`; its own comment said the manifest "usually" points elsewhere, which means not always. The exclusion now asks the manifest where its spec actually is.

### Fixed — MEDIUM: the task-text refusal broke manifests that were valid

3.3.4 refused any job without `body`/`description`/`prompt`/`spec`. The review caught both the compatibility break and the tell: the fixtures were made to pass by **injecting synthetic `body` strings**, not by showing the contract required one.

A title plus acceptance criteria **is** a task — this function renders both itself. That shape is accepted again, with a line in the prompt telling the worker to report BLOCKED rather than invent scope. What stays refused is the shape that caused the damage: lanes, a title, and nothing to check the work against.

## [3.3.5] - 2026-09-02

### Added — the Phase 1 pre-flight runs as a native Workflow

The three auditors — `code-archaeologist` (1A), `domain-expert` (1B), `doc-validator` (1C) — have always run in parallel, as three separate `Task` calls. A developer watching saw three opaque spawns: no phase grouping, no progress tree, no shared budget ceiling, no structured result. The same "we built our own instead of using the native one" pattern this release line has been closing everywhere else.

`scripts/compound-v-emit-preflight.py` emits them as one Workflow: `parallel()` under a single `Pre-flight` phase, each spawned **by role** via `agentType` so it arrives with its own definition rather than a re-pasted prompt.

`parallel()` and not `pipeline()` is the documented exception to this repo's own default: the brainstorm cannot continue without **all three**, so the barrier is real rather than incidental, and there is no second stage to overlap with.

**What it deliberately does not do**, each for a reason this release earned:

* **No `bashCommandClamp`.** Dogfood 24 watched a clamped agent get its own documented first step denied. An auditor greps, reads, runs `git log` and queries recall.
* **No tool narrowing.** The Implement stage denies `WebFetch`/`WebSearch` on purpose — research belongs to a pre-flight, and this **is** the pre-flight. `domain-expert` and `doc-validator` reference WebSearch four and six times in their own definitions.
* **No `model` override.** Each agent's frontmatter decides: sonnet for the two scanners, opus for domain judgment. The one place in this whole release where *not* wiring something was the correct choice.
* **No routing.** These produce evidence. `routing-policy.md` stays deterministic and untouched.

An audit that returns `null` is recorded as **NOT RUN**, never as clean; one that throws cannot take the other two with it; and the caller is handed an `incomplete` list, because an audit that did not run is not an audit that found nothing.

### Fixed — three defects the new pre-flight immediately found in our own hooks

Its first real run audited a small spec and returned 14 + 13 findings. Three were bugs in code shipped hours earlier.

**The SessionStart banner died without `jq`.** `jq` ships by default on neither macOS nor most Linux images, and `session-banner.sh` runs under `set -euo pipefail` — so a missing `jq` did not degrade the banner, it killed it on every session start with no diagnostic. The JSON is now written directly; `jq` is no longer required.

**The banner emitted a shape the runtime discards.** Its generic branch produced a bare top-level `{"additionalContext": …}`. That key is recognised only *inside* `hookSpecificOutput` alongside a `hookEventName` — the binary's own hook-output table lists exactly that shape — so a bare one is unrecognised and dropped. The branch was reached whenever `CLAUDE_PLUGIN_ROOT` was unset, and the banner then silently did nothing. Claude's shape is now the **default**, not a branch conditional on an environment variable: a missing plugin root is not evidence of a different harness.

**`postcompact-resume.sh` reported a successful empty query as a failed one**, and a comment above it claimed the rendered line and the live ids "can never disagree". Since 3.3.0 they can — the line may come from the PreCompact snapshot and the ids always come from a live query, and the audit reproduced the divergence. Both halves are correct; they describe different moments. Saying otherwise sends a reader hunting a bug that is not there, and the empty-vs-failed conflation had the hook reporting a check as not-run when it had run.

**And one comment of mine naming a reader that does not read:** `precompact-snapshot.sh` said `session-banner.sh` finds the snapshot. It contains zero references to it. Naming a reader that does not read is the same defect as claiming a caller that does not call — the defect this entire release line has been about.

`tests/test-native-points.sh`: 78 → **85 checks**, including the banner surviving with a stubbed-out `jq` on `PATH`.

## [3.3.4] - 2026-09-02

### Fixed — the task text never reached the worker. For twenty-five runs.

`render_worker_prompt` read the job's instructions as:

```python
body = job.get("description") or job.get("prompt") or job.get("spec")
```

Every manifest in this repository writes `body:`. The names never intersected, so **the task text was silently dropped from every worker prompt**. Workers received a title, their lanes and their acceptance criteria — and no instructions. They then wrote whatever seemed reasonable, inside their lane, and passed every gate: the scope gate checks *which* files changed and never what they say.

Reading a prompt back confirms it: `jobs/impl-slice.prompt.md` carries title, write-allowed, read-allowed and acceptance, and no task at all.

**Five prior reviews reported this** — df10, df11, df12, df18, df20 — and it stayed live, because each was read as a one-off spec gap in that run. Dogfood 25 is what closed it, and only because recall had been made reachable an hour earlier: the reviewer's second query returned all five reports at once, and the finding stopped being *"a spec gap"* and became *"the loop is not closing"*. That is the argument for recall, demonstrated on recall's own release, by the agent recall was given to.

Fixed three ways, because one was not enough:

* **`body` is read first**, with `description` / `prompt` / `spec` kept as aliases.
* **A job with none of them is refused at emit.** A prompt with lanes and no instructions asks the worker to invent the task, and an invented task that stays in its lane is invisible to every check this pipeline has. This is the mechanism that would have caught it on run 1 instead of run 25.
* **The field is documented**, in the per-job table it was missing from — which is a fair share of why the mismatch survived: nothing said what the field was called.

The shipped `examples/manifest.example.yaml` was itself refused by the new guard — five jobs, no task text, and it is the file people copy. It now carries real instructions for all five.

### Fixed — recall was unreachable behind the bash clamp

3.3.3 told five agents to consult V-memory first. Dogfood 24 spawned `spec-reviewer` — the one agent Engine C spawns by role — and watched it try. The harness denied the recall query, a second phrasing, the `recall-check` bridge, and the form `/v:remember` itself instructs: the Implement clamp admitted exactly one command form, `register-lane`.

The instruction was prose in an agent definition; the clamp is mechanism, and mechanism wins. This repository has a name for that failure, and it shipped into the feature meant to demonstrate recall.

The clamp now admits `compound-v-memory.py search` and `recall-check`. Both only read — a SQLite index outside the repo, printed. `refresh` and `bootstrap`, which write, are deliberately not admitted, and a selftest asserts it.

**Worth recording on its own:** that reviewer refused to write *"V-memory returned nothing"*, because it would have claimed an empty result set from a query that never ran. A less careful agent would have satisfied the acceptance criterion falsely. The gap is invisible unless the agent distinguishes an empty result from a blocked one.

## [3.3.3] - 2026-09-02

### Fixed — V-memory had no callers among the agents

V-memory shipped in v2.0. Asked whether the design subagents use it, the answer was measurable and blunt: **all six agents contained zero references** to V-memory, `/v:remember` or `compound-v-memory.py`.

Recall was a command a human ran. So the code archaeologist re-read code this repository had already described, the domain expert re-derived conclusions already written into an ADR, and the doc validator re-checked libraries a previous audit had checked. That is the same defect this release line kept finding — **a mechanism with no caller** — one layer up, in prose instead of code.

**Five agents now consult it, each at the right intent:**

| Agent | Call | What it is for |
|---|---|---|
| `code-archaeologist` | `search --intent planning` | do not re-derive what the repo already documents |
| `domain-expert` | `search --intent planning` | do not re-litigate a settled domain decision |
| `doc-validator` | `search --intent planning` | a previous audit may already have checked this library |
| `spec-reviewer` | `search --intent review` + `recall-check` | the failure this shape produced last time |
| `partition-reviewer` | `recall-check --files <lanes>` | a partition can be disjoint and still one this repo has failed on |

`parallel-dispatcher` is **deliberately excluded**: it executes a decided manifest and must not acquire opinions from prose mid-dispatch.

**The rules that keep it safe are written into every one of them.** A recalled claim is evidence with a citation, not authority — name the document, quote the constraint, and where prose and code disagree the code wins and the disagreement is itself a finding. Recall is **never a routing input**; that order stays deterministic in `routing-policy.md`. The one path from recall back into action is `recall-check`'s `tighten`, which is escalation-only: it can force worktree isolation or an extra review pass, and can never loosen a control, reroute to a cheaper backend, or turn a FAIL into a PASS. An empty result is a normal answer, and a missing script is noted and stepped past — a recall layer that is absent must never block the audit it was meant to accelerate.

### Added — `tests/test-agent-recall.sh`

A prose instruction has no compiler, so this file is its compiler: 29 checks that the instruction is present in each of the five, that it names a command that really exists with the flags it uses, that it states both safety rules, and that the dispatcher has *not* acquired one. Watched failing — strip the block from one agent and four checks redden.

## [3.3.2] - 2026-09-02

### Fixed — V-memory was 43% machine output

Asked whether recall still works under 3.x's dogfooding cadence, the measurement said no.

`docs/superpowers/execution/<run>/` carries two machine-generated shapes that end in `.md`: the per-job worker prompt the emitter renders, and the `spec.md` / `plan.md` a run keeps when its real spec lives elsewhere (the manifest's `spec_path` points into `docs/superpowers/specs/`). On this repository, after a night of dogfooding, that was **71 worker prompts and 44 run-directory stubs out of 267 indexable files — 43% of the corpus**, and the prompts are ~40 lines of near-identical boilerplate.

The effect, measured on a real query rather than argued:

```
"scope gate write_allowed violation"
before:  1 useful result, then FIVE near-identical worker prompts
after:   the PRD's Scope Gate section, a dogfood review, the architecture doc,
         the implementation plan, another dogfood review
```

Both are excluded from the **index** now. They stay in git, stay in the audit trail, stay readable — they are simply not what anyone means by *"what do we know about X"*. Recall is evidence for planning and review, and evidence that is 43% copies of one template is worse than a smaller corpus.

Deliberately **not** excluded: `docs/superpowers/dogfood/**`, which is hand-written and the densest record this project has of what actually went wrong. A query for *"why was a red test floor merged"* now returns that section first.

Index: 196 → 152 files, 1712 chunks, all human prose.

### Known

The dense lane holds **0 vectors** — the venv is bootstrapped but nothing has been embedded, so recall is FTS5-only and the `>= 80 vectors` scale gate has never engaged. That is unchanged by this release and unrelated to it; `/v:memory-refresh --bootstrap` is what populates it.

## [3.3.1] - 2026-09-02

> v3.3.0 was cut automatically mid-session, when its version bump reached `main`, and
> describes only the two new hook events. Everything below is the twenty-two dogfood
> runs and two cross-model review rounds that followed it.

### Fixed — a red test floor was merged

Dogfood 14 declared a floor that exits 3. It ran, failed, and was recorded with perfect honesty. **The job was recorded `success` and merged.** Status came from the scope verdict alone, and the scope gate has no opinion about whether code works.

The `tests` block was the fourteenth mechanism this project built and left without a consumer — and the only one that did worse than nothing: it gave a green light to red tests. A red floor is now `blocked`, not `error`: the machinery is fine, the work did not pass its own declared tests.

### Fixed — in direct mode, the pipeline blocked the job that produced its evidence

The largest chain of the release, five runs long. A `direct`-mode job's run directory sits **inside** the tree the scope gate measures, and the pipeline never stops writing into it. Each fix revealed the next file, because a file only becomes visible once the ones before it are exempt: `state.json` (a sibling's Record rewrites it) → `preexisting/<id>.txt` (records digests including its own) → `<id>.verified.txt` (written by the gate, after the list that would contain it) → `receipts/<id>.gate.json` and `results/<id>.json` (written after the gate).

The fix that held was not another filename. The exemption list is now built from **the three writers, by construction**, at the point the list is made.

Alongside it, two seams that made the gate and the authority disagree about the same tree: the digest was taken over the whole tree by both sides at different moments (now both exclude the run directory, in direct mode only), and the authority re-derived from the raw exemption list while the gate used the verified one (now both use the verified one).

### Fixed — two CRITICALs a review found and no run would

**The manifest defines the lanes, and it was exempt by name.** A worker could write out of lane, rewrite its own `manifest.yaml` to widen `write_allowed`, and have the gate **and** the authority read the widened manifest and agree — with an honest baseline and an honest digest, because neither binds the document that says what "in scope" means. The by-name pass is now a closed list; everything else falls back to a digest bound at register time.

**The worktree cleanup re-read its target from `state.json`**, which is on that closed list. A worker could redirect it at a **refused** job's tree and have the finalizer `--force`-delete the one copy of work the refusal exists to preserve.

**A hook executed a script from the project.** `PreCompact` preferred `${cwd}/scripts/compound-v-dashboard.py`; any repository merely containing `docs/superpowers/` would have had its own Python run automatically, with the user's privileges, on every compaction. Cloning a repo was enough.

### Fixed — five refusals under the wrong name

`no_work` as a fourth verdict word · a moved HEAD as `forged` (now `stale`, decided by ancestry **and** the absence of any other fault) · a job that did nothing as `error` (now `blocked`, and only when the gate also passed and saw no changes) · an all-refused wave as *"already in HEAD"* · a retired worktree as `unverifiable` (now `merged`, on the recorded integration).

Every decision was correct. Every name cost a debugging session, and two cost a dogfood run each.

### Changed — the finalizer retires the worktrees it merged

The runtime only auto-removes worktrees that changed **nothing**, so eleven runs into a day this repository had nineteen. They are not merely untidy: in direct mode the gate attributed all fifteen leftovers to the next job and blocked it. Only merged worktrees are removed — a refused job's tree still holds the only copy of its work.

### Fixed — the inventory section's own numbers

It claimed *"6 of 13 hook events"* and counted `SubagentStop` as unused. The binary's own table lists **ten** registrable events; `SessionEnd` and `UserPromptExpansion` exist as executors but are absent from it, and are now recorded as **unverified** rather than counted. `SubagentStop` is *received* and deliberately refused — the runtime converts a `Stop` registration into it for subagents, and `epic-goal-stop.sh` rejects it first thing or a subagent burns the main session's counter.

### Known, and stated rather than fixed

**In `direct` mode a worker can write anywhere in the tree, so no file-based exemption list is tamper-proof** — and a digest-bound one stored in that same writable tree is not either. The cross-model review was right that names alone are weak; it is equally true that digests in a writable tree are not strong. What backstops this is the integration authority, which re-derives the diff from git and refuses a receipt whose bindings disagree, plus the baseline pin, which stays digest-bound. The architecture's answer is the authority, not the list.

**The plugin you edit is not the plugin you run.** The session that built this was running a July build the whole time; every hook here was verified by direct invocation with real payloads, and the registration path is asserted by `hooks.json` and its tests, not by observing a hook fire inside a live dispatch.

**A `direct`-mode run needs a quiet repository.** Editing during one attributes your edits to the job. Four runs died of that. The gate now lists such paths under `foreign_execution_paths` so the diagnosis is immediate.

## [3.3.0] - 2026-09-02

### Added — two native hook events this plugin had never registered

**8 of the runtime's 10 documented hook events**, up from 6. Both additions have a reader; a hook that writes where nobody looks is the defect this whole release line has been about.

**`PreCompact` → `hooks/precompact-snapshot.sh`.** The last moment at which a session still knows what it was doing. The other two compaction-adjacent events both arrive too late to *know*: `PostCompact` receives the summary but its stdout is display-only on 2.1.238 (the context-injection path lists exactly `SessionStart`, `UserPromptSubmit` and `UserPromptExpansion` — read out of the binary with `strings`, not from docs), and `SessionStart` runs a session later. The complaint that started the 3.0 line was *"Клод забывает"*, and both existing answers **read** state at the moment they run; this one **writes** it while it is still true.

It never blocks compaction — the runtime supports that and a blocked compaction on a full context is a wedged session. It writes one file into the session's temp store, never into the project. And it re-derives nothing: `compound-v-dashboard.py resume` still owns what unfinished means.

**`PostToolUseFailure` → `hooks/tool-failure-ledger.sh`.** The only event that sees a failure at the moment it happens. Compound V has had a failure classifier since 2.x, but only external worker scripts ever fed it — a `backend: claude` implementer's failed Bash was seen by nobody. The ledger appends one JSON line and exits: it does not classify, decide, retry or block, because a hook that started routing from a single failed call would be inventing a policy nobody wrote.

It records **no tool input**. A failed `Write` carries file content and a failed `Bash` carries a command line; both routinely contain secrets, and a ledger quietly accumulating them in a world-readable temp directory would be a data-exposure surface built for convenience. Tool name, agent id, timestamp, bounded error excerpt.

### Fixed — the inventory section's own numbers were wrong

It claimed *"6 of 13 hook events"* and counted `SubagentStop` as unused. Both from reading `strings` without reading the code:

* **Thirteen is not the registrable set.** The binary's own `### Hook Events` table lists **ten**. `SessionEnd` and `UserPromptExpansion` exist as executors but are absent from it; whether they can be registered is **unverified**, and is now recorded as unverified rather than counted.
* **`SubagentStop` is received and deliberately ignored.** The runtime converts a `Stop` registration into `SubagentStop` for subagents, and `epic-goal-stop.sh` rejects it in its first gate — otherwise a subagent shares the session id, passes session isolation and burns the main session's counter. That is "received and refused", with the reason in the code, not "never used".

`PermissionRequest` and `Notification` stay unregistered with verified reasons: the first never fires in bypass mode and is a weaker second path to a decision `PreToolUse` already makes; the second carries nothing any guarantee here needs.

### Also verified while building this

The `prompt` and `agent` hook types (available on `PreToolUse`/`PostToolUse`/`PermissionRequest`) are deliberately unused: a model call per tool invocation contradicts the proportionality policy 3.1.0 just established. `updatedInput` on `PreToolUse` — rewriting a caller's tool input instead of refusing it — is deliberately unused too.

The first draft of the snapshot hook passed an invented `--repo` flag to the dashboard, argparse rejected it, and the hook silently wrote nothing. Its own live probe caught it before it shipped. This project has killed an invented flag this way before.

`tests/test-native-points.sh`: 65 → **78 checks**, including the cross-hook one that writes with `PreCompact` and reads with `PostCompact` against a **deliberately divergent disk** — remove the reader and exactly one check reddens.

## [3.2.0] - 2026-09-02

### Changed — the triage gate is ON by default, and the claim that kept it off was wrong

This is a behaviour change, and it exists because a limitation this project published about itself did not survive being checked. **Twice in two releases now.**

The `Stop` triage gate shipped off under `enforcement.triage_gate`, and the audit table justified that with: *"turning it on by default blocks turn-end in every session of every install, including for sessions that never touched Compound V."* A live probe on 2026-09-02 disproved both halves:

| State | Behaviour |
|---|---|
| no `.claude/compound-v.json` | **silent** — a project that never ran `/v:init` is untouched, which is most installs |
| config present, no uncovered change | silent |
| `docs/superpowers/**`, the hook's own store | exempt |
| uncovered code changes | fires **once per session**, marker written *before* the block, so it cannot loop |
| any timeout / unreadable record / git error | **fails open**, whole rule bounded at ~800 ms |

The real population is *a repository that deliberately initialised Compound V, once per session, with code changes no triage record covers*. That is exactly the failure this plugin exists to catch — the complaint that started the 3.0 line was an agent skipping the pipeline — and leaving the one mechanism that catches it switched off was not caution. It was the mechanism-with-no-caller defect wearing a config key.

**Opt out with `"enforcement": {"triage_gate": false}`** in `.claude/compound-v.json`. Documented in the README, in `/v:init`, and in the block message itself. `pipeline_bypass` is unchanged and still off.

### Fixed — the flip introduced a bug that would have made the opt-out a lie

`jq`'s `//` is the **alternative** operator: it yields the right-hand side when the left is `null` **or `false`**. So the obvious `.enforcement.triage_gate // true` turns an explicit `"triage_gate": false` back into `true`, and the opt-out documented in the gate's own block message would silently not work.

Caught by its own test on the first run of the flip — the opt-out test was written before the flip was believed. The value is now read with an explicit `== false` comparison, and both the boolean and the string form turn it off.

### Changed — the triage gate now shadows the bypass rule, deliberately

Both rules say *"you changed code without X"*, and only one response per `Stop` event is permitted. The more specific diagnosis goes first: `/v:triage` **is** the first step of the correction the bypass rule asks for. So a project with `pipeline_bypass: true` and no `triage_gate` key now sees the triage wording instead of the bypass wording. Setting `"triage_gate": false` restores the old message. Pinned by three tests so it can never become an accident.

`tests/test-epic-goal-stop.sh`: 88 → **98 checks**, including the opt-out, the shadowing, and the four live-probed states.

### Where the native-mechanism audit stands now

Eleven of the twelve "native mechanism exists, we were not using it" rows close fully. The remaining one is `agentType`, at its designed end state and explained in the table.

Triage-at-prompt-arrival keeps a small, honest ⚠: `UserPromptSubmit` still carries a *reminder*, and the enforcement lands one turn later at `Stop`. Between those two points nothing stops work beginning without triage. The gate makes that expensive, not impossible — and no wording here should be read as saying otherwise.

## [3.1.2] - 2026-09-02

### Fixed — a caveat this project published about itself was wrong

3.0.6 shipped with a stated limitation: *"`bashCommandClamp` on Implement is still conditional — `_clamp_rules` returns `None` for a non-`claude` job whose worker script is missing, and an implementer with no clamp is unnarrowed on Bash."*

It is not true. That `None` is returned, but `job_entry` **refuses that job outright** a few lines later — an external backend with no worker script cannot launch at all. A `claude` job always carries the register-lane rule. **No implementer that reaches `agent()` is ever unclamped.**

The caveat came from reading the function and not the path around it. Two selftests now hold the invariant shut — every launched job carries a clamp, and the one clampless path is refused before it can launch — because an invariant asserted is worth more than an invariant described. Corrected in the dogfood record and in the audit table, both of which repeated it.

Understating a guarantee is a smaller sin than overstating one, but it is the same failure: a claim about the code that the code does not support.

### The two remaining ⚠ rows are conclusions, not a to-do list

Both were re-examined against the code. They are ⚠ for different reasons, and the difference matters.

**`agentType` is at its designed end state.** Spawning by role happens where a role exists: `type: review` gets `superpowers-v:spec-reviewer`. Gate, Record and Finalize have no role and should not have one — each runs exactly one clamped command and returns its JSON verbatim, and their entire safety is `disallowedTools` + `bashCommandClamp`. Writing an `agents/gate.md` to spawn them by role would invent a role that describes nothing, and since **no agent under `agents/` declares a `tools:` restriction**, role-spawning would hand them the whole toolbox and undo the narrowing 3.0.6 just finished. ⚠ is more honest than ✅ — the mechanism is used as far as it applies here. Closed, not deferred.

**Triage-at-prompt-arrival is half closed, and the other half is not an engineering decision.** The reminder is now accurate (3.1.1). The remaining gap is mechanical: a model that ignores the line leaves no triage record at all, and the only thing that would catch it is the Stop gate, off by default under `enforcement.triage_gate`.

Turning that on by default is **not a fix, it is a default with a blast radius across every session of every install** — the gate blocks turn-end until a triage record covers the diff, including for sessions that never touched Compound V. That is the maintainer's call, and it is recorded here as a decision rather than as a forgotten task. If the answer is yes, what it takes: raise `enforcement.triage_gate` in the default config, re-run `tests/test-epic-goal-stop.sh` against the new default, and put the opt-out somewhere visible in the README.

## [3.1.1] - 2026-09-02

### Fixed — a question no longer burns the session's one triage nudge

The `UserPromptSubmit` nudge fires **at most once per session**. The native-mechanism audit named the consequence precisely and it sat there unfixed: a session whose first prompt is *"what does this do?"* spent the reminder on a question, and the real change request that followed got nothing.

A prompt of at most 200 characters ending in `?` now returns **before** the marker is written — the session stays armed, and the cost is the ~9 ms early exit rather than the ~89 ms eligibility path.

The test is deliberately narrow, because "is this a change request?" is not decidable in a hook. Only a *short* prompt ending in `?` counts as a question; a long prompt that happens to end in `?` is a description with a question attached and still nudges. The direction of the error is chosen: a missed nudge costs a reminder, a spent one costs the session's **only** reminder.

Six regression tests, and the guard was watched failing — removed from a copy of the hook, exactly three checks go red. A guard nobody has seen fail is a guard nobody should trust.

**The audit row stays ⚠, and the reason is unchanged:** a model that ignores the line still leaves no triage record at all, and the Stop gate that would catch that is still off by default (`enforcement.triage_gate // false`). The reminder got more accurate. It did not become a mechanism.

### Fixed — the auto-generated release title was a date

The CHANGELOG heading is `## [X.Y.Z] - YYYY-MM-DD`, so the text after the dash is the date. v3.0.6 and v3.1.0 — the first two releases the repaired gate published on its own, and the first two where nobody passed `--title` by hand — both shipped as *"vX.Y.Z — 2026-09-02"*. The title now comes from the entry's first `###` heading, where a release actually names itself, and falls back to no suffix rather than to a date. Both releases retitled.

## [3.1.0] - 2026-09-02

Three maintainer requirements, set 2026-09-02. Each one turned out to be a mechanism that already existed and was defaulted, named, or gated wrong.

### Fixed — a two-line change no longer runs twenty thousand tests

The test-selection machinery was right: `impacted ∪ previously-failing ∪ newly-added`, a declared `impacted_map`, a fail-closed refusal of an empty set. **Its default was the literal string `full`.** A job that did not write `test_scope:` ran the entire suite — and on a real application that is twenty to thirty thousand tests for a two-line change that nobody chose. It was what you got for not writing a line of YAML.

`default_scope_for` now derives it from what the repository has actually said:

| Condition | Default |
|---|---|
| triage tier `DIRECT` **and** a declared `floor_command` | `floor_only` |
| a declared, non-empty `impacted_map` | `impacted` |
| otherwise | `full` — with a note saying the contract declares no map, so nothing knows what relates to what and "all of them" is the only truthful answer |

**A derived `impacted` degrades; a declared one halts.** If the changed set cannot be computed, a scope the resolver *derived* falls back to `full` with a note — a convenience that halts a run is worse than the behaviour it replaced. An explicit `test_scope: impacted` still fails closed: someone declared it, and silently widening their declaration is exactly the fabricated-scope failure this resolver exists to prevent. That distinction came out of the resolver's own selftest going red on the first attempt.

Demonstrated: a job with no `test_scope`, changing `src/db/schema.sql` against the example contract, resolves to `npm run test:floor` + `npm run test:db`. Before this release it ran `npm test`.

**Unchanged and still true:** the union rule, the empty-set refusal, and the standing statement that the scoped floor is **early feedback** and does not restore what a full suite guarantees. A glob map carries strictly less information than a call graph, and call-graph selection is already measured at 0.2%–10.6% unsafe per revision.

### Changed — a second opinion follows the same entry criterion as brainstorming

If a change was too small to brainstorm, it is too small to hand to a second model family — there is no plan for it to read. The gate now rides the triage tier, and it is a call rather than a rule to remember: `compound-v-preeval.py --cross-model-review <tier>`.

`DIRECT` → no (no brainstorm, no plan, no manifest exist). `SCOPED` → no by default. `FULL` → yes. An unrecognised tier → **yes**: not knowing how big a change is, is itself a reason to have another family read it, and this gate only ever spends tokens — it can never let a worse plan through.

It is derived, never stored. The pre-eval record is digest-sealed; adding a field would change the bytes of every future record while old ones keep theirs, and a reused `pre_eval_id` would then be refused as a conflict over a field carrying no new information.

The existing stakes list now chooses the review's **depth**, not whether to ask — plus one criterion in the maintainer's own terms: **volume is not the signal, coupling is.** A thousand mechanical lines in one lane still does not need a second family; eighty coupled ones do.

### Fixed — Context7 was named wrong, and detected wrong

Asked to double-check that Context7 and WebSearch are actually used at Brainstorm and Plan, the answer came back worse than "not enough".

Context7 arrives under **two different names**: plugin-bundled (`mcp__plugin_<plugin>_context7__*`) or user/project-configured (`mcp__context7__*`). Every document in this plugin hardcoded the first — nine occurrences across eight files. On a machine running the second shape, the pre-flight agents were told to call a tool **that does not exist**, and fell silently back to WebSearch.

`/v:init`'s detector had the same assumption in grep form: `plugin[:_]context7[:_]context7`. Verified live on 2026-09-02 — `claude mcp list` printed `context7: https://mcp.context7.com/mcp (HTTP) - ✔ Connected` and a real `resolve-library-id` call returned results, while the documented matcher found nothing and would have told the user to install what they already had.

Both now match by suffix and cover either shape; the new matcher was checked against the live output **and** against the plugin form.

### Changed — the model policy reaches the pre-flight stages

Same split as the execution ladder: **Sonnet executes, Opus judges.** Scanning a repository is execution however large the repository is.

| Agent | Model | Why |
|---|---|---|
| `code-archaeologist` | **sonnet** | Measures existing code. Produces findings, decides nothing. |
| `doc-validator` | **sonnet** | Resolves a library, queries current docs, compares against what the repo declares. Checking, not deciding. |
| `domain-expert` | **opus** | Domain and regulatory judgment — what the brainstorm took for granted. |
| every reviewer + the dispatcher | **opus** | The safety net. A cheap reviewer is no reviewer. |

`lint-frontmatter.py` enforced a flat `model: opus` on every agent; it now holds an explicit, short `SONNET_ELIGIBLE_AGENTS` allow-list. The rule was absolute so that it could not drift, and a two-name allow-list keeps that property where "any agent picks its own model" would not.

**Fable stays out of frontmatter.** A static `model: fable` would spend the top model on every routine pre-flight; it is a dispatch-time override for business-critical work, set by the caller with the Agent tool's `model` parameter.

**And one thing that cannot be done, stated rather than promised:** effort is tunable on Engine C jobs (`opts.effort`) and **not** on the pre-flight path — the Agent/Task tool takes a `model` override and has no effort parameter. At Brainstorm and Plan, raising the model is the lever that exists.

## [3.0.6] - 2026-09-02

### Fixed — two releases that were never released

The release workflow gated on the **tag**, not the release. Tagging by hand before CI runs — which is how every release in this project is cut — made the job a silent no-op: it logged *"nothing to release"* and skipped. **v3.0.4 and v3.0.5 were both tagged, both went green, and neither was ever published.** GitHub's latest release sat at v3.0.3 while two versions' worth of code shipped past it. Both are published now, and the gate asks about the release instead. `gh release create` accepts an existing tag, so a hand-pushed tag is no longer a reason to skip.

This is the same defect this release cycle keeps finding, in a new place: a mechanism that exists, looks like it is working, and has no caller. It is the fourteenth.

### Added — the Implement stage is narrowed at spawn too

`disallowedTools` sat on Gate and Record and never on Implement — the one stage that actually holds write access. The audit table has recorded that as ⚠ since the day it was written.

Implement now carries its own, **different** list — a strict subset of the transport narrowing, keeping `Read`/`Write`/`Edit`, `Glob`/`Grep` and `Bash`:

| Removed | Why |
|---|---|
| `Task`, `Agent` | A nested spawn is not the job. `hooks/lane-guard.sh` resolves a write by `agent_id` first; a nested agent carries a different one, and the only fallback is cwd-under-a-**registered**-worktree — which a `direct`-mode job does not have. So a nested agent's writes are logged `job unresolved` and **allowed**. The git-derived gate still sees the bytes, but attributes them to a job that did not write them, and that attribution is what the whole enforcement chain rests on. |
| `SlashCommand` | An implementer running `/v:dispatch` re-enters the pipeline from inside one of its own jobs. |
| `WebFetch`, `WebSearch` | Research is a pre-flight phase in this plugin (Trigger 0, the doc-validator). An implementer holding write access while pulling untrusted web content into its own context is the injection surface the charter exists for. A job that genuinely needs external material gets it through a pre-flight, or pinned into `read_allowed` and the prompt. |

**This is a removal of capability**, stated here rather than discovered by whoever wonders why their implementer cannot search.

Dogfooded live on the same two-lane shape as 3.0.5, so the narrowing was the only variable: both lanes wrote, both gated clean, merged as `5c89a37`. That proves the list is **harmless**, not that it **bites** — no job in that run tried to spawn a nested agent or reach the network. That it bites is the runtime's contract for `disallowedTools`, not something the run observed.

`bashCommandClamp` on Implement stays conditional: `_clamp_rules` returns `None` for a non-`claude` job whose worker script is missing, and an implementer with no clamp is unnarrowed on Bash. Unchanged here.

### Where the native-mechanism audit stands

Ten of the twelve "native mechanism exists, we were not using it" rows now close fully; two close partially. Triage-at-prompt-arrival is still a reminder rather than a mechanism, with its blocking gate off by default. `agentType` spawns the reviewer by role, but Gate, Record and Finalize stay anonymous on purpose — **no agent under `agents/` declares a `tools:` restriction**, so spawning them by role would hand back the whole toolbox and undo the narrowing this release just finished. No row is left unclosed.

## [3.0.5] - 2026-09-02

### Fixed — routing that routes

Compound V has carried a tier vocabulary since 1.1. The manifest validator enforced it, five documents explained it, and until this release **it never reached `agent()`**.

`resolve_job_model` was invoked only for external backends, where `--model` is a required CLI argument. For `backend: claude` — every job in every real run — it was never called, `opts.model` was never set, and every agent inherited the session model. The tier was real everywhere except at the one call site that spends money. That is the thirteenth mechanism this project has shipped with no caller, and the second one found by asking a plain question about it rather than by a test.

Two more inputs were dead in the same place. The manifest's `routing_stance` and the project's own `/v:models` map were written by one command and read by nobody on the dispatch path: every resolution silently used the built-in balanced defaults. Both are now passed on every resolve.

### Changed — the ladder, and what decides it

Set by the maintainer on 2026-09-02. The split is **execution vs judgment**, not how much code a job touches.

**Sonnet executes.** A spec that already survived brainstorming and planning, HTML/CSS, Node plumbing, translations, mechanical refactors — and *reading* code, which is execution however large the codebase.

**Opus judges.** Deciding, and connecting parts of code to each other. Business logic with many code-level dependencies is Opus **however mechanical each individual edit looks**; coupling is the signal, not line count.

**Fable is the extreme seat**, reached through a new `frontier` tier — what a failed job escalates into, and where interface design belongs.

| Stance | `frontier` | `deep` | `standard` | `light` |
|---|---|---|---|---|
| balanced *(default)* | `fable` | `opus` | **`sonnet`** | `sonnet` |
| conservative | `fable` | `opus` | `opus` | `sonnet` |
| cost-aware | `opus` | `opus` | `sonnet` | `sonnet` |

`standard` on `claude` was `opus` before. Conservative is now the stance that keeps it there — that is what choosing it means. Reviewers are unaffected and unmovable: Invariant 3 still demands `deep`/`opus`, because a sealed review receipt must carry a Claude Opus `reviewer_model`.

### Added — transport, and escalation

**Gate, Record and Finalize are transport**, and are now routed as such. Each runs exactly one clamped command and hands back its JSON verbatim; the real logic is Python the integration authority re-verifies from git. They take the `light` cell instead of inheriting the session model.

**A job that failed is re-dispatched one rung up** — `sonnet → opus → fable` — and stops at the top. The signal is the recorded `results/<id>.json` status, never a counter we keep: an absent result is not a failure. Two exemptions, both load-bearing. A **reviewer** is never escalated, or its own receipt stops being valid. A **model the manifest pinned explicitly** is never escalated, because stepping a value we did not choose is a fabricated routing decision.

### Fixed — a reader of the tier vocabulary that had been wrong all along

Adding `frontier` surfaced it: the failure policy halted a `context_length` failure at `deep` as "the deepest tier, no bigger model exists". The naive fix is to escalate `deep → frontier` first. It would be wrong — `frontier` is a stronger model, **not a bigger context window**; Fable and Opus carry the same 1M window, so the escalation would buy nothing and would dress a fabricated remedy as a routing decision. Both tiers now halt, and the message says why.

Model discovery proposes `frontier` = its own `deep` pick for every external backend, since no vendor here ships a rung above its top model.

### Verified

`opts.model` was probed against the live 2.1.238 runtime **before** any of this was built — three clamped agents on `sonnet`, `opus` and `fable`; all three accepted. Then a two-lane Engine C run whose only routing input was the tier: `standard`→Sonnet, `deep`→Opus, both gated clean and merged as one commit. Six of that run's seven agents ran on Sonnet where all seven would have been Opus.

**That is a count, not a saving.** No cost and no duration were measured, and none is claimed.

Not exercised live: escalation (nothing failed, so nothing escalated — it is covered by selftests), the `frontier` tier inside a real run, and any stance other than `balanced`.

## [3.0.4] - 2026-09-01

### Fixed — the multi-wave dispatch, and one field name that meant two things

3.0.3 discharged the "first live run" caveat for a **single-job** manifest. This release runs a real **two-wave, four-job dispatch with `depends_on`**, and it found six more defects. Five of them are the same defect wearing five hats.

**`isolation` named two different things on two layers.** In the manifest it answers *"how are this job's changes attributed?"* — the validator requires `worktree` for parallel jobs and scope attribution depends on it. At the agent layer it answers *"where does this agent physically work?"* For an ordinary job the two answers coincide, which is why nothing ever caught this. For a **dependent** job they are opposite: the runtime's `isolation: 'worktree'` branches from the default ref, so a fresh worktree does **not** contain the wave that just committed — a dependent must run in the project checkout.

Five readers each broke differently: the agent option, the gate's root, the gate's mode, Record's branch, and `register-lane` — which decides both where the baseline is pinned **and** whether the pre-existing snapshot is taken, so the job that most needed a snapshot was the only one that never got one. All five now read the agent layer.

Proven live: wave 1's three parallel jobs merge into one commit, and the dependent job pins its baseline to **that commit**, not to the start of the run. The wave barrier is real.

### Fixed — a job that changed nothing was recorded as a success

The quietest defect of the release. The dependent job returned `files_changed: []`, the gate passed it, Record wrote `success`, and the wave finalizer honestly reported *"nothing left to commit"*. The whole chain reported success for work that never happened — **and every component was correct on its own terms**, because "no files changed" and "clean" are indistinguishable on a pass/blocked axis.

The manifest makes it decidable: a job with an empty `write_allowed` (a reviewer) is expected to change nothing; a job that declares lanes and fills none did not do its job. That now fails closed, as `blocked` with a `no_work` reason — **not** as a fourth verdict word, because the schema pins `verdict` to `pass|blocked|error` and the authority cross-checks it against `exit_code`. The first attempt did invent a fourth value, and the authority correctly read the incoherent receipt as `forged`: a refusal for the wrong reason sends whoever reads it hunting a forgery that never happened.

### Known and unfixed

**Model routing is not routing.** *(Fixed in 3.0.5.)* `resolve_job_model` is invoked only for external backends, where `--model` is a required CLI argument. For `backend: claude` — every job in every real run — it is never called, `opts.model` is never set, and every agent inherits the session model. The tier vocabulary exists and never reaches `agent()`. Under `balanced`, `deep` and `standard` both resolve to `opus` anyway, `light` is used by no manifest in this repo, and **Fable appears nowhere in the routing map**. This is the thirteenth mechanism this project has shipped with no caller; it is recorded here rather than fixed, because changing it changes the cost of every future run and that is the maintainer's call.

**The dependent job's implementer produced no file** across several runs. The machinery now refuses that correctly instead of blessing it, but why that particular agent declines to write is unresolved and is an agent-behaviour question, not an Engine C one.

## [3.0.3] - 2026-09-01

### Fixed — three defects found by dogfooding, none of which any gate had caught

3.0.2 shipped Engine C with 143 selftest checks, 50 contract assertions, three partition-gate rounds, two cross-model reviews and a three-pass Review Gate. Then it was **run for real**, and three defects surfaced immediately. All three sit on **seams between two components** — each half correct on its own, each half passing its own tests, and the contract between them broken. A selftest lives inside one half and cannot see that the halves agreed on different things.

**The DIRECT tier was unreachable through `/v:triage` for any request.** A request consisting of nothing but an existing filename — `TROUBLESHOOTING.md` — resolved to **301 paths** at `ambiguous`, fired Layer-A override #1 and fail-closed to FULL. Token extraction split it into `.md` and `TROUBLESHOOTING` and grepped `.md` across every markdown file. The consequence was not imprecision: the entire nine-predicate auto-route class, its compare-and-swap landing gate and its circuit breaker — all built and tested across 3.0 and 3.0.2 — could not be reached by any input. A request that names a file now resolves to that file, narrowly: only whitespace-separated words that are already a regular file, no globbing and no fuzzy matching.

**The probe surface under-reported the tier, always optimistically.** `compound-v-localize.py` with no explicit `--taxonomy` classified with **no content rules at all** and returned `flags: []`; `preeval --score-only` then scored that flagless localization and additionally omitted `churn_hot` and `tier2`. Two independent omissions, both cheapening the answer, on the documented way to ask "is this safe to auto-commit?". `README.md` read `low/low` through the probe and `low/high` through the engine. Probe and engine now agree exactly, and an absent taxonomy says so on stderr instead of looking like a clean classification.

**A dirty working tree blocked every direct-mode run.** In `direct` mode the gate measures the whole tree against the baseline, so pre-existing dirt was attributed to the job. The snapshot is now taken at `register-lane` — the only point that provably precedes the work — and never in worktree mode, where the tree starts clean and a subtraction could only hide a real violation. A failed snapshot falls into the stricter gate, never the looser one.

### Engine C has now run

Five live dispatches. It emits, implements, gates, records, finalizes the wave, asks the integration authority, merges and commits — and refuses correctly when it should: a dirty tree halted the run with nothing merged and nothing committed, and a crashed check counted as a failure rather than as "no violations found". The wave finalizer is idempotent: re-running found the work already in `HEAD` and created no duplicate commit.

The caveat carried since 3.0 — *"treat the first live run as a first live run"* — is now discharged for a single-job manifest. **It has still not run a real 18-job dispatch.**

### Also corrected

`docs/superpowers/dogfood/` withdraws its own tier table: every figure in it was measured with the broken probe above. `README.md`, `CHANGELOG.md` and `TROUBLESHOOTING.md` were all listed as auto-routable and **none of the three is**. Recorded rather than fixed: a file large enough to exhaust the content-scan byte cap scores `unknown`, so **file size alone can force the full pipeline**.

## [3.0.2] - 2026-09-01

### Fixed — Engine C's three criticals, and it is enabled again

3.0.1 disabled Engine C after a cross-model review of the shipped code. All three are closed, and **each is pinned by a test observed red against 3.0.1** rather than asserted:

- **A `direct` job's patch could land in the wrong repository.** `record` branched on whether the agent-reported worktree was empty — and a compliant direct agent always reports its cwd, so it always entered `merge_back` — while the emitted command carried no `--repo-root` and fell back to the repo containing the installed script. The reproduction observed `M README.md` **in the plugin repository**. The branch is now the manifest's `isolation`, `--repo-root` is required by every subcommand, and the default destination is deleted.
- **A job could land with the integration authority never having run.** `record` staged into the checkout before the gate and never committed, so any later plain `git commit` swept it into history. `record` is now evidence-only; a serialized `finalize-wave` gates each wave, merges only what the authority permitted, and commits pathspec-restricted. The wave loop stops scheduling after any non-success result.
- **The external worker lost its invocation and its worktree.** `emit` now materializes a per-job prompt and a complete launcher argv; the Gate carries its observed worktree into Record; `register-lane` pins the baseline before launch. An unpinned baseline fails closed.

Also closed: the lane-map read-modify-write raced (a 12-writer subprocess test pins it; a mutant reverting only the lock loses 1–3 of 12 lanes); `GATE_SCHEMA` rejected the `tests` object the Gate emits on every passing verdict; and a throw in Implement dropped the item past both Gate and Record — the v2.6.4 audit-trail loss, reproduced structurally.

### Fixed — the landing gate guarded `HEAD`, not the tree it committed

A *passing* `full_command` that staged one extra line raised an authorised 19-line diff to 21 **after** the in-lock revalidation, and `commit-tree` committed it with all predicates reporting PASS. The floor now runs against an isolated candidate index, and the predicates are re-checked against the exact tree handed to `commit-tree`.

### Fixed — DIRECT landings produce outcomes; the lane guard parses quotes

The landed commit sha is now the outcome key, and a revert sweep appends a correction under it, so the auto-route breaker can see a bad landing. **CI failure still has no producer for a DIRECT decision** and the breaker's header now says so per negative, rather than claiming a numerator it cannot fill.

The lane guard split Bash on `;` and `|` **before** parsing quotes, so `sed -i 's/a/b/; s/c/d/' README.md` was allowed — and, more expensively, `git commit -m "fix; rm README.md"` was denied. Replaced with a quote-aware scanner that also skips heredoc bodies. Fail-open discipline unchanged: nothing new can deny.

### Fixed — two published latency figures, neither reproducible

README said 63 ms, the hook's own header said ~112 ms. A re-measurement over 50 invocations per path reproduced **neither**. Both withdrawn; the measured range is **47–81 ms** (~31 ms bare-interpreter floor), and the deny path turns out not to be the expensive one — resolution and manifest parsing are.

### Changed — `agentType`, the last unused native mechanism, is used for the review role

A `type: review` job was receiving the generic implementer prompt with none of the reviewer's three-pass contract. Gate, Record and Finalize stay anonymous **on purpose**: their safety is `disallowedTools` plus `bashCommandClamp`, and no agent under `agents/` declares a `tools:` restriction, so spawning them by role would hand the whole toolbox back. The audit row says ⚠, not ✅.

### Still true

Engine C now carries 143 selftest checks and 50 contract assertions and **has still not run a real 18-job dispatch.** Treat the first live run as a first live run — that caveat is what 3.0 wrote and then ignored by shipping it as the default.

## [3.0.1] - 2026-09-01

### Fixed — Engine C is disabled by default; it had never run, and it has three critical defects

A post-release cross-model review of the shipped code returned **SHIP-BLOCKING DEFECTS FOUND**. All three criticals are in Engine C, the path 3.0 made the default **without ever executing it end to end** — only a three-stage seam probe had run.

- A `direct` job's patch could be applied into **the repository containing the installed plugin** rather than the project: every implementer returns `pwd` as its worktree, `record` decides direct-vs-worktree from whether that locator is empty, and the emitted Record command omits `--repo-root`.
- A job could **land without the integration authority running at all**: `record` stages with `git apply --index` before `/v:dispatch` runs the gate and never commits, so any later plain `git commit` sweeps it into history.
- **Dependents could not see their prerequisites**, since staged-not-committed work is invisible to a worktree created from `HEAD`.

Engine C now requires `engine_c: true` in `.claude/compound-v.json`. The residual subagent path is the default until 3.0.1's fixes land.

### Fixed — the result schema promised recovery the authority does not perform

`gate_receipt`'s description said a digest-mismatched receipt is re-derived and the new verdict wins. The code refuses it outright as forged, and the code is right — re-deriving a forgery over a tree that happens to be clean would reward it. The schema was the wrong public interface; corrected to match.

### Note

3.0's own release text said Engine C had never been executed. It should also have kept an unexecuted path off the default. That is the lesson this release records.

## [3.0.0] - 2026-09-01

### Changed — the native runtime becomes the execution engine

Compound V stops being an orchestrator. Claude Code grew a native orchestration runtime and a full set of enforcement points; this release hands execution to them and keeps the parts that have no native equivalent: **triage, disjoint file lanes, the git-derived verdict, cross-session recovery and the cross-vendor arbiter.**

The audit that drove it is committed at [`docs/superpowers/architecture/native-mechanisms.md`](docs/superpowers/architecture/native-mechanisms.md) — 23 guarantees matched against the mechanism that could provide them. Of those, **11 had a native mechanism that covers the need and which we were not using**: five decided in 1.0 and never built, three we did not know existed, one never looked at, one deleted on a false premise, one rendered by hand. All eleven are used now.

**Requires Claude Code ≥ 2.1.219.**

### Added — proportionate triage, with a caller

A three-tier decision (`DIRECT` / `SCOPED` / `FULL`) replacing the two-value one, computed inside the engine so a fired override can never be paired with a cheap tier. The existing 7,883-line scorer needed no new scoring logic — it needed an entry point. It now has three: `/v:triage`, a `UserPromptSubmit` nudge, and a manifest validator that **refuses to validate a manifest without a triage block** when `/v:dispatch` passes `--require-triage`, which it does in every mode.

A narrow auto-commit class gated on nine mechanically checkable predicates, including a floor that must have passed, full post-diff re-validation against an immutable pre-edit taxonomy snapshot, and a `git update-ref` compare-and-swap so two sessions cannot both act on the same authorization. A miscalibration breaker counts **negative outcomes** — CI failures, reverts, escalations — not demotions, which a demotion-only counter structurally cannot see.

### Added — tests proportionate to the change, bought with a floor

`test_contract` and per-job `test_scope` in the manifest, transported to workers as a real argument rather than prose in a prompt. The floor is impacted ∪ previously-failing ∪ newly-added; an unmapped path resolves to the full suite, never to nothing.

**Stated plainly, because it is the point:** the floor is early feedback. It does **not** restore what the full suite guaranteed — CI does, and CI always runs. Call-graph-derived test selection is measured at 0.2%–10.6% unsafe per revision, and a hand-written glob map carries strictly less information than a call graph, so 0.2% is an optimistic floor rather than an expectation. This reverses a decision made in 2.17; the reasoning is recorded in [ADR 0003](docs/superpowers/adr/0003-scoped-tests-with-a-floor.md).

### Added — lane enforcement before the write

A `PreToolUse` deny that refuses an out-of-lane `Write`/`Edit`/`Bash` write. Its limits are recorded as **passing tests rather than comments** — interpreter one-liners, variable-held paths and build tooling are not caught by command inspection, and are caught by the git-derived postcondition instead, which remains the authority. The guard runs on every matching tool call in every session. **The 63 ms figure published here in 3.0.0 is withdrawn:** a re-measurement over 50 invocations per path reproduced neither it nor the ~112 ms the hook's own header carried. The measured cost is **47–81 ms** — ~47 ms when no job resolves, ~81 ms when one does, against a ~31 ms bare-interpreter floor. The deny path is not the expensive one; resolution and manifest parsing are. See `hooks/lane-guard.sh`'s COST header for the reproduction command.

### Fixed

- `run_test_floor` had never executed once: `--test-cmd` had no producer. It has one.
- The floor recorded commands via a lossy shlex join, so a recorded failure could not be re-run — silently shrinking the next run's previously-failing set.
- Merge-back diffed against `HEAD` rather than the pinned baseline, so an executor that committed inside its worktree passed the gate while its committed half failed to land.
- CI executed nothing under `tests/`. It now sweeps recursively, as a job that always runs and fails when it discovers nothing.

### Note on measurement

No speed or cost claim ships with this release. The observation that motivated proportionate tests — a one-word change running a full suite — was **not reproduced** by any lane of the recon, so Feature B's defaults are **principle-derived, not measured**. The pipeline now records selected-test counts and measured-only durations so the next release can speak from our own data.

## [2.19.0] - 2026-08-30

### Fixed — the SessionStart banner becomes stateful ("Claude forgets")

`SessionStart` fires on **`compact`** as well as `startup`, but `hooks/session-banner.sh` was **stateless**: it emitted identical text to a fresh session and to one that was six hours into a 16-job dispatch. What a compaction destroys is not the rules — the skill body brings those back — but the agent's **position** in the pipeline.

The reported failure looked exactly like that: an agent ran the full pipeline for features 1 and 2 of an epic, then improvised a mid-flight rescope, skipping recon and brainstorming, and self-reported it only when the user asked whether it was still running Compound V.

- **`compound-v-dashboard.py resume`** — a new read-only subcommand reusing `build_records()`. Prints ONE line naming unfinished runs/epics (id, phase, job progress, age), or nothing at all. `--json` for machine use, `--max-age-hours` to widen the window.
- **Freshness comes from the recorded timestamp, never a file mtime.** Found during live probing: git rewrites mtimes on clone and branch-switch, so an mtime window made all seven historical runs look seconds old on a fresh checkout. A record with **no** recorded timestamp stays silent rather than being assigned a fabricated age. Covered by a named regression test.
- **The spec-write nudge now refutes the incident's two excuses.** `doc-validator` is skipped only when a spec has **zero** technical dependencies — *"no NEW dependency"* is not the rule, because dependencies you already use go stale and acquire CVEs. And a rescope re-enters the pipeline at the top: earlier compliance within an epic does not carry.
- **An absent recon doc is now declared, not passed over.** Trigger 0 runs *before* a brainstorm and cannot be replayed once a spec exists — a retroactive recon would be the fabricated-evidence pattern, not a recovery. All the hook can honestly do is turn a silent skip into a stated one.
- Three new rows in `rationalization-table.md` for the same incident.

### Added — CI gate: every committed run dir carries a committed `state.json`

Found while verifying the fix above: the last **four** run directories (2026-07-13 … 2026-07-25) ship a `manifest.yaml` with **no** `state.json`. The last committed run state is 2026-07-11. `/v:status` renders `NO STATE` for all four, and the new resume banner — which reads `state.json` — was blind to exactly the runs it most needs to see.

Root cause is this release's own theme: `/v:orchestrate` step 6 writes `state.json` and step 8 commits it, and **both are prose in a markdown file**. An agent can satisfy neither and nothing breaks. Now it breaks.

The four are **allowlisted by id, not back-filled** — their state is genuinely gone, and reconstructing an audit trail after the fact is fabricated evidence, not a repair. The gate was verified to actually fail: a planted run dir with a staged manifest and no state exited 1 and named the directory; removing it returned 0.

### Note on versioning

2.18 is skipped as a release number. The `v2.18-autonomy` branch (Stop-hook restoration, `timeout_sec` validation, Iron Five relocation) is real but unfinished — no command wiring, no Review Gate, no cross-model pass — and will land under a later version rather than being shipped half-wired.

## [2.17.0] - 2026-07-26

### Added — Co-change advisory (ordered, git-derived) + failure-prioritized evidence packing

Two approaches internalized from a critical read of the [`repowise`](https://github.com/repowise-dev/repowise) project (AGPL-3.0 — **ideas only, NO code copied**), then built from scratch against this repo's own history. Six further candidates from the same review were evaluated and rejected on our own data.

**Feature A — co-change advisory: the inverse of the scope gate.** The scope gate answers *"did a worker write OUTSIDE its lane?"* — a containment question. It cannot answer the opposite failure: *"does this partition own file A but forget partner file B, which this repo's own history says almost always moves with A?"* New `scripts/compound-v-cochange.py` (`rules` / `check`) answers that from `git log` alone — **zero model involvement**.

- **ORDERED rules, never symmetric pairs.** It emits `A -> B` with its own direction: `marketplace.json -> plugin.json` and `plugin.json -> marketplace.json` are two distinct rules with different support and different confidence, because "is B missing when A moves?" is a directional question.
- **Four conjunctive bars before a rule fires** — support ≥ 8, P(B|A) ≥ 0.70, a 95% Wilson lower bound ≥ 0.50 (guards small-sample luck: `8/11` reads as 0.73 but its lower bound is 0.43), and narrow support ≥ 3 (co-changes in non-release, non-format commits touching ≤ 10 files — what separates a real coupling from a wide doc sweep). Release and bulk commit counts are reported beside every rule so a headline `support` can't be read in isolation. Rename unification (`-M`) is applied, so a rename cannot manufacture a phantom rule. `--explain-rejections` shows what was rejected and on which bar.
- **ADVISORY — it adds NO NEW hard gate.** `compound-v:partition-reviewer` now writes its `PASS`/`FAIL` verdict FIRST (new Step 6.5) and only then runs co-change (Step 7), which may **only append** to an unconditional `WARNINGS` section rendered for BOTH PASS and FAIL. There is no `FAIL: COCHANGE_*` code and the agent is instructed not to invent one. The guarantee is **ordering-bound, not exit-code-bound**, because an exit code cannot bind an LLM reviewer — and `check` **exits 0 whether or not it finds anything** (non-zero is reserved for operational errors), which is what structurally stops a caller from promoting a correlation into a gate.
- **It does NOT replace either existing CI lockstep guard, and neither guard changed.** CI enforces the plugin.json / marketplace.json / CHANGELOG versions **exactly, at push time**; co-change advises **statistically, at partition time**, about a file a plan may have forgotten. Both stay.
- **"Could not tell" is a distinct answer from "nothing found."** A byte-capped git read or a history too short to clear the support bar returns `complete: false` with a reason and emits **no rules at all**; the reviewer must report that as `NOTE: COCHANGE_INCOMPLETE` ("could not determine"), never as a clean bill of health. A non-zero git exit is surfaced as an operational error, never flattened into "no rules".
- **Anti-ruflo:** every warning carries support, rate, Wilson lower bound, narrow support and the sample window **verbatim** — no risk score, no confidence %, no "likely". Inventing a summary metric on top of the counts is precisely the fabricated-evidence failure this project exists to prevent.

**Feature B — failure-prioritized, explicitly lossy evidence packing.** Every truncator feeding an external judge was a tail-drop, so it amputated exactly the traceback at the END of a log. `pack_evidence()` in `scripts/compound-v-collect-results.py` keeps the failure content and drops the filler instead, via a TOTAL 8-rung loss hierarchy (byte-identical passthrough → drop non-failure spans → zero the context radius → priority-allocate and truncate an oversized span → shrink the header → drop the header and all markers → a fixed placeholder → omit the block).

- **The claim is exactly "failure-prioritized, explicitly lossy, and always within budget" — NOT "never drops a failure line".** Those two are mutually impossible: failure lines alone can exceed any budget, and a log where every line is an `ERROR` has no filler left to drop. Rungs 5-7 are **unmarked by construction** — there is no room left for a marker, so the rung reached IS the signal (the caller logs it).
- **Packing runs AFTER redaction, and that ordering is the security property.** `redact_uncapped()` is extracted from `compound-v-epic-arbiter.py` with both fail-closed rules intact (unclosed PEM/PGP block, unclosed quoted labelled secret), and the evidence path is redact → fail-closed → pack, on already-sanitized text. Packing only deletes WHOLE lines, so it can never un-redact. Packing first would be a real egress hole, not a style preference: dropping a key's `BEGIN`/`END` or a `password=` label line destroys the multi-line structure redaction matches on, and a short secret would then also evade the opaque-token regex. Omission markers are path-free by construction and `section_label` is a closed enum.
- **An over-budget prompt SKIPS the poll** with a bounded diagnostic rather than silently truncating it. A missing ballot is honest; a quietly-shortened prompt changes what a judge votes on.

**ADR 0002 — any published number ships with its limits in the same document** ([`docs/superpowers/adr/0002-limits-ship-with-the-claim.md`](docs/superpowers/adr/0002-limits-ship-with-the-claim.md)). The anti-ruflo CI gate catches *fabricated* numbers; it cannot catch a number that is entirely real and still misleads because the reader can't see what it was measured on. Every published figure now carries a "What this does not show" note next to the claim. Five alternatives declined, including `CONVENTIONS.md` (generated — `/v:onboard --refresh` would silently erase the rule) and a CI grep (a regex cannot separate a claim from a version string, and widening the anti-ruflo gate would false-positive itself into being disabled — the v2.14.1 lesson). The ADR applies the rule to itself and states plainly that it creates no hard gate.

### Verification

Selftests under `LANG=C` on the Python 3.9 floor: `compound-v-cochange.py` 69 cases; `compound-v-collect-results.py` 94 checks; `compound-v-epic-arbiter.py` 237 checks (was 196 — the original 196 are untouched); `compound-v-scope-check.py` passing; frontmatter lint clean. Run against this repo's own history, the engine emits **six firing ordered rules** and nothing sub-threshold.

#### What this does not show

Those six rules were measured on **one repository — this one** — over the 381 eligible commits in its history at the time of measurement, with a ≤ 10-file narrow-support bar calibrated to this repo's commit width. A young repo, a squash-merge-only history, or a wide monorepo will legitimately produce **no rules at all**; that is a correct result, not a failure. A rule is a **correlation** in past commits — not a causal claim, and not a contract that two files must move together. The historical single-file touches behind these rules are **unpaired historical touches**: an unadjudicated signal. None was adjudicated as a violation and this release does not claim any was one. Nothing here measures whether the advisory improves review outcomes, catches real omissions in practice, or saves any time or tokens — no such measurement was taken.

## [2.16.0] - 2026-07-15

### Added — Decision memory + challenge (recall your own past reasoning, always challenged)

During the brainstorm/elicitation phase Compound V already intercepts, it now **remembers your own dated past decisions** and surfaces them as *falsifiable history* — **always paired with a divergent counter-move**, so a recall triggers re-examination, not autopilot. New `scripts/compound-v-preferences.py` (`recall`/`capture`/`distill`/`stats`/`purge`) + `/v:preferences` + a `brainstorm.preferences` config key. Grounded by three pre-flights whose **domain audit reframed the feature**: the original "let the brainstorm reason as the creator" clone was rated high-hazard (choice-blindness confabulation, default-nudge dark patterns, echo chamber, opposing this project's own anti-anchoring moat), so v1 ships the safe **memory + challenge** framing instead.

- **Three modes** `off | on-demand (default) | marked`. **`marked`** puts a soft, falsifiable dated badge (`↩ your past pick: N/M · date`) beside the matching option — a **label, never a pre-selected default** (a mark is information; a pre-tick is an answer you must override — the audit's red line). Every surfacing is challenge-paired or suppressed (`no-challenge`).
- **The "why" is captured UNPROMPTED** (free-text first); a tapped candidate is a weaker `borrowed` class, excluded from the distilled "your reasoning" — never an inferred rationale.
- **Anti-anchoring:** suppressed on recon-touched / high-novelty forks (never fires where Trigger-0 widens). **Drift honesty:** recency-weighted last-K disagreement demotes + banners a shifting pattern; a holdout probe records un-nudged choices; patterns auto-expire.
- **Split storage:** the raw `decisions.jsonl` stays **LOCAL** (`~/.claude/compound-v/preferences/`, private, `purge`-able); the distilled `preferences.md` is written **in-repo** (`docs/superpowers/preferences/`, git-tracked → V-memory, `/v:remember`-able) and is **secret+PII-scrubbed before write**.
- **Anti-ruflo:** counts only (`4/5 similar forks`), never a fabricated confidence `%`; recall is evidence, never an authority — the brainstorm human-gate is untouched. Pure Python 3.9 stdlib (reuses V-memory's `fts5_escape` + `redact` and `append_line` by import); `--selftest` auto-run by the CI all-selftest gate.

## [2.15.0] - 2026-07-14

### Added — Local observability dashboard (present-only, read-only)

Closes the plugin's biggest competitive gap (no observability UI) — while keeping the no-daemon / git-derived-control philosophy. New `scripts/compound-v-dashboard.py` renders `docs/superpowers/execution/**` (runs, epics, per-job status, scope-gate verdicts, usage, blocker ledger) as a browser view; wired through `/v:status --html|--serve` and the new `/v:dashboard` command.

- **`emit`** — a **self-contained static HTML snapshot** (data inlined, offline, theme-aware — for sharing / audit), written to a git-ignored `docs/superpowers/execution/dashboard.html`.
- **`serve`** — an **ephemeral, read-only, `127.0.0.1`-only** live viewer that auto-refreshes as a run/epic progresses (the local equivalent of a competitor's live agent UI). It is a foreground process you Ctrl-C; it never backgrounds, never auto-launches, binds loopback only, serves **GET/HEAD only** (any other method → 405), is realpath-contained to the execution root (traversal / symlink-escape → 403, non-`.json/.html/.yaml` → 404, no directory-listing leak), and writes nothing to any run dir.
- **Read-only by design — observe in the browser, control via the CLI.** No merge/kill/retry buttons; the guarantees stay git-derived and human-gated (the moat, not a gap).
- **Anti-ruflo — a dashboard that does not lie:** renders only what is in the state files — real counts (never a fabricated `%`-progress), measured-only usage (`—` when a backend reports none, never a fabricated `0`), and only real timestamps sourced from the state files. Degrade-safe: a run with only `manifest.yaml` shows "no state yet", malformed JSON shows "unparseable", an empty root shows "no runs yet" — never a crash.
- Pure Python 3.9-safe stdlib (`http.server`, no Flask/CDN/npm); `--selftest` (auto-run in CI by the v2.14.1 all-selftest gate); security posture verified live (loopback bind, 405/403/404 on the attack cases).

## [2.14.1] - 2026-07-14

### Fixed — CI safety net & housekeeping (from a plugin health audit)

A 5-dimension health audit (dead-code · CI/test-coverage · doc/skill-drift · contract-consistency · safety) found the plugin CODE clean (all safety invariants hold, contracts tight) but two real holes in the CI safety net that let regressions ship green.

- **CI ran only 4 of 29 script `--selftest`s.** `validate.yml` now runs **every** `scripts/*.py --selftest` (dynamic discovery) under the Python 3.9 floor — previously only the marathon quartet (epic-state/arbiter/watch/headless-shim) was defended, leaving the scope gate (`compound-v-scope-check.py`), model resolver, pre-eval, usage, memory, and the collector uncovered. It also validates **every** tracked run-manifest (not just the example) and hard-fails if the validator script is missing.
- **The intra-plugin dead-link guard was a silent no-op.** Its `fail=1` was set inside a piped `while` subshell and never propagated, so the guard printed dead links but never failed the build. It now accumulates hits in a temp file, covers `.py/.sh/.json/.yml` link targets (not just `.md`), and strips `:line` suffixes. Fixed the 10 dead cross-refs it now catches.
- **Test coverage:** added `--selftest` to `compound-v-collect-results.py` (33 checks over the real job_result conformance logic CI previously only checked via a drift-prone reimplementation) and `compound-v-update-memory.py` (15 checks).
- **Cleanup:** removed two dead helpers (`_split_lines`, `_repo_root_default`) and a stray `models.err` (now gitignored).
- **Docs:** corrected the stale "devin/opencode worker not yet built" claim (both scripts are built; auth-pending/unverified), added `/v:adr` to the AGENTS.md command table, and documented the v2.14 headless `--allow-build` opt-in.

## [2.14.0] - 2026-07-14

### Added — Confirmed blockers (2nd external family) + headless resurrection shim

Built as one dogfooded epic (`docs/superpowers/execution/2026-07-14-v2.14-blockers-and-headless/`), grounded by three LIVE pre-flights (archaeology · domain · library) that reshaped the design before a line was written, plus three user policy decisions.

**Confirmed blockers — `done_with_blockers` now reachable via a genuine 2nd external family.**
- The marathon arbiter panel (`compound-v-epic-arbiter.py`) now polls a **second, distinct external model family — Gemini via `agy`** — read-only, alongside Codex (GPT). The advisory poll passes an **explicit resolved Gemini `--model`** (family derived from that string, **fail-closed** — `agy` 1.1.1's catalog is no longer Gemini-only), reads stdout, reuses the Codex redaction/parse/security-boundary path, and passes **no** `--dangerously-skip-permissions` (verified live: `agy --print` answers read-only without it).
- A blocker is **CONFIRMED only when ≥2 distinct external families agree on the SAME `blocker_category`** (closed enum: `credential | external-account | infra | third-party-data | legal-approval | human-decision`) — not merely the `blocked_external` label. This defends the correlated-oracle false-confirm (two LLMs hallucinating different missing facts under the same label).
- `compound-v-epic-state.py` **derives** `confirmed` from the arbiter's **frozen audit** (bound via a new `--audit-file`, realpath-contained + validated: matching `epic_id`/`feature`/`blocked_external` disposition, `audit["confirmed"] is True`) — **never** from a caller-supplied `--families-agreeing` CSV (which stays as recorded metadata), and raw `--confirmed`/`--blocker-confirmed` booleans stay hard-rejected. It adds the **`done_with_blockers`** terminal (a *successful*, auto-merging terminal) + an awaiting-final-review pre-terminal + the mandatory `is_terminal` prefix; records the agreed `--blocker-category` on the ledger; auto-sets a **durable `blocker_audit_due`** obligation on a confirmed blocker (gates `record_final_review(passed)` + the terminal until an approved re-review clears it, with an atomic `--record-blocker-audit-failed` revert on ISSUES); and relaxes `record_final_review(passed)` to accept an epic whose only non-`done` features are confirmed-blocked. An **abandoned/`halt_feature`** feature or a **SUSPECTED** (unconfirmed) blocker still halts to `blocked_needing_human`. The checkpoint (non-marathon) path is byte-identical.
- `/v:epic` auto-merges `done_with_blockers` via the final integration review → `finishing-a-development-branch` (the chosen policy); a confirmed blocker is **always over-sampled** by a durable-obligation PASS-integrity re-review (verifying the frozen audit's `confirmed`, ≥2 distinct external families on the same category, and no retry dissent); and the blocked remainder (feature · category · families · evidence) is **surfaced to the human, never silently dropped**. Framed honestly: ≥2 distinct families is the **minimum defensible bar** — distinct-family LLM votes are correlated (shared pretraining/RLHF), not fully independent — paired with same-category agreement + audit over-sampling, not treated as strong independent corroboration.

**Headless resurrection shim — opt-in, present-only.**
- New `compound-v-headless-shim.py emit --os macos|linux` **prints** a macOS `launchd` plist / Linux cron entry + runbook so a user can opt into resurrecting a marathon epic while the desktop app is closed. It is **present-only** — the plugin never `launchctl`/`crontab`-installs it (AST-asserted) and never runs the agent.
- The emitted command uses **`--permission-mode dontAsk` + a curated `--allowedTools` allowlist** (runs read-only + allowlist, refuses everything else) — never a bypass flag. The runbook carries a prominent DO-NOT block referencing the repo-deletion incident. It bakes an **absolute** `claude` path (fails the emit if unresolved), `/dev/null` stdin, and prints `launchctl bootstrap gui/$UID` (modern) as the user's install step. Honest boundary: launchd fires on wake with one coalesced catch-up; it does not run while powered off/asleep, and a `gui/$UID` LaunchAgent needs a GUI login.

### Changed
- `.github/workflows/validate.yml` runs the new `compound-v-headless-shim.py --selftest` under the Python 3.9 floor alongside the existing epic-state/arbiter/watch selftests.

## [2.12.0] - 2026-07-13

### Added — Per-ticket usage capture + on-demand cross-brand advisor

Two features, built as one dogfooded epic (`docs/superpowers/execution/2026-07-13-usage-and-advisor/`), grounded by three LIVE pre-flights that changed the design before a line was written.

- **Feature A — measured usage on `job_result`.** A new optional `usage` object (`{input_tokens, output_tokens, advisor_calls, backend, measured}`) is threaded worker → collector → aggregator → `/v:status`, recording ONLY real measured backend output (anti-ruflo: never an estimate).
  - `scripts/compound-v-usage-extract.py` (new) normalizes per-backend event streams (verified live, not from training data): codex `turn.completed.usage` summed across turns, opencode `step_finish.part.tokens`, cursor `result.usage`. Backends with no machine-readable usage (antigravity `agy`, claude-via-Task subagent, devin) emit `measured:false` + null tokens — fail-open, never a fabricated number.
  - `scripts/compound-v-collect-results.py` `build_result()` now passes `usage` through (a pre-flight-caught blocking gap: the collector re-synthesizes every result and previously dropped it, so every measured value was silently discarded).
  - `scripts/compound-v-usage-aggregate.py` (new) rolls usage up per ticket/feature/epic, counting `measured:false` jobs as "unmeasured" rather than zero. `/v:status` gains a degrade-safe usage column; the old blanket "no token metrics" line is reworded to permit MEASURED usage while still banning estimates.
- **Feature B — on-demand cross-brand advisor (opt-in, subagent pattern).** A cheap Sonnet executor consults a stronger advisor of a preferably DIFFERENT brand (Codex if available, else Opus) only on a hard sub-decision.
  - Live pre-flight REFUTED the assumed `claude -p --advisor` flag (it does not exist) and rejected the real `advisor_20260301` API tool (requires an API key + `anthropic` SDK, breaking the plugin's pure-stdlib/no-service/subscription ethos). Advisor is therefore a harness subagent pattern.
  - `scripts/compound-v-resolve-model.py` exposes `advisor_eligible` (a standard/core-slice implementer OR a fast-path Claude worker) and a cross-brand advisor selector (codex > other non-claude > Opus fallback; never Haiku). `scripts/compound-v-validate-manifest.py` validates an optional per-job `advisor:` block and rejects it on ineligible job types; manifests without it stay valid.
  - `scripts/compound-v-advisor-consult.sh` (new) runs ONE READ-ONLY advisory turn — `codex exec --sandbox read-only` or `claude -p --model opus --permission-mode plan`, and **NEVER `--dangerously-skip-permissions`**. A read-only advisor that cannot write files structurally forecloses the 2026-07-13 nested-bypass-agent incident. Proven by a fake-backend stub test with no live run.
  - `scripts/compound-v-preeval.py` gains an `advisor_calls → escalate` sensor (a fail-open, escalation-only clone of the `churn_hot` triad): repeated advisor consults are a post-run signal that a job was harder than its tier.

## [2.11.0] - 2026-07-13

### Added — Auto-resurrection watch (opt-in, marathon-only)

v2.10 shipped the Marathon Loop but deliberately deferred auto-resurrection: a hard death still needed a human to re-run `/v:epic <epic-id>`. v2.11 closes that gap with an ADDITIVE opt-in `watch` surface on top of marathon (`--watch` at `--init`, rejected without `--stance marathon`; no in-place upgrade of an existing epic, same rule as marathon itself). A watch-off marathon epic stays byte-identical to v2.10 — none of the fields below are ever written for it.

- **V1 — atomic resume authority + liveness heartbeat** (`scripts/compound-v-epic-state.py`): `--claim-resume` is the crux — ONE `fcntl.flock`-guarded atomic transaction that decides whether a scheduler-fired session may resume a dead epic, returning `{"claimed","reason":"claimed|live|terminal|resume-cap","resume_count"}`. There is no pid or lease object involved — the Claude Code harness has no stable driver pid across shell calls, so a FRESH `last_progress_at` heartbeat alone defers the claim (`live`) and the `--claim-resume` flock is the sole ownership/serialization authority, closing the duplicate-resurrection gap an earlier pid-lease design would have had. `--liveness` is a read-only watcher poll (`{"incomplete","stale","epic_status","terminal","resume_count"}`); `stale` requires incomplete, non-terminal, and past a heartbeat threshold (default 45 min) — heartbeat age is the whole staleness signal. `--renew-lease` is the live driver's own heartbeat call (kept under its original flag name for driver-side stability): it simply bumps `last_progress_at` to now, no pid, no TTL, nothing to create-or-renew. A new `resume_count` global breaker axis (`max_resume_count`, default 20) permits N resumes and blocks the (N+1)th, tripping the same `blocked_needing_human` latch as every other breaker; `--clear-breaker --reset-resume-count` re-arms it. Built directly on v2.10's crash-safe resume — nothing about the existing single-process marathon path changed.
- **V2 — two-tier watcher** (`scripts/compound-v-epic-watch.py`, new): never talks to a scheduler directly and never re-implements any state-spine logic. `emit-prompt` prints a SELF-CONTAINED resume prompt for a scheduler to hand to a fresh, memoryless session — that session calls `--claim-resume`, branches on the result, and performs the full disarm inline on a terminal/resume-cap verdict (a cold-prompt design: no conversation history is assumed). `plan` reads `--liveness` and advises the two tiers' cadence (off-minute `:17`/`:47`, ~30 min apart) and whether to disarm. The driver (`/v:epic`, not this script) owns the real scheduler wiring — session `CronCreate`/`CronDelete` for Tier-1, `mcp__scheduled-tasks__create_scheduled_task`/`delete_scheduled_task` for Tier-2.
- **V3 — idempotent watcher registry + driver arm/disarm + capability detection**: `--record-watcher-armed`/`--record-watcher-disarmed`/`--list-watchers` track scheduler tasks idempotently by `(provider, task-id)`, so a crash-and-replay during arming or disarming is a harmless no-op, never a duplicate or a leak. `/v:epic`'s marathon loop (`commands/v-epic.md` §0c "Watch-on marathon start" and "Watch disarm") bumps the heartbeat and arms both tiers once at invocation start (recording an intent record before each real scheduler create call, so a crash mid-arm never double-arms on re-entry), re-arms a Tier-1 task past its ~7-day expiry, and disarms both tiers (plus a deterministic-id fallback, attempted even when the registry is empty) at every terminal exit. `/v:init` gained a capability-detection step for scheduler availability on this machine, feeding the `epic.autonomy.watch` config key (consulted only once, at a NEW epic's `--init` — the persisted `epic-state.json` is the sole authority afterward).
- **CI**: `.github/workflows/validate.yml` now also runs `python3 scripts/compound-v-epic-watch.py --selftest` in the same Python 3.9 step as the existing `compound-v-epic-state.py`/`compound-v-epic-arbiter.py` selftests.

### The corrected honest boundary (v2.11) — still not "survives while you sleep"

Auto-resurrection is bounded and partial, not magic:

- **Tier-1 (session `CronCreate`)** pauses while the session is unavailable or busy, MISSES any fire that elapses while paused (no catch-up), may restore on the next conversation turn while still unexpired, and expires after 7 days even inside a continuously open session.
- **Tier-2 (`scheduled-tasks`, on-disk)** runs only while the desktop app is open and the machine is awake; it performs exactly ONE catch-up for the most recent missed run on app start/wake, within 7 days. It is not an always-on server.
- **"Survives quota exhaustion"** holds only if the quota has since reset AND the session is still authenticated — an expired OAuth token still needs a human.
- **A machine that is truly off (laptop closed, asleep) is not covered by either tier.** Genuine machine-off execution needs remote infrastructure, never claimed built-in here.
- **Resurrection is bounded** by `max_resume_count` (default 20) — a persistently-dying run halts at `blocked_needing_human` for a human, same as any other tripped breaker.

Opt-in (`epic.autonomy.watch`, default off); the default epic and a watch-off marathon are unchanged. No fabricated cost/token metrics anywhere in this surface.

### Provenance

Built on v2.10's crash-safe marathon resume. Cross-model reviewed by **Codex gpt-5.6-sol**.

## [2.10.0] — 2026-07-13

### Added — Marathon Loop (opt-in autonomous `/v:epic`, PHASED scope)

An opt-in **marathon** stance for `/v:epic`: instead of stopping at every feature checkpoint, the epic can chew through the whole runnable feature DAG in one invocation. The default `checkpoint` epic is **behaviorally unchanged** — marathon is chosen only at `--init` time and cannot be flipped onto an existing checkpoint epic. Scope was deliberately PHASED after three Codex Sol `xhigh` review rounds converged that every *critical* concurrency finding traced to auto-resurrection (a two-tier watcher reviving the epic while you're away); removing that from v2.10 makes the marathon single-process and the whole class of concurrency criticals disappears. See `docs/superpowers/specs/2026-07-12-epic-autonomous-mode-design.md` for the full scope decision and the deferred v2.11 sketch.

- **Marathon Loop + DAG-autonomous routing** (`scripts/compound-v-epic-state.py`): a marathon-only `autonomy` state block, `--next --autonomous` (a separate, read-only routing function from the default `--next` — byte-identical default behavior preserved) that routes on deterministic DAG reachability, so an abandoned or blocked feature removes only its *transitive dependents*, never its independents. `attempts` tracking, `--can-retry`, `--record-disposition`, `--record-final-review`. **Terminal states:** `done` (all features done **and** a persisted `final_review.status=="passed"` — never on feature-completion alone), `blocked_needing_human` (a tripped breaker, a `halt_epic` verdict, or exhausted reachable work), `running_with_failures` (non-terminal). `done_with_blockers` is defined but structurally unreachable in v2.10 (needs a 2nd confirming external model family — deferred to v2.11).
- **Cross-model Arbiter Panel** (`scripts/compound-v-epic-arbiter.py`, new): classifies a feature FAILURE via a two-phase, **challenge-bound** API — `--prepare` issues a bounded Claude ballot-task prompt tied to `{epic_id,feature,attempt,challenge_id}` (an HMAC-keyed, per-epic challenge secret; a mismatched/replayed/stale challenge is dropped before any model call), then `--classify` polls Codex (real sandbox, read-only, through the timeout supervisor, evidence size-capped and secret-redacted before egress) and validates a driver-supplied Claude ballot, aggregating both with a complete, deterministic truth table. **Family-diverse aggregation:** ballots collapse one-per-family (`gpt`/`gemini`/`claude`/`grok`/`unknown`); a parse-failed or errored ballot is dropped and logged, never fabricated as a vote; empty or tied → conservative `halt_feature`; `retry_fix` past the per-feature retry cap is masked to `halt_feature`. Antigravity/Cursor are excluded from arbitration (no kernel write-confinement) — implementation workers only, never advisors. **Fail-closed secret redaction** before any external-model egress (labelled tokens, auth headers, private keys, URL credentials, multiline/unclosed-quote secrets — omits the suspect evidence rather than risk a half-redacted leak). **O_NOFOLLOW evidence containment**: every untrusted path under the arbiter's audit directory is opened via dir-fd + `O_NOFOLLOW` (TOCTOU-safe — never validate-a-name-then-reopen-it), atomic tmp+rename writes, capped/rotated audit JSONs so an all-night run can't fill the disk. Every ballot + resolved family + aggregation reason is frozen to `docs/superpowers/execution/epics/<epic-id>/arbiter/<feature>-<attempt>.json`.
- **Blocker Ledger** (`scripts/compound-v-epic-state.py`): "do everything you can" — finish everything reachable, isolate only the genuinely impossible, escalate with proof, never halt the rest. A `blocked_external` disposition marks a feature `blocked` (ledger entry) without halting the epic; `--next --autonomous` skips it and routes around only its transitive dependents. **v2.10 blockers are always SUSPECTED** — `--blocker-confirmed true` is hard-rejected everywhere it could be set; CONFIRMED (`≥2` distinct known external model families agreeing) is structurally unreachable on a Codex+Claude-only panel and is deferred to v2.11 alongside a second safe external family and the `done_with_blockers` terminal.
- **Global circuit breakers + human resume** (`scripts/compound-v-epic-state.py`): `total_attempts`, `no_progress_cycles` (a full autonomous pass that advances `done` by zero), and wall-clock hours since `autonomy.started_at` — counts and hours only, **never a fabricated cost**. `--breaker-check` is read-only; `--trip-breaker` atomically parks the epic at `blocked_needing_human`. Re-checked before every feature *and* before every model call (arbiter, sample-audit, final review) — an honest, not a hard real-time, guarantee. **Human recovery, never automatic:** `--clear-breaker` (`--reset-wall-clock`, `--set-max-total-attempts N`) re-arms a tripped breaker; `--clear-disposition` clears a sticky `halt_epic` verdict — both followed by the human re-running `/v:epic <epic-id>`, which is re-entrant and resumes the marathon from `epic-state.json`.
- **PASS integrity — anti-reward-hack gate** (`agents/spec-reviewer.md` §2.5, `commands/v-epic.md`): a marathon SUCCESS is not blindly trusted. The reviewer contract gained a deterministic "did this diff weaken its own tests/scorers to pass?" check; the marathon driver **sample-audits** a deterministic fraction of PASSes (every 3rd `done` this invocation, plus always the first) with a fresh adversarial re-review, and gates terminal `done` on a **final cross-feature re-verification** (`--record-final-review`) over the whole accumulated diff since `autonomy.start_sha`.
- **CI**: `.github/workflows/validate.yml` now sets up Python 3.9 (the documented marathon-scripts floor) and runs both new `--selftest` suites (`compound-v-epic-state.py`, `compound-v-epic-arbiter.py`) as a required job — a red selftest now fails CI.

### The honest v2.10 boundary — no auto-resurrection

Marathon is opt-in; the default epic still checkpoints. "Survives a fall" means two things, both true today and neither overclaimed: **in-session**, the loop continues past a soft per-feature error to the next runnable feature automatically, within the one live `/v:epic` invocation. **After a hard death** (quota, closed terminal, crashed machine), a **human re-invokes `/v:epic <epic-id>`**, which resumes from the committed `epic-state.json`. There is **no automatic resurrection while you're away** in v2.10 — nothing wakes the epic back up on its own. That is the deferred **v2.11** auto-watcher (Execution Lease + Two-Tier Watcher + generation-fenced execution across the dispatcher/worker/merge-back/commit layer) — its own spec, its own review pass, because it needs correct distributed concurrency that the v2.10 single-process design deliberately avoids. No fabricated cost/token metrics anywhere in either stance.

### Provenance
Converged from four independent pre-implementation reviews plus three Codex Sol `xhigh` adversarial rounds on 2026-07-12 that drove the phased-scope decision. Built across four disjoint units (state spine → arbiter panel → driver/reviewer wiring → this docs/CI/release unit) and cross-model reviewed by **Codex gpt-5.6-sol**.

## [2.9.0] — 2026-07-12

### Added — Pre-Evaluation stage + proportionate fast-path

A fast, cheap **Pre-Evaluation** stage now runs *before* Trigger 0, scores each change request on two separate axes, and — only when a change is provably trivial **and** low-impact — OFFERS a proportionate fast-path. Everything else routes to the full pipeline. The request-level score never auto-routes; it only ever offers (Iron-Invariant #4). Fail-closed is the law everywhere: any ambiguity, missing data, tier disagreement, `unknown` axis, budget overrun, or parse failure → `FULL_PIPELINE` (or escalate, post-diff). Never fail open.

- **Two-axis truth-table scoring, no raw LLM magnitude** (`scripts/compound-v-preeval.py`, `skills/compound-v/phase-preeval.md`). Bands (difficulty ⊥ impact) are assembled by deterministic logic from tiered evidence — path patterns (T1), a calibrated fast-path history (T2), and a single `light`-tier classify (T3) invoked by the parent harness as a Task, never from Python. The derived 1-10 is a post-decision band-midpoint DISPLAY label, never the gate. Six hard Layer-A overrides (localization-failed, sensitive-path, shared-token/a11y/generated, semantic-vs-path disagreement, churn-hot, unknown-axis) each short-circuit to FULL with zero further cost; a fired override needs **zero** model calls.
- **Bounded localization** (`scripts/compound-v-localize.py`): a `low` verdict is impossible until a bounded, read-only `localize()` (rg → git grep → grep degrade, hard file-cap + timeout, every external CLI routed through the timeout supervisor with `stdin </dev/null`) has resolved real paths / tokens / fan-out. Writes a committed localization artifact the fast-path manifest binds against.
- **Content-pattern taxonomy** (`.claude/compound-v-impact-taxonomy.example.yaml`, `scripts/compound-v-taxonomy.py`): impact is decided on what a change semantically **is**, not only where its file lives (AC-8). Kinds include `shared_token` and `a11y` — a "cosmetic" color that is really a brand/contrast-compliance surface, or an `aria-label` that silently breaks WCAG, both escalate. Regex patterns are a documented safe subset (no nested quantifiers), deterministically validated and matched inside a killable subprocess (AC-16).
- **Cross-artifact-bound fast-path manifest, materialized by a dedicated owner** (`scripts/compound-v-fastpath-materialize.py`, AC-14): an accepted `FASTPATH_ELIGIBLE` record is materialized into a run whose single-implementer manifest (review modeled as a dispatcher **phase** outside `jobs`, not a job) passes `compound-v-validate-manifest.py --mode pre-dispatch` — the sole `write_allowed` literal equals `localization.resolved_paths[0]`, and `pre_eval_id` / decision / `taxonomy_digest` / localization content-digest are all validator-enforced to be equal across manifest + record + artifact (AC-13). A tampered or ineligible record is rejected fail-closed **before any write or commit**.
- **Normalized escalation-only churn** (`scripts/compound-v-churn.py`): generated/vendor paths and pure-format commits are excluded (single-sourced in the taxonomy `churn` block). A churn-hot path escalates; absence or an insufficient sample never *lowers*.
- **Sibling post-diff re-classifier** (`scripts/compound-v-postdiff-reclassify.py`, AC-5): a separate analyzer (never an extension of the hardened name-only scope gate) runs pre-merge against the pinned baseline and the same authoritative changed-path set. It answers one question — "does the materialized diff still deserve the fast-path, or must it ESCALATE?" — via sensitive-path touch, size accounting (tracked numstat unioned with separately-measured untracked bytes), a shared taxonomy content re-check over changed hunks, and a typed structural pass (a real stdlib-`ast` analyzer for Python; JS/TS/Go/Ruby fail closed unless provably trivial). Any uncertainty escalates.
- **Three new state-machine states, idempotent + crash-consistent escalation** (`skills/compound-v/state-machine.md`, AC-15): `PRE_EVAL_DONE` is a record-status field (no `state.json` exists at prediction time), while `FASTPATH_DISPATCHED` / `ESCALATION_REQUIRED` are real phases. Escalation mints a **new** run-id and never mutates the frozen manifest (AC-4); a two-phase protocol (commit patch+baseline evidence → deterministic child run-id → create+commit child → commit parent `escalated_to`) reconciles partial states on resume, discovering an existing child before minting one.
- **Three-event triage-outcomes + git-derived precision in `/v:status`** (`scripts/compound-v-triage-outcomes.py`, AC-3/AC-12): telemetry is strictly append-only — `predicted` → `bind` → `actual`, joined on the write-once `pre_eval_id`, no back-fill. Precision is computed from the fast-path **parent** outcome only, git-derived, and reports **`insufficient`** (never a fabricated number) on an empty or below-floor stream (AC-10). The escalation child contributes escalation evidence, never a healthy signal (cohort separation).
- **`/v:init` + `/v:onboard` wiring**: `/v:init` gains `pre_eval.*` config (fail-closed defaults, malformed → warn → default) and revocable remember-my-choice per taxonomy-category (AC-11 — a remembered choice skips the OFFER for that category only; it can never bypass the fail-closed overrides). `/v:onboard` drafts a first-cut taxonomy + churn-exclusion block from the repo's structure, kept/edited by a human at the gate (never auto-applied). Thin ADR capture is exposed via `/v:adr`.

### Tests
- **`tests/v2.9-e2e/test_fastpath_and_escalation.py`** — a runnable stdlib `unittest` e2e suite (12 cases, green under `LANG=C`) driving the REAL merged scripts end-to-end: AC-1 (shared-token "make button red" → FULL via override #3), AC-11 (a css-only-remembered request still escalates on a shared-token/a11y surface; the engine has no `remember` parameter), AC-3/7 (accepted fast-path → materialized manifest passes `--mode pre-dispatch`; clean diff does not escalate; a sensitive-path or shared-token diff does), and AC-10/12 (precision reports `insufficient`, never a number, on an empty/below-floor stream).

### Provenance
Built by **Compound V dogfooding itself** — the feature shipped as a 16-job manifest dispatched through the very orchestrator it extends. The plan was hardened to convergence across **5 Codex plan-review rounds** (each `reject → accept-all`, closing 3–4 crit + high findings per round, folded into a single Lifecycle & commit-ordering protocol as the release's one authority).

## [2.8.1] — 2026-07-11

### Added — session-aware codex workers

- **Structured session-id capture.** The headless codex worker now runs `codex exec` with `--json` and parses the first `{"type":"thread.started","thread_id":"<uuid>"}` event, carrying the UUID-validated `thread_id` inside the canonical `job_result.session_id` (empty when the event is absent) — replacing the brittle stderr banner scrape; the dispatcher persists `session_id` + `failure_class` into `state.json jobs[<id>]`. (`scripts/compound-v-run-codex-worker.sh`, `skills/backend-launcher/adapter-codex.md`)
- **`logs/<job-id>.jsonl` run-dir convention.** A new `--events-log <path>` worker arg tees the `--json` event stream to `docs/superpowers/execution/<run-id>/logs/<job-id>.jsonl`; the dispatcher records that same path in `state.json jobs[<id>].log`. Standalone worker use keeps an `$ART` default, so the arg is optional and degrade-safe. (`agents/parallel-dispatcher.md`, `skills/compound-v/state-machine.md`)
- **Liveness JSONL signal.** `classify_job()` now reads the events-log's newest line when present: an event newer than the staleness threshold is a WORKING signal, an older newest-event reinforces STALE. Malformed/partial JSONL never raises — it falls through to the prior git+FS+pid behavior. No `log` field ⇒ identical prior behavior. (`scripts/compound-v-liveness.py`)
- **`--ephemeral` discovery review.** `compound-v-codex-review.sh` adds `--ephemeral` to its single `codex exec` invocation — discovery rounds must not persist or resume (statelessness is the anti-anchoring point). Never added to the worker. (`scripts/compound-v-codex-review.sh`)

### Fixed

- **Resume/parallel-dispatcher contradiction reconciled.** `v-resume.md` and `parallel-dispatcher.md` now state a byte-identical resume-eligibility rule: a codex job may be resumed via `codex exec resume <captured-uuid>` IFF its `failure_class` is environmental (timeout | network) AND its worktree still exists; every other case recreates the worktree fresh at HEAD. Kills the archaeology-flagged contradiction (v-resume.md:29 vs parallel-dispatcher.md:183). (`commands/v-resume.md`, `agents/parallel-dispatcher.md`)
- **Dead `job["log"]` now populated.** The state-machine's `log` field, previously documented but never written, is now recorded at dispatch for codex jobs and consumed by liveness.
- **Stderr UUID-scrape replaced.** The fragile stderr session-id extraction is deleted in favor of the structured `--json` `thread.started` capture above.

### Probed

- **Thread-naming unsupported in `codex exec`** (live-probed 2026-07-11): `codex exec` exposes no flag to name or pin a thread id, so the worker captures the auto-generated UUID from the `thread.started` event rather than assigning one. `--json` and `--output-last-message` verified to coexist (result path unchanged); `--ephemeral` verified accepted by `codex exec`. All codex capability facts here are live-probed, per the library audit — not re-invented.

## [2.8.0] — 2026-07-11

### Security — two scope-gate exploits, both reproduced before fixing

- **Rename bypass (HIGH).** The gate's diff ran with git's default rename detection ON, so `git mv docs/important.md src/renamed.md` under `write_allowed: [src/**]` collapsed to a single record whose `--name-only` output was just the destination — the out-of-scope deletion of `docs/important.md` was invisible and the verdict was **pass** (reproduced). The diff argv now carries `--no-renames`: both sides of a rename surface as a delete + an add, and the out-of-scope source path BLOCKS. (`scripts/compound-v-scope-check.py`)
- **Symlink escape (MEDIUM).** The gate string-matched changed paths and never `lstat`-ed anything — a symlink inside the allowed area pointing outside the worktree glob-matched cleanly, and a write through it landed OUTSIDE the repo with verdict **pass** (reproduced). The verdict path now scans the WHOLE gate root (`os.walk` with `followlinks=False`, symlinks only — cheap) and reports every symlink whose `realpath` escapes the root as a violation `"<path> (symlink escapes the worktree)"` — unconditionally: even inside the allowed area, and even for a **pre-existing** link committed before the baseline with no new changes at all, because a write through either lands where git sees nothing and the link itself is the only reliable gate-time signal. Degrade-safe on unreadable entries. **Honesty note (in the module docstring too):** the gate DETECTS the channel; it cannot observe writes already made through it — kernel-level confinement (the codex backend's sandbox) remains the preventive layer.
- **Three new selftest cases** — rename-out-of-scope, job-created escaping symlink, pre-existing (committed-before-baseline) escaping symlink — each verified to FAIL against the unfixed logic via a temporary revert and PASS after the fix; the suite is green.

### Added
- **Trigger-0 hook backstop** (`hooks/brainstorm-trigger0-nudge.sh`, registered in `hooks/hooks.json`): when the Skill tool invokes `superpowers:brainstorming`, a one-line idempotent reminder to run the Trigger 0 gates is injected. A reminder, not enforcement — Trigger 0 stays description-driven; the hook closes the "agent simply forgets" gap documented in v2.7.0.
- **`xhigh` effort — codex-only.** codex-cli live-accepts `model_reasoning_effort=xhigh` (probed 2026-07-11 on 0.144.1); the effort vocabulary gains `xhigh` valid **iff** `backend: codex` — every other backend rejects with a clear error naming the rule. Enforced in lockstep at `compound-v-resolve-model.py`, `compound-v-validate-manifest.py`, both codex shell workers, and stated identically on every active effort-vocabulary surface.
- **Directions-late protocol (anti-anchoring, made explicit):** the brainstorm forms its own first-principles proposals BEFORE reading the recon doc's `## SUGGESTED DIRECTIONS`; consumption is observable via the recon-outcomes stream.
- **recon-outcomes stream** (`docs/superpowers/memory/recon-outcomes.jsonl`): an append-only event machine — a gate-stopped Trigger-0 evaluation emits exactly one terminal event (`plumbing_skip|kb_skip|off|declined|no_engine`); an engine run emits `fired` → `saved` (with `path`) → `consumed` as three separate appended events, never a mutated line. Never read by routing.
- **VERIFIED / UNVERIFIED split in recon docs:** the output contract is now genuinely five verbatim sections (`## QUESTIONS TO ASK`, `## VERIFIED FACTS / CONSTRAINTS`, `## UNVERIFIED LEADS`, `## SUGGESTED DIRECTIONS`, `## SOURCES`). VERIFIED = checked against a cited primary source (provisionally binding; 1B/1C revalidate); everything else is an UNVERIFIED LEAD that must become a question until validated.
- **Gate-2 freshness rule:** a strong KB hit now requires scope AND freshness — volatile material (libraries, APIs, regulations, availability, best practices) older than ~30 days degrades to partial: still evidence, no longer skip-authority.

### Fixed
- **Recon wiring finally reaches the executing 1B/1C:** the recon-read step existed only in the phase docs — `agents/domain-expert.md`, `agents/doc-validator.md`, and both prompt templates never mentioned it, so dispatched pre-flights never learned a recon doc existed. All four now carry the read step plus the exact-path handoff contract.
- **Epistemic contradiction in the gate-3 offer:** the "verbatim" copy promised deep-research even on machines without it, conflicting with the honesty rule one section down — the offer is now engine-aware and honest, and decline paths are reachable.
- **Fail-closed config, verbatim everywhere it's consumed:** missing file or key → documented defaults (`deep_research: "ask"`, `batch_elicitation: true`); malformed JSON, wrong type, or unknown value → warn once, then `deep_research=ask` and `batch_elicitation=false` for the session — an invalid value is never treated as `auto`.
- **Staleness sweep:** `GEMINI.md` was entirely pre-v2.7 ("three transitions", Gemini 2.5, missing command rows) — refreshed to the four-transition reality; surviving `codex-cli 0.130` pins → 0.144.1 and cursor worker provenance comments 2025.09.12 → 2026.06.26.

### Audit credit
Five audit lines drove this release: **F1** (live dogfood of Trigger 0/elicitation — procedures actually executed), **F2** (cross-repo consistency/staleness sweep), **F3** (scripts robustness — both scope-gate exploits reproduced on scratch fixtures before any fix), from three parallel Fable agents; plus **C1/C2** — two independent max-effort **Codex gpt-5.6-sol passes at `xhigh`** (the v2.7.0 guidance red-teamed as executable instructions, 28 findings; design red-team, 9 findings + 5 proposals). Cross-model by construction, convergent findings independently confirmed across lines. The pre-dispatch Codex plan review (verdict `reject`, 7 findings, all accepted) reshaped the plan itself — including the whole-root pre-existing-symlink scan shipped above.

### Post-build cross-model review (Codex gpt-5.6-sol @ `xhigh`, 5 rounds)
The build was reviewed to convergence. Round 1 (9 findings, all accepted): a `.git`-named escaping symlink bypassed the scan; the outcomes event machine had no legal failure transition; the exact-path handoff had no literal storage carrier; five active surfaces still described batching as companion-only; the dedicated "max-effort" review command still capped at `high`. Rounds 2–5 hardened the symlink scan alone through four more genuine edges — a nested **real** `.git` directory hiding a link, a `chmod 000` directory, and finally a **real false-PASS** where `os.path.islink` silently swallows `EACCES` on a `0400` (readable-but-not-searchable) directory (fixed by switching to `os.lstat`, which raises). Each fix carries a selftest; the gate self-test suite is green.

## [2.7.0] — 2026-07-10

### Added
- **Trigger 0 — pre-brainstorm recon** (`skills/compound-v/phase-0-recon.md`): when a brainstorm is about to begin on an unfamiliar topic, a gated, bounded research pass (bundled `deep-research` if present, ≤6 parallel WebSearch otherwise, skip-with-notice if neither) writes an anti-anchoring recon doc to `docs/superpowers/recon/` that the brainstorm — and later pre-flights 1B/1C — read first. Gate order: plumbing-skip → V-memory KB hit → `brainstorm.deep_research` config (`ask` default / `auto` / `off` hard kill-switch). Recon is evidence, never a routing input. Description-driven with zero hook backstop — weaker than Triggers 1–3, documented as such.
- **Batched elicitation** (`skills/compound-v/brainstorm-elicitation.md`): ≥3 *independent* questions (≤5 groups/screen, never a grid) may batch into ONE Visual Companion form screen — reusing upstream's companion server as-is, only if the user already accepted it this session. Independence is judged on answer interaction; when unsure → sequential. Deliberately overrides upstream's "text questions → terminal" rule for this narrow case, and says so.
- **`/v:init`**: `brainstorm.deep_research` + `brainstorm.batch_elicitation` policy keys (committed config) and a `deep_research` presence probe (machine-local capabilities cache, advisory only — fire-time listing check is the contract).
- **CI guard:** CHANGELOG top version must equal `plugin.json` version — closes the bug class where v2.6.4 shipped with both manifests still at 2.6.3 (the bump was written but never committed, and manifest-vs-manifest lockstep can't see it).

### Fixed
- Pre-flight phase docs 1B/1C now read `docs/superpowers/recon/` before opening new searches (deepen, don't repeat).
- `skills/compound-v/skill-escalation.md` reconciled with Trigger 0's earlier deep-research use (previously claimed deep-research fires only past 1B/1C).

### Cross-model review (Codex gpt-5.6-sol, 6 rounds, 10 accepted findings)
- `/v:init` stated `ask`/`auto` unconditionally — now explicitly gate 3 of 3 (plumbing-skip and KB-hit gates named, authority linked).
- **Epic mode silently bypassed Trigger 0** — per-feature brainstorms now run the recon gate sequence up front; later features converge via the KB-hit gate by design; the autonomous loop is described as the post-spec execution tail.
- Stale three-phase enumerations (SKILL.md quick-reference heading, plugin/marketplace descriptions) updated to the four-transition reality.
- The CHANGELOG guard was hardened round-by-round to CommonMark-correct fence handling: opener char+length tracked, closer requires same char + run ≥ opener + only trailing whitespace, a backtick opener with a backtick in its info string is not a fence, headings indented ≤3 spaces are matched with indent-independent version extraction. A 15-fixture adversarial suite was exercised locally; unbalanced fences still fail conservatively (loud, never a false pass).

## [2.6.4] — 2026-07-10

### Fixed — Compound V's own audit trail could be silently deleted, and `/v:status` could mislead

Two real incidents **noticed by Oscar Salcedo**, which a requested Codex cross-model hunt for
"similar/adjacent bugs" grew into a full sweep of the same bug class across the orchestrator:

- **Data loss: an uncommitted run directory vanishes on worktree cleanup.** `docs/superpowers/execution/<run-id>/**` is documented as "the committed run substrate" (`execution-manifest.md`) — but nothing in the pipeline actually committed it. `superpowers:finishing-a-development-branch`'s cleanup step runs `git worktree remove` on **both** its Merge and Discard paths, which **silently deletes any uncommitted files** in that worktree — taking Compound V's own audit trail with it. After a restart, `/v:status` would then honestly (but confusingly) report "no orchestrator runs" for a repo that demonstrably had one.
- **Misleading status message for non-Compound-V work.** When a repo had real prior work done via plain Superpowers `subagent-driven-development` (evidenced by `.superpowers/sdd/` task-brief/report/review artifacts) rather than Compound V's own manifest-driven dispatch, `/v:status`'s "no orchestrator runs" message read as "nothing happened here" — it had no visibility into that different, upstream-owned execution path. **Fixed with a cheap presence-check** (not a parse — that directory's format belongs to the base Superpowers plugin, not Compound V) that disambiguates the message without trying to understand or summarize its contents.

**The commit-discipline fix, after four rounds of Codex review, landed nine explicit commit points across the pipeline** (each closing a path where state could be written but never survive a worktree cleanup):
1. `/v:orchestrate` — commits `manifest.yaml` + the initial `state.json` right after materializing them.
2. `parallel-dispatcher` Step 7 — commits the run directory + memory/scorecard files in one shot **before** handing off to `finishing-a-development-branch` (the one point that can trigger the destructive cleanup). **Round 1 of review caught a bug in this very fix**: `state.json`'s phase was flipped to `MERGED` *after* the commit, so the committed record permanently lagged one phase behind reality — fixed by writing `MERGED` first, then committing everything together.
3–7. `commands/v-epic.md` — a **separate, epic-level `epic-state.json`** (the epic's *only* resume mechanism, one level up from any single feature's run directory) was never committed anywhere. Five commit points added: after init, at every checkpoint (the default `MAX_FEATURES=1` stopping point after *every* feature), at epic-complete, at epic-blocked, and — caught in round 3 — after crash-reconcile (the `--status failed` "abandon and stop" path is terminal and doesn't otherwise pass through the checkpoint's commit).
8. `commands/v-resume.md` — its own completion path didn't reference committing the recovered run substrate; a resume completing this way could re-lose the very state it just recovered.
9. `commands/v-collect.md` — standalone use (re-checking an already-dispatched run without re-dispatching) rewrote `results/*.json` + `state.json` with no commit step at all.

`state-machine.md` documents the general "written to disk ≠ durable" principle tying it all together. Docs-only; no code changed. **Codex cross-model verification, four rounds:** round 1 found the `MERGED`-ordering bug plus the v-epic/v-resume/v-collect gaps; round 2 (broad hunt) confirmed the fix and found nothing new to add; round 3 caught the crash-reconcile gap; round 4 (narrow re-check) confirmed all nine commit points present, correctly scoped, and non-contradictory.

## [2.6.3] — 2026-07-10

### Changed — Codex defaults bumped to the GPT-5.6 family (Sol/Terra/Luna)

- **`deep`→`gpt-5.6-sol`, `standard`→`gpt-5.6-terra`, `light`→`gpt-5.6-luna`** (was `gpt-5.5`/`gpt-5.5`/`gpt-5.3-codex-spark`) — a real per-tier differentiation where `deep`/`standard` previously shared the same model. Live-verified all three on `codex-cli 0.144.1` (`PROBE_OK`). **`gpt-5.6-sol` requires codex-cli >= 0.143.0** — confirmed broken with a clear 400 `"requires a newer version of Codex"` on 0.142.5, working on 0.144.1; an under-floor client fails loud (not silently — the failure-policy retries once then halts cleanly). `gpt-5.6-terra`/`gpt-5.6-luna` work on older clients too (verified back to 0.142.5). `compound-v-codex-review.sh`'s cross-model-review default follows the deep tier (`gpt-5.6-sol`, "Codex on their max").
- **Two independently-stale adapter pins refreshed during the audit:** `adapter-codex.md`'s verified-against pin (`0.130.0` → `0.144.1`); `adapter-cursor.md`'s verified-against pin (`2025.09.12` → `2026.06.26`) **and** a now-**false** claim — "cursor-agent has no models list command" — corrected: it does now (`cursor-agent models`, a live 187-entry catalog verified). **Grok is not present in that live catalog** for this account (press coverage says available, likely region/plan-gated — not documented since unconfirmed hands-on). No auto-discovery was added for Cursor's catalog (would be over-engineering — it spans unrelated vendor families with no shared naming convention, unlike Antigravity's single-family Gemini catalog `/v:models` already ranks); curated + user-overridable stays the flow, now pointing at the real command for manual discovery.
- Every doc stating the codex model map as **current fact** updated for consistency (`v-init.md` seed, `v-models.md` roster/table/example, `routing-policy.md` map/resolve-example, `execution-manifest.md` tier table/config example). Illustrative "(e.g. `gpt-5.5`)" mentions explaining the resolution *mechanism* (never hardcode a model — the resolver handles it) and the dated `routing-lessons.md` historical entry were deliberately left untouched. **Codex cross-model verification caught one real miss** — `compound-v-resolve-model.py`'s own source comment still said "cursor-agent has no `models` list command" (I'd audited the `.md` docs for this false claim but missed the `.py` comment) — fixed; a second pass confirmed every codex tier mapping, the review-script default, and every version pin consistent, with no remaining stale `gpt-5.5`/`gpt-5.3-codex-spark` current-default claims.

## [2.6.2] — 2026-07-06

### Fixed — `.claude/compound-v.json` no longer commits machine-local capability

- **Closed a real downstream-repo review comment:** a teammate flagged the committed `.claude/compound-v.json` as looking like it should be gitignored. The diagnosis: the file mixed genuine team **policy** (`stance`, `models`, `memory`, `epic`, `review`, `workflows_accelerator` — correct to commit) with a **machine-local capability snapshot** (`backends`, `checked_at` — "which CLI/MCP tools were detected on the machine that last ran `/v:init`") — a fact about one developer's machine, wrong the moment a teammate with a different local setup opens the file.
- **The fix removes `backends`/`checked_at` from the committed file — no new file needed.** A correct, already-uncommitted home for exactly this data already existed: `~/.claude/compound-v-capabilities.json` (`/v:init` Step 4b, user-home-scoped, already documented as "reused across repos"). `backends` was pure redundancy with it.
- **Audited before touching anything:** `compound-v-resolve-model.py`'s `load_config_models()` reads only the `models` key; a full-repo grep found **zero** programmatic readers of `backends`/`checked_at` — actual backend availability is already re-probed live at dispatch time (the env-aware codex→claude fallback). So this is a hygiene/trust fix, not a routing-behavior change — nothing about dispatch logic changed. **Backward-compatible**: an existing committed file with the old fields is simply ignored, no migration needed.
- `commands/v-init.md` Step 4a and `commands/v-models.md` Step 3 updated (write path + example JSON + an explicit "why" note at the canonical source). **Codex cross-model verification: ACCURATE** — independently confirmed `load_config_models()` reads only `models`, zero remaining `backends` references anywhere in the repo, the sole remaining `checked_at` is correctly inside the Step 4b capability-cache shape, and the Step 4b cache fully covers the old capability role.

## [2.6.1] — 2026-07-06

### Fixed — worktree git-base fixes are the caller's job, never the worker's

- **Closed a real incident from a downstream repo:** a parallel-dispatch batch assigned a job to Codex, but the job's worktree needed its git base fixed — Codex's sandbox is confined to `$WT`, while the worktree's actual git metadata lives *outside* it, in `<repo>/.git/worktrees/<job-id>/`, and `approval_policy: never` means it can't ask to escalate. A **sandbox limitation, not a code one**. The orchestrator worked around it by dropping worktree isolation for Codex — which is **not** a fix: it removes the only file-scope enforcement Codex has (`codex ⇒ worktree` is a hard invariant in `compound-v-validate-manifest.py` precisely because Codex can only be confined to a *directory*, never a file allow-list), and risks interleaved writes if other jobs are running concurrently in the same tree.
- **The correct fix, now explicit:** every dispatch or retry of an external worker (Codex/Antigravity/Cursor) goes through the **full worker-script lifecycle**, which already recreates the worktree fresh at current HEAD every time — never patch an existing worktree's git state, and never delegate that patch to the worker itself. A job that needs another job's already-landed output must model that as `depends_on` in the manifest, not discover it mid-run.
- New `SKILL.md` §**Worktree git-base fixes** (the shared, mechanism-level explanation), a cross-reference in `adapter-codex.md`, and explicit language in `parallel-dispatcher.md`'s isolation step and its retry line (which previously just said "re-dispatch the same backend" without specifying the worktree is recreated fresh — the exact ambiguity that let the workaround slip through). Docs-only; no code changed.
- **Codex cross-model verification, two rounds, caught real gaps in the fix itself.** Round 1 confirmed the core sandbox mechanism but found the `depends_on` guidance **overclaimed**: merge-back only *stages* a job's changes (`git apply --index`) — it never commits, so `HEAD` doesn't move, and a dependent job's "fresh worktree at `HEAD`" would **not** contain a prerequisite's merged-but-uncommitted work. Fixed: `parallel-dispatcher.md` Step 1 now requires the caller to **verify Task 0's result is actually committed** (for both `direct` and `worktree` isolation) before Step 2 begins — the missing link between `depends_on` and a correct fresh-worktree baseline. Round 1 also flagged an overclaim that Codex "cannot touch outside metadata even with `--dangerously`-style flags" — narrowed to the documented pinned invocation only. **Round 2 confirmed the round-1 fixes, then caught one more:** the wording assumed a `direct`-isolation implementer always commits its own work — `adapter-claude.md` establishes only that it writes against the main tree, not that it commits — fixed to an explicit caller-side verify-and-commit step for both isolation modes. Two full review rounds, three real corrections, all fixed.

## [2.6.0] — 2026-07-06

### Added — `pr-review` skill + `/v:pr-review` command

- **`pr-review` skill** — a two-axis, stack-agnostic **deep code-review** skill for a pull/merge request or a local diff. It first builds shared understanding of the change's intent, then hunts bugs and edge cases along **two deliberately separate axes** run as context-isolated sub-agents so neither pollutes the other: **Standards** (does the code follow *this repo's* documented conventions, discovered in a Phase-0 sweep?) ⊥ **Spec** (does it faithfully implement the originating spec/issue/PRD?). Findings are reported **side by side, never merged across axes**; genuine author-intent unknowns are promoted to Open Questions; every finding carries a **verdict + confidence**. **Review-only — it never edits, commits, pushes, or merges code.** Ships `SKILL.md` + four `references/` (exploration checklist, review domains, findings format, comment-posting).
- **`/v:pr-review` command** — a thin entry point in the `/v:*` family that runs the skill. Argument = PR/MR URL or number; empty = current branch vs. its base. Auto-detects the host: GitHub (`gh`), GitLab (`glab`), or a hostless local diff.
- **Self-contained** — no new runtime deps, hooks, or scripts; frontmatter within the linter's limits and all intra-plugin `.md` cross-refs resolve.

## [2.5.5] — 2026-07-05

### Performance
- **Dense search: repeated queries skip the model load.** Every dense search paid one isolated-venv subprocess = one ONNX model load per query (seconds). A new `query_cache` SQLite table (`sha256(query) + model → vector`, `IF NOT EXISTS` so no migration, bounded to the 500 most-recent rows) lets a repeated query — the common case for `/v:remember` and the recall→action bridge's templated queries — return in milliseconds. A model change misses by key; **identity drift (embedder revision change) clears the cache** alongside the corpus re-embed, so a stale-revision vector is never served; any cache error falls back to embedding (the cache is an optimization, never a failure mode). Selftest proves hit / miss / model-miss / failed-embed-not-cached with a counting fake embedder. Profiled first: the FTS5 lane (rebuild 0.7 s, search 0.28 s, hooks ≤0.25 s) was left untouched — already fast. **Codex cross-model verification caught the stale-vector hazard** — the `(query, model)` key alone can't see an embedder **revision** change (the same drift the corpus re-embed handles), independently confirming the author's own finding — fixed via `_invalidate_query_cache` on the drift branch, plus the extra coverage Codex asked for (different-query miss, cache bound, drift invalidation): 7 cache checks total, all green.

## [2.5.4] — 2026-07-05

### Performance
- **V-memory DENSE refresh now loads the embedding model *once*, not per file.** The refresh embedded per file — `reindex_file` invoked the isolated-venv embedder subprocess once per file, and each subprocess rebuilt the ONNX `InferenceSession`, so `N` files meant `N` model loads (the reason the first full pass over `docs/superpowers/**` was slow). `cmd_refresh` now uses a new `reindex_batch` that chunks all to-index files, flattens their chunks into **one** embedder call, and slices the vectors back per file — **one model load per refresh**. The FTS5-only (embeddings-off) path is unchanged and it stays **degrade-safe** (a failed batch persists `NULL` embeddings → FTS5-only; the CORE lexical lane is never affected). Selftest injects a **call-counting fake embedder** proving the single call + correct per-file vector slicing + degrade — no network/model needed. **Codex cross-model verification: ACCURATE** on all five claims with `file:line` evidence (single call, offset slicing with no off-by-one, empty-corpus skips the model load, degrade-safe `NULL` fallback, atomic persistence preserved).

## [2.5.3] — 2026-07-05

### Added — `npx autoskills` recommender for `/v:onboard`

- **Third-party skill discovery.** `/v:onboard` now recommends [`npx autoskills`](https://www.autoskills.sh/) when a project manifest is detected — a new `recommend-autoskills` subcommand in `scripts/compound-v-onboard.py` flags applicability (`package.json`, `pyproject.toml`, `requirements.txt`, `Gemfile`, `go.mod`, `Cargo.toml`, `composer.json`, `pom.xml`, `build.gradle`, or a top-level `*.tf`), with the marker file as **evidence**; an unknown repo yields `applicable: false` (no false recommendation).
- **Present-only, gated `--dry-run`, never auto-installs.** In DIAGNOSE, onboarding surfaces the recommendation and — **behind a human confirm** — runs the **preview** `npx autoskills --dry-run` through the process-group timeout supervisor with `stdin </dev/null` (the v2.5.0 external-launch invariant), to show *which* skills it would install. The real install stays the user's own action (autoskills has its own confirm + SHA-256 verification).
- **Auto-trigger-degradation caution.** Because mass-installing overlapping skills degrades auto-triggering across the whole skill set (the onboarding **Skills stance**), the recommendation always carries a loud caution to review the dry-run and prefer a focused subset.
- **Built with TDD, dogfooded, cross-model Codex-verified.** 5 selftest checks (manifest → applicable + evidence + `--dry-run` command; empty → not applicable; `pyproject.toml` → applicable; a top-level `main.tf` → applicable with the filename as evidence; a *directory* named `*.tf` → not applicable). Dogfood on superpowers-v itself (no standard manifest) → `applicable: false` — the negative path. **Codex cross-model verification** (the model that writes ≠ the model that checks) caught **two** real bugs in the Terraform branch — the evidence was the literal `"*.tf"` instead of the actual filename, and a *directory* named `foo.tf` was a false positive — **both accepted and fixed**, each with added selftest coverage.

## [2.5.2] — 2026-07-03

### Added
- **Compound V Academy** — a gamified 3-episode tutorial (**Developer · Product Owner · Universal Creator**) is now linked prominently from the README: **<https://amiainative.dev/compound-v>**. The fastest way to learn the whole pipeline (onboarding → the three scouts → dispatch → the review gates), with the squad as guides.

### Fixed
- **Scope gate: bracketed path segments are literal.** `[locale]` / `[uid]` / `[slug]` in a `write_allowed` glob were parsed as fnmatch **character classes** (`[locale]` = "one of `l,o,c,a,e`"), which **falsely BLOCKED** any Next.js App Router write scope (e.g. `app/[locale]/…/[uid]/page.tsx`) and raised a regex `FutureWarning`. Bracketed dynamic segments — the dominant real-world case — now match **literally**; the selftest covers the App Router case positive + negative. (`scripts/compound-v-scope-check.py`)
- **`/v:review-plan` schema resolves from the plugin, not the reviewed repo.** The cross-model review script defaulted its JSON-schema path to `$REPO/schemas/…` (the **reviewed** repo), so `/v:review-plan` died with "schema not found" in **every project except this one**. It now resolves the default schema next to the script (its install dir); the `--schema` override is unchanged. (`scripts/compound-v-codex-review.sh` + new regression test)

## [2.5.1] — 2026-07-01

### Added — MCP / external-tool recommender for `/v:onboard`

- **`/v:onboard` now recommends the right external tools for your stack** — a new `recommend-mcp` subcommand in `scripts/compound-v-onboard.py` maps repo signals → tools from a **curated, currency-verified table**, with a deliberate **CLI-over-MCP bias**: a `github.com` remote yields the **`gh` CLI**, never a GitHub MCP server (avoids the broad-PAT toxic flow). Rows: Supabase MCP (`--read-only --project-ref`), Postgres MCP (`--access-mode=restricted`), Playwright MCP (pinned `>=0.0.40`, CVE-2025-9611), Context7, Sentry — every MCP row ships **least-privilege flags pre-filled**.
- **`.mcp.json` via diff + confirmation, never auto-apply.** `mcp_json_config()` builds the config from the confirmed MCP recommendations, **merged additively** — it never clobbers an existing same-named server, and CLI recommendations (`gh`) are surfaced as setup instructions, not `.mcp.json` entries. The write is a gated WRITE-step artifact behind the human approval gate.
- **Lethal-trifecta warn-only.** Any private-data + untrusted-content + external-write server (Supabase / Postgres) emits a **named warning with a specific remedy** (read-only + dev/branch-scoped + single-repo session). Read-only defaults defuse most at the source; no hard refusal — the user decides.
- **Deterministic + evidence-cited + honest.** The table is a static curated map (no model guesswork on tool names/flags); each recommendation cites its triggering signal; an **unknown stack yields an empty set** (no invented tools). Currency (packages / flags / CVE pin) was WebSearch-verified 2026-07-01.
- **Built with TDD, dogfooded, cross-model Codex-verified.** 21 selftest checks (github→gh CLI, Supabase read-only, Postgres restricted, fast-moving→Context7, Playwright, citation-grade evidence, trifecta warning, additive-merge, no-clobber, empty-on-unknown, Postgres DSN, existing-server warning). Dogfood on superpowers-v itself: exactly one recommendation (`github → gh CLI`), **no false MCPs**, empty `mcpServers` (the negative path). **Codex cross-model verification** (the model that writes ≠ the model that checks) caught **three** real spec/impl gaps the Opus author missed — a Postgres **DSN** (no `pg` dep) went undetected, evidence wasn't **`file:line`** citation-grade, and trifecta warnings skipped **existing** `.mcp.json` servers — **all three accepted and fixed**, each with added selftest coverage.
- **Onboarding scope:** `.mcp.json` / MCP recommender moved from fast-follow to **in-scope**; `.claude/rules/*.md` (→ future) and bulk skill generation (deliberately avoided) stay out.

## [2.5.0] — 2026-07-01

### Added — hang detector (liveness probe + dispatcher sweep + enforced external launch)

- **Liveness probe — `scripts/compound-v-liveness.py`.** Classifies each `running` job in a run's `state.json` from **git + filesystem only** (never model-self-report — same ethos as the scope gate): `LIKELY-DONE` (the worktree has a commit past its recorded `baseline` — the work landed and only the completion notification is stuck), `STALE` (no working-tree progress past the threshold — a suspected hang), `WORKING`, `DEAD` (a recorded pid died with no progress), and `UNKNOWN` (degrade-safe — a missing/unreadable signal never crashes the probe). `.git` is excluded from the mtime walk so a commit doesn't mask staleness. Stdlib-only; `--selftest` (12 checks) covers every class with **real** git/fs/pid fixtures; exit `3` when any job is STALE/DEAD.
- **`/v:status` gains a `Liveness` column** — every running job shows its class + a hint (`LIKELY-DONE → /v:resume / auto-collected`, `STALE → suspected hang`). Degrade-safe: a probe error shows `—` and never breaks the table.
- **Dispatcher liveness sweep (`parallel-dispatcher` Step 2d).** Between batches — and while awaiting a background job whose completion notification never arrived — the dispatcher runs the probe and acts: **`LIKELY-DONE` → collect now** (scope-gate + merge + `done`), ending the "nudge the dispatcher by hand" failure mode a parked subagent caused; a `STALE`/`DEAD` **external** worker → the existing `timeout` failure-policy (retry cap, then halt — no new mechanism); a `STALE` **Claude subagent** → surfaced (the harness owns the kill), reclassifying `LIKELY-DONE` once its commit is observed. No new phase, no daemon; documented in `state-machine.md` + `failure-policy.md`.
- **Fixed — the one uncapped external-launch path.** `scripts/compound-v-codex-review.sh` (the cross-model plan review) capped its `codex exec` via a `timeout`/`gtimeout` binary **only when one was installed** (no binary ⇒ **no cap**) and signalled only the direct child. It now runs under the shared process-group supervisor `compound-v-run-with-timeout.py` (guaranteed hard cap + whole-group kill), matching the three worker scripts. This closes the gap behind a real **44-minute hang** this cycle (an ad-hoc codex review that had no cap and blocked on stdin).
- **Enforced-launch invariant (`backend-launcher/SKILL.md`).** Every external-CLI invocation — dispatched worker OR orchestrator-level (cross-model review, ad-hoc verification) — MUST run through `compound-v-run-with-timeout.py` with `stdin </dev/null`; **a bare `codex`/`cursor`/`agy` call is a bug.** The probe *detects* a hang after the fact; this rule *prevents* it.
- **Anti-over-engineering.** Archaeology confirmed the three worker scripts already enforce supervisor + `</dev/null` and run synchronously under the hard cap, so the probe deliberately does **not** police external workers or add `pid` bookkeeping — its unique, non-redundant value is the Claude-subagent `LIKELY-DONE`/`STALE` case that nothing caught before. ~200-line stdlib probe, one purpose; no daemon, no new deps.
- **Built directly with TDD, dogfooded live.** The probe was proven end-to-end on a fabricated run with a real git worktree: a parked job (worktree committed past baseline) classified `LIKELY-DONE`, a 40-minute-idle worktree classified `STALE`, a fresh one `WORKING`, a `done` job skipped — exit 3 as designed. Full regression (6 script selftests + banner + frontmatter lint + CI version-lockstep) green.
- **Cross-model Codex verification earned its keep.** A GPT reviewer (the model that writes ≠ the model that checks) adversarially reviewed the probe and caught **four real issues** the Opus author missed: `LIKELY-DONE` using `HEAD != baseline` instead of git **ancestry** (a reset/checkout would read as done), `_pid_alive` misreading **EPERM** (an alive-but-unsignalable process) as dead, `_newest_mtime` **following symlinks** (`os.stat` → `os.lstat`), and a stale bare-`timeout … codex exec` example in `SKILL.md` contradicting the new launch invariant. **All four accepted and fixed**, each with added selftest coverage (15 checks, green).

## [2.4.0] — 2026-07-01

### Added — stance-aware models map (cost-aware routes Claude `standard` → Sonnet 5)

- **Tier→model resolution is now stance-aware.** The `cost-aware` stance routes Claude `standard`-tier implementers (`core_slice`, `tests_new`) to **Sonnet 5** (via the native `sonnet` alias — no concrete ID pinned); `balanced` (the default) is unchanged (`standard → opus`). Exactly one built-in cell changed: `cost-aware.claude.standard` `opus → sonnet`. `cost-aware.claude.deep` stays `opus`; the `codex`/`antigravity`/`cursor` maps are identical across stances.
- **Resolver (`scripts/compound-v-resolve-model.py`).** `DEFAULT_MODELS` → `DEFAULT_MODELS_BY_STANCE` keyed by stance (with a derived `DEFAULT_MODELS = DEFAULT_MODELS_BY_STANCE["balanced"]` alias so existing references are untouched). New `--stance` flag (default `balanced`); `stance` is a **trailing** kwarg on `resolve()` so every existing caller is unbroken. `VALID_STANCES` is re-declared locally (mirrors `compound-v-validate-manifest.py`, no shared import).
- **Config backward-compat.** `.claude/compound-v.json` `models` accepts BOTH the legacy flat shape `{backend:{tier:model}}` (applied to every stance) and a new per-stance shape `{stance:{backend:{tier:model}}}`, discriminated by whether **every** top-level key is a stance name. Existing seeded configs keep working unchanged.
- **Every Claude-model-resolving call site threads `--stance <routing_stance>`** — `parallel-dispatcher` (the batch resolve **and** Task 0), `phase-3-parallel-opus-dispatch`, `adapter-claude`, `/v:status` (its per-job model column — without the flag it would display `opus` for a job that actually dispatches as `sonnet` under `cost-aware`), and the `/v:models` verification loop. No flag ⇒ `balanced` (current behavior).
- **partition-reviewer stance-gate.** Under `cost-aware`, a `standard`-tier Claude Sonnet implementer is the **routing-policy default** and is exempt from the 8-box `SONNET_UNJUSTIFIED` junior-task check; `balanced`/`conservative`/`claude-only` apply the check as before. **Invariants hold in every stance:** reviewers ⇒ deep ⇒ opus, sensitive (auth/payments/PII/a11y) ⇒ deep ⇒ opus, the light-tier Sonnet check, and **never Haiku**. The deterministic validator is unchanged — it never adjudicated implementer Sonnet eligibility.
- **Fixed — version lockstep (`marketplace.json`).** `.claude-plugin/marketplace.json` had lagged at `2.1.1` while `plugin.json` advanced to `2.3.1` (the 2.3.0 and 2.3.1 releases bumped only `plugin.json`), which the CI lockstep check in `.github/workflows/validate.yml` flags as a mismatch. Both are now bumped in lockstep to **`2.4.0`**, greening CI.
- **Built by Compound V, dogfooded, cross-model verified.** Implemented through the plugin's own `/v:dispatch` pipeline (5 jobs — resolver serial spine + 3 parallel worktrees + integration review; git-derived scope-gate PASS on every job; 3-pass Review Gate **APPROVED**, 5/5 acceptance criteria). The new behavior was dogfooded live: a `cost-aware` manifest with a `standard`-tier Claude job resolved to Sonnet and passed partition-review with **no** `SONNET_UNJUSTIFIED` flag, while the deep reviewer stayed Opus. **Codex cross-model verification** (the model that writes ≠ the model that checks) returned **ACCURATE** on all seven claims with `file:line` evidence (incl. `cost-aware.claude.deep` stays opus, the config-shape discrimination, and fail-closed resolution).

## [2.3.1] — 2026-06-30

### Added — model visibility in the dispatch tree

- **The dispatch tree and `/v:status` now show the resolved model per job.** `parallel-dispatcher` announces each batch as a tree annotated with `backend · model (tier/effort)` (resolved via `scripts/compound-v-resolve-model.py` **before** dispatch), and `/v:status` gains a `Backend · Model` column — so it is always visible *which model each job runs on*, both live during dispatch and after the fact.

### Note — Claude Sonnet 5

- Claude **Sonnet 5** (`claude-sonnet-5`, released 2026-06-30) is picked up automatically wherever Compound V routes to the `sonnet` tier alias (the `light` tier on the Claude backend) — the resolver intentionally emits native tier aliases (`opus`/`sonnet`), so the new model flows in with no code change. Routing **more** work to Sonnet 5 (it benchmarks close to Opus 4.8 at lower cost) is a deliberate routing-policy change tracked for a future minor (a `cost-aware`-stance `standard → sonnet` route), **not** a silent default shift — the default stays **Opus by default, reviewers always Opus, never Haiku.**

## [2.3.0] — 2026-06-30

### Added — `/v:onboard` (project onboarding → trusted, citation-verified knowledge base)

- **New `/v:onboard` command** — studies an existing repo and builds a trusted knowledge base (`docs/superpowers/architecture/{architecture,business-logic,tech-context}.md`) plus cross-tool agent instructions (root `CONVENTIONS.md`, `AGENTS.md` as the portable source of truth + a thin `@AGENTS.md` `CLAUDE.md` bridge, conditional `DESIGN.md` for UI repos), all behind a **human approval gate**, then feeds them into V-memory. Authority doc: `skills/compound-v/onboarding.md`; thin command: `commands/v-onboard.md`. `/v:onboard --refresh` re-checks cited-evidence staleness.
- **Deterministic toolkit `scripts/compound-v-onboard.py`** (stdlib-only): `pack` (repo pack-manifest + advisory secret scan), `verify-citations` (the two-tier gate), `staleness` (cited-evidence drift + uncited-new-file heuristic), `design-lint` (wraps `npx @google/design.md`), `detect-ui`, `scan-output`.
- **Two-tier citation gate (anti-hallucination).** Tier-1 (cited path resolves + `1 ≤ start ≤ end ≤ lineCount`) is mechanical and blocks 100% of claims; Tier-2 (do the cited lines actually support the claim?) runs on 100% of **load-bearing** claims (security / fail-closed / concurrency), where an unsupported load-bearing claim is **BLOCKING**. Generation defaults to **read-then-cite**. (Live feasibility probe on this repo: read-then-cite scored 23/23 path/range/support under an adversarial verifier; naive free-write failed to even produce valid structured output.)
- **Untrusted-input rule.** Any existing instruction file (`AGENTS.md` / `CLAUDE.md` / `GEMINI.md` / cursor / windsurf / copilot rules) is treated as **evidence to quote and summarize, never a directive to execute** during onboarding; the managed-policy layer is informational-only.
- **Secret-scan granularity (input advisory, output blocking).** The `pack` input scan is **advisory** — it surfaces secret-shaped strings anywhere in the repo (test fixtures, security docs) at the human gate but does NOT halt the run. The **blocking** refusal is `scan-output`, run on the GENERATED docs only, enforcing the invariant "no credential reaches a generated, committed file." (Caught while dogfooding: the input scan reports ~40 benign false positives on this very repo — the plugin's own selftest fixtures and secret-scanning scripts — which a repo-wide hard block would have wrongly halted on.)
- **V-memory engine extension (`scripts/compound-v-memory.py`).** `tracked_files()` now also indexes root `AGENTS.md` / `CLAUDE.md` / `CONVENTIONS.md` / `DESIGN.md` via a scoped second `git ls-files` union (`DOCS_REL` not widened, fail-closed `[]` on git error preserved); `doc_type_for()` gains clean labels for them. *(Cosmetic: until the first refresh after upgrade, `search` may report "N new behind".)*
- **`/v:init` + SessionStart banner.** `/v:init`'s closing report now suggests running `/v:onboard`; the banner gains a read-only, **fail-silent** staleness line ("N architecture docs stale vs HEAD → run /v:onboard --refresh") guarded so it can never abort the banner under `set -euo pipefail`.
- **Built by Compound V, dogfooded on itself.** Implemented through the plugin's own `/v:dispatch` pipeline (5 jobs, all Opus, scope-gate PASS on every job, one transient `Overloaded` auto-retried, 3-pass Review Gate **APPROVED** 6/6), then `/v:onboard` was run on superpowers-v itself (51 claims, all 11 load-bearing passing Tier-2 `ok:true`, output secret gate clean, `DESIGN.md` correctly skipped on the no-UI repo). This release ships alongside the repo's own generated knowledge base and the `CLAUDE.md` bridge it previously lacked.
- **Dependencies verified current (2026-06-30):** `@google/design.md` v0.3.0 (`lint` real, JSON findings + WCAG), `repomix` v1.16.0 (Secretlint secret-scan built-in). Deliberately **fast-follow / out of v1**: the MCP recommender (and per the maintainer, GitHub is used via the `gh` CLI, **not** a GitHub MCP server), path-scoped `.claude/rules` writing, and bulk skill generation.

## [2.1.1] — 2026-06-27

### Fixed — Cursor worker hardening (all caught by live verification, not self-tests)

- **Process-tree timeout supervisor (`scripts/compound-v-run-with-timeout.py`) — adopted by ALL three external workers (cursor, codex, antigravity).** These backends previously capped via an external `timeout`/`gtimeout` (or a bash watchdog), which signals only the **direct child** — a tool/shell child the agent spawned could outlive the cap and write **after** the scope gate (the exact leak the gate exists to stop). The new supervisor starts the command in a new session (`setsid`) and on expiry `killpg`s the **whole process group** (SIGTERM → grace → **always** SIGKILL — a descendant that ignores SIGTERM is still reaped) → `status: timeout` (124). It holds no copy of the command's output fds, so a hung child can't hang the dispatcher's `$(…)` capture. Proven by `--selftest` (a descendant — incl. one that **traps SIGTERM** — that tries to write after the cap is reaped first; the write never lands) and **live success + `--timeout-sec 1 ⇒ status:timeout` through all three workers**. `--timeout-sec` must be `> 0`; `--grace` `>= 0`. (Limitation: a descendant that itself `setsid`s into a new session escapes — true containment needs cgroups/job-objects; backend tool children don't daemonize.)
- **Fixed a dispatcher-hang in the watchdog.** The watchdog subshell inherited the worker's stdout, so its `sleep` held the dispatcher's `$(...)` capture pipe open — every Cursor dispatch hung for the full timeout *after* the job finished. The watchdog's fds are now redirected to `/dev/null` and its `sleep` child is reaped. Verified: worker E2E back to ~29 s (was hanging ~600 s).
- **Cursor model default is now `auto`.** A Cursor **Free** plan can only use Auto — passing a named model (`sonnet-4` / `gpt-5` / …) errors with *"Named models unavailable."* `resolve-model` now maps every Cursor tier to `auto` (works free **and** paid); named per-tier ids are a paid-plan opt-in via `/v:models` / config. `/v:init` Step 1e detects `timeout`/`gtimeout` and warns when the Codex worker would have no hard cap.
- **New regression coverage:** a full-pipeline **seam** test (`validate-manifest → cursor worker → merge-back git-apply`) — 8/8 live, verifying the merge-back path the isolated worker test never exercised.

## [2.1.0] — 2026-06-27

### Added — Cursor CLI backend (4th dispatch backend)

- **`cursor-agent` as a headless dispatch backend** — `scripts/compound-v-run-cursor-worker.sh`, a Bash-spawned worker in its own git worktree that mirrors the Antigravity adapter (worktree isolation + git-derived scope gate → canonical `job_result`). **Verified live** (cursor-agent 2025.09.12): the success path (write within `write_allowed`) and the **BLOCKED** path (write outside scope → `violations`) both pass.
- **Invocation** (verified): `cd "$WT" && cursor-agent -p -f --output-format json [--model M] "<prompt>" </dev/null`. `-f` is **required** — a headless run refuses an untrusted worktree without it. Output is one JSON object: `.result` → `summary`, `.session_id` (a real UUID) → resumable via `cursor-agent --resume`. Token `.usage` is ignored (anti-ruflo).
- **Lower-trust / opt-in — same tier as Antigravity.** No kernel write-confinement (`-f` grants arbitrary write+shell); the git-diff gate is detection, not prevention. **Prefer Codex (kernel-sandboxed) for untrusted / high-stakes work**; `backend: cursor` ⇒ `isolation: worktree`.
- **Plumbing:** `classify-failure.py --backend cursor` (OpenAI/Anthropic-style needles + provisional cursor-auth); `resolve-model.py` cursor map (`sonnet-4-thinking` / `sonnet-4` / `gpt-5`, user-overridable via `/v:models`); `adapter-cursor.md` runbook; `/v:init` detects `cursor-agent` + auth and adds it to `backends`. Available only when installed AND authenticated (env-aware routing).

## [2.0.0] — 2026-06-27

### Added — V-memory (local-first recall over docs/superpowers prose)

- **V-memory — a local-first RECALL layer over the `docs/superpowers/**` prose** (a new subsystem, hence the major bump). It **extends** the existing two-half memory (machine-generated `task-outcomes.jsonl`/scorecard + human-curated `routing-lessons.md`) and **never rewrites them**; recall is **EVIDENCE for planning + review, NOT a routing input** — routing stays the deterministic v1.1 order (`routing-lessons.md` → stance table → conservative scorecard → fallback → invariants). Engine: `scripts/compound-v-memory.py`. Authority doc: `skills/compound-v/memory.md`.
- **Two lanes — CORE always on, DENSE opt-in.** **CORE** is SQLite **FTS5** BM25 over the git-tracked prose (pure stdlib, the default, always on). **DENSE** is opt-in embeddings (**multilingual-e5-small**) used in a **rank-union** with FTS5, **scale-gated**, and **degrade-safe** — when the embeddings are absent or broken the engine silently falls back to FTS5-only. The DENSE venv lives **OUTSIDE the repo** (`~/.cache/compound-v/memory/<repo-id>/`) and is bootstrapped only by an explicit command — never on its own.
- **Embeddings are PURE PYTHON.** `fastembed` (onnxruntime + tokenizers) — **NO Node, no daemon, no external vector-DB service, no fabricated metrics.**
- **One deterministic, conservative-only recall→action bridge — `recall-check --files <glob>`.** It counts prior `job_result` records (status in `{blocked, error, timeout}` / scope violation) on the same file pattern; **N ≥ k** (default **2**) yields the verdict **`tighten`** (force worktree / add a review pass / fold into Task 0). It **never reroutes to lower trust and never loosens** — the prose analogue of the scorecard's `unhealthy → escalate`.
- **Two new commands** — `/v:remember` (recall search) and `/v:memory-refresh` (index / bootstrap).
- **`/v:init` now configures recall + autonomy** (structured questions → `.claude/compound-v.json`, honored by the engine/skills): the recall lane (`memory.embeddings`, FTS5 vs opt-in embeddings — the engine adds vectors automatically when on **and** bootstrapped), the memory autonomy level (`memory.auto_recall` / `memory.auto_tighten`), the epic-autonomy cadence (`epic.max_features`), and an automatic cross-model review default (`review.cross_model`).
- **New hook — `hooks/memory-refresh.sh`.** Silent, self-backgrounds an **FTS5-only** refresh, **never installs/bootstraps**; appended to `SessionStart` + `PostToolUse:Write`.
- **Key invariants (all enforced):** the cache lives **outside the repo**; only **git-tracked** prose is indexed; the FTS5 lane is **crash-safe**; writes use **`flock` + a transaction**; **hooks never bootstrap** the DENSE lane.
- **New surfaces:** engine `scripts/compound-v-memory.py`; authority doc `skills/compound-v/memory.md`; commands `commands/v-remember.md` + `commands/v-memory-refresh.md`; hook `hooks/memory-refresh.sh`.

## [1.2.0] — 2026-06-27

### Changed — Epic mode hardening (closes the gaps a re-review of v1.1 surfaced)

- **Specs are batched UP FRONT — the autonomy-vs-quality tension resolved.** The epic now brainstorms a real spec file **per feature before the autonomous loop** (the one human-interactive phase, approved once), carried as a **`spec_path`** on every feature in `features.json`/`epic-state.json`. The loop runs each feature **from its pre-approved spec** and never pauses to brainstorm. `compound-v-epic-state.py --init --require-specs` **refuses to start unless every feature has an existing `spec_path`** — deterministic enforcement, not just prose.
- **Decomposition review gate (one level up from partition-review).** `compound-v-epic-state.py --lint --features F.json` flags structural smells in the feature DAG — an **ISLAND** feature (no `depends_on` and no dependents → a likely missed dependency) and an **over-coupled** feature (depends on most others → a layer, not a vertical slice) — plus hard validation, before any build. A weak decomposition is the #1 way an epic fails downstream.
- **Autonomy budget / checkpoint.** An epic is *N full v1.0 runs*, so it runs under a `MAX_FEATURES` budget per `/v:epic` invocation (default **1**): after the budget is spent it STOPS and reports `--stats` (done/remaining) for the human to review and re-run — a real cost ceiling + human-in-the-loop point, not an unbounded autonomous burn.
- **Reconcile-by-resume — no discarded work.** A feature stuck `running` (crashed mid-pipeline) is reconciled by running its own `/v:resume <run-id>` **first** (re-dispatch only that run's incomplete jobs), falling back to full restart (`pending`) or `failed` only if it can't recover — composing with the per-feature crash-resume instead of throwing away half-built work.
- `compound-v-epic-state.py` gains `--lint`, `--stats`, `--require-specs`, and a `spec_path` field (21-case self-test, up from 12). Docs: `commands/v-epic.md` + `skills/compound-v/epic-mode.md` rewritten to the batched-spec, budgeted, decomposition-gated, resume-reconciling workflow.
- **Validated end-to-end:** a real 2-feature epic (`core` → `cli`, dependency-ordered) driven through the full loop with **live Codex workers** — batched specs → `--lint` → `--init --require-specs` → topological build accumulating on one branch → the **integrated app runs** (`python cli.py → 5`, `cli` importing `core`'s code) → fail-fast halt on a scope-blocked feature → reconcile drill — all behaved correctly.

## [1.1.0] — 2026-06-27

### Added — Epic mode (multi-feature autonomous build)

- **Epic mode — chain multiple plan-runs into one autonomous, resumable, dependency-ordered multi-feature build** (PRD §8). A v1.0 run executes ONE plan (one feature); an **epic** chains several — an ordered set of features, each run through the FULL v1.0 pipeline (spec → 3 pre-flights → writing-plans + partition → manifest → dispatch → 3-pass review) in **dependency order**, accumulating onto **one branch** ("build a whole app"). It is the same discipline one level up — resumable, topological, no daemon. `scripts/compound-v-epic-state.py` is the deterministic state spine over `epic-state.json` (one level up from `state.json`): `--init` validates feature ids/refs/cycles and writes every feature `pending`; `--next` returns the next runnable feature (`pending` with all `depends_on` `done`, in topological order) or a stop reason (`runnable|epic complete|epic blocked|epic needs reconcile`) — the loop is **fail-fast** (any `failed` feature halts the whole epic, even independent pending ones, until reconciled) and **reconcile-strict** (a `running` feature seen between features means a prior run crashed → reconcile via `--update --status pending|failed` before continuing, never an infinite wait); `--update` sets a feature's status/run-id and rolls up the epic status; `--summary` renders the feature table. The new `/v:epic` command (`commands/v-epic.md`) is the driver: it resolves the epic brief into a feature list (`{id, title, depends_on}`), inits or **resumes** from `docs/superpowers/execution/epics/<epic-id>/epic-state.json`, loops `--next` → run that one feature through the full v1.0 pipeline → `--update --status done --run-id <run-id>`, then on `epic complete` runs a **final cross-feature integration review** (the whole accumulated diff against the epic's acceptance criteria) and hands to `superpowers:finishing-a-development-branch`; on `epic blocked` it stops, surfaces the failed feature, and stays resumable (re-run `/v:epic` after a fix). Every per-feature concern is **reused unchanged** (scope gate, model-broker, failure-handling, scorecards). **Honesty boundary, stated loudly:** epic mode is autonomous *chaining*, not "guess a product from one sentence" — each feature still needs a real spec; large epics run **sequentially feature-by-feature** (parallelism is within a feature, no cross-feature parallel dispatch in v1.1); quality is bounded by per-feature spec + partition quality. Docs: `skills/compound-v/epic-mode.md` (the model, the resumable run-dir layout, the integration review, the honesty boundary); `skills/compound-v/SKILL.md` lists epic mode as a capability.

### Added — Antigravity backend adapter (promoted from 1.0 stub)

- **Antigravity (`agy`) is now a real backend, not a stub.** A Bash-spawned `agy --print` worker (`scripts/compound-v-run-antigravity-worker.sh`) that mirrors the Codex worker: runs one file-scoped job inside a dedicated `$TMPDIR` git worktree at HEAD, then emits the canonical `job_result`. Same CLI shape as the codex worker (`--run-id/--job-id/--repo/--prompt-file/--model/--write-allowed/--timeout-sec/[--read-only]/[--network]/[--output-schema]`), same id-safety + timeout-int guards, same delegation to the deterministic scope gate `scripts/compound-v-scope-check.py` for git-derived enforcement (baseline SHA captured **before** `worktree add` so an in-worktree commit can't hide changes), and the same fail-closed status + `failure_class`/`retry_after_seconds` emit. Verified live against **agy 1.0.13**: `cd "$WT" && agy --dangerously-skip-permissions --add-dir "$WT" --print-timeout "<sec>s" [--model …] --print "<prompt>"` — **flag order is load-bearing (`--print` MUST be last; its value is the prompt)**. Summary comes from agy's printed stdout; `session_id` is `""` (agy exposes no resumable session UUID). `--model` is optional (omitted when empty); `--read-only`/`--network`/`--output-schema` are accepted for CLI parity but advisory/ignored (agy has no kernel sandbox toggle or output-schema flag).
- **⚠️ Lower-trust, opt-in backend (documented loudly).** Unlike Codex's `--sandbox workspace-write` (a kernel-level write-confinement root), `agy` has **NO kernel write-confinement**, and headless writes **require** `--dangerously-skip-permissions` — which lets the agent run arbitrary shell and write **outside** the worktree. The worktree + post-hoc `git diff` gate enforces file-scope **inside** the worktree (detection) but **cannot prevent** an out-of-worktree write/shell side-effect. So Antigravity is **opt-in / lower-trust — prefer Codex (kernel-sandboxed) for untrusted / high-stakes work.**
- **`antigravity ⇒ worktree` invariant** added to `scripts/compound-v-validate-manifest.py` (mirrors `codex ⇒ worktree`): an external worker with no kernel sandbox must be worktree-isolated. New self-test: `antigravity` + `isolation: direct` → INVALID.
- **Failure classifier** (`scripts/compound-v-classify-failure.py`) gains an `antigravity` backend with Gemini/agy error rules. Gemini reuses `RESOURCE_EXHAUSTED` for **both** quota exhaustion and per-minute throttling, so the `out_of_credits` needles are deliberately **quota/billing/credit-specific** (`billing`, `exceeded your current quota`, `insufficient credit`, …) — bare `quota` / `exceeded your` / `usage limit` are **excluded** so throttle text like *"Quota exceeded for quota metric … per minute"* or *"exceeded your rate limit"* classifies as `rate_limited` (transient retry), not `out_of_credits` (which would force a needless backend reroute); ambiguous exhaustion falls through to the safer `rate_limited`. Also `auth` (permission_denied/401/403), `context_length`, `overloaded` (503/500/unavailable), `network`. Self-tests cover the quota-vs-throttle split (per-minute quota → rate_limited; hard billing → out_of_credits; permission_denied → auth).
- **Model resolver** (`scripts/compound-v-resolve-model.py`) carries a fallback antigravity map (`deep → Gemini 3.1 Pro (High)`, `standard → Gemini 3.1 Pro (Low)`, `light → Gemini 3.5 Flash (Low)`) used when no discovered map is present; the worker omits `--model` if the resolved value is empty. New self-test for `antigravity/deep`.
- **Docs:** `skills/backend-launcher/adapter-antigravity.md` replaced the stub with the real adapter runbook (6 load-bearing steps, verified `agy` invocation + flag order, worktree + git-diff scope gate, no resume, and a prominent **Safety** section); `skills/backend-launcher/SKILL.md` updated (real adapter, lower-trust caveat); `skills/compound-v/routing-policy.md` lists antigravity as a selectable alternative for `large_isolated` (env-aware: only when `agy` is installed) with the `antigravity ⇒ worktree` invariant and the prefer-Codex safety note; `commands/v-init.md` detects `agy` and records it as a lower-trust backend.

### Added — Antigravity model auto-discovery

- **Antigravity model auto-discovery.** `agy models </dev/null` returns the live catalog **headlessly** (it just waits on stdin — the same `</dev/null` fix already used for `agy --print`; no TTY needed, ~2s), and `scripts/compound-v-discover-models.py` (pure parse + rank — the caller fetches the catalog and pipes it in; the script never calls a backend) ranks it into a deep/standard/light proposal written to `.claude/compound-v.json` (`--write-config` merges into the `models.antigravity` block, preserving the other backends). `/v:models` and `/v:init` use it — `agy models </dev/null | python3 scripts/compound-v-discover-models.py --backend antigravity --write-config .claude/compound-v.json` — so the tier map tracks the live catalog instead of a hand-curated list. Against agy 1.0.13 the proposal is `deep: Gemini 3.1 Pro (High)`, `standard: Gemini 3.1 Pro (Low)`, `light: Gemini 3.5 Flash (Low)`. **Corrected the earlier "`agy models` hangs / needs a TTY" claim** — it does not; it is auto-discoverable headlessly.

### Added — adaptive routing (worker scorecards)

- **Worker scorecards — a data-driven routing signal from measured outcomes** (PRD §8). Routing was a *static guess* (a task-type → a fixed backend/tier, applied the same in every repo); scorecards make it **adaptive**. `scripts/compound-v-scorecard.py` deterministically aggregates `docs/superpowers/memory/task-outcomes.jsonl` into `docs/superpowers/memory/worker-performance.jsonl` — one row per `(backend, type)` with `{total, success, blocked, error, timeout, avg_rework, block_rate, error_rate, success_rate, health}`, where `health ∈ {insufficient_data, healthy, watch, unhealthy}` (a cell needs **≥5 samples** to be judged; below that it stays `insufficient_data`). CLI: `--update [--outcomes P] [--out P]` regenerates the file; `--query --backend B --type T` prints one cell's stats + health. Before assigning a task-type's static-default backend, the router queries the measured health of that `(backend × task-type)` **in this repo** and acts on it: `unhealthy` → **escalate UP a fixed trust ordering** (`claude` ≥ `codex` ≥ `antigravity`) to an equal-or-higher-trust seat (Opus is the safe escalation) with a one-line justification — it **never auto-routes to a lower-trust backend** (a Codex-unhealthy cell escalates to Opus, never silently to Antigravity, which is explicit opt-in only); `watch` → keep the default but note it; `healthy`/`insufficient_data` → static default unchanged. Scorecards are a **hint layered on the static policy, not a replacement**, and only ever make routing **more conservative** (escalate up), never weaker — the HARD invariants (reviewers⇒opus, Codex⇒worktree, unclear⇒planning, sensitive surfaces⇒deep) are untouched. The scorecard **never** modifies the human-curated `routing-lessons.md` and emits **no** cost/token metrics (anti-ruflo). `worker-performance.jsonl` is **machine-generated**, regenerated each run by `compound-v-scorecard.py --update` after the dispatcher appends fresh outcomes — never hand-edited. Wired into `agents/parallel-dispatcher.md` (post-run memory step + per-job routing query), `skills/compound-v/routing-policy.md` (§Scorecard-aware routing), and `skills/compound-v/SKILL.md` (memory layout).

### Hardened — cross-model review + worker robustness

- **Cross-model (Codex) adversarial review of the v1.1 diff, fixed to convergence.** A read-only Codex `gpt-5.5`/high pass reviewed the new code over **two rounds**; every real finding was fixed: epic-state **fail-fast + crash-reconcile** semantics, scorecard **trust-ordering** (escalate up, never auto-downgrade to a lower-trust backend), and the classifier's **quota-vs-throttle** needle narrowing (all reflected in the entries above). Two findings were follow-up-tracked, then completed below.
- **Newline-safe path transport in both backend workers.** `compound-v-run-codex-worker.sh` and `compound-v-run-antigravity-worker.sh` now pass the scope gate's `.changed`/`.violations` JSON arrays **straight through** (`jq --argjson`) instead of a newline-joined round-trip, so a filename containing a literal newline stays **one** element in `files_changed`/`violations`; the blocked decision keys off a gate-derived `viol_count` (a JSON `[]` is non-empty). The gate itself (`compound-v-scope-check.py`) was already NUL-correct, so the BLOCK decision was always right — this fixes the reported arrays. New `scripts/test-worker-path-transport.sh` self-test; fixed **byte-identically** in both workers.
- **TMPDIR / worktree-root canonicalization (both workers).** Require an **absolute** `$TMPDIR`, canonicalize the tmp root up front and build the worktree parent from the **real** path, reject a symlinked parent, and assert the worktree lives outside the repo — defense-in-depth on the existing id-character + symlink-safe containment guards. The deterministic `$RUN_ID/$JOB_ID` worktree path is kept on purpose (resume/cleanup locate the worktree by it, so no random `mktemp -d`).

## [1.0.0] — 2026-06-26

Compound V graduates from a description-driven skill-pack into a **lightweight execution orchestrator**. The three pre-flights and `/v:archaeology` are behaviourally unchanged; the orchestrator extends the *tail* of the flow (manifest → dispatch → scope-gate → collect → review → memory) with multi-backend execution, per-job isolation, and crash-resume. No daemon, no MCP server, no vector DB, and **no fabricated token-cost metrics** (the anti-ruflo charter). Built by dogfooding the Compound V pipeline on this repo.

### Added — the orchestrator delta

- **Execution manifest** (`skills/compound-v/execution-manifest.md`, `examples/manifest.example.yaml`). A machine-readable `manifest.yaml` of file-scoped jobs — backend · optional `tier`/`effort` · isolation · `write_allowed`/`read_allowed` · per-job and feature-level acceptance criteria — materialized from the verified Partition Map immediately after `writing-plans`. A job carries an optional `tier` + `effort`; `model` becomes an optional **override**. A job MUST have `model` **or** `tier` (backward-compatible: existing explicit-`model` jobs stay valid); reviewer jobs must resolve to `tier=deep` **or** `model=opus`. This is the contract between planner and executors.
- **Backend Launcher** sub-skill (`skills/backend-launcher/`). One `job_spec → job_result` contract (`schemas/job_result.schema.json`) that every adapter implements; the orchestrator speaks only this contract and never sees backend-specific flags. Adapters: `adapter-claude.md` (Task-based, model override, `maxTurns: 15`), `adapter-codex.md` (headless `codex exec` in a git worktree), `adapter-antigravity.md` (stub — see dispositions below).
- **Headless Codex worker** (`scripts/compound-v-run-codex-worker.sh`). Runs one file-scoped job on `codex exec` inside a dedicated `$TMPDIR` git worktree, then emits the canonical `job_result`. Verified against `codex-cli 0.130`: the flag set is `--cd / --sandbox / --skip-git-repo-check / --model / --output-last-message / -c sandbox_workspace_write.network_access` (plus optional `--output-schema`). **`--ask-for-approval never` is invalid for `codex exec` and is omitted** — `exec` already defaults to `approval: never`. Resume is `codex exec resume <uuid>`. The cosmetic `[features].codex_hooks is deprecated` stderr is suppressed.
- **Scope gate** (`scripts/compound-v-scope-check.py`). The deterministic authority behind the prose `SCOPE LOCK`. After every job it unions `git diff --name-only <baseline>` with `git ls-files --others --exclude-standard` *and* the gitignored set (`git ls-files --others --ignored --exclude-standard -- .`) and tests each changed path against `write_allowed`. A violation is **BLOCKED** — the job never merges and the run halts. Enforcement fields (`files_changed` / `violations` / `blocked`) are **git-derived, never model-self-reported**.
- **Manifest validator** (`scripts/compound-v-validate-manifest.py`). A deterministic invariant gate the `partition-reviewer` runs: disjoint `write_allowed`, Codex⇒worktree, reviewers⇒Opus/deep, shared resources in the serial Task 0. Extended for the model-broker: `tier ∈ {deep,standard,light}` and `effort ∈ {low,medium,high}` when present, and every job must carry `model` **or** `tier`.
- **State machine + crash-resume** (`skills/compound-v/state-machine.md`). A lightweight `state.json` (not an FSM engine) tracks phase + per-job status under `docs/superpowers/execution/<run-id>/`. `/v:resume` reconciles `state.json` against git reality (**git-wins** tie-break) and re-dispatches only `pending`/`failed`/`blocked` jobs. Resume lives in Engine A so it survives a hard crash.
- **Result collector + lean memory** (`scripts/compound-v-collect-results.py`, `scripts/compound-v-update-memory.py`, `docs/superpowers/memory/routing-lessons.md`). Normalizes heterogeneous worker output into schema-conforming `job_result`s, folds in the scope verdict, and appends one line per job to `task-outcomes.jsonl`. `routing-lessons.md` is human-curated. No semantic search, no scorecards in 1.0.
- **Routing policy** (`skills/compound-v/routing-policy.md`). task-type → **(tier, effort)** + backend/isolation (no concrete model strings in the table). **Balanced** default; **Conservative** and **Cost-aware** stances; **env-aware Claude-only fallback** when Codex is absent. Documents the config `models` map, the resolver, and `/v:models`. Cites `routing-lessons.md` as a consulted input.
- **`/v:init`** (`commands/v-init.md`). Detects Codex CLI / Context7 MCP / required skills, walks through any missing installs one at a time, re-probes the Codex flag set against `codex exec --help`, sets the routing stance, and saves config: project `.claude/compound-v.json` (stance + a **seeded default `models` map** so routing works out of the box — mentions `/v:models` for refresh/customization) + user `~/.claude/compound-v-capabilities.json` (capability cache).
- **New commands** `/v:orchestrate`, `/v:collect`, `/v:status`, `/v:resume`, `/v:models` (`commands/`).
- **Skill escalation policy** (`skills/compound-v/skill-escalation.md`). Gated pull-in of deep-research / playground / avoid-ai-writing, plus forced Context7 — only when genuinely needed, each logged in the run's reasoning.
- **Strict `job_result` schema** (`schemas/job_result.schema.json`) and committed fixtures (`examples/`) so CI validates real data.
- New CI gates in `validate.yml`: schema validity, manifest-invariant check, collector schema-conformance, and a no-fabricated-cost-metric grep.
- **Cross-model plan review** (optional, gated). A different model family (Codex/GPT) adversarially reviews a high-stakes plan/manifest *before* dispatch — the value is **error decorrelation** (a second Opus shares Opus's blind spots; Codex has different priors). Policy in `skills/compound-v/cross-model-review.md`; the read-only reviewer is `scripts/compound-v-codex-review.sh`, emitting findings against `schemas/plan-review.schema.json`. **Advisory only — the orchestrator arbitrates every finding; Codex is never the authority.** Gated by stakes (security/auth/payments/migrations/shared data model, large/coupled partition, architectural change, or human request); skipped for small/mechanical plans. Wired in after the `partition-reviewer` PASS in `phase-3` and surfaced by the `partition-reviewer` agent; manually triggerable via the new **`/v:review-plan`** command.
- **Graceful backend-failure handling** (classify → retry / reroute / halt). When a dispatched job returns non-success, the dispatcher runs a deterministic two-stage pipeline instead of guessing or blindly retrying. `scripts/compound-v-classify-failure.py` classifies the failure from exit code + stderr (codex) or the stream-json `api_retry.error` enum (claude) into one of `{out_of_credits, rate_limited, overloaded, auth, context_length, timeout, network, other, none}` — by error **TYPE**, not HTTP status (OpenAI `insufficient_quota` and a throttle are both 429; the Anthropic credit error is a **400/402, not 429**). `scripts/compound-v-failure-policy.py` is the static decision table: `out_of_credits`/`auth` **never retry** (`out_of_credits` circuit-breaks the backend for the run and re-routes the remaining jobs via the env-aware **codex→claude** rewrite — the SAME runtime rewrite, not just `/v:init`; `auth` halts for re-auth); transient classes **retry the same backend** with exponential backoff + jitter (honoring `retry-after`), capped **per-class AND** by a run-level `max_total_retries` (anti retry-storm); `context_length` re-routes with `escalate_tier` (bigger tier, or split the job). `job_result` gains a `failure_class` field (Codex worker emits it; `null` on success/blocked). The "circuit breaker" is `state.json` fields read at batch boundaries (**no daemon**): `attempts` / `cooldowns` / `circuit_open` / `total_retries` / `max_total_retries`; a transient failure only **deprioritizes** (short cooldown, probed half-open next batch) while a confirmed `out_of_credits`/`auth` opens the breaker for the run. A failed job past its retry budget is marked `failed` and the **batch continues** (ralph-tui-style — independent jobs don't die because a sibling 429'd); the run halts only when the last viable backend is exhausted (→ `/v:resume` after top-up). Every re-route/circuit-break is **loud** — surfaced in `/v:status` and the run summary with the cost direction; never a silent cheap→expensive swap. Policy in `skills/compound-v/failure-policy.md`; wired into `agents/parallel-dispatcher.md` (Step 2c), `phase-3`, `state-machine.md`, `routing-policy.md`, `commands/v-status.md`, and the backend-launcher contract. claude has no further local fallback in 1.0 (antigravity is 1.1), so an `out_of_credits`/`auth` on claude halts rather than re-routes.

### Security / Fixed — independent Codex review hardening (round 2)

A second independent Codex review went deeper and surfaced eight more findings — including a critical enforcement bypass and two regressions introduced by round 1; all are fixed:

- **Commit-inside-worktree bypass of the scope gate (CRITICAL).** The gate keyed off uncommitted `git diff HEAD` ∪ untracked, so an executor that COMMITTED its changes inside its worktree left a clean tree and slipped past enforcement. `compound-v-run-codex-worker.sh` now captures the baseline SHA with `git rev-parse HEAD` BEFORE `git worktree add` and passes `--baseline <sha>` (not `HEAD`) to `compound-v-scope-check.py`, so a `git diff <baseline-sha>` still includes the committed change and BLOCKS it. New scope-gate self-test: a file committed inside a worktree, outside `write_allowed`, must block.
- **Timeout argv-injection guard.** `--timeout-sec` is interpolated unquoted into the `timeout` argv in both bash wrappers; a crafted value like `5; touch /tmp/PWNED` injected argv. Both `compound-v-run-codex-worker.sh` and `compound-v-codex-review.sh` now reject any non-`^[0-9]+$` value with `die`.
- **macOS-symlink-safe containment (REGRESSION fix).** Round 1's containment assertion compared a canonical (`pwd -P`) parent against a raw `$WT` prefix; on macOS `$TMPDIR` is `/var/folders/...` while its canonical form is `/private/var/folders/...`, so the prefix check falsely rejected every valid run. The worker now canonicalizes BOTH sides before comparing; the id-character regex (no `/`, no `..`) remains the real traversal defense.
- **Direct-mode pre-existing snapshot (REGRESSION fix).** Round 1's gitignored/untracked union made direct-mode checks flag PRE-EXISTING untracked/ignored files a job never created. `compound-v-scope-check.py` gains `--preexisting <file>` (paths present before the job, one per line) that are excluded from the changed/violation set; `parallel-dispatcher.md` documents the dispatcher snapshotting pre-existing untracked+ignored for a direct job and passing `--baseline <sha> --preexisting <snapshot>`. New self-test: a snapshotted pre-existing file is not flagged, while a new out-of-scope file still BLOCKS. (Worktree mode is unaffected — a fresh `worktree add HEAD` has no pre-existing untracked.)
- **Backend enum aligned to `antigravity`.** `compound-v-validate-manifest.py` accepted an undocumented `none` and rejected the documented stub backend `antigravity`. The job-backend enum is now `{claude, codex, antigravity}` (`none` is the routing "return to planning" sentinel, never a dispatched job); `execution-manifest.md` and `routing-policy.md` wording matches.
- **Validator requires the remaining top-level fields.** `compound-v-validate-manifest.py` now also requires top-level `spec_path`, `plan_path`, and `audits` (joining the round-1 `run_id`/`feature`/`acceptance_criteria`/`routing_stance`/`max_parallel` set); `examples/manifest.example.yaml` still validates.
- **Collector job-id traversal guard.** `compound-v-collect-results.py` builds `<run-dir>/results/<job-id>.json`; `--job-id` is now validated against `^[A-Za-z0-9._-]+$` (rejecting `.`/`..`) before any path is built, exiting non-zero on a bad id (same class as the round-1 worker guard, previously missed here).
- **Empty write-scope allowed for review jobs.** `compound-v-run-codex-worker.sh` no longer `die`s on an empty `--write-allowed`; an empty allow-list means NO writes are permitted, so the gate treats any changed path as a violation. `adapter-codex.md` documents empty write-scope = read-only/review job.

### Hardened — backend-failure round 2 (fail-closed + health-aware reroute + deepest-tier guard)

A second hardening pass on the graceful backend-failure feature, tightening the executable behavior and the docs that describe it:

- **Fail-closed enforcement faults.** A worker `error`/`timeout` status can no longer carry `failure_class: none` — a genuine failure can't masquerade as success and skip the policy loop.
- **Fallback-health-aware reroute.** `compound-v-failure-policy.py` gained `--fallback-open`: an `out_of_credits` whose only fallback is itself circuit-open now returns **`halt`** (both causes surfaced) instead of a doomed reroute. The dispatcher passes it when `circuit_open[<fallback-backend>].open` is true.
- **Deepest-tier context guard.** The policy gained `--current-tier {deep|standard|light}`: a `context_length` failure escalates a tier **unless already at the deepest tier** (`deep`), where it halts and the job is split (back to planning) rather than escalating into a model that doesn't exist.
- **Real claude enum parsing.** The classifier now **parses** the claude stream-json `api_retry.error` enum and maps the exact value (`billing_error` → `out_of_credits`, etc.); the claude substring needles are a narrow fallback used only when the output isn't JSON (no bare `context`/`invalid_request`, which would mis-escalate). Run the adapter with `--output-format stream-json`.
- **`Retry-After` honored.** The classifier extracts the provider wait; `job_result` carries it as `retry_after_seconds` (int), which the dispatcher passes as `--retry-after` so a retry sleeps the provider's stated time instead of synthetic backoff.
- **Circuit breaker is a reconciled object.** `state.json` `circuit_open` is now `{ "<backend>": { "open", "reason": "out_of_credits|auth", "opened_at", "cleared_by" } }` (not a bare bool). `/v:resume` reconciles it by `reason` — `out_of_credits` stays open until a top-up or a liveness probe, `auth` until re-auth (`/v:init`) — and **never silently re-dispatches** to a still-open breaker.
- **Per-(job, class) attempts.** `state.json` `attempts` is keyed `{ "<job>": { "<failure-class>": n } }`, so a budget consumed by one class doesn't starve another; the counter resets/forks on a backend re-route or class change. The dispatcher passes `attempts[job][class]` as `--attempts`.

Docs updated to match the scripts (no behavior is encoded in prose that the scripts don't enforce): `skills/compound-v/failure-policy.md`, `skills/compound-v/state-machine.md`, `agents/parallel-dispatcher.md`, `commands/v-resume.md`, `skills/backend-launcher/adapter-claude.md`.

### Hardened — backend-failure round 3 (collector parity + breaker wiring)

A third pass closing what a cross-model review of the round-2 code surfaced:

- **Collector parity (critical regression fix).** `compound-v-collect-results.py` now emits the new required `failure_class` + `retry_after_seconds` fields, so a normalized `claude`/`direct` `job_result` satisfies `job_result.schema.json` (its hand-rolled conformance checker now also handles nullable `["string","null"]` types).
- **Auth opens the breaker.** Opening `circuit_open[<backend>]` is keyed on the policy's `circuit_break: true` — true for `auth` as well as `out_of_credits` — not only the out_of_credits reroute path.
- **Retries write a cooldown timestamp.** The `retry` action records `cooldowns[<backend>] = now + backoff_seconds` *before* sleeping, so the resume/half-open logic has a real timestamp to probe.
- **Mid-batch circuit-break is check-before-launch.** Before launching each job the dispatcher checks `circuit_open[backend]`; in-flight jobs on a newly-broken backend complete and fail-fast (a no-daemon dispatcher can't un-launch them).
- **Codex 5xx → overloaded.** `server_error` / `5xx` from codex now classify as `overloaded` (retryable), not `other`.

### Fixed / Documented — independent Codex review hardening (round 3)

A third independent Codex review pass (0 critical, 3 high, 5 medium) produced quick real fixes plus honest documentation of inherent limits:

- **`model: haiku` execution-layer override rejected.** The never-Haiku policy was only checked in frontmatter (`lint-frontmatter.py`), but a manifest job could pin `model: haiku` (or `claude-haiku-...`) as an execution-layer override and slip through. `compound-v-validate-manifest.py` now flags ANY job whose explicit `model` contains "haiku" (case-insensitive) as a violation. New self-test: a job with `model: haiku` is INVALID.
- **`depends_on` graph validated (refs + cycles).** `compound-v-validate-manifest.py` now validates each job's `depends_on`: every referenced id must exist among the manifest job ids (a dangling ref is a violation), and the dependency graph must be acyclic (cycle detection via DFS, naming the jobs on the cycle). New self-tests: dangling ref INVALID, cycle INVALID, valid DAG OK.
- **Manifest structural type-checks.** Required fields are now type-checked, not just presence-checked: `jobs` non-empty list, `acceptance_criteria` list, `audits` mapping, `max_parallel` int, `run_id`/`feature`/`spec_path`/`plan_path` strings, and per-job `write_allowed`/`read_allowed`/`acceptance` lists. A wrong-typed field is its own specific violation; `examples/manifest.example.yaml` still validates.
- **NUL-safe scope-gate path handling.** `compound-v-scope-check.py` switched all three git probes to NUL-delimited output (`git diff --name-only -z`, `git ls-files --others --exclude-standard -z`, and the `-z` ignored variant) and splits on `\0`, so a filename containing a newline cannot smuggle additional paths past the gate. New self-test: an unusual filename (a name with a space, and a name with a literal newline where the FS allows) is attributed as a single path and BLOCKS correctly.
- **Documented inherent limit: `read_allowed` is advisory.** Only `write_allowed` is git-enforced; git cannot track reads, so `read_allowed` documents intent and scopes the prompt but is NOT a hard boundary. Stated plainly in `execution-manifest.md`, `backend-launcher/SKILL.md`, `adapter-codex.md`, and `adapter-claude.md`.
- **Documented inherent limit: `direct`-mode dirty-tree caveat → prefer `worktree`.** `isolation: direct` gates against a baseline minus a pre-existing untracked/ignored snapshot, so a job that MODIFIES a pre-existing untracked/ignored file is not flagged. `worktree` (a fresh checkout with no pre-existing files) is the exact-gate safe default for anything untrusted or on a dirty tree; `direct` stays serial-only and is for trusted, clean-tree jobs. Documented in `execution-manifest.md` and `routing-policy.md`.
- **Stale merge-back instructions corrected.** Removed the remaining `git diff HEAD | git apply` (drops untracked additions) merge-back forms in `adapter-claude.md`, `phase-3-parallel-opus-dispatch.md`, `compound-v/SKILL.md`, and this CHANGELOG's model-broker note, replacing them with the index-based patch (`git add -A && git diff --cached --binary HEAD | git apply --index`) used everywhere else.
- **Clarified deliberate design: agent-driven flow, deterministic enforcement.** Added a note in `phase-3-parallel-opus-dispatch.md` that the orchestration flow is intentionally agent-driven (Engine A, anti-ruflo: no daemon) while enforcement lives in deterministic scripts (scope-check / validate-manifest) — the safety guarantees are in the scripts, not the flow.

### Security / Fixed — independent Codex review hardening

A pass of an independent Codex code review surfaced eight correctness/security findings in the orchestrator scripts and docs; all are fixed:

- **Path-traversal guard on `run_id` / `job_id` (CRITICAL).** `compound-v-run-codex-worker.sh` built a worktree path from these ids and ran `git worktree remove -f || rm -rf` on it — a `../` in an id could escape `$TMPDIR` and delete arbitrary directories. Ids are now validated against `^[A-Za-z0-9._-]+$` (rejecting `.`/`..`) before any path is built, and the worktree path is asserted to live strictly under `$TMPDIR/compound-v/` before any removal. `compound-v-validate-manifest.py` rejects the same unsafe ids (and `run_id`) so a malicious manifest never reaches dispatch.
- **Worker delegates enforcement to the Python gate.** The worker previously derived `violations`/`files_changed`/`status` with a bash `case`-glob matcher that was *weaker* than the Python authority (bash `*` matches `/`) and diverged from it. The bash matcher is deleted; after the codex run the worker now calls `compound-v-scope-check.py` (parsed with `jq`) as the single source of truth, layering timeout/error exit codes on top.
- **Scope gate now sees gitignored writes.** `compound-v-scope-check.py` only probed `git ls-files --others --exclude-standard`, which excludes ignored files — a worker could write a gitignored path (`dist/`, `.env`) undetected. It now also unions `git ls-files --others --ignored --exclude-standard -- .`, so any ignored write outside `write_allowed` is reported and BLOCKS (covered by a new self-test).
- **Allowed new files survive merge-back.** The documented merge-back `git diff HEAD | git apply` silently dropped untracked (new) files — an allowed new file passed the gate but was lost. Replaced everywhere with an index-based patch that includes additions (`git add -A && git diff --cached --binary HEAD | git apply --index`) across `backend-launcher/SKILL.md`, `adapter-codex.md`, `parallel-dispatcher.md`, and the PRD/plan.
- **Direct-mode scope check requires `--baseline`.** A `--repo` (direct) job's baseline must be the recorded pre-dispatch commit, not a defaulted (possibly-moved) HEAD; the gate now errors if `--baseline` is omitted in direct mode. Worktree mode keeps the HEAD default (worktrees are fresh from HEAD).
- **Validator enforces all required fields + `parallel ⇒ worktree`.** `compound-v-validate-manifest.py` now validates every required top-level and per-job field and their enums (`backend`/`isolation`/`run`/`routing_stance`/`tier`/`effort`) before the invariant checks, and rejects any `run: parallel` + `isolation: direct` job (per-job scope attribution requires worktree isolation). The example manifest's parallel claude jobs moved to `isolation: worktree`; `execution-manifest.md` and `routing-policy.md` state the rule crisply (parallel ⇒ worktree; direct ⇒ serial).
- **Collector can no longer override the scope verdict.** In `compound-v-collect-results.py` the `--files-changed` / `--violations` / `--blocked` flags are now **additive-only** when a scope verdict is present: `blocked` = scope OR flag, `violations`/`files_changed` = union(scope, flag). A flag may force a block or add entries but can never clear a scope-gate block or drop a scope violation.

### Fixed

- **`validate-manifest.py` `globs_overlap` soundness fix.** The manifest validator's write-glob overlap test (rule 1, disjoint writes) had a soundness bug — caught on the first real cross-model review run when Codex read the repo and flagged it. Hardened so overlapping `write_allowed` globs are reliably detected.

### Added — the model-broker delta

Stops hardcoding model strings. Jobs route by **intent**, not by a literal model name, so the plugin survives model churn and gains Codex's reasoning-effort dimension.

- **Tier + effort vocabulary** — a stable routing vocabulary that never changes when models churn. `tier ∈ {deep, standard, light}` (deep = strongest reasoning: architecture, security/auth/payments, designing tests, external APIs, **all** reviewers, the shared-foundation Task 0; standard = bounded core/feature build incl. large isolated Codex work; light = mechanical single-file / docs / i18n). `effort ∈ {low, medium, high}` is an orthogonal hint with a sensible default pairing (deep→high, standard→medium, light→low) that stays independently tunable per task-type.
- **Refreshable config model-map** — `.claude/compound-v.json` gains a `models` map (`claude` / `codex` / `antigravity`, each `deep`/`standard`/`light` → a concrete model). The map is **not** committed in the repo — it is documented and seeded by `/v:init`, then refreshed via `/v:models`. Claude uses native tier aliases (`opus`/`sonnet`), Codex is a curated+user-overridable list (it has no `models` list command), and Antigravity values are auto-discovered from `agy models` (see the 1.1 auto-discovery note). **Never `haiku`, anywhere.**
- **Model resolver** (`scripts/compound-v-resolve-model.py`). Generic — no backend-specific Codex/Antigravity logic baked into routing. CLI: `--backend {claude|codex|antigravity} --tier {deep|standard|light} [--effort {low|medium|high}] [--config PATH] [--explicit-model M]`. Carries a **built-in default map** so it resolves with no config file; a `models.<backend>.<tier>` entry in `--config` overrides the default; `--explicit-model` (a manifest override) always wins. Emits one JSON object on stdout — `{ "backend", "tier", "model", "effort" }` — and exits non-zero when a tier can't be resolved. Python 3.9-safe, stdlib only.
- **Codex `--effort`** — `scripts/compound-v-run-codex-worker.sh` gains an optional `--effort {low|medium|high}` arg that appends `-c model_reasoning_effort=<effort>` to **both** `codex exec` invocations (with and without `--output-schema`). Everything already there is preserved: the `</dev/null` stdin redirect, stdout capture, scratch-outside-worktree handling, no `--ask-for-approval never`, bash 3.2 safety, shellcheck-clean.
- **`/v:models`** (`commands/v-models.md`). Discovers available models per backend — `agy models` for Antigravity (when present), a curated list for Codex, native tiers for Claude — shows them, lets the user assign tier→model, and **writes** the `models` map into `.claude/compound-v.json`. This is the "skill picks the models and offers you options" surface.

### Changed

- **`plugin.json` + `marketplace.json` → `1.0.0`** in lockstep; added the `orchestrator` keyword.
- **`SKILL.md`** evolved to orchestrator-as-default — the description now mentions manifest materialization and the scope-enforced, resumable pipeline, **without weakening the auto-fire triggers** (every existing `evals.json` case still passes).
- **`/v:dispatch`** evolved to be manifest-aware **backward-compatibly**: it accepts a bare plan path (auto-materializing a manifest), a manifest, or a run-id. The 0.1.x plan-path flow — and the `plan-saved-nudge` hook — keep working.
- **Agents evolved:** `parallel-dispatcher` is manifest-driven and multi-backend — for each job it runs `compound-v-resolve-model.py` with `(backend, tier, effort, config)` **before** dispatch to get the concrete model, passes `--model <resolved>` (+ `--effort` for Codex) to the worker, then calls `scope-check.py` after every job and HALTS on BLOCKED (an explicit manifest `model` skips resolution); `partition-reviewer` runs `validate-manifest.py` as its deterministic backing gate; `spec-reviewer` runs the three-pass Review Gate (spec acceptance criteria · quality/no-regression/no-fabricated-metrics · final integration). All reviewers remain `model: opus`. The agent's own `model: opus` frontmatter is unrelated to execution-layer resolution; resolved manifest models (`gpt-5.5`, etc.) are execution-layer data and **never** appear in frontmatter.
- **Phases evolved:** `phase-2` emits `manifest.yaml` (not only prose); `phase-3` is manifest-driven multi-backend dispatch with per-job isolation and the scope gate.
- **Hooks evolved:** `session-banner.sh` adds a `/v:init` hint when `.claude/compound-v.json` is absent; `plan-saved-nudge.sh` mentions `/v:orchestrate` alongside the existing dispatch path. Both keep all three platform JSON branches and stay `shellcheck`-clean.

### Explicit dispositions

- **Antigravity adapter = stub, deferred to 1.1.** Assessed, not assumed. Google's official `agy` CLI fits the contract, but two blockers keep it out of 1.0: headless `agy --print` returns empty stdout when piped/redirected ([#408](https://github.com/google-antigravity/antigravity-cli/issues/408), [#318](https://github.com/google-antigravity/antigravity-cli/issues/318)) and there is no non-interactive auth ([#223](https://github.com/google-antigravity/antigravity-cli/issues/223)). `adapter-antigravity.md` ships as a stub returning `unsupported`; the 1.1 spike targets the Antigravity Python SDK first.
- **Workflows accelerator = kept in 1.0 as opt-in (Engine C).** `skills/compound-v/workflows-accelerator.md` is a capability-probed fast-path for large parallel batches (16-wide) that **auto-falls-back to Engine A's batched `Task` dispatch** when Workflows is absent or disabled. The scope gate and `state.json` resume **stay in Engine A** even when C runs, so file-scope enforcement and crash-resume never regress. Engine B (`claude -p` shell-out) was rejected (rate-limit cascades + third-party-orchestrator policy).

### Notes

- All helper scripts — including the new `compound-v-resolve-model.py` — target stock-macOS **bash 3.2** and **python 3.9** (stdlib only; pyyaml optional with an embedded-subset fallback) and are `shellcheck`-clean and executable.
- The `models` map is **documentation + seeded config**, never committed in the repo. `compound-v-resolve-model.py` ships with a built-in default map so routing works even with no config file present.
- Worktrees live in `$TMPDIR/compound-v/<run-id>/<job-id>`; merge-back on PASS is an index-based patch that includes new files (`git -C <wt> add -A && git -C <wt> diff --cached --binary HEAD | (cd <repo> && git apply --index)`) into the main tree — a plain `git diff HEAD | git apply` would drop allowed untracked additions.
- Honestly **not** auto-tested (documented + manually verified, no CI gate): the worker-prompt pre-emptive STOP behaviour (only the post-hoc scope-check is gated), Codex-session resume re-attachment, the `/v:init` flag-probe, capability-cache staleness, and the Workflows probe-fails→fallback path.

## [0.1.3] — 2026-05-18

### Changed
- Marketplace name renamed from `superpowers-v-marketplace` to `procoders`. End-user install command is now `/plugin install superpowers-v@procoders` (was the awkward `superpowers-v@superpowers-v-marketplace`). The `procoders` name is also future-proof — additional procoders plugins can ship via the same marketplace.
- README install section trimmed to one path at the top; local-clone / `--plugin-dir` dev flows moved to a new **Development** section lower in the doc.

## [0.1.2] — 2026-05-18

### Fixed (critical)
- **Install instructions in README were wrong.** Claimed `/plugin install <github-url>` works directly; it does not. Real path is the documented two-step: `/plugin marketplace add <url-or-path>` first, then `/plugin install <plugin>@<marketplace-name>`. Reported by user trying to install v0.1.1 from GitHub and getting "Marketplace not found."

### Changed
- Marketplace name renamed from `superpowers-v-dev` to `superpowers-v-marketplace` (mirrors the upstream `obra/superpowers` → `superpowers-marketplace` naming convention; cleaner for end-user-facing install command).
- README install section now shows three install paths: marketplace + GitHub, marketplace + local clone, and `--plugin-dir` live-edit mode.

## [0.1.1] — 2026-05-18

Honesty pass after an independent verification audit caught several fabricated CLI/env-var references that I had baked into hooks and docs without verifying against the official Claude Code documentation.

### Fixed (critical — load-bearing)
- **Hook scripts no longer read fabricated environment variables.** Rewrote `session-banner.sh` and `plan-saved-nudge.sh` to follow the documented Claude Code hook interface: input read from JSON on stdin (via `jq`), output emitted as JSON for `additionalContext` context injection. Pattern adapted from upstream `obra/superpowers v5.1.0` reference hooks. Previous scripts read `$CLAUDE_HOOK_MATCHER` and `$CLAUDE_TOOL_INPUT_FILE_PATH`, neither of which exists in the official hook spec — the hooks were technically running but always silently no-op'd.
- **SessionStart matcher corrected** from `*` to the documented pattern `startup|clear|compact` (matches upstream superpowers).

### Removed
- `compound-v:doctor` agent + `/v:doctor` slash command — clutter for typical sessions; manual debug instructions in TROUBLESHOOTING.md cover the same ground.
- `SubagentStop` hook configuration + `sidekick-nudge.sh` script — the `SubagentStop` event is not in the official Claude Code hooks reference and the reference plugin `obra/superpowers` does not use it. Replaced with description-based auto-fire (which was always the primary mechanism) plus the `PostToolUse(Write)` plan-saved nudge.
- `gemini-extension.json` — manifest schema was not verifiable against official Gemini CLI docs; removed rather than ship a fabricated config.

### Changed
- **Multi-harness shims (AGENTS.md, GEMINI.md) marked 🧪 experimental / untested.** Previous wording implied verified support; honest reality is the shims are based on documentation patterns but were not exercised on a real Codex or Gemini install. The README compatibility table now reflects this.
- README install steps: removed fictional `/mcp add context7` command; correct install path is `/plugin install context7@claude-plugins-official` or manual `~/.claude.json` MCP config. Context7 demoted from step 1 to step 3 (recommended, not required).
- Phase 3 dispatcher announce string toned down (was "going Supe"; now neutral "dispatching N implementers").
- SKILL.md auto-fire caveat rewritten honestly: skill invocation is description-driven; hooks provide reminders but do NOT enforce the trigger.
- `.github/workflows/validate.yml` no longer validates `gemini-extension.json` (file removed).

### Added
- Hard citation-rigor rules in `agents/domain-expert.md`: ≥10 distinct community posts OR 1 official source for consensus claims; isolated reports flagged explicitly; no fabricated URLs; verbatim quotes only; empty section > padded section.

### Notes on the honesty audit
The verifier could not find official documentation for several Task tool parameters used throughout the plugin (`subagent_type: "<plugin>:<agent>"` plugin-namespaced syntax, `maxTurns`, `run_in_background: true`). These remain in the plugin's prompts and docs because they are observably functional in Claude Code as of v0.1.1, but should be revisited if they break in a future CC version. Tracked for future verification.

## [0.1.0] — 2026-05-18

Initial public release.

### Added

**Core skill (`skills/compound-v/`):**
- Three-trigger interceptor for Superpowers transitions (after brainstorming, inside writing-plans, before execution)
- Phase 1A: code-archaeology pre-flight (five-phase audit of existing-code reality)
- Phase 1B: domain-expert advisor with three-layer parallel WebSearch (official docs, practitioner channels, audience/persona forums)
- Phase 1C: library/doc validator via Context7 MCP (catches stale deps, abandoned libraries, outdated API signatures)
- Phase 2: Disjoint File Partition Map enforcement inside writing-plans
- Phase 3: batched parallel Opus dispatch with strict scope locks; `model: opus` by default, `model: sonnet` only when a task ticks every box of the strict 8-box junior-task taxonomy

**6 first-class agents (`agents/`)** — invokable as `subagent_type: "compound-v:<name>"`:
- `code-archaeologist`, `domain-expert`, `doc-validator`, `partition-reviewer`, `parallel-dispatcher`, `spec-reviewer`

**2 slash commands (`commands/`):**
- `/v:archaeology <topic>`, `/v:dispatch <plan-path>`

**Hooks (`hooks/`)** — sidekick auto-fire (text-printer only, no side effects):
- `SessionStart` banner reminding parent Claude that Compound V is loaded
- `PostToolUse matcher=Write` nudges when a plan or spec is saved

**Operational:**
- `.github/workflows/validate.yml` — JSON schema, agent frontmatter (with no-Haiku project policy), dead-link scan, shellcheck on hooks
- `scripts/lint-frontmatter.py` — Python frontmatter linter for local pre-commit
- `evals/evals.json` — 8 trigger eval test cases (3 positive, 2 negative, 3 edge) for the compound-v skill
- `.cclintrc.json` — config for [`@felixgeelhaar/cclint`](https://github.com/felixgeelhaar/cclint)
- `TROUBLESHOOTING.md` — common issues
- All code blocks tagged with explicit language

**Realistic concurrency limits documented:** 4-6 foreground / 5-10 background Task calls per message; batched dispatch for larger plans; `maxTurns: 15` cap; `run_in_background: true` recommended for implementer batch.

**Output convention:** `docs/superpowers/{archaeology,expert,library-audit}/` with `_knowledge-base/` subdirectories for cross-feature knowledge persistence.

## [0.1.0] — 2026-05-18

Initial public release.

### Added

**Core skill (`skills/compound-v/`):**
- Three-trigger interceptor for Superpowers transitions (after brainstorming, inside writing-plans, before execution)
- Phase 1A: code-archaeology pre-flight (five-phase audit of existing-code reality)
- Phase 1B: domain-expert advisor with three-layer parallel WebSearch (official docs, practitioner channels, audience/persona forums)
- Phase 1C: library/doc validator via Context7 MCP (catches stale deps, abandoned libraries, outdated API signatures)
- Phase 2: Disjoint File Partition Map enforcement inside writing-plans
- Phase 3: batched parallel Opus dispatch with strict scope locks; `model: opus` by default, `model: sonnet` only when a task ticks every box of the strict 8-box junior-task taxonomy

**6 first-class agents (`agents/`)** — invokable as `subagent_type: "compound-v:<name>"`:
- `code-archaeologist`, `domain-expert`, `doc-validator`, `partition-reviewer`, `parallel-dispatcher`, `spec-reviewer`

**2 slash commands (`commands/`):**
- `/v:archaeology <topic>`, `/v:dispatch <plan-path>`

**Hooks (`hooks/`)** — sidekick auto-fire (text-printer only, no side effects):
- `SessionStart` banner reminding parent Claude that Compound V is loaded
- `SubagentStop matcher=brainstorming|writing-plans` nudges with next-step dispatch
- `PostToolUse matcher=Write` nudges when a plan or spec is saved

**Multi-harness compatibility shims (experimental):**
- `AGENTS.md` (Codex CLI)
- `GEMINI.md` + `gemini-extension.json` (Gemini CLI)

**Operational:**
- `.github/workflows/validate.yml` — JSON schema, agent frontmatter (with no-Haiku project policy), dead-link scan, shellcheck on hooks
- `scripts/lint-frontmatter.py` — Python frontmatter linter for local pre-commit
- `evals/evals.json` — 8 trigger eval test cases (3 positive, 2 negative, 3 edge) for the compound-v skill
- `.cclintrc.json` — config for [`@felixgeelhaar/cclint`](https://github.com/felixgeelhaar/cclint) (silences CLAUDE.md-specific false-positives)
- `TROUBLESHOOTING.md` — 11 documented common issues
- All code blocks tagged with explicit language (`plaintext`, `markdown`, etc.)

**Realistic concurrency limits documented:** 4-6 foreground / 5-10 background Task calls per message; batched dispatch for larger plans; `maxTurns: 15` cap; `run_in_background: true` recommended for implementer batch.

**Output convention:** `docs/superpowers/{archaeology,expert,library-audit}/` with `_knowledge-base/` subdirectories for cross-feature knowledge persistence.
