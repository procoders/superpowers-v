# Phase 1C — Library & Documentation Validation: v3.4.8 workflow retry

**Spec:** [`docs/superpowers/specs/2026-09-03-v3.4.8-workflow-retry-design.md`](../specs/2026-09-03-v3.4.8-workflow-retry-design.md)
**Plan (already drafted, read for context only):** [`docs/superpowers/plans/2026-09-03-v3.4.8-workflow-retry.md`](../plans/2026-09-03-v3.4.8-workflow-retry.md)
**Date:** 2026-09-03 · **Topic slug:** `v3-4-8-workflow-retry`

There are no third-party (npm/pip/registry) libraries in this spec — confirmed by `Glob` for
`package.json`/`requirements.txt`/`pyproject.toml`/`Cargo.toml`/`go.mod`/`Gemfile`/`composer.json`/lockfiles
at repo root: **none exist** (consistent with the 2026-09-02 KB entry — this repo is bash + Python3 stdlib +
emitted-JS-as-a-string by construction). The one real "library" surface this spec touches is **Claude Code's
own native `Workflow` (`RunWorkflow`) script runtime** — specifically the `agent()` promise-resolution
contract — plus the **Anthropic API's transient-error taxonomy** the classifier regex is built to match.
Both are validated below against live sources, not training data.

---

## 0. V-memory recall (Step 0)

`compound-v-memory.py search` run three times (`"workflow retry design"`, `"native Workflow tool retry
resume"`, `"Engine C workflow script API resume"`, `--intent planning --top 8`). Relevant hits used below:

- The **plan already exists** and drafts a workaround for the no-filesystem constraint (`retries.jsonl`
  written by Record via Bash, never by the JS script directly) — read in full, cited in §3.
- **`docs/superpowers/preflight/2026-09-01-v3.0-1c-docs.md`** — the prior Phase 1C audit for this same
  `Workflow` runtime, two days old, `BINARY`-sourced against installed Claude Code `2.1.238`. Its `agent()`
  contract is the primary prior evidence for this audit's headline finding (§4-1) and is re-verified live
  below, not assumed.
- **`docs/superpowers/library-audit/_knowledge-base/claude-code-runtime.md`** — three prior 2026-09 entries
  already document this exact runtime; this audit's update is appended as a fourth, not a rewrite (§9).
- No V-memory hit disagreed with anything below. Nothing here is stale prose overridden by code — it is a
  fresh live-doc finding the *existing* code already, correctly, works around in two of three places.

---

## 1. Tools Available

| Tool | Status | Note |
|---|---|---|
| Context7 MCP | ❌ **not attached to this subagent** (`ToolSearch "context7 resolve-library-id query-docs"` → no match) | Consistent with three same-week 1C runs recorded in the KB (2026-09-03 triage-size, 2026-09-03 readme-clarity). Also **not applicable** here regardless — Claude Code's own runtime and the Anthropic API's HTTP error taxonomy are not Context7-indexed packages. |
| WebFetch | ✅ used, primary source | Full live fetch of `code.claude.com/docs/en/workflows.md`, 2026-09-03. |
| WebSearch | ✅ used, triangulation | Anthropic API error taxonomy, TypeScript SDK default retry behavior, `agent()` `opts.model` values — each cross-checked against ≥2 independent origins. |
| Local Bash / binary string-extraction | ❌ **not available this spawn** | `bashCommandClamp` on this agent permits only `compound-v-memory.py search`/`recall-check` — no `claude --version`, no `strings`, no `find`. Unlike the 2026-09-01 1C audit, this run cannot re-extract the binary's own tool description. Repo code (`Read`/`Grep`, unrestricted) substitutes as a second live source below. |
| Dependency manifests | n/a | None exist in the tree (confirmed by `Glob`, this session). |
| Repo code as corroborating evidence | ✅ used | `scripts/compound-v-emit-workflow.py`'s **already-shipped, dogfooded** JS template is read (narrowly, around `agent()` call sites) to check what error-handling shape the current, working implementation actually uses — not to re-do Phase 1A's archaeology, but because it is a second, independent, currently-*running* confirmation of the documented `agent()` contract. |

