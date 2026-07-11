# Compound V vs. 2026 Agent-Infrastructure Standards — Research Report

**Date:** 2026-07-11. Research agent: general-purpose, WebSearch-driven. Part of the
[2026 orchestrator landscape synthesis](2026-07-11-2026-orchestrator-landscape-synthesis.md).

Sources: parallel research plus direct searches/fetches, cross-checked against each other. All dates below reflect claims made in sources published between late 2025 and July 2026.

---

## 1. Agent-to-Agent Protocols (Google A2A)

**What it is.** A2A standardizes four things: **Agent Cards** (capability discovery documents), **task lifecycle** (delegate → execute → complete, with multi-turn messaging), and **structured artifact exchange** between independently-operated agents. It's explicitly designed to complement, not replace, MCP: MCP connects an agent to tools/data; A2A connects one agent to *another agent* treated as an autonomous, independently-deployed actor, often across organizational/trust boundaries. [IBM: What Is A2A Protocol?](https://www.ibm.com/think/topics/agent2agent-protocol) · [StackOne: MCP vs A2A](https://www.stackone.com/blog/mcp-vs-a2a-protocol/)

**Maturity/adoption — real traction, but self-reported at the impressive-sounding layer.** Google donated A2A to the Linux Foundation in June 2025 under its Agentic AI Foundation. The Foundation's own April 2026 one-year press release claims 150+ supporting organizations (up from 50+), 22,000+ GitHub stars, SDKs in five languages, and a v1.0 stable spec release (multi-protocol support, multi-tenancy, OAuth-hardened security). Named adopters: Microsoft (Azure AI Foundry, Copilot Studio), AWS (Bedrock AgentCore Runtime), plus Cisco/IBM/Salesforce/SAP/ServiceNow listed as "supporters." [Linux Foundation press release](https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year) · [Google donates A2A to LF](https://developers.googleblog.com/en/google-cloud-donates-a2a-to-linux-foundation/)

Skeptical counterweight: an independent analysis explicitly warns "'supported by' organizations is not equivalent to widespread developer adoption... the real test remains retention in production after the first real operational incident" — not yet demonstrated. [Glukhov: A2A in 2026, Reality vs. Hype](https://www.glukhov.org/ai-systems/comparisons/a2a-protocol-2026-adoption). Treat the 150-orgs / 22k-stars numbers as foundation-reported momentum, not independently audited production penetration.

**Relevance to Compound V — clean non-fit, not a gap.** Every direct source comparing A2A to single-process orchestration agrees it solves a different problem than Compound V has. Compound V is one human operator, one machine, one git repo, subprocess/subagent workers in local worktrees coordinated via `state.json` and `git diff`. Glukhov's piece states it plainly: "if everything runs inside one application and the components are not independently deployable, A2A is unnecessary overhead." [Augment Code: A2A vs MCP for Coding Tool Interop](https://www.augmentcode.com/guides/a2a-vs-mcp) agrees — A2A matters "when multiple autonomous agents delegate tasks to each other across processes or machines," which Compound V's design deliberately avoids (no networked agent discovery, no cross-org trust boundary).

**Verdict: SKIP.** Adopting A2A would mean bolting on network-based agent discovery/negotiation for a coordination problem Compound V solved locally with git. It's solving cross-org interop; Compound V is a single-operator local orchestrator. No fit, and no conflict with the charter either way — it's simply orthogonal.

---

## 2. MCP (Model Context Protocol) Evolution in 2026

**Governance shift.** MCP moved to the Linux Foundation's Agentic AI Foundation in December 2025 (Anthropic donating, OpenAI/Block as co-founders) — the same umbrella as A2A, with an active joint interoperability effort between the two projects. [2026 MCP Roadmap](https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/) · [Zylos: Agent Interoperability Protocols 2026](https://zylos.ai/research/2026-03-26-agent-interoperability-protocols-mcp-a2a-acp-convergence/)

**Largest spec revision since launch: the 2026-07-28 release candidate.** Key changes:
- **Stateless core** — removes the `initialize` handshake and `Mcp-Session-Id`, so requests can route to any server instance behind a plain load balancer (a scaling concern, not relevant to a single local process).
- **Elicitation**, formalized via SEP-2322 ("Multi Round-Trip Requests"): a server returns an `InputRequiredResult` with `inputRequests`/`requestState`; the client collects answers and re-issues the call. Stateless by design — no held connection.
- **Extensions framework** (reverse-DNS versioned IDs) shipping two official extensions: **MCP Apps** (sandboxed HTML UIs) and a stateless **Tasks** primitive.
- **OAuth/OIDC hardening**: mandatory `iss` validation, RFC 8707 resource indicators, formal 12-month deprecation lifecycle.

[MCP 2026-07-28 Release Candidate](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/)

**Multi-server composition** is handled outside the core spec, via third-party **gateway/aggregation** patterns that centralize auth and lazy-load tool descriptions — motivated by a real, measured problem: raw tool-description payloads were consuming 40-50% of context windows on multi-server setups, per Perplexity's CTO at a March 2026 conference. [MCP Aggregation/Gateway state Q1 2026](https://www.heyitworks.tech/blog/mcp-aggregation-gateway-proxy-tools-q1-2026). The MCP Registry has grown to ~2,000 server entries.

**Does Compound V's Context7-based doc validation lag?** Context7's resolve→query flow is still the dominant pattern but is fully cloud-dependent — all queries hit Upstash's servers, and the free tier was cut from ~6,000 to 1,000 req/month in January 2026. Local-first alternatives now exist (Grounded Docs — open-source, on-machine, MIT; Docfork — 9,000+ libraries, project-locked; Nia Oracle, Deepcon — claim lower hallucination via semantic indexing), but **none of these use elicitation** to interactively confirm ambiguous library versions yet — that would be a natural, spec-compliant extension (elicitation adds no daemon, it's a structured pause in an existing MCP round trip) but isn't an established pattern in any doc-lookup server today. [Top 7 Context7 Alternatives 2026](https://neuledge.com/blog/2026-02-06/top-7-mcp-alternatives-for-context7-in-2026/) · [Grounded Docs / docs-mcp-server](https://github.com/arabold/docs-mcp-server)

