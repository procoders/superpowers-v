# Library & Documentation Audit — v3.4.10 recall→action bridge

**Spec:** `docs/superpowers/specs/2026-09-03-v3.4.10-recall-to-action-design.md`
**Plan:** `docs/superpowers/plans/2026-09-03-v3.4.10-recall-to-action.md`
**Topic slug:** `v3-4-10-recall-to-action` · **Date:** 2026-09-03

**DEGRADED: WebSearch-only.** No `*context7*resolve-library-id` / `*context7*query-docs` tool was
present in this session's tool list (checked via `ToolSearch` for `context7 resolve-library-id
query-docs` and again for `library documentation lookup mcp` — no MCP-provided library-doc tool
matched either query). This turned out not to bind the outcome: the spec and plan introduce **zero**
new third-party libraries, so there was nothing in Context7's actual domain (SDK docs) to look up.
The one live check this audit needed — Python's own EOL/support status — was done with `WebSearch`
directly against vendor/EOL-tracker sources.

## Step 0 — V-memory recall

Two queries against `scripts/compound-v-memory.py search` (`--intent planning --top 8`):
`"recall to action bridge emit time tighten"` and `"auto_tighten auto_recall memory.md"`. Both
returned the spec and plan under audit (expected — they're the newest matching prose) plus, usefully,
three prior-audit citations that are directly on point and are treated as evidence below, not
re-derived: `docs/superpowers/library-audit/_knowledge-base/python-tooling.md`'s
**v3.4.5-recall-freshness** entry (Python 3.9 EOL date + `sqlite3.autocommit` trap, live-verified
earlier the same day) and its **F2** entry (this repo's stdlib-first design promise and where it's
already been violated, elsewhere, not here). No V-memory result was stale or contradicted by the
code read below; nothing here overrides code with prose.

## 1. Tools Available

| Tool | Status |
|---|---|
| Context7 MCP (`resolve-library-id` / `query-docs`) | ❌ not present in this session (see DEGRADED note above) |
| WebSearch | ✅ used once (Python EOL cross-check) |
| Repo dependency manifests | **None exist.** `Glob` for `package.json`, `requirements.txt`, `pyproject.toml` (repo-wide) returned zero matches. This is a pure-stdlib-Python + POSIX-shell plugin repo with no formal dependency manifest — consistent with the AGENTS.md-documented "stdlib only" design stance and with the existing KB's F2 entry (which is about that promise being violated by `lint-frontmatter.py`'s unconditional `import yaml`, a file untouched by this spec). |
| Trigger 0 recon doc for this topic | **None found.** No exact path was handed to this agent; the fallback scan (`Glob docs/superpowers/recon/*recall*`, `*3.4.10*`) found nothing. Recon step skipped, noted per protocol — not a gap this audit can fill. |

## 2. Libraries Mentioned

The spec and plan name **zero** third-party libraries, SDKs, or external APIs. Direct read of both
target files' import blocks (`Grep '^import |^from '`) confirms what's actually available at the
call site Task A extends:

| Name | Spec context | Current ver | Repo pinned | Last release | Maintenance | Status |
|---|---|---|---|---|---|---|
| Python (CPython) runtime | The floor the plan pins for `--selftest`: *"`--selftest` green; Python 3.9"* (plan, Task A, last bullet) | 3.14.7 (2026-08-05); 3.15.0rc2 cut 2026-09-01, GA expected Oct 2026 | **3.9** — `.github/workflows/validate.yml:280-283,343-346` (per existing KB entry, not re-derived) | 3.9 line: final release **3.9.25**, EOL **2025-10-31** (re-confirmed live this session, see below) | Frozen — no further patches of any kind, ever, for 3.9 | 🟡 MEDIUM (frozen EOL floor; see Finding M-1) |
| `subprocess`, `json`, `argparse`, `sys`, `os` (stdlib) | Implicit — Task A's `[sys.executable, "-B", ...]` subprocess call and JSON parsing of its stdout | Ships with the interpreter; no independent versioning | n/a | n/a | n/a | 🟢 OK — already imported in `scripts/compound-v-emit-workflow.py` (`Grep` lines 54-55, 110-116) and `scripts/compound-v-memory.py` (lines 30-41); no new dependency added |
| `numpy`, `onnxruntime`, `tokenizers`, `huggingface_hub` | **Not** mentioned by this spec. Found by `Grep` inside `compound-v-memory.py` (line 453-454, `EMBEDDER_SRC` string) while scanning that file's actual imports for Step 3 diligence | Already documented — see `_knowledge-base/agent-instruction-tooling.md`, "V-memory embedding lane" entry, 2026-06-30 | Unpinned, isolated out-of-repo venv | (not re-verified here — out of scope) | (not re-verified here — out of scope) | 🟢 OK / **out of scope** — this is the DENSE lane, architecturally unreachable from `recall-check` (the FTS5-only, "NOT embedding similarity" path this spec's Decision section names explicitly) and from `build_plan`. Flagged only so the next reader doesn't mistake the `import numpy as np` sitting 450 lines above Task A's grep target for something Task A touches. |

**Bottom line:** this spec adds no dependency for anyone to go stale. The only "library" in play is the
Python interpreter itself, and the finding there is about the *floor*, not about a specific package
version.

## 3. API Signatures Verified

No third-party SDK method calls appear in the spec or plan, so there is no Context7-style signature
to validate. The two stdlib call shapes the plan specifies were checked against current CPython docs
(these are unchanged across every CPython 3.x release relevant here — 3.9 through 3.14 — so no
version-specific drift is possible, but stating the shape confirms the plan isn't assuming a removed
or renamed kwarg):

| Call | Plan's shape | Verified current signature | Drift |
|---|---|---|---|
| `subprocess.run([sys.executable, "-B", ...], timeout=30, ...)` | positional `args` list + `timeout=` kwarg | `subprocess.run(args, *, timeout=None, capture_output=False, text=None, ...)` — `timeout` (3.3+), `capture_output` (3.7+), `text` (3.7+, alias of `universal_newlines`) all present since well before the 3.9 floor | None |
| `python3 -B ...` | `-B` flag to suppress `.pyc` writes | Documented CLI flag, unchanged since Python 2 | None |

No internal (`compound-v-memory.py` `recall-check` subcommand) signature is re-verified here —
that CLI's actual flag names/JSON shape (`--files`, `--json`, `--results-root`, the `verdict` field)
is this repo's own code, not a third-party API, and is code-archaeology's (Phase 1A) territory to
confirm against the live source, not mine to duplicate.

## 4. Critical Findings 🔴

None.

## 5. High-Priority Findings 🟠

None. (No library crosses 12+ months without a commit, because no library is introduced.)

## 6. Medium Findings 🟡

### M-1 — Python 3.9 floor is frozen-EOL; this spec's plan re-commits to it without flagging that

- **What:** The plan's Task A explicitly gates its selftests on *"Python 3.9"*. Live-reconfirmed this
  session (WebSearch, 2026-09-03): Python 3.9 reached end-of-life **2025-10-31**; **3.9.25** was the
  final release; no further bug fixes or security patches will ever ship for it. Current stable line
  is 3.14 (3.14.7, 2026-08-05); 3.15 is in RC. This matches, word-for-word on the date, the existing
  KB entry from the same-day v3.4.5-recall-freshness audit (`python-tooling.md`), so it is not new
  information — it is a **re-surfacing**, because this spec is the kind of change (new code added to
  a file already pinned at that floor) where the constraint actually bites.
- **Why it's a finding here specifically, not just background:** none of Task A's new logic (JSON
  parsing, dict construction, tier-rung arithmetic, prompt-string concatenation) needs anything newer
  than 3.9 — so the floor is *achievable* — but it is also *unenforced at runtime*: `Grep` for
  `sys.version_info` anywhere under `scripts/` found no matches. The only place 3.9-compatibility is
  actually checked today is CI's pinned `python-version: '3.9'` job. A contributor or dispatched
  worker running a newer local interpreter (very likely — 3.9 is EOL, most dev machines and CI images
  default newer) would see 3.10+-only syntax work locally and fail only in CI, or on a real user's
  stock-3.9.6 macOS `python3`.
- **Alternative / mitigation:** none needed for the *library* (there's no library to replace — this
  is the interpreter). The actionable mitigation is process, not library choice: see Design
  Constraints §7 below, which turns this into MUST/MUST NOT bullets for the plan.
- **Source:** WebSearch 2026-09-03 (python.org 3.9.25 notes; endoflife-tracker aggregation;
  Red Hat Developer 2025-12-04 "Python 3.9 reaches end of life"); cross-checked against
  `_knowledge-base/python-tooling.md`'s v3.4.5-recall-freshness entry (same claim, same date, earlier
  same day).

### M-2 — Two Python-3.10+-only constructs are easy for an LLM to reach for here, and only one of them is protected by the file's existing `__future__` import

- **What:** `scripts/compound-v-emit-workflow.py` line 52 has `from __future__ import annotations`
  (confirmed by direct `Grep`). That defers evaluation of **annotations** (parameter/return/variable
  type hints) to strings, so writing `def foo(verdict: str | None = None)` in *annotation position*
  is safe on 3.9 in this file specifically — the `X | Y` union-type PEP 604 syntax will not raise, because it's never evaluated as a live expression.
  That is a genuine, non-obvious point in this spec's favor and worth stating so nobody "fixes" it by
  quoting the annotation unnecessarily.
- **The trap `from __future__ import annotations` does NOT cover:** any `X | Y` union used as a
  **runtime expression**, not an annotation — most concretely `isinstance(verdict_value, str | None)`
  or `case str() | None():` inside a `match`/`case` statement. Both require Python **3.10+** at the
  language level regardless of the `__future__` import, because they are evaluated immediately, not
  deferred. The plan's own branching is exactly the shape that invites this: verdict is one of three
  literal strings (`"tighten"` / `"none"` / `"unavailable"`), and `match verdict: case "tighten": ...`
  is a natural, idiomatic-looking choice for code written against a post-3.10 mental model — and it
  would break the file's own stated 3.9 floor. `Grep` for `match \w+:`/`case ["']`/`:=` (walrus, 3.8+,
  fine) across `compound-v-emit-workflow.py` found zero existing uses of `match`/`case` — so there is
  no established in-file precedent either way to imitate, which makes this an anti-anchoring risk
  specific to a model whose training data skews post-3.10, not a repo-convention question Phase 1A
  would already have answered.
- **Alternative:** plain `if`/`elif`/`else` on the string value — already the file's demonstrated
  style everywhere else in its 6,000+ lines (spot-checked via the same greps above; no `match` blocks
  exist to contradict this).
- **Source:** direct file read (`Grep '^import \|^from '`, `Grep 'match \w+:\|case \["\x27\]\|:='`,
  both against `scripts/compound-v-emit-workflow.py`, 2026-09-03) + CPython language reference for
  PEP 604 (`X | Y` types, 3.10+) and PEP 634 (`match`/`case`, 3.10+) — well-established, stable facts
  not subject to further drift, so not re-fetched live this session; flagged here because it's the
  kind of stale-training-data trap this role exists to catch, not because the version numbers
  themselves were in doubt.

## 7. Design Constraints for the Plan

- **MUST** keep Task A's new code stdlib-only (`subprocess`, `json`, `os`, `sys` — already imported
  in both target files). No new `import` of any third-party package belongs in this change.
- **MUST NOT** use a `match`/`case` statement to branch on the `verdict` string (`"tighten"` /
  `"none"` / `"unavailable"`) — Python 3.10+ only; this file's floor is 3.9. Use `if`/`elif`/`else`,
  matching the file's existing, unbroken style.
- **MUST NOT** write a runtime `isinstance(x, TypeA | TypeB)` / `issubclass(x, TypeA | TypeB)`
  expression anywhere in the new code — Python 3.10+ only, and **not** protected by the file's
  existing `from __future__ import annotations` (that import defers annotation evaluation only, never
  runtime expressions). Use `isinstance(x, (TypeA, TypeB))` (the pre-3.10 tuple form), which works
  identically on every CPython version this repo has ever targeted.
- **MAY** freely use `X | Y` union syntax in actual type-hint *annotation* positions (parameter,
  return, and variable annotations) in `compound-v-emit-workflow.py` specifically — `from __future__
  import annotations` at line 52 already makes that safe on 3.9 in this file. Do **not** remove or
  move that import line; removing it would silently turn every such annotation in the file into a
  runtime `TypeError` on 3.9.
- **MUST** invoke `compound-v-memory.py`'s `recall-check` via `subprocess`
  (`[sys.executable, "-B", <path>, "recall-check", ...]`), never via `import` of that module — this
  is what the spec's Decision section already specifies ("subprocess, the same stdlib CLI; never an
  import"), and it is the right call: it sidesteps exactly the kind of hard, fallback-free dependency
  coupling the existing KB already flags as this repo's known anti-pattern elsewhere (`import yaml`
  with no fallback in `lint-frontmatter.py`, per `_knowledge-base/python-tooling.md`'s F2 entry) —
  worth stating explicitly here so nobody "simplifies" Task A into an `import` during implementation.
- **MUST NOT** introduce a code path in `build_plan` (or anywhere Task A touches) that imports
  `numpy`, `onnxruntime`, `tokenizers`, or `huggingface_hub` directly. Those live only inside the
  string-embedded `EMBEDDER_SRC` script (`compound-v-memory.py` lines 449-454) that runs *inside the
  isolated out-of-repo venv* the DENSE lane bootstraps — importing any of them from the emitter's own
  process would break the "stdlib only in the emitter" invariant this spec otherwise preserves, for a
  path (`recall-check`) the spec itself says is structured-match-only, not embedding similarity.
- **subprocess.run(..., timeout=30, capture_output=True, text=True)** is a safe, unchanged stdlib
  call shape on Python 3.9 — no constraint needed here beyond confirming it (§3 above); noted so a
  reviewer doesn't spend a review cycle re-verifying it.

## 8. Open Questions for the Human

- **Is a runtime or CI floor-check ever planned for the 3.9 pin, or does it stay convention-only?**
  Today nothing in `scripts/` checks `sys.version_info` — the only enforcement is CI's pinned
  `python-version: '3.9'` job. That's an existing-code fact (Phase 1A's to confirm/own), not something
  this spec should fix, but it is the reason Finding M-2's traps are real rather than theoretical: a
  contributor's or a dispatched worker's local interpreter is very likely newer than 3.9 (3.9 has been
  EOL for ~11 months as of this audit's date), so a 3.10+-only construct written and tested locally
  would pass every check the author personally runs and fail only in CI, or in the field on a real
  user's stock macOS `python3.9.6`. Worth a scoping decision at the human/portfolio level (raise the
  floor now that 3.9 is fully dead, vs. keep 3.9 for the stock-macOS-python3 compatibility reason the
  KB's F2 entry documents) — not a decision this spec or this audit should make unilaterally.

## 9. Knowledge Base Updates

Appended one dated entry to `docs/superpowers/library-audit/_knowledge-base/python-tooling.md`
(`## Updated 2026-09-03 — v3.4.10-recall-to-action`): records (a) the same-day EOL re-confirmation
via independent WebSearch (cross-checks, does not contradict, the earlier same-day v3.4.5 entry),
and (b) the new, reusable finding about `match`/`case` and runtime `X | Y` in `isinstance()` being
3.10+-only and NOT covered by an existing `from __future__ import annotations` import — general
enough that the next Phase 1C pass touching any `from __future__ import annotations`-carrying,
3.9-floored file in this repo can cite it instead of re-deriving it. No prior entry in that file was
struck through — nothing here contradicts a previous claim.
