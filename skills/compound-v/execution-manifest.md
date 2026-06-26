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
| `backend` | enum | yes | `claude` \| `codex` \| `antigravity`. **Execution-layer data — NEVER appears in any frontmatter.** |
| `tier` | enum | yes¹ | `deep` \| `standard` \| `light`. The **intent** the routing policy assigns; the dispatcher resolves it to a concrete model. Stable vocabulary that survives model churn. |
| `effort` | enum | no | `low` \| `medium` \| `high`. Orthogonal reasoning-effort hint. Default pairing `deep→high`, `standard→medium`, `light→low`, but independently tunable per task-type. For `codex` it maps to `-c model_reasoning_effort=<effort>`; for `claude` it is advisory (the `Task` path has no separate effort flag). |
| `model` | string | no¹ | Explicit override, e.g. `opus`, `sonnet`, `gpt-5.5`. When present it **skips resolution** (the manifest pins the model directly). Execution-layer data — never in frontmatter. Backward-compatible: pre-tier manifests carrying only `model` remain valid. |
| `isolation` | enum | yes | `direct` \| `worktree`. |
| `run` | enum | yes | `serial` \| `parallel`. |
| `depends_on` | string[] | no | Job ids that must finish first (defaults to empty). |
| `write_allowed` | string[] | yes | Glob list this job MAY write. The scope gate enforces it. |
| `read_allowed` | string[] | yes | Glob list this job MAY read. Auto-includes Task 0 outputs + the three audits. |
| `acceptance` | string[] | yes | This job's narrow acceptance, checked in its per-task review. |

¹ **Every job MUST have `model` OR `tier`** (at least one). Most jobs carry `tier` (+ optional `effort`) and let the dispatcher resolve the concrete model; a job MAY instead pin an explicit `model` override that skips resolution. A job with neither is a validation failure.

`backend`, `tier`, `effort`, and `model` are execution-layer values. They drive dispatch; they MUST NOT leak into any agent/skill/command frontmatter (`lint-frontmatter.py` + `validate.yml` reject Haiku, and reviewers/agents always carry `model: opus`).

### Tier vocabulary (stable — never changes when models churn)

| Tier | Strongest fit | Routes to (Balanced) |
|---|---|---|
| `deep` | Strongest reasoning: architecture, security/auth/payments, designing tests, external APIs, **ALL reviewers**, shared-foundation Task 0. | claude `opus`, codex `gpt-5.5`, antigravity top model. |
| `standard` | Bounded core/feature build, incl. large isolated codex work. | claude `opus`, codex `gpt-5.5`, antigravity mid model. |
| `light` | Mechanical single-file / docs / i18n. | claude `sonnet`, codex spark model, antigravity flash model. |

`effort ∈ {low, medium, high}` is orthogonal to tier. The default pairing (`deep→high`, `standard→medium`, `light→low`) is just a default — a task-type may pin a different effort independently.

### Config `models` map (project `.claude/compound-v.json`)

The concrete model behind each tier lives in a **refreshable** map in the project config — not hardcoded in any job. This is what lets the plugin survive model churn: when models change, refresh the map (`/v:models`), not the manifests. Shape:

```jsonc
"models": {
  "claude":      { "deep": "opus",                      "standard": "opus",                       "light": "sonnet" },
  "codex":       { "deep": "gpt-5.5",                    "standard": "gpt-5.5",                     "light": "gpt-5.3-codex-spark" },
  "antigravity": { "deep": "Gemini 3.1 Pro (High)",     "standard": "Gemini 3.1 Pro (Medium)",     "light": "Gemini 3.1 Flash" }
}
```

The map is **documented, not committed** in this repo (it is project-local config). `/v:init` seeds the default map so routing works out of the box; `/v:models` discovers available models per backend and rewrites the map. NEVER `haiku` anywhere. Antigravity values are illustrative placeholders refreshed by `agy models`; codex has no list command, so its map is curated + user-overridable; claude uses native tier aliases.

### Resolution (tier → model)

[`scripts/compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) is the resolver the dispatcher runs **before** invoking any backend. Given `--backend`, `--tier`, optional `--effort`, and optional `--config`, it returns one JSON object on stdout — `{ "backend", "tier", "model", "effort" }` — using a built-in default map (the one above) that an `--config` `models.<backend>.<tier>` entry overrides, and an `--explicit-model` (the manifest `model` override) always wins. It is generic: no backend-specific routing logic baked in. See [`routing-policy.md`](routing-policy.md) for the task-type → (tier, effort) table.

---

## Invariant rules (deterministic — enforced by `compound-v-validate-manifest.py`)

1. **Disjoint writes.** Every file path belongs to exactly one job's `write_allowed`. No glob in two jobs may overlap. Overlap ⇒ validation fails with the colliding pair.
2. **Shared resources → serial Task 0.** Lockfiles, generated code, schema migrations, barrels, and shared type files are not splittable. They go into a single `type: shared_foundation`, `run: serial`, `isolation: direct` job (conventionally `task-0-*`) that no sibling can race. Other jobs `depends_on` it.
3. **Codex ⇒ worktree.** Any job with `backend: codex` MUST have `isolation: worktree`. (Codex's sandbox can only restrict writes to a *directory*, not a file allow-list, so the worktree + `git diff` combo is the only file-scope enforcement.)
4. **Reviewers ⇒ deep.** Any review/reviewer job MUST resolve to the strongest tier — `tier: deep` OR an explicit `model: opus`. (Mirrors the frontmatter rule: reviewers are always Opus; `deep` resolves to `opus` for claude.)
5. **Model OR tier.** Every job MUST carry at least one of `model` or `tier`. A job with neither cannot be dispatched (the resolver has nothing to route on) and fails validation.
6. **Tier / effort enums.** If present, `tier ∈ {deep, standard, light}` and `effort ∈ {low, medium, high}`. Any other value fails validation.
7. **Unclear scope never dispatches.** A job whose scope the planner can't pin returns to planning rather than shipping with a guessed partition.
8. **`read_allowed` auto-includes** Task 0 outputs + the three audit files, so every job can read the shared foundation and the pre-flight findings without listing them.

A violation of rule 1, 3, 4, 5, or 6 is a hard validation failure (non-zero exit + specifics). Rules 2/7/8 are partition-design rules enforced jointly by `partition-reviewer` and the validator.

---

## Relationship to the rest of the pipeline

- **Phase 2 (disjoint partitioning)** emits this manifest (not only prose).
- **Phase 3 / the dispatcher** reads it and dispatches each job to the named backend via [`backend-launcher`](../backend-launcher/SKILL.md), honoring `depends_on`, `run`, and `max_parallel`.
- **The scope gate** checks every job's `files_changed` against its `write_allowed` after dispatch.
- **The state machine** tracks per-job status in `state.json` alongside this manifest in the run dir.
- Each job's `job_result` conforms to [`schemas/job_result.schema.json`](../../schemas/job_result.schema.json).
