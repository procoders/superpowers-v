# Local range `c011d6e..7dfaeeb` — releases 3.4.11 → 3.4.15

Review session: 2026-09-04 · Host: `local` (hostless range; `gh` is installed and `origin` is
github.com, but no PR exists for this range) · Branch: `main` · Head SHA: `7dfaeeb`
Diff under review: `git diff c011d6e..7dfaeeb -- scripts/` (code axis).

Standards sources discovered and read: `CLAUDE.md`, `AGENTS.md`, `CONVENTIONS.md`,
`docs/superpowers/architecture/*`, `.github/workflows/validate.yml`, `scripts/lint-frontmatter.py`.
Spec source: **partial** — design specs exist only for 3.4.13
(`docs/superpowers/specs/2026-09-03-v3.4.13-preflight-git-history-design.md`) and 3.4.10; for
**3.4.11, 3.4.12, 3.4.14 and 3.4.15 there is no design doc** and the `CHANGELOG.md` entry is the
only spec. Note for the skill's own Source Auto-Discovery: none of its documented spec globs
(`specs/*/spec.md`, `docs/specs/**`, `docs/prd/**`, `.scratch/**`) matches this repo's real spec
home, `docs/superpowers/specs/*-design.md`.

> **Reviewed against the commit, not the working tree.** During this review the working tree
> carried 42 uncommitted modifications/deletions from concurrent sessions. Every anchor below was
> re-verified against `7dfaeeb` with `git show`/`git ls-tree`. See the retracted candidate at the
> foot of the Findings table — the dirty tree produced one false positive.

---

## What this PR does

**What.** Five point releases that harden three separate levers a human or an orchestrator pulls
when something has already gone wrong: the model the Antigravity backend picks for cheap work, the
state a crashed run must be put back into before it can be relaunched, and the retry cap a stalled
epic is measured against. Alongside them, the pre-flight auditors are allowed to read git history,
recall's file matcher is unified with the scope gate's, and a repo-wide audit corrects a set of
documents that promised mechanisms that did not exist.

**Why.** Every one of these came from an observed failure, not from a design wish: a discovery
ranker that proposed the *oldest* Flash model, a resumed job BLOCKED by its own dead attempt's
baseline pin, a marathon epic parked at `blocked_needing_human` with no lever to un-park it, and a
1A archaeologist that reported twice in one day that `git log` was unreachable. The area is in
hardening, not new-build: each change is small, each ships with selftest coverage, and each sits on
a path that only executes after something has failed — which is exactly the code least likely to be
exercised again before the next incident.

**How.**
- `scripts/compound-v-discover-models.py` — the series ranker's `light` pick moves from the
  oldest to the newest series of the weakest strength class; `compound-v-resolve-model.py`'s
  built-in fallback follows it to `Gemini 3.8 Flash (Low)`.
- `scripts/compound-v-emit-workflow.py` — a sixth subcommand, `resume-prepare`, that the
  orchestrator (never a worker) runs before a relaunch: it un-pins, re-pends, un-lanes and
  archives the receipts of every job that did not integrate.
- `scripts/compound-v-epic-state.py` — `--clear-breaker` gains
  `--set-max-attempts-per-feature N`; `scripts/compound-v-emit-preflight.py` widens the auditors'
  Bash clamp from two rules to five; `scripts/compound-v-memory.py` drops `fnmatch` and loads the
  scope gate's `matches()` from source behind the same fail-closed bytecode-cache guard the
  integration gate uses.

---

## Two-Axis Pre-Pass

_(Phase 3.5 — two context-isolated sub-agents, run in parallel. Reports verbatim, lightly cleaned,
kept separate. Not merged, not deduped across axes, not reranked.)_

### Standards

STANDARDS axis — `c011d6e..7dfaeeb`, scripts/ (read-only; temp worktree removed).

## Hard violations

