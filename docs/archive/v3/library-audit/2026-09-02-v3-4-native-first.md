# Phase 1C — Library & Documentation Validation: v3.4 native-first design

**Spec:** [`docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md`](../specs/2026-09-02-v3.4-native-first-design.md)
**Date:** 2026-09-02 · **Branch:** `main` (worktree jobs not yet dispatched — `docs/superpowers/execution/2026-09-02-v3.4-native-first/state.json` shows `PARTITION_VERIFIED`, all five jobs `pending`) · **Local Claude Code:** `2.1.238`

**Step 0 (V-memory).** Five queries run before any file was opened: "epic goal loop schedule native
mechanisms", "triage UserPromptSubmit hook scorer", "ProposeGoal /loop /schedule cron ScheduleWakeup",
"dashboard serve workflows tasks scorecard results json", "hooks.json timeout UserPromptSubmit budget",
plus a targeted "hooks.json exists timeout field registration schema". All returned real hits — the
index reported "65 new / 0 removed docs behind the repo" on every call (stale by files added since the
last `/v:memory-refresh`, not by content quality of what it did return). The two most load-bearing hits
were the project's own [`native-mechanisms.md`](../architecture/native-mechanisms.md) and
[`2026-09-02-viability-audit.md`](../architecture/2026-09-02-viability-audit.md) §7 — the spec's own
cited source — both read in full below. Where this audit repeats a claim from those docs it says so;
where it adds new evidence, that is marked `PROBE (this audit)`.

**Headline.** This spec has no third-party library in it — same situation the 2026-09-01 and
2026-09-02 (preflight-workflow-probe) 1C audits for this repo already established, reconfirmed here:
`PROBE`, no `package.json`/`requirements.txt`/`pyproject.toml`/`go.mod`/`Cargo.toml`/`Gemfile`/
`composer.json` anywhere in the tree. The "libraries" under audit are four Claude Code native
mechanisms the spec proposes to depend on for the first time: `ProposeGoal`, `/loop` (backed by
`CronCreate`/`CronList`/`CronDelete` for interval mode, `ScheduleWakeup` for dynamic mode), `/schedule`,
and `/workflows`+`/tasks`. **One of the four checks out with a live schema in hand and surfaces a real
gap the spec's own honesty-boundary language misses (Critical §4). Two of the four (`ProposeGoal`,
`ScheduleWakeup`) are not independently re-verifiable from where this audit runs, and that limit is
itself worth recording (High §5).**

---

## 1. Tools Available

| Tool | Status | Note |
|---|---|---|
| Context7 MCP | ❌ **not attached to this subagent** — `ToolSearch "context7 resolve-library-id query-docs"` → no match. The 2026-09-02 preflight-workflow-probe audit (same day) had it (`mcp__context7__*`); this spawn does not. Not applicable regardless: no library in this spec is Context7-indexed. |
| Live `ToolSearch` probe from inside this subagent | ✅ **primary source for §3, §4** | Fetched the real `CronCreate`/`CronList`/`CronDelete` schemas (below). Same methodology the 2026-09-01 and 2026-09-02 1C audits used for `Workflow`/`RunWorkflow`. |
| Local binary string extraction | not run this pass | Not needed — the CronCreate/List/Delete schemas came back as live tool definitions, a stronger source than `strings` on the binary for this question (it is what will actually be handed to the model). The prior two 1C audits already did the `strings` pass for the `Workflow`/`Stop` contracts this spec also relies on; reused, not repeated. |
| WebFetch / WebSearch | not used | Nothing here is a public-doc question; the methodology warning already on file (`claude-code-hooks.md`: a `WebFetch` of the hooks page fabricated a contract on its second call) argues for binary/tool evidence over fetched prose whenever both are available, and both were. |
| Dependency manifests | n/a | none exist (see Headline). |
| `hooks/hooks.json` (repo) | ✅ read | Ground-truths the spec's own `timeout: 10` claim (§3). |

**Not DEGRADED** — every claim below is either a live tool schema fetched in this session, a repo
file read in this session, or an explicit citation to a same-day sibling audit's `BINARY`/`FETCHED`
evidence (never re-asserted as if newly verified by this audit).

---

## 2. Libraries Mentioned

