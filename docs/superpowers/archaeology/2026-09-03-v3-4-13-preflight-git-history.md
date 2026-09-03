# v3.4.13 — Pre-flight Git History Clamp — Code Archaeology

**Spec:** `docs/superpowers/specs/2026-09-03-v3.4.13-preflight-git-history-design.md`
**Target file:** `scripts/compound-v-emit-preflight.py` (568 lines, read in full)

## Step 0 — V-memory recall

Three queries run before any file was opened:

1. `"pre-flight bashCommandClamp git history"` — top hit is the spec itself (expected,
   it is in the index); second hit is `docs/superpowers/memory/triage-outcomes.jsonl`
   recording a **`predicted` / `SCOPED_PIPELINE`** triage verdict for
   `pre_eval_id 2026-09-03T211541Z-let-the-pre-flight-auditors-read-git-history-...-af46`
   at `difficulty_band: medium`, `impact_band: medium` — matches the manifest already on
   disk (see "A plan already exists" below). Third hit,
   `docs/superpowers/research/2026-07-11-git-history-as-complexity-signal.md`, is a
   **different feature** (mining git churn as a Pre-Evaluation complexity signal) — cited
   here only to rule it out: it does not touch `bashCommandClamp` or the pre-flight
   auditors and is not evidence for this spec.
2. `"code archaeologist git log git blame unreachable"` — no hit describes a prior
   incident of the clamp denying `git log`/`git blame`; V-memory returned nothing that
   predates today's spec on this exact failure. The spec's own "Probe" paragraph is the
   only recorded instance.
3. `"compound-v-emit-preflight clamp selftest"` — surfaces the sibling audit
   `docs/superpowers/archaeology/2026-09-03-v3-4-9-preflight-kb-paths-and-retries-schema.md`,
   the last archaeology pass over this same file (added `kb_files` to the schema, touched
   `_selftest` too). Read in full below as the most relevant prior audit.

**No prior archaeology document already covers the clamp list or its two now-fragile
assertions** — this is new ground, not a restatement.

**Directly observed, not inferred:** this very agent invocation is running under a
`bashCommandClamp` that admits only
`Bash(.../compound-v-memory.py search:*)` and `Bash(.../compound-v-memory.py
recall-check:*)`. An attempt to run `ls docs/superpowers/archaeology/` was refused by the
permission system with "this agent's Bash use is clamped to a fixed set of command
forms... Allowed forms: [the two memory.py forms]." This is finding 145 happening live,
not a claim from prose: Phase 1A's own contract (`agents/code-archaeologist.md:52`,
"Repo root path — so you can `grep`, `rg`, `git log`, `git blame`") is currently
unsatisfiable for `git log`/`git blame` when this agent is spawned through the emitted
Workflow pre-flight, and every finding below was produced with `Read`/`Grep`/`Glob`
instead (which are *not* Bash and are unaffected by the clamp) — the one substitute the
current clamp does not offer for history evidence.

**A plan already exists for this spec** —
`docs/superpowers/plans/2026-09-03-v3.4.13-preflight-git-history.md`, with a manifest at
`docs/superpowers/execution/2026-09-03-v3.4.13-preflight-git-history/` in state
`PARTITION_VERIFIED`, jobs `pending` (not yet dispatched — confirmed by reading the
actual `scripts/compound-v-emit-preflight.py` on disk: it still has only the two
`compound-v-memory.py` clamp entries, no git forms). The plan's Step 2 independently
narrows the same two selftest checks this audit identifies below by the same line
numbers and for the same reason. This audit was produced by reading the code, not by
reading that plan first — the agreement is cross-validation, not the source.

## 1. Matrix

Dimensions the code branches on when constructing and applying the clamp:

| `os.path.exists(memory)` | role's `agents/<role>.md` present | `agentType` spawn succeeds | Clamp passed to `agent()` | Git forms reachable (after fix) | Handled today |
|---|---|---|---|---|---|
| true | true | true | full list (2 python forms today → 5 with the fix) | yes | `build_plan` + `opts.bashCommandClamp = CFG.clamp` (`:277`) |
| true | true | false → inline fallback | **same list**, via `Object.assign({}, opts)` then `delete inl.agentType` (`:287-290`) | yes | yes — `inl` is a shallow copy of `opts`, `bashCommandClamp` survives untouched |
| true | false (agent file missing) | n/a — entry marked `skipped`, `agent()` never called | n/a | n/a | yes — the `if e.skipped` branch (`:247-250`) returns before `opts` exists |
| **false** | any | any | `plan["clamp"]` is **`None`**, passed as `bashCommandClamp: null` | **no** — collapses along with the two memory forms | pre-existing behaviour, unguarded — see §5 |

