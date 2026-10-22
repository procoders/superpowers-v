# v3.4.2 Transcript Play-ahead — Code Archaeology

Spec under audit: `docs/superpowers/specs/2026-09-03-v3.4.2-transcript-watch-design.md`.
A plan (`docs/superpowers/plans/2026-09-03-v3.4.2-transcript-watch.md`) already exists for this
spec; it is treated here as another artifact to verify against, never as settled ground.

**NOTE ON WHERE THIS FILE LIVES.** The assigned destination was
`docs/superpowers/archaeology/2026-09-03-v3-4-2-transcript-watch.md`. Every attempt to write there
was denied, live, by `hooks/lane-guard.sh` — see §0b, which is itself one of this audit's findings.
This copy is parked in the scratchpad so the analysis is not lost; it still needs to be moved to the
intended path by whoever can write there (or once the stale lane map named in §0b ages out).

## Step 0 — V-memory recall

Three queries run (`compound-v-memory.py search ... --intent planning --top 8`):

1. `"transcript watch worker jsonl signals"` — no hit on this feature (it postdates the index by
   87 docs; V-memory reports itself 87 docs behind). Closest adjacent material: the v2.5.0
   hang-detector spec/plan and the session-aware-workers archaeology/library-audit docs (session-id
   capture from Codex's own `--json` stream — a **different** JSONL format, external-worker-sourced,
   not a Claude subagent transcript).
2. `"scope gate write_allowed matcher out-of-lane"` — surfaced `2026-09-01-v3.0-triage-tests-orchestration-design.md`'s E1 rule (the lane-guard's own summary of its resolution order) and several dogfood notes confirming the scope gate is git-derived and matcher-shared.
3. `"lane-map.json register-lane state.json v:status"` — surfaced the same E1 rule plus dogfood
   partition-integrity notes (`lane-map.json` resolves cwd/agent → job in practice, not just in prose).

**What to do with it:** nothing in V-memory documents the transcript JSONL format directly — this
is a genuinely new mechanism, corroborated by Phase 3 below (no sibling script parses it). The E1
citation is the one piece of prior art worth carrying forward: it independently confirms the
lane-guard's resolution order and matcher-sharing rule the spec's design decision #1 depends on.
Where V-memory is silent, this audit went to the filesystem directly (Phase 3/4) rather than
inventing history.

## 0b. Live incident during this audit (self-demonstrating finding)

Writing this file's real destination was **denied**, twice, live, by `hooks/lane-guard.sh`
mid-audit, with identical text both times:

> `Compound V lane guard: job 'spec-review-3' is not allowed to write
> 'docs/superpowers/archaeology/2026-09-03-v3-4-2-transcript-watch.md'. Its write_allowed lane is:
> docs/superpowers/dogfood/2026-09-03-v3.4.1-triage-size-review-3.md. Resolved via cwd->worktree.`

This code-archaeology task has no run directory of its own (`docs/superpowers/execution/` has no
`v3.4.2-transcript-watch*` entry — confirmed by listing every `lane-map.json` in the tree), so this
agent should be in the guard's ordinary "job unresolved → allow" bucket. It was not. Root cause,
confirmed by reading the actual file:

`docs/superpowers/execution/2026-09-03-v3.4.1-triage-size-r5/lane-map.json`:
```json
{"agents": {}, "worktrees": {"/Users/oleg/Dev/superpowers-v": "spec-review-3"}, ...}
```

A **direct-isolation** job's `register-lane` call records its "worktree" as the bare repo root
(there is no separate worktree in direct mode — `compound-v-emit-workflow.py:4356`,
`pin_root = repo_root if args.isolation == "direct" else ...`). `hooks/lane-guard.sh`'s
`resolve_job()` cwd→worktree fallback then does `_rel_under(cwd, wt)` against **every** worktree
entry in the **newest** lane map it finds (`map_files()`, newest-mtime-first, first match wins) —
and a worktree entry equal to the repo root matches **any** cwd inside the repo, not just the one
agent that registered it. Because `2026-09-03-v3.4.1-triage-size-r5`'s lane map happens to be the
freshest on disk right now, **every** ordinary tool call anywhere in this checkout — this
archaeology task's included, which has no relationship to that run at all — is being resolved as
job `spec-review-3` and gated against **that job's** one-file lane, until a newer run's lane map
supersedes it.

