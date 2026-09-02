# superpowers-v 💉

**Compound V** — a multi-model coding sidekick for [Superpowers](https://github.com/obra/superpowers), running on Claude Code.

> *"You don't tell people you're injecting them with Compound V. You just hand them the spec and watch them ship."*

![Compound V — a sidekick to Superpowers](assets/compound-v-cover.png)

You describe a feature. Claude plans it, splits it into non-overlapping pieces, and hands the implementation out across **Claude / Codex / Antigravity / Cursor** — each working in its own isolated sandbox. Then it reviews the result (including a second opinion from a different model) before merging. You don't press a "start" button — it kicks in on its own as you work.

---


## Requirements

**Claude Code ≥ 2.1.219.** Compound V 3.0 hands execution to the native Workflow runtime and to native hook events (`PreToolUse`, `UserPromptSubmit`, `PostCompact`, `Stop`); older versions lack them.

**On measurement, stated up front.** No speed or cost claim ships with 3.0. The observation that motivated proportionate tests — a small change running a full suite — was not reproduced during the design recon, so the test-scoping defaults are **principle-derived, not measured**. The scoped floor is early feedback and does **not** restore what a full suite guarantees; the merge-blocking CI run does, and it always runs. The pipeline records selected-test counts and measured-only durations so a future release can speak from real data instead.

**One ambient cost worth knowing before you install.** The lane-enforcement hook runs on every `Write`/`Edit`/`Bash` tool call in every session. Its cost is **47–81 ms**, and which end you pay depends on the path: **47 ms** where no Compound V job is acting — the ordinary human session, and the only path a session that never dispatches will ever take — rising to **81 ms** once a job resolves and the manifest is parsed, whether that write is then allowed or denied (the two resolved paths cost the same; the deny is not the expensive one). Re-measured 2026-09-01, mean of 50 invocations per path, on macOS 26.5.2 / arm64 with `/usr/bin/python3` 3.9.6, against a checkout carrying 12 run directories. Reproduce the unresolved figure from a checkout root — the total divided by 50:

```bash
P=$(printf '{"hook_event_name":"PreToolUse","tool_name":"Write","session_id":"s","cwd":"%s","tool_input":{"file_path":"%s/README.md"}}' "$PWD" "$PWD")
time (for i in $(seq 1 50); do printf '%s' "$P" | ./hooks/lane-guard.sh >/dev/null; done)
```

The two resolved figures need a lane map, so drive the same loop against the sandbox `tests/test-lane-guard.sh` builds; set `CV_LANE_GUARD_LOG` and read it back to confirm which path you actually hit, because an unresolved run is silent and looks like an allow. **These numbers supersede the 63 ms this file used to publish and the 54/112/152 ms in `hooks/lane-guard.sh`'s own header** — those two disagreed with each other, and re-measurement reproduced neither. It is what turns lane enforcement from detection-after-the-fact into a refusal before the write.

## 🎮 New here? Learn it as a game → **[Compound V Academy](https://amiainative.dev/compound-v)**

The fastest way to *get* what this plugin does. Three gamified episodes — **Developer · Product Owner · Universal Creator** — walk you through the whole pipeline (onboarding → the three scouts → manifest + dispatch → the review gates), with the squad — **The Trench**, **Bootcher**, **Monsieur Contexte**, **Motherboard**, **Git Noir**, **A-Express** — as your guides. 👉 **<https://amiainative.dev/compound-v>**

[![Compound V Academy — meet the squad](assets/compound-v-squad.png)](https://amiainative.dev/compound-v)

📄 Prefer a quick reference? The **[Compound V Cheatsheet](https://amiainative.dev/compound-v/cheatsheet)** puts the whole 8-phase pipeline, commands, skill triggers, memory, and backend-routing rules on one page.

---

## Main features

- **Multi-model orchestration** — Claude builds the plan and routes implementation jobs to the right backend (**Claude / Codex / Antigravity / Cursor**). Each worker runs isolated under a scope check, so nothing writes outside the files it was given.

- **Cross-model (Codex) review** — a second opinion on the plan **and** the code. Different models have different blind spots, so it's very good at catching planning gaps and mistakes. Advisory — the orchestrator makes the final call.

- **Epic mode** — feed it a whole PRD with many tasks and it builds feature by feature, in dependency order, on one branch. By default it checkpoints after each feature so you can review (raise the budget to let it run longer).

- **Epic autonomy** (v3.4, native) — when an epic's stance is `marathon`, `/v:epic` offers, never arms silently, a native way to keep going past a checkpoint: `/loop 30m /v:epic <epic-id>` to keep resuming inside this session, or a `/schedule` routine for the same command in the cloud, plus `/goal` (or a plain `/goal <condition>` typed by hand) to let the harness's own evaluator decide when the epic is met. `/v:epic` is re-entrant, so every firing is a plain resume, and it stops its own loop or scheduled entry once the epic is terminal. Honesty boundary: **`/loop` shares the session's fate** — paused while the session is busy or gone, and its interval mode expires after 7 days like any recurring `CronCreate` job; **`/schedule` is the actual machine-off path**, and it runs under its own cloud-routine auth, not this session's.

- **V-memory** — project memory that builds up as you work: decisions made, bugs fixed, things that failed. It surfaces the relevant bits when you plan or review.

- **Co-change advisory** (v2.17) — before dispatch, the partition reviewer asks this repo's own git history which files almost always move together, and warns when a plan owns one but forgot its usual partner. Pure `git log`, no model involved. It is **advisory**: it only appends a warning, never changes the PASS/FAIL verdict, and adds no new gate. On a short or squash-merged history it will legitimately find nothing — and it says "could not tell" rather than "all clear".

- **Research-grounded brainstorming** 🧪 — before a brainstorm on an unfamiliar topic, a gated, bounded recon pass (off by one config key) writes an evidence doc the brainstorm reads first. And when the brainstorm has 3+ *independent* clarifying questions, it can batch them into one screen — the Visual Companion form if you've accepted it, else a structured question, else the usual one-at-a-time (dependent questions always stay sequential). Both are description-driven guidance, not hook-enforced.

---

## How it routes the work

Compound V never lets a worker pick its own model. A **deterministic router** looks at each job — its type, the files it may touch, whether it is a review — and assigns the mode from code, not from a vibe. Two forks, three worker modes:

![How Compound V decides who does the work](docs/routing.svg)

- **Pre-Evaluation** splits the request first: trivially simple and low-impact takes a cheap **fast path** (one worker); anything real enters the full pipeline.
- In the pipeline an **orchestrator** (a strong model) plans and splits the work, then the **router** assigns each job a mode: **full Opus** for risky / review / security / cross-cutting work, **Sonnet solo** for routine mechanical jobs, and, *opt-in*, **a cheaper executor plus an on-demand read-only advisor** for medium, self-contained jobs. When advisor mode is enabled on an eligible job, that job's executor MAY, on a genuinely hard sub-decision, consult a read-only advisor of a different brand (Codex if you have it, otherwise Opus) for a second opinion, then decide and do the writing itself. The advisor is read-only by contract: it advises, it never writes files. Each consult is logged, and the count is recorded honestly on the job (it is derived by counting the consult log, not self-reported). It is a subagent pattern, no API key — and it is wired only on the residual `Task` dispatch path: Engine C, the default engine since 3.0, emits no consult step, so on a default run the advisor does not fire.
- Everything runs in parallel, every write is checked against a git-derived scope gate, and an Opus reviewer gates "done".

---

## Install

In Claude Code:

```
/plugin marketplace add https://github.com/procoders/superpowers-v
/plugin install superpowers-v@procoders
```

**Want the other models too?** Install and log into their CLIs first — Compound V picks them up automatically. All optional; without them it just runs Claude-only.

- **Codex:** `npm i -g @openai/codex` → `codex login`
- **Cursor:** `curl https://cursor.com/install -fsS | bash` → `cursor-agent login`
- **Antigravity:** install the `agy` CLI → log in

_Recommended combo:_ **Claude Max $200 + Codex Max $100**.

_(Optional)_ Context7 MCP makes the library-docs check sharper: `/plugin install context7@claude-plugins-official`.

---

## How to use it — two commands

**1. Set up once:**

```
/v:init
```

It detects which model CLIs you have, picks a routing setup, and saves the config.

**2. Then just work.** Describe the feature or start brainstorming as usual — Compound V takes over planning and execution by itself. On unfamiliar topics it first *offers* a quick pre-brainstorm research pass (gated, bounded, off by one config key) and saves the findings as a recon doc in `docs/superpowers/recon/` for the brainstorm — and the later pre-flights — to read. **There is no command to "launch" the orchestration; it's automatic.**

That's it.

### Want to drive it by hand?

| Command | What it does |
|---|---|
| `/v:epic <PRD or brief>` | Build a whole multi-feature PRD, feature by feature |
| `/v:remember "<query>"` | Search the project memory |
| `/v:status` · `/v:resume <id>` | Check progress / continue after a crash |
| `/v:dashboard` (v2.15, native in 3.4) | `emit` a static HTML snapshot of past runs/epics — a live run is watched natively, with `/workflows` and `/tasks` |
| `/v:preferences` (v2.16) | Your own dated past-brainstorm reasoning, as **falsifiable memory + a challenge** — `stats` / `distill` / `show` / `purge`. `marked` mode badges the option matching your history (never pre-selects it); raw log stays local, the scrubbed distillate is `/v:remember`-able |
| `/v:models` | Refresh which model each backend uses |

---

## Good to know

- **Antigravity and Cursor are lower-trust** (no kernel sandbox). The scope check catches out-of-bounds writes *after the fact* but can't *prevent* them. For anything sensitive or untrusted, prefer **Codex** — it runs in a real workspace sandbox.
- **Cursor on a Free plan** can only use its `auto` model (named models are paid).
- **Epic mode is bounded by default** — it stops after each feature for a human checkpoint. It is *not* a fire-and-forget overnight build unless you raise the budget.
- **Marathon mode (opt-in) is still not fire-and-forget-overnight.** It removes the per-feature checkpoint and adds an arbiter panel + blocker ledger + global breakers so it can run further unattended in one sitting — but on its own it does not self-revive after a hard death. If the session dies, you re-run `/v:epic <epic-id>` yourself; it resumes from the last committed state.
- **The triage gate is ON by default (3.2.0), and here is how to turn it off.** The `UserPromptSubmit` hook now scores the first change request of a session itself — it runs the same scorer `/v:triage` does and writes the record (uncommitted; `/v:orchestrate` commits it at bind, and a DIRECT commit includes it by hand) — so a manual `/v:triage` is only needed for the T3 escalation path. Once per session, in a repo that has a `.claude/compound-v.json`, if the working tree carries code changes that no triage record covers, the `Stop` hook holds the turn open and asks for `/v:triage`. It is exempt on `docs/superpowers/**`, it fires at most once per session, it is bounded at ~800 ms and fails open on any timeout or error, and a project that never ran `/v:init` never sees it. To opt out:

  ```json
  { "enforcement": { "triage_gate": false } }
  ```

  in `.claude/compound-v.json`. An explicit `false` is the only value that turns it off. It is **advisory** — the runtime discards a `Stop` block when a turn ends via a tool result or a loop tick, and `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` (default 8) lets the harness override it outright. It raises the cost of skipping the pipeline; it cannot make skipping impossible.
- No daemon, no server, no MCP service, no made-up cost numbers. Everything is small, readable scripts.

---

## Under the hood (for the curious)

The orchestration, scope enforcement, routing, and memory are plain bash + Python scripts and skill docs you can read. Start here:

- [skills/compound-v/SKILL.md](skills/compound-v/SKILL.md) — the orchestrator
- [skills/compound-v/epic-mode.md](skills/compound-v/epic-mode.md) — epic mode
- [skills/compound-v/memory.md](skills/compound-v/memory.md) — V-memory
- [skills/backend-launcher/SKILL.md](skills/backend-launcher/SKILL.md) — the backend workers
- [CHANGELOG.md](CHANGELOG.md) — full version history

Built as a sidekick to [Superpowers](https://github.com/obra/superpowers). MIT licensed.
