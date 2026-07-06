---
description: Deep, two-axis, stack-agnostic code review of a pull/merge request or a local diff — review-only, never edits code. Runs the pr-review skill. Works on GitHub (gh), GitLab (glab), or a hostless local branch. Argument = PR/MR URL or number; empty = current branch vs base.
---

You are running a **deep PR/MR code review** on `{{args}}` — a pull/merge request URL or number, or, if empty, the current branch against its base.

Invoke the [`pr-review`](../skills/pr-review/SKILL.md) skill and follow it exactly. The skill is **review-only**: it never edits, commits, pushes, or merges code.

## Steps

1. **Resolve the target.** Use `{{args}}` as the PR/MR URL or number. If empty, review the current branch against its base. The skill auto-detects the host — GitHub (`gh`), GitLab (`glab`), or a hostless local diff.
2. **Run the pr-review skill** end-to-end: build shared understanding of the change's intent, then hunt bugs and edge cases along the two deliberately separate axes — **Standards** (does the code follow *this repo's* documented conventions?) ⊥ **Spec** (does it faithfully implement the originating spec/issue?) — run as context-isolated sub-agents. Promote real unknowns to Open Questions for the author. Every finding gets a verdict + confidence.
3. **Hand back** the triaged findings table. Never modify the reviewed code — if the user asks for a fix mid-review, stop and confirm they want to leave the review first.

## Notes

- Review-only — no edits, commits, pushes, or merges (skill Prime Directive 1).
- Full behavior — exploration checklist, review domains, findings format, and comment-posting — lives in [`skills/pr-review/SKILL.md`](../skills/pr-review/SKILL.md) and its `references/`.