| Name | Spec context | Current state (live, this session) | Repo/spec assumption | Status |
|---|---|---|---|---|
| `ProposeGoal` tool | WS1 §0d — propose the marathon completion condition | **Not visible to this subagent.** `ToolSearch "select:ProposeGoal"` → no match. Documented same-day (`native-mechanisms.md`, `BINARY`-graded, gathered from the main authoring session, not a subagent) as real: one goal/session, `ask_user` default true, plan-mode blocks it, `@internal.disabled` toggle. | Spec already has a graceful fallback ("If the tool is absent: print exactly that as `/goal <condition>`"), so this is a verification-coverage gap, not a design defect. | 🟡 see §5 |
| `/loop [interval] <prompt>` skill | WS1 §0c — resurrection, this-session tier | **Confirmed live** — this session's own skill listing: *"Run a prompt or slash command on a recurring interval... Omit the interval to let the model self-pace."* Matches the spec's interval/dynamic split exactly. | Correct | 🟢 OK |
| `CronCreate` / `CronList` / `CronDelete` | WS1 — named as `/loop` interval mode's underlying mechanism | **Confirmed live**, full schema fetched this session (§3). **Carries a 7-day auto-expiry the spec does not carry forward** (§4). | Partially correct — the mechanism exists and matches the "shares session's fate" framing, but the spec drops a real constraint | 🔴 see §4 |
| `ScheduleWakeup` | WS1 — `/loop` dynamic mode, `stop: true` termination | **Not visible to this subagent.** `ToolSearch "select:ScheduleWakeup"` → no match. Not independently reproducible from here; see §5. | Unconfirmed by this audit | 🟡 see §5 |
| `/schedule` (cloud routines) | WS1 §0c, alternative resurrection tier | **Confirmed live** — this session's own skill listing: *"Create, update, list, or run scheduled cloud agents (routines) that execute on a cron schedule... a one-time scheduled run."* Matches "genuine machine-off path" and the one-shot-run framing. | Correct | 🟢 OK |
| `/workflows`, `/tasks` (native progress UI) | WS3a — replaces `/v:dashboard serve` | Not independently re-probed this session (no UI surface reachable from a headless subagent). Inherited from the 2026-09-01 1C audit's `BINARY`-graded `RunWorkflow`/`phase()`/`log()` evidence, which this spec's WS3a text quotes almost verbatim ("the progress tree Engine C populates through `phase()`/`log()`"). | Consistent with existing KB; not newly verified | 🟢 accepted-on-file |
| `hooks/hooks.json` `UserPromptSubmit` `timeout: 10` | Global constraints — "`UserPromptSubmit`: `timeout: 10` in `hooks.json`" | `PROBE` (this audit) — read the file: `hooks/hooks.json:47`, `"timeout": 10` on the existing `triage-prompt-nudge.sh` registration, verbatim. | Correct, already true today — WS2 changes the hook body, not this registration | 🟢 OK |
| `PostToolUseFailure` / `tool-failure-ledger.sh` | WS3c — to be removed | `PROBE`: both exist today, `hooks/hooks.json:110-122` (`async: true`, `timeout: 5`). Matches the viability audit's "registered 3.3.0, no reader" finding. | Correct, nothing stale in the *removal* claim itself | 🟢 OK |
| PyYAML ("soft... via the shared loader, never a hard dependency") | Global constraints | `PROBE`: `import yaml` in `scripts/compound-v-emit-workflow.py` is guarded by `except ImportError` at three call sites (`:4469-4476`, `:4850-4852` — degrades to `have_yaml = False`), **but** a fourth, `_load_yaml()` (`:181-187`), `raise SystemExit("PyYAML is required...")` on `ImportError` — a genuine hard dependency for whatever selftest path calls it. Manifest job `observe-native`'s own body already knows this ("Run the emit-workflow selftest with `/usr/bin/python3` [it needs PyYAML]"). | The global-constraints sentence is accurate for the *triage* engine (`compound-v-preeval.py:109`, which really is unconditionally soft) but overgeneralizes to `compound-v-emit-workflow.py`, where one path is hard | 🟡 see §6 |

---

## 3. API Signatures Verified

**`CronCreate`** (live tool schema, this session, verbatim):

```
cron: string (5-field, local time)
prompt: string
recurring: boolean (default true)
durable: boolean — "Has no effect — durable persistence is not available.
                    All jobs are session-only (in-memory, gone when this Claude session ends)."
```

