# Troubleshooting

Common issues with Compound V and how to fix them.

## Sidekick isn't auto-firing after brainstorming

**Symptom:** You finished `superpowers:brainstorming`, the spec is saved, but Compound V didn't dispatch the pre-flights.

**Cause:** "Auto-fire" is **description-driven** — the parent Claude has to read Compound V's skill description and recognize the trigger condition. The plugin ships a `PostToolUse(Write)` hook that prints a *reminder* when a Compound-V artifact is saved (three arms: plan saved → dispatch next steps, spec saved → the three pre-flights, recon saved → read it before the first brainstorm question), but the actual skill invocation still depends on the parent's recognition. Reliability is high on Opus / Sonnet 4.6+; weaker models may miss it.

**Fix:**
1. Confirm the plugin is installed: `/plugin list` should show `superpowers-v`.
2. Confirm hooks are loaded: plugin hooks ship inside the plugin (`hooks/hooks.json`) and are loaded automatically at session start — they do **not** appear in `~/.claude/settings.json` or your project's `.claude/settings.json`, so don't hunt for them there. The observable signal that they loaded is the next item.
3. Confirm the SessionStart banner appeared at session start: re-start the session if not (`/session new`).
4. As a manual fallback, invoke the skill directly: `Skill compound-v`.

## Trigger 0 (recon) didn't fire

**Symptom:** You started a brainstorm on a topic you expected research for, but no recon offer appeared and no doc landed in `docs/superpowers/recon/`.

**Cause:** Trigger 0 is **description-driven** — the parent Claude has to read the skill description and run the gates in `skills/compound-v/phase-0-recon.md`; nothing in the harness forces it. Since v2.8 there is a hook backstop, `hooks/brainstorm-trigger0-nudge.sh`, which injects a one-line reminder when the Skill tool invokes `superpowers:brainstorming` — but it is a **reminder, not enforcement**: it cannot make the recon run. Also, a silent skip is often *correct* behavior: gate 1 skips plumbing topics, gate 2 skips on a strong V-memory KB hit, and gate 3 honors `brainstorm.deep_research: "off"` as a hard kill-switch.

**Fix:**
1. Check *why* it stopped: `docs/superpowers/memory/recon-outcomes.jsonl` appends one terminal event per gated stop (`plumbing_skip` | `kb_skip` | `off` | `declined` | `no_engine`), and `fired` / `saved` / `consumed` events for runs that happened.
2. Check the config: `brainstorm.deep_research` in `.claude/compound-v.json` (`ask` default / `auto` / `off`). `off` means no offer, ever — that's the kill-switch working, not a bug.
3. Manual fallback — plain language works: tell the agent **"run the Trigger 0 recon from phase-0-recon.md for \<topic\>"**. It reads `skills/compound-v/phase-0-recon.md` and runs the gates + engine ladder for that topic.

## Phase 1C says "Context7 unavailable"

**Symptom:** The doc-validator agent reports "DEGRADED: WebSearch-only" instead of using Context7.

**Cause:** Context7 MCP isn't installed in this Claude Code session.

**Fix:**
```
/plugin install context7@claude-plugins-official
```

Or in your `~/.claude.json` (or project `.mcp.json`):
```json
{
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"]
    }
  }
}
```

Restart the session. Phase 1C will now use Context7 first, falling back to WebSearch only for libraries not in the index.

## Partition reviewer fails with FILE_OVERLAP

**Symptom:** `compound-v:partition-reviewer` returns `FAIL: FILE_OVERLAP` and the plan's Partition Map looks fine to you.

**Cause:** Two parallel tasks reference the same file (commonly a barrel/index file, a type declaration, a config, or a migration). Glob patterns count as expanded — `src/i18n/locales/*.json` overlaps with `src/i18n/locales/en.json`.

**Fix:** Move the shared file to **Task 0 (serial pre-phase)**, or split the original parallel task by namespace so each gets a disjoint subset. See `skills/compound-v/phase-2-disjoint-partitioning.md` § "Shared Resources → Serial Pre-Phase" and § "Default approach: split by feature slice, not by layer."

## Implementer returned BLOCKED: "need to read sibling file"

**Symptom:** During Phase 3 dispatch, one implementer reports `BLOCKED` because it needs to read a file in another parallel task's WRITE-allowed list.

**Cause:** The Partition Map missed a coupling. The two tasks aren't actually disjoint.

**Fix:**
1. Identify the shared file.
2. If it's read-only shared (e.g. a type), move it to **Task 0** so all parallel tasks get auto-propagated READ access.
3. If it's modified by both, **merge the two tasks** — they aren't actually parallelizable.
4. Re-dispatch the blocked task with the updated scope lock.

Never tell the implementer to "just peek" — that defeats the partition contract.

## Two implementers collided on a file despite the partition

**Symptom:** Phase 3 finished but `git status` shows merge conflicts or unexpected file states.

