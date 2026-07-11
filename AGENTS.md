# Compound V — Codex / Universal Agent Shim (🧪 experimental, untested)

This file documents how the plugin's content *would* be consumed by tools that read `AGENTS.md` from a project root (Codex CLI and similar). **It has not been tested on a real Codex install** — tool-name mappings and dispatch syntax are based on documentation and may need adaptation per your harness version.

## What this plugin does

Compound V is a **sidekick to Superpowers**. It intercepts the four Superpowers phase transitions (pre-brainstorm recon → brainstorming → writing-plans → execution) and adds:

0. **Gated pre-brainstorm recon (Trigger 0)** 🧪 description-driven, with a **reminder-only hook backstop** (v2.8: `hooks/brainstorm-trigger0-nudge.sh` nudges when the Skill tool invokes `superpowers:brainstorming` — a reminder, not enforcement; nothing can force the recon to run): before a brainstorm begins on an unfamiliar topic, a gated, bounded research pass (bundled `deep-research` if present, 3–6 parallel WebSearch otherwise, skip-with-notice if neither) writes an anti-anchoring recon doc to `docs/superpowers/recon/` that the brainstorm — and later pre-flights 1B/1C — read first. Gate order: plumbing-skip → V-memory KB hit → `brainstorm.deep_research` config (`ask` default / `auto` / `off` hard kill-switch). Recon is evidence, never a routing input. Also 🧪 description-driven: **batched elicitation** — ≥3 *independent* clarifying questions may batch into one Visual Companion form screen (dependent chains stay sequential; when unsure → sequential); see `skills/compound-v/brainstorm-elicitation.md`.
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
- **Headless Codex worker:** `scripts/compound-v-run-codex-worker.sh`. The verified `codex-cli 0.144.1` invocation runs in a git worktree:

  ```bash
  codex exec --cd "$WT" --sandbox workspace-write --skip-git-repo-check \
    --model "$model" --output-last-message "$WT/.job_result.txt" \
    -c sandbox_workspace_write.network_access=false "$prompt"
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
| `mcp__plugin_context7_context7__*` | Whatever the local Context7 MCP installation exposes |
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
| `/v:memory-refresh` | (Re)index the FTS5 recall lane; `--bootstrap` provisions the opt-in dense embeddings venv |
| `/v:onboard` | Scan the repo and build a trusted, citation-verified knowledge base (`docs/superpowers/architecture/*`) plus an `AGENTS.md`/`CLAUDE.md` bridge, behind a human approval gate; `--refresh` re-checks staleness |
| `/v:pr-review [url\|number]` | Deep two-axis (Standards ⊥ Spec) code review of a PR/MR or local diff — review-only, never edits; GitHub (`gh`), GitLab (`glab`), or a hostless local branch |

## Model policy (universal)

- **Opus by default** — every implementer, reviewer, advisor
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
