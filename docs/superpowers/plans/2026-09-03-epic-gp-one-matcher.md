# F1 `one-matcher` — recall-check uses the scope gate's glob matcher — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `scripts/compound-v-memory.py` `recall-check` judges "did a prior failure touch this lane" with the same glob matcher the scope gate uses, proven by a parity selftest.

**Architecture:** `_file_matches` delegates to `compound-v-scope-check.py`'s `matches(path, pattern)`, loaded once by path with `importlib` (the pattern `compound-v-discover-models.py`'s selftest already uses). A bare glob keeps meaning "this path or anything under it" via a `/**` fallback. A loader failure surfaces as `verdict: unavailable`, never as a silent `none`.

**Tech Stack:** Python 3.9 stdlib only (CI floor). No new files.

## Global Constraints

- Python 3.9 syntax (CI runs every `--selftest` under 3.9). No third-party imports.
- Never `haiku`; no fabricated metrics; no `Date.now`-style clock reads in emitted JS (not applicable here).
- `scripts/compound-v-scope-check.py` is read-only for this feature — its semantics are the contract.

## Partition Map (Phase 2 — disjoint write paths)

| Task | write_allowed | type |
|---|---|---|
| A `matcher-swap` | `scripts/compound-v-memory.py` | implement (claude · standard · medium · worktree) |
| R `spec-review-1` | `docs/superpowers/dogfood/2026-09-03-epic-gp-one-matcher-review-1.md` | review (claude · deep · high · direct, depends_on A) |

Shared resources: none. Task 0: none (one implementer).

---

### Task A: `matcher-swap` — delegate `_file_matches` to the scope gate's matcher

**Files:**
- Modify: `scripts/compound-v-memory.py:32` (drop `import fnmatch`), `:1061-1069` (`_file_matches`), `:1072-1092` (`recall_check` — the `unavailable` path), `:1196+` (`_selftest` — parity rows)
- Test: the script's own `--selftest`

**Interfaces:**
- Consumes: `compound-v-scope-check.py` `matches(path: str, pattern: str) -> bool` (module-level function, no side effects at import; the script's `main` is under `if __name__ == "__main__"`).
- Produces: `_file_matches(changed: str, globs: list[str]) -> bool` (same signature as before); `recall_check(...)` may now return `verdict == "unavailable"` with a `note` starting `scope-check matcher unavailable:`.

- [ ] **Step 1: Write the failing parity rows in `_selftest`** (append before the final `RESULT`/return of `_selftest`; find it with `grep -n 'fails' scripts/compound-v-memory.py | tail -3`):

```python
    # glob parity with the scope gate (epic 2026-09-03-glob-parity F1): one matcher, two callers.
    _scope = _scope_matches()
    parity = [
        ("src/*.py", "src/a.py", True), ("src/*.py", "src/a/b.py", False),
        ("src/**", "src/a/b.py", True), ("src/**", "src", True),
        ("app/[locale]/**", "app/[locale]/page.tsx", True), ("app/[locale]/**", "app/l/page.tsx", False),
        ("README.md", "README.md", True), ("README.md", "docs/README.md", False),
        ("**/x.py", "x.py", True), ("docs/**", "docs/a/b.md", True),
    ]
    for pat, path, want in parity:
        check("parity %s ~ %s" % (pat, path),
              _scope(path, pat) is want and _file_matches(path, [pat]) is want)
    # bare-dir form: recall-only sugar, equal to the gate's `dir/**`
    check("bare dir == dir/**", _file_matches("docs/a/b.md", ["docs"]) is True
          and _scope("docs/a/b.md", "docs/**") is True and _file_matches("docs2/a.md", ["docs"]) is False)
    # loader failure -> unavailable, never none
    saved = globals()["_SCOPE_CHECK_PATH"]
    globals()["_SCOPE_CHECK_PATH"] = "/nonexistent/compound-v-scope-check.py"; globals()["_SCOPE_MATCH"] = None
    v = recall_check(["src/**"], "/nonexistent-results", 1)
    globals()["_SCOPE_CHECK_PATH"] = saved; globals()["_SCOPE_MATCH"] = None
    check("matcher missing -> unavailable", v["verdict"] == "unavailable"
          and v["note"].startswith("scope-check matcher unavailable"))
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 scripts/compound-v-memory.py --selftest 2>&1 | tail -5`
Expected: `NameError: _scope_matches` (or FAIL lines for `app/[locale]/**` under fnmatch).

- [ ] **Step 3: Implement the loader and the delegation** — replace `_file_matches` (and remove `import fnmatch` at line 32):

```python
_SCOPE_CHECK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compound-v-scope-check.py")
_SCOPE_MATCH = None


def _scope_matches():
    """The scope gate's matcher, loaded once by path. One matcher for recall and the gate:
    `*` within a segment, `**` across, `dir/**` includes `dir`, `[`/`]` literal, anchored."""
    global _SCOPE_MATCH
    if _SCOPE_MATCH is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cv_scope_check", _SCOPE_CHECK_PATH)
        if spec is None or spec.loader is None:
            raise ImportError("cannot load %s" % _SCOPE_CHECK_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _SCOPE_MATCH = mod.matches
    return _SCOPE_MATCH


def _file_matches(changed, globs):
    """Anchored match with the scope gate's glob semantics — no substring fallback (so `src/api`
    can't match `src/api2/…`). A bare path with no wildcard means "this path or anything under it"
    (`<g>/**`), the same reading the gate gives `dir/**`."""
    m = _scope_matches()
    for g in globs:
        if m(changed, g):
            return True
        if "*" not in g and "?" not in g and m(changed, g.rstrip("/") + "/**"):
            return True
    return False
```

and at the top of `recall_check`, before `scan_failures`:

```python
    try:
        _scope_matches()
    except (OSError, ImportError, AttributeError, SyntaxError) as e:
        return {"verdict": "unavailable", "match_count": 0, "k": k, "files_queried": file_globs,
                "actions": [], "evidence": [],
                "note": "scope-check matcher unavailable: %s" % e}
```

- [ ] **Step 4: Run the selftest to verify it passes**

Run: `python3 scripts/compound-v-memory.py --selftest 2>&1 | tail -3` and `python3 scripts/compound-v-scope-check.py --selftest 2>&1 | tail -1` and `grep -n fnmatch scripts/compound-v-memory.py`
Expected: every parity line `ok`, both selftests pass, the grep prints nothing.

- [ ] **Step 5: Live check and commit**

Run: `python3 -B scripts/compound-v-memory.py recall-check --files 'app/[locale]/**' --json | head -5`
Expected: exit 0, `"verdict"` in `none|tighten|unavailable`.

```bash
git add scripts/compound-v-memory.py
git commit -m "feat(memory): recall-check matches lanes with the scope gate's glob matcher (parity selftest)"
```

### Task R: `spec-review-1` — the three-pass Review Gate

**Files:**
- Create: `docs/superpowers/dogfood/2026-09-03-epic-gp-one-matcher-review-1.md`

Follow the `spec-reviewer` agent definition: Step 0 recall, SPEC (every acceptance criterion of the spec, by name), QUALITY (no regression: scope-check untouched, no fabricated metrics, selftests green under `/usr/bin/python3` 3.9), INTEGRATION (the emitted implementer prompt's recall clause still works: `python3 -B scripts/compound-v-memory.py recall-check --files scripts/compound-v-memory.py --json` returns a verdict). End with `## Verdict` and one line `VERDICT: APPROVED` or `VERDICT: ISSUES`.
