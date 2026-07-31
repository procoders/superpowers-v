# zai — a headless GLM worker backend (PR 1 of 3)

**Goal:** add `zai` as a sixth dispatch backend so a run can use **codex, claude and z.ai
concurrently**, each drawing on its own quota. Role in v1 is deliberately narrow: `zai` is an
**implementation worker** and a **fallback when another backend is rate-limited** — never a
reviewer, never an arbiter-panel seat.

**Architecture:** a Bash-spawned `claude -p --bare` process in its own git worktree, under the
process-group timeout supervisor, with the dispatcher's own provider credentials scrubbed and
z.ai's Anthropic-compatible endpoint injected. Enforcement is the caller's git-derived scope gate —
identical to codex/cursor/antigravity. z.ai ships no headless CLI of its own; Claude Code is on
z.ai's list of officially supported tools for the GLM Coding Plan, so this is the compliant path.

**Tech stack:** bash 3.2 (no arrays), Python 3.9-safe stdlib, jq. No new external dependency,
no SDK, no service. The `claude` binary is already a prerequisite of this plugin.

> **Grounded by live probes on 2026-07-31 — NOT training data.**
> Versions: `claude 2.1.207`, `codex-cli 0.144.4`. Probes ran against a real GLM Coding Plan key.
>
> - **The redirect works.** A local stub HTTP server captured what `claude -p` sends when
>   `ANTHROPIC_BASE_URL` is set: `POST {base}/v1/messages?beta=true`, `Authorization: Bearer …`,
>   `anthropic-version: 2023-06-01`, `stream: true`, 46–53 tool definitions.
> - **z.ai accepts it and validates the model name.** `glm-5.2`, `glm-5.1`, `glm-5`, `glm-5-turbo`,
>   `glm-4.7`, `glm-4.6`, `glm-4.6v`, `glm-4.5-air` → accepted. `glm-5.2-air`, `glm-4.6-air`,
>   `glm-5-fast`, `glm-5.2-fast`, `glm-5-flash`, `glm-4.6-flash`, `glm-5.2-turbo` → rejected with
>   `API Error: 400 [1211][Unknown Model, please check the model code.][<trace-id>]`. An Anthropic
>   alias (`claude-opus-4-8`) is also accepted, so z.ai maps Anthropic names onto GLM.
> - **The agentic tool loop works.** A worker prompt with the planner/executor lock added a function
>   to `calc.py` in 3 turns, zero permission denials; `git diff` confirmed exactly one file changed.
> - **`--bare` is load-bearing, not cosmetic** — see "Context policy" below.
> - **`session_id` is a real RFC-4122 UUID** (`ce0ba7c7-…`), so the codex worker's UUID validator
>   can be reused verbatim — unlike opencode's `ses_…` tokens.
> - **codex cannot reach z.ai at all.** The installed `codex 0.144.4` binary contains the literal
>   string ``` `wire_api = "chat"` is no longer supported. How to fix: set `wire_api = "responses"` ```.
>   z.ai exposes an Anthropic-compatible endpoint and an OpenAI **Chat Completions** endpoint; it has
>   no Responses API. This is why `zai` is its own backend rather than a codex provider config.

## Global constraints (apply to every task)

- Opus by default for reviewers; **never Haiku**. This PR changes no model policy in either
  direction — see "Non-goals".
- **anti-ruflo:** only real measured usage is recorded. No estimated or invented token/cost numbers.
- Enforcement fields (`blocked`, `files_changed`, `violations`) are **git-derived by the caller**,
  never self-reported by the worker.
- Every external-CLI launch goes through `scripts/compound-v-run-with-timeout.py` with
  `stdin </dev/null`, per the non-negotiable rule in `skills/backend-launcher/SKILL.md`.
- No `--dangerously-skip-permissions`, no `--yolo`, no bypass `--permission-mode`, on any path.

## Endpoint and credentials

The GLM Coding Plan (subscription) is reachable on two compatibility layers, and both differ from
the pay-as-you-go paths:

| Layer | Subscription (Coding Plan) | Pay-as-you-go |
|---|---|---|
| Anthropic | `https://api.z.ai/api/anthropic` | same URL, only if a Coding Plan was never purchased |
| OpenAI | `https://api.z.ai/api/coding/paas/v4` | `https://api.z.ai/api/paas/v4` |

This adapter uses the **Anthropic** layer. The OpenAI layer is documented here only so a reader does
not reach for `/api/paas/v4` and get rejected.

