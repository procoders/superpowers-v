# Execution Manifest — schema + rules

The manifest is the **machine-readable contract between the planner and the executors**. It is materialized from the verified Partition Map + Routing Policy immediately after `writing-plans`, one per run, at:

```
docs/superpowers/execution/<run-id>/manifest.yaml
```

Worked example: [`examples/manifest.example.yaml`](../../examples/manifest.example.yaml) (mirrors PRD §5.1). The deterministic validator is [`scripts/compound-v-validate-manifest.py`](../../scripts/compound-v-validate-manifest.py) (built downstream) — it is the authority behind the rules below; this doc is the human-readable spec.

---

## Top-level fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `run_id` | string | yes | Unique run identifier; also the run-dir name. Convention: `YYYY-MM-DD-<slug>`. |
| `feature` | string | yes | One-line feature title. |
| `spec_path` | string | yes | Path to the spec the brainstorming produced. |
| `plan_path` | string | yes | Path to the plan `writing-plans` produced. |
| `audits` | map | yes | `{archaeology, domain, library}` → the three pre-flight output paths. |
| `acceptance_criteria` | string[] | yes | **Feature-level** AC. The final integration review gates DONE on these. |
| `routing_stance` | enum | yes | `balanced` \| `conservative` \| `cost-aware` \| `claude-only`. |
| `max_parallel` | integer | yes | Batch concurrency ceiling (the phase-3 reality, typically 4–6). |
| `jobs` | list | yes | One entry per file-scoped job (schema below). |
| `triage` | map | no† | v3.0 (Feature A2): `{tier, pre_eval_id, taxonomy_digest, decided_at}`. **Required under `--require-triage`**, which `/v:dispatch` passes on every live dispatch. See the v3.0 section below. |
| `test_contract` | map | no | v3.0 (Feature B2): `{floor_command, full_command, impacted_map}`. Absent ⇒ every job runs `full`. See the v3.0 section below. |

**`{path}` substitution is the contract, not an illustration.** Inside a rule's `run`, the literal token `{path}` is replaced by the changed path that matched the rule's `when` glob, once per matching path. It appeared only inside examples until now, so an implementer had to infer it; a rule whose `run` omits `{path}` is still valid and simply runs once per match.

† `triage` is absent-valid for the mode-less CI sweep only, so the manifests committed before 3.0 stay valid without a back-filled record. Every live dispatch demands it.

`acceptance_criteria` is feature-level and gates the final integration review. Each job *also* carries its own narrow `acceptance` (below) for its per-task review — do not confuse the two.

---

## Per-job fields (`jobs[]`)

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | string | yes | Unique job id within the run (e.g. `task-1-editor-ui`). |
| `title` | string | yes | One-line job title. |
| `type` | string | yes | Job-type token used by the routing policy (e.g. `shared_foundation`, `bounded_crud`, `large_isolated`, `core_slice`, `mechanical_refactor`, `docs`, `tests_new`, `external_api`, `review`). |
| `backend` | enum | yes | `claude` \| `codex` \| `antigravity` \| `cursor` \| `devin` \| `opencode`. **Execution-layer data — NEVER appears in any frontmatter.** (`antigravity`/`cursor`/`opencode` are opt-in, lower-trust, no kernel sandbox ⇒ always `worktree`; `devin` has a Research-Preview kernel sandbox treated as unverified/no-confinement for v1 ⇒ also always `worktree`. `devin`/`opencode` are **worker-only** — never a routable arbiter/review-panel seat, since both are multi-provider brokers whose resolved model family is data-dependent.) |
| `tier` | enum | yes¹ | `frontier` \| `deep` \| `standard` \| `light`. The **intent** the routing policy assigns; the dispatcher resolves it to a concrete model and passes it as `agent()`'s `opts.model`. Stable vocabulary that survives model churn. |
| `effort` | enum | no | `low` \| `medium` \| `high` \| `xhigh`. Orthogonal reasoning-effort hint. Default pairing `frontier→high`, `deep→high`, `standard→medium`, `light→low`, but independently tunable per task-type. For `codex` it maps to `-c model_reasoning_effort=<effort>`; for `claude` it is advisory (the `Task` path has no separate effort flag). `xhigh` is valid **iff** `backend: codex`; every other backend rejects it with a clear error naming the rule (use `high` instead). |
| `model` | string | no¹ | Explicit override, e.g. `opus`, `sonnet`, `gpt-5.6-sol`. When present it **skips resolution** (the manifest pins the model directly). Execution-layer data — never in frontmatter. Backward-compatible: pre-tier manifests carrying only `model` remain valid. |
| `isolation` | enum | yes | `direct` \| `worktree`. **`run: parallel` ⇒ `worktree`** (per-job scope attribution); `direct` is only valid with `run: serial`. |
| `run` | enum | yes | `serial` \| `parallel`. A `parallel` job MUST be `isolation: worktree` (see the rule above). |
| `depends_on` | string[] | no | Job ids that must finish first (defaults to empty). |
| `write_allowed` | string[] | yes | Glob list this job MAY write. The scope gate **enforces** it (git-derived). |
| `read_allowed` | string[] | yes | Glob list this job MAY read. **ADVISORY only — NOT enforced** (git cannot track reads). Documents intent + scopes the prompt. Auto-includes Task 0 outputs + the three audits. |
| `acceptance` | string[] | yes | This job's narrow acceptance, checked in its per-task review. |
| `test_scope` | enum | no | v3.0 (Feature B2): `full` \| `impacted` \| `floor_only`. **Absent ⇒ `full`.** `floor_only` requires a non-empty `test_contract.floor_command`; `impacted` requires a non-empty `full_command` (an unmapped path resolves to it). |
| `timeout_sec` | integer | no | Wall-clock seconds this job's worker gets before the supervisor kills it. Domain **60 … 21600** inclusive (a bool is rejected — `true` is not `1`). **Absent ⇒ the worker script's own `DEFAULT_TIMEOUT_SEC=900`, unchanged**, which is what every manifest committed before v2.18 relies on. Applies to the **worker-script backends** (`codex`, `antigravity`, `cursor`, `devin`, `opencode`), where the dispatcher passes it through as `--timeout-sec`; for `claude` (in-harness `Task`) there is no equivalent knob and the field is advisory. Anything above **600** MUST be dispatched on the background path — see the outer-bound rule in [`parallel-dispatcher.md`](../../agents/parallel-dispatcher.md). |

