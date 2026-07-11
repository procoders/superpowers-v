# Guardrail-Retry: Fallback When the Repo Has No Tests/Linter/Build

**Date:** 2026-07-11. Deep-dive follow-up, triggered by a direct user challenge to the prior
[guardrail-retry design](2026-07-11-guardrail-retry-pattern.md): "if the project has no
tests and no linter, how does this help at all?" Part of the
[2026 orchestrator landscape synthesis](2026-07-11-2026-orchestrator-landscape-synthesis.md).

**Honesty note on this research pass:** of five dispatched research angles, only angle 1
(coding-agent product behavior) returned fresh, session-verified, cited findings. Angles 2-5
below are reasoned synthesis from general knowledge, explicitly flagged as such rather than
presented with fabricated citations. This gap is noted so a future pass can re-verify section
4 (the tiered-ladder pattern) specifically, since a confirmed real-world precedent would
strengthen the design's justification.

---

## 1. What major coding-agent products do with no tests/lint/build configured — VERIFIED

- **Devin / Cognition** — the only product with a real, shipped, tooling-independent fallback:
  **computer-use/runtime verification**. Devin spins up the app, clicks through it, and
  confirms changes work visually — a test report with labeled screenshots and video. Activates
  autonomously for UI/navigation/form/visual tasks regardless of whether a test suite exists.
  ([cognition.com/blog/testing-development](https://cognition.com/blog/testing-development),
  [docs.devin.ai/work-with-devin/computer-use](https://docs.devin.ai/work-with-devin/computer-use))
- **Aider** — `--auto-lint` ships built-in linters for most languages, zero-config.
  `--auto-test` requires the user to supply a test command explicitly; with none configured,
  testing is simply inactive — no auto-detection, no bootstrap.
  ([aider.chat/docs/usage/lint-test.html](https://aider.chat/docs/usage/lint-test.html))
- **Cursor (Bugbot)** — static diff review only, never executes tests; can flag "missing
  tests" by pattern-matching changed files, but has no fallback for a repo with zero test
  infrastructure. ([cursor.com/docs/bugbot](https://cursor.com/docs/bugbot))
- **GitHub Copilot coding agent** — "automatically runs your project's tests and linter" in
  an ephemeral env; no documentation addresses the zero-tooling case.
  ([github.blog/changelog/2026-03-18](https://github.blog/changelog/2026-03-18-configure-copilot-coding-agents-validation-tools/))
- **OpenHands** — opt-in "Stop hooks" can block completion pending lint/test success, but
  this is not a default; with no hook configured, the agent finishes with no quality gate at
  all. ([docs.openhands.dev/openhands/usage/customization/hooks](https://docs.openhands.dev/openhands/usage/customization/hooks))

**Pattern**: Devin is the sole outlier with a real fallback independent of pre-existing
tooling. Every other product surveyed gates verification behind tooling that must already
exist. **This is a genuine, confirmed industry-wide documentation gap**, not a search-quality
artifact — five separate products, five separate negative results.

## 2. Universal syntax/parse/compile-only checks — real tools, unconfirmed as a ladder pattern

Per-language zero-config syntax/compile-only commands are real and stable: `python -m
py_compile`, `node --check`, `tsc --noEmit` (needs a tsconfig), `go build`/`go vet` (needs
go.mod), `cargo check` (needs Cargo.toml), `ruby -c`, `php -l`, `javac -Xlint`. **What is NOT
independently confirmed**: whether any 2026 coding-agent product or CI framework treats this
tier as a documented, automatic fallback specifically invoked *because* a project test/lint
command was absent. Treat as a real, usable building block — not a validated industry pattern.

## 3. Auto-bootstrapping a minimal check — no evidence found

No verified evidence that any major agent detects "zero verification tooling" and proactively
offers to add a minimal one. Consistent with §1's negative results across five products.
Flagged as an open question (not checked: Replit Agent, Windsurf, Amazon Q Developer, Cline,
Continue.dev), not a confirmed absence.

## 4. The tiered ladder (1: real tests → 2: syntax-only → 3: cheap LLM diff-read → 4: full review)

Honest breakdown: tier 1 is standard practice everywhere (evidenced). Tier 2's underlying
tools are real (§2) but no product was found chaining them as an explicit fallback rung. Tier
3 (single-pass LLM diff review) is a well-established technique in isolation (LLM-as-judge,
self-critique literature; CodeRabbit/Greptile-style tools run LLM diff review) but not
confirmed as *specifically the fallback invoked only when tiers 1-2 are unavailable*. **The
ladder itself, as a deliberate cascade gated on what's configured in the repo, is original
design work for Compound V — not a copied industry pattern.** State it that way, don't
oversell it as "best practice."

## 5. Honest cost-benefit: is skipping the cheap gate for a no-tooling repo actually correct?

Two real, opposing arguments:

- **Skipping is correct** when the alternative would be a *fake* check — a lint pass that
  always exits 0 because nothing's configured produces false confidence, worse than no check
  at all (echoes Michael Feathers' "legacy code = code without tests": the real fix belongs
  upstream, not in a downstream workaround that manufactures a fake signal).
- **Skipping has a real, avoidable cost** when a *genuine* zero-config check exists and is
  simply not being used — a parse/compile-only check catches a narrow but real failure class
  (unclosed brackets, truncated generations, wrong-language files, import typos) at near-zero
  cost, before paying for a full expensive review that would catch the same trivial errors at
  10-100x the cost/latency. Treating "no project-specific test/lint" as "no cheap check
  possible" conflates *behavioral correctness* (genuinely needs tests) with *basic structural
  validity* (needs only a language-aware parser, already on the machine).

**Resolution**: don't fabricate a fake project-specific check. Do use a real, free,
already-available language-level one. That's exactly tier 2 below.

## 6. Recommended tiered design for Compound V

Tiers 1-2 are fully deterministic, no LLM. Tier 3 is a narrow, proportionate LLM exception —
an explicit, deliberate departure from the prior research's "deterministic-only for v1"
stance, justified only for the case where NEITHER a real test/lint command NOR a language
parse-check applies (e.g. a docs-only or copy-only diff — no code, nothing to compile).

| Tier | Trigger | Mechanism | Deterministic? | Cost |
|---|---|---|---|---|
| 1 | Project test/lint/build configured | Run the configured command | Yes | Existing (variable) |
| 2 | No project command, but a touched file's language has a toolchain on PATH | `py_compile`/`node --check`/`tsc --noEmit` (if tsconfig exists)/`go build` (if go.mod)/`cargo check` (if Cargo.toml)/`ruby -c`/`php -l` on git-diff-touched files only | Yes | Sub-second |
| 3 | Neither 1 nor 2 applies (docs/config/copy-only diff) | ONE fast model call, diff-only input, narrow smoke-test question ("internally consistent with the stated job, no obvious break/placeholder left in") — NOT a correctness review | No (1 fast call) | Low, proportionate — categorically cheaper than the full gate it stands in for |
| 4 | Tier 3 unavailable | Existing full three-pass `spec-reviewer`, unchanged | N/A | Existing (highest) |

**Bootstrapping belongs in `/v:onboard`, never inside the gate.** The guardrail-retry gate
should only *detect and use* what already exists (tier 2 needs zero installation — it's part
of the language toolchain, not project config). Proposing to *add* real test infrastructure to
an untested project is a human-gated onboarding decision, matching the existing
propose-then-confirm pattern `/v:onboard` already uses for MCP tool recommendations (v2.5.1) —
never invented ad-hoc mid-job inside the retry gate.

## Sources verified this session (§1 only)

cognition.com/blog/testing-development · docs.devin.ai/work-with-devin/computer-use ·
docs.devin.ai/get-started/devin-intro · aider.chat/docs/usage/lint-test.html ·
aider.chat/docs/config/options.html · cursor.com/docs/bugbot · cursor.com/blog/bugbot-autofix ·
docs.github.com/copilot/concepts/agents/coding-agent/about-coding-agent ·
github.blog/changelog/2026-03-18-configure-copilot-coding-agents-validation-tools/ ·
docs.github.com/en/copilot/responsible-use/copilot-coding-agent ·
docs.openhands.dev/openhands/usage/customization/hooks · OpenHands/software-agent-sdk#1527 ·
devops.com/meta-researchers-show-ai-agents-can-verify-code-without-running-it-and-hit-93-accuracy/ ·
arxiv.org/pdf/2603.01896

Sections 2-5 are reasoning/synthesis, not fresh-cited — flagged inline above.
