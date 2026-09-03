# Engine C — the execution engine (3.0)

> *"The brakes are not bolted to a different chassis any more. They are bolted to this one,
> and a second set is bolted to the road."*

**Status: primary and default since 3.0.** Engine C is how Compound V jobs execute. It is a
native Claude Code Workflow, generated from the run's `manifest.yaml` by
[`scripts/compound-v-emit-workflow.py`](../../scripts/compound-v-emit-workflow.py) and launched
as `Workflow({ scriptPath: … })`.

---

## This file used to say the opposite, and that reversal is deliberate

In 1.0 this document decided Engine C was an **opt-in accelerator, default OFF**, and stated a
"load-bearing guarantee": that Engine C *"only changes how jobs fan out, never the enforcement
or recovery layer"*, that the scope gate stayed outside it, and that `state.json` resume stayed
outside it.

3.0 reverses the first two. The reasoning behind the 1.0 decision was sound and its conclusion
was wrong, because of what the layer it protected actually was: on the `claude` backend — **73
of 73 recorded jobs** — there was no program running the scope gate. There was a paragraph
telling an agent to run it. Keeping the gate "out of Engine C" kept it in prose.

The reversal, its rationale, and its falsification condition are recorded in
[`adr/0004-workflow-as-the-dispatch-engine.md`](../../docs/superpowers/adr/0004-workflow-as-the-dispatch-engine.md).
Read that before arguing with this file.

**The third-engine idea is also dead.** The 1.0 text implied Compound V might ship three
competing orchestrators. It ships none. The hand-rolled batching, ordering, worktree lifecycle
and concurrency prose that used to live in
[`agents/parallel-dispatcher.md`](../../agents/parallel-dispatcher.md) is **deleted**, not left
beside Engine C — two live paths for one job means the audit trail is written by whichever one
an agent happened to pick.

---

## What the emitted script is

```
export const meta = { name, description, phases };   // FIRST statement, pure literal
…
for each dependency wave:
  phase('Wave N')
  await pipeline(wave, implementStage, gateStage, recordStage)
```

- **`depends_on` → topological waves.** Each wave is a **barrier**, and the barrier is
  load-bearing (see *Ordering*, below).
- **`max_parallel` → chunking** within a wave. Advisory only: the runtime caps concurrent
  `agent()` calls at `min(16, available CPUs − 2)` per workflow, so on a 4-CPU runner the real
  ceiling is 2. Never size a claim on 16.
- **`backend` / `tier` / `effort` / `isolation` → `agent()` options**, read from the manifest and
  never re-decided in the script.

### The three stages

| Stage | Returns | Property that matters |
|---|---|---|
| **Implement** | a raw result — `status`, `worktree`, `summary` | **never a `job_result`.** `job_result` carries `blocked`, `files_changed` and `violations`, which this project's contract says are git-derived by the caller. Asking the implementer to report them is asking the constrained party to fill in its own enforcement fields — the fabricated-evidence pattern with extra steps. |
| **Gate** | a `GATE_VERDICT`, always | **cannot throw** (below). `null` is **FAIL**, never pass. |
| **Record** | a `RECORD_ACK` | **idempotent**, and every commit merged **at most once** (below). |

Every `agent()` call carries `opts.phase`; the global `phase()` is used only at wave boundaries,
because the runtime warns it races inside `pipeline()` stages. `meta.phases[].title` matches the
phase strings exactly, so the native progress tree is populated rather than re-rendered from our
own state after the fact. `log()` narrates each wave.

---

## Three properties that are not optional

### The Gate stage cannot throw

> *"A stage that throws drops that item to `null` and skips its remaining stages."*

So a Gate exception means **Record never runs for that job**: no `state.json` write, no result
file, and the job silently becomes `null` in the results array — precisely on the jobs that went
wrong. That is the v2.6.4 audit-trail loss reappearing structurally.

The emitted Gate wraps everything and returns a verdict for every outcome, *including* "the gate
itself failed". A BLOCKED verdict **returned as a value** is fine and flows to Record; the hazard
is an exception, which is indistinguishable from a clean run at the pipeline level.

