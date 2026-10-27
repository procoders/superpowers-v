# Plan: run cost and budget inside a long turn

Run `20261027-183220-fix-run-cost-budget-unde`. Request: "Fix: run cost / budget undercounts
spending inside a long turn and in subagents".

Claude Code writes `cost-state` only when a turn ends, and subagent transcripts have none, so a run
built inside one long `claude -p` turn read $0.63 (or $0.00) against $7 while about $31 was spent.
The fix prices the API responses after the last `cost-state` (main thread and
`subagents/agent-*.jsonl`) at the list prices cited in `scripts/cvcore/prices.json`, labels the
figure an estimate, and lets the SubagentStop hook bind a run started inside the turn.

## Acceptance

| Behaviour | Check |
|---|---|
| A single long turn counts main-thread and subagent spend and trips the budget | `test_usage.test_single_long_turn_counts_subagents_and_trips_budget` |
| A run started mid-turn excludes spend before its creation | `test_usage.test_run_started_mid_turn_excludes_earlier_spend` |
| A first turn with no `cost-state` is estimated, cache writes and searches included | `test_usage.test_first_turn_without_cost_state_is_estimated` |
| Streamed blocks of one response count once, with the last usage | `test_usage.test_streamed_blocks_count_once_with_the_last_usage` |
| A model missing from the price list leaves the cost null (`basis: unpriced`) until the turn ends | `test_usage.test_unpriced_model_leaves_cost_unknown_until_the_turn_ends` |
| A `cost-state` slightly below the estimate is not treated as a restart | `test_usage.test_estimate_above_the_cli_figure_is_not_a_restart` |
| Band and brief label the estimate (`~$`, "(estimate)") | `test_usage.test_brief_and_band_label_the_estimate` |
| SubagentStop binds a run started inside the turn and prices it | `test_hooks.test_subagent_stop_binds_a_run_started_inside_the_turn` |
| Review F1: Workflow agents (`subagents/workflows/wf_*/agent-*.jsonl`) count, once per message | `test_usage.test_workflow_agents_are_counted_once` |
| Review F2: a cost-state any distance back is found (mmap), so a long turn keeps counting | `test_usage.test_turn_longer_than_any_tail_keeps_counting` |
| Review F3: an unpriced request after creation does not move the run's start | `test_usage.test_unpriced_request_after_creation_keeps_the_start` |
| Review F4: a malformed line is skipped or unpriced, not fatal to the read | `test_usage.test_malformed_lines_are_skipped_not_fatal` |
| Review F5: `compound-v.py usage` prints `cost_basis` | `test_usage.test_cli_usage_prints_the_basis` |
| Existing cost, hook and band behaviour unchanged; core stays at or under 2500 lines | full `tests/core`, `tests/hooks/*.sh`, CI size guard |

## Tasks

1. `scripts/cvcore/usage.py` + `scripts/cvcore/prices.json`: anchor, request scan, pricing, estimate fields, `cost_basis`.
2. `scripts/cvcore/hooks.py`: pass `created_at`; SubagentStop binds the run.
3. `scripts/cvcore/receipts.py`, `scripts/cvcore/hud.py`, `hooks/run-band.tsx`, `types/index.d.ts`: expose and draw `basis`.
4. Docs: `CONVENTIONS.md`, `.claude/rules/*.md` citations, build and verify skills.
5. Tests in `tests/core/test_usage.py` and `tests/core/test_hooks.py`.

```compound-v-plan
{
  "test_cmd": "python3 -m unittest discover -s tests/core",
  "live_cmd": "python3 scripts/lint-frontmatter.py .",
  "is_web": false,
  "change_set": [
    "scripts/cvcore/usage.py",
    "scripts/cvcore/prices.json",
    "scripts/cvcore/hooks.py",
    "scripts/cvcore/hud.py",
    "scripts/cvcore/receipts.py",
    "scripts/cvcore/cli.py",
    "hooks/run-band.tsx",
    "types/index.d.ts",
    "tests/core/test_usage.py",
    "tests/core/test_hooks.py",
    "CONVENTIONS.md",
    ".claude/rules/*.md",
    "skills/build/SKILL.md",
    "skills/verify/SKILL.md",
    "docs/compound-v/plans/2026-10-27-mid-turn-run-cost.md"
  ]
}
```