> "Jobs only fire while the REPL is idle (not mid-query)."
> "Recurring tasks auto-expire after 7 days — they fire one final time, then are deleted. This
> bounds session lifetime. **Tell the user about the 7-day limit when scheduling recurring jobs.**"
> "The scheduler adds a small deterministic jitter... recurring tasks fire up to 10% of their period
> late (max 15 min)."

**`CronList`** — no parameters, lists jobs from this session's in-memory store.
**`CronDelete`** — `{id: string}`, cancels a job from this session's in-memory store.

| Element | Spec's claim (WS1) | Verified this session | Verdict |
|---|---|---|---|
| `/loop` interval mode = a cron entry, torn down with `CronList`/`CronDelete` | "interval mode is a cron entry (`CronList`/`CronDelete`)" | Consistent: `CronList`+`CronDelete` are exactly the pair a caller needs to discover-and-cancel a `CronCreate` job; no other cron-like tool exists in this session's surface | ✅ shape correct |
| `/loop` "shares the session's fate exactly as the old tier-1 did" | Honesty boundary, WS1 | `CronCreate`: "jobs live only in this Claude session — nothing is written to disk, and the job is gone when Claude exits" | ✅ correct |
| 7-day expiry belongs only to "our schedulers" and can be deleted | Honesty boundary, WS1: *"The `:17/:47` cadence, the 7-day expiry, the resume cap and the 'one catch-up per wake' paragraphs are deleted — they described our schedulers."* | `CronCreate`, verbatim: **"Recurring tasks auto-expire after 7 days — they fire one final time, then are deleted."** The replacement mechanism carries the identical constraint the deleted paragraph described. | ❌ **false as stated — see Critical §4** |
| `ProposeGoal` semantics (condition shape, `ask_user: true` default, plan-mode block, `/goal clear`, `@internal.disabled`) | "What the binary offers" | Not independently reproducible from this subagent's tool surface (§5) | ⚠ unconfirmed here, inherited from same-day sibling evidence |
| `ScheduleWakeup` + `stop: true` for dynamic-mode termination | "What the binary offers" | Not independently reproducible from this subagent's tool surface (§5) | ⚠ unconfirmed here |
| `/schedule` = cloud routines, cron **or one-time** | "runs without the local machine" | This session's own skill description: *"Create, update, list, or run scheduled cloud agents (routines)... a one-time scheduled run."* | ✅ confirmed, including the one-time case the spec doesn't explicitly call out |

---

## 4. Critical Findings 🔴

### 🔴-1 · The native `/loop` interval mode inherits the exact 7-day expiry the spec deletes as obsolete

**Claim in the spec (WS1, Honesty boundary):** *"The `:17/:47` cadence, the 7-day expiry, the resume
cap and the 'one catch-up per wake' paragraphs are deleted — they described our schedulers."*

**Live evidence, this session, `CronCreate` tool description, verbatim:**

> "Recurring tasks auto-expire after 7 days — they fire one final time, then are deleted. This bounds
> session lifetime. **Tell the user about the 7-day limit when scheduling recurring jobs.**"

The spec's own §"What the binary offers" names `CronCreate`/`CronList`/`CronDelete` as `/loop`
interval mode's mechanism. That mechanism auto-expires after 7 days. The old, deleted
`compound-v-headless-shim.py`/`compound-v-epic-watch.py` machinery had its *own* 7-day story (per the
viability audit, 1 088 lines of it) — but deleting the disclosure paragraph on the premise that it
"described our schedulers" is not true of this specific fact. The replacement carries the same number.

