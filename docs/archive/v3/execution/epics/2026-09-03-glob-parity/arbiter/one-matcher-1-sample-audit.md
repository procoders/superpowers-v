# Sample-audit of F1 `one-matcher` attempt 1 (marathon §4, first success of the invocation) — 2026-09-03

Fresh adversarial `spec-reviewer` (Opus), Pass 2 QUALITY + 2.5 reward-hack only, over the merged wave-1 commit 4bc979a.

Verified live: no test weakened (selftest hunk is +26/-0, scope-check has a 0-line diff); fail-closed on `tempfile.mkdtemp` failure
is real (patched to raise → RuntimeError, no import attempted); a failed load is cached and never retried; `fnmatch` gone; selftests
memory 82 ok / scope-check 70 ok; no fabricated metric.

VERDICT: ISSUES

1. TEST_GAP (blocking) — scripts/compound-v-memory.py:1647-1653: the only loader-failure row is the missing-path case. Pre-flight
   amendment 1's MUST (fail closed when the private bytecode cache cannot be created) has no row; deleting the `if err is None:` guard
   at :1084 leaves the full selftest green. Fix: one row patching `tempfile.mkdtemp` to raise (the globals-patching idiom at :1648).
2. LOW — :1643: the `_file_matches(...) is want` half of each parity row is near-tautological after delegation; the load-bearing half
   is `_scope(path, pat) is want`; the review's "a future divergence in either fails" over-claims.
3. LOW — :1119: `_file_matches` propagates RuntimeError; only `recall_check` guards it (no other caller today).