This is not a rare edge case: **every** direct-mode job produces a worktree entry equal to the repo
root by construction (isolation `direct` has no separate tree — confirmed live in
`docs/superpowers/execution/2026-09-02-df18-direct-digest/lane-map.json` and others), so this
collision recurs any time a direct-mode job's lane map is the newest one on disk and any other
agent — Compound-V job or not — happens to be working from the repo root at the same time. See
Finding 0 in §7 and the sibling-bug note in §3; it is the single most concrete, live-reproduced
finding in this audit, and it is exactly the class of "wrong cwd" collision the feature under
audit will itself need to reason about if it ever resolves a job by the same cwd→worktree fallback.

## 1. Matrix

The dimensions the new script must classify per observed event, and what already exists to answer
each:

| Dimension | Values seen live | Existing code that resolves it | New code must add |
|---|---|---|---|
| Transcript directory shape | `<session>/subagents/agent-*.jsonl` (plain Task-tool subagent) vs `<session>/subagents/workflows/<wf_id>/agent-*.jsonl` (Workflow-spawned) — **both exist on disk simultaneously in this project's own session** | nothing (no script reads either) | discovery logic that scans the `workflows/*` shape specifically (spec §2) — verified correct, see Phase 3 |
| Transcript line `type` | `"user"`, `"assistant"`, `"attachment"` | nothing | a per-line type switch; `"attachment"` lines carry **no `message` key at all** |
| `message.content` shape | a **raw string** (the very first user line — the initial prompt) vs an **array** of `{"type":"tool_use"|"text",...}` (assistant) vs an **array** of `{"type":"tool_result",...}` (user, after the first line) | nothing | must not assume array-of-objects unconditionally |
| Denial channel | `hooks/lane-guard.sh` PreToolUse `deny()` (scope-lane specific) vs the harness's **bashCommandClamp** permission-rule denial (unrelated to lanes, routine, self-corrected) | `hooks/lane-guard.sh` produces the first; the harness produces the second, and it is **far more common** in the sample read (2 occurrences in one ordinary job's transcript, 0 lane-guard denials found in transcripts anywhere — though one WAS just triggered live against this very agent, see §0b) | must not conflate the two — see Finding 1 |
| `register-lane` attempt count per agent | 1 (clean) vs 2+ (first attempt denied by bashCommandClamp for using `$PWD`/`&&`, retried in a clamp-legal literal form) — **observed directly**, not hypothesized | nothing | resolution must key off the **succeeded** `register-lane` call, not the first `tool_use` matching the name |
| `isolation` | `direct` \| `worktree` (argparse `choices=["direct","worktree"]`, `compound-v-emit-workflow.py:4294`) | `register-lane`'s CLI + `state.json.jobs.<id>.isolation` | comparing the manifest's `isolation:` (confirmed field name, `manifest.yaml:26,43`) against the `--isolation` value parsed out of the tool_use command string |
| cwd→worktree collision | a **direct-mode** job's worktree entry == the bare repo root, matching every cwd in the checkout (live-confirmed, §0b) | nothing catches this; `hooks/lane-guard.sh` inherits it silently | if the watcher resolves an agent's job by the same cwd→worktree fallback, it will misattribute events across unrelated concurrent runs exactly as just happened to this audit |
| manifest YAML parse, when PyYAML is absent | PyYAML present vs absent on the interpreter that runs the watch script | `hooks/lane-guard.sh`'s whole viability ladder + `compound-v-validate-manifest.py`'s `load_yaml()` subset-parser fallback (≈250 lines, built because this exact problem bit a real run) | **nothing in the spec or plan says how `compound-v-transcript-watch.py` parses `manifest.yaml` under "Python 3.9 stdlib only"** — stdlib has no YAML parser at all. See Finding 5. |

## 2. Shared State

**`isolation` (per job, compared against a register-lane `tool_use`):**
- Set in the manifest: `jobs[].isolation` (`manifest.yaml:26,43`, confirmed live: `worktree` / `direct`).
- Set again, independently, in `state.json.jobs.<id>.isolation` by `register-lane` itself
  (`compound-v-emit-workflow.py:4375`, `entry["isolation"] = args.isolation`) — this is the CLI
  argument the agent passed, **not** re-derived from the manifest by the register-lane command
  itself (register-lane trusts the prompt-supplied `--isolation`).
