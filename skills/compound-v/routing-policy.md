# Routing Policy — task-type → backend · model · isolation · run

> *"Right supe, right job. You don't send the new kid to do Soldier Boy's work, and you don't burn Homelander on a printout."*

This is the **routing engine** for Compound V. Given a job's `type` (the token in
the manifest, see [`execution-manifest.md`](execution-manifest.md)), it decides
**backend · model · isolation · run**. The planner applies it when materializing
`manifest.yaml`; the deterministic invariants below are also enforced by
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

| Job type | Backend · Model | Isolation | Run |
|---|---|---|---|
| `shared_foundation` (Task 0) | claude · opus | direct | serial |
| Security / auth / payments / PII / a11y | claude · opus | worktree | parallel |
| `core_slice` (design judgment) | claude · opus | worktree | parallel |
| `bounded_crud` (8-box junior) | claude · sonnet | direct | parallel |
| `large_isolated` build | **codex · gpt-5.5** | worktree | parallel |
| `mechanical_refactor` / rename / format | claude · sonnet | direct | parallel |
| `docs` / i18n strings | claude · sonnet | direct | parallel |
| `tests_new` — designing new tests | claude · opus | direct | parallel |
| `external_api` integration | claude · opus | worktree | parallel |
| `review` — spec / quality / integration | claude · opus | direct | parallel/serial |
| **Unclear scope** | **none → return to planning** | — | — |

---

## Stance: Conservative (Opus-heavy, no Codex)

For high-stakes or unfamiliar codebases where you want maximum judgment and no
external worker. Every implementation job is Opus; Sonnet is reserved for purely
mechanical slices; Codex is not used at all.

| Job type | Backend · Model | Isolation | Run |
|---|---|---|---|
| `shared_foundation` | claude · opus | direct | serial |
| Security / auth / payments / PII / a11y | claude · opus | worktree | parallel |
| `core_slice` | claude · opus | worktree | parallel |
| `bounded_crud` | claude · opus | worktree | parallel |
| `large_isolated` build | **claude · opus** | worktree | parallel |
| `mechanical_refactor` / rename / format | claude · sonnet | direct | parallel |
| `docs` / i18n strings | claude · sonnet | direct | parallel |
| `tests_new` | claude · opus | direct | parallel |
| `external_api` | claude · opus | worktree | parallel |
| `review` | claude · opus | direct | parallel/serial |
| Unclear scope | none → return to planning | — | — |

---

## Stance: Cost-aware (more Sonnet / Codex)

For well-specified, lower-risk work where throughput and cost matter more than
deep judgment. Pushes routine slices to Sonnet and large isolated builds to Codex.
**Reviewers stay Opus** (invariant) — the savings come from implementers, never the gate.

| Job type | Backend · Model | Isolation | Run |
|---|---|---|---|
| `shared_foundation` | claude · opus | direct | serial |
| Security / auth / payments / PII / a11y | claude · opus | worktree | parallel |
| `core_slice` | claude · sonnet | worktree | parallel |
| `bounded_crud` | claude · sonnet | direct | parallel |
| `large_isolated` build | **codex · gpt-5.5** | worktree | parallel |
| `mechanical_refactor` / rename / format | claude · sonnet | direct | parallel |
| `docs` / i18n strings | claude · sonnet | direct | parallel |
| `tests_new` | claude · sonnet | direct | parallel |
| `external_api` | claude · opus | worktree | parallel |
| `review` | claude · opus | direct | parallel/serial |
| Unclear scope | none → return to planning | — | — |

> Security / auth / payments / PII / a11y stays Opus in **every** stance — sensitive
> surfaces are never cost-optimized.

---

## Env-aware Claude-only fallback

If `/v:init` finds **no Codex CLI** (or the user picks Claude-only), the stance
collapses so nothing routes to a backend that is not installed:

- Every `backend: codex` row is rewritten to **`claude · opus`, `isolation: worktree`**
  (the large-isolated build keeps its worktree isolation; only the worker changes).
- All other rows are unchanged from the chosen base stance.
- The saved config records `backends: ["claude"]` so the dispatcher never attempts a
  Codex launch and the manifest validator does not expect one.

This is exactly Success Criterion #5 (PRD §9): with Codex absent, the pipeline runs
unchanged, just Claude-only.

---

## Invariants (non-negotiable, deterministically enforced)

These hold in **every** stance and are checked by `compound-v-validate-manifest.py`
(hard, non-zero exit) and `partition-reviewer`:

1. **Reviewers ⇒ opus.** Any `review`/reviewer job is `model: opus`. Mirrors the
   frontmatter rule (reviewers/agents always carry `model: opus`).
2. **Codex ⇒ worktree.** Any `backend: codex` job MUST be `isolation: worktree`.
   Codex's sandbox can only restrict writes to a *directory*, so worktree + `git diff`
   is the only file-scope enforcement.
3. **Unclear scope ⇒ return to planning.** A job whose scope the planner cannot pin
   never dispatches with a guessed partition — it goes back to writing-plans.

`backend` and `model` are **execution-layer data**. They drive dispatch and live only
in the manifest — they **never** appear in any agent/skill/command frontmatter.

---

## How a job type is routed (the decision, in order)

1. Read the active **stance** from `.claude/compound-v.json` (default Balanced;
   Claude-only if no Codex).
2. Check [`routing-lessons.md`](../../docs/superpowers/memory/routing-lessons.md)
   for a lesson matching this `type` + backend — if one applies, follow it.
3. Otherwise apply the stance table above.
4. Apply the env-aware fallback (rewrite Codex rows if Codex is absent).
5. Validate the result against the invariants (the validator is the backstop).
6. If the type is "unclear scope," **stop and return to planning** — do not guess.
