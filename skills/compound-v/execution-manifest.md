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

`acceptance_criteria` is feature-level and gates the final integration review. Each job *also* carries its own narrow `acceptance` (below) for its per-task review — do not confuse the two.

---

## Per-job fields (`jobs[]`)

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | string | yes | Unique job id within the run (e.g. `task-1-editor-ui`). |
| `title` | string | yes | One-line job title. |
| `type` | string | yes | Job-type token used by the routing policy (e.g. `shared_foundation`, `bounded_crud`, `large_isolated`, `core_slice`, `mechanical_refactor`, `docs`, `tests_new`, `external_api`, `review`). |
| `backend` | enum | yes | `claude` \| `codex` \| `antigravity` \| `cursor`. **Execution-layer data — NEVER appears in any frontmatter.** (`antigravity`/`cursor` are opt-in, lower-trust, no kernel sandbox ⇒ always `worktree`.) |
| `tier` | enum | yes¹ | `deep` \| `standard` \| `light`. The **intent** the routing policy assigns; the dispatcher resolves it to a concrete model. Stable vocabulary that survives model churn. |
| `effort` | enum | no | `low` \| `medium` \| `high` \| `xhigh`. Orthogonal reasoning-effort hint. Default pairing `deep→high`, `standard→medium`, `light→low`, but independently tunable per task-type. For `codex` it maps to `-c model_reasoning_effort=<effort>`; for `claude` it is advisory (the `Task` path has no separate effort flag). `xhigh` is valid **iff** `backend: codex`; every other backend rejects it with a clear error naming the rule (use `high` instead). |
| `model` | string | no¹ | Explicit override, e.g. `opus`, `sonnet`, `gpt-5.6-sol`. When present it **skips resolution** (the manifest pins the model directly). Execution-layer data — never in frontmatter. Backward-compatible: pre-tier manifests carrying only `model` remain valid. |
| `isolation` | enum | yes | `direct` \| `worktree`. **`run: parallel` ⇒ `worktree`** (per-job scope attribution); `direct` is only valid with `run: serial`. |
| `run` | enum | yes | `serial` \| `parallel`. A `parallel` job MUST be `isolation: worktree` (see the rule above). |
| `depends_on` | string[] | no | Job ids that must finish first (defaults to empty). |
| `write_allowed` | string[] | yes | Glob list this job MAY write. The scope gate **enforces** it (git-derived). |
| `read_allowed` | string[] | yes | Glob list this job MAY read. **ADVISORY only — NOT enforced** (git cannot track reads). Documents intent + scopes the prompt. Auto-includes Task 0 outputs + the three audits. |
| `acceptance` | string[] | yes | This job's narrow acceptance, checked in its per-task review. |

¹ **Every job MUST have `model` OR `tier`** (at least one). Most jobs carry `tier` (+ optional `effort`) and let the dispatcher resolve the concrete model; a job MAY instead pin an explicit `model` override that skips resolution. A job with neither is a validation failure.

`backend`, `tier`, `effort`, and `model` are execution-layer values. They drive dispatch; they MUST NOT leak into any agent/skill/command frontmatter (`lint-frontmatter.py` + `validate.yml` reject Haiku, and reviewers/agents always carry `model: opus`).

### Tier vocabulary (stable — never changes when models churn)

| Tier | Strongest fit | Routes to (Balanced) |
|---|---|---|
| `deep` | Strongest reasoning: architecture, security/auth/payments, designing tests, external APIs, **ALL reviewers**, shared-foundation Task 0. | claude `opus`, codex `gpt-5.6-sol`, antigravity top model, cursor `auto`. |
| `standard` | Bounded core/feature build, incl. large isolated codex work. | claude `opus` (`sonnet` under the `cost-aware` stance), codex `gpt-5.6-terra`, antigravity mid model, cursor `auto`. |
| `light` | Mechanical single-file / docs / i18n. | claude `sonnet`, codex `gpt-5.6-luna`, antigravity flash model, cursor `auto`. |

