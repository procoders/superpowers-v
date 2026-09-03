# Compound V — Codex / Universal Agent Shim (🧪 experimental, untested)

This file documents how the plugin's content *would* be consumed by tools that read `AGENTS.md` from a project root (Codex CLI and similar). **It has not been tested on a real Codex install** — tool-name mappings and dispatch syntax are based on documentation and may need adaptation per your harness version.


## Requirements

**Claude Code ≥ 2.1.219.** Compound V 3.0 hands execution to the native Workflow runtime and to native hook events (`PreToolUse`, `UserPromptSubmit`, `PostCompact`, `Stop`); older versions lack them.

**On measurement, stated up front.** No speed or cost claim ships with 3.0. The observation that motivated proportionate tests — a small change running a full suite — was not reproduced during the design recon, so the test-scoping defaults are **principle-derived, not measured**. The scoped floor is early feedback and does **not** restore what a full suite guarantees; the merge-blocking CI run does, and it always runs. The pipeline records selected-test counts and measured-only durations so a future release can speak from real data instead.

**One ambient cost worth knowing before you install.** The lane-enforcement hook runs on every `Write`/`Edit`/`Bash` tool call in every session, and its cost depends on the machine — **it is a small table, not a single number** — because it first has to find an interpreter that can read a manifest. Re-measured 2026-09-03: **~149 ms** on the ordinary machine — the one whose first candidate interpreter can `import yaml`, which on macOS is `/usr/bin/python3`, and which pays exactly **one** viability probe — rising to **~200 ms** where **no** candidate has PyYAML and the hook pays **three** probes (two `import yaml`, one `-c pass`). A machine whose *second* candidate has PyYAML pays two probes, about **175 ms**; that one is derived from the measured parts, not timed end to end, and is flagged as such rather than published as if it had been. All three are the **unresolved** path — the ordinary human session, and the only path a session that never dispatches will ever take. Once a job resolves and the manifest is parsed the figure is **~240 ms**, whether that write is then allowed or denied (the verdict has never been the expensive part; resolution and the manifest parse are). Method: mean of 50 invocations per cell, on macOS 26.5.2 / arm64 with `/usr/bin/python3` 3.9.6, against a sandbox project carrying copies of this repository's 48 run directories, with the bare-interpreter floor — **26 ms** — taken in the same round; **two** rounds qualified and both are published above. Take the floor with every round you take, **discard any round whose floor is above ~31 ms**, and measure the unresolved path somewhere actually unresolved — a checkout that a live run's lane map claims measures the *resolved* path and calls it unresolved, which is exactly how the first attempt at this round produced a 247 ms "unresolved" figure. Reproduce it from a checkout root — the total divided by 50:

```bash
P=$(printf '{"hook_event_name":"PreToolUse","tool_name":"Write","session_id":"s","cwd":"%s","tool_input":{"file_path":"%s/README.md"}}' "$PWD" "$PWD")
time (for i in $(seq 1 50); do printf '%s' "$P" | ./hooks/lane-guard.sh >/dev/null; done)
```

The resolved figure needs a lane map, so drive the same loop against the sandbox `tests/test-lane-guard.sh` builds. Set `CV_LANE_GUARD_LOG` and read it back to confirm which path you actually hit: the hook names the interpreter it chose on **every** path, but **once per session**, not once per call — measured over 50 invocations in one session, that is **1** interpreter line instead of 50 (100 log lines → 51 on the unresolved path; 50 → 1 on a resolved in-lane allow). A repeat is suppressed by a marker kept beside the log, so if the line is missing from the run you are timing, look earlier in the same log rather than concluding the ladder did not run; a *change* — a different interpreter, a candidate newly passed over — is a different message and reappears. An unresolved call adds `ALLOW (job unresolved)`, while a resolved in-lane allow says nothing more. A checkout with a **live** run in it does not take the unresolved path at all — if that run's lane map claims the checkout for a job, the recipe above measures the resolved path, and the log is how you find that out instead of publishing it.

