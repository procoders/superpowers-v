# Routing lessons (human-curated)

Hard-won routing knowledge for Compound V — distilled by a human from the raw
`task-outcomes.jsonl` log. This is the qualitative half of Compound V's memory
(PRD §5.8); the quantitative half is the JSONL outcomes log next to it.

> **No script writes this file.** It is curated by hand and reviewed in PRs.
> `scripts/compound-v-update-memory.py` only appends to `task-outcomes.jsonl`
> and explicitly refuses to write here. `scripts/compound-v-collect-results.py`
> writes `results/<id>.json` and never touches memory. The loop is:
> collector → `task-outcomes.jsonl` (automatic) → a human spots a pattern →
> a lesson here (manual). Keep entries lean, dated, and reversible.

The routing engine (`skills/compound-v/routing-policy.md`) consults this file as
an input when it picks backend / model / isolation for a job type — so a lesson
recorded here actually changes future routing decisions. That is the whole point
of the loop: a hand-curated lesson, written from outcomes, that the router obeys.
(Since v1.1 the router also reads the machine-generated scorecard, and v2.0 adds a
prose-recall layer for planning/review — but this file stays the authoritative,
human-written override, and no script ever writes it.)

## Lessons

Format: `<job type> on <backend·model> → <observed outcome>; prefer <action>.`
One bullet per lesson. Date each one. Cite the run(s) when you can.

- **2026-06-26** — `large_isolated` on **codex·gpt-5.5** (worktree) **blocked twice
  on shared barrel files** (`index.ts` re-exports the slice didn't own) → prefer
  moving barrels / shared re-export files into the serial **Task 0
  `shared_foundation`** job so the isolated worker never needs to touch them.
  *(Seed example — replace with real runs as they accrue.)*

## How to add a lesson

1. **Read the data first.** Skim `task-outcomes.jsonl` for a repeated signal —
   the same `type`+`backend` repeatedly `blocked`, or a high `rework_rounds`.
   One bad run is noise; **two or more is a pattern** worth a lesson.
2. **Write it in the format above**, in the `## Lessons` list:
   `<job type> on <backend·model> → <outcome>; prefer <action>.`
   Lead with the date. Name the run id(s) if you have them.
3. **Make it actionable.** A lesson must change a future decision — e.g. "route
   this type to Opus", "force worktree", "fold X into Task 0". A pure observation
   with no "prefer …" is not yet a lesson.
4. **Keep it lean and honest.** No fabricated cost or token numbers (anti-ruflo).
   If a lesson stops holding, edit or delete it — this file is meant to be pruned,
   not to grow forever.
5. **Commit it in a PR** like any other curated doc. Never script-generate it.
