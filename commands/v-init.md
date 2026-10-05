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

## Resolving the plugin root

The `scripts/` this command calls ship with the plugin — they are not files in your own
repository. Resolve the plugin root once per session before calling any of them:

```bash
CV="${CLAUDE_PLUGIN_ROOT:-$(ls -d "$HOME"/.claude/plugins/cache/*/superpowers-v/*/ 2>/dev/null | sort -V | tail -1)}"
CV="${CV:-$PWD}"; CV="${CV%/}"
```

`CLAUDE_PLUGIN_ROOT` is set for hooks but is not set in this Bash environment, so treat it as a
hint, never the whole answer — the fallback line covers an installed plugin cache or a checkout
of this repo.

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
agy models </dev/null | python3 "$CV/scripts/compound-v-discover-models.py" \
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
  The pinned headless invocation holds (verified, cursor-agent 2026.06.26):
  `cd "$WT" && cursor-agent -p -f --output-format json [--model <M>] "<prompt>" </dev/null`
  (`.result` → summary, `.session_id` → resume). Default model is **`auto`** — VERIFIED that a
  Cursor **Free** plan can *only* use Auto (named models like `sonnet-4` error). On a **paid**
  plan, run `cursor-agent models` to see the live catalog, then set named per-tier ids via
  [`/v:models`](v-models.md) / config (manual — Compound V doesn't auto-rank cursor's multi-vendor
  catalog). Note the plan when you record it.
- Installed but **not** authenticated → record it as **present but unauthenticated**; treat as
  unavailable and tell the user to run `cursor-agent login` (or set `CURSOR_API_KEY`).

> **Flag it as lower-trust when you record it.** cursor-agent has **no kernel write-confinement**
> like Codex's `--sandbox workspace-write`, and a headless run **requires `-f`** (an untrusted
> dir is otherwise refused), which also grants arbitrary shell + out-of-worktree writes. The
> worktree + `git diff` gate detects in-worktree scope leaks but cannot *prevent* an
> out-of-worktree side-effect — so it is **opt-in (same tier as Antigravity)**, and **Codex is
> preferred for untrusted / high-stakes work**. See
> [`adapter-cursor.md`](../skills/backend-launcher/adapter-cursor.md).

### 1a-quinquies. opencode CLI (`opencode`) — optional, lower-trust, WORKER-ONLY, multi-provider backend

```bash
command -v opencode || npx -y opencode-ai@latest --version   # confirms installable even if not on PATH
```

If absent → opencode is **not available** (record it; routing never offers it).

If present → check for at least one usable provider credential (auth-free command,
verified live):

```bash
opencode providers list </dev/null 2>&1 | grep -qv '0 credentials' \
  && echo "opencode has stored credentials" \
  || echo "opencode has NO stored credentials (may still work via ambient provider env vars)"
```

