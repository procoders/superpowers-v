# Compound V — Phase 1C Library & Documentation Audit

**Spec audited:** `docs/superpowers/execution/epics/2026-09-03-glob-parity/specs/one-matcher.md` (F1 `one-matcher`)
**Topic slug:** `epic-gp-one-matcher`

## 0. V-memory recall (Step 0)

Six `compound-v-memory.py search` calls run before opening any project file, with different
phrasings (feature's own words, subsystem, and the failure class I most expected — an
in-repo hardened pattern the spec might not be citing): `"glob matcher parity fnmatch
pathspec"`, `"importlib spec_from_file_location sibling script loader"`, `"python version
pinned requirements stdlib only no dependencies"`, `"fnmatch character class bracket glob
semantics stdlib"`, `"compound-v-discover-models selftest importlib pattern sibling
loader"`, `"sys.pycache_prefix forged pyc importlib hardening"`. Two calls reported the FTS5
index was 1–2 docs behind HEAD and self-refreshed before answering (not the 87-doc-behind
state a prior 1C run flagged — negligible here, not treated as an open item).

Load-bearing hits, each independently re-verified live rather than trusted as-is (findings
below cite the live re-verification, not the recall text): the spec itself (expected — it's
the document under audit); `matcher-docs.md` (F2, the sibling doc-sync spec, confirms F1 is
scoped to code only); and five `dogfood`/`archaeology`/`specs` docs from the 2026-09-02
"v3.4-native-first" review chain that record a real, previously-exploited vulnerability class
in this exact area — a forged `scripts/__pycache__/compound-v-scope-check.<tag>.pyc` executing
in place of the real matcher — and the hardened fix for it. That thread is the basis for
**High-Priority Finding 🟠-1** below; I did not stop at the recall text, I re-read the current
shipped code it describes (§2–§3).

No Trigger-0 recon doc exists for this topic: `Glob` for `docs/superpowers/recon/*glob*` and
`*matcher*` returned no files. Consistent with the epic brief framing this as a small,
two-feature "stage 7" exercise, not a recon-gated topic.

## 1. Tools Available

- **Context7 MCP: not attached to this subagent** — `ToolSearch("context7 resolve-library-id
  query-docs")` returned no matching deferred tools. **DEGRADED: WebSearch-only.** This bites
  less than usual here: the spec introduces **zero third-party dependencies** (confirmed §1
  manifest check below), so the only genuinely "external" surface is CPython stdlib
  (`fnmatch`, `importlib.util`), which WebSearch/docs.python.org covers fine.
- **Manifests found: none.** `Glob` for `package.json` / `pnpm-lock.yaml` / `yarn.lock` /
  `requirements.txt` / `pyproject.toml` / `Cargo.toml` / `go.mod` / `Gemfile` /
  `composer.json` at repo root — zero matches, 2026-09-03. Matches this repo's repeatedly
  reconfirmed convention (stdlib-only Python, no dependency manifest of any kind — see
  `_knowledge-base/claude-code-runtime.md`, `_knowledge-base/python-tooling.md`).
- **Bash: clamped** to only `compound-v-memory.py search`/`recall-check` invocations for this
  spawn (`bashCommandClamp`). All other inspection below used `Read`/`Grep`/`Glob` directly
  against the live tree at current `HEAD`, not against recalled or remembered text.

## 2. Libraries / Internal Surfaces Mentioned

