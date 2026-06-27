---
description: Refresh the Compound V tier→model map — discover the concrete models each backend (claude, codex, antigravity) currently offers, show them, let you assign deep/standard/light, and write the result into .claude/compound-v.json so intent-based routing survives model churn without touching any call site.
disable-model-invocation: true
---

You are running **`/v:models`** — the Compound V model broker's **refresh
surface**. Compound V routes work by **intent** (a stable `tier` vocabulary —
`deep` / `standard` / `light`) instead of hardcoding model strings that rot every
time a provider ships a new model. The mapping from tier → concrete model lives in
a **refreshable** `models` block in `.claude/compound-v.json`. This command
discovers what each backend can run **right now**, lets you assign each tier, and
rewrites that block. Nothing else in the plugin changes — the dispatcher resolves
tiers through [`scripts/compound-v-resolve-model.py`](../scripts/compound-v-resolve-model.py)
at dispatch time, so refreshing the map here is the *only* thing you ever touch
when models churn.

Argument (optional): `{{args}}` may name a single backend to refresh in isolation
(`claude` | `codex` | `antigravity`); otherwise walk all three.

**This is the "skill picks the models and offers you the options" surface.** Do the
discovery, *show* what you found, then let the user choose. Never silently pick a
model the user did not confirm. **NEVER assign `haiku` to any tier on any backend.**

---

## Step 0 — Load the current map

Read `.claude/compound-v.json` if it exists. Remember its current `models` block
(seeded by [`/v:init`](v-init.md)) so you can show the user what is changing and
preserve any backend they don't refresh this run. If the file or its `models` key
is absent, fall back to the built-in default (the resolver carries the same one):

```jsonc
"models": {
  "claude":      { "deep": "opus",                  "standard": "opus",                  "light": "sonnet" },
  "codex":       { "deep": "gpt-5.5",               "standard": "gpt-5.5",               "light": "gpt-5.3-codex-spark" },
  "antigravity": { "deep": "Gemini 3.1 Pro (High)", "standard": "Gemini 3.1 Pro (Medium)", "light": "Gemini 3.1 Flash" }
}
```

If `{{args}}` named one backend, only discover + reassign that backend and leave the
other two blocks exactly as they are.

---

## Step 1 — Discover available models per backend

Each backend exposes its catalog differently. Discover, don't guess — and report
honestly what discovery actually returned.

### 1a. claude — native tier aliases (no discovery call)

Claude resolves a tier to one of its **native model aliases**. The shipped tiers are:

- `deep` → `opus` (strongest reasoning)
- `standard` → `opus`
- `light` → `sonnet`

There is no list command to run; the alias set is `opus` / `sonnet`. **Never
`haiku`.** Offer `opus` and `sonnet` as the only choices per tier.

### 1b. codex — curated list (no list command exists)

Codex has **no `models` list command**. Maintain a small **curated** roster and let
the user override any entry by hand (a model the curated list doesn't know about is
still valid — codex accepts whatever model string you pass to `codex exec --model`).
Present this curated starting roster:

- `gpt-5.5` — strongest; suggested for `deep` and `standard`
- `gpt-5.3-codex-spark` — fast/cheap; suggested for `light`

Confirm codex is even usable first (so you don't write a map the project can't run):

```bash
command -v codex && codex exec --help 2>/dev/null | grep -q -- '--model' && echo "codex usable" || echo "codex unavailable"
```

If codex is unavailable, say so, keep the existing codex block unchanged, and skip
its reassignment (the map can still carry codex entries for when it returns).

### 1c. antigravity — `agy models` when present

Antigravity (Gemini family) **does** have a discovery command. Probe for it, then
list:

```bash
command -v agy && agy models 2>/dev/null || echo "agy unavailable"
```

- If `agy models` returns a catalog, parse the available model names from it and
  offer those (e.g. the Gemini Pro / Flash variants, including any effort-labelled
  variants the CLI surfaces). These supersede the placeholder defaults.