- Installed **and** (stored credentials via `opencode providers login`, **or** a known
  provider env var like `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`ANTHROPIC_BASE_URL` is
  explicitly set for this purpose) → opencode is **usable**; record it and add it to
  `backends`. **Load-bearing, live-observed finding:** opencode successfully authenticated
  with **zero** stored credentials purely from an inherited `ANTHROPIC_BASE_URL` — record
  `auth` as `ambient-env` vs `stored-credentials` so the operator knows which path is live
  on this machine, and see the adapter's env-scrub requirement below.
- Installed but no credentials and no relevant env var set → present but unauthenticated;
  tell the user to run `opencode providers login`.

> **Flag it as lower-trust, worker-only, AND multi-provider when you record it.** opencode
> has **no kernel write-confinement** at all (no `--sandbox` equivalent), and per its own
> docs defaults to **allowing all operations without explicit approval** — the opposite
> posture from Cursor/Antigravity, which refuse until explicitly unlocked. The worktree +
> `git diff` gate is the only real enforcement (detection, not prevention). **Prefer Codex
> for untrusted / high-stakes work.** opencode addresses models as `provider/model`
> strings (e.g. `anthropic/claude-opus-5-5`), so its resolved model family
> is data-dependent; it is **WORKER-ONLY for v1, excluded from any cross-model
> arbiter/review panel** until family-dedup keys on the resolved model. See
> [`adapter-opencode.md`](../skills/backend-launcher/adapter-opencode.md) for the
> **mandatory env-scrub** (the worker script must NOT blindly inherit the dispatcher's own
> provider env vars into the `opencode run` child process).

### 1b. Context7 MCP (match the NAME, not one install shape)

Context7 arrives under **two different names** depending on how it was installed, and
until 3.1.0 this step matched only one of them:

* plugin-bundled → `plugin:context7:context7`, tools `mcp__plugin_<plugin>_context7__*`
* user- or project-configured → `context7`, tools `mcp__context7__*`

The old matcher was `grep -E 'plugin[:_]context7[:_]context7'`, which finds nothing on a
machine running the second shape. Verified live on 2026-09-02: `claude mcp list` printed
`context7: https://mcp.context7.com/mcp (HTTP) - ✔ Connected` and a `resolve-library-id`
call returned real results, while the documented matcher reported Context7 **missing** and
would have told the user to install what they already had.

```bash
claude mcp list 2>/dev/null | grep -iE '(^|[:_ ])context7([:_ ]|$)'
```

A match under EITHER name → Context7 is available (forced-on per
[`skill-escalation.md`](../skills/compound-v/skill-escalation.md)). Record which name
matched, because the agents that use it must match the same shape by suffix
(`*context7*resolve-library-id`, `*context7*query-docs`) rather than by a hardcoded
string. No match → record it as missing (install in Step 2).

### 1c. Required skills & agents

Confirm the Compound V surface is present in this install:

- Agents: `superpowers-v:parallel-dispatcher`, `superpowers-v:partition-reviewer`,
  `superpowers-v:spec-reviewer`, and the three pre-flight agents.
- Skills: `compound-v` (this skill pack) and `backend-launcher`.

If any are missing, the plugin is not fully installed — tell the user to reinstall the
`superpowers-v` plugin before proceeding.

### 1d. Dynamic Workflows (capability probe)

Note whether Dynamic Workflows look available (they are not exposed in a plain subagent
shell). Record it in the capability cache (Step 4b). Engine C — the native Workflow
dispatch engine — is the default and needs no opt-in.

### 1d-bis. `deep-research` bundled skill (advisory presence probe)

Check whether `deep-research` appears in **your own available-skills listing** (the
skills the harness lists for this agent). This is a presence check ONLY:

- **NOT a version check** — there is no version floor to assert.
- **NOT a `Workflow({...})` call** — under the hood deep-research is a gate-able dynamic
  Workflow, and the `Workflow` tool may be absent in a plain subagent shell; the only
  contract is the skill/slash interface, i.e. its entry in the available-skills listing.

Record the result for Step 4b: present in the listing → `deep_research: true`; absent →
`false`. Either way it is an **advisory hint**: Trigger 0 (pre-brainstorm recon,
[`phase-0-recon.md`](../skills/compound-v/phase-0-recon.md)) re-checks the live listing
at fire time, because this flag can go stale — `disableBundledSkills` /
`CLAUDE_CODE_DISABLE_BUNDLED_SKILLS` can hide the skill after `/v:init` ran. Absence
never blocks recon; the engine ladder falls back to parallel WebSearch.

### 1e. Wall-clock cap for external workers

No probe needed: all three external workers (Codex, Antigravity, Cursor) run under the bundled
**process-group timeout supervisor** ([`scripts/compound-v-run-with-timeout.py`](../scripts/compound-v-run-with-timeout.py)) —
pure Python stdlib, **no `timeout`/`gtimeout` binary required**. On a job timeout it `killpg`s the
whole backend process tree (not just the direct child) and reports `status: timeout`. Nothing to
configure; just confirm `python3` is present (the workers already require it).

### 1f. Skill hygiene (native `/skill-doctor`)

**Version gate first.** `/skill-doctor` needs Claude Code **v2.1.261 or later** — the version the
official `CHANGELOG.md` names for the feature. (`skills.md` itself says 2.1.252; the two
Anthropic-owned sources disagree and this step cites the stricter one so the probe never fires on
a build that lacks the command.) Check with:

```bash
claude --version
```

Below 2.1.261 → skip this step (say so plainly — "skipped, below the 1f version floor" — rather
than attempting the command).

At or above the floor, run it headless, as text, with no stdin:

```bash
python3 "$CV/scripts/compound-v-run-with-timeout.py" --timeout 180 -- claude -p '/skill-doctor' --output-format text < /dev/null
```

**What to parse.** From the printed report, print in full the rows whose first column begins with
`superpowers-v:`. Other rows belong to other plugins or to skills the user or the project defined
directly — bundled and enterprise skills never appear in the report at all, per its own documented
exclusions.

**What to print.** For each `superpowers-v:` row: its context size, its 7-day token count, its use
count, and when it was last used. Then print one more line: the sum of the context column over
**every loaded skill in the report**, `superpowers-v:` and non-`superpowers-v:` alike — that total
is the whole-session context cost this project's rows sit inside, not just this plugin's share of
it.

**State these three limits plainly, every time this step runs:**
- The report reflects **this machine's session history**, not a property of the repo — a fresh
  machine or a cleared history reports zero uses for everything, and that is not evidence a skill
  is unused project-wide.
- A skill invoked only through a hook or a description-driven trigger (Trigger 0's recon, the
  Compound V phase-transition sidekick) never shows a `/skill-doctor` use count for that
  invocation — the report counts explicit skill invocations, not hook firings or description
  matches. A `0×` beside `v-dispatch` is not proof it went unused; it may have fired entirely
  through the sidekick's description trigger instead of a direct `/v:dispatch` call.
- `/skill-doctor` is unavailable over Remote Control (it replies that usage reports aren't
  available on that connection) and is unavailable whenever the session skips feature-flag
  fetching (e.g. `DISABLE_TELEMETRY`) — a session in either state reports nothing, which is not
  evidence any skill is unused.

**This step only ever reports.** It never disables a skill and never writes a file — turning a
skill off is the user's own call, made in the `/plugin` manager's Stats tab (interactive) or by
editing plugin config directly, never by this walkthrough.

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
Confirm the chosen stance back to the user before saving.

---

## Step 3b — V-memory recall lane (semantic embeddings: opt-in)

V-memory (recall over `docs/superpowers/**` prose — see [`memory.md`](../skills/compound-v/memory.md))
**always** runs its **FTS5 core** (pure stdlib, offline, zero setup) — nothing to do here for it:
the first `/v:remember` or `/v:memory-refresh` builds the index by itself, on the fly.

Ask the user — **as a structured choice (use the AskUserQuestion tool on Claude Code; a plain
two-option question on other harnesses)** — whether to also enable the semantic lane:

- **"FTS5 only — fast, zero-setup"** — lexical BM25 over the prose; no install, no model,
  fully offline. **Recommend this** while `docs/superpowers/` is small or young — lexical
  search already wins there.
- **"Semantic embeddings — one-time download, ~200 MB"** — adds a dense lane of vectors beside
  FTS5. Say what it measurably did on the plugin's own repo (2026-09-24, `tests/memory-queries.tsv`):
  one extra hit in 23 fused queries; **no** cross-lingual recall (a Russian question gets the same
  few Russian documents whatever it asks — `/v:remember` translates the question instead) and no
  help on paraphrases. Costs: one network download of the ONNX model plus an isolated venv
  (onnxruntime/tokenizers/numpy) living **outside the repo**; the first embed of that repo's
  6,050 chunks took **19 minutes**, and each dense search adds about a second and a half. Recommend
  FTS5 only unless the user wants to measure it on their own corpus (`bench`).

**Whichever the user picks, do all of the following, in order, before moving to Step 3c** — this
sequence is deliberately self-contained and idempotent (safe to re-run), because a session that
stops partway through must never leave embeddings bootstrapped with no config to show for it (a
live install hit exactly that: bootstrapped in June, no `.claude/compound-v.json` at all, so
`refresh` never added a single vector while `doctor` still called it "bootstrapped"):

1. **On "semantic embeddings":**
   - **Bootstrap** — the one consented install step (never done from a hook):
     ```bash
     python3 "$CV/scripts/compound-v-memory.py" bootstrap
     ```
     Confirm the `bootstrap OK` line before continuing. If it fails (offline / no wheels), tell
     the user, fall back to FTS5-only, and treat this as the "FTS5 only" branch below instead
     (write `embeddings: false`, not `true`) — recall still works either way.
   - **Write the choice right now** — read `.claude/compound-v.json` if it exists (else start
     from `{}`), merge in `"memory": { "embeddings": true }` (preserving every other top-level
     key and every other `memory.*` sub-key already present), and write the file back, creating
     `.claude/` if it doesn't exist yet. Do this **immediately after bootstrap succeeds**, not
     deferred to Step 4a's single end-of-flow write — this file is **committed project config**:
     it is how every teammate's own `refresh` (including their background hook) knows to add
     vectors once THEY bootstrap. Step 4a's later full-file write is a no-op on this one key —
     it writes back the same value.
   - **Populate vectors:**
     ```bash
     python3 "$CV/scripts/compound-v-memory.py" refresh --with-embeddings
     ```
   - **Show the real mode** — run `doctor` and show its mode line to the user, so they see the
     dense lane actually engaged (not just "bootstrapped"):
     ```bash
     python3 "$CV/scripts/compound-v-memory.py" doctor
     ```
2. **On "FTS5 only":**
   - **Write the choice right now, explicitly** — read-merge-write `.claude/compound-v.json`
     the same way, setting `"memory": { "embeddings": false }`. Do not leave the key absent: an
     absent key reads as "never asked," which is exactly what lets this question resurface on a
     later `/v:init`, and it is also what stops `doctor` from being able to say "disabled by
     choice" instead of "not bootstrapped."
   - **Run `doctor` too**, so the user sees the FTS5-only mode line before moving on:
     ```bash
     python3 "$CV/scripts/compound-v-memory.py" doctor
     ```

Step 4a's full-file write of `.claude/compound-v.json` later in this flow carries `memory.embeddings`
forward at whatever value was just written above — it never re-asks or overrides it.

**Then ask a second structured choice — how much V-memory should DRIVE the pipeline:**

- **"Manual only"** — recall fires only when you run `/v:remember`. (`memory.auto_recall: false`)
- **"Auto-recall" (recommend)** — memory auto-surfaces related prior work during planning and
  before the review gate, as **advisory evidence**. (`auto_recall: true`, `auto_tighten: false`)
- **"Auto-tighten"** — additionally, the deterministic `recall-check` bridge **auto-tightens**
  the next run when the same lane has repeatedly failed: at emit time the job's tier is raised
  one rung (`light → standard`, `standard → deep`; an explicit `model:` pin is never touched),
  and the review job's acceptance gains a re-check clause. Conservative-only — never reroutes to
  lower trust, never loosens. (`auto_recall: true`, `auto_tighten: true`)

---

## Step 3c — Autonomy & review defaults

Two more structured choices — sensible defaults, reconfigurable any time:

- **Epic autonomy — `epic.max_features`** (default **1**): how many features `/v:epic` builds
  before stopping at a human checkpoint. An epic is *N full v1.0 runs*, so this is the
  human-in-the-loop **cadence**, not a token meter. `1` checkpoints after every feature
  (safest); raise it for more autonomy per invocation.
- **Marathon autonomy — `epic.autonomy.stance`** (options `checkpoint` / `marathon`; default
  **`checkpoint`**): whether `/v:epic` stops at a human checkpoint after `max_features` (the
  bullet above — always the default), or opts into the **v2.10 marathon loop**
  ([`epic-mode.md`](../skills/compound-v/epic-mode.md) "Marathon stance") that chews the whole
  runnable feature DAG in one invocation, routing failures through a Codex+Claude arbiter panel
  and staying bounded by hard global circuit breakers. Offer `marathon` only with the **honest
  boundary** stated plainly: it survives *within one live `/v:epic` invocation* (a soft
  per-feature failure routes to the next runnable feature automatically) and is *human-resumable*
  after a hard death — quota, closed terminal, crashed machine — via a person re-invoking
  `/v:epic <epic-id>`, which is re-entrant. **There is no automatic resurrection while you're away
  unless the user starts one** (the next bullet). `marathon` also needs the **global
  breaker caps** agreed up front (sensible defaults, all tunable): `max_wall_clock_hours` (default
  **10**), `max_total_attempts` (default `max(6, 3×features)`), and `max_no_progress_cycles`
  (default **3** — a full pass with no new feature reaching `done` counts as one non-progressing
  cycle). These caps bound **counts and wall-clock hours only** — never a fabricated cost or token
  number. `checkpoint` remains the safe, unchanged default; only set `marathon` when the user
  explicitly wants unattended, multi-feature autonomy and accepts the boundary above.
- **Re-entry is native and needs no config (3.4.0).** There is no auto-resurrection toggle any more:
  `/v:epic` offers `/loop 30m /v:epic <epic-id>` (this session) or a `/schedule` routine (cloud,
  machine-off) at the start of every marathon invocation, and starts neither without the user's yes.
  Say the boundary once here: a `/loop` shares the session's fate and its interval mode is a
  `CronCreate` job that fires one final time after 7 days and is then deleted, so a marathon expected
  to outlive a week needs a re-arm or `/schedule`; `/schedule` is the genuine machine-off path and
  carries its own auth. Full design:
  [`epic-mode.md`](../skills/compound-v/epic-mode.md) "Goal and resurrection are native (3.4.0)".
- **Cross-model review — `review.cross_model`** (default **off**): run an automatic Codex
  second opinion ([`/v:review-plan`](v-review-plan.md)) on high-stakes plans before dispatch.
  Off = run it manually when you want it; on = decorrelated review by default, at the cost of
  one extra read-only Codex pass.

---

## Step 3d — Brainstorm defaults (recon + elicitation)

Two brainstorm-phase policy choices (committed team policy → the Step 4a `brainstorm` block):

- **Pre-brainstorm recon mode — `brainstorm.deep_research`** (options `ask` / `auto` /
  `off`; default **`ask`**, recommended): whether Trigger 0 may run a research pass
  before a brainstorm starts. Describe it with the honest cost/egress line — qualitative
  only, no token or cost numbers:
  > *"I can run a quick research pass before we brainstorm — either one deep-research
  > pass (usually several minutes, spawns subagents) or up to 6 parallel web searches
  > (usually under a couple of minutes).
  > Note: this sends the topic text to external search services."*
  This config value is **gate 3 of three** — consulted only after Trigger 0's first two
  gates pass (gate 1: plumbing-topic skip; gate 2: V-memory strong-hit skip — the
  authoritative order lives in
  [`phase-0-recon.md`](../skills/compound-v/phase-0-recon.md)). A plumbing topic or a
  strong local KB hit means no offer and no recon regardless of this setting.
  `ask` then makes that offer per brainstorm; `auto` runs it without asking (same bounds);
  `off` is a hard kill-switch — honored for cost AND confidentiality (some topics must
  never leave the machine). Invalid or unknown values fail **closed** (warn once → `ask`,
  never `auto`) — the verbatim rule is in Step 4a below.
- **Batched elicitation — `brainstorm.batch_elicitation`** (toggle, default **on**):
  allow ≥3 *independent* clarifying questions to batch into ONE screen via the surface
  ladder — Visual Companion form if accepted this session, else the harness's
  structured-question tool, else sequential; companion acceptance gates only the top
  surface, never batching itself (dependent chains always stay sequential — see
  [`brainstorm-elicitation.md`](../skills/compound-v/brainstorm-elicitation.md)).
  `false` keeps upstream's one-at-a-time questioning everywhere.

Confirm all choices back to the user before saving.

---

## Step 3e — Pre-Evaluation triage defaults (`pre_eval.*`)

The pre-eval stage is a **routing/triage** gate that may OFFER a proportionate fast-path on a
proven-trivial change. Its config surface is the Task 0 contract
[`pre-eval-config.md`](../docs/superpowers/architecture/pre-eval-config.md); `/v:init` seeds it into
`.claude/compound-v.json` (Step 4a). **Every default is fail-closed** — the SAFE, offer-only value,
never one that routes a change on its own — so a user who just presses Enter gets the safe
behaviour. Read/round-trip these ONLY through
the shared loader `compound-v-project-config.load_project_config(repo)` + `resolve_pre_eval(cfg)`
(never re-interpret the keys here). Offer two structured choices (defaults are safe; reconfigurable
any time):

- **Fast-path offer — `pre_eval.fast_path`** (options `ask` / `off`; default **`ask`**): whether the
  pre-eval stage may *offer* a fast-path when a change is provably trivial. `ask` folds the offer
  into the ONE recon/clarify interaction (never a standalone screen); it only ever OFFERS, and a
  fast-path is never taken without the human accepting it. `off` is a **hard kill-switch** — no
  offer, no fast-path, ever (honored for cost AND confidentiality). There is deliberately **no
  `auto` value** for this key; a malformed/unknown value is coerced back to `ask` (offer), never to
  anything that routes on its own.

  **Iron Invariant #4, as amended in v3.0**
  ([spec §A4](../docs/superpowers/specs/2026-09-01-v3.0-triage-tests-orchestration-design.md) —
  amended, not deleted): *the score OFFERS by default; it auto-routes only inside the DIRECT
  auto-route class, whose membership is decided by mechanically checkable predicates and never by
  model judgement, and every other tier still requires a human offer and acceptance.* That class is
  a property of the triage scorer and its repo-local impact taxonomy — **not** of this key: nothing
  written into `pre_eval.*` widens it, and no value of `fast_path` places a change inside it.
- **Remembered categories — `pre_eval.remember`** (default **`{}`** = ask every time): AC-11's
  explicit, revocable, one-time per-taxonomy-category opt-in — e.g. after accepting the fast-path for
  `css-only`, the developer MAY choose not to be re-asked for that category, recorded as
  `{ "css-only": "fastpath" }`. This is a human opt-in, **NOT a silent auto-route**: it suppresses
  **only the OFFER** for that category. Every fail-closed override — **sensitive path, shared-token,
  a11y, churn-hot, tier-disagreement, and the post-hoc diff escalation** — STILL fires on every
  request regardless of a remembered choice (the scorer re-checks them per spec §2). A remembered
  category can never encode "skip an override": the **only honored value is the literal
  `"fastpath"`** — `resolve_pre_eval` drops anything else and warns.

**On every `/v:init` run, DISPLAY the currently-remembered categories and offer to revoke** (AC-11
"displayable + revocable"): load the existing `.claude/compound-v.json` (if any) through the shared
loader and list each remembered `category → fastpath`. Let the user drop any or all of them, and
write the pruned map back in Step 4a. Revocation is also possible by hand-editing the config. When no
prior config exists, nothing is remembered (ask every time).

The remaining knobs (`enabled`, `min_sample_count`, `fan_out_threshold`, `token_cap`) keep their
fail-closed defaults from the contract unless the user has a specific reason to change one; do **not**
prompt for them by default — seed the defaults in Step 4a and point advanced users at
[`pre-eval-config.md`](../docs/superpowers/architecture/pre-eval-config.md).

Confirm the choices back to the user before saving.

---

## Step 4 — Save config (two files)

Write **both**. Create parent dirs as needed.

### 4a. Project stance → `.claude/compound-v.json` (project-local; committed in YOUR project, never in the plugin repo)

**Committed team POLICY only — never machine-local capability.** This file is shared across every
developer's checkout, so it must never claim something that's only true of the machine that ran
`/v:init` (e.g. "Codex is available" when a teammate's machine doesn't have it installed) — that
data already has a correct, uncommitted home: the Step 4b user-level capability cache below. Do not
add a `backends` or `checked_at` field here; they were removed in v2.6.2 for exactly this reason
(a real downstream repo review flagged the committed file as looking like machine-local state — it
was, in those two fields).

```json
{
  "stance": "balanced",
  "memory": { "embeddings": false, "auto_recall": true, "auto_tighten": false },
  "epic":   {
    "max_features": 1,
    "autonomy": {
      "stance": "checkpoint",
      "max_wall_clock_hours": 10,
      "max_no_progress_cycles": 3
    }
  },
  "review": { "cross_model": false },
  "enforcement": { "pipeline_bypass": false, "triage_gate": true },
  "brainstorm": {
    "deep_research": "ask",
    "batch_elicitation": true
  },
  "pre_eval": {
    "enabled": true,
    "fast_path": "ask",
    "min_sample_count": 5,
    "fan_out_threshold": 1,
    "token_cap": 20000,
    "remember": {}
  },
  "models": {
    "balanced": {
      "claude":      { "frontier": "fable", "deep": "opus",  "standard": "sonnet",                "light": "sonnet" },
      "codex":       { "frontier": "gpt-6-astra", "deep": "gpt-6.1-sol", "standard": "gpt-6.1-sol", "light": "gpt-6-luna" },
      "antigravity": { "deep": "Gemini 3.1 Pro (High)", "standard": "Gemini 3.1 Pro (Low)", "light": "Gemini 3.8 Flash (Low)" },
      "cursor":      { "deep": "auto",                  "standard": "auto",                  "light": "auto" },
      "opencode":    { "deep": "anthropic/claude-opus-5-5", "standard": "openai/gpt-6.1-sol", "light": "opencode/mimo-v2.5-free" }
    },
    "cost-aware": {
      "claude":      { "frontier": "opus",  "deep": "opus",  "standard": "sonnet",                "light": "sonnet" },
      "codex":       { "frontier": "gpt-6-astra", "deep": "gpt-6.1-sol", "standard": "gpt-6.1-sol", "light": "gpt-6-luna" },
      "antigravity": { "deep": "Gemini 3.1 Pro (High)", "standard": "Gemini 3.1 Pro (Low)", "light": "Gemini 3.8 Flash (Low)" },
      "cursor":      { "deep": "auto",                  "standard": "auto",                  "light": "auto" },
      "opencode":    { "deep": "anthropic/claude-opus-5-5", "standard": "openai/gpt-6.1-sol", "light": "opencode/mimo-v2.5-free" }
    }
  }
}
```

- `opencode` is a **worker-only** backend (v1): excluded from any cross-model
  arbiter/review panel until family-dedup keys on the *resolved* model rather than the
  backend name (it is a multi-provider router, so `backend: opencode`
  does not fix a single model family — see `adapter-opencode.md`).

(`conservative` and `claude-only` mirror `balanced` — seed those two stance blocks
identically to `balanced`. Only `cost-aware.claude.standard` differs: `sonnet`, not
`opus`; `cost-aware.claude.deep` stays `opus`.)

- `stance` = the stance chosen in Step 3.
- **`memory.embeddings`** = the Step 3b lane choice (default `false` = FTS5-only) — already
  written to disk by Step 3b itself the moment the user answered; this pass writes the same
  value back as part of the whole-file save, it does not decide it. When `true`,
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
- **`epic.autonomy.stance`** (default `"checkpoint"`) = the Step 3c marathon opt-in. `"checkpoint"`
  is the unchanged default (the bullet above governs it). `"marathon"` engages the v2.10
  autonomous loop in [`v-epic.md`](v-epic.md) ("Autonomous marathon loop") — but stance alone is
  advisory config: the driver always re-confirms it against the **persisted**
  `epic-state.json`'s own `autonomy.stance` before running any autonomous command (the state file
  is authoritative, not this config). `max_wall_clock_hours` (default `10`) and
  `max_no_progress_cycles` (default `3`) seed the marathon global breakers verbatim; leave
  `max_total_attempts` **unset** here — its documented default is derived from the epic's actual
  feature count at `--init` time (`max(6, 3×features)`), which this project-local file cannot know
  in advance. `max_attempts_per_feature` (per-feature retry cap, script default `2`) is likewise
  left to its script default unless a specific epic has a documented reason to raise it — set it
  per-epic at `--init`, not globally here.
