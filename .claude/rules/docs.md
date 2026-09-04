---
paths:
  - "docs/**/*.md"
---

# Generated and working docs

Sourced from `CONVENTIONS.md` §"Doc placement" and §"No fabricated metrics (anti-ruflo)".
  (`CONVENTIONS.md:123-134`, `CONVENTIONS.md:79-87`)

- Compound V writes to a flat, predictable structure under `docs/superpowers/`.
  (`skills/compound-v/SKILL.md:209-211`)
- Onboarding's own output goes to `docs/superpowers/architecture/*` plus the root `CONVENTIONS.md`,
  `AGENTS.md` and the `CLAUDE.md` bridge. (`skills/compound-v/onboarding.md:9-13`)
- Architecture prose is **read-then-cite**: every claim carries a `file:line` citation, and a cited
  path that does not resolve strictly INSIDE this repo — or whose range is out of bounds — is
  blocking; the claim is regenerated or dropped, never shipped.
  (`skills/compound-v/onboarding.md:96-100`)
- Every intra-repo markdown link must resolve. The dead-link scan runs **last** in its job so
  cross-refs to files authored by later batches resolve at integration time.
  (`.github/workflows/validate.yml:232-234`, `.github/workflows/validate.yml:271-274`)
- Never print a token-cost or savings number you cannot measure — the anti-ruflo grep covers `docs/`
  as well as `scripts/`. (`.github/workflows/validate.yml:185-214`)