**On the 167/245 ms this file published on 2026-09-02:** superseded as noisy, not withdrawn as wrong. Today's two rounds put the same cells at ~149 ms and ~240 ms by the same protocol, with no code in between that touches either path — that gap is round-to-round variation on a shared machine, which is why the method and the floor are published alongside the number. **The 47–81 ms from 2026-09-01 stays withdrawn**, and so does the 63 ms before it: two defences landed after that measurement and neither was cheap. The `PYTHONPYCACHEPREFIX` redirection that stops a planted `.pyc` being executed costs about **59 ms per call** — a redirected bytecode-cache lookup that `PYTHONDONTWRITEBYTECODE` forbids populating recompiles every stdlib module from source, every time (31 ms plain → 90 ms with both, measured directly). The interpreter **viability probe** costs about **25 ms** marginal and is what guarantees the guard never picks an interpreter that cannot run. Both are worth paying; neither was free, and this file once said they were. **Every external process the hook starts is bounded**: 0.9 s per interpreter probe (against a ~25 ms ordinary probe — the bound is there for the interpreter that *hangs*), 5 s for a delegated manifest parse, and `timeout: 10` on the registration in `hooks/hooks.json`, because a budget a hook applies to itself is not a budget on the hook. A probe that runs out of budget stops the ladder, says so once, and allows. And when the hook cannot create the private bytecode-cache directory that redirection needs, it now imports **nothing** — it used to carry on without the redirection, which dropped the defence on precisely the machine whose temp dir is full, unwritable or hostile. It is what turns lane enforcement from detection-after-the-fact into a refusal before the write.

## What this plugin does

Compound V is a **sidekick to Superpowers**. It intercepts the four Superpowers phase transitions (pre-brainstorm recon → brainstorming → writing-plans → execution) and adds:

0. **Gated pre-brainstorm recon (Trigger 0)** 🧪 description-driven, with a **reminder-only hook backstop** (v2.8: `hooks/brainstorm-trigger0-nudge.sh` nudges when the Skill tool invokes `superpowers:brainstorming` — a reminder, not enforcement; nothing can force the recon to run): before a brainstorm begins on an unfamiliar topic, a gated, bounded research pass (bundled `deep-research` if present, 3–6 parallel WebSearch otherwise, skip-with-notice if neither) writes an anti-anchoring recon doc to `docs/superpowers/recon/` that the brainstorm — and later pre-flights 1B/1C — read first. Gate order: plumbing-skip → V-memory KB hit → `brainstorm.deep_research` config (`ask` default / `auto` / `off` hard kill-switch). Recon is evidence, never a routing input. Also 🧪 description-driven: **batched elicitation** — ≥3 *independent* clarifying questions may batch into ONE screen via the surface ladder — Visual Companion form if accepted this session, else the harness's structured-question tool, else sequential (companion acceptance gates only the top surface); dependent chains stay sequential; when unsure → sequential; see `skills/compound-v/brainstorm-elicitation.md`.
1. **Three parallel pre-flights** after brainstorming:
   - Code archaeology (existing-code reality)
   - Domain-expert advisor with three-layer audience search (product/regulatory reality)
   - Library/doc validator via Context7 MCP (dependency currency)
2. **Disjoint File Partition Map enforcement** inside writing-plans, which **materializes a `manifest.yaml`** — the machine-readable contract that drives dispatch
3. **Manifest-driven multi-backend dispatch** (4-6 concurrent) on Opus by default, Sonnet only for strict junior-level mechanical tasks, or a headless **Codex** worker for large isolated builds
4. **A `git diff` scope gate after every job** — a worker that writes outside its `write_allowed` list is BLOCKED and never merges; enforcement fields are git-derived, never model-self-reported
5. **Crash-resume** via a `state.json` run directory

## Orchestrator surface (v1.0 + 1.1)

The execution tail is a small, deterministic orchestrator — contracts + helper scripts + the agent you already have. No daemon, no MCP server, no fabricated metrics.

