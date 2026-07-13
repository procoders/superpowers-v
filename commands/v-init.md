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

### 1a-quater. Devin CLI (`devin`) — optional, lower-trust, WORKER-ONLY backend

```bash
command -v devin
```

If absent → Devin is **not available** (record it; routing never offers it).

If present → check **authentication** (auth-free command, verified live):

```bash
devin auth status </dev/null 2>&1 | head -3   # or: [ -n "$COGNITION_API_KEY" ]
```

- Installed **and** authenticated (`devin auth login`, or `COGNITION_API_KEY` set) →
  Devin is **usable**; record it and add it to `backends`. The pinned headless invocation
  (devin-cli 3000.1.27, verified live for its help/flag surface — task-execution behavior is
  DOC-CLAIMED, unverified without an authenticated run):
  `cd "$WT" && devin -p "<prompt>" --permission-mode dangerous [--model <M>] --export <path> </dev/null`.
  Also probe sandbox availability (auth-free, verified live): `devin sandbox setup` — on macOS
  reports *"No sandbox setup is required"*; on Linux it either confirms `bubblewrap`+`socat`
  are present or prints install instructions. Record the result — it tells `/v:models` /
  the operator whether Devin's `--sandbox` (Research Preview) is even usable on this machine,
  though this plugin does **not** rely on it for enforcement in v1 (see below).
- Installed but **not** authenticated → record it as **present but unauthenticated**; treat as
  unavailable and tell the user to run `devin auth login` (or set `COGNITION_API_KEY`).

> **Flag it as lower-trust AND worker-only when you record it.** Devin has a real,
> live-confirmed kernel `--sandbox` flag (macOS Seatbelt / Linux bwrap+seccomp) — a
> genuine differentiator from Antigravity/Cursor — but Cognition labels it
> **"[Research Preview]"**, its coverage is scoped to "exec-tool processes" (non-shell
> file-edit tool coverage unverified), and its network-filtering is called "currently
> unstable" in Cognition's own docs. Until those are live-verified, this plugin treats
> Devin as **opt-in, lower-trust — the same tier as Antigravity/Cursor**, NOT Codex: the
> worktree + `git diff` gate is the *real* enforcement (detection, not confirmed
> prevention). **Prefer Codex for untrusted / high-stakes work.** Devin is also
> **model-agnostic** (`--model` accepts a free string spanning Claude/GPT/Gemini/Devin's
> own SWE family) — its resolved model family is data-dependent, so it is **WORKER-ONLY
> for v1, excluded from any cross-model arbiter/review panel** until family-dedup keys on
> the resolved model rather than the backend name. See
> [`adapter-devin.md`](../skills/backend-launcher/adapter-devin.md).

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
> strings (e.g. `anthropic/claude-opus-4-6`), so — like Devin — its resolved model family
> is data-dependent; it is **WORKER-ONLY for v1, excluded from any cross-model
> arbiter/review panel** until family-dedup keys on the resolved model. See
> [`adapter-opencode.md`](../skills/backend-launcher/adapter-opencode.md) for the
> **mandatory env-scrub** (the worker script must NOT blindly inherit the dispatcher's own
> provider env vars into the `opencode run` child process).

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

### 1d-ter. Scheduler tiers for auto-resurrection (Cron + `scheduled-tasks` MCP) — v2.11, optional

Marathon auto-resurrection (`epic.autonomy.watch`, Step 3c) needs at least one of two schedulers to
actually re-invoke a stalled epic while you're away. Detect both, **presence-only** — this is
Claude-Code/Desktop-specific tooling, not a shell probe, and mirrors the same
available-tools-listing check as Step 1d-bis:

- **Tier-1 (session `CronCreate`)** — present when `CronCreate` appears in your own available-tools
  listing (a plain subagent shell may not have it).
- **Tier-2 (`scheduled-tasks` MCP)** — present when `mcp__scheduled-tasks__create_scheduled_task`
  appears in your own available-tools listing (the MCP server must be connected).