**DEGRADED, partially:** Context7-equivalent for this runtime doesn't exist by design (not a registry
package); WebFetch/WebSearch are fully functional and are this audit's primary sources.

---

## 2. Libraries Mentioned

| Name | Spec context | Current state | Repo pinned | Last verified | Maintenance | Status |
|---|---|---|---|---|---|---|
| Claude Code `Workflow`/`RunWorkflow` script runtime — `agent()`, `pipeline()`, `budget` | Every `agent()` call in the JS template is wrapped in `withRetry` | Live doc `code.claude.com/docs/en/workflows.md`, fetched in full 2026-09-03 | Repo floor implied `>= 2.1.219` (from the 2026-09-01 1C audit; not restated in this spec) | 2026-09-03 (this audit) | Active — Anthropic first-party, doc dated to current release cadence | 🟠 see §4-1, §5-2 (behavior drift from the spec's assumption, not staleness) |
| Anthropic Messages API error taxonomy (`overloaded_error` 529, `rate_limit_error` 429) | `withRetry`'s classifier regex: `529\|Overloaded\|overloaded_error\|rate.?limit\|429\|ECONNRESET\|ETIMEDOUT\|network` | `docs.anthropic.com/en/api/errors`, WebSearch-triangulated 2026-09-03 across 3 independent sources | n/a (no SDK call site — Compound V never calls the Messages API directly; it goes through `agent()`) | 2026-09-03 | Active, unchanged core taxonomy | 🟢 current — `overloaded_error`/`rate_limit_error`/429/529 strings are still correct as of today |
| `@anthropic-ai/sdk` (TypeScript) default retry (`maxRetries: 2`, exp. backoff + ≤25% jitter) | Not called directly, but the spec's backoff shape ("2 s → 4 s → 8 s… ± jitter, capped 60 s") is analogous | WebSearch-confirmed 2026-09-03 (GitHub `client.ts`, npm) | n/a — this repo never imports the SDK; `compound-v-failure-policy.py`'s own `_backoff()` is authoritative and pre-exists this spec | 2026-09-03 | Active | 🟢 informational only, not load-bearing |

---

## 3. API Signatures Verified

### `agent(prompt, opts?)` — the load-bearing signature for this entire spec

Verbatim from `code.claude.com/docs/en/workflows.md`, fetched in full 2026-09-03:

> "An `agent()` call **resolves to `null`** if you stop it mid-run or **it hits an unrecoverable API
> error**. `pipeline()` keeps that `null` in the results array, which is why the example ends with
> `.filter(Boolean)` to drop those entries."

This is the **complete, general** statement of `agent()`'s error-resolution behavior on the current live
doc — there is no separate documented "throws on a transient API error" path. It corroborates, word for
word in substance, the 2026-09-01 1C audit's independent `BINARY` extraction from the installed executable:
*"`agent` return … Returns `null` if skipped or terminally errored."* Two independent methods (rendered doc
today; binary string extraction two days ago), two days and one full engine version-range apart, agree.

**Third, independent corroboration — this repo's own shipped code.** `scripts/compound-v-emit-workflow.py`'s
JS template, already dogfooded on Engine C, handles `agent()` results with **both** a `try/catch` *and* an
explicit `=== null` check at every call site — e.g. `recordStage` (`:2227-2248`):

```js
const ack = await agent(prompt, { label: 'record ' + job.id, phase: 'Record', schema: RECORD_SCHEMA, ... });
if (ack === null || ack === undefined) {
  return { job_id: job.id, recorded: false, reason: 'record agent returned null' };
}
return ack;
} catch (e) {
  return { job_id: job.id, recorded: false, reason: 'record stage caught: ' + String(e && e.message ? e.message : e) };
}
```

The same dual pattern repeats in `gateStage` (`:2171-2179`) and `finalizeWave` (`:2299-2309`). This is the
current implementer(s) having *already* learned, empirically, that `agent()` has two distinct failure
surfaces — and, critically, **the `null` branch carries zero error detail**: the reason string is a static
literal (`'record agent returned null'`), never `String(err)`, because there is no `err` on that path.

### `opts.model` accepting `'fable'`

Not new to this spec — already exercised and selftested (`compound-v-emit-workflow.py:1072,5722,5764-5796`,
`routing-policy.md:107-108,283`: `frontier` → `fable` on the `claude` ladder). WebSearch (2026-09-03)
independently confirms `fable` (`claude-fable-5`) is a current, valid `opts.model` alias. **Not a finding** —
flagged only to confirm the reviewer-lift's model string is correct; the *substitution* risk around it is
§5-3.

### Sandbox constraints (re-fetched in full, 2026-09-03, for drift against the 2026-09-01 `BINARY` wording)

| 2026-09-01 (`BINARY`, installed 2.1.238) | 2026-09-03 (`FETCHED`, live doc) | Drift? |
|---|---|---|
| "No filesystem or Node.js API access." (single combined clause) | "No direct filesystem or shell access from the workflow itself" / "No module loading: a script that contains `import()` fails" (two separate, narrower bullets) | **Possible narrowing, not confirmed** — see §5-1. The live doc no longer states a blanket "no Node.js API" prohibition; it names filesystem/shell access and `import()` specifically. Whether this is a wording simplification or an actual behavior change (e.g. whether JS runtime globals like `setTimeout` are in scope) is **unverified either way**. |
| Concurrency `min(16, availableCPUs − 2)`, 1000 agents/run, 4096 items/call | Same three numbers, verbatim | none |
| `opts`: `label, phase, schema, model, effort, isolation, agentType` | Same six named in prose; `disallowedTools`/`bashCommandClamp` still **not mentioned anywhere** in the full fetched page | none — see §6-4 |
| Determinism ban: `Date.now()`, `Math.random()`, argless `new Date()` throw | Same, verbatim ("Claude Code makes `Date.now()`, `Math.random()`, and a no-argument `new Date()` throw") | none |

---

## 4. Critical Findings 🔴

### 🔴-1 · `withRetry`'s catch-a-thrown-error design will not fire for the exact failure class this spec exists to fix

**The spec's own Probe:** *"Three consecutive `API Error: 529 Overloaded` on the Opus reviewer (r8–r10 of
v3.4.6)… each cost a run."* **Decision #1:** *"wraps every `agent()` call … in `withRetry(label, fn)`: on
a **thrown error** whose message matches the transient classes … it waits … and retries."*

