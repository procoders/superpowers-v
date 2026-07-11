# v2.8.0 — Hardening + Structural Anti-Anchoring — Design

**Status:** approved in conversation 2026-07-11 (Oleg). "ок" on the exact scope below;
`/v:recon` command explicitly REJECTED by the user (no new commands — plain-language ask +
freshness rule + hook backstop cover its use cases).
**Driver:** five-line max-effort audit of v2.7.0 (2 Fable + 1 dogfood + 2 Codex@xhigh) —
68 raw findings. Full registries live in the three audit docs:
`docs/superpowers/{archaeology,expert,library-audit}/2026-07-11-v2-8-hardening.md`.
Findings are cited below as `A#` (archaeology), `E#` (expert/design).

## Goal

Fix everything the audit proved wrong (two reproduced scope-gate exploits, one unwired
contract, one self-contradictory epistemic contract, a body of non-executable guidance),
plus four accepted improvements: a real hook backstop for Trigger 0, codex-only `xhigh`
effort, the directions-late anti-anchoring protocol, and a recon-outcomes stream.

## Non-goals (explicit rejections, arbitrated)

- **No `/v:recon` command** (user decision). TROUBLESHOOTING gains one line: recon can be
  requested in plain language; the freshness rule fixes the stale-doc-suppression case.
- **No adversarial fixtures in CI** for the CHANGELOG guard (local suite suffices).
- **No fresh-context ideator** (over-engineering; directions-late + honest residual-risk
  note instead).
- **No recon outcomes in the routing scorecard** — separate stream, never a routing input.
- **No new agents, no new servers, no upstream Superpowers edits** (standing invariants).

## Workstream 1 — Script fixes (all reproduced; fixes verified in audit)

1. **scope-check**: add `--no-renames` to the diff argv (A1, rename bypass); per-changed-path
   symlink check — `os.path.islink()` and realpath escaping the repo/worktree root ⇒
   violation (A2). New selftest cases for BOTH exploits.
2. **epic-state**: `f.get("status")` in `next_feature` (no KeyError on hand-made state);
   fix the tautological `--next` exit-code branch to intentional behavior with a comment (A7).
3. **memory.py**: catch `sqlite3.DatabaseError` at `open_db` call sites → clean
   "index corrupt — delete <path> and re-run refresh", exit 1 (A8).
4. **supervisor**: catch `FileNotFoundError` from Popen → clean message, exit 127 (A9).
5. **lint-frontmatter**: path-class presence gate — `agents/`, `commands/`, `skills/*/SKILL.md`
   MUST have frontmatter, other .md exempt (A4); accept closing `---` at EOF without trailing
   newline (A6); use `path.parts` not substring for the commands/ exemption (A6);
   **enforce `model: opus` on `agents/*.md`** to match the documented policy (A5) —
   verify the current tree passes before landing.
6. **effort vocabulary `xhigh`, codex-only** (A3, E-improvements): `resolve-model.py`
   (accept `xhigh` iff backend codex, reject otherwise with a clear error), `validate-
   manifest.py` (same rule), `run-codex-worker.sh` + `codex-review.sh` case guards,
   adapter-codex.md + execution-manifest.md prose. Selftests updated in lockstep.

## Workstream 2 — phase-0-recon.md contract hardening (E: C1 1–20, C2 1–5; A16–18, A20)

Rewrite the authority doc so no step requires invented policy:
- **Eligibility:** evaluate before EVERY feature brainstorm; gates 1–3 are the complete
  list (kill the "session grounding" phrasing). Announce Phase 0 only when the gates decide
  to RUN; skips emit the one-line `RECON skipped (<gate>)` log, no announcement.
- **Gate 1 narrowed:** skip only when the change cannot alter a shipped artifact, runtime
  behavior, release semantics, security/compliance posture, availability, or user-observable
  performance. Tool choices/migrations/version questions are NOT plumbing.
- **Gate 2 executable:** open the top results (excluding `memory`-type jsonl rows); strong
  hit = same product/domain AND same task class AND current framework/runtime constraints
  AND fresh (volatile material — libraries, APIs, regulations, availability, best practices —
  older than ~30 days degrades to partial: evidence, not skip-authority). Rank alone never
  suffices. When unsure → weak hit, continue to gate 3. If the search warns the index is
  behind → refresh first. Memory command missing/nonzero/invalid JSON → `KB=unavailable`,
  warn once, continue; never infer a hit from a failed lookup. **Epic rule:** sibling epic
  recon = partial by default; strong only if it covers the feature-specific delta.
