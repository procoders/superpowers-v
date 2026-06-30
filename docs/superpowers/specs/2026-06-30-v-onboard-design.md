# /v:onboard — project onboarding for Compound V (design, v1)

**Status:** approved for build (2026-06-30). Converged after a 4-angle 2025–2026
best-practices research sweep and a live citation-feasibility probe on a real repo.

## 1. What it is
A new command that studies an existing repository and builds a **trusted project
knowledge base** plus **cross-tool agent instructions**. It is the doc-producing front
half of V-memory: what onboarding writes becomes recall (`/v:remember`) and pre-flight
context for the orchestrator (`code-archaeologist`, `domain-expert`). It **extends**
`docs/superpowers/**`; it never rewrites V-memory's recall engine or the routing layer.

The differentiator over peer rule-generators (Cursor rules, Cline Memory Bank, Copilot
instructions) is the loop: onboarding output feeds the orchestrator's planning and the
recall layer, not just a static instruction file.

## 2. Why a separate command, not part of `/v:init`
`/v:init` is fast and idempotent (backend detection → `.claude/compound-v.json`).
Onboarding is heavyweight, repo-scanning, doc-writing, and human-gated — run once, then
refresh. Folding it into `/v:init` would change that command's character. They stay
composable: `/v:init` **suggests** running `/v:onboard` at the end; it never chains into it.

## 3. Pipeline
```
1. DETECT     existing instruction files, stack, UI presence, DB/MCP signals,
              style configs (eslint/prettier/ruff/editorconfig/tsconfig/lockfiles), git remote
2. PACK       deterministic repo pack (file tree, configs, entry points, token counts,
              .gitignore-aware) + SECRET SCAN (blocking — never emit credentials)
3. EXTRACT    read-then-cite generation: every architecture/business-logic claim carries a
              file:line citation; claim only what was read
4. VERIFY     Tier 1 path+range gate (all claims, blocking) · Tier 2 LLM support check
              (sample + 100% of load-bearing claims, advisory in v1) ·
              DESIGN.md → `npx @google/design.md lint` (blocking) · secret scan (blocking)
5. DIAGNOSE   "responsible doctor": flag bloated CLAUDE.md, cross-layer contradictions,
              missing AGENTS.md bridge, foreign-tool rules to reconcile, aspirational rules
              better expressed as hooks — including restructuring recommendations
6. HUMAN GATE present a reviewable diff + per-section confidence/staleness + the diagnosis.
              Nothing is written before approval. (Successor to the old 02-step Yes/No check.)
7. WRITE      only approved artifacts; detect-and-bridge for existing files; narrow write surface
8. INDEX      write .onboard-manifest.json (cited files + hashes); auto-run /v:memory-refresh
```

## 4. Artifacts and taxonomy
| File | Location | When | Verification |
|---|---|---|---|
| `architecture.md`, `business-logic.md`, `tech-context.md` | `docs/superpowers/architecture/` | always | citation hybrid (§7) |
| `CONVENTIONS.md` | repo root | code present | derived from real config evidence |
| `DESIGN.md` (Google format) | repo root | UI repo only | `@google/design.md lint` |
| `AGENTS.md` (primary) + thin `CLAUDE.md` (`@AGENTS.md`) | repo root | always | detect-and-bridge (§6) |
| `.onboard-manifest.json` (cited files + content hashes) | `docs/superpowers/architecture/` | always | — |

The three `architecture/` files follow Cline's Memory Bank model (systemPatterns,
productContext, techContext), trimmed to the durable set. The fast-changing
`progress.md`/`activeContext.md` are **out of v1** — they are active-development artifacts,
not onboarding output.

V-memory's index is **extended** to cover root `CONVENTIONS.md` / `DESIGN.md` / `AGENTS.md`
(all git-tracked) in addition to `docs/superpowers/**`.

## 5. Hard requirements (invariants)
1. **Nothing is written without an explicit human approval at the gate (§6).** No auto-apply
   of any file, ever — diff + confirm is mandatory.
2. **Narrow write surface.** Onboarding writes only: `docs/superpowers/architecture/*`, root
   `CONVENTIONS.md`, root `DESIGN.md` (conditional), `AGENTS.md`, `CLAUDE.md` (thin bridge),
   path-scoped `.claude/rules/*.md` (conditional, §8), `.onboard-manifest.json`, and —
   fast-follow — `.mcp.json`. Each is still subject to the §6 human gate. Foreign-tool files
   (`.cursor/rules`, `.cursorrules`, `.windsurfrules`, `.github/copilot-instructions.md`) are
   **read-only**: incorporated and reconciled, never modified.
3. **Secret scan is blocking** at PACK and again before WRITE. No credential
   (`sk-`/`ghp_`/`AKIA`/`-----BEGIN … KEY-----`) reaches any generated, committed file.
