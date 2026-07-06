# Review Domains

Domains to interrogate during Phase 4. Stack-agnostic — the grep examples are illustrative; adapt the patterns to the diff's language.

**Order:**
1. **Domain 0 — Dead Code & Call-Graph Reality Check** (always first; cheap, catches the worst class of bug).
2. **Domain 1 — Intent Alignment** (always; sets the frame).
3. **Remaining domains** by relevance to what the diff touches. Skip irrelevant ones.

For each domain: (1) identify the lines/files under it; (2) run the [exploration checklist](exploration-checklist.md), writing the `Already checked:` line; (3) route — codebase answers → record finding; genuine judgment → `AskUserQuestion` (batched); author-intent unknown → Open Question.

**Anti-pattern reminder:** if 30 seconds of grep answers it, do the grep — don't surface the question.

---

## Domain 0: Dead Code & Call-Graph Reality Check (always first)

For every function/path the diff modifies or adds side-effects to, verify it has **live, non-test callers**.

The failure mode this catches: a PR adds an emission, fix, or guard to function `X` — but `X` has no non-test callers, while a different function `Y` is the production path. The change ships, looks correct, and does nothing.

**Questions:**
- For every modified function: any non-test caller in a production path?
- For every new emission (analytics event, log, side effect): is the surrounding function actually invoked at runtime?
- For every guard / early return added: does control flow actually reach it from a live entry point?
- If the diff says "X is the {checkout / refund / first-payment / …} path," is X actually invoked from a controller, route, cron, webhook, or other live entry?

**Explored evidence (adapt to language):**
```bash
# Live callers of a symbol, excluding tests
grep -rn 'processFirstPayment\b' src --include='*.ts' | grep -vi test

# Live entry points calling into changed code
grep -rn 'changedFunction\b' src/controllers src/routes src/cron src/webhooks 2>/dev/null

# Nothing comes back? The change may be on a dead path — search for the sibling that IS live:
grep -rn 'similarFunctionName\b' src | grep -vi test
```

**Promotion:** if the function is dead, that itself is a finding (severity Medium+, anchored on the dead function; recommended action: identify the real path and apply the change there).

---

## Domain 1: Intent Alignment (always; sets the frame)

What is this change *trying* to do, and does the diff actually do that?
- What does the title / body / linked issue / spec claim?
- What does the diff actually change? (Your read.)
- Where does claimed intent diverge from actual changes?
- Changes unexplained by the stated intent? Parts of the intent missing from the diff?

**Explored evidence:** title/body, commit messages, linked issue/spec (Phase-0 discovery), branch name.

**Output rule:** the agreed "What this PR does" briefing (Phase 1) is canonical. Any unresolved divergence becomes an Open Question.

---

## Domain 2: Bug Risk in the Diff

Line-by-line: what can break?
- Null / undefined / `None` paths not guarded
- Off-by-one, boundary conditions, empty / single-element collections
- Async ordering, races, double-fire, missed `await` / unhandled promise
- Error swallowing (`catch {}` with no rethrow, returning `null`/`nil` on failure)
- Side effects in the wrong order (write before validation, etc.)
- Money / currency math (cents vs units, fee calc, rounding)
- Auth / permission gaps (missing role check, wrong tenant filter)
- New code paths that bypass existing invariants

**Explored evidence:** read full functions (not hunks). Read immediate callers. Check the repo's discovered anti-pattern/convention docs for known traps.

**Promotion:** escalate to Open Question only if the invariant truly can't be confirmed from the repo. Trace call sites first — if every caller demonstrably passes non-null, record a finding (or no-finding).

---

## Domain 3: Edge Cases & Inputs Not Covered

What inputs/states does this code not handle?
- Parent entity in an unusual state (paused, refunded, deleted, archived)
- Retry / replay: is the operation idempotent?
- Concurrency: two users, two tabs, two cron firings
- Empty / max / negative / unicode / malformed inputs
- Upstream slow / down / 4xx / 5xx

**Explored evidence:** look for guards, early returns, validation. Identify which inputs flow through unchecked.

---

## Domain 4: Regression Risk (Things Not in the Diff)