**Impact.** A marathon epic armed with `/v:epic --stance marathon` and resurrected via
`/loop 30m /v:epic <epic-id>` will, seven days in, fire once more and then have its cron entry silently
deleted — no error, no `additionalContext`, nothing in `state.json`, nothing a human reads unless they
happen to notice the epic stopped progressing. The design's own WS1 §0c termination logic (`ScheduleWakeup
stop` / `CronDelete` when the epic reaches a terminal status) handles the *clean* end of a loop; it has no
branch for "the loop ended because a week passed while the epic is still running." The tool's own guidance
— *"Tell the user about the 7-day limit when scheduling recurring jobs"* — is advice to the caller
(`/v:epic` itself, at the moment it offers `/loop`), and nothing in WS1's replace-text for
`commands/v-epic.md` §0c or `skills/compound-v/epic-mode.md`'s "honesty boundary" section currently does
that telling. Given the project's explicit "no fabricated metrics... a mechanism names its caller" ethos
already in this very spec's Global Constraints, silently dropping a real constraint about the mechanism
being adopted is the same failure class the honesty-boundary section exists to prevent, just aimed at
the code's own claims instead of a user-facing metric.

**Constraint:** WS1 §0c (`commands/v-epic.md`) and the "honesty boundary" replacement text in
`skills/compound-v/epic-mode.md` MUST state, in the sentence that offers `/loop`, that the interval-mode
loop auto-expires after 7 days (fires once more, then is gone) and that a marathon expected to outlive a
week needs either a fresh `/loop` re-arm or `/schedule` instead. This is a one-sentence fix, not a redesign
— but it belongs in the plan the manifest jobs (`epic-native`, task A5/A6) execute, not discovered after
`/v:epic` ships and a real week-plus marathon goes quiet.

---

## 5. High-Priority Findings 🟠

### 🟠-1 · Two of WS1's four load-bearing native tools are not independently verifiable from a Phase 1C subagent

`ToolSearch "select:ProposeGoal"` and `ToolSearch "select:ScheduleWakeup"` both returned **"No matching
deferred tools found"** in this session — in contrast to `CronCreate`/`CronList`/`CronDelete`, which
returned full schemas on the first try, and to `Workflow`/`RunWorkflow`, which the 2026-09-01 1C audit
found absent from a subagent's surface too (its 🟠-4, `ToolSearch "select:Workflow,RunWorkflow"` → no
match). The pattern across three separate 1C audits now (2026-09-01, this one) is consistent: **session-
scoped, interactive tools (goal-setting, dynamic self-pacing, ad-hoc workflow launch) are not exposed to
a spawned subagent**, while stateless session-store tools (`CronCreate`/`List`/`Delete`) are.

This is not evidence that `ProposeGoal`/`ScheduleWakeup` don't exist — `/v:epic` itself runs in the main
session, where the design's own logic already accounts for the tool being absent ("If the tool is absent:
print exactly that as `/goal <condition>`"), so the design degrades correctly either way. What it means is
narrower: **this audit cannot independently confirm the specific claimed shape** — condition-string
requirement, `ask_user` default, plan-mode gating, `/goal clear`, the `@internal.disabled` toggle — because
the tool never appeared in a probe this session could run. That evidence currently rests entirely on the
same-day `native-mechanisms.md` entry, gathered from a different (main, non-subagent) session context and
graded `BINARY` there.

**Constraint:** the spec's own "Testing and evidence" section says *"Live: the new hook driven with
synthetic stdin against this repo... `/v:triage` on this very release's request is the first record bound
to a real run"* — that bullet exercises WS2, not WS1. **Add an equivalent live-probe requirement for WS1**:
before job `epic-native` is accepted, actually invoke `ProposeGoal` (not just reference its documented
shape) from the context `/v:epic` really runs in, and confirm the condition string this design proposes
(*"epic `<epic-id>`: `python3 scripts/compound-v-epic-state.py --stats --state <path>` reports every
feature `done` or the epic terminal"*) is accepted rather than rejected for length or shape. A tool schema
read from documentation is not the same evidence as a tool call that returned success.

---

## 6. Medium Findings 🟡

**🟡-1 · The "soft PyYAML, never a hard dependency" framing is accurate for the triage engine and
overgeneralized for the workflow emitter.** `compound-v-preeval.py:109`'s own docstring — *"Python
3.9-safe, stdlib only; soft-PyYAML via the shared taxonomy loader (never a hard dependency)"* — is the
sentence the spec's Global Constraints paraphrases, and it is true where it's written: that file's own
YAML use degrades. But `compound-v-emit-workflow.py` (untouched write-scope for WS1/WS2, in scope for
WS3b's `observe-native` job) has a fourth call site, `_load_yaml()` (`:181-187`), that `raise
SystemExit("PyYAML is required...")` outright — no `except ImportError: have_yaml = False` fallback there.
The `observe-native` job body already knows this operationally ("Run the emit-workflow selftest with
`/usr/bin/python3` [it needs PyYAML]"), so nothing breaks in practice — but the spec's Global Constraints
sentence, read at face value, promises a repo-wide invariant ("never a hard dependency") that is false for
one function in a file WS3b touches. **Constraint:** either scope the sentence to the triage engine
explicitly, or (cleaner) note the one hard-dependency exception and the `/usr/bin/python3` workaround it
already relies on, so a future reader doesn't rediscover this the hard way.

**🟡-2 · Jitter replaces the old fixed `:17/:47` cadence with an automatic, smaller one — worth recording
as a positive, not a gap.** `CronCreate`: *"recurring tasks fire up to 10% of their period late (max
15 min)."* For `/loop 30m`, that is up to 3 minutes of drift per cycle — well inside what the old
scheduler's fixed off-minute cadence was defending against (thundering-herd alignment across many users'
sessions), and the native scheduler already randomizes for exactly that reason. No action needed; recorded
so the "what we lose" column in the viability audit's §7 table #1 doesn't have to guess at this later.

**🟡-3 · `/workflows`/`/tasks` as WS3a's replacement UI are inherited evidence, not re-verified today.**
Nothing found in this pass contradicts the 2026-09-01 1C audit's `BINARY`-graded `RunWorkflow`/`phase()`/
`log()` findings that WS3a's phrase ("the progress tree Engine C populates through `phase()`/`log()`")
draws on, and this audit did not have a UI surface to independently re-probe `/workflows` or `/tasks` as
slash commands. Flagged only so "confirmed" in §2's table is read as "consistent with existing on-file
evidence," not "independently re-run this session."

---

## 7. Design Constraints for the Plan

**MUST**
1. State, in the text that offers `/loop` for epic resurrection (`commands/v-epic.md` §0c and the
   "honesty boundary" section replacing it in `skills/compound-v/epic-mode.md`), that interval-mode
   `/loop` auto-expires after 7 days (fires once more, then is deleted) and that a marathon expected to
   run longer needs a re-arm or `/schedule`. (🔴-1)
2. Add a live-probe step for `ProposeGoal` — an actual tool call, not a documentation citation — before
   job `epic-native`'s acceptance criteria are considered met, run from the session context `/v:epic`
   itself executes in. (🟠-1)
3. Scope or correct the "soft PyYAML... never a hard dependency" sentence in Global Constraints so it
   does not overclaim for `compound-v-emit-workflow.py:_load_yaml()`, which the `observe-native` job's
   own body already treats as a real, `/usr/bin/python3`-dependent exception. (🟡-1)

**MUST NOT**
4. Delete the "7-day expiry" honesty-boundary paragraph outright on the premise that it "described our
   schedulers" — the fact it stated is still true of the mechanism replacing them. (🔴-1)
5. Treat a documentation citation of `ProposeGoal`'s or `ScheduleWakeup`'s shape as equivalent to a live
   tool-call confirmation — neither tool is visible from a Phase 1C subagent's own probe, so nothing in
   this audit chain has yet called either one and observed success. (🟠-1)

---

## 8. Open Questions for the Human

1. **Is a week-plus unattended marathon actually a scenario worth designing for right now?** Per the
   viability audit, zero epics have ever run. 🔴-1's fix is one sentence of honest disclosure either way
   — cheap regardless of the answer — but if marathons longer than 7 days are explicitly out of scope for
   3.4.0, say so instead of silently relying on the cap never being hit. (🔴-1)
2. **Who runs the WS1 live probe, and when?** `ProposeGoal`/`ScheduleWakeup` need a main-session context to
   verify, which no Phase 1 pre-flight subagent has. Should this be a step in job `epic-native`'s own
   acceptance run (§7 constraint 2), or a separate manual check before the manifest dispatches? (🟠-1)

---

## 9. Knowledge Base Updates

Appended to
[`_knowledge-base/claude-code-runtime.md`](_knowledge-base/claude-code-runtime.md) under a new
`## Updated 2026-09-02 — v3.4-native-first (epic resurrection tools)` section: the full live `CronCreate`
schema (7-day auto-expiry, session-only/no-disk persistence, jitter bounds), the `CronList`/`CronDelete`
shapes, and the observed absence of `ProposeGoal`/`ScheduleWakeup`/`Workflow` from a subagent's tool
surface as a now three-times-reproduced pattern (session-scoped interactive tools vs. session-store
tools). No new entry was needed in `claude-code-hooks.md` — the `UserPromptSubmit`/`PostToolUseFailure`
registrations this spec touches were already correctly documented there and in `hooks/hooks.json` itself.
