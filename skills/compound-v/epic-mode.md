# Epic Mode — chain many features into one autonomous build (PRD §8 / v1.1)

A v1.0 run executes **ONE plan (one feature)**. An **epic** chains several: an ordered set of features, each run through the **full v1.0 pipeline** (spec → 3 pre-flights → writing-plans + partition → manifest → dispatch → 3-pass review), in **dependency order**, accumulating onto **one branch**. "Build a whole app."

It is the **same discipline one level up**. Where [`state-machine.md`](state-machine.md) is the per-run spine (`state.json` over jobs), epic mode adds an **epic spine** (`epic-state.json` over *features*) — resumable, topological, no daemon. The driver is [`commands/v-epic.md`](../../commands/v-epic.md) (`/v:epic`); the deterministic state spine is [`scripts/compound-v-epic-state.py`](../../scripts/compound-v-epic-state.py).

---

## What an epic is

- **A feature** = one `{id, title, depends_on}` — a vertical product capability that is a *real* v1.0 unit of work (a spec the pre-flights and partition can chew on).
- **An epic** = an ordered set of features with cross-feature dependencies, run feature-by-feature onto a single branch, finished once with one integration review.

One feature = **one v1.0 run** (its own run dir, its own manifest, its own scope gate, review, and memory). The epic layer only **orders and chains** those runs; it never reaches inside a feature's pipeline.

---

## The feature-decomposition + dependency-ordering model

1. **Decompose the product into features.** Split by **feature slice** (a vertical capability — `auth`, `api`, `ui`), not by layer. Each feature should stand as its own spec. Over-coarse features can't be partitioned; over-fine features drown the epic in cross-feature deps. Aim for independent-ish slices.
2. **Capture cross-feature dependencies** in each feature's `depends_on` (e.g. `api` depends_on `auth`; `ui` depends_on `api`). A dependency means "feature B's spec/partition assumes feature A's code already exists on the branch."
3. **Brainstorm a real spec PER feature, UP FRONT.** Before the autonomous loop, run `superpowers:brainstorming` for **each** feature and save a real spec file (feature-level Acceptance Criteria) to `docs/superpowers/execution/epics/<epic-id>/specs/<feature-id>.md`. Each feature carries that path as **`spec_path`** in `features.json` and `epic-state.json`. This is the **only** human-interactive phase — every spec is written and approved *here*, once, so the loop never pauses to brainstorm. That up-front batching is what resolves the central tension: the epic stays genuinely **autonomous** *and* every feature still runs from a **real, approved spec**.
4. **Gate the decomposition before init (one level up from partition-review).** A weak decomposition is the #1 way an epic fails downstream, so critique the feature DAG twice:
   - **Deterministic lint:** `compound-v-epic-state.py --lint --features <…>/features.json` prints structural warnings — an **ISLAND** feature (no `depends_on` *and* no dependents → a likely missed dependency, or it belongs in its own epic) and an **over-coupled / LAYER** feature (depends on most others → a layer, not a vertical slice) — plus any hard validation errors.
   - **By judgment:** are these *real* vertical slices? Are the `depends_on` edges correct **and complete**? A missing edge means a feature builds before its prerequisite. Fix `features.json` until lint is clean and the split is sound.
5. **Topological order is enforced by the state spine, not by you.** `compound-v-epic-state.py --init --require-specs` validates ids (`A-Za-z0-9._-`, no `.`/`..`), rejects **dangling refs**, **duplicate ids**, and **dependency cycles**, and — with `--require-specs` — **refuses to start unless every feature has an existing `spec_path`** (deterministic enforcement that no feature enters the loop without an approved spec). `--next` returns the next feature that is `pending` **and** has all `depends_on` `done`, in topological order — or a stop reason.

A feature advances through `pending → running → done` (or `failed`). The epic rolls up to `running | done | blocked`. The full CLI:

