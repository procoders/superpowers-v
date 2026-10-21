---
description: Capture one genuine architecture decision as a thin, human-confirmed ADR under docs/superpowers/adr/NNNN-slug.md — decision-with-alternatives-and-consequences, references verified to exist, draft→confirm→commit, then FTS5-recallable via /v:remember. ADR only — no C4 diagrams, no SAD documents.
---

You are running **`/v:adr`** — thin ADR capture. The decision to record is `{{args}}`.

Branch on `{{args}}`:

- **Empty** → ask: "What architecture decision should I capture? Name the choice, at least one
  alternative you weighed, and what it trades away." Then proceed.
- **A decision description** → capture it per the discipline below.

## Resolving the plugin root

The `scripts/` this command calls ship with the plugin — they are not files in your own
repository. Resolve the plugin root once per session before calling any of them:

```bash
CV="${CLAUDE_PLUGIN_ROOT:-$(ls -d "$HOME"/.claude/plugins/cache/*/superpowers-v/*/ 2>/dev/null | sort -V | tail -1)}"
CV="${CV%/}"
[ -f "$CV/scripts/compound-v-emit-workflow.py" ] || CV="$PWD"
[ -f "$CV/scripts/compound-v-emit-workflow.py" ] || { echo "superpowers-v plugin root not found: reinstall the plugin" >&2; CV=""; }
```

`CLAUDE_PLUGIN_ROOT` is set for hooks but is not set in this Bash environment, so treat it as a
hint, never the whole answer — the cache line covers an installed plugin, `$PWD` is used only inside a checkout of this plugin, and an empty `$CV` is a stop — do not run the steps below with it. Paths under `docs/superpowers/` stay relative; only the plugin's own `scripts/` get
`$CV`.

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
6. Then it's **FTS5-recallable**: `python3 "$CV/scripts/compound-v-memory.py" refresh` and confirm with
   `search`.

**Out of scope:** C4 diagrams and SAD / full-architecture documents. This captures an ADR and
nothing else — if asked for a diagram or an architecture write-up, say so and stop at the ADR.
