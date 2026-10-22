# Library/Doc Audit — epic-vi-review-index (F1 `review-index`)

**Spec:** `docs/superpowers/execution/epics/2026-09-03-verification-index/specs/review-index.md`
**Plan found in-repo (read for grounding, not as an input requirement):** `docs/superpowers/plans/2026-09-03-epic-vi-review-index.md`
**Date:** 2026-09-03

**DEGRADED: WebSearch-only.** No `*context7*` tool is present in this environment's tool list (checked via `ToolSearch`). This feature has no Context7-indexable SDK anyway (see §1), so the degradation cost is low, but it is noted per protocol.

---

## 0. V-memory recall

Two queries run (`compound-v-memory.py search`, `--intent planning`):

- `"dogfood review index generator bash"` — no hit on this topic (index itself doesn't exist yet — expected, this is the first time it's being built). Adjacent hits only: `v-onboard` dogfood-E2E task, unrelated PRD/plan docs.
- `"shellcheck bash 3.2 macOS awk sed"` — no hit naming shellcheck or this script, but one directly load-bearing adjacent fact from `docs/superpowers/architecture/tech-context.md`: *"Python (stdlib only). The deterministic toolkits are Python scripts that avoid third-party dependencies... 'Python 3.9-safe, stdlib only. Targets stock-macOS python3 3.9.6.'"* — this is the repo's established pattern (target the stock OS-shipped interpreter, zero third-party deps) and it generalizes directly to this spec's own "Bash 3.2 ... no python" constraint: F1 is the bash-tooling analogue of a pattern this repo already lives by for Python. No contradiction found — the spec is consistent with existing repo convention, not stale against it.

The index also reports itself **104 new / 0 removed docs behind the repo** — noted for the caller; does not change my verdict on the two queries above (neither hit domain is in that backlog).

V-memory returned nothing specific to this feature. Said plainly, per instructions, rather than invented.

## 1. Tools Available

