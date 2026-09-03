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

---

## Updated 2026-09-03 — epic-gp-matcher-docs (F2)

Audit: `docs/superpowers/library-audit/2026-09-03-epic-gp-matcher-docs.md`. Sibling of the
`epic-gp-one-matcher` (F1) entry that would otherwise sit above this one chronologically —
F1 shipped the code (`compound-v-memory.py` delegates to the scope gate's matcher instead
of `fnmatch`, merged per `docs/superpowers/dogfood/2026-09-03-epic-gp-one-matcher-review-1.md`);
F2 is a pure two-file doc-sync (`skills/compound-v/memory.md`,
`skills/compound-v/execution-manifest.md`) with **zero third-party dependencies** —
confirmed via the standard manifest `Glob` sweep, zero matches, same as every other
Compound V audit to date.

**Live source-of-truth citations for the "one glob contract," so the next 1C pass on this
topic doesn't have to re-derive them:**
- The six-rule semantics (`*` single-segment / `**` cross-segment incl. `dir/**`⇒`dir` /
  `?` one non-`/` char / `[`,`]` literal / fully anchored) live in
  `scripts/compound-v-scope-check.py:317-382` (`glob_to_regex`/`matches`/`is_allowed`).
- The **bare-path-recursive** reading ("`dir` also means everything under `dir`") exists
  **only** in `scripts/compound-v-memory.py:1115-1125` (`_file_matches`) — `scope-check.py`'s
  own `matches`/`is_allowed` have no such special-casing. A doc (or a future spec) that
  states `write_allowed`/`read_allowed` get this bonus would be documenting an **enforced**
  scope boundary incorrectly; it is `recall-check`-only.
- The cross-check both docs are meant to point readers at is the `parity` fixture list in
  `scripts/compound-v-memory.py:1632-1642` (tag: `# glob parity with the scope gate (epic
  2026-09-03-glob-parity F1): one matcher, two callers.`), run via `--selftest`. Confirmed
  passing post-F1-merge (all rows `ok`, including `bare dir == dir/**`) per
  `docs/superpowers/dogfood/2026-09-03-epic-gp-one-matcher-review-1.md`.

**Forward-pointer to the F2 entry above (PyYAML hard-import, no fallback,
`scripts/lint-frontmatter.py:31`):** F2's own acceptance criteria run
`/usr/bin/python3 scripts/lint-frontmatter.py` as AC #3. That command inherits the gap
recorded above — a `ModuleNotFoundError` on a machine without PyYAML importable under that
interpreter is an environment failure, not a defect in F2's doc edits, and could be
misdiagnosed as one. Not re-derived, not re-fixed here — cited so this spec's reviewer has
the context. This is the first spec whose *own acceptance criteria* directly exercise that
gap; prior entries only noted it as inherited shared infrastructure.

No prior entry needed strikethrough — additive only.

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

---

## Updated 2026-09-03 — v3.4.10-recall-to-action

Audit: [`docs/superpowers/library-audit/2026-09-03-v3-4-10-recall-to-action.md`](../2026-09-03-v3-4-10-recall-to-action.md).

### Python 3.9 EOL — independently re-confirmed same day, cross-checks the v3.4.5 entry above

- **2026-09-03 (WebSearch, separate query/session from the v3.4.5 entry above):** Python 3.9 reached
  end-of-life **2025-10-31**; **3.9.25** is the final release, no further patches of any kind will
  ever ship. Current stable line 3.14 (3.14.7, 2026-08-05); 3.15.0rc2 cut 2026-09-01. Numbers match
  the v3.4.5 entry exactly — recorded as an independent cross-check, not a re-derivation, so a future
  reader has two same-day, differently-sourced confirmations rather than one entry copy-pasted twice.
- Source: python.org 3.9.25 release notes; endoflife-tracker aggregation; Red Hat Developer
  (2025-12-04, "Python 3.9 reaches end of life").