- **There is no auto-resurrection key (3.4.0).** `/loop` and `/schedule` are offered per invocation
  by `/v:epic` §0c and are never persisted as policy; a config file written by an older release may
  still carry a `watch` key under `epic.autonomy`, and nothing reads it any more.
- **`review.cross_model`** (default `false`) = the Step 3c toggle; when `true`, high-stakes
  plans get an automatic Codex second opinion ([`/v:review-plan`](v-review-plan.md)) before
  dispatch.
- **`enforcement.*`** (every gate defaults **`false`** — OFF) = the blocking `Stop`-hook rules in
  [`hooks/epic-goal-stop.sh`](../hooks/epic-goal-stop.sh). This is a **map of named gates**, not a
  fixed pair: each reader owns exactly one key and reads it fail-closed-to-OFF
  (`jq -r '.enforcement.<key> // false'`), so a key that is absent, misspelled, malformed or unknown
  to this version is simply OFF and a future release adds a gate by adding a key — never by changing
  the shape. Seed the block above verbatim and leave keys you do not recognize untouched when
  re-running `/v:init` over an existing config. Shipped gates: **`pipeline_bypass`** (v2.18 — tracked
  source changed this session with no run record and no accepted fast-path record; corrects toward
  the pipeline or its sanctioned Pre-Evaluation shortcut) and **`triage_gate`** (v3.0 — non-exempt
  files changed with no committed triage record covering that diff).

  **`triage_gate` is ON by default as of 3.2.0; `pipeline_bypass` is still OFF.** The two are not
  symmetrical. `triage_gate` asks for the *first* step of the correction (`/v:triage`), it is exempt
  on `docs/superpowers/**`, and a project with no `.claude/compound-v.json` never sees it at all —
  so its population is exactly "a repo that deliberately initialised Compound V, once per session,
  with uncovered code changes". It shipped OFF on a blast-radius claim this project made about
  itself and never checked; a live probe on 2026-09-02 disproved the claim, and leaving the one
  mechanism that catches a skipped pipeline switched off was the mechanism-with-no-caller defect
  wearing a config key.

  **Opt out with `"triage_gate": false`** — an explicit boolean `false` (or the string `"false"`),
  which is the ONLY value that turns it off. Enabling `pipeline_bypass` is still a deliberate human
  edit. Both rules are **advisory and best-effort by construction**: each blocks at most once while its own temp-dir marker survives, and
  the runtime silently discards a `Stop` block when a turn ends via a tool result, an MCP end-turn or
  a loop tick. They raise the cost of skipping the pipeline; they cannot make skipping impossible, so
  do not describe them to the user as enforcement that cannot be bypassed. `hooks/epic-goal-stop.sh`
  carries only these two gates as of 3.4.0 — the epic-goal continuation rule it used to arm was
  removed, because `/v:epic` §0d now offers Claude Code's own native `/goal` instead.
