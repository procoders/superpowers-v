# Phase 1A — Pre-Flight Archaeology

**When this fires:** Brainstorming has produced a spec. Runs **in parallel with Phase 1B (domain-expert advisor)** before invoking `writing-plans`.

**Goal:** Force an honest look at the existing **code** the new design will sit next to. Without this, the plan inherits latent bugs and silently conflicts with sibling code.

(Phase 1B covers the *domain* reality — see [phase-1b-domain-expert.md](phase-1b-domain-expert.md). The two pre-flights are independent; dispatch them in a single message with two concurrent Task calls.)

## The Trigger Check

Run the `code-archaeology` skill if ANY of these apply to the spec:

- New code sits inside existing middleware (gateway, auth, credentials, session)
- New code reads variables set by sibling code paths (`userId`, `apiKeyRecord`, `server`, etc.)
- The feature branches by a dimension that already has branches (server type, auth type, mode flags)
- You catch yourself thinking "this is basically the same as the other path"
- External API involved (OAuth, Stripe, Supabase, LinkedIn, Notion, GitHub)
- Spec adds a "path like X but for Y" and X already exists

**Skip only if:** greenfield in a new directory, pure UI tweaks, copy changes, config edits.

If you're unsure → run it. The cost of running archaeology on a small feature is minutes. The cost of skipping it on a feature that needed it is hours of rework.

## How To Invoke

Use the `code-archaeology` skill if present in this environment, OR run its five-phase audit manually:

1. **Matrix enumeration** — every branching dimension × every combination × marked "new code handles?"
2. **Shared-state audit** — every variable the new code reads, documented per branch where it's set
3. **Sibling-code read** — the analogous existing path read IN FULL before writing the new one
4. **External API verification** — `context7` for every third-party API; paste the relevant spec
5. **Regression surface + DRY** — what existing code paths could break + grep for duplicates

Output goes to `docs/superpowers/archaeology/YYYY-MM-DD-<topic>.md`.

## What The Audit Produces

The audit's final section — **"Design constraints for the spec"** — is the deliverable that `writing-plans` consumes. Every bullet there becomes a non-negotiable requirement in the plan.

Example design constraints (from the gateway audit):

```
- MUST handle all 4 server-type cells, not just hosted-free
- MUST fall back to apiKeyRecord.user_id when userId is undefined
- MUST NOT duplicate credential-injection logic — extend the existing one
- MUST verify Notion's Basic auth contract via context7 before designing the OAuth flow
```

## Compound V Specific Additions

In addition to the standard code-archaeology output, Compound V requires the audit to declare:

### File Touch Map (for Phase 2)

After the regression scan, list **every file** the implementation will touch, with a one-line rationale:

```markdown
## File Touch Map (for partitioning)

- `src/middleware/auth.ts` — add new auth branch
- `src/middleware/auth.test.ts` — tests for the new branch
- `src/lib/credentials.ts` — extend existing credential-injection (DRY finding)
- `src/lib/credentials.test.ts` — tests
- `db/migrations/0042_add_oauth_state.sql` — SHARED RESOURCE (migration ordering matters)
- `src/types/auth.ts` — SHARED RESOURCE (other tasks may read these types)
```

Flag any file as `SHARED RESOURCE` if:
- It's a generated file (lockfiles, schema dumps, codegen outputs)
- It's a type declaration file other tasks will read
- It's a migration / config / route registry where order matters
- It's an index/barrel file that aggregates exports

Phase 2 uses this map to build the Partition Map and decide which files go in the serial pre-phase.

## Anti-Patterns (Compound V Specific)

- **Skipping archaeology to "save time."** You're trading 10 minutes of audit for hours of parallel-implementation rework when subagents stomp on hidden coupling.
- **Filling the File Touch Map from intuition** instead of grep. Grep for the feature name, the affected types, the sibling path. Write down what's actually there.
- **Marking shared resources as "probably fine."** If it might be shared, declare it shared. The serial pre-phase is cheap.

## Handoff to Phase 2

When the audit is complete, announce:

> "Archaeology complete. Audit at `docs/superpowers/archaeology/<file>.md`. File Touch Map identifies N candidate files, M flagged as SHARED."

Wait for Phase 1B (domain-expert) to complete in parallel. Then invoke `writing-plans` with BOTH audits attached as design-constraint sources.