¹ **Every job MUST have `model` OR `tier`** (at least one). Most jobs carry `tier` (+ optional `effort`) and let the dispatcher resolve the concrete model; a job MAY instead pin an explicit `model` override that skips resolution. A job with neither is a validation failure.

`backend`, `tier`, `effort`, and `model` are execution-layer values. They drive dispatch; they MUST NOT leak into any agent/skill/command frontmatter (`lint-frontmatter.py` + `validate.yml` reject Haiku, and reviewers/agents always carry `model: opus`).

### Tier vocabulary (stable — never changes when models churn)

The ladder splits on **execution vs judgment**, not on how much code a job touches.
Sonnet executes: a spec that already survived brainstorming and planning, HTML/CSS,
Node plumbing, translations, and *reading* code. Opus judges: deciding, and connecting
parts of code to each other. Business logic with many code-level dependencies is Opus
however mechanical each individual edit looks.

| Tier | Strongest fit | Routes to (Balanced) |
|---|---|---|
| `frontier` | The extreme case. Reachable by design, assigned rarely: it is what a **re-attempt escalates into** after a recorded failure, and where interface-design work belongs. | claude `fable`, codex `gpt-5.6-sol`, antigravity top model, cursor `auto`, devin `claude-opus-4.6`, opencode `anthropic/claude-opus-4-6`. Under `cost-aware` it caps at claude `opus`. |
| `deep` | Judgment: architecture, security/auth/payments, coupled business logic, designing tests, external APIs, **ALL reviewers**, shared-foundation Task 0. | claude `opus`, codex `gpt-5.6-sol`, antigravity top model, cursor `auto`, devin `claude-opus-4.6`, opencode `anthropic/claude-opus-4-6`. |
| `standard` | Execution against a spec that is already settled: bounded core/feature build, incl. large isolated codex work. | claude `sonnet` (`opus` under the `conservative` stance), codex `gpt-5.6-terra`, antigravity mid model, cursor `auto`, devin `claude-sonnet-4`, opencode `openai/gpt-5.6-terra`. |
| `light` | Mechanical single-file / docs / i18n / scanning. Also where the pipeline's own **transport** stages run (Gate, Record, Finalize — each one clamped command, verbatim JSON back). | claude `sonnet`, codex `gpt-5.6-luna`, antigravity flash model, cursor `auto`, devin `gpt-5.5`, opencode `opencode/mimo-v2.5-free` (a real credential-free model). |

**Reviewers are not satisfied by `frontier`.** Invariant 3 still demands `tier: deep` or
`model: opus`, because a sealed review receipt must carry a Claude Opus `reviewer_model`.
For the same reason a reviewer is **never** escalated on a re-attempt.

**Escalation.** A job with a recorded non-success result in this run is re-dispatched one
rung up the claude ladder — `sonnet → opus → fable` — and stops there. The signal is the
recorded `results/<id>.json` status, not a counter: an absent result is not a failure. A
model the manifest pinned explicitly is never escalated; escalating a value we did not
choose would be a fabricated routing decision.

