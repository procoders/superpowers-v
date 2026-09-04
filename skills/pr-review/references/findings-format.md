# Findings Format

The findings file is the working artifact of the review. It survives compaction and is the input to the comment-posting phase.

**Path** — in the repo root of the **launch** worktree, never inside the disposable review worktree. Create `./reviews/` if missing.

- **Host modes:** `./reviews/pr-review-findings-{N}.md`.
- **Local mode:** `./reviews/pr-review-findings-<base>..<head>-<YYYY-MM-DD>.md` — e.g.
  `pr-review-findings-c011d6e..7dfaeeb-2026-09-04.md`, or `pr-review-findings-origin-main..feature-x-2026-09-04.md`.
  The range and the date are in the name because a fixed `-local.md` gives every hostless review on a repo
  the same filename: the second one silently overwrites the first.
- **Sanitize each end before joining:** replace `/` with `-` (`origin/main` → `origin-main`), and collapse
  any run of two or more dots *inside* an end to a single `-`, so the only `..` left in the name is the
  separator. The result must stay a plain filename — no path separator, no leading dot, no `..` segment.

The launch-repo-root `./reviews/` location is a deliberate, target-repo-scoped choice (stack-agnostic) — it
belongs to whatever repo is under review, so it is not a doc-placement violation when this skill runs on a
repo with its own docs conventions.

**Write timing:** create at the end of Phase 1 (briefing agreed). Append the two sub-agent reports under `## Two-Axis Pre-Pass` at the end of Phase 3.5. Update the Findings table at the end of each domain in Phase 4. Finalize after Phase 5 (verdict + confidence assigned).

---

## File Structure

```markdown
# PR/MR #{n} — {title}

Review session: {date} · Host: `{github|gitlab|local}` · Branch: `{branch}` · Head SHA: `{sha}`
Diff under review: `{the exact diff command — e.g. git diff A..B, or git diff <base>...HEAD}`
Standards sources: {discovered files}. Spec coverage: {per file/area — `spec: <path>` | `changelog only` | `none`}.

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

| # | Category | Severity | Confidence | File:Line | Anchor | Finding | Recommended Action | Verdict | Class-check | Post? |
|---|----------|----------|------------|-----------|--------|---------|--------------------|---------|-------------|-------|
| 1 | Bug Risk | High | High | `checkout.ts:8565` | Summary | Cycle 1 never emits `cycle_succeeded`. | Emit it after `markCycleSucceeded`. | Fix before merge | `2 other instances` | `[x]` |
| 2 | Open Question | — | Low | `cycle.ts:166` | Inline | `getSender()` returns `null` when the row is gone. | Author: handled downstream, or crash? | Verify before merge | `n/a — low confidence` | `[x]` |

---

## Posting plan
- Summary review body bundles: {list of summary-anchored findings + intro text}
- Inline comments: {file:line list}
```

**Header substitution (local mode).** There is no `#{n}` and no PR title, so the H1 is the range:
`# Local review — <range>` (e.g. `# Local review — c011d6e..7dfaeeb`). `Host:` reads `local`, and the
`Diff under review:` line carries the exact command — two-dot vs three-dot changes what the findings
mean, so a later reader must not have to guess which form produced them. In local mode the
`## Posting plan` section reads "Local mode — nothing is posted; this file is the deliverable."

**`## Gate decisions (auto)`** — present only in Auto Mode / non-interactive runs: one line per gate
that proceeded without a user (briefing, verdicts, triage, any auto-promoted question), naming the
gate and the default taken. See the interactivity table in `SKILL.md`.

---

## Column definitions

| Column | Values | Notes |
|--------|--------|-------|
| **#** | sequential | Stable across the session. |
| **Category** | `Bug Risk` / `Edge Case` / `Regression Risk` / `Open Question` / `Style` / `Convention` / `Spec Gap` / `Scope Creep` / `Test Gap` / `Security` / `Perf` / `Doc` | Pick the dominant one. A Standards-axis finding usually becomes `Convention`; a Spec-axis finding becomes `Spec Gap` (missing/wrong) or `Scope Creep` (unasked-for). |
| **Severity** | `High` / `Medium` / `Low` / `—` | `—` for Open Questions and pure Style. |
| **Confidence** | `High` / `Medium` / `Low` | High = verified by grep/code reading. Medium = plausible pattern. Low = suspicion, needs the author. |
| **File:Line** | `path/to/file.ts:NNN` | Tightest anchor possible. Range OK: `file.ts:100-115`. |
| **Anchor** | `Inline` / `Summary` / `n/a (local)` | Phase 3, **posting mode only**. `Inline` = file is in the diff; `Summary` = referenced but not. Local mode posts nothing: Phase 3 is skipped, every row reads `n/a (local)`. |
| **Finding** | One paragraph | What's wrong / surprising. Be specific. No "this might be a problem." |
| **Recommended Action** | One sentence | What the author should do. For Open Questions, this is the question itself. |
| **Verdict** | `Fix before merge` / `Reviewer decides` / `Verify before merge` / `Nice-to-have` / `Confirmed safe` | Phase 5. |
| **Class-check** | `n other instances` / `no other instances` / `n/a — low confidence` | Phase 5, required on every High/Medium row — and a **column of the template above**, not only of this list. The result of grepping the finding's *pattern* across the repo, not just its site. `no other instances` is a real result and must be recorded — it is what lets a later reader tell "we looked" from "we never asked". Sibling instances are added as their own rows, individually anchored. |
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

**Local mode:** neither applies. Nothing is posted, Phase 3 is skipped, and the `Anchor` column records `n/a (local)`.
