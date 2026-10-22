# Phase 1C — Library & Documentation Validation: v3.4.9 preflight kb-paths and retries schema

**Spec:** [`docs/superpowers/specs/2026-09-03-v3.4.9-preflight-kb-paths-and-retries-schema-design.md`](../specs/2026-09-03-v3.4.9-preflight-kb-paths-and-retries-schema-design.md)
**Plan (already drafted, read for context only):** [`docs/superpowers/plans/2026-09-03-v3.4.9-preflight-kb-paths-and-retries-schema.md`](../plans/2026-09-03-v3.4.9-preflight-kb-paths-and-retries-schema.md)
**Date:** 2026-09-03 · **Topic slug:** `v3-4-9-preflight-kb-paths-and-retries-schema`

**Headline: this spec introduces zero third-party libraries.** Its entire write-set is
`scripts/compound-v-emit-preflight.py`, `commands/v-dispatch.md`, `scripts/compound-v-collect-results.py`, and
`CHANGELOG.md` — two pure-stdlib Python scripts and two Markdown files. Confirmed by `Glob` for
`package.json`/`requirements.txt`/`pyproject.toml`/`Cargo.toml`/`go.mod`/`Gemfile`/`composer.json`/lockfiles
at repo root: **none exist**, consistent with every prior 1C audit this week. The one API surface genuinely
in scope is Claude Code's own native `Workflow` (`agent()`) structured-output contract, since Task A adds a
field to a JSON Schema handed to `agent()`. That is validated live below, not from training data.

---

## 0. V-memory recall (Step 0)

`compound-v-memory.py search` run three times (`"preflight knowledge base paths retries schema kb_files"`,
`"collect-results retries validation usage schema pydantic"`, `"compound-v-emit-preflight context7 audit
KB"`, `--intent planning --top 8`). Relevant hits used below, all treated as evidence with citation, not
authority:

- The **spec and plan themselves** are the top hits (expected — they're freshly written today) — read in
  full directly, not just via recall snippets.
- **`docs/superpowers/dogfood/2026-09-03-v3.4.8-workflow-retry-review-2.md`** — LOW observation #1 is the
  exact defect this spec's Part 2 fixes (`retries[]` not deep-validated); confirms Part 2 is not new
  information, just closing a gap already recorded two runs ago.
- **`docs/superpowers/library-audit/2026-09-03-v3-4-8-workflow-retry.md`** (same day, earlier run) — full
  live-doc fetch of `code.claude.com/docs/en/workflows.md` and a `claude-code-runtime.md` KB entry already
  cover `agent()`'s general contract. Re-fetched narrowly below rather than re-derived, specifically for the
  one facet that prior audit didn't need: the `schema` option's property-addition semantics.
- **`docs/superpowers/library-audit/2026-09-03-v3-4-7-readme-clarity.md`** — confirms the pattern "Context7
  MCP not attached to this subagent" on three same-week runs before this one.
- No V-memory hit disagreed with anything below.

---

## 1. Tools Available

| Tool | Status | Note |
|---|---|---|
| Context7 MCP | ❌ **not attached to this subagent** (`ToolSearch "context7 resolve-library-id query-docs"` / `"context7"` → no match) | Fourth same-week 1C run recording this (2026-09-03: triage-size, readme-clarity, workflow-retry, this one). **Also not applicable regardless** — this spec touches zero Context7-indexed packages. |
| WebFetch | ✅ used, primary source | Full live fetch of `code.claude.com/docs/en/workflows.md`, 2026-09-03, prompted specifically for the `schema` option's shape and property-addition semantics (narrower ask than the same-day v3.4.8 fetch, which focused on error/retry behavior). |
| Local Bash | ❌ clamped to `compound-v-memory.py search`/`recall-check` only this spawn | No `find`/`grep`/`git` via Bash; `Read`/`Grep`/`Glob` (unrestricted) substitute throughout. |
| Dependency manifests | n/a | None exist in the tree (`Glob`, this session, root-level check). |
| Repo code as a live, running second source | ✅ used | `RESULT_SCHEMA` and the JS wrapper prompt/fallback literals in `scripts/compound-v-emit-preflight.py` (`Read`, this session) are the **already-shipping** contract the spec extends — the most authoritative source for "does this schema shape actually work," stronger than any doc. `schemas/job_result.schema.json`'s existing `retries.items` sub-schema (v3.4.8) is the authoritative source for Task B's field list. |

**DEGRADED, narrowly:** Context7 absent again but immaterial here — WebFetch is fully functional and is this
audit's primary source for the one applicable contract.

---

## 2. Libraries Mentioned

| Name | Spec context | Current state | Repo pinned | Last verified | Maintenance | Status |
|---|---|---|---|---|---|---|
| *(none — third-party)* | — | — | — | — | — | n/a: no `package.json`/`requirements.txt`/equivalent in the tree; both touched scripts import only `argparse, bisect, collections, json, os, re, shutil, sys, tempfile, typing` / `argparse, datetime, json, os, re, sys` (`Grep`, this session) |
| Claude Code `Workflow` runtime — `agent(prompt, {schema, ...})` structured-output contract | Task A adds a property (`kb_files`) to `RESULT_SCHEMA`, the JSON Schema object handed to every `agent()` call this script makes | Live doc `code.claude.com/docs/en/workflows.md`, fetched 2026-09-03 (this audit); cross-checked against the same-day v3.4.8 audit's independent fetch of the same URL and against this repo's already-shipping `RESULT_SCHEMA` | Repo floor implied `>= 2.1.219` (carried from the 2026-09-01/09-02/09-03 1C audits; this spec neither restates nor needs a new floor — it changes no runtime-visible behavior beyond a schema field) | 2026-09-03 (this audit) | Active, first-party | 🟢 current — the exact `{"type":"array","items":{"type":"string"}}` shape this spec proposes for `kb_files` is not just doc-consistent, it is **byte-identical** to the shape already used for `blocking` in the same schema (`RESULT_SCHEMA["properties"]["blocking"]`, line 102) — zero drift risk |
| Python 3.9 stdlib (`json`, `argparse`, type-map-driven hand-rolled validation in `compound-v-collect-results.py`) | Task B's `retries[]` validation | Frozen floor; 3.9 reached EOL 2025-10-31, 3.9.25 final release — already fully documented in `_knowledge-base/python-tooling.md` (2026-09-03 entry), not re-derived here | 3.9 (repo-wide) | Cited, not re-fetched (same-day KB entry already live-sourced) | n/a — stdlib | 🟢 no new stdlib surface introduced; Task B reuses the exact type-check machinery (`_TYPE_MAP`, the `additionalProperties:false`-aware loop) already exercised by `_usage_conformance_errors` |

---

## 3. API Signatures Verified

### `agent(prompt, {schema, ...})` — the `schema` option's property-addition semantics

Live-fetched `code.claude.com/docs/en/workflows.md`, 2026-09-03, the page's own worked example:

```javascript
const found = await agent('List every .ts file under src/routes/.', {
  schema: { type: 'object', required: ['files'], properties: { files: { type: 'array', items: { type: 'string' } } } },
})
```

and: *"`agent()` with `schema` forces a StructuredOutput tool call and returns the validated object."*

This confirms the array-of-strings shape (`{type: 'array', items: {type: 'string'}}`) is the documented,
current pattern for a schema property — exactly the shape Task A proposes for `kb_files`. **No mention
anywhere on the fetched page of a property-count limit, nesting-depth limit, or any caveat about adding a
new property to an existing schema** — the doc simply doesn't address schema *evolution*, only schema
*shape*. That gap is closed empirically instead: `RESULT_SCHEMA` (`additionalProperties: false`, a
`required` list, an array-of-strings property) is **already shipping and already working** in this exact
codebase for the `blocking` field (`compound-v-emit-preflight.py:91-105`) — the strongest possible evidence
that this shape is supported, stronger than any doc statement, because it is observed running code, not a
claim about to be tested for the first time.

**What the doc does NOT establish, and what standard JSON Schema semantics (not Claude-Code-specific, not
subject to library drift) says instead:** a property listed in `properties` but absent from `required` is
optional — a schema-compliant response may omit it. The live doc's own example schema doesn't demonstrate
this case (its one property, `files`, *is* required), so this is not directly quoted from a Claude Code
source; it is standard JSON Schema behavior, which `agent()`'s `schema` option visibly follows already
(`RESULT_SCHEMA`'s existing `notes` property is in `properties` but never in `required`, and the current
wrapper script never populates it from any explicit ask — see §5-1 for why this matters for `kb_files`).

### `retries[]` item shape — plan vs. the already-declared schema

`schemas/job_result.schema.json:219-257` (v3.4.8, unchanged today) already declares, verbatim:

```json
"retries": { "type": "array", "items": { "type": "object",
  "properties": { "stage": {"type": "string"}, "job": {"type": "string"},
                   "attempt": {"type": "integer", "minimum": 1},
                   "wait_ms": {"type": "integer", "minimum": 0},
                   "escalated_from": {"type": ["string", "null"]},
                   "model": {"type": ["string", "null"]} },
  "required": ["stage", "attempt"], "additionalProperties": false } }
```

This is an **exact** match to Task B's proposed field list (required `stage`/`attempt`; optional
`job`/`wait_ms`/`escalated_from`/`model`; no other keys). **No drift, no new schema authoring needed** —
Task B validates against a contract that already exists and is already the single source of truth; it just
needs a Python-side deep-checker, which `_usage_conformance_errors` (`compound-v-collect-results.py:395-421`)
already provides as a directly reusable pattern: type-map-driven, `additionalProperties:false`-aware,
reads field types from the schema object rather than hardcoding them.