`effort ∈ {low, medium, high, xhigh}` is orthogonal to tier. The default pairing (`frontier→high`, `deep→high`, `standard→medium`, `light→low`) is just a default — a task-type may pin a different effort independently. `xhigh` is valid **iff** `backend: codex`; every other backend rejects it with a clear error naming the rule (use `high` instead) — it maps to codex's `model_reasoning_effort=xhigh` (live-verified 2026-07-11 on codex-cli 0.144.1).

Resolution is **stance-aware**: the `standard` Claude row resolves to `sonnet` under `balanced` / `cost-aware` / `claude-only`, and to `opus` under `conservative` — that is what the conservative stance means. `frontier` is `fable` everywhere except `cost-aware`, whose ceiling is `opus`. `deep` (incl. all reviewers + sensitive surfaces) is `opus` in every stance, and `codex`/`antigravity`/`cursor`/`devin`/`opencode` are identical across stances.

The dispatcher reads the manifest's `routing_stance` and passes it (`--stance`) to the resolver on every resolve, along with `--config` for the project map; omitting the stance defaults to `balanced`. **Both were unwired until 3.0.5** — every resolution silently used the built-in balanced defaults, and on `backend: claude` the resolver was not called at all.

### Config `models` map (project `.claude/compound-v.json`)

The concrete model behind each tier lives in a **refreshable** map in the project config — not hardcoded in any job. This is what lets the plugin survive model churn: when models change, refresh the map (`/v:models`), not the manifests. The map is **per-stance** — its shape is `{<stance>: {<backend>: {<tier>: model}}}`. Only the `claude` rows differ across stances (`conservative.claude.standard = opus`; everywhere else `standard` is `sonnet`, and `cost-aware.claude.frontier` caps at `opus`); `codex`/`antigravity`/`cursor`/`devin`/`opencode` are identical in every stance. `opencode`'s cells are full `provider/model` strings (the provider may legitimately differ per tier — no schema change, the resolver already treats every cell as opaque):

```jsonc
"models": {
  "balanced": {
    "claude":      { "frontier": "fable", "deep": "opus",  "standard": "sonnet",                     "light": "sonnet" },
    "codex":       { "deep": "gpt-5.6-sol",                "standard": "gpt-5.6-terra",                "light": "gpt-5.6-luna" },
    "antigravity": { "deep": "Gemini 3.1 Pro (High)",     "standard": "Gemini 3.1 Pro (Low)",        "light": "Gemini 3.5 Flash (Low)" },
    "cursor":      { "deep": "auto",                       "standard": "auto",                        "light": "auto" },
    "devin":       { "deep": "claude-opus-4.6",            "standard": "claude-sonnet-4",              "light": "gpt-5.5" },
    "opencode":    { "deep": "anthropic/claude-opus-4-6",  "standard": "openai/gpt-5.6-terra",         "light": "opencode/mimo-v2.5-free" }
  },
  "cost-aware": {
    "claude":      { "frontier": "opus",  "deep": "opus",  "standard": "sonnet",                     "light": "sonnet" },
    "codex":       { "deep": "gpt-5.6-sol",                "standard": "gpt-5.6-terra",                "light": "gpt-5.6-luna" },
    "antigravity": { "deep": "Gemini 3.1 Pro (High)",     "standard": "Gemini 3.1 Pro (Low)",        "light": "Gemini 3.5 Flash (Low)" },
    "cursor":      { "deep": "auto",                       "standard": "auto",                        "light": "auto" },
    "devin":       { "deep": "claude-opus-4.6",            "standard": "claude-sonnet-4",              "light": "gpt-5.5" },
    "opencode":    { "deep": "anthropic/claude-opus-4-6",  "standard": "openai/gpt-5.6-terra",         "light": "opencode/mimo-v2.5-free" }
  }
  // claude-only mirrors balanced; conservative keeps standard on opus
}
```

The map is **documented, not committed** in this repo (it is project-local config). `/v:init` seeds the per-stance default map so routing works out of the box; `/v:models` discovers available models per backend and rewrites the map. The resolver also **accepts the legacy flat shape** `{<backend>: {<tier>: model}}` (applied to every stance) for backward-compat — it auto-detects which shape it was given. NEVER `haiku` anywhere. Antigravity values are illustrative placeholders refreshed by `agy models`; codex has no list command, so its map is curated + user-overridable; claude uses native tier aliases.

### Resolution (tier → model)

