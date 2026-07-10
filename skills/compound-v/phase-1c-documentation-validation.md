# Phase 1C — Library & Documentation Validation

**When this fires:** Brainstorming has produced a spec. Runs **in parallel with Phase 1A (archaeology) and Phase 1B (domain-expert)** before invoking `writing-plans`.

**Goal:** Validate every library, framework, SDK, API, and version the spec mentions (or implies) against **current documentation**. Catch stale dependencies, deprecated APIs, version drift, and abandoned libraries BEFORE the plan locks them in.

(Phase 1A = existing code; Phase 1B = domain/regulatory; Phase 1C = library currency. All three are independent and run in one parallel dispatch.)

## Why a Separate Phase

LLM training data is months-to-years stale. An LLM will confidently suggest:
- A library that hasn't been updated in 4 years
- A method signature that changed two majors ago
- A `npm install <pkg>@latest` where the latest is `1.x` but the spec needs `2.x`
- A "standard" approach that was replaced by a new official solution last year

Archaeology can't catch this — it reads YOUR code, not the library's. The domain advisor knows the *field*, not the *SDK*. Phase 1C is the only layer dedicated to library/version currency.

## The Trigger Check

Run Phase 1C if ANY of these apply (almost always true):

- Spec names a library, framework, SDK, language version, or runtime
- Spec implies a category that requires choosing one (e.g. "ORM", "HTTP client", "queue", "auth library")
- Spec includes example code or pseudo-code with imports
- Spec references an external API (the API has SDKs with versions)

**Skip only if:** the spec is pure prose/UX copy with zero technical surface. Almost never.

## Prerequisite: MCP Context7