---

## 4. Critical Findings 🔴

None. No third-party library is deprecated, archived, or stale in this spec's scope — there are no
third-party libraries in this spec's scope.

---

## 5. High-Priority Findings 🟠

None.

---

## 6. Medium Findings 🟡

### 🟡-1 · An optional `kb_files` property will not populate itself — the schema change alone does not compel the model to fill it

Per §3, `agent()`'s `schema` option follows standard JSON Schema semantics: a property in `properties` but
not in `required` may be legitimately absent from a compliant structured-output response. The plan's Task A
says only "add `kb_files`... to the structured result" and "the result object carries `kb_files` (empty
when none)" — it does not say whether `kb_files` goes into `RESULT_SCHEMA["required"]`, and the existing
`notes` property (also `properties`-only, never `required`) is precedent in this exact codebase for a field
the schema *allows* but does not *compel*, and which the wrapper prompt currently never explicitly asks the
agent to fill (the current prompt text, `compound-v-emit-preflight.py:249-251`, asks only for `wrote`,
`findings`, and `blocking` by name — `notes` is filled at the agent's discretion, if at all).

If `kb_files` ships the same way `notes` did (schema-allowed, never explicitly requested in the wrapper
prompt), a compliant `agent()` response can legally omit it, defeating finding 100's actual goal (the
orchestrator needing to know which KB files to commit).

**Constraint:** the wrapper prompt text in the JS template (not only `RESULT_SCHEMA`) MUST explicitly ask
for `kb_files` by name — schema membership alone is not sufficient to make a model populate an optional
field. Whether to additionally add `kb_files` to `required` (forcing every response, including a SKIPPED
phase's, to include it even if empty) is a design choice outside this audit's lane — flagged as an open
question in §8, not decided here.

### 🟡-2 · `RESULT_SCHEMA` and the wrapper prompt are ONE object/string shared verbatim by all three phases (1A, 1B, 1C), not two

Confirmed by direct read of `compound-v-emit-preflight.py:236-267`: the `parallel()` fan-out builds ONE
`opts` object per phase from the SAME `CFG.schema` (== `RESULT_SCHEMA`, assigned once at
`emit_script:322-323`) and the SAME wrapper `prompt` template (`_SCRIPT:242-251`) — 1A (code-archaeologist),
1B (domain-expert), and 1C (doc-validator) all receive an *identical* schema and near-identical prompt text,
differing only in the interpolated `purpose`/`out` strings. The spec's own Part 1 describes only 1A and 1C
as producers of `_knowledge-base` files; 1B is not mentioned. Adding `kb_files` to this shared schema
therefore makes it a **valid** (if currently pointless) field for 1B's response too — harmless given §6-1's
optionality, but non-obvious from the plan's Task A wording ("the emitted auditor prompts... add `kb_files`"
reads as if the auditor prompts are three separate texts; they are one shared template plus one shared
schema object).

**Also structurally relevant:** three places in the JS template construct a result object **without** going
through `agent()`/`schema` at all, and so get **no** schema enforcement, defaulting, or validation
whatsoever: the `e.skipped` branch (`:240`), the `r === null` branch (`:287-288`), and the `catch` branch
(`:296-297`). Each is a hand-written object literal that already lists `blocking: []` explicitly (proving
the pattern: a field the post-processing loop reads unconditionally — `for (const b of (r.blocking || []))`
— must exist, or be defensively coalesced, at every one of these three sites, not only in the schema).

