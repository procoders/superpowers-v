# POSIX/Bash Shell Tooling Knowledge Base

Maintained by Compound V Phase 1C validator. Append at the bottom.

Scope: the OS-shipped shell toolchain (bash, sed, awk, grep, sort) as it actually behaves on
macOS (BSD userland) vs Linux CI (GNU coreutils), plus `shellcheck` as the static-analysis gate
this repo relies on. None of this is Context7-indexable (no SDK, no npm/pip package) — sources are
live WebSearch against vendor docs, GitHub, and this repo's own CI config.

---

## Updated 2026-09-03 — epic-vi-review-index F1 (`review-index`)

Validated for [`docs/superpowers/library-audit/2026-09-03-epic-vi-review-index.md`](../2026-09-03-epic-vi-review-index.md).

**Bash 3.2 on macOS — still the shipped default, 2026.** Confirmed live: macOS Tahoe 26.x /
Sequoia 15.7.8 (current as of Aug 2026 per search) still ship `/bin/bash` at **3.2.57** — the last
GPLv2 release, frozen there by Apple's licensing stance, not "abandoned" in the deprecation sense.
Bash-4.0+-only constructs **absent** from 3.2 and confirmed live: `declare -A` (associative
arrays, need 4.0+), `mapfile`/`readarray` (need 4.0+, `-d` needs 4.4+), `declare -n` (namerefs,
need 4.3+), `${var,,}`/`${var^^}` (case-conversion parameter expansion, need 4.0+). `[[ str =~
regex ]]` **is** available (bash 3.0+) but uses the system's POSIX-ERE engine — see the `\s` note
below, it applies there too.

**BSD vs GNU tool signature drift (macOS default userland).**
- **grep/awk/bash `[[ =~ ]]`:** BSD's POSIX-ERE engines do **not** support PCRE shorthands. `\s`,
  `\d`, `\w` are *not* character classes — they match a literal backslash followed by that letter.
  Use `[[:space:]]`, `[[:digit:]]`, `[[:alpha:]]` (POSIX bracket classes) instead. Source: Apple
  Developer forums + POSIX regex references, cross-checked live 2026-09-03.
- **sed -i:** BSD sed (macOS) requires an argument to `-i` — `sed -i ''` for "no backup file". GNU
  sed's suffix argument is optional (bare `-i` works). `sed -i.bak 'script' file` is the one form
  both accept identically (suffix glued to the flag). Source: Baeldung "GNU sed vs BSD sed",
  cross-checked live 2026-09-03.
- **awk:** macOS ships BSD/nawk ("the one true awk"), not gawk. GNU-only functions (`gensub`,
  etc.) are absent. `brew install gawk` is the escape hatch if a script genuinely needs them —
  don't assume it's present.
- **sort locale/collation:** BSD `sort` (macOS) and GNU coreutils `sort` (Ubuntu CI) can order
  identically-prefixed strings differently under different active locales. `LC_ALL=C sort ...`
  pins deterministic, cross-environment-identical ordering. This repo's own CI already uses this
  pattern (`.github/workflows/validate.yml:361`, unrelated glob-sort) — follow the existing
  house style rather than inventing a new one.

**shellcheck — maintained, but not a bash-minor-version checker, and CI's copy is stale relative
to upstream.**
- Upstream `koalaman/shellcheck`: latest stable **v0.11.0** (~Aug 2025 release), 39.9k GitHub
  stars, issues actively opened through Aug 2026 — actively maintained, not archived.
- **Gap, confirmed live and still open:** `koalaman/shellcheck#2850` requests a
  bash-minor-version-aware mode (`shell=bash:3.x`) that would flag `mapfile`/`declare -A`/etc. as
  unavailable. As of v0.11.0 this does not exist. `shellcheck --shell=bash` distinguishes
  sh/bash/dash/ksh *dialect* (its `SC3xxx` codes cover POSIX/dash-incompatibility) but has **no**
  bash-*version* awareness. A shellcheck-clean script can still use bash-4-only syntax that breaks
  on macOS's stock 3.2.57. Do not treat "shellcheck-clean" as proof of bash-3.2 compatibility.