Per §3, `agent()`'s documented behavior for an unrecoverable API error (which a 529/Overloaded exhaustion
is) is to **resolve its promise to `null`**, not throw — confirmed independently by the live doc (2026-09-03),
the prior `BINARY` extraction (2026-09-01), and this repo's own already-shipped code's dual-handling pattern
(which records `null` with **no** error text, because none exists to record).

`withRetry(label, fn)`'s `try { await fn() } catch (err) { … classify String(err) … }` structure, exactly as
Decision #1 specifies it, **only fires on the throw path** — the one used for setup/programmer errors
(unknown `agentType`, exceeded `budget`, malformed options). It will not fire when `agent()` quietly returns
`null` on an overloaded/rate-limited/network exhaustion, which per every source checked is the documented
resolution for that class. As spec'd, the retry logic can ship, pass its own selftests against a stub that
`throw`s (per the plan's Task A: *"a fake `agent()` that throws twice"*), and still **never engage** on a
real production 529 — the identical failure the feature was commissioned to fix.

**A second, compounding consequence for Decision #2.** *"Record the class honestly … `failure_class` from
the classifier's class … not `other`."* The `null` path carries **no message to classify** — not `overloaded`,
not `rate_limited`, nothing. There is no reachable signal inside the documented `agent()` contract that
distinguishes *why* it returned `null`. Decision #2's promise cannot be honored for this path without an
additional source of that detail that no source consulted (live doc, prior binary extraction, or this repo's
current code) shows existing.

**Constraint:** `withRetry` MUST treat a `null`/`undefined` resolution from `agent()` — not only a thrown
exception — as the retry trigger; a design that only wraps the throw path is retrying the wrong failure
mode. The plan MUST NOT promise a specific `failure_class` (`overloaded`/`rate_limited`/`network`/`timeout`)
for the `null` path unless a reachable source for that detail is identified first — absent one, the honest
record for that path is `other` (or a new, explicitly-named `unknown_null` class), not an invented specific
one. The plan's fixture ("a stub agent in the emitter selftest" that *throws* twice, per AC-1) should be
extended to also cover a stub that *resolves to `null`* twice — the throwing-stub test alone will pass while
this defect ships.

---

## 5. High-Priority Findings 🟠

### 🟠-1 · Backoff-wait mechanism (`setTimeout`/timer-based delay) is unverified inside the script sandbox

Decision #1's backoff step — *"waits the policy's backoff (`_backoff(attempt)` mirrored in JS: 2 s → 4 s →
8 s… ± jitter, capped at 60 s)"* — requires the script to literally suspend execution for up to 60 real
seconds between attempts. This needs `setTimeout` (or an equivalent timer) inside the sandboxed JS.

