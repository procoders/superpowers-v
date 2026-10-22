# Library/Doc Audit — epic-vi-readme-section (F2 `readme-section`)

**Spec:** `docs/superpowers/execution/epics/2026-09-03-verification-index/specs/readme-section.md`
**Depends on:** F1 `review-index` (already `done`, run `2026-09-03-verification-index-review-index-r3`; see its own audit at `docs/superpowers/library-audit/2026-09-03-epic-vi-review-index.md`)
**Date:** 2026-09-03

**DEGRADED: WebSearch-only.** No `*context7*` tool is present in this session's tool list (checked via `ToolSearch("context7 resolve-library-id query-docs")` — zero matches). Noted per protocol; see §1 for why it is moot for this particular spec.

---

## 0. V-memory recall

Three queries run (`compound-v-memory.py search`, `--intent planning`), matching this repo's `bashCommandClamp` (only `search`/`recall-check` subcommands were permitted this session):

- `"verification index readme section"` — no hit on this specific feature (expected: F2 doesn't exist yet). Adjacent hits only: unrelated PRD/plan/onboarding docs. Index reported **112 new / 0 removed docs behind the repo** — noted for the caller, does not change any verdict below (none of the hit domains are in that backlog).
- `"README docs-only feature acceptance numbers must match generated file"` — no hit specific to this pattern. One tangentially relevant precedent: `docs/superpowers/specs/2026-07-25-v2.17-cochange-and-evidence-packing-design.md`, Feature C — *"Any published number about Compound V ships with a 'What this does not show' note in the same document"* — a documentation-accuracy norm this repo already holds itself to, consistent with (not contradicting) this spec's own "numbers must equal the footer at the time of writing" requirement.
- `"lint-frontmatter.py PyYAML dependency"` — **one directly load-bearing hit that disagrees with code reality**, used below (§6, M1): `docs/superpowers/plans/2026-06-26-compound-v-orchestrator-v1-plan.md` §7 *Cross-cutting requirements* states *"Scripts target bash 3.2 + python 3.9, stdlib only (no npm/pip mandatory deps; pyyaml optional with fallback)"* — verified against the actual script and found stale (code wins; the disagreement is reported as a finding, not silently resolved).

V-memory returned nothing specific to this feature itself (it doesn't exist yet — expected), and one genuine doc-vs-code drift on an inherited dependency. Said plainly, per instructions, rather than invented.

## 1. Tools Available

| Tool | Status |
|---|---|
| Context7 MCP | ❌ Not present in this session's tool list. Not consequential — see below. |
| Dependency manifests | **None exist.** `package.json`, `pnpm-lock.yaml`, `yarn.lock`, `requirements.txt`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Gemfile`, `composer.json` — zero matches at repo root (`Glob` confirmed, one call covering all eight). This repo has no package-manager dependency of any kind. |
| Trigger-0 recon doc | **None handed by the caller and none found on fallback scan.** `docs/superpowers/recon/` contains only `2026-07-11-fts5-cyrillic-tokenizer.md` and `2026-09-01-v3.0-triage-tests-orchestration.md` — neither matches this topic. `epic-state.json`/`brief.md`/`features.json` for this epic carry no recon-path field. |

**Why Context7 doesn't matter for this spec.** F2's entire deliverable is three sentences of prose, a relative Markdown link, and two integers copied from an already-generated file — added to `README.md`. There is no library, SDK, framework, runtime, or external API named or implied anywhere in the spec text. This is the smallest possible surface for a Phase 1C audit: the honest finding is that there is nothing here to look up.

## 2. Libraries/Tools Mentioned

**None, explicit or implied, in the spec itself.** `README.md` is Markdown; the spec names no library, package, SDK, ORM, queue, or external API.

One dependency is *inherited* through the spec's own acceptance criterion (not introduced by F2, but worth recording since it gates whether F2 can be verified):

| Name | Spec context | Current state (live, 2026-09-03) | Repo-pinned | Maintenance | Status |
|---|---|---|---|---|---|
| **PyYAML** (`yaml` import) | Acceptance criterion #4: `/usr/bin/python3 -B scripts/lint-frontmatter.py .` green — that script does `import yaml` at module scope (`scripts/lint-frontmatter.py:31`), unconditionally, with no `try`/`except ImportError` fallback. | PyPI latest **6.0.3**; libraries.io rates its maintenance "Sustainable" with a release in the past 12 months; canonical repo `yaml/pyyaml` on GitHub, actively maintained, MIT-licensed. Not deprecated, not archived. | Unpinned everywhere in this repo (no manifest exists — see §1). CI installs it fresh, unpinned, three separate times: `.github/workflows/validate.yml:115` (`pip install pyyaml`), `:294` and `:342` (`pip install --quiet pyyaml jsonschema`). | Upstream actively maintained. | 🟢 OK as a library — current, healthy, not stale. 🟡 **but see M1**: the *project's own documented promise* about how this dependency degrades has drifted from what the code does. |

No ORM/queue/HTTP-client/etc. "implied by category" items apply — there is no such category in this spec. No external web API is called. No SDK version, no method signature, nothing to resolve against Context7 even if it were present.

## 3. API Signatures Verified

**N/A — the spec contains no code, no example calls, and no method signatures.** The only "interface" in the spec is a Markdown link (`[...](docs/superpowers/dogfood/README.md)`, a static relative path, no API) and two integers read by eye from a table footer. Nothing to verify against live docs.

## 4. Critical Findings 🔴

None. Zero libraries are named or implied by this spec; there is nothing that could be deprecated, archived, or 24+ months stale, because there is nothing external to become stale.

## 5. High-Priority Findings 🟠

None, for the same reason as §4.

## 6. Medium Findings 🟡

**M1 — The acceptance-criteria-gating script's PyYAML dependency has no fallback, contradicting this repo's own documented cross-cutting design promise; F2 inherits that fragility without introducing it.**

- **The promise:** `docs/superpowers/plans/2026-06-26-compound-v-orchestrator-v1-plan.md`, both in the design-decisions table (line 49: *"Stock macOS = bash 3.2.57 / python 3.9.6 ... All helper scripts target bash 3.2 + py 3.9, stdlib only (+ optional pyyaml with fallback)"*) and again in §7 Cross-cutting requirements (line 155: *"Scripts target bash 3.2 + python 3.9, stdlib only (no npm/pip mandatory deps; pyyaml optional with fallback)"*).
- **The code:** `scripts/lint-frontmatter.py:31` is a bare `import yaml` at module top-level. Confirmed via `Grep` for `ImportError|try:|except|import yaml` across the file: the only `try`/`except` blocks in the file (lines 110/112, 202) are for YAML *parse* errors inside the linter's own logic, not for the *import* itself. If PyYAML is not importable under whatever `python3` runs this script, the script does not degrade or skip — it throws `ModuleNotFoundError` and exits nonzero before doing anything, including on a file class the linter would otherwise no-op on (README.md itself is exempt from the frontmatter-presence gate — only `agents/*.md`, `commands/*.md`, `skills/*/SKILL.md` require it — but the script still must successfully `import yaml` to run at all).
- **Why this isn't invisible today:** CI never hits it, because `.github/workflows/validate.yml` explicitly `pip install pyyaml`s before every invocation (lines 115, 294, 342) — three separate, unpinned installs. And on the specific machine this project's own `AGENTS.md` documents as "the ordinary machine" for its lane-guard hook, PyYAML is stated to already be importable under `/usr/bin/python3` (AGENTS.md: *"the one whose first candidate interpreter can `import yaml`, which on macOS is `/usr/bin/python3`"*) — implying that assumption does *not* hold universally, which is exactly why that hook carries a multi-candidate probing ladder that `lint-frontmatter.py` does not.
- **Relevance to F2 specifically:** F2's own acceptance criterion #4 is literally `/usr/bin/python3 -B scripts/lint-frontmatter.py .` green. On the two paths this repo actually exercises (CI, and the AGENTS.md-documented "ordinary" macOS dev machine) that criterion is reliable. On any other machine — a contributor's Linux box without a prior `pip install pyyaml`, or a macOS install where the system `python3` doesn't happen to have it — the *same acceptance command the spec asks the reviewer to run* fails with an unrelated `ModuleNotFoundError`, not a real lint finding, and a reviewer unfamiliar with this quirk could misdiagnose it as an F2 defect.
- **Disposition:** this is pre-existing infrastructure F2 does not touch or introduce — it is Phase 1A code-archaeology territory in scope, not F2's to fix. Recorded here because Phase 1C's Step 0 explicitly asks for exactly this: a documented project promise checked live against the code and found to disagree, with code treated as authoritative.

No other Medium findings — everything else in scope for F2 is prose-only.

## 7. Design Constraints for the Plan

- **MUST NOT** introduce any new library, package, SDK, or runtime dependency for this feature — the entire deliverable is a prose edit to `README.md` (three sentences, one relative link, two integers). Any plan step that reaches for a templating library, a Markdown-table generator, or similar is over-engineering a change that is pure text editing.
- **MUST** source the two counts ("N review files, A APPROVED") by reading `docs/superpowers/dogfood/README.md`'s footer line at write time (`Reviews: N · APPROVED: A · ISSUES: I · other: O`, per F1's shipped format — confirmed live in the repo: `Reviews: 32 · APPROVED: 2 · ISSUES: 25 · other: 5` as of this audit) — never hardcode numbers independently of that file, and never let them drift if the index is regenerated between plan-writing and merge.
- **MUST NOT** assume F1's footer string format is a versioned/stable contract independent of F1's own script — F2 depends on it verbatim. The spec already requires the reviewer to verify the two numbers by reading both files (not by a test), which is the correct compensating control given there is no schema; keep that manual-equality check as the acceptance mechanism, don't silently drop it for a passing CI run.
- **MUST** pass `/usr/bin/python3 -B scripts/lint-frontmatter.py .` (spec's own acceptance criterion #4). Be aware this command's reliability depends transitively on PyYAML being importable under the invoking `python3` — true in CI and on the documented "ordinary" macOS dev machine, not guaranteed everywhere despite this repo's own design doc promising a stdlib-first, fallback-safe posture (§6, M1). Not a blocker for F2 on the paths this repo actually runs; flagged so a failure on an unusual machine isn't mistaken for an F2-caused regression.
- **MUST NOT** treat this audit's clean bill as license to skip the standard review gates — "zero libraries" means Phase 1C found nothing to flag, not that Phase 1A (does the section's claimed placement/wording match the actual README structure and F1's actual output) or the human spec-acceptance review are any less necessary.

## 8. Open Questions for the Human

1. **Is M1 (PyYAML hard-import, no fallback, contradicting the 2026-06-26 design doc's "optional with fallback" promise) worth a standalone follow-up ticket against `scripts/lint-frontmatter.py`, or does the team consider "CI always installs it" a sufficient closure of that promise going forward?** Out of scope for F2 to decide or fix — it's pre-existing shared infrastructure this feature merely depends on for its own acceptance gate, not something F2's spec introduces.

No other open questions — the spec is small and unambiguous; nothing else here requires a scoping decision Phase 1C can't make on its own evidence.

## 9. Knowledge Base Updates

No existing KB topic file covered PyYAML/Python-dependency-fallback conventions in this plugin's own tooling (checked: `agent-instruction-tooling.md`, `claude-code-hooks.md`, `claude-code-runtime.md`, `posix-shell-tooling.md` — none match). Created a new one: `docs/superpowers/library-audit/_knowledge-base/python-tooling.md`, dated 2026-09-03, recording the PyYAML/`lint-frontmatter.py` fallback-promise-vs-code-reality gap (M1 above) with full citations, for any future feature whose acceptance criteria also route through `scripts/lint-frontmatter.py`.