- **`brainstorm.deep_research`** (default `"ask"`) / **`brainstorm.batch_elicitation`**
  (default `true`) = the Step 3d choices: the pre-brainstorm recon mode (`ask|auto|off`;
  `off` is a hard kill-switch) and the independent-question batching toggle. These are
  **policy** (committed), not capability — the machine-local `deep-research` presence flag
  lives in Step 4b, per the v2.6.2 split. Nothing validates this file, so the readers
  ([`phase-0-recon.md`](../skills/compound-v/phase-0-recon.md),
  [`brainstorm-elicitation.md`](../skills/compound-v/brainstorm-elicitation.md)) own the
  defaults and apply the shared fail-closed rule verbatim:
  Missing file or key → the documented defaults (`deep_research: "ask"`, `batch_elicitation: true`). Malformed JSON, wrong type, or unknown value → warn once, then use `deep_research=ask` and `batch_elicitation=false` for this session; never treat an invalid value as `auto`.
- **`pre_eval`** (defaults `enabled:true`, `fast_path:"ask"`, `min_sample_count:5`,
  `fan_out_threshold:1`, `token_cap:20000`, `remember:{}`) = the Step 3e Pre-Evaluation triage
  surface, per the Task 0 contract
  [`pre-eval-config.md`](../docs/superpowers/architecture/pre-eval-config.md). Seed the block above
  verbatim; every default is the fail-closed, offer-only value. `fast_path:"off"` is a **hard
  kill-switch**; `remember` holds AC-11's revocable per-category opt-ins (`{category: "fastpath"}`,
  only the literal `"fastpath"` honored). This is **committed team POLICY**, not machine capability.
  Unlike the resolver's `models` map, nothing hand-validates this file at read time on the hot path:
  the shared loader `scripts/compound-v-project-config.py` owns the fail-closed rules for every
  consumer — **structural** malformation (not JSON / root or `pre_eval` not an object) makes
  `load_project_config` raise so the caller warns once and falls back to all-defaults, while a
  **per-key** invalid value (`fast_path:"banana"`, negative `token_cap`, a `remember` value ≠
  `"fastpath"`) is coerced to its declared default by `resolve_pre_eval`, which returns a `warnings`
  list to surface once. An invalid value can only DEGRADE to the safe, offer-only default — it can
  **NEVER** be read as a request to route a change on its own, and it can never place one in the
  DIRECT auto-route class (Iron Invariant #4 as amended in v3.0, plus #5: membership in that class is
  decided by the scorer's mechanically checkable predicates against the repo-local impact taxonomy,
  never by a config value and never by model judgement). Do not re-implement these rules inline; call the loader.
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
  used when `agy` is absent; codex gets no equivalent live-discovery step here — this
  step just seeds the static GPT-6 default above (codex's own live discovery, via
  `codex debug models` since codex-cli 0.156.1, is `/v:models` §1b's job, run later or
  on demand); claude uses native tier aliases. Tell the user they can refresh or customize this map any time
  with [`/v:models`](v-models.md) — they do **not** need to hand-edit JSON. The map
  is project-local config; it is documented but not committed in the plugin repo.