The current live doc's sandbox table (§3, right column) no longer states the 2026-09-01 `BINARY` extraction's
blanket "no filesystem or **Node.js API** access" — it now separately names "no filesystem or shell access"
and "no module loading (`import()`)." Whether that is a doc simplification (still true, just phrased
narrower) or an actual capability change is **not resolvable from either fetched source**, and this audit has
no Bash or Context7 access this spawn to binary-extract or live-probe it directly (`bashCommandClamp` allowed
only the V-memory script). **This repo's own already-shipped JS template — dogfooded on Engine C — contains
zero occurrences of `setTimeout` or `await new Promise(...)`-style delays anywhere** (`Grep`, this session):
the backoff-wait this spec proposes has never been exercised by this codebase's Workflow scripts before.

**Constraint:** before Task A is built, run one live, throwaway probe — a `RunWorkflow` script whose entire
body is `await new Promise(r => setTimeout(r, 1000)); return 'ok';` — from a session where the tool is
reachable (main session; per the KB, a subagent cannot see the `Workflow` tool at all). If `setTimeout` is
unavailable, Decision #1's backoff step needs a different mechanism (e.g., an agent-side wait, or accepting
the harness's own default pacing) before it can ship as designed.

### 🟠-2 · A reviewer's escalation to `fable` can be silently substituted by an org's model allowlist

Live doc, 2026-09-03: *"When your organization's `availableModels` allowlist blocks a model the script
requests for an agent, that agent runs on a **substituted model** instead, following the same substitution
rules as subagents. The run's progress view in `/workflows` shows a warning naming both the requested and
substituted models."* That warning is a **`/workflows` UI-only** surface — nothing in the fetched doc
indicates it reaches the script's `agent()` return value or any inspectable field.

Decision #3: *"a review job … is re-spawned once on tier `frontier` (Fable) … and the receipt notes
`escalated_from: deep`."* If an org's `availableModels` allowlist excludes `fable`, the re-spawned agent
silently runs on a substituted (lower) model while the receipt still asserts the escalation happened —
an unverifiable audit-trail claim, which cuts against this spec's own stated ethos ("measured, never
estimated," Acceptance item 6).

**Constraint:** the receipt SHOULD NOT assert `escalated_from: deep` implies the frontier model actually ran
unless that is independently verifiable (e.g., asking the escalated agent to report its own model identity as
part of its structured output, if that is knowable to it) — or the design should explicitly accept and
document this as a known, unclosed gap rather than an implicit guarantee.

---

## 6. Medium Findings 🟡

**🟡-3 · Version floor not restated for this spec.** The 2026-09-01 1C audit set `>= 2.1.219` as the
recommended floor for anything built on the Workflow runtime; this spec builds directly on `agent()`/
`pipeline()`/error-resolution and does not restate a floor. Not new information — carry it forward explicitly
rather than relying on it being inherited implicitly.

**🟡-4 · `/workflow-authoring` skill availability unconfirmed this session.** Floor `v2.1.248`; recorded
`NOT AVAILABLE` locally on 2026-09-01 (installed `2.1.238`). This audit has no Bash access to re-check the
locally installed version two days later. Low risk for this spec specifically — Task A's own selftests are
string-checks on the emitted script and a Python-side backoff simulation, not skill-mediated authoring — but
worth reconfirming before relying on the skill for anything else in this feature's build.

