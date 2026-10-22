# v3.4.9 — Pre-flight KB Paths + Retries Schema — Code Archaeology

**Spec audited:** `docs/superpowers/specs/2026-09-03-v3.4.9-preflight-kb-paths-and-retries-schema-design.md`
**Plan already on disk (read for context, not rubber-stamped):** `docs/superpowers/plans/2026-09-03-v3.4.9-preflight-kb-paths-and-retries-schema.md`
**Repo:** `/Users/oleg/Dev/superpowers-v` @ `main` (plugin 3.4.8, per `CHANGELOG.md`)

## Step 0 — V-memory recall

Ran `scripts/compound-v-memory.py search` five times (planning intent): `kb_files` reporting/append,
`retries` schema validation, scope-gate/stash incident, who-commits-the-audits, and git-log-shaped
queries. Every hit that mattered is cited inline below. Two negative results are load-bearing findings
in their own right (§2, §5): a search for "who commits the archaeology/expert/library-audit docs" and
a direct grep for "commit the audit" returned **only this spec and this plan** — no prior doc, ADR, or
dogfood record describes an existing commit step for the pre-flight outputs. V-memory did not
contradict the spec on Part 2 (retries schema) at all — that half checks out cleanly against the code.

## 1. Matrix

Dimensions: **which auditor** (1A/1B/1C) × **file state** (new/untracked vs. append-to-existing/tracked)
× **job isolation mode** (`direct` vs. `worktree`). This is the matrix finding 100 is actually about —
narrower and more specific than "the result doesn't name what it wrote."

| Auditor | KB file naming | Typical file state on a real run | Isolation mode | Protected by `--preexisting`? |
|---|---|---|---|---|
| 1A code-archaeologist | `archaeology/_knowledge-base/<topic-slug>.md` (per-run topic; **no write step exists today**, see §2) | new/untracked (first run for that slug) | `direct` | Yes — untracked files are subtracted (`compound-v-scope-check.py` `--preexisting`) |
| 1B domain-expert | `expert/_knowledge-base/<domain>.md` (`agents/domain-expert.md:146`) | **modified/tracked** — domain names are a small reused vocabulary (`agent-instruction-files.md`, `requirements-elicitation-ux.md`, `software-testing-selection.md`, `preference-modeling-choice-architecture.md`, `autonomous-agent-orchestration.md` — all pre-existing) | `direct` | **No** — `--preexisting` only subtracts untracked/ignored paths (`compound-v-scope-check.py:97-99`); a diff against baseline still shows the modification |
| 1C doc-validator | `library-audit/_knowledge-base/<library-topic>.md` (`agents/doc-validator.md:122-124`, Step 7) | **modified/tracked** — same reason (`claude-code-runtime.md`, `claude-code-hooks.md`, `posix-shell-tooling.md` all pre-existing and repeatedly appended) | `direct` | **No**, same gap |
| any | the dated `wrote` doc itself (`archaeology/`, `expert/`, `library-audit/YYYY-MM-DD-<topic>.md`) | new/untracked on the common case (first pass for that date+slug) | `direct` | Yes |
| any | any of the above | `worktree` | N/A — a worktree is checked out from a pinned ref; an ambient working-tree modification the worktree's own commit predates simply isn't present inside it | Not charged, but also invisible to that job unless separately read |

