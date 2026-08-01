# Handoff — adversarial review of PR 2 (tier model pools)

> Paste everything below the line into a fresh agent session. Self-contained: assume no history.

---

You are reviewing a pull request nobody has reviewed yet. Read this brief fully before starting.

## The subject

Repo: `/Users/yurifediai/Projects/Procoders/compaund-v`
PR: https://github.com/procoders/superpowers-v/pull/6 — branch `feat/tier-model-pool` → `main`.
**24 files, +5092 / −120.**

It lets one tier name several backends and hands successive jobs to them in a deterministic
weighted rotation, so a run draws on more than one provider's quota instead of draining a single
one.

The surface is large and unevenly distributed. Weight your effort accordingly:

| File | Δ | Why it matters |
|---|---|---|
| `scripts/compound-v-pool-state.py` | **+896, new** | The whole feature. Nothing else in the repo resembles it. |
| `scripts/compound-v-failure-policy.py` | +506 | Suspiciously large for what the spec asked. Check for scope creep and for silent changes to existing behaviour. |
| `scripts/compound-v-validate-manifest.py` | +445 | Five separate backend-keyed gates had to change; each is a way to slip a bad job through. |
| `scripts/compound-v-project-config.py` | +270 | New config shape; must fail **closed**. |
| `scripts/compound-v-resolve-model.py` | +198 | Purity is load-bearing here. |
| `compound-v-classify-failure.py`, 12 docs | small | Consistency with the above. |

The spec is `docs/superpowers/specs/2026-08-01-tier-model-pool-design.md`; the plan is
`docs/superpowers/plans/2026-08-01-tier-model-pool.md`. **Review the code against the spec, and
review the spec itself** — it was rewritten once already after three pre-flight audits
(`docs/superpowers/{archaeology,expert,library-audit}/2026-08-01-tier-model-pool.md`), and a
rewrite that fixes four defects is exactly where a fifth gets introduced.

## What to attack, in priority order

### 1. Determinism, which is the feature's entire promise

The spec says the assignment index is **the job's ordinal among pool-routed jobs of that tier in
the manifest**, never dispatch order, and that the member list is **frozen into `state.json` at run
start**. Verify by execution, not by reading:

- Same manifest, same config → identical assignments, every time.
- An **unavailable member is skipped while the counter still advances**, so later assignments keep
  the positions they would otherwise have had. Getting this wrong silently shifts everything.
- Editing `pools` mid-run changes nothing for that run.
- Weight expansion: a member of weight *n* takes *n* consecutive slots. All weights 1 ⇒ plain
  rotation.
- `resolve()` must stay **pure**. Every production caller is a fresh subprocess, so any counter
  living inside the resolver returns member 0 forever. Grep for module-level mutable state.
- Look for `random`, `Date`/`time`-derived choices, set/dict iteration used as ordering, or
  anything that makes two runs differ.

### 2. The five gates a `pool` job could slip past

`backend: pool` is a routing instruction, not a backend — it is resolved to a real backend before
dispatch. Every site keying off the backend string had to be taught about it. Verify each with a
manifest that *should* be rejected:

1. **Worktree invariant** — `backend: pool` + `isolation: direct` must fail.
2. **Reviewer prohibition** — a reviewer job with `backend: pool` must fail. Before this PR it
   slipped through *while the deep/opus check still passed*, so the manifest looked compliant.
3. **never-Haiku** — the execution-layer gate fires on a job's explicit `model`, and a pool job has
   none, so the gate becomes unreachable unless it now runs on the **resolved** model. Prove it
   fires: point a pool member at a haiku model and confirm rejection.
4. **`advisor_backend`** — `pool` must be rejected there while staying valid as `job.backend`.
   `select_advisor` has no path for it.
5. **`FALLBACK` / classifier argparse** — neither must ever see the literal string `pool`.

### 3. Failure interaction

Existing behaviour, which the PR must not break: `rate_limited` **retries the same backend** (cap
3) and never reroutes; only `out_of_credits` reroutes, and previously always to `claude`.

- A pool job's `out_of_credits` must reroute to the **next available pool member**, falling back to
  the old chain only when the pool is exhausted.
- `attempts` are per failure-class and **reset on reroute**, so a 3-retry cap can become 9 across a
  3-member pool against a 12-retry run budget. Verify the run-level budget actually decrements
  across reroutes.
- Check for oscillation: can a job bounce between two exhausted members, or can one healthy member
  absorb a stampede?
- +506 lines here is far more than "reroute to the next member". Read every changed line and ask
  what else moved.

### 4. Resume

`/v:resume` must re-dispatch a pool job to its **recorded** `assigned_backend`, never re-derive it
— a resumed job belongs to a specific worktree and a specific partial diff. The one exception is a
quota-class failure, where the assignment is cleared deliberately. Test by destroying the counter
state and resuming.

