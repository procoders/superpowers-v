# Phase 1C — Library & Documentation Validation: preflight-workflow-probe

**Spec:** [`docs/superpowers/specs/2026-09-02-preflight-workflow-probe.md`](../specs/2026-09-02-preflight-workflow-probe.md)
**Date:** 2026-09-02 · **Branch:** `v3.0-dogfood-collector-tests` · **Local Claude Code:** `2.1.238`
**Recon:** none. No path was handed by the caller, and the fallback scan of `docs/superpowers/recon/`
found no doc for slug `preflight-workflow-probe` (only `2026-07-11-fts5-cyrillic-tokenizer.md` and
`2026-09-01-v3.0-triage-tests-orchestration.md`). This audit rests on live sources only.

**Headline:** the change this spec proposes is **already shipped**. `--json` exists on
`compound-v-dashboard.py resume`, it works, and one of the two consumers the spec names is already
consuming it. The audit below documents that, then reports what is actually stale.

**Evidence grades:** `PROBE` (command run on this machine, reproducible) · `BINARY` (verbatim string
from the installed executable) · `FETCHED` (official doc URL) · `CODE` (file:line in this repo).

---

## 1. Tools Available

| Tool | Status | Note |
|---|---|---|
| Context7 MCP | ✅ available (`mcp__context7__*`, the non-plugin form) | ❌ **not applicable to the decisive questions.** Resolved `/python/cpython` but the contracts at issue are the Claude Code hook runtime and this repo's own CLI — neither is a Context7-indexed library. Not used for any finding. |
| WebFetch on `code.claude.com/docs/en/hooks` | ✅ used | Note the 301 from `docs.claude.com` → `code.claude.com`. |
| **Local binary string extraction** | ✅ **primary source** | `/Users/oleg/.local/share/claude/versions/2.1.238`. Used to corroborate every hook claim, per the methodology warning in the 2026-09-01 1C audit (a WebFetch of this same page confabulated a Stop-hook contract). |
| WebSearch | ✅ used | Python 3.9 EOL, jq release/CVE state. |
| Live CLI probes | ✅ **primary source** | The `--json` flag, the selftest under two interpreters, the jq-failure behaviour. |
| Dependency manifests | **none exist** | `PROBE`: no `package.json`, `requirements.txt`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `Gemfile`, `composer.json` anywhere in the tree. Repo is bash + Python stdlib + markdown, per `CONVENTIONS.md` ("Python: stdlib only"). There is no third-party library to be stale. |

Because there are no manifests, this audit validates the three things that *are* external
dependencies: the **Python runtime**, the **`jq` binary**, and the **Claude Code hook contract**.

---

## 2. Libraries Mentioned

| Name | Spec context | Current | This machine | Repo floor / pin | Maintenance | Status |
|---|---|---|---|---|---|---|
| `argparse` (stdlib) | "a dependency (Python's argparse)" | tracks CPython | 3.9.6 / 3.14.7 | 3.9 (`CONVENTIONS.md`) | stdlib, maintained | 🟢 OK |
| **CPython (floor)** | implied runtime | 3.14.x | `/usr/bin/python3` = **3.9.6** | **3.9** (CI `validate.yml:276,345`) | **EOL 2025-10-31**, final 3.9.25 | 🟠 HIGH |
| **CPython (actual)** | implied runtime | 3.14.x | `python3` = **3.14.7** | untested above 3.12 | current | 🟡 MEDIUM |
| **`jq`** | "the hooks' `jq` parsing" | **1.8.2** (2026-06-20) | **1.7.1** (`/opt/homebrew/bin/jq`); `/usr/bin/jq` also present | unpinned, undeclared | active | 🟡 MEDIUM |
| Claude Code hook contract | `SessionStart`, `PostCompact` | 2.1.238 | 2.1.238 | — | active | 🟢 OK |
| `compound-v-dashboard.py resume --json` | **the thing to be built** | **already exists** | live-probed working | shipped in v2.19 | — | 🔴 see §4 |

---

## 3. API Signatures Verified