- If `agy` is absent or errors, say so plainly, keep the **illustrative placeholder**
  values (`Gemini 3.1 Pro (High)` / `(Medium)` / `Gemini 3.1 Flash`) from the current
  map, and note they are unverified placeholders to be refreshed once `agy` is
  installed. Do **not** invent model names beyond what `agy models` actually printed.

---

## Step 2 — Show findings and let the user assign tiers

For each backend in scope, present a compact table: discovered/available models on
one side, the three tiers on the other, and your **suggested** assignment (the
sensible-default pairing: strongest model → `deep`, a mid option → `standard`, the
fast/cheap option → `light`). Example shape:

| Backend | Available now | deep | standard | light |
|---|---|---|---|---|
| claude | opus, sonnet | opus | opus | sonnet |
| codex | gpt-5.5, gpt-5.3-codex-spark | gpt-5.5 | gpt-5.5 | gpt-5.3-codex-spark |
| antigravity | *(from `agy models`)* | … | … | … |

Then **let the user assign** each tier per backend — accept the suggestion as-is, or
override any cell with any model name the discovery surfaced (or, for codex, any
string they want). Re-state the final assignment back to them before writing.

Guardrails on every assignment:

- Every backend in scope must have all three tiers (`deep`, `standard`, `light`) set
  to a non-empty string.
- **No `haiku` anywhere**, on any backend, ever — refuse and re-ask if requested.
- `deep` should be the strongest available model for that backend (it's what
  reviewers and Task 0 resolve through — see
  [`routing-policy.md`](../skills/compound-v/routing-policy.md)); warn if the user
  assigns a weaker model to `deep` than to `standard`/`light`, but allow it on
  explicit confirmation.

---

## Step 3 — Write the map into `.claude/compound-v.json`

Merge the confirmed assignments into the config's `models` block. **Preserve every
other key** in the file (`stance`, `backends`, `checked_at`, `workflows_accelerator`,
…) and any backend block you did not refresh this run. Create the file (and parent
dir) if absent, seeding the non-`models` keys from `/v:init` conventions if they
aren't there yet.

Resulting shape (only `models` is this command's responsibility):

```jsonc
{
  "stance": "…",            // preserved
  "backends": ["…"],         // preserved
  "checked_at": "…",         // preserved
  "models": {
    "claude":      { "deep": "opus",    "standard": "opus",    "light": "sonnet" },
    "codex":       { "deep": "gpt-5.5", "standard": "gpt-5.5", "light": "gpt-5.3-codex-spark" },
    "antigravity": { "deep": "…",       "standard": "…",       "light": "…" }
  }
}
```

The `models` map is **project-local config** — written into the project, not
committed in the plugin repo (it is documented in
[`execution-manifest.md`](../skills/compound-v/execution-manifest.md), seeded by
`/v:init`, refreshed here).

---

## Step 4 — Verify the map resolves

Before declaring success, confirm the resolver agrees with the new map — this is the
loop that proves routing will actually use what you wrote:

```bash
for b in claude codex antigravity; do
  for t in deep standard light; do
    python3 scripts/compound-v-resolve-model.py --backend "$b" --tier "$t" \
      --config .claude/compound-v.json
  done
done
```

Each line should be a JSON object whose `model` matches the cell you just assigned
(the resolver's `--config models.<backend>.<tier>` override beats its built-in
default). A non-zero exit or a mismatched model means the write didn't take — fix the
JSON and re-run. (Skip the `codex` rows if codex is unavailable on this machine; the
map entries are still valid for when it returns.)

---

## Step 5 — Report

Summarize per backend: what discovery returned (or that it was unavailable /
placeholder), the final `deep`/`standard`/`light` assignment, and the path written
(`.claude/compound-v.json`). Note that the dispatcher now resolves these via
[`scripts/compound-v-resolve-model.py`](../scripts/compound-v-resolve-model.py) and
that `effort` (`low`/`medium`/`high`) is an **orthogonal** dimension chosen per
task-type in [`routing-policy.md`](../skills/compound-v/routing-policy.md), not set
here.

**Honesty rules:** report only what discovery actually returned. If `agy models`
didn't run, say the antigravity values are unverified placeholders — don't pass them
off as confirmed. Never print token or cost numbers (anti-ruflo). Never assign
`haiku`.