`state.json` has **no schema and no validator** in this repo, and real runs carry three different
per-job shapes. The PR was supposed to add a narrow validator for its own fields. Check it exists
and that it actually rejects a dispatched pool job missing `assigned_backend`.

### 5. Config, fail-closed

`load_project_config` type-checks every known top-level key and raises on a bad value. `pools` and
`backend_max_parallel` must join that check: a malformed **routing** key must fail closed, never
fail open — a silently-ignored bad pool means jobs quietly route somewhere unintended. Confirm the
`resolve_<block>() -> (values, warnings)` convention is followed.

Also verify the weight bounds (1–100, expanded ring capped at 256 slots) are enforced and are not
merely documented. **These bounds were added to the spec late and were not covered by any of the
three audits** — treat them as unreviewed. The stated rationale is memory safety: the resolver
materialises positional slots, so an arbitrary JSON integer would make config parsing a
deterministic memory-exhaustion path. Check that claim and the enforcement.

### 6. Claims the repo forbids

- **No fabricated metrics.** The spec deliberately does *not* claim the feature "burns quotas
  evenly" — it balances **job counts**, and the three providers meter in different units (rolling
  message windows vs credits derived from tokens with per-model multipliers that double at peak).
  Grep the diff for any language that promises measured savings or even balance.
- **`backend_max_parallel` is documented and shape-validated only.** Batching is prose instruction
  to the dispatcher, not code. If anything in the PR claims it is enforced, that is a false claim
  of enforcement.

### 7. Tests

The diff shows **no new `scripts/test-*.sh`**. This repo's convention is `--selftest` inside each
Python script — confirm the new and changed scripts have real ones, and check they are not
vacuous. On the sibling PR, a selftest reported `53 ok, 0 fail` while four of eight classes were
wrong, because the fixtures used invented inputs that happened to dodge a needle collision. Read
the fixtures and ask: would this test fail if the code were wrong?

The PR also commits a run manifest at
`docs/superpowers/execution/2026-08-01-tier-model-pool/manifest.yaml`. CI validates every tracked
manifest — confirm it passes and that it is not a fixture masquerading as a real run.

### 8. The merge-order claim

The spec declares PR 1 (branch `feat/zai-backend`, PR #5) a **merge prerequisite**: every shipped
example uses `zai`, and with `claude` excluded from pools by default a pool without `zai`
degenerates to one member. PR #5 is **not merged**. So check what the examples in this PR actually
do against `main` — a `zai` job fails manifest validation there. Either the examples were changed,
or the PR is not mergeable yet. Say which.

## How to verify — and what "verified" means here

**A zero is not a result.** A broken checker and a clean repo print the same zero. Report the
denominator, and prove the check can fail: plant a defect, confirm it is caught, remove it, and
confirm the tree is unchanged by comparing a `git status --porcelain` hash before and after — not
by checking one file is clean, since your own edits are legitimately dirty.

**The file most likely to break a rule is the file documenting that rule.** After editing any doc
about a gate, re-run that gate.

Full sweep, all must pass:

```bash
jq empty .claude-plugin/plugin.json .claude-plugin/marketplace.json hooks/hooks.json \
         schemas/job_result.schema.json
python3 scripts/lint-frontmatter.py .
for s in resolve-model validate-manifest classify-failure failure-policy usage-extract \
         pool-state epic-state epic-arbiter epic-watch; do
  python3 "scripts/compound-v-$s.py" --selftest >/dev/null 2>&1 && echo "ok $s" || echo "FAIL/absent $s"
done
shellcheck hooks/*.sh scripts/*.sh
for m in examples/manifest.example.yaml docs/superpowers/execution/*/manifest.yaml; do
  python3 scripts/compound-v-validate-manifest.py "$m" >/dev/null && echo "ok $m" || echo "FAIL $m"
done
```

Traps: the CI runner has shellcheck **0.9.0**, which flags things 0.11.x does not — a local pass on
a newer version is not proof. The dead-link and anti-fabricated-metric gates are shell loops in
`.github/workflows/validate.yml`; port their regexes to Python to run them locally, because a `zsh`
subshell silently loses `PATH` in that loop and prints an empty, clean-looking result. Python floor
in CI is **3.9** while your interpreter is newer, so 3.10+ syntax passes locally and fails there.

## Report

Classify every finding: **CONFIRMED** (you reproduced it), **PLAUSIBLE** (could not fully verify),
**REJECTED** (with the reason). A finding you cannot substantiate is noise — say so rather than
passing it through. Give a merge verdict and name the single most serious surviving issue.

Write to `docs/superpowers/reviews/2026-08-01-tier-model-pool-review.md`. Do not modify code, do
not push, do not merge.
