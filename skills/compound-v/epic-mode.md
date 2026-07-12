# Epic Mode — chain many features into one autonomous build (PRD §8 / v1.1)

A v1.0 run executes **ONE plan (one feature)**. An **epic** chains several: an ordered set of features, each run through the **full v1.0 pipeline** (recon-gated spec → 3 pre-flights → writing-plans + partition → manifest → dispatch → 3-pass review), in **dependency order**, accumulating onto **one branch**. "Build a whole app."

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
3. **Brainstorm a real spec PER feature, UP FRONT.** Before the autonomous loop, run `superpowers:brainstorming` for **each** feature and save a real spec file (feature-level Acceptance Criteria) to `docs/superpowers/execution/epics/<epic-id>/specs/<feature-id>.md`. **Trigger 0 applies to each per-feature brainstorm** — run the [`phase-0-recon.md`](phase-0-recon.md) gate sequence first (plumbing-skip → KB-hit → config); later features increasingly skip via the KB-hit gate as earlier recon/audit docs accumulate — designed behavior, not a bypass. Each feature carries that path as **`spec_path`** in `features.json` and `epic-state.json`. This is the **only** human-interactive phase — every spec is written and approved *here*, once, so the loop never pauses to brainstorm. That up-front batching is what resolves the central tension: the epic stays genuinely **autonomous** *and* every feature still runs from a **real, approved spec**.
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
| `--check-specs --state S` | resume guard: every non-`done` feature still has an existing, contained `spec_path` |
| `--summary --state S` | render the feature table |

`--next` is **read-only** and never an error: a `null` feature with a stop reason is *information*, not failure. Mutate state only through `--update`; never hand-edit `epic-state.json`.

**The loop is fail-fast and reconcile-strict** (the guard order in `next_feature` encodes it):

- **`epic blocked`** — any `failed` feature halts the WHOLE epic, even independent pending features; the loop never autonomously routes around a failure (it may be systemic). Recover by retrying it (`--update --feature <id> --status pending`) or dropping it, then re-run.
- **`epic needs reconcile`** — a feature is still `running`. Because epic mode is **sequential**, `--next` is only called between features, so a `running` feature on resume means that feature's run **crashed mid-pipeline**. **Reconcile by resuming first — don't discard half-built work:** the crashed feature ran a *normal v1.0 run* with its own crash-resume, so run [`/v:resume <run-id>`](../../commands/v-resume.md) (via the recorded `run_id`) to re-dispatch only that run's incomplete jobs; if it completes, mark the feature `--status done`. **If `run_id` is null** (the crash predated recording it, or an old state), there is nothing to resume → restart with `--status pending`. Only if a resumed run cannot be recovered, fall back to `--status pending` (full restart from the spec) or `--status failed` (abandon). Never leave a feature `running` across a resume. (The driver records `run_id` when it marks a feature `running` — see [v-epic.md](../../commands/v-epic.md) step 4.1 — precisely so a mid-run crash stays resumable.)

**The loop runs under an autonomy budget** — `MAX_FEATURES` per `/v:epic` invocation (**default 1**: build one feature, then checkpoint). An epic is *N full v1.0 runs*, so the budget is the **human-in-the-loop checkpoint cadence** — a *driver policy*, not a script-enforced token meter. When this invocation's budget is spent, the epic **STOPS** and reports `compound-v-epic-state.py --stats --state <…>` (done / remaining) for the human to review the accumulated diff and re-run `/v:epic` to continue. Raise `MAX_FEATURES` only when the user wants more autonomy per run.

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

When `--next` returns a runnable feature, mark it `running`, then run it through the **v1.0 pipeline's post-spec execution tail on the current branch** — nothing about a feature's run changes because it is inside an epic. The one difference: the loop **starts from the feature's already-approved `spec_path`** — Trigger 0 recon and brainstorming already ran up front (model step 3), so it does **not** recon or brainstorm inside the loop:

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

