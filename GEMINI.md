# Compound V — Gemini CLI Shim (🧪 experimental, untested)

This file documents how the plugin's content *would* be used in Gemini CLI. **The shim has not been tested on a real Gemini CLI install** — the manifest format for Gemini CLI extensions is version-specific and the maintainer has not verified compatibility. Treat this as a starting point, not a working integration.

## What this plugin does

Compound V is a **sidekick to Superpowers**. It intercepts the four Superpowers phase transitions (pre-brainstorm recon → brainstorming → writing-plans → execution) and adds:

0. **Gated pre-brainstorm recon (Trigger 0)** 🧪 description-driven, with a **reminder-only hook backstop** (`hooks/brainstorm-trigger0-nudge.sh`, a Claude Code hook that nudges when the Skill tool invokes `superpowers:brainstorming` — a reminder, not enforcement): before a brainstorm begins on an unfamiliar topic, a gated, bounded research pass (bundled `deep-research` if present, 3–6 parallel WebSearch otherwise, skip-with-notice if neither) writes an anti-anchoring recon doc to `docs/superpowers/recon/` that the brainstorm — and later pre-flights 1B/1C — read first. Gate order: plumbing-skip → V-memory KB hit → `brainstorm.deep_research` config (`ask` default / `auto` / `off` hard kill-switch). Recon is evidence, never a routing input. Also 🧪 description-driven: **batched elicitation** — ≥3 *independent* clarifying questions may batch into ONE screen via the surface ladder — Visual Companion form if accepted this session, else the harness's structured-question tool, else sequential (companion acceptance gates only the top surface); dependent chains stay sequential; when unsure → sequential; see `skills/compound-v/brainstorm-elicitation.md`.
1. **Three parallel pre-flights** after brainstorming:
   - Code archaeology (existing-code reality)
   - Domain-expert advisor with three-layer audience search (product/regulatory reality)
   - Library/doc validator via Context7 MCP (dependency currency)
2. **Disjoint File Partition Map enforcement** inside writing-plans, which **materializes a `manifest.yaml`** — the machine-readable contract that drives dispatch
3. **Manifest-driven dispatch** on the most capable model available (Gemini 3.1 Pro or equivalent), with a **`git diff` scope gate after every job** (a worker that writes outside its `write_allowed` list is BLOCKED and never merges) and **crash-resume** via a `state.json` run directory

## Orchestrator surface (v1.0 + 1.1)

The execution tail is a small, deterministic orchestrator — contracts + helper scripts + the agent you already have. No daemon, no MCP server, no fabricated metrics.

- **Manifest contract:** `skills/compound-v/execution-manifest.md` + `examples/manifest.example.yaml`.
- **Backend Launcher sub-skill:** `skills/backend-launcher/SKILL.md` — one harness-neutral `job_spec → job_result` contract (`schemas/job_result.schema.json`).
- **Adapters:** `adapter-claude.md`, `adapter-codex.md` (a headless `codex exec` worker, OpenAI-specific), `adapter-antigravity.md` (1.1: a **real** headless `agy --print` worker — same worktree + `git diff` scope gate as Codex), and `adapter-cursor.md` (2.1: a headless `cursor-agent -p -f` worker, verified live, same worktree + scope gate — opt-in / lower-trust, needs an authenticated `cursor-agent`). Since `agy` is **Gemini-family**, on Gemini CLI it is the natural backend — but it is spawned as an external `agy` process, not an in-harness adapter (opt-in / lower-trust: no kernel sandbox, so the gate *detects* in-worktree scope leaks yet cannot *prevent* an out-of-worktree side-effect). There is still **no Gemini-specific in-harness adapter** — on Gemini CLI you either spawn the external `agy` worker or run the Claude-equivalent path through your harness's subagent mechanism. 🧪 untested.
- **Scope gate:** `scripts/compound-v-scope-check.py` (git-derived; pure Python 3.9 stdlib, harness-neutral).
- **State + resume:** `skills/compound-v/state-machine.md`.

## V-memory recall surface (v2.0)

A local-first RECALL layer over `docs/superpowers/**` prose. Engine: `scripts/compound-v-memory.py`; authority doc: `skills/compound-v/memory.md`. Two lanes: **CORE** = SQLite FTS5 BM25 over git-tracked prose (pure stdlib, always on); **DENSE** = opt-in embeddings (multilingual-e5-small) in an isolated venv outside the repo, rank-unioned with FTS5 and degrade-safe (absent/broken ⇒ FTS5-only). Embeddings are **PURE PYTHON** (`fastembed` = onnxruntime + tokenizers) — no Node, no daemon, no external vector-DB service. Recall is **evidence for planning + review, never a routing input** — routing stays the deterministic v1.1 order. The prose at `skills/compound-v/memory.md` is harness-neutral; on Gemini CLI, read it directly.

