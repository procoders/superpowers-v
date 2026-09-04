---
paths:
  - "scripts/*.py"
---

# Python helper scripts

Sourced from `CONVENTIONS.md` §"Python: stdlib only" and §"No fabricated metrics (anti-ruflo)".
  (`CONVENTIONS.md:12-24`, `CONVENTIONS.md:79-87`)

- Pure Python **standard library** — no third-party runtime dependency. The scope gate states the
  floor: "Python 3.9-safe, stdlib only. Targets stock-macOS python3 3.9.6."
  (`scripts/compound-v-scope-check.py:141`, `scripts/compound-v-onboard.py:1-2`)
- The exception is named, not open: `scripts/lint-frontmatter.py` imports PyYAML unconditionally
  (`scripts/lint-frontmatter.py:35`), and CI installs `pyyaml` + `jsonschema` before the selftest
  sweep because those two are the only third-party deps any selftest needs.
  (`.github/workflows/validate.yml:296-301`)
- Reuse a canonical shared constant instead of forking a second copy — the secret-pattern families are
  imported from `compound-v-memory.py`, never redefined. (`scripts/compound-v-onboard.py:5-9`)
- Ship a built-in `--selftest`. The pattern to copy is the scope gate's: it builds throwaway git repos
  in `$TMPDIR` and runs offline. (`scripts/compound-v-scope-check.py:626`)
- CI sweeps every `scripts/*.py` that mentions `--selftest` and fails the build on any that fails;
  discovery is dynamic, so a new script is picked up with no registration step.
  (`.github/workflows/validate.yml:298-312`)
- A test script parked in `scripts/` is a test CI never runs — that sweep globs `scripts/*.py` only,
  and everything under `tests/` belongs to a separate job. Put tests in `tests/`.
  (`.github/workflows/validate.yml:314-315`)
- Never print a token-cost or savings number you cannot measure; CI greps `scripts/` and `docs/` for
  fabricated-metric phrasing and fails the build on a hit. (`.github/workflows/validate.yml:185-214`)
- Measurement that is absent stays absent: a missing or unparseable usage source yields
  `measured:false` with null counts, never a substituted zero.
  (`scripts/compound-v-usage-extract.py:17-27`)
