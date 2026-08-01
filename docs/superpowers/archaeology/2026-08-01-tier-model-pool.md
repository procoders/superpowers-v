# Tier Model Pools — Code Archaeology (Phase 1A)

**Spec audited:** `docs/superpowers/specs/2026-08-01-tier-model-pool-design.md` (branch `feat/tier-model-pool`, commit `a017aec`, the branch's only change vs `main`).
**Method:** every claim below was read out of the file at the cited line, or reproduced by running the script. Nothing is from memory.
**Legend:** **[C]** = CONFIRMED by reading the cited line or by a reproduced run. **[I]** = INFERRED (a consequence I reasoned to, not something the code states).

---

## 0. Two things the spec asserts that are not true today

Stated up front because they invalidate parts of §2, §3 and §5 of the spec.

**(a) "The dispatcher already knows which backends are available (env-aware routing, `/v:init`)."** — spec §Risks, line 129.
**[C] There is no availability list in `.claude/compound-v.json`.** `commands/v-init.md:507` says verbatim: *"Do not add a `backends` or `checked_at` field here; they were removed in v2.6.2 for exactly this reason."* Availability lives in the **uncommitted, user-home** cache `~/.claude/compound-v-capabilities.json` (`commands/v-init.md:652-681`). The **only** machine-readable consumer of that file in the whole repo is `scripts/compound-v-epic-arbiter.py:517-525` (`load_capabilities`), which exposes exactly two strict-identity predicates — `codex_available` (`:529-536`, double gate on `available` **and** `exec_flags_verified`) and `agy_available` (`:539-548`). **There is no `available(backend)` function for cursor / devin / opencode**, and none for a future `zai`. So AC-5 ("an unavailable member is filtered before the counter") has no existing mechanism to call.

**(b) "`zai` defaults to 4, per its adapter."** — spec §5, line 113.
**[C] That number is prose on a different branch.** `git show feat/zai-backend:skills/backend-launcher/adapter-zai.md` line 112 reads *"Default `max_parallel` for zai is **4** — below the measured ceiling."* It is a doc recommendation with **no consuming code**. Also **[C]** the spec's own cross-reference link the spec's link to the zai design doc (spec line 16) is **dead on this branch** — `docs/superpowers/specs/2026-07-31-zai-backend-design.md` does not exist here; it exists only on `feat/zai-backend`.

---

## 1. Matrix

### 1a. Dimensions the resolver branches by

`scripts/compound-v-resolve-model.py:247` — `resolve(backend, tier, effort, config_models, explicit_model, stance, job_type, fast_path)`.

| Dimension | Values | Site | New pool code must handle? |
|---|---|---|---|
| `backend` | 6: claude, codex, antigravity, cursor, devin, opencode | `:144` `BACKENDS`; enforced `:254-255` | **YES** — `pool` is a 7th token that is *not* a backend |
| `tier` | 3: deep, standard, light | `:145` `TIERS`; enforced `:256-257` | YES — pools are tier-keyed; spec ships `standard`+`light` only |
| `effort` | 4: low, medium, high, **xhigh** | `:150`; `xhigh` gated to codex at `:260-264` | **YES** — see 1c |
| `stance` | 4: balanced, conservative, cost-aware, claude-only | `:153`; enforced `:265-266` | YES — `pools.<stance>.<tier>` |
| config shape | 2: per-stance **or** legacy flat, auto-detected | `:222` `all(k in VALID_STANCES for k in keys)` | **YES** — see 3a, this is a live bug |
| `explicit_model` | present / absent | `:270-283` short-circuit | YES — precedence vs pool undefined in the spec |
| `job_type` | present / absent | `:279-282`, `:304-307` — adds `advisor_eligible` | YES — see 1d |

### 1b. Backend × pool-membership cells the new code must survive

Only the 4 backends whose `isolation` is unconstrained-vs-forced actually differ. `claude` is the only one that can be `direct` today.

| Member backend | worktree forced today? | site | Under `backend: pool` (spec §4 forces worktree) |
|---|---|---|---|
| claude | **no** — may be `direct` | `validate-manifest.py:1817` (claude absent from the tuple) | changes: a claude pool member now always pays for a worktree |
| codex | yes | `:1817` | unchanged |
| antigravity | yes | `:1817` | unchanged |
| cursor | yes | `:1817` | unchanged |
| devin | yes + **reviewer-forbidden** | `:1817`, `:1833-1841` | reviewer ban **silently bypassed** — see 2c |
| opencode | yes + **provider/model shape check** | `:1817`, `:1852-1864` | manifest-side shape check **structurally unreachable** — see 2e |

### 1c. `effort` × `backend: pool` — a 2×2 nobody has specified

| effort | backend in manifest | today | with `backend: pool` |
|---|---|---|---|
| `xhigh` | `codex` | accepted (`validate-manifest.py:1790-1796`) | **[C]** rejected, because `str(job.get("backend")).lower() != "codex"` — `"pool" != "codex"`. Fail-closed, but it means **no pool job can ever carry `xhigh`**, even a pool whose only member is codex. |
| `xhigh` | non-codex | rejected with the rule named | same |
| `low/medium/high` | any | accepted | accepted |
| `xhigh` | pool resolving **to** codex | n/a | **undefined.** `resolve()` raises at `:260-264` if the resolved backend is not codex; the spec never says whether effort is validated against `pool` or against the resolved member. |

### 1d. `advisor_eligible` × `backend: pool` — the 4 cells

`resolve-model.py:348-362`, mirrored byte-for-intent at `validate-manifest.py:599-613`.

| tier | fast_path | backend | today | with `pool` |
|---|---|---|---|---|
| standard | false | any | **True** (`:361`, tier check ignores backend) | **True** — a pool job IS advisor-eligible **[C]** |
| light | true | claude | True (`:358-359`) | **False** — `b == "claude"` fails when `b == "pool"` **[C]** |
| light | true | pool→claude | n/a | **False at validation time, True in reality.** The manifest says `pool`; the resolved member is claude. **[I]** the two disagree. |
| deep | false | any | False | n/a (spec: no `deep` pools) |

**[C]** `resolve-model.py:395` restricts the `--advisor-eligible` CLI's `--backend` to `choices=list(BACKENDS)`; `--backend pool` exits **2** with an argparse usage dump, not a clean JSON error. Reproduced.

---

## 2. Shared state — every site that keys off the backend string

One block per site. All line numbers are `scripts/compound-v-validate-manifest.py` unless stated.

### 2a. `VALID_BACKENDS` (`:519`)
```python
VALID_BACKENDS = ("claude", "codex", "antigravity", "cursor", "devin", "opencode")
```
Consumed at **three** sites, not one:
- `:1733` — the per-job `backend` enum check.
- `:664` — the **`advisor.advisor_backend`** check. Adding `pool` to `VALID_BACKENDS` would make `advisor: {advisor_backend: pool}` legal, which is nonsense (an advisor must resolve to one concrete consultable backend; `resolve-model.py:345` `ADVISOR_CONSULTABLE_NONCLAUDE = ("codex",)`).
- `:1736`/`:667` — both error messages join it into user-facing text, so adding `pool` changes both messages.

**What `pool` must do here:** it must **not** join `VALID_BACKENDS`. It needs its own token (`POOL_BACKEND = "pool"`) accepted only at `:1733`, and explicitly excluded at `:664`.

### 2b. The worktree invariant tuple (`:1816-1823`)
```python
backend_lc = str(job.get("backend", "")).lower()
if backend_lc in ("codex", "antigravity", "cursor", "devin", "opencode"):
    if str(job.get("isolation", "")).lower() != "worktree":
```
**[C]** `"pool"` is not in the tuple ⇒ **a `backend: pool` + `isolation: direct` job passes this check today.** Spec §4/AC-2 requires the opposite.
**What `pool` must do:** add a separate branch `if backend_lc == "pool" and isolation != "worktree"` with its **own** message (the current message interpolates `backend_lc` twice — *"job 'x' uses backend pool but isolation is 'direct' (pool requires worktree)"* is confusing since pool is not a backend). Note the existing `parallel ⇒ worktree` rule at `:1756-1762` already forces worktree for every `run: parallel` job, so the pool rule only bites on `run: serial` pool jobs.

### 2c. The reviewer WORKER-ONLY prohibition (`:1833-1841`)
```python
if _is_reviewer(job) and backend_lc in ("devin", "opencode"):
```
**[C] A reviewer job with `backend: pool` bypasses this entirely** — `backend_lc == "pool"`. If the pool contains `devin` or `opencode`, a reviewer lands on a lower-trust multi-provider broker, defeating the guarantee the check exists to protect. Spec §What-does-not-change says *"`backend: pool` on a reviewer job is rejected"* but assigns no site.
`_is_reviewer` (`:563-570`) matches substrings `("review","reviewer","spec_review","quality","integration")` against **`type` OR `id` OR `title`** — so the check is broad and cheap to reuse.
**What `pool` must do:** a new unconditional check `if _is_reviewer(job) and backend_lc == "pool"` → violation, placed **before** the `:1866-1876` reviewers⇒deep/opus check.

### 2d. The reviewers ⇒ deep/opus check (`:1866-1876`)
```python
is_deep = str(job.get("tier","")).lower() == "deep"
is_opus = str(job.get("model","")).lower() == "opus"
```
**[C]** Backend-agnostic, so a `backend: pool` + `tier: deep` reviewer **passes** this check. Combined with 2c, that is the exact hole: the manifest looks compliant, the dispatched worker is whatever the counter picked. This is why 2c must be unconditional and not a sub-clause of the deep/opus rule.

### 2e. The opencode `provider/model` shape check (`:1852-1864`)
```python
if backend_lc == "opencode" and "model" in job:
```
**[C]** Two-way miss for pools. (i) `backend_lc == "pool"` never triggers it. (ii) a pool job **must not** carry a manifest `model` key at all (the pool supplies the model), so the `"model" in job` guard is false regardless.
**Mitigation that already exists:** `resolve-model.py:295-301` shape-checks **at resolution time** whenever `backend == "opencode"`, including the config-cell path. **[I]** So if the pool lookup routes each member through `resolve(member.backend, tier, ...)` rather than reading the pool entry's `model` directly, opencode shape enforcement is preserved. If it reads the entry's `model` field and hands it straight to the launcher, it is lost.
**What `pool` must do:** the spec must state that a pool member is resolved through `resolve()` with `explicit_model=entry.model`, not bypassed — and note that `resolve()`'s `explicit_model` path **does** shape-check opencode (`:271-277`).

### 2f. never-Haiku, execution layer (`:1721-1727`)
```python
model_raw = job.get("model")
if model_raw is not None and "haiku" in str(model_raw).lower():
```
**[C]** This is the **only** haiku gate on the execution path. `resolve()` has **no** haiku check anywhere; `resolve-model.py:586-587` only asserts no haiku in the **built-in** `DEFAULT_MODELS_BY_STANCE`, inside `_selftest`, never at runtime. A `models.<stance>.<backend>.<tier>` config override containing `haiku` resolves silently today.
**[I] The pool makes this hole structural rather than incidental.** A pool-routed job has **no** manifest `model` key by construction, so `:1721` can never fire for it; every pool-routed model comes from an unchecked config cell. The spec's Non-goal *"No change to the never-Haiku policy in either direction"* is not neutral here — it converts an opt-in hole (operator hand-edits the models map) into the default path for every pooled job. Never-Haiku is a hard project invariant (`CLAUDE.md`; `scripts/lint-frontmatter.py`; `.github/workflows/validate.yml:118`).

### 2g. `circuit_open[<job.backend>]` — check-before-launch
`agents/parallel-dispatcher.md:199`: *"Before dispatching each job in a batch, check `circuit_open[<job.backend>]`; if it is open, do NOT launch the job."*
**[C]** For a pool job `job.backend` is the literal string `pool`. `circuit_open` is keyed by real backend (`skills/compound-v/state-machine.md:180`). **A pool job therefore never sees any breaker** and will happily launch onto an out-of-credits backend.
**What `pool` must do:** the check must read `state.json jobs[<id>].assigned_backend`, and — because the assignment is made *at dispatch* — the breaker must be consulted **while choosing the member**, i.e. an open-breaker member is filtered out of the pool exactly like an unavailable one.

### 2h. `cooldowns[<backend>]`
`state-machine.md:179` — keyed by **backend**, not by job. **[I]** A pool re-assignment does not clear a cooldown; and a pool member under cooldown is currently invisible to the counter. Same filtering requirement as 2g.

### 2i. `attempts[<job>][<failure_class>]`
`state-machine.md:178`, verbatim: *"reset/fork the counter when the job is re-routed to a different backend or the class changes."*
**[I] Double-counting risk, quantified.** `PER_CLASS_MAX["rate_limited"] = 3` (`scripts/compound-v-failure-policy.py:49`). If clearing the assignment counts as "re-routed to a different backend", a 3-member pool gives a single job **3 × 3 = 9** rate-limit retries instead of 3, bounded only by the run-wide `max_total_retries` (default 12, `state-machine.md:182`). Two pool jobs failing this way exhaust the run budget. The spec's §3 exception clause does not say whether the counter resets.

### 2j. `FALLBACK` in the failure policy (`scripts/compound-v-failure-policy.py:59`)
```python
FALLBACK = {"codex": "claude", "antigravity": "claude", "cursor": "claude", "claude": None}
```
**[C] Pre-existing latent bug, independent of this spec:** `devin` and `opencode` — both shipped, both in `VALID_BACKENDS` — are **absent**. `FALLBACK.get("devin")` is `None`, so an `out_of_credits` on devin takes the `:98-100` path and **halts** with *"the fallback (none) is unavailable too"* instead of rerouting to claude. `zai` would land in the same hole.
**[C] For pools:** `FALLBACK.get("pool")` is also `None` ⇒ every pool-job credit exhaustion halts the run. The policy must be called with the **assigned** backend.

### 2k. `--backend` argparse choices in the classifier (`scripts/compound-v-classify-failure.py:334`)
```python
p.add_argument("--backend", choices=["codex", "claude", "antigravity", "cursor"])
```
**[C]** Another pre-existing gap: `devin` and `opencode` are already rejected here, so `parallel-dispatcher.md:165`'s `--backend "$BACKEND"` call **exits 2** for a devin/opencode job today. `pool` would too. Must be passed the assigned backend, and the choices list needs the missing backends.

### 2l. `select_advisor(executor_backend, ...)` (`resolve-model.py:365-382`)
**[C]** Reproduced: `--select-advisor --executor pool --available codex,claude` returns `{"advisor_backend": "codex", ...}`, exit 0 — no validation, because `--executor` has no `choices` (`:414-415`). If the pool assigned this job to **codex**, the advisor is same-brand codex, silently defeating the cross-brand guarantee at `:376-379` (`cand != exec_b`).
**[I]** `scripts/compound-v-advisor-consult.sh:154` passes `--executor "$EXECUTOR"` straight through. The dispatcher must pass the **assigned** backend as `--executor`.
Separately, `parallel-dispatcher.md:117` gates the advisor block on *"the job is a `claude` executor"* — for a pool job that is only knowable post-assignment.

### 2m. `resolve()` / `select_advisor()` purity — where a counter may legally live
**[C] `resolve()` is pure today** — no I/O beyond `load_config_models` (a caller-supplied path), no module-level mutable state, no randomness. Its only self-call is `select_advisor` → `resolve(cand, "deep", stance=stance)` at `:378`.
**[C] Every production caller runs it as a fresh subprocess.** `agents/parallel-dispatcher.md:95`: `RESOLVED=$(python3 scripts/compound-v-resolve-model.py "$@")`; `commands/v-status.md:30` does the same for display; `scripts/compound-v-advisor-consult.sh:149,154` likewise. The single in-process caller is `validate-manifest.py:932` via `_sibling` (`:916`).
**[I] Therefore a round-robin counter cannot live inside `resolve()` or inside the resolver process at all** — it would reset on every invocation and produce member 0 for every job. Legal homes, in order of fit:
1. **`state.json` itself**, as a run-level `pool_cursor: {"<tier>": n}` map written by the dispatcher at the same moment it writes `assigned_backend` — same writer, same file, same crash-consistency story as `attempts`/`cooldowns`.
2. **Derived, not stored:** `n` = count of jobs in `state.json.jobs` that already carry an `assigned_backend` **and** whose manifest entry is `backend: pool` **and** same tier. This is stateless, crash-proof, and reproduces AC-4 exactly — but only if dispatch order is deterministic (see 5b).
3. A new `resolve_pool(tier, n, ...)` **pure** function in `resolve-model.py` that takes `n` as an argument and never owns it. This keeps `resolve()` pure and testable; the dispatcher owns `n`.
**Not legal:** a module global, a temp file, or an env var — none survive the subprocess boundary or a crash.

### 2n. `advisor_eligible` / `select_advisor` / `--select-advisor` — direct impact summary
- `advisor_eligible(...)`: **affected**. `backend="pool"` breaks the fast-path branch (`:358-359`) and its validator mirror (`:609-610`). The standard-tier branch (`:361`) is backend-blind, so it still returns True — meaning validation and reality can disagree (1d row 3).
- `select_advisor(...)`: **affected** via the executor argument (2l). The function body itself needs no change.
- `--select-advisor` CLI: **affected only at the call site** — it accepts `pool` silently today.
- `--advisor-eligible` CLI: **affected** — `--backend pool` is an argparse error (`:395`).

---

## 3. Sibling code — read in full

### 3a. `_config_cell` (`resolve-model.py:214-231`) — the sibling the pool lookup mirrors, and its live bug

```python
keys = list(config_models.keys())
if keys and all(k in VALID_STANCES for k in keys):    # per-stance shape
    stance_cfg = config_models.get(stance)
    backend_map = stance_cfg.get(backend) if isinstance(stance_cfg, dict) else None
else:                                                  # legacy flat shape
    backend_map = config_models.get(backend)
```

**Entry condition:** any non-empty `config_models`. **Discriminator:** *"is every top-level key a stance name?"* — a heuristic, not a declared version field.

**[C] LATENT BUG, reproduced live.** `scripts/compound-v-discover-models.py:122-139` (`write_config`) merges with `models[backend] = tier_map` — the **flat** shape — into a config whose `models` is per-stance. One backend key among the stance keys flips the discriminator at `:222` to the legacy branch, and **every per-stance override in the file silently stops applying**. Reproduction:

```
config models keys before: ['balanced', 'cost-aware']
  codex/deep/balanced  -> MY-PINNED-DEEP           (config override honored)
$ printf '...' | compound-v-discover-models.py --backend antigravity --write-config <cfg>
config models keys after:  ['balanced', 'cost-aware', 'antigravity']
  codex/deep/balanced  -> gpt-5.6-sol              (built-in default; override GONE)
  antigravity/deep     -> Gemini 3.1 Pro (High)    (the only cell still read)
```

This fires on the documented `/v:models` flow (`commands/v-models.md:125-126`, `commands/v-init.md:79-81`) — i.e. the normal way an operator refreshes antigravity models silently disables their whole model map. It is **not caused by** this spec, but it is the exact failure mode the pool inherits if `pools` copies the same auto-detect heuristic.

**What the spec must do:** `pools` must be **per-stance only** — no legacy-flat variant, no auto-detection — because a pool entry has a `backend` field and a flat `pools.<tier>` vs per-stance `pools.<stance>.<tier>` cannot be told apart by key inspection. And the spec should say whether it repairs `write_config` or leaves the bug (leaving it means a `/v:models` run can silently blank a pool the operator just configured, if pools ever share the discriminator).

### 3b. `load_project_config` (`scripts/compound-v-project-config.py:93-111`) — the fail-closed structural gate

Checks exactly three keys are objects-if-present: `models` (`:102-104`), `pre_eval` (`:105-107`), `brainstorm` (`:108-110`). **[C] An unknown top-level key like `pools` or `backend_max_parallel` is passed through untouched and unvalidated.** `get_models` (`:114-128`) reads only `models`.
**What `pool` must do:** add `pools` (and `backend_max_parallel`) to the structural check at `:102-110`, and add a `get_pools(cfg)` sibling to `get_models`, so both the resolver and any other consumer share one verdict. The house rule is stated at `project-config.py:5-9`: *"both the resolver and the pre-eval engine must read the SAME file with the SAME rules — so the loader lives here once."*
**Per-key rules:** the module's established split is structural→raise, per-key→coerce+warn (`:16-23`). An unparseable **pool entry** (missing `backend`, unknown `backend`, empty `model`) is a per-key problem: **[I]** it should be dropped with a warning and leave a shorter pool, matching how `remember` drops invalid entries at `:177-190` — not raise, and not fail the run.

### 3c. `_review_resolution` (`validate-manifest.py:894-946`) — the precedent for validator-side config reads

Loads the sibling resolver by path (`_sibling`, `:916`), locates the config (`:921-924`, defaulting to `<repo_root>/.claude/compound-v.json`), calls `rm.load_config_models` (`:926`), then `rm.resolve(...)` in-process (`:931-936`), and **fails closed** on every error path (`:917-920`, `:927-930`, `:937-940`).
**[I]** This is the exact mechanism a validator-side "does this tier actually have a pool?" check would use — the wiring already exists, including the `--config` / `--repo-root` flags. Note the cost: it makes pool validation **config-dependent**, so `compound-v-validate-manifest.py <manifest>` with no `--config` cannot check pool existence. The spec must decide: silent skip (like today's mode-less legacy path) or fail-closed.

### 3d. `parallel-dispatcher.md` Step 2 §1 (`:80-105`) — where routing is resolved today

Reads `$BACKEND` and `$TIER` **from the manifest job entry** (`:80`), builds the resolver flag list (`:91-94`), runs the resolver (`:95`), extracts `model`/`effort` (`:96-97`). Then per-backend branches at `:100` (claude), `:101-102` (codex, incl. session capture), `:103` (antigravity), `:104` (cursor). **[C] `devin` and `opencode` have no branch here** — another pre-existing gap; the backend→adapter table at `:48-53` also omits both, though `skills/backend-launcher/SKILL.md:120-121` documents their adapters.
**[C] The batch announcement at `:70-78`** prints `backend · model (tier/effort) · isolation` before dispatch and states *"Always show the **resolved** model … never the bare tier or a placeholder."* For a pool job the announced backend must be the **assigned** one, or the human sees `pool · ?`.
**Known latent bug in this sibling, inherited:** the constraint at `:377` — *"DO NOT re-decide backend / tier / isolation — they come from the manifest"* — is exactly what a pool violates. The spec must amend that sentence, not work around it.

### 3e. `commands/v-status.md:30` — will break outright on a pool manifest

> *"resolve the concrete **model** it runs on with `scripts/compound-v-resolve-model.py` — `--backend <job.backend> --tier <job.tier> …`"*

**[C]** `--backend` is `choices=list(BACKENDS)` (`resolve-model.py:438`). Reproduced: `--backend pool` exits **2** with an argparse usage dump. `/v:status` on a pool run therefore renders a broken `Backend · Model` column unless it reads `assigned_backend`/`assigned_model` first and only falls back to the resolver for non-pool jobs.

---

## 4. External APIs

**[C] None.** This feature touches no third-party API. The whole change is Python 3.9 stdlib (`resolve-model.py:54`, `project-config.py:25`), a JSON config file, a YAML manifest, and `state.json`. `mcp__context7__*` was deliberately not invoked — there is no library to validate. The only "external" surface is the **CLI contract of the sibling scripts**, which is audited above from the source rather than from docs.

One version-adjacent note **[C]**: CI runs every `--selftest` under a **Python 3.9 floor** (`.github/workflows/validate.yml:242-280`, dynamic discovery at `:272`). Any pool code must be 3.9-safe — no `match`, no `X | Y` unions, per the house rule at `resolve-model.py:54`.

---

## 5. Regression surface

### 5a. Every path that works today and could break

| Path | Site | If pool code misbehaves |
|---|---|---|
| Non-pool manifests validate | `validate-manifest.py:1729-1737` | Adding `pool` to `VALID_BACKENDS` makes `advisor_backend: pool` legal (`:664`) — a nonsense advisor passes the gate. |
| `/v:status` per-job model column | `v-status.md:30` | **[C]** exits 2 on any pool job; the whole table degrades. |
| Circuit-breaker check-before-launch | `parallel-dispatcher.md:199` | **[C]** pool jobs launch onto out-of-credits backends; the run burns retries against a dead provider. |
| `out_of_credits` reroute | `failure-policy.py:90-100` | **[C]** `FALLBACK.get("pool") is None` ⇒ every pool credit-exhaustion halts the run instead of rerouting. |
| Failure classification | `classify-failure.py:334` | **[C]** `--backend pool` exits 2 ⇒ the classify→decide→act loop (`parallel-dispatcher.md:162-167`) dies mid-failure-handling. |
| Reviewer trust guarantee | `validate-manifest.py:1833-1841` | **[C]** a pooled reviewer can land on devin/opencode; the Review Gate's opus guarantee becomes false while the manifest still validates. |
| never-Haiku | `validate-manifest.py:1721-1727` | **[I]** a haiku string in a pool entry reaches a worker with no gate anywhere. |
| Advisor cross-brand guarantee | `resolve-model.py:376-379` | **[C]** same-brand advisor when the pool assigns codex. |
| `git worktree` disk/time cost | `execution-manifest.md:42`, `parallel-dispatcher.md:108` | **[I]** forcing worktree on claude pool members adds one `git worktree add` + `git apply --index` + `git worktree remove` per job; on an 8-job run that is 8 extra worktrees where 0 were needed. |
| Scorecard routing signal | `scripts/compound-v-scorecard.py:75-77` (`key = (backend, type)`), `compound-v-update-memory.py:106` | **[I]** if the dispatcher records `backend: "pool"` in `task-outcomes.jsonl`, every pool job collapses into one bogus `("pool", type)` row and the per-backend health signal `routing-policy.md:387` reads is destroyed. Must record the **assigned** backend. |
| Usage aggregation | `usage-extract.py:56-58` `UNMEASURED_BACKENDS` | **[I]** `"pool"` is not in the frozenset, so it would take the *measured* branch and try to parse an events log that may not exist for a claude-assigned member. |
| Liveness sweep | `liveness.py:154-157` | **[C]** reads only `worktree`/`baseline`/`pid`/`log` — **unaffected**, degrade-safe. |
| Dashboard | `dashboard.py:279-345` | **[C]** reads `phase`, `jobs[].status` only — **unaffected**; it will simply not show the assignment. |
| Existing selftests | `validate.yml:266-280` | AC-1 requires all pass unchanged. `resolve-model.py --selftest` has 90+ cases including `"no haiku in any stance map"` (`:586-587`) and `"resolve without job_type has NO advisor_eligible key"` (`:745-746`) — the additive-key discipline is already asserted. |

### 5b. Determinism risk behind AC-4

AC-4 requires the sequence `0,1,2,0,1,2` *"asserted deterministically, with no randomness anywhere."*
**[C]** Dispatch order today is *"Group `run: parallel` jobs into batches of 4-6 max per message"* (`parallel-dispatcher.md:66`) — an **LLM agent** decides batch composition, constrained only by `depends_on` and `max_parallel`. Nothing in the repo pins job order. **[I]** So "dispatch order" is not a deterministic input, and a testable AC-4 must be defined against a fixed order — the manifest's `jobs[]` list order is the only stable candidate. The spec must say so explicitly, or AC-4 is untestable.

### 5c. DRY findings

| Thing the pool needs | Already exists | Decision |
|---|---|---|
| Read `.claude/compound-v.json` fail-closed | `project-config.py:71-111` + `get_models:114-128`; `resolve-model.py:183-211` is already a thin wrapper (`:189-191` says so) | **Extend** — add `get_pools()` beside `get_models()`. Do **not** add a third reader; that is the exact duplication CR2-11 removed. |
| Resolve (backend, tier, stance) → model | `resolve-model.py:247` | **Extend** — `resolve_pool()` should call `resolve()` per member, not re-implement cell lookup, or opencode shape-checking (`:295-301`) and stance handling get duplicated. |
| Stance vocabulary | `resolve-model.py:153` and `validate-manifest.py:522` — **already duplicated on purpose**, with a "keep in sync" comment at `:151-152` | **Follow the house style** — a third duplicate is the established (documented) pattern for these standalone stdlib CLIs; do not introduce a shared import. |
| Advisor-eligibility logic | `resolve-model.py:348-362` and `validate-manifest.py:599-613` — same deliberate mirror (`:593-596`) | Any pool-related change must be applied to **both** or the mirror comment becomes a lie. |
| Backend availability probe | `epic-arbiter.py:517-548` — `load_capabilities` + two per-backend predicates | **Extend or refactor.** A generic `backend_available(caps, name)` is needed. Note `codex_available` is a **double** gate and `agy_available` a **single** gate, by documented design (`:541-548`) — a naive generic function would weaken codex. |
| Per-backend concurrency cap | **nothing** | New. See §6. |

---

## 6. Concurrency: where `max_parallel` is actually consumed

**[C] Nowhere in code.** Full inventory of every non-fixture reference:

| Site | What it does |
|---|---|
| `validate-manifest.py:525-535` (`TOPLEVEL_REQUIRED`) | requires the key to be **present** |
| `validate-manifest.py:1627-1631` | requires it to be an **int**. That is the entire enforcement. |
| `agents/parallel-dispatcher.md:66` | prose: *"Group `run: parallel` jobs into batches of 4-6 max per message — the manifest's `max_parallel`, capped by the phase-3 concurrency reality"* |
| `agents/partition-reviewer.md:93` | prose: emits **`WARN: BATCHING_MISSING`** — explicitly *"a warning, not a fail"* |
| `commands/v-resume.md:28` | prose: *"honoring `depends_on`, `run`, and `max_parallel` exactly as the original dispatch"* |
| `scripts/compound-v-fastpath-materialize.py:436` | writes the literal `"max_parallel": 1` into a single-job fast-path manifest |

**[C] Batching is 100% prose-driven — an LLM agent reads the number and decides how many `Task` calls to put in one message.** There is no scheduler, no semaphore, no queue.
**[I] Therefore `backend_max_parallel` as specified is not expressible as an enforced cap today.** It can only be a second number in the same prose instruction — with the extra difficulty that for a **pool** job the backend is not known until the assignment is made, so respecting a per-backend cap requires the counter and the batch-filler to be the same decision, not two independent ones. Spec §5's framing (*"consulted by the dispatcher when it fills a batch"*) is accurate about the mechanism (prose) but understates that it is unenforceable, and AC-10 (*"`backend_max_parallel` caps concurrent jobs per backend"*) asserts an enforcement that no gate can verify.

---

## 7. `state.json` — shape, writer, validation

**Per-job record shape [C].** Documented at `skills/compound-v/state-machine.md:163-170`: `status`, `isolation`, `worktree`, `session_id`, `failure_class`, `baseline`, `log`. Spec §3's claim that *"`state.json` already carries `isolation` per job, so per-job routing state is an established shape"* is **correct**.

**Who writes it [C].** Two writers, both outside any schema:
1. **The dispatcher agent (an LLM)** — `parallel-dispatcher.md:102` (`session_id`, `failure_class`), `:126` (`running`), `:156` (*"Write `state.json` after every per-job transition"*), `:191` (`cooldowns`, `attempts`), `:192`/`:197` (`circuit_open`); `commands/v-orchestrate.md:34` writes the initial file.
2. **`scripts/compound-v-fastpath-materialize.py`** — the only script that writes one (`:9`, `:20-24`), and only for single-job fast-path runs.

**What validates it [C]: nothing.** `schemas/` contains `job_result`, `fastpath-review-receipt`, `plan-review`, `pre-eval-record` — **no `state.json` schema**. Readers are tolerant by design: `liveness.py:154` (*"fields consumed (all optional, degrade-safe)"*), `dashboard.py:296-299` (unparseable ⇒ an honest error card, `:580`).

**Observed drift across real runs [C]** — the shape is already inconsistent in-repo:

| Run | extra per-job keys | missing documented keys |
|---|---|---|
| `2026-07-01-v2.4.0-stance-aware-models/state.json` | `commit`, `merged_commit`, `scope_gate`, `selftest`, `verdict` | `failure_class`, `log` |
| `2026-07-11-v2.9-pre-evaluation/state.json` | `scope_gate` (one job only) | `baseline` on 10 of 16 jobs |
| `2026-07-11-session-aware-workers/state.json` | — | `failure_class`, `baseline` |

**[I] Consequence:** adding `assigned_backend`/`assigned_model` costs nothing structurally — but it also gets **no** enforcement, and AC-7 (*"Every assignment is recorded"*) is unverifiable by any existing gate. If the assignment is load-bearing for resume (AC-8) and for the breaker (2g), an unwritten field is a silent correctness failure, not a cosmetic one. This is the strongest argument in the audit for a minimal `state.json` schema, or at minimum a `--check-assignments` mode on an existing script.

**Where resume re-derives routing today, exactly [C]:**

| Site | Line | Text | Required change |
|---|---|---|---|
| `commands/v-resume.md` | `:28` | *"via Engine A … honoring `depends_on`, `run`, and `max_parallel` exactly as the original dispatch. Each re-dispatch replays the captured prompt at `jobs/<id>.prompt.md` verbatim."* | add: for `backend: pool`, the backend/model come from `state.json jobs[<id>].assigned_backend/assigned_model`, **not** the manifest |
| `skills/compound-v/state-machine.md` | `:223` | same rule, the authoritative copy | same |
| `agents/parallel-dispatcher.md` | `:68` | *"Each dispatch is built **from the manifest** — never re-decide backend/model/isolation here"* | carve out the pool case explicitly |
| `agents/parallel-dispatcher.md` | `:80` | *"Backend + tier/effort from the manifest job entry"* | must read the assignment first when present |
| `agents/parallel-dispatcher.md` | `:377` | *"DO NOT re-decide backend / tier / isolation — they come from the manifest."* | amend; this sentence currently forbids what the feature requires |
| `agents/parallel-dispatcher.md` | `:70-78` | batch announcement shows resolved `backend · model` | must show the assigned member |
| `agents/parallel-dispatcher.md` | `:48-53` | backend→adapter table | needs a `pool` row saying "resolves to a member; no adapter" |
| `skills/compound-v/state-machine.md` | `:170` | the per-job field list | add the two fields |
| `commands/v-status.md` | `:30` | re-derives the model via the resolver | must not pass `--backend pool` |

**The prompt replay is safe [C]:** `jobs/<id>.prompt.md` is replayed verbatim (`state-machine.md:140`, `v-resume.md:28`) and contains no backend name in its required contents (`parallel-dispatcher.md:111-124`) — **except** the optional advisor block at `:117-123`, whose `--executor claude` is hard-coded in the documented command line. **[I]** A pool job's captured prompt would pin the wrong executor for an advisor consult.

**Quota-failure clearing (spec §3, AC-9) vs the actual policy [C]:**
- `out_of_credits` → `failure-policy.py:90-100` returns `reroute` to `FALLBACK[backend]`, which is **always `claude`** — never "the next pool member". Clearing the assignment does not make the policy pick a pool member; something must re-run the pool selection *after* the policy says reroute.
- `rate_limited` → `failure-policy.py:111-121` returns **`retry` on the SAME backend**, never `reroute`. **AC-9 is factually wrong for `rate_limited`.** Either the spec drops `rate_limited` from AC-9, or it adds a pool-specific branch to the policy (which contradicts §What-does-not-change).
- `auth` → `:85-88` returns `halt` + `circuit_break`, no reroute at all. A pool member with a bad key halts the run rather than rotating to the next member — probably not what the operator wants, and unaddressed.

---

## 8. Design constraints for the spec (non-negotiable)

1. **`pool` must NOT be added to `VALID_BACKENDS`** (`validate-manifest.py:519`) — it is consumed at `:664` for `advisor.advisor_backend` where `pool` is meaningless. Introduce a separate token and accept it only at the job-`backend` enum site `:1733`.
2. **Reviewer-with-pool must be rejected by its own unconditional check**, placed before `:1866`. Reusing `_is_reviewer` (`:563-570`). Without it, `backend: pool` + `tier: deep` passes every reviewer gate while dispatching to an arbitrary member — including `devin`/`opencode`, which `:1833-1841` exists to forbid.
3. **The pool⇒worktree rule needs its own branch**, not membership in the `("codex","antigravity","cursor","devin","opencode")` tuple at `:1817` — the tuple's message interpolates the backend name twice and would print "pool requires worktree" as if pool were a backend.
4. **Round-robin state must live in `state.json` (or be derived from it), never in the resolver.** `resolve()` is pure (`:247-308`) and every production caller is a fresh subprocess (`parallel-dispatcher.md:95`, `v-status.md:30`, `advisor-consult.sh:149`). Name the chosen home and say `resolve_pool(tier, n, …)` takes `n` as a parameter.
5. **Define the deterministic order AC-4 is asserted against.** Batch composition is LLM-decided (`parallel-dispatcher.md:66`); manifest `jobs[]` order is the only stable candidate.
6. **The failure policy, the classifier, and the breaker check must all receive the ASSIGNED backend, never `"pool"`.** Sites: `failure-policy.py:59` (`FALLBACK.get("pool") is None` ⇒ halt), `classify-failure.py:334` (argparse exit 2), `parallel-dispatcher.md:199` (breaker check-before-launch).
7. **Say what `attempts[<job>][<class>]` does when the assignment is cleared.** `state-machine.md:178` currently mandates a reset on re-route, which multiplies a 3-retry cap into 9 across a 3-member pool against a 12-retry run budget (`:182`).
8. **Fix AC-9: `rate_limited` does not reroute.** `failure-policy.py:111-121` returns `retry` on the same backend. Only `out_of_credits` reroutes — and to `FALLBACK[backend]` (always `claude`), not to the next pool member.
9. **State where the availability filter (AC-5) reads from.** There is no `backends` list in `.claude/compound-v.json` (`v-init.md:507`); availability is in the uncommitted `~/.claude/compound-v-capabilities.json` with exactly two predicates in one script (`epic-arbiter.py:529-548`). Either extend that module or declare AC-5 out of scope for v1.
10. **`pools` must be per-stance only, with no legacy-flat auto-detection**, and must be added to the structural gate in `project-config.py:102-110` plus a `get_pools()` beside `get_models()`. The flat/per-stance heuristic at `resolve-model.py:222` is the cause of a live bug (§3a).
11. **Take a position on never-Haiku for pool entries.** A pool job carries no manifest `model`, so the sole execution-layer haiku gate (`validate-manifest.py:1721-1727`) is structurally unreachable for every pooled job. "No change in either direction" is not neutral — it makes the hole the default path for this feature.
12. **Route pool members through `resolve()`, not around it** — that is what preserves the opencode `provider/model` shape check (`resolve-model.py:271-277`, `:295-301`), which the manifest-side check (`:1852-1864`) cannot reach for a pool job.
13. **Resolve the `effort` question.** `xhigh` is currently rejected for every pool job (`:1790-1796`, `"pool" != "codex"`), and `resolve()` raises for xhigh on a non-codex resolved member (`:260-264`). Say whether effort is validated against `pool` or against the assignment.
14. **Say what the dispatcher records in `task-outcomes.jsonl`.** `scorecard.py:75-77` keys on `(backend, type)`; recording `"pool"` collapses every pooled job into one meaningless health row and blinds the scorecard-aware routing at `routing-policy.md:387`.
15. **Concede that `backend_max_parallel` is prose, not enforcement.** `max_parallel` is only presence- and int-checked (`validate-manifest.py:1627-1631`); batching is an LLM instruction (`parallel-dispatcher.md:66`). Reword AC-10 to something a gate can actually check, or mark it advisory.
16. **Amend `parallel-dispatcher.md:377` explicitly.** *"DO NOT re-decide backend / tier / isolation — they come from the manifest"* currently forbids exactly what this feature does. Silence here guarantees a dispatcher that refuses to pool.
17. **Fix the dead cross-reference.** the spec's link to the zai design doc (spec line 16) resolves to nothing on this branch. Either drop the link or state the branch dependency plainly.
18. **Nothing validates `state.json`.** AC-7 is currently unverifiable and the field is load-bearing for AC-8 and for the breaker. Either add a minimal check or state that the risk is accepted.

---

## 9. File Touch Map (for Phase 2 partitioning)

| File | Why it is touched | Flag |
|---|---|---|
| `scripts/compound-v-project-config.py` | `pools` + `backend_max_parallel` structural check (`:102-110`); new `get_pools()` beside `get_models()` (`:114-128`) | **SHARED RESOURCE** — the single fail-closed config reader (CR2-11); the resolver, the pre-eval engine and the validator all read through it |
| `scripts/compound-v-resolve-model.py` | pure `resolve_pool(tier, n, …)`; `advisor_eligible` backend handling; new selftest cases | **SHARED RESOURCE** — loaded in-process by `validate-manifest.py:916`, and by shell in 3 docs; `VALID_STANCES`/`ADVISOR_INELIGIBLE_TYPE_TOKENS` are documented duplicates that must move in lockstep with the validator |
| `scripts/compound-v-validate-manifest.py` | pool enum token; pool⇒worktree; reviewer-not-pool; `_advisor_eligible` mirror; new fixtures + selftest cases | **SHARED RESOURCE** — the deterministic gate behind `partition-reviewer`; CI runs it over `examples/*` and every `docs/superpowers/execution/*/manifest.yaml` (`validate.yml:126-132`) |
| `scripts/compound-v-failure-policy.py` | `FALLBACK` must handle the assigned backend; the devin/opencode/zai gap (`:59`) | **SHARED RESOURCE** — the decision table every backend failure flows through |
| `scripts/compound-v-classify-failure.py` | `--backend` choices (`:334`) | — |
| `agents/parallel-dispatcher.md` | counter ownership; assignment write; assignment-first re-dispatch; adapter table; announcement; amend `:377` | **SHARED RESOURCE** — the executable spec other docs quote verbatim (the resume-eligibility rule is byte-identical with `v-resume.md`) |
| `commands/v-resume.md` | step 5 must prefer the recorded assignment (`:28`) | **SHARED RESOURCE** — byte-identical block with `parallel-dispatcher.md:205-209`; edits must stay word-for-word |
| `skills/compound-v/state-machine.md` | per-job fields (`:170`); resume step 5 (`:223`); optional `pool_cursor` | **SHARED RESOURCE** — the authority `/v:status`, `/v:resume` and the dispatcher all implement against (`:58-60`) |
| `skills/compound-v/execution-manifest.md` | `backend` enum row (`:38`); pool⇒worktree invariant; `pools` config block | **SHARED RESOURCE** — the human-readable schema the validator backs |
| `skills/compound-v/routing-policy.md` | when a planner chooses `backend: pool`; interaction with the env-aware rewrite (`:250-271`) and the scorecard (`:374-395`) | — |
| `commands/v-status.md` | must not pass `--backend pool` to the resolver (`:30`) | — |
| `commands/v-init.md` | seed `pools` (and/or `backend_max_parallel`) in the 4a config block (`:511-556`) | **SHARED RESOURCE** — config seed template mirrored in `execution-manifest.md:69-89` and `v-models.md:39-56` |
| `commands/v-models.md` | `/v:models` must not clobber `pools` (see §3a) | — |
| `scripts/compound-v-discover-models.py` | `write_config` (`:122-139`) writes the flat shape — decide fix-or-document | **SHARED RESOURCE** — writes the shared config file |
| `scripts/compound-v-scorecard.py` / `compound-v-update-memory.py` | must receive the assigned backend, not `"pool"` | — |
| `scripts/compound-v-usage-extract.py` | `UNMEASURED_BACKENDS` (`:56-58`) must never see `"pool"` | — |
| `examples/manifest.example.yaml` | optional worked pool example | **SHARED RESOURCE** — CI validates it on every push (`validate.yml:126`) |
| `CHANGELOG.md` | release note | **SHARED RESOURCE** — every feature branch appends here; classic merge-conflict site |
| `schemas/` (new `state.json` schema, if constraint 18 is accepted) | — | **SHARED RESOURCE** — schema directory read by multiple scripts |

**Not touched (verified):** `schemas/job_result.schema.json`, every `scripts/compound-v-run-*-worker.sh`, `scripts/compound-v-scope-check.py`, `skills/backend-launcher/adapter-*.md`, `scripts/compound-v-liveness.py`, `scripts/compound-v-dashboard.py` — the spec's "what does not change" list holds for all of these, confirmed by reading each one's backend handling.