## Marathon stance (v2.10, opt-in)

Everything above this section is the **checkpoint** stance — the unchanged default. `marathon` is an opt-in alternative, chosen only at `--init` time (`--stance marathon`; no in-place upgrade of an existing checkpoint `epic-state.json`), that chews the **whole runnable feature DAG in one `/v:epic` invocation** instead of stopping at every `MAX_FEATURES` checkpoint. The full driver sequence lives in [`v-epic.md`](../../commands/v-epic.md) "Autonomous marathon loop" — this section is the authority for *what* marathon is and *why* it's shaped this way; read the command doc for the exact command-by-command steps.

**Schema (marathon-only, additive on top of the checkpoint shape above).** Absent `autonomy` ⇒ every checkpoint code path is untouched — new fields are read via `.get(..., default)` everywhere:

```json
{
  "autonomy": {"stance": "marathon", "max_attempts_per_feature": 2, "max_no_progress_cycles": 3,
               "max_total_attempts": 12, "max_wall_clock_hours": 10, "started_at": "2026-07-12T00:00:00+00:00",
               "start_sha": "<git rev-parse HEAD at --init — the accumulated-diff baseline>"},
  "final_review": {"status": "pending"},
  "blocker_ledger": [],
  "no_progress_cycles": 0,
  "total_attempts": 0
}
```

Per feature, marathon adds `"attempts": 0, "last_error": null, "disposition": null`.

