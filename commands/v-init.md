---
description: Initialize Compound V in this project — detect backends and capabilities (Codex, Context7, required skills/agents), walk through any missing installs one at a time, pick a routing stance, and save project + user config.
disable-model-invocation: true
---

You are running **`/v:init`** — the Compound V capability + stance setup for this
project. Argument (optional): `{{args}}` may name a stance to pre-select
(`balanced` | `conservative` | `cost-aware` | `claude-only`); otherwise you recommend one.

**This walkthrough IS the configurator.** There is no separate shipped playground or
runtime UI — the stance is set here and in [`routing-policy.md`](../skills/compound-v/routing-policy.md).
A standalone HTML configurator, if it exists, is only an optional dev tool, never a
shipped surface. Do not claim otherwise.

Run the steps **in order**. Do not batch installs — detect everything first, then walk
the user through missing pieces **one at a time**, confirming after each.

---

## Step 1 — Detect capabilities

Probe each, and remember the result. Do **not** install anything yet.

### 1a. Codex CLI (and verify the EXEC flag surface)

```bash
command -v codex
```

If absent → Codex is **not available** (record it; routing will be Claude-only).

If present, **verify the flags Compound V depends on live in the `codex exec`
subcommand help — not merely in the merged top-level help.** This is the check that
caught the real adapter bug (PRD §3): `--ask-for-approval` appears in `codex --help`
but is **absent from `codex exec --help`**, because it is a top-level/interactive flag.
Asserting against the wrong help would have shipped an adapter that fails on every job.

```bash
# Assert the worker flags are in the EXEC subcommand help specifically:
codex exec --help 2>/dev/null | grep -q -- '--cd'                  || echo "MISSING --cd in exec help"
codex exec --help 2>/dev/null | grep -q -- '--sandbox'             || echo "MISSING --sandbox in exec help"
codex exec --help 2>/dev/null | grep -q -- '--skip-git-repo-check' || echo "MISSING --skip-git-repo-check in exec help"
codex exec --help 2>/dev/null | grep -q -- '--model'              || echo "MISSING --model in exec help"
codex exec --help 2>/dev/null | grep -q -- '--output-last-message' || echo "MISSING --output-last-message in exec help"
# And confirm the bug-marker flag is NOT in exec help (it must be top-level only):
if codex exec --help 2>/dev/null | grep -q -- '--ask-for-approval'; then
  echo "WARN: --ask-for-approval appears in exec help on this codex version — re-check the adapter"
fi
```

- All required flags present in **exec** help, and `--ask-for-approval` absent there →
  Codex is **usable**; the pinned adapter flag set holds for this version.
- Any required flag missing from exec help → record Codex as **present but
  version-incompatible**; treat as Claude-only and warn the user to update Codex.
- `--output-schema` is optional (drives only the human summary) — note it if present,
  but do not gate on it.

Resume form for reference (no `--session-id` flag exists): `codex exec resume <uuid>`.

### 1a-bis. Antigravity CLI (`agy`) — optional, lower-trust backend

```bash
command -v agy
```

If absent → Antigravity is **not available** (record it; routing never offers it).

If present → Antigravity is **usable** (the pinned `agy 1.0.13` invocation holds:
`cd "$WT" && agy --dangerously-skip-permissions --add-dir "$WT" --print-timeout "<sec>s" [--model …] --print "<prompt>"`).
Record antigravity as available and add it to `backends`.

`agy models` is **headless-friendly** — it just waits on stdin, so redirect `</dev/null`
(the same fix used for `agy --print`) and it returns the catalog in ~2s, no TTY needed.
Seed a **real** antigravity model map at init by piping that catalog through the
discovery script (only when `agy` is present), which merges a real deep/standard/light
proposal into `.claude/compound-v.json`:

```bash
agy models </dev/null | python3 scripts/compound-v-discover-models.py \
  --backend antigravity --write-config .claude/compound-v.json
```

