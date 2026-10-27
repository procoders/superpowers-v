---
paths:
  - "tests/**"
---

# Tests

- Core tests are stdlib `unittest` under `tests/core/`; hook, skill, band and onboard tests are bash
  scripts under `tests/hooks/`. (`CONVENTIONS.md:74-75`)
- Every test builds throwaway git repos in a temp dir and points `HOME` and the receipt key there.
  (`tests/hooks/test-hooks.sh:4-6`, `tests/core/helpers.py:49-54`)
- Write no bytecode: the hook tests export `PYTHONDONTWRITEBYTECODE=1`, and the core helpers set
  `sys.dont_write_bytecode`. (`tests/hooks/test-hooks.sh:6`, `tests/core/helpers.py:12`)