**Cause:** One implementer wrote a file outside its WRITE-allowed list. The scope lock is enforced by prompt, not by harness, so a misbehaving subagent can violate it.

**Fix:**
1. `git diff` to identify which file landed unexpectedly.
2. `git log --oneline -5` to see commit attribution.
3. Reject the violating implementer's commits; re-dispatch with a stricter scope lock and an explicit reminder: "improvising files outside the WRITE-allowed list is a scope-lock violation per Compound V Phase 3."
4. Update the Partition Map if the implementer's "improvisation" reveals a real partition gap.

## A job came back BLOCKED — "wrote outside write_allowed"

**Symptom:** During dispatch a job's `job_result` has `"status": "blocked"` with `violations` listing files, the run halts, and nothing merged for that job.

**Cause:** This is the **scope gate doing its job** (`scripts/compound-v-scope-check.py`). The worker touched a file outside its manifest `write_allowed` list. Unlike 0.1.x — where the SCOPE LOCK was prose a subagent could ignore — the gate is now deterministic: it unions `git diff --name-only HEAD` with `git ls-files --others --exclude-standard` and rejects any path not matched by `write_allowed`. The `violations` field is **git-derived**, not self-reported, so it's authoritative.

**Fix:**
1. Look at the `violations` paths in `docs/superpowers/execution/<run-id>/results/<job-id>.json`.
2. If the violating file is a genuine shared resource (barrel/index, type, config, migration), move it into the **serial Task 0** (`shared_foundation` job) in the manifest, then re-dispatch — see `skills/compound-v/execution-manifest.md` and `skills/compound-v/phase-2-disjoint-partitioning.md`.
3. If two jobs both need to write it, the partition was wrong — **merge those jobs**; they aren't parallelizable.
4. If the worker simply improvised, re-dispatch with a tighter scope lock. For worktree jobs, the worktree is left in place (under `$TMPDIR/compound-v/<run-id>/<job-id>`) for inspection and is **not** merged.

Never "just let it through." A BLOCKED job never merges by design.

## `validate-manifest.py` rejects the manifest before dispatch

**Symptom:** `partition-reviewer` fails (or `/v:dispatch` halts) with a manifest-invariant violation — e.g. overlapping `write_allowed`, a Codex job without `isolation: worktree`, or a reviewer not on Opus.

**Cause:** `scripts/compound-v-validate-manifest.py` is the deterministic backing gate behind the partition review. It enforces: disjoint `write_allowed` across jobs, **Codex ⇒ worktree**, **reviewers ⇒ Opus**, shared resources in the serial Task 0, and "unclear scope never dispatches."

**Fix:** Read the specific violation it printed and edit `manifest.yaml`:
- Overlap → move the shared file to Task 0 or split the job by namespace.
- Codex without worktree → set `isolation: worktree` (mandatory for external workers).
- Reviewer not Opus → set `model: opus`.

Re-run the validator (or `/v:dispatch`) until it's clean. The manifest schema + rules live in `skills/compound-v/execution-manifest.md`.

## Codex worker produces no result / hangs / emits a deprecation warning

**Symptom:** `scripts/compound-v-run-codex-worker.sh` returns nothing useful, times out, or you see `[features].codex_hooks is deprecated` noise.

**Causes & fixes:**
1. **The deprecation line is cosmetic.** `codex` emits `[features].codex_hooks is deprecated` on stderr; the worker script already suppresses it. If you call `codex exec` by hand, ignore that line — it does not indicate a failure.
2. **Wrong flags.** The verified `codex-cli 0.144.1` flag set is `--cd <wt> --sandbox workspace-write --skip-git-repo-check --model <m> --output-last-message <f> -c sandbox_workspace_write.network_access=<bool>` (optionally `--output-schema <f>`). **Do not pass `--ask-for-approval never`** — it is invalid for `codex exec` (a top-level/interactive flag only) and will fail every job. `exec` already defaults to `approval: never`; if you ever need a non-default, use `-c approval_policy=never`.
3. **Timeout.** The worker wraps `codex exec` in `timeout` (default 900s). A `status: timeout` result means the job exceeded it — raise `--timeout-sec` or split the job smaller.
4. **Stale flags after a Codex upgrade.** Re-probe with `/v:init`, which re-checks the flag set against `codex exec --help` (the **exec** subcommand help, not the top-level help — the top-level merge is what masked the original `--ask-for-approval` bug).
5. **No worktree / dirty diff.** The worker runs inside a fresh `git worktree add <wt> HEAD` under `$TMPDIR`. If `git worktree` fails (e.g. repo not initialized, or `$TMPDIR` unwritable), the script reports an environment fault rather than a job result.

## A run was interrupted — how do I resume?

**Symptom:** You killed a session (or it crashed) mid-batch. Some jobs finished, some didn't.