4. **Architecture prose is never inlined into CLAUDE.md/AGENTS.md.** Those files point to
   `docs/superpowers/architecture/*`. CLAUDE.md stays under Anthropic's 200-line ceiling.
5. **`@import` is not a token optimization.** Imported files load in full at launch; only
   path-scoped `.claude/rules/` and skills defer. The bridge uses `@AGENTS.md` for one source
   of truth, not for context savings.
6. **Every architectural claim is mechanically verified (§7).** A claim that fails the Tier-1
   path+range gate is regenerated or dropped, never written.
7. **Generated output is git-committed, not cached.** Recall and the scope gate both require
   git-tracked files; ignoring under `docs/superpowers/` would blind
   `git ls-files --others --exclude-standard`.
8. **Hooks never bootstrap or self-background for onboarding.** Refresh is user-invoked; the
   only hook-side surface is a read-only staleness line in the existing SessionStart banner.
9. **No fabricated metrics; `--selftest` coverage for the deterministic gates.**

## 6. Existing-file reconciliation — the "responsible doctor"
Detect first, then diagnose boldly, then apply only on confirmation.

- **Bold by default.** When the repo already has instruction files, onboarding names the
  problems plainly — bloated CLAUDE.md, contradictions across managed/user/project/local
  layers, a missing AGENTS.md bridge, foreign-tool rules that conflict, aspirational rules no
  hook enforces — and **recommends fixes, including restructuring**. The patient decides.
- **Bridge policy.** `AGENTS.md` is the portable primary (Linux Foundation AAIF standard,
  read by Codex/Cursor/Copilot/Gemini). `CLAUDE.md` is a thin file whose first line is
  `@AGENTS.md` plus an optional `## Claude Code` section.
  - `AGENTS.md` exists → it is the source of truth; augment via diff, ensure the CLAUDE.md
    bridge exists.
  - `CLAUDE.md` exists, no `AGENTS.md` → recommend extracting the portable parts into a new
    `AGENTS.md` + bridge.
  - Neither exists → generate `AGENTS.md` + thin `CLAUDE.md` bridge.
- **Apply only through a reviewable diff + confirmation.** Mirror Claude `/init`'s
  explore → ask → propose → write flow. Never silently overwrite.

## 7. Citation verification — hybrid, two-tier
The dominant failure mode for any "scan → describe the system" feature is hallucinated
architecture, which V-memory would then amplify as authoritative. Verification is mechanical,
not a "please cite" prompt.

- **Tier 1 — mandatory, blocking, on 100% of claims.** Lightweight, language-agnostic gate:
  the cited path resolves inside the repo and `1 ≤ startLine ≤ endLine ≤ lineCount`. Catches
  hallucinated paths and phantom ranges at zero AST cost.
- **Tier 2 — sampled, advisory in v1.** An LLM "do the cited lines actually support this
  claim?" check on a sample (~20–30%) plus **100% of load-bearing claims** (security,
  fail-closed, concurrency). Unsupported claims are surfaced for regeneration; a flaky judge
  does not hard-block a release in v1.
- **No full AST/tree-sitter in v1.** It is per-language and heavy; the probe shows it is not
  the binding constraint.
- **Generation defaults to read-then-cite** (read files, claim only what was read).

**Feasibility proof (live probe, 2026-06-30, on this repo).** The read-then-cite strategy
produced 23/23 claims at 100% with-citation, 100% path-valid, 100% range-valid, 100%
support under an adversarial verifier. The naive free-write strategy failed to produce valid
structured output across 5 retries — a weak robustness signal, not a measured A/B. The
verifier flagged the real residual gap: two claims cited a range whose load-bearing line sat
just outside the cited span (adjacent cited lines carried the support), proving
range-validity ≠ support and justifying Tier 2. Caveat: n=23 on one cooperative repo —
re-measure on the dogfood run (§11) before treating the ceiling as a law.

## 8. CONVENTIONS.md and DESIGN.md
- **`CONVENTIONS.md`** (Aider-style, repo root). Small, read-only, prompt-cacheable. Derived
  from deterministic evidence — eslint/prettier/ruff/editorconfig/lockfile choices and
  observed naming — not from the model's prior. Phrase concretely and verifiably ("use
  2-space indentation"), and emit only the delta from competent-developer defaults. Broad
  conventions go into the thin AGENTS.md/CLAUDE.md; file-pattern constraints go into
  path-scoped `.claude/rules/*.md`, not into generated skills.
- **`DESIGN.md`** (Google Labs format, repo root, UI repos only). YAML design tokens
  (colors, typography, spacing, rounded, components) + prose rationale. Generated only when
  a UI is detected (React/Vue/Svelte, Tailwind, CSS variables, design tokens), extracted from
  real sources (`tailwind.config`, CSS variables, token files), and **verified by the
  official linter** `npx @google/design.md lint` (structure, token references, WCAG contrast)
  as a blocking gate before write. On a backend/CLI/library repo it is not generated.