This is a **seed** — refreshable any time via [`/v:models`](v-models.md). If `agy` is
absent, skip it and let Step 4a write the resolver's built-in fallback map.

> **Flag it as lower-trust when you record it.** `agy` has **no kernel write-confinement**
> like Codex's `--sandbox workspace-write`, and headless writes require
> `--dangerously-skip-permissions` (arbitrary shell + out-of-worktree writes possible).
> The worktree + `git diff` gate detects in-worktree scope leaks but cannot *prevent* an
> out-of-worktree side-effect — so it is **opt-in**, and **Codex is preferred for
> untrusted / high-stakes work**. See [`adapter-antigravity.md`](../skills/backend-launcher/adapter-antigravity.md).

### 1a-ter. Cursor CLI (`cursor-agent`) — optional, lower-trust backend

```bash
command -v cursor-agent
```

If absent → Cursor is **not available** (record it; routing never offers it).

If present → check **authentication** (the headless worker needs a logged-in session or
`CURSOR_API_KEY`):

```bash
cursor-agent status </dev/null 2>&1 | head -3   # or: [ -n "$CURSOR_API_KEY" ]
```

- Installed **and** authenticated → Cursor is **usable**; record it and add it to `backends`.
  The pinned headless invocation holds (verified, cursor-agent 2025.09.12):
  `cd "$WT" && cursor-agent -p -f --output-format json [--model <M>] "<prompt>" </dev/null`
  (`.result` → summary, `.session_id` → resume). Default model is **`auto`** — VERIFIED that a
  Cursor **Free** plan can *only* use Auto (named models like `sonnet-4` error). On a **paid**
  plan, set named per-tier ids via [`/v:models`](v-models.md) / config (no `models` list
  command, so no auto-discovery). Note the plan when you record it.
- Installed but **not** authenticated → record it as **present but unauthenticated**; treat as
  unavailable and tell the user to run `cursor-agent login` (or set `CURSOR_API_KEY`).

> **Flag it as lower-trust when you record it.** cursor-agent has **no kernel write-confinement**
> like Codex's `--sandbox workspace-write`, and a headless run **requires `-f`** (an untrusted
> dir is otherwise refused), which also grants arbitrary shell + out-of-worktree writes. The
> worktree + `git diff` gate detects in-worktree scope leaks but cannot *prevent* an
> out-of-worktree side-effect — so it is **opt-in (same tier as Antigravity)**, and **Codex is
> preferred for untrusted / high-stakes work**. See
> [`adapter-cursor.md`](../skills/backend-launcher/adapter-cursor.md).

### 1b. Context7 MCP (match by namespace)

Context7 is **plugin-namespaced** — match the namespace, not a bare `context7`:

```bash
claude mcp list 2>/dev/null | grep -E 'plugin[:_]context7[:_]context7'
```

A match (`plugin:context7:context7` / `plugin_context7_context7`) → Context7 is
available (forced-on per [`skill-escalation.md`](../skills/compound-v/skill-escalation.md)).
No match → record it as missing (install in Step 2).

### 1c. Required skills & agents

Confirm the Compound V surface is present in this install:

- Agents: `compound-v:parallel-dispatcher`, `compound-v:partition-reviewer`,
  `compound-v:spec-reviewer`, and the three pre-flight agents.
- Skills: `compound-v` (this skill pack) and `backend-launcher`.

If any are missing, the plugin is not fully installed — tell the user to reinstall the
`superpowers-v` plugin before proceeding.

### 1d. Dynamic Workflows (optional accelerator)

Note whether Dynamic Workflows look available (they are not exposed in a plain subagent
shell). This only decides whether to *offer* the opt-in
[`workflows-accelerator.md`](../skills/compound-v/workflows-accelerator.md) in Step 3 —
it is never required and defaults OFF.

### 1e. Wall-clock cap for external workers