The key is read from a single environment variable, `ZAI_API_KEY`, named in `.claude/compound-v.json`
and detected by `/v:init`. The worker never reads a key from a file inside the repo.

**Credential isolation (load-bearing).** The worker launches under `env -i` with an explicit
allow-list — `PATH HOME TMPDIR LANG` — plus exactly three injected variables:
`ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY` (set from `ZAI_API_KEY`), `ANTHROPIC_MODEL`. This mirrors
the opencode worker's scrub, which exists because opencode was observed authenticating from an
inherited ambient `ANTHROPIC_BASE_URL`. `--bare` reinforces it: in bare mode Claude Code authenticates
**strictly** from the environment — OAuth and keychain are not read — so a `zai` job is structurally
incapable of billing the operator's Anthropic subscription.

## Context policy — `--bare` plus an explicit CLAUDE.md injection

Two measurements, both same directory, same prompt, same `--allowedTools`. The first is a
single-turn request captured by a local stub; the second is the 3-turn agentic job against z.ai:

| | one request | credits for the 3-turn job (glm-5.2) |
|---|---|---|
| without `--bare` | ~49 385 tokens | 50.4 |
| with `--bare` | ~1 179 tokens | 1.7 |

The ~48k difference is **not** project context. It breaks down as ~29 168 tokens of 53 tool
definitions (23 of them a design-service MCP, plus cron/notification/scheduling tools a code worker
never calls), ~16 000 tokens of `SessionStart` hook output (a skills catalog and an agent roster),
and ~2 300 tokens of `CLAUDE.md`.

Two facts decide the policy:

1. **Today's `claude` backend does not receive that block either.** It dispatches an in-harness
   `Task`; the 16k block is injected by `SessionStart`, which fires once per *session*. A subagent
   fires `SubagentStart` instead — measured output: 17 characters, ~4 tokens. Running `zai` without
   `--bare` would give it context that claude workers have never had.
2. **A `Task` subagent does receive `CLAUDE.md`.** `--bare` disables CLAUDE.md auto-discovery, so
   for parity the worker passes the same set back explicitly via `--append-system-prompt-file`:
   the user-level `CLAUDE.md` files, the project `CLAUDE.md`, and `AGENTS.md` it imports —
   ~6 965 tokens, 4.8 credits fresh or 1.18 from cache on glm-5.2.

Caching does not remove the need for `--bare`. The 50.4-credit measurement was taken **with caching
already active** (50 048 tokens billed as cache reads). Worse, the cacheable prefix does not survive
across workers: two identical `claude -p "hi"` runs seconds apart produced different requests — the
system block embeds `git status` output (`(clean)` vs `?? .claude-flow/`), and the hook text carries a
varying session codename. Since every worker runs in its own worktree with different files, that
prefix diverges by construction.

**Known, accepted gap:** the injected user-level `CLAUDE.md` contains orchestrator-facing
instructions (a reply-language rule, model-routing policy, `/delegate`). A probe confirmed a
non-bare worker obeying them — it answered in Russian. This is not specific to `zai`: claude
subagents receive the same files. Out of scope here; recorded so a reader is not surprised.

**Also accepted:** `--bare` disables LSP. A worker therefore loses editor-side diagnostics. The
per-job `acceptance` command is the deterministic check that must catch what a diagnostic would
have hinted.

## Job contract

`job_spec` is unchanged. `zai` accepts `backend`, `prompt`, `tier`, `effort`, `model`, `cwd`,
`write_allowed`, `read_only`, `timeout_sec`, `network`. `effort` is **advisory** — Claude Code has no
reasoning-effort flag, exactly as documented for the `claude` adapter — and `effort: xhigh` is
rejected, since `xhigh` is codex-only. `network` and `read_only` are accepted for CLI parity;
a read-only job is enforced post-hoc with an empty `write_allowed`.

`job_result` is unchanged and assembled by the caller:

| Field | Source |
|---|---|
| `files_changed`, `violations`, `blocked` | `scripts/compound-v-scope-check.py`, git-derived |
| `status` | `blocked` → blocked; supervisor exit 124 → timeout; non-zero → error; else success |
| `summary` | `.result` from `--output-format json` — informational only |
| `session_id` | `.session_id`, validated as a UUID with the codex worker's existing pattern |
| `worktree` | the absolute worktree path (always set; `zai` is never `direct`) |
| `usage` | `.usage.input_tokens` / `.output_tokens`, with `measured: true` |
| `failure_class` | see below; `null` on success/blocked |