- **Gate 3 fail-closed:** absent file/key = documented defaults; malformed JSON/wrong type/
  unknown enum = warn + `deep_research=ask` (never auto) + `batch_elicitation=false` for the
  session. `off` = no external recon; local recall may still surface (stated). Offer:
  one blocking choice; cancel/timeout/empty/unrelated reply = skip; narrowed-scope needs
  nonblank text (ask once, then skip); omit unavailable engines from the copy; a declined
  deep-research with accepted quick pass = Engine B.
- **Engine ladder:** bounded delay with per-rung timeouts (never indefinite); at most one
  engine COMPLETES; failed A may fall to B with both attempts recorded; incomplete A
  discarded unless individually sourced (`partial`); WebSearch denial/quota: no retry,
  partial success → `PARTIAL RECON`, report the real reason. Engine B bound: 3–6 (harmonized).
- **Output contract:** anti-anchoring header + exactly FOUR verbatim `##` sections, with
  FACTS/CONSTRAINTS split into **VERIFIED** (primary-source, provisionally binding) vs
  **UNVERIFIED LEADS** (must become questions until 1B/1C validate) — resolves the
  binding-vs-unverified contradiction. Claim→source ids (`[F1]`, accessed date, exact claim;
  "verified manually" names the artifact). Directions: at least 2, prefer 3, materially
  divergent, explicitly non-exhaustive (template line given). Slug rule (effective scope;
  lowercase; unicode-normalized; non-alnum→`-`; ≤60 chars; hash fallback; repo-local date);
  create the directory; never overwrite — collision gets a unique suffix; no front-matter.
  Commit: separate `git add -- <path>` then `git commit -m "docs(recon): <topic>" -- <path>`
  (no editor, no `&&`); on failure announce "written but not committed: <reason>" and
  continue. **Store the exact recon path in the brainstorm's working state and the spec's
  metadata; directory scanning is fallback-only.**
- **Directions-late protocol (structural anti-anchoring):** the brainstorm first works from
  VERIFIED constraints + QUESTIONS only; produces ≥3 first-principles proposals including
  one that deliberately rejects the recon framing; only then reads SUGGESTED DIRECTIONS as
  a coverage/novelty check. Residual anchoring risk stated plainly.
- **recon-outcomes stream:** every gate decision appends one line to
  `docs/superpowers/memory/recon-outcomes.jsonl`
  (`{ts, topic, outcome: fired|plumbing_skip|kb_skip|off|declined|no_engine|saved, engine,
  path, consumed}`) — committed with the recon doc when one exists; NEVER a routing input.

## Workstream 3 — brainstorm-elicitation.md hardening (E: C1 21–27, C2 6–7; A19)

- **Checkpoint rule:** at each design checkpoint (whenever the interviewer plans its next
  questions), list candidate questions, build the pairwise dependency graph (edge = either
  answer can alter the other's wording/options/necessity/shared budget **or** seeing one
  group's framing could plausibly shift another answer — the psychological co-presence
  test), batch only isolated nodes, recompute after every sequential answer.
- **Gate restructure (arbitrated):** independence+count+config gate BATCHING; companion
  acceptance gates only the companion SURFACE; the fallback ladder picks the surface
  (companion → harness structured-question tool → one-at-a-time). Overflow: ≤5 eligible at
  one checkpoint, rest sequential, no second batch from the same checkpoint.
- **Acceptance observable:** accepted = explicit yes in THIS conversation AND a recorded
  `state_dir`; unknown ⇒ companion unavailable. Companion runtime failures descend the ladder.
- **Transactional answers:** namespaced ids (`data-choice="group:option"`, globally unique);
  multiselect = toggle replay in timestamp order; read+parse events BEFORE any screen push
  (terminal submission is the completion barrier); per-group resolution (explicit terminal
  answer overrides that group; unmentioned groups keep event values; acknowledgements
  override nothing; ambiguity → re-ask that group sequentially); never infer defaults for
  unanswered groups (sequential or explicitly deferred).

## Workstream 4 — Trigger 0 hook backstop (new; E-library #2)