**Verdict: mostly SKIP for the spec changes (stateless core, OAuth hardening, Tasks are backend-scaling concerns Compound V doesn't have), watch-not-adopt for elicitation.** Compound V's fire-and-forget Context7 pre-flight isn't behind a best practice — the interactive-confirmation pattern elicitation would enable simply hasn't been built by any doc server yet. Worth revisiting once a doc-validator MCP actually ships elicitation-based version confirmation; it would fit the charter cleanly (no new process) if/when it exists.

---

## 3. Agent Observability / Tracing Standards

**OpenTelemetry GenAI semantic conventions — still not stable, but converging.** As of mid-2026 the spec covers model-call spans (`gen_ai.operation.name`, `gen_ai.usage.input_tokens`/`output_tokens`, finish reasons), `execute_tool` spans, and top-level `invoke_agent`/workflow spans. Client/LLM-call spans reportedly exited "experimental" in early 2026, but the broader agent/MCP/multi-agent conventions remain in **"Development" status** with no public stabilization timeline. [OpenTelemetry GenAI semconv page](https://opentelemetry.io/docs/specs/semconv/gen-ai/) · [OTel GenAI SemConv Cheat Sheet 2026](https://techbytes.app/posts/opentelemetry-genai-agent-semconv-cheat-sheet-2026/). Note: OpenTelemetry itself reached CNCF Graduate status in 2026 — a project-governance milestone several blog posts conflate with GenAI-semconv stability, which it is not.

**Tooling landscape — all hosted-first, which is the core tension with Compound V's charter.**

| Tool | Model | Notable 2026 fact |
|---|---|---|
| Langfuse | Open-source, but self-host needs Postgres+ClickHouse+Redis+S3 | Acquired by ClickHouse Jan 2026; Cloud free tier 50k units/mo |
| LangSmith | Proprietary SaaS | 5k free traces, then $2.50/1k; deepest LangChain/LangGraph integration |
| Arize Phoenix | Open-source | 50+ eval metrics, heavier eval focus than pure tracing |
| Braintrust | Hosted, CI-gated | Generous free tier (1M spans/mo) |
| AgentOps | Hosted | Strongest multi-framework agent debugging, ~12% measured overhead |

[Langfuse Pricing 2026](https://coverge.ai/blog/langfuse-pricing) · [Latitude: Best AI Agent Observability Tools 2026](https://latitude.so/blog/best-ai-agent-observability-tools-2026-comparison) · [Arize: Best AI Observability for Autonomous Agents 2026](https://arize.com/blog/best-ai-observability-tools-for-autonomous-agents-in-2026/)

**What they show that Compound V's approach cannot:** a real trace waterfall across parallel/nested subagent spans, per-tool-call latency breakdown, live drift/hallucination scoring, queryable cross-run history. **What none of them offer that Compound V has:** zero external dependency. Every tool above needs either a hosted account or a multi-service self-hosted stack — exactly the daemon/DB surface the charter rejects.

**Adoption reality check:** market-size projections ($2.69B → $9.26B by 2030) are analyst forecasts, not adoption evidence. Actual production maturity is low — only ~4% of orgs report full operational AI-observability maturity, ~49% still in pilot, and Gartner projects &gt;40% of agentic AI projects will be canceled by 2027 over cost/value concerns. [LogicMonitor: Observability &amp; AI Trends 2026](https://www.logicmonitor.com/blog/observability-ai-trends-2026). Many "top-N tools" comparison posts are near-identical in structure — treat them as SEO content, not independent benchmarking.

**The lightweight, no-daemon path genuinely exists.** OpenTelemetry has a real **File Exporter** spec: writes OTLP-JSON-encoded spans as newline-delimited JSON directly to disk, explicitly designed for archival/debugging without any collector or backend. [OTel Protocol File Exporter spec](https://opentelemetry.io/docs/specs/otel/protocol/file-exporter/). Third-party implementations exist today (e.g. `otel-file-exporter`, Python, MIT — "zero-dependency observability for demos, local development and CI," writing `traces.jsonl` with the real OTel SDK). [Brishen/otel_file_exporter](https://github.com/Brishen/otel_file_exporter)

**Verdict: ADAPT (narrow, specific).** Compound V could write OTel-shaped span/trace JSON per run directory — populated *only* with real measured facts already available today (wall-clock start/end per job, actual git-diff-derived scope-gate verdicts, actual exit codes, actual tool-call sequence) — while explicitly *omitting* `gen_ai.usage.*` token/cost fields rather than estimating them. This upgrades `state.json` from a bespoke format to an OTel-interoperable one (later viewable in Jaeger/Phoenix if ever wanted) with zero daemon and zero fabricated numbers. This is the one finding in this whole report that fits the charter with no tension at all — it's a strict superset of what already exists.

---

## 4. Agent Evaluation / Benchmarking as a CI Gate

**The pattern.** A golden-task regression suite (typically 200-500 hand-curated cases) wired as a merge gate: every PR runs the agent/prompt against the dataset, an LLM judge scores outputs, a calibrated pass-rate threshold (often ±3% on key metrics) blocks merge on regression. [Adaline: Complete Guide to LLM &amp; Agent Evaluation 2026](https://www.adaline.ai/blog/complete-guide-llm-ai-agent-evaluation-2026) · [DeepEval: LLM-as-a-Judge in 2026](https://deepeval.com/blog/llm-as-a-judge)

**Maturity — real, not vaporware.** DeepEval is pytest-native, runs as an ordinary CI step, no hosted service required. [DeepEval docs](https://deepeval.com/docs/introduction). Braintrust ships a GitHub Action posting pass/fail deltas as PR comments. **Promptfoo was acquired by OpenAI in March 2026 (~$86M)** but stays MIT-licensed and vendor-neutral — a real signal of momentum, though also a consolidation risk. [Top 5 AI Agent Eval Tools After Promptfoo's Exit](https://dev.to/thedailyagent/top-5-ai-agent-eval-tools-after-promptfoos-exit-576i)

**Coding-specific benchmarking is having a credibility crisis, which matters for anyone tempted to lean on public leaderboards.** SWE-bench Verified is the most-cited public number, but on Feb 23, 2026, OpenAI's Frontier Evals team publicly disclosed it had stopped reporting SWE-bench Verified scores after auditors found **59.4% of the hardest problems had fundamentally flawed or unsolvable test cases**. [SWE-bench in 2026 — CallSphere](https://callsphere.ai/blog/swe-bench-evaluating-agentic-coding-agents). A newer research proposal, **SWE-CI**, argues for repurposing CI loops to score agents on long-term codebase-maintainability across evolving repos rather than one-shot snapshots — promising conceptually but still a paper, not a shippable tool. [SWE-CI, arXiv 2603.03823](https://arxiv.org/abs/2603.03823). The practical takeaway echoed across sources: "Public benchmarks tell you who is worth testing. Your own harness tells you who is worth trusting" — i.e., build a small internal eval set from real tickets/tests rather than trusting public leaderboards.

**Relevance to Compound V.** The three-pass review gate (spec/quality/integration) is a one-shot qualitative judge over a single diff — no persistent golden dataset, no trend line across runs, no calibration against human judgment. Evals-as-CI-gate would add exactly what a single-shot review structurally can't: a fixed regression suite re-run on *every* job to catch things silently broken outside the diff, plus a numeric pass-rate trend over time.

**Verdict: ADAPT with real friction.** A DeepEval-style pytest suite invoked as a scripted post-collect step (no persistent service) would fit the no-daemon philosophy — same shape as the existing scope-gate script. But it genuinely conflicts with the no-fabricated-metrics charter if adopted naively: judge "scores" and pass percentages are themselves LLM outputs, and presenting them with the same epistemic weight as git-diff-derived scope enforcement would be exactly the kind of invented-number problem the charter exists to prevent. If pursued, any eval score would need to be clearly labeled as a judged/soft signal, never conflated with the deterministic gates.

---

## 5. Durable Execution for (Coding) Agents

**What it is.** Temporal/DBOS/Restack replay an event-sourced execution log to resume a crashed workflow at the exact failed step, with built-in retries, timers, and human-in-the-loop signal injection. [Temporal: Durable Execution meets AI](https://temporal.io/blog/durable-execution-meets-ai-why-temporal-is-the-perfect-foundation-for-ai)

**Business traction is real and large.** Temporal raised $300M at a $5B valuation in February 2026 (a16z-led, Sequoia/Lightspeed/Index participating), reporting 380% YoY revenue growth and 9.1 trillion lifetime action executions on Temporal Cloud. Replay 2026 shipped Serverless Workers, Standalone Activities, Workflow Streams, plus GA integrations with Google ADK and OpenAI Agents SDK. [WorkOS: Maxim Fateev on Temporal + AI agents](https://workos.com/blog/maxim-fateev-temporal-durable-execution-ai-agents)

**The one concrete coding-agent case: Replit migrated Replit Agent to Temporal**, per Temporal's own case study — for orchestration reliability at scale and pausing workflows on human consent. [Replit × Temporal case study](https://temporal.io/resources/case-studies/replit-uses-temporal-to-power-replit-agent-reliably-at-scale). Most other cited "production" users (OpenAI, ADP, Abridge) are generic long-running/multi-tenant agent workloads, not coding agents specifically — one such case study fetched directly had **zero concrete metrics, just architectural narrative**. Real skepticism exists too: durable execution adds per-step write latency and genuine distributed-systems complexity, and one 2026 industry analysis reports a ~37% gap between agent benchmark and real-world performance. [The Agent Hype Just Broke](https://learnagentic.substack.com/p/the-agent-hype-just-broke-the-reliability)

**Honest tradeoff for Compound V.** Replit's case is the closest real analog but is a persistent, multi-tenant, cloud-hosted service serving concurrent users over long sessions — the structural opposite of Compound V's single-operator, ephemeral, local-worktree model. Adopting Temporal would require either a managed Temporal Cloud subscription or self-hosting a server + Postgres — **that is precisely the daemon/external-service dependency the charter rules out.** DBOS is lighter (can run against a local Postgres/SQLite workflow table without a separate server process) but still adds a persistent-DB dependency and a new failure-mode class for a benefit Compound V's actual workload (a handful of parallel jobs per run, short-lived worktrees, git as an incorruptible ground truth) doesn't clearly need.

**Verdict: SKIP, with a note of self-validation.** Compound V's `state.json` + "git-wins" tie-break is, structurally, already a minimal daemon-free version of the same core idea (event record + replay-to-truth-source) — it just replays against `git diff` instead of an event log. Durable execution would meaningfully help if Compound V ever became a long-running multi-tenant server; for its current design, it's added infrastructure weight without a matching problem.

---

## 6. Human-in-the-Loop Patterns for Autonomous Coding Agents

**Plan-then-execute gates are now table stakes, not a differentiator.** Devin requires two non-negotiable checkpoints — a Planning Checkpoint before any code runs, a PR Checkpoint before merge. [Devin AI Guide 2026](https://aitoolsdevpro.com/ai-tools/devin-guide/). Google Jules works identically: generate plan → human approves/edits → then touch files. [InfoWorld: Agentic coding with Google Jules](https://www.infoworld.com/article/4086269/agentic-coding-with-google-jules.html). Claude Code itself formalized "Plan Mode" (read-only research phase, `/plan` or Shift+Tab twice, blocks Edit/Write/Bash until approval). [ClaudeLog: Plan Mode](https://claudelog.com/mechanics/plan-mode/). Compound V's brainstorming→plan-approval gate matches this pattern exactly — not behind, not ahead, just current baseline practice.

**Per-step diff/tool-call approval is mainstream in interactive IDEs but structurally mismatched to Compound V.** Windsurf's Cascade stages edits as a reviewable diff with per-step approval; Claude Code ships six permission modes (default/acceptEdits/plan/auto/dontAsk/bypassPermissions), with a March 2026 "auto mode" built after Anthropic found 93% of prompts get approved anyway. [Anthropic: How we built Claude Code auto mode](https://www.anthropic.com/engineering/claude-code-auto-mode). This is a live, single-session interactive UI feature — forcing it across 4-6 concurrent headless worktree backends would break Compound V's batching model. Correctly out of scope.

**Risk-tiered / auto-escalation review is the real 2026 shift, and the most relevant gap for Compound V.** GitHub now lets admins skip the "Approve and run workflows" gate for trusted repos on agent-opened PRs — an explicit risk-tier toggle. [GitHub changelog Mar 2026](https://github.blog/changelog/2026-03-13-optionally-skip-approval-for-copilot-coding-agent-actions-workflows/). OpenAI's Codex "Auto-review" (April 2026) replaces synchronous human approval at sandbox boundaries with a *second agent* judging risk — escalates ~200x less often than manual mode, 99.1% approval accuracy on escalated actions. [OpenAI Auto-review](https://alignment.openai.com/auto-review/). Meta's RADAR does the same for code review at scale: a Diff Risk Score plus static/LLM checks auto-lands low-risk diffs (535K+ diffs reviewed, 331K+ landed, revert rate 1/3 of non-RADAR diffs), reserving human attention for the risky tail. [RADAR paper, arXiv 2605.30208](https://arxiv.org/abs/2605.30208)

**No ratified standard yet, but a converging shape.** NIST launched an agent-standards initiative in February 2026 targeting an "AI Agent Interoperability Profile" for late 2026 — not shipped yet. EU AI Act Article 14 (effective August 2, 2026) mandates demonstrable human-oversight capability for high-risk systems, pushing toward auditable checkpoints rather than a specific UI. [Strata: HITL 2026 guide](https://www.strata.io/blog/agentic-identity/practicing-the-human-in-the-loop/)

**Where Compound V sits.** Its plan-approval and final-merge checkpoints are squarely in line with Devin/Jules. Its partition-reviewer + git-diff-derived scope gate is arguably **ahead**: most 2026 "agent boundary" gates (Codex Auto-review, RADAR) are LLM-judging-LLM risk scoring, whereas Compound V's scope enforcement is deterministic and git-derived, never model-self-reported — a stronger provenance guarantee than the industry's dominant pattern.

**The one concrete gap.** Compound V applies the *same* uniform three-pass review to every job regardless of risk. The clear 2026 pattern it's missing is risk-tiered escalation *within* a run: tagging jobs whose `write_allowed` globs touch auth/payments/migrations/schema as mandatory-synchronous-human-review, while routing low-risk jobs (docs, styling, tests) through the existing lighter path — the way GitHub's admin-toggle, Codex Auto-review, and RADAR's diff-risk-score all do.

**Verdict: ADOPT (narrow).** This is a deterministic manifest-level regex/glob check against `write_allowed` paths (no live UI, no new infra) that would insert a mandatory blocking checkpoint only for flagged high-risk jobs before the existing three-pass review runs. It fits the no-daemon, phase-boundary philosophy exactly — it's a stricter gate on an existing mechanism, not a new one.

---

## Summary Table: Recommendations for Compound V

| Area | Finding | Maturity mid-2026 | Fit with charter | Verdict |
|---|---|---|---|---|
| A2A protocol | Cross-org agent interop standard, LF-governed, 150+ orgs (self-reported) | Real but unaudited at production-retention level | Orthogonal — solves a different problem | **SKIP** |
| MCP spec changes (stateless core, OAuth, Tasks) | 2026-07-28 RC; mostly multi-instance/scaling concerns | Draft/RC, not final | N/A — Compound V has no multi-instance deployment | **SKIP** |
| MCP elicitation for doc validation | SEP-2322 spec'd; no doc-lookup server implements it yet | Spec exists, no implementation | Would fit cleanly (no daemon) if/when built | **WATCH** |
| OTel GenAI span shape → local file export | File Exporter spec + real OSS implementations exist | Span taxonomy still "Development," file-export mechanism is solid | Fits perfectly if `gen_ai.usage.*` (cost/token) fields are omitted, not estimated | **ADOPT** |
| Hosted observability platforms (Langfuse/LangSmith/Phoenix/Braintrust/AgentOps) | Real tools, real usage, but all require hosted account or multi-service self-host stack | Genuine production tools; ~4% of orgs report full observability maturity | Every one requires exactly the daemon/DB Compound V's charter forbids | **SKIP** |
| Agent evals as CI gate (DeepEval/Promptfoo-style) | Real, pytest-native, no-daemon options exist; Promptfoo acquired by OpenAI Mar 2026 | Genuinely adopted pattern | Fits as a scripted step; scores must be labeled as soft/judged signals, not fused with deterministic gates | **ADAPT (carefully)** |
| Public coding benchmarks (SWE-bench etc.) as quality signal | SWE-bench Verified credibility damaged (59.4% of hard problems flawed, OpenAI stopped reporting Feb 2026) | Contested / declining trust | N/A | **SKIP as ground truth; build internal eval set instead** |
| Durable execution (Temporal/DBOS) | Real business traction ($5B Temporal valuation); one true coding-agent case (Replit, but multi-tenant hosted service) | Real for long-running multi-tenant agents; not proven for single-operator local orchestration | Requires a server/DB — the exact daemon dependency the charter rejects | **SKIP** |
| Risk-tiered escalation within review (Codex Auto-review, RADAR, GitHub admin-toggle pattern) | Real, production-scale (RADAR: 535K+ diffs), converging industry pattern, no ratified standard yet | Genuinely emerging best practice | Deterministic glob/regex check on `write_allowed` — no new infra | **ADOPT** |
| Plan-then-execute gates | Table stakes across Devin/Jules/Claude Code | Fully mature/standard | Already matches Compound V's design | **Already aligned — no action** |
| Live per-tool-call approval UI | Mainstream in IDEs (Cascade, Claude Code permission modes) | Mature but session-interactive by nature | Structurally incompatible with headless multi-backend batch dispatch | **Correctly out of scope** |

**Bottom line:** Compound V is not behind the field on its core bets — its git-diff-derived scope gate and phase-boundary checkpoints are, if anything, more rigorous (deterministic, non-self-reported) than the LLM-judges-risk pattern dominating 2026 industry practice (Codex Auto-review, RADAR). The two changes worth actually making are narrow and both fit the existing minimal/no-daemon shape: (1) write OTel-shaped, file-exported trace JSON per run using only already-available real measurements, with cost/token fields omitted rather than fabricated; and (2) add a deterministic risk-tier check on `write_allowed` globs (auth/payments/migrations/schema) that forces mandatory synchronous review for flagged jobs before the existing three-pass gate runs. Everything else surveyed — A2A, hosted observability SaaS, durable-execution engines, live per-tool-call UI — either solves a different problem than Compound V has, or would require exactly the daemon/external-service dependency its charter exists to prevent.