What does this change affect that isn't visible in the diff?
- Callers of functions whose signature/behavior changed
- Code reading a field/column whose semantics changed
- Cron jobs, webhooks, scheduled tasks touching the same data
- Existing tests that pass but no longer assert what they claim
- Cached data now stale (Redis, materialized views, in-memory, CDN)
- **Sibling functions that should have received the same change but didn't** (the Domain-0 dead-code case has a twin here: live code doing the same thing as the modified function, not updated)

**Explored evidence:**
```bash
grep -rn 'changedFunction\b' src | grep -vi test          # callers
grep -rn 'markCycleSucceeded\|markCycleFailed' src | grep -vi test   # siblings
```

**Promotion:** don't ask "did you check caller X?" — check it yourself. `grep`, record a concrete risk or note no-finding. Escalate only when reading the caller doesn't reveal whether the change is safe.

---

## Domain 5: Data / Schema Migration Safety (skip if no migration)

For diffs touching migrations / schema (`migrations/`, `prisma/`, `drizzle/`, `*.sql`, ORM schema files):
- Backward-compatible with code already running in prod (expand-contract)?
- Does pre-deploy code still work against the new schema?
- Rollback survival: does data stay intact if reverted?
- `NOT NULL` adds, type narrowings, column/table removals → staged?
- Locks on large tables that could block prod traffic?
- Paired metadata/permission changes applied together?

**Explored evidence:** read the migration top-to-bottom; read accompanying metadata diffs; check precedents in the migrations dir for the same kind of operation.

---

## Domain 6: API / Contract Changes

For diffs touching public contracts — REST/GraphQL/gRPC endpoints, exported library functions, queue message shapes, webhook payloads:
- Backward-compatible for live clients/consumers? (removed/renamed field, narrowed type, new required input)
- New read/write permissions scoped correctly? (a silent `null`/empty return is a permission fail in disguise)
- Polymorphic / discriminated payloads resolved correctly?
- Input validation present at the boundary? Admin/system-level operations gated?
- Versioning honored if the contract is versioned?

**Explored evidence:** read the changed schema/contract files. Cross-check that every newly-queried field is actually exposed/permitted. Check the repo's discovered API conventions.

---

## Domain 7: Tests — What's Covered, What's Not

- Does the change include tests? Unit, integration, or both?
- Do tests exercise the risky paths, or just the happy path?
- Placeholder tests (mocks compared to themselves, only "it renders" asserted)?
- Integration tests hitting real deps vs mocking the critical path?
- What's untested that should be? (Tie back to Domain 2/3 findings.)

**Explored evidence:** read new/changed test files. Diff them against the production logic.

**Promotion:** "should this path have a test?" is sometimes a judgment call — ask the user, fall back to Open Question.

---

## Domain 8: Logging, Observability & Operations

- Logging on new failure paths? Structured and useful?
- Anything sensitive logged (tokens, full PII, raw payment data)?
- Background work: would we notice if it silently stopped?
- New analytics/events firing the right type, not double-firing one a lower layer already emits?
- Is a rollback observable — would we know to roll back if this misbehaves?

**Explored evidence:** `grep` for the repo's logger / event helpers in the diff. Check catch blocks: do they log before swallowing?

---

## Domain 9: Conventions & Codebase Hygiene

Lighter pass — flag clear violations, not stylistic preference. **This domain consumes the Standards-axis findings from the Phase 3.5 pre-pass.**
- Anti-patterns from the repo's discovered convention/instruction files
- Hardcoded values that should be constants/config
- Dead code, commented-out blocks, TODOs referencing this change
- Comments referencing "this PR" / "the previous version" (rot fast)
- Naming inconsistent with the repo's glossary/domain terms

**Batching:** hygiene findings rarely need user input — record directly, severity Low. **Posting default `[ ]`** — don't drown a review in nits.

---

## Domain 10: Security & Privacy (always at least a quick scan)

- New endpoints: authn + authz present?
- User input flowing into SQL / shell / HTML / template without sanitization?
- Secrets / tokens / keys in code, logs, or fixtures?
- Cross-tenant data leakage (org A reading org B's data)?
- New permissions / role grants — least privilege?
- Webhook / callback endpoints: signature verification?

**Explored evidence:** skim the diff for `req.body`/`req.query`, raw SQL strings, `process.env`/`os.environ`, new route handlers. Trace the auth chain.

**Promotion:** don't pre-emptively escalate a suspected vuln — trace first. Most "can A read B's data?" questions are answerable by reading the auth chain. Escalate only when the path depends on context outside the repo.
