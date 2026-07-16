---
description: Manage Compound V decision preferences — your OWN dated past-reasoning memory (memory + challenge, never a clone). Present-only, observe-in-output / control-via-CLI. `stats` shows override/disagreement rates and demoted/expired patterns; `distill` regenerates the in-repo (secret+PII-scrubbed) preferences.md; `show` prints the current distilled model; `purge` wipes the LOCAL raw log (irreversible). Mode is set by .claude/compound-v.json `brainstorm.preferences` (off|on-demand|marked).
---

You are managing **Compound V decision preferences** — the maker's OWN dated past reasoning at a brainstorm
fork. This is **memory + challenge, not a clone**: it recalls "you decided X before" only to trigger
**re-examination**, always paired with a divergent counter-move — never "reason as the creator", never a
pre-selected default. It has **no routing influence**. Every subcommand here is read-only-ish observation and
LOCAL model management; the live fork surface is wired into the elicitation driver, not this command.

**Split storage (state it honestly):**

- The **raw `decisions.jsonl`** — the full free-text `why` + question context, the PII-prone part — lives
  **LOCAL** under `~/.claude/compound-v/preferences/` and is **NEVER committed / never shipped**. It is
  purgeable.
- The **distilled `preferences.md`** lives **in-repo** at `docs/superpowers/preferences/preferences.md`,
  git-tracked and **V-memory-indexed** (recallable via [`/v:remember`](v-remember.md)) — the "all in one
  memory" path. It is **secret+PII-scrubbed at `distill` time** before it is written, so the committed copy
  carries no flagged token (the honest caveat: the scrubbed distillate DOES ship with the plugin).

Deterministic mechanics live in [`scripts/compound-v-preferences.py`](../scripts/compound-v-preferences.py)
(pure stdlib, `--selftest`-gated). **Anti-ruflo:** counts only ("4/5 similar forks"), **never a fabricated
confidence %**; drift + staleness are surfaced, never hidden.

Args: `{{args}}` — one of `stats` (default) · `distill` · `show` · `purge`.

## Branch on `{{args}}`

- **`stats`** (default) — per-pattern override/disagreement rates plus demoted/expired flags, from the LOCAL log:
  ```
  python3 scripts/compound-v-preferences.py stats
  ```
  Render each pattern's dominant choice with its sample size (counts only), the recency-weighted last-K
  disagreement (`N/M diverged`, **not** an all-time ratio), and any `demoted` (your reasoning here may have
  shifted → stops surfacing) or `expired` (past the staleness window → stops surfacing until refreshed) banner.
  Never print a `%` confidence.

- **`distill`** — regenerate the in-repo `docs/superpowers/preferences/preferences.md` from the LOCAL jsonl,
  **secret+PII-scrubbed before write**:
  ```
  python3 scripts/compound-v-preferences.py distill --repo .
  ```
  Only **unprompted** rationales appear as "your reasoning" — a `borrowed` (candidate-tapped) why is excluded.
  Print the written path + pattern count. Commit the result so V-memory can index it (then it surfaces via
  `/v:remember`); re-index with [`/v:memory-refresh`](v-memory-refresh.md).

- **`show`** — print the current distilled model (the committed, scrubbed in-repo view):
  ```
  cat docs/superpowers/preferences/preferences.md
  ```
  If it is absent, say so and suggest running `distill` first (it only writes once at least one decision has
  been captured). This is the shared, aggregated model — the raw per-decision log is never shown here.

- **`purge`** — wipe the **LOCAL** raw `decisions.jsonl` in one command. **State that it is IRREVERSIBLE**
  (per the base rule for destructive actions — say WHY and confirm intent before running): it deletes the full
  free-text history under `~/.claude/compound-v/preferences/`. The already-committed distillate is untouched.
  ```
  python3 scripts/compound-v-preferences.py purge
  ```

## Modes — `.claude/compound-v.json` `brainstorm.preferences`

The fork surface (in the elicitation driver, not this command) is governed by `brainstorm.preferences`,
resolved fail-closed by [`scripts/compound-v-project-config.py`](../scripts/compound-v-project-config.py)
(`resolve_brainstorm`) — a bad/missing value degrades to the safe `on-demand`, never silently to `marked`:

- **`off`** — nothing surfaces.
- **`on-demand`** (default) — the human/driver **pulls** history ("have I decided something like this
  before?"); no unsolicited surface. A pull can't nudge.
- **`marked`** — a *qualifying* fork's past-matching option carries a **falsifiable dated soft badge**
  (`↩ your past pick: N/M · date`), rendered **together with the mandatory divergent challenge** and
  **never pre-selected** — a label beside a neutral choice, not a default you must un-tick.

Authority doc: [`skills/compound-v/decision-preferences.md`](../skills/compound-v/decision-preferences.md).
Wiring: [`skills/compound-v/brainstorm-elicitation.md`](../skills/compound-v/brainstorm-elicitation.md).
