# Task-8 — Live end-to-end validation evidence (2026-07-11)

Executor: the run orchestrator (direct mode). Every command below was actually run against
the merged tree at `2781ffe`+; outputs are recorded verbatim in the session transcript.
Honesty notes inline — nothing simulated is reported as organic.

## 1. Unfamiliar-topic Trigger-0 run under `ask` — PASS
Topic: "improve V-memory FTS5 recall for Cyrillic/multilingual queries" (genuinely uncovered).
- Gate 1: not plumbing (recall quality is user-feelable) → proceed. ✅
- Gate 2: exact shell-out ran; **stale-index warning fired and the new rule was exercised**
  (refresh → re-search). Hits = same product/domain but NOT the same task class → weak hit →
  gate 3. ✅ (the v2.7 doc would have left this judgment undefined)
- Gate 3: config file absent → default `ask`. **Engine-aware offer exercised**: deep-research
  absent from the session's available-skills listing → offer omitted Engine A (A16 fix live).
  Acceptance with narrowed scope performed by the orchestrator per the release-gate protocol
  (honest note: no human in the loop for this step; the mechanics, not consent UX, were under test).
- Engine B: exactly 3 WebSearch calls in ONE message (bound 3–6 respected). ✅
- Output: `docs/superpowers/recon/2026-07-11-fts5-cyrillic-tokenizer.md` — 38 lines (≤150),
  anti-anchoring header + exactly 5 `##` sections (grep-verified: 5), [F]/[L] source ids with
  accessed dates, 3 materially divergent directions, VERIFIED vs UNVERIFIED split honest
  (GitHub-readme claims placed in LEADS, sqlite.org claims in VERIFIED). ✅
- Commit: separate `git add --` / `git commit -m … --` with exit checks, no chaining, no editor. ✅
- Events: `fired` + `saved` appended (separate lines, append-only). ✅

## 2. Directions-late consumption — PASS (mechanics)
From QUESTIONS + VERIFIED only, three first-principles proposals were produced BEFORE reading
DIRECTIONS: (P1) measure baseline Cyrillic-query miss rate before changing anything;
(P2) close the morphology gap via DENSE-lane adoption (bootstrap nudge when Cyrillic queries
detected) — **deliberately rejects the recon framing** (no tokenizer change at all);
(P3) unicode61 option tuning + explicit re-index plan. Then DIRECTIONS were read as a
coverage/novelty check: D2 (trigram) was genuinely novel vs the proposals; D1≈P3; D3's need is
covered differently by P2. `consumed` event appended.
Honesty note: author and consumer are the same context here, so the anti-anchoring *psychology*
is not testable in-run — what this validates is the PROTOCOL shape (proposals-before-directions,
one proposal rejecting the frame, directions as checklist). The residual-risk sentence in
phase-0-recon.md covers exactly this limitation.

## 3. Related-topic re-run (KB-hit + freshness) — PASS
`refresh` picked up the committed recon doc (auto-indexed, doc_type=recon, date=2026-07-11);
search for "improve V-memory Russian Cyrillic query recall tokenizer" returned the recon doc in
ALL top-3 slots → strong hit under the new rule (same product/domain + same task class + fresh
today) → skip with the doc handed to the brainstorm; `kb_skip` event appended. ✅

## 4. `off` negative control + fail-closed — PASS
Scratch config `{"deep_research": "off"}` → gate-3 walk: no offer, no engine, terminal `off`
event; "local recall may still surface" semantics confirmed as documented. Malformed value
`"of"` → effective `deep_research='ask'`, `batch_elicitation=False` — fail-closed, never auto. ✅

## 5. Engine-failure transition — PASS (injected)
Failure injected by decision (engines treated unavailable), not a real network denial — honest.
The documented transition was exercised: real-reason skip notice ("web search unavailable/denied",
never "no engine exists"), brainstorm continues, terminal `no_engine` event appended. ✅

## 6. Hook backstop on the merged tree — PASS
Real stdin JSON through `hooks/brainstorm-trigger0-nudge.sh`: matching Skill+brainstorming →
nudge with the contract reminder text (exit 0); non-matching skill → silent exit 0; malformed
stdin → silent exit 0. (PreToolUse additionalContext injection itself was proven live by
task-3's nested-session probe with a token round-trip — evidence in that job's report.) ✅

## Event-stream shape after validation (append-only, never routing)
fired → saved → consumed (run 1) · kb_skip (run 2) · off · no_engine — six events, one per
emission point, no mutated lines. Stream lives at `docs/superpowers/memory/recon-outcomes.jsonl`.

**Verdict: 6/6 checks PASS; zero fixes required; nothing blocked release.**