### 4b. User capability cache → `~/.claude/compound-v-capabilities.json` (uncommitted)

The user-level cache of what this machine can do, reused across repos:

```json
{
  "codex": { "available": true, "exec_flags_verified": true, "version": "<from `codex --version`>" },
  "antigravity": { "available": false, "trust": "lower (no kernel sandbox)", "version": "<from `agy --version`>" },
  "cursor": { "available": false, "authenticated": false, "trust": "lower (no kernel sandbox)", "version": "<from `cursor-agent --version`>" },
  "opencode": {
    "available": false,
    "auth": "none",
    "trust": "lower (no kernel sandbox; docs claim default-allow permissions); worker-only, multi-provider",
    "version": "<from `opencode --version`>",
    "providers_configured": []
  },
  "context7": { "available": true },
  "workflows": { "available": false },
  "deep_research": true,
  "checked_at": "<YYYY-MM-DD>"
}
```

- `codex.exec_flags_verified` reflects the Step 1a exec-help assertion (false if Codex
  is present but version-incompatible).
- `antigravity.available` reflects the Step 1a-bis `command -v agy` probe; record the
  `version` from `agy --version`. When present, Step 1a-bis also seeds a real model map
  via `agy models </dev/null` (headless — no TTY needed).
- `opencode.available` reflects the Step 1a-quinquies `command -v opencode` probe;
  `opencode.auth` records **how** it is authenticating (`ambient-env` /
  `stored-credentials` / `none`) — this machine-local nuance matters more for opencode
  than any other backend, given the live-observed ambient-credential finding (see
  `adapter-opencode.md`).
