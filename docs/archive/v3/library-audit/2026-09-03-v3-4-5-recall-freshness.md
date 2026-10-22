# Library & Documentation Audit — v3.4.5 recall-that-is-fresh-by-construction

**Spec:** `docs/superpowers/specs/2026-09-03-v3.4.5-recall-freshness-design.md`
**Topic slug:** `v3-4-5-recall-freshness`
**Date:** 2026-09-03 · **Phase:** 1C (library/doc currency only — not code archaeology, not domain/regulatory)

## 0. V-memory recall (Step 0)

Three `compound-v-memory.py search` calls ran before opening any file (`--intent planning --top 6-8`):
`"recall freshness FTS5 staleness index refresh"`, `"fastembed onnxruntime tokenizers dense embeddings venv"`, `"SQLite FTS5 python stdlib version"`. A fourth (`"recall-check … dispatcher … Step 0"`) located prior Phase 1C dogfood runs on this same script family.

Every call printed **`V-memory: index is 2 new / 0 removed docs behind the repo — run /v:memory-refresh`**. This is the exact defect this spec is designed to close, reproduced live, on this run, against this repository — the recall CLI itself is 2 documents stale and told me so instead of silently returning an incomplete result. Treated as evidence, not fixed here.

Relevant recalled evidence:
- `docs/superpowers/adr/0001-fts5-not-vector-db.md` — the standing decision that CORE recall is SQLite FTS5, pure stdlib, always on; DENSE embeddings are opt-in and never a requirement. This spec touches only the CORE lane, consistent with the ADR.
- `docs/superpowers/library-audit/_knowledge-base/agent-instruction-tooling.md` (2026-06-30 entry) — already on record that the DENSE lane uses **direct onnxruntime**, not `fastembed`, and that `/v:onboard` adds zero new embedding deps. This spec's decision explicitly keeps the dense lane untouched ("A search on a repository with no index... The dense lane is never touched by a search"), so that KB entry is consistent, not contradicted, and is not re-litigated here.
- `docs/superpowers/library-audit/_knowledge-base/python-tooling.md` (2026-09-03, F2 entry) — records the project's own documented floor: *"Stock macOS = bash 3.2.57 / python 3.9.6 ... All helper scripts target bash 3.2 + py 3.9, stdlib only."* Directly relevant to this spec's `--selftest` acceptance criterion (§7 below).
- `docs/superpowers/specs/2026-06-27-v-memory-prd.md` §3 Invariants — "index only git-tracked files," "cache outside the repo" — unaffected by this spec; the inline-refresh change reuses the existing `refresh` machinery under those same invariants.

No recalled document contradicts the spec's decision. No stale claim found in what came back.

## 1. Tools Available