### `match`/`case` (PEP 634) and runtime `X | Y` in `isinstance()`/`issubclass()` (PEP 604) — both 3.10+, and NOT covered by an existing `from __future__ import annotations` import

- **The gap this entry closes:** a file carrying `from __future__ import annotations` (confirmed
  present at `scripts/compound-v-emit-workflow.py:52`) is safe for `X | Y` union syntax **only in
  annotation position** (parameter/return/variable type hints) — that import defers annotation
  evaluation to strings. It does **not** protect a `match`/`case` statement, nor a runtime expression
  like `isinstance(x, str | None)` — both are evaluated immediately as language constructs, and both
  require CPython **3.10+** regardless of that future-import. A file floored at Python 3.9 (this
  repo's CI-pinned floor per the F2 entry above) breaks immediately, at parse or call time, if either
  appears — not a subtle runtime bug, a hard `SyntaxError` (`match`/`case`) or `TypeError`
  (`isinstance` with `|`).
- **Why this is a live risk, not a theoretical one:** `Grep` for `sys.version_info` across
  `scripts/` found zero matches — 3.9-compatibility is enforced **only** by CI's pinned
  `python-version: '3.9'` job (see the F2 entry above for that pin's exact location), never at
  runtime. Since 3.9 has been EOL for ~11 months as of this entry's date, a contributor's or
  dispatched worker's local interpreter is very likely newer, so 3.10+-only syntax written and
  locally tested would pass every check its author personally runs and fail only in CI (or, worse,
  only on a real end user's stock-3.9.6 macOS `python3`, which never runs this repo's CI at all).
- **Practical implication for any future spec that adds branching logic on a small fixed set of
  string/enum values to a `from __future__ import annotations`-carrying, 3.9-floored file in this
  repo:** use plain `if`/`elif`/`else` and the pre-3.10 tuple form `isinstance(x, (TypeA, TypeB))` —
  not `match`/`case`, not `isinstance(x, TypeA | TypeB)`. Cite this entry instead of re-deriving the
  distinction between "protected by `from __future__ import annotations`" (annotations only) and "not
  protected" (runtime expressions) from scratch.
- Source: direct `Grep` of `scripts/compound-v-emit-workflow.py` (import block, and a
  `match \w+:`/`case ["']`/`:=` sweep finding zero existing uses — no in-file precedent either way)
  + CPython language reference for PEP 604 and PEP 634 (both 3.10+, stable long-established facts,
  not re-fetched live this session since the version floor itself was never in question).

### DENSE-lane third-party packages (`numpy`, `onnxruntime`, `tokenizers`, `huggingface_hub`) — confirmed still isolated, still out of reach of `recall-check`

## Updated 2026-09-03 — epic-gp-one-matcher (F1)

Audit: [`docs/superpowers/library-audit/2026-09-03-epic-gp-one-matcher.md`](../2026-09-03-epic-gp-one-matcher.md).
No Context7 attached to this subagent (`ToolSearch` → no match); `bashCommandClamp` allowed
only the V-memory search script — all code inspection below is direct `Read`/`Grep` against
the live tree at current `HEAD`, 2026-09-03.

### Two competing in-repo patterns for loading `compound-v-scope-check.py` in-process — only one is safe to copy

F1 (`scripts/compound-v-memory.py`'s `_file_matches`) needs to import
`scripts/compound-v-scope-check.py` in-process to reuse its `matches(path, pattern)`. This
repo already has **two** different precedents for dynamically importing a sibling `.py` file
by path via `importlib.util.spec_from_file_location`/`module_from_spec`/`exec_module`, and
they are not interchangeable:

1. **Plain / unhardened** — `scripts/compound-v-discover-models.py:228-234`, inside a
   developer-invoked `--selftest` only, loads `compound-v-resolve-model.py`. No cache
   protection of any kind.
2. **Hardened** — `scripts/compound-v-integration-gate.py:417-470`
   (`load_scope_matcher`), loads **the same file F1 needs**
   (`compound-v-scope-check.py`). Redirects `sys.pycache_prefix` to a private
   `tempfile.mkdtemp()` directory before `exec_module`, and imports **nothing at all** if that
   directory cannot be created — restoring the prior prefix and removing the temp dir in a
   `finally`. Has dedicated selftest coverage (`:2372-2398`) that plants a forged
   `scripts/__pycache__/compound-v-scope-check.pyc` and asserts it is never executed.

**Why pattern 2 exists, evidenced not asserted:** `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-4.md`
("ISSUE 1 — QUALITY: the narrowed carve-out still hides a forged `.pyc`, and that `.pyc`
executes as the lane guard's own matcher — demonstrated end to end") records this as a
found-and-fixed vulnerability in this exact codebase, against this exact target file, days
before the one-matcher spec was written. `AGENTS.md`'s own top-of-file cost accounting calls
the `PYTHONPYCACHEPREFIX` redirection out by name as deliberate, non-free defense-in-depth.

**Why F1 must use pattern 2, not pattern 1 (and not a subprocess either):**
`compound-v-integration-gate.py`'s own **production** per-job scope check
(`run_scope_check:742-747`) avoids this whole question by shelling out —
`subprocess.run([sys.executable, scope_check], ...)`, with the comment *"A subprocess, not an
import: this script must not be able to perturb the matcher it is checking against."* A
subprocess running a script as `__main__` is never written to or read from `__pycache__`, so
it is naturally immune to the forged-bytecode class. But `recall_check` calls `_file_matches`
once per `(failure, changed-file)` pair in a nested loop — a subprocess-per-call design is not
viable there. Given in-process loading is the only workable choice for F1's call shape,
pattern 2 (hardened) is the only one of the two existing precedents that is safe to copy.
`agents/partition-reviewer.md:16-19` confirms `recall-check` is not interactive-only — it runs
automatically for every lane before every dispatch, the same automated trust boundary the
hardening was built to protect.

**Call-frequency trap for whoever implements this:** load once, reuse the callable. Do not
put the `spec_from_file_location`/`mkdtemp` dance inside `_file_matches` itself — it is called
many times per single `recall-check` invocation, and unlike `fnmatch.fnmatch` (pure stdlib,
no I/O), `tempfile.mkdtemp()` is a real filesystem syscall.

**Practical implication for any future spec that needs to consume `compound-v-scope-check.py`
from a third file:** cite `compound-v-integration-gate.py:417-470` as the reference
implementation, not `compound-v-discover-models.py`'s selftest form — the two are not
equivalent, and only one has been through an adversarial review pass against this specific
attack.

Sources: `scripts/compound-v-integration-gate.py:417-470,742-747,2372-2398` (`Read`/`Grep`,
this session, current HEAD) · `scripts/compound-v-discover-models.py:228-234` (`Grep`) ·
`agents/partition-reviewer.md:16-19` (`Grep`) ·
`docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-4.md` and `-review-5.md`
(V-memory recall, cross-checked against the live code above rather than trusted standalone) ·
`AGENTS.md` (root, `PYTHONPYCACHEPREFIX` cost-accounting paragraph).

- No new information beyond `_knowledge-base/agent-instruction-tooling.md`'s existing 2026-06-30
  entry (same packages, same isolated-venv architecture) — recorded here only as a cross-reference
  because this audit re-found the same imports (`compound-v-memory.py:453-454`, inside the
  string-embedded `EMBEDDER_SRC`) while scanning for anything Task A of v3.4.10 might touch, and
  confirmed by source read that `recall-check` (the FTS5-only, "NOT embedding similarity" path this
  spec's Decision section names explicitly) never reaches that code. See the audit above, §2, for the
  full reasoning; not re-litigated here to avoid duplicating the other KB file.
