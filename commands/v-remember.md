---
description: Recall relevant past Compound V context — prior decisions, failures, routing lessons, specs/plans — from docs/superpowers via V-memory (FTS5, plus semantic embeddings when bootstrapped). It surfaces EVIDENCE for planning and review, never an authority over routing. Use before planning a feature, before reviewing a diff, or any time you need "have we hit this before?".
---

You are running **`/v:remember`** — V-memory recall. The query is `{{args}}`.

Run the recall and present what comes back:

```
python3 scripts/compound-v-memory.py search "{{args}}" --top 8
```

If it reports the index is missing, run `/v:memory-refresh` first, then retry.

**Memory is EVIDENCE, not authority:**

- It surfaces related prior prose (specs, plans, reviews, archaeology, routing lessons). It **never decides routing** — backend/model/isolation stay governed by [`routing-lessons.md`](../docs/superpowers/memory/routing-lessons.md) + the scorecard, per [`routing-policy.md`](../skills/compound-v/routing-policy.md). Treat a retrieved chunk as a pointer to read, not a ruling.
- When you need a **structured** "has this file pattern repeatedly failed before?" verdict that may *auto-tighten* the next run (force worktree / add a review pass / fold into Task 0), use the deterministic bridge instead:

  ```
  python3 scripts/compound-v-memory.py recall-check --files <glob> [<glob>…]
  ```

Authority doc: [`skills/compound-v/memory.md`](../skills/compound-v/memory.md).