| Command | Effect |
|---|---|
| `--lint --features F.json` | structural decomposition warnings (**ISLAND** = no deps + no dependents; **LAYER** = depends on most others) **plus** hard validation; advisory gate before init |
| `--init --require-specs --features F.json --epic-id E --title T --out S` | validate + write `epic-state.json`, every feature `pending`; `--require-specs` **refuses to start unless every feature has an existing `spec_path`** |
| `--next --state S` | print `{"feature": <runnable\|null>, "reason": "runnable\|epic complete\|epic blocked: …\|epic needs reconcile: …"}` |
| `--update --feature F --status {pending\|running\|done\|failed} [--run-id R] --state S` | set a feature's status/run-id; roll up epic status |
| `--stats --state S` | progress counts: `total / done / pending / running / failed / remaining` |
| `--summary --state S` | render the feature table |

`--next` is **read-only** and never an error: a `null` feature with a stop reason is *information*, not failure. Mutate state only through `--update`; never hand-edit `epic-state.json`.

**The loop is fail-fast and reconcile-strict** (the guard order in `next_feature` encodes it):

- **`epic blocked`** — any `failed` feature halts the WHOLE epic, even independent pending features; the loop never autonomously routes around a failure (it may be systemic). Recover by retrying it (`--update --feature <id> --status pending`) or dropping it, then re-run.
- **`epic needs reconcile`** — a feature is still `running`. Because epic mode is **sequential**, `--next` is only called between features, so a `running` feature on resume means that feature's run **crashed mid-pipeline**. **Reconcile by resuming first — don't discard half-built work:** the crashed feature ran a *normal v1.0 run* with its own crash-resume, so run [`/v:resume <run-id>`](../../commands/v-resume.md) (via the recorded `run_id`) to re-dispatch only that run's incomplete jobs; if it completes, mark the feature `--status done`. Only if the run cannot be recovered, fall back to `--status pending` (full restart from the spec) or `--status failed` (abandon). Never leave a feature `running` across a resume.

**The loop runs under an autonomy budget** — `MAX_FEATURES` per `/v:epic` invocation (**default 1**: build one feature, then checkpoint). An epic is *N full v1.0 runs*, so the budget is the **cost ceiling** and the deliberate **human-in-the-loop** point. When this invocation's budget is spent, the epic **STOPS** and reports `compound-v-epic-state.py --stats --state <…>` (done / remaining) for the human to review the accumulated diff and re-run `/v:epic` to continue. Raise `MAX_FEATURES` only when the user wants more autonomy per run.

`epic-state.json` shape:

```json
{
  "epic_id": "2026-06-27-notes-app",
  "title": "Notes app",
  "status": "running",
  "features": [
    { "id": "auth", "title": "Auth",     "depends_on": [],       "spec_path": "specs/auth.md", "status": "done",    "run_id": "2026-06-27-auth" },
    { "id": "api",  "title": "Notes API", "depends_on": ["auth"], "spec_path": "specs/api.md",  "status": "running", "run_id": "2026-06-27-api" },
    { "id": "ui",   "title": "Notes UI",  "depends_on": ["api"],  "spec_path": "specs/ui.md",   "status": "pending", "run_id": null }
  ]
}
```

---

## One feature = one full v1.0 run

When `--next` returns a runnable feature, mark it `running`, then run it through the **entire v1.0 pipeline on the current branch** — nothing about a feature's run changes because it is inside an epic. The one difference: the pipeline **starts from the feature's already-approved `spec_path`** — it does **not** brainstorm inside the loop, because every spec was batched + approved up front:

```
read spec_path (the pre-approved feature spec — NO brainstorm in the loop)
   ▼
[1A archaeology ∥ 1B domain ∥ 1C library] ─► 3 audits   (🔴 → HALT this feature)
   ▼ writing-plans + Phase-2 Partition Map
★ MANIFEST  (/v:orchestrate)                              (partition FAIL → HALT)
   ▼ DISPATCH  (/v:dispatch) — Task 0 serial, then parallel batches across backends
★ SCOPE GATE  git diff vs write_allowed                   (violation → BLOCKED → HALT)
   ▼ 3-pass REVIEW (spec · quality · integration, AC-gated)
   ▼ feature done → --update --status done --run-id <run-id>
```

