# Posting Comments

Posting happens in **Phase 7**, only on explicit user instruction ("post the comments" or equivalent). Never post on Phase-6 completion. **Skip this file entirely in local mode** — the findings file is the deliverable.

The host was resolved in Phase 0. Use the matching section below.

---

## Pre-flight (both hosts)

1. Confirm the head SHA (used as `commit_id` / required for GitLab positions). Stale SHAs are rejected.
2. Re-verify Phase-3 anchor classifications. Any file not in the diff is `Summary`-only.
3. Group findings by Anchor:
   - **Inline-anchorable** → posted individually on the diff line.
   - **Summary-only** → bundled into a single top-level review / MR note.

**Severity emoji convention:** 🔴 Fix before merge · 🟡 Verify before merge / Reviewer decides · 🟢 Confirmed safe (only if posting).

---

## GitHub (`gh`)

**Head SHA:** `gh pr view {n} --json headRefOid -q .headRefOid`

**Inline comment** (file is in the diff):
```bash
gh api repos/{owner}/{repo}/pulls/{n}/comments -X POST --input - <<'JSON'
{ "commit_id": "<head SHA>", "path": "src/util/paymentPlanCycle.ts", "line": 143, "side": "RIGHT", "body": "..." }
JSON
```
- `line` must appear in the diff (added or context); an unchanged-region line is rejected.
- `side`: `RIGHT` for added/modified, `LEFT` for deleted. Multi-line: `start_line` + `line` (same side).
- Failure: "review thread for that diff hunk is missing" → line not in diff, reclassify as `Summary`. "422" → usually a stale SHA; re-fetch and retry.

**Summary review** (files not in the diff, bundled):
```bash
gh api repos/{owner}/{repo}/pulls/{n}/reviews -X POST --input - <<'JSON'
{ "commit_id": "<head SHA>", "event": "COMMENT", "body": "<markdown — see body structure>" }
JSON
```
- `event`: `REQUEST_CHANGES` if any `Fix before merge`; `COMMENT` if only verify/decide/open-questions. **Never `APPROVE`** — approval is a human decision.

---

## GitLab (`glab`)

**Resolve project + diff refs** (positions need all three SHAs):
```bash
PROJ=$(git remote get-url origin | sed -E 's#^.*[:/]([^/]+/.+?)(\.git)?$#\1#' | sed 's#/#%2F#g')
glab api "projects/$PROJ/merge_requests/{n}" --jq '{base: .diff_refs.base_sha, start: .diff_refs.start_sha, head: .diff_refs.head_sha}'
```

**Inline comment** = a discussion pinned to a diff position:
```bash
glab api "projects/$PROJ/merge_requests/{n}/discussions" -X POST \
  -f body="..." \
  -f position[position_type]=text \
  -f position[base_sha]=<base> -f position[start_sha]=<start> -f position[head_sha]=<head> \
  -f position[new_path]=src/util/paymentPlanCycle.ts \
  -f position[old_path]=src/util/paymentPlanCycle.ts \
  -f position[new_line]=143
```
- `new_line` must be a line on the diff's RIGHT side. For a deleted line use `old_line` instead.
- Failure (`400 line_code`/position invalid) → the line isn't on the diff; reclassify as `Summary`.

**Summary** = a single MR note (no position):
```bash
glab mr note {n} -m "<markdown — see body structure>"
# or: glab api "projects/$PROJ/merge_requests/{n}/notes" -X POST -f body="..."
```
GitLab has no `REQUEST_CHANGES`/`APPROVE` via this skill — convey the verdict in the note body + the title icon (Phase 8). Never run `glab mr approve`.

---

## Summary body structure (both hosts)

```markdown
{One-sentence intro about the review and its scope.}

---

### 🔴 {Finding title}
{Finding body, prose-referencing file:line via Markdown code spans.}
**Required:** {recommended action}

---

### 🟡 {Finding title}
...

---

Inline comments cover: {brief list of inline anchors}.
```

---

## After Posting

1. Capture the comment/discussion URLs from the API responses.
2. Mark each posted row in the findings file: `[x]` → `[posted]`.
3. Report one line per posted comment (URL + finding #) in chat. Don't repeat the full table.

---

## Edge Cases

- **Local mode / no PR yet:** skip Phase 7. The findings file is the deliverable.
- **Draft PR/MR:** posting works; confirm the user wants comments visible while drafting.
- **The author is the user:** self-review comments are valid; confirm they want them visible.
- **Re-review:** you already read existing comments in Phase 0 — don't post duplicates.
- **No host CLI / unknown remote:** you should be in local mode; there is nothing to post.
