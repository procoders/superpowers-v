# zai — a headless GLM worker backend (PR 1 of 3)

**Goal:** add `zai` as a sixth dispatch backend so a run can use **codex, claude and z.ai
concurrently**, each drawing on its own quota. Role in v1 is deliberately narrow: `zai` is an
**implementation worker** and a **fallback when another backend is rate-limited** — never a
reviewer, never an arbiter-panel seat.

**Architecture:** a Bash-spawned `claude -p` process in its own git worktree, under the
process-group timeout supervisor, with the dispatcher's own provider credentials scrubbed, `HOME`
and `CLAUDE_CONFIG_DIR` redirected to a scratch directory, and z.ai's Anthropic-compatible endpoint
injected. Enforcement is the caller's git-derived scope gate — identical to codex/cursor/antigravity.
z.ai ships no headless CLI of its own; Claude Code is a tier-1 officially supported tool for the GLM
Coding Plan, so this is the compliant path.

**Tech stack:** bash 3.2 (no arrays), Python 3.9-safe stdlib, jq. No new external dependency,
no SDK, no service. The `claude` binary is already a prerequisite of this plugin.

> **Revision note.** This document was rewritten on 2026-08-01 after three Compound V pre-flights
> (`docs/superpowers/archaeology/2026-07-31-zai-backend.md`,
> `docs/superpowers/expert/2026-07-31-zai-backend.md`,
> `docs/superpowers/library-audit/2026-07-31-zai-backend.md`) found defects in the first draft. The
> most serious: the first draft's `--allowedTools` list did not do what it claimed, leaving the
> worker without a `Write` tool while granting the `Bash` the draft said was withheld. Every
> correction below is measured, not reasoned.

## Verified facts

All probes ran on 2026-07-31/08-01 against `claude 2.1.207` and `codex-cli 0.144.4`, using a real
GLM Coding Plan key. Wire-level captures came from a local stub HTTP server standing in for the
Anthropic endpoint, so they cost no quota.

**Transport.** `claude -p` honours `ANTHROPIC_BASE_URL` and sends
`POST {base}/v1/messages?beta=true`, `anthropic-version: 2023-06-01`, `stream: true`.
`ANTHROPIC_AUTH_TOKEN` produces `Authorization: Bearer …`; `ANTHROPIC_API_KEY` produces `x-api-key`
and **no** `Authorization`. z.ai documents only the `Bearer` form. Both were observed working
against z.ai, so the choice is about documented support, not function — this spec uses
`ANTHROPIC_AUTH_TOKEN`.

**Model names.** z.ai validates them: an invented name returns
`API Error: 400 [1211][Unknown Model, please check the model code.][<trace-id>]`. Accepted on the
subscription: `glm-5.2`, `glm-5.1`, `glm-5`, `glm-5-turbo`, `glm-4.7`, `glm-4.6`, `glm-4.6v`,
`glm-4.5-air`, and Anthropic aliases such as `claude-opus-4-8`. Rejected: `glm-5.2-air`,
`glm-4.6-air`, `glm-5-fast`, `glm-5.2-fast`, `glm-5-flash`, `glm-4.6-flash`, `glm-5.2-turbo`.

> The Coding Plan's own documentation lists only three models — GLM-5.2, GLM-5-Turbo, GLM-4.7 — yet
> the others answered successfully on this key. The discrepancy is unexplained and is why the default
> map uses only the three documented models.

**Agentic loop.** Six worker jobs with the planner/executor lock, run concurrently, each added a
function to `calc.py` in 3 turns with zero permission denials. `git diff` confirmed **only**
`calc.py` changed in all six — the surrounding `README.md` and `tests/test_calc.py` decoys were left
alone by both models tested.

**Concurrency.** Two, four and six simultaneous requests all completed with **zero** 429s (~7 s per
round for trivial prompts; six real jobs finished in 13 s). A widely-cited field report claims Pro
enforces a concurrent limit of 1; that did not reproduce here. z.ai publishes no concurrency number
and states limits adjust dynamically, so this is one measurement on one account at one time, not a
guarantee — hence the configurable cap below.

