# Phase 1B — Domain-Expert Advisor

**When this fires:** Brainstorming has produced a spec. Runs **in parallel with Phase 1A (archaeology)** before invoking `writing-plans`.

**Goal:** Force an honest look at the **product/domain** reality the new design has to satisfy. Phase 1A catches *technical* surprises (what the code already does). Phase 1B catches *domain* surprises (what the field already knows that the brainstorm probably missed).

> Think of Phase 1B as Vought's R&D consultant: the one who already knows that Soldier Boy can't fly, that Compound V doesn't work on adults the same way, and that the supe market has regulations you didn't read.

## Why Both Audits, Not Just Archaeology

Archaeology answers: *"What does the existing code do?"*

The domain advisor answers: *"What does the *field* require that the brainstorm took for granted?"*

Examples of failures only the domain advisor catches:

| Domain | Brainstorm assumes... | Domain reality |
|---|---|---|
| OAuth integrations | "All OAuth providers follow the spec" | Notion uses Basic auth + JSON body; Slack rotates tokens; GitHub fine-grained tokens have a different scopes model |
| Astrology calculations | "House systems are interchangeable" | Placidus fails at extreme latitudes; whole-sign vs Placidus changes interpretation; Vedic uses sidereal zodiac, not tropical |
| Payments | "Stripe handles everything" | EU SCA requires 3DS challenge flow; some card networks require explicit consent for recurring; PSD2 strong-customer auth has specific UI requirements |
| Healthcare data | "We'll store user health metrics" | HIPAA / GDPR Article 9 classify health as special-category data; encryption-at-rest required; audit logs required |
| Maps / geocoding | "Lat/long is lat/long" | Some countries (China) use shifted coordinate systems (GCJ-02); precision rules differ for export-controlled regions |
| Localization | "Translate the strings" | Right-to-left scripts flip the entire UI; CJK has no word boundaries; plural rules differ (Russian has 4, Arabic has 6) |
| AI/LLM features | "Just call the model" | Cost per token varies 50×; context windows differ; some providers have hard content-policy filters that block legitimate use |
| Crypto | "We'll use AES" | NIST SP 800-38 says don't use ECB; GCM nonce reuse is catastrophic; key rotation policy is part of the design, not an afterthought |

Code archaeology can't catch any of these — they aren't in the existing code. The domain advisor is the only layer that knows what the spec *should have said*.

## Skip Rule

Skip Phase 1B ONLY if the spec is entirely about **internal plumbing** with no user-facing or domain-specific surface:

- Pure build system changes (webpack config, tsconfig tweaks)
- Lint rule additions
- Internal refactors that don't change behavior
- Dev-tooling improvements

If users will see or feel the result, the domain applies. **When in doubt, run it.** A 10-minute advisor pass beats a launch blocker.

## How To Invoke

Dispatch a fresh subagent using the **`domain-expert-prompt.md`** template in this skill directory. Key dispatch rules:

1. **Model: `opus`** — domain reasoning is exactly where Opus earns its cost
2. **One Task call**, dispatched in the same message as Phase 1A's archaeology Task call (so both pre-flights run in parallel)
3. **Full spec text** in the prompt (don't make the subagent re-read brainstorming output)
4. **Path to existing knowledge base** if any: `docs/superpowers/expert/_knowledge-base/`

The subagent will:

1. **Identify the domain(s).** From the spec text, infer: payments / auth / health / mapping / astrology / NLP / etc. List 1-3 domains.
2. **Check the knowledge base** at `docs/superpowers/expert/_knowledge-base/<domain>.md`. If it exists and is recent (< 6 months) and covers the spec's scope, treat it as authoritative; only run web searches for genuine gaps.
3. **Check `docs/superpowers/recon/` for a Trigger 0 recon doc matching this topic.** If present, read it first and *deepen* its queries rather than repeating them — recon already covered the surface pass, so spend the web-search budget on what it didn't reach. Treat its SUGGESTED DIRECTIONS as non-exhaustive evidence, not a shortlist.
4. **Run parallel web searches** if knowledge is thin: 3–6 WebSearch calls in a single message covering: official spec / docs, common pitfalls, regulatory constraints, recent breaking changes, comparison vs alternatives.
5. **Produce the audit** at `docs/superpowers/expert/YYYY-MM-DD-<topic>.md` (template below).
6. **Update the knowledge base** at `docs/superpowers/expert/_knowledge-base/<domain>.md` with any new general-purpose findings (not feature-specific details). Append; never overwrite.

## Output Template

The audit at `docs/superpowers/expert/YYYY-MM-DD-<topic>.md`:

```markdown
# <Feature> Domain Audit

## 1. Domain(s) Identified
- Primary: <e.g., OAuth provider integration>
- Secondary: <e.g., token storage and rotation>

## 2. Sources Consulted
- Prior KB: `_knowledge-base/oauth.md` (last updated 2026-04-01, covers RFC 6749 baseline) — REUSED
- Web search: <query 1> — <key finding 1>
- Web search: <query 2> — <key finding 2>
- Official spec: <link + version + relevant section>

## 3. Domain Constraints the Brainstorm Probably Missed
<list every domain rule that the spec does NOT mention but MUST satisfy>
- MUST: Notion uses Basic auth (base64 of client_id:client_secret) in the token-exchange Authorization header, NOT the body. Brainstorm said "POST credentials" — ambiguous.
- MUST: Token responses come back with `bot_id`, `workspace_id`, `workspace_name` — store all three, the workspace_id is the actual integration identity
- MUST NOT: Don't reuse the Slack token-refresh handler — Notion tokens don't expire (currently)
- SHOULD: Notion's rate-limit header is `Retry-After` in seconds, distinct from Slack's `X-Rate-Limit-Reset` epoch

## 4. Common Traps in This Domain
<things the field has learned the hard way>
- The redirect URI must match EXACTLY, including trailing slash. Production support tickets are 80% this.
- Don't store `code` after exchange — it's single-use and an attacker who reads logs gets nothing useful
- OAuth callback CSRF: always use `state` parameter, never trust referer

## 5. Regulatory / Compliance Notes
- GDPR: workspace_name + workspace_id are pseudonymous identifiers — purge on user account deletion
- SOC 2: token storage requires encryption-at-rest if you're in scope

## 6. Recent Breaking Changes (last 12 months)
<from web search>
- 2025-09: Notion deprecated the v1 OAuth endpoint; v2 only. Confirm spec targets v2.

## 7. Design Constraints for the Plan
<this section feeds writing-plans as non-negotiables>
- MUST use Notion v2 OAuth endpoint
- MUST use Basic auth header (not body) for token exchange
- MUST store workspace_id alongside the token; this is the integration identity
- MUST NOT reuse Slack token-refresh handler
- MUST handle `Retry-After` seconds, not epoch
- MUST validate exact redirect URI match including trailing slash
- MUST persist `state` parameter and validate on callback

## 8. Open Questions for the Human
<things the advisor genuinely cannot resolve without product-side input>
- Should we support Notion workspace re-installs (overwrite existing record) or treat as a new integration?
- Token revocation: do we revoke on user-side logout, or only on admin removal?

## 9. Knowledge Base Updates
<what was appended to _knowledge-base/oauth.md (link to commit/section)>
- Added: "OAuth provider quirks matrix" with Notion, Slack, Linear, GitHub rows
```

## Knowledge Base Persistence

The advisor's most valuable output is the **persistent KB** at `docs/superpowers/expert/_knowledge-base/<domain>.md`. It grows over time.

Rules for the KB:

- **One file per domain**, named by the canonical domain noun: `oauth.md`, `payments.md`, `astrology.md`, `localization.md`, etc.
- **Append, don't overwrite.** New findings go at the bottom with a date stamp.
- **Promote feature-specific findings to general findings.** If you found "Notion uses Basic auth" while building Notion OAuth, the KB entry is "OAuth provider quirks matrix → Notion: Basic auth in header" — generalized, indexed for the next provider.
- **Periodically consolidate.** If the KB has 5 entries about the same topic, refactor them into a single canonical section with a "see history" link to git.
- **Cite sources.** Every claim needs a link, a spec section, or a "verified manually on <date>." No "the docs say" without a link.

The KB is what makes Phase 1B *cheaper over time*. The first OAuth feature in a codebase pays the full advisor cost. The fifth pays maybe 20% — most of the value is already on disk.

## Anti-Patterns

- **Skipping 1B "because I know the domain."** Write it down anyway. Future-you doesn't have your memory. Future agents definitely don't.
- **One huge KB file with everything.** Split by domain. `_knowledge-base/` is a directory, not a single file.
- **Web searches without parallelism.** 3 sequential searches = 3× wall-clock. One message, three concurrent WebSearch calls = same cost, 1× wall-clock.
- **Treating the KB as immutable scripture.** If a finding goes stale (API changed, regulation updated), strike it through and add the new version with date.
- **Letting the advisor write code.** This phase produces *findings*, not implementation. Feature constraints go into the plan; code goes into Phase 3.

## Handoff

When the audit is complete, the controller announces:

> "Domain audit complete. Audit at `docs/superpowers/expert/<file>.md`. N hard constraints identified, M open questions for the human."

If there are open questions in section 8, **surface them to the human BEFORE invoking writing-plans.** A plan built on unanswered domain questions is a plan built on guesses.

Once Phase 1A (archaeology) ALSO completes, invoke `writing-plans` with both audits attached.