Phase 1C is most useful when [Context7 MCP](https://github.com/upstash/context7) is installed (`mcp__plugin_context7_context7__*` tools). Context7 fetches current, authoritative library documentation directly — bypassing training data staleness.

**Detection:** if Context7 tools are unavailable, Phase 1C degrades to WebSearch-only. Still useful, but slower and less authoritative. Note the degradation in the audit output.

## How To Invoke

Dispatch a fresh subagent using the **`doc-validator-prompt.md`** template (in this skill directory). Key dispatch rules:

1. **Model: `opus`** — the subagent must reason about whether to flag, not just retrieve. Opus.
2. **One Task call**, dispatched in the **same message** as Phase 1A's archaeology and Phase 1B's domain-expert Task calls (all three pre-flights in one parallel dispatch).
3. **Full spec text** in the prompt.
4. **Pointer to** any package.json / requirements.txt / Cargo.toml / go.mod / Gemfile in the repo so the subagent can cross-check declared vs current versions.

The subagent will:

1. **Check `docs/superpowers/recon/` for a Trigger 0 recon doc matching this topic.** If present, reuse its library/tooling findings as *leads to verify* — recon is unverified reconnaissance, so 1C still validates every claim it makes against live docs (Context7 or WebSearch), same as any spec claim. It tells you where to look first; it never substitutes for validation.
2. **Extract every library/version mention** from the spec, including implied ones ("we'll use an ORM" → flag for choice validation).
3. **For each library, query Context7** (or fall back to WebSearch + package registry) to get:
   - Current stable version
   - Last release date
   - Deprecation status
   - Known migration notes from major to major
   - Active maintenance signal (commits in last 12 months, open issues, response cadence)
4. **Cross-check repo's declared versions** (if package manifest exists): are we pinned to something old?
5. **Validate proposed APIs** against current docs via Context7's `query-docs`. If the spec or its example code uses a method, confirm the signature matches today's docs.
6. **Flag staleness explicitly:**
   - 🔴 **CRITICAL**: library deprecated, archived, or abandoned (no commits 24+ months)
   - 🟠 **HIGH**: library not updated in 12-24 months — may still work, verify alternatives
   - 🟡 **MEDIUM**: major version behind current — migration may be needed
   - 🟢 **OK**: current, actively maintained
7. **Recommend alternatives** for 🔴 and 🟠 cases. Cite usage stats (npm downloads, GitHub stars trend, what big projects use today).
8. **Write the audit** to `docs/superpowers/library-audit/YYYY-MM-DD-<topic>.md`.

## Output Template

The audit at `docs/superpowers/library-audit/YYYY-MM-DD-<topic>.md`:

```markdown
# <Feature> Library & Documentation Audit

## 1. Tools Available
- Context7 MCP: ✅ available / ❌ unavailable (degraded to WebSearch)
- Package manifest: <path or "none">

## 2. Libraries Mentioned (or Implied)

| Library / SDK | Spec context | Current ver | Repo pinned | Last release | Maintenance | Status |
|---|---|---|---|---|---|---|
| stripe-node | "Use Stripe SDK" | 17.4.1 | 11.0.0 | 2026-03-12 | 🟢 active | 🟡 6 majors behind — migrate to v17 |
| oauth2orize | Implied by OAuth server impl | 1.12.0 | not in repo | 2022-04-02 | 🔴 abandoned | 🔴 No commits 4 years. Use `@node-oauth/oauth2-server` instead. |
| jsonwebtoken | "Use JWT" | 9.0.2 | 9.0.0 | 2024-11-15 | 🟢 active | 🟢 OK |

## 3. API Signatures Verified

For each method the spec or its examples call, did the current docs confirm the signature?

| Symbol used in spec | Confirmed via | Match? | Notes |
|---|---|---|---|
| `stripe.paymentIntents.create({automatic_payment_methods})` | Context7 stripe-node v17 | ✅ | Confirmed in v17 docs; added in v8, stable |
| `oauth2orize.grant.code()` | Context7 oauth2orize | ⚠️ | Signature unchanged but library abandoned |
| `jwt.sign(payload, secret, {algorithm})` | Context7 jsonwebtoken v9 | ✅ | Unchanged from v8 |

## 4. Critical Findings 🔴

<one per blocker>
- **oauth2orize is abandoned (no commits since 2022-04).** GitHub issues open and unresponded. CVE-2024-XXXX un-patched. RECOMMEND: replace with `@node-oauth/oauth2-server` (active, last release 2026-04). Migration is non-trivial; document scope in spec.

## 5. High-Priority Findings 🟠

<libraries 12-24 months stale>
- (none)

## 6. Medium Findings 🟡

<major versions behind>
- **stripe-node pinned to v11, current is v17.** v12 → v17 introduced `automatic_payment_methods` as default (relevant to EU SCA from Phase 1B audit). Recommend upgrading as part of this feature.

## 7. Design Constraints for the Plan

<this section feeds writing-plans as non-negotiables>
- MUST replace oauth2orize with @node-oauth/oauth2-server (oauth2orize abandoned)
- MUST upgrade stripe-node to v17 (needed for automatic_payment_methods API)
- MUST verify stripe-node breaking changes between v11 and v17 (separate sub-task)
- MUST NOT add new dependencies without checking Context7 currency

## 8. Open Questions for the Human

- Stripe migration v11 → v17 is a 6-major jump. Do we scope this within the EU feature or split into a prerequisite cleanup task?
- oauth2orize replacement breaks our existing OAuth callback handlers. Do we replace surgically (one provider at a time) or migrate the whole gateway in one shot?

## 9. Knowledge Base Updates

<persistent KB at docs/superpowers/library-audit/_knowledge-base/>
- Added: `payments-stripe.md` — Stripe SDK version-jump notes (v11 → v17 major changes)
- Added: `oauth-libraries.md` — Active vs abandoned OAuth server libraries in Node ecosystem (2026 survey)
```

## Persistence: Library Knowledge Base

Like Phase 1B, Phase 1C persists findings at `docs/superpowers/library-audit/_knowledge-base/<topic>.md`. Each pass appends. Future features that touch the same library start with the KB and only re-validate what's stale.

Rules:
- One file per library OR per ecosystem topic (e.g. `nodejs-oauth.md`, `python-celery-alternatives.md`)
- Date-stamp every entry. The "last release was 2022-04" claim only stays valid until you next check.
- Strike-through (not delete) outdated claims when re-validating

## Anti-Patterns

- **Trusting the LLM's "latest version" claim** without Context7 confirmation. The training cutoff is older than you think.
- **Validating only libraries the spec names explicitly.** "We'll use an ORM" implies a choice — flag it for validation BEFORE writing-plans locks in Sequelize when Prisma is what 2026 projects use.
- **Skipping Phase 1C because "the libraries are stable."** Stable libraries also get abandoned. Verify the abandonment signal, don't assume.
- **Flagging staleness without a recommended alternative.** "X is abandoned" is half a finding. "X is abandoned; Y is the 2026 successor with N downloads/month and active commits" is a finding.

## Handoff

When the audit is complete, the controller announces:

> "Library/doc audit complete. Audit at `docs/superpowers/library-audit/<file>.md`. N critical / M high / K medium findings."

If section 4 (Critical) is non-empty, **surface to the human BEFORE invoking writing-plans.** A plan that builds on an abandoned library is a plan with a known-bad foundation.

Once Phase 1A and 1B ALSO complete, invoke `writing-plans` with all three audits attached. Their "Design Constraints" sections compose into the plan's non-negotiable requirements list.