No probe needed: all three external workers (Codex, Antigravity, Cursor) run under the bundled
**process-group timeout supervisor** ([`scripts/compound-v-run-with-timeout.py`](../scripts/compound-v-run-with-timeout.py)) —
pure Python stdlib, **no `timeout`/`gtimeout` binary required**. On a job timeout it `killpg`s the
whole backend process tree (not just the direct child) and reports `status: timeout`. Nothing to
configure; just confirm `python3` is present (the workers already require it).

---

## Step 2 — Walk through missing installs, ONE AT A TIME

For each missing capability, guide the user through a single install, **confirm it
worked, then move to the next.** Never chain installs.

- **Codex CLI missing** (and the user wants the Codex backend):
  `npm i -g @openai/codex` (or `brew install codex`). After they confirm, re-run the
  Step 1a probe (including the exec-help flag assertion) before counting it usable.
- **Context7 MCP missing:**
  `/plugin install context7@claude-plugins-official` (or the marketplace path in use).
  After they confirm, re-run the Step 1b namespace grep.
- **Plugin surface incomplete:** direct them to reinstall `superpowers-v`; stop and
  resume `/v:init` once it is whole.

After each install, **re-probe that one capability** and report the new state before
touching the next. Codex is **optional** — if the user declines it, proceed Claude-only.

---

## Step 3 — Pick the routing stance

Stances are defined in [`routing-policy.md`](../skills/compound-v/routing-policy.md).

1. If `{{args}}` named a valid stance, pre-select it; else **recommend**:
   - **Codex usable** → recommend **Balanced** (the shipped default).
   - **Codex absent or version-incompatible** → **Claude-only** (the env-aware
     fallback; Codex rows collapse to `claude · opus`, worktree).
2. Offer the alternatives explicitly: **Conservative** (Opus-heavy, no Codex) and
   **Cost-aware** (more Sonnet/Codex). Let the user override the recommendation.
3. If Dynamic Workflows were detected in 1d, **offer** the opt-in Workflows accelerator
   (default OFF). Only set it on if the user explicitly says yes.

Confirm the chosen stance back to the user before saving.

---

## Step 3b — V-memory recall lane (semantic embeddings: opt-in)

V-memory (recall over `docs/superpowers/**` prose — see [`memory.md`](../skills/compound-v/memory.md))
**always** runs its **FTS5 core** (pure stdlib, offline, zero setup). Ask the user — **as a
structured choice (use the AskUserQuestion tool on Claude Code; a plain two-option question on
other harnesses)** — which recall lane this project should use:

- **"FTS5 only — fast, zero-setup"** — lexical BM25 over the prose; no install, no model,
  fully offline. **Recommend this** while `docs/superpowers/` is small or young — lexical
  search already wins there.
- **"Semantic embeddings — ~200 MB model, once"** — adds a dense lane that also finds related
  prior work when the wording differs (including **across languages**); downloads a small
  multilingual model one time into an out-of-repo cache.

**If the user picks semantic**, bootstrap it now — this is the **one consented install step**
(never done from a hook):
  ```bash
  python3 scripts/compound-v-memory.py bootstrap
  python3 scripts/compound-v-memory.py refresh --with-embeddings
  ```
  Confirm the `bootstrap OK` line before counting it enabled. If bootstrap fails (offline /
  no wheels), say so and fall back to FTS5-only — recall still works.

Record the lane choice in Step 4a as `memory.embeddings: true|false`. When `true`, the engine
adds vectors on every refresh (including the silent background hook) — but still **only once
bootstrapped**; it never installs on its own.

**Then ask a second structured choice — how much V-memory should DRIVE the pipeline:**

- **"Manual only"** — recall fires only when you run `/v:remember`. (`memory.auto_recall: false`)
- **"Auto-recall" (recommend)** — memory auto-surfaces related prior work during planning and
  before the review gate, as **advisory evidence**. (`auto_recall: true`, `auto_tighten: false`)
