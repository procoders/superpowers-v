# 2026 AI Coding-Agent Orchestration Landscape — Research Report

**Date:** 2026-07-11. Research agent: general-purpose, WebSearch-driven. Part of the
[2026 orchestrator landscape synthesis](2026-07-11-2026-orchestrator-landscape-synthesis.md).

Research conducted July 2026. Each section notes concrete mechanism + whether Compound V already has an equivalent or structurally lacks it.

---

## 1. Devin / Cognition Labs

- **Devin 2.0 / parallel Devins** (Feb 2026): tasks get decomposed and delegated to a team of managed Devins, each in its own **isolated cloud VM**, running truly in parallel; each has its own interactive cloud IDE. Coordination model is explicitly **map-reduce-and-manage**: a manager splits work, children execute, manager synthesizes. ([Cognition blog](https://cognition.com/blog/devin-2))
- **"Multi-Agents: What's Actually Working"** (Cognition's own research, important): Cognition explicitly **rejects naive parallel-writer swarms**. Their finding: "actions carry implicit decisions" — style, edge-case handling, patterns — that conflict when multiple agents write concurrently without a hard partition. Their production-validated patterns instead are: (1) fresh-context reviewer agents (isolation improves bug-catch rate, ~2 bugs/PR, 58% severe), (2) a "smart friend" consult pattern (cheap primary + frontier-model consultant), (3) manager-coordinated delegation with **centralized writes**. ([cognition.com/blog/multi-agents-working](https://cognition.com/blog/multi-agents-working))
- **Devin Fusion**: not a best-of-N racer. Two co-resident agents — a frontier "decision-maker" and a cheaper "sidekick" executor — with a lightweight classifier deciding mid-task when to switch models (switches happen for free during context-compaction cache misses anyway). 88% of merged PRs were fully router-driven; 35–41% cost reduction at frontier-level quality. ([cognition.com/blog/devin-fusion](https://cognition.com/blog/devin-fusion))
- **Devin verification**: writes an explicit test plan grounded in source, then — notably — uses **computer-use** to actually run the app, click through it, and visually confirm the change works, not just pass unit tests. "Devin Review" then closes the loop by fixing findings until the diff comes back clean. ([cognition.ai/blog/testing-development](https://cognition.ai/blog/testing-development))
- **Windsurf ⇒ Devin Desktop**: Cognition bought Windsurf (~$250M, Dec 2025) after the OpenAI $3B deal collapsed on Microsoft's contractual rights; rebranded to Devin Desktop June 2, 2026. New **Agent Command Center** — a Kanban board (Running / Waiting for Review / Done) surfacing every local and cloud agent in one place — is a telemetry/observability UI Compound V has no analog for. ([digitalapplied.com](https://www.digitalapplied.com/blog/windsurf-becomes-devin-desktop-ide-migration-2026), [lumichats.com](https://lumichats.com/blog/openai-windsurf-acquisition-what-it-means-developers-ai-coding-2026))

**vs Compound V**: The map-reduce-manager pattern and Cognition's own anti-parallel-swarm finding is a strong *external validation* of Compound V's disjoint-file-partition design — Cognition arrived independently at "don't let multiple writers touch overlapping implicit decisions" as the failure mode Compound V's Partition Map + git-diff scope gate is built to prevent. Gaps: computer-use/E2E runtime verification, and a Kanban-style live dashboard.

## 2. OpenAI Codex CLI — native multi-agent

- Native subagents (`/agent` command family), config: `agents.max_threads` (default **6** concurrent), `agents.max_depth` (default 1, no grandchildren). Subagents **inherit parent sandbox policy** (workspace-write / read-only / full-access) and, as of v0.115.0 (Mar 2026), reliably inherit sandbox+network rules including project-profile layering — "stable enough for CI use." ([learn.chatgpt.com/docs/agent-configuration/subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents))
- **Isolation**: each spawned subagent runs in its own **git worktree** (auto-created by the subagent runtime), same primitive Compound V's Codex adapter already drives externally. ([codex.danielvaughan.com](https://codex.danielvaughan.com/2026/03/26/codex-cli-worktree-parallel-development/))
- **Scope enforcement**: important finding — Codex's own scope constraints are **prompt-based, not deterministic**: "Codex respects scope constraints better than expected — **but only if explicit**" (i.e., you tell it "only touch src/auth/*" and it usually complies, no independent verification). There is **no git-diff-derived gate** analogous to Compound V's `compound-v-scope-check.py`. ([inventivehq.com](https://inventivehq.com/knowledge-base/openai/how-to-use-git-worktrees))
- Result collection: orchestrator waits for all requested subagent threads, returns a consolidated response; `/agent` lets a human inspect individual threads mid-flight.

**vs Compound V**: Codex's native orchestration has grown real teeth (worktree isolation, thread caps, sandbox inheritance) since Compound V started headlessly driving `codex exec`, so the low-level primitives now overlap more. But Codex's scope enforcement is still self-reported/prompt-compliance, not git-derived — **Compound V's "never trust model self-report" scope gate remains a genuine structural differentiator**, not a redundant reinvention. Compound V's cross-vendor fan-out (Claude+Codex+agy+Cursor in one run) is also something Codex's own orchestrator, scoped to Codex-only subagents, cannot do.

## 3. Cursor — Composer / Background Agents / Bugbot

- **Cursor 3 / Agents Window**: parallel agents run on local git worktrees or remote cloud VMs; UI reorganized around *agents* not *files*. Background Agent clones the repo into a cloud VM, agent works a dedicated branch, result lands as a PR; up to **8 parallel agents** fan-out for high-volume homogeneous work (dependency bumps, test backfills, same-change-across-services). ([digitalapplied.com](https://www.digitalapplied.com/blog/cursor-3-deep-dive-agents-composer-review-2026), [baeseokjae.github.io](https://baeseokjae.github.io/posts/cursor-3-guide-2026/))
- **Composer 2.5** (May 18, 2026): Cursor's own RL-trained frontier model for the agent loop, 79.8% SWE-Bench Multilingual, ~1/10 the cost of Opus 4.7 (80.5%).
- **Bugbot → "fixer"** (Feb 2026): reviews PRs; on finding a real bug it **autonomously spins up its own cloud agent, writes and tests a fix, and posts it directly on the PR** — a closed-loop, CI-triggered, *post-merge-review-driven* fix pipeline. ~80% resolution rate, ahead of competing review bots. ([aitoolanalysis.com](https://aitoolanalysis.com/cursor-ai-review/))

**vs Compound V**: The Bugbot fixer loop is a **structural gap** — Compound V's Review Gate is pre-merge only, run inside the orchestrated session; nothing watches a merged/open PR asynchronously and files fix-PRs on review comments or CI failure the way Bugbot does.

## 4. OpenHands (formerly OpenDevin)

- **OpenHands Enterprise / Agent Control Plane** (May 2026): centralized coordination for "hundreds of agents across an organization" — workflows defined once, executed across many repos in parallel, with built-in scheduling, retries, state management, and a plugin marketplace. ([openhands.dev/blog](https://www.openhands.dev/blog/openhands-enterprise-agent-control-plane))
- **Architecture**: a main planning agent that dynamically spawns short-lived sub-agents (supervisor-forks-workers), event-sourced state with **deterministic replay**, immutable agent config, typed tool system with MCP. ([docs.openhands.dev/sdk/arch/agent](https://docs.openhands.dev/sdk/arch/agent))

**vs Compound V**: Deterministic-replay event sourcing is stronger crash-recovery machinery than Compound V's state.json + git-wins reconciliation for *exact* step-by-step replay, but Compound V's git-wins approach is simpler and arguably more robust against non-deterministic LLM output (replay assumes determinism that doesn't hold across LLM calls). Org-wide control-plane scheduling across "hundreds of repos" is out of Compound V's single-repo-run scope by design.

## 5. SWE-agent / SWE-bench ecosystem

- **mini-swe-agent**: radical simplification (~100 lines Python, no tool-calling schema, no stateful shell) scoring 74%+ on SWE-bench Verified; now in production at Meta, NVIDIA, IBM, Anyscale — industry trend toward *minimal scaffolding, model does the reasoning*. ([swe-agent.com](https://swe-agent.com/latest/))
- **Agentless**: a deliberate counter-architecture — no iterative tool loop at all, one-shot structured localization→repair→validation pipeline, 34.2% at a fraction of agentic token cost.
- **SWE-bench Pro**: harder, enterprise-realistic benchmark (1,865 problems, 41 actively-maintained repos) superseding the saturating original SWE-bench. ([simonwillison.net](https://simonwillison.net/2026/Feb/19/swe-bench/))

**vs Compound V**: Not a direct orchestration comparable — these are single-agent-loop research artifacts/benchmarks, not multi-backend dispatch systems. Relevant mainly as a reminder that Compound V's manifest-driven approach sits at the opposite end of the complexity spectrum from mini-swe-agent's minimalism; no structural gap here.

## 6. Anthropic — Claude Code subagents & Claude Agent SDK

- **Dynamic Workflows** (June 2026, Claude Code ≥ v2.1.154): the lead agent **writes a JavaScript orchestration script** that a runtime executes in the background, fanning out **10s to 100s of parallel subagents** (16 concurrent, hard cap 1,000/run) while keeping the *lead* agent's own context window clean — the script holds loop/branching/intermediate state, not the conversation. Real example: Bun's Zig→Rust port, 750k lines, 11 days, 99.8% of existing tests passing. ([claude.com/blog](https://claude.com/blog/introducing-dynamic-workflows-in-claude-code), [code.claude.com/docs/en/workflows](https://code.claude.com/docs/en/workflows))
- **"Performance Outcomes"**: a separate grader agent sends subagent output back for revision until it clears a rubric — an automated quality-gate loop baked into the SDK itself.
- Claude Agent SDK usage now **metered separately** from interactive Claude Code billing (from June 15, 2026) — direct evidence of the industry-wide cost-governance pressure (see §Cost below).

**vs Compound V**: Dynamic Workflows is architecturally close to what Compound V's `parallel-dispatcher` + manifest does, but native and script-driven rather than manifest/YAML-driven, and it's homogeneous (Claude-only subagents) vs Compound V's explicit multi-vendor fan-out. Dynamic Workflows' scale ceiling (1,000 subagents) is far beyond Compound V's typical 4-6 concurrent batches — worth knowing as a scale reference, not necessarily a gap since Compound V's batching is intentionally small (git-diff scope gate per job, human-reviewable batches).

## 7. Amp (Sourcegraph → spun out as independent Amp Inc.)

- Spun out as standalone company in 2026 (Quinn Slack now Amp CEO). Four "effort" agent modes — low/medium/high/ultra. Plugin system: "create agents, run them once, keep talking to their threads." Terminal-first, whole-codebase orchestration. ([sourcegraph.com/amp](https://sourcegraph.com/amp?gad_source=1&amp;gad_campaignid=22948010551), [ainativedev.io](https://ainativedev.io/news/sourcegraph-spins-out-ai-coding-agent-amp-as-a-standalone-company))

**vs Compound V**: The "effort tier" knob (low→ultra) parallels Compound V's deep/standard/light routing tiers conceptually, but Amp's is a single-model dial, not cross-backend routing. No structural gap identified beyond what's already covered elsewhere.

## 8. Replit Agent 4

- Launched March 2026 ($400M Series D, $9B valuation). **Parallel forking of a single task**: splits one task into concurrent forks — auth, DB, backend, frontend, testing progress simultaneously, then presumably reconciled by the parent agent. Predecessor Agent 3 ran autonomously up to 200 min/session. ([replit.com/agent4](https://replit.com/agent4))

**vs Compound V**: This is a same-task-decomposed-into-parallel-subsystems pattern, closer to Compound V's own Partition Map + parallel dispatch than to best-of-N racing. Structurally similar idea, but Replit's is single-vendor/single-model, cloud-hosted, and consumer/app-building oriented rather than an explicit disjoint-file-contract with a deterministic scope gate.

## 9. Factory.ai — Droids

- **Coordinator-dispatches-to-specialist-droids** model: Writer → Reviewer → Tester → Docs → Deployer, explicit role boundaries (not one generalist). #1 on Terminal-Bench. ([factory.ai/news/terminal-bench](https://factory.ai/news/terminal-bench))
- **Droid Computers** (Apr 2026): *persistent* machines (cloud or the user's own) that preserve full dev-environment state — filesystem, config, credentials, local services, **process memory** — across sessions, so a droid resumes exactly where it left off instead of re-provisioning. ([factory.ai/news/droid-computers](https://factory.ai/news/droid-computers))

**vs Compound V**: The specialist-role pipeline (Writer/Reviewer/Tester/Docs/Deployer) is close in spirit to Compound V's phase structure (archaeology/domain/doc-validator → dispatch → scope-gate → spec-reviewer), but Factory chains it as a persistent, resumable *SDLC* pipeline rather than a single per-run manifest. Droid Computers' persistent-environment-across-sessions concept (no re-provisioning cost) is something Compound V's worktree-per-job model explicitly does *not* do — each job gets a fresh worktree at HEAD (a deliberate correctness tradeoff per the v2.6.1 fix, but it does cost re-provisioning time/tokens on every dispatch).

## 10. GitHub Copilot (2026 "agent-native desktop")

- **Sandboxes now first-class**: local sandboxes (restricted filesystem/network/process access, included in standard seat) and **cloud sandboxes** (`copilot --cloud`, fully isolated ephemeral Linux VM hosted by GitHub). ([github.blog/changelog](https://github.blog/changelog/2026-06-02-cloud-and-local-sandboxes-for-github-copilot-now-in-public-preview/))
- **Copilot App**: each agent session gets its own isolated git worktree so multiple agents can work the same repo in parallel without collision; an orchestrator agent can spawn parallel subagents for discrete workstreams (lint, test-gen, docs, **security review**) running simultaneously. ([digitalapplied.com](https://www.digitalapplied.com/blog/github-copilot-app-agent-native-desktop-orchestration-2026))

**vs Compound V**: Notably, GitHub's own architecture now includes a **security-review subagent as a first-class parallel workstream** — this is direct evidence for the "security scanning integration" gap flagged below; Compound V has no equivalent job-type in its manifest schema.

## 11. Google Jules

- GA at I/O 2026. Clones repo into a cloud VM (no local sandbox needed); **15 concurrent tasks**, "submit ten tasks, come back to ten PRs" workflow — closer to fire-and-forget batch dispatch than Compound V's dependency-aware, scope-gated batches. Gemini 2.5 Pro-backed. ([blog.google](https://blog.google/innovation-and-ai/models-and-research/google-labs/jules/))

**vs Compound V**: No disjoint-partition contract or scope gate evident — Jules's 15-task concurrency is throughput-oriented, not correctness-oriented (no mention of conflict prevention across the 15 parallel PRs on the same repo).

---

## Cross-Cutting Themes

### A. AI code-review bots (PR-review-loop automation)
CodeRabbit (largest install base, 2M+ repos, cross-VCS), Greptile (full-repo code-graph indexing, multi-hop dependency tracing, highest catch rate 82% in benchmarks but also highest false-positive rate), Graphite (stacked-PR workflow + bundled review, lowest catch rate 6% but &lt;5% negative feedback — optimized for low-noise), Cursor Bugbot (58% catch rate, **only one with an autonomous fix-loop**). ([greptile.com/content-library](https://www.greptile.com/content-library/best-ai-code-review-tools))
**Gap for Compound V**: none of these are "orchestrators" — they're PR-comment bots — but the **Bugbot-style closed fix-loop triggered by CI/PR-review, not by the original dispatch run**, is a pattern Compound V's pre-merge-only Review Gate doesn't cover.

### B. Sandboxing/container strategy
2026 consensus stack: **Docker** (fast, &lt;1s, shares host kernel, weakest isolation) → **gVisor** (userspace syscall interception, container-speed + partial hardening) → **Firecracker/microVMs** (separate kernel, ~125ms boot, &lt;5MB overhead, strongest isolation, powers AWS Lambda/E2B/Modal). Recommendation pattern: Firecracker for long-lived tenant workloads, gVisor for low-trust research tooling, Docker for cached build steps; **Codex CLI's built-in sandbox is called out as "best built-in sandbox... OS-level isolation, network disabled by default."** ([amux.io](https://amux.io/guides/ai-agent-sandboxing/), [northflank.com](https://northflank.com/blog/how-to-sandbox-ai-agents))
**Gap for Compound V**: Compound V relies entirely on git-worktree isolation + each backend's own sandbox (Codex's workspace-write, agy/Cursor's weaker or absent write-confinement — already flagged internally in AGENTS.md as a known caveat). It has no microVM/gVisor layer of its own. This matters specifically for the already-documented agy/Cursor "opt-in, lower-trust" backends, where the scope gate can *detect* but not *prevent* an out-of-worktree side effect.

### C. Cost / token budget controls — the dominant 2026 storyline
TechCrunch (June 2026): "the token bill comes due" — Uber blew through its entire 2026 AI-coding budget by April; Microsoft revoked Claude Code licenses months after enabling them; per-developer token consumption rose ~18.6x in nine months; agents burn ~50x more tokens than single-turn chat. Industry response: per-user/team token visibility with 50%/80% alerts, default-to-cheap-tier with approval-gated frontier-model escalation, **session cost caps**, circuit breakers for loops, anomaly detection for runaway agent loops. Linux Foundation is standing up a "Tokenomics Foundation." ([techcrunch.com](https://techcrunch.com/2026/06/05/the-token-bill-comes-due-inside-the-industry-scramble-to-manage-ais-runaway-costs/), [gartner.com](https://www.gartner.com/en/newsroom/press-releases/2026-06-24-gartner-predicts-ai-coding-costs-will-surpass-average-developer-salary-by-2028-as-token-consumption-surges))
**Gap for Compound V**: This is the single most timely, most concrete gap. Compound V is "Opus by default" across a 4-6-way parallel multi-backend fan-out — exactly the profile the industry is now flagging as a runaway-cost risk — yet its documented failure-classification/circuit-breaker is about backend *reliability* (retries/backoff on failure), not backend *spend* (no evidence of a session/run token or dollar cap, no alert threshold, no anomaly detector for a job that's looping).

### D. Verifying AI-written code beyond scope-gating
- **Mutation testing** is becoming a default PR-workflow gate: coverage alone is proven insufficient (100% line/branch coverage scored 4% mutation score in a cited example — missed leap-year edge case). Gartner recommends mutation-guided test-suite-hardening integrated into PR workflows; one case study showed feeding surviving mutants back to the coding agent raised mutation score 70%→78% on the next attempt. Suggested thresholds: 70% critical-path / 50% standard / 30% experimental. ([augmentcode.com/guides](https://www.augmentcode.com/guides/mutation-testing-ai-generated-code))
- **Security (SAST) integration is moving in-loop**: Harness "Secure AI Coding" scans at generation time inside Cursor/Windsurf/Claude Code; Snyk's 2026 agents do "reachability triage" (only surface exploitable findings) and "Agent Fix" autonomously generates+validates security fixes pre-commit. GitHub Copilot App already runs a security-review subagent as a parallel workstream (see §10). ([dryrun.security](https://www.dryrun.security/blog/top-ai-sast-tools-2026), [getsecureslate.com](https://getsecureslate.com/blog/the-7-best-sast-solutions-for-2026-balancing-speed-accuracy-and-security-controls))
**Gap for Compound V**: Confirmed real gap on both counts. The three-pass Review Gate (spec/quality/integration) checks correctness-against-spec and regressions, but there's no evidence of (a) a mutation-testing pass to catch weak/hollow AI-written test suites, or (b) a SAST/security-scan job type in the manifest schema. Both are cheap to bolt on as an optional manifest job (`verify: mutation_test` / `verify: sast_scan`) rather than a new architecture.

### E. Telemetry / observability
2026 leaders: Braintrust (purpose-built trace DB, per-trace accuracy/duration/token-count), LangSmith, Arize Phoenix, Datadog LLM Observability; Windsurf's Agent Command Center gives a Kanban view across all running/local/cloud agents. ([augmentcode.com/tools](https://www.augmentcode.com/tools/best-ai-agent-observability-tools), [confident-ai.com](https://www.confident-ai.com/knowledge-base/compare/best-ai-agent-observability-tools-2026))
**Gap for Compound V**: `/v:status` renders `state.json` (run/job status) but there's no per-job token/cost/latency trace export and no cross-run dashboard — a deliberate minimalism choice per the "no daemon, no fabricated metrics" charter, but genuinely thinner than what teams now expect for FinOps accountability, especially combined with gap C above.

### F. Human approval checkpoints
2026 consensus pattern is **milestone-gate**, not per-edit approval: agents handle retries/CI failures autonomously, humans approve at PR/merge time; agents are expected to "flag uncertainty rather than blindly attempt," escalating ambiguous or high-stakes decisions. ([webfuse.com](https://www.webfuse.com/blog/agentic-coding-in-2026))
**vs Compound V**: Already matches this pattern closely — partition-reviewer/spec-reviewer gates + `/v:dispatch` HALT-on-BLOCKED is milestone-gate style, not per-edit. No gap.

### G. Best-of-N / test-time-compute racing
Academic: "Scaling Test-Time Compute for Agentic Coding" (arXiv 2604.16529, Apr 2026) introduces **Recursive Tournament Voting (RTV)** — recursively narrows a population of parallel rollout summaries through small-group comparisons (beyond naive best-of-N) — combined with Parallel-Distill-Refine; lifts Claude Opus 4.5 SWE-bench Verified 70.9%→77.6%. ([arxiv.org/abs/2604.16529](https://arxiv.org/abs/2604.16529))
Practically, this shows up as "container-per-attempt, race N attempts on the identical task, keep the diff that passes tests" in some tooling (Cursor's same-prompt parallel agents, some CI racing setups). **But** recall Cognition's own finding (§1) that racing full-task parallel writers causes implicit-decision conflicts.
**vs Compound V**: Compound V has no racing mode at all — its parallelism is 100% disjoint-partition (different files), never same-task racing. This is a legitimate, currently-absent capability, but should be scoped narrowly (e.g., only for a single hard/ambiguous file inside an otherwise-disjoint partition) rather than adopted wholesale, given Cognition's caution applies exactly to naive racing.

### H. Circuit breaker / failure classification patterns (industry framing)
Standard 2026 pattern: classify failure as transient/permanent/critical → retry-with-backoff / trip circuit breaker / fallback / escalate-to-human; fallback hierarchy = alternative specialist agent → simpler rule-based agent → cheaper LLM → human queue; "Agent Tennis" detection (two agents disagreing &gt;3 turns without new state = trip). ([cogentinfo.com](https://cogentinfo.com/resources/when-ai-agents-collide-multi-agent-orchestration-failure-playbook-for-2026))
**vs Compound V**: Compound V already documents "failure classification + circuit-breaker/backoff per backend" — matches this pattern. No gap, but worth explicitly checking Compound V's circuit breaker covers the cost dimension too (see gap C), and whether it has an "Agent Tennis"-style stuck-loop detector for cross-model review rounds (Compound V does multi-round Codex review "to convergence" — worth confirming there's a hard round cap, not just implicit good behavior).

### I. Cross-model adversarial review
Now a named, published pattern (not just a hunch): independent second-vendor model reviews a diff **without seeing the first model's reasoning**, forcing genuine independence; "Optimizer vs Skeptic" dual-agent debate loops where only consensus issues auto-fix. ([digitalapplied.com](https://www.digitalapplied.com/blog/dual-model-content-review-claude-gpt-5-6-2026), [github.com/alecnielsen/adversarial-review](https://github.com/alecnielsen/adversarial-review))
**vs Compound V**: Already has this via `/v:review-plan` (Codex reviews Claude's plan/code, orchestrator arbitrates) — matches the pattern. Worth checking Compound V's reviewer explicitly withholds the builder's chain-of-reasoning (diff-only) as the cited "key constraint" for forcing true independence — if it currently passes full context, that's a small tightening opportunity, not a structural gap.

### J. Agent memory frameworks
Mem0 (hierarchical extraction, temporal/multi-hop retrieval gains), Cognee (remember/recall/improve/forget API), AgentMemory (auto-capture via hooks, zero-config local-first) — all vector-DB or hybrid, cross-session semantic memory of *decisions and provenance*, not just docs search. ([mem0.ai/blog](https://mem0.ai/blog/state-of-ai-agent-memory-2026))
**vs Compound V**: V-memory (FTS5 + optional local embeddings, evidence-only, no vector-DB service) is a deliberately lighter-weight equivalent already covering the core need; the gap is narrow — these frameworks add **auto-capture-via-hooks** (memory written automatically as decisions happen, not just indexed from committed docs) and **temporal/multi-hop query** which V-memory doesn't claim. Low priority since it conflicts with the "no daemon" charter.

---

## Ranked Candidate Gaps for Compound V

1. **Token/dollar budget governor** — session/run cost caps, 50%/80% alert thresholds, and a spend-based circuit breaker (not just reliability-based) for the multi-backend Opus-by-default fan-out. This is the single most time-pressured gap given the 2026 "token bill comes due" narrative and Compound V's inherently cost-amplifying architecture (4-6 concurrent Opus-tier workers).
2. **Verification-beyond-scope-gating**: add optional mutation-testing and SAST-scan job types to the manifest schema (industry has normalized both as in-loop PR gates in 2026; GitHub Copilot App already runs security-review as a parallel workstream natively).
3. **Cost/telemetry attribution surface** — extend `/v:status`/state.json with per-job token count, latency, and $-cost, even without a full observability daemon; complements gap 1 and is cheap given state.json already exists.
4. **Stronger sandbox isolation for lower-trust backends** (agy, Cursor) — a microVM/gVisor option to close the already-known "can detect but not prevent out-of-worktree side effects" caveat, rather than relying solely on worktree isolation + the git-diff scope gate.
5. **Post-merge / CI-triggered fix-loop** (Bugbot-style) — currently Compound V gates pre-merge only; an opt-in async watcher that reacts to CI failures or human PR comments after merge is a distinct, currently-absent capability.
6. **Narrowly-scoped best-of-N racing** for single hard/ambiguous files within an otherwise-disjoint partition — informed by RTV/PDR test-time-compute research, but deliberately scoped to avoid the implicit-decision-conflict failure mode Cognition's own research flags against naive full-task racing.
7. **Optional runtime/computer-use verification hook** in the Review Gate (e.g., wiring the marketplace's own `run`/`verify` Playwright-driven skills into a manifest job's acceptance check) — closes the gap with Devin's "actually click through the app" verification step.

Items explicitly checked and found **not** to be gaps (Compound V already has a comparable mechanism): human milestone-gate approval model, cross-model adversarial review, crash-resume/state reconciliation, backend-reliability circuit breaking, and lightweight local-first recall memory.
