---
description: Refresh the Compound V tier→model map — discover the concrete models each backend (claude, codex, antigravity, cursor, devin, opencode) currently offers, show them, let you assign deep/standard/light, and write the result into .claude/compound-v.json so intent-based routing survives model churn without touching any call site.
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
(`claude` | `codex` | `antigravity` | `cursor` | `devin` | `opencode`); otherwise walk
all of them. `devin` and `opencode` are **worker-only** backends (v1) — their model
maps drive dispatch only, never any arbiter/review panel seat.

**This is the "skill picks the models and offers you the options" surface.** Do the
discovery, *show* what you found, then let the user choose. Never silently pick a
model the user did not confirm. **NEVER assign `haiku` to any tier on any backend.**

---

## Step 0 — Load the current map

Read `.claude/compound-v.json` if it exists. Remember its current `models` block
(seeded by [`/v:init`](v-init.md)) so you can show the user what is changing and
preserve any backend they don't refresh this run. The `models` block is **per-stance**
— shape `{<stance>: {<backend>: {<tier>: model}}}`. If the file or its `models` key
is absent, fall back to the built-in default (the resolver carries the same one). Only
the `claude` rows differ across stances — `cost-aware.claude.standard` is `sonnet`,
everywhere else `standard` Claude is `opus`:

```jsonc
"models": {
  "balanced": {
    "claude":      { "deep": "opus",                  "standard": "opus",                  "light": "sonnet" },
    "codex":       { "deep": "gpt-5.6-sol",            "standard": "gpt-5.6-terra",          "light": "gpt-5.6-luna" },
    "antigravity": { "deep": "Gemini 3.1 Pro (High)", "standard": "Gemini 3.1 Pro (Low)", "light": "Gemini 3.5 Flash (Low)" },
    "cursor":      { "deep": "auto",                  "standard": "auto",                  "light": "auto" }
  },
  "cost-aware": {
    "claude":      { "deep": "opus",                  "standard": "sonnet",                "light": "sonnet" },
    "codex":       { "deep": "gpt-5.6-sol",            "standard": "gpt-5.6-terra",          "light": "gpt-5.6-luna" },
    "antigravity": { "deep": "Gemini 3.1 Pro (High)", "standard": "Gemini 3.1 Pro (Low)", "light": "Gemini 3.5 Flash (Low)" },
    "cursor":      { "deep": "auto",                  "standard": "auto",                  "light": "auto" }
  }
  // conservative + claude-only mirror balanced
}
```