**Reading the matrix:** the row that actually produced the 2026-09-03 stash incident the spec cites is
row 2/3 — a **KB append to an already-tracked file**, in `direct` mode. Row 1/4 (a brand-new file) was
never the problem; `_preexisting_snapshot()` already handles it with zero code change. The spec's Part 1
probe describes the symptom (the result doesn't name the KB path) without identifying that the
underlying scope-gate mechanism (`--preexisting`) is untracked-only by construction and structurally
cannot forgive a modification to a tracked file — see §5 finding F4.

## 2. Shared State

### `kb_files` (proposed; does not exist in the codebase today)
- Searched the whole repo for the literal string `kb_files`: **zero hits outside the spec and plan
  being audited.** This is a clean greenfield addition — no naming collision, no prior partial
  implementation to reconcile.
- **Set by:** nothing yet. Task A proposes adding it to the emitted auditor prompt (the *one* shared
  template string in `compound-v-emit-preflight.py`'s `_SCRIPT`, used identically for 1A/1B/1C — see
  the `parallel(CFG.entries.map(...))` loop, `scripts/compound-v-emit-preflight.py:236-300`) and to
  `RESULT_SCHEMA["properties"]` (`scripts/compound-v-emit-preflight.py:91-105`).
- **Gap:** `RESULT_SCHEMA` has `"additionalProperties": False` (`scripts/compound-v-emit-preflight.py:93`),
  and the selftest asserts this is load-bearing (`_selftest()`, `check("the schema forbids unknown
  fields", ...)`, line ~499). Adding `kb_files` to the *prompt text* without adding it to
  `RESULT_SCHEMA["properties"]` produces a schema that **rejects the very field being asked for**.
  Task A's own description ("add `kb_files` ... to the structured result") covers both halves in
  prose, but this is exactly the kind of two-place edit that's easy to do in only one place — worth
  stating as an explicit MUST, not an implied one.
- **1A specifically has no KB-write step to produce a `kb_files` value from.** `agents/code-archaeologist.md`
  (my own agent definition — the text baked into this very audit's system prompt) instructs a KB
  **read** at Step 0 ("if any prior archaeology audits in this repo touched the same subsystem, read
  them first") and nothing else; there is no "Step 7 — Update the persistent KB" analog to
  `agents/doc-validator.md:122-139` or `agents/domain-expert.md` lines 140-163. `skills/compound-v/phase-1a-archaeology.md`
  has zero mentions of `_knowledge-base` at all. The spec's own Part 1 probe hedges this
  correctly ("1A **may** create...") but the plan's Task A does not carry that hedge forward — after
  Task A ships, 1A will report `kb_files: []` on essentially every run unless a *separate*,
  currently-unscoped change gives it a write step. Not blocking (an empty array is honest), but the
  plan should say so rather than imply 1A's KB behavior mirrors 1C's.

### `retries[]` (exists; schema at `schemas/job_result.schema.json:219-258`)
- **Set by:** `scripts/compound-v-emit-workflow.py`, in exactly two shapes, both already
  schema-conformant:
  - Plain per-attempt entries via `withRetry()`: `retries.push({ stage: stage, job: jobId,
    attempt: attempt, wait_ms: wait })` (`compound-v-emit-workflow.py:2177`) — 4 keys.
  - The one-time reviewer escalation-lift entry: `{ stage: 'implement', job: job.id, attempt:
    CFG.retry.max_attempts + 1, wait_ms: 0, escalated_from: current, model: next }`
    (`compound-v-emit-workflow.py:2302-2304`) — 6 keys, all schema-declared.
  - Folded into the job result at `compound-v-emit-workflow.py:4276-4282`
    (`result["retries"] = retry_meta["retries"]`).
- **NOT set by** `scripts/compound-v-collect-results.py` at all — grepped the whole file for `retries`
  as a producer/passthrough key: zero hits outside the conformance-check code Task B is extending.
  Task B's write lane (`compound-v-collect-results.py` only) is therefore genuinely isolated from the
  producer; there is no risk of Task B accidentally needing to touch `compound-v-emit-workflow.py` too.
- **Gap the plan targets is real and precisely as described:** `conformance_errors()`
  (`compound-v-collect-results.py:441-500`) checks `retries` generically as `"array" → items must be
  type object` (line 483-489) and never inspects the object's own keys. `_usage_conformance_errors`
  (line 395-438) is the sibling deep-validator, called only for `usage` at line 498-499.

## 3. Sibling Code

**`_usage_conformance_errors(usage, usage_schema)`** — `scripts/compound-v-collect-results.py:395-438`.
This is the function Task B is explicitly modeled on ("validate ... next to the `usage` deep-validation").

- **Entry gate:** called only `if isinstance(result.get("usage"), dict)` (line 498) — a single object,
  not a list.
- **What it checks:** (a) `additionalProperties:false` → any key not in the sub-schema's `properties`
  is a violation; (b) for every key **present in the schema AND present in the payload**, the type is
  checked (null-vs-nullable, bool-is-not-int, etc.).
- **What it deliberately does NOT check, and why that's fine for `usage` but NOT fine for `retries[]`
  as a direct copy:** the loop is `for key, spec in uprops.items(): if key not in usage: continue` —
  a key absent from the payload is silently skipped. This is correct for `usage`, because
  `schemas/job_result.schema.json`'s `usage` sub-schema (lines 183-218) has **no `required` list at
  all** — every usage field is optional by design (the whole object is optional, "omitted entirely
  when the worker provided no usage").
- **`retries[].items` is different: it has `"required": ["stage", "attempt"]`**
  (`schemas/job_result.schema.json:252-255`). A verbatim copy of `_usage_conformance_errors`'s pattern
  has no concept of "required" and will **not** catch a retries item missing `stage` — which is one of
  the four cases the plan's own Task B acceptance text demands ("a good item passes; an unknown key,
  a missing `stage`, a string `attempt` fail"). The new validator needs an explicit required-field
  check `_usage_conformance_errors` never needed. This is the one place a "just copy the sibling"
  approach silently drops a requirement — flagging it so the plan states it as a MUST, not an
  afterthought.
- **Shape mismatch to bridge:** `_usage_conformance_errors` validates one object against one
  sub-schema. `retries` is an array; the new function needs to iterate `result["retries"]`, validate
  each element against `props.get("retries", {}).get("items", {})` (not `props.get("retries", {})`
  directly — the schema nests the object shape one level deeper than `usage` does), and — per the
  plan's own text — prefix each violation with its index, which `_usage_conformance_errors` has no
  precedent for (`usage` violations are named by key alone, never by array position).
- **Downstream effect of a violation (both today's `usage` gate and Task B's new `retries` gate):**
  `main()` at `scripts/compound-v-collect-results.py:1318-1323` — `if errs: ... return 1` — happens
  **before** the result file is written (`out_path` write logic starts at line 1325). A conformance
  violation is a hard fail: no `results/<job-id>.json` is produced at all, not a warning appended to
  one. Verified the live producer (`compound-v-emit-workflow.py`, §2 above) emits only conformant
  shapes today, so Task B does not break anything currently running — but it does mean any *future*
  change to the retry-tracking code that adds or renames a key will now hard-block `collect-results.py`
  for that job unless the schema is updated in lockstep. Worth naming in the plan as a going-forward
  coupling, not a present-day risk.

**No sibling exists for the Part 1 half** (a "commit the pre-flight audits" step) — see §5, this is
itself the central finding.

## 4. External APIs

None. This spec touches zero third-party libraries, SDKs, or hosted APIs — it is two internal,
same-repo mechanical fixes (a JSON result schema field, and a validation function). Phase 1C
(library/doc validator) has nothing to audit here; noting that explicitly rather than leaving it
implied.

## 5. Regression Surface

1. **`scripts/compound-v-emit-preflight.py --selftest`** exercises every auditor prompt and the result
   schema on every pre-flight run system-wide (1A/1B/1C, every feature). If Task A adds `kb_files` to
   the prompt string but not to `RESULT_SCHEMA["properties"]` (§2), the schema starts rejecting a field
   the prompt now asks the agent to return — this would surface as `agent()` structured-result
   validation failing on the **very first** pre-flight run after the change ships, for all three
   auditors, on every feature going forward. High blast radius, one-line fix, easy to catch with the
   selftest **only if** the selftest is updated to assert `kb_files` is in `RESULT_SCHEMA["properties"]`
   too (the plan's existing selftest bullet — "the emitted script text contains `kb_files` in both
   prompts and in the result builder" — checks for the substring in the emitted script text, which
   would catch a schema omission too, since the schema is serialized into the same script via
   `emit_script()`'s `json.dumps(cfg, ...)`; still worth being explicit that this is what makes the
   substring check sufficient).
2. **`scripts/compound-v-collect-results.py --selftest`** currently has 5 usage-shaped checks (lines
   986-1034) plus the top-level conformance suite. Adding `retries[]` deep-validation without adding
   the four parallel checks the plan promises (good/unknown-key/missing-stage/string-attempt) would
   ship an unused, untested code path — not a functional regression, but it defeats the honesty framing
   ("finding 126") the spec itself uses.
3. **`compound-v-integration-gate.py`** and **`compound-v-scope-check.py`**'s `check()` are the actual
   enforcement surface finding 100 is trying to protect against a false BLOCK on. Neither is in this
   plan's Partition Map, and neither needs to be — the fix as scoped (reporting `kb_files`, and
   whatever commits them) works upstream of the gate, not inside it. But if the eventual "commit the
   audits" step is placed somewhere that runs *after* a `direct` job's baseline is already pinned
   (register-lane pins the baseline before the worker launches — `commands/v-dispatch.md`'s Engine C
   changelog, "3. The external worker lost its invocation..." section, and the `--baseline` contract
   documented at `compound-v-scope-check.py:110-113`), the commit arrives too late to help that job
   regardless of what it lists. This is a sequencing constraint the plan should verify against wherever
   it ends up placing the fix (see §7).
4. **The `--preexisting` snapshot mechanism itself is untouched** by anything in scope here, and that's
   correct — it is not broken, it does exactly what its docstring says (`compound-v-scope-check.py:97-99`:
   "drops paths that were ALREADY UNTRACKED/ignored before the job started"). The regression risk is a
   plan author reading finding 100 and concluding `--preexisting` needs to change to also cover tracked
   modifications — it structurally can't (a content-diff mechanism has no notion of "this modification
   predates job X" without a commit boundary), and the only real fix is committing the KB files before
   any direct-mode job's baseline is captured, which is exactly what the spec's Part 1 decision gestures
   at but the plan's Task A locates in a file (`commands/v-dispatch.md`) that has no committing
   machinery for this class of file at all (§ below).
5. **`tests/test-engine-c-contract.sh`**, named in the plan's Task B and AC #3 as a green-bar check,
   contains **zero references** to `retries` or to `compound-v-collect-results.py` (grepped both
   directly). "Stays green" is true trivially — nothing in that file exercises the changed code — and
   should not be read as regression coverage for this change; only the script's own `--selftest` does.

## 6. DRY Findings

**The literal thing Task A asks for — "the step that commits the audits lists these two KB
directories" — does not exist anywhere in `commands/v-dispatch.md`.** Grepped the file for
`archaeology|library-audit|expert/|_knowledge-base` and separately for `Pre-flight|Phase 1`: **zero
matches, all patterns.** The file's 10 numbered steps (`commands/v-dispatch.md:55-186`) start at
manifest validation (Step 1) and run through partition review, engine selection, the git-derived scope
gate, review, and `finishing-a-development-branch` — none of them touch the pre-flight's output files at
all, because by the time `/v:dispatch` runs, Phase 1 (which writes the archaeology/expert/library-audit
docs and their KB files) already finished, in a different command's-worth of the pipeline entirely
(`skills/compound-v/SKILL.md:139`: "After brainstorming produces a spec, BEFORE invoking writing-plans,
run ALL THREE pre-flights"). This is not a stale reference that drifted — a repo-wide search (including
V-memory) for any prior doc describing an existing "commit the audits" step returned only this spec and
this plan. **The plan's Task A instruction to "list the two directories" in that step presumes a step
that must first be authored, not extended** — a materially different (if still small) task than the
spec's "two mechanical fixes with no policy content" framing suggests.

**A closer, better home already exists and does part of both halves of the job:**
`commands/v-orchestrate.md` (not `v-dispatch.md`):
- Step 2 (`commands/v-orchestrate.md:62-66`) *already* extracts "the three audit paths
  (`docs/superpowers/{archaeology,expert,library-audit}/<topic>.md`)" from the plan, by name, as part
  of materializing the manifest — this is the one place in the whole pipeline that already knows these
  paths exist and reads them.
- Step 8 (`commands/v-orchestrate.md:84-89`) *already* has the exact `git add` + `git commit` pattern
  the fix needs — "Commit the run directory... This is not optional. If this run is happening inside a
  git worktree, an *uncommitted* [file] is silently deleted by `git worktree remove`" — currently scoped
  to `manifest.yaml`/`state.json` only, but structurally identical to what committing the audit +
  KB files would look like.
- `v-orchestrate.md` runs **before** `v-dispatch.md`, i.e. before any job's baseline is pinned — which
  is exactly the timing the fix needs (§5 finding 3) and `v-dispatch.md` cannot offer, since dispatch
  starts after materialization.

Whether the plan extends `v-orchestrate.md`'s existing Step 2/Step 8 machinery, authors a genuinely new
step in `v-dispatch.md`, or does something else, is a plan-level decision — not mine to make — but
proceeding with Task A exactly as currently worded (edit a nonexistent step in the file that runs
*after* the timing window that matters) reproduces the DRY failure this phase exists to catch: two
almost-identical audit-path-handling mechanisms would end up living in two different command files, one
of them incomplete.

**No duplicate credential-injection, retry-validation, or KB-write path exists elsewhere** — Task B's
target function (`_usage_conformance_errors`) is the only deep-validator of its kind in the file, and
extending it (rather than writing a third one) is the correct call already implied by the plan.

## 7. Design constraints for the spec

1. **`kb_files` MUST be added to both places in `compound-v-emit-preflight.py`: the shared prompt
   string AND `RESULT_SCHEMA["properties"]`.** The schema has `additionalProperties: False`; adding the
   field to the prompt alone produces a schema that rejects the value being asked for. (§2, §5-1)
2. **The commit step Task A describes does not exist in `commands/v-dispatch.md` today, in any form.**
   The plan must either (a) author it there as new content, explicitly, or (b) relocate the fix to
   `commands/v-orchestrate.md`, which already extracts the three audit paths (Step 2) and already has a
   working `git add`/`git commit` pattern for exactly this class of "new files on disk, not yet in git"
   problem (Step 8) — and which runs *before* any job's baseline is pinned, unlike `v-dispatch.md`.
   Either choice is legitimate; silently treating it as a one-line addition to an existing list is not,
   because no such list exists. (§5-3, §6)
3. **Whatever directory list or path source the commit step ends up using MUST include
   `docs/superpowers/expert/_knowledge-base/**`, not only `archaeology` and `library-audit`.**
   `agents/domain-expert.md:146` gives 1B an explicit KB-append step, evidenced by five-plus existing
   KB files under that path across prior runs; the spec's own Part 1 decision text names only two of
   the three directories. A static two-entry list reproduces the exact scope-gate hazard finding 100
   exists to close, for 1B specifically. Preferring the dynamic `kb_files` values the auditors now
   report over a hardcoded directory list avoids this by construction. (§1, §7-3)
4. **1A's `kb_files` will be empty in practice unless a KB-write step is added to
   `agents/code-archaeologist.md` / `skills/compound-v/phase-1a-archaeology.md`, which this spec does
   not put in scope.** That's an acceptable outcome (an honest empty array), but the plan should say so
   rather than imply parity with 1C. (§2)
5. **The new `retries[]` validator MUST check `required: ["stage", "attempt"]` explicitly** —
   `_usage_conformance_errors`, its named model, has no required-field concept because `usage`'s
   sub-schema declares none. Copying that function's pattern verbatim silently drops the "missing
   `stage` fails" case the plan's own acceptance text demands. (§3)
6. **The new validator must read `props.get("retries", {}).get("items", {})`**, one level deeper than
   `_usage_conformance_errors`'s `props.get("usage", {})`, and must iterate a list rather than validate
   a single object; violations should be indexed, which the sibling has no established convention for.
   (§3)
7. **A conformance violation is a hard, file-blocking failure** (`main()` returns 1 before the result
   JSON is written) — confirm the plan intends `retries[]` violations to behave exactly like `usage`
   violations do today (block the job's result entirely) rather than something softer, since that's
   what "validated ... exactly as it does for `usage`" commits to. (§3, §5-3 note on future coupling)
8. **`tests/test-engine-c-contract.sh` exercises none of this** — do not cite it as coverage for Task B
   beyond "did not regress something unrelated"; the real verification is `compound-v-collect-results.py
   --selftest`. (§5-5)
9. **No schema change is needed.** `schemas/job_result.schema.json`'s `retries[].items` shape
   (`required: ["stage","attempt"]`, typed `wait_ms`/`escalated_from`/`model`) already matches the
   plan's Task B description exactly — confirm the plan does not also touch this file (it isn't in the
   Partition Map, correctly).

## 8. File Touch Map

| File | Role in this change | Notes |
|---|---|---|
| `scripts/compound-v-emit-preflight.py` | Task A — add `kb_files` to prompt + `RESULT_SCHEMA` | Not shared; single-purpose emitter. Selftest lives in the same file. |
| `commands/v-dispatch.md` | Task A — plan's chosen home for the commit-step edit | **Contested**: no existing step to extend (§6). Confirm placement before implementing, or redirect to `commands/v-orchestrate.md`. |
| `commands/v-orchestrate.md` | **Not currently in the Partition Map** but is where the closest existing machinery (Step 2 audit-path extraction, Step 8 commit pattern) already lives | Flagging per §6/§7-2; the plan author should explicitly decide to touch this file or explicitly decide not to, rather than leave it untouched by default. |
| `scripts/compound-v-collect-results.py` | Task B — new `retries[]` deep-validator beside `_usage_conformance_errors` | Not shared; selftest in the same file (`_selftest()`). |
| `schemas/job_result.schema.json` | Read-only reference for Task B (dynamic schema lookup, matching the `usage` pattern) | **SHARED RESOURCE** — canonical cross-adapter contract, consumed by claude/codex/antigravity adapters and multiple scripts. Confirmed no edit needed here; if a future task ever does touch it, treat as high-blast-radius. |
| `CHANGELOG.md` | Task C — two `### Fixed` entries under `[Unreleased]` | **SHARED RESOURCE** — every plan in this repo appends to the same `[Unreleased]` section; currently empty (`CHANGELOG.md:7-9`, next entry is `## [3.4.8]`), so no merge-order conflict exists right now, but this file collects edits from unrelated concurrent work routinely. |
| `agents/code-archaeologist.md`, `agents/domain-expert.md`, `agents/doc-validator.md` | **Not touched by this plan** | Relevant context only (§2, §7-3/4): these define whether `kb_files` is ever non-empty and which KB directories are real. Not asking the plan to touch them — flagging so the omission is a decision, not an oversight. |
