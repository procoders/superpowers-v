---
description: (Re)index docs/superpowers prose into the local V-memory cache so recall is current. Incremental by file hash; runs fully offline (FTS5, pure stdlib). Optionally enable the semantic lane with a one-time bootstrap. Run it after pulling new docs, or when /v:remember looks stale.
---

You are running **`/v:memory-refresh`**. Args: `{{args}}`.

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

**Default — offline, FTS5, no install, no network:**

```
python3 "$CV/scripts/compound-v-memory.py" refresh
python3 "$CV/scripts/compound-v-memory.py" doctor
```

Report the `doctor` summary (files / chunks / staleness / whether embeddings are bootstrapped).

**Semantic lane (opt-in).** Embeddings are OFF by default and live **outside the repo**
(`~/.cache/compound-v/memory/<repo-id>/`). Enabling them is the **only** step that touches
the network — and it must be explicit, never from a hook:

```
python3 "$CV/scripts/compound-v-memory.py" bootstrap                 # creates the out-of-repo venv + model (one time)
python3 "$CV/scripts/compound-v-memory.py" refresh --with-embeddings # populate vectors
```

If the project opted into embeddings at [`/v:init`](v-init.md) (`memory.embeddings: true` in
`.claude/compound-v.json`), the engine **already** adds vectors on a plain `refresh` once
bootstrapped — you don't need the flag. If `{{args}}` asks for `--with-embeddings` and
`doctor` shows embeddings are not bootstrapped, run `bootstrap` first (tell the user it will
download a ~200 MB model once).

**`--with-embeddings` only does something once ALL THREE conditions hold** — say this plainly
if `doctor` shows the dense lane inactive after a refresh:

1. `bootstrap` has completed (out-of-repo venv present);
2. `.claude/compound-v.json` has `memory.embeddings: true` (set at [`/v:init`](v-init.md) Step
   3b, or by hand); and
3. the corpus has reached the scale gate (a minimum vector count — dense stays dormant,
   FTS5-only, below it, deliberately: on a handful of docs a full read or FTS5 already wins).

`doctor`'s own `mode` line reports exactly which of the three is missing in plain language (e.g.
"dense venv installed but disabled", "dense enabled but not bootstrapped", "below the scale
gate (N vectors < gate)") — read that line rather than re-deriving the state from the other
fields. Any one of the three missing ⇒ FTS5-only, silently and correctly. This is also the shape
of the most common confusion: bootstrapped-but-not-configured (condition 2 missing) looks
identical to "nothing happened" from the outside — the `mode` line is what tells them apart. See
[`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) for that failure mode written out.

The semantic lane is **scale-gated**: it only changes ranking once the corpus is large
enough to matter; on a small corpus FTS5 already wins. If bootstrap fails (offline / no
wheels), the engine stays FTS5-only — recall still works. See
[`skills/compound-v/memory.md`](../skills/compound-v/memory.md).