**Fix:** `/v:resume <run-id>`. It re-reads `docs/superpowers/execution/<run-id>/state.json`, **reconciles it against git reality** (what actually landed — git wins the tie-break, so if `state.json` says `done` but the files aren't in git, the job is re-dispatched), and re-dispatches only `pending` / `failed` / `blocked` jobs. Finished jobs are not re-run.

- Check status first with `/v:status <run-id>` (renders `state.json` — phase + per-job status).
- Resume lives in **Engine A** (the helper-script layer), which is exactly why it survives a hard crash. The opt-in Workflows accelerator (Engine C) does **not** provide crash-resume — its resume is same-session-only, so the orchestrator never routes resume through it.
- If you don't know the run-id, list `docs/superpowers/execution/` — each subdirectory is a run.

## `/v:init` can't find Codex (or sets Claude-only unexpectedly)

**Symptom:** `/v:init` reports Codex absent and sets the routing stance to **Claude-only**, even though you think Codex is installed.

**Cause / fix:**
1. Confirm the CLI is on `PATH`: `command -v codex`. If missing, install it (`npm i -g @openai/codex`) and re-run `/v:init`.
2. Claude-only is a **correct, supported** stance, not a failure — the pipeline runs unchanged, with large-isolated jobs routed to `opus` + `worktree` instead of Codex. You only need Codex for the cheaper large-isolated carve-out.
3. The capability cache lives at `~/.claude/compound-v-capabilities.json` (user-level) and the stance at `.claude/compound-v.json` (project-level). Delete the cache and re-run `/v:init` if it's stale after an install.

## "Opus rate-limited" mid-batch

**Symptom:** Halfway through a 6-task parallel batch, some implementers fail with rate-limit errors.

**Cause:** Anthropic's API enforces per-account rate limits. 4-6 parallel Opus subagents is the practical ceiling; 10+ reliably hits the wall.

**Fix:**
1. Reduce batch size to 3-4 in the plan's Partition Map.
2. Use `run_in_background: true` on implementers — staggered start helps.
3. As a last resort: document the rate-limit fallback in the plan (`"Compound V fallback: Sonnet used for tasks X/Y because Opus rate-limited at <timestamp>"`) and re-dispatch failed tasks on Sonnet. Note this is a degradation, not the contract.

## Domain-expert audit feels generic, no community quotes

**Symptom:** Phase 1B audit returns text from official docs only — no Reddit, HN, or community sources.

**Cause:** The agent skipped Layer 2 + Layer 3 searches. Common when the dispatch prompt didn't emphasize them, or when WebSearch returned mostly official docs for the top hits.

**Fix:** Re-dispatch the domain-expert agent with an explicit instruction: "Spend at least 2 of your searches on persona/community forums where the END USER of this feature hangs out — not just the vendor docs." The agent definition has Layer 3 in its system prompt, but a busy advisor sometimes under-uses it.

## Knowledge base files are getting huge

**Symptom:** `docs/superpowers/expert/_knowledge-base/oauth.md` is 2000+ lines and hard to navigate.

**Fix:** Run a manual consolidation pass:
1. Identify entries with the same heading topic.
2. Merge them into a single canonical section, keeping the latest date stamps.
3. Move older entries to a `_history/` subdirectory if you want to preserve them for git context.

Compound V agents don't currently auto-consolidate the KB — that's a P2 enhancement.

## How do I run only Phase 1A (no domain or library audit)?

Use the slash command: `/v:archaeology <topic>`.

## How do I run only Phase 1B?

Currently: dispatch the agent manually: `Task(subagent_type: "compound-v:domain-expert", prompt: "...")`. A `/v:domain` command is P1 backlog.

## How do I run only Phase 1C?

Currently: dispatch the agent manually: `Task(subagent_type: "compound-v:doc-validator", prompt: "...")`. A `/v:libs` command is P1 backlog.

## I'm using Codex / Gemini CLI, not Claude Code

The plugin ships compatibility shims:
- **Codex**: `AGENTS.md` at the project root is auto-loaded by Codex CLI; it points at the same skills.
- **Gemini CLI**: `GEMINI.md` documents the conceptual mapping. The extension manifest schema is harness-specific — adapt to your Gemini CLI version's actual format (the shim is untested as of v1.1.0).

The skill content is harness-neutral. Tool names differ (Claude Code's `Task` ≈ Codex's `subagent`); the dispatcher logic adapts. The orchestrator's deterministic core (the manifest schema, the `git diff` scope gate in `scripts/compound-v-scope-check.py`, and the `job_result` contract) is harness-neutral; only the dispatch wiring is Claude-Code-specific. The Codex *backend* (`adapter-codex.md`) is itself just `codex exec` driven by a shell script, so any harness with a shell can spawn it. These shims remain 🧪 untested on real non-Claude installs.

## Compound V says my repo is too small for it

Compound V is overkill for:
- Greenfield single-file features
- Pure refactors that touch every file (no partition possible)
- Pure plumbing (build config, lint rules)
- Solo learning sessions

Fall back to default Superpowers for those. Document the fallback at the top of the plan: `"Compound V skipped — single-file feature; using default subagent-driven-development."`
