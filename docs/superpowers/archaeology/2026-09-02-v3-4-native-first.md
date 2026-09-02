# v3.4 Native-First Code Archaeology

## Step 0 — V-memory recall (evidence, not routing)

Five queries run against `scripts/compound-v-memory.py search … --intent planning`. The index
reported itself 65 docs behind the repo (`/v:memory-refresh` not run this session) — evidence
below is what FTS5 could see, not a guarantee of completeness.

- **Epic goal / resurrection.** `docs/superpowers/specs/2026-07-26-v2.18-autonomy-mechanisms-design.md`
  (Feature A's original design), `docs/superpowers/plans/2026-09-01-v3.0-triage-tests-orchestration.md`
  Task 8 (the triage rule was *added to* `epic-goal-stop.sh`, "never a second registration — two
  blocking `Stop` registrations are undefined ordering, which is why v2.18 put both of its rules in
  ONE script"), and `docs/superpowers/preflight/2026-09-01-v3.0-1a-archaeology.md` §3.1 (the prior
  archaeology on this same hook, from the v3.0 cycle — read directly, see Phase 3 below).
- **Triage / UserPromptSubmit.** `docs/superpowers/specs/2026-09-01-v3.0-triage-tests-orchestration-design.md`
  §E3 ("the same probe pass over the installed runtime surfaced events this project was not
  using"), and a **methodology warning** worth repeating verbatim from
  `docs/superpowers/preflight/2026-09-01-v3.0-1c-docs.md`: *"`WebFetch` on the hooks page returned,
  on a second call, a confident table stating the Stop hook's `decision` field is
  `"continue" | "stop"`. This is false."* — a caution against trusting a fetched summary of the
  hooks contract over the installed binary's own reference.
- **Dashboard / observability.** `docs/superpowers/specs/2026-07-14-v2.15-observability-dashboard.md`
  (original `emit`/`serve` design) and **ADR 0004** `docs/superpowers/adr/0004-workflow-as-the-dispatch-engine.md`
  ("The native Workflow runtime becomes the dispatch engine, and the scope gate moves into the
  run" — Engine C, `phase()`/`log()`, is already the dispatch engine this spec's WS3a leans on).
- **Scorecard / memory.** `docs/superpowers/memory/routing-lessons.md` and the PRD's §5.8 (`memory/
  task-outcomes.jsonl` / `routing-lessons.md` split) — the human-curated half is explicitly
  **out of this spec's scope** and no workstream here touches it; confirmed correct.
- **Tool-failure-ledger / DIRECT landing.** `docs/superpowers/architecture/native-mechanisms.md`
  (the row this spec's Task D updates) and `docs/superpowers/specs/2026-09-01-v3.0-triage-tests-orchestration-design.md`
  §A4 (the nine auto-route predicates DIRECT landing is built on — unchanged by this spec, only
  the *attended* path's prose changes).

No stale-vs-code conflict surfaced in recall itself; the conflicts below were found by reading the
code, not by recall disagreeing with it.

## 0. A sequencing finding that governs how to read everything below

**This archaeology is being written after the plan, the manifest, and the OTHER two pre-flight
audits already exist.** Before touching any source file, `docs/superpowers/plans/2026-09-02-v3.4-native-first.md`,
`docs/superpowers/execution/2026-09-02-v3.4-native-first/manifest.yaml`, and
`docs/superpowers/library-audit/2026-09-02-v3-4-native-first.md` were all already on disk, and
`docs/superpowers/execution/2026-09-02-v3.4-native-first/state.json` already reports
`"phase": "PARTITION_VERIFIED"` with all five jobs `"pending"` — i.e. partition-review has already
run and approved the manifest. The manifest's own `audits.archaeology` field already points at
*this file's path*, before this file existed.

Normal Compound V order is archaeology (1A) → domain (1B) → library (1C) → **writing-plans** →
manifest materialization → partition-review → dispatch. Here the plan was written, and a job
partition already verified, **without this document existing to ground it.** That does not make
the plan wrong — the job bodies below turn out to be unusually precise, down to exact function
names (`_ReadOnlyHandler`, `cmd_serve`, `_FakeServer`) that could only come from having actually
read the code — but it means every finding below is a **retroactive check on an already-committed
partition**, not an input the plan author had before writing. Where a finding below implies a file
needs editing that no job's `write_allowed` currently covers (§7, §8), that is a partition gap
against an already-verified manifest, not a plan-drafting note — treat it accordingly.

---

## 1. Matrix

### 1a. The goal-rule matrix being *deleted* (hooks/epic-goal-stop.sh `_goal_rule`)

Every combination the current code checks, in order, each one a `return 1` (fall through) unless
noted. WS1 must delete every branch, not just the header paragraph describing them.

| Check | State that blocks (all must hold) | Any other value |
|---|---|---|
| `goal_arm` key present in epic-state.json | present | absent → cheap negative fast-path, no python spawned |
| epic-state CLI found + python3 present | both | either missing → rule inert |
| `--goal-status` exit code | 0, non-empty stdout | non-zero/empty → FAIL OPEN |
| `armed` | `true` | not armed → fall through |
| `session_id` on the armed record | non-empty AND `== sid` | empty → FAIL OPEN (not just fall through); mismatch → fall through |
| `arm_id` | non-empty | empty → FAIL OPEN |
| `max_continues` | positive integer | `0`, negative, non-numeric → FAIL OPEN (0 is invalid, not unlimited) |
| `should_continue` (armed ∧ ¬met ∧ ¬terminal) | `true` | false → fall through (covers BOTH "met" and "terminal-but-unmet") |
| store slot (`goal-<key>` dir) | exists with a valid counter, OR absent-and-`stop_hook_active≠true` | dir exists but counter file missing → FAIL OPEN ("store lost mid-arm"); dir absent but `stop_hook_active==true` → FAIL OPEN ("store swept") |
| counter vs max | `cnt < maxc` | `cnt >= maxc` → budget exhausted, fall through |
| counter persist (write+rename) | succeeds | fails → FAIL OPEN |

Nine independent fail-open exits plus two success paths (block-and-increment vs. fall-through).
**All eleven of these branches, and the store/digest/key-derivation machinery under them
(`_digest`, `_store_dir`'s `goal-<key>` sub-path, `_discover_state`, `_locate_cli`), are what "delete
`_goal_rule`" means in practice** — not one function name, an entire fail-open decision tree.

### 1b. The new UserPromptSubmit auto-triage matrix (WS2, replacing the reminder)

| prompt type | session has a covering record? | run active? | today (reminder) | WS2 (scores + writes) |
|---|---|---|---|---|
| slash command | — | — | silent | silent (unchanged gate) |
| short question (≤200 chars, ends `?`) | — | — | silent, session stays armed | silent, session stays armed (unchanged gate) |
| long / no-`?` question, e.g. "walk me through how X works" | no | no | **nudges once** (cheap, no write) | **mints a real scored pre-eval record** (see §2, §7 — this is new exposure, not a bug, but the spec must own the tradeoff) |
| genuine change request | no | no | nudges once | mints record, tier in `additionalContext` |
| any prompt | **yes** | — | silent (marker or record either way) | silent (`_has_session_record` is now the sole gate — see §3) |
| any prompt | no | **yes** | silent ("cannot contaminate the run") | must stay silent — same check, now gating a real write instead of a reminder |
| engine call | — | — | n/a | success / `needs_t3` / **failure-or-timeout** — only the last of three falls back to the old reminder text (spec §WS2.4) |

### 1c. DIRECT landing matrix (WS4 — human-attended vs. not)

| Tier | In auto-route class (predicates 1–6)? | Attended (human sees diff)? | Path today | Path after WS4 |
|---|---|---|---|---|
| DIRECT | yes | either | `/v:triage --land` (Phase L, CAS) | **unchanged** — Phase L stays general, both attended and unattended may use it |
| DIRECT | no | attended | "implement, then offer it to the user as usual" (commands/v-triage.md:311, vague) | explicit: implement, run the floor, commit on the branch, include the pre-eval artifacts (spec WS4 exact text) |
| DIRECT | no | unattended (`/loop`, `/schedule`, `--permission-mode dontAsk`) | same vague line, no landing gate available (not in the class) | **spec does not name this cell.** An unattended session hits a DIRECT-not-in-class change with no human to "offer it to" and no `--land` eligibility (predicates 7–9 require the class). Worth the plan author confirming this cell was intended to stay exactly as under-specified as it is today, since WS4 tightens the *attended* cell's prose but says nothing about this one. |
| SCOPED / FULL | n/a | either | `/v:orchestrate` / full pipeline | unchanged |

---

## 2. Shared State

### 2a. `docs/superpowers/memory/triage-outcomes.jsonl` — write path (THE finding)

```
run_preeval()                                          scripts/compound-v-preeval.py:987-1145
  └─ build_record(...)                                  :1115  (no binding kwarg passed today)
  └─ write_record(...)                                   :1117
  └─ if new record: tm.append_predicted(...)             :1121-1131
       tm = _triage_mod() = _load_sibling(
         "compound-v-triage-outcomes.py", …)              :287-288
         └─ compound-v-triage-outcomes.py:append_predicted(...) :300-325
              └─ _append_event(...) :287-297
                   └─ _update_memory().append_line(path, obj)   :297
                        _update_memory() = _load_sibling(
                          "compound-v-update-memory.py", …)     :176-183
```

**Set:** every time `run_preeval()` produces a *new* record — today only from `/v:triage` (human,
occasional); after WS2, from **every UserPromptSubmit that clears the existing gates and has no
covering record yet** (§1b), i.e. routinely, once per session.

**Read:** `compound-v-triage-outcomes.py`'s `tier2_lookup` (Tier-2 historical corroboration, called
from inside `run_preeval` itself, `:1071-1076`) and predicate 9's circuit-breaker check
(`compound-v-triage-outcomes.py breaker`, referenced from `commands/v-triage.md` table row 9).

**Gap:** `compound-v-triage-outcomes.py:176-183` loads `compound-v-update-memory.py` as a sibling
module specifically to reuse its `append_line` — the docstring says outright: *"we reuse its
`append_line` … never recopy it."* WS3b's Task C literally does `git rm
scripts/compound-v-update-memory.py`. The failure is not graceful: `_load_sibling` calls
`importlib.util.spec_from_file_location` + `exec_module` on a path that no longer exists, which
raises (unhandled) inside `run_preeval`'s `append_predicted` call — which has no `try/except`
around it (`:1119-1131`). Every call to the new `triage` subcommand, and every remaining call from
`/v:triage`'s own T2, throws.

### 2b. `compound-v-preferences.py` — the SAME dependency, unconditionally

```
scripts/compound-v-preferences.py:93-94 (MODULE LEVEL, executes on import/invoke, not lazily)
  _cv_update = _load_sibling("compound-v-update-memory.py", "cv_update_prefs")
  append_line = _cv_update.append_line
```

This is a **module-level** statement — it runs the instant `compound-v-preferences.py` is imported
or executed at all, including by its own `--selftest` (confirmed present, `:894-898`), which means
CI's "Run ALL script selftests" step (`.github/workflows/validate.yml:297-311`, globs `scripts/*.py`
for anything containing `--selftest`) runs it. Deleting `compound-v-update-memory.py` makes
`python3 scripts/compound-v-preferences.py --selftest` fail on import, unconditionally, in CI.

**This directly contradicts the spec's own decision #3** ("`preferences` stays as is") and its
own global constraint ("Existing tests either keep passing or are rewritten…" / "every `--selftest`
green under CI's 3.9 floor"). Neither is a hypothetical interaction — both are confirmed by reading
the two files' own import statements.

**Neither job owns the fix.** `triage-hook`'s `write_allowed` has `scripts/compound-v-preeval.py`
but not `scripts/compound-v-triage-outcomes.py`. `observe-native`'s `write_allowed` has
`scripts/compound-v-update-memory.py` (to delete it) but not `scripts/compound-v-triage-outcomes.py`
or `scripts/compound-v-preferences.py`. Whichever of `triage-hook` / `observe-native` merges last
(they run `parallel`, no `depends_on` between them) either hits this immediately in its own
selftest run, or — worse — merges clean and leaves the *other* job's later merge to break it with
no attribution.

### 2c. `docs/superpowers/pre-eval/*.json` — the coverage-binding contract

`build_record`'s `binding` kwarg (`compound-v-preeval.py:754-810`) already exists and is
**by-construction digest-safe** (binding fields are folded in before the record's own integrity
digest is computed) — this is real, working, in-repo machinery, not something WS2 has to invent.
What does NOT exist: a way to get a `binding` dict into `run_preeval()` without external
monkey-patching. `run_preeval` calls the bare module-level name `build_record` (`:1115-1116`) with
no `binding=` argument; today's ONLY producer of a bound record is `commands/v-triage.md` T2, which
achieves it by reassigning `pe.build_record` to a wrapper **from outside the module**
(`commands/v-triage.md:178-183`) before calling `run_preeval`. That trick exists **because T2 is
external** to the module. A `triage` subcommand living natively inside `compound-v-preeval.py` has
no such constraint and should thread a `binding=None` parameter through `run_preeval` to its
internal `build_record` call instead of reimplementing the external monkey-patch inside the module
that owns the function it would be patching. (`build_record`'s own docstring already promises
byte-identical output when `binding` is absent — "every call this module makes" — so adding the
parameter cannot regress the four other CLI callers below.)

### 2d. `autonomy.watch` / `watcher_registry` / `resume_count` in `epic-state.json` — read by dashboard.py

```
scripts/compound-v-dashboard.py:708-728 (rendering)
  st = rec["state"]
  auto = st.get("autonomy") or {}
  if auto:                                    # true for every marathon epic, watch or not
      watch_on = bool(auto.get("watch"))       # WS1 removes the writer of this key
      watchers = st.get("watcher_registry")    # WS1 removes the writer of this key
      "resume_count"                           # WS1 removes the writer of this key
      → renders "watcher armed: off" always, and silently drops the resume_count metric
        (`if val is not None` at :721-724 skips it gracefully — no crash)
scripts/compound-v-dashboard.py:1135-1191 (its OWN selftest)
  fabricates {"autonomy": {"watch": True, "max_resume_count": 20}, "resume_count": 2,
              "watcher_registry": [{"provider": "cron", ...}]}
  asserts "watcher armed" appears in the rendered HTML
```

Degrades gracefully (no crash, no wrong number) but becomes dead code the moment
`--init --stance marathon` can never again produce those keys, and the selftest keeps exercising a
state shape the rest of the system can no longer emit. `scripts/compound-v-dashboard.py` **is** in
`observe-native`'s `write_allowed`, so this is fixable inside that job's lane — but WS3a's job body
(C1) only names `_ReadOnlyHandler`/`cmd_serve`/etc. for deletion and never mentions this panel or
its selftest, so as written the body gives the implementer no instruction to touch it.

---

## 3. Sibling Code

### 3a. `hooks/epic-goal-stop.sh` — full read (911 lines, header included)

Three rules, evaluated in strict order, exactly one JSON response or none per event (see §1a for
the goal rule's own matrix). Two fail-open mechanisms are load-bearing and **must survive verbatim**:
(a) `hooks.json` registers the script as `"<script>" || true`; (b) an unconditional `trap 'exit 0'
EXIT` plus stdout-suppression-unless-`hook_main`-returned-0. Both are asserted by
`tests/test-epic-goal-stop.sh` in both directions (a parse error above vs. below the trap line).

**The spec's removal instructions under-scope the header surgery.** WS1 says: *"the header's
Feature A text and decision-table rows 4 and the goal-related parts of 7"*. Reading the actual
header end to end:

- The **decision table** (`:49-70`) has exactly 7 numbered rows. Row 7 is `"otherwise ...
  exit 0, silent"` — it carries **no goal-related text at all**. The goal-referencing cross-links
  actually live in rows 5 and 6 ("only if the goal rule did not block" / "only if neither rule
  above blocked"). "Row 7" appears to be a miscount; the plan should point at rows 5–6's
  cross-references, not row 7.
- **"BOUNDS, HONESTLY RANKED"** (`:129-132`) is entirely about the goal rule — *"Our own
  `continue_count` is THE bound … The epic circuit breakers remain unchanged and authoritative
  above both"* — and is not named in the removal list at all. Left in place, it becomes a stale
  claim about a variable (`continue_count`) the file no longer has.
- **"STORE LOSS, AND THE ONE CONSERVATIVE EDGE IT COSTS"** (`:110-120`) is entirely goal-rule
  content (arm/re-arm, `max_continues`, the slot-directory-vs-counter-file distinction) and is not
  named either.
- **The `stop_hook_active` paragraph** (`:122-127`) says its flag is used as corroborating
  evidence "in one place: see 'store loss' below" — that one place is the goal rule. Once the goal
  rule is gone, `sha`/`stop_hook_active` is computed and logged (`hook_main:867-869`) but consumed
  by nothing; the paragraph explaining why it's read becomes a pointer to deleted code.

None of these three paragraphs is optional cleanup — each makes a factual claim about code that
will no longer exist. All three sit inside `epic-goal-stop.sh`, which **is** in `epic-native`'s
`write_allowed`, so this is a scoping gap inside an already-owned file, not a missing grant.

**A second, cross-document naming collision worth pinning down before rewriting the header.** The
current header (`:2-3`) defines "Feature A" = the goal rule and "Feature B" = the pipeline-bypass
rule (rule 3, `_enforcement_rule`) **only** — NOT the triage gate (rule 2), which has no letter in
this file at all. `docs/superpowers/architecture/native-mechanisms.md` (line 39, part of this same
release's own grounding) uses "Feature B" differently — *"хук — оставить себе только Feature B
(триаж-гейт и обход пайплайна)"*, i.e. Feature B = triage gate **and** bypass rule *combined*. The
v3.4 spec's own Q&A table adds a third reading: *"Feature B (triage gate)"* — Feature B = triage
gate *alone*. Three documents, three different scopes for the same label. The manifest's mechanical
instruction ("`hook_main` calls `_triage_rule` then `_enforcement_rule` only") sidesteps the
ambiguity by not relying on the label — but whoever writes the *replacement* header prose needs to
either retire the letter-naming scheme (the goal rule it names is being deleted anyway) or define
it once, explicitly, rather than reusing "Feature B" in a fourth sense.

### 3b. `hooks/triage-prompt-nudge.sh` — full read (371 lines, header included)

This hook's header is not incidental commentary — it is a **deliberate, multi-paragraph design
argument for never writing a record**, load-bearing enough that it names the specific failure mode
by name: *"an unguarded hook mints a record for 'status?', for 'what does this do?', for every
mid-run check-in. Each spurious record lands in `docs/superpowers/memory/triage-outcomes.jsonl`
(the stream task-2's circuit breaker computes its rolling rate from)…"* (`:20-24`), and states the
rule in caps: *"THIS HOOK NEVER WRITES A RECORD, NEVER COMMITS, AND NEVER RUNS `/v:triage`."*
(`:27`).

WS2 reverses exactly this. The mitigating detail — confirmed by reading `hook_main` line by line
(`:230-364`) — is that the two filters this old argument was written around (**not a slash
command**, `:279`; **not a short question ≤200 chars ending `?`**, `:281-299`) are kept verbatim by
the spec ("keeps … every gate it has today"), and the **new** gate (`_has_session_record`, `:190-207`)
still fires **at most once per session** exactly as the retired marker did — so the *frequency*
argument in the old header (spurious records "for every mid-run check-in") is not reopened; the
per-session cap is preserved by a different mechanism. What genuinely changes, and what the old
header explicitly reasoned should not happen, is: the **first** qualifying prompt of a session that
is neither a slash command nor a short question — including an informational prompt like "walk me
through how the epic system works" that is long or doesn't end in `?` — now unconditionally runs
the full scoring engine and writes a real, taxonomy-scored record plus a `triage-outcomes.jsonl`
append, silently. That is a genuine widening of what "no covering record" used to cost (a free-text
reminder) to what it now costs (a real classification + a durable file write, feeding the exact
circuit-breaker rolling rate the old header worried about contaminating). Whether that tradeoff is
accepted is a spec decision to make explicitly, not an archaeology verdict — but the file's own
prior design rationale argued against it by name, and the spec text does not currently address it.

Three separate places assert the "never writes a record" claim and all three go stale together:
this hook's own header (`:13-28`), `hooks/hooks.json`'s `$comment_native_points`
(*"triage-prompt-nudge.sh is a REMINDER that never writes or commits a record"*, line 5), and
`docs/superpowers/architecture/native-mechanisms.md` line 20 (which quotes the header's own
capitalized sentence back at itself, with a line-number citation, as evidence the hook is
`⚠`-graded). `hooks/hooks.json` **is** in `triage-hook`'s `write_allowed`; the manifest job body
(B4) mentions it only for the unrelated `PostToolUseFailure` deletion, not for this comment.
`native-mechanisms.md` is Task D's job (docs-release), which runs after triage-hook merges —
sequencing is fine there, but the *content* of the update needs to know this specific sentence is
now false, not merely "row upgraded from ⚠ to ✅."

### 3c. `commands/v-triage.md` T2/T3/T4/Phase L — full read of the extraction that becomes the new `run_preeval` behavior

T2 (`:121-285`) is the exact orchestration the new `triage` subcommand must reproduce: bind via a
`build_record` wrapper (see §2c), call `run_preeval`, then compute predicates 1–6 from the record
plus a fresh `match_auto_route` call and an `is_test_path` heuristic (`:218-233`) — **these two
helper computations are not currently inside `compound-v-preeval.py` or `compound-v-taxonomy.py`;
they live only in this markdown file's inline script.** The `triage` subcommand needs its own copy
or import of `is_test_path` (predicate 6) and the `match_auto_route` call pattern (predicates 4–5)
— not just `run_preeval` — to print the same six predicates the spec's JSON shape promises
(`predicates:[…]`).

T4 (`:306-313`) has **two** DIRECT bullets, not one: "DIRECT, in the class" (→ `--land`, unchanged
by WS4) and "DIRECT, not in the class" (→ the vague "offer it to the user as usual" line WS4
replaces). The manifest's B6 instruction ("T4's DIRECT sentence →") is singular; it is the second
bullet (line 311) that changes. The first (line 310) must be left alone — an implementer skimming
for "the DIRECT line" could plausibly touch both or the wrong one.

Phase L's extraction test (`tests/test-triage-landing.sh:74-98`) locates the heredoc by scanning
for the literal line `V_TRIAGE_ID=… python3 - <<'PY'` and a terminating bare `PY`, **not** by the
`## Phase L` heading text. **Confirmed safe:** WS4's heading rename ("Phase L — the landing gate" →
"Phase L — unattended landings only") cannot break this extraction, since the extractor never looks
at the heading at all. Worth stating precisely because it was a real thing to check, not assume.

### 3d. CLI wiring for the new `triage` subcommand — `compound-v-preeval.py:main` (`:1151-1178`)

`main(argv)` is flat-flag argparse today, no subparsers, with exactly one existing precedent for a
pre-argparse dispatch: `if "--selftest" in argv[1:]: return _selftest()` (`:1152-1153`) runs
**before** the `ArgumentParser` is even constructed. Adding `triage` as a **positional subcommand**
(`compound-v-preeval.py triage --request-file F …`) needs the same kind of early short-circuit —
today's parser defines zero positional arguments, so `argv[1] == "triage"` would otherwise be
rejected by argparse as an unrecognized positional before ever reaching the new logic. New flags
the subcommand needs — `--request-file`, `--request-env`, `--session-id` — do not exist on the
current parser at all and must be added fresh; `--repo` and `--t3-category` already exist and can
be reused with identical semantics. **Four other callers** already invoke this CLI in its current
flag-only form and must keep working unmodified: `scripts/compound-v-fastpath-run.py`,
`skills/compound-v/cross-model-review.md`, `skills/backend-launcher/SKILL.md`,
`tests/v2.9-e2e/test_fastpath_and_escalation.py` (confirmed by repo-wide grep, none of them use a
`triage` positional today, so none collide — but the wiring change must not perturb their existing
`--score-only` / `--cross-model-review` / `--request` invocations).

---

## 4. External APIs

None in scope for this feature at the code-archaeology layer. Every mechanism this spec adopts
(`ProposeGoal`, `/loop`, `/schedule`, `UserPromptSubmit`, `hookSpecificOutput.additionalContext`,
`ScheduleWakeup`, `CronList`/`CronDelete`) is Claude Code's own native surface, probed against the
installed binary per the spec's own "probed 2026-09-02" citations — that verification is the
library/doc-validator's lane (Phase 1C), and `docs/superpowers/library-audit/2026-09-02-v3-4-native-first.md`
already exists at the path the manifest names (see §0). Re-deriving that verification here would
duplicate it rather than add to it.

---

## 5. Regression Surface

| Path that works today | Breaks if… | Who notices |
|---|---|---|
| `/v:triage <request>` (T2) | `compound-v-update-memory.py` is deleted without a replacement `append_line` home | Every invocation, immediately (unhandled exception inside `run_preeval`) — §2a |
| `python3 scripts/compound-v-preferences.py --selftest` | same deletion | CI's "Run ALL script selftests" step, red, on the FIRST run after Task C merges — §2b |
| `/v:triage --land` (Phase L, CAS commit) | none identified — WS4 explicitly leaves Phase L's code untouched and the extraction test doesn't key on the heading being renamed | — (confirmed safe, §3c) |
| Marathon epics' dashboard render (`/v:dashboard emit`) | nothing crashes; the "marathon / watch" panel silently stops being able to show a real watcher count for any epic created after 3.4.0 | Nobody — it degrades to a permanent "off" with no error, which is the failure mode this project's own dogfood record on v2.14.1 calls "false-green" — §2d |
| `enforcement.triage_gate` Stop-time gate (rule 2, unchanged) | nothing in this spec touches it directly, but it now runs *after* records are being minted much more often by the UserPromptSubmit hook, so its "no covering record" condition will empirically fire less often across a session — not a bug, but the two mechanisms' interaction is now closer and worth the plan author noting, since a currently-passing test asserting the triage gate's coverage logic was written against a world where records were rare | Anyone reading `tests/test-epic-goal-stop.sh`'s "does not burn the marker on a question" assertions, which the spec already flags for a text-only rename — the *semantics* change is broader than the text change |
| CI's `.github/workflows/validate.yml` "epic-watch.py selftest" / "headless-shim.py selftest" named steps (`:284-288`) | the two files no longer exist | The named steps themselves fail to find the script and error, not silently skip — this IS in WS1's removal list (A4), just flagging that the named-step deletion and the file deletion must land in the same commit or CI redlines in between |
| `CONVENTIONS.md:17`'s citation `.github/workflows/validate.yml:225-244` | the two CI steps it cites shift by ~10 lines once epic-watch/headless-shim steps above them are deleted | Nobody automatically — this is a generated, cited doc whose own preamble insists citations trace to real evidence; the manifest instruction ("drop 'epic-watch / headless-shim'") doesn't mention re-verifying the line range |

---

## 6. DRY Findings

**The `_load_sibling` pattern is already the repo's established way to share code between these
scripts** — `compound-v-preeval.py`, `compound-v-triage-outcomes.py`, and
`compound-v-preferences.py` all use the identical `importlib.util.spec_from_file_location` +
`exec_module` idiom to reach into a sibling script for one or two functions (`fts5_escape`/`redact`
from `compound-v-memory.py`; `append_line` from `compound-v-update-memory.py`; taxonomy/localize/
churn/config helpers from their own siblings). This is a real, working DRY discipline, not
duplication — the problem in §2a/2b is not that sharing exists, it's that WS3b deletes the file
being shared **without relocating the one function two other modules import from it**, and no job
in the current partition owns making that call. This is not "add a third copy" territory — it's
"the plan must say where `append_line` lives after `compound-v-update-memory.py` is gone, and grant
write access to whichever file(s) end up needing edited to keep pointing at it" (`compound-v-triage-outcomes.py`
and `compound-v-preferences.py` at minimum).

No other duplication found: the new `triage` subcommand's predicate-1–6 logic (§3c) is presently
un-DRY in the opposite direction — it exists only as inline markdown script, not as importable
code — so moving it into the module is consolidation, not new duplication.

---

## 7. Design constraints for the spec

Non-negotiable, derived from the above:

1. **The `compound-v-update-memory.py` deletion (WS3b) cannot land as a bare `git rm` without
   first relocating `append_line`.** Two runtime importers depend on it today —
   `compound-v-triage-outcomes.py` (lazy, breaks on the first new pre-eval record after deletion)
   and `compound-v-preferences.py` (immediate, breaks its own `--selftest` in CI on import). This
   directly contradicts the spec's own decision #3 ("preferences stays as is") and its global
   "every `--selftest` green" constraint. Whatever job performs the deletion must also either grant
   itself write access to both dependent files and fix their imports, or the deletion must be
   deferred to a job that owns all three files together.
2. **`run_preeval()` needs a `binding=None` passthrough parameter**, threaded to its internal
   `build_record(...)` call, rather than the new native `triage` subcommand reimplementing T2's
   external module-level monkey-patch of `build_record` inside the very module that defines it.
   `build_record`'s own docstring already guarantees byte-identical output for every existing
   caller when `binding` is absent.
3. **`hooks/epic-goal-stop.sh`'s header rewrite must also remove the "BOUNDS, HONESTLY RANKED" and
   "STORE LOSS" paragraphs and the `stop_hook_active`-corroboration sentence** (§3a) — not just the
   "Feature A" intro and decision-table row 4. All three are entirely goal-rule content not named
   in the spec's current removal list, and left in place they reference a variable
   (`continue_count`) and a rule that no longer exist.
4. **Do not reuse "Feature B" for a fourth meaning when rewriting the header.** Three existing
   documents already disagree on its scope (§3a); the cleanest resolution is to retire the
   letter-naming scheme entirely once the goal rule it distinguishes from is gone.
5. **`hooks/triage-prompt-nudge.sh`'s header needs a full prose rewrite, not just its shell body.**
   The current header's central claim — "THIS HOOK NEVER WRITES A RECORD" — is being made false by
   design, and the header presently argues, by name, against exactly what WS2 does (auto-minting a
   record on an unrecognized informational prompt). The spec should explicitly decide whether that
   old argument's concern (a real, taxonomy-scored record and a `triage-outcomes.jsonl` append for
   a prompt that was never a change request) is accepted, not merely overwrite the text that raised
   it. The same stale claim also lives in `hooks/hooks.json`'s `$comment_native_points` (line 5) —
   both need to change together.
6. **The new `triage` subcommand needs `is_test_path` (predicate 6) and the `match_auto_route`
   call pattern (predicates 4–5), not just `run_preeval`,** to print the same six predicates the
   spec's own JSON shape promises — these currently exist only as inline script in
   `commands/v-triage.md`, not as importable code anywhere.
7. **Wiring `triage` as a CLI subcommand needs an early dispatch before `main`'s flat argparse
   parser is built** (the file's own `--selftest` short-circuit is the precedent), plus three new
   flags (`--request-file`, `--request-env`, `--session-id`) that do not exist today — while
   leaving the four other existing callers' flag-only invocations (§3d) untouched.
8. **`scripts/compound-v-dashboard.py`'s "marathon / watch" panel and its selftest fixture (§2d)
   need an explicit decision** — leave it silently dead (documented as such) or remove it in the
   same job that already owns the file for the `serve`-mode deletion. As written, no job body
   mentions it.
9. **T4's DIRECT-bullet edit (WS4) targets `commands/v-triage.md:311` specifically** ("DIRECT, not
   in the class"), not line 310 ("DIRECT, in the class," which routes to the unchanged `--land`
   gate) — the spec's singular "T4's DIRECT sentence" phrasing should name the line precisely to
   avoid an implementer touching or merging both.
10. **`CONVENTIONS.md:17`'s cited line range into `.github/workflows/validate.yml` will go stale**
    once the two named CI steps above it are deleted (§5) — the edit should re-verify the citation,
    not just the prose ("epic-watch / headless-shim" → the pair named).
11. **`hooks/hooks.json`'s `PostToolUseFailure` block is the last key in the `hooks` object** — its
    removal must also drop the trailing comma after the preceding `PreCompact` block, or the file
    stops being valid JSON; validate with a parser, not by eye.

---

## 8. File Touch Map

From the manifest already on disk (`docs/superpowers/execution/2026-09-02-v3.4-native-first/manifest.yaml`),
plus two files this audit found undeclared (marked below).

**Job `epic-native`:** `hooks/epic-goal-stop.sh` · `tests/test-epic-goal-stop.sh` ·
`scripts/compound-v-epic-state.py` · `scripts/compound-v-epic-watch.py` (deleted) ·
`scripts/compound-v-headless-shim.py` (deleted) · `commands/v-epic.md` · `commands/v-init.md` ·
`commands/v-onboard.md` · `commands/v-status.md` · `skills/compound-v/epic-mode.md` ·
`docs/superpowers/loops.md` · `.github/workflows/validate.yml` **SHARED RESOURCE** (CI config,
order/format matters) · `CONVENTIONS.md` **SHARED RESOURCE** (generated/cited doc, §7.10).

**Job `triage-hook`:** `scripts/compound-v-preeval.py` · `hooks/triage-prompt-nudge.sh` ·
`hooks/tool-failure-ledger.sh` (deleted) · `hooks/hooks.json` **SHARED RESOURCE** (single registry
for every hook in the plugin; malformed JSON here breaks every hook, not just this one) ·
`tests/test-native-points.sh` · `commands/v-triage.md` · `commands/v-orchestrate.md` ·
`skills/compound-v/phase-preeval.md`.

**Job `observe-native`:** `scripts/compound-v-dashboard.py` · `scripts/compound-v-scorecard.py` ·
`scripts/compound-v-update-memory.py` (deleted — **not safe as scoped**, §7.1) ·
`scripts/compound-v-emit-workflow.py` · `commands/v-dashboard.md` · `commands/v-collect.md` ·
`agents/parallel-dispatcher.md` · `skills/compound-v/routing-policy.md` ·
`skills/compound-v/memory.md`.

**Undeclared in any job, but required by §7.1's fix:** `scripts/compound-v-triage-outcomes.py`
**SHARED RESOURCE** (imported by both `compound-v-preeval.py`'s `run_preeval` and, transitively,
predicate 9's breaker check — a bug here affects every triage decision, not one caller) ·
`scripts/compound-v-preferences.py` (must at minimum re-point its `append_line` import; currently
owned by no job).

**Job `docs-release` (serial, depends on all three above):** `README.md` · `CHANGELOG.md` ·
`.claude-plugin/plugin.json` **SHARED RESOURCE** (version lockstep with marketplace.json) ·
`.claude-plugin/marketplace.json` **SHARED RESOURCE** · `skills/compound-v/SKILL.md` ·
`docs/superpowers/architecture/native-mechanisms.md` · `docs/superpowers/architecture/2026-09-02-viability-audit.md`.

**Job `spec-review` (serial, depends on docs-release):** writes only
`docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review.md`; reads everything (`**`).
