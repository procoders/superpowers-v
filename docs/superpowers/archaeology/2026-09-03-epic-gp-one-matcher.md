# F1 `one-matcher` Code Archaeology

Spec under audit: `docs/superpowers/execution/epics/2026-09-03-glob-parity/specs/one-matcher.md`.
Scope per spec: modify `scripts/compound-v-memory.py` only (`_file_matches`, a new loader, the
selftest). No other file.

## Step 0 — V-memory recall

Ran `scripts/compound-v-memory.py search` three times (`"glob matcher pattern parity fnmatch"`,
`"recall-check scope-check write_allowed glob"`, `"compound-v-discover-models selftest importlib
spec_from_file_location"`), `--intent planning`. Not empty — all three returned the spec itself
plus real prior art:

- The epic's own two specs (`one-matcher.md`, `matcher-docs.md`) and `brief.md` — read in full
  below.
- `docs/superpowers/architecture/architecture.md` — "The git-diff scope gate": confirms
  `compound-v-scope-check.py` is *the* deterministic authority and `blocked`/`files_changed`/
  `violations` are git-derived, never model-self-reported.
- `docs/superpowers/specs/2026-09-01-v3.0-triage-tests-orchestration-design.md` — "E1. The rule":
  `hooks/lane-guard.sh` already tests `tool_input.file_path` against `write_allowed` "with the
  same matcher" — i.e. the scope-gate matcher is already the intended single source of truth
  project-wide; F1 brings `recall-check` into line with an existing project norm, not inventing one.
- `docs/superpowers/archaeology/2026-09-02-v3-4-native-first.md` — **stale but load-bearing**: its
  §2a and §5 document that `_load_sibling` (the import-by-path pattern used throughout this repo)
  "raises (unhandled)" when the target file is gone, inside `run_preeval`'s append path. That
  finding was written about a *hypothetical* future deletion of `compound-v-update-memory.py`
  (which still exists today — confirmed live, see §3) — so the specific incident never happened.
  What is NOT stale: it proves this repo already has a live, undocumented pattern of unguarded
  `_load_sibling` calls that raise instead of degrading, and F1's own spec explicitly requires the
  opposite ("never a silent `none`" — actually never a silent *crash* either). Treated as a
  warning about a class of bug in sibling code, not as a claim about current file existence.
- `docs/superpowers/dogfood/2026-09-03-v3.4.10-recall-to-action-review.md` and
  `docs/superpowers/plans/2026-09-03-v3.4.10-recall-to-action.md` — confirm `recall-check` is
  wired into production at emit time as a **subprocess**, never an import, from
  `compound-v-emit-workflow.py`. Read the live code in full below (§2, §5).

No claim below rests on a stale recollection alone — every one is cross-checked against the code
as it reads today (2026-09-03).

**Tooling note:** this run's Bash access was clamped to exactly two command forms (both
`compound-v-memory.py` invocations). `git log` / `git blame` were not reachable from this sandbox,
so "recent commits" evidence below comes from V-memory's dated prose (dogfood/archaeology docs)
and from live behavioral probes against the current file contents, not from git history directly.
That is a real gap in this audit's method, not a silent omission.

## 1. Matrix

Dimensions the matcher touches: **glob-pattern class** × **matcher implementation** × **call site**.