| Tool | Status |
|---|---|
| Context7 MCP | ❌ Not present in this session's tool list (`ToolSearch` returned no `*context7*` match). Not consequential here — see below. |
| Dependency manifests | **None exist.** `package.json`, `requirements.txt`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Gemfile`, `composer.json` — zero matches at repo root (`Glob` confirmed each). This feature has no package-manager dependency of any kind. |
| Trigger-0 recon doc | **None handed by the caller and none found on fallback scan.** `docs/superpowers/recon/` contains only `2026-07-11-fts5-cyrillic-tokenizer.md` and `2026-09-01-v3.0-triage-tests-orchestration.md` — neither matches this topic. `features.json` / `epic-state.json` / `brief.md` for this epic carry no recon-path field. |

**Why Context7 doesn't matter for this spec.** Every "library" this spec names — Bash 3.2, git, sed, awk, shellcheck — is an OS-shipped CLI tool or a static-analysis binary, not an SDK with a Context7-indexed doc set. The applicable question isn't "is there a newer major version with a breaking API," it's "does the *specific dialect this script will actually run under* (BSD userland on macOS, GNU coreutils on the Ubuntu CI runner) match what the spec's example regex/idioms assume." That's a WebSearch-and-cross-reference-with-repo-CI question, not a Context7 one, so the fallback is not a real degradation of the audit for this particular topic.

## 2. Libraries/Tools Mentioned

| Name | Spec context | Current state (live, 2026-09-03) | Repo-pinned | Maintenance | Status |
|---|---|---|---|---|---|
| **Bash 3.2** | Explicit target: "Bash 3.2 + git + sed/awk" | Confirmed live: macOS still ships `/bin/bash` 3.2.57 as of current releases (macOS Tahoe 26.x / Sequoia 15.7.8, per 2026 sources) — Apple has not moved off the last GPLv2 bash release. | N/A (OS-shipped) | N/A — frozen by design (Apple licensing decision), not "abandoned" | 🟢 OK as a deliberate floor, but see §3/§4 — it materially constrains what the implementation may use |
| **git** | Explicit: "+ git" (used for the idempotence check, `git diff --exit-code`, per the plan's Task B — not for the script's own file-discovery logic) | Ambient tool; the one invocation named (`git diff --exit-code`) is a stable, ancient flag with no version-drift risk. | N/A | N/A | 🟢 OK |
| **sed / awk** | Explicit: "+ sed/awk" | macOS ships **BSD sed** and **BSD/"one true" awk (nawk)**, not GNU sed/gawk. Confirmed live 2026: BSD sed's `-i` requires an argument (`sed -i ''` for no backup) where GNU's is optional; BSD/nawk lacks GNU-only functions (`gensub`, etc.); neither BSD grep nor BSD sed/awk supports PCRE shorthands (`\s`, `\d`) — only `[[:space:]]`-style POSIX bracket classes. | N/A | N/A | 🟢 OK as tools, but this signature drift is a live landmine for this spec's own example regex — see Critical/High findings |
| **shellcheck** | Explicit: "shellcheck-clean" acceptance bar | Upstream `koalaman/shellcheck`: latest stable **v0.11.0** (released ~Aug 2025), 39.9k GitHub stars, issues actively opened through Aug 2026, not archived. **CI's actual copy** (`.github/workflows/validate.yml:229`, `sudo apt-get install -y shellcheck` on `ubuntu-latest`) resolves to **Ubuntu Noble (24.04) universe package 0.9.0-1** — two minor versions behind upstream. | CI: apt 0.9.0-1 (unpinned, resolves whatever Ubuntu's repo has). No local/repo pin found. | Upstream actively maintained. | 🟢 OK (not stale/abandoned) but 🟡 the CI copy is version-skewed from upstream and from a contributor's likely-newer local install — see Medium findings |

No ORM/queue/HTTP-client/etc. "implied by category" items apply — there is no such category in this spec. No external web API is called.

## 3. API Signatures Verified

| Call/idiom | Spec or plan text | Verified against | Result |
|---|---|---|---|
| `^\**VERDICT:?\**\s*(APPROVED\|ISSUES)` (verdict regex, case-insensitive) | Spec's own Parsing section, verbatim | BSD grep/awk/bash `[[ =~ ]]` regex engines (macOS default userland) | **`\s` is not a whitespace class in BSD's POSIX-ERE engines — it matches a literal backslash+`s`.** The spec's own example pattern will not match on the OS it targets unless rewritten with `[[:space:]]`. This is not a hypothetical: confirmed live via Apple's own developer forums and POSIX-regex references, cross-checked against ss64's macOS grep-pattern reference. |
| `sed -i 's/…/…/'` (implied in-place-edit idiom, not in the spec text but the default idiom an implementer reaches for) | N/A — flagged because it's the most common LLM-default and the most common real-world macOS breakage | BSD sed (macOS) vs GNU sed | BSD sed's `-i` **requires** an argument (use `sed -i ''`); a bare `-i` is a hard error or corrupts the file, unlike GNU sed where the suffix is optional. |
| Case-insensitive verdict match implemented as `${line,,}` | Not in the spec text — flagged because the spec's case-insensitive requirement is the natural place an implementer reaches for this | Bash parameter-expansion case-conversion (`${var,,}`/`${var^^}`) | **Bash 4.0+ only.** Absent from bash 3.2. Confirmed live (multiple 2026 bash-portability references) alongside `declare -A`, `mapfile`/`readarray`, `declare -n` — all bash-4.0+/4.3+-only and all absent from macOS's stock 3.2.57. |
| `shellcheck` as a proxy for "safe under bash 3.2" | Spec's own acceptance criterion: "shellcheck-clean" | `koalaman/shellcheck` issue tracker | **Confirmed gap, still open:** GitHub issue `koalaman/shellcheck#2850` requests exactly this (a `shell=bash:3.x` mode that would flag `mapfile`/associative arrays as unavailable) and is unresolved as of the live 2026 search. ShellCheck's `--shell=bash` dialect check has no bash-*minor-version* awareness — it will not fail a script for using bash-4-only syntax. "shellcheck-clean" is real signal for POSIX/dash-portability (`SC3xxx` codes) but is **not** evidence of bash-3.2 safety. |