- **"Auto-tighten"** — additionally, the deterministic `recall-check` bridge **auto-tightens**
  the next run (force worktree / +review pass / fold into Task 0) when the same files have
  repeatedly failed. Conservative-only — never reroutes to lower trust, never loosens.
  (`auto_recall: true`, `auto_tighten: true`)

---

## Step 3c — Autonomy & review defaults

Two more structured choices — sensible defaults, reconfigurable any time:

- **Epic autonomy — `epic.max_features`** (default **1**): how many features `/v:epic` builds
  before stopping at a human checkpoint. An epic is *N full v1.0 runs*, so this is the
  human-in-the-loop **cadence**, not a token meter. `1` checkpoints after every feature
  (safest); raise it for more autonomy per invocation.
- **Cross-model review — `review.cross_model`** (default **off**): run an automatic Codex
  second opinion ([`/v:review-plan`](v-review-plan.md)) on high-stakes plans before dispatch.
  Off = run it manually when you want it; on = decorrelated review by default, at the cost of
  one extra read-only Codex pass.

Confirm all choices back to the user before saving.

---

## Step 4 — Save config (two files)

Write **both**. Create parent dirs as needed.

### 4a. Project stance → `.claude/compound-v.json` (project-local; committed in YOUR project, never in the plugin repo)

```json
{
  "stance": "balanced",
  "backends": ["claude", "codex"],
  "checked_at": "<YYYY-MM-DD>",
  "memory": { "embeddings": false, "auto_recall": true, "auto_tighten": false },
  "epic":   { "max_features": 1 },
  "review": { "cross_model": false },
  "models": {
    "balanced": {
      "claude":      { "deep": "opus",                  "standard": "opus",                  "light": "sonnet" },
      "codex":       { "deep": "gpt-5.5",               "standard": "gpt-5.5",               "light": "gpt-5.3-codex-spark" },
      "antigravity": { "deep": "Gemini 3.1 Pro (High)", "standard": "Gemini 3.1 Pro (Low)", "light": "Gemini 3.5 Flash (Low)" },
      "cursor":      { "deep": "auto",                  "standard": "auto",                  "light": "auto" }
    },
    "cost-aware": {
      "claude":      { "deep": "opus",                  "standard": "sonnet",                "light": "sonnet" },
      "codex":       { "deep": "gpt-5.5",               "standard": "gpt-5.5",               "light": "gpt-5.3-codex-spark" },
      "antigravity": { "deep": "Gemini 3.1 Pro (High)", "standard": "Gemini 3.1 Pro (Low)", "light": "Gemini 3.5 Flash (Low)" },
      "cursor":      { "deep": "auto",                  "standard": "auto",                  "light": "auto" }
    }
  }
}
```

(`conservative` and `claude-only` mirror `balanced` — seed those two stance blocks
identically to `balanced`. Only `cost-aware.claude.standard` differs: `sonnet`, not
`opus`; `cost-aware.claude.deep` stays `opus`.)

- `stance` = the stance chosen in Step 3.
- `backends` = the usable set: always includes `"claude"`; add `"codex"` if Codex is
  usable, add `"antigravity"` if `agy` is installed (Step 1a-bis), add `"cursor"` if
  `cursor-agent` is installed **and authenticated** (Step 1a-ter). E.g. `["claude","codex"]`
  or `["claude","codex","antigravity","cursor"]`. Antigravity and Cursor are the lower-trust
  opt-in backends (no kernel sandbox); list each only when its CLI is present (Cursor also
  requires auth).
- `checked_at` = today's date.
- If the user opted into the Workflows accelerator, also include
  `"workflows_accelerator": true` (omit otherwise — default OFF).
- **`memory.embeddings`** = the Step 3b lane choice (default `false` = FTS5-only). When `true`,
  `compound-v-memory.py` adds the semantic lane on every refresh (the engine reads this flag),
  but only after an explicit `bootstrap` — it never installs on its own. `false` keeps the
  pure-stdlib FTS5 lane.