- **Manifest contract:** `skills/compound-v/execution-manifest.md` (schema) + `examples/manifest.example.yaml`.
- **Backend Launcher sub-skill:** `skills/backend-launcher/SKILL.md` defines one `job_spec → job_result` contract (`schemas/job_result.schema.json`). Adapters: `adapter-claude.md`, `adapter-codex.md`, `adapter-antigravity.md` (1.1: a **real** headless `agy --print` worker — same worktree + `git diff` scope gate as Codex, but **opt-in / lower-trust**: `agy` has no kernel write-confinement, so the gate *detects* in-worktree scope leaks yet cannot *prevent* an out-of-worktree side-effect — **prefer Codex for untrusted work**), and `adapter-cursor.md` (2.1: a headless `cursor-agent -p -f` worker, verified live, same worktree + scope gate — also opt-in / lower-trust, same caveat as Antigravity; needs an authenticated `cursor-agent`).
- **Headless Codex worker:** `scripts/compound-v-run-codex-worker.sh`. The verified `codex-cli 0.144.1` invocation runs in a git worktree (with `--json` for structured `thread.started` session-id capture as of v2.8.1):

  ```bash
  codex exec --cd "$WT" --sandbox workspace-write --skip-git-repo-check \
    --model "$model" --json --output-last-message "$WT/.job_result.txt" \
    -c sandbox_workspace_write.network_access=false "$prompt" >"$events_log"
  ```

  Do **not** pass `--ask-for-approval never` — it is invalid for `codex exec` (top-level/interactive flag only); `exec` already defaults to `approval: never`. Resume is `codex exec resume <uuid>`. Effort `xhigh` is **codex-only** (kernel `model_reasoning_effort`); every other backend rejects it — use `high` elsewhere.
- **Scope gate:** `scripts/compound-v-scope-check.py` unions `git diff --name-only HEAD` with `git ls-files --others --exclude-standard` and tests each path against `write_allowed`.
- **State + resume:** `skills/compound-v/state-machine.md`; `/v:resume <run-id>` re-dispatches only incomplete jobs (git-wins tie-break).

> Note: the orchestrator scripts and adapters are exercised on Claude Code. On a non-Claude harness, the prose contracts (`SKILL.md`, the adapter docs, the manifest schema) are harness-neutral, but the dispatch wiring assumes Claude Code's `Task` tool — adapt to your harness's subagent mechanism. 🧪 **untested on Codex/other harnesses.**

## V-memory recall surface (v2.0)

A local-first RECALL layer over `docs/superpowers/**` prose. Engine: `scripts/compound-v-memory.py`; authority doc: `skills/compound-v/memory.md`. Two lanes: **CORE** = SQLite FTS5 BM25 over git-tracked prose (pure stdlib, always on); **DENSE** = opt-in embeddings (multilingual-e5-small) in an isolated venv outside the repo, rank-unioned with FTS5 and degrade-safe (absent/broken ⇒ FTS5-only). Embeddings are **PURE PYTHON** (`fastembed` = onnxruntime + tokenizers) — no Node, no daemon, no external vector-DB service. Recall is **evidence for planning + review, never a routing input** — routing stays the deterministic v1.1 order. The harness-neutral prose lives in `skills/compound-v/memory.md`; read it directly.

## How Codex / non-Claude-Code harnesses use it

The skill content lives at `skills/compound-v/SKILL.md` and its phase reference files. Read those directly — they're harness-neutral prose. The dispatch templates assume Claude Code's `Task` tool; in Codex, substitute your harness's subagent-spawning mechanism (e.g. `subagent` in Codex CLI).

## Tool name mapping (Claude Code → Codex)