| Glob-pattern class | Example | `fnmatch` (today) | `scope.matches` (target) | New code must handle? |
|---|---|---|---|---|
| single-segment `*` | `src/*.py` vs `src/a.py` | match | match | yes — unchanged case |
| single-segment `*`, nested path | `src/*.py` vs `src/a/b.py` | **match (bug — `*` crosses `/`)** | no match | yes — this is the fix |
| cross-segment `**` | `src/**` vs `src/a/b.py` | match (accidentally, same bug) | match (by design) | yes |
| `dir/**` matches `dir` itself | `src/**` vs `src` | no match (fnmatch has no such rule) | match | yes — new capability, not just a bug fix |
| bracket segment | `app/[locale]/**` vs `app/[locale]/page.tsx` | **no match (bug — `[locale]` read as a 5-char class, not literal)** | match | yes — this is the headline fix |
| bracket segment, different literal segment | `app/[locale]/**` vs `app/l/page.tsx` | no match (coincidentally correct) | no match | yes |
| bare dir/prefix, no wildcard | `docs` vs `docs/a/b.md` | match (via `_file_matches`'s own `g + "/*"` fallback, which crosses `/` under fnmatch) | **no match unless the fallback suffix becomes `/**`** | yes — see §2 "the fallback suffix" |
| bare literal file | `README.md` vs `README.md` | match | match | yes |
| bare literal file, different dir | `README.md` vs `docs/README.md` | no match | no match | yes |
| `**/x.py` leading double-star | `**/x.py` vs `x.py` | match (again by `*`-crosses-`/` accident) | match (by explicit "zero-or-more leading segments" rule, `scope-check.py:350-356`) | yes |

**Live-verified today (2026-09-03), against this exact checkout, with real fixture
`job_result.json` records under a `--results-root`** (see §5 for the reproduction):

1. `recall-check --files 'app/[locale]/**' --k 1` against a recorded `blocked` failure whose
   `violations` is `["app/[locale]/page.tsx"]` → **`verdict: none, match_count: 0`**. The
   fnmatch-based matcher cannot see this real, recorded, repeat failure at all — silent false
   negative, exactly the bug the spec names.
2. `recall-check --files 'src/*.py' --k 1` against a recorded `blocked` failure whose `violations`
   is `["src/a/b.py"]` → **`verdict: tighten, match_count: 1`**. `src/*.py` should NOT match a
   file two segments deep, but fnmatch's `*` crosses `/`, so this is a false positive — a lane
   that never should have tightened does.

Both directions of the bug are real and reproducible today, not hypothetical.

Was the fix's own acceptance table (8 rows, spec lines 22–27) verified against the CURRENT
`fnmatch`-based code, cell by cell, to confirm which rows already coincidentally pass and which
are the actual regressions being fixed? Yes:

| Row | `fnmatch.fnmatch` today | `scope.matches` (target) | Same? |
|---|---|---|---|
| `("src/*.py","src/a.py",True)` | True | True | yes |
| `("src/*.py","src/a/b.py",False)` | **True (bug)** | False | **no — this row is the regression test** |
| `("src/**","src/a/b.py",True)` | True | True | yes (coincidence: fnmatch's `*` already crosses `/`) |
| `("src/**","src",True)` | **False** — fnmatch has no `dir/**`-matches-`dir` rule | True | **no — new capability** |
| `("app/[locale]/**","app/[locale]/page.tsx",True)` | **False (bug)** | True | **no — the headline fix** |
| `("app/[locale]/**","app/l/page.tsx",False)` | False | False | yes |
| `("docs","docs/a/b.md",True)` — via the bare-dir fallback | True (fallback suffix `/*` crosses `/` under fnmatch) | True **only if the fallback suffix becomes `/**`** | conditionally yes — see the design constraint below |
| `("README.md","README.md",True)` | True | True | yes |
| `("README.md","docs/README.md",False)` | False | False | yes |
| `("**/x.py","x.py",True)` | True | True | yes (coincidence) |

## 2. Shared State

### `_file_matches`'s bare-dir fallback suffix (`compound-v-memory.py:1061-1069`)

- Set today as: `g.rstrip("/") + "/*"` (single star), relying on fnmatch's `*` crossing `/` to mean
  "anything under `g`, any depth."
- Under `scope.matches`, `*` does **not** cross `/` (`compound-v-scope-check.py:359-361`, "single
  `*`: anything but `/`"). If the fallback suffix is not also changed to `/**`, `_file_matches("docs",
  changed="docs/a/b.md")` silently narrows from "anything under docs, any depth" to "one file
  directly inside docs" — a correctness regression the spec's own row 7 (`("docs",
  "docs/a/b.md", True)`) is designed to catch, but only if the implementer reads the spec's prose
  ("try `g`, then `g.rstrip("/") + "/**"`") and not just the current source, which still says `/*`.
- **Gap the code alone does not surface**: nothing in `_file_matches`'s current docstring or the
  function body warns that the fallback suffix itself must change. An implementer copying the
  existing two-line `if/if` structure and only swapping `fnmatch.fnmatch(...)` for `scope.matches(...)`,
  without also touching the string literal `"/*"`, produces code that passes 9 of the spec's 10 rows
  and silently fails row 7 exactly as fixture `v4` in the existing selftest (`compound-v-memory.py:1344-1348`,
  glob `"src/api"` against `"src/api/types.ts"`) would also then fail once ported.

### `recall_check`'s `file_globs` argument — where it comes from in each caller

| Caller | Value of `file_globs` | Set where |
|---|---|---|
| `cmd_recall_check` (CLI) | `args.files` | `--files` flag, `nargs="+"`, argparse (`compound-v-memory.py:1607`) — raw strings, shell-expanded **before** Python ever sees them if unquoted (documented gotcha, `skills/compound-v/memory.md:119-122`) |
| `run_recall_check` (pipeline, `compound-v-emit-workflow.py:1340-1422`) | `write_allowed` (the job's manifest lane) | `job.get("write_allowed") or []`, `compound-v-emit-workflow.py:1834` — the SAME glob list the scope gate itself enforces post-hoc |
| `--selftest` fixtures (`compound-v-memory.py:1336-1348`) | hardcoded literal lists | in-file constants |

The pipeline caller is the one that matters in production: it feeds the exact `write_allowed`
globs — the same strings `compound-v-scope-check.py`'s `is_allowed` will later test the job's real
diff against — into `_file_matches`. Any semantic gap between the two matchers is therefore a gap
between "what recall says a lane's history looks like" and "what the gate will actually enforce on
this lane" for the *same* glob string. That is precisely what the spec's "Why" paragraph asserts;
confirmed here at the call-site level, not just by reading the two docstrings side by side.

### The sibling loader is not yet written — but its two required properties are both externally testable today

1. **Must be lazy, not module-level.** `scripts/compound-v-onboard.py:6-9` does an *unconditional,
   top-of-file* `spec_from_file_location` + `exec_module` of `compound-v-memory.py`, on every
   `/v:onboard` invocation, solely to reuse `SECRET_RE`/`PEM_RE`/`file_sha` (verified: `grep
   cv_memory\.` in that file returns only those three symbols — never `recall_check` or
   `_file_matches`). If F1's scope-check loader runs at `compound-v-memory.py`'s module top level
   (mirroring `compound-v-scope-check.py`'s own top-level `_harden_sys_path()` call, or naively
   following it), **every `/v:onboard` run would pay the cost and inherit the side effects below,
   even though onboard never calls recall-check.** The loader must be invoked only from inside
   `_file_matches` (or a function it calls), on first use.
2. **Must be memoized.** `recall_check` calls `_file_matches` once per `(failure-record × changed
   file)` pair (`compound-v-memory.py:1077-1081`) — potentially many times in one process. A
   loader that re-imports and re-execs `compound-v-scope-check.py` on every call re-runs its
   module-level side effects (next item) once per comparison. Every other sibling-loader in this
   repo that is called more than once memoizes: `compound-v-postdiff-reclassify.py:186-194`
   (`_SCOPE_MOD` global), `compound-v-preeval.py:308-316` (`_MOD_CACHE` dict),
   `compound-v-fastpath-materialize.py:115-123` (`_MOD_CACHE` dict). None of these load
   `compound-v-scope-check.py` un-cached.

### `compound-v-scope-check.py`'s own module-level side effects that any importer inherits

Importing `compound-v-scope-check.py` (by any of the patterns above) is not side-effect-free —
its module body runs two things unconditionally, before any function is called:

- `_harden_sys_path()` (`compound-v-scope-check.py:169-199`, called at line 199): strips the
  script's own directory and the current working directory from `sys.path`, **in the process that
  imported it** — i.e. in `compound-v-memory.py`'s own process, not a subprocess. Documented there
  as a defence against a planted `scripts/subprocess.py` shadowing the stdlib; the mutation is
  never undone.
- `sys.dont_write_bytecode = True` (`compound-v-scope-check.py:213`), also process-wide and never
  restored.

Both are almost certainly harmless for `compound-v-memory.py` specifically (all of its own
top-level imports are stdlib and already resolved by the time any sibling load could run, and it
does no further `sys.path`-relative imports afterward) — but they are real, undocumented,
unscoped process mutations that any future caller several import-hops away (e.g. a script that
imports `compound-v-memory.py` for a reason unrelated to recall, the way `compound-v-onboard.py`
already does) inherits silently if it ever *does* reach a code path that calls `recall_check`.
Confirmed the guard that keeps this from also running `compound-v-scope-check.py`'s CLI: `main()`
is gated by `if __name__ == "__main__":` (`compound-v-scope-check.py:1195-1198`), and
`spec_from_file_location(name, path)` sets `__name__` to whatever `name` string the loader passes
— never `"__main__"` — so `main()` will not fire. Verified this is the only such guard; there is
no `atexit`, no `os.environ` mutation, no second unconditional call in the module body between
lines 199 and 213.

## 3. Sibling Code

Four existing patterns import `compound-v-scope-check.py` (or a sibling like it) by path. Read
each in full; none is a perfect match for F1's own stated requirements, and picking the wrong one
is the main design decision the plan has to make explicitly.

### 3a. `compound-v-integration-gate.py:load_scope_matcher` (lines 417-470) — the hardened pattern

This is the function the **live scope gate itself** uses to load `is_allowed` out of
`compound-v-scope-check.py` at merge-gate time. Entry conditions: called once per
`evaluate_job`/`evaluate_run` pass. What it does beyond a plain import:

- Redirects `sys.pycache_prefix` to a fresh `tempfile.mkdtemp(prefix="cv-pycache-")` **before**
  `exec_module`, specifically so a forged `scripts/__pycache__/compound-v-scope-check.<tag>.pyc`
  cannot be executed in this process instead of the real source (a hash-based `.pyc` is never
  validated against source by CPython).
- **Fails closed** if that temp directory cannot be created — does not fall back to the default
  (in-tree) cache location. The docstring explicitly records that the *first* version of this
  function silently degraded here, and that was treated as a bug and fixed.
- Restores `sys.pycache_prefix` in a `finally`, and removes the temp dir.
- Wraps the whole load in `try/except Exception` and returns `(None, "loading %s raised: %s")` on
  any failure — never raises.
- Checks `callable(getattr(module, "is_allowed", None))` before returning success — a contract
  check, not just an import-succeeded check.

Known latent gap in this pattern as written: it does **not** call `_harden_sys_path` awareness or
undo scope-check's own sys.path mutation — it inherits it same as anyone. Not a new bug F1
introduces; noted because F1's own loader will inherit the identical residue regardless of which
pattern it copies.

### 3b. `compound-v-postdiff-reclassify.py:_load_sibling` + `_scope_module` (lines 160-201) — the plain, DRY-relevant precedent

**This file already imports `compound-v-scope-check.py` by path for the same reason F1 wants to.**
Entry condition: lazy, memoized (`_SCOPE_MOD` global, `or False` sentinel so a failed load is
cached as failure rather than retried every call — a real, useful trick F1 should consider).
`_load_sibling` itself:

```python
def _load_sibling(basename, modname):
    import importlib.util
    path = os.path.join(_script_dir(), basename)
    try:
        spec = importlib.util.spec_from_file_location(modname, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001
        return None
```

Handles the missing/broken-sibling case (returns `None`, caught by the `or False` at the call
site) — this satisfies F1's "never a silent crash" requirement structurally. **What it does NOT
do, unlike §3a**: no `sys.pycache_prefix` redirection, so a forged `.pyc` beside
`compound-v-scope-check.py` in `scripts/__pycache__/` would be loaded here instead of source. This
is a **latent bug in an existing sibling**, not a new one F1 would introduce by copying it — flagged
per the audit's own instruction to call out latent bugs in siblings rather than silently inherit
them. Whether F1's plan accepts this gap (recall-check is advisory, "conservative-only... never
reroutes to a lower-trust backend," per `recall_check`'s own docstring) or closes it (mirror §3a
instead) is a decision the plan must make explicitly, not by default.

### 3c. `compound-v-discover-models.py`'s selftest (lines 229-234) — the pattern the spec text names

The spec's own prose says: "the pattern `compound-v-discover-models.py`'s selftest uses." Read in
full:

```python
import importlib.util
rp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compound-v-resolve-model.py")
spec = importlib.util.spec_from_file_location("cv_resolve", rp)
rmod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rmod)
```

**This is the least defended of the four patterns** — no `try/except` at all, no memoization (it
runs once, inline, inside a selftest, where a raise is an acceptable, visible test failure). Taken
literally as "the pattern to use," it would violate the spec's own requirement two paragraphs later
("If the sibling cannot be loaded, `recall-check` reports `verdict: unavailable`... never a silent
`none`" — which implies never a silent *crash* either, given the AC requires `exit 0`). Read
charitably, the spec is naming this only as the *path-resolution idiom* (`os.path.dirname(os.path.abspath(__file__))`
+ `spec_from_file_location` + `module_from_spec` + `exec_module`), not as the *error-handling*
contract — but the text does not say that, and an implementer who follows it literally produces
code that fails the acceptance criteria's last row (`recall-check --files 'app/[locale]/**' --json`
exits 0) the moment the sibling is unreadable. **This ambiguity is a design constraint, not a
nitpick** — see §7.

### 3d. Fully unguarded siblings elsewhere (for contrast, not for reuse)

`compound-v-triage-outcomes.py:_load_sibling` (160-166) and `compound-v-preeval.py:_load_sibling`
(308-316) are both bare — no `try/except` in the function itself, and several of their own callers
(`_update_memory()` at triage-outcomes.py:179-183, `_preeval()` at preeval.py:319-320) call them
with no surrounding `try/except` either. This is the exact shape the stale-but-relevant archaeology
citation in §0 warns about ("raises (unhandled)"). Confirmed live: `compound-v-update-memory.py`
still exists today, so this particular unguarded path has not yet been exercised by a real
deletion — but the pattern itself is present, uncorrected, in this codebase right now, in two
files. F1 must not add a third.

## 4. External APIs

None. This feature touches no third-party library, SDK, or network API — it is a pure in-repo
delegation from one stdlib-only script to another. Context7 was not invoked; there is nothing for
it to verify.

## 5. Regression Surface

| Path that works today | Breaks if F1 lands wrong | Who notices |
|---|---|---|
| `run_recall_check` (`compound-v-emit-workflow.py:1340-1422`), called once per `type: implement` job at emit time, `job.get("write_allowed")` as globs | If the new matcher under- or over-matches relative to the *intended* (scope-gate) semantics, `memory.auto_tighten` jobs get the wrong tier — a job with a real repeat-failure history on `app/[locale]/**` still gets `light` (today's actual bug, live-reproduced in §1); after a bad fix, a job with NO real history could get wrongly tightened instead | Silent either way — no test exercises this at the manifest level today; only `compound-v-emit-workflow.py`'s own selftest fixtures (`_rk_impl.get("verdict") == "tighten"`, lines 8230-8233) would catch a *behavioral* regression, and only for the specific glob shapes those fixtures already use |
| `run_recall_check`'s own subprocess-crash handling (`compound-v-emit-workflow.py:1340-1422`, tested at 8307-8332) | **Unaffected by F1 either way** — it already converts any nonzero exit / bad JSON / timeout from the `recall-check` subprocess into `verdict: unavailable` with the rc and stderr recorded (verified: `_rk_err["verdict"] == "unavailable" and "rc=3" in _rk_err["note"]`, line 8319). This is a separate, already-hardened safety net one layer above whatever F1's in-process loader does. | N/A — flagged so the plan does not spend effort re-solving a problem this caller already solves |
| `RECALL_REVIEW_CLAUSE` (`compound-v-emit-workflow.py:1321-1328`) — a **review agent is told to run `recall-check` directly via the CLI itself**, not through `run_recall_check`'s subprocess wrapper | If F1's in-process sibling loader raises instead of degrading, this is the path most exposed: the agent gets a raw Python traceback on stderr instead of a JSON verdict to quote, and the acceptance criterion "quote its verdict and match_count" cannot be satisfied | The review agent, mid-review, on a live run — not caught by any automated test today |
| `hooks/*` clamp entries (`compound-v-emit-workflow.py:1011-1014`) admitting `Bash(... compound-v-memory.py recall-check:*)` and `search:*` | Unaffected — the clamp only cares about the command line shape, not the matcher inside | N/A |
| `--selftest`'s existing `recall_check(...)` fixtures (`compound-v-memory.py:1326-1348`), specifically `v4`'s bare-dir case (`"src/api"` vs `"src/api/types.ts"` / `"src/api2/x.ts"`) | If the fallback suffix is left as `/*` instead of becoming `/**` (see §2), this exact existing assertion (`match_count == 2`) still happens to pass for THIS fixture (both files are exactly one level under the dir), which means **the existing selftest will not catch the fallback-suffix regression** — only the NEW parity rows the spec requires (row 7, `("docs","docs/a/b.md",True)`, two levels deep) would | Nobody, until a real lane like `"docs/**"` used as a bare `"docs"` glob needs to match something two-plus levels deep in production |
| `compound-v-scope-check.py --selftest` (untouched by F1) | Only breaks if F1's implementer edits this file despite the spec's "No other file" — worth stating as an explicit non-goal since §3a-3d all live partly inside files this feature is not allowed to touch | CI / the AC's own second bullet |
| `scripts/compound-v-onboard.py`'s reuse of `compound-v-memory.py`'s `SECRET_RE`/`PEM_RE`/`file_sha` (lines 6-9) | Breaks only if F1 changes anything about `compound-v-memory.py`'s module-level exports or makes the module fail to import cleanly (e.g. an eager, non-lazy sibling load that itself throws) — every `/v:onboard` run would then break, not just recall-check | Every `/v:onboard` invocation, immediately, on an unrelated command |

## 6. DRY Findings

**A near-duplicate already exists.** `compound-v-postdiff-reclassify.py:160-201` already contains a
lazy, memoized, exception-swallowing loader for exactly `compound-v-scope-check.py`, built for the
same purpose (comparing a changed path against a glob using the gate's own semantics —
`_path_matches` at line 204 immediately below it, not shown in full here but present in the same
file). This is not identical code the plan can literally import (it is private to that module,
`_script_dir()`/`_load_sibling` are not exported, and the file has no `if __name__` guard making it
safe to import as a library either way), but it is the same *shape* of solution solved twice
independently already in this repo, plus the two unguarded variants in §3d, plus the hardened one
in §3a. That is **four** existing sibling-loader implementations before F1 adds a fifth. The spec
does not ask the plan to refactor these into one shared helper (F1's own "Files" section scopes it
to `compound-v-memory.py` only), so the decision to add a fifth rather than extract a shared
`_load_sibling`-with-pycache-protection helper is implicitly made by the spec's own file scope —
worth the plan stating that choice out loud (extend/refactor/third, per this audit's own
instructions) rather than leaving it implicit.

## 7. Design constraints for the spec

Non-negotiable, derived from the above:

1. **The bare-dir fallback suffix must change from `/*` to `/**`,** not just the matcher call. The
   spec's prose already says this ("try `g`, then `g.rstrip("/") + "/**"`") but the current source
   at `compound-v-memory.py:1067` reads `g.rstrip("/") + "/*"` — an implementer working from the
   diff alone, without re-reading the spec's prose closely, will plausibly leave the suffix
   unchanged and pass 9 of 10 required rows while silently narrowing "anything under this dir" to
   "one level under this dir." Row 7 of the parity table (`("docs", "docs/a/b.md", True)`) is the
   only thing that catches this — it must actually be added, not skipped as "obviously covered."

2. **The sibling loader must be invoked lazily — first call inside `_file_matches` (or a helper it
   calls), never at `compound-v-memory.py`'s module top level.** `compound-v-onboard.py:6-9`
   already imports `compound-v-memory.py` unconditionally on every `/v:onboard` run for unrelated
   symbols (`SECRET_RE`, `PEM_RE`, `file_sha`) and never touches `recall_check`. An eager,
   module-level scope-check import would tax every onboard run with a cost and a set of process
   mutations (§2) it has no reason to pay.

3. **The sibling loader must be memoized** (module-level cache, load-once-per-process, cache
   failure too) — `recall_check` calls `_file_matches` once per `(failure-record × changed file)`
   pair, potentially many times per CLI invocation; re-importing and re-`exec_module`-ing
   `compound-v-scope-check.py` on every comparison repeats its module-level side effects (§2) once
   per pair instead of once per process. Every comparable existing loader in this repo (§3b, and
   `compound-v-preeval.py`, `compound-v-fastpath-materialize.py`) memoizes; F1 should not be the
   exception.

4. **Pick one of the four existing sibling-loader shapes explicitly, and say which, and why** —
   don't silently synthesize a fifth. The two live options that actually satisfy "never a silent
   crash" are §3a (`load_scope_matcher`'s hardened pycache-redirect pattern — closes the
   forged-`.pyc` gap but is the most code to port) and §3b (`compound-v-postdiff-reclassify.py`'s
   plain memoized `try/except` — matches the spec's own "any load failure ⇒ fail-closed" framing
   used elsewhere in this repo, but inherits the un-defended-`.pyc` gap). The pattern the spec's
   prose literally names (§3c, `compound-v-discover-models.py`'s selftest) has **no error handling
   at all** and, read literally, would violate the spec's own "never a silent crash" requirement —
   the plan must not follow it verbatim for the load itself, only for the path-resolution idiom
   (`os.path.dirname(os.path.abspath(__file__))` + `spec_from_file_location`).

5. **Wrap the load in `try/except` covering `spec_from_file_location`, `module_from_spec`, AND
   `exec_module` together** — not just a `spec is None` check. A missing target file does not make
   `spec_from_file_location` return `None`; the `FileNotFoundError` only surfaces when
   `exec_module` tries to read the source (this is why the WS3b-era citation in §0 describes an
   *unhandled raise*, not a caught "spec is None" branch, from a functionally identical call
   shape). After a successful load, also check `callable(getattr(module, "matches", None))` before
   trusting it (mirrors `load_scope_matcher`'s `is_allowed` check, §3a) — a sibling that loads but
   has silently lost the `matches` function (e.g. renamed) must also degrade to `unavailable`, not
   raise an `AttributeError` at first use.

6. **`verdict: unavailable` must be reachable from the CLI with exit 0**, per the spec's own
   acceptance criterion. This is stricter than what any of §3a-3d's patterns guarantee by
   themselves (they hand back `None`/an error string; something in `cmd_recall_check` or
   `recall_check` itself must turn that into the same well-formed JSON shape `recall_check`
   already returns for `none`/`tighten`, not a Python exception surfacing at `main()`).

7. **Remove the `fnmatch` import** (`compound-v-memory.py:32`) once `_file_matches` no longer calls
   it. Verified nothing else in the file references `fnmatch` (only the import line plus the two
   call sites being replaced) — the spec's instruction to remove it is correct and complete, not
   just a nice-to-have.

8. **Do not touch `compound-v-scope-check.py`**, including its `--selftest` (AC bullet 2) — every
   pattern read in §3 lives partly inside files this feature is not scoped to modify; the plan
   must import from it, never edit it, even to "fix" the un-pycache-defended gap noted in §3b/§6.

## 8. File Touch Map

| File | Change | Notes |
|---|---|---|
| `scripts/compound-v-memory.py` | Modified: `_file_matches`, new sibling-loader function, `--selftest` (new ≥8-row parity table + keep existing `recall_check` fixtures passing), remove `import fnmatch` | Not a generated file, not a lockfile, not a schema dump, not a migration/route registry, not a barrel/index file — does **not** meet this repo's stated SHARED-RESOURCE criteria. Worth a footnote anyway: `scripts/compound-v-onboard.py:6-9` imports it unconditionally by path for unrelated symbols on every `/v:onboard` run (see constraint 2) — a syntax error or import-time exception introduced here breaks onboarding too, not just recall-check. Single job in this run per the epic brief, so no partition-conflict risk within F1 itself. |
| `scripts/compound-v-scope-check.py` | **Not touched.** Read-only dependency; `matches`/`glob_to_regex`/`is_allowed` are imported by path, never edited. Its own `--selftest` (lines ~640-683 for the `matches()` table) must keep passing unmodified, per AC. | Do not flag as touched; listed here only so the loader's target path is explicit. |
| `skills/compound-v/memory.md`, `skills/compound-v/execution-manifest.md` | **Not touched by F1** — explicitly F2 `matcher-docs`' scope (depends_on F1 per the epic brief). `memory.md:81-122` already documents `recall-check` as a subprocess call at emit time; it does not yet describe the matcher's own semantics, which is exactly what F2 adds. | Named for completeness; F1's spec's own "no other file" line already excludes these. |
