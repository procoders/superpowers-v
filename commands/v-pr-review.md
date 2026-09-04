---
description: Deep, two-axis, stack-agnostic code review of a PR/MR, a commit range, or a local diff — review-only, never edits code. Runs the pr-review skill. GitHub (gh), GitLab (glab), or hostless. Argument = PR/MR URL or number, a range (`A..B`/`A...B`), a tag or a SHA; empty = current branch vs base.
---

You are running a **deep PR/MR code review** on `{{args}}` — a pull/merge request URL or number, a commit range (`A..B` / `A...B`), a tag or a SHA, or, if empty, the current branch against its base.

Invoke the [`pr-review`](../skills/pr-review/SKILL.md) skill and follow it exactly. The skill is **review-only**: it never edits, commits, pushes, or merges code.

## Steps

1. **Resolve the target.** Use `{{args}}` as the PR/MR URL or number, **or as a commit range / ref**. If empty,
   review the current branch against its base. The skill auto-detects the host — GitHub (`gh`), GitLab (`glab`),
   or a hostless local diff.
   - **A range or a ref** (`A..B`, `A...B`, a tag, a SHA) is a **local-mode** target even when `gh`/`glab` is
     installed — a range has no PR to fetch, so don't go looking for one. `A..B` is diffed literally; `A...B` and
     the empty-argument default `<base>...HEAD` are **three-dot, merge-base** diffs. Whichever form is used, name
     it in the findings-file header.
   - **Host present but no PR** — a host CLI exists and the remote is known, but `gh`/`glab` finds no PR/MR for the
     current branch → run in local mode without attempting a PR fetch. This is the ordinary case for reviewing an
     already-merged range, not an error.
   - **Empty diff = nothing to review.** On the base branch itself (HEAD `main`, base `origin/main`) the
     branch-vs-base diff is empty. Say so plainly — "nothing to review; pass a range, e.g. `/v:pr-review A..B`" —
     and stop rather than producing an empty review.
2. **Run the pr-review skill** end-to-end: build shared understanding of the change's intent, then hunt bugs and edge cases along the two deliberately separate axes — **Standards** (does the code follow *this repo's* documented conventions?) ⊥ **Spec** (does it faithfully implement the originating spec/issue?) — run as context-isolated sub-agents. Promote real unknowns to Open Questions for the author. Every finding gets a verdict + confidence.
3. **Hand back** the triaged findings table. Never modify the reviewed code — if the user asks for a fix mid-review, stop and confirm they want to leave the review first.

## Notes

- Review-only — no edits, commits, pushes, or merges (skill Prime Directive 1).
- **No user to answer?** In a subagent, a `claude -p` run, or a workflow step, every user-facing gate (Phase 1
  briefing, Phase 5 verdicts, Phase 6 triage, Prime Directive 3) proceeds under the skill's documented
  non-interactive default, and each auto-taken choice is recorded in the findings file.
- Full behavior — exploration checklist, review domains, findings format, and comment-posting — lives in [`skills/pr-review/SKILL.md`](../skills/pr-review/SKILL.md) and its `references/`.