Record both into the user-level capability cache (Step 4b) — **never** the committed
`.claude/compound-v.json`, per the same v2.6.2 machine-local-vs-committed-policy split as every other
capability here. **Fail closed on zero tiers**: if neither is present, tell the user
auto-resurrection cannot arm on this machine and they should decline (or leave off) the
`epic.autonomy.watch` offer in Step 3c — `watch` is worthless without a scheduler to fire it. One tier
detected → note which, and that a single-tier arm is real but honestly degraded (state the boundary
in Step 3c). Both present → full two-tier coverage. This is a presence flag only, like
`deep_research` above — the driver re-confirms live availability at arm time in
[`v-epic.md`](v-epic.md) §0c; a stale "yes" here never forces an arm.

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
  unless the epic also opts into `watch`** (the next bullet). `marathon` also needs the **global
  breaker caps** agreed up front (sensible defaults, all tunable): `max_wall_clock_hours` (default
  **10**), `max_total_attempts` (default `max(6, 3×features)`), and `max_no_progress_cycles`
  (default **3** — a full pass with no new feature reaching `done` counts as one non-progressing
  cycle). These caps bound **counts and wall-clock hours only** — never a fabricated cost or token
  number. `checkpoint` remains the safe, unchanged default; only set `marathon` when the user
  explicitly wants unattended, multi-feature autonomy and accepts the boundary above.
- **Auto-resurrection — `epic.autonomy.watch`** (toggle, default **off**; marathon-only, v2.11):
  whether a `marathon` epic ALSO arms a scheduler watcher that automatically re-invokes
  `/v:epic <epic-id>` after a hard death, instead of waiting for a human to do it. Offer this only
  when `marathon` (above) is also being chosen — `watch` is meaningless without it — and only after
  Step 1d-ter found **at least one** scheduler tier available; with zero tiers, decline the offer
  (or leave it off) and say why. State the **corrected honest boundary** plainly before offering it:
  - **Tier-1 (session `CronCreate`)** pauses whenever the session is unavailable or busy, MISSES any
    fire that elapses while paused (no catch-up), may resume on the next conversation turn if not yet
    expired, and expires outright after **7 days** even in a continuously open session; its
    ~30-minute cadence (`:17`/`:47`) is approximate, not exact — recurring fires carry jitter.
  - **Tier-2 (`scheduled-tasks`, on-disk)** runs only while the desktop app is **open and the machine
    is awake**; it performs exactly **one** catch-up for the most recent missed run on app
    start/wake, within 7 days — it is not a truly always-on server.
  - **"Survives quota exhaustion"** only holds if the quota has since **reset** and the session is
    still **authenticated** — an expired OAuth token still needs a human.
  - **A closed laptop needs remote infra**, not this feature: neither tier runs while the machine is
    asleep. A local `launchd`/cron shim removes the app-open dependency but still does not fire
    while the laptop sleeps — genuine machine-off execution needs remote infrastructure plus a
    remotely-reachable state substrate, which is an optional user-side add-on, never claimed built-in
    here.
  - **Resurrection is bounded** — `max_resume_count` (script default **20**, set per-epic via
    `--init --watch --max-resume-count N`) caps how many times the watcher may resurrect the epic; a
    persistently-dying run halts at `blocked_needing_human` for a human, exactly like any other
    tripped breaker.
  `off` (the default) leaves marathon exactly as v2.10 — a human re-invokes `/v:epic <epic-id>`
  after a hard death, same as always. Full design: [`epic-mode.md`](../skills/compound-v/epic-mode.md)
  "Auto-resurrection watch".
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
`.claude/compound-v.json` (Step 4a). **Every default is fail-closed** — the SAFE, never-auto-route
value — so a user who just presses Enter gets the safe behaviour. Read/round-trip these ONLY through
the shared loader `compound-v-project-config.load_project_config(repo)` + `resolve_pre_eval(cfg)`
(never re-interpret the keys here). Offer two structured choices (defaults are safe; reconfigurable
any time):