Budget exhaustion throws too, which is why the script guards fan-out on `budget.remaining()` and
**stops scheduling** rather than running into the ceiling. `budget` is a **hard** ceiling: once
`spent()` reaches `total`, further `agent()` calls throw. `total` is `null` unless the user set a
`+500k`-style directive, so most runs are uncapped — but where a ceiling exists it is the only
real cost control the runtime offers, and taking it is free.

### `null` is FAIL, never pass

`agent()` returns `null` when it is skipped or dies on a terminal API error. A gate that reads
`null` as "no violations found" is unreachable exactly when the worker died.

### Record is idempotent, and the merge applies a sealed patch

The runtime's resume is **same-session-only** and, past a failure point, **re-runs completed
agents** — so a finished job can implement, gate and record a second time. Idempotence on Record
alone would still leave double commits, double worktree integration and duplicate outcome events.

**The Gate seals what it approved.** `gate-receipt` writes `jobs/<id>.patch` — `git diff --cached
--binary <baseline>` restricted to the paths the scope gate approved — and records that file's
sha256 in its receipt. The wave finalizer applies **that artifact**, never a fresh diff of the
live worktree.

Sealing exists because the fresh diff bound nothing. The digest bound a receipt to a tree at *gate
time*; the merge read the tree at *merge time*, and everything in between rode along:

- a worktree reverted to its baseline after the gate produced an **empty** fresh diff, which the
  finalizer read as "already landed" — the job was marked integrated and its worktree, the only
  copy of the work, was pruned;
- `.pytest_cache/` and friends, written by the test floor that runs *after* the scope check, made
  the authority's re-derivation disagree with an honest receipt and refused it as `contradicted`;
- any post-gate write to an in-lane file landed unmeasured.

**And the finalizer proves the merge from git, before anything is deleted.** After the commit it
applies the artifact to a throwaway index seeded from the baseline, reads the blob ids that
produces, and compares them with `HEAD:<path>`. A job it cannot prove is not pruned and the wave
does not report itself integrated. The same proof replaces the old at-most-once test: a run whose
`state.json` says `merged.integrated: true` is skipped **only** when git agrees the content is in
`HEAD`. `state.json` is exempt by name from the scope gate and writable by a direct worker, so it
is a **cache**, never the authority.

### The manifest is digest-bound

The manifest declares every job's `write_allowed`, and it lives in the run directory the pipeline
exempts by name from the scope gate. A job could therefore widen its own lane map mid-run, and
every later check would run, pass, and prove nothing — it would be checking against the widened
list.

`emit` hashes `manifest.yaml` at generation time and bakes the digest into `CFG.manifest_digest`.
Gate, Record and Finalize each carry it back as `--manifest-digest`, the finalizer forwards it to
[`compound-v-integration-gate.py`](../../scripts/compound-v-integration-gate.py), and all four
refuse on a mismatch. The lane map that is enforced is provably the one that was reviewed.

### Enforcement imports cannot be shadowed

`scripts/` is a directory a job may hold a write lane over, and CPython puts a script's own
directory at `sys.path[0]`. A job that wrote `scripts/yaml.py` had it imported by the very
`import yaml` that loads the manifest declaring that job's lanes. Both
`compound-v-emit-workflow.py` and `compound-v-integration-gate.py` now drop their own directory
and the cwd from `sys.path` **before any other import**, comparing by `realpath` (the script
directory arrives resolved while `__file__` keeps the symlinked spelling — on macOS those differ
for every run under a temp dir, and an `abspath` comparison silently kept the entry).

They also refuse to `importlib`-load a sibling script when the private bytecode-cache directory
cannot be created. Falling back to the default cache location would execute the in-tree
`__pycache__` entry the redirect exists to avoid — and a full or unwritable temp dir is a
condition an attacker can arrange, so the protection had an off switch.

---

## Ordering: commit before the dependent, still

