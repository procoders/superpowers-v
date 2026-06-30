# Domain-Expert Audit — /v:onboard (Compound V) — 2026-06-30

Phase 1B (domain reality). Stress-tests the spec's locked decisions; does not restate
what is already decided. Companion to Phase 1A (code archaeology) and Phase 1C (library
currency). Scope here: the agent-instruction-file standard, the MCP lethal-trifecta
security model, WCAG/design-token accessibility, and the staleness/citation model.

---

## 1. Domain(s) Identified
1. **agent-instruction-files** — AGENTS.md / CLAUDE.md layered memory model, cross-tool standard, bridging.
2. **mcp-agent-security** — lethal trifecta, least-privilege MCP, the 2025 Supabase + GitHub incidents.
3. **design-md-tokens** — DESIGN.md (Google Labs alpha), design-token extraction, WCAG contrast.

(Citation-verification mechanics, secret scanning, and git-tracking are Phase 1A/1C territory and are touched here only where a domain rule bears on them.)

## 2. Sources Consulted
- KB reused: none (KB was empty). KB created this pass: `agent-instruction-files.md`, `design-md-tokens.md`.
- Primary docs fetched: [Claude Code memory](https://code.claude.com/docs/en/memory) · [design.md spec.md](https://github.com/google-labs-code/design.md/blob/main/docs/spec.md) · [design.md README](https://github.com/google-labs-code/design.md).
- Primary security: [Willison lethal trifecta (Jun 2025)](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) · [Willison Supabase (Jul 2025)](https://simonwillison.net/2025/Jul/6/supabase-mcp-lethal-trifecta/) · [Invariant GitHub MCP](https://invariantlabs.ai/blog/mcp-github-vulnerability) · [Invariant toxic-flow](https://invariantlabs.ai/blog/toxic-flow-analysis) · [github-mcp-server#844](https://github.com/github/github-mcp-server/issues/844).
- Standard status: [LF AAIF press](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation) · [OpenAI AAIF](https://openai.com/index/agentic-ai-foundation/).
- Practitioner (Layer 3, dated below): HN [45788866](https://news.ycombinator.com/item?id=45788866), [45791391](https://news.ycombinator.com/item?id=45791391); [codegateway](https://www.codegateway.dev/en/blog/agents-md-playbook-2026); [obviousworks](https://www.obviousworks.ch/en/designing-claude-md-right-the-2026-architecture-that-finally-makes-claude-code-work/); Tailwind [discussion #18748](https://github.com/tailwindlabs/tailwindcss/discussions/18748); [accessibility-test.org WCAG](https://accessibility-test.org/blog/support/advanced-guides/color-contrast-in-wcag-2-2-testing-and-fixes-that-actually-work/).

---

## 3. Domain Constraints the Brainstorm Probably Missed

**MUST**
1. **MUST treat the managed-policy CLAUDE.md layer as untouchable.** Org-deployed `CLAUDE.md` (macOS `/Library/Application Support/ClaudeCode/CLAUDE.md`, Linux `/etc/claude-code/CLAUDE.md`) "cannot be excluded by individual settings" and `claudeMdExcludes` is ignored for it ([memory docs](https://code.claude.com/docs/en/memory)). The "responsible doctor" must NEVER recommend restructuring/overriding managed-layer content, and must NEVER flag a managed-layer rule as a "contradiction to fix" — it can only add at the project layer and surface the conflict as *informational*. The spec's diagnosis bullet says "contradictions across managed/user/project/local layers" as if all four are equally editable; the managed layer is read-only to onboarding by construction.
2. **MUST NOT claim a token-passing `design.md lint` proves accessibility.** The linter checks flat `backgroundColor`/`textColor` pairs at 4.5:1 only. It is blind to gradients, opacity/alpha blending, background images, and runtime (dark-mode/CSS-variable) theming ([accessibility-test.org](https://accessibility-test.org/blog/support/advanced-guides/color-contrast-in-wcag-2-2-testing-and-fixes-that-actually-work/), [Deque axe](https://dequeuniversity.com/rules/axe/4.8/color-contrast)). The human-gate text MUST phrase the DESIGN.md gate as "token pairs pass WCAG AA structurally" — not "UI is accessible."
3. **MUST build token extraction itself; `@google/design.md` does not reverse-extract.** Verified against the README: export is one-directional (DESIGN.md → `json-tailwind`/`css-tailwind`/`dtcg`). There is **no** feature to parse `tailwind.config`/CSS and produce a DESIGN.md. The linter validates the authored file's internal consistency, never its fidelity to the source code. So §8's "extracted from real sources… verified by the official linter" conflates two things: extraction (our code, unverified by the tool) and lint (file-internal only). A linted DESIGN.md whose tokens were mis-extracted is *confidently wrong*.
4. **MUST scope nested instruction files or accept context bloat.** Codex concatenates global + every AGENTS.md from git-root to cwd, capped 32 KiB, closer-wins ([codegateway 2026](https://www.codegateway.dev/en/blog/agents-md-playbook-2026)). If /v:onboard writes a root AGENTS.md in a monorepo that already has package-level ones, it adds to a chain that "fills the cap quickly" and unscoped content leaks across packages. Onboarding MUST detect existing nested instruction files and write root-level content that stays generic, or recommend package-level placement.

**MUST NOT**
5. **MUST NOT assert a strict AGENTS.md-vs-CLAUDE.md precedence to the user.** Inside Claude Code there is no semantic "X wins" rule — files are *concatenated*, and "if two rules contradict, Claude may pick one arbitrarily" ([memory docs](https://code.claude.com/docs/en/memory)). The widespread "CLAUDE.md has absolute top authority" / "AGENTS.md wins for project rules" claims are community folklore, not doc-backed. The diagnosis output must describe layering as *positional concatenation with arbitrary tie-break*, and the fix for contradictions is *removal*, not relying on precedence.

**SHOULD**
6. **SHOULD position the bridge as compatibility, not novelty.** `/init` already reads AGENTS.md/.cursorrules/.windsurfrules/.devin and incorporates them; `CLAUDE_CODE_NEW_INIT=1` already does explore→propose→review-before-write ([memory docs](https://code.claude.com/docs/en/memory)). The detect-and-bridge half of /v:onboard overlaps native /init. The genuine differentiator (per the spec's own §1) is the cited recall/orchestrator loop — lead with that, and avoid re-litigating bridging the user can get from `/init`.

---

## 4. Common Traps in This Domain
- **The "linted = correct" trap (DESIGN.md).** Green lint on a mis-extracted token file. Mitigation: the human gate must show the *source evidence* for each token (which `tailwind.config` key / CSS var), exactly as the MCP recommender shows file evidence — not just the linter verdict.
- **The CSS-variable / dark-mode collapse.** A single token resolves to multiple rendered colors under theming; a static extractor records one. A `--primary` that is `#fff` in light and `#111` in dark cannot be one token row. Detect `prefers-color-scheme` / theme files and either emit per-theme tokens or flag "multi-theme — not fully captured."
- **Arbitrary-value blindness (Tailwind).** Real in-use colors live in `className="text-[#1a2b3c]"` strings, not config. A config-only extractor under-reports used colors and over-reports unused config tokens ([Tailwind #18748](https://github.com/tailwindlabs/tailwindcss/discussions/18748)). Tailwind v3 (JS config) vs v4 (`@theme` CSS) need different parsers; v3 configs are often computed JS, not static JSON.
- **Symlink confusion (the bridge).** `ln -s AGENTS.md CLAUDE.md` "often gets confused, requiring several iterations" (HN [45788866](https://news.ycombinator.com/item?id=45788866), 2025-11). The spec already chose `@AGENTS.md` import over symlink — correct call; keep it, and don't offer the symlink as an equal option on Windows (it needs admin/Developer Mode).
- **Staleness false-negative (see §6 of spec).** Cited-file-hash drift catches "the code moved." It cannot catch "the doc was wrong on day one" or "the architecture changed in a file the doc never cited." A doc describing auth can rot when a *new, uncited* auth file appears. Hash-drift is necessary, not sufficient.
- **The auto-generated-architecture distrust tax.** Practitioners report `/init` "hallucinates file structures, recommends wrong libraries" ([obviousworks 2026](https://www.obviousworks.ch/en/designing-claude-md-right-the-2026-architecture-that-finally-makes-claude-code-work/)). Generated architecture prose starts with negative trust; the citation gate is what earns it back — which is exactly why Tier-2 being advisory (below) is the riskiest locked decision.

## 5. Regulatory / Compliance Notes
- **No statutory regulation** governs CLAUDE.md/AGENTS.md/DESIGN.md content. But two compliance-adjacent rules bind:
  - **Accessibility (WCAG 2.2 AA, 4.5:1 normal text / 3:1 large & UI components).** Relevant because EU Accessibility Act (in force Jun 2025) and ADA/Section 508 reference WCAG. /v:onboard does not *make* a product compliant, but it MUST NOT emit a DESIGN.md that *claims* compliance it cannot verify (see MUST #2) — that is a misrepresentation an auditor would flag.
  - **Secret-handling.** The blocking secret scan is correct and non-negotiable; the domain addition is that `.onboard-manifest.json` stores cited file paths + hashes — ensure the manifest itself never embeds a cited *snippet* that contains a secret (hash-only is safe; quoted line context is not).
- **MCP security is governance, not law,** but the lethal trifecta is now the de-facto standard of care; shipping a recommender that co-enables it without warning would be negligent by 2026 community norms (§6 below).

## 6. Recent Breaking Changes / Reality Checks (last 12 months)
- **AAIF formed Dec 2025** (LF), folding AGENTS.md + MCP + goose under one foundation. The spec's "Linux Foundation AAIF standard" label is **correct and current**. ([LF press](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation))
- **Supabase MCP service-role exfiltration — REAL, disclosed Jul 2025.** Confirmed via Willison + General Analysis + Supabase's own defense-in-depth post. ([Willison](https://simonwillison.net/2025/Jul/6/supabase-mcp-lethal-trifecta/))
- **GitHub MCP toxic-flow — REAL, Invariant Labs May 2025.** Confirmed via Invariant + the open github-mcp-server#844 issue. Root cause is architectural (PAT over-scope), "no obvious fix." ([Invariant](https://invariantlabs.ai/blog/mcp-github-vulnerability), [#844](https://github.com/github/github-mcp-server/issues/844))
- **`@google/design.md` is `alpha`** — spec/CLI under active development, "components specification is actively evolving." A blocking gate on an alpha CLI is a supply-chain/version-pin risk: pin the version and tolerate the linter changing rule IDs.
- **Tailwind v4 (CSS-first `@theme`) vs v3 (JS config)** is a live fork in extraction strategy as of 2026. ([Mavik 2026](https://www.maviklabs.com/blog/design-tokens-tailwind-v4-2026/))
- **Claude Code memory facts that drifted from the spec's wording:** the 200-line figure is a *target/recommendation* ("loaded in full regardless of length"), not a ceiling; the 200-line/25KB hard cap applies to auto-memory `MEMORY.md`, not CLAUDE.md. ([memory docs](https://code.claude.com/docs/en/memory))

---

## 7. Design Constraints for the Plan (non-negotiable)
1. The managed-policy CLAUDE.md layer is **read-only and un-excludable**; onboarding writes only at project layer and surfaces managed-layer conflicts as informational, never as "fix this."
2. The DESIGN.md gate's human-facing language is **"token pairs pass WCAG AA structurally,"** never "accessible." Document the linter's blindness to gradient/opacity/theming in the gate output.
3. **Token extraction is owned code, separately validated.** The human gate shows per-token *source evidence* (config key / CSS var / class string). `design.md lint` PASS is necessary but not sufficient; it does not certify extraction fidelity.
4. Token extraction **handles Tailwind v3 (JS config) AND v4 (`@theme` CSS) AND arbitrary-value class strings AND multi-theme**, or explicitly flags each unhandled case as "partial capture" at the gate.
5. The diagnosis describes layered memory as **positional concatenation with arbitrary tie-break** — not strict precedence. Contradiction fixes are *removals*, not reliance on a winner.
6. Bridge uses **`@AGENTS.md` import, not symlink** (already chosen — keep; do not present symlink as an equal option, especially on Windows).
7. In monorepos, detect **existing nested instruction files** before writing a root AGENTS.md; keep root content generic or recommend package-level placement; respect the 32 KiB practical chain budget for cross-tool readers.
8. **MCP recommender: default read-only / least-privilege flags are the primary control; the warning is the backstop** (see §8 below for the warn-vs-block ruling). Read-only neutralizes the Supabase pattern at the source; the GitHub-PAT pattern needs single-repo/token-scoping, which read-only does NOT fix — call that out specifically.
9. **Pin the `@google/design.md` version** in the blocking gate; treat rule-ID changes on the alpha CLI as expected churn.
10. Staleness signal is **hash-drift PLUS a new-uncited-file heuristic** (a doc about subsystem X should be re-reviewed when new files matching X's paths appear that the doc never cited) — see §8 ruling on staleness.

## 8. Locked Decisions I Would Challenge (with the domain reason)

**(A) "lethal-trifecta = warn-only" — DEFENSIBLE, with one carve-out. Confidence: high.**
Warn-only is the right *default* and matches Willison's own framing (he advocates avoiding the combination and is skeptical of guardrail products, not of informed user choice). Crucially, the spec already pre-fills `--read-only` for Postgres and Supabase — that *eliminates the write leg* of the Supabase incident at the source, so by the time the warning fires, the demonstrated attack is already defused. **The carve-out:** the GitHub toxic-flow incident is NOT fixed by read-only — it is read(public issue)→read(private repo)→write-to-public-PR, defeated only by single-repo-session or token-scoping ([Invariant](https://invariantlabs.ai/blog/mcp-github-vulnerability)). So warn-only is negligent *only* for the specific case where onboarding recommends GitHub MCP **with a broad-scope PAT and** another private-data source in the same session. Recommendation: keep warn-only globally, but for the GitHub-MCP-with-broad-PAT case the warning must name the *token-scope* remedy, not just describe the trifecta. Not a hard block — a sharper warning.

**(B) "Tier-2 support check is advisory in v1" — CHALLENGE for load-bearing claims. Confidence: medium-high.**
The spec's own §1 says onboarding output "becomes recall and pre-flight context for the orchestrator." A hallucinated architecture claim that passes Tier-1 (valid path + in-range) but fails support is exactly the failure the spec's own live probe caught (2 of 23 claims: range-valid but support sat outside the cited span). If that class of error is advisory-only, V-memory amplifies a *confidently-cited-but-wrong* claim as authoritative — the precise distrust tax practitioners already report on `/init` output ([obviousworks](https://www.obviousworks.ch/en/designing-claude-md-right-the-2026-architecture-that-finally-makes-claude-code-work/)). Domain ruling: Tier-2 advisory is fine for the *sampled 20-30%*, but for the **100%-load-bearing set (security, fail-closed, concurrency)** an unsupported result should **block that individual claim** (regenerate-or-drop), not merely surface it. Blocking one claim ≠ blocking the release; this preserves "a flaky judge doesn't hard-block a release" while giving Tier-2 teeth exactly where a wrong claim is dangerous. The flakiness concern is real, so: two-judge agreement or one regeneration retry before drop.

**(C) "cited-file-hash drift is THE staleness signal" — INSUFFICIENT alone. Confidence: high.**
Hash-drift answers "did a file the doc cited change?" It cannot answer "is the doc wrong even though its cited files are untouched?" Two concrete misses: (1) a doc that was wrong on generation day — hashes never drift, staleness never fires; (2) architecture migrated into a *new file the doc never cited* (e.g., auth moved from `auth.py` to a new `auth/oauth.py` the doc predates) — the old cited file may be unchanged or deleted, but the doc's *picture* is now wrong. Add a cheap heuristic: when refresh runs, for each architecture doc, glob the path-space its cited files occupy and flag if **new files appear in that space that no doc cites**. Still deterministic, no AST. This is the difference between "the doc's sources moved" and "the doc no longer describes the system."

**(D) "AGENTS.md-primary + thin CLAUDE.md bridge as the universal default" — RIGHT default, two backfire cases. Confidence: medium.**
The default is correct for cross-tool repos. It backfires when:
- **A managed/enterprise CLAUDE.md already governs.** If the org distributes a managed CLAUDE.md, the *project-layer* CLAUDE.md is additive and the AGENTS.md indirection adds a hop that some non-Claude tools may not follow — but the managed content can't move to AGENTS.md anyway (it's machine-policy, not repo-tracked). Here "AGENTS.md primary" is fine but onboarding must not imply it captures the org rules.
- **A Claude-only shop with no other agents.** The thin-bridge indirection is pure overhead — `@AGENTS.md` loads the same tokens, and the extra file is one more thing to drift. The spec's invariant #5 already concedes the bridge is "for one source of truth, not context savings"; in a verified single-tool repo, recommend *CLAUDE.md-primary* and skip AGENTS.md, or make AGENTS.md-primary a confirmable default rather than an unconditional one. Detection signal: presence of `.cursor*`/`.windsurf*`/`.github/copilot-instructions.md`/`GEMINI.md` ⇒ AGENTS.md-primary clearly wins; their total absence ⇒ offer CLAUDE.md-primary.

**(E) "Responsible doctor: bold diagnosis, apply-on-confirm" — SAFE, given one guard. Confidence: high.**
Diagnose-but-confirm is safe on arbitrary repos *because nothing writes without the gate* (invariant #1). The one edge case that breaks "safe": **restructuring recommendations that move content OUT of a managed or foreign-tool file.** Foreign-tool files are already read-only by invariant #2 — good. The residual risk is a *bold* recommendation that says "your CLAUDE.md is bloated, extract these 80 lines to AGENTS.md" when those 80 lines include an `@import` whose transitive content the diff view doesn't expand — the human approves a diff that looks small but changes what loads. Guard: the diff preview MUST expand `@import` targets (up to the 4-hop limit) so "what actually loads after this change" is visible, not just the literal file delta.

## 9. Open Questions for the Human
1. **Tier-2 teeth (decision B):** accept per-claim blocking on the 100%-load-bearing set, or keep fully advisory in v1? (Domain rec: block-the-claim with 2-judge/retry.)
2. **GitHub-MCP carve-out (decision A):** is the recommender allowed to suggest GitHub MCP at all in v1, given read-only doesn't fix the PAT-scope trifecta? Or defer GitHub MCP to the fast-follow with the token-scoping warning built in?
3. **AGENTS.md-primary unconditional vs confirmable (decision D):** does the maintainer want AGENTS.md-primary even in a verified Claude-only repo, on bet-on-the-future grounds? Product call, not a domain fact.
4. **DESIGN.md on alpha CLI as a *blocking* gate:** acceptable to block writes on an alpha-versioned third-party linter, or downgrade DESIGN.md lint to advisory until `@google/design.md` hits beta?
5. **Multi-theme token capture:** for v1, is "flag dark-mode/CSS-var theming as partial capture" acceptable, or is full per-theme extraction in scope?

## 10. Knowledge Base Updates
- Created `_knowledge-base/agent-instruction-files.md` — AGENTS.md governance status, Claude Code memory layering (verified), managed-layer immutability, /init native bridging overlap, MCP lethal-trifecta incident dossier (Supabase + GitHub, primary-sourced), read-only-vs-PAT-scope nuance, dated practitioner pain.
- Created `_knowledge-base/design-md-tokens.md` — `@google/design.md` alpha status + 9 lint rules + one-directional export (no reverse extraction), WCAG automated-contrast blind spots, Tailwind v3/v4 + arbitrary-value extraction reliability.

---

### Confidence flags
- **High:** managed-layer immutability, DESIGN.md no-reverse-extraction, both MCP incidents real, WCAG linter blind spots, /init native bridging, 200-line-is-a-target.
- **Medium-high:** Tier-2-needs-teeth (reasoned from spec's own probe, not an external measurement).
- **Medium:** AGENTS.md-primary backfire cases (informed judgment; no hard data on single-tool-repo overhead cost).
- **Isolated report (verify before treating as law):** symlink-confusion is HN anecdote (1 thread, 2025-11, [45788866](https://news.ycombinator.com/item?id=45788866)) corroborated by a second HN comment ([45791391](https://news.ycombinator.com/item?id=45791391)) — moderate, not ≥10-thread consensus. The spec already avoids symlinks, so this only confirms the existing choice.
