---
paths:
  - "docs/superpowers/execution/**/manifest.yaml"
  - "examples/*.yaml"
---

# Execution manifests

Sourced from `CONVENTIONS.md` §"YAML in manifests" and §"The test contract: a scope may never
  resolve to nothing". (`CONVENTIONS.md:113-121`, `CONVENTIONS.md:89-100`)

- Write a multi-line job `body` as a **block scalar** (`body: |`) — the shape every job in the shipped
  example uses, and the only one that keeps a paragraph's line breaks; a quoted flow scalar folds them
  into one line. (`CONVENTIONS.md:115-117`, `examples/manifest.example.yaml:66-69`)
- `body` (or one of its `description` / `prompt` / `spec` aliases) is **required**: a job with none of
  them is refused at emit, because a prompt carrying lanes and no instructions asks the worker to
  invent the task — and an invented task that stays inside its lane passes every gate here.
  (`CONVENTIONS.md:118-121`, `skills/compound-v/execution-manifest.md:58`)
- `test_scope: floor_only` requires a non-empty `floor_command` and `test_scope: impacted` requires a
  non-empty `full_command`, so no scope can resolve to running nothing.
  (`skills/compound-v/execution-manifest.md:597-604`)
- Overlapping `impacted_map` `when` globs **union**; first-match-wins would silently drop coverage the
  map explicitly declares. (`skills/compound-v/execution-manifest.md:606-607`)
- Never write, anywhere, that the floor preserves pre-merge safety: the floor is early feedback, and
  the merge-blocking CI run is what restores the full-suite guarantee.
  (`skills/compound-v/execution-manifest.md:617-621`)
- Every tracked manifest is validated against the invariant gate — the shipped example and every
  `docs/superpowers/execution/*/manifest.yaml`. (`.github/workflows/validate.yml:120-134`)
- Every committed run directory carries a committed `state.json`; the historical gaps are allowlisted
  by id rather than back-filled, because a reconstructed audit trail is fabricated evidence, not a
  repair. (`.github/workflows/validate.yml:136-159`)