- `opencode` is never added to any arbiter/review-panel capability block — it is
  **worker-only** in v1.
- `deep_research` reflects the Step 1d-bis presence probe (is `deep-research` in the
  available-skills listing?) — an **advisory hint only**: Trigger 0 re-checks the live
  listing at fire time, because the flag can go stale (`disableBundledSkills` /
  `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS` can hide the skill after init). A stale or absent
  flag is never treated as a hard "off."
- Set each block from the actual probe results — never guess.

### 4c. One optional environment offer — `CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT`

**Offer it; never write it.** Ask once, in plain terms, and only edit the file if the
user says yes:

> The harness picks between two built-in system prompts by this variable: `"1"`
> selects the SIMPLE (short) one, `"0"` turns it off and selects the long preset —
> the one that carries the anti-verbosity rules. Some users report that the long
> preset reinforces the concision Compound V's agents are already told to keep. If
> you want it, add `"CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT": "0"` to the `env` block of
> your own `~/.claude/settings.json`. Shall I show you the edit?

```jsonc
// ~/.claude/settings.json — the USER's file, not the project's, not the plugin's
{
  "env": {
    "CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT": "0"
  }
}
```

**Where this comes from, honestly.** The variable's name and its "0"/"1" semantics
are binary-verified — confirmed against the installed harness binary, not assumed
from the name. What is still a **community claim**, not something this project has
measured, is whether the long preset actually improves output: we have run **no**
before/after comparison of length, latency or cost with it set, and we publish no
number for it. It is offered because it is cheap to try and trivial to revert
(delete the key), and it is offered rather than written because it changes the
user's own global harness behaviour in every project, not just this one. If the
user asks whether it helps, the honest answer is "we do not know; try it and judge
the output yourself."

Record nothing about it in either config file: it lives in the user's settings, and a
copy of it in `.claude/compound-v.json` would be the machine-local-data-in-a-committed-file
mistake v2.6.2 already fixed.

### 4d. One optional project setting — `worktree.baseRef`

**Offer it; never write it without a yes.** `worktree.baseRef` is a **native Claude Code
project setting**, not a Compound V key, and it lives in a different file from Step 4a's
config: the project's own `.claude/settings.json`, not `.claude/compound-v.json`. It has
exactly two legal values, `"fresh"` (the default) and `"head"`, and it is **project-wide**
— it governs every worktree in the repo, including interactive `--worktree` sessions, not
only Compound V's own dispatch.