**1. Forked security-critical loader.** `scripts/compound-v-memory.py:1064-1113` `_scope_matches()` is a near-verbatim fork of `load_scope_matcher()` at `scripts/compound-v-integration-gate.py:417-470` — same mkdtemp / `sys.pycache_prefix` / `spec_from_file_location` / fail-closed sequence, differing only in return convention. Its own docstring names the duplication ("Same hardening as compound-v-integration-gate.py load_scope_matcher"). Violates `CONVENTIONS.md:19-20` ("Reuse canonical shared constants instead of forking a second copy"), whose cited exemplar is exactly a cross-script import from this file. A future hardening must now be applied twice.

**2. New lever missing from its authority docs.** `scripts/compound-v-epic-state.py:3903` adds `--set-max-attempts-per-feature`, absent from `skills/compound-v/epic-mode.md:153` (CLI table) and `commands/v-epic.md:372` — the §7 runbook `epic-mode.md:168` calls "every field + copy-paste commands". Both files were edited later *in this same range* (7dfaeeb) and still list only `--reset-wall-clock` / `--set-max-total-attempts`. Its sole invocation site is a one-off generated halt page under `docs/superpowers/execution/`. Mechanism-without-a-caller rule, `docs/superpowers/architecture/2026-09-02-viability-audit.md:41,49`.

## Judgement calls

**3.** `.github/workflows/validate.yml:268` — dead-link guard narrowed by `-not -path "./docs/superpowers/execution/*/jobs/*"` with **no inline rationale**, in a file where every other guard decision carries one, eight lines from the comment block (`:316-332`) warning that narrowed discovery caused v2.14's false-green.
**4.** `scripts/compound-v-memory.py:26` — "the CORE imports stdlib only" is now inaccurate; `recall_check` imports a sibling script. Rule intact (no third-party dep), stated invariant not amended.
**5.** `scripts/compound-v-emit-workflow.py:120` — `import datetime` between `io` and `json` breaks the block's otherwise strict alphabetical order (`:117-126`).
**6.** `scripts/compound-v-emit-workflow.py:8464` — `cmd_resume_prepare` defined *after* `selftest()`; all five siblings precede it (`:3458,4345,4829,5322,5662`).
**7.** `scripts/compound-v-discover-models.py:118` — "the Flash line ships a new version every few weeks" is an unmeasured cadence claim (`AGENTS.md`, "On measurement, stated up front"). `compound-v-resolve-model.py:96` does it right: version + date + "VERIFIED against `agy models`".

## Verified clean (asked explicitly)

- **Both** moved tests exist at 7dfaeeb and **both** run: recursive sweep `validate.yml:351-374` (`find tests -type f \( -name '*.sh' -o -name '*.py' \)`); `jq` installed at `:339`. I executed both at 7dfaeeb — PASS. Their old `scripts/` home was never swept (`:302` globs `scripts/*.py`), so the move is a net CI gain; no stale `scripts/test-…` refs remain.
- `resume-prepare` has a real caller: `commands/v-resume.md:31`.
- All six changed scripts cover the new behavior in `--selftest`; all pass under 3.9.
- No anti-ruflo pattern hits (`validate.yml:194`); `skills/compound-v/memory.md:54,108,115` already carries the new matcher semantics and `unavailable` verdict.

### Spec

SPEC-axis review, `c011d6e..7dfaeeb -- scripts/`.

**Spec status:** design specs exist only for 3.4.13 (`docs/superpowers/specs/2026-09-03-v3.4.13-preflight-git-history-design.md`) and 3.4.10. For **3.4.11, 3.4.12, 3.4.14 and 3.4.15 there is no design spec — the CHANGELOG entry is the spec**, as briefed. The glob-parity work has feature plans (`docs/superpowers/plans/2026-09-03-epic-gp-*.md`).

