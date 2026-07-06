---
name: pr-review
description: Use when the user wants to deeply review a pull/merge request or a local diff — "review this PR", "grill the MR", "stress-test this diff", "deep-dive code review", "code review before merge", or when they name a PR/MR URL, number, or feature branch. Works on GitHub (gh), GitLab (glab), or a plain local branch with no host. Review-only — never edits code.
argument-hint: PR/MR URL or number | empty = current branch vs base
---

# PR Review — Two-Axis, Stack-Agnostic Deep Code Review

## Philosophy

The purpose of reviewing a change is to build **shared understanding** of what the change is trying to do, then systematically hunt for the bugs and edge cases that intent reveals. Every diff carries implicit assumptions, unstated invariants, and ambiguous decisions. The review walks through them one by one.

When neither the codebase nor the user can resolve a question deterministically — when it's a real unknown about author intent or non-local context — that question itself becomes a review comment for the author to answer. The goal is **zero unexamined assumptions** before the review is finalized.

### The two review axes (Standards ⊥ Spec)

The diff is checked along **two deliberately separate axes** by parallel, context-isolated sub-agents (Phase 3.5):

- **Standards** — does the code conform to *this repo's* documented conventions (discovered in Phase 0)?
- **Spec** — does the code faithfully implement the originating spec / issue / story / PRD?

A change can pass one axis and fail the other:
- Code that follows every standard but implements the wrong thing → **Standards pass, Spec fail.**
- Code that does exactly what the issue asked but breaks the project's conventions → **Spec pass, Standards fail.**

The two axes run as **separate sub-agents** so neither pollutes the other's context, and their findings are reported **side by side, never merged or reranked across axes** — separation stops one axis from masking the other.

## Prime Directives

1. **Review only — never modify code.** No edits, fixes, commits, pushes, or merges. If the user asks for a fix mid-review, stop and confirm they want to leave the review before touching code.
2. **Exhaust the codebase before asking.** Every question to the user (or the author) must include an `Already checked:` line citing what you grepped/read and why it didn't answer it. If you can't write that line, you haven't explored enough. See [references/exploration-checklist.md](references/exploration-checklist.md).
3. **Use AskUserQuestion for every judgment question.** Never plain-text a question. Lead with your recommendation (first option, `(Recommended)`). Batch up to 4 same-domain questions per call.
4. **Don't surface what the code already answers.** Anti-pattern: asking something that 30 seconds of `grep` resolves. Reserve user questions for genuine judgment calls and author-intent for genuine non-local unknowns.
5. **Stay concrete.** Anchor every question and finding to a specific `file:line` and a specific failure mode.
6. **Promote real unknowns to review comments.** When neither code nor user can answer, record as an Open Question for the Author (defaults to post = `[x]`).
7. **Verdict and confidence are mandatory.** Every finding gets both before the user sees the triage table.

## Non-Goals

- ❌ Editing the change's code, tests, or docs
- ❌ Running migrations, fixing bugs, applying suggestions
- ❌ Merging, closing, or approving the PR/MR
- ❌ Pushing commits
- ❌ Re-printing the findings table in chat after writing it to the file (unless asked)

The only host side-effects this skill performs are **posting review comments** (Phase 7) and **updating the PR/MR title verdict icon** (Phase 8), both only on explicit user confirmation, and skipped entirely in local-branch mode.

---

## Inputs & VCS Auto-Detection

Resolve the target and the host **once**, in Phase 0. Pick the cheapest mode that works — never require a host.

| Input | Mode | How to fetch |
|-------|------|--------------|
| PR/MR **URL** | host from the URL domain | `github.com` → `gh`; `gitlab.*` → `glab` |
| PR/MR **number** | host from `git remote get-url origin` | github.com → `gh`; gitlab.* → `glab` |
| **empty / "current branch"** | **local** (no host) | `git diff <base>...HEAD`, `git log <base>..HEAD` |