Everything is **reused per feature**: the scope gate, the model-broker/routing policy ([`routing-policy.md`](routing-policy.md)), graceful failure-handling ([`failure-policy.md`](failure-policy.md)), and the scorecards. A feature that HALTs (BLOCKED scope gate, unresolvable reviewer ISSUES, 🔴 pre-flight, exhausted backend) is marked `failed` and stops the loop — but the epic stays resumable.

---

## Resumable run-dir layout

The epic owns a directory; each feature owns a normal v1.0 run dir under it (or anywhere under `execution/` — the `run_id` recorded in `epic-state.json` is the link):

```
docs/superpowers/execution/epics/<epic-id>/
├── epic-state.json        # the epic spine (this doc) — features + topological status
├── features.json          # the input feature list: [{id, title, depends_on}, …]
└── runs/                  # (or the flat execution/<run-id>/ dirs the run-ids point to)
    └── <run-id>/          # one normal v1.0 run dir per feature (manifest.yaml, state.json, jobs/, results/)
        ├── manifest.yaml
        ├── state.json
        ├── jobs/<id>.prompt.md
        └── results/<id>.json
```

`epic-state.json` is the single source of truth for "where is this epic"; each feature's `state.json` is the source of truth for "where is that feature" (per [`state-machine.md`](state-machine.md)). **Resume is re-entrant:** re-running `/v:epic` reads the existing `epic-state.json`, skips `done` features, and continues from the next runnable one — no daemon, no background process. The same git-wins discipline that protects a single run protects each feature's run dir.

---

## The final cross-feature integration review

When `--next` returns `epic complete` (all features `done`), run a **final integration review** before finishing:

- It reviews the **whole accumulated diff** on the branch against the **epic's** acceptance criteria — the *cross-feature* contracts (do the features compose, do shared boundaries line up, is the product coherent end-to-end), **not** the per-feature ACs (those already passed in each feature's own 3-pass review).
- On PASS → hand to `superpowers:finishing-a-development-branch` (merge / PR / cleanup).
- On ISSUES → surface them; the epic stays resumable.

---

## Honesty boundary

State this to the user — epic mode is bounded, not magic:

- **Autonomous *chaining*, not "guess a product from one sentence."** Each feature still needs a **real spec** — brainstormed and human-approved up front (carried as `spec_path`); the per-feature pre-flights and partition do the work, the epic layer only orders and chains.
- **Bounded, not unbounded.** An epic is *N full v1.0 runs*; it runs under a `MAX_FEATURES` budget (default 1) and **STOPS at a human checkpoint** after the budget is spent — not a fire-and-forget overnight build. The checkpoint is the cost ceiling and the human-in-the-loop point.
- **Large epics run sequentially, feature-by-feature.** Parallelism is *within* a feature (the v1.0 batch dispatch); features advance one runnable-front at a time in topological order. Independent features at the same depth still run one after another — there is **no cross-feature parallel dispatch** in v1.1.
- **Quality is bounded by per-feature spec + partition quality.** A weak decomposition (overlapping features, missed deps) produces a weak epic. The state spine guarantees **order and resumability**, not that your decomposition was right.

---

## Cross-references

- Epic state spine (CLI + validation): [`scripts/compound-v-epic-state.py`](../../scripts/compound-v-epic-state.py)
- Driver command: [`commands/v-epic.md`](../../commands/v-epic.md) (`/v:epic`)
- Per-run state machine + crash-resume (one level down): [`state-machine.md`](state-machine.md)
- The per-feature manifest contract: [`execution-manifest.md`](execution-manifest.md)
- The main skill: [`SKILL.md`](SKILL.md)