**Claims verified**
- 3.4.13 "emits five clamp rules instead of two" — **TRUE.** Live emit produced exactly 5 rules, 3 of them `Bash(git log|blame|show:*)`; selftest 41/41 (`scripts/compound-v-emit-preflight.py:206-220`, `:508-526`). Spec ACs all met, incl. amendments 1-3.
- 3.4.14 "every built-in default and doc that named 3.6 Flash names 3.8 Flash" — **TRUE.** Only surviving `3.6 Flash` is the deliberate selftest fixture at `scripts/compound-v-discover-models.py:237`; default at `scripts/compound-v-resolve-model.py:100`.
- 3.4.15 "two orphan test scripts moved into `tests/` (both pass, CI now runs them)" — **TRUE.** `SCRIPT_DIR` correctly re-anchored to `../scripts` in both; I ran both at 7dfaeeb: PASS/PASS; `.github/workflows/validate.yml:367` discovers `tests/` recursively.
- 3.4.12 **"The halt page names it" — FALSE.** See (a)1.

**(a) Missing / partial**
1. Spec line: *"The lever now sits beside `--set-max-total-attempts` ... The halt page names it."* The flag is defined at `scripts/compound-v-epic-state.py:3903` but appears in **no document**. The halt-page runbook `commands/v-epic.md:372` still lists only `--reset-wall-clock` / `--set-max-total-attempts`; ditto the recovery table `skills/compound-v/epic-mode.md:153` and prose `:168`. The operator who hits the exact halt that motivated finding 151 cannot discover the lever.
2. The glob-parity behaviour change ships with no `### Changed` entry — CHANGELOG mentions it only inside the stage-7 narrative. `scripts/compound-v-memory.py:1115-1126` materially **narrows** recall-check: under the old `fnmatch`, `src/*.py` matched `src/a/b.py` and `a?b` matched `a/b`; both now `False` (verified). A silent narrowing of a routing-tighten input deserves its own entry.

**(b) Scope creep**
3. `scripts/compound-v-memory.py:1131-1136` adds an **engine-side** `unavailable` verdict. Neither the F1 plan (selftest row only, "no production change") nor 3.4.10 (whose `unavailable` is emitter-side, `compound-v-emit-workflow.py:1364+`) asked for it. Benign — the emitter enum accepts it (`:1407`) and `skills/compound-v/memory.md:54,108` document it.
4. `cmd_resume_prepare` (`scripts/compound-v-emit-workflow.py:8524`) unconditionally rewrites `state["phase"] = "PARTITION_VERIFIED"`. The 3.4.12 spec sentence enumerates pin/worktree/pending/receipt only; `commands/v-resume.md:31` also omits the phase rewrite.

**(c) Implemented but looks wrong**
5. `scripts/compound-v-emit-workflow.py:8516-8517`: the superseded-receipt name is keyed on `realised_commit[:12]`, and `os.replace` silently clobbers. Two crashed attempts sharing a realised commit lose the earlier superseded receipt — the audit trail the archive exists to preserve. A timestamp suffix (already the fallback branch) would make it collision-free.

_Summary: **Standards** — 2 hard violations + 5 judgement calls (worst: a security-critical fail-closed loader forked rather than shared, `compound-v-memory.py:1064` vs `compound-v-integration-gate.py:417`). **Spec** — 4 CHANGELOG claims verified TRUE, 1 verified FALSE, plus 5 gaps (worst: the 3.4.12 claim "the halt page names it" is false in every authority doc). No winner is picked across the two axes._

---

## Decisions log (per domain)

- **Domain 0 — Dead code & call-graph reality.** All three new mechanisms have a real caller:
  `resume-prepare` is invoked by `commands/v-resume.md:31`; the git clamp forms are emitted into
  the pre-flight workflow at `compound-v-emit-preflight.py:213`; `_scope_matches()` is called by
  `_file_matches`/`recall_check`. `--set-max-attempts-per-feature` has a code path but **no
  runbook caller** — see Finding 2.
- **Domain 1 — Intent alignment.** 3.4.14's stated intent ("the newest series of the weakest
  class") is implemented for `light` and holds on the 3.6/3.7/3.8 catalog it was written against;
  it does **not** hold once a series number reaches two decimal digits — Finding 1.
- **Domain 2 — Contracts between documents.** `resume-prepare` and the resume-eligibility rule
  now contradict each other — Finding 3. `recall_check`'s verdict vocabulary grew a value its two
  consumer contracts still deny exists — Findings 4 and 5.