A prerequisite's merge-back only **stages** — `git apply --index` does not commit, so `HEAD` does
not move — and a dependent worktree created at `HEAD` checks out the last *commit*, not the
caller's staged state. **A dependent that runs before its prerequisite is committed does not see
it.** That rule predates Engine C and survives it.

Engine C preserves it structurally rather than by instruction: **the wave barrier is the rule.**
Record commits inside the wave, and the next wave's agents — hence the next wave's worktrees —
are not spawned until the whole wave has resolved. Do not flatten the waves into one `pipeline()`
call to "go wider": `pipeline()` has **no barrier between stages**, and flattening would let a
dependent's worktree be created before its prerequisite's commit exists.

---

## The gate is a stage; the authority is not

The workflow gate is **defence in depth and an early exit**. It is not the authority, and r2 was
wrong to claim it was.

The Gate agent is narrowed at spawn, using two `agent()` options the public tool description does
not mention (found by reading the installed 2.1.238 binary):

- **`disallowedTools`** strips its pool to Bash plus structured output.
- **`bashCommandClamp`** confines its shell to a single command form.

The clamp is genuinely fail-closed: it denies when the permission check crashes, denies commands
whose structure it cannot verify, and **refuses to spawn the agent at all** if it can bind
nothing. Entries are permission rules — `Bash(<command or prefix>)` — and Bash must survive the
`disallowedTools` list, or the clamp binds nothing and the spawn is refused.

**It still cannot be forced to report honestly.** A clamp limits what an agent *can do*, not what
it *returns*; a schema proves shape, not execution. So the authority is
[`scripts/compound-v-integration-gate.py`](../../scripts/compound-v-integration-gate.py), which
verifies or re-derives every receipt before any job commit is integrated:

- receipt missing, `null`, or **partial** → re-derive; that verdict wins;
- receipt present but its bindings disagree with the tree → **refused outright, never re-derived**
  (re-deriving a forgery rewards it with a second chance);
- receipt present and bound, but its **conclusion** disagrees with an independent re-derivation →
  refused as **contradicted** — an honest digest beside a lying `verdict: pass` is exactly the
  "schema-valid PASS having done nothing" a workflow Gate agent can produce;
- no gateable tree, or more than one receipt for a job → fails closed.

The authority also validates the **sealed patch**: where the gate's receipt document records a
`patch_sha256`, `jobs/<id>.patch` must exist and hash to it, or the receipt is refused. That
validation is what lets one honest disagreement stand down: when a worktree job's re-derivation
objects only to paths the sealed artifact does not contain — post-gate test byproducts — the
objection is noted rather than refused, because the finalizer applies the artifact and none of
those paths can reach the project. A violation that *is* in the artifact is still a refusal.

The Gate stage's job is to **produce** that receipt: `baseline_commit`, `realised_commit`,
`diff_digest`, `verdict`, `raw_stdout`, `exit_code`. The `diff_digest` recipe is **pinned** in
[`schemas/job_result.schema.json`](../../schemas/job_result.schema.json) so producer and verifier
cannot diverge; `compound-v-emit-workflow.py` imports the verifier's own function rather than
writing a second one. A partial receipt is emitted as **no receipt**, because a partial receipt is
a missing receipt.

---

## Engine selection — a probe, not a version check

Engine C runs in a **top-level session where a live probe succeeds**.

**The probe spawns a clamped agent.** It does not read a version number. The product claims
workflow support from 2.1.219, but `disallowedTools` and `bashCommandClamp` were found in
2.1.238 — a build that accepts `Workflow` and refuses the clamp would pass a version test, select
Engine C, and then fail to create the Gate agent. `compound-v-emit-workflow.py --engine-probe`
prints the snippet to run.

Environment refusals to check alongside it:

