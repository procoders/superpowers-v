# F1 `one-matcher` — recall-check uses the scope gate's glob matcher — spec

**Goal.** `scripts/compound-v-memory.py` `_file_matches(changed, globs)` stops using `fnmatch` and delegates to
`scripts/compound-v-scope-check.py`'s `matches(path, pattern)` — the one matcher whose semantics the manifest
contract documents (`*` within one segment, `**` across segments, `dir/**` also matches `dir`, `?` one
non-`/` character, `[` and `]` literal, anchored to the full repo-relative path). A bare glob with no `*`,
`?` or trailing `/` keeps meaning "this path or anything under it": try `g`, then `g.rstrip("/") + "/**"`.

**Why.** Today the two matchers disagree: `fnmatch` lets `*` cross `/` and reads `[locale]` as a character
class, so a lane written as `app/[locale]/**` matches nothing in recall-check while the scope gate matches the
real directory, and `src/*.py` matches `src/a/b.py` in recall but not in the gate. Recall evidence must be
judged by the same rule that judges the diff.

**Loading.** Import the sibling script by path (`importlib.util.spec_from_file_location`, the pattern
`compound-v-discover-models.py`'s selftest uses), resolved from `os.path.dirname(__file__)`. If the sibling
cannot be loaded, `recall-check` reports `verdict: unavailable` with `note: "scope-check matcher unavailable"`
— never a silent `none`. Remove the `fnmatch` import if nothing else uses it.

**Files.** Modify `scripts/compound-v-memory.py` (`_file_matches`, the loader, the selftest). No other file.

**Selftest (parity table).** Add to `compound-v-memory.py --selftest` a table of at least eight
`(pattern, path, expected)` rows, each asserted against BOTH `scope.matches` and `_file_matches`:
`("src/*.py", "src/a.py", True)`, `("src/*.py", "src/a/b.py", False)`, `("src/**", "src/a/b.py", True)`,
`("src/**", "src", True)`, `("app/[locale]/**", "app/[locale]/page.tsx", True)`,
`("app/[locale]/**", "app/l/page.tsx", False)`, `("docs", "docs/a/b.md", True)` (bare-dir form, recall only
via the `/**` fallback — assert `_file_matches` True and `scope.matches("docs/a/b.md", "docs/**")` True),
`("README.md", "README.md", True)`, `("README.md", "docs/README.md", False)`, `("**/x.py", "x.py", True)`.

**Acceptance criteria.** `python3 scripts/compound-v-memory.py --selftest` passes with the parity rows;
`python3 scripts/compound-v-scope-check.py --selftest` unchanged and passing; `grep -n fnmatch
scripts/compound-v-memory.py` finds nothing; `python3 -B scripts/compound-v-memory.py recall-check --files
'app/[locale]/**' --json` exits 0 with a verdict in `none|tighten|unavailable`.

## Pre-flight amendments (2026-09-03, after 1A archaeology and 1C library audit; 1B skipped — internal plumbing)

1. **Loader = the hardened pattern, not the bare triple.** Load `compound-v-scope-check.py` exactly as
   `scripts/compound-v-integration-gate.py` `load_scope_matcher` does: `sys.pycache_prefix` redirected to a private
   `tempfile.mkdtemp` directory for the duration of the import, **fail closed** (no load) when that directory cannot be
   created, the whole `spec_from_file_location` / `module_from_spec` / `exec_module` sequence inside one `try/except`,
   `callable(getattr(module, "matches", None))` verified before use. The discover-models selftest pattern named above is
   the path-resolution idiom only. recall-check runs automatically before every dispatch (partition-reviewer), so it sits
   on the trust boundary a forged `.pyc` already exploited on 2026-09-02.
2. **Lazy and memoized, failure included.** Never load at module top level (`compound-v-onboard.py` imports this module
   for unrelated symbols on every `/v:onboard`). Load once per process on first use and cache the callable; cache a
   failed load too (its reason), so `recall_check` never re-execs the sibling per (record × file) pair.
3. **`unavailable` is a well-formed verdict, exit 0.** Any load failure is translated into the same JSON shape as
   `none`/`tighten`: `verdict: unavailable`, `match_count 0`, `note: "scope-check matcher unavailable: <reason>"`.
4. **Bare-dir fallback is `/**`**, not `/*` (the current source narrows bare dirs to one level; the parity row
   `("docs", "docs/a/b.md")` catches it).
5. **Untouched:** `scripts/compound-v-scope-check.py` (including its selftest); no third-party packages; `import fnmatch`
   removed (nothing else in the file uses it).