Three phases (1A/1B/1C) share one `plan["clamp"]` value — verified by reading `build_plan`:
`clamp` is computed once (`:196-215`) outside the per-phase loop and returned as a single
top-level key; the JS template reads `CFG.clamp` identically for every entry in
`parallel(CFG.entries.map(...))` (`:277`). The spec's own text ("1A, 1B, 1C share one
clamp") is confirmed true in code, not merely asserted.

**Does 1B or 1C need git access?** `agents/domain-expert.md` and `agents/doc-validator.md`
contain zero mentions of `git`, `git log`, `git blame`, `git show`, or `Bash` (grepped in
full — no matches in either file). Only 1A's contract (`agents/code-archaeologist.md:52,
99`) asks for git history. The fix is necessarily coarse: because the clamp is one shared
value, 1B and 1C receive the same three read-only git forms they never asked for and do
not use. This is not a security gap (read-only, no network, no mutation) but it is a real
over-grant by association that the spec text already acknowledges — flagged here as
confirmed-true, not as something the plan needs to additionally fix.

## 2. Shared State

**`plan["clamp"]` (`scripts/compound-v-emit-preflight.py:196-215`, local to `build_plan`):**
- Set to a 2-element list when `os.path.exists(memory)` is true (memory script present).
- Set to `None` when the memory script is absent.
- No other assignment site in the file. No fallback.
- Consumed once, verbatim, in the emitted JS template's `opts.bashCommandClamp = CFG.clamp`
  (`:277`) — applied unconditionally, unlike the sibling stage-clamp in
  `compound-v-emit-workflow.py:2575` (`if (job.implement_clamp) opts.bashCommandClamp =
  job.implement_clamp;`), which **omits the key entirely** when the value is falsy rather
  than passing `null` explicitly. **Gap, not addressed by this spec:** whether the
  Workflow runtime treats an explicit `bashCommandClamp: null` the same as an omitted key
  is unverified by any tool available to this audit (no access to the runtime internals,
  and the harness's own docs on hand do not state the null-vs-absent distinction). The
  sibling emit-workflow.py script treats a falsy clamp as dangerous enough to actively
  **refuse to launch** an external-backend job rather than let it run with `bashCommandClamp`
  omitted (`compound-v-emit-workflow.py:6284-6410`, the "clampless path is refused"
  invariant, backed by a `ValueError` and a selftest). `compound-v-emit-preflight.py` has
  no equivalent guard: if `compound-v-memory.py` is ever missing from an installation, all
  three auditors get `bashCommandClamp: null` and proceed to spawn anyway — with **whatever
  that null value means** for the Bash tool. If it means "no clamp = unclamped Bash," a
  missing memory script silently grants an auditor a fully open shell (curl, git commit,
  rm -rf, everything) instead of the narrow read-only surface the module docstring claims.
  This is a pre-existing wrinkle, not introduced by this spec, and the spec's own file
  scope ("the clamp list ... and its `--selftest`") does not touch the `if
  os.path.exists(memory) else None` structure — the three new git forms will live inside
  the same conditional and vanish along with the memory forms in the same missing-script
  case. In every real installation `compound-v-memory.py` ships with the plugin (confirmed
  present in this repo), so the practical exposure is low, but the code path is real and
  the plan should know it is not being closed, only inherited.

**Module-docstring and inline-comment claims about the clamp's shape (not a variable, but
asserted-as-fact prose that becomes false the moment the fix lands):**
- `scripts/compound-v-emit-preflight.py:48-49` — "`Bash` goes because nothing in these
  three definitions needs a shell that `Grep`, `Glob` and `Read` do not already give —
  with **ONE exception**, admitted through a clamp: the recall query..."
- `scripts/compound-v-emit-preflight.py:206` — "The **one** shell form an auditor needs,
  and the one its own Step 0 names."
- Both statements are singular ("ONE exception" / "the one shell form"). After the fix
  there are two distinct capabilities behind the clamp (recall query + read-only git
  history) expressed as five literal forms, not one. The spec's stated file scope ("Modify
  `scripts/compound-v-emit-preflight.py` only: the clamp list ... and its `--selftest`")
  does not explicitly authorize touching these two comment blocks. If the plan takes the
  scope literally, these two passages ship provably false the moment the git forms land —
  a future reader (including a future Phase 1A run over this same file) will find prose
  that contradicts the code sitting three lines away from it.

## 3. Sibling Code

**`IMPLEMENT_SHELL`, `scripts/compound-v-emit-workflow.py:224-237`** — the only other
`bashCommandClamp` allowlist in the repo that admits git forms as literal prefixes. Entry
conditions: applied to every `implement`-type job at spawn
(`opts.bashCommandClamp = job.implement_clamp` at `:2575`, gated on truthiness). Inputs:
none beyond the job's own `backend`/worker-script data (clamp construction is independent
of the manifest). Edge cases handled: a job with `isolation: worktree` and an external
backend but **no** resolvable clamp is refused before launch — see `:6284-6410`
("the only clampless path is refused before it can launch"), enforced with a `ValueError`
and asserted by `_check("the one clampless path is refused before it can launch",
_refused)`. **`compound-v-emit-preflight.py` has no analogous refusal** for its own
`None`-clamp case (see §2) — the sibling's safety invariant was not carried over, and the
spec does not ask for it.

The literal forms already established in `IMPLEMENT_SHELL`: `"Bash(git status:*)",
"Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)"` plus `git ls-files`, `git
grep`, `git rm`, `git mv`, `git add`, `git rev-parse` — a **mutation-capable** set (`git
rm`, `git mv`, `git add`) appropriate for an implementer that commits its own worktree.
Confirms the `"Bash(git <verb>:*)"` prefix syntax the new spec proposes is the
established, already-working convention in this codebase (`compound-v-emit-workflow.py`
selftest exercises real clamp strings against this exact syntax, `:6388-6410`). Notably,
`IMPLEMENT_SHELL` does **not** include `git blame` — the new preflight clamp's inclusion
of `git blame` (which `IMPLEMENT_SHELL` lacks) is not an inconsistency to fix; it is a
correct divergence, since only the read-only auditor's contract
(`agents/code-archaeologist.md:99`, "check `git blame` and recent commits") asks for it.

**Known-latent-bug check via `git blame`/`git log` on the sibling:** not performed — this
very audit's own Bash access is clamped to the two `compound-v-memory.py` forms (see Step
0 above), so `git blame` on `IMPLEMENT_SHELL` or its selftest was not possible from inside
this run. Reported as an unknown, not silently skipped: the archaeologist's own contract
forbids "verify later" language, and this is the literal case the spec exists to close.

**Existing tests in `compound-v-emit-preflight.py:_selftest` that assume the clamp is
exactly the two memory forms — these WILL BREAK once git forms are added, unless edited
in the same change:**

1. `:500-502` —
   ```
   check("Bash is clamped to the recall query, not denied outright",
         plan["clamp"] is None
         or all("compound-v-memory.py" in r for r in plan["clamp"]))
   ```
   Once `plan["clamp"]` contains `"Bash(git log:*)"` etc., `"compound-v-memory.py" in r`
   is `False` for those entries and `all(...)` fails. **Confirmed by direct read of the
   assertion, not simulation.**

2. `:506-508` —
   ```
   check("every clamped python command carries -B after the interpreter",
         plan["clamp"] is None
         or all(" -B " in r for r in plan["clamp"]), str(plan["clamp"]))
   ```
   `"Bash(git log:*)"` contains no `" -B "` substring — same failure mode.

Both checks currently pass (verified by reading the current file: the clamp really is
exactly the two `compound-v-memory.py` forms today) and both are **structurally certain**
to fail the instant the clamp list gains any entry that is not a `compound-v-memory.py`
python invocation carrying `-B`. This is the single most concrete, load-bearing finding in
this audit: a naive patch that only appends the three git strings to the list literal
(and adds the two new checks the spec's Acceptance Criteria names) leaves these two
pre-existing checks red. `--selftest` is not advisory here — see §5, it is a CI gate.

## 4. External APIs

None. `compound-v-emit-preflight.py` makes no network calls, no third-party SDK calls, no
HTTP client of any kind (confirmed by reading the file in full — its only I/O is
`open()` on local paths and `subprocess.run([node, "--check", ...])` for the optional
JS-parse selftest check). The three new clamp entries name a local CLI (`git`), not a
third-party API — Phase 4 (Context7) does not apply to this spec.

## 5. Regression Surface

- **`python3 scripts/compound-v-emit-preflight.py --selftest` is a real CI gate, not just
  a local convenience.** `.github/workflows/validate.yml:298-311` dynamically globs every
  `scripts/*.py` that contains the literal string `--selftest` and runs it under Python
  3.9; a `FAIL:` line or non-zero exit fails the job (`rc` tracked, `exit 1` on any
  failure). `compound-v-emit-preflight.py` is one of the discovered scripts (it defines
  `--selftest` at `:369`). **If new code breaks:** the two checks in §3 above go red and
  CI fails on the very commit that is supposed to close finding 145 — not a downstream
  surprise, an immediate build break.
- **Every future brainstorm's Trigger 1 pre-flight** (`skills/compound-v/SKILL.md:89,139`)
  emits its Workflow script from this file. **If new code breaks:** either the script
  fails to emit at all (a `build_plan`/`emit_script` exception), or it emits with a
  clamp that admits more than the three intended git forms — silently widening every
  future pre-flight's Bash surface, exactly the class of bug the spec's second selftest
  check exists to prevent ("no form beginning with `Bash(git ` other than those three").
- **The inline-fallback spawn path** (`:239-243`, `:281-292`, exercised when `agentType`
  registration is stale — the documented dogfood `wf_3b6697df-5e0` incident) inherits
  `bashCommandClamp` via `Object.assign({}, opts)`. **If new code breaks:** whatever the
  primary path grants or omits, the fallback path grants or omits identically — no
  separate regression surface here, confirmed by code read, not assumed.
- **The `None`-clamp fallback for a missing `compound-v-memory.py`** (§2): unaffected by
  this spec either way, since the new forms live inside the same conditional. **If this
  latent gap is ever hit:** all three auditors run with `bashCommandClamp: null` instead
  of a narrow read-only clamp — a correctness question the spec text does not resolve
  and this audit could not resolve either (no access to runtime null-vs-absent semantics).
- **`RESULT_SCHEMA`, `PREFLIGHTS`, `agent_definition()`, `agent_available()`, the
  inline-fallback JS, `kb_files` handling** — none of these read or branch on `clamp`
  except the two consuming sites already covered (`:277` in the JS template, `:500-508`
  in `_selftest`). No other regression surface found in this file.

## 6. DRY Findings

No duplicate to extend or refactor. The only prior appearance of literal `git log`/`git
blame`/`git show`-shaped clamp strings anywhere in the repo (`grep` for
`"git log:\*|git blame:\*|git show:\*"` across all `.py` files) is `IMPLEMENT_SHELL` in
`compound-v-emit-workflow.py:228` — a ~40-entry, mutation-capable allowlist built for a
completely different security posture (an implementer that commits its own worktree).
Extending or importing `IMPLEMENT_SHELL` for the read-only pre-flight clamp would be a
large over-grant (network-adjacent tools, `rm`, `mv`, `chmod`, `git add` all live in that
list) for three agents whose own contracts explicitly renounce write authority
(`compound-v-emit-preflight.py:44-49`, "the authority to mutate anything beyond the audit
goes"). A fresh three-item literal, matching the already-established `"Bash(git
<verb>:*)"` prefix convention, is the correct choice — not a duplication.

## 7. Design constraints for the spec

- **MUST** update the two existing `_selftest` checks at `scripts/compound-v-emit-preflight.py:500-502`
  and `:506-508` in the same change that adds the git forms — both assume every clamp
  entry is a `compound-v-memory.py` python invocation and will fail (not just weaken —
  fail) the instant a `"Bash(git ..." ` string is added to the list. This is stricter than
  the spec's own Acceptance Criteria phrasing ("every other existing selftest check still
  passes") states as a passive requirement — it is an active edit, not a no-op.
- **MUST** verify against the live CI gate, not just local intuition: `--selftest` for
  this file is discovered and run by `.github/workflows/validate.yml:298-311`. A change
  that "looks done" locally but leaves either narrowed check unedited will fail CI on the
  first push.
- **MUST** decide, and state, whether the module docstring (`:48-49`, "ONE exception") and
  the inline comment above the clamp (`:206`, "the one shell form") are edited to stop
  claiming singularity, or left stale with an explicit reason — both are now false claims
  about the code three lines away once the fix lands, and the spec's stated file scope
  does not currently authorize touching them.
- **MUST NOT** widen the shared clamp beyond `git log`, `git blame`, `git show` — no
  `git status`, `git diff`, or any other verb — since the second new selftest check
  (an exhaustive "no other `Bash(git ` form" assertion) is only meaningful if the
  implementation actually stays exhaustive; this is a stricter bar than
  `IMPLEMENT_SHELL`'s negative-list style test (`compound-v-emit-workflow.py:6396-6402`,
  which asserts specific forbidden verbs are absent rather than that nothing outside an
  allowlist is present).
- **SHOULD acknowledge, need not fix:** the `None`-clamp fallback when `compound-v-memory.py`
  is absent (§2) has no equivalent to the sibling's "refuse to launch on a clampless path"
  invariant (`compound-v-emit-workflow.py:6284-6410`). Out of this spec's stated scope
  (it lives outside "the clamp list ... and its `--selftest`" as literally read), but a
  real, uncovered code path that the plan should not describe as closed by this change.
- **SHOULD note for the plan, not fix silently:** 1B (`domain-expert`) and 1C
  (`doc-validator`) receive the same three git forms as 1A despite neither agent
  definition ever mentioning `git` — confirmed harmless (read-only, no network) and
  already implicit in the spec's own "1A, 1B, 1C share one clamp" framing, but worth the
  plan stating explicitly rather than leaving as an unstated side effect.
- **Convention gap worth flagging, not a code constraint:** `CHANGELOG.md` records closed
  finding numbers under `## [Unreleased]` or a release heading (e.g. `[3.4.12]` already
  lists findings 143/144/146/148/151 — not yet 145). The sibling spec v3.4.9's plan
  included a dedicated `changelog` job in its 3-task partition; the v3.4.13 plan on disk
  has only two jobs (`git-history-clamp`, `spec-review-1`) and no `CHANGELOG.md` write.
  Not a code-archaeology defect — `CHANGELOG.md` is documentation, not code the new
  feature reads or branches on — but the plan should state whether finding 145's entry is
  deferred to a later batched release commit or is missing.

## 8. File Touch Map

| File | Touch | Notes |
|---|---|---|
| `scripts/compound-v-emit-preflight.py` | Modify | Sole file the spec's stated scope covers: the `"clamp": (...)` literal (`:212-214`) and the two `_selftest` checks it invalidates (`:500-502`, `:506-508`). Not a generated file, lockfile, type-declaration, or migration/route registry per the SHARED-RESOURCE taxonomy — but it is the single generator every future brainstorm's Trigger 1 pre-flight depends on (`skills/compound-v/SKILL.md:89,139`) and its `--selftest` is a CI-discovered gate (`.github/workflows/validate.yml:298-311`), so a defect here has plugin-wide blast radius even though only one job's `write_allowed` needs to name it. |
| `scripts/compound-v-emit-preflight.py` (docstring prose, `:27-53`, `:206-211`) | Same file, separate concern | Two comment blocks assert "ONE exception" / "the one shell form" — becomes a false claim about the code once git forms land (see §7). Whether this counts as in-scope for "the clamp list ... and its `--selftest`" is for the plan to decide, not this audit. |
| `CHANGELOG.md` | Not in the current plan's `write_allowed` for either job | Repo convention records closed finding numbers here (see §7); flagged, not asserted as required. |
| `docs/superpowers/plans/2026-09-03-v3.4.13-preflight-git-history.md`, `docs/superpowers/execution/2026-09-03-v3.4.13-preflight-git-history/**` | Pre-existing, not produced by this audit | A plan and manifest already exist for this exact spec (state `PARTITION_VERIFIED`, jobs `pending`). Recorded for the record in Step 0; not treated as ground truth by this audit. |

No other file reads, writes, imports, or invokes `build_plan`/`emit_script` from this
module (grepped for `emit_preflight`/`compound_v_emit_preflight` as a Python import
target across `scripts/` — zero hits; every `compound-v-emit-*.py` script is a standalone
CLI, invoked as a subprocess, never imported). The write surface for this feature is a
single file.
