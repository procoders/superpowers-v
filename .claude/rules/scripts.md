---
paths:
  - "scripts/*.py"
  - "scripts/cvcore/*.py"
---

# Python scripts

- Standard library only, Python 3.9 floor; the named exception is CI tooling, where
  `scripts/lint-frontmatter.py` imports PyYAML. (`CONVENTIONS.md:58-62`)
- The entry point sets `sys.dont_write_bytecode` and puts its own directory on `sys.path`.
  (`scripts/compound-v.py:7-8`)
- Receipts, outcomes, scope verdicts and usage are written by the CLI from real command results,
  never by the model. (`CONVENTIONS.md:32-33`)
- A receipt keeps at most the last 20 lines of a command's output. (`scripts/cvcore/receipts.py:138-139`)
- Durable state goes to `docs/compound-v/` (project) or the repo's git dir (`.git/compound-v/`, the receipt key), never under the plugin root.
  (`CONVENTIONS.md:49-54`)
- An unknown cost stays `null`, never a substituted zero. (`scripts/cvcore/usage.py:126-130`)
- The new core stays at or under 2550 lines. (`CONVENTIONS.md:63-64`)