**Constraint:** if the post-processing step reads `r.kb_files` (per the plan: "add `kb_files` per audit and
a de-duplicated top-level `kb_files`"), it MUST default via `|| []` the same way `blocking` already is
(`compound-v-emit-preflight.py:304`), and the selftest (`--selftest`) MUST check for `kb_files` in all of:
`RESULT_SCHEMA["properties"]`, the wrapper prompt text, the post-processing accumulator, AND ideally the
three bypass literals — not only "the schema and the result builder" as the plan's own selftest line
currently scopes it, or the SKIPPED/null/threw paths silently produce `undefined` where the top-level
accumulator expects an array.

---

## 7. Design Constraints for the Plan

Non-negotiable, each traced to a finding above.

**MUST**
1. Ask for `kb_files` explicitly, by name, in the wrapper prompt text (`_SCRIPT`'s `prompt` string) — adding
   it only to `RESULT_SCHEMA["properties"]` does not compel a model to populate an optional field.
   (🟡-1)
2. Default `kb_files` with `|| []` wherever it's read (the top-level accumulator, any per-phase display),
   mirroring the existing `blocking` pattern, because three JS-literal fallback paths (`skipped`, `null`,
   `catch`) never go through schema validation and won't carry the field unless added there too. (🟡-2)
3. Extend the selftest coverage beyond "the schema and the result builder" (as currently scoped in the plan)
   to also cover the wrapper prompt text and, ideally, the three bypass literals — otherwise a SKIPPED or
   errored phase silently drops `kb_files` from its result object while the happy path passes. (🟡-2)
4. For Task B, validate `retries[]` items against the field list **already declared** in
   `schemas/job_result.schema.json:219-257` (confirmed byte-for-byte matching the plan's proposed rules) —
   reuse `_usage_conformance_errors`'s type-map-driven, `additionalProperties:false`-aware pattern rather
   than writing a second, parallel hand-rolled checker. (§3)

**MUST NOT**
5. MUST NOT assume `RESULT_SCHEMA["properties"]["kb_files"]` alone guarantees the field is populated —
   standard JSON Schema semantics (visibly already followed by `agent()`'s `schema` option in this exact
   codebase, via the existing `notes` field) allow a non-`required` property to be absent from a compliant
   response. (🟡-1)
6. MUST NOT treat "the emitted auditor prompts" as three independently-editable texts, or `RESULT_SCHEMA` as
   scoped to 1A/1C only — both are single shared objects/strings that 1B (domain-expert) also receives
   verbatim; the field addition is global by construction. (🟡-2)

---

## 8. Open Questions for the Human

1. **Should `kb_files` be added to `RESULT_SCHEMA["required"]`, forcing every response (including a SKIPPED
   phase's hand-built literal) to carry it, or left optional with prompt-text-driven best-effort plus
   defensive `|| []` reads?** A scoping decision, not a library-currency question — §6-1/§6-2 lay out the
   mechanics either way but do not choose for you.
2. **Is it acceptable that 1B (domain-expert) technically becomes eligible to report `kb_files` once the
   shared schema changes, even though the spec's Part 1 only describes 1A/1C as knowledge-base producers?**
   If 1B's own agent definition (`agents/domain-expert.md`) independently maintains a `_knowledge-base/`
   convention (Phase 1A's territory to confirm, not this audit's), the schema change may be more broadly
   useful than Part 1 states; if not, it's simply inert for 1B, which is harmless but worth naming rather
   than leaving implicit.

---

## 9. Knowledge Base Updates

Appended to
[`docs/superpowers/library-audit/_knowledge-base/claude-code-runtime.md`](_knowledge-base/claude-code-runtime.md)
under `## Updated 2026-09-03 — agent() schema property-addition semantics (v3.4.9 kb_files/retries)`: the
live doc's own array-of-strings worked example, the confirmation that this repo's `blocking` field is
byte-identical prior art, the required-vs-optional JSON-Schema semantic (grounded in the existing `notes`
field's behavior, not asserted from training data), and the fact that `RESULT_SCHEMA`/the wrapper prompt are
one shared object/string across all three parallel pre-flight phases (1A/1B/1C), not per-phase. Prior
entries were not altered; this is a pure append per the KB's own convention.

No entry added to `_knowledge-base/python-tooling.md` — this spec introduces no new stdlib surface beyond
what `_usage_conformance_errors`'s already-documented pattern already covers, and the Python 3.9 EOL facts
relevant to any `--selftest` work here are already current (2026-09-03 entry, same day, not re-derived).
