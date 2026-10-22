# F1 `one-matcher` attempt 2 — the fail-closed selftest row — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the marathon sample-audit's one blocking finding on F1: a selftest row proving `recall_check` reports `unavailable` — and loads nothing — when the private bytecode cache cannot be created.

**Architecture:** One row appended to `_selftest` in `scripts/compound-v-memory.py`, next to the existing missing-path row, using the same globals-reset idiom; `tempfile.mkdtemp` is patched to raise for the duration of one `recall_check` call. No production code changes. Attempt 1's pre-flight audits (`docs/superpowers/archaeology/2026-09-03-epic-gp-one-matcher.md`, `docs/superpowers/library-audit/2026-09-03-epic-gp-one-matcher.md`) are reused: the spec is unchanged.

**Tech Stack:** Python 3.9 stdlib.

## Global Constraints

- Only `scripts/compound-v-memory.py` changes, and only inside `_selftest`.
- The two LOW notes of the audit (near-tautological parity halves; `_file_matches` propagating `RuntimeError`) are recorded, not acted on: the parity rows keep both halves on purpose (the bare-dir branch can still diverge) and no caller besides `recall_check` exists.

## Partition Map (Phase 2 — disjoint write paths)

| Task | write_allowed | type |
|---|---|---|
| A `selftest-row` | `scripts/compound-v-memory.py` | implement (claude · standard · medium · worktree) |
| R `spec-review-1` | `docs/superpowers/dogfood/2026-09-03-epic-gp-one-matcher-r2-review-1.md` | review (claude · deep · high · direct, depends_on A) |

---

### Task A: `selftest-row` — no private bytecode cache ⇒ `unavailable`, nothing loaded

**Files:**
- Modify: `scripts/compound-v-memory.py` — `_selftest`, directly after the existing check `"matcher missing -> unavailable"` (find it with `grep -n 'matcher missing -> unavailable' scripts/compound-v-memory.py`)

- [ ] **Step 1: Append the row**

```python
    # fail-closed: when the private bytecode cache cannot be created, NOTHING is loaded
    # (pre-flight amendment 1; marathon sample-audit finding 1 — this row keeps the guard honest)
    import tempfile as _tf
    _real_mkdtemp = _tf.mkdtemp

    def _no_cache(*_a, **_k):
        raise OSError("no space left")

    globals()["_SCOPE_MATCH"] = None; globals()["_SCOPE_MATCH_ERR"] = None
    _tf.mkdtemp = _no_cache
    try:
        v3 = recall_check(["src/**"], "/nonexistent-results", 1)
    finally:
        _tf.mkdtemp = _real_mkdtemp
        globals()["_SCOPE_MATCH"] = None; globals()["_SCOPE_MATCH_ERR"] = None
    check("no private bytecode cache -> unavailable, nothing loaded",
          v3["verdict"] == "unavailable" and "private bytecode cache" in v3["note"])
```

- [ ] **Step 2: Prove the row is load-bearing**

Run: `sed -n '/def _scope_matches/,/return fn/p' scripts/compound-v-memory.py | grep -n 'if err is None'` (the guard exists), then temporarily comment out that `if err is None:` guard line in a scratch copy: `cp scripts/compound-v-memory.py /tmp/cv-mem-guardless.py && python3 - <<'PY'` … — simpler: run the selftest with the guard intact (expected `ok`), then confirm the row fails when the guard is removed by running `python3 -c "import re,sys; s=open('scripts/compound-v-memory.py').read(); s=s.replace('        if err is None:\n            spec = ', '        if True:\n            spec = ',1); open('/tmp/cv-mem-guardless.py','w').write(s)"` and `python3 /tmp/cv-mem-guardless.py --selftest 2>&1 | grep 'no private bytecode cache'`.
Expected: `FAIL no private bytecode cache -> unavailable, nothing loaded` for the guardless copy (the sibling loads fine without the cache redirect, so the verdict would not be `unavailable`), `ok` for the real file. Delete `/tmp/cv-mem-guardless.py` afterwards.

- [ ] **Step 3: Run both selftests**

Run: `/usr/bin/python3 -B scripts/compound-v-memory.py --selftest 2>&1 | tail -3` and `/usr/bin/python3 -B scripts/compound-v-scope-check.py --selftest 2>&1 | tail -1`
Expected: `0 failed` (83 ok) and `SELFTEST PASSED`.

- [ ] **Step 4: Commit**

```bash
git add scripts/compound-v-memory.py
git commit -m "test(memory): recall-check fails closed when the private bytecode cache cannot be created (sample-audit finding)"
```

### Task R: `spec-review-1` — the three-pass Review Gate

**Files:**
- Create: `docs/superpowers/dogfood/2026-09-03-epic-gp-one-matcher-r2-review-1.md`

Follow the `spec-reviewer` agent definition. SPEC: the sample-audit's blocking finding (`docs/superpowers/execution/epics/2026-09-03-glob-parity/arbiter/one-matcher-1-sample-audit.md`, item 1) is closed by a row that FAILS when the `if err is None:` guard is removed (reproduce Step 2 yourself). QUALITY: no production change (`git diff --stat` shows only `_selftest` lines), no weakened test. INTEGRATION: both selftests green under `/usr/bin/python3`. End with `## Verdict` and one line `VERDICT: APPROVED` or `VERDICT: ISSUES`.