- **This repo's CI (`.github/workflows/validate.yml:229`)** installs shellcheck via
  `sudo apt-get install -y shellcheck` on `ubuntu-latest`. Ubuntu Noble (24.04)'s `universe`
  package resolves to **shellcheck 0.9.0-1** — confirmed live via Ubuntu package search,
  2026-09-03 — two minor versions behind the 0.11.0 upstream a contributor's Homebrew install
  would likely have. Non-blocking on its own; means CI and local lint results can diverge on any
  `SC` check added between 0.9 and 0.11.
- ~~This repo's CI shellcheck step only covers `hooks/*.sh` (`validate.yml:227-230`, `shellcheck
  hooks/*.sh`) — `scripts/*.sh` is not linted by CI at all as of 2026-09-03. Any feature whose
  acceptance criterion is "shellcheck-clean" for a new `scripts/*.sh` file gets that checked once,
  by hand, at implementation time, with no CI regression guard afterward unless the glob is
  widened.~~ → **corrected 2026-09-03 (later same day, v3.4.6-triage-test-scoping-fixes audit):**
  wrong even at the time it was written. Direct re-read of `validate.yml:227-230` gives
  `shellcheck hooks/*.sh scripts/compound-v-*.sh` — the glob **does** cover `scripts/compound-v-*.sh`
  and always did in this line; only `hooks/*.sh` was quoted above, and the rest of the line was
  missed. `scripts/compound-v-*.sh` — including every `compound-v-run-*-worker.sh` — has a standing
  CI shellcheck regression guard. What's still true and unaffected by this correction: shellcheck
  itself is not bash-*version*-aware (previous bullet), and any `scripts/*.sh` file that does **not**
  match the `compound-v-*.sh` glob (a hypothetical future non-`compound-v`-prefixed script) genuinely
  would fall outside this CI step.

---

## Updated 2026-09-03 — v3.4.6-triage-test-scoping-fixes

Audit: [`docs/superpowers/library-audit/2026-09-03-v3-4-6-triage-test-scoping-fixes.md`](../2026-09-03-v3-4-6-triage-test-scoping-fixes.md).

**`jq`'s existing `tc_validate` predicates (all five `scripts/compound-v-run-*-worker.sh`) re-checked against the jq-1.8.0 binding-syntax breaking change — unaffected, by source read.**

- Building on the `jq` entry already recorded in `2026-09-02-preflight-workflow-probe.md` (current
  **1.8.2**, this machine **1.7.1**, unpinned/undeclared minimum, jq 1.8.0's breaking change to `as`
  bindings: `[-1 as $x | 1,$x]` now yields `[1,-1]`): the `tc_validate` function repeated across all
  five workers (canonical copy `compound-v-run-codex-worker.sh:122-137`) contains one `as` binding —
  `.scope as $s | [...] | index($s) != null` — that binds a single scalar (`.scope`, one value) to a
  body that itself produces exactly one output. That shape is not the multi-value-generator pattern
  the 1.8.0 change affects, so this predicate's behavior is unchanged across 1.7.1 → 1.8.2.
- **Caveat, stated plainly:** this conclusion is a *source-level read* against jq's documented
  changelog, not a live `jq` execution — the auditing session had no shell access to run `jq --version`
  or exercise the predicate directly. If a future edit to `tc_validate` introduces a *new* `as`
  binding whose body is a multi-value generator (e.g., a list comprehension emitting more than one
  value per bound input), re-verify live rather than extend this conclusion by analogy.
- Practical note for the next feature that touches any of the five workers' `tc_validate`/`tc_run` jq
  filters: keep new predicates in the same `has()` / `type ==` / plain-comparison idiom already used
  throughout — that whole family is confirmed unaffected by the one known jq-1.8.0 breaking change,
  and jq stays unpinned in this repo, so there is no version floor forcing a re-check on every run.

---
