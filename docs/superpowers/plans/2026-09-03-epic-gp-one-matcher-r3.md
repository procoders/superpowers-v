# F1 `one-matcher` attempt 3 — a load-bearing fail-closed row — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace attempt 2's selftest row (merged in 42cac01, proven NOT load-bearing by `docs/superpowers/dogfood/2026-09-03-epic-gp-one-matcher-r2-review-1.md` §3) with one that fails the moment the `if err is None:` load guard in `_scope_matches` is removed.

**Architecture:** The row asserts on *behaviour the guard controls*, not on the verdict alone: with `tempfile.mkdtemp` patched to raise, `importlib.util.spec_from_file_location` is wrapped by a spy; the row passes only if the verdict is `unavailable` AND the spy recorded zero calls (the sibling was never reached). Without the guard the loader proceeds to `spec_from_file_location` while `err` is set, the spy records a call, and the row FAILS. One row in, one row out; no production change. Attempt 1's pre-flight audits are reused (spec unchanged).

**Tech Stack:** Python 3.9 stdlib.

## Global Constraints

- Only `scripts/compound-v-memory.py` changes, and only inside `_selftest`: the block that starts at the comment `# fail-closed: when the private bytecode cache cannot be created` and ends at the `check("no private bytecode cache -> unavailable, nothing loaded", …)` call is replaced by the block below. Nothing else moves.
- The proof (Step 2) copies BOTH `scripts/compound-v-memory.py` and `scripts/compound-v-scope-check.py` side by side into a scratch directory, because `_SCOPE_CHECK_PATH` is derived from `__file__`'s directory (the r2 plan's recipe forgot the sibling and proved nothing — review §3(a)).

## Partition Map (Phase 2 — disjoint write paths)

| Task | write_allowed | type |
|---|---|---|
| A `load-bearing-row` | `scripts/compound-v-memory.py` | implement (claude · standard · medium · worktree) |
| R `spec-review-1` | `docs/superpowers/dogfood/2026-09-03-epic-gp-one-matcher-r3-review-1.md` | review (claude · deep · high · direct, depends_on A) |

---

### Task A: `load-bearing-row`

**Files:**
- Modify: `scripts/compound-v-memory.py` — `_selftest`, the existing fail-closed block (find it with `grep -n 'no private bytecode cache' scripts/compound-v-memory.py`)

- [ ] **Step 1: Replace the block** (from its leading comment through its `check(...)` call) with:

```python
    # fail-closed: when the private bytecode cache cannot be created, the sibling is NEVER executed.
    # Load-bearing on purpose (attempt-2 review §3): a spy on spec_from_file_location proves the loader
    # stopped BEFORE reaching the sibling — a verdict-only assertion passes with the guard removed.
    import importlib.util as _ilu
    import tempfile as _tf
    _real_mkdtemp, _real_sfl = _tf.mkdtemp, _ilu.spec_from_file_location
    _sfl_calls = []

    def _no_cache(*_a, **_k):
        raise OSError("no space left")

    def _spy_sfl(*a, **k):
        _sfl_calls.append(a)
        return _real_sfl(*a, **k)

    globals()["_SCOPE_MATCH"] = None; globals()["_SCOPE_MATCH_ERR"] = None
    _tf.mkdtemp, _ilu.spec_from_file_location = _no_cache, _spy_sfl
    try:
        v3 = recall_check(["src/**"], "/nonexistent-results", 1)
    finally:
        _tf.mkdtemp, _ilu.spec_from_file_location = _real_mkdtemp, _real_sfl
        globals()["_SCOPE_MATCH"] = None; globals()["_SCOPE_MATCH_ERR"] = None
    check("no private bytecode cache -> unavailable AND the sibling was never loaded",
          v3["verdict"] == "unavailable" and "private bytecode cache" in v3["note"]
          and _sfl_calls == [])
```

- [ ] **Step 2: Prove the row is load-bearing (both files side by side)**

```bash
D=$(mktemp -d) && cp scripts/compound-v-memory.py scripts/compound-v-scope-check.py "$D"/ \
  && python3 -c "s=open('$D/compound-v-memory.py').read(); s2=s.replace('        if err is None:\n            spec = ', '        if True:\n            spec = ', 1); assert s2 != s; open('$D/guardless-memory.py','w').write(s2)" \
  && cp "$D"/guardless-memory.py "$D"/compound-v-memory-guardless.py \
  && echo "REAL:" && /usr/bin/python3 -B "$D"/compound-v-memory.py --selftest 2>&1 | grep 'never loaded' \
  && echo "GUARDLESS:" && /usr/bin/python3 -B "$D"/compound-v-memory-guardless.py --selftest 2>&1 | grep 'never loaded'; rm -rf "$D"
```

Expected: `REAL:` followed by `  ok   no private bytecode cache -> unavailable AND the sibling was never loaded`; `GUARDLESS:` followed by `  FAIL no private bytecode cache -> unavailable AND the sibling was never loaded`. Paste both lines into your summary verbatim.

- [ ] **Step 3: Run both selftests**

Run: `/usr/bin/python3 -B scripts/compound-v-memory.py --selftest 2>&1 | tail -3` and `/usr/bin/python3 -B scripts/compound-v-scope-check.py --selftest 2>&1 | tail -1`
Expected: `0 failed` and `SELFTEST PASSED`.

- [ ] **Step 4: Commit**

```bash
git add scripts/compound-v-memory.py
git commit -m "test(memory): the fail-closed row proves the sibling is never loaded without a private bytecode cache"
```

### Task R: `spec-review-1` — the three-pass Review Gate

**Files:**
- Create: `docs/superpowers/dogfood/2026-09-03-epic-gp-one-matcher-r3-review-1.md`

Follow the `spec-reviewer` agent definition. SPEC: reproduce Step 2 yourself (both files side by side) and confirm REAL `ok` / GUARDLESS `FAIL`; the review-r2 §3(b) marker instrumentation is an acceptable second proof. QUALITY: `git diff --stat` shows only `scripts/compound-v-memory.py`, only `_selftest` lines, one block replaced. INTEGRATION: both selftests green under `/usr/bin/python3`. End with `## Verdict` and one line `VERDICT: APPROVED` or `VERDICT: ISSUES`.