**Codex cannot reach z.ai.** The installed binary contains
``` `wire_api = "chat"` is no longer supported. How to fix: set `wire_api = "responses"` ```, and
z.ai exposes no Responses API. This is why `zai` is its own backend rather than a codex provider
entry.

## Global constraints

- Opus by default for reviewers; **never Haiku**. This PR changes no model policy — see Non-goals.
- **anti-ruflo:** only real measured usage is recorded. No estimated or invented token/cost numbers.
- Enforcement fields (`blocked`, `files_changed`, `violations`) are **git-derived by the caller**.
- Every external-CLI launch goes through `scripts/compound-v-run-with-timeout.py` with
  `stdin </dev/null`.
- No `--dangerously-skip-permissions`, no `--yolo`, no bypass `--permission-mode`, on any path.

## Endpoint, credentials and isolation

The GLM Coding Plan is reachable on two compatibility layers, both distinct from the pay-as-you-go
paths:

| Layer | Subscription (Coding Plan) | Pay-as-you-go |
|---|---|---|
| Anthropic | `https://api.z.ai/api/anthropic` | same URL, only if a Coding Plan was never purchased |
| OpenAI | `https://api.z.ai/api/coding/paas/v4` | `https://api.z.ai/api/paas/v4` |

This adapter uses the Anthropic layer. The key comes from one environment variable, `ZAI_API_KEY`,
named in `.claude/compound-v.json` and detected by `/v:init`; the worker never reads a key from a
file inside the repo.

**The pinned invocation:**

```bash
python3 scripts/compound-v-run-with-timeout.py --timeout "$timeout_sec" --grace 3 -- \
  env -i PATH="$PATH" HOME="$SCRATCH" TMPDIR="$TMPDIR" LANG="$LANG" \
      CLAUDE_CONFIG_DIR="$SCRATCH/.claude" \
      ANTHROPIC_BASE_URL="https://api.z.ai/api/anthropic" \
      ANTHROPIC_AUTH_TOKEN="$ZAI_API_KEY" \
      ANTHROPIC_MODEL="$model" \
      ANTHROPIC_DEFAULT_OPUS_MODEL="$model" \
      ANTHROPIC_DEFAULT_SONNET_MODEL="$model" \
      ANTHROPIC_DEFAULT_HAIKU_MODEL="$model" \
      API_TIMEOUT_MS="$((timeout_sec * 1000))" \
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    claude -p --permission-mode dontAsk \
      --tools "Read,Edit,Write,Bash" \
      --allowedTools "Read,Edit,Write,Bash" \
      --exclude-dynamic-system-prompt-sections \
      --output-format json \
      -- "$(cat "$prompt_file")" </dev/null >"$out" 2>"$err"
```

Every element is load-bearing:

- **`env -i` with a four-name allow-list** — the same shape as the opencode worker's scrub, which
  exists because opencode was observed authenticating from an inherited ambient `ANTHROPIC_BASE_URL`.
- **`HOME` and `CLAUDE_CONFIG_DIR` point at a scratch directory outside the worktree.** This is what
  replaces `--bare` (see below). It removes the operator's hooks, plugins, skills catalogue and
  `CLAUDE.md` from the request, and it puts `~/.claude/.credentials.json` out of the worker's reach —
  which matters because a read-only `cat` is available in every permission mode and is not
  configurable.
- **All four model slots are set to the same resolved GLM model.** z.ai's own integration guide sets
  every slot; an unset small/fast slot sends an Anthropic identifier and earns the `1211` error above.
  The slot named `…_HAIKU_MODEL` is a Claude Code variable name, not a model choice — it is filled
  with a GLM model, so the never-Haiku policy is untouched. A comment in the worker must say so,
  because a reviewer grepping for `haiku` will find it.
