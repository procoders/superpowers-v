# Direct-mode writer — the shape that was blocked by our own files

This job runs at `direct` isolation: no worktree, writing straight into
the project checkout. Its lane is exactly one file:

```
docs/superpowers/dogfood/2026-09-02-df2b-direct-bookkeeping.md
```

It registered its lane via `compound-v-emit-workflow.py register-lane`
before touching anything, pinning its baseline commit so the scope gate
measures the write against a HEAD that didn't move. A direct job has no
worktree to merge — `worktree` is reported as the empty string, not `pwd`.
