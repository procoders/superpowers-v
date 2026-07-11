# Compound V Guardrail-Retry Design Research

**Date:** 2026-07-11. Deep-dive research agent (general-purpose, WebSearch-driven), requested
after the user identified this as a real recurring pain: small fixes shouldn't require the
full three-pass Review Gate on every retry ("не превращались в Одиссею Нолана"). Part of the
[2026 orchestrator landscape synthesis](2026-07-11-2026-orchestrator-landscape-synthesis.md).

*(Research conducted July 2026 via 5 parallel search agents fetching primary sources — CrewAI
GitHub source, official framework docs, GitHub issues, and 2025-2026 engineering blogs. All
claims below are cited; anything unverifiable is flagged as such rather than assumed.)*

---

## 1. CrewAI's actual guardrail implementation

Verified directly against `crewAIInc/crewAI` source (`lib/crewai/src/crewai/task.py`, `agent/core.py`, `utilities/guardrail.py`, `tasks/llm_guardrail.py`) and `docs.crewai.com`.

**API surface**
- `Task(guardrail=...)` takes a single callable or a plain string. `Task(guardrails=[...])` takes a *list*, executed sequentially (each stage receives the prior stage's output), and takes precedence over the singular field. There is no separate `@task` decorator or `TaskGuardrail` class — it's a constructor kwarg. ([source](https://github.com/crewAIInc/crewAI/blob/main/lib/crewai/src/crewai/task.py), [docs](https://docs.crewai.com/en/concepts/tasks))
- String guardrails are auto-wrapped into an `LLMGuardrail(description=..., llm=self.agent.llm)` object via a `field_validator`.

**`guardrail_max_retries`**
- `guardrail_max_retries: int = Field(default=3, ...)` — set **per-Task**, not per-Crew. A deprecated `max_retries` alias still copies into it. ([source, lines 273-274](https://github.com/crewAIInc/crewAI/blob/main/lib/crewai/src/crewai/task.py))

**Feedback-loop shape — fresh prompt, not appended conversation**
- On failure, `Task._invoke_guardrail_function` builds a formatted error string (`I18N_DEFAULT.errors("validation_error").format(guardrail_result_error=..., task_output=task_output.raw)`) and calls `agent.execute_task(task=self, context=context, tools=tools)` **again**.
- `Agent.execute_task` **re-derives the prompt from scratch every attempt** (`task.prompt()` → `build_task_prompt_with_schema` → `format_task_with_context`), re-runs memory/knowledge retrieval, and issues a fresh executor call. It is the **same agent instance and same Task object**, but **not a persisted, appended conversation** — the guardrail error is injected as fresh context into a rebuilt prompt each retry. ([source](https://github.com/crewAIInc/crewAI/blob/main/lib/crewai/src/crewai/agent/core.py))
- Result of each guardrail call is standardized into `GuardrailResult {success, result, error}` (mutually exclusive `result`/`error`).

**Deterministic vs. LLM validator**
- Function-based guardrails are plain Python: `callable(TaskOutput) -> Tuple[bool, Any]` — no LLM call required. ([docs](https://docs.crewai.com/en/concepts/tasks), [PR #1742](https://github.com/crewAIInc/crewAI/pull/1742))
- String guardrails run as an LLM judge using the *task's own agent's LLM*, returning `LLMGuardrailResult(valid, feedback)`.

**Exhausted retries**
- Literal code: `if attempt >= self.guardrail_max_retries: raise Exception(f"Task failed {guardrail_name} validation after {self.guardrail_max_retries} retries. Last error: {guardrail_result.error}")` — a plain Python exception, **no built-in human-escalation path**, no custom exception type. ([source, lines 1292-1301](https://github.com/crewAIInc/crewAI/blob/main/lib/crewai/src/crewai/task.py))
- Flagged unverifiable: an enterprise "Hallucination Guardrail" is documented but the OSS repo file is an explicit no-op placeholder — real implementation is closed-source.
- Cautionary note surfaced independently in §3: CrewAI's *iteration* cap (`max_iter`, separate from `guardrail_max_retries`) has a real open bug where `handle_max_iterations_exceeded` fires but gets overwritten by subsequent LLM calls, so the loop continues anyway ([issue #3847](https://github.com/crewAIInc/crewAI/issues/3847)) — evidence that trusting a framework's own internal cap-enforcement logic is fragile.

---

## 2. Similar patterns in other frameworks/products

**LangGraph** — no official named "cheap-gate-before-review-subgraph" recipe. Closest primitives: `interrupt()`-based human-in-the-loop middleware (a checkpoint, not an automated cheap check) ([docs](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)), and the community "Reflection" pattern (generator → critic → conditional-edge loop-back) which is a tutorial pattern, not a framework primitive ([example](https://learnopencv.com/langgraph-self-correcting-agent-code-generation/)). NVIDIA NeMo Guardrails wraps LangGraph nodes as pre/post middleware, which is the closest thing to a true cheap gate, but it's NVIDIA's layer, not LangChain's ([docs](https://docs.nvidia.com/nemo/guardrails/latest/integration/langchain/langgraph-integration.html)).

**AutoGen/AG2** — a genuine two-tier example exists in official docs: "Nested Chat" Scenario 1 is a cheap single-turn `reflection_message` self-check; Scenario 2 escalates to a heavier multi-turn `critic_executor` with tool calls for a fuller review. ([docs](https://docs.ag2.ai/0.8.4/docs/use-cases/notebooks/notebooks/agentchat_nestedchat/))

**Coding-agent products:**
- **Aider**: `--auto-lint`/`--auto-test` run the linter/test suite after every edit and auto-repair on failure — a per-edit self-healing tier, separate from human review. ([docs](https://aider.chat/docs/usage/lint-test.html))
- **GitHub Copilot coding agent**: iterates write→test→diagnose→revise inside an ephemeral sandbox, with layered security scanning, *before* a PR is opened for human/Copilot review. ([docs](https://docs.github.com/copilot/concepts/agents/coding-agent/about-coding-agent))
- **OpenHands**: repo-level lint-fix Actions workflow auto-fixes and commits before PR review; agent-level "Stop hooks" force the agent to keep working until lint/tests pass before it's even allowed to finish. ([docs](https://docs.openhands.dev/openhands/usage/customization/hooks))
- **Cursor Background Agent + Bugbot**: the background agent runs deterministic build/test before opening a PR; Bugbot's LLM review is a separately-invoked, decoupled step. ([cursor.com/bugbot](https://cursor.com/bugbot))
- Devin/Cursor "8-iteration test-fix loop" claims are from secondary coverage only, flagged lower-confidence.
- **metaswarm** (OSS orchestrator): `IMPLEMENT → VALIDATE (deterministic coverage gate, blocking) → ADVERSARIAL REVIEW (LLM, capped at 3 iterations) → COMMIT`, escalating to human after 3 failed iterations. ([github](https://github.com/dsifry/metaswarm))
- **Qodo Merge/PR-Agent**: deterministic static analysis (SonarQube/Semgrep-style) as a first gate, with explicit guidance to configure the LLM review to *skip* categories already covered deterministically. ([source](https://sourcegraph.com/blog/automated-code-review-tools))

**No single canonical name exists** for "cheap gate → expensive gate" specific to AI agent pipelines in 2025-2026 writing — confirmed absent across all five search angles. Recurring vocabulary instead: "tiered eval strategy" ([Galileo](https://galileo.ai/blog/continuous-integration-ci-ai-fundamentals)), "layered/defense-in-depth guardrails" ([Medium](https://ssahuupgrad-93226.medium.com/building-production-ready-guardrails-for-agentic-ai-a-defense-in-depth-framework-4ab7151be1fe)), "risk-tiered review stack" ([Propel Code](https://www.propelcode.ai/blog/agentic-engineering-code-review-guardrails)), and explicit AI-adapted framings of the classic gates: Factory.ai's "linters are the cheapest gate" ([source](https://factory.ai/news/using-linters-to-direct-agents)), Motomtech's "Lint → Test → Scan → Review" ([source](https://www.motomtech.com/blog-post/ai-generated-code-quality-gates/)), and Optimum Partners' claim that "LLM-as-a-Judge is the standard design pattern for 2026" sitting *downstream* of deterministic checks ([source](https://optimumpartners.com/insight/how-to-architect-self-healing-ci/cd-for-agentic-ai/)).

Classic non-AI analogues confirmed with primary sources: Fowler/Shore's "Fail Fast" (2004) ([PDF](https://martinfowler.com/ieeeSoftware/failFast.pdf)), the test pyramid, Google's "just say no to more end-to-end tests" ([Google Testing Blog](https://testing.googleblog.com/2015/04/just-say-no-to-more-end-to-end-tests.html)), trunk-based CI staging ([trunkbaseddevelopment.com](https://trunkbaseddevelopment.com/continuous-integration/)), pre-commit hooks catching ~80% of issues for the "cost of a second" ([source](https://blog.lueurexterne.com/en/blog/git-hooks-and-ci-cd-automate-code-quality-before-every-deployment/)), and smoke-test-before-regression staging ([Harness](https://www.harness.io/harness-devops-academy/integrating-smoke-testing-into-your-ci-cd-pipeline-what-devops-needs-to-know)).

Notably, "guardrail" itself is consolidating industry-wide (2025-2026) into exactly this meaning — a **cheap, inline, blocking check** distinct from expensive offline evaluation: OpenAI's Agents SDK ships input/output/tool guardrails that run and complete *before* the agent starts, explicitly to avoid wasted token spend on a doomed run ([docs](https://openai.github.io/openai-agents-python/guardrails/)); industry framing states "Guardrails run inline... gate or rewrite in real time. Evaluation runs on traces or datasets, often offline" ([source](https://www.digitalapplied.com/blog/llm-guardrails-production-safety-layers-reference-2026)).

---

## 3. Failure-mode research: retry loops made too permissive

**Real, verified incidents:**
- Claude Code subagent recursion bug — 50+ levels deep, permission denials triggering *more* spawning instead of stopping, 4M tokens burned in under 5 minutes. ([issue #68619](https://github.com/anthropics/claude-code/issues/68619))
- Claude Code unbounded "thinking" loop post-compaction, 21 min / 73k tokens, zero output — flagged as a recurring bug class. ([issue #26171](https://github.com/anthropics/claude-code/issues/26171))
- CrewAI's own `max_iter` cap failing to actually stop a loop (§1 above). ([issue #3847](https://github.com/crewAIInc/crewAI/issues/3847))
- LangGraph regression where an agent loops indefinitely instead of raising `GraphRecursionError` (v1.0.6). ([issue #6731](https://github.com/langchain-ai/langgraph/issues/6731)); LangGraph.js ignoring a configured `recursionLimit` entirely and silently falling back to the default of 25. ([issue #1524](https://github.com/langchain-ai/langgraphjs/issues/1524))
- AutoGen's "gratitude loop" — agents thanking each other indefinitely after task completion, halted only by `max_consecutive_auto_reply`. ([issue #254](https://github.com/microsoft/autogen/issues/254))

**Safeguards teams/frameworks converged on:**
- **Hard iteration caps with real defaults**: CrewAI `max_iter` defaults to 25 ([docs](https://docs.crewai.com/en/learn/customizing-agents)); LangGraph `recursion_limit` defaults to 25 ([docs](https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT)).
- **Escalate-after-N**: community guidance converges on escalating to a human after ~3 failed self-recovery attempts. ([fast.io](https://fast.io/resources/ai-agent-retry-patterns/), [agent-works.ai](https://agent-works.ai/insights/agent-error-handling-recovery-patterns))
- **"Materially different" requirement / duplicate-fix detection**: a documented "DebounceHook" pattern fingerprints tool name+params over a sliding window of 3 calls and blocks a 3rd identical call, forcing a different approach. ([source](https://dev.to/aws/how-to-prevent-ai-agent-reasoning-loops-from-wasting-tokens-2652)) Praetorian's (2026, vendor architecture write-up) loop-detector triggers on 3 consecutive iterations with &gt;90% output-string similarity. ([source](https://www.praetorian.com/blog/deterministic-ai-orchestration-a-platform-architecture-for-autonomous-development/))
- **Retry-scoped cost/token budgets**, distinct from the whole-run budget. ([Arthur.ai](https://www.arthur.ai/blog/best-practices-for-building-agents-guardrails))
- **Root-cause framing**: "step repetition" is cited as the single most common production agent failure (~15.7% of failures across models); the recommended fix is architectural (explicit terminal states, timeouts, kill switches) — not a smarter model. ([dev.to/alanwest](https://dev.to/alanwest/why-your-ai-agent-loops-forever-and-how-to-break-the-cycle-12ia))

---

## 4. Design recommendation for Compound V

### (a) Where it slots in
**A new deterministic gate between the scope gate and the three-pass Review Gate — at job level, not inside the worker.** Three tiers result:

```
worker finishes → scope gate (existing, deterministic, structural)
                       ↓ PASS
                new guardrail-retry gate (deterministic, job-level)
                       ↓ PASS or retries-exhausted-clean
                three-pass Review Gate (existing, Opus, batch-level)
```

Rationale, grounded in the research: AGENTS.md's own charter states enforcement fields must be "git-derived, never model-self-reported" — same reasoning that makes the scope gate a `git diff` check rather than trusting the worker's self-report applies here. CrewAI's own iteration-cap enforcement had a real bug (issue #3847) because it lived *inside* the same loop it was supposed to stop; keeping the guardrail-retry check external and orchestrator-owned avoids that exact failure class. The job_result schema already carries `exit_code` and `failure_class` — that's the worker's self-report, useful as a *signal* but not sufficient on its own.

The retry itself, however, should re-invoke the **same worker/session** (matching CrewAI's same-agent-fresh-prompt shape, §1), not spawn a new job. Compound V already has the plumbing for this: `/v:resume`'s re-dispatch-only-incomplete-jobs mechanism and the Codex `codex exec resume <uuid>` pattern (v2.8.1's session-aware workers) are directly reusable — no new dispatch code path needed.

### (b) What the validator checks
**Cheap deterministic (build/lint/test-pass), not an LLM read, and not sole reliance on the worker's self-report.** Concretely: run whatever build/lint/test command the job_spec/manifest already declares for the touched file types. This matches CrewAI's own recommended default (function-based guardrails are cheaper and preferred over the LLM-string guardrail), Aider's `--auto-lint`/`--auto-test`, and OpenHands' Stop-hooks pattern of blocking completion until lint/tests are green. Skip the "cheap single-pass LLM read" option for v1 entirely — see (d).

### (c) Retry cap and escalation triggers
- **Default cap: 2 retries** (bias toward cheap — CrewAI's own default of 3 total attempts is a reasonable outer bound, but escalating one attempt sooner keeps this "not a Christopher Nolan odyssey").
- **Escalate to the full three-pass Review Gate** when: retries are exhausted with the deterministic check *still failing but converging* (diffs are changing, not stuck), OR the deterministic check passes outright (normal path).
- **Skip the retry loop and go straight to BLOCKED** when: the scope gate already failed (never eligible for cheap retry — a scope violation is a policy breach, not a quality near-miss) or the retry attempt's diff is unchanged/near-identical (&gt;90% similarity, per the Praetorian pattern and the DebounceHook fingerprinting pattern) to the previous attempt — this directly closes the "loop retrying the identical fix" failure mode documented in the CrewAI/Claude Code/LangGraph GitHub issues in §3.
- Each retry attempt increments a `guardrail_attempts` counter written into the same job_result/state.json audit trail already committed per the v2.6.4 fix — no new persistence mechanism.

### (d) Smallest-viable version (avoiding over-engineering)
- **No new daemon, no new agent type, no new backend, no new schema file.** Extend `job_result.schema.json` with one small optional block: `guardrail: {enabled, check_cmd, max_retries (default 2), attempts}`.
- **Deterministic-only for v1** — no LLM guardrail call at all. This is the actual smallest version that solves the reported problem: a one-line typo or formatting near-miss is caught by a build/lint/test exit code, not by spending another Opus call. Add an LLM single-pass guardrail later only if deterministic coverage proves insufficient in practice — don't build it speculatively.
- **If no deterministic check command is configured for the touched files, skip the cheap gate entirely** — go straight to eligibility for the three-pass Review Gate. Don't invent a universal linter/build abstraction to cover every project type; that's exactly the over-engineering the charter warns against.
- **Reuse existing resume/worktree plumbing** for the same-worker retry rather than building new dispatch logic.

This gives Compound V a genuine three-tier structure — fast structural check (scope gate) → fast quality check (new guardrail-retry) → slow full review (three-pass gate) — that mirrors both the CrewAI pattern the user found and the emerging 2025-2026 industry consensus (Factory.ai, Motomtech, OpenAI Agents SDK, Qodo/PR-Agent) that "guardrail" now specifically means a cheap, inline, blocking check kept separate from expensive offline/batch evaluation, while staying inside the existing no-daemon, git-derived-enforcement, minimal-new-surface constraints already governing the project.