**🟡-5 · `bashCommandClamp`/`disallowedTools` remain undocumented as of 2026-09-03, and this spec makes them
fire more often.** The 2026-09-01 1C audit flagged these two `agent()` options (already used by this repo's
`recordStage`/`finalizeWave`) as present in the binary's option-validation list but **absent from both the
public doc and the tool's own reference text** — "building on them is building on sand." The full live fetch
today reconfirms: neither string appears anywhere on `code.claude.com/docs/en/workflows.md`. This is
pre-existing code the v3.4.8 spec does not introduce or modify — but Task A's `withRetry` wraps these exact
call sites, so an undocumented option that could silently change behavior in a future Claude Code release
now gets exercised up to `retry.max_attempts` times per call (default 3×) instead of once. Not blocking; the
plan's Task A selftests should confirm the clamp/disallowed-tools options survive unchanged across retries of
the same call.

---

## 7. Design Constraints for the Plan

Non-negotiable, each traced to a finding above.

**MUST**
1. Treat a `null`/`undefined` `agent()` resolution — not only a thrown exception — as `withRetry`'s retry
   trigger. (🔴-1)
2. Not assert a specific `failure_class` (`overloaded`/`rate_limited`/`network`/`timeout`) for the `null`
   path unless a reachable source of that detail is found first; record it honestly as `other`/an explicit
   `unknown_null` otherwise. (🔴-1)
3. Extend AC-1/AC-2's fixtures to include a stub `agent()` that **resolves to `null`** twice then succeeds
   (or exhausts), not only one that throws — the throw-only fixture the plan currently describes will pass
   while 🔴-1 ships unfixed. (🔴-1)
4. Live-probe `setTimeout`/promise-based delay availability inside an actual `RunWorkflow` script from a
   session where the tool is reachable, before building the backoff-wait step. (🟠-1)
5. State a Claude Code version floor (`>= 2.1.219`, inherited from the 2026-09-01 audit) explicitly in this
   feature's own docs, not only by inheritance. (🟡-3)

**MUST NOT**
6. Assume `agent()` throws on a transient API failure as its general error-surfacing mechanism — the
   documented, binary-confirmed, and already-self-consistent-in-this-repo behavior is a `null` resolution
   for that class. (🔴-1)
7. Present the reviewer-lift receipt's `escalated_from: deep` as a guarantee the frontier model ran, given
   the documented `availableModels` silent-substitution behavior, without independent verification or an
   explicit documented caveat. (🟠-2)

---

## 8. Open Questions for the Human

1. **Does the Workflow script sandbox support `setTimeout` (or any timer-based delay) at all?** Genuinely
   unresolved by every source this audit could reach — the two fetched-doc snapshots (2026-09-01 `BINARY`,
   2026-09-03 live) phrase the sandbox's Node.js-API restriction differently enough that neither confirms
   nor denies it, and this repo has never used one. This blocks Decision #1 as designed until answered.
   (🟠-1)
2. **Is there any reachable signal — on the `agent()` return value, in `budget`, or elsewhere in the script
   API — that distinguishes *why* a call resolved to `null`** (overloaded vs. rate-limited vs. network vs.
   a user-initiated stop)? If none exists, Decision #2's "record the class honestly" promise needs to be
   scoped down for the majority of real-world transient failures, which is a design decision, not a
   documentation gap this audit can close. (🔴-1)
3. **Given 🟠-2, is a silently-substituted "escalation" acceptable, or does the reviewer-lift need its own
   verification step** (e.g., the escalated agent reporting its own model identity)? Scoping decision, not
   a library-currency question.

---

## 9. Knowledge Base Updates

Appended to
[`docs/superpowers/library-audit/_knowledge-base/claude-code-runtime.md`](_knowledge-base/claude-code-runtime.md)
under `## Updated 2026-09-03 — v3.4.8 workflow retry (agent() null-vs-throw contract)`: the full live-fetched
`agent()` null-resolution quote, the three-way corroboration (live doc / 2026-09-01 binary extraction / this
repo's own shipped dual-handling code), the sandbox-wording drift table from §3, and the still-undocumented
`bashCommandClamp`/`disallowedTools` reconfirmation. Prior entries were not altered; this is a pure append
per the KB's own convention.