## 9. Refresh and staleness
Two layers, two mechanisms, no conflation.

- **`/v:onboard --refresh`** owns the **docs**: re-extract only files whose content hash
  changed since generation; flag any doc whose **cited files** changed (the staleness signal);
  run the same human gate. On completion it **auto-runs `/v:memory-refresh`** so the index
  follows.
- **`/v:memory-refresh`** (existing) owns the **index** (FTS5/embeddings by file hash).
  Unchanged.
- **Staleness signal** is deterministic: `.onboard-manifest.json` stores each doc's cited
  files and their content hashes at generation time; on refresh, drift → the doc is marked
  STALE and queued for a human-reviewed update.
- **Manual only in v1.** No hook bootstraps or self-backgrounds. The single hook-side surface
  is a read-only line in the SessionStart banner: "N architecture docs are stale vs HEAD →
  run /v:onboard --refresh." It writes nothing.

## 10. MCP recommender (fast-follow, not a v1 blocker)
Signal → server. A detector maps real evidence to a maintained vendor server and presents a
confirmable shortlist (~3–5) with the file evidence that triggered each: `github.com` origin
→ GitHub MCP; Postgres DSN / `prisma`+`pg` → Postgres MCP (read-only); `@supabase/*` →
Supabase MCP (`--read-only --project-ref`, dev/branch DB); `playwright.config` → Playwright
MCP; fast-moving libs → Context7; `@sentry/*` → Sentry.

- **Writes `.mcp.json` through diff + confirmation**, with read-only / least-privilege flags
  pre-filled. Never silent. Resolves to the maintained vendor server, not archived
  `modelcontextprotocol/servers` reference entries.
- **Lethal-trifecta is warn-only, loud, and specific.** When a recommendation would co-enable
  private data + untrusted content + external write in one session, onboarding emits a named
  warning (the 2025 Supabase service-role and GitHub toxic-agent exfiltration pattern) and
  **the user decides**. No hard refusal.

## 11. Skills stance
No bulk skill generation — overlapping descriptions degrade auto-triggering across the user's
entire skill set and burn the shared skill-listing budget. v1 only **recommends which
existing superpowers-v skills fit this repo**. Scaffolding a single project-specific
review/quality skill (only when the repo has bespoke multi-step conventions, with a specific
non-overlapping description, through the human gate) is **optional / fast-follow**.

## 12. Quality bar and acceptance
Per the project's dogfooding + cross-model + iterate-to-convergence style:

- **E2E on superpowers-v itself** — a multi-config repo (`AGENTS.md`, `GEMINI.md`, `docs/`).
  Exercises detect-and-bridge, the conditional **skip** of `DESIGN.md` (no UI — verifies the
  negative path), and citation verification on real Python/bash/Markdown.
- **E2E on a UI repo** — exercises the `DESIGN.md` extraction + linter path.
- **Cross-model (Codex) review** of a sample of generated architecture prose before the
  pipeline is declared trustworthy. The backend that writes prose and the backend that
  verifies it differ.
- **`--selftest`** on the deterministic gates: Tier-1 path+range, secret scan, staleness-hash
  drift, conditional `DESIGN.md` detection.

## 13. Command surface
| Command | Effect |
|---|---|
| `/v:onboard` | full pipeline (§3) → human gate → write → index |
| `/v:onboard --refresh` | re-extract changed-hash files, flag stale docs, gate, write, re-index |

`/v:init` gains a closing suggestion to run `/v:onboard`. No other command changes in v1.

## 14. Out of scope (v1, deliberate)
Bulk skill generation · full AST/tree-sitter citation verification · any auto-apply ·
hooks that bootstrap or self-background · `progress.md`/`activeContext.md` · the MCP
recommender as a v1 blocker (it ships as a fast-follow).

## 15. Open items
- Exact detector heuristics for "UI repo" (which signals, and the precedence when mixed).
- Tier-2 sampling rate and the precise "load-bearing claim" classifier.
- Whether the optional single review skill lands in v1 or the fast-follow.
- Target version: proposed **v2.2.0** (next minor) — confirm against the planned numbering.

## 16. References
- Claude Code memory / CLAUDE.md (length ceiling, `@import`, layering): https://code.claude.com/docs/en/memory
- Claude Code best practices (CLAUDE.md anti-patterns, hooks-are-deterministic): https://code.claude.com/docs/en/best-practices
- AGENTS.md standard (Linux Foundation AAIF): https://agents.md
- Cline Memory Bank (six-file taxonomy, update ritual): https://docs.cline.bot/prompting/cline-memory-bank
- DESIGN.md format + linter: https://github.com/google-labs-code/design.md
- Prior art (this maintainer, 2024 Cursor→Claude prompts): https://github.com/procoders/make-cursor-friendly-prompts