- **`--tools` and `--allowedTools` are different things and both are required.** `--tools` decides
  which built-in tools exist; `--allowedTools` decides which run without asking. Measured: with only
  `--allowedTools`, `Write` was absent and `Bash` present — the exact inverse of the first draft's
  claim. With only `--tools`, `dontAsk` refused the write. `Grep` and `Glob` do not exist as tools in
  this CLI version at all; searching is done through `Bash`.
- **`--` before the prompt.** `--tools` and `--allowedTools` are variadic and will otherwise swallow
  the positional prompt.
- **`--exclude-dynamic-system-prompt-sections`** moves `cwd`, environment info and `git status` out
  of the cached system block. Without it the cacheable prefix diverges for every worker by
  construction, since each runs in a different worktree.

**Residual risk, stated plainly.** `--bare` guaranteed that OAuth and keychain are never read; this
invocation does not carry that guarantee, only the absence of stored credentials under the scratch
`HOME`. The compensating control is deterministic: the worker **asserts that the response's
`modelUsage` key is a GLM model** and fails the job otherwise. Any silent fall-back to another
credential path therefore surfaces as a failed job rather than an unnoticed charge.

## Why not `--bare`

`--bare` was the first draft's answer and is rejected on measurement. In bare mode the built-in tool
set is exactly `Bash, Edit, Read` — **`Write` does not exist and cannot be restored**; `--tools` can
only narrow within what is available. `Edit` modifies an existing file only, so a bare worker cannot
create a new file except by shelling out — and this very PR creates two new files.

Measured, same prompt, same directory:

| | tools | one request | credits/job (glm-5.2) | prefix shared across worktrees |
|---|---|---|---|---|
| no isolation | 53 | ~49 385 tokens | 50.4 | no |
| `--bare` | 3 (no `Write`) | ~1 179 tokens | 1.7 | no |
| **this spec** | 4 (`Bash,Edit,Read,Write`) | **~3 329 tokens** | **2.30 fresh / 0.57 cached** | **yes** |

The chosen invocation is the only one of the three that both gives the worker a `Write` tool and
produces a byte-identical `tools` and `system` prefix across two different worktrees — verified by
diffing two captured requests.

Note what the ~46k saving is not: it is not project context. It is ~29 168 tokens of tool
definitions the worker never calls (23 of them a design-service MCP, plus cron, notification and
scheduling tools), ~16 000 tokens of `SessionStart` hook output, and ~2 300 tokens of `CLAUDE.md`.
Today's `claude` backend never sees that block either — it dispatches an in-harness `Task`, and
`SessionStart` fires once per *session*; a subagent fires `SubagentStart`, whose measured output here
is 17 characters.

**Accepted losses.** The worker does not receive `CLAUDE.md`, so it does not know project
conventions unless the job prompt carries them; the manifest's `read_allowed` already auto-includes
the shared foundation and the pre-flight audits, and the job prompt is where any convention a task
depends on belongs. LSP is unavailable, so editor-side diagnostics are gone; the per-job `acceptance`
command is the deterministic check that must catch what a diagnostic would have hinted.

## Job contract

`job_spec` is unchanged. `zai` accepts `backend`, `prompt`, `tier`, `effort`, `model`, `cwd`,
`write_allowed`, `read_only`, `timeout_sec`, `network`.

`effort` **is** honoured: `claude --effort <low|medium|high|xhigh|max>` exists in 2.1.207 and accepts
`xhigh`. This contradicts both the first draft and `skills/backend-launcher/adapter-claude.md`, which
still says the `Task` path has no effort knob. Correcting the claude adapter is out of scope here, but
the plugin-wide rule that `xhigh` is codex-only is now factually wrong and must be flagged to the
maintainer rather than silently worked around; until it is resolved, `zai` accepts
`low|medium|high` and rejects `xhigh`, matching the documented rule rather than the observed CLI.

`network` and `read_only` are accepted for CLI parity; a read-only job is enforced post-hoc with an
empty `write_allowed`.

`job_result` is unchanged and assembled by the caller:

| Field | Source |
|---|---|
| `files_changed`, `violations`, `blocked` | `scripts/compound-v-scope-check.py`, git-derived |
| `status` | `blocked` → blocked; supervisor exit 124 → timeout; non-zero → error; else success |
| `summary` | `.result` — informational only |
| `session_id` | `.session_id`, a real UUID; the codex worker's validator applies unchanged |
| `worktree` | absolute worktree path (always set; `zai` is never `direct`) |
| `usage` | `.usage.input_tokens` / `.output_tokens`, `measured: true` |
| `failure_class` | see below; `null` on success/blocked |

**On cost:** `job_result.usage` has five fields — `input_tokens`, `output_tokens`, `advisor_calls`,
`backend`, `measured` — and no cost field, so the CLI's `total_cost_usd` (computed from Anthropic's
price table for a model that never ran) is not carried. Token counts come from z.ai's own response
and are real, so `zai` is **not** added to `UNMEASURED_BACKENDS`. The CLI's reported `contextWindow`
and `maxOutputTokens` are the alias's Anthropic defaults and are not recorded; only `glm-5.2` has a
1M window, and reaching it appears to require the distinct identifier `glm-5.2[1m]` rather than the
bare name — untested here and out of scope.

## Isolation, trust tier and concurrency

`isolation: worktree` is **mandatory**, a new entry beside the existing
`codex|antigravity|cursor|devin|opencode ⇒ worktree` invariant.

`zai` sits in the lower-trust, opt-in tier with antigravity and cursor: no kernel write-confinement,
so the worktree plus the git-derived gate **detects** an in-worktree scope leak but cannot **prevent**
an out-of-worktree side effect. Prefer codex for untrusted or high-stakes work.

`max_parallel` for `zai` is **configurable, default 4**. Six concurrent real jobs were measured
clean, but z.ai publishes no concurrency limit, states that limits adjust dynamically with plan tier,
and its usage policy recommends one project on Lite and one to two on Pro. The default sits below the
measured ceiling; anyone on Lite should lower it.

## Model resolution

`zai` is single-vendor: every resolved model is a bare GLM name, never a `provider/model` string.

```
deep     → glm-5.2
standard → glm-5.2
light    → glm-5-turbo
```

Identical in every stance, like all non-claude backends.

Credit consumption is `(input × Mi + cached × Mc + output × Mo) / 10 000`. Published multipliers:
glm-5.2 `6.9 / 1.7 / 24`, glm-5-turbo `5.7 / 1.5 / 21`, glm-4.7 `4.6 / 1.2 / 16`, glm-4.6v
`1.2 / 0.3 / 2.7`. Plan quotas are 2 000 / 12 000 / 28 000 credits per 5-hour window and
10 000 / 60 000 / 140 000 per week for Lite / Pro / Max, the weekly window counted from the purchase
date rather than the calendar.

At ~2.3 credits per job even the cheapest plan affords several hundred jobs per window, so quota is
not the binding constraint and the map is chosen for capability first. `glm-5.2` takes `deep` and
`standard` as the strongest model available.

