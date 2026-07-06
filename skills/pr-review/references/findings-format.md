# Findings Format

The findings file is the working artifact of the review. It survives compaction and is the input to the comment-posting phase.

**Path:** `./reviews/pr-review-findings-{N}.md` (host modes) or `./reviews/pr-review-findings-local.md` (local-branch), in the repo root of the **launch** worktree — never inside the disposable review worktree. Create `./reviews/` if missing. The launch-repo-root `./reviews/` location is a deliberate, target-repo-scoped choice (stack-agnostic) — it belongs to whatever repo is under review, so it is not a doc-placement violation when this skill runs on a repo with its own docs conventions.

**Write timing:** create at the end of Phase 1 (briefing agreed). Append the two sub-agent reports under `## Two-Axis Pre-Pass` at the end of Phase 3.5. Update the Findings table at the end of each domain in Phase 4. Finalize after Phase 5 (verdict + confidence assigned).

---

## File Structure

```markdown
# PR/MR #{n} — {title}

Review session: {date} · Host: `{github|gitlab|local}` · Branch: `{branch}` · Head SHA: `{sha}`
Standards sources: {discovered files}. Spec source: {discovered spec / issue / "no spec available"}.

---

## What this PR does

{Phase-1 briefing — what / why / how, with system context. Three short paragraphs.}

---

## Two-Axis Pre-Pass

{Phase-3.5 output. Two sub-agent reports, verbatim (lightly cleaned), kept separate — never merged or reranked across axes.}

### Standards
{Standards sub-agent report — violations of documented conventions, each citing the source file + rule, anchored to file:line.}

### Spec
{Spec sub-agent report — missing/partial requirements, scope creep, wrong-looking implementations, each quoting the spec/issue line. Or "No spec available."}

_Summary: Standards — N findings (worst: …). Spec — M findings (worst: …)._

---

## Decisions log (per domain)
{One line per domain explored in Phase 4. Optional — useful for compaction recovery.}

---

## Findings

| # | Category | Severity | Confidence | File:Line | Anchor | Finding | Recommended Action | Verdict | Post? |
|---|----------|----------|------------|-----------|--------|---------|--------------------|---------|-------|
| 1 | Bug Risk | High | High | `src/services/checkout.ts:8565` | Summary | Cycle 1 of every recurring plan calls `markCycleSucceeded` but the new `cycle_succeeded` event is never emitted here. Consumers bound to that event silently miss cycle 1. | Emit `cycle_succeeded` after the `markCycleSucceeded` call. | Fix before merge | `[x]` |
| 2 | Open Question | — | Low | `src/util/paymentPlanCycle.ts:166` | Inline | `getSender()` returns `null` when the row is gone. Downstream dispatcher behavior unverified. | Author: does the dispatcher handle a `null` sender gracefully, or crash? | Verify before merge | `[x]` |

---

## Posting plan
- Summary review body bundles: {list of summary-anchored findings + intro text}
- Inline comments: {file:line list}
```

---

## Column definitions

| Column | Values | Notes |
|--------|--------|-------|
| **#** | sequential | Stable across the session. |
| **Category** | `Bug Risk` / `Edge Case` / `Regression Risk` / `Open Question` / `Style` / `Convention` / `Spec Gap` / `Scope Creep` / `Test Gap` / `Security` / `Perf` / `Doc` | Pick the dominant one. A Standards-axis finding usually becomes `Convention`; a Spec-axis finding becomes `Spec Gap` (missing/wrong) or `Scope Creep` (unasked-for). |
| **Severity** | `High` / `Medium` / `Low` / `—` | `—` for Open Questions and pure Style. |
| **Confidence** | `High` / `Medium` / `Low` | High = verified by grep/code reading. Medium = plausible pattern. Low = suspicion, needs the author. |
| **File:Line** | `path/to/file.ts:NNN` | Tightest anchor possible. Range OK: `file.ts:100-115`. |
| **Anchor** | `Inline` / `Summary` | Phase 3. `Inline` = file is in the diff. `Summary` = referenced but not in the diff; post via the review body. |
| **Finding** | One paragraph | What's wrong / surprising. Be specific. No "this might be a problem." |
| **Recommended Action** | One sentence | What the author should do. For Open Questions, this is the question itself. |
| **Verdict** | `Fix before merge` / `Reviewer decides` / `Verify before merge` / `Nice-to-have` / `Confirmed safe` | Phase 5. |
| **Post?** | `[ ]` / `[x]` / `[posted]` | Default `[ ]`. Open Questions default `[x]`. After posting, mark `[posted]`. |

---

## Defaults for Post?

- **Open Questions** → `[x]` (they exist *because* the author must weigh in)
- **`Fix before merge`** → `[x]`
- **`Verify before merge`** → `[x]`
- **`Reviewer decides`** → `[ ]` (user opts in)
- **`Nice-to-have`** → `[ ]`
- **`Confirmed safe`** → `[ ]` (working doc only)
- **Style / hygiene** → `[ ]` (don't drown reviews in nits)

User can override any default in Phase 6.

---

## What goes inline vs. in the summary review

**Inline (Anchor = `Inline`):** the file appears in the diff. Use the host's inline-comment API; cite `file:line` via the native UI.

**Summary (Anchor = `Summary`):** the file is referenced but not in the diff. Inline comments will fail. Bundle these in the top-level review body and reference `file:line` in prose (Markdown code spans).

When in doubt, check Phase 3 classification. If Phase 3 wasn't done for a file, do it now before posting.