| Signature | Claimed / assumed | Verified | Verdict |
|---|---|---|---|
| `resume --json` | spec: to be **added** | `CODE` `scripts/compound-v-dashboard.py:1552` — `p_resume.add_argument("--json", dest="as_json", action="store_true", help="machine-readable output")`; handled `:1505-1512` | ❌ **already present** |
| `resume --json` output shape | — | `PROBE`: `{"active":[{"age_hours":…,"display_ts":…,"done":16,"id":…,"kind":"run","status":"COLLECTED","total":18}]}` — `json.dumps(..., indent=2, sort_keys=True)` (`:1511`) | ✅ exists, **untested** (§5) |
| PostCompact consuming JSON | spec: to be **enabled** | `CODE` `hooks/postcompact-resume.sh:222-225` — `resume --json … \| jq -r '.active[]? \| .id // empty'` | ❌ **already consuming** |
| `PostCompact` is a real event | assumed | `BINARY`: `\| PostCompact \| "manual"/"auto" \| After compaction (receives summary) \|`; `FETCHED` lists it #28 of 33 | ✅ correct |
| `PostToolUseFailure`, `PreCompact` | registered in `hooks/hooks.json` | `BINARY` 19 and 7 quoted hits; `FETCHED` lists both | ✅ correct |
| SessionStart context injection | `{hookSpecificOutput:{hookEventName,additionalContext}}` | `BINARY`: `hookSpecificOutput` — "must include `hookEventName`"; `additionalContext` — "Text injected into model context"; error string `Did you mean hookSpecificOutput.additionalContext (with a hookEventName)?` | ✅ `hooks/session-banner.sh:52-53` correct |
| PostCompact stdout → model context? | `hooks/hooks.json` claims **display text, not model context** | `FETCHED`: stdout becomes context only for `UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, `PostModelSwitch` — PostCompact absent | ✅ repo's claim holds; see 🟠-3 |

---

## 4. Critical Findings 🔴

### 🔴-1 · The spec's entire deliverable already exists

The spec asks to "add a `--json` flag to `scripts/compound-v-dashboard.py resume`". It is there.

```
scripts/compound-v-dashboard.py:1552
    p_resume.add_argument("--json", dest="as_json", action="store_true",
                          help="machine-readable output")
```

`PROBE` — `/usr/bin/python3 scripts/compound-v-dashboard.py resume --json` exits 0 and prints the
payload shown in §3. `resume --help` lists `[--json]`. It is documented as shipped in two places:
`CHANGELOG.md:535` ("`--json` for machine use, `--max-age-hours` to widen the window") and
`commands/v-status.md:132`.

**Consequence for the plan:** there is no build here. A plan written from this spec would either
re-add an existing flag or produce an empty diff, and the scope gate would have nothing to enforce.

### 🔴-2 · The PostCompact half of the goal is already done

```
hooks/postcompact-resume.sh:222-225
  ids="$(PYTHONDONTWRITEBYTECODE=1 "$py" "$dash" resume --json \
           --execution-root "$xroot" 2>/dev/null \
         | jq -r '.active[]? | .id // empty' 2>/dev/null \
         | head -n "$_MAX_IDS")" || ids=""