- **Domain 3 — Test reality.** Every touched script's selftest passes on this machine:
  `compound-v-emit-workflow.py` 508/508 (needs `/usr/bin/python3` — PyYAML),
  `compound-v-epic-state.py` 373/373, `compound-v-emit-preflight.py` 41/41,
  `compound-v-discover-models.py` 27/27, `compound-v-memory.py` 0 failed. CI's recursive
  `tests/**` discovery (`.github/workflows/validate.yml:351`) does reach both relocated scripts.
- **Domain 4 — Fail-closed behaviour.** `compound-v-memory.py:1663-1685` deserves the note: the
  new fail-closed test spies on `spec_from_file_location` and asserts `_sfl_calls == []`, so it
  proves the sibling was never *reached* rather than only that the verdict was right. A
  verdict-only assertion would pass with the guard deleted. This is the correct shape for a
  fail-closed test and there is no finding here.

---

## Findings

| # | Category | Severity | Confidence | File:Line | Anchor | Finding | Recommended Action | Verdict | Class-check | Post? |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Bug Risk | High | High | `scripts/compound-v-discover-models.py:68` | Inline | `version = float(ver_m.group(1))` parses a dotted series number as a decimal, so `Gemini 3.10 Flash` reads as version `3.1` — *below* `Gemini 3.8 Flash`. 3.4.14's new `light` pick (`:122`) ranks the weakest strength class by exactly that float, so the first two-digit minor version reintroduces the bug this release shipped to fix. Reproduced live: on the catalog `[3.10 Flash (Low), 3.8 Flash (Low/High), 3.1 Pro (High/Low)]` the ranker proposes `light = Gemini 3.8 Flash (Low)`. The selftest at `:234-241` pins only single-digit minors (3.6/3.7/3.8), so it cannot catch this. | Parse the version as a tuple of ints per dotted component (`tuple(int(p) for p in m.group(1).split("."))`) and compare tuples; add a `3.10 vs 3.8` row to the selftest. | Fix before merge | 1 other instance — `series_key`/`labels[-1]` at `:118-120` ranks `strongest` by the same float, so `deep`/`standard` regress identically once the Pro line reaches `3.10` | `[x]` |
| 2 | Spec Gap | High | High | `commands/v-epic.md:372` | Summary | `CHANGELOG.md` [3.4.12] says of `--set-max-attempts-per-feature`: *"The halt page names it."* The §7 halt-page runbook — the one place a human is told which lever to pull at `blocked_needing_human` — names `--reset-wall-clock` and `--set-max-total-attempts` and stops there. Finding 151's own scenario (F1 parked at attempts 2/2) is precisely the halt this lever exists for, so a human following the runbook literally is left with the hand-edit that `commands/v-epic.md:29` forbids outright ("Never hand-edit an existing `epic-state.json`"). The flag is named only in `CHANGELOG.md`, in `compound-v-epic-state.py`, and in one *generated artifact* from the run that discovered it (`docs/superpowers/execution/epics/2026-09-03-glob-parity/halt-page-2026-09-03.md`) — an instance, not the template. | Add `--set-max-attempts-per-feature <N>` to the tripped-breaker bullet at `commands/v-epic.md:372`, beside `--set-max-total-attempts`, with the "a feature exhausted its per-feature cap" trigger spelled out. | Fix before merge | 2 other instances — `skills/compound-v/epic-mode.md:153` (CLI table) and `:168` (§7 runbook prose, which calls itself "every field + copy-paste commands") omit the flag too; both files were edited later in this same range | `[x]` |
| 3 | Regression Risk | Medium | Medium | `scripts/compound-v-emit-workflow.py:8505` | Inline | `resume-prepare` sets `entry["worktree"] = None` for every job without `merged.integrated`, and `commands/v-resume.md:31` orders it to run **before** the relaunch. The resume-eligibility rule — held byte-identical at `commands/v-resume.md:40` and `agents/parallel-dispatcher.md:297` — permits `codex exec resume <uuid>` only IFF the failure class is environmental **AND** "its worktree still exists at the recorded path". After `resume-prepare` there is no recorded path for any resumable job, so on the `/v:resume` path that IFF can never evaluate true and the documented codex session-resume branch is unreachable. `session_id` survives, which makes the dead branch look live. | Decide which contract wins and write it down: either exempt environmental-failure jobs with a live worktree from the `worktree`/pin clearing, or state in both copies of the rule that `/v:resume` always recreates fresh and the session-resume branch applies only outside it. | Reviewer decides | 1 other instance — the same now-unreachable rule is restated verbatim at `agents/parallel-dispatcher.md:297` | `[x]` |
| 4 | Doc | Medium | High | `agents/spec-reviewer.md:40` | Summary | The consumer contract states `recall-check` "returns **the single verdict** `tighten`". As of this range that is false: `compound-v-memory.py:1134` returns a second verdict, `"unavailable"`, whenever the scope matcher cannot be loaded. An agent holding the documented contract meets an undocumented value on the one path where the recall bridge has silently stopped working. | Update the sentence to name both values and say what to do with `unavailable` (note it and step past, as the sibling doc already says for a missing script). | Fix before merge | 1 other instance — Finding 5. Not a blanket gap: `skills/compound-v/memory.md:54,108` **does** document `unavailable`, which is what makes the two agent-facing contracts the outliers | `[x]` |
| 5 | Doc | Low | High | `agents/partition-reviewer.md:21-31` | Summary | Same gap, milder wording: this contract documents `tighten` plus "an empty result is a normal answer, and a missing script is noted and stepped past" — which is close enough that an agent will most likely read `unavailable` as "empty" and continue. That is the fail-safe direction (the bridge is escalation-only, so the loss is an escalation, not a relaxation), but it is fail-safe by luck rather than by contract, and the operator is never told the bridge was down. | Name `unavailable` explicitly alongside the missing-script case. | Nice-to-have | 1 other instance — Finding 4 | `[ ]` |
| 6 | Edge Case | Low | Medium | `scripts/compound-v-epic-state.py:3903` | Inline | `--set-max-attempts-per-feature` passed **without** `--clear-breaker` is silently ignored: `main()` reads it only inside the `--clear-breaker` branch (`:4093-4097`), so the command exits 0 having changed nothing. Its help string also breaks the sibling convention — it opens `--clear-breaker:` where `--reset-wall-clock` and `--set-max-total-attempts` both open `(with --clear-breaker)`. | Either reject the flag outside `--clear-breaker` with a usage error, or at minimum match the sibling help wording so the coupling reads the same way. | Nice-to-have | 2 other instances (pre-existing, same silent-ignore) — `--set-max-total-attempts`, `--reset-wall-clock` | `[ ]` |
| 7 | Open Question | — | Low | `scripts/compound-v-emit-workflow.py:8508-8511` | Inline | `state["phase"] = "PARTITION_VERIFIED"` is written only when `out["unpinned"]` is non-empty. A crashed run in which every job *did* integrate keeps whatever phase the crash left (`BLOCKED`, `DISPATCHED`), and `resume-prepare` reports `kept: [...]`/`unpinned: []` without correcting it. | Author: is leaving the phase untouched when there is nothing to relaunch deliberate (the run is effectively finished and `finalize-wave` owns the phase), or should `resume-prepare` normalise it? | Verify before merge | n/a — low confidence | `[x]` |
| 8 | Convention | Medium | High | `scripts/compound-v-memory.py:1064-1113` | Inline | `_scope_matches()` is a near-verbatim fork of `load_scope_matcher()` at `scripts/compound-v-integration-gate.py:417-470` — the same mkdtemp / `sys.pycache_prefix` / `spec_from_file_location` / fail-closed-on-no-cache sequence, differing only in its return convention. Its own docstring admits the duplication ("Same hardening as compound-v-integration-gate.py load_scope_matcher"). `CONVENTIONS.md:19-20` forbids forking a second copy of a canonical shared mechanism, and its cited exemplar is a cross-script import from this very file. This one is security-critical: the next hardening of the bytecode-cache defence must now be found and applied in two places, and the fail-closed selftest added here covers only one of them. | Hoist the loader into one shared helper and have both callers import it, or state in both docstrings why the fork is deliberate and pin the pair with a cross-file selftest. | Fix before merge | 1 other instance — the fork itself; both copies now need every future change | `[x]` |
| 9 | Regression Risk | Medium | High | `scripts/compound-v-memory.py:1115-1126` | Inline | Adopting the scope gate's matcher **narrows** `recall_check` silently: under the old `fnmatch`, `src/*.py` matched `src/a/b.py` and `a?b` matched `a/b`; both are now `False`. Narrower is the *correct* semantics (it is the whole point of one-matcher parity) and it is escalation-only, so the failure mode is a missed `tighten` rather than a wrong one — but a behaviour change to a routing-tighten input ships here with no `### Changed` CHANGELOG entry at all, mentioned only inside 3.4.12's stage-7 narrative. A future operator diffing recall behaviour has nothing to find. | Add a `### Changed` entry naming the narrowed cases, so the parity change is discoverable outside the stage narrative. | Fix before merge | no other instances — the other four releases in this range each carry their own `### Added`/`### Changed`/`### Fixed` heading | `[x]` |
| 10 | Bug Risk | Low | Medium | `scripts/compound-v-emit-workflow.py:8516-8517` | Inline | The superseded-receipt archive names the destination `<id>.gate.superseded-<realised_commit[:12]>.json` and moves with `os.replace`, which silently overwrites. Two crashed attempts that realised the same commit — the retry-after-crash case this path exists for — collapse onto one filename and the earlier archive is lost. The timestamp form is already written as the fallback branch, so the collision-free key is one line away. | Append the UTC timestamp unconditionally, or `os.replace` only after checking the destination is free. | Reviewer decides | no other instances — the sibling archive/rename sites in this file key on immutable realised commits that are written once | `[ ]` |

