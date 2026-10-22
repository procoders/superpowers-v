---
paths:
  - "docs/**/*.md"
---

# Docs

- Never write a cost, time, token or savings number that was not measured; every number names its
  source, and salon numbers come only from `docs/v4/salon-report.md`. (`CONVENTIONS.md:8-9`)
- Dollar figures are the CLI's own cost record, labelled "the CLI's estimate"; an unknown cost stays
  `null`. (`CONVENTIONS.md:10-13`)
- Project state lives under `docs/compound-v/` (specs, plans, pre-flights, runs).
  (`CONVENTIONS.md:45-46`, `scripts/cvcore/run.py:15`)
- Run records under `docs/compound-v/runs/` are written by the CLI only; never edit them by hand.
  (`CONVENTIONS.md:30-31`, `scripts/cvcore/hooks.py:289`)
- Onboard output goes to `docs/compound-v/architecture/`, and every claim there carries a `file:line`
  citation that must resolve. (`skills/onboard/SKILL.md:3`, `skills/onboard/SKILL.md:25`)