- **`memory.auto_recall` / `memory.auto_tighten`** = the Step 3b autonomy level. `auto_recall`
  (default `true`) makes the pipeline surface V-memory evidence in planning + at the review
  gate; `auto_tighten` (default `false`) additionally lets the deterministic `recall-check`
  bridge auto-tighten the next run on repeated structured failures (conservative-only). Both
  `false` = memory is a manual `/v:remember` lookup only.
- **`epic.max_features`** (default `1`) = the Step 3c epic-autonomy cadence `/v:epic` reads as
  its per-invocation budget before a human checkpoint.
- **`review.cross_model`** (default `false`) = the Step 3c toggle; when `true`, high-stakes
  plans get an automatic Codex second opinion ([`/v:review-plan`](v-review-plan.md)) before
  dispatch.
- **`models` — SEED the default per-stance tier→model map (exactly the block above)** so
  intent-based routing resolves out of the box even with no further setup. The map is
  **per-stance** — shape `{<stance>: {<backend>: {<tier>: model}}}`. Only the `claude`
  rows differ across stances: `cost-aware.claude.standard` is `sonnet` (Sonnet 5),
  everywhere else `standard` Claude is `opus`, and `cost-aware.claude.deep` stays `opus`;
  `codex`/`antigravity`/`cursor` are identical in every stance. This is the same default
  the resolver
  ([`scripts/compound-v-resolve-model.py`](../scripts/compound-v-resolve-model.py))
  carries built-in; writing it here makes the project config self-describing and
  user-editable. The resolver also **accepts the legacy flat shape**
  `{<backend>: {<tier>: model}}` (applied to every stance) for backward-compat — it
  auto-detects which shape it was handed — so an older flat config keeps working.
  NEVER `haiku` anywhere. If `agy` is present, the Step 1a-bis discovery
  pipe has already overwritten the `antigravity` block with **real** discovered names
  (`agy models </dev/null` → discovery script), so the block above is just the fallback
  used when `agy` is absent; codex has no list command (curated + user-overridable);
  claude uses native tier aliases. Tell the user they can refresh or customize this map any time
  with [`/v:models`](v-models.md) — they do **not** need to hand-edit JSON. The map
  is project-local config; it is documented but not committed in the plugin repo.

### 4b. User capability cache → `~/.claude/compound-v-capabilities.json` (uncommitted)

The user-level cache of what this machine can do, reused across repos:

```json
{
  "codex": { "available": true, "exec_flags_verified": true, "version": "<from `codex --version`>" },
  "antigravity": { "available": false, "trust": "lower (no kernel sandbox)", "version": "<from `agy --version`>" },
  "cursor": { "available": false, "authenticated": false, "trust": "lower (no kernel sandbox)", "version": "<from `cursor-agent --version`>" },
  "context7": { "available": true },
  "workflows": { "available": false },
  "checked_at": "<YYYY-MM-DD>"
}
```

- `codex.exec_flags_verified` reflects the Step 1a exec-help assertion (false if Codex
  is present but version-incompatible).
- `antigravity.available` reflects the Step 1a-bis `command -v agy` probe; record the
  `version` from `agy --version`. When present, Step 1a-bis also seeds a real model map
  via `agy models </dev/null` (headless — no TTY needed).
- Set each block from the actual probe results — never guess.

---

## Step 5 — Report

Summarize: detected backends, the saved stance, both config paths written, and any
capability still missing (with the exact next step). If Codex came back
version-incompatible, say so plainly and recommend updating it. Mention that the
default tier→model `models` map was seeded into `.claude/compound-v.json`, and that
[`/v:models`](v-models.md) refreshes or customizes it whenever a backend ships new
models.

- **Next:** run `/v:onboard` to build the project knowledge base (architecture docs + AGENTS.md bridge). This is a suggestion, not automatic.

**Honesty rules:** report only what the probes actually returned. Never print token or
cost numbers. Never claim a backend works that the probe did not confirm.