A new hook fires on the `Skill` tool invoking `superpowers:brainstorming` and injects a
one-line reminder to run the Trigger 0 gates (idempotent: "if not already done"). Build task
MUST live-probe the installed Claude Code first: prefer `PreToolUse` if it injects
`additionalContext` on this version, else `PostToolUse` (known-good). Register in
hooks.json; smoke-test with real stdin JSON both matching and non-matching; silent exit 0
on non-matching/malformed input; never blocks the tool call. Docs updated honestly: the
auto-fire caveat and TROUBLESHOOTING describe the backstop as a reminder, not enforcement;
"weakest trigger" wording softened only to the extent the hook actually works when probed.

## Workstream 5 — Wiring + staleness (A11–15; E: C1 11, 28)

- **Recon wiring:** add the recon-read step to `agents/domain-expert.md`,
  `agents/doc-validator.md`, `skills/compound-v/domain-expert-prompt.md`,
  `skills/compound-v/doc-validator-prompt.md` (as already written in phase-1b:54 / phase-1c:47;
  read the exact path handed by the caller, fallback scan only).
- **SKILL.md:** Trigger-0 summary made literal to the authority (direct search command, 3–6,
  exact 150); "runs unchanged **except the gated elicitation override**" (:250); "BOTH audits"
  → all three (:167, :51); quick-ref/overrides rows updated for the reworked gates.
- **Staleness:** GEMINI.md rewritten to four transitions + item 0 + Gemini 3.1 + two missing
  command rows (AGENTS.md gets the rows too); 0.130 → 0.144.1 in adapter-codex.md:44,
  backend-launcher/SKILL.md:128, AGENTS.md:25; worker-script provenance comments refreshed;
  V-memory prose lists gain `recon`; skyscraper-metaphor gets "1A + 1B + 1C" + a one-line
  post-v1.0 note; TROUBLESHOOTING gains a Trigger-0 section (incl. plain-language recon ask
  + the new hook backstop) and nudge-wording touch-ups; rationalization-table gains rows for
  recon-skip and one-at-a-time-always rationalizations.
- Version lockstep → **2.8.0** (three places) + CHANGELOG entry.

## Workstream 6 — Live end-to-end validation (E: C2 9) — release gate, not a code task

After all jobs merge: execute the C2 protocol against the BUILT tree — unfamiliar-topic run
under `ask` (accept, narrowed scope), engine bounded, contract-valid doc written+committed,
directions-late consumption demonstrated, related-topic re-run (KB-hit + freshness), `off`
negative control, one engine-failure path, hook backstop fires on a real Skill invocation.
Failures block release.

## Acceptance Criteria

1. Both scope-gate exploits (rename, symlink) have failing-then-passing selftest cases;
   `--selftest` green; the fixed gate is used to gate this run's own parallel jobs.
2. All Workstream-1 script fixes land with selftests/lint green on the current tree
   (incl. `model: opus` enforcement passing on all existing agents).
3. `xhigh` resolves/validates/dispatches for codex only; every other backend rejects it
   with a clear error; all five layers + docs agree; selftests cover accept + reject.
4. phase-0-recon.md contains every Workstream-2 rule (four sections, VERIFIED/UNVERIFIED
   split, freshness, fail-closed config, no-reply, slug/collision, no-editor commit,
   exact-path handoff, directions-late, outcomes stream) with zero remaining
   "agent must invent policy" gaps from the audit registry (A16-20, E C1 1-20).
5. brainstorm-elicitation.md contains every Workstream-3 rule (checkpoint algorithm,
   restructured gate, observable acceptance, transactional protocol) — C1 21-27 closed.
6. The hook backstop exists, is live-probed, registered, smoke-tested (match + non-match +
   malformed), and documented without overclaiming.
7. Recon wiring present in all 4 agent/template files; SKILL.md summary literal;
   "runs unchanged except" fixed; staleness list fully applied (GEMINI, pins, shim tables,
   TROUBLESHOOTING, rationalization rows, V-memory prose, skyscraper note).
8. `recon-outcomes.jsonl` documented (schema + writer discipline) and excluded from routing
   in prose; scorecard untouched.
9. Version 2.8.0 lockstep ×3 + CHANGELOG (incl. the audit story + counts); CI green.
10. Standing invariants hold: no new commands, no new agents, no new servers, no upstream
    edits, no fabricated metrics, recon never a routing input.
11. Workstream-6 live validation executed with results recorded in the run dir; failures
    fixed before release.
12. Cross-model plan review (Codex) ran BEFORE dispatch; disagreements arbitrated in
    writing in the plan; post-build Codex review rounds run to a clean verdict.
