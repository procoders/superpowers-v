# Claude Code `/skill-doctor` — Knowledge Base

Maintained by Compound V Phase 1C validator. Append at the bottom.

---

## Updated 2026-09-11 — version-floor discrepancy, headless behavior, exclusions, Remote Control limitation

Validated for [`docs/superpowers/library-audit/2026-09-11-v3-6-wide-dispatch.md`](../2026-09-11-v3-6-wide-dispatch.md). Sources: `code.claude.com/docs/en/skills` (live fetch 2026-09-11) and `raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md` (live fetch 2026-09-11), checked against installed Claude Code 2.1.263.

**What it does (verbatim from `skills.md`):** *"Run `/skill-doctor` to see what each of your skills costs and how often it gets used, so you can decide which ones to turn off. In an interactive session, the report opens in the `/plugin` manager's Stats tab. In non-interactive mode with `-p`, Claude Code prints it as text."* It flags never-invoked skills, tells you where to turn them off, and separately lists plugins you haven't used recently.

**Version-floor discrepancy — flag before citing a number:**
- `skills.md` states: *"`/skill-doctor` requires Claude Code v2.1.252 or later and isn't available in sessions that skip feature-flag fetching."*
- The official `CHANGELOG.md` states, at **v2.1.261**: *"Added `/skill-doctor` to show which loaded skills go unused and what they cost in context, so you can prune them."*
- No changelog entry between 2.1.238 and 2.1.260 mentions `/skill-doctor`, `skill-doctor`, or "skill usage" in any form.
- **These two Anthropic-owned sources disagree on when the feature shipped.** Neither has been reconciled by this audit — flagging rather than picking a winner. Practical effect on any spec targeting Claude Code ≥ 2.1.263: none, since 2.1.263 clears both candidate floors. A spec that needs the *true* introduction version (e.g. for a compatibility matrix spanning older installs) should not cite "2.1.252" as changelog-confirmed; it isn't.

**Report exclusions (verbatim):** *"The report covers the skills in your session other than bundled skills and enterprise skills."*

**Remote Control limitation (verbatim):** *"If you run `/skill-doctor` over Remote Control from your phone or browser, Claude Code replies `Skill usage reports are not available on this connection.` instead. Run `/skill-doctor` in the terminal on the machine where the session is running."*

**Feature-flag dependency:** same gate as the advisor tool — a session that skips feature-flag fetching (e.g. `DISABLE_TELEMETRY`) never gets `/skill-doctor` either.

**Report column schema is NOT documented anywhere.** `skills.md`, `commands.md`, and `costs.md` all describe the report's *purpose* (cost + usage frequency, never-invoked flags, stale-plugin list) but none enumerates a column layout, order, or field names. Any spec citing specific columns (e.g. "skill · source · context · 7d tokens · uses · last used") is reporting a live-probe observation on a specific machine/version, not a documented contract — those columns can be renamed or reordered in a future release with zero changelog obligation, since they're not a named setting or flag. A parser built against `/skill-doctor` output should match on labeled fields, not fixed column position.

**`/commands` page:** does not mention `/skill-doctor` at all — it is documented only on the `skills.md` page, not cross-referenced from the commands reference.
