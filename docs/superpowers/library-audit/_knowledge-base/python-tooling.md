# Python Tooling Library Knowledge Base

Maintained by Compound V Phase 1C validator. Append at the bottom.

---

## Updated 2026-09-03 — epic-vi-readme-section (F2)

**PyYAML in `scripts/lint-frontmatter.py`: hard `import yaml`, no fallback — contradicts this project's own "stdlib only, pyyaml optional with fallback" design promise.**

- **Library status (checked live, 2026-09-03, WebSearch — no Context7 available this session):** PyYAML is current and healthy. Latest PyPI release **6.0.3**. libraries.io rates its maintenance "Sustainable," with a release in the past 12 months. Canonical repo `yaml/pyyaml` on GitHub, MIT-licensed, not archived, not deprecated. 🟢 OK as a library in its own right — this entry is not a staleness finding.
  - Source: <https://pypi.org/project/PyYAML/>, <https://libraries.io/pypi/PyYAML>, <https://github.com/yaml/pyyaml/>

- **The documented promise:** `docs/superpowers/plans/2026-06-26-compound-v-orchestrator-v1-plan.md`:
  - Design-decisions table, line 49: *"Stock macOS = bash 3.2.57 / python 3.9.6 ... All helper scripts target bash 3.2 + py 3.9, stdlib only (+ optional pyyaml with fallback)."*
  - §7 Cross-cutting requirements, line 155: *"Scripts target bash 3.2 + python 3.9, stdlib only (no npm/pip mandatory deps; pyyaml optional with fallback)."*

- **The code, as shipped (verified 2026-09-03 via direct file read + Grep):** `scripts/lint-frontmatter.py:31` is a bare, unconditional `import yaml` at module top level. The file's only `try`/`except` blocks (lines 110/112, 202) catch YAML *parse* errors inside the linter's own logic — none guard the *import statement itself*. There is no `ImportError` handler and no stdlib fallback path anywhere in the file. If PyYAML is not importable under the invoking `python3`, the script raises `ModuleNotFoundError` and exits nonzero before running any lint logic — it does not degrade to a reduced-functionality or skip mode.

- **Why the gap hasn't surfaced as breakage yet:**
  - CI (`.github/workflows/validate.yml`) explicitly installs PyYAML, unpinned, before every invocation that needs it: line 115 (`pip install pyyaml`, before the main `lint-frontmatter.py .` run) and lines 294/342 (`pip install --quiet pyyaml jsonschema`, before selftest runs).
  - This plugin's own `AGENTS.md` (root) documents, for an unrelated hook (`hooks/lane-guard.sh`), that "the ordinary machine" on macOS has PyYAML importable under `/usr/bin/python3` as its *first* candidate interpreter — implying that assumption is a per-machine fact the codebase already knows it cannot take for granted everywhere (hence that hook's own multi-candidate probing ladder, which `lint-frontmatter.py` does not have).

- **Practical implication for any future spec whose acceptance criteria route through `scripts/lint-frontmatter.py`** (this is a recurring gate across the whole plugin, not specific to any one feature): the command is reliable on the two paths this repo actually exercises today (CI; the AGENTS.md-documented "ordinary" macOS dev box). On any other machine — a contributor without a prior `pip install pyyaml`, or a `python3` resolution that lands on an interpreter without it — the acceptance command fails with an environment error, not a real lint finding, and could be misread as a defect in the feature under review rather than in shared tooling.

- **Disposition:** not fixed here — this is pre-existing shared infrastructure (Phase 1A / code-archaeology territory), not something any single small feature introduces or owns. Recorded so the next Phase 1C pass that touches this script doesn't have to re-derive it, and so a reviewer who hits the `ModuleNotFoundError` failure mode on an unusual machine has a documented explanation.

- No prior entry in this file to strike through — this is the first KB entry for this topic.

---

## Updated 2026-09-03 — v3.4.5-recall-freshness

Audit: `docs/superpowers/library-audit/2026-09-03-v3-4-5-recall-freshness.md`.

### Python 3.9 end-of-life (live-confirmed date, cross-references the F2 entry above)