**Retracted candidate (recorded deliberately).** An earlier pass flagged
`scripts/compound-v-advisor-consult.sh:36` for pointing at `tests/test-advisor-worker-stub.sh`
while that file appeared absent — contradicting `CHANGELOG.md` [3.4.15]'s claim that both orphan
test scripts moved into `tests/` and CI now runs them. **This was a false positive.**
`git ls-tree 7dfaeeb tests/` shows both scripts present at the reviewed commit, and CI's recursive
discovery (`.github/workflows/validate.yml:351`) reaches them. The apparent absence came from a
concurrent session's *staged deletion* in the shared working tree. The CHANGELOG claim is true.
It is left here because the way the review nearly shipped it is itself the most useful finding of
this run — see dogfood note 7.

---

## Posting plan

Local mode — nothing is posted. This file is the deliverable (skill Non-Goals; Phase 7).

---

## Appendix — dogfood notes on `/v:pr-review` itself

Recorded during this run, which followed `commands/v-pr-review.md` and `skills/pr-review/SKILL.md`
literally on a hostless commit range. These are defects in the *command*, not in the reviewed code.

1. **No input mode for a commit range.** `commands/v-pr-review.md:11` and the Inputs table
   (`SKILL.md:53-57`) admit exactly three targets: PR/MR URL, PR/MR number, or empty → current
   branch vs base. A hostless `A..B` range is not one of them. I read it as local mode and
   substituted `git diff c011d6e..7dfaeeb` for the documented `git diff <base>...HEAD`. The skill
   also never says whether its `...` is deliberate (merge-base) or shorthand; on a range that
   matters.