```

The hook already consumes structured output, and the comment above it states the intent the spec is
re-proposing: "from the same command's machine-readable mode, so the two can never disagree about
which runs are active."

**Only the SessionStart banner does not consume `--json`** (`hooks/session-banner.sh:42`). That is
the residual 25% of the spec — and 🟠-1 argues it should stay that way.

---

## 5. High-Priority Findings 🟠

### 🟠-1 · The stated motivation describes a parsing step that does not exist

The spec's rationale is "instead of parsing a rendered line". **No consumer parses the rendered
line.** All four use it verbatim:

| Consumer | Line | What it does with the line |
|---|---|---|
| `hooks/session-banner.sh` | `:42,44` | `banner="$banner $resume"` — string concatenation |
| `hooks/postcompact-resume.sh` | `:214-220` | prints it verbatim in `printf` |
| `hooks/precompact-snapshot.sh` | `:223` | writes it verbatim to the snapshot file |
| `hooks/triage-prompt-nudge.sh` | `:221` | consumes it as a line |

Switching the banner to `--json` would **create** parsing where none exists, and would force
`format_resume_line`'s vocabulary (`:1483-1502` — the "⏸ UNFINISHED COMPOUND V WORK…" sentence,
the `/v:status` recovery instruction, the `+N more` cap) to be re-implemented in bash. The repo
explicitly guards against exactly that; `hooks/postcompact-resume.sh:210` calls the line "rendered
by the one function that owns the vocabulary", and `precompact-snapshot.sh:33` says "It re-derives
NOTHING."

### 🟠-2 · The spec names two consumers; there are four

Blast radius of any change to the `resume` contract: `session-banner.sh`, `postcompact-resume.sh`,
`precompact-snapshot.sh`, `triage-prompt-nudge.sh`. The spec names the first two. A partition map
built from the spec as written would leave two hooks outside `write_allowed` and outside review.

### 🟠-3 · Structured output cannot change what the model sees at PostCompact

`FETCHED` — plain-text stdout is promoted to model context for only four events
(`UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, `PostModelSwitch`). `PostCompact` is not
among them; `hooks/hooks.json:5` already records this for 2.1.238 ("its stdout becomes the
compaction's display text, NOT model context"). Two independent sources agree.

So for the PostCompact consumer, "structured vs rendered" is invisible to the model either way. Any
benefit claimed for that half of the spec is presentational only.

### 🟠-4 · The `--json` payload has zero test coverage, and a hook depends on it

`_selftest()` exercises the resume surface hard — `format_resume_line` empty/populated/over-cap,
`active_records` freshness and the mtime-resurrection guard (`:1351-1401`). It **never calls
`cmd_resume` with `as_json=True`**, and never asserts the payload's keys.

`PROBE`: `grep -n "as_json" scripts/compound-v-dashboard.py` → two hits only, `:1507` and `:1552`.

Meanwhile `postcompact-resume.sh:224` hard-depends on `.active[].id`. Renaming `active` or `id`
passes `--selftest`, passes CI, and silently degrades the hook to its `"the id query did not
return"` branch (`:243`) — a fail-open path that looks like normal operation.

### 🟠-5 · `session-banner.sh` is the only hook with no `jq` guard, and it fails loudly

`PROBE`, with a stub `jq` that exits 127 first on `PATH`:

| Hook | `command -v jq` guards | stdout | exit |
|---|---|---|---|
| `hooks/session-banner.sh` | **0** | *(empty)* | **127** |
| `hooks/postcompact-resume.sh` | 1 (`:145`) | *(empty)* | 0 |

`set -euo pipefail` (`session-banner.sh:13`) plus three unguarded `jq -n` calls (`:50,52,55`) means a
jq failure destroys the **whole** banner — the Compound V load notice, the `/v:init` hint, the
staleness warning and the resume line — not just the JSON envelope. `hooks/plan-saved-nudge.sh` has
the same shape (0 guards, 4 uses).

The spec proposes routing *more* JSON work through precisely this hook. `/usr/bin/jq` happens to
exist on this Mac, which is why the failure has never been seen here.

---

## 6. Medium Findings 🟡

### 🟡-1 · Python 3.9 is EOL; it is the CI floor

Python 3.9 reached end of life **2025-10-31**; 3.9.25 was the final security release. `validate.yml`
pins `python-version: '3.9'` for the selftest sweep (`:276`) and the tests job (`:345`), and
`/usr/bin/python3` on this machine is 3.9.6. The floor is deliberate (stock-macOS target,
`scripts/compound-v-scope-check.py:98`) and the code is correct for it — but it is now an
unsupported runtime, and CVEs disclosed after that date have no upstream patch.

### 🟡-2 · CI's ceiling is 3.12; the banner actually runs 3.14.7

`hooks/session-banner.sh:42` calls bare `python3`, which resolves to **3.14.7** here. CI tests 3.9
(`:276,345`) and 3.12 (`:112`). 3.13 and 3.14 are untested. `PROBE`: the selftest does pass on
3.14.7 — with warnings (🟡-3). Note the asymmetry: `postcompact-resume.sh` has a `_python` resolver
(`:120-133`), the banner does not, so the two hooks can run the same script under different
interpreters in one session.

### 🟡-3 · The `--json` payload's own fields come from APIs scheduled for removal

`PROBE` on 3.14.7:

```
scripts/compound-v-dashboard.py:262: DeprecationWarning: datetime.datetime.utcfromtimestamp() is deprecated
scripts/compound-v-dashboard.py:1180: DeprecationWarning: datetime.datetime.utcnow() is deprecated
```

Line 262 is `_iso()`, which produces **`display_ts`** — a field the `--json` payload exports
(`:1509`). So the exact contract the spec wants to formalize is computed by a deprecated call.
Five occurrences of `utcnow()`/`utcfromtimestamp()` across `scripts/*.py`.

Deprecated since 3.12; upstream says "scheduled for removal in a future version" and **no removal
version has been announced** — I found none, and am not going to invent one. Today the warnings are
invisible because every caller redirects `2>/dev/null`, which also means CI will not see them.

### 🟡-4 · `jq` is an undeclared, unpinned dependency, one minor behind

Current **1.8.2** (2026-06-20); this machine has **1.7.1**. Since 1.7.1: 1.8.0 fixed CVE-2024-23337
(signed integer overflow in `jvp_array_write`/`jvp_object_rehash`) and CVE-2024-53427 (NaN-with-
payload accepted when parsing JSON); 1.8.1 fixed CVE-2025-49014 (heap use-after-free in
`f_strftime`/`f_strflocaltime`). The hooks do not call `strftime`, so CVE-2025-49014 does not reach
them; the two parser fixes do, because `postcompact-resume.sh:231` pipes the model-generated
`compact_summary` through `jq`.

jq 1.8.0 also carries a **breaking change** to binding syntax (`[-1 as $x | 1,$x]` now yields
`[1,-1]`). The repo's filters use `--arg` and simple field access, so nothing here is affected — but
no minimum jq version is declared anywhere, so both the old parser bugs and the new semantics are
whatever the user's machine happens to have.

---

## 7. Design Constraints for the Plan

- **MUST NOT** plan "add `--json` to `resume`". It exists (`:1552`), works, and is documented in
  `CHANGELOG.md:535`. Re-read the file before writing a task for it.
- **MUST NOT** plan "make PostCompact consume structured output". `postcompact-resume.sh:222-225`
  already does.
- **MUST NOT** justify any task with "instead of parsing a rendered line" — no consumer parses it
  (🟠-1). If the banner is changed anyway, the justification has to be a real one.
- **MUST NOT** re-implement `format_resume_line`'s vocabulary in bash. `format_resume_line`
  (`:1483`) is the single owner; `postcompact-resume.sh:210` and `precompact-snapshot.sh:33` both
  encode that as an invariant.
- **MUST** treat the `resume` contract as having **four** consumers, not two, and list all four in
  `write_allowed` for any job that touches the output shape.
- **MUST** add `--selftest` coverage of `cmd_resume(as_json=True)` asserting the `active[].id` key
  **before** any change to the payload. Today CI cannot catch a rename that breaks
  `postcompact-resume.sh` (🟠-4).
- **MUST** guard `jq` in `hooks/session-banner.sh` with `command -v jq` — proven exit 127 with empty
  stdout otherwise (🟠-5) — before adding any further jq work to that hook. Note SessionStart also
  accepts plain-text stdout as context (`FETCHED`), so a jq-free fallback is available there.
- **MUST** keep every new line Python 3.9-safe (`CONVENTIONS.md`) *and* warning-clean on 3.14, since
  the banner runs 3.14.7 here while CI stops at 3.12 (🟡-2).
- **MUST NOT** add new `datetime.utcnow()` / `utcfromtimestamp()` calls (🟡-3). `datetime.timezone.utc`
  is the 3.9-compatible replacement; `datetime.UTC` is 3.11+ and would break the floor.

---

## 8. Open Questions for the Human

1. **The spec is factually stale — what should the probe do?** Its premise ("add `--json`") was
   implemented in v2.19 and its motivation ("instead of parsing a rendered line") never described
   this codebase. As a *workflow probe* this is arguably a success: three auditors ran and 1C caught
   it. But there is no work to dispatch. Options: (a) close it as "probe succeeded, no build";
   (b) rescope to the real defects this audit surfaced (🟠-4 test gap, 🟠-5 jq guard);
   (c) rewrite the spec against current `HEAD` and re-run the pre-flight.
2. **Should the SessionStart banner consume `--json` at all?** I recommend no (🟠-1, 🟠-5). If you
   want it anyway, the reason needs stating, because the current design is deliberate.
3. **Is the Python 3.9 floor still wanted now that 3.9 is EOL?** (🟡-1) Out of this spec's scope;
   it governs every script in the repo, so it is a standing decision, not a task.
4. **Declare a minimum `jq` version?** (🟡-4) Nothing declares one today.

---

## 9. Knowledge Base Updates

Appended to [`_knowledge-base/claude-code-hooks.md`](_knowledge-base/claude-code-hooks.md) and
[`_knowledge-base/claude-code-runtime.md`](_knowledge-base/claude-code-runtime.md) under
`## Updated 2026-09-02 — preflight-workflow-probe`: the full 33-event list, the four events whose
plain stdout becomes model context, `PostCompact`'s binary-confirmed row, the SessionStart
`hookSpecificOutput` shape, and the jq/Python currency facts with their probes.