| Claude Code | Codex / generic |
|---|---|
| `Task(subagent_type, prompt, model, maxTurns, run_in_background)` | `subagent <name> --model opus --max-turns 15 --background` |
| `Skill <name>` | Read the skill file directly and apply |
| `*context7*` tools | Whatever the local Context7 MCP installation exposes |
| Codex backend (`adapter-codex.md`) | A Bash-spawned `codex exec` worker process — its own process, its own git worktree. NOT a subagent, NOT the `openai-codex` JSON-RPC broker (single-flight, can't fan out). |

The Codex backend is harness-independent on purpose: it is just `codex exec` driven by `scripts/compound-v-run-codex-worker.sh`. Any harness with a shell can spawn it.

## First-class agents (under `agents/`)

These work in any harness that reads `agents/*.md` frontmatter. Codex CLI loads them as `subagent_type` candidates automatically:

- `compound-v:code-archaeologist` — Phase 1A
- `compound-v:domain-expert` — Phase 1B (with multi-layer WebSearch incl. persona forums)
- `compound-v:doc-validator` — Phase 1C
- `compound-v:partition-reviewer` — pre-execution gate; runs `compound-v-validate-manifest.py` as its deterministic backing check
- `compound-v:parallel-dispatcher` — manifest-driven multi-backend dispatcher; calls `compound-v-scope-check.py` after every job and HALTS on BLOCKED
- `compound-v:spec-reviewer` — the three-pass Review Gate (spec acceptance criteria · quality/no-regression/no-fabricated-metrics · final integration), AC-gated
- `compound-v:implementer` — the role every Claude implementation job arrives as (3.4.0). Carries the turn cap (`maxTurns: 60` — a field of an agent definition, which is the only native way a workflow job gets one) and the official Opus 5 guidance on scope, narration cadence and deliverable length

All reviewers/agents carry `model: opus`. Manifest `backend`/`model` values (`gpt-5.5`, etc.) are execution-layer data and **never** appear in any frontmatter.

## Slash commands

| Command | Purpose |
|---|---|
| `/v:init` | Detect capabilities (Codex CLI, Context7 MCP), walk through installs, set + save routing stance |
| `/v:orchestrate <plan>` | Materialize a `manifest.yaml` from a plan + routing policy |
| `/v:dispatch <plan\|manifest\|run-id>` | Run the autonomous pipeline (partition-review → dispatch → scope-gate → collect → review). A bare plan path still works (backward-compatible) |
| `/v:collect <run-id>` | Re-run collect + scope-gate + review on an existing run |
| `/v:status [run-id]` | Render `state.json` |
| `/v:resume <run-id>` | Reconcile + re-dispatch incomplete jobs after interruption |
| `/v:models` | Discover models per backend (`agy models`, curated Codex list, native Claude tiers) and write the tier→model map into `.claude/compound-v.json` |
| `/v:review-plan <plan>` | Optional cross-model (Codex) second opinion on a high-stakes plan before dispatch — read-only, advisory; the orchestrator arbitrates |
| `/v:epic <brief>` | Chain several features into one autonomous, resumable, dependency-ordered build on a single branch; each feature runs the full pipeline in topological order, ending with a cross-feature integration review |
| `/v:archaeology <topic>` | (unchanged) Phase 1A only |
| `/v:remember <query>` | Recall search over `docs/superpowers/**` prose (V-memory) — evidence for planning + review, not a routing input |
| `/v:adr <decision>` | Capture one genuine architecture decision as a thin, human-confirmed ADR (`docs/superpowers/adr/NNNN-slug.md`) — decision + alternatives + consequences, references verified to exist, draft→confirm→commit, then FTS5-recallable via `/v:remember` |
| `/v:memory-refresh` | (Re)index the FTS5 recall lane; `--bootstrap` provisions the opt-in dense embeddings venv |
| `/v:onboard` | Scan the repo and build a trusted, citation-verified knowledge base (`docs/superpowers/architecture/*`) plus an `AGENTS.md`/`CLAUDE.md` bridge, behind a human approval gate; `--refresh` re-checks staleness |
| `/v:pr-review [url\|number]` | Deep two-axis (Standards ⊥ Spec) code review of a PR/MR or local diff — review-only, never edits; GitHub (`gh`), GitLab (`glab`), or a hostless local branch |

## Model policy (universal)

- **Opus by default** — every implementer, reviewer, advisor
- **Sonnet for scanning** — `code-archaeologist` and `doc-validator` (3.1.0): reading a repository and checking a library version is execution, not judgment
- **Sonnet** — narrow exception per the 8-box junior-task taxonomy in `skills/compound-v/phase-3-parallel-opus-dispatch.md`
- **Never Haiku** — not permitted in this project

## Key entry points

- For setup: `README.md` (and `/v:init` to detect capabilities)
- For the full skill flow: `skills/compound-v/SKILL.md`
- For the execution contract: `skills/compound-v/execution-manifest.md` + `skills/backend-launcher/SKILL.md` + `schemas/job_result.schema.json`
- For routing: `skills/compound-v/routing-policy.md`
- For state + resume: `skills/compound-v/state-machine.md`
- For "what's in this plugin": `CHANGELOG.md`
- For "it broke": `TROUBLESHOOTING.md`
- For the comic / why it exists: `assets/skyscraper-metaphor.md`

## Disclaimer

This plugin was built and tested primarily on Claude Code. Codex / Gemini compatibility is best-effort via shims. If you find harness-specific gotchas, please file an issue.

> **Context7 tool naming.** Context7's tool names depend on HOW it is installed: a plugin-bundled server is `mcp__plugin_<plugin>_context7__*`, a user- or project-configured server is `mcp__context7__*`. **Match on the suffix, not the full string** — `*context7*resolve-library-id` and `*context7*query-docs` — and read the tool list you actually have. Every document in this plugin hardcoded the plugin-bundled form until 3.1.0; on a machine with the plain form that named a tool which does not exist, and the agent silently fell back to WebSearch.