**On cost:** `job_result.usage` has exactly five fields — `input_tokens`, `output_tokens`,
`advisor_calls`, `backend`, `measured`. There is no cost field, so the CLI's `total_cost_usd` (which
is computed from Anthropic's price table for a model that never ran) is simply not carried. Token
counts, by contrast, come from z.ai's own response and are real — so `zai` is **not** added to
`UNMEASURED_BACKENDS` in `scripts/compound-v-usage-extract.py`, unlike `claude`.

The CLI's `contextWindow` (200 000) and `maxOutputTokens` (32 000) are the alias's Anthropic defaults,
not GLM's real limits (1M / 131 072). Neither is recorded.

## Isolation and trust tier

`isolation: worktree` is **mandatory** — a new invariant beside the existing
`codex|antigravity|cursor|devin|opencode ⇒ worktree` rule in `scripts/compound-v-validate-manifest.py`.

`zai` sits in the same lower-trust, opt-in tier as antigravity and cursor: there is no kernel
write-confinement under this invocation, so the worktree plus the git-derived gate **detects** an
in-worktree scope leak but cannot **prevent** an out-of-worktree side effect. Prefer codex for
untrusted or high-stakes work.

The worker runs `--permission-mode dontAsk` with a curated non-empty `--allowedTools` list —
`Read,Grep,Glob,Edit,Write`, exactly the set the live probe verified. Under `dontAsk` an off-list
tool is refused rather than prompted, so a headless run neither stalls nor bypasses. **`Bash` is
deliberately withheld:** a worker's job is to edit its allowed files, and the per-job `acceptance`
command runs caller-side after the scope gate, so the worker never needs a shell. Granting bare
`Bash` would also hand a backend with no kernel confinement an arbitrary-command channel — the
precedent for scoping it narrowly is `ALLOWED_TOOLS` in `scripts/compound-v-headless-shim.py`.

## Model resolution

`zai` is single-vendor: every resolved model is a bare GLM name, never a `provider/model` string, so
the resolver needs no shape check (contrast opencode).

```
deep     → glm-5.2
standard → glm-5.2
light    → glm-5-turbo
```

Identical in every stance, like all non-claude backends.

The rationale differs from other backends and is recorded deliberately. Credit consumption is
`(input × Mi + cached × Mc + output × Mo) / 10 000`, with published multipliers of 6.9 / 1.7 / 24 for
glm-5.2, 5.7 / 1.5 / 21 for glm-5-turbo and 4.6 / 1.2 / 16 for glm-4.7; off-peak usage is billed at
half rate (peak = Mon–Fri 14:00–18:00 SGT). Plan quotas are 2 000 / 12 000 / 28 000 credits per
5-hour window for Lite / Pro / Max, with weekly caps of 10 000 / 60 000 / 140 000.

A measured job costs 1.7 credits bare, or ~6.5 with the CLAUDE.md injection above — roughly 300 jobs
per 5-hour window on the cheapest plan, against 39 without `--bare`. Quota is therefore not the
binding constraint, and the map is chosen for capability first. `glm-5.2` takes both
`deep` and `standard` because it is the strongest model available and `glm-5-turbo` would save only
14%. `glm-5-turbo` takes `light` for **latency**, not credits. `glm-4.7` is documented as a config
override worth 32% for anyone who does hit the weekly window.

Only models with a **published multiplier** appear in the default map. `glm-5.1`, `glm-5`,
`glm-4.6`, `glm-4.5-air` and `glm-4.6v` are accepted by the endpoint but z.ai publishes no
multiplier for them, so their burn is unpredictable; they remain available as user overrides and are
documented as unverified.

## Failure classification

Only one live error shape is known: `API Error: 400 [1211][Unknown Model, please check the model
code.][<trace-id>]`, a configuration fault that maps to `other`. Quota-exhaustion and rate-limit
shapes have **not** been observed and must not be invented.

`scripts/compound-v-classify-failure.py --backend zai` therefore ships a minimal needle set and
**fails closed to `other`** for anything unmatched — the same provisional pattern the cursor adapter
already uses. Because the transport is Claude Code's own, the `--backend claude` stream-json path is
the fallback where the output is JSON.

Consequence: a `zai` job that hits a z.ai quota wall is retried, not rerouted, in v1. Automatic
rerouting is PR 3 and depends on error samples this PR's operation will produce.

## Files touched

New: `scripts/compound-v-run-zai-worker.sh` (structured after
`scripts/compound-v-run-cursor-worker.sh`, the shortest existing worker),
`skills/backend-launcher/adapter-zai.md`.