`light` is `glm-5-turbo` on measurement, not on the multiplier table. Head-to-head on the same task,
three runs each: turbo averaged 8.5 s and 2.56 credits; glm-4.7 averaged 10.1 s and 2.38 credits.
Turbo is **16% faster** and glm-4.7 only **7% cheaper** — the multiplier table's apparent 32%
advantage mostly disappears because glm-4.7 emits ~60% more output. Scope discipline was
indistinguishable: both were 3/3 clean with no stray writes. glm-4.7 remains a documented config
override for anyone squeezing the weekly window; the counter-argument from its model card (it names
Claude Code, where turbo's card names a different harness) was considered and did not survive the
measurement.

Off-peak billing at half rate exists but is **promotional** and time-limited, so no arithmetic in this
document relies on it, and the worker does not schedule around it.

## Failure classification

The first draft claimed no quota-error shapes were observable. That was true of the probes and false
of the documentation: z.ai publishes the full surface — `1113, 1302, 1305, 1308, 1310, 1311, 1316,
1317`, all HTTP 429, each with a message template, in the envelope
`{"error":{"code":"XXXX","message":"…"}}`. No `Retry-After` header is documented anywhere; the reset
time is embedded in the message text.

`scripts/compound-v-classify-failure.py` therefore gains an **explicit `zai` branch** with a needle
set built from those codes. This is not optional politeness: the function's final `else` falls back to
`_CODEX_RULES`, so adding `zai` to the accepted backends without a branch would silently apply
OpenAI's needle set — including advice to run `codex login` — to GLM errors.

Two operational consequences must be honoured by the retry policy:

1. **No `Retry-After` means backoff must be conservative and bounded**, not derived from a header
   that will never arrive.
2. **Enforcement throttling is indistinguishable on the wire from ordinary rate limiting** — z.ai's
   April 2026 enforcement wave surfaced as codes in the same range. Aggressive retry against a
   provider that penalises repeat offences is therefore itself the hazard. Default: low retry ceiling,
   then circuit-break.

The classifier consumes JSON on **stdout**, not the `--stderr-file` every other worker passes, and
the `--backend claude` path is not reachable: it is gated on the backend string being exactly
`claude`, and it parses an `api_retry` event that exists only in `stream-json`. The `zai` worker
passes its own captured stdout file explicitly.

## Files touched

**New:** `scripts/compound-v-run-zai-worker.sh`, `skills/backend-launcher/adapter-zai.md`.

The worker is **not** a copy of any single existing worker. Per-block sources: worktree lifecycle and
baseline-SHA ordering from the codex worker; `write_allowed` expansion **with `set -f`** from the
opencode worker (the cursor worker omits it, which lets glob entries pathname-expand against the
launcher's cwd and corrupt the allow-list); the 11-argument `emit_job_result` carrying `usage` from
codex/opencode, not cursor's 10-argument form; bounded output capture; `session_id` shape validation.

**Edited:** `scripts/compound-v-resolve-model.py`; `scripts/compound-v-validate-manifest.py` (four
separate sites: `VALID_BACKENDS`, the worktree invariant, the reviewer prohibition, the selftest
fixtures); `schemas/job_result.schema.json`; `scripts/compound-v-usage-extract.py`;
`scripts/compound-v-collect-results.py`; `scripts/compound-v-classify-failure.py`;
**`scripts/compound-v-failure-policy.py`** — without a `FALLBACK` entry, a `zai` credit wall returns
`None` and **halts the whole run**; **`agents/parallel-dispatcher.md`** — its adapter table is what
tells the dispatcher which script to run, and `devin`/`opencode` are already missing from it;
`skills/backend-launcher/SKILL.md`; `skills/compound-v/execution-manifest.md`;
`skills/compound-v/routing-policy.md`; `commands/v-init.md`; `commands/v-models.md`;
**`.github/workflows/validate.yml`** (see Testing); `CHANGELOG.md`; `.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json` (version lockstep, CI-enforced).

`scripts/compound-v-usage-aggregate.py` needs **no** change — it never reads `usage.backend`.

## Testing

**Stub-first for argv and environment.** Following `scripts/test-advisor-worker-stub.sh`, a fake
`claude` on `PATH` asserts the pinned argv, the `--` terminator, that `env -i` forwards exactly the
allowed names and nothing else, and the success / BLOCKED / timeout paths.

**A stub cannot catch the class of bug that broke the first draft.** It validates argv, not the real
binary's interpretation of it — the `--allowedTools`/`--tools` inversion passed every conceivable argv
assertion. So the suite adds a **real-binary, no-network smoke test**: run the actual `claude` against
a local stub HTTP server and assert the captured request contains exactly the four expected tools.
That is the check that would have failed the first draft.

Selftests: `compound-v-resolve-model.py --selftest` gains `zai` tier assertions and keeps its existing
"no haiku in any stance map" assertion; `compound-v-validate-manifest.py` gains a fixture whose only
defect is `backend: zai` with `isolation: direct`, and one whose only defect is a `zai` reviewer job.

**Two CI gates the first draft cited do not exist.** `shellcheck` runs only over `hooks/*.sh`, and no
CI step executes any `scripts/test-*.sh` — the sweep covers `scripts/*.py` only. This PR must **add**
both: shellcheck over `scripts/*.sh`, and a step running the new stub and smoke tests.

The live verification recorded above is the acceptance evidence for what CI cannot reach. It is
reproducible with a Coding Plan key and is not re-run in CI.

## Compliance

Claude Code is a tier-1 officially supported tool for the GLM Coding Plan. z.ai's restriction targets
*bypassing* a supported tool — "directly invoking model APIs", "SDK-based access" — and this adapter
spawns the genuine binary, which makes its own HTTP calls. Anthropic's acceptable-use policy and
commercial terms contain no clause against pointing the CLI at a third-party endpoint; their
obligations attach to "accessing the Services", which a `zai` job does not do. Claude Code's own
headless documentation describes bare/scripted invocation as supported and expected.

Three z.ai clauses do bear on how this is used, and the adapter documentation must state them: the
plan is licensed to **one natural person**, credential **sharing is prohibited**, and
**"resell, sub-resell, repackage, aggregate, proxy"** is prohibited. A single operator dispatching
their own jobs is inside those lines; shipping this so a team shares one key would not be.

## Non-goals

- **No model-policy change.** The never-Haiku rule is enforced on frontmatter and on an explicit
  per-job `model`, but not on a `.claude/compound-v.json` map cell — verified: a config cell of
  `haiku` resolves successfully today. This PR neither closes that gap nor relies on it.
- **No reviewer or arbiter seat for `zai`.** `scripts/compound-v-epic-arbiter.py` matches model
  families by substring over `gpt`, `gemini`, `claude`, `opus`, `sonnet`, `grok`; `glm` is absent, so
  a GLM ballot buckets as `unknown` and could be deduped against an unrelated model. Adding the needle
  is a one-line change plus a test, and belongs to the follow-on that lifts this restriction.
- **No correction of `adapter-claude.md`'s effort claim**, though it is now known to be wrong.
- **No multi-model tier pool and no round-robin** (PR 2). **No rate-limit rerouting** (PR 3).
- **No time-of-day routing** around the promotional off-peak rate.
- **No generic "any Anthropic-compatible endpoint" backend.** Considered and rejected: this plugin
  pins each adapter to a flag set verified live against a named CLI version. Generalise later, from
  two live examples.

## Acceptance criteria

1. A manifest with `backend: zai, isolation: worktree` validates; the same manifest with
   `isolation: direct` fails with a message naming the invariant.
2. A `zai` reviewer job fails validation with a message naming the restriction.
3. `compound-v-resolve-model.py --backend zai --tier {deep,standard,light}` returns
   `glm-5.2`, `glm-5.2`, `glm-5-turbo` in every stance; `--effort xhigh` is rejected.
4. The real-binary smoke test captures a request whose `tools` array is exactly
   `Bash, Edit, Read, Write` — no more, no fewer.
5. `compound-v-classify-failure.py --backend zai` maps each of `1113, 1302, 1305, 1308, 1310, 1311,
   1316, 1317` to a rate-limit or credit class, and an unrecognised payload to `other` — never to a
   `_CODEX_RULES` verdict.
6. `compound-v-failure-policy.py` returns a reroute or a bounded retry for a `zai` quota failure, not
   a run halt.
7. A worker that writes outside `write_allowed` yields `blocked: true` with the offending paths in
   `violations`, and the caller does not merge.
8. `job_result.usage` carries real `input_tokens` / `output_tokens` with `measured: true`, and no cost
   value appears in the result or the aggregate.
9. A job whose response reports a non-GLM model fails rather than succeeding silently.
10. `env -i` forwards exactly `PATH HOME TMPDIR LANG` plus the declared `ANTHROPIC_*`, `API_TIMEOUT_MS`
    and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` variables; a probe with an ambient
    `ANTHROPIC_BASE_URL` pointing elsewhere does not reach the worker.
11. CI runs shellcheck over `scripts/*.sh` and executes the new tests, and every existing gate still
    passes.
