@AGENTS.md

## Claude Code

- This repository is built with Compound V 4 itself: brainstorm → build (one builder researches,
  plans and codes) → verify, with run records in `docs/compound-v/runs/`. Load the plugin from this checkout with
  `claude --plugin-dir .`, or run `/compound-v:init` once if it is installed.
- Model policy: Opus by default, Sonnet for mechanical tasks chosen at dispatch, never Haiku except the
  read-only `v-memory` agent, Fable only by explicit choice. `scripts/lint-frontmatter.py` enforces it.
- Where things are: the CLI in `scripts/compound-v.py` + `scripts/cvcore/`, hooks in `hooks/`, the
  cycle prose in `skills/`, subagents in `agents/`, design and plan in `docs/compound-v/`, the
  evidence for v4 in `docs/v4/`, v3's docs in `docs/archive/v3/`. Conventions: `CONVENTIONS.md`.
- Tests: `python3 -m unittest discover -s tests/core -v`, then
  `for t in tests/hooks/*.sh; do bash "$t"; done`, `python3 scripts/lint-frontmatter.py .` and
  `shellcheck hooks/*.sh`.
- Never run a live headless worker with `--dangerously-skip-permissions` against this checkout; test
  end to end in a throwaway repo.
