# Phase 1B — Domain audit: `compound-v-dashboard.py resume --json` for the SessionStart banner and PostCompact hook

**Spec:** `docs/superpowers/specs/2026-09-02-preflight-workflow-probe.md`
**Date:** 2026-09-02 · **Auditor:** Compound V Phase 1B (domain-expert)
**Runtime probed:** Claude Code `2.1.238` (`~/.local/share/claude/versions/2.1.238`, the installed binary this repo runs under)

> **Premise warning, read before planning.** The change this spec proposes is
> **already half-shipped.** `--json` exists on `resume`
> (`scripts/compound-v-dashboard.py:1552`, `cmd_resume`/`as_json` at `:1505-1516`) and
> `hooks/postcompact-resume.sh` **already consumes it**
> (`resume --json … | jq -r '.active[]? | .id // empty'`). The only unbuilt half is
> `hooks/session-banner.sh`, which still shells out to the **rendered** line and
> string-concatenates it into the banner. A plan written to the spec's literal wording
> will produce a near-empty diff on the CLI side. Phase 1A owns the full code reality;
> this is flagged here only because every constraint below is scoped to the half that
> is actually undone. **This is the single most important thing on this page.**

---

## 1. Domain(s) Identified

1. **`agent-hook-context-injection`** — producing output consumed by an agent harness's
   lifecycle hooks (Claude Code `SessionStart` / `PostCompact`). The governing "regulation"
   in this domain is a vendor runtime contract, not a law: what shape the harness accepts,
   what it silently discards, and which events reach the model versus the user.
2. **`cli-machine-readable-output`** — the dual-consumer CLI contract: one command serving
   both a rendered line for a human/model and a structured document for a script, without
   the two drifting apart.

There is **no third domain**. This spec touches no user data, no payments, no PII, no
regulated surface. Section 5 says so plainly rather than padding.

## 2. Sources Consulted

**V-memory (Step 0), run first.** Two queries, both returned hits:
`"dashboard resume banner json output"` and `"SessionStart PostCompact hook additionalContext"`.
The engine reported *"index is 4 new / 0 removed docs behind the repo"* — recall here is
**stale by 4 documents**, so absence of a hit is not evidence of absence. Load-bearing hits:
- `docs/superpowers/library-audit/_knowledge-base/claude-code-hooks.md` (Phase 1C's KB,
  updated 2026-07-26) — `Stop`/`SubagentStop` contract, exit-2 semantics, and the machine
  fact that on this host `jq` is 1.7.1, `python3` is 3.9.6, and `timeout`/`setsid` are absent.
- `docs/superpowers/architecture/native-mechanisms.md` — the row recording that v2.19 sat on
  `SessionStart` without knowing `PostCompact` carries the summary.
- `docs/superpowers/preflight/2026-09-01-v3.0-1c-docs.md` — prior binary-recovered hook schemas.

**Trigger 0 recon.** The caller handed **no** recon path. Fallback scan of
`docs/superpowers/recon/` found no doc for slug `preflight-workflow-probe`; the newest recon
(`2026-09-01-v3.0-triage-tests-orchestration.md`) is a different topic and was read only for
its standing warning that its line numbers are frozen at `d9286c7` and not maintained.
**No recon existed for this spec** — stated so the plan author does not assume one was consulted.

**Primary source — the shipped runtime.** All hook-contract claims below are recovered from
the installed `2.1.238` binary by byte-offset extraction, not from prose. Every quoted `js`
fragment in this document was copy-pasted out of that binary.

**Primary source — official docs.** `https://code.claude.com/docs/en/hooks`, fetched twice
on 2026-09-02.

**Web search (8 parallel queries, all three layers).** Layer 1: hooks documentation, CLI
`--json` output conventions, jq install status. Layer 2: HN threads on CLI JSON output,
argparse exit-code behavior. Layer 3 (the persona — people who write Claude Code hooks that
shell out to a script): GitHub issue search plus `gh` verification.
**Honest negative result:** the `site:reddit.com/r/ClaudeAI` query returned **zero r/ClaudeAI
posts** — the engine substituted GitHub issues. There is no Reddit evidence in this audit
because none was found, not because it was omitted.