No external library appears anywhere in this spec. The "libraries" in scope are two CPython
stdlib surfaces and one first-party contract this repo maintains as if it were a library
(the scope gate's matcher) — treated with the same currency scrutiny per this project's own
established 1C convention (see `_knowledge-base/claude-code-runtime.md`, which does the same
for Claude Code's own runtime contracts when no third-party dependency exists).

| Surface | Spec context | Current state (live-checked 2026-09-03) | Repo floor | Maintenance | Status |
|---|---|---|---|---|---|
| CPython stdlib `fnmatch` | being **removed** from `compound-v-memory.py` | Unchanged since Python 3.2 through the current 3.15.0rc1 docs (WebSearch); no deprecation notice anywhere. `*` crosses `/`, `[seq]` is a character class — confirmed against `docs.python.org` — matching exactly the two defects the spec cites as its reason for removal. | 3.9 | stdlib, permanent | 🟢 removal is well-founded, not a library-currency issue |
| CPython stdlib `importlib.util` (`spec_from_file_location` / `module_from_spec` / `exec_module`) | spec's proposed loading mechanism | Same 3-call workflow, unchanged, current across every version searched (WebSearch, multiple independent tutorial + reference sources, 2026-09-03) | 3.9 | stdlib, permanent | 🟢 the API itself is current — **but see 🟠-1: the spec cites the wrong existing in-repo reference implementation of it** |
| `sys.pycache_prefix` | needed for the hardened variant of the above (not currently cited by the spec) | Stdlib attribute since Python 3.8 (PEP 3147/552 era) — safe under this repo's 3.9 floor | 3.9 (safe) | stdlib | 🟢 OK |
| `scripts/compound-v-scope-check.py` — `matches(path, pattern)` / `is_allowed(path, allowed)` | F1's delegation target | Live-read 2026-09-03: both exist exactly as the spec names them, at lines 378 and 384. Docstring semantics (`*` single-segment, `**` cross-segment incl. `dir/**`⇒`dir`, `?` one non-`/` char, `[`/`]` literal, fully anchored) match the spec's Goal paragraph verbatim. | n/a (first-party) | Actively maintained — 8+ same-week revisions per git history context in the docstring itself | 🟢 signature confirmed, no drift |

## 3. API / Signature Verification

| Call / claim | Spec's claim | Verified against | Result |
|---|---|---|---|
| `matches(path, pattern)` | Exists in `compound-v-scope-check.py`, single-pattern form | Live `Read`, `scripts/compound-v-scope-check.py:378-381`: `def matches(path, pattern): ... re.compile(glob_to_regex(pattern)).match(path) is not None` | **MATCH** |
| Bare-glob fallback should become `g.rstrip("/") + "/**"` | New behavior F1 wants (recursive) | Current `_file_matches` (`compound-v-memory.py:1067`) instead does `g.rstrip("/") + "/*"` — **single** star, non-recursive | Confirms the spec's own stated defect — not audit drift. Today's fallback under-matches (`fnmatch.fnmatch(x, "docs/*")` doesn't match `docs/a/b.md`); the spec's `/**` fix is correct and necessary for the `("docs", "docs/a/b.md", True)` parity row to pass. |
| "`importlib.util.spec_from_file_location`, the pattern `compound-v-discover-models.py`'s selftest uses" | Cited as the loading pattern to follow | Live `Read`, `scripts/compound-v-discover-models.py:228-234` (loads `compound-v-resolve-model.py`) | **MATCH as literally described** — but this is the **plain, unhardened** 3-line form, used only inside a developer-invoked `--selftest`. See 🟠-1: a **different**, hardened, in-repo precedent exists for loading *this exact sibling file* (`compound-v-scope-check.py`) and the spec does not cite it. |
| (not cited by spec) hardened equivalent for loading `compound-v-scope-check.py` in-process | — | Live `Read`, `scripts/compound-v-integration-gate.py:417-470` (`load_scope_matcher`) | Exists, targets the **same** sibling file F1 needs, adds `sys.pycache_prefix` redirection to a throwaway `tempfile.mkdtemp()` dir + fail-closed if that dir can't be created + `finally`-block restore/cleanup. Has its own dedicated selftest coverage (`:2372-2398`) that plants a forged `.pyc` and asserts it is never executed. |
| `fnmatch.fnmatch(path, pattern)` current semantics | Spec's stated reason for removal (`*` crosses `/`, `[...]` reads as char class) | WebSearch, `docs.python.org` 3.9 through 3.15 `fnmatch` pages, 2026-09-03 | **MATCH** — unchanged, no version-specific drift found |

## 4. Critical Findings 🔴

None in the literal sense this rubric defines (deprecated/archived/unmaintained
**dependency**) — there is no dependency. This audit's one blocking finding is a
pattern-currency / API-signature issue, not a dependency-lifecycle one, so it is filed under
§5 per this project's own established convention (see `2026-09-03-v3-4-2-transcript-watch.md`,
same shape: 0 in Critical, the real substance in High-Priority). Do not read the empty section
here as "nothing to fix before merge" — 🟠-1 below is a MUST.

## 5. High-Priority Findings 🟠

**🟠-1 — The spec cites the wrong in-repo reference pattern for loading `compound-v-scope-check.py`; the right one already exists in this exact codebase, is security-motivated, and is dogfooded/tested.**

This repo has *already* solved "how do we safely load `scripts/compound-v-scope-check.py` as
a Python module, in-process, from another script" — and the solution is not the plain
`spec_from_file_location`/`module_from_spec`/`exec_module` triple the spec cites from
`compound-v-discover-models.py`'s selftest.

- `scripts/compound-v-integration-gate.py:417-470` (`load_scope_matcher`) loads this **same**
  sibling file and additionally: redirects `sys.pycache_prefix` to a private `tempfile.mkdtemp()`
  directory before `exec_module`, and **imports nothing at all** if that directory cannot be
  created (`:433-452`) — restoring the prior prefix and removing the temp dir in a `finally`.
  Its own docstring states why: *"It is loaded FROM SOURCE, never from a cache beside it. A
  forged `scripts/__pycache__/compound-v-scope-check.<tag>.pyc` — an unchecked hash-based one,
  which CPython never validates against its source — would otherwise execute HERE, in this
  process, and could hand back an `is_allowed` that returns True for every path."*
- This is not theoretical: `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-4.md`
  ("ISSUE 1 — QUALITY: the narrowed carve-out still hides a forged `.pyc`, and that `.pyc`
  executes as the lane guard's own matcher — demonstrated end to end") and the subsequent
  review-5 pass record this as a **found-and-fixed** vulnerability in this exact codebase,
  against this exact target file, days before this spec was written. `AGENTS.md`'s own
  top-of-file cost accounting calls the `PYTHONPYCACHEPREFIX` redirection out by name as "worth
  paying" defense-in-depth, not a hypothetical.
- The pattern the spec cites instead — `compound-v-discover-models.py:228-234` — loads a
  **different**, lower-stakes sibling (`compound-v-resolve-model.py`) with none of that
  hardening, and only ever runs inside a developer-invoked `--selftest`, never in an automated
  pipeline path. It is a reasonable pattern **for that context**, not for this one.
- **Why the trust boundary is the same here, not lower:** `_file_matches`'s caller,
  `recall_check`, is not an interactive-only tool. `agents/partition-reviewer.md` invokes
  `python3 scripts/compound-v-memory.py recall-check --files <every write_allowed glob>` for
  every lane, as part of the pre-execution gate that runs before every dispatch (confirmed by
  direct `Grep` of that agent file, `:16-19`). A forged `.pyc` sitting in
  `scripts/__pycache__/compound-v-scope-check.*.pyc` would be silently executed the first time
  `compound-v-memory.py`'s new loader imports it in-process — in the orchestrator's own
  process, before dispatch, exactly the moment the existing hardening was built to protect.
- `compound-v-integration-gate.py`'s **own** production per-job scope check
  (`run_scope_check`, `:742-747`) deliberately does **not** import `compound-v-scope-check.py`
  at all — it shells out via `subprocess.run([sys.executable, scope_check], ...)`, with the
  comment *"A subprocess, not an import: this script must not be able to perturb the matcher
  it is checking against."* A subprocess running a script as `__main__` is not written to or
  read from `__pycache__`, so that path is naturally immune to the .pyc-forgery class — but a
  subprocess-per-call design is not viable for F1's call shape (`_file_matches` is invoked once
  per (changed-file, glob) pair inside a nested loop over every recorded failure — potentially
  many calls per single `recall-check` invocation). In-process loading is the right choice for
  F1's performance needs; **given that**, the hardened in-process pattern
  (`load_scope_matcher`) is the only one of this repo's two existing precedents that is safe to
  copy — not the unhardened selftest-only one the spec names.

**MUST:** the implementer loads `compound-v-scope-check.py` using the same
`sys.pycache_prefix`-redirect-and-fail-closed shape as
`compound-v-integration-gate.py:417-470`, not the bare 3-call form at
`compound-v-discover-models.py:228-234`. Concretely: `import shutil` (not currently imported
in `compound-v-memory.py`; `sys` and `tempfile` already are) alongside the existing
`import importlib.util`. `getattr(sys, "pycache_prefix", None)` before, `tempfile.mkdtemp()`
guarded by its own `try`/`except` returning the `unavailable` verdict on failure (never
falling back to the default in-tree cache), restore + `shutil.rmtree` in a `finally`. This is
additive to, not a replacement for, the spec's own already-correct "sibling cannot be loaded ⇒
`verdict: unavailable`" contract (§ Loading) — that contract already covers the *"module raised
on exec"* failure mode; it does not by itself cover the *"module loaded successfully because it
was forged bytecode"* mode, which only the cache redirection closes.

**🟠-2 — The loading/exec step must be hoisted out of the per-file hot path, not repeated inside `_file_matches`.**

`recall_check` calls `_file_matches(changed, file_globs)` once per `(failure, changed-file)`
pair in a nested loop (`compound-v-memory.py:1076-1081`) — potentially dozens of calls per
single `recall-check` invocation (one per lane's `write_allowed` glob list, called for every
lane before every dispatch, per 🟠-1's `partition-reviewer.md` citation). Today that's cheap:
`fnmatch.fnmatch` is a pure-stdlib call with no I/O. The replacement is not: `tempfile.mkdtemp()`
is a real filesystem syscall, and even the hardened loader's `exec_module` re-parses and
re-executes the sibling file's top level. If the natural refactor — swap
`fnmatch.fnmatch(changed, g)` for a call to the loaded `matches`/`is_allowed` — is written
inline inside `_file_matches` itself, the import-and-mkdtemp dance re-runs on **every** call
instead of once. `compound-v-integration-gate.py`'s own usage of `load_scope_matcher` is
call-once-reuse-the-callable (confirmed: exactly one production-shaped call site, `:2389`,
itself inside a selftest that calls it directly rather than in a loop). **MUST:** load once
per `recall_check` (or `cmd_recall_check`) invocation — e.g. as a module-level lazy cache, or a
callable threaded through `_file_matches`'s call sites — and reuse the resulting function object
across every glob/file pair, matching the existing precedent's call shape rather than the
per-item shape `_file_matches` currently has.

## 6. Medium Findings 🟡

**🟡-1 — Python 3.9 EOL, inherited, not novel to this spec.** Independently reconfirmed by
three separate same-week 1C audits already in `_knowledge-base/python-tooling.md`
(2026-09-03 entries for v3.4.5, v3.4.6, v3.4.10): Python 3.9 reached end-of-life 2025-10-31,
3.9.25 is the final release, and this repo's CI floor (`.github/workflows/validate.yml`) pins
`python-version: '3.9'` on purpose (stock-macOS `/usr/bin/python3` is 3.9.6). Not re-derived
here — cited. This spec's own change carries **no new 3.9-incompatibility risk**: the
`importlib.util` trio, `sys.pycache_prefix`, `tempfile.mkdtemp`, and `shutil.rmtree` have all
been 3.9-safe since well before that floor (`pycache_prefix` since 3.8). The one concrete trap
for the implementer to actively avoid while writing the new loader: no `match`/`case`, no
`X | Y` in `isinstance()`, no `datetime.UTC` — none of which this task has a reason to reach
for, but the KB's own v3.4.10 entry names this exact trap-list for the next contributor who
does.

## 7. Design Constraints for the Plan

**MUST:**
1. Load `scripts/compound-v-scope-check.py` using the `sys.pycache_prefix`-redirect,
   fail-closed-on-mkdtemp-failure pattern already shipped at
   `scripts/compound-v-integration-gate.py:417-470` (`load_scope_matcher`) — not the bare
   `spec_from_file_location`/`module_from_spec`/`exec_module` triple at
   `compound-v-discover-models.py:228-234`, which the spec currently names and which lacks this
   hardening (🟠-1).
2. Perform that load-and-exec exactly once per `recall_check`/`cmd_recall_check` invocation and
   reuse the resulting callable across every `(file, glob)` pair; do not repeat the loading
   inside `_file_matches`'s per-item call path (🟠-2).
3. Keep the spec's own already-correct "sibling failed to load ⇒ `verdict: unavailable`,
   `note: "scope-check matcher unavailable"`" contract — the pycache hardening is additive, not
   a replacement for that fallback.
4. Target Python 3.9 syntax throughout the new loader code (plain `if`/`elif`, no
   `match`/`case`, no `X | Y` isinstance checks, no `datetime.UTC`) — inherited floor, no new
   risk, but worth stating explicitly since this touches new code (🟡-1).
5. `import shutil` at module top level in `compound-v-memory.py` (not currently imported;
   `sys`/`tempfile` already are) — required by the hardened pattern's `finally`-block cleanup.

**MUST NOT:**
1. Add any third-party Python package — every surface this spec touches is stdlib-sufficient
   (confirmed §2).
2. Fall back to the default (in-tree) `__pycache__` location if the private cache directory
   cannot be created — that silently reopens the exact forged-`.pyc` execution path
   `compound-v-integration-gate.py`'s own history shows was found and closed once already
   (🟠-1).
3. Remove the `fnmatch` import from `compound-v-memory.py` (per the spec's own acceptance
   criteria) while leaving any other use of it in the file — confirmed via live `Grep` that the
   only two current uses (`compound-v-memory.py:1065,1067`) are both inside `_file_matches`
   itself, so removal is currently clean; re-check this if `_file_matches` moves before the
   fnmatch import is deleted.

## 8. Open Questions for the Human

1. **Is `load_scope_matcher`'s hardening pattern itself meant to be reused verbatim by a
   second file, or refactored into a shared helper first?** Two independent copies of the same
   ~35-line security-critical dance (one in `compound-v-integration-gate.py`, a near-duplicate
   about to land in `compound-v-memory.py`) is a real DRY question — but resolving *how* to
   share it (a third sibling module both import? a copy with a comment pointing at the other?)
   is a design decision for writing-plans, not something this audit should decide. Flagging so
   it isn't accidentally decided by whichever file gets written first.
2. Whether `load_scope_matcher`'s in-process path is actually reachable from
   `compound-v-integration-gate.py`'s **production** `evaluate_run`/gate flow, or is currently
   exercised only by its own selftest (the production per-job scope check instead shells out to
   `run_scope_check`, `:742-747`) — not resolved this pass, and not this spec's problem, but
   worth a Phase 1A confirmation since it changes how "established" the precedent in 🟠-1 truly
   is in *production* terms (it is, at minimum, established and tested — whether it is also
   *currently invoked outside its own test* is the open part).

## 9. Knowledge Base Updates

Appended one dated section to the **existing**
`docs/superpowers/library-audit/_knowledge-base/python-tooling.md` (correct home — it already
owns this repo's Python-pattern-currency findings, including the v3.4.10 entry on the sibling
`_load_sibling`/DENSE-lane boundary). New section:
`## Updated 2026-09-03 — epic-gp-one-matcher (F1)`, recording: the two competing in-repo
patterns for loading `compound-v-scope-check.py` in-process (hardened vs. plain), exact line
citations for both, the dogfood-review provenance of the hardening, and the
call-once-not-per-item constraint. No prior entry needed strikethrough — first entry on this
specific sub-topic (loading `compound-v-scope-check.py` from a second consumer).
