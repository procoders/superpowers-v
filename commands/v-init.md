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

## Step 4 — Save config (two files)

Write **both**. Create parent dirs as needed.

### 4a. Project stance → `.claude/compound-v.json` (committed)

```json
{
  "stance": "balanced",
  "backends": ["claude", "codex"],
  "checked_at": "<YYYY-MM-DD>"
}
```

- `stance` = the stance chosen in Step 3.
- `backends` = `["claude","codex"]` if Codex is usable, else `["claude"]`.
- `checked_at` = today's date.
- If the user opted into the Workflows accelerator, also include
  `"workflows_accelerator": true` (omit otherwise — default OFF).

### 4b. User capability cache → `~/.claude/compound-v-capabilities.json` (uncommitted)

The user-level cache of what this machine can do, reused across repos:

```json
{
  "codex": { "available": true, "exec_flags_verified": true, "version": "<from `codex --version`>" },
  "context7": { "available": true },
  "workflows": { "available": false },
  "checked_at": "<YYYY-MM-DD>"
}
```

- `codex.exec_flags_verified` reflects the Step 1a exec-help assertion (false if Codex
  is present but version-incompatible).
- Set each block from the actual probe results — never guess.

---

## Step 5 — Report

Summarize: detected backends, the saved stance, both config paths written, and any
capability still missing (with the exact next step). If Codex came back
version-incompatible, say so plainly and recommend updating it.

**Honesty rules:** report only what the probes actually returned. Never print token or
cost numbers. Never claim a backend works that the probe did not confirm.