- The spec's `wrong-cwd` signal wants "a `register-lane` whose `--isolation` disagrees with the
  manifest's `isolation` for that job" — meaning the watch script must read the **manifest's**
  value (source of truth) and compare it against the **command string's** `--isolation` flag as
  typed by the agent (which could differ from `state.json`'s copy if a later `register-lane` were
  re-run with a different flag — the ONE-SHOT baseline-pin logic at `:4335` does not prevent a
  second call with a different `--isolation`, only from re-snapshotting `preexisting/`).
  **Gap the plan must close:** whether to trust the *first* `register-lane` invocation, the *last*,
  or *every* one when several appear for the same agent (see the retry finding above).
- **`worktree` (per job, in `lane-map.json`):** for a `direct`-isolation job this is set to the bare
  repo root (§0b, live-confirmed), **not** `null`/absent/a sentinel meaning "no worktree." Any
  consumer — the shipped guard, or the new watcher if it reuses this map — that treats a
  `worktrees` entry as "this path uniquely identifies one job" is wrong for every direct job.

**`agentId` → job (register-lane resolution):**
- Set from the FIRST successful (`is_error` absent/false) `register-lane` `tool_result` for that
  `agentId` in the transcript, per the spec's own design decision #3's last paragraph.
- **NOT set**, or set from garbage, if the resolver naively takes the first `tool_use` named
  `register-lane` regardless of whether its `tool_result` was a clamp denial. Directly observed:
  `agent-ac9dcaa78a0bd7ee6.jsonl` line 4 is a `register-lane` `tool_use` using `"$PWD"` and `&&
  pwd`, denied at line 5 by the bashCommandClamp (not the lane guard); the real, effective call is
  line 6, succeeding at line 7. A resolver that reads line 4's `--cwd "$PWD"` (an unresolved shell
  variable, never a literal path) would record cwd as the literal string `$PWD` for that job.

**`message.content` (per transcript line):**
- On `type:"user"`, line 1 of a subagent's transcript: a **plain string** (the prompt text).
- On `type:"user"`, later lines: an **array** of `{"type":"tool_result", "content":..., "is_error":
  bool, "tool_use_id":...}`.
- On `type:"assistant"`: an **array** of `{"type":"tool_use","id":...,"name":...,"input":...}` or
  `{"type":"text","text":...}`.
- On `type:"attachment"`: **no `message` key exists on the line at all** — the payload is under
  `attachment` (`{"type":"deferred_tools_delta",...}` or `{"type":"skill_listing",...}`).
- **Gap:** neither the spec nor the plan's Step 2 ("parsers (`iter_tool_events(path)`)") names this
  shape split. A parser written against only the examples in the spec's own prose (which quotes no
  raw JSONL) will almost certainly assume `message.content` is always present and always a list,
  and crash or silently skip the first line and every attachment line of every transcript.

## 3. Sibling Code