> A job that `depends_on` another needs its own worktree branched from the current `HEAD`,
> not the default ref — otherwise that worktree cannot see the prerequisite job's commit,
> and the dependent job's agent falls back to editing the shared main checkout directly
> instead of an isolated tree (`TROUBLESHOOTING.md`, "A job with `depends_on` runs in the
> shared checkout instead of its own worktree"). Set `worktree.baseRef` to `"head"` in
> `.claude/settings.json` to fix that. Shall I show you the edit?

```jsonc
// .claude/settings.json — the PROJECT's file, not the plugin's, not ~/.claude/settings.json.
// Merge only the "worktree" key in; every other key already in this file (permissions,
// hooks, env, ...) is preserved untouched. Create the file if it does not exist yet.
{
  "worktree": {
    "baseRef": "head"
  }
}
```

Read the file first if it exists, merge `worktree.baseRef` into the parsed object, and
write the merged result back — never truncate the file to just this one key.

### 4e. One optional project setting — `advisorModel`

**Offer it; never write it without a yes.** `advisorModel` is, like `worktree.baseRef`, a **native
Claude Code project setting** in the project's own `.claude/settings.json` — not a Compound V key,
and not `.claude/compound-v.json`. It names the model the built-in `advisor` tool consults, and
it has legal values `fable`, `opus`, `sonnet`, or a full model ID.

> Every job Compound V dispatches — and every review agent — can call the advisor tool at its own
> decision points: before committing to an approach, when stuck, before declaring done. A stronger
> model judging those moments catches what the acting model, mid-task, is the wrong vantage point
> to catch itself. Subagents inherit whatever `advisorModel` this project sets and apply the same
> pairing check against their own model. Shall I show you the edit?

```jsonc
// .claude/settings.json — the PROJECT's file, not the plugin's, not ~/.claude/settings.json.
// Merge only the "advisorModel" key in; every other key already in this file (worktree,
// permissions, hooks, env, ...) is preserved untouched. Create the file if it does not exist yet.
{
  "advisorModel": "fable"
}
```

**The `opus` alternative.** If the user would rather not opt into Fable, `"advisorModel": "opus"`
gets the same advisor-at-decision-points behavior from an Opus reviewer instead — offer it in the
same breath as the Fable default.

**The pairing rule.** An advisor must be at least as capable as the session's main model, or the
harness rejects the pairing. Concretely: a Fable main only accepts a same-or-newer Fable advisor
— a Fable 5.1 main accepts Fable 5.1 and rejects everything else, including Opus. Say this before
the user picks, since it means "set advisorModel to fable" and "the main model is Fable" are not
independent choices.

**The cost, honestly.** Every advisor call re-reads the entire conversation transcript from
scratch — nothing is cached, so a long-running job pays that re-read on every call, not just the
first. On plans where Fable usage bills to usage credits, Fable-as-advisor bills there too, after
the one-time `/model fable` consent step that both selects Fable as a model and unlocks it as an
advisor choice.

**Two ways it turns off**, worth naming so a later "why did advice stop happening" has an answer:
`DISABLE_TELEMETRY` (and anything else that skips feature-flag fetching) disables the advisor tool
entirely, same as it disables `/skill-doctor` in Step 1f; `CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1`
disables it outright regardless of `advisorModel` — the setting is then ignored, not an error.

Read the file first if it exists, merge `advisorModel` into the parsed object alongside whatever
is already there (including `worktree` from Step 4d), and write the merged result back — never
truncate the file to just this one key.

### 4f. Two optional native settings — `bashOutputMaxChars` / `taskOutputMaxChars`, and `bashEditDiffEnabled`

**Offer each; never write either without a yes.** Both are **native Claude Code settings**, not
Compound V keys, verified against `code.claude.com/docs/en/settings-reference` (and
`/docs/en/hooks#bash` for the third one) rather than assumed from a version number — the same
discipline Step 4e already applies to `advisorModel`. None of the three was exercised live when
this step was written (3.7.0), so treat every behavioral claim here as **documented, not
probed**, and re-verify once against your own project before trusting it at scale.

**`bashOutputMaxChars` / `taskOutputMaxChars` — why now.** A 3.6.0 wide dispatch found Engine C's
80-turn implementer cap is a real ceiling: a documentation job hit it three times reading a large
merged diff file-by-file, because Bash output past the default ~30,000-character inline window is
saved to a file and has to be re-read — each re-read is another turn spent on plumbing, not on the
task. Both settings raise that window; both are scope `Any file`, so the project's own
`.claude/settings.json` is a legal place for them, both require **Claude Code v2.1.261 or later**,
and Claude Code clamps either value into `4000`–`128000` regardless of what is asked for.

> Raising the inline ceiling costs nothing on a small command — a `git status` or a one-file
> diff still reads back exactly as many characters as it produces. The only downside is a rare
> huge command flooding context inside the 80-turn cap, which a large-but-bounded value avoids.
> Shall I show you the edit?

```jsonc
// .claude/settings.json — the PROJECT's file. Merge only these two keys in; every other key
// already present (worktree, advisorModel, permissions, hooks, env, ...) is preserved untouched.
{
  "bashOutputMaxChars": 100000,
  "taskOutputMaxChars": 100000
}
```

100000 is comfortably above the default (~30,000 for Bash, ~32,000 for background tasks) and
comfortably under the 128,000 ceiling, leaving headroom before the 80-turn cap without inviting a
single oversized command to dominate a job's whole context budget. `bashOutputMaxChars` then
supersedes the `BASH_MAX_OUTPUT_LENGTH` env var; `taskOutputMaxChars` supersedes
`TASK_MAX_OUTPUT_LENGTH` the same way.

**`taskOutputMaxChars`, honestly: it may already do nothing.** It governs what the `TaskOutput`
tool reads back from a finished background task — but Claude Code **2.1.277** (September 18,
2026) removed `TaskOutput` outright: "Claude reads a background task's output file with `Read`
instead, and the `taskOutputMaxChars` setting … no longer [has] any effect." This development
session's own `2.1.278` is past that floor. Offer it anyway for a project that may run on an
older pinned binary, but say plainly that on 2.1.277+ it is inert — `bashOutputMaxChars` is the
one that actually addresses the 80-turn-cap finding above; `taskOutputMaxChars` is offered only
for completeness on an older install.

**`bashEditDiffEnabled` — a different scope, and public beta.** Compound V's transcript-watch
(a parallel effort — see `scripts/compound-v-transcript-watch.py`) attributes in-flight Bash
writes to a job's lane; this setting is what makes a Bash-made edit carry a diff in the first
place, so the in-flight lane watch has something to read before the job finishes. Requires
**Claude Code v2.1.269 or later**, and the settings-reference marks it **public beta**: "The list
is best effort … The field shape may change." Unlike the two settings above, its scope is **User
or managed only** — the reference is explicit that "a `true` in a repository's
`.claude/settings.json` … can't turn the recording on" — so this one goes in the user's own
`~/.claude/settings.json`, the same file Step 4b already writes to, never the project file.

> With this on, every Bash-made file edit records a diff Claude Code can read back — in every
> permission mode, not only auto mode and `bypassPermissions`. Compound V's own in-flight lane
> watch is the reason to want it; it costs nothing to a session that never reads the field. It's
> a beta field, so the shape may still move. Shall I show you the edit?

```jsonc
// ~/.claude/settings.json — the USER's file, not the project's, and not .claude/settings.local.json
// (a project file cannot turn this on, only turn it off if a higher-precedence file set it true).
// Merge only the "bashEditDiffEnabled" key in; every other key already there is preserved untouched.
{
  "bashEditDiffEnabled": true
}
```

`CLAUDE_CODE_BASH_EDIT_DIFF` overrides this key for one session, in either direction.

Read each file first if it exists, merge the offered key(s) into the parsed object alongside
whatever is already there, and write the merged result back — never truncate either file to just
the key(s) this step adds.

---

## Step 5 — Report

Summarize: detected backends, the saved stance, both config paths written, and any
capability still missing (with the exact next step). If Codex came back
version-incompatible, say so plainly and recommend updating it. Mention that the
default tier→model `models` map was seeded into `.claude/compound-v.json`, and that
[`/v:models`](v-models.md) refreshes or customizes it whenever a backend ships new
models.

- **Next:** run `/v:onboard` to build the project knowledge base (architecture docs + AGENTS.md bridge). This is a suggestion, not automatic.
- Report whether Step 1f's `/skill-doctor` hygiene check ran (and its `superpowers-v:` summary, if
  so) — or was skipped below the version floor — and whether Step 4e's `advisorModel` offer and
  Step 4f's `bashOutputMaxChars`/`taskOutputMaxChars`/`bashEditDiffEnabled` offers were accepted or
  declined.