**Citation integrity — one correction made during this pass.** A draft of this audit cited
[openstatus](https://www.openstatus.dev/blog/building-cli-for-human-and-agents) for the
stdout/stderr split. I then fetched it: it does not say that. The claim was re-grounded on
[clig.dev](https://clig.dev/), fetched and quoted verbatim. Recorded because the same draft
error is the failure mode this audit's own rules exist to prevent. Every remaining URL in this
document was fetched (`WebFetch`) or verified through `gh`, except where a line explicitly says
it was not.

## 3. Domain Constraints the Brainstorm Probably Missed

### MUST — SessionStart JSON must be wrapped in `hookSpecificOutput`, or it is silently discarded

Runtime `2.1.238`, verbatim (offset 296941375):

```js
case"SessionStart":
  u.additionalContext=e.hookSpecificOutput.additionalContext,
  u.initialUserMessage=e.hookSpecificOutput.initialUserMessage,
  u.sessionTitle=e.hookSpecificOutput.sessionTitle,
```

`SessionStart` **is** a supported `hookSpecificOutput` variant, carrying `additionalContext`,
`initialUserMessage` and `sessionTitle`. But a **bare top-level** `{"additionalContext": …}`
is not read at all. Verbatim (offset 296470892):

```js
let s=r.includes("additionalContext")?" Did you mean hookSpecificOutput.additionalContext (with a hookEventName)?":"";
T(`Hook JSON output had unrecognized keys (ignored): ${r.join(", ")}.${s}`)
```

Unrecognized keys are **ignored**, and the diagnostic goes to the debug log only. This is a
**silent** failure: exit 0, no error, no banner.

`hooks/session-banner.sh` has three output branches. Its third — the "generic SDK" fallback,
taken whenever `CLAUDE_PLUGIN_ROOT` is unset **or** `COPILOT_CLI` is set — emits exactly the
discarded shape:

```bash
jq -n --arg ctx "$banner" '{additionalContext: $ctx}'
```

Under Claude Code with the plugin installed the correct branch is taken, so this is latent
rather than active. It becomes active the moment the hook is registered from a plain
`.claude/settings.json` instead of as a plugin. **The plan MUST NOT touch the branch
selection, and MUST keep the plugin branch's shape byte-identical.**

### MUST — stdout is parsed as JSON only when it starts with `{`

Verbatim (function `$Gi`, offset ~296937800):

```js
let t=e.trim();
if(!t.startsWith("{"))return T("Hook output does not start with {, treating as plain text"),{plainText:e};
```

The docs state the same rule: *"Starts with `{` and ends with `}`: Claude Code parses it as
JSON"* ([hooks reference](https://code.claude.com/docs/en/hooks), fetched 2026-09-02). Any
stray stdout write — a warning, a `set -x` trace, a Python `DeprecationWarning` routed to
stdout — ahead of the payload silently reclassifies the whole thing as plain text.

On `SessionStart` this fails **soft**: plain-text stdout is itself injected as context
(*"The exceptions are `UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, and
`PostModelSwitch`, where Claude Code adds plain-text stdout as context that Claude can see
and act on"* — same page). On most other events it fails **silent**. The plan MUST keep the
hook's stdout single-shot and MUST route every diagnostic to stderr.

### MUST — `additionalContext` over 10,000 chars is persisted to disk, and truncated only if that fails

A widely-repeated secondary claim says `additionalContext` has a "10,000-character cap"
([claudefa.st](https://claudefa.st/blog/tools/hooks/session-lifecycle-hooks)). **That framing
is wrong, and the runtime is more forgiving than it says.** Verbatim:

```js
async function gTt(e,t,r,n=uFp){
  if(e.length<=n)return e;
  let o=await Net(e,`hook-${t}-${r}`,tY());
  if(Fet(o))return N("tengu_hook_output_persisted",{…truncatedFallback:!0}),
    `${e.slice(0,n)}\n\n[Hook ${r} truncated at ${n} chars — persist-to-disk failed: ${o.error}]`;
  …
}
```

with `uFp=1e4` (offset 287057089: `var Z3r=50000,Q3r=500000,$3n=4,lFp=400000,cFp=200000,W8=50,uFp=1e4;`).

So 10,000 is a **persist-to-disk threshold**, not a cap. Over it, the content is written to
disk and replaced by a reference; only if that write fails is it hard-truncated **with an
explicit marker**. Note also that `additionalContext` is **not** run through the capping
function that `classifierContext` is — the runtime's own log strings distinguish them:
`") provided classifierContext ("` + `" chars after cap)"` versus
`") provided additionalContext ("` + `" chars)"`.

Relevance: the banner is a concatenation (base string + `/v:init` tip + staleness warning +
resume line), and `format_resume_line` already bounds itself at `RESUME_MAX_RECORDS = 2` with
a `+N more` counter. It is nowhere near 10,000 today. The hazard is specific to this change:
**a JSON-driven banner is exactly the change that invites "now that we have the array, render
all of them."** The plan MUST preserve an explicit record cap on the banner path.

### MUST NOT — treat PostCompact like SessionStart. Its stdout is display text, not model context

The producer, verbatim (offset ~697620):

```js
let i={...c_(e,er()),hook_event_name:"PostCompact",trigger:t.trigger,compact_summary:t.compactSummary},
    s=await Hj({session:e,hookInput:i,matchQuery:t.trigger,signal:n,timeoutMs:o});
…
a.push(`PostCompact [${l.command}] completed successfully: ${l.output.trim()}`)
…
return{userDisplayMessage:a.length>0?a.join(…
```

Three consequences the spec's phrasing ("so the banner and the hook can consume structured
output") glosses over:

1. Hook stdout becomes `userDisplayMessage` — **shown to the user at the compaction
   boundary, not injected into the model's context.** The official docs corroborate by
   omission: `PostCompact` is not in the four-event exception list.
2. The runtime **wraps** the output in `PostCompact [<command>] completed successfully: …`.
   The hook does not control its own prefix.
3. There is **no `hookSpecificOutput` variant for `PostCompact`**. The variants enumerated in
   the runtime's own validation-error text are `PreToolUse`, `UserPromptSubmit`,
   `UserPromptExpansion`, `PostToolUse`, `PostToolBatch`, `Stop`/`SubagentStop` — plus
   `SessionStart` in the switch above. `PostCompact` appears in none of them.

`hooks/postcompact-resume.sh` already gets all three right and documents them in its header.
**The plan MUST NOT "unify" the two hooks onto one JSON output shape** — they have opposite
output contracts, and a JSON object emitted from PostCompact would be rendered to the user as
raw JSON.

### MUST — `compact_summary` and `trigger` are undocumented; consuming them is version-coupled

Both fields are real in `2.1.238` (quoted above) and **absent from the public hooks page**
(fetched 2026-09-02: no `compact_summary`, no `trigger` in the PostCompact input schema; the
page documents no PostCompact input schema at all). An undocumented field carries no
compatibility promise. Any consumer MUST fail silent when it is missing — as
`postcompact-resume.sh` already does, requiring the `jq` parse to *succeed* rather than
merely yield empty fields.

### MUST — `jq` is a hard dependency that the banner does not guard, and this change deepens it

`jq` ships by default on **neither macOS nor Linux**
([jq install docs](https://github.com/jqlang/jq/wiki/Installation) — package-manager install
required on Debian/Ubuntu/Fedora; [download page](https://jqlang.org/download/)).

The two hooks disagree about this today:
- `hooks/postcompact-resume.sh` guards: `command -v jq >/dev/null 2>&1 || return 1`.
- `hooks/session-banner.sh` does **not**. It runs under `set -euo pipefail` and reaches an
  unguarded `jq -n` on every branch. On a host without `jq`, the **entire** SessionStart
  banner dies — not just the resume segment.

Routing the banner through `--json` means parsing JSON in bash, i.e. **more** `jq`, on the
one hook that has no fallback. `python3` is already an unconditional dependency of this path
(the hook shells into a Python script to get the line at all). **The plan MUST either guard
`jq` in `session-banner.sh`, or do the JSON→prose rendering in Python and keep bash out of
the parsing business.** The second is strictly less fragile.

### MUST — tolerate version skew: an older dashboard rejects `--json` with exit 2

This project has already been bitten by a lagging installed plugin cache (recorded in the
maintainer's own v2.5.4 note: *"user's installed plugin cache may lag"*). A hook that passes
`--json` to a pre-v3.0 dashboard hits argparse, which
[prints to stderr and exits 2](https://docs.python.org/3/library/argparse.html) on
`unrecognized arguments`. `postcompact-resume.sh` survives this (`set -uo pipefail`, pipeline
failure caught by `|| ids=""`, and it degrades to a "not checked" note). A new banner
consumer MUST do the same: **non-zero exit plus empty stdout is a normal, expected state.**

Second-order and easy to miss: **stderr from a SessionStart hook can make the UI show a hook
error even on exit 0.** [anthropics/claude-code#12671](https://github.com/anthropics/claude-code/issues/12671)
(opened 2025-11-29, now CLOSED) reports `SessionStart:startup hook error` with the debug log
showing `Hook output does not start with {, treating as plain text` — the same runtime string
recovered above. *Isolated report* by this audit's evidence threshold (one issue, Windows/Git
Bash, since closed) — cited because its debug evidence corroborates the binary, **not** as
community consensus. A near-identical class of complaint appears at
[thedotmack/claude-mem#1181](https://github.com/thedotmack/claude-mem/issues/1181)
("SessionStart hooks show as 'error' in Claude Code UI due to stderr usage"), which this audit
did **not** independently verify. Practical rule: keep argparse's stderr away from the hook's
stderr — redirect it, as both hooks already do with `2>/dev/null`.

### SHOULD — the JSON payload has no version discriminator

`cmd_resume` emits a fixed key set:

```python
payload = [{k: r.get(k) for k in
            ("kind", "id", "status", "done", "total", "age_hours", "display_ts")}
           for r in records]
print(json.dumps({"active": payload}, indent=2, sort_keys=True))
```

Current CLI guidance is blunt that this becomes a contract the moment a second consumer
exists — verbatim, confirmed on fetch: *"The most important design constraint is that commands,
flags, and output fields become a contract once agents start using them"*
([Designing a CLI for AI agents](https://blog.arcjet.com/designing-a-cli-for-ai-agents/),
fetched 2026-09-02). Adding the banner makes **two** in-repo consumers plus a documented
cross-version skew problem. A `schema_version` (or an explicitly frozen key list with a test)
is cheap now and expensive later.

### SHOULD — the two modes have asymmetric empty-states, and that asymmetry is undocumented

- Rendered mode on no records: prints **nothing**, exit 0.
- JSON mode on no records: prints `{"active": []}`, exit 0.

Both are defensible — "machine output always emits a document" is the better convention — but
the difference is currently implicit in `cmd_resume`'s early return. The banner's existing
`[ -n "${resume:-}" ]` emptiness test does not survive translation to JSON mode, because JSON
mode is **never** empty. This is the most likely single bug in a naive port.

### SHOULD — `indent=2` is a pretty-printer on a machine path

[clig.dev](https://clig.dev/) is explicit that *"Anything that is machine readable should also
go to `stdout`—this is where piping sends things by default"*, and that JSON exists so
complex structures survive the pipe. Pretty-printing does not break `jq`, but it does break a
`while read -r line` consumer immediately. Not a defect today — `postcompact-resume.sh` uses
`jq` — but the plan SHOULD decide deliberately rather than inherit it.

*Evidence honesty:* the "one compact object per line / JSON Lines" convention appeared in
search-result summaries for this topic but I did not fetch a primary source stating it, so it
is recorded as a weak preference here, not as a cited rule.

## 4. Common Traps in This Domain

| # | Trap | Why it bites here |
|---|---|---|
| 1 | **Silent-discard by wrong JSON shape** | Wrong wrapper ⇒ exit 0, no output, no error. Nothing in CI catches a banner that stopped appearing. |
| 2 | **Assuming every hook event reaches the model** | Only 4 of ~30 events inject stdout as context. PostCompact is not one of them. |
| 3 | **Emptiness inversion between rendered and JSON modes** | Rendered-empty means "nothing to say"; JSON-empty is still a document. A ported truthiness check announces a banner for zero runs. |
| 4 | **Depending on undocumented stdin fields** | `compact_summary` / `trigger` exist in the binary, not on the docs page. |
| 5 | **Adding a `jq` call to a `set -e` hook with no jq guard** | Turns a degraded segment into a dead banner on hosts without jq. |
| 6 | **Version skew across the plugin cache** | `--json` against an old dashboard is argparse exit 2, not a soft failure. |
| 7 | **Diagnostics on stdout** | One stray line before `{` silently downgrades JSON to plain text. |
| 8 | **Fixing the "no cap" by growing the banner** | 10,000 chars is a persist-to-disk boundary, not a wall — over it you silently spend context budget instead of failing. |
| 9 | **Rendering JSON for an LLM consumer** | The banner's reader is a model, which reads prose. JSON→prose is a step with a cost and no consumer benefit unless something new is computed from the structure. |

## 5. Regulatory / Compliance Notes

**None apply.** This is internal developer tooling. The `resume` payload carries
`kind`, `id`, `status`, `done`, `total`, `age_hours`, `display_ts` — no personal data, no
credentials, no third-party data. There is no GDPR, HIPAA, PCI, SOC2, or accessibility
surface. Padding this section would be the fraud my own instructions forbid.

Two **house rules** in this repo do bind the plan, and they are not regulation but are
enforced by CI:
- **Anti-fabricated-metrics gate** (`AGENTS.md`; `agents/spec-reviewer.md` pass 2). Any
  timing figure quoted for the new path must be measured, with method and host stated — the
  standard `hooks/postcompact-resume.sh` already meets ("~147 ms measured on the development
  machine, mean of 10 runs").
- **Dashboard charter: present-only, read-only** (`scripts/compound-v-dashboard.py:78-80`).
  A structured-output consumer must not become a writer.

## 6. Recent Breaking Changes (last 12 months)

| Change | Evidence | Impact |
|---|---|---|
| `PostCompact` event exists and carries the compaction summary | binary `2.1.238`; [hooks reference](https://code.claude.com/docs/en/hooks) lists it as "After context compaction completes" | The v2.19 design assumption ("SessionStart is the only event available") is obsolete; already closed in v3.0. |
| Hook event surface grew to ~30 lifecycle events | [hooks reference](https://code.claude.com/docs/en/hooks); 1C KB entry 2026-07-26 (30-event enum @238483006) | More events, still only 4 injecting stdout as context. |
| Hook output over 10,000 chars persisted to disk rather than dropped | binary: `gTt`, `uFp=1e4`, telemetry `tengu_hook_output_persisted` | Softens a limit widely reported as a hard cap. |
| Docs host moved: `docs.claude.com/en/docs/claude-code/hooks` → `code.claude.com/docs/en/hooks` | 1C KB 2026-07-26 records the 301 | Old bookmarked URLs redirect; cite the new host. |
| Per-event timeout defaults published (600 s command; 30 s `UserPromptSubmit`; 10 s `MessageDisplay`; `SessionEnd` 1.5 s budget) | [hooks reference](https://code.claude.com/docs/en/hooks), fetched 2026-09-02 | `hooks/hooks.json` sets `timeout: 10` on PostCompact — well inside the default, deliberate, keep it. |

**Explicitly not found:** no breaking change to `hookSpecificOutput.additionalContext` on
`SessionStart` in the last 12 months. No evidence either way on whether `compact_summary` is
stable. Saying so beats guessing.

## 7. Design Constraints for the Plan (non-negotiable)

1. **Re-scope against reality first.** `--json` exists and PostCompact already consumes it.
   The deliverable is the **SessionStart banner path**, or the spec needs rewriting. Do not
   plan work that is already merged.
2. **SessionStart output MUST stay `{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"…"}}`.** A bare
   top-level `additionalContext` is silently ignored by runtime 2.1.238.
3. **PostCompact MUST keep emitting plain text.** No JSON, no `hookSpecificOutput`, and no
   documentation claiming it re-injects context. Do not unify the two hooks' output shapes.
4. **Parse the JSON in Python, not in bash.** `python3` is already required on this path;
   `jq` is not installed by default on macOS or Linux, and `session-banner.sh` runs under
   `set -euo pipefail` with no `jq` guard. If bash parsing is kept, a `command -v jq` guard in
   `session-banner.sh` becomes mandatory in the same change.
5. **Treat a failing/unknown `--json` as normal.** Non-zero exit, empty stdout, or
   `unrecognized arguments` (argparse exit 2) MUST degrade to today's behavior, never to a
   broken banner. Keep argparse's stderr off the hook's stderr.
6. **Handle `{"active": []}` explicitly.** JSON mode is never empty; the banner's current
   `[ -n "$resume" ]` test silently inverts when ported.
7. **Keep the banner bounded.** Preserve a record cap equivalent to `RESUME_MAX_RECORDS = 2`
   with a `+N more` counter. 10,000 chars is a persist-to-disk threshold, not a wall.
8. **stdout carries the payload and nothing else.** One write. Diagnostics to stderr. The
   leading `{` decides whether the runtime parses it at all.
9. **Freeze or version the payload keys.** Two consumers plus known plugin-cache skew.
   `schema_version`, or a test that pins
   `("kind","id","status","done","total","age_hours","display_ts")`.
10. **The rendered line and the JSON MUST NOT diverge.** Both already derive from
    `active_records()`; keep `format_resume_line` the single owner of the prose vocabulary, as
    `postcompact-resume.sh` explicitly requires.
11. **Read-only stays read-only.** No writes on the structured-output path.
12. **No unmeasured performance claims.** Both hooks run on every session start / every
    compaction; if the plan asserts a cost, it states host, method and run count.

## 8. Open Questions for the Human

1. **What is the actual deliverable, given `--json` already exists and PostCompact already
   consumes it?** Is this probe spec meant to produce a real diff, or only to exercise the
   pre-flight? Nobody but the maintainer can answer this, and every downstream phase depends
   on it.
2. **What does the banner gain from JSON?** Its consumer is a language model, which reads
   prose. Switching `session-banner.sh` to parse JSON and re-render prose adds a step, a `jq`
   dependency, and a skew failure mode. The change pays for itself only if the banner starts
   computing something new from the structure (filtering by status, ranking by age). **Is
   there such a requirement, or is prose already the right interface?**
3. **Is the payload key set frozen?** Adding `schema_version` is a contract decision, not a
   technical one.
4. **Should `session-banner.sh`'s "generic SDK" branch be kept?** It emits a shape Claude Code
   silently discards. It exists for non-Claude harnesses; if none is actually supported, it is
   a live footgun that looks like coverage.
5. **Minimum supported dashboard version for the hooks?** Determines whether skew handling is
   a graceful degrade or a hard floor with a version check.

## 9. Knowledge Base Updates

Two files under `docs/superpowers/expert/_knowledge-base/`, both **created** by this pass:

- **`cli-machine-readable-output.md`** — the dual-consumer CLI contract: stdout/stderr split,
  emptiness asymmetry, version discriminators, pretty-vs-NDJSON, argparse skew behavior.
- **`agent-hook-context-injection.md`** — which Claude Code hook events reach the model, the
  `hookSpecificOutput` wrapper requirement and its silent-discard failure, the 10,000-char
  persist-to-disk threshold, and the PostCompact `userDisplayMessage` path — all with the
  runtime offsets they were recovered from.

**Deliberately NOT written:** `docs/superpowers/library-audit/_knowledge-base/claude-code-hooks.md`.
That file belongs to **Phase 1C**, which may be running concurrently; appending to it from
this lane risks a write conflict and duplicates 1C's remit. The event-level API surface stays
theirs. My files record the *design* rules for producing output that those surfaces accept,
and cross-reference theirs.