Edited: `scripts/compound-v-resolve-model.py` (`BACKENDS` + the `_ZAI` tier map);
`scripts/compound-v-validate-manifest.py` (`VALID_BACKENDS`, the worktree invariant, the reviewer
prohibition, selftest manifests); `schemas/job_result.schema.json` (the `usage.backend` description
string); `scripts/compound-v-usage-extract.py`; `scripts/compound-v-usage-aggregate.py`;
`scripts/compound-v-collect-results.py`; `scripts/compound-v-classify-failure.py`;
`skills/backend-launcher/SKILL.md` (backend enum + adapter table);
`skills/compound-v/execution-manifest.md` (tier table, models map, invariant list);
`skills/compound-v/routing-policy.md`; `commands/v-init.md`; `commands/v-models.md`;
`CHANGELOG.md`; `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (version
lockstep, enforced by CI).

## Testing

**Stub-first, no live call in CI.** Following `scripts/test-advisor-worker-stub.sh`, a fake `claude`
placed on `PATH` drives the worker end-to-end and asserts: the pinned argv (including `--bare`,
`--permission-mode dontAsk`, the allow-list, `</dev/null`); that `env -i` forwards exactly the four
safe variables plus the three injected ones and nothing else; the success path; the BLOCKED path
(a write outside `write_allowed`); the timeout path (supervisor exit 124 → `status: timeout`).

Selftests: `compound-v-resolve-model.py --selftest` gains `zai` tier assertions and keeps its
existing "no haiku in any stance map" assertion unchanged; `compound-v-validate-manifest.py`
gains a manifest whose only defect is `backend: zai` with `isolation: direct`, and one whose only
defect is a `zai` reviewer job.

CI gates this must satisfy: plugin/marketplace/CHANGELOG version lockstep, the frontmatter linter
(no Haiku), the manifest invariant gate, the `job_result` example-against-schema check, the
anti-fabricated-metrics gate, the dead intra-plugin cross-reference check, shellcheck, and the
Python 3.9 selftest floor.

The live verification recorded at the top of this document is the acceptance evidence for the parts
CI cannot reach; it is reproducible with a Coding Plan key and is not re-run in CI.

## Non-goals

- **No model-policy change.** The never-Haiku rule is enforced on frontmatter and on an explicit
  per-job `model`, but not on a `.claude/compound-v.json` map cell — verified: a config cell of
  `haiku` resolves successfully today. This PR neither closes that gap nor relies on it.
- **No reviewer or arbiter seat for `zai`.** `scripts/compound-v-epic-arbiter.py` matches model
  families by substring over `gpt`, `gemini`, `claude`, `opus`, `sonnet`, `grok`; `glm` is absent, so
  a GLM ballot buckets as `unknown` alongside every other unrecognised model and could be deduped
  against an unrelated one. Adding the needle is a one-line change plus a test, and belongs to the
  follow-on that lifts this restriction.
- **No multi-model tier pool and no round-robin** (PR 2). **No rate-limit rerouting** (PR 3).
- **No time-of-day routing** to exploit z.ai's half-rate off-peak window — it belongs with PR 2.
- **No generic "any Anthropic-compatible endpoint" backend.** It was considered and rejected: this
  plugin pins each adapter to a flag set verified live against a named CLI version, and a
  parameterised backend cannot carry that guarantee. If a second such provider appears, generalise
  then, from two live examples.

## Acceptance criteria

1. A manifest with `backend: zai, isolation: worktree` validates; the same manifest with
   `isolation: direct` fails with a message naming the invariant.
2. A `zai` reviewer job fails validation with a message naming the restriction.
3. `compound-v-resolve-model.py --backend zai --tier {deep,standard,light}` returns
   `glm-5.2`, `glm-5.2`, `glm-5-turbo` in every stance; `--effort xhigh` is rejected.
4. The stub test passes for all four paths (success, blocked, timeout, argv/env assertions), with no
   network call.
5. A worker that writes outside `write_allowed` yields `blocked: true` with the offending paths in
   `violations`, and the caller does not merge.
6. `job_result.usage` carries real `input_tokens` / `output_tokens` with `measured: true`, and no
   cost value appears anywhere in the result or the aggregate.
7. The `env -i` allow-list forwards exactly `PATH HOME TMPDIR LANG` plus the three injected
   `ANTHROPIC_*` variables; a probe with an ambient `ANTHROPIC_BASE_URL` set to a different host does
   not reach the worker.
8. Every CI gate listed under Testing passes.
