# Routing Policy — task-type → backend · tier · effort · isolation · run

> *"Right supe, right job. You don't send the new kid to do Soldier Boy's work, and you don't burn Homelander on a printout."*

This is the **routing engine** for Compound V. Given a job's `type` (the token in
the manifest, see [`execution-manifest.md`](execution-manifest.md)), it decides
**backend · tier · effort · isolation · run**. Note the column shift: routing no
longer names concrete model strings. It picks a **tier** (the stable intent) and an
**effort** hint; the concrete model is resolved separately at dispatch time from a
refreshable config map (see [Tiers, the models map, and the resolver](#tiers-the-models-map-and-the-resolver)).
That indirection is what lets the plugin survive model churn: when a provider ships
a new model, you refresh the map, not every table and manifest.

The planner applies this policy when materializing `manifest.yaml`; the
deterministic invariants below are also enforced by
[`scripts/compound-v-validate-manifest.py`](../../scripts/compound-v-validate-manifest.py)
and reviewed by [`partition-reviewer`](../../agents/partition-reviewer.md).

The active **stance** is chosen once at [`/v:init`](../../commands/v-init.md) and
saved to `.claude/compound-v.json` (project-level). Different repos can run
different stances. **Balanced** is the default when Codex is present; **Claude-only**
when it is not.

These are *not* the only inputs. Before routing a job type, the engine **consults
[`docs/superpowers/memory/routing-lessons.md`](../../docs/superpowers/memory/routing-lessons.md)** —
the human-curated lessons distilled from `task-outcomes.jsonl`. A recorded lesson
("`large_isolated` on codex blocked twice on barrel files → fold barrels into Task 0")
overrides the table default for that pattern. That is the closed loop: outcomes →
lessons → routing, no scorecards or vector DB (anti-ruflo, PRD §5.8).

---

## Stance: Balanced (default, shipped) — PRD §5.5

Routing assigns a **(tier, effort)** pair, not a model. The default effort pairing
is `deep→high`, `standard→medium`, `light→low`, but effort is orthogonal and
independently tunable per task-type — the `effort` column below is the recommended
value, not a derived one. The concrete model comes from the [models map](#tiers-the-models-map-and-the-resolver)
at dispatch.

| Job type | Backend | Tier · Effort | Isolation | Run |
|---|---|---|---|---|
| `shared_foundation` (Task 0) | claude | deep · high | direct | serial |
| Security / auth / payments / PII / a11y | claude | deep · high | worktree | parallel |
| `core_slice` (design judgment) | claude | deep · high | worktree | parallel |
| `bounded_crud` (8-box junior) | claude | light · low | direct | parallel |
| `large_isolated` build | **codex** | standard · medium | worktree | parallel |
| `mechanical_refactor` / rename / format | claude | light · low | direct | parallel |
| `docs` / i18n strings | claude | light · low | direct | parallel |
| `tests_new` — designing new tests | claude | deep · high | direct | parallel |
| `external_api` integration | claude | deep · high | worktree | parallel |
| `review` — spec / quality / integration | claude | deep · high | direct | parallel/serial |
| **Unclear scope** | **none → return to planning** | — | — | — |

Why these tiers: `deep` is the strongest reasoning seat — it carries architecture,
all sensitive surfaces, designing new tests, external APIs, every reviewer, and
shared-foundation Task 0. `standard` carries bounded core/feature build including
large isolated Codex work. `light` carries mechanical single-file edits, docs, and
i18n. `bounded_crud` sits on `light` here (a well-specified 8-box junior slice); a
fuzzier CRUD slice that needs more judgment is bumped to `standard` — that is a
planner call, not a hard rule.

> With the Balanced models map, `deep`/`standard` on `claude` both resolve to `opus`
> and `light` to `sonnet`; `standard` on `codex` resolves to `gpt-5.5`. So this
> table produces the same effective models as the pre-tier version — the difference
> is that the model strings now live in one refreshable place, not in the table.

---

## Stance: Conservative (Opus-heavy, no Codex)

For high-stakes or unfamiliar codebases where you want maximum judgment and no
external worker. Every implementation job is `deep`; `light` is reserved for purely
mechanical slices; Codex is not used at all. (With the Balanced models map `deep`
resolves to `opus` and `light` to `sonnet`, so this is "Opus-everywhere except the
mechanical edges" — but stated in the churn-proof tier vocabulary.)

| Job type | Backend | Tier · Effort | Isolation | Run |
|---|---|---|---|---|
| `shared_foundation` | claude | deep · high | direct | serial |
| Security / auth / payments / PII / a11y | claude | deep · high | worktree | parallel |
| `core_slice` | claude | deep · high | worktree | parallel |
| `bounded_crud` | claude | deep · high | worktree | parallel |
| `large_isolated` build | **claude** | deep · high | worktree | parallel |
| `mechanical_refactor` / rename / format | claude | light · low | direct | parallel |
| `docs` / i18n strings | claude | light · low | direct | parallel |
| `tests_new` | claude | deep · high | direct | parallel |
| `external_api` | claude | deep · high | worktree | parallel |
| `review` | claude | deep · high | direct | parallel/serial |
| Unclear scope | none → return to planning | — | — | — |

---

## Stance: Cost-aware (more Sonnet / Codex)

For well-specified, lower-risk work where throughput and cost matter more than
deep judgment. Pushes routine slices to `standard`/`light` and large isolated builds
to Codex. **Reviewers stay `deep`** (invariant) — the savings come from implementers,
never the gate.

| Job type | Backend | Tier · Effort | Isolation | Run |
|---|---|---|---|---|
| `shared_foundation` | claude | deep · high | direct | serial |
| Security / auth / payments / PII / a11y | claude | deep · high | worktree | parallel |
| `core_slice` | claude | standard · medium | worktree | parallel |
| `bounded_crud` | claude | light · low | direct | parallel |
| `large_isolated` build | **codex** | standard · medium | worktree | parallel |
| `mechanical_refactor` / rename / format | claude | light · low | direct | parallel |
| `docs` / i18n strings | claude | light · low | direct | parallel |
| `tests_new` | claude | standard · medium | direct | parallel |
| `external_api` | claude | deep · high | worktree | parallel |
| `review` | claude | deep · high | direct | parallel/serial |
| Unclear scope | none → return to planning | — | — | — |

> Security / auth / payments / PII / a11y stays `deep` (⇒ Opus) in **every** stance
> — sensitive surfaces are never cost-optimized.

---

## Tiers, the models map, and the resolver

Routing speaks **tiers**, not models. The mapping from tier to a concrete model
lives in one refreshable place, so model churn touches the map — never the tables
or the manifests.

### Tier vocabulary (stable — never changes when models churn)

| Tier | Strongest fit | Default effort |
|---|---|---|
| `deep` | strongest reasoning — architecture, security/auth/payments/PII/a11y, designing new tests, external APIs, **all reviewers**, shared-foundation Task 0 | high |
| `standard` | bounded core/feature build, incl. large isolated Codex work | medium |
| `light` | mechanical single-file edits, docs, i18n strings | low |

`effort ∈ {low, medium, high}` is **orthogonal** to tier. The default pairing
(`deep→high`, `standard→medium`, `light→low`) is only a default; a task-type may pin
a different effort independently. For `codex`, effort maps to
`-c model_reasoning_effort=<effort>`; for `claude` it is advisory (the `Task` path
has no separate effort flag).

### The models map (project config, refreshable, not committed)

`.claude/compound-v.json` carries a `models` map — one `{tier → model}` row per
backend:

```json
"models": {
  "claude":      { "deep": "opus", "standard": "opus", "light": "sonnet" },
  "codex":       { "deep": "gpt-5.5", "standard": "gpt-5.5", "light": "gpt-5.3-codex-spark" },
  "antigravity": { "deep": "Gemini 3.1 Pro (High)", "standard": "Gemini 3.1 Pro (Medium)", "light": "Gemini 3.1 Flash" }
}
```

The map is **documented, not committed** in this repo — it is project-local config.
[`/v:init`](../../commands/v-init.md) seeds this default map so routing works out of
the box; `/v:models` discovers what is actually available per backend and rewrites
the map (`agy models` for antigravity; a curated, user-overridable list for codex,
which has no list command; native tier aliases for claude). Antigravity values above
are illustrative placeholders. **NEVER `haiku` anywhere.**

### Resolution (tier → model), at dispatch time

[`scripts/compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) is
the generic resolver the dispatcher runs **before** invoking any backend — once per
job. It is the single indirection point; no backend-specific routing logic is baked
into it.

```
compound-v-resolve-model.py --backend codex --tier deep --effort high \
  --config .claude/compound-v.json
# → {"backend": "codex", "tier": "deep", "model": "gpt-5.5", "effort": "high"}
```

Precedence, lowest to highest:

1. **Built-in default map** (the one above) so the resolver works with no config file.
2. **`models.<backend>.<tier>`** from `--config`, if present, overrides that one cell.
3. **`--explicit-model M`** (a manifest `model` override) always wins and skips the
   map entirely.

The dispatcher passes the resolved `model` to the worker (plus `--effort` for codex →
`-c model_reasoning_effort`). A job carrying an explicit manifest `model` **skips
resolution** — the manifest pinned it directly. The resolver exits non-zero if a tier
cannot be resolved for a backend, which the dispatcher treats as a hard stop. See
[`execution-manifest.md`](execution-manifest.md) for the job-spec `tier`/`effort`/`model`
fields and [adapter-codex](../backend-launcher/adapter-codex.md) /
[adapter-claude](../backend-launcher/adapter-claude.md) for per-backend effort
handling.

---

## Env-aware Claude-only fallback

If `/v:init` finds **no Codex CLI** (or the user picks Claude-only), the stance
collapses so nothing routes to a backend that is not installed:

- Every `backend: codex` row is rewritten to **`backend: claude`, `isolation: worktree`**
  and bumped to **`tier: deep`** (the large-isolated build keeps its worktree
  isolation; only the worker and tier change — Claude doing isolated build work warrants
  the strongest seat, which resolves to `opus`). Effort follows the tier (`high`).
- All other rows are unchanged from the chosen base stance — they keep their
  `(tier, effort)` pairs and resolve through the same models map.
- The saved config records `backends: ["claude"]` so the dispatcher never attempts a
  Codex launch and the manifest validator does not expect one.

This is exactly Success Criterion #5 (PRD §9): with Codex absent, the pipeline runs
unchanged, just Claude-only.

---

## Invariants (non-negotiable, deterministically enforced)

These hold in **every** stance and are checked by `compound-v-validate-manifest.py`
(hard, non-zero exit) and `partition-reviewer`:

1. **Reviewers ⇒ deep.** Any `review`/reviewer job MUST resolve to the strongest
   tier — `tier: deep` **OR** an explicit `model: opus`. (`deep` resolves to `opus`
   for claude, so this mirrors the frontmatter rule that reviewers/agents always
   carry `model: opus`.)
2. **Codex ⇒ worktree.** Any `backend: codex` job MUST be `isolation: worktree`.
   Codex's sandbox can only restrict writes to a *directory*, so worktree + `git diff`
   is the only file-scope enforcement.
3. **Unclear scope ⇒ return to planning.** A job whose scope the planner cannot pin
   never dispatches with a guessed partition — it goes back to writing-plans.
4. **Model OR tier.** Every job MUST carry at least one of `model` or `tier`. A job
   with neither gives the resolver nothing to route on and fails validation.
5. **Tier / effort enums.** When present, `tier ∈ {deep, standard, light}` and
   `effort ∈ {low, medium, high}`. NEVER `haiku` anywhere — not in the map, not as
   a model override, not in frontmatter.
6. **Parallel ⇒ worktree.** A `run: parallel` job MUST be `isolation: worktree`;
   `isolation: direct` is valid only with `run: serial`. A repo-wide `git diff`
   cannot attribute a parallel direct job's writes, so per-job isolation is
   mandatory for parallel work. The validator rejects parallel+direct.

`backend`, `tier`, `effort`, and `model` are **execution-layer data**. They drive
dispatch and live only in the manifest — they **never** appear in any
agent/skill/command frontmatter. (`lint-frontmatter.py` + `validate.yml` reject
Haiku; reviewers/agents always carry `model: opus` in their own frontmatter, which
is the agent's model and is unrelated to this execution-layer tier resolution.)

> **Parallel ⇒ worktree (enforced); direct ⇒ serial.** The scope gate reads a
> repo-wide `git diff`, so a `direct` job only gets deterministic *per-job*
> attribution when it does not run concurrently in the same working tree. The
> validator therefore **rejects any `run: parallel` + `isolation: direct` job**: a
> parallel job MUST be `isolation: worktree` (true per-job attribution), and
> `isolation: direct` is valid only with `run: serial`. Where a table row above
> reads `direct · parallel`, that is the *intent* for an isolated parallel job — the
> planner materializes it as `isolation: worktree` in the manifest. Serial `direct`
> jobs keep their own per-job gate. (Batch-granularity gating — union of
> `write_allowed`, run once after a batch — remains a coarse out-of-batch-leak
> fallback that cannot attribute per job; it is not the primary path.) See
> [`execution-manifest.md`](execution-manifest.md) §"Scope-attribution rule" and
> [`phase-3-parallel-opus-dispatch.md`](phase-3-parallel-opus-dispatch.md) Step 2b.

> **`direct` mode assumes a clean-ish tree — prefer `worktree` when untrusted.** A
> `direct` job gates against a pre-dispatch baseline commit **minus** a snapshot of
> untracked/ignored paths that existed before it (so a dirty tree does not
> false-BLOCK). The inherent blind spot: a job that **modifies a pre-existing
> untracked/ignored file** (already in that snapshot) is **not** flagged. A fresh
> `worktree` has no pre-existing untracked files, so its gate is exact — every write
> is attributed. So **recommend `isolation: worktree` as the safe default for
> anything untrusted or running on a dirty working tree**; `direct` stays serial-only
> and is for trusted, clean-tree jobs. This is a runtime property of the working
> tree, so neither the validator nor `partition-reviewer` can detect it at plan time
> — it is a routing judgment, not a hard gate.

---

## How a job type is routed (the decision, in order)

1. Read the active **stance** from `.claude/compound-v.json` (default Balanced;
   Claude-only if no Codex).
2. Check [`routing-lessons.md`](../../docs/superpowers/memory/routing-lessons.md)
   for a lesson matching this `type` + backend — if one applies, follow it.
3. Otherwise apply the stance table above to get **backend + (tier, effort)**.
4. Apply the env-aware fallback (rewrite Codex rows if Codex is absent).
5. Validate the result against the invariants (the validator is the backstop).
6. If the type is "unclear scope," **stop and return to planning** — do not guess.
7. At **dispatch** (not planning), resolve `(backend, tier, effort)` → a concrete
   `model` via [`compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py)
   against the project `models` map. An explicit manifest `model` skips this step.