2. **"Host available but no PR" is undefined.** `SKILL.md:59` falls back to local only when the
   CLI is missing or the remote is unknown. Here `gh` is installed and `origin` is github.com —
   the documented detection lands on GitHub mode, which then has no PR to fetch. There is no rule
   for this, and it is the ordinary case for reviewing a merged range.
3. **The documented local target produces an empty diff here.** HEAD is `main` and base detection
   (`SKILL.md:61`) resolves to `origin/main`, so "current branch vs base" is empty. The only
   runnable local review on this repo is one the skill does not document.
4. **Phase 1's exit gate cannot be satisfied non-interactively.** `SKILL.md:147`: *"user confirms
   the briefing... Do not start Phase 2 before this."* Auto Mode is defined only inside Phase 5
   (`:196-198`); Phase 6 has its own user gate (`:223`). A `--print`/subagent run is formally
   blocked twice. Auto Mode should be resolved in Phase 0 and referenced by every gate.
5. **Prime Directive 3 has no non-interactive path.** `SKILL.md:268` mandates `AskUserQuestion`
   for every judgment question; the fallback at `:278` is for "no AskUserQuestion *tool*", not
   "no user". A subagent has neither.
6. **Spec auto-discovery misses this repo's specs entirely.** `SKILL.md:81` globs `specs/*/spec.md`,
   `specs/**/spec.md`, `docs/prd/**`, `docs/specs/**`, `.scratch/**`. This repo's specs live at
   `docs/superpowers/specs/*-design.md` — matched by none of them (`docs/specs/**` is not
   `docs/superpowers/specs/**`, and the filename is `*-design.md`, not `spec.md`). A literal run
   reports "no spec available" on a repo holding eleven design specs. The stack-agnostic core is
   the part that fails first on its own repo.
