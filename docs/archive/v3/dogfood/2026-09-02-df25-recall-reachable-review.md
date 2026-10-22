# 2026-09-02 df25 recall-reachable — review

## Recall

Two commands, both admitted by the clamp this time:

```
/usr/bin/python3 scripts/compound-v-memory.py search \
  "red test floor merged because nothing read the tests block" --intent review --top 8

/usr/bin/python3 scripts/compound-v-memory.py search \
  "manifest job field task instructions description prompt spec write_allowed acceptance" \
  --intent review --top 6
```

Both returned results. (A third, `recall-check`, exited 2 — it requires `--files`; I did not
pursue it.) Both runs printed the same standing warning: `V-memory: index is 3 new / 0 removed
docs behind the repo`, so recall is reading a slightly stale index.

The first query returned, in rank order:

1. `docs/superpowers/dogfood/2026-09-02-v3.3.0-four-runs.md` — "The most dangerous: a red test floor merged"
2. `docs/superpowers/plans/2026-09-01-v3.0-triage-tests-orchestration.md` — "Task 0 — The shared contract"
3. `docs/superpowers/preflight/2026-09-01-v3.0-1a-archaeology.md` — "7. Design constraints for the spec"
4. `docs/superpowers/dogfood/2026-09-02-df12-reviewer-third-review.md` — "3.3 Build green — NOT asserted"
5. `docs/superpowers/plans/2026-09-01-v3.0-triage-tests-orchestration.md` — "Global Constraints"
6. `docs/superpowers/dogfood/2026-09-02-df20-final-review.md` — "PASS 2 — QUALITY"
7. `docs/superpowers/dogfood/2026-09-02-df13-reviewer-fourth-review.md` — "2.3 Test alignment"
8. `docs/superpowers/dogfood/2026-09-02-v3.3.0-four-runs.md` — "Run 1 — the derived test scope"

The second query returned:

1. `docs/superpowers/dogfood/2026-09-02-df10-review.md` — "ISSUE: INTEGRATION_MISMATCH (PASS 3)"
2. `docs/superpowers/dogfood/2026-09-02-df20-final-review.md` — "ISSUE: INTEGRATION_MISMATCH — the manifest's `body:` is silently discarded"
3. `docs/superpowers/dogfood/2026-09-02-df12-reviewer-third-review.md` — "ISSUE: SPEC_NOT_PROPAGATED (PASS 1) — root cause, and the more serious finding"
4. `docs/superpowers/dogfood/2026-09-02-df11-reviewer-retry-review.md` — "ISSUE: SPEC_GAP — the job body never reached the worker"
5. `docs/superpowers/dogfood/2026-09-02-df18-direct-digest-review.md` — "ISSUE: SPEC_GAP (PASS 1)"
6. `docs/superpowers/plans/2026-06-26-compound-v-orchestrator-v1-plan.md` — "Task 0 — Shared foundation"

What that second set is worth stating plainly, because it is the whole point of making recall
reachable: **five prior reviews — df10, df11, df12, df18, df20 — already reported this exact
defect, and it is still live.** `render_worker_prompt` reads the task text as

```python
body = job.get("description") or job.get("prompt") or job.get("spec")
```

`manifest.yaml` writes it as `body:` (`:31`, `:50`). The names do not intersect, so the
instructions are dropped. Recall pins the line number those five reviews cited — `:678`, then
`:688` — against where it sits today, `scripts/compound-v-emit-workflow.py:705`. The file has
been edited around this line repeatedly and the line itself was never touched. Without recall I
would have filed this as a first-time finding; with it, the finding is that the loop is not
closing.

The consequence is visible in both of this run's prompts. `jobs/impl-slice.prompt.md` carries
title, write-allowed, read-allowed and acceptance, and no task text at all;
`jobs/spec-review.prompt.md` likewise. I learned my own three-section instruction only by
reading `manifest.yaml` directly. A reviewer that trusted its prompt would have produced a
non-conforming review and never known.

## Review

The file under review is accurate as a sentence about itself and wrong as an artifact: it reads
"Writes the file the reviewer reviews," which is the job's *title* echoed back, where
`manifest.yaml:32-36` demanded it contain exactly "# impl" and "A red test floor once merged
because nothing read the tests block." That is a SPEC_GAP, but the owner is the emitter and not
the implementer — the implementer was handed a prompt with no content instruction in it and
wrote the only thing it had, and `receipts/impl-slice.gate.json` then passed it `verdict: pass`
with `tests.passed: true`, because the scope gate checks which files changed and never what
they say, which is the same blind spot recall's first query surfaced as "a red test floor
merged."

## Routing

Nothing recalled changed any routing decision — both jobs ran on the backend, tier and
isolation the manifest fixed before recall was consulted, and recall entered this review only
as evidence, which is the only thing it is ever allowed to be.
