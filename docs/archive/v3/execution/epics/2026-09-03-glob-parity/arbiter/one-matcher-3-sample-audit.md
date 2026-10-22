# Sample-audit of F1 `one-matcher` attempt 3 (marathon §4, first success of the re-entered invocation) — 2026-09-03

Fresh adversarial `spec-reviewer` (Opus), Pass 2 QUALITY + 2.5 over the merged commit 70cdfa1. Load-bearing CONFIRMED by the
side-by-side proof (REAL `ok` / GUARDLESS `FAIL`); only the `_sfl_calls == []` conjunct carries the weight — the attempt-2 verdict-only
form would still pass. Nothing weakened (+15/-7, one hunk inside `_selftest`, check() sites 74 → 74, 83 ok rows before and after);
the row is replaced, not duplicated; both selftests pass under /usr/bin/python3. One disclosed tension: the job acceptance asked for
the REAL/GUARDLESS lines quoted in the worker's summary, and `results/load-bearing-row.json` carries the job title as its summary.

VERDICT: APPROVED