**Host detection:** parse `git remote get-url origin`. If it contains `github.com` and `gh` exists → GitHub. If it contains `gitlab` and `glab` exists → GitLab. If neither CLI is present, or the remote is unknown, **fall back to local mode** and tell the user posting will be unavailable.

**Base branch detection:** `git symbolic-ref refs/remotes/origin/HEAD` → strip to branch name; fall back to `main`, then `master`. Confirm with the user via `AskUserQuestion` only if ambiguous.

**Metadata fetch (host modes):**
- GitHub: `gh pr view {n} --json title,body,author,baseRefName,headRefName,files,additions,deletions,headRefOid,commits` + `gh pr diff {n}`
- GitLab: `glab mr view {n}` (or `glab api projects/:id/merge_requests/{n}`) + `glab mr diff {n}`

If the input is ambiguous, ask via `AskUserQuestion`.

---

## Source Auto-Discovery (the stack-agnostic core)

Do NOT hardcode any project's doc paths. In Phase 0, **discover** the two axes' sources by globbing well-known locations and matching to the changed areas. Record what you found (and what you didn't) in the findings file.

**Standards-axis sources** (read those that exist, prefer ones relevant to the changed files):
- Instruction files: `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`, `GEMINI.md` (repo root **and** nested dirs touched by the diff), `CONTRIBUTING.md`, `.cursorrules`
- Convention docs: `docs/coding-standards/**`, `docs/**/best_practices*/**`, `docs/conventions/**`, `docs/architecture/**`, `docs/**/style*`
- Tooling configs as ground truth: `.editorconfig`, `eslint*`, `.prettier*`, `tsconfig*`, `ruff*`, `.golangci*` — but **skip anything the linter already enforces** (don't re-flag what CI catches).

**Spec-axis sources** (first match wins; if none → "no spec available"):
- A spec/PRD matching the branch/feature: `specs/*/spec.md`, `specs/**/spec.md`, `docs/prd/**`, `docs/specs/**`, `.scratch/**` (match by branch slug or feature name).
- A **linked issue/story** referenced in the branch name or PR/MR body. Parse common ID shapes: `#NNN`, `GH-NNN`, `sc-NNNNN`, `[A-Z]+-\d+` (Jira), GitLab `!NN`/`#NN`. Fetch via `gh issue view` / `glab issue view` when a host is available.
- If multiple candidates, ask the user which is authoritative (`AskUserQuestion`).

**Exit:** the findings file's `## What this PR does` section names the Standards sources read and the Spec source (or "no spec available").

---

## Two Modes: First Review vs Re-Review

Decided in Phase 0 by whether **the current user already has comments on this PR/MR**:

- **First review** — full phase order: context → briefing → audit → two-axis pre-pass → interrogation → verdict → triage → post.
- **Re-review** — the change was already reviewed and the author presumably pushed responses. Skip heavy context-gathering and full interrogation; instead confirm what changed, check each prior comment for resolution, sanity-check the new commits, produce a verdict. **The re-review verdict is always presented for user confirmation — never finalized autonomously.**

**Detection (Phase 0):** after fetching comments, get the current user (`gh api user --jq .login` / `glab api user --jq .username`) and match against comment authors (GitHub: `gh pr view {n} --comments` + `gh api repos/{owner}/{repo}/pulls/{n}/comments`; GitLab: `glab api projects/:id/merge_requests/{n}/notes`). Prior comments by the current user → **re-review** ([flow below](#re-review-flow)). Else → first review. Ambiguous → ask.

In **local mode** there are no host comments — always first review.

---

## Worktree Isolation (optional, host modes)

So a review never disturbs the user's working tree or another concurrent review:

1. **Never `git checkout` in the session's working tree.** Materialize the PR/MR in a dedicated detached worktree.
2. Deterministic path so concurrent sessions converge: `<repo-parent>/<repo>-reviews/pr-{n}`.
3. Worktrees are **detached, read-only, disposable.** Never edit/build/commit inside (Prime Directive 1).
4. Run all grep/read against the worktree with absolute paths.

```bash
MAIN_REPO="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
REPO_NAME="$(basename "$(git rev-parse --show-toplevel)")"
REVIEW_WT="$MAIN_REPO/../${REPO_NAME}-reviews/pr-{n}"
# GitHub: git fetch origin "pull/{n}/head" ; GitLab: git fetch origin "merge-requests/{n}/head"
git fetch origin "<pull-ref>"
git worktree add --detach "$REVIEW_WT" FETCH_HEAD
```

- Reuse `$REVIEW_WT` if it exists; refresh to the head SHA if stale.
- If worktree creation fails, fall back to read-only inspection: fetch the ref and read files via `git show <ref>:{path}`.
- **Skip entirely in local mode** — the session's own worktree IS the review target.
- The **findings file lives in the launch repo** (`./reviews/`), never inside the disposable worktree.
- Offer `git worktree remove "$REVIEW_WT"` at the end (decline if another session may still use it).

---

## Phase Order (the spine — each phase has an exit gate; do not skip)

### Phase 0 — Context Setup
1. Resolve target + host + base branch (see Inputs). Fetch metadata, diff, head SHA, comments. **Determine the mode** (first vs re-review). If re-review → jump to the [Re-Review Flow](#re-review-flow).
2. (Host modes) Materialize the PR/MR in an isolated worktree.
3. **Auto-discover the Standards and Spec sources** (see Source Auto-Discovery).
4. Read the changed files in full (surrounding context, not just hunks).
5. Read existing review comments; don't re-litigate.

**Exit gate:** none — proceed to Phase 1 (first review) or the Re-Review Flow.

### Phase 1 — "What this PR does" Briefing (mandatory, before any interrogation)
Plain-English, zoomed out enough to picture the change inside the whole system. Three parts:
1. **What** — user-facing terms, one short paragraph.
2. **Why** — the problem it solves and where it sits in the product (what depends on it, what it depends on, what stage the area is in: new feature / hardening / migration / cleanup). One–two short paragraphs.
3. **How** — a 1–3 bullet structural sketch of the layers/files touched and how they connect. NOT a line-by-line diff summary.

Write it to the findings file under `## What this PR does`. Present it; the user confirms or corrects.

**Exit gate:** user confirms the briefing (or accepts corrections). Do not start Phase 2 before this.

### Phase 2 — Description Audit
Does the PR/MR body actually describe the change?
- **Empty/boilerplate** → finding, severity Low, post=`[x]`, ask author to add a description.
- **Stale/partial** → finding flagging the divergence.
- **Accurate** → no finding.

(In local mode with no PR yet, skip.) **Exit gate:** none.

### Phase 3 — Diff Anchor Classification
For each file in context, classify:
- **Inline-anchorable** — file appears in the diff. Inline comments will work.
- **Summary-only** — referenced but NOT modified. Inline comments will fail; findings go in the review body, citing `file:line` in prose.

**Exit gate:** none — but every finding from Phase 4 on MUST carry its anchor class.

### Phase 3.5 — Two-Axis Parallel Pre-Pass (Standards ⊥ Spec)
Run **two context-isolated sub-agents in parallel** (two `Agent` calls, `subagent_type: general-purpose`, ONE message) to produce a baseline along each axis. This front-loads deterministic, codebase-grounded findings so Phase 4 can focus on judgment calls.

Pin the inputs (gathered in Phase 0): the diff command + commit list; the discovered Standards sources; the discovered Spec source (or "no spec available"). Each sub-agent runs all grep/read against the review worktree (or local tree) with absolute paths.

**Standards sub-agent prompt** (include diff command + commit list + discovered Standards source paths):
> Report — per file/hunk — every place the diff violates a documented convention in this repo. Use the provided instruction/convention files to find the relevant rule per changed area. Cite the source file + the specific rule for each finding. Distinguish hard violations (rule clearly broken) from judgement calls (rule arguably bent). Skip anything tooling enforces (lint/format). Anchor each to `file:line`. Under 400 words. Return the report as your final message — it is data, not a human-facing summary.

**Spec sub-agent prompt** (include diff command + commit list + the spec/issue path or contents):
> Report: (a) requirements the spec asked for that are missing or only partially implemented; (b) behaviour in the diff the spec did not ask for (scope creep); (c) requirements that look implemented but where the implementation looks wrong. Quote the spec line / acceptance criterion for each finding. Anchor each to `file:line`. Under 400 words. Return the report as your final message — it is data, not a human-facing summary. If no spec was provided, reply exactly: "No spec available."

**Aggregate** into the findings file under `## Two-Axis Pre-Pass` with two sub-headings — `### Standards` and `### Spec` — holding each report **verbatim (lightly cleaned)**. Do NOT merge, dedupe across the two, or rerank between axes. End with one summary line per axis (count + single worst issue *within that axis*). Do not pick a winner across axes.

**Feeding Phase 4:** treat each pre-pass finding as a candidate. Standards findings flow into Domain 9 (Conventions); Spec findings into Domain 1 (Intent Alignment). Each candidate is confirmed (promoted with verdict/confidence/anchor in Phase 5), downgraded to no-finding, or promoted to an Open Question. The Prime-Directive-2 exploration gate still applies.

**Exit gate:** both reports written under `## Two-Axis Pre-Pass` (Spec may read "No spec available").

### Phase 4 — Domain Interrogation
Work through [references/review-domains.md](references/review-domains.md), starting with **Domain 0 (Dead Code & Call-Graph Reality Check)**, then **Domain 1 (Intent Alignment)**, then by relevance. For each domain:
1. Identify the lines/files that fall under it.
2. **Run the [exploration checklist](references/exploration-checklist.md) per question.** Write the `Already checked:` line. If empty, keep exploring.
3. Route: code answers it → record finding directly; genuine judgment → `AskUserQuestion` (batched ≤4, same domain); genuine author-intent unknown → Open Question.
4. **Loop-break:** if the user answers "not sure / verify" 2+ times in one batch, STOP the batch, go re-explore, return with grounded recommendations.
5. Append a one-line summary per domain to the findings file.

**Exit gate:** every relevant domain covered; findings file updated per domain.

### Phase 5 — Verdict & Confidence Pass
Assign two mandatory fields per finding:
- **Confidence:** High (verified by grep/code reading) / Medium (plausible pattern) / Low (suspicion).
- **Verdict:** `Fix before merge` / `Reviewer decides` / `Verify before merge` / `Nice-to-have` / `Confirmed safe`.

**Auto Mode:** assign autonomously. **Otherwise:** present as `AskUserQuestion` batch(es) and let the user adjust.

**Exit gate:** every row has Confidence + Verdict.

### Phase 6 — Triage With User
Present the complete findings table ([references/findings-format.md](references/findings-format.md)). User checks `[x]` in Post?. Defaults: Open Questions → `[x]`; Confirmed-safe → `[ ]`; Low hygiene → `[ ]`; everything else → `[ ]` (opt in).

**Exit gate:** user finalized Post? selections.

### Phase 7 — Post Comments (explicit instruction only; host modes only)
Do not post on Phase-6 completion — wait for "post the comments". Route per Phase-3 anchor class (inline vs summary). See [references/posting-comments.md](references/posting-comments.md) for the gh + glab recipes (head SHA, payload shapes, GitLab discussion positions, fallbacks). After posting, report which comments went out (URLs); mark posted rows `[posted]`. **Local mode: skip — the findings file is the deliverable.**

### Phase 8 — Update PR/MR Title Verdict Icon (optional; host modes only)
After the outcome is settled, prefix the title with the icon(s):

| Icon | Meaning |
|------|---------|
| 💬 | Comment / open questions awaiting the author; no blocking issues |
| 🔴 | Change required — at least one `Fix before merge` finding |
| 🟢 | Approved / ready to merge — no blocking findings |

Combine when mixed (common: **🟢💬**), strongest-first (🔴 before 💬; 🟢 before 💬). **Replace, don't stack** — strip existing icon(s) first. Update via `gh pr edit {n} --title "…"` / `glab mr update {n} --title "…"`. Confirm with the user first. Skip in local mode.

---

## Re-Review Flow

Entered from Phase 0 when the current user already commented. **Replaces Phases 1–6.** Worktree setup, posting (Phase 7), and title-icon (Phase 8) machinery still apply. Mental model: the change was already reviewed, the author pushed responses — verify those, don't re-derive everything.

- **R1 — Collect prior state.** Gather every prior comment by the current user (inline + summary), each with its `file:line`, what it flagged, and its original verdict (check `./reviews/pr-review-findings-{n}.md` if it survives). Read author replies. Identify the **delta since last review** (commits after the last comment timestamp; diff `{sha-at-last-review}...HEAD`).
- **R2 — Resolution check** (per prior comment, by reading the code at the worktree, not trusting reply text): Resolved / Partially resolved / Not resolved / Won't-fix-but-justified. Apply Prime Directive 2 — record an `Already checked:` line for any "not resolved" call.
- **R3 — Sanity check the delta.** Focused pass (not the full Domain sweep): did fixes introduce regressions or new edge cases? Did unrelated changes sneak in? Quick scan against Domain 0 + obviously-touched domains, changed lines only. New issues → fresh findings (verdict + confidence + anchor).
- **R4 — Verdict (always user-confirmed).** Per-prior-comment status table + new findings + proposed overall verdict and icon. **Require explicit user confirmation before acting — always, including Auto Mode.** Write under `## Re-review ({date})`, appended below prior content.
- **R5 — Post & retitle** once confirmed; then offer worktree cleanup.

---

## Artifacts

All file artifacts go in `./reviews/` of the **launch** repo (create if missing), never inside the disposable worktree.

| Artifact | Purpose | Lifecycle |
|----------|---------|-----------|
| **Findings file** (`./reviews/pr-review-findings-{n}.md`, or `-local.md`) | Working doc; survives compaction; holds briefing, two-axis pre-pass (kept separate), table with verdict+confidence+anchor, Post? selections. | Updated per domain; persisted to disk. |
| **Posted comments** | Published output to the author. | Only what the user checked. |
| **Title icon** (💬/🔴/🟢) | At-a-glance verdict. | Set in Phase 8; replaced on re-review. |
| **Chat** | Live interrogation. | Don't regurgitate the table after writing the file; don't volunteer an end-of-session summary unless asked. |

---

## Asking Questions (rules)

- **Use `AskUserQuestion`** — never plain-text questions.
- **First option = recommendation,** with `(Recommended)` in the label.
- **Batch ≤4, same domain only.** Cross-domain → separate calls.
- **Every question body MUST include an `Already checked:` line** — the exploration gate made visible.
- **Include an escape hatch:** an "I don't know — ask the author" option (promotes to Open Question without forcing "Other").
- **Anchor to `file:line`.** "What happens at `paymentPlan.ts:204` when `last_*` is null?" beats "is null-handling right?"
- **Loop-break:** user can't answer twice → stop the batch, re-explore.

Tool constraints: 2–4 options, header ≤12 chars, `multiSelect: true` only when options aren't mutually exclusive.

**Fallback (no AskUserQuestion):** `**[Domain] — [Topic] — file:line**` + question + `**My read:**` + `**Already checked:**` + 2–3 lettered options including one "I don't know — promote to comment."

---

## When to Stop

**First review** is complete when: the briefing is agreed; the two-axis pre-pass has run (both reports in the file, or Spec marked "no spec available"); every relevant domain is worked (including pre-pass candidates); every risk hot-spot is a finding, no-finding, or Open Question; every row has Confidence + Verdict + Anchor; Post? is finalized.

**Re-review** is complete when: every prior comment has a resolution status (R2); the delta had its sanity pass (R3); the overall verdict is **explicitly confirmed by the user** (R4) — never skipped.

After that, await explicit instruction to post (or to end without). Then close out: Phase 8 title icon (host modes), then offer to remove the review worktree.