## 4. Critical Findings 🔴

None. This is a zero-dependency, OS-tool-only feature; there is no deprecated/archived/critically-stale library to report. The risk in this spec is entirely signature-drift between tool *dialects* (BSD vs GNU) and a version-blind acceptance bar (shellcheck), not staleness — covered as High/Medium below.

## 5. High-Priority Findings 🟠

**H1 — "shellcheck-clean" does not verify bash-3.2 compatibility, and the spec's own case-insensitive-match requirement is exactly where that gap bites.**
The spec requires case-insensitive VERDICT matching. The idiomatic bash-native way to do that is `${line,,}` — bash 4.0+ only, silently absent from macOS's stock bash 3.2.57, and **shellcheck will not flag it** (verified live: no bash-minor-version check exists in shellcheck as of v0.11.0; `koalaman/shellcheck#2850` requests it and is still open). Same trap for reaching for `declare -A` (a verdict→count map) or `mapfile` (reading file lists) instead of the spec-safe alternatives.
*Alternative, verified-safe idioms:* `grep -iE` or `tr '[:upper:]' '[:lower:]'` / `awk 'tolower($0)'` for case-folding; indexed arrays + `case`/`if` chains instead of associative arrays; a `while IFS= read -r` loop instead of `mapfile`.

**H2 — CI does not lint the file the spec requires to be shellcheck-clean, so the acceptance bar has no regression guard.**
`.github/workflows/validate.yml:227-230` runs `shellcheck hooks/*.sh` — that glob does not include `scripts/*.sh`. `scripts/compound-v-dogfood-index.sh` (and `tests/test-dogfood-index.sh`) will be shellcheck-clean exactly once, at implementation time (plan's Task A Step 3, run by hand), and never checked again by CI. This repo has already been burned by exactly this failure mode once — its own CI comments (`validate.yml:363`) reference the incident where "25 of 29 selftests silently stopped running" because a discovery glob quietly excluded files. Recommend closing the same class of gap here rather than repeating it.

## 6. Medium Findings 🟡

**M1 — GNU-vs-BSD sed/awk/grep signature drift (beyond the verdict regex in §3).** macOS's default userland is BSD grep/sed/nawk, not GNU. Any regex written with PCRE shorthands (`\s`, `\d`, `\w`) is silently wrong (matches a literal character, not a class) under BSD engines; `sed -i` needs the empty-string form; GNU-only awk builtins (`gensub`) don't exist. All confirmed live in §3.

**M2 — Locale-dependent `sort` collation risks the byte-identical-output acceptance criterion across environments.** If row/file ordering is produced by piping through `sort` without pinning collation, BSD `sort` on a macOS dev machine and GNU coreutils `sort` on the Ubuntu CI runner can order identically-prefixed filenames differently depending on each environment's active locale. Within one machine, two runs are still byte-identical (locale doesn't change between runs) — the spec's own idempotence acceptance criterion (`git diff --exit-code` after a second run, same machine) is not directly threatened. But cross-environment reproducibility (dev-authored output vs. CI-verified output) is, and the repo already sets a precedent for exactly this fix (`LC_ALL=C ... sort` pattern already used in `validate.yml:361` for an unrelated glob-sort). Cheap, standard, matches existing house style: prefix any ordering-relevant `sort` with `LC_ALL=C`.