**Honesty rules:** report only what the probes actually returned. Never print token or
cost numbers of your own estimation. (Step 1f's context/7-day-token figures are an exception:
they are the harness's own `/skill-doctor` report reproduced verbatim, not a Compound V estimate.)
Never claim a backend works that the probe did not confirm.

---

## Verification fixture — `pre_eval.*` seeding + AC-11 (the "selftest" for this doc)

This is a command doc (no runnable code of its own), so the selftest is a **verification fixture**
that pins the four Step-3e/4a behaviours to the **real** shared loader
`scripts/compound-v-project-config.py` (Task 0) — no fabricated behaviour, no re-implemented rules.
It asserts: **(a)** `pre_eval.*` defaults are seeded; **(b)** a malformed value warns → uses the
default → **never routes a change on its own** (this key's domain has no `auto` value at all, and
the amended Iron Invariant #4's DIRECT auto-route class is decided by the scorer's predicates, not
by anything in `pre_eval.*`); **(c)** a remembered category is displayable + revocable; **(d)**
`off` is a hard kill-switch — and that **every fail-closed override still fires on a remembered
category** (structurally, because `remember` can only ever store the literal `"fastpath"`; the
overrides themselves are re-checked by the scorer per spec §2, never by this config).

Run from the repo root; it exits non-zero on any failure:

```bash
python3 - <<'PY'
import importlib.util, os, tempfile
spec = importlib.util.spec_from_file_location("cfg", "scripts/compound-v-project-config.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

fails = []
def ok(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond: fails.append(name)

# (a) defaults are seeded exactly as Step 4a writes them (all fail-closed).
v, w = m.resolve_pre_eval({})
ok("(a) pre_eval defaults seeded", v == dict(m.PRE_EVAL_DEFAULTS) and w == [])
ok("(a) fast_path default OFFERS ('ask'), is not an auto-route", v["fast_path"] == "ask")

# (b) per-key malformed value -> warn once -> declared default -> NEVER auto-routes.
v, w = m.resolve_pre_eval({"pre_eval": {"fast_path": "banana", "token_cap": -1}})
ok("(b) bad fast_path -> default 'ask'", v["fast_path"] == "ask")
ok("(b) bad token_cap -> default", v["token_cap"] == m.PRE_EVAL_DEFAULTS["token_cap"])
ok("(b) malformed values warn once", len(w) >= 2)
ok("(b) fast_path domain has no auto-route value at all", v["fast_path"] in ("ask", "off"))
# structural malformation RAISES so the caller warns once + falls back to all-defaults.
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, ".claude"))
    with open(os.path.join(td, ".claude", "compound-v.json"), "w") as fh:
        fh.write("{ not json")
    raised = False
    try: m.load_project_config(td)
    except ValueError: raised = True
    ok("(b) structural malformation raises (caller warns -> defaults, never routes)", raised)

# (c) a remembered category is displayable, and revocable (drop the key / edit config).
v, _ = m.resolve_pre_eval({"pre_eval": {"remember": {"css-only": "fastpath"}}})
ok("(c) remembered category is displayable", v["remember"] == {"css-only": "fastpath"})
v, _ = m.resolve_pre_eval({"pre_eval": {"remember": {}}})
ok("(c) revoked -> not remembered (ask every time)", v["remember"] == {})
# 'remember' can ONLY store 'fastpath' -> it can never encode "skip a fail-closed override".
v, w = m.resolve_pre_eval({"pre_eval": {"remember": {"css-only": "skip-overrides"}}})
ok("(c/AC-11) non-'fastpath' remember value is dropped + warned",
   v["remember"] == {} and len(w) >= 1)

# (d) off is a hard kill-switch: it round-trips; no offer is representable beyond ask|off.
v, w = m.resolve_pre_eval({"pre_eval": {"fast_path": "off"}})
ok("(d) off is a hard kill-switch (round-trips, no warnings)", v["fast_path"] == "off" and w == [])

print("\nRESULT:", "PASS" if not fails else "FAIL (%d)" % len(fails))
raise SystemExit(1 if fails else 0)
PY
```

> **Why the fail-closed overrides are proven here structurally, not executed:** the six overrides —
> sensitive path, shared-token, a11y, churn-hot, tier-disagreement, and the post-hoc diff escalation
> — live in the pre-eval **scorer** (spec §2 truth-table), not in this config. `remember` only ever
> suppresses the *offer* for a category, and its value space is the single literal `"fastpath"`, so a
> remembered category **cannot** encode "skip an override." The end-to-end proof that a
> `css-only`-remembered request STILL escalates on a shared-token/a11y hit is the AC-11 scorer
> fixture (plan Step 2, owned by A3/Z1); this fixture pins the config half of that contract.

Expected output: every line `ok`, ending `RESULT: PASS` (exit 0).
