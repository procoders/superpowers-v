---
paths:
  - "hooks/**"
---

# Hooks

- Every hook script starts with `trap 'exit 0' EXIT` and prints a decision only on success.
  (`CONVENTIONS.md:40-41`, `hooks/stop.sh:2`)
- Every registration carries `"shell": "bash"`, a timeout of at most 10 s and a `|| true` suffix,
  the guard included, so a parse error cannot block a stop or reject a prompt.
  (`CONVENTIONS.md:42-43`, `hooks/hooks.json:2`)
- The scripts stay thin wrappers; the decisions live in `scripts/cvcore/hooks.py`.
  (`CONVENTIONS.md:45`, `hooks/stop.sh:5`)
- The Stop hook refuses an unverified run once per tree and stage, then lets the stop through and
  records the run incomplete or failed. (`CONVENTIONS.md:44`, `scripts/cvcore/hooks.py:81-89`)
- Hooks run Python with `-I -B`, so no bytecode lands next to the scripts.
  (`CONVENTIONS.md:59-60`)
