---
description: Recall relevant past Compound V context — prior decisions, failures, routing lessons, specs/plans — from docs/superpowers via V-memory (FTS5, plus semantic embeddings when bootstrapped). It surfaces EVIDENCE for planning and review, never an authority over routing. Use before planning a feature, before reviewing a diff, or any time you need "have we hit this before?".
---

You are running **`/v:remember`** — V-memory recall. The query is `{{args}}`.

**Resolving the plugin root.** The `scripts/` this command calls ship with the plugin — they are
not files in your own repository. Resolve the plugin root once per session before calling any of
them:

```bash
CV="${CLAUDE_PLUGIN_ROOT:-$(ls -d "$HOME"/.claude/plugins/cache/*/superpowers-v/*/ 2>/dev/null | sort -V | tail -1)}"
CV="${CV%/}"
[ -f "$CV/scripts/compound-v-emit-workflow.py" ] || CV="$PWD"
[ -f "$CV/scripts/compound-v-emit-workflow.py" ] || { echo "superpowers-v plugin root not found: reinstall the plugin" >&2; CV=""; }
```

`CLAUDE_PLUGIN_ROOT` is set for hooks but is not set in this Bash environment, so treat it as a
hint, never the whole answer — the cache line covers an installed plugin, `$PWD` is used only inside a checkout of this plugin, and an empty `$CV` is a stop — do not run the steps below with it.

**Search in the corpus's language.** This repository's engineering prose is almost all English,
and neither lane crosses languages: FTS5 matches words, and the measured dense lane (multilingual-e5-small)
answers a Russian question with the same handful of Russian documents whatever it asks — pure-Russian
benchmark rows score 0/4 in both modes, the same questions translated to English score 2/4
(`tests/memory-queries.tsv`, 2026-09-24). So when `{{args}}` is not English, translate it to English
yourself — keep identifiers, flags, file names and error strings verbatim — and run **both** queries,
the translation first:

```
python3 "$CV/scripts/compound-v-memory.py" search "<English translation>" --top 8
python3 "$CV/scripts/compound-v-memory.py" search "{{args}}" --top 8
```

Merge the two result lists (drop repeats of the same path and heading) and say you translated. An
English query needs only the one search:

```
python3 "$CV/scripts/compound-v-memory.py" search "{{args}}" --top 8
```

Present what comes back.

A first search on a repo with no index builds one automatically.

**Tell the reader which mode answered** — lexical-only or lexical+semantic — don't let the
result stand without it: `search`'s own plain-text output names the active lane on a "Recall
mode: …" header line — surface it verbatim. If it's absent (e.g. `--json` was used), run
`python3 "$CV/scripts/compound-v-memory.py" doctor` once and read its `mode` line instead
(bootstrapped vs FTS5-only, and whether the corpus has reached the scale gate — see
[`memory.md`](../skills/compound-v/memory.md)). This matters most when the query crossed a
synonym or a language boundary and got nothing: that is expected on FTS5-only, not a bug.

**Memory is EVIDENCE, not authority:**

- It surfaces related prior prose (specs, plans, reviews, archaeology, recon, routing lessons). It **never decides routing** — backend/model/isolation stay governed by [`routing-lessons.md`](../docs/superpowers/memory/routing-lessons.md) + the scorecard, per [`routing-policy.md`](../skills/compound-v/routing-policy.md). Treat a retrieved chunk as a pointer to read, not a ruling.
- When you need a **structured** "has this file pattern repeatedly failed before?" verdict that may *auto-tighten* the next run (force worktree / add a review pass / fold into Task 0), use the deterministic bridge instead:

  ```
  python3 "$CV/scripts/compound-v-memory.py" recall-check --files <glob> [<glob>…]
  ```

Authority doc: [`skills/compound-v/memory.md`](../skills/compound-v/memory.md).
