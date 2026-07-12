---
description: Capture one genuine architecture decision as a thin, human-confirmed ADR under docs/superpowers/adr/NNNN-slug.md — decision-with-alternatives-and-consequences, references verified to exist, draft→confirm→commit, then FTS5-recallable via /v:remember. ADR only — no C4 diagrams, no SAD documents.
---

You are running **`/v:adr`** — thin ADR capture. The decision to record is `{{args}}`.

Branch on `{{args}}`:

- **Empty** → ask: "What architecture decision should I capture? Name the choice, at least one
  alternative you weighed, and what it trades away." Then proceed.
- **A decision description** → capture it per the discipline below.

The authoritative flow lives in [`skills/compound-v/adr-capture.md`](../skills/compound-v/adr-capture.md) —
read it and apply it. In short:

1. **Litmus test.** Only capture a *genuine* decision — a real alternative existed and something was
   traded away. If not, decline and say why; do not manufacture an ADR.
2. **Draft** the `context / decision / consequences` record in-message, with the target path
   `docs/superpowers/adr/NNNN-slug.md` (next unused number).
3. **References MUST exist.** Verify every cited path/section/URL before confirming — drop any you
   can't vouch for. A fabricated citation is worse than none.
4. **Human-confirm.** Write nothing until the human approves the draft. No auto-write.
5. **Commit** with the two-command discipline (`git add` then a separate `git commit`, no `&&`,
   check each exit code) — an uncommitted ADR is invisible to recall and can be lost on worktree
   cleanup.
6. Then it's **FTS5-recallable**: `python3 scripts/compound-v-memory.py refresh` and confirm with
   `search`.

**Out of scope:** C4 diagrams and SAD / full-architecture documents. This captures an ADR and
nothing else — if asked for a diagram or an architecture write-up, say so and stop at the ADR.