- **Context7 MCP: ❌ NOT AVAILABLE this session.** `ToolSearch` for `context7`, `resolve-library-id`/`query-docs` (both the plugin-bundled `mcp__plugin_*_context7__*` and the plain `mcp__context7__*` forms), and a broad `mcp` sweep returned no matching tool. **DEGRADED: WebSearch + WebFetch-only for this audit.** All library/version claims below are WebSearch-sourced or WebFetch'd directly from `docs.python.org`, with URLs cited.
- **Dependency manifests found: NONE.** `Glob` for `**/requirements*.txt`, `**/pyproject.toml`, `package.json` at repo root returned zero matches — confirmed by direct search, not assumed. This is expected and correct: the repo's own documented policy (`python-tooling.md`) is "stdlib only, pyyaml optional with fallback" for helper scripts, and this spec's own file list (`scripts/compound-v-memory.py`, `skills/compound-v/memory.md`, `commands/v-remember.md`, `CHANGELOG.md`) introduces no new package.
- **Trigger 0 recon doc:** none exists for this topic. `Glob` for `docs/superpowers/recon/*recall*`, `*memory*`, `*v3.4.5*` — zero matches. Fallback scan also empty. Nothing to revalidate against; noted, not treated as a gap requiring escalation (the spec's own probe *is* the recon here — it already found and reproduced the defect live, per §0 above).

## 2. Libraries Mentioned

The spec introduces **zero new third-party libraries**. Its full dependency surface is the Python standard library, already in use by the file it edits. Table reflects what a library-currency check actually applies to here: the interpreter floor and the one stdlib module (`sqlite3`) whose transaction-control API this spec's new code path exercises.

| Name | Spec context | Current stable | Repo-targeted floor | Last release | Maintenance | Status |
|---|---|---|---|---|---|---|
| CPython (language/runtime) | every touched file (`scripts/compound-v-memory.py` shebang `#!/usr/bin/env python3`) | **3.14.7** (2026-08-05); 3.15.0rc2 cut 2026-09-01, GA expected Oct 2026 | **3.9** — hard-pinned in `.github/workflows/validate.yml:283,346` (`actions/setup-python@v5`, `python-version: '3.9'`) for exactly the selftest sweep this spec's AC #2 depends on | 3.9.25 (2025-10-14) — **final** release | frozen, no further releases | 🟠 HIGH (see §5) |
| `sqlite3` (stdlib, FTS5 lane) | the whole spec — inline refresh before recall, extending `index_staleness`, reusing `_persist_chunks`'s `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` | current docs at docs.python.org/3 (checked against 3.12–3.14 semantics) | same interpreter as above | n/a (stdlib, ships with CPython) | active, PEP-249 migration ongoing | 🟡 see §6 (forward-compat note, not a version-drift bug) |
| `fcntl` (stdlib, refresh lock) | spec's "if the refresh lock is held... it never waits" — this is the *existing* `acquire_lock`/`release_lock` behavior (`fcntl.flock(fd, LOCK_EX\|LOCK_NB)`), not new code | n/a (stdlib, POSIX) | same | n/a | stable, unchanged API for years | 🟢 OK — no signature drift; POSIX-only is a pre-existing constraint, not introduced here |
| `argparse` (stdlib, `--no-refresh` flag) | spec's opt-out flag | n/a (stdlib) | same | n/a | stable | 🟢 OK |

## 3. API Signatures Verified

| Call | Where it's used / extended | Verified against | Result |
|---|---|---|---|
| `sqlite3.Connection.execute("BEGIN IMMEDIATE")` + explicit `COMMIT`/`ROLLBACK` (`_persist_chunks`, `scripts/compound-v-memory.py:639,657,659`) | The shared refresh helper this spec extracts from `cmd_refresh` calls this same persistence path from `cmd_search` | `docs.python.org/3/library/sqlite3.html#sqlite3.Connection.autocommit`, fetched live 2026-09-03 | **Still current, no signature drift.** Confirmed live: `Connection.autocommit` defaults to `sqlite3.LEGACY_TRANSACTION_CONTROL` in every currently-shipping Python (3.12 through 3.14 dev). Under that default, `isolation_level` governs implicit-transaction behavior and explicit `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` statements work exactly as this code already relies on. No change needed for the new call site. |
| `sqlite3.connect(path, timeout=30)` (`scripts/compound-v-memory.py:405`) | Opens the shared connection the new inline-refresh path also opens (or reuses) | same doc page, `sqlite3.connect` signature | 🟢 unchanged across 3.9–3.14; `timeout` is a busy-timeout in seconds, no deprecation |
| `fcntl.flock(fd, fcntl.LOCK_EX \| fcntl.LOCK_NB)` (`acquire_lock`, line 617) | Spec: *"If the refresh lock is held ... it never waits"* — this is already what `LOCK_NB` does (raises `OSError` immediately on contention, caught and returned as `None`) | Python stdlib docs (unchanged for years; no version-specific check warranted — flagged only to confirm the spec is describing existing, not new, behavior) | 🟢 no new call needed; spec's requirement is already satisfied by the existing function signature |
| `argparse.ArgumentParser.add_argument("--no-refresh", action="store_true")` | New CLI flag | stdlib, unchanged | 🟢 OK, no drift |

**Signature not to introduce:** `sqlite3.connect(path, autocommit=False)` — the `autocommit` keyword argument does not exist before **Python 3.12** (confirmed live via the fetched doc page: *"It is suggested to set autocommit to False, which implies PEP 249-compliant transaction control. This is the recommended value of autocommit"* — but only reachable on 3.12+). Passing it under the repo's Python-3.9 floor raises `TypeError: 'autocommit' is an invalid keyword argument for this function`. See §7.

## 4. Critical Findings 🔴

None. No deprecated, archived, or 24+-month-dead library is in play — there is no third-party library in play at all.

## 5. High-Priority Findings 🟠

### 🟠-1 — The CI floor this spec's own acceptance criteria run under (Python 3.9) is upstream end-of-life and permanently frozen at 3.9.25.

- **What:** `.github/workflows/validate.yml:280-283` and `:343-346` pin `actions/setup-python@v5` to `python-version: '3.9'` for exactly the job that will run `python3 scripts/compound-v-memory.py --selftest` (spec AC #2) — the dynamic `scripts/*.py` selftest sweep at lines 298-312 globs every script with a `--selftest` string, which includes `compound-v-memory.py`.
- **Live-verified (WebSearch, 2026-09-03):** Python 3.9 reached end-of-life on **2025-10-31**; **3.9.25** was the final release. No further security patches will ever be issued for this line. (Sources: python.org release notes for 3.9.25; endoflife.date/python; Red Hat Developer, 2025-12-04.)
- **Is this a bug introduced by the spec? No.** It's the project's own long-standing, documented choice (`docs/superpowers/library-audit/_knowledge-base/python-tooling.md`, F2 entry, quoting `2026-06-26-compound-v-orchestrator-v1-plan.md`: *"Stock macOS = bash 3.2.57 / python 3.9.6 ... All helper scripts target bash 3.2 + py 3.9"*) — it exists because macOS ships Python 3.9.6 as its system interpreter, and this project's hooks/scripts must run there without setup. This spec neither widens nor narrows that floor.
- **Why it's still worth flagging here, not just noted:** this spec's new code (the shared inline-refresh helper, the extended `index_staleness`) will be written and tested against exactly this frozen floor. Any implementer instinct to "modernize" the touched functions — e.g., reaching for a 3.10+ `match` statement, 3.11+ `tomllib`, or (concretely, see §6) the 3.12+ `sqlite3` `autocommit` kwarg — will pass locally on a newer interpreter and then fail CI's 3.9 selftest job or, worse, fail silently on a contributor's un-updated macOS system Python outside CI.
- **Alternative / mitigation (since "swap the library" doesn't apply to a language floor):** no upstream security-patch path exists for 3.9 any more — `actions/setup-python@v5` will keep resolving `'3.9'` to the same frozen 3.9.25 build indefinitely, which is actually a *stability* property CI can rely on (no future patch-level drift risk), not a live risk of an unpatched-CVE regression appearing under this pin. The only real forward option, if the project ever revisits the floor itself, is bumping to 3.10 (still supported, actively patched) or later — but that is a standalone decision with its own blast radius (every hook/script, not just this spec) and is explicitly **out of scope** for a fix-per-cycle change. Recorded as an open item, not a blocker (§8).

## 6. Medium Findings 🟡

### 🟡-1 — `sqlite3`'s transaction-control default is mid-migration upstream; don't let this spec's refactor reach for the newer, incompatible form.

- **What:** Live-fetched from `docs.python.org/3/library/sqlite3.html` (2026-09-03): `Connection.autocommit` currently defaults to `sqlite3.LEGACY_TRANSACTION_CONTROL` (the mode this codebase already relies on), but *"the default will change to `False` in a future Python release"* — Python's own docs recommend migrating call sites to `sqlite3.connect(path, autocommit=False)` plus a PEP-249-compliant transaction style.
- **Why it matters for this spec specifically, not just in general:** the spec's own file list has the implementer opening and editing `_persist_chunks`'s neighborhood — extracting a "shared helper... from `cmd_refresh`" that the new `cmd_search` path also calls. That's precisely the kind of touch where a well-intentioned "modernize while I'm in here" edit could add `autocommit=False` to `open_db_checked`'s `sqlite3.connect()` call. That keyword **does not exist before Python 3.12** and would break the repo's Python-3.9 CI floor (§5) outright — `TypeError` on `import`/connect, not a subtle bug.
- **This is not a live vulnerability or urgent migration** — `LEGACY_TRANSACTION_CONTROL` remains the *current* default in every shipping Python through 3.14, with no removal date announced. It's a forward-compat trap specific to touching this file right now, not a stale-dependency problem.
- **No alternative needed** — the fix is "don't do it," captured as a MUST NOT in §7.

## 7. Design Constraints for the Plan (MUST / MUST NOT)

- **MUST** keep the new shared refresh helper (extracted from `cmd_refresh`, called from `cmd_search`) and the extended `index_staleness` pure-stdlib — no new import beyond what `scripts/compound-v-memory.py` already uses (`argparse, fcntl, fnmatch, hashlib, json, os, re, sqlite3, subprocess, sys, tempfile, time`). No manifest file exists to add a dependency to, and none should be created for this feature (§1).
- **MUST** keep all new/changed code Python-3.9-compatible, because `.github/workflows/validate.yml`'s selftest sweep (lines 280-312) runs `compound-v-memory.py --selftest` under a hard-pinned `python-version: '3.9'`, and that pin now resolves to a permanently-frozen, upstream-EOL 3.9.25 (§5) — there is no forward patch cushion if a 3.10+-only construct slips in and happens to work on a contributor's newer local interpreter.
- **MUST NOT** add `autocommit=` to `sqlite3.connect()` (or otherwise adopt PEP-249-compliant transaction mode) anywhere the shared helper touches — the keyword requires Python 3.12+ and would break the 3.9 floor; keep the existing `LEGACY_TRANSACTION_CONTROL`-implicit pattern (`BEGIN IMMEDIATE` / explicit `COMMIT`/`ROLLBACK`) that `_persist_chunks` already uses and that the inline-refresh path will inherit (§3, §6).
- **MUST** reuse the existing `acquire_lock`/`release_lock` (`fcntl.flock(..., LOCK_EX | LOCK_NB)`) for the spec's "proceed against the stale index, never wait" requirement when a refresh is already running — that is already this function's exact behavior; do not add a second lock mechanism, a timeout-based wait, or any third-party file-locking library (§3).
- **MUST NOT** touch the dense/embeddings lane's dependency surface (`onnxruntime`, `tokenizers`, `huggingface_hub`, `numpy`) — the spec correctly scopes the inline refresh to FTS5-only and this audit found nothing in the dense lane's own currency (already covered by the 2026-06-30 KB entry) that this spec needs to react to.

## 8. Open Questions for the Human

1. **Not this spec's problem, but adjacent and now overdue:** the Python-3.9 CI floor (§5) is not just "old" — it is *frozen forever* (upstream will never release 3.9.26). Is there an appetite for a standalone future ticket to move the floor to 3.10+ (still patched) on the CI side, independent of macOS's local system Python constraint? Flagging per the standing "fix per cycle, no over-engineering" directive — explicitly **not** recommending it be folded into v3.4.5.
2. No open questions block v3.4.5 itself. The spec introduces no new library, and every stdlib call surface it touches was verified live against current docs with no signature drift.

## 9. Knowledge Base Updates

Appended one dated section to `docs/superpowers/library-audit/_knowledge-base/python-tooling.md` (no prior claim struck through — new information, not a correction): the live-confirmed `sqlite3.Connection.autocommit` / `LEGACY_TRANSACTION_CONTROL` default and forward-migration note, cross-referenced to the existing Python-3.9-floor entry (F2, 2026-09-03) already in that file, plus the live-confirmed Python 3.9 EOL date (2025-10-31, final release 3.9.25) for future Phase 1C passes to cite without re-searching.

No new topic-slug KB file created — this spec's library surface (stdlib `sqlite3`/`fcntl`) belongs in the existing `python-tooling.md` bucket, not a new `v-memory`-specific file; the V-memory-specific prior art (dense-lane onnxruntime-not-fastembed) already lives in `agent-instruction-tooling.md` and needed no update (nothing in this spec contradicts or extends it).
