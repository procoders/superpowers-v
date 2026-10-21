---
description: Draft routing lessons from run results and let a human confirm each one — mines docs/superpowers/execution results joined with each run's manifest for repeated job-attributed failures (scope violations, failed test floors, reviewer escalations, a shared file hit by different jobs), proposes each pattern seen in ≥2 independent runs as a routing-lessons.md bullet with a fixed-menu "prefer …" action and its evidence, and writes only what the human accepts.
---

You are running **`/v:lessons`** — the human-confirmed half of the routing-lessons loop. `{{args}}` may
carry `--since YYYY-MM-DD` and/or `--min-count N`; pass them through to `draft` unchanged.

[`docs/superpowers/memory/routing-lessons.md`](../docs/superpowers/memory/routing-lessons.md) is
curated by hand and the router obeys it. Its loop — records → *a human spots a pattern* → a lesson —
stalls at the spotting step. [`scripts/compound-v-lessons.py`](../scripts/compound-v-lessons.py)
makes the spotting mechanical; **this command keeps the writing human.** No script writes that file:
you do, one bullet at a time, and only after the human says yes. Same discipline as
[`/v:adr`](v-adr.md): a litmus test, references that must exist, human confirmation, a two-command commit.

## Resolving the plugin root

The `scripts/` this command calls ship with the plugin — they are not files in your own
repository. Resolve the plugin root once per session before calling any of them:

```bash
CV="${CLAUDE_PLUGIN_ROOT:-$(ls -d "$HOME"/.claude/plugins/cache/*/superpowers-v/*/ 2>/dev/null | sort -V | tail -1)}"
CV="${CV%/}"
[ -f "$CV/scripts/compound-v-emit-workflow.py" ] || CV="$PWD"
[ -f "$CV/scripts/compound-v-emit-workflow.py" ] || { echo "superpowers-v plugin root not found: reinstall the plugin" >&2; CV=""; }
```

`CLAUDE_PLUGIN_ROOT` is set for hooks but is not set in this Bash environment, so treat it as a
hint, never the whole answer — the cache line covers an installed plugin, `$PWD` is used only inside a checkout of this plugin, and an empty `$CV` is a stop — do not run the steps below with it. Paths under `docs/superpowers/` stay relative; only the plugin's own `scripts/` get
`$CV`.

## Steps

1. **Draft (read-only).**

   ```bash
   python3 "$CV/scripts/compound-v-lessons.py" draft --repo . --json {{args}}
   ```

   It writes nothing. Each candidate carries `fingerprint`, `bullet` (the routing-lessons format with
   the literal date placeholder `YYYY-MM-DD`), `prefer` (from the fixed menu below — never your own
   wording), `evidence` (run id, job id, reason, the violated/failing files, a one-line summary),
   and `possibly_covered` / `covered_by`.

2. **None?** Say so plainly, with the numbers the draft actually scanned — `scanned.run_dirs`,
   `scanned.result_records`, `scanned.attributed_failures`, the `excluded_by_scan_failures` tally,
   and how many groups sat `below_threshold` / `unactionable` / `skipped_reviewed`. Do not lower
   `--min-count` on your own to manufacture a candidate; one bad run is noise. Stop.

3. **Litmus test, per candidate, before you show it.** A lesson must change a future routing
   decision and rest on independent runs. If the evidence is plainly one incident — every run in a
   single `-rN` chain (`evidence[].continues`), or the same deliberate probe re-run — say that next
   to the candidate so the human can weigh it. If `possibly_covered` is true, quote `covered_by`
   and say the match is a plain-text heuristic (job type AND backend named in an existing bullet).

4. **References MUST exist.** Before offering a candidate, check every cited run directory:
   `test -d docs/superpowers/execution/<run-id>` for each id in its `runs`. Drop a candidate whose
   evidence you cannot resolve and say which id failed — a lesson citing a run that is not there
   is worse than no lesson.

5. **Ask — one candidate at a time.** Show the proposed bullet, the evidence runs (run / job /
   reason / files) and the covered note. When there are **four or fewer** candidates you may instead
   present them as a numbered list and ask **as a structured choice (the AskUserQuestion tool on
   Claude Code; a plain numbered question on other harnesses)**, one question per candidate with the
   options **Accept**, **Accept with edited wording**, **Reject**, **Skip**. More than four: go one
   at a time. For each answer:

   - **Accept (optionally edited).** Replace `YYYY-MM-DD` with today's real date, apply the human's
     wording if they edited it (keep the `<job type> on <backend·model> → <outcome>; prefer <action>.`
     shape and the cited runs), and append the bullet as the LAST item of the `## Lessons` list in
     `docs/superpowers/memory/routing-lessons.md` — nowhere else in the file. Then:

     ```bash
     python3 "$CV/scripts/compound-v-lessons.py" record --repo . --fingerprint <fp> --decision accepted --note "<edited wording, if any>"
     ```

   - **Reject.** Ask for the reason in one line and record it, so the draft never proposes it again:

     ```bash
     python3 "$CV/scripts/compound-v-lessons.py" record --repo . --fingerprint <fp> --decision rejected --note "<the human's reason>"
     ```

   - **Skip.** Do nothing. It will be proposed again next time.

   **Never write the lesson file, and never run `record`, without an explicit answer from the human
   for that candidate.** There is no `--auto` and no silent path.

6. **Commit — two commands, never chained.** Only if anything was accepted or rejected:

   ```bash
   git add docs/superpowers/memory/routing-lessons.md docs/superpowers/memory/lesson-reviews.jsonl
   ```

   check its exit code, then separately:

   ```bash
   git commit -m "memory: routing lessons from /v:lessons (<n> accepted, <m> rejected)"
   ```

   Add only those two exact paths. If nothing was accepted, `routing-lessons.md` is unchanged and
   adding it is harmless; `lesson-reviews.jsonl` exists whenever anything was recorded. An uncommitted lesson is invisible to the next
   clone and to the router's other readers. Afterwards `python3 "$CV/scripts/compound-v-memory.py" refresh`
   makes it recallable through `/v:remember`.

## The prefer-action menu (fixed)

The draft proposes only these, keyed by signal. Anything else is reported `unactionable`, never
a candidate:

| Signal | Action |
|---|---|
| the same file written out of lane by different jobs in ≥N runs | move `<file>` into the serial Task 0 `shared_foundation` job |
| repeated test-floor failures for a type on a light / standard tier or a Sonnet model | route `<type>` one tier up |
| repeated reviewer escalation (`escalated_from`, `retry_exhausted`) | start `<type>` reviews at `<rung>` |
| repeated scope violations for a type or inside one lane area | force worktree isolation (when the jobs ran `direct`), else narrow the lane |

## Out of scope

This command never edits the header or the "How to add a lesson" section of routing-lessons.md,
never deletes or rewrites an existing lesson (pruning is a human edit in a PR), and never changes a
manifest or the routing policy. It proposes; the human decides; you write only what was accepted.