**M3 — shellcheck version skew: CI's apt-sourced 0.9.0-1 (Ubuntu Noble) vs. upstream 0.11.0.** Not a maintenance problem (upstream is healthy — see §2) but a reproducibility one: any `SC` check added between 0.9 and 0.11 will not fire in CI even after H2 is fixed, so a script that's clean on a contributor's newer local shellcheck could still be the first to trip a check nobody has installed in CI, or vice versa. Non-blocking for F1 alone; worth a one-line note if the team ever wants CI and local lint results to agree.

## 7. Design Constraints for the Plan

- **MUST NOT** use any bash-4.0+-only construct in `scripts/compound-v-dogfood-index.sh` or `tests/test-dogfood-index.sh`: no `declare -A`, no `mapfile`/`readarray`, no `declare -n`, no `${var,,}`/`${var^^}`. Verified live: macOS's stock `/bin/bash` remains 3.2.57 in 2026, and shellcheck does not fail a script on this basis.
- **MUST** implement the spec's case-insensitive VERDICT match with a bash-3.2-safe idiom (`grep -iE`, `tr '[:upper:]' '[:lower:]'`, or `awk 'tolower($0)'`), not `${var,,}`.
- **MUST** use POSIX bracket classes (`[[:space:]]`, `[[:digit:]]`, `[[:alpha:]]`) — not PCRE shorthands (`\s`, `\d`, `\w`) — in every grep/sed/awk/`[[ =~ ]]` regex, including the spec's own example verdict pattern. Confirmed live: BSD tools on macOS treat `\s` as a literal `\` + `s`, not a whitespace class.
- **MUST** use `sed -i ''` (explicit empty-string backup arg) for any in-place edit, or avoid `sed -i` entirely (temp file + `mv`) — BSD sed's `-i` requires an argument where GNU's does not.
- **MUST NOT** rely on GNU-only awk builtins (e.g. `gensub`) — macOS ships BSD/nawk by default, no gawk guaranteed.
- **MUST** prefix any ordering-relevant `sort` invocation with `LC_ALL=C` to protect the byte-identical-output guarantee across macOS-dev and Ubuntu-CI collation defaults (precedent already in this repo's own CI at `validate.yml:361`).
- **MUST** widen `.github/workflows/validate.yml`'s shellcheck step (currently `shellcheck hooks/*.sh`, line 230) to also cover `scripts/compound-v-dogfood-index.sh` (and ideally `tests/*.sh` generally), or file this as an explicit, named follow-up — otherwise "shellcheck-clean" silently stops being enforced the moment this PR merges.
- **MUST NOT** treat a green `shellcheck` run as proof of bash-3.2 compatibility in the spec-review/integration-review gate — it isn't (verified live, `koalaman/shellcheck#2850` open, no version-pinning capability shipped as of v0.11.0). The reviewer needs a manual bash-3.2-syntax check (or literally testing under `/bin/bash` on a stock macOS box) as a separate gate.

## 8. Open Questions for the Human

1. **Is widening the CI shellcheck glob (H2 / constraint 6) in scope for F1 itself, or a separate housekeeping PR?** The spec's stated acceptance criterion is only "`shellcheck` clean" (a one-time, locally-run check per the plan's Task A Step 3) — it does not say "CI enforces this going forward." Recommend folding it into F1 since it's a two-line CI change directly caused by this feature's own new file, but that's a scoping call, not mine to make.
2. **Does the team want a pinned/reproducible shellcheck version** (e.g. a specific GitHub-release binary rather than whatever `apt-get`/`brew` happen to resolve to) given the confirmed 0.9.0-vs-0.11.0 skew between CI and a typical contributor's machine (M3)? Out of scope for this single small feature to decide unilaterally.

## 9. Knowledge Base Updates

No existing KB topic file covered POSIX-shell/shellcheck/BSD-vs-GNU tooling — created a new one: `docs/superpowers/library-audit/_knowledge-base/posix-shell-tooling.md`, dated 2026-09-03, citing every claim above with its source.