`effort ∈ {low, medium, high, xhigh}` is orthogonal to tier. The default pairing (`deep→high`, `standard→medium`, `light→low`) is just a default — a task-type may pin a different effort independently. `xhigh` is valid **iff** `backend: codex`; every other backend rejects it with a clear error naming the rule (use `high` instead) — it maps to codex's `model_reasoning_effort=xhigh` (live-verified 2026-07-11 on codex-cli 0.144.1).

Resolution is **stance-aware**: the `standard` Claude row resolves to `opus` under the `balanced` stance and `sonnet` under `cost-aware` (the resolver's `cost-aware.claude.standard = sonnet`; `cost-aware.claude.deep` stays `opus`). The dispatcher reads the manifest's `routing_stance` and passes it (`--stance`) to the resolver on every resolve; omitting it defaults to `balanced`. Only the `standard` Claude cell shifts — `deep` (incl. all reviewers + sensitive surfaces) is `opus` in every stance, and `codex`/`antigravity`/`cursor` are identical across stances.

### Config `models` map (project `.claude/compound-v.json`)

The concrete model behind each tier lives in a **refreshable** map in the project config — not hardcoded in any job. This is what lets the plugin survive model churn: when models change, refresh the map (`/v:models`), not the manifests. The map is **per-stance** — its shape is `{<stance>: {<backend>: {<tier>: model}}}`. Only the `claude` rows differ across stances (`cost-aware.claude.standard = sonnet`; everywhere else `standard` is `opus`); `codex`/`antigravity`/`cursor` are identical in every stance:

```jsonc
"models": {
  "balanced": {
    "claude":      { "deep": "opus",                      "standard": "opus",                       "light": "sonnet" },
    "codex":       { "deep": "gpt-5.6-sol",                "standard": "gpt-5.6-terra",                "light": "gpt-5.6-luna" },
    "antigravity": { "deep": "Gemini 3.1 Pro (High)",     "standard": "Gemini 3.1 Pro (Low)",        "light": "Gemini 3.5 Flash (Low)" },
    "cursor":      { "deep": "auto",                       "standard": "auto",                        "light": "auto" }
  },
  "cost-aware": {
    "claude":      { "deep": "opus",                      "standard": "sonnet",                     "light": "sonnet" },
    "codex":       { "deep": "gpt-5.6-sol",                "standard": "gpt-5.6-terra",                "light": "gpt-5.6-luna" },
    "antigravity": { "deep": "Gemini 3.1 Pro (High)",     "standard": "Gemini 3.1 Pro (Low)",        "light": "Gemini 3.5 Flash (Low)" },
    "cursor":      { "deep": "auto",                       "standard": "auto",                        "light": "auto" }
  }
  // conservative + claude-only mirror balanced
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

A violation of rule 1, 3, 4, 5, 6, 7, or 8 is a hard validation failure (non-zero exit + specifics). Rules 2/9/10 are partition-design rules enforced jointly by `partition-reviewer` and the validator.

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
| `localization_ref` | Committed path to the localization artifact. Its canonical-JSON content-digest is bound across manifest+record+artifact (AC-13). |
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

- the sole `write_allowed` literal **==** `localization.resolved_paths[0]`;
- `pre_eval_id`, the `FASTPATH_ELIGIBLE` decision, `taxonomy_digest`, and the **localization
  content-digest** are **equal** across the manifest, the pinned pre-eval record, and the
  localization artifact.

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

## Relationship to the rest of the pipeline

- **Phase 2 (disjoint partitioning)** emits this manifest (not only prose).
- **Phase 3 / the dispatcher** reads it and dispatches each job to the named backend via [`backend-launcher`](../backend-launcher/SKILL.md), honoring `depends_on`, `run`, and `max_parallel`.
- **The scope gate** checks every job's `files_changed` against its `write_allowed` after dispatch.
- **The state machine** tracks per-job status in `state.json` alongside this manifest in the run dir.
- Each job's `job_result` conforms to [`schemas/job_result.schema.json`](../../schemas/job_result.schema.json).
