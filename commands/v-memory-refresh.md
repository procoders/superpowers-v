---
description: (Re)index docs/superpowers prose into the local V-memory cache so recall is current. Incremental by file hash; runs fully offline (FTS5, pure stdlib). Optionally enable the semantic lane with a one-time bootstrap. Run it after pulling new docs, or when /v:remember looks stale.
---

You are running **`/v:memory-refresh`**. Args: `{{args}}`.

**Default — offline, FTS5, no install, no network:**

```
python3 scripts/compound-v-memory.py refresh
python3 scripts/compound-v-memory.py doctor
```

Report the `doctor` summary (files / chunks / staleness / whether embeddings are bootstrapped).

**Semantic lane (opt-in).** Embeddings are OFF by default and live **outside the repo**
(`~/.cache/compound-v/memory/<repo-id>/`). Enabling them is the **only** step that touches
the network — and it must be explicit, never from a hook:

```
python3 scripts/compound-v-memory.py bootstrap                 # creates the out-of-repo venv + model (one time)
python3 scripts/compound-v-memory.py refresh --with-embeddings # populate vectors
```

If the project opted into embeddings at [`/v:init`](v-init.md) (`memory.embeddings: true` in
`.claude/compound-v.json`), the engine **already** adds vectors on a plain `refresh` once
bootstrapped — you don't need the flag. If `{{args}}` asks for `--with-embeddings` and
`doctor` shows embeddings are not bootstrapped, run `bootstrap` first (tell the user it will
download a ~200 MB model once).
The semantic lane is **scale-gated**: it only changes ranking once the corpus is large
enough to matter; on a small corpus FTS5 already wins. If bootstrap fails (offline / no
wheels), the engine stays FTS5-only — recall still works. See
[`skills/compound-v/memory.md`](../skills/compound-v/memory.md).
