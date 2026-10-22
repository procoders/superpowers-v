# 2026 Orchestrator Landscape — General Frameworks — Gap Analysis vs Compound V

**Date:** 2026-07-11. Research agent: general-purpose, WebSearch-driven. Part of the
[2026 orchestrator landscape synthesis](2026-07-11-2026-orchestrator-landscape-synthesis.md).

Research conducted July 2026. Covers the 6 requested frameworks plus the coding-agent-specific
orchestrator niche (closer analogs to Compound V than general business-workflow tools) and
cross-cutting infrastructure (A2A, guardrails, evaluation, cost enforcement).

---

## LangGraph (LangChain)

- **Time-travel + fork-from-checkpoint**: every node transition is checkpointed (Memory/SQLite/Postgres saver); you can rewind execution to any prior checkpoint, inspect state, then either *replay* forward from it or *fork* a new branch with modified state — navigable like a git-commit tree. ([docs.langchain.com](https://docs.langchain.com/oss/python/langgraph/use-time-travel), [Towards AI](https://pub.towardsai.net/langgraph-human-in-the-loop-pausing-reviewing-and-rewinding-your-agent-4028bd05b049))
- **`interrupt()` as a first-class HITL primitive**: a node can pause execution mid-run, hand state to a human for review/edit, and resume — not just an approval gate between phases. ([aipractitioner.substack.com](https://aipractitioner.substack.com/p/human-in-the-loop-agents-steering))
- **Per-node `RetryPolicy` + `TimeoutPolicy`**: declarative exponential backoff with jitter, a predicate distinguishing retryable transient errors (network/5xx) from programming bugs (ValueError/TypeError — not retried by default), plus separate `run_timeout` (total node budget) vs `idle_timeout` (no observable progress). Partial writes from a failed attempt are cleared before retry so state never gets polluted. ([LangChain blog](https://www.langchain.com/blog/fault-tolerance-in-langgraph), [reference.langchain.com](https://reference.langchain.com/python/langgraph/types/RetryPolicy))
- **Supervisor / swarm / network multi-agent topologies with subgraph context isolation**: each specialist agent is a full subgraph with its own state schema — private data is walled off from siblings by construction, not by convention. ([machinelearningplus.com](https://machinelearningplus.com/gen-ai/langgraph-multi-agent-systems-supervisor-swarm-network/))
- **DeltaChannel typed streaming**: Q2 2026 added a delta-based state channel that cuts checkpoint overhead for long-running threads, plus a v2 typed streaming API for structured live progress. ([LangChain resources](https://www.langchain.com/resources/ai-agent-frameworks))

## CrewAI

- **Task guardrails with auto-retry-and-feedback loop**: a function-based or LLM-based validator runs on a task's output *before* it's accepted into the pipeline; on failure it doesn't hard-block — it generates a structured error message and sends the task back to the same agent for another attempt (`guardrail_max_retries`). ([Analytics Vidhya](https://www.analyticsvidhya.com/blog/2025/11/introduction-to-task-guardrails-in-crewai/), [aport.io](https://aport.io/blog/crewai-guardrails-safe-ai-agents-kill-switch-audit-guide/))
- **Flows as an event-driven control layer over Crews**: `@start`/`@listen`/`@router` decorators build explicit state machines that wrap autonomous Crews, giving branching/looping/conditional routing without hand-coding an orchestrator. ([jahanzaib.ai](https://www.jahanzaib.ai/blog/crewai-flows-production-multi-agent-guide))
- **Hierarchical manager-worker with per-task tool scoping**: the auto-assigned manager agent both delegates *and validates* results, and tool access is scoped at the task level for security. ([braincuber.com](https://www.braincuber.com/blog/what-is-crewai-multi-agent-ai-explained))
- Judgment: guardrails trailing observability/error-recovery maturity vs LangGraph is a noted 2026 weakness. ([presenc.ai](https://presenc.ai/research/multi-agent-orchestration-frameworks-2026))

## Microsoft AutoGen / AG2 → now Microsoft Agent Framework (MAF)

- **AutoGen and Semantic Kernel are now in maintenance mode**; Microsoft merged them into **Microsoft Agent Framework**, which hit 1.0 GA April 2, 2026. If researching "AutoGen" in 2026, MAF is the living target. ([devblogs.microsoft.com](https://devblogs.microsoft.com/agent-framework/migrate-your-semantic-kernel-and-autogen-projects-to-microsoft-agent-framework-release-candidate/), [alexbevi.com](https://alexbevi.com/blog/2026/06/18/two-lineages-one-framework-how-autogen-and-semantic-kernel-became-the-microsoft-agent-framework/))
- **GroupChat with pluggable speaker-selection**: 6 modes for who talks next, from round-robin to LLM-driven selection — orchestration logic literally embedded as a state machine over the conversation. ([futureagi.com](https://futureagi.com/blog/what-is-autogen-2026/))
- **HandoffMessage tool-driven routing**: agents route to each other via explicit tool calls rather than a central dispatcher deciding — "Swarm" pattern, localized routing. ([futureagi.com](https://futureagi.com/blog/what-is-autogen-2026/))
- **MagenticOne-style dynamic-replanning orchestrator**: a planner agent tracks progress against an open-ended goal, delegates to specialists (web surfer, file surfer, coder), and *replans when stuck* — built for tasks that don't decompose into a fixed topology upfront. ([futureagi.com](https://futureagi.com/blog/what-is-autogen-2026/))
- MAF adds native **A2A + MCP protocol support**, session-based state, middleware, and telemetry from the Semantic Kernel lineage. ([learn.microsoft.com](https://learn.microsoft.com/en-us/agent-framework/overview/))

## OpenAI Agents SDK (Swarm successor)

- **Swarm is fully retired** — repo redirects to Agents SDK, "no production support." Agents SDK is production-ready, v0.17.1 as of May 2026. ([respan.ai](https://www.respan.ai/articles/openai-agents-sdk-vs-swarm))
- **Guardrails run in parallel with execution, fail-fast**: input/output validators execute concurrently with the agent loop rather than sequentially gating it, so a violation aborts fast without wasting the full turn. ([sureprompts.com](https://sureprompts.com/blog/openai-agents-sdk-prompting-guide))
- **Handoffs as agents-as-tools**: an agent can hand off to a specialist agent as a typed tool call, with the delegating agent choosing when/whether to resume control.
- **Built-in tracing + Sessions** (auto conversation history) + hosted tools (web/file search, code interpreter) + sandbox agents shipped as SDK primitives, not bolt-ons. ([niteagent.com](https://niteagent.com/blog/2026-07-08-openai-agents-sdk-production-guide/))

## Google Agent Development Kit (ADK)

- **Pre-built workflow orchestrator primitives**: `SequentialAgent`, `ParallelAgent`, and a third loop/conditional primitive ship as composable building blocks rather than something you hand-roll every time. ([Google Codelabs](https://codelabs.developers.google.com/codelabs/production-ready-ai-with-gc/3-developing-agents/build-a-multi-agent-system-with-adk))
- **Agents-as-tools + third-party framework bridging**: LangChain/LlamaIndex tools and other agents can be dropped in as ADK tools directly. ([cloud.google.com](https://cloud.google.com/blog/products/ai-machine-learning/build-multi-agentic-systems-using-google-adk))
- **2026 repositioning as a full execution/ops layer**: integrations into GitHub, Jira, MongoDB, observability platforms — ADK 2.0 GA with graph workflows and Vertex AI deployment. ([dailyaiworld.com](https://dailyaiworld.com/blogs/google-adk-20-multi-agent-guide-2026))
- Judgment: this is largely enterprise-deployment/ops surface (Vertex AI hosting, GitHub/Jira connectors) — not orchestration mechanics Compound V is missing for its actual coding-agent job.

## Temporal / Restack / durable-execution ecosystem

- **Deterministic-replay-as-a-service**: workflow code must be deterministic; all non-deterministic work (LLM calls, tool execution) is pushed into `Activities`, which get automatic retry/recovery independent of the workflow's own state. ([byteiota.com](https://byteiota.com/temporal-replay-2026-serverless-workers-ai-agents/))
- **Worker Versioning (GA in Replay 2026)**: pins an already-running workflow instance to the exact worker code version that started it, so a mid-flight upgrade to the orchestrator doesn't silently change semantics for workflows already in progress. ([Temporal blog](https://temporal.io/blog/replay-2026-product-announcements))
- **Serverless Workers / Standalone Activities**: durable workflow state persists for months/years independent of any single running process — the workflow can survive the worker fleet being fully recycled. ([Temporal blog](https://temporal.io/blog/replay-2026-product-announcements))
- **Restack**: same durable-execution philosophy packaged with task queues, concurrency/rate-limit policies, cron, and built-in retry, targeted specifically at agent builders (Kubernetes-native, MCP-integrated). ([restack.io](https://www.restack.io/enterprise))
- The emerging pattern industry-wide is explicitly "LangGraph for agent graph logic, Temporal for durable execution underneath it" — two different layers, not one framework. ([appscale.blog](https://appscale.blog/en/blog/durable-execution-llm-agents-temporal-langgraph-checkpointing-2026))

## Coding-agent-specific orchestrators (closest analogs to Compound V)

This niche is where the sharpest, most directly-comparable gaps live — general business-workflow frameworks above are a weaker match for a coding orchestrator than these:

- **Port/resource collision avoidance**: Emdash injects a unique `$EMDASH_PORT` per parallel task so N concurrently-running worktrees' dev servers/test runners don't collide on default ports. A concrete, coding-specific infra hazard that has nothing to do with git-diff scope. ([augmentcode.com](https://www.augmentcode.com/tools/open-source-agent-orchestrators))
- **Post-merge CI-failure recovery loop**: Composio's orchestrator watches CI after merge, auto-dispatches a fix job on failure, and only escalates to a human after N automatic retries — closing the loop between "passed local review gate" and "actually green in CI." ([augmentcode.com](https://www.augmentcode.com/tools/open-source-agent-orchestrators))
- **Deterministic, zero-LLM-token scheduling** (Bernstein): dependency/ordering decisions made in plain Python, not by an LLM — Compound V's epic-mode `depends_on` topological ordering already matches this philosophy; this is validation, not a gap.
- **Hard per-agent token/turn budget with auto-pause + kill criteria**: e.g. auto-pause at 85% of budget, kill after 3+ stuck iterations — enforcement, not just post-hoc reporting. ([addyosmani.com](https://addyosmani.com/blog/code-agent-orchestra/))
- **AGENTS.md "compound learning" file, human-gated**: a terse, curated file every worker reads at session start and can propose additions to via a `REFLECTION.md` pattern, gated on human approval before merging into the canonical file. Notably, the research behind this pattern found **AI-authored versions of this file reduce agent success rate by ~3%** — a concrete empirical argument for keeping such files human-curated. ([addyosmani.com](https://addyosmani.com/blog/code-agent-orchestra/))
- **Beads pattern (Gastown)**: immutable, git-backed decision records with full provenance, queried structurally rather than via vector search — this is close to what Compound V's own committed audit trail (`docs/superpowers/execution/**`, `epic-state.json`, fixed in v2.6.4) already does; also validation, not a gap.
- **Peer-to-peer inter-agent messaging** (Agent Teams pattern): "Backend tells Frontend the API contract without the lead as intermediary" — deliberately *not* how Compound V works (disjoint-partition-by-design avoids needing this), flagged below as a design tension, not a straightforward import.
- Devin's 2026 rebrand made **fleet management** (many Devins, coordinated) the headline feature, and Cursor 3 runs up to 8 agents across isolated worktrees — both converging on the same worktree-isolation architecture Compound V already uses. ([scopir.com](https://scopir.com/posts/multi-agent-orchestration-parallel-coding-2026/))

## Cross-cutting infrastructure

- **A2A protocol** (Agent2Agent, Linux Foundation-governed): a standard wire protocol (HTTP/SSE/JSON-RPC 2.0) + "Agent Cards" for cross-vendor agent discovery/delegation, now in 150+ orgs and all 3 major clouds. ([niteagent.com](https://niteagent.com/blog/a2a-protocol-guide-2026/), [developers.googleblog.com](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/))
- **Cost enforcement vs monitoring**: 2026 industry framing draws a hard line — monitoring is asynchronous (you find out after the spend happened); enforcement intercepts *before* the next call and kills the session at a ceiling. ([toriihq.com](https://www.toriihq.com/articles/seven-tools-for-tracking-ai-token-usage-across-vendors))
- **Golden-dataset regression CI for the agent system itself**: run a growing set of known-good/known-bad cases on every PR to the orchestrator, score with a calibrated LLM-judge, block merge on regression — treating the orchestrator's own reviewer/gate logic as a system under test, not just the tasks it dispatches. ([confident-ai.com](https://www.confident-ai.com/blog/llm-agent-evaluation-complete-guide))
- **Claude Agent SDK** (Anthropic's own, renamed from Claude Code SDK, Sept 2025): ships subagents, hooks (PreToolUse/PostToolUse/Stop/SessionStart/etc.), skills, MCP, and — as of June 15, 2026 — a dedicated monthly Agent SDK credit pool separate from interactive usage. Since Compound V sits directly on top of this, most of its primitives (hooks, subagents, skills) are already the substrate Compound V builds on, not a gap. ([code.claude.com](https://code.claude.com/docs/en/agent-sdk/overview), [totalum.app](https://www.totalum.app/blog/claude-agent-sdk-totalum-2026))

---

## Candidate gaps for Compound V, ranked by relevance

1. **CI-failure-after-merge auto-recovery loop, bounded retries, then human escalation.** The review gate validates against the local worktree build; real CI can still go red post-merge for reasons the gate never saw (flaky infra, environment drift, downstream integration). A bounded "CI red → auto-dispatch fix job → re-gate → escalate after N failures" loop directly extends Compound V's existing scope-gate/review-gate machinery. Concrete, coding-specific, high value.

2. **Hard per-job token/turn budget with proactive kill, not just liveness detection.** V2.5.0 shipped hang detection (alive vs. hung); it does not appear to catch "alive, making progress, but burning unbounded tokens/turns." An explicit budget ceiling with auto-pause + kill-after-N-stuck-iterations closes a distinct failure mode and fits the project's "never fabricate metrics, but do enforce real ones" ethos.

3. **Lightweight per-job guardrail-and-retry loop, distinct from the full three-pass Review Gate.** CrewAI's task guardrail pattern (validate → structured feedback → same-agent retry) operates at a cheaper granularity than re-running spec-reviewer's three passes. Could reduce full-review-gate churn for a job that's almost right, before it even reaches collection.

4. **Port/resource collision guard for concurrently-running worktree dev servers/test runners.** A near-zero-cost, purely coding-specific fix (inject a unique port per job the way Emdash does) that scope-gate's file-path enforcement doesn't currently address at all.

5. **Golden-dataset regression CI for Compound V's own gate agents** (partition-reviewer, spec-reviewer, scope-check.py) — a small, versioned set of known PASS/FAIL manifests/diffs re-run whenever prompts or routing change, so calibration drift in the reviewers themselves gets caught mechanically instead of by incident (per the project's own MEMORY.md history of Codex catching gaps after the fact).

6. **Mid-job HITL interrupt for a designated risky step**, not just phase-boundary approval gates (partition-review before dispatch, review gate after collection). LangGraph's `interrupt()` pattern — pause a running worker at a specific point, show state, resume — would let a manifest flag a specific job step (e.g., a schema migration) as needing sign-off mid-execution rather than only before/after the whole job.

7. **Worker/prompt version pinning across a resumed epic.** Epic mode spans long, multi-day, multi-feature builds; Temporal's Worker Versioning (pin a running workflow to the code version that started it) suggests a real edge case worth checking: does `/v:resume` re-dispatch an interrupted job against whatever manifest-materialization/prompt logic is current at resume time, or the version that was current when the job started? Worth an explicit audit, not necessarily a big build.

8. **Scoped mid-flight write-allowlist amendment request, instead of hard block-and-never-merge.** A narrow middle ground between Compound V's current binary scope gate and full dynamic replanning (MagenticOne-style) — for the rare legitimately-emergent case, let a job request an amendment to its `write_allowed` list, subject to the same reviewer approval a manifest gets, rather than either silently allowing scope creep or unconditionally discarding otherwise-good work.

**Explicitly not recommended to import** (judged as belonging to general business-workflow orchestration, not this niche):
- Blackboard/shared-scratchpad architecture — conflicts with the deterministic-upfront-partition design that makes the git-diff scope gate possible.
- Full A2A protocol adoption — solves cross-vendor/cross-org agent discovery; Compound V's bespoke per-backend adapters already work and a standard wire protocol adds surface area for a benefit (external third parties writing new adapters) that hasn't been asked for.
- N-way multi-model voting/consensus — Compound V's Codex-second-opinion adversarial review already covers the reliability-via-disagreement idea at a fraction of the cost; full committee/debate patterns are for answer-quality-critical research/business agents, not code-diff review.
- Peer-to-peer inter-agent messaging mid-dispatch — directly opposed to the disjoint-partition invariant; if two jobs need to share an interface contract, that belongs in the manifest at materialization time (baked into each job's prompt), not as live cross-worker chatter during execution.
- ADK-style hosted deployment/ops platform (Vertex AI hosting, GitHub/Jira enterprise connectors) — orthogonal to being a Claude Code plugin; not a capability gap in the orchestration logic itself.