[`scripts/compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) is the resolver the dispatcher runs **before** invoking any backend. Given `--backend`, `--tier`, optional `--effort`, optional `--stance` (default `balanced`, threaded from the manifest's `routing_stance`), and optional `--config`, it returns one JSON object on stdout — `{ "backend", "tier", "model", "effort" }` — using the stance's built-in default map (the one above) that a `--config` cell overrides (per-stance `models.<stance>.<backend>.<tier>` or legacy flat `models.<backend>.<tier>`), and an `--explicit-model` (the manifest `model` override) always wins. It is generic: no backend-specific routing logic baked in. See [`routing-policy.md`](routing-policy.md) for the task-type → (tier, effort) table.

---

## Invariant rules (deterministic — enforced by `compound-v-validate-manifest.py`)

1. **Disjoint writes.** Every file path belongs to exactly one job's `write_allowed`. No glob in two jobs may overlap. Overlap ⇒ validation fails with the colliding pair.
2. **Shared resources → serial Task 0.** Lockfiles, generated code, schema migrations, barrels, and shared type files are not splittable. They go into a single `type: shared_foundation`, `run: serial`, `isolation: direct` job (conventionally `task-0-*`) that no sibling can race. Other jobs `depends_on` it.
3. **Codex ⇒ worktree.** Any job with `backend: codex` MUST have `isolation: worktree`. (Codex's sandbox can only restrict writes to a *directory*, not a file allow-list, so the worktree + `git diff` combo is the only file-scope enforcement.)
4. **Reviewers ⇒ deep.** Any review/reviewer job MUST resolve to the strongest tier — `tier: deep` OR an explicit `model: opus`. (Mirrors the frontmatter rule: reviewers are always Opus; `deep` resolves to `opus` for claude.)
5. **Model OR tier.** Every job MUST carry at least one of `model` or `tier`. A job with neither cannot be dispatched (the resolver has nothing to route on) and fails validation.
6. **Tier / effort enums.** If present, `tier ∈ {deep, standard, light}` and `effort ∈ {low, medium, high, xhigh}`. `xhigh` is valid **iff** `backend: codex`; every other backend rejects it with a clear error naming the rule (use `high` instead). Any other value fails validation.
7. **Parallel ⇒ worktree.** A `run: parallel` job MUST be `isolation: worktree`. `isolation: direct` is only valid with `run: serial`. (A repo-wide `git diff` cannot attribute a parallel direct job's writes to that job, so per-job isolation is mandatory for parallel work.) Hard validation failure.
8. **Required fields + safe ids.** Every top-level required field (`run_id`, `jobs`, `feature`, `acceptance_criteria`, `routing_stance`, `max_parallel`) and every per-job required field (`id`, `title`, `type`, `backend`, `isolation`, `run`, `write_allowed`, `read_allowed`, `acceptance`, plus `model` OR `tier`) must be present; enums must be in range; and each `id`/`run_id` must match `^[A-Za-z0-9._-]+$` (not `.`/`..`) — a `../x` id is a path-traversal vector, rejected before dispatch.
9. **Unclear scope never dispatches.** A job whose scope the planner can't pin returns to planning rather than shipping with a guessed partition.
10. **`read_allowed` auto-includes** Task 0 outputs + the three audit files, so every job can read the shared foundation and the pre-flight findings without listing them.

11. **Triage, on demand (v3.0).** Under `--require-triage`, a missing or malformed `triage` block, a `tier` outside `{DIRECT, SCOPED, FULL}`, or a `taxonomy_digest` that disagrees with the taxonomy on disk is a hard failure. Without the flag the block is ignored entirely.
12. **A scope never resolves to nothing (v3.0).** `test_scope: floor_only` requires a non-empty `test_contract.floor_command`; `test_scope: impacted` requires a non-empty `full_command`; every `impacted_map` entry carries both `when` and `run`.

A violation of rule 1, 3, 4, 5, 6, 7, 8, 11 or 12 is a hard validation failure (non-zero exit + specifics). Rules 2/9/10 are partition-design rules enforced jointly by `partition-reviewer` and the validator.

### Only `write_allowed` is enforced; `read_allowed` is advisory

The scope gate is git-derived, and git tracks **writes**, not reads. So **only `write_allowed` is a hard, enforced boundary** — every changed path is checked against it after every job and any path outside it BLOCKS the run. **`read_allowed` is ADVISORY**: it documents the intended read surface and scopes the worker prompt (the SCOPE LOCK), but git cannot detect that a worker read a file it shouldn't have, so there is no deterministic gate behind it. Treat `read_allowed` as intent + prompt-scoping, never as a guarantee. Do not present it as enforced anywhere.

### Scope-attribution rule (parallel ⇒ worktree, enforced)

The scope gate reads a **repo-wide** `git diff`, so per-job attribution requires per-job isolation. A `worktree` job (its tree holds only its own changes) and a **serial `direct`** job (nothing else writes concurrently) each get a deterministic per-job gate. **Parallel `direct`** jobs sharing one working tree do **not** — each job's per-job gate would also see its siblings' writes, yielding a false BLOCK or an unattributable diff. So the rule is enforced (invariant 7): **`run: parallel` ⇒ `isolation: worktree`; `isolation: direct` ⇒ `run: serial`.** The validator rejects any parallel+direct job.

> Note: batch-granularity gating (run the gate once after a batch against the **union** of the batch's `write_allowed`) remains available as a coarse out-of-batch-leak check, but it cannot attribute a leak to a specific job — so it is a fallback, not the primary path. The primary, enforced path is per-job worktree isolation for every parallel job.

### `direct` mode assumes a clean-ish tree — prefer `worktree` for anything untrusted

`isolation: direct` gates against a pre-dispatch baseline commit **minus** a `--preexisting` snapshot of untracked/ignored paths that existed before the job (so a normal dirty tree does not produce false BLOCKs). That subtraction has an inherent blind spot: a job that **MODIFIES a pre-existing untracked or ignored file** — one already in the `--preexisting` snapshot — is **not flagged**, because the path is subtracted from the changed set whether the job touched it or not. The gate is exact only for *tracked* files (caught by the baseline diff) and *newly created* untracked/ignored files (not in the snapshot).

So **`isolation: worktree` is the safe default for anything untrusted or run on a dirty tree.** A fresh `worktree add HEAD` has **no** pre-existing untracked/ignored files, so nothing is subtracted and the gate is exact — every write, including a modification to a would-be-ignored path, is attributed. `direct` remains **serial-only** (invariant 7) and is intended for **trusted, clean-tree** jobs where the speed of writing in place outweighs the blind spot. When in doubt, route the job to `worktree`.

### `.gitignore` does not blind the scope gate

The gate unions THREE git probes — `git diff --name-only`, `git ls-files --others --exclude-standard` (untracked), **and** `git ls-files --others --ignored --exclude-standard -- .` (gitignored). The third term means a worker that writes a **gitignored** path (e.g. `dist/`, `.env`, `build/`) is still detected and BLOCKED if it falls outside `write_allowed` — an over-broad ignore can no longer hide a worker's writes. Even so, keep the committed run substrate (`docs/superpowers/execution/**`, `docs/superpowers/memory/**`, and any other tracked output a job writes) **un-ignored**, and keep ignores limited to scratch/worktree artifacts.

---

## v2.9 — Conditional `fast_path` block

When Pre-Evaluation offers a proportionate fast-path and the user accepts, the fast-path materializer
(M1) writes a **conditional** manifest carrying an optional top-level `fast_path` block. It is
**absent** on every normal manifest (fully backward-compatible — the validator ignores the block
unless present). A `fast_path` manifest is a single-job manifest with a relaxed spec/plan and a review
modeled as a dispatcher **phase**, not a `jobs` entry.

```yaml
fast_path:
  eligible: true                       # must be true; mirrors the pinned record's FASTPATH_ELIGIBLE
  pre_eval_id: 2026-07-12T101500Z-make-button-red-a1b2
  pre_eval_ref: docs/superpowers/pre-eval/2026-07-12T101500Z-make-button-red-a1b2.json
  localization_ref: docs/superpowers/pre-eval/2026-07-12T101500Z-make-button-red-a1b2.localization.json
  taxonomy_ref: docs/superpowers/execution/<run-id>/taxonomy-snapshot.yaml   # immutable snapshot copied into the run
  taxonomy_digest: "sha256:…"          # content-address of taxonomy_ref (RAW bytes) — MUST equal the record's
  review:                              # the combined SPEC+QUALITY review DECLARATION (a PHASE, not a job)
    backend: claude
    tier: deep                         # backend:claude + tier:deep  OR  model:opus  (CR4-8/CR5-5)
```

| `fast_path` field | Meaning |
|---|---|
| `eligible` | Must be `true`. A `fast_path` block with `eligible` not-true is rejected. |
| `pre_eval_id` | The write-once id; the cross-artifact binding key. MUST match the pinned record and the localization artifact. |
| `pre_eval_ref` | Committed path to the pinned pre-eval record (`schemas/pre-eval-record.schema.json`). |
| `localization_ref` | Committed path (pointer) to the localization artifact. The artifact's canonical-JSON content-digest is verified **record ↔ artifact**; the manifest is tied to it via `write_allowed[0] == localization.resolved_paths[0]` (AC-13). |
| `taxonomy_ref` | Committed path to the **immutable taxonomy snapshot** copied under the run (not a sha of mutable working-tree state; CR2-6/CR4-2). |
| `taxonomy_digest` | `sha256:` content-address of `taxonomy_ref`'s RAW bytes. MUST equal the record's `taxonomy_digest`. Absent/malformed/unreadable ⇒ the pre-eval engine never produces `FASTPATH_ELIGIBLE` in the first place. |
| `review` | The combined SPEC+QUALITY review **declaration** — a dispatcher PHASE outside `jobs`. MUST be `backend: claude` + `tier: deep` **OR** an explicit `model: opus`. |

### What a fast-path manifest looks like

- **(a) Minimal committed spec/plan stub.** `spec_path`/`plan_path` point to committed stubs the
  materializer wrote — not the full brainstorm output. Still real, committed files.
- **(b) Exactly ONE implementer job**, and the combined SPEC+QUALITY review is a **dispatcher phase**
  (the `fast_path.review` declaration), NOT a second `jobs` entry. A second job under a fast-path
  manifest is a validation failure. The INTEGRATION pass is vacuous (single job, no seams) →
  auto-pass **with recorded rationale**; SPEC+QUALITY run as one combined Opus pass on the tiny diff.
- **(c)** `localization_ref` resolves to a committed artifact.
- **(d)** an **immutable taxonomy snapshot** lives under the run and is referenced by `taxonomy_ref` +
  `taxonomy_digest`.
- **Sentinel audits.** `audits` still validates as a non-empty dict, but each entry is a tiny
  **block-YAML** skip-record `{skipped: true, reason: fastpath, localization: <path>,
  taxonomy_version: …}` — auditable, not a silent null. (Flow-`{}` mappings are rejected: the
  `_mini_yaml` fallback mis-parses them — use block YAML.)
- **Single-literal-path partition.** The sole `write_allowed` entry MUST be **exactly one literal
  normalized path** — no glob metachar (`*?[`), and not shared/generated/config/migration (classified
  via the shared taxonomy loader against the **pinned snapshot**, not the working tree).

### Cross-artifact binding the validator enforces (AC-13/CR2-3)

The validator (C1) checks, for a `fast_path` manifest:

- the sole `write_allowed` literal **==** `localization.resolved_paths[0]` (this is what ties the
  manifest to the localization artifact — the manifest carries a `localization_ref` pointer, not a
  copy of the localization digest);
- `pre_eval_id` and `taxonomy_digest` are **equal** across the manifest and the pinned pre-eval
  record (and `taxonomy_digest` also matches the pinned taxonomy snapshot's content-address);
- the `FASTPATH_ELIGIBLE` decision is bound via the manifest's `fast_path.eligible: true` **and** the
  record's `decision == "FASTPATH_ELIGIBLE"` (the localization artifact carries no decision field);
- the **localization content-digest** is verified **record ↔ artifact** (plus the artifact's own
  self-digest); the record's self-digest is verified too.

A mismatch on any field **fails validation** (tampering fixtures required). Otherwise a manifest
could cite a safe CSS localization while authorizing a *different* file the scope gate would then
happily enforce. Digest conventions are single-sourced in
[`pre-eval-config.md`](../../docs/superpowers/architecture/pre-eval-config.md) §2.

### Two validation modes (Lifecycle protocol / CR4-1)

The validator runs in one of two modes for a `fast_path` manifest (a `fast_path` manifest with **no
explicit mode is rejected** — ambiguity is fail-closed; a normal manifest is validated mode-lessly as
before):

- **`--mode pre-dispatch`** — validate the review **DECLARATION** (`backend: claude` + `tier: deep`
  **OR** `model: opus`; CR4-8/CR5-5) + all cross-artifact bindings + containment, and **forbid** any
  review **receipt** (it cannot exist yet).
- **`--mode post-review`** — require + verify the dispatcher-generated **invocation receipt**
  (`schemas/fastpath-review-receipt.schema.json`) naming the resolved model **before**
  `REVIEWED`/`MERGED`. Reviewer-opus is proven by resolving the declaration through the real resolver
  against the project config and requiring the concrete result == **Claude Opus** (a
  `models.<stance>.claude.deep` override that isn't opus fails; CR5-5).

### Path containment (CR4-6)

Every `*_ref` and the sole `write_allowed` literal MUST be: **normalized**, **repo-relative** (no
absolute path, no `..` segment), **realpath-under-repo-root**, and a **committed regular file** — NOT
an escaping symlink. The validator reuses `scope-check.py`'s escaping-symlink scan; it does **not**
rely on `_seg_is_literal` alone (that only rejects `*?[`, not traversal or symlinks).

> **Reviewer invariant is untouched.** The savings come from skipping the brainstorm + 3 pre-flights +
> multi-job partition, NEVER from a cheaper reviewer — reviewers stay `deep`/opus (invariant 4). The
> git-diff scope gate, the test floor, and a proportionate (not zero) review are **never** skipped.

---

## v2.12 — Optional `usage` on `job_result` (measured-only)

Each job's `job_result` ([`schemas/job_result.schema.json`](../../schemas/job_result.schema.json)) MAY carry an
optional `usage` object recording the job's token/advisor accounting. It is **worker-sourced and
informational — exactly like `summary`, NEVER git-derived enforcement.** The scope gate and every DONE
decision ignore it; nothing routes on it. It is a property only (never `required`), so pre-2.12
results without it stay valid.

```yaml
usage:
  input_tokens: 12480      # int | null
  output_tokens: 3120      # int | null
  advisor_calls: 1         # int | null
  backend: codex           # string
  measured: true           # bool
```

| Field | Type | Meaning |
|---|---|---|
| `input_tokens` | int \| null | Total input/prompt tokens for the job, summed across the backend's own usage events. `null` when not measured. |
| `output_tokens` | int \| null | Total output/completion tokens for the job, summed across the backend's own usage events. `null` when not measured. |
| `advisor_calls` | int \| null | Times the executor actually consulted the read-only advisor subagent. **Worker-COUNTED** by the advisor worker (not derived from any CLI turn/iteration count, which is turns, not advisor consults), and set only when advisor mode ran; `null` otherwise. |
| `backend` | string | Backend the usage was extracted for (`codex` \| `opencode` \| `cursor` \| `agy`/`antigravity` \| `claude` \| `devin`). |
| `measured` | bool | `true` **only** when real token counts were extracted from the backend's structured usage events; `false` when the backend exposes nothing (see below). |

### Measured-only contract (anti-ruflo)

`usage` records **only REAL measured backend output** — never an estimate, never a fabricated or
inferred number. Where a backend exposes no machine-readable usage, or its events log is
absent/empty/unparseable, the worker emits `measured: false` with **null token counts** — a null is
honest; a made-up number is not.

| Backend | Measured? | Source |
|---|---|---|
| `codex` | **yes** | sum of `turn.completed.usage` across all turns (`--json`) |
| `opencode` | **yes** | sum of `step_finish.part.tokens` (`--format json`) |
| `cursor` | **yes** | `result.usage` (needs `-f`/trust) |
| `agy` (antigravity) | **no** → `measured:false`, null tokens | no structured usage (`--print` only) |
| `claude` via `Task` subagent | **no** → `measured:false`, null tokens | in-harness, returns text only |
| `devin` | **no** → `measured:false`, null tokens | no machine-readable usage |

The three measured backends (`codex`, `opencode`, `cursor`) each use a different casing/shape, so a
single normalizer handles them. The worker's stdout stays EXACTLY one `job_result` JSON — the
extractor reads the events log into a variable and never writes stdout.

### Extraction and aggregation

- [`scripts/compound-v-usage-extract.py`](../../scripts/compound-v-usage-extract.py) — `(backend,
  events_log_path) → usage`. The per-backend normalizer the codex/opencode workers call before
  emitting `job_result`; unknown/unmeasured backends and missing logs return `measured:false` + null
  tokens. Ships with a `--selftest` over fixtures captured from real CLI output.
- [`scripts/compound-v-usage-aggregate.py`](../../scripts/compound-v-usage-aggregate.py) — scans a
  run's `results/*.json`, summing `usage` per ticket / feature / epic. `measured:false` jobs are
  counted as **unmeasured** (an honest count), never folded in as zero. `/v:status` surfaces the
  rollup in a usage column; degrade-safe (results absent ⇒ shows `—`, never breaks the table).

---

## v3.0 — `triage` (Feature A2) and `test_contract` (Feature B2)

Two optional top-level blocks land in 3.0. Both are **absent-valid**, so every manifest committed
before 3.0 keeps validating unchanged; `triage` becomes mandatory the moment the validator is called
with `--require-triage`.

### The `triage` block — the mechanical consumer of the tier

A triage decision is prose until something refuses to run without it. That something is this block:

```yaml
triage:
  tier: SCOPED                              # DIRECT | SCOPED | FULL
  pre_eval_id: 2026-09-01T101500Z-slug-a1b2 # names the committed pre-eval record
  taxonomy_digest: "sha256:<64-hex>"        # content-address of the taxonomy's RAW bytes
  decided_at: "2026-09-01T10:15:00Z"        # ISO-8601
```

| `triage` field | Meaning |
|---|---|
| `tier` | `DIRECT` \| `SCOPED` \| `FULL`. Compared **verbatim** downstream, so the value is case-sensitive — `direct` is not `DIRECT`. |
| `pre_eval_id` | The write-once id of the record at `docs/superpowers/pre-eval/<id>.json`. It becomes a path segment, so `/`, `\`, `.` and `..` are rejected. |
| `taxonomy_digest` | `sha256:<64-hex>` over the RAW bytes of the impact taxonomy that produced the decision. Verified against `.claude/compound-v-impact-taxonomy.yaml` (override with `--taxonomy FILE`) through the shared `compound-v-taxonomy.py` primitive, so a producer and this consumer can never diverge. |
| `decided_at` | ISO-8601 timestamp. A trailing `Z` is stripped before parsing: Python 3.9 — the CI floor — rejects the Zulu suffix that every producer writes. |

Unknown keys inside the block are rejected. A `taxonomy-digest` typo would otherwise pass silently
and leave the digest unchecked, which is the one failure this block exists to prevent.

**When it is required, and why not sooner.** `--require-triage` ships **default OFF in every mode**.
A mode-scoped default (on for `--mode pre-dispatch`) was designed and removed as circular twice over:
the block is emitted by the fast-path materializer, so defaulting it on would turn the e2e suite red
inside the very task that adds the emitter — and because `pre-dispatch` is only ever selected for
`fast_path` manifests, an ordinary future run would inherit exactly the mode-less pass 3.0 takes once
during bootstrap, permanently rather than once.

The closure is behavioural and load-bearing: **`/v:dispatch` passes `--require-triage` in every mode,
on every live dispatch.** The CI historical sweep stays mode-less and flag-less, which is what keeps
the committed run manifests and the shipped example valid **without back-filling** a `triage` block
into them — a reconstructed audit trail is the fabricated-evidence pattern, not a repair.

Under the flag, each of these is a hard failure: a **missing** block, a **malformed** one (non-mapping,
missing field, unknown key, unparseable `decided_at`, mis-shaped digest), a `tier` **outside the enum**,
and a `taxonomy_digest` that **does not match** the taxonomy bytes on disk. An **absent or unreadable**
taxonomy also fails — a record whose rules cannot be found has outlived them, and that is the case the
digest exists to catch, so it fails closed rather than skipping the comparison.

### The `test_contract` block and per-job `test_scope`

```yaml
test_contract:
  floor_command: "bash tests/run-floor.sh"   # always runs, every tier
  full_command:  "bash tests/run-all.sh"
  impacted_map:
    - when: "scripts/compound-v-*.py"
      run:  "python3 {path} --selftest"

jobs:
  - id: task-1
    test_scope: impacted                     # full | impacted | floor_only
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `test_contract` | map | no | Absent ⇒ no declared contract; every job runs `full`. |
| `test_contract.floor_command` | string | no¹ | The merge-blocking floor. Runs at every tier. |
| `test_contract.full_command` | string | no¹ | The full suite. Also the resolution of any changed path that matches no `when` glob. |
| `test_contract.impacted_map` | list | no | Declarative `{when, run}` rules. **Both fields are mandatory per entry** — a half-declared rule selects nothing. Unknown keys are rejected. |
| `test_scope` (per job) | enum | no | `full` \| `impacted` \| `floor_only`. **Absent ⇒ `full`**, which is what every pre-3.0 manifest relies on. |

¹ Conditionally required by the two resolution rules the validator enforces, so that a scope can never
resolve to running **nothing**:

- a job with `test_scope: floor_only` requires a **non-empty `floor_command`** — `floor_only` means
  *only the floor*, never nothing;
- a job with `test_scope: impacted` requires a **non-empty `full_command`**, because a changed path
  matching no `when` glob is unknown blast radius and resolves to the full suite.

Overlapping `when` globs **union** (every matching `run` is selected); first-match-wins would silently
drop coverage the map explicitly declares.

**What the floor is, said without varnish.** The floor is an early-feedback optimization. It does not
restore what the full suite guaranteed — CI does. The union of impacted, previously-failing and
newly-added structurally omits every existing, previously-passing test the declared map fails to
select, so an indirect break can pass the floor and be caught only by the merge-blocking CI run. Do not
write, anywhere, that the floor preserves pre-merge safety.

---

## Relationship to the rest of the pipeline

- **Phase 2 (disjoint partitioning)** emits this manifest (not only prose).
- **Phase 3 / the dispatcher** reads it and dispatches each job to the named backend via [`backend-launcher`](../backend-launcher/SKILL.md), honoring `depends_on`, `run`, and `max_parallel`.
- **The scope gate** checks every job's `files_changed` against its `write_allowed` after dispatch.
- **The state machine** tracks per-job status in `state.json` alongside this manifest in the run dir.
- Each job's `job_result` conforms to [`schemas/job_result.schema.json`](../../schemas/job_result.schema.json).