- **2026-09-03 (WebSearch):** Python 3.9 reached end-of-life on **2025-10-31**; **3.9.25** was the final release (no further bugfix or security patches will ever be issued). Current stable line as of this date is **3.14** (3.14.7, 2026-08-05), with 3.15.0rc2 cut 2026-09-01 and GA expected October 2026.
  Sources: python.org 3.9.25 release notes; endoflife.date/python; Red Hat Developer (2025-12-04, "Python 3.9 reaches end of life").
- This does not contradict the F2 entry above — it confirms the *reason* `python-version: '3.9'` in `.github/workflows/validate.yml:280-283,343-346` is now a **frozen** floor, not merely an old one: that pin will resolve to the same 3.9.25 build indefinitely, with no forward patch-level drift risk but also no future security fix, ever, for this interpreter line. Recorded so the next Phase 1C pass touching any `scripts/*.py` with a `--selftest` doesn't have to re-derive the EOL date.

### `sqlite3` (stdlib) — `Connection.autocommit` / `LEGACY_TRANSACTION_CONTROL` default, live-verified

- **2026-09-03 (WebFetch, `docs.python.org/3/library/sqlite3.html#sqlite3.Connection.autocommit`):** `Connection.autocommit` currently defaults to `sqlite3.LEGACY_TRANSACTION_CONTROL` in every shipping CPython through 3.14 (and 3.15 as of rc2). Under that default, `isolation_level` governs implicit-transaction behavior and explicit `BEGIN <mode>` / `COMMIT` / `ROLLBACK` statements executed via `Connection.execute()` behave exactly as pre-3.12 Python always did — this is the pattern `scripts/compound-v-memory.py`'s `_persist_chunks` (`BEGIN IMMEDIATE` ... `COMMIT`/`ROLLBACK`) already relies on, and it remains current with no signature drift.
- **Forward-compat trap, not a current bug:** Python's own docs say *"the default will change to `False` in a future Python release"* and recommend migrating to `sqlite3.connect(path, autocommit=False)` (PEP-249-compliant mode) — but the `autocommit` keyword argument to `connect()` **does not exist before Python 3.12**. Any script pinned to the Python-3.9 floor (see above) that adds this kwarg breaks immediately with `TypeError`, not a subtle bug. No removal date is published for `LEGACY_TRANSACTION_CONTROL` itself.
- **Practical implication for any future spec that touches this codebase's `sqlite3` usage:** do not "modernize" `sqlite3.connect()` calls to the newer `autocommit=` form while the project's floor stays at 3.9 — verify the floor first, per the entry above, before applying any upstream-recommended `sqlite3` migration.
- Source: `docs.python.org/3/library/sqlite3.html` (fetched live 2026-09-03; no Context7 available this session — see the audit's §1 for why).

---

## Updated 2026-09-03 — v3.4.6-triage-test-scoping-fixes

Audit: [`docs/superpowers/library-audit/2026-09-03-v3-4-6-triage-test-scoping-fixes.md`](../2026-09-03-v3-4-6-triage-test-scoping-fixes.md).

### `isinstance(v, int) and not isinstance(v, bool)` — this repo's established guard for validating an integer manifest field, worth citing by name instead of re-deriving

- Python's `bool` is a subclass of `int` (language semantics, not a version-specific fact — true in
  every CPython release this repo has ever targeted). A bare `isinstance(v, int)` check therefore
  silently accepts `True`/`False` as `1`/`0` for any manifest field documented as "a positive
  integer" — a classic, easy-to-miss trap when validating hand-authored YAML/JSON where a boolean is
  just as plausible a typo as a string.
- **This repo already has an established, repeated defense**, found by direct read of
  `scripts/compound-v-validate-manifest.py`: the `isinstance(v, int) and not isinstance(v, bool)`
  guard (or its negation, `not isinstance(v, int) or isinstance(v, bool)`) appears at **six** sites —
  lines 999, 1344, 1346, 1352, 2362, 2554 — each validating a different integer-typed manifest field.
  This is house style, not a one-off.
- **Practical implication for any future spec that adds a new integer-typed manifest or contract
  field to this file** (the v3.4.6 spec's own `test_contract.timeout_s` is the worked example this
  entry was written for): use the same guard. A plain `isinstance(v, int)` check would pass this
  file's own pattern-matching review at a glance while being silently wrong for a boolean input — cite
  this entry, or the six existing line numbers above, instead of re-deriving the trap from scratch.