**CLI additions** (every one below REJECTS a non-marathon state; see [`compound-v-epic-state.py`](../../scripts/compound-v-epic-state.py)'s docstring "## CLI contract" for the authoritative, full argument list):

| Command | Effect |
|---|---|
| `--init --stance marathon [--max-attempts-per-feature N] [--max-no-progress-cycles N] [--max-total-attempts N] [--max-wall-clock-hours H] [--start-sha <sha>]` | writes the marathon block once; checkpoint `--init` (no `--stance`) stays byte-identical. `--start-sha` (driver passes `git rev-parse HEAD`) is stored as `autonomy.start_sha`, the accumulated-diff baseline |
| `--next --autonomous --state S` | `{"feature","reason","blocked_by":[ids]}` — DAG-transitive routing: an abandoned/blocked feature removes only its transitive **dependents**, never its independents; a runnable independent is always returned before any terminal escalation |
| `--can-retry --feature F --state S` | `{"can_retry","attempts","cap"}` (read-only) |
| `--record-disposition --feature F --disposition retry_fix\|halt_feature\|halt_epic\|blocked_external [--reason R] [--families-agreeing a,b]` | stores the arbiter's verdict; `--confirmed true` is **hard-rejected** in v2.10. **Omit `--families-agreeing` when the arbiter returns an empty `families_agreeing`** (argparse needs a value — drop the flag, or pass `""`) |
| `--update --status blocked --feature F [--blocker-reason R] [--families-agreeing a,b] [--evidence E]` | appends/reactivates an idempotent blocker-ledger entry; `--blocker-confirmed true` is **hard-rejected** — v2.10 blockers are always `confirmed:false` (SUSPECTED, never caller-asserted) |
| `--update --status failed --feature F [--last-error "..."]` | persists the failure reason (cleared on the next successful retry/done) |
| `--record-final-review --status pending\|passed\|failed --state S` | `passed` requires every feature `done`; the epic reaches top-level `done` **only** via all-done AND `final_review.status=="passed"` — feature completion alone is never enough |
| `--breaker-check [--now ISO] --state S` | read-only → `{"tripped","which":[...],"detail":{...}}` |
| `--trip-breaker [--now ISO] --state S` | atomic write **iff** tripped — parks the epic at `blocked_needing_human` |
| `--record-progress-cycle --cycle-id C [--now ISO] --state S` | idempotent by `cycle_id`; compares the pass's `done` count to the prior one, resets/increments `no_progress_cycles` |
| `--clear-breaker --state S [--reset-wall-clock] [--set-max-total-attempts N]` | **human recovery:** clears the `blocked_needing_human` latch + re-arms the tripped caps so the next `/v:epic` **resumes the marathon**; `--reset-wall-clock` re-stamps `started_at`, `--set-max-total-attempts` raises the attempt cap |
| `--clear-disposition --feature F --state S` | **human recovery:** clears a sticky `halt_epic` disposition on a feature so `--next --autonomous` routes normally again |

**The arbiter panel** ([`compound-v-epic-arbiter.py`](../../scripts/compound-v-epic-arbiter.py), NEW in v2.10) classifies a feature FAILURE via a two-phase exchange — `--prepare --state S --feature F --attempt N` issues a bounded Claude ballot-task prompt + challenge id (bound to `{epic_id,feature,attempt,challenge_id}`; a mismatched/replayed/stale challenge is dropped before any model call), then `--classify --state S --feature F --challenge <id> [--evidence-file REL] [--claude-ballot FILE]` polls Codex (through the timeout supervisor, read-only sandbox, redacted+capped evidence) if the capabilities file says it's usable, validates the Claude ballot the **driver** supplies (the arbiter cannot itself launch an in-harness Claude Task — that's the driver's job), and aggregates with a complete deterministic truth table: a parse-fail/errored ballot is **dropped, never a fabricated halt vote**; empty/tied → conservative `halt_feature`; `retry_fix` past the per-feature `--can-retry` cap is masked to `halt_feature`; a `blocked_external` verdict on this Codex+Claude panel is always **SUSPECTED** — only two *distinct known external* families (`GPT`/`Gemini`/`Grok`) can CONFIRM one, and Claude-self can never count as an independent confirming family (same family as the implementer). Every ballot + the resolved family + the aggregation reason is written to a frozen audit JSON under `docs/superpowers/execution/epics/<epic-id>/arbiter/<feature>-<attempt>.json`.

**The blocker ledger** — "do everything you can" credo: finish everything reachable, isolate only the genuinely impossible, escalate with proof, never halt the rest. A `blocked_external` disposition marks the feature `--status blocked` (ledger entry, always `confirmed:false` in v2.10); `--next --autonomous` treats `blocked` as a benign skip — only its transitive dependents drop out — and never trips a whole-epic halt by itself. The epic only resolves to `blocked_needing_human` once no other reachable work remains, or a `halt_epic` verdict or a tripped breaker fires (those two *do* halt the whole epic immediately, on purpose — a panel-level "stop everything" vote, or a hard resource limit, is not something the DAG should route around).

**Global circuit breakers** — the honest bound on "how much can `/v:epic` do unattended": `total_attempts >= max_total_attempts` (default `max(6, 3×features)`), `no_progress_cycles >= max_no_progress_cycles` (default 3 — a full pass that advances `done` by zero counts as one), or wall-clock elapsed since `autonomy.started_at >= max_wall_clock_hours` (default 10). Counts and hours only — **never a fabricated cost**. Breakers are re-checked before every feature *and* after every attempt *and* before every model call (the arbiter, the final review) — not only once per pass; a single in-flight pipeline phase may still overrun its check window before the next boundary catches it (an honest, not a hard real-time, guarantee).

**PASS integrity (spec Component 5).** A marathon SUCCESS is not blindly trusted. Two guards: (1) the driver **sample-audits a deterministic fraction of PASSes** — a fresh adversarial `compound-v:spec-reviewer` re-review (QUALITY + the 2.5 reward-hack check in [`agents/spec-reviewer.md`](../../agents/spec-reviewer.md)) on a sampled successful feature; the concrete rule (every 3rd `done`, plus always the first success of the invocation) lives in [`v-epic.md`](../../commands/v-epic.md) §4, and a failed sample-audit reverts the feature to `failed` and routes it through the arbiter path; (2) the **final cross-feature re-verification** (`--record-final-review`) gates terminal `done`. Both are model calls, so both are preceded by a breaker re-check.

**Terminal states:** `done` (all features done **and** `final_review.status=="passed"` — feature completion alone is never `done`); `blocked_needing_human` (a `halt_epic` verdict, a tripped breaker, or exhausted reachable work — the v2.10 blocker terminal); `running_with_failures` (non-terminal, work still runnable, or all done and awaiting final review). v2.10 never emits `done_with_blockers` — that terminal needs a second safe external confirming family, deferred to v2.11.

**Human recovery from a halt (resume the marathon — not a fallback to checkpoint).** `blocked_needing_human` is a latch, but it is not a dead end: a human resolves the root cause and **re-runs `/v:epic <epic-id>` to resume the marathon**. A tripped breaker is cleared and re-armed with `--clear-breaker` (`--reset-wall-clock` for the wall-clock cap, `--set-max-total-attempts N` for the attempt cap — without re-arming, the same cap re-trips on the first pass); a sticky `halt_epic` verdict is cleared with `--clear-disposition --feature F`; a mid-pipeline crash is recovered in place with `/v:resume <run-id>` (the feature's recorded `run_id`), distinct from a full `--update --status pending` restart from the spec. All human-gated — **nothing un-trips or re-runs automatically in v2.10** (that is the deferred v2.11 auto-watcher). The exact runbook (every field + copy-paste commands) is [`v-epic.md`](../../commands/v-epic.md) §7.

---

## Honesty boundary

State this to the user — epic mode is bounded, not magic:

- **Autonomous *chaining*, not "guess a product from one sentence."** Each feature still needs a **real spec** — brainstormed and human-approved up front (carried as `spec_path`); the per-feature pre-flights and partition do the work, the epic layer only orders and chains.
- **Bounded, not unbounded (checkpoint stance).** An epic is *N full v1.0 runs*; it runs under a `MAX_FEATURES` budget (default 1) and **STOPS at a human checkpoint** after the budget is spent — not a fire-and-forget overnight build. The checkpoint is a **driver-enforced cadence** (default: stop after every feature), the human-in-the-loop point — not a script-enforced token meter.
- **Large epics run sequentially, feature-by-feature.** Parallelism is *within* a feature (the v1.0 batch dispatch); features advance one runnable-front at a time in topological order. Independent features at the same depth still run one after another — there is **no cross-feature parallel dispatch** in v1.1.
- **Quality is bounded by per-feature spec + partition quality.** A weak decomposition (overlapping features, missed deps) produces a weak epic. The state spine guarantees **order and resumability**, not that your decomposition was right.
- **Marathon (v2.10, opt-in) — "survives a fall" is honest, not magic.** *In-session:* the loop continues past a soft per-feature error to the next runnable feature automatically, within the one live `/v:epic` invocation; a crashed feature is caught by the existing `running` → reconcile path on the next pass. *Hard death* (quota, closed terminal, crashed machine): a **human re-invokes `/v:epic <epic-id>`**, re-entrant, resuming from `epic-state.json`. **There is no automatic resurrection in v2.10** — nothing revives this epic while you're away; that is the deferred v2.11 auto-watcher (Execution Lease + Two-Tier Watcher + generation-fenced execution — its own spec, its own review pass). No fabricated cost/token metrics anywhere in either stance.

---

## Cross-references

- Epic state spine (CLI + validation): [`scripts/compound-v-epic-state.py`](../../scripts/compound-v-epic-state.py)
- Marathon arbiter panel (v2.10): [`scripts/compound-v-epic-arbiter.py`](../../scripts/compound-v-epic-arbiter.py)
- Driver command: [`commands/v-epic.md`](../../commands/v-epic.md) (`/v:epic`) — the marathon loop's exact command sequence
- Per-run state machine + crash-resume (one level down): [`state-machine.md`](state-machine.md)
- The per-feature manifest contract: [`execution-manifest.md`](execution-manifest.md)
- The main skill: [`SKILL.md`](SKILL.md)
