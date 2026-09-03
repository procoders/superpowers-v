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