## How Gemini uses it

The skill content lives at `skills/compound-v/SKILL.md` and its phase reference files. Read those directly — they're harness-neutral.

Gemini's `activate_skill` tool can load the SKILL.md content on demand. Trigger: when the conversation mentions brainstorming completion, planning, or implementation orchestration.

## Tool name mapping (Claude Code → Gemini CLI)

| Claude Code | Gemini CLI |
|---|---|
| `Task(subagent_type, prompt, model)` | Gemini's `run_subagent` or `agent_dispatch` (varies by version) |
| `Skill <name>` | `activate_skill <name>` |
| `mcp__plugin_context7_context7__*` | MCP tools loaded via Gemini's MCP integration |

## Model policy mapping

This plugin was authored for the Anthropic Claude family. On Gemini:

- "Opus default" → **Gemini 3.1 Pro** (or whatever is currently the most capable model)
- "Sonnet exception" → **Gemini 3.5 Flash** for the same narrow junior-task taxonomy
- "Never Haiku" → Never use Gemini Flash-Lite or smaller; the project's reasoning bar is high

See `skills/compound-v/phase-3-parallel-opus-dispatch.md` § "Model Selection Taxonomy" for the strict 8-box criteria that gate the cheaper-model carve-out, and `skills/compound-v/routing-policy.md` for the env-aware stances (Balanced / Conservative / Cost-aware). Reviewers are always the top-tier model; the cheaper-model carve-out never applies to a reviewer.

## Slash commands

These are Claude Code `/v:*` commands. On Gemini CLI, invoke the equivalent skill content directly (the commands are thin wrappers over the skill prose).

| Command | Purpose |
|---|---|
| `/v:init` | Detect capabilities (Codex CLI, Context7 MCP), walk through installs, set + save routing stance |
| `/v:orchestrate <plan>` | Materialize a `manifest.yaml` from a plan + routing policy |
| `/v:dispatch <plan\|manifest\|run-id>` | Run the autonomous pipeline (bare plan path still works) |
| `/v:collect <run-id>` | Re-run collect + scope-gate + review |
| `/v:status [run-id]` | Render `state.json` |
| `/v:resume <run-id>` | Reconcile + re-dispatch incomplete jobs |
| `/v:models` | Discover models per backend (`agy models`, curated Codex list, native Claude tiers) and write the tier→model map into `.claude/compound-v.json` |
| `/v:review-plan <plan>` | Optional cross-model (Codex) second opinion on a high-stakes plan before dispatch — read-only, advisory; the orchestrator arbitrates |
| `/v:epic <brief>` | Chain several features into one autonomous, resumable, dependency-ordered build on a single branch; each feature runs the full pipeline in topological order, ending with a cross-feature integration review |
| `/v:archaeology <topic>` | (unchanged) Phase 1A only |
| `/v:remember <query>` | Recall search over `docs/superpowers/**` prose (V-memory) — evidence for planning + review, not a routing input |
| `/v:memory-refresh` | (Re)index the FTS5 recall lane; `--bootstrap` provisions the opt-in dense embeddings venv |
| `/v:onboard` | Scan the repo and build a trusted, citation-verified knowledge base (`docs/superpowers/architecture/*`) plus an `AGENTS.md`/`CLAUDE.md` bridge, behind a human approval gate; `--refresh` re-checks staleness |
| `/v:pr-review [url\|number]` | Deep two-axis (Standards ⊥ Spec) code review of a PR/MR or local diff — review-only, never edits; GitHub (`gh`), GitLab (`glab`), or a hostless local branch |

## Key entry points

- For setup: `README.md`
- For the full skill flow: `skills/compound-v/SKILL.md`
- For the execution contract: `skills/compound-v/execution-manifest.md` + `skills/backend-launcher/SKILL.md`
- For routing: `skills/compound-v/routing-policy.md`
- For state + resume: `skills/compound-v/state-machine.md`
- For "what's in this plugin": `CHANGELOG.md`
- For "it broke": `TROUBLESHOOTING.md`

## Disclaimer

This plugin was built and tested primarily on Claude Code. Gemini compatibility is best-effort. If you find Gemini-specific gotchas, please file an issue.
