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
lessons → routing — a deterministic order, not a learned model.

> **V-memory (v2.0) does not change this order.** The new prose-recall layer
> (see [`memory.md`](memory.md)) is **evidence for planning + review, not a routing
> input.** Routing stays the deterministic v1.1 order — lessons → stance table →
> scorecard → fallback → invariants — exactly as above; recall never reorders it. The
> one bridge from recall back into action is **conservative-only**: `recall-check
> --files <glob>` counts prior structured `job_result` records (`blocked`/`error`/`timeout`
> / scope violation) on the same file pattern, and `N≥k` returns a single verdict
> **`tighten`** (force worktree / +review pass / fold into Task 0). It is the prose
> analogue of the scorecard's `unhealthy → escalate`: it only ever makes routing **more**
> conservative, and it **never reroutes to a lower-trust backend**.

The engine also consults a **machine-generated scorecard** (see [Scorecard-aware
routing](#scorecard-aware-routing) below). The scorecard is a *deterministic
aggregate* of the same `task-outcomes.jsonl` — not a learned model, not a vector
store — and it only ever makes routing **more** conservative. The human-curated
`routing-lessons.md` remains the authoritative override; scorecards are a hint
layered underneath it.

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
| `large_isolated` build | **codex** (alt: **antigravity** / **cursor**, lower-trust) | standard · medium | worktree | parallel |
| `mechanical_refactor` / rename / format | claude | light · low | direct | parallel |
| `docs` / i18n strings | claude | light · low | direct | parallel |
| `tests_new` — designing new tests | claude | deep · high | direct | parallel |
| `external_api` integration | claude | deep · high | worktree | parallel |
| `review` — spec / quality / integration | claude | deep · high | direct | parallel/serial |
| **Unclear scope** | **none → return to planning** | — | — | — |

> **Antigravity is a selectable alternative for `large_isolated` build — opt-in and
> lower-trust.** It is a real backend (Bash-spawned `agy --print` in its own worktree,
> same git-diff scope gate as Codex — [`adapter-antigravity.md`](../backend-launcher/adapter-antigravity.md)),
> **available only when `agy` is installed** (env-aware; absent → the row stays on
> codex/claude). But `agy` has **NO kernel write-confinement** like Codex's
> `--sandbox workspace-write`, and headless writes require `--dangerously-skip-permissions`
> (arbitrary shell + out-of-worktree writes possible). The worktree + `git diff` gate
> detects in-worktree scope leaks but cannot *prevent* an out-of-worktree side-effect —
> so **prefer Codex (kernel-sandboxed) for untrusted / high-stakes work**, and pick
> antigravity only when the prompt and surface are trusted. **antigravity ⇒ worktree**
> is a hard invariant (below).

Why these tiers: `deep` is the strongest reasoning seat — it carries architecture,
all sensitive surfaces, designing new tests, external APIs, every reviewer, and
shared-foundation Task 0. `standard` carries bounded core/feature build including
large isolated Codex work. `light` carries mechanical single-file edits, docs, and
i18n. `bounded_crud` sits on `light` here (a well-specified 8-box junior slice); a
fuzzier CRUD slice that needs more judgment is bumped to `standard` — that is a
planner call, not a hard rule.

> With the per-stance models map (Balanced shown), `deep`/`standard` on `claude` both resolve to `opus`
> and `light` to `sonnet`; `standard` on `codex` resolves to `gpt-5.6-terra`. So this
> table produces the same effective models as the pre-tier version — the difference
> is that the model strings now live in one refreshable place, not in the table.

---

## Stance: Conservative (Opus-heavy, no Codex)

For high-stakes or unfamiliar codebases where you want maximum judgment and no
external worker. Every implementation job is `deep`; `light` is reserved for purely
mechanical slices; Codex is not used at all. (With the per-stance models map (Balanced shown) `deep`
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
>
> Under this stance the `standard`-tier `claude` cell resolves to **Sonnet 5** (the
> resolver's `cost-aware.claude.standard = sonnet`), so `core_slice`/`tests_new`
> implementers run on Sonnet here — while `deep` (architecture, sensitive surfaces,
> **all reviewers**) stays Opus. Only the `standard` Claude cell shifts; `light` is
> `sonnet` in every stance, and `codex`/`antigravity`/`cursor` are identical across stances.

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

`.claude/compound-v.json` carries a **per-stance** `models` map — its shape is
`{<stance>: {<backend>: {<tier>: model}}}`, so each stance carries its own
`{tier → model}` rows. Only the `claude` rows differ across stances; `codex` /
`antigravity` / `cursor` are identical in every stance. The one cell that moves is
`cost-aware.claude.standard`, which is **`sonnet`** (Sonnet 5) — everywhere else
`standard` Claude is `opus`:

```json
"models": {
  "balanced": {
    "claude":      { "deep": "opus", "standard": "opus", "light": "sonnet" },
    "codex":       { "deep": "gpt-5.6-sol", "standard": "gpt-5.6-terra", "light": "gpt-5.6-luna" },
    "antigravity": { "deep": "Gemini 3.1 Pro (High)", "standard": "Gemini 3.1 Pro (Low)", "light": "Gemini 3.5 Flash (Low)" }
  },
  "cost-aware": {
    "claude":      { "deep": "opus", "standard": "sonnet", "light": "sonnet" },
    "codex":       { "deep": "gpt-5.6-sol", "standard": "gpt-5.6-terra", "light": "gpt-5.6-luna" },
    "antigravity": { "deep": "Gemini 3.1 Pro (High)", "standard": "Gemini 3.1 Pro (Low)", "light": "Gemini 3.5 Flash (Low)" }
  }
}
```

(`conservative` and `claude-only` mirror `balanced`. Only `cost-aware.claude.standard`
differs — `sonnet`, not `opus`. `cost-aware.claude.deep` stays `opus`.)

The map is **documented, not committed** in this repo — it is project-local config.
[`/v:init`](../../commands/v-init.md) seeds this per-stance default map so routing
works out of the box; `/v:models` discovers what is actually available per backend
and rewrites the map (`agy models` for antigravity; a curated, user-overridable list
for codex, which has no list command; native tier aliases for claude). The resolver
still **accepts the legacy flat shape** `{<backend>: {<tier>: model}}` (applied to
every stance) for backward-compat — it auto-detects which shape it was handed.
Antigravity values above are illustrative placeholders. **NEVER `haiku` anywhere.**

### Resolution (tier → model), at dispatch time

[`scripts/compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) is
the generic resolver the dispatcher runs **before** invoking any backend — once per
job. It is the single indirection point; no backend-specific routing logic is baked
into it.

```
compound-v-resolve-model.py --backend codex --tier deep --effort high \
  --config .claude/compound-v.json
# → {"backend": "codex", "tier": "deep", "model": "gpt-5.6-sol", "effort": "high"}
```

Precedence, lowest to highest:

1. **Built-in default map** (the one above) so the resolver works with no config file.
2. **`models.<backend>.<tier>`** from `--config`, if present, overrides that one cell.
3. **`--explicit-model M`** (a manifest `model` override) always wins and skips the
   map entirely.

Resolution is **stance-aware**: the dispatcher reads the manifest's `routing_stance`
and passes `--stance <stance>` (default `balanced`) on every resolve, so the
`standard` Claude cell resolves to `opus` under `balanced` and `sonnet` under
`cost-aware`. The dispatcher passes the resolved `model` to the worker (plus
`--effort` for codex → `-c model_reasoning_effort`). A job carrying an explicit
manifest `model` **skips resolution** — the manifest pinned it directly. The resolver
exits non-zero if a tier cannot be resolved for a backend, which the dispatcher treats
as a hard stop. See
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

> **Also invoked at runtime, not only at `/v:init`.** This same env-aware codex→claude
> rewrite fires **during a run** when a Codex job fails with `out_of_credits`: the
> failure policy circuit-breaks Codex for the run and re-routes the failed job — and
> every remaining Codex job — through exactly this rewrite (codex rows → `backend:
> claude`, `isolation: worktree`, `tier: deep`). It is the same transformation, just
> triggered by a runtime credit-exhaustion event instead of an install-time capability
> probe. The swap is **announced** — never a silent cheap→expensive substitution — and
> surfaced in [`/v:status`](../../commands/v-status.md) and the run summary (e.g. *"codex
> out of credits → N jobs re-routed to claude/opus, est. cost ↑"*). The full policy is
> [`failure-policy.md`](failure-policy.md).

---

## Invariants (non-negotiable, deterministically enforced)

These hold in **every** stance and are checked by `compound-v-validate-manifest.py`
(hard, non-zero exit) and `partition-reviewer`:

1. **Reviewers ⇒ deep.** Any `review`/reviewer job MUST resolve to the strongest
   tier — `tier: deep` **OR** an explicit `model: opus`. (`deep` resolves to `opus`
   for claude, so this mirrors the frontmatter rule that reviewers/agents always
   carry `model: opus`.)
2. **Codex / Antigravity / Cursor ⇒ worktree.** Any `backend: codex`, `backend: antigravity`,
   **or** `backend: cursor` job MUST be `isolation: worktree`. All three are external workers
   with no per-file enforcement of their own: Codex's sandbox restricts writes only to a
   *directory*, and Antigravity and Cursor have **no kernel sandbox at all** (Cursor's headless
   `-f` grants arbitrary write+shell) — so worktree + `git diff` is the only file-scope
   enforcement they get. The validator rejects any of these backends with `isolation: direct`.
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
4. **Scorecard check** (see [Scorecard-aware routing](#scorecard-aware-routing)): query
   the measured `health` of this (static-default backend × task-type) in THIS repo. If
   `unhealthy`, **escalate to an equal-or-higher-trust seat** (Codex → Opus/`deep` by
   default; **never auto-route to a lower-trust backend** — see [What scorecards are NOT](#what-scorecards-are-not)) and log a one-line
   justification; if `watch`, keep the default but note it; if `healthy` /
   `insufficient_data`, keep the default unchanged.
5. Apply the env-aware fallback (rewrite Codex rows if Codex is absent).
6. Validate the result against the invariants (the validator is the backstop).
7. If the type is "unclear scope," **stop and return to planning** — do not guess.
8. At **dispatch** (not planning), resolve `(backend, tier, effort)` → a concrete
   `model` via [`compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py)
   against the project `models` map. An explicit manifest `model` skips this step.

---

## Scorecard-aware routing

The stance tables above are a **static guess**: a task-type maps to a fixed backend
and tier, decided once and applied to every repo the same way. Scorecards make that
guess **adaptive** — before assigning a task-type's static-default backend, the
planner/router checks how that backend has *actually* performed for that task-type
**in THIS repo**, and escalates to a higher-trust seat (never a lower-trust backend) when the default is measured-unhealthy.

The signal comes from [`worker-performance.jsonl`](../../docs/superpowers/memory/),
the machine-generated scorecard that
[`scripts/compound-v-scorecard.py`](../../scripts/compound-v-scorecard.py) aggregates
from `task-outcomes.jsonl` — one row per `(backend, type)` with a `health` verdict.
Query a single cell at routing time:

```bash
python3 scripts/compound-v-scorecard.py --query --backend <default> --type <task-type>
# → stats + health ∈ {insufficient_data, healthy, watch, unhealthy}
```

Act on `health`:

| `health` | Action |
|---|---|
| `unhealthy` | **Escalate UP the trust/capability ordering** — to a *stronger, equal-or-higher-trust* seat (Opus, `tier: deep`, is the safe escalation), and **log a one-line justification** (e.g. *"codex unhealthy on `large_isolated` here: block_rate .35 over 12 jobs → escalating to opus/deep this run"*). **Never auto-route to a lower-trust backend** (trust ordering below): a Codex-unhealthy cell escalates to Opus — it does NOT silently fall to Antigravity. |
| `watch` | Keep the static default, but **note it** in the routing log (one line) so a drift toward `unhealthy` is visible. |
| `healthy` / `insufficient_data` | **Use the static default unchanged.** Don't over-react to thin data — the script needs **≥5 samples** to judge a cell; below that it returns `insufficient_data` and the static policy stands. |

### What scorecards are NOT

- **Not a replacement for the static policy** — they are a **hint layered on top of
  it.** The stance table is still the default; the scorecard only nudges the router
  off a default that the repo's own measured outcomes show is failing.
- **They only ever escalate UP a fixed trust/capability ordering, never down.** The
  ordering is **`claude` (in-process, no external write surface) ≥ `codex` (kernel
  `workspace-write` sandbox) ≥ `antigravity` (no kernel sandbox — opt-in/lower-trust)**.
  An `unhealthy` cell pushes work to a *stronger or higher-trust* seat (Opus); it can
  never downgrade a `deep` job to `light`, route a sensitive surface off Opus, or
  **auto-select a lower-trust backend**. In particular a scorecard NEVER converts an
  unhealthy Codex cell into Antigravity — Antigravity is entered only by explicit
  per-job opt-in, never as an automatic "escalation."
- **They do not override the HARD invariants.** Reviewers ⇒ `deep`, Codex ⇒
  `worktree`, and unclear scope ⇒ return to planning hold regardless of any scorecard.
  Security / auth / payments / PII / a11y stays `deep` in every stance, scorecard or
  not.
- **No cost/token metrics.** The scorecard reports only outcome health
  (`block_rate`, `error_rate`, `success_rate`, `avg_rework`) — never a fabricated
  cost or token number (anti-ruflo).

### Where the scorecard comes from

`worker-performance.jsonl` is **regenerated each run** by
`compound-v-scorecard.py --update` after the dispatcher appends fresh outcomes to
`task-outcomes.jsonl` (see [`parallel-dispatcher.md`](../../agents/parallel-dispatcher.md)
post-run memory step). It is **machine-generated and never hand-edited** — unlike the
human-curated `routing-lessons.md`, which remains the authoritative override. The
loop is the same closed loop, with one extra derived artifact: outcomes →
{lessons (hand-curated), scorecard (auto-aggregated)} → routing.