- **Fast-path offer — `pre_eval.fast_path`** (options `ask` / `off`; default **`ask`**): whether the
  pre-eval stage may *offer* a fast-path when a change is provably trivial. `ask` folds the offer
  into the ONE recon/clarify interaction (never a standalone screen); it only ever OFFERS — it
  **never auto-routes** (Iron-Invariant #4). `off` is a **hard kill-switch** — no offer, no
  fast-path, ever (honored for cost AND confidentiality). There is deliberately **no `auto` value**;
  a malformed/unknown value is coerced back to `ask` (offer), never to any auto-route.
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
      "watch": false,
      "max_wall_clock_hours": 10,
      "max_no_progress_cycles": 3
    }
  },
  "review": { "cross_model": false },
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
      "claude":      { "deep": "opus",                  "standard": "opus",                  "light": "sonnet" },
      "codex":       { "deep": "gpt-5.6-sol",            "standard": "gpt-5.6-terra",          "light": "gpt-5.6-luna" },
      "antigravity": { "deep": "Gemini 3.1 Pro (High)", "standard": "Gemini 3.1 Pro (Low)", "light": "Gemini 3.5 Flash (Low)" },
      "cursor":      { "deep": "auto",                  "standard": "auto",                  "light": "auto" },
      "devin":       { "deep": "claude-opus-4.6",        "standard": "claude-sonnet-4",        "light": "gpt-5.5" },
      "opencode":    { "deep": "anthropic/claude-opus-4-6", "standard": "openai/gpt-5.6-terra", "light": "opencode/mimo-v2.5-free" }
    },
    "cost-aware": {
      "claude":      { "deep": "opus",                  "standard": "sonnet",                "light": "sonnet" },
      "codex":       { "deep": "gpt-5.6-sol",            "standard": "gpt-5.6-terra",          "light": "gpt-5.6-luna" },
      "antigravity": { "deep": "Gemini 3.1 Pro (High)", "standard": "Gemini 3.1 Pro (Low)", "light": "Gemini 3.5 Flash (Low)" },
      "cursor":      { "deep": "auto",                  "standard": "auto",                  "light": "auto" },
      "devin":       { "deep": "claude-opus-4.6",        "standard": "claude-sonnet-4",        "light": "gpt-5.5" },
      "opencode":    { "deep": "anthropic/claude-opus-4-6", "standard": "openai/gpt-5.6-terra", "light": "opencode/mimo-v2.5-free" }
    }
  }
}
```

- `devin` and `opencode` are **worker-only** backends (v1): excluded from any cross-model
  arbiter/review panel until family-dedup keys on the *resolved* model rather than the
  backend name (both are multi-provider routers, so `backend: devin`/`backend: opencode`
  does not fix a single model family — see `adapter-devin.md` / `adapter-opencode.md`).

(`conservative` and `claude-only` mirror `balanced` — seed those two stance blocks
identically to `balanced`. Only `cost-aware.claude.standard` differs: `sonnet`, not
`opus`; `cost-aware.claude.deep` stays `opus`.)

- `stance` = the stance chosen in Step 3.
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
- **`epic.autonomy.watch`** (default `false`, v2.11) = the Step 3c auto-resurrection opt-in — policy
  only, same shape as `epic.autonomy.stance` right above it: the driver re-confirms it against the
  **persisted** `epic-state.json`'s own `autonomy.watch` before arming anything (a persisted "no"
  wins even if this config later flips to `true`, and vice versa — arming requires **both** the
  config AND the persisted state to say yes; see [`v-epic.md`](v-epic.md) §0c). Marathon-only —
  `stance` must be `"marathon"` for `watch` to mean anything; a `checkpoint` epic ignores this key
  entirely. `max_resume_count` (script default **20**) is deliberately left **unset** here — like
  `max_attempts_per_feature` above, it is a per-epic choice made at `--init --watch
  [--max-resume-count N]`, not a global policy.
- **`review.cross_model`** (default `false`) = the Step 3c toggle; when `true`, high-stakes
  plans get an automatic Codex second opinion ([`/v:review-plan`](v-review-plan.md)) before
  dispatch.
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
  verbatim; every default is the fail-closed / never-auto-route value. `fast_path:"off"` is a **hard
  kill-switch**; `remember` holds AC-11's revocable per-category opt-ins (`{category: "fastpath"}`,
  only the literal `"fastpath"` honored). This is **committed team POLICY**, not machine capability.
  Unlike the resolver's `models` map, nothing hand-validates this file at read time on the hot path:
  the shared loader `scripts/compound-v-project-config.py` owns the fail-closed rules for every
  consumer — **structural** malformation (not JSON / root or `pre_eval` not an object) makes
  `load_project_config` raise so the caller warns once and falls back to all-defaults, while a
  **per-key** invalid value (`fast_path:"banana"`, negative `token_cap`, a `remember` value ≠
  `"fastpath"`) is coerced to its declared default by `resolve_pre_eval`, which returns a `warnings`
  list to surface once. An invalid value can only DEGRADE to the safe default — it is **NEVER** treated
  as an auto-route (Iron-Invariant #4/#5). Do not re-implement these rules inline; call the loader.
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
  "devin": {
    "available": false,
    "authenticated": false,
    "trust": "lower (Research-Preview kernel sandbox; exec-tool-only coverage unverified; network filtering unstable per vendor); worker-only",
    "version": "<from `devin --version`>",
    "sandbox_setup_required": null
  },
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
  "scheduler": { "tier1_cron": true, "tier2_scheduled_tasks": false },
  "checked_at": "<YYYY-MM-DD>"
}
```