| Variable / setting | Effect |
|---|---|
| `CLAUDE_WORKFLOW_NAME_ONLY` | restricts the session to **named** workflows and refuses `script` / `scriptPath` / `resumeFromRunId` / `remote` — *"Invoke as `{name, args}` only"*. Kills the committed-artefact form. |
| `CLAUDE_CODE_WORKFLOWS=false` | disables the Workflow tool for the session. |
| `CLAUDE_CODE_DISABLE_WORKFLOWS`, managed `disableWorkflows`, `enableWorkflows: false` | disable it too. |

> **Naming correction.** The 3.0 spec and plan attribute the name-only restriction to
> `CLAUDE_CODE_WORKFLOWS`. In 2.1.238 those are two different variables:
> `CLAUDE_CODE_WORKFLOWS` is a boolean availability override, and `CLAUDE_WORKFLOW_NAME_ONLY` is
> the one that refuses `scriptPath`. Both are probed.

**The fallback is justified operationally, and never by the refuted headless claim.** Workflows
**are** available in `claude -p` and in the Agent SDK — an earlier claim in the spec that they are
not is withdrawn; only the `ultracode` keyword is route-restricted. The real reason the residual
subagent path exists is that **a subagent has no Workflow tool**, probed live under both the
public name `Workflow` and the internal `RunWorkflow`. Headless launch additionally needs an allow
rule, auto mode, or a `PreToolUse` hook, and must **never** be armed under `bypassPermissions`,
where a run could start with no prompt and no spend cap.

---

## `scriptPath` is mandatory

The tool's own guidance is *"pass the script inline — do not Write it to a file first"*, which is
the opposite of committing the artefact. `scriptPath` takes documented precedence, so the emitted
script is written into the run directory, committed, and launched by path — otherwise **the
committed artefact is not what ran**.

One consequence worth knowing: the runtime's static determinism check for `Date.now`,
`Math.random` and the argless clock read is applied **only to the inline `script` input**. The
`scriptPath` form skips it and would discover the problem when a global throws mid-run. So the
generator refuses to emit a script containing any of them, and that refusal is the real backstop.

Timestamps arrive via `args`.

---

## The two survivors, neither of which is an engine

- **The verification layer.** The git-derived integration postcondition above, plus `state.json`
  and [`/v:resume`](../../commands/v-resume.md) for cross-session recovery. The native runtime's
  resume is same-session-only and re-runs completed agents past a failure point. This is the
  product, not a fallback.
- **The residual subagent path.** A reduced form of the old loop, retained *only* for contexts
  that physically cannot launch a workflow. See
  [`agents/parallel-dispatcher.md`](../../agents/parallel-dispatcher.md).

---

## Cross-vendor jobs

Codex, Gemini, Cursor and the other external families are OS processes launched by
`scripts/compound-v-run-*-worker.sh`, and a workflow `agent()` has Bash, so the mechanism
survives the move. Three interactions are designed rather than assumed:

1. **The clamp must admit the worker script.** A clamped agent whose clamp does not include
   `scripts/compound-v-run-<backend>-worker.sh` cannot launch the external family at all — and a
   clamp that binds nothing makes the runtime refuse the spawn, so this fails loudly rather than
   degrading. Any job whose `backend` is not `claude` gets the worker invocation in its clamp, or
   **no clamp**.
2. **The lane-guard `PreToolUse` hook matches `Bash` and must not deny that invocation.** It also
   must not try to police what the external process writes: that happens in a separate process, in
   its own worktree, outside any hook this session controls. Those writes are covered as they are
   today — by the worker script calling the scope gate itself, and by the integration
   postcondition.
3. **No nested worktrees.** The worker creates and owns its own worktree, and this repository
   already carries a downstream incident from getting that wrong. **Non-`claude` jobs run their
   workflow agent at `isolation: 'direct'`**, letting the worker script own the isolation exactly
   as it does today.

The arbiter's own logic — a second, genuinely different model family, the frozen audit, the
confirmed-blocker bar — is untouched: none of it lives in the dispatch loop.

---

## Version floor

**Claude Code ≥ 2.1.219.** The `/workflow-authoring` skill requires 2.1.248 and is unavailable on
the development machine, so nothing here depends on it.