**`scripts/compound-v-liveness.py`** (`hang detector`, v2.5.0) is the nearest sibling in spirit —
read-only, git+FS-derived (never model-self-report), pure stdlib, `argparse`, `--json`, `--selftest`
with synthetic fixtures built in `tempfile.TemporaryDirectory()`, `_render()` for the table form,
exit-code semantics distinguishing "nothing to report" from "attention needed" (0 vs 3, here 0
always per spec since this feature is advisory). **It never reads a Claude subagent transcript** —
its only JSONL consumer is `_newest_jsonl_event()`, which tails an EXTERNAL worker's `--json`
stream (Codex's `thread.started`/`item.completed` events via `job.log` in `state.json`), a
different, already-machine-readable, single-object-per-line format with no `message`/`type`
envelope at all. Its defensive pattern IS directly reusable, though: it reads only the **tail**
bytes of a growing log, skips a partial/mid-write trailing line without raising, and degrades to
`None` on any malformed JSON — the transcript watcher will want the identical discipline for a live
tail read of a still-growing `agent-*.jsonl`, since (per `hooks/lane-guard.sh`'s own header) these
files are written by a live, in-flight session.

**`hooks/lane-guard.sh`** is the second sibling, load-bearing for THREE of the spec's design
decisions, and it carries a live, self-demonstrated latent bug (§0b):

- **Latent bug, live-reproduced (not hypothesized):** `resolve_job()`'s cwd→worktree fallback
  (`for wt, job in worktrees.items(): if cwd and _rel_under(cwd, wt) is not None: return job, ...`)
  treats a `worktrees` entry equal to the bare repo root — which is exactly what a `direct`-isolation
  job's `register-lane` call produces — as matching **every** cwd anywhere inside the repo, not only
  the one job that registered it. `map_files()` returns the single **newest** lane map first and
  `resolve_job()` returns on the first match, so whichever run most recently ran a direct-mode job
  becomes the involuntary lane for **every** other agent working from the repo root — including this
  archaeology task, which has no run directory of its own at all. This blocked this file's real
  destination write, twice (§0b), with the exact deny text quoted there. It is a false-POSITIVE
  resolution (the guard is confident and wrong), not one of the documented fail-open cases in the
  hook's own header.
- **Matcher import** (design decision #3, `out-of-lane`): `load_matcher()` at line ~1075-1083
  (current tree) does exactly what the spec asks — `importlib.util.spec_from_file_location` +
  `exec_module` on `compound-v-scope-check.py`, then calls `mod.is_allowed(rel, allowed)` where
  `rel` is a repo-relative path string and `allowed` is the job's glob list. This is a **proven,
  already-shipped** pattern; the plan should cite it as precedent, not re-derive the import
  mechanics from scratch.
- **YAML parsing** (needed for `manifest.yaml` per design decision #2/#3, but **absent from the
  spec's own Global Constraints**): `repo_loader()` imports `compound-v-validate-manifest.py` by
  the same `importlib` pattern and calls `mod.load_yaml(text)`, which prefers PyYAML in-process,
  falls back to trying PyYAML via another interpreter on `CV_PY_CANDIDATES`, and only then falls
  back to an embedded SUBSET parser. This machinery exists **because a real run was silently
  mis-guarded** when the interpreter on hand had no PyYAML (documented at length in the hook's own
  header, "READING THAT MANIFEST NEEDS PyYAML"). See Finding 5 — the spec/plan do not mention this
  at all, despite needing `manifest.yaml`'s `isolation` and `write_allowed` per design decisions
  #2 and #3.
- **The literal denial text** (design decision #3, `denied`): `deny()` at line ~629-634 emits JSON
  with `permissionDecisionReason` set to one of two f-string templates, both starting
  `"Compound V lane guard: job '%s' ..."` (no hyphen) — confirmed both from source and from the
  live deny in §0b. The FAILED-OPEN, non-denial notices use a **different, hyphenated** prefix,
  `"Compound V lane-guard FAILED OPEN: ..."` (`open_notice()`, same file). Neither ever contains the
  literal word `DENY` — the JSON field carrying the verdict is `"permissionDecision": "deny"`
  (lowercase, structural, not prose). See Finding 1.

**Known latent gap in the sibling itself** (documented in the hook's own comments, not discovered
here): "LANE REGISTRATION IS NOT ENFORCED, AND THIS HOOK CANNOT ENFORCE IT" — a worker that writes
before calling `register-lane` is invisible to the guard until it registers. The hook's own
mitigation is the `lane-guard-unresolved.jsonl` record in the run directory. The transcript watcher
is a **second, independent way to see the same gap** (an agent's first tool_use, before any
register-lane, that writes) — worth naming as exactly the kind of event `out-of-lane` should catch
even before the lane map exists, which the spec's design (comparing against `write_allowed` via the
scope-gate matcher) does not obviously handle for an `(unregistered)` agent, since there is no lane
to match against yet. The spec does name `(unregistered)` and says "its writes are all
`out-of-lane` candidates" — consistent with this gap, good — but the plan does not show HOW an
unregistered agent's target path is judged "out-of-lane" with no `write_allowed` list to check it
against (candidate for `(unregistered)`, everything is flagged? nothing is flagged until the job is
known? unspecified).

## 4. External APIs / Native Artefacts (live-verified, not from memory)

Not a third-party API — the "external" surface here is the Claude Code harness's own on-disk
session format, which is unversioned and undocumented as a public contract. Verified LIVE against
this machine's real `~/.claude/projects/` tree (both this project's sessions and five other
projects' Workflow runs), not assumed from the spec's prose:

- **Path shape is correct as specified**, once corrected for my own first (wrong) glob: the real
  path is `<project>/<session-uuid>/subagents/workflows/<wf_id>/agent-<agent-id>.jsonl` (five path
  segments between `projects/` and the file — a glob missing the `<session-uuid>` level, as my
  first attempt was, finds nothing and would wrongly read as "the format doesn't exist"). A plain
  Task-tool subagent (not Workflow-spawned) instead lands flat at
  `<project>/<session-uuid>/subagents/agent-<id>.jsonl`, one level up — **no `workflows/` segment**.
  Confirmed on `wf_c37ab0b0-dc5` (a real Compound V run, `2026-09-02-df18-direct-digest`), whose
  `journal.jsonl` — `{"type":"started"|"result", "key":..., "agentId":...}` per line — matches
  the spec's item-1 description exactly, and whose per-agent `agent-*.jsonl` / `agent-*.meta.json`
  pairs sit alongside it in the same directory, also matching.
- `agent-<id>.meta.json` — confirmed shape: `{"agentType":"general-purpose","description":"...",
  "toolUseId":"...","parentAgentId":"...","spawnDepth":N}`. The spec's claim ("agentType, model") is
  half right: **no `model` field was found in any `.meta.json` sampled** — model is only visible
  inside the transcript's own assistant messages (`message.model`, e.g. `"claude-sonnet-5"`), never
  in the meta file. A design that reads `.meta.json` for `model` will get nothing.
- **Persistence**: the transcript directory for `wf_c37ab0b0-dc5` (created 2026-09-02) is still
  present today (2026-09-03) even though its git worktree (`.claude/worktrees/wf_c37ab0b0-dc5-1`)
  would have been removed by `finishing-a-development-branch` on merge/discard — the transcript
  store is independent of worktree lifecycle. Good news for "watch after the fact," not just live.
- **Denial text, both channels, confirmed by direct reading of a real transcript, and one channel
  confirmed live against this very agent** (see §0b, Finding 1, and the Matrix above) — this is the
  single most load-bearing verification in this audit, because it directly contradicts the spec's
  parenthetical characterization of the denial text.

## 5. Regression Surface

This is a new, additive, read-only script wired into two existing docs (`v-status.md`,
`v-dispatch.md`) and the version/changelog files. Nothing existing is *modified* in a way that can
regress a currently-working path — but three integration points are worth naming precisely because
getting them wrong degrades existing, currently-reliable behavior:

1. **`v-status.md`'s existing degrade-safe contract.** Step 4's "Liveness (hang detection)" and
   "Usage (measured-only)" sub-sections both carry an explicit rule: *"if the probe errors or is
   missing, show `—` for every row — never break the table."* This is the established house style
   for optional, best-effort columns in this file. If Task B's `--live` wiring does not carry the
   identical degrade-safe framing (script missing, script errors, no transcript found yet), it
   would be the first sub-section in this file to regress that contract — a small thing, but this
   file is explicit and consistent about it everywhere else, and a silent crash on `--live` would
   break the *whole* status render, not just one column, since it is a new top-level flag on the
   command rather than one more table column.
2. **`v-dispatch.md`'s numbered step 6 is already load-bearing and narrowly scoped.** Confirmed by
   reading the file: step 6's actual title is **"Launch it by `scriptPath` — this form is
   mandatory"** — about the one required invocation shape for the native Workflow launch, not about
   post-launch monitoring. Steps 7-9 are integration-gate, review-gate, and hand-off. There is
   **no existing step anywhere in this 9-step list about background monitoring** — the repo's only
   prior art for a background probe (`compound-v-liveness.py`) is invoked from `v-status.md`
   entirely, never from `v-dispatch.md`. Grafting "run `--every 120` in the background… treat two
   signals as a reason to `TaskStop`" onto step 6's existing prose would blur a step whose entire
   current content is the mandatory launch form. The safer target is a **new** step inserted after 6
   (renumbering 7→8, 8→9, 9→10), not an amendment to step 6's own text.
3. **The cwd→worktree collision (§0b) is a LIVE, PRESENT-TENSE hazard for the feature itself, not
   just for the guard.** If the watcher's own job/isolation resolution for a transcript event ever
   falls back to "does this agent's cwd fall under one of the manifest's `write_allowed`/isolation
   assumptions" using the same *shape* of reasoning the lane guard uses (matching a worktree path
   prefix), it will misattribute a direct-mode job exactly as just happened to this audit's own
   write. The spec's design already avoids most of this by resolving jobs from the `--job-id` typed
   into each agent's own `register-lane` command rather than from `lane-map.json`'s `worktrees`
   dict — which is the right call — but design decision #2's discovery step ("the run directory's
   absolute path... carried in every worker prompt's register-lane command") should be read as the
   reason THAT choice is safe, and the plan should say explicitly that it is deliberately NOT reusing
   `lane-map.json`'s cwd→worktree resolution, given what that resolution just did to this very audit.

## 6. DRY Findings

- **No duplicate parser exists.** As established in Phase 3, nothing in this repo currently reads a
  Claude Code subagent transcript (`agent-*.jsonl`); `compound-v-liveness.py` reads only
  `state.json` plus an optional external worker log. This is genuinely new machinery, not a
  candidate for extension.
- **The scope-gate matcher import IS a DRY win the spec already claims correctly** — `is_allowed`
  from `compound-v-scope-check.py`, imported by path exactly as `hooks/lane-guard.sh` already does.
  No third matcher should be written; none is proposed.
- **The YAML loader is a DRY gap the spec does NOT claim, and should.** `compound-v-validate-manifest.py`'s
  `load_yaml()` (with its PyYAML-preferred, subset-parser-fallback machinery) is the ONLY existing
  in-repo way to read `manifest.yaml` without assuming PyYAML is on the invoking interpreter. The
  spec's Global Constraint "Python 3.9 stdlib only" is silent on how `manifest.yaml` gets parsed at
  all — stdlib alone cannot parse it. See Finding 5.
- **The `--json`/`--selftest`/`_render()` CLI conventions of `compound-v-liveness.py` are a style
  precedent worth copying wholesale** (already noted in Phase 3) rather than inventing a new CLI
  idiom for this script.

## 7. Design constraints for the spec (non-negotiable)

0. **The watcher must NOT resolve an agent's job via `lane-map.json`'s `worktrees` cwd→prefix map.**
   Live-confirmed in this very audit (§0b): a `direct`-isolation job's worktree entry is the bare
   repo root, which matches every cwd in the checkout, and the newest such entry on disk silently
   captures every unrelated agent working from the repo root — it just captured this
   code-archaeology task, which has no run directory at all. The spec's own design (resolve by the
   `--job-id` literally typed into each agent's `register-lane` tool_use, scoped per-transcript) is
   the right shape and must not be weakened into reusing this map.
1. **Name the manifest YAML parser explicitly, and it must be `compound-v-validate-manifest.py`'s
   `load_yaml()`, imported by path exactly as `hooks/lane-guard.sh`'s `repo_loader()` does.** "Python
   3.9 stdlib only" cannot parse `manifest.yaml` on its own; the repo already solved exactly this
   problem once, at real cost (the whole viability ladder), and a second, silent solution (or a
   silent crash on any interpreter without PyYAML) is unacceptable. This is the largest
   spec-completeness gap found in this audit alongside Finding 0.
2. **The `denied` signal must match the lane-guard's actual surfaced text, not a literal "DENY."**
   The real strings, both confirmed against real source AND a live deny (§0b), are `"Compound V
   lane guard: job '<job>' is not allowed to write"` (a genuine deny) versus `"Compound V
   lane-guard FAILED OPEN:"` (an allow-with-notice, must NOT be flagged as `denied`). Both differ
   from the harness's own **bashCommandClamp** permission-rule denial text (`"...has been denied:
   this agent's Bash use is clamped..."`), which is unrelated to lanes, routine, and — measured
   directly on one ordinary job's transcript — occurred twice with zero lane-guard denials anywhere
   in that sample. The plan must decide explicitly whether clamp denials are (a) ignored, (b)
   surfaced under a different signal name, or (c) folded into `denied` deliberately — but not
   conflated by accident via a generic substring match.
3. **`register-lane` resolution must use the succeeded call, not the first `tool_use` with that
   name.** Directly observed: the bashCommandClamp frequently forces a first `register-lane`
   attempt (using `"$PWD"`/`&&`) to fail and a corrected, literal-argument retry to follow. Reading
   `--cwd`/`--isolation` off a denied attempt yields an unresolved shell variable, not a real path.
4. **The line-type switch must handle three shapes, not one:** `message.content` as a bare string
   (the transcript's first line), as an array of `tool_use`/`text` objects (assistant lines), and
   as an array of `tool_result` objects (later user lines) — plus `type:"attachment"` lines that
   carry no `message` key at all. A parser written only against the spec's prose description (which
   quotes no raw JSONL) will not anticipate this without being told.
5. **`.meta.json` does not carry `model`.** Confirmed live: only `agentType`, `description`,
   `toolUseId`, `parentAgentId`, `spawnDepth`. If per-tick output wants to show a model, it must
   come from the transcript's own `message.model` field on an assistant line, not the meta file.
6. **Decide the `(unregistered)` policy precisely.** The spec correctly anticipates an agent whose
   writes precede any `register-lane` call, but does not say what "out-of-lane candidate" means
   operationally when there is no `write_allowed` list yet to check a path against. Silence here
   reproduces, in the watcher, the exact ambiguity `hooks/lane-guard.sh`'s own header documents as
   already-known and already-mitigated one way (a deduplicated `lane-guard-unresolved.jsonl` record)
   — the plan should either mirror that mitigation's semantics or explicitly diverge and say why.
7. **`v-dispatch.md`'s wiring is a new step, not an edit to step 6.** Step 6 ("Launch it by
   `scriptPath` — this form is mandatory") is narrowly scoped and already load-bearing; insert the
   `--every 120` / `TaskStop` guidance as its own step, renumbering the steps after it, rather than
   appending to step 6's prose.
8. **`v-status.md`'s `--live` flag needs explicit arg-parsing prose.** The command's current
   Step 1 model is bare `{{args}}` = an optional run-id; there is no existing flag-parsing
   convention in this file to fall back on. The plan must spell out how `--live <run-id>` is
   distinguished from a bare `<run-id>` in `{{args}}`, and the `--live` section must carry the same
   "if the probe errors or is missing, show `—`/skip — never break the render" contract every other
   optional section in this file already carries.
9. **A live capture of an actual `hooks/lane-guard.sh` PreToolUse deny landing inside a subagent's
   own transcript was not found in this audit's transcript sample** (only the hook's *source being
   read* by an agent was found in a transcript, which is unrelated) — though this audit DID trigger
   a real deny against *its own* Write tool call (§0b), confirming the exact reason-string format the
   hook's source predicts. What remains unconfirmed is whether that same JSON payload, when it fires
   inside a *subagent's own* transcript (as opposed to this top-level agent's), is serialized into
   that subagent's `agent-*.jsonl` through the identical `tool_result`/`is_error:true` channel the
   bashCommandClamp denial uses, or through a different channel entirely (e.g. only as
   `additionalContext` prepended to the NEXT turn, never as this tool call's own `tool_result`).
   Treat this as an open verification item before the plan's synthetic test fixtures (built by hand)
   are treated as representative of what a real deny event looks like on disk.

## 8. File Touch Map (for Phase 2 partitioning)

| File | New/Modified | Notes |
|---|---|---|
| `scripts/compound-v-transcript-watch.py` | New | Depends on `compound-v-scope-check.py` (`is_allowed`) and, per Finding 1, must also depend on `compound-v-validate-manifest.py` (`load_yaml`) — both imported by path, per `hooks/lane-guard.sh`'s proven pattern. |
| `tests/test-transcript-watch.sh` | New | Sibling style: `tests/test-lane-guard.sh` (synthetic lane maps + manifests) is the closer precedent than `compound-v-liveness.py`'s Python-only `--selftest`, since this feature needs synthetic **JSONL transcripts**, not just synthetic run-dir files. |
| `commands/v-status.md` | Modified | **SHARED RESOURCE** — a single prose file every `/v:status` invocation reads; already governs Liveness/Usage columns with an explicit degrade-safe contract (Finding 8) that the new `--live` section must match. |
| `commands/v-dispatch.md` | Modified | **SHARED RESOURCE** — a single prose file every dispatch reads; step numbering is load-bearing (steps are cited elsewhere by number, e.g. this very audit's Finding 7); insert a new step rather than editing step 6. |
| `CHANGELOG.md` | Modified | **SHARED RESOURCE** — append-only by convention; current latest entries confirmed at the top of the file (v3.3.x/v3.4.x releases), so a `## [3.4.2]` section is a pure append if ordering is respected. |
| `.claude-plugin/plugin.json` | Modified | **SHARED RESOURCE** — single `"version"` field, currently `"3.4.1"` (confirmed live), read by the harness for plugin identity; must move in lockstep with `marketplace.json`. |
| `.claude-plugin/marketplace.json` | Modified | **SHARED RESOURCE** — mirrors `plugin.json`'s version; the two have desynced before in this project's history, so a partition that lets two different jobs touch these two files independently is a latent-bug risk even though this plan keeps both in one task. |
| `README.md` | Modified | Not shared in the SHARED RESOURCE sense (no other job or script depends on its exact content), but human-facing and low-risk. |