- `codex.exec_flags_verified` reflects the Step 1a exec-help assertion (false if Codex
  is present but version-incompatible).
- `antigravity.available` reflects the Step 1a-bis `command -v agy` probe; record the
  `version` from `agy --version`. When present, Step 1a-bis also seeds a real model map
  via `agy models </dev/null` (headless — no TTY needed).
- `devin.available` reflects the Step 1a-quater `command -v devin` probe;
  `devin.authenticated` reflects `devin auth status`. `sandbox_setup_required` records
  whether `devin sandbox setup` reported readiness (macOS: always ready; Linux: depends
  on `bubblewrap`/`socat`) — informational only, not relied on for enforcement in v1.
- `opencode.available` reflects the Step 1a-quinquies `command -v opencode` probe;
  `opencode.auth` records **how** it is authenticating (`ambient-env` /
  `stored-credentials` / `none`) — this machine-local nuance matters more for opencode
  than any other backend, given the live-observed ambient-credential finding (see
  `adapter-opencode.md`).
- `devin` and `opencode` are never added to any arbiter/review-panel capability block —
  they are **worker-only** in v1.
- `scheduler.tier1_cron` / `scheduler.tier2_scheduled_tasks` reflect the Step 1d-ter presence
  probes (`CronCreate` / `mcp__scheduled-tasks__create_scheduled_task` in your own available-tools
  listing) — the machine-local capability `epic.autonomy.watch` (Step 3c, committed policy) needs at
  least one of to actually arm anything; **never** written to the committed
  `.claude/compound-v.json`, same v2.6.2 split as every other capability here. Like
  `deep_research` below, this is an **advisory hint** — the driver re-confirms live availability at
  arm time in [`v-epic.md`](v-epic.md) §0c, not just at `/v:init` time.
- `deep_research` reflects the Step 1d-bis presence probe (is `deep-research` in the
  available-skills listing?) — an **advisory hint only**: Trigger 0 re-checks the live
  listing at fire time, because the flag can go stale (`disableBundledSkills` /
  `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS` can hide the skill after init). A stale or absent
  flag is never treated as a hard "off."
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

---

## Verification fixture — `pre_eval.*` seeding + AC-11 (the "selftest" for this doc)

This is a command doc (no runnable code of its own), so the selftest is a **verification fixture**
that pins the four Step-3e/4a behaviours to the **real** shared loader
`scripts/compound-v-project-config.py` (Task 0) — no fabricated behaviour, no re-implemented rules.
It asserts: **(a)** `pre_eval.*` defaults are seeded; **(b)** a malformed value warns → uses the
default → **never auto-routes**; **(c)** a remembered category is displayable + revocable; **(d)**
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