7. **Local mode drops worktree isolation exactly where the skill's own rationale demands it.**
   `SKILL.md:104` justifies worktrees so a review never disturbs "the user's working tree **or
   another concurrent review**", then `:122` skips them entirely in local mode. During this run the
   working tree carried 42 uncommitted paths from concurrent sessions, including a *staged
   deletion* of a file that exists at the reviewed commit. Reading the tree instead of the ref
   produced a false finding that survived to a written draft and was caught only by an unrelated
   `git ls-tree` cross-check. When the target is a ref or range, the skill should require
   `git show <ref>:<path>` (its own documented fallback at `:121`) rather than the live tree.
8. **The findings-file template contradicts its own column spec.** The `## Findings` table header
   in `references/findings-format.md:44` has ten columns and no `Class-check`; the column
   definitions below it define `Class-check`, and `SKILL.md:218` makes it a Phase-5 exit-gate
   requirement on every High/Medium row. Copying the template verbatim yields a file that fails
   the gate. I added the column by hand.
9. **One filename for every hostless review.** `references/findings-format.md:5` fixes local mode
   to `./reviews/pr-review-findings-local.md` — no `{range}`, no date. A second local review
   silently overwrites the first. This repo already holds `reviews/pr-review-findings-6.md`, so
   the collision is one review away.
10. **The header template has no local-mode substitution.** `findings-format.md:15` is
    `# PR/MR #{n} — {title}`; local mode has neither. Undefined.
11. **Phase 3's anchor classification is ceremony in local mode.** `SKILL.md:157-162` requires
    every finding to carry Inline/Summary, whose sole purpose is routing comments — which local
    mode never posts (`:226`). Mandatory bookkeeping in the mode the skill calls cheapest.
12. **`reviews/` placement is defended but not reconciled.** `findings-format.md:5` pre-empts the
    objection; on this repo `reviews/` is neither gitignored nor one of the `docs/superpowers/**`
    artifact roots, so a review lands outside both V-memory's index and the committed audit trail
    that this project's own v2.6.4 incident exists to protect.
13. **"First match wins" cannot express a partial spec.** `SKILL.md:80` picks one spec source for
    the whole diff. Here 3.4.13 has a design doc and 3.4.11/12/14/15 have only CHANGELOG entries —
    a per-area spec map, not a winner.

**What worked, unprompted:** Phase 3.5 earned its keep. The two sub-agents ran cleanly from the
pinned inputs, and each returned a finding the other axis and I had missed — the forked fail-closed
loader (Standards) and the silent matcher narrowing plus the receipt-clobber (Spec) — while
independently confirming Finding 2 from a different direction. Keeping the reports unmerged made
the Spec agent's one inaccuracy (calling the phase rewrite "unconditional" when it is gated) easy
to leave standing as its report rather than launder into the table.
