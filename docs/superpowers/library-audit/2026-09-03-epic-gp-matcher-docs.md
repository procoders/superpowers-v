# Compound V — Phase 1C Library & Documentation Audit

**Spec audited:** `docs/superpowers/execution/epics/2026-09-03-glob-parity/specs/matcher-docs.md`
(F2 `matcher-docs`), including its 2026-09-03 orchestrator amendment.
**Topic slug:** `epic-gp-matcher-docs`

## 0. V-memory recall (Step 0)

Four `compound-v-memory.py search` calls, run before opening any project file, with
different phrasings (the feature's own words, the sibling F1 feature it depends on, the
subsystem, and the failure class I most expected — a doc claim that has drifted from the
code F1 already shipped): `"glob matcher documentation"`, `"glob-parity recon fnmatch
scope-check"`, `"matcher docs write_allowed glob semantics"`, `"200 characters line length
markdown lint"`. One call self-refreshed 1 stale doc, another 2, before answering — both
noted, neither treated as an open item.

Load-bearing hits, each independently re-verified live rather than trusted as-is (findings
below cite the live re-verification, not the recall text):

- `docs/superpowers/execution/epics/2026-09-03-glob-parity/specs/matcher-docs.md` itself —
  expected, it's the document under audit, including its orchestrator amendment.
- `docs/superpowers/library-audit/2026-09-03-epic-gp-one-matcher.md` — the sibling F1
  Phase-1C audit. F1 (code: `_file_matches` in `compound-v-memory.py` stops using
  `fnmatch`, delegates to the scope gate's hardened matcher) has **already merged**
  (`docs/superpowers/dogfood/2026-09-03-epic-gp-one-matcher-review-1.md` records the
  reviewed diff `4bc979a`). F2 documents a fact that is now true in the shipped code, not a
  fact still in flight — re-confirmed directly against the live tree in §2-§3 below, not
  taken on the recall text's word.
- `docs/superpowers/plans/2026-09-03-epic-gp-matcher-docs.md` — the implementation plan
  already written for F2. Its Task A anchors and six-rule phrasing were cross-checked
  against live source in §3, not assumed correct because a plan already states them.
- `docs/superpowers/library-audit/_knowledge-base/python-tooling.md` — an existing,
  directly relevant entry: `scripts/lint-frontmatter.py` does a hard `import yaml` with no
  stdlib fallback, contradicting this repo's own "stdlib-only, pyyaml optional" promise.
  Cited, not re-derived, in §6 — it bears directly on this spec's own acceptance criteria.

No Trigger-0 recon doc exists for this topic: `Glob` for `docs/superpowers/recon/*glob*`
returned no files (same result the F1 audit recorded). Consistent with the epic brief
framing this as a small, two-feature "stage 7" exercise, not a recon-gated topic.

## 1. Tools Available

- **Context7 MCP: not attached to this subagent** — `ToolSearch("context7
  resolve-library-id query-docs")` returned no matching deferred tools. **DEGRADED:
  WebSearch-only.** This costs nothing here: the spec touches **zero libraries, zero
  APIs, zero code** — it edits the wording of two already-existing Markdown sections to
  agree with each other and with code F1 already shipped. There is no third-party surface
  for Context7 or WebSearch to check currency against.
- **Manifests found: none.** `Glob` for `package.json` / `pnpm-lock.yaml` / `yarn.lock` /
  `requirements.txt` / `pyproject.toml` / `Cargo.toml` / `go.mod` / `Gemfile` /
  `composer.json` at repo root — zero matches, 2026-09-03. Matches this repo's repeatedly
  reconfirmed convention (stdlib-only Python, no dependency manifest of any kind).
- **Bash: clamped** to only `compound-v-memory.py search`/`recall-check` invocations for
  this spawn (`bashCommandClamp`). All other inspection below used `Read`/`Grep`/`Glob`
  directly against the live tree at current `HEAD`, not against recalled or remembered text.

## 2. Libraries Mentioned

**None.** This spec's two target files (`skills/compound-v/memory.md`,
`skills/compound-v/execution-manifest.md`) name no third-party library, SDK, framework,
runtime, or external API anywhere in the sections F2 touches or in the surrounding text I
read in full for both files. The only "libraries" in scope, per this project's own
established Phase 1C convention of scrutinizing first-party contracts the same way as
external ones when no external dependency exists, are:

| Surface | Spec context | Current state (live-checked 2026-09-03) | Status |
|---|---|---|---|
| `scripts/compound-v-scope-check.py` `glob_to_regex`/`matches`/`is_allowed` | The "one matcher" both docs must describe identically | Live `Read`, `:317-388`. Docstring + implementation confirmed to implement exactly the six rules the spec's Goal paragraph states (§3). Actively maintained (this exact epic touched it days ago). | 🟢 current, no drift |
| `scripts/compound-v-memory.py` `_file_matches`/`_scope_matches` | F1's already-merged delegation; F2 documents its behavior | Live `Read`, `:1060-1125`. Confirms the bare-path-recursive addendum and the hardened-load pattern F1's own audit (🟠-1) required are both shipped. | 🟢 current, no drift |
| PyYAML (transitive, via `scripts/lint-frontmatter.py`, one of F2's own AC checks) | Not named by the spec, but AC #3 runs a script that hard-imports it | 🟢 PyYAML itself current/healthy (6.0.3, "Sustainable" — per the existing KB entry, not re-derived). The risk is **availability under `/usr/bin/python3`**, not currency — see §6. | 🟢 library OK; 🟡 environment risk on the AC command (§6) |

No `requirements.txt`/`pyproject.toml` pins PyYAML's version anywhere in this repo (§1) —
CI installs it unpinned (`pip install pyyaml`) per the existing KB entry.

## 3. API / Signature Verification

Every claim below is the spec's or the amendment's own wording, checked against the
current shipped code — not against the plan, not against the recall text.

| Claim (spec / amendment) | Verified against | Result |
|---|---|---|
| `*` matches within one path segment, `**` matches across segments, `dir/**` also matches `dir`, `?` matches one non-`/` character, `[`/`]` are literal, the whole pattern is anchored to the full repo-relative path | Live `Read`, `scripts/compound-v-scope-check.py:317-382` (`glob_to_regex`/`matches`) | **MATCH.** Docstring (`:317-324`) states the same six rules verbatim in spirit; implementation confirms each: `*` emits `[^/]*` (`:361`), `**` emits `.*`/collapses `dir/**`→`(?:/.*)?` (`:339-357`), `?` emits `[^/]` (`:364-367`), `[`/`]` fall through to `re.escape` on purpose (`:368-372`, comment explicitly rejects fnmatch-style character classes for this exact reason — App-Router segments), and the regex is wrapped `(?s:…)\Z` with `re.match` — fully anchored (`:330,374,381`). |
| `recall-check` "adds" that a bare path with no wildcard means "this path or anything under it" | Live `Read`, `scripts/compound-v-memory.py:1115-1125` (`_file_matches`) vs. `scripts/compound-v-scope-check.py:378-388` (`matches`/`is_allowed`) | **MATCH, and correctly scoped.** The bare-path-recursive reading exists **only** in `_file_matches`'s own loop (`:1123`, `g.rstrip("/") + "/**"`) — `scope-check.py`'s `matches`/`is_allowed` have no such special-casing. The spec's word "adds" is accurate: `write_allowed`/`read_allowed` (governed directly by `scope-check.py`) do **not** get this bonus; a bare `dir` entry there matches only the literal string `dir`, never its contents, unless written as `dir/**`. Documenting this backwards — implying `write_allowed` also treats a bare path as recursive — would misstate an **enforced** scope boundary. |
| "the parity rows in `compound-v-memory.py --selftest`" is the proof both files can point to | Live `Grep`, `scripts/compound-v-memory.py:1632-1642` | **MATCH.** A `parity` fixture list exists, tagged `# glob parity with the scope gate (epic 2026-09-03-glob-parity F1): one matcher, two callers.` (`:1632`), asserted in a loop (`:1641-1642`). Confirmed passing post-merge: `docs/superpowers/dogfood/2026-09-03-epic-gp-one-matcher-review-1.md` records all rows `ok`, including a `bare dir == dir/**` case. |
| Amendment: `execution-manifest.md` never states glob semantics today; the note lands "directly under the `write_allowed`/`read_allowed` rows... near line 54" | Live `Read`, `skills/compound-v/execution-manifest.md:53-54` | **MATCH.** Both rows exist exactly there today (`write_allowed` line 53, `read_allowed` line 54), and neither row nor any surrounding text in the file states the six-rule contract — confirmed via full-file read, not just the two `Grep` hits at those lines. Every other `glob`-mentioning line in the file (`:30,190,224,231,337,510,521,524,530,531`) refers to *using* a glob, never *defining* its semantics. |
| Amendment: `memory.md`'s `recall-check` row (spec says "line 54") is the one to replace | Live `Read` + `Grep`, `skills/compound-v/memory.md:54` | **MATCH.** Line 54 is exactly the `recall-check --files <glob>…` CLI-table row, and it currently states only the verdict contract (`deterministic recurring-failure → tighten/none verdict`) — no glob semantics, nothing to strike beyond that one cell. |
| Spec AC: `grep -n fnmatch skills/compound-v/memory.md skills/compound-v/execution-manifest.md` finds nothing | Live `Grep -i 'fnmatch\|glob'` over both files | The literal string `fnmatch` does not appear in **either** file today — the AC is **vacuously true before any edit is made**. See §7/§8: this AC guards against *reintroducing* the word, it does not by itself prove the new six-rule text was actually added. |
| Spec AC: the dead-link check passes | Live `Read`, `.github/workflows/validate.yml:232-264` | **MATCH, gate is real and live.** A repo-wide dead-link scan runs as the final CI step, resolving every `[text](path)` relative link in tracked Markdown and failing loudly (`❌ Dead link in $file → $path`) on any that don't resolve. Any new cross-reference link F2 adds between the two files (or to `compound-v-memory.py`/`compound-v-scope-check.py`) is checked by this exact gate. |

## 4. Critical Findings 🔴

None. There is no dependency in scope to be deprecated, archived, or unmaintained.

## 5. High-Priority Findings 🟠

None. Every surface this spec touches (§2) is first-party, current, and under active
maintenance in this same epic.

## 6. Medium Findings 🟡

**🟡-1 — Spec AC #3 (`/usr/bin/python3 scripts/lint-frontmatter.py` clean) inherits a
pre-existing PyYAML-availability gap; not introduced by this spec, but this spec is a new
consumer of the risk.**

Cited from `docs/superpowers/library-audit/_knowledge-base/python-tooling.md` (dated
2026-09-03, epic-vi-readme-section F2 entry) rather than re-derived: `scripts/lint-frontmatter.py:31`
is a bare, unconditional `import yaml` with no `ImportError` fallback, contradicting this
repo's own documented "stdlib only (+ optional pyyaml with fallback)" design promise. On
any machine where `/usr/bin/python3` (or whichever `python3` runs the AC command) cannot
`import yaml`, the AC command raises `ModuleNotFoundError` before running a single lint
check — a failure that looks identical to "the linter found a real problem" unless the
person running it already knows this gap exists. PyYAML itself is not stale (6.0.3,
"Sustainable" maintenance, per that same KB entry) — the risk is availability, not
currency, which is why this is filed Medium rather than escalated: it changes nothing
about whether F2's own edits are correct, only whether the third of its three AC commands
can be trusted to run cleanly everywhere a contributor might invoke it. Not this spec's to
fix (pre-existing shared infrastructure, per the KB's own disposition) — flagged so a
`ModuleNotFoundError` on this AC isn't misdiagnosed as a defect in F2's doc edits.

**🟡-2 — AC #1 (the `fnmatch` grep) is a non-regression check, not a positive proof of
work done (§3 above).** Both target files are already `fnmatch`-free today. A worker could
in principle satisfy AC #1 and AC #2 ("both files contain the phrase 'the same matcher' and
a reference to the parity selftest") independently of actually landing the six-rule
contract text the spec's Goal paragraph describes, if AC #2's wording is checked loosely
(literal-string presence, not semantic content). Not a library-currency defect — a
plan/acceptance-criteria precision note, carried here because I verified it against live
grep output rather than assuming the AC exercises what it appears to.

## 7. Design Constraints for the Plan

**MUST:**
1. State the six-rule contract exactly as verified live in §3 (`*` single-segment, `**`
   cross-segment incl. `dir/**`⇒`dir`, `?` one non-`/` char, `[`/`]` literal, fully
   anchored to the repo-relative path) — this is what `scripts/compound-v-scope-check.py`'s
   `glob_to_regex` actually implements today, not a paraphrase that could drift from it.
2. Keep the bare-path-recursive reading ("this path or anything under it") scoped to the
   `memory.md`/`recall-check` edit **only**. Do not let it leak into the
   `execution-manifest.md`/`write_allowed`/`read_allowed` note — `scope-check.py`'s own
   `matches`/`is_allowed` have no such special-casing (§3), so stating it there would
   misdocument an **enforced** write-scope boundary, not just an advisory one.
3. Anchor the `execution-manifest.md` addition directly after the `read_allowed` row
   (line 54 today) and the `memory.md` edit at its `recall-check` row (line 54 today) —
   both confirmed live at those exact lines (§3), matching the orchestrator amendment's
   own anchor description.
4. Cite the parity selftest as `compound-v-memory.py --selftest`'s `parity …` assertions
   (`:1632-1642`, confirmed passing) — the real, current name and location, not a
   paraphrase or a different script.
5. Any new relative link either edit introduces must resolve under the repo's dead-link CI
   gate (`.github/workflows/validate.yml:232-264`, confirmed live) — verify locally before
   considering the task done, since that gate is the final CI step and failing it blocks
   merge.

**MUST NOT:**
1. Introduce any third-party dependency, tool, or reference to justify or illustrate the
   glob contract — every fact needed already lives in this repo's own shipped code (§2);
   nothing here calls for a library.
2. State or imply that `write_allowed`/`read_allowed` glob entries get the bare-path
   "matches everything under it" treatment — they do not (§3, Design Constraint 2).
3. Treat a passing `grep -n fnmatch` (§6, 🟡-2) as sufficient proof the six-rule text was
   actually added — confirm the actual new prose is present and matches §3's verified
   rules, not just the absence of one string.

## 8. Open Questions for the Human

1. **Should AC #2's "both files contain the phrase 'the same matcher'" be interpreted as
   requiring identical wording of the six rules in both files (true parity, per the spec's
   title "one glob contract, stated once"), or merely a cross-reference from one file to
   the other with the phrase present in both?** The spec's Goal paragraph reads as wanting
   the former ("say the same thing in the same words") but the amendment's "Glob
   semantics note" (execution-manifest.md) vs. "replaces the recall-check row's wording"
   (memory.md) could be written as one canonical statement + a pointer, or as two
   independent restatements. Not a library-currency question — a scope decision for
   writing-plans, flagged so it isn't decided implicitly by whichever file is edited first.
2. **Is the pre-existing PyYAML-availability gap (§6, 🟡-1) worth a one-line mention in
   this spec's own acceptance criteria** (e.g., "run under an interpreter with PyYAML
   installed") **or is it out of scope for a docs-only spec to touch its own tooling
   dependency?** Not resolved here — genuinely a scoping call, not something this audit
   should decide unilaterally.

## 9. Knowledge Base Updates

Appended one dated section to the **existing** `docs/superpowers/library-audit/_knowledge-base/python-tooling.md`
(correct home — it already owns both this repo's Python-pattern-currency findings and the
PyYAML/`lint-frontmatter.py` gap this audit cites). New section:
`## Updated 2026-09-03 — epic-gp-matcher-docs (F2)`, recording: confirmation this spec
touches zero third-party dependencies (pure two-file doc sync), the live source-of-truth
citations for the six-rule contract and the parity selftest (so the next Phase 1C pass on
this topic doesn't have to re-derive them), the write_allowed-vs-recall-check bare-path
asymmetry, and a forward-pointer noting the PyYAML gap now also gates this spec's own AC.
No prior entry needed strikethrough — additive only.