`/v:models` writes this **per-stance** shape; the resolver still accepts the **legacy
flat shape** `{<backend>: {<tier>: model}}` (applied to every stance) for backward-compat.
If `{{args}}` named one backend, only discover + reassign that backend (across every
stance's block) and leave the other backends exactly as they are.

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

- `gpt-5.6-sol` — strongest; suggested for `deep` (requires codex-cli >= 0.143.0)
- `gpt-5.6-terra` — balanced; suggested for `standard`
- `gpt-5.6-luna` — fast/cheap; suggested for `light`

Confirm codex is even usable first (so you don't write a map the project can't run):

```bash
command -v codex && codex exec --help 2>/dev/null | grep -q -- '--model' && echo "codex usable" || echo "codex unavailable"
```

If codex is unavailable, say so, keep the existing codex block unchanged, and skip
its reassignment (the map can still carry codex entries for when it returns).

### 1c. antigravity — headless `agy models` discovery (real names)

Antigravity (Gemini family) **does** have a discovery command, and it runs
**headlessly** — `agy models` just waits on stdin, so redirect `</dev/null` (the same
fix used for `agy --print`) and it returns the catalog in ~2s without a TTY. Pipe that
catalog through [`scripts/compound-v-discover-models.py`](../scripts/compound-v-discover-models.py)
(pure parse + rank — the CALLER fetches the catalog; the script never calls a backend)
to get a real `proposed` deep/standard/light map plus the full `available` list:

```bash
command -v agy >/dev/null \
  && agy models </dev/null | python3 scripts/compound-v-discover-models.py --backend antigravity \
  || echo "agy unavailable"
```

- This prints JSON `{available:[...], proposed:{deep,standard,light}, note, backend}`.
  **Show the user the `available` catalog and the `proposed` map**, then let them
  confirm or override (Step 2). The proposal is real, current model names — no more
  placeholders. Against the live catalog (agy 1.0.13: Gemini 3.5 Flash Low/Medium/High,
  Gemini 3.1 Pro Low/High, Claude Opus/Sonnet 4.6 Thinking, GPT-OSS 120B Medium) the
  proposal is **deep: `Gemini 3.1 Pro (High)`, standard: `Gemini 3.1 Pro (Low)`,
  light: `Gemini 3.5 Flash (Low)`**.
- To write the confirmed proposal straight into the config, use the `--write-config`
  form (it merges into `models.antigravity`, preserving the other backends):

  ```bash
  agy models </dev/null | python3 scripts/compound-v-discover-models.py \
    --backend antigravity --write-config .claude/compound-v.json
  ```

- If `agy` is **absent**, say so plainly and keep the resolver's built-in fallback map
  (the antigravity block from Step 0); note it can be refreshed once `agy` is installed.
  The script never invents names — it only ranks the catalog `agy models` actually
  printed, so anything you show came from the live CLI.

### 1d. cursor — Auto by default (manual list command; plan-gated)

cursor-agent (2026.06.26+) has a `models` list command (`cursor-agent models`) for **manual**
discovery — a paid-plan user can run it to see the live, real catalog and pick a named override.
Compound V does not auto-rank/auto-discover it (unlike antigravity's single-family Gemini
catalog): cursor's catalog spans many unrelated vendor families (GPT/Claude/Gemini/…) with no
shared naming/effort convention, so ranking it well would need its own bespoke logic — curated +
user-overridable stays the flow. Named models are also **plan-gated**: a Cursor **Free** plan can
only use **`auto`** (passing a named model errors with *"Named models unavailable"* — verified
live). So the default map is `auto` for every tier:

```bash
command -v cursor-agent && cursor-agent status </dev/null >/dev/null 2>&1 && echo "cursor usable (auth ok)" || echo "cursor unavailable/unauthed"
```

- **Free plan (or unsure):** keep `{deep,standard,light} = "auto"`. Tiering is a no-op (Auto
  picks the model) — that is expected, not a bug.
- **Paid plan:** the user may assign named ids per tier (e.g. `sonnet-4`, `gpt-5`,
  `sonnet-4-thinking`) — a curated roster like codex (no discovery; whatever the plan accepts
  via `cursor-agent --model` is valid). Only offer named models if the user confirms a paid plan.

### 1e. devin — curated list, no discovery command (mirrors codex's pattern)

Devin has **no `devin models` / `--list-models` subcommand** — like codex, discovery is
only via the interactive `/model` picker inside a session, so the map is a small
**curated** roster the user can override by hand (devin accepts whatever string you pass
to `--model`). Present this curated starting roster (DOC-CLAIMED aliases — devin-cli
3000.1.27's own `--help` uses these exact strings as its examples, but no authenticated
run has confirmed they resolve):

- `claude-opus-4.6` — strongest; suggested for `deep`
- `claude-sonnet-4` — balanced; suggested for `standard`
- `gpt-5.5` — fast/cheap; suggested for `light`

Confirm devin is even usable first:

```bash
command -v devin && devin auth status </dev/null 2>&1 | grep -q 'Not logged in' \
  && echo "devin present, unauthenticated" || echo "devin usable (or absent)"
```

If devin is unavailable/unauthenticated, say so, keep the existing devin block
unchanged, and skip its reassignment. **Devin is model-agnostic** (`--model` spans
Claude/GPT/Gemini/Devin's own SWE family) — remind the user that whichever family they
pick here determines Devin's error-correlation with the rest of the panel, which is
exactly why it stays **worker-only, never an arbiter seat**, in this plugin.

### 1f. opencode — real discovery command, but curated + user-confirmed assignment

opencode **does** have a real, live discovery command that works even with **zero**
stored credentials (it falls back to a credential-free `opencode/*` catalog via
models.dev):

```bash
command -v opencode >/dev/null && opencode models </dev/null 2>&1 || echo "opencode unavailable"
```

Unlike antigravity's single-family Gemini catalog, opencode spans **multiple unrelated
providers with no shared naming convention** — so, like cursor, Compound V does **not**
auto-rank it. Show the user the live `opencode models` output, then let them assign each
tier. The one genuinely novel option here: `light` MAY legitimately point at one of the
**credential-free** `opencode/*` models (e.g. `opencode/mimo-v2.5-free`) — a real free
tier no other backend offers. Every cell **MUST** be a full `provider/model` string (the
resolver's selftest asserts every `opencode` tier cell contains `/`); a bare model name
will likely fail opencode's own model resolution even though `--model` accepts the
string syntactically. The built-in fallback map (curated, user-overridable):

- `deep` → `anthropic/claude-opus-4-6`
- `standard` → `openai/gpt-5.6-terra`
- `light` → `opencode/mimo-v2.5-free`

If opencode is unavailable/unauthenticated, say so and keep the existing opencode block
unchanged. **opencode is model-agnostic per-cell** (each tier may use a different
provider) — remind the user this is exactly why it stays **worker-only, never an
arbiter seat**: an opencode ballot's family is determined entirely by which
`provider/model` was resolved, not by the backend name.

---

## Step 2 — Show findings and let the user assign tiers

For each backend in scope, present a compact table: discovered/available models on
one side, the three tiers on the other, and your **suggested** assignment (the
sensible-default pairing: strongest model → `deep`, a mid option → `standard`, the
fast/cheap option → `light`). Example shape:

| Backend | Available now | deep | standard | light |
|---|---|---|---|---|
| claude | opus, sonnet | opus | opus | sonnet |
| codex | gpt-5.6-sol, gpt-5.6-terra, gpt-5.6-luna | gpt-5.6-sol | gpt-5.6-terra | gpt-5.6-luna |
| antigravity | *(from `agy models </dev/null`)* | Gemini 3.1 Pro (High) | Gemini 3.1 Pro (Low) | Gemini 3.5 Flash (Low) |
| devin | *(curated: claude-opus-4.6, claude-sonnet-4, gpt-5.5)* | claude-opus-4.6 | claude-sonnet-4 | gpt-5.5 |
| opencode | *(from `opencode models </dev/null`)* | anthropic/claude-opus-4-6 | openai/gpt-5.6-terra | opencode/mimo-v2.5-free |

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
other key** in the file (`stance`, `memory`, `epic`, `review`, `workflows_accelerator`,
…) and any backend block you did not refresh this run. Create the file (and parent
dir) if absent, seeding the non-`models` keys from `/v:init` conventions if they
aren't there yet. **Never write `backends` or `checked_at`** — machine-local
capability lives in `~/.claude/compound-v-capabilities.json`, not in this committed
file (v2.6.2). If an older file already has those two keys (pre-2.6.2), leave them
untouched — they're inert, no migration needed.

Resulting shape (only `models` is this command's responsibility) — write the
**per-stance** shape, refreshing each backend's row inside every stance block (only
`cost-aware.claude.standard` differs: `sonnet`, not `opus`):

```jsonc
{
  "stance": "…",            // preserved
  "models": {
    "balanced": {
      "claude":      { "deep": "opus",    "standard": "opus",    "light": "sonnet" },
      "codex":       { "deep": "gpt-5.6-sol", "standard": "gpt-5.6-terra", "light": "gpt-5.6-luna" },
      "antigravity": { "deep": "…",       "standard": "…",       "light": "…" },
      "cursor":      { "deep": "auto",    "standard": "auto",    "light": "auto" },
      "devin":       { "deep": "claude-opus-4.6", "standard": "claude-sonnet-4", "light": "gpt-5.5" },
      "opencode":    { "deep": "anthropic/claude-opus-4-6", "standard": "openai/gpt-5.6-terra", "light": "opencode/mimo-v2.5-free" }
    },
    "cost-aware": {
      "claude":      { "deep": "opus",    "standard": "sonnet",  "light": "sonnet" },
      "codex":       { "deep": "gpt-5.6-sol", "standard": "gpt-5.6-terra", "light": "gpt-5.6-luna" },
      "antigravity": { "deep": "…",       "standard": "…",       "light": "…" },
      "cursor":      { "deep": "auto",    "standard": "auto",    "light": "auto" },
      "devin":       { "deep": "claude-opus-4.6", "standard": "claude-sonnet-4", "light": "gpt-5.5" },
      "opencode":    { "deep": "anthropic/claude-opus-4-6", "standard": "openai/gpt-5.6-terra", "light": "opencode/mimo-v2.5-free" }
    }
    // conservative + claude-only mirror balanced
  }
}
```

The resolver still accepts the **legacy flat shape** `{<backend>: {<tier>: model}}`
(applied to every stance) for backward-compat, so an older flat config keeps working;
new writes use the per-stance shape above.

The `models` map is **project-local config** — written into the project, not
committed in the plugin repo (it is documented in
[`execution-manifest.md`](../skills/compound-v/execution-manifest.md), seeded by
`/v:init`, refreshed here).

---

## Step 4 — Verify the map resolves

Before declaring success, confirm the resolver agrees with the new map — this is the
loop that proves routing will actually use what you wrote. Pass `--stance` so the
resolver reads the per-stance block you wrote (omitting it defaults to `balanced`):

```bash
for s in balanced cost-aware; do
  for b in claude codex antigravity cursor devin opencode; do
    for t in deep standard light; do
      python3 scripts/compound-v-resolve-model.py --backend "$b" --tier "$t" \
        --stance "$s" --config .claude/compound-v.json
    done
  done
done
```

Each line should be a JSON object whose `model` matches the cell you just assigned for
that stance (the resolver's per-stance `--config models.<stance>.<backend>.<tier>`
override beats its built-in default; under a legacy flat config the `--stance` is
ignored and the same map applies to every stance). In particular,
`--backend claude --tier standard --stance cost-aware` must resolve to `sonnet`, while
`--stance balanced` (or omitted) resolves to `opus`. A non-zero exit or a mismatched
model means the write didn't take — fix the JSON and re-run. (Skip the `codex` rows if
codex is unavailable on this machine; the map entries are still valid for when it
returns.)

---

## Step 5 — Report

Summarize per backend: what discovery returned (the real catalog from
`agy models </dev/null` for antigravity, or that the backend was unavailable), the
final `deep`/`standard`/`light` assignment, and the path written
(`.claude/compound-v.json`). Note that the dispatcher now resolves these via
[`scripts/compound-v-resolve-model.py`](../scripts/compound-v-resolve-model.py) and
that `effort` (`low`/`medium`/`high`/`xhigh`) is an **orthogonal** dimension chosen
per task-type in [`routing-policy.md`](../skills/compound-v/routing-policy.md), not
set here. `xhigh` is valid **iff** `backend: codex`; every other backend rejects it
with a clear error naming the rule (use `high` instead).

**Honesty rules:** report only what discovery actually returned. `agy models </dev/null`
and `opencode models </dev/null` both run headlessly and return live catalogs, so
report the discovered models as discovered. Only if the CLI is **absent** do we fall
back to the built-in map — say so plainly when that happens, rather than passing the
fallback off as discovered. devin has no discovery command at all — its roster is
always curated, say so. Never print token or cost numbers (anti-ruflo). Never assign
`haiku`. Always remind the user that `devin` and `opencode` are worker-only backends —
whatever they assign here never seats either on an arbiter/review panel.
