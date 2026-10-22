---
paths:
  - "scripts/*.py"
  - "scripts/cvcore/*.py"
---

# Python scripts

- Standard library only, Python 3.9 floor; the named exception is CI tooling, where
  `scripts/lint-frontmatter.py` imports PyYAML. (`CONVENTIONS.md:54-58`)
- The entry point sets `sys.dont_write_bytecode` and puts its own directory on `sys.path`.
  (`scripts/compound-v.py:7-8`)
- Receipts, outcomes, scope verdicts and usage are written by the CLI from real command results,
  never by the model. (`CONVENTIONS.md:28-29`)
- A receipt keeps at most the last 20 lines of a command's output. (`scripts/cvcore/receipts.py:81-88`)
- Durable state goes to `docs/compound-v/` or `~/.claude/compound-v/`, never under the plugin root.
  (`CONVENTIONS.md:45-50`)
- An unknown cost stays `null`, never a substituted zero. (`scripts/cvcore/usage.py:84-88`)
- The new core stays at or under 2500 lines. (`CONVENTIONS.md:59-60`)
