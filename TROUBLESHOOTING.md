# Troubleshooting

Common issues with Compound V and how to fix them.

## Sidekick isn't auto-firing after brainstorming

**Symptom:** You finished `superpowers:brainstorming`, the spec is saved, but Compound V didn't dispatch the pre-flights.

**Cause:** "Auto-fire" is **description-driven** — the parent Claude has to read Compound V's skill description and recognize the trigger condition. The plugin ships a `PostToolUse(Write)` hook that prints a *reminder* when a Compound-V artifact is saved (three arms: plan saved → dispatch next steps, spec saved → wait for the user's spec review; the three pre-flights fire when writing-plans is invoked, recon saved → read it before the first brainstorm question), but the actual skill invocation still depends on the parent's recognition. Reliability is high on Opus / Sonnet 4.6+; weaker models may miss it.

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

## A worktree job came back BLOCKED and every violation is under `node_modules/` (or `.venv/`, `vendor/`, a build cache)

**Symptom:** a job that has to install something before it can build or test returns `"status": "blocked"` with hundreds of `violations`,
all of them inside a dependency or build directory the model never meant to author.

**Cause:** the model ran the install itself. The scope gate unions the worktree's untracked *and* ignored files into the changed set, so
everything an install created reads as a write this job made — and none of it is in `write_allowed`.

**Fix:** declare the install in the manifest instead, so the worker script runs it before the model ever starts:

```yaml
# top level of manifest.yaml — one dependency install for the whole run
provision_command: "npm ci"
provision_timeout_s: 600        # optional; defaults to 600, range 1-1800
```

A single job may override either key by declaring it on the job itself; the emitter reads the job's value first and falls back to the
manifest's. Only worktree jobs provision — a `direct` job runs in the checkout, which already has its dependencies.

The worker script — never the model — runs that command once inside the fresh worktree, then lists exactly what it created into
`preexisting.txt` and hands that file to the gate as `--preexisting`. That subtraction is the *only* one the gate performs, and what makes
it safe is when the snapshot is taken: after provisioning and before the model launches, so it can only ever contain what provisioning made.
On the four headless backends the same two flags exist on the command line as `--provision-command` and `--provision-timeout-sec`.

Two consequences worth knowing before you use it:

- The command must be **idempotent and must not modify tracked files**. A tracked file it edits is still a violation — the snapshot only
  ever forgives untracked and ignored paths.
- A path whose filename contains a newline cannot be written to that line-oriented file, so it is **left out and stays a violation** —
  fail closed, the same rule the gate applies to a file it could not read.

Do not "fix" this by widening `write_allowed` to `node_modules/**`. That hands the job a lane it can write anything into for the rest of
the run, and the gate will agree with it.

## Scope gate BLOCKS `tsconfig.tsbuildinfo` / a vitest or jest cache / `.next/` that the job never wrote

**Symptom:** a job is BLOCKED with violations under a single build-artifact path — `tsconfig.tsbuildinfo`, `node_modules/.vite/vitest/<hash>/results.json`, a Jest cache, `.turbo/`, `.next/` — none of them a file the implementer's own diff touched.

**Cause:** the before-image snapshot (`preexisting/<id>.txt`) is taken after `provision_command` runs but **before the test floor ever runs** in the fresh worktree. If your floor is the first thing to create that path (e.g. `tsc --noEmit` with `"incremental": true` in `tsconfig.json`, or a Vitest/Jest run seeding its cache), the snapshot never saw it, and the gate attributes it to the job like any other new gitignored write.

**Fix, either of:**
- Declare it in the manifest: `toolchain_artifacts: ["tsconfig.tsbuildinfo", "node_modules/.vite/**"]` (top level, alongside `provision_command`). The gate subtracts a matching path only when `git check-ignore` confirms it is actually gitignored at gate time — a tracked file, or `.env`/`dist/` left off the list, is still caught. See `skills/compound-v/execution-manifest.md` § `toolchain_artifacts`.
- Or warm the artifact inside `provision_command` so it already exists when the snapshot is taken, e.g. `npm ci && npx tsc --noEmit || true && npx vitest run <one fast test> || true`. No manifest schema change needed; this is the older workaround and still works.

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
2. **Wrong flags.** The verified `codex-cli 0.144.1` flag set (verified 2026-07-11 on 0.144.1, re-verified 2026-09-24 on 0.156.1 with `gpt-6-sol`/`gpt-6-luna` and 2026-09-30 on 0.159.1 with `gpt-6.1-sol`/`gpt-6-astra`) is `--cd <wt> --sandbox workspace-write --skip-git-repo-check --model <m> --output-last-message <f> -c sandbox_workspace_write.network_access=<bool>` (optionally `--output-schema <f>`). **Do not pass `--ask-for-approval never`** — it is invalid for `codex exec` (a top-level/interactive flag only) and will fail every job. `exec` already defaults to `approval: never`; if you ever need a non-default, use `-c approval_policy=never`.
3. **Timeout.** The worker wraps `codex exec` in `timeout` (default 900s). A `status: timeout` result means the job exceeded it — raise `--timeout-sec` or split the job smaller.
4. **Stale flags after a Codex upgrade.** Re-probe with `/v:init`, which re-checks the flag set against `codex exec --help` (the **exec** subcommand help, not the top-level help — the top-level merge is what masked the original `--ask-for-approval` bug).
5. **No worktree / dirty diff.** The worker runs inside a fresh `git worktree add <wt> HEAD` under `$TMPDIR`. If `git worktree` fails (e.g. repo not initialized, or `$TMPDIR` unwritable), the script reports an environment fault rather than a job result.

## Codex job fails: "The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account"

**Cause:** the installed `codex` is too old to know the model. The message says "account", but the account is fine: on 2026-09-30 codex-cli 0.157.0 returned exactly this for `gpt-6.1-sol`, and 0.159.1 ran it on the same account.

**Fix:** `codex update` (standalone install) or `npm i -g @openai/codex`, then `codex debug models` should list `gpt-6.1-sol`. To stay on an old client, pin the previous workhorse in `.claude/compound-v.json`: `"models": {"codex": {"deep": "gpt-6-sol", "standard": "gpt-6-sol"}}`.

## `/v:onboard --refresh` always says 0 stale, though the code changed

**Cause (before 3.7.6):** step 9 wrote `.onboard-manifest.json` with `docs: {}`, so there was nothing to compare (issue #21).

**Check:** `python3 scripts/compound-v-onboard.py staleness --repo .`. `state: unregistered` means the manifest registers no cited file; its `count: 0` is not a clean result. `state: registered` is a real check.

**Fix:** update to 3.7.6 or later and run `/v:onboard --refresh`. It re-verifies each generated doc's citations and re-registers them with `staleness --write --docmap <file>`; the write now fails loudly without a docmap.

## The run band above the prompt does not appear (or I want it gone)

**It appears only while a run has a pending or running job**, and only on Claude Code ≥ 2.1.287 in the terminal or the desktop Code tab; with no active run it draws nothing by design. Check the reader it draws from: `python3 scripts/compound-v-dashboard.py hud` prints `{"run": null}` when nothing is active. A run older than 72 hours is not shown.

**An age shows `?`:** the liveness probe did not answer in time; the band prints "unknown" rather than a number it did not measure.

**Turn it off:** `CV_DISABLED_HOOKS=run-band` in the shell that launches Claude Code.

## A run was interrupted — how do I resume?

**Symptom:** You killed a session (or it crashed) mid-batch. Some jobs finished, some didn't.

**Fix:** `/v:resume <run-id>`. It re-reads `docs/superpowers/execution/<run-id>/state.json`, **reconciles it against git reality** (what actually landed — git wins the tie-break, so if `state.json` says `done` but the files aren't in git, the job is re-dispatched), and re-dispatches only `pending` / `failed` / `blocked` jobs. Finished jobs are not re-run.

- Check status first with `/v:status <run-id>` (renders `state.json` — phase + per-job status).
- Resume lives in the **verification layer** (`state.json` + the helper scripts), which is exactly why it survives a hard crash. **Engine C runs the jobs; it does not own recovery.** The native runtime's resume is same-session-only *and* re-runs completed agents past a failure point — in a 16-job run whose job 3 failed, jobs 4–16 would re-run despite having succeeded, paying full cost twice. `/v:resume` does not.
- Resume also gates integration: it runs `scripts/compound-v-integration-gate.py` before any job commit is integrated, so **do not remove a job's worktree before resuming** — a missing receipt is *re-derived* from the tree, and a removed worktree makes the job `unverifiable` instead.
- A run dispatched **before** 3.0's cutover has no `baseline`, no `lane-map.json` and no receipts. That resumes fine: every field Engine C adds is optional on read, and each such job simply takes the re-derivation branch.
- If you don't know the run-id, list `docs/superpowers/execution/` — each subdirectory is a run.

## After re-running `/v:dispatch` on a halted run, the gate lists `manifest.yaml`, `state.json`, `dispatch.workflow.js`, `results/…` as violations

**Symptom:** you re-ran `/v:dispatch` (not `/v:resume`) on the same run-id after a halt, and the gate now BLOCKS a job whose own lane files were fine, citing the run directory's own bookkeeping — `manifest.yaml`, `dispatch.workflow.js`, `state.json`, `results/<id>.json`, `preexisting/<id>.txt` — as out-of-lane writes.

**Cause:** the job's `baseline` was pinned once, at the first attempt, and a bare re-dispatch branches the new worktree from the current `HEAD` while the gate still diffs against that first pin — so every commit the pipeline made to the run directory between attempts (including the previous attempt's own record-keeping) reads as a write this attempt made. This is finding 146 (2026-09-03), reached through a door `/v:resume` does not guard.

**Fix:** fixed in 3.6.3 for `worktree` jobs — `register-lane` now detects a concluded previous attempt (a receipt or result already on disk for the job) and re-pins `baseline` to the fresh worktree's `HEAD` before re-registering, so this no longer happens on a plain re-dispatch. For a `direct` job the pin still does not clear itself; run [`/v:resume <run-id>`](commands/v-resume.md) instead, which calls `resume-prepare` to clear it. See `skills/compound-v/state-machine.md` § `baseline` re-pins on a re-attempt.

## Engine C didn't run — the dispatch fell back to the subagent path

**Symptom:** `/v:dispatch` reports it is using the residual subagent path, or the Workflow tool refuses the launch.

**Cause / fix — in the order worth checking:**

1. **You are in a subagent.** A subagent has no Workflow tool at all — probed live under both the public name `Workflow` and the internal `RunWorkflow`. Run `/v:dispatch` from the **top level**. This is also why `/v:dispatch` no longer delegates its run to `compound-v:parallel-dispatcher`: delegating would silently drop every run onto the residual path.
2. **`CLAUDE_WORKFLOW_NAME_ONLY` is set.** The tool then accepts only `{name, args}` and refuses `script` / `scriptPath` / `resumeFromRunId` / `remote` outright. Engine C needs `scriptPath`, because that is what makes the committed artefact the thing that ran. Unset it, or accept the residual path.
3. **Workflows are off.** `CLAUDE_CODE_WORKFLOWS=false`, `CLAUDE_CODE_DISABLE_WORKFLOWS`, the managed `disableWorkflows` setting, or `enableWorkflows: false` each disable the tool.
4. **The build accepts `Workflow` but refuses the clamp.** `disallowedTools` and `bashCommandClamp` were found in 2.1.238 while workflow support is claimed from 2.1.219 — so a version check is not a capability check, and a build that passes one and fails the other selects Engine C and then **fails to create the Gate agent**. Run `python3 scripts/compound-v-emit-workflow.py --engine-probe` and execute the clamped-spawn snippet it prints.

**What is NOT the cause:** headless. Workflows **are** available in `claude -p` and in the Agent SDK; only the `ultracode` keyword is route-restricted. Do not report "workflows are unavailable headless" — that claim is withdrawn.

## `agent() opts.bashCommandClamp can bind nothing` — the spawn is refused

**Symptom:** the run dies at the Gate (or at an external-backend implementer) with a refusal naming the clamp.

**Cause:** the clamp is an **allowlist of shell command forms**, and it is fail-closed by design — including refusing the spawn outright rather than running an agent un-clamped. The three ways to trip it:

- **Bash was removed from the agent's tool pool** (by the spawn's own `disallowedTools`, the agent definition's denies, or absence from the session pool). A clamp on a Bash-less agent keeps nothing, so it refuses. Never put `Bash` in `disallowedTools` on a clamped spawn.
- **A malformed or inert entry.** Each entry must be a `Bash(<command or prefix>)` permission rule: tool name case-sensitive, non-empty content, no whitespace padding inside the parens.
- **A non-`claude` job whose clamp doesn't admit its worker.** A clamp that omits `scripts/compound-v-run-<backend>-worker.sh` cannot launch that family at all. Either add the worker invocation to the clamp, or give that job **no clamp** — which is what the generator does when it cannot find the worker script.

At runtime the same fail-closed posture applies to individual commands: *"no clamp rule matches this command"* and *"permission check crashed"* both **deny**.

## `compound-v-integration-gate.py` says `unverifiable` for every job

**Symptom:** the gate refuses integration and every job reads `unverifiable`.

**Cause:** it has nothing to gate. Before 3.0 nothing wrote the fields it needs — a smoke run against this release's own run dir returned `unverifiable` for all 18 jobs: no `results/` directory, `worktree: null`, no `baseline`. The gate is failing **closed**, correctly.

**Fix:** record what it needs, per job — `state.json jobs[<id>].worktree` (where to gate) and `.baseline` (the pinned pre-launch SHA to measure against), plus one `results/<id>.json`. Engine C writes all three. For an older run, supply them by hand or re-dispatch. Do not remove the worktrees first: without a gateable tree there is nothing to re-derive from.

**Related:** if a job reads `forged` with a duplicate-receipt reason, look for a stray `results/<id>.<something>.json`. D1 requires **exactly one** receipt per job, so any dotted sibling of the primary is read as a rival receipt. Superseded attempts belong in `results/attempts/`.

## Record reports a `verdict_disagreement`

**Symptom:** a job's ack and its `state.json` entry carry a `verdict_disagreement` object — `field`, `receipt`, `workflow`, `receipt_path` —
and, when `field` is `verdict`, the job's `summary` ends with:

```text
gate verdict disagreement: receipt <path> says <x>, the workflow held <y>; this comparison establishes no cause
```

**Cause:** two readings of the same gate differed, and Record says so instead of asserting why.

- `receipt` is the value in the gate receipt on disk — the artefact the gate itself wrote, and the one the integration authority
  re-derives against.
- `workflow` is the value the workflow carried in `--expect-verdict` — a value that travelled through an agent's transport.

**Neither of the two is a proven cause of the other.** A rewritten receipt, a mis-read field and a stale transport all look identical from
where this comparison stands; before 3.6 the message named a cause the code had never established, and that sentence is gone.

**Fix:** decide from the receipt, not from the summary.

1. `field: verdict` — the **receipt's** verdict is what got recorded, deliberately. Open `receipt_path`, check it against the job's
   `results/<id>.json` and the scope-gate outcome, and treat the workflow's value as the suspect reading.
2. `field: diff_digest` — this is **not** a soft disagreement. The job is recorded as an `error` and the receipt's verdict is **not**
   adopted, because the digest is what binds a receipt to the tree the gate measured. A missing digest counts as disagreement too, not as
   agreement. Re-run the tail for that job (`/v:collect <run-id>`) so a fresh receipt is written against the tree as it is now.
3. Never edit a receipt to make the two agree. That removes the signal and leaves the forgery check with nothing to catch.

Two things the field is **not**: it is not a scope-gate verdict (that lives in the job result's `violations`), and `/v:status` does not
render it — read it from `state.json` or the ack.

## A job with `depends_on` runs in the shared checkout instead of its own worktree

**Symptom:** a dependent job (one with `depends_on` and `isolation: worktree` in the manifest) shows `agent_isolation: null` in its job spec inside `docs/superpowers/execution/<run>/dispatch.workflow.js` (never in `state.json`, which keeps the manifest's `isolation: worktree`) and its agent edited the main checkout directly, alongside whatever else that wave is running — not an isolated worktree.

**Cause:** `scripts/compound-v-emit-workflow.py`'s `_worktree_base_is_head` reads `worktree.baseRef` from the project's `.claude/settings.json`. Absent (the default), a dependent worktree job's `agent_isolation` resolves to `None` and the agent runs direct in the shared checkout — because a fresh worktree still branches from the default ref, which cannot see the prerequisite wave's commit yet (finding 60). Set to `"head"`, every worktree in the repo branches from the current `HEAD` instead, and the dependent job gets a real, isolated worktree that does contain the prerequisite's commit.

**Fix:** add `{"worktree": {"baseRef": "head"}}` to the project's `.claude/settings.json` (merge — do not overwrite `permissions`/`hooks`/`env` or any other existing key). `/v:init` offers to make this edit for you; see [`v-init.md`](commands/v-init.md) Step 4d. This is a native, project-wide Claude Code setting (not a Compound V config key, and not the same file as `.claude/compound-v.json`) — the only two legal values are `"fresh"` (default) and `"head"`.

**Related:** the finalizer now takes its record of where a job ran from the emitter's own gate receipt rather than trusting the manifest's `isolation` label (finding 89), so a direct-mode dependent job is not refused at integration on that account alone. What `baseRef: head` buys is **parallelism**, not survival. Two or more dependent jobs sharing one checkout cannot be attributed — a single before-image cannot separate concurrent writers, so each job's diff carries the other's files and both are BLOCKED for out-of-lane writes. The emitter no longer allows that shape: a wave carrying 2+ downgraded jobs is split so each runs alone, and emit says on stderr which jobs it serialized and that this setting restores full parallelism. So without the setting a dependent wave still completes, just one job at a time.

## The lane guard never denies anything

**Symptom:** `hooks/lane-guard.sh` is registered, but an obviously out-of-lane write goes through.

**Cause:** the guard could not resolve which job is acting, and its contract is **fail-open** — a false deny inside a long autonomous run costs far more than a missed write the git gate catches anyway. It resolves `agent_id` first, then falls back to `cwd` → worktree, both via `docs/superpowers/execution/<run>/lane-map.json`. **If nothing wrote that file, the guard resolves nothing and allows everything, silently.**

**Fix:** dispatch through Engine C, which writes `lane-map.json` — each implementer registers its real worktree as its first command. Confirm the file exists and maps that worktree to the job. Check the guard's log (`$TMPDIR/compound-v-lane-guard.log`, or `$CV_LANE_GUARD_LOG`); it records every allow-because-unresolved.

Two honest limits: on Claude Code 2.1.238 an agent is **not told its own `agent_id`**, so the `agents` map is normally empty and resolution runs on the `worktrees` map — which is the fallback the 1D probe proved works. And the guard is **defence in depth, never the authority**: shell writes have unbounded evasions (`eval`, an interpreter one-liner, a variable holding the path), and the git-derived scope gate plus the integration postcondition still decide what enters the tree.

## A Compound V hook is noisy

**Symptom:** one particular hook (a nudge, a banner line, the triage record) keeps firing and you want it off without disabling the whole plugin.

**Fix:** set `CV_DISABLED_HOOKS` to a comma-separated list of hook basenames (no `.sh`; spaces around names are ignored), e.g. `CV_DISABLED_HOOKS=triage-prompt-nudge,memory-refresh`. It covers the 8 reminder/nudge/banner hooks in `hooks/` — not `lane-guard`, which deliberately ignores it (it is the pre-write enforcement gate; an env var that can switch it off, including one set for every clone via a committed `.claude/settings.json` `env` block, would widen an authorization). Naming `lane-guard` there is reported by the session banner as "ignored (enforcement hook)" and changes nothing.

Set it in the shell that launches Claude Code — verified by `tests/test-disabled-hooks.sh`. Per the Claude Code docs it can also go in `settings.json`'s `env` block and takes effect after a restart, but that path is **not verified here**.

## There is a line in `lane-guard-unresolved.jsonl`

**Symptom:** `docs/superpowers/execution/<run-id>/lane-guard-unresolved.jsonl` has one or more JSON lines, and the session that produced
one saw a notice saying an isolated agent resolved to no job in that run's live lane map and the write was not lane-checked.

**Cause, stated exactly:** at the moment of that `Write`/`Edit`/`Bash` call, the agent's `agent_id` and its worktree matched nothing in the
lane map, and all four recording gates were satisfied — a lane map was found, at least one worktree it names still exists on disk, the
`cwd` is inside `.claude/worktrees/<id>`, and the command was **not** the `register-lane` bootstrap. That fourth gate is the bootstrap
suppression: the one command every job must run *first* is, by construction, run before the job has an entry to resolve to, so recording it
would have made the record's opening line an incident the run's own contract mandates. It suppresses **only that command** — nothing else.

So what a record now means is narrow and worth reading literally: an isolated agent wrote something, under a live lane map, that the guard
could not attribute. The entry's `why` states that observation and nothing about the cause — a registration that was never run and one a
concurrent sibling's read-modify-write lost are indistinguishable from here. `candidate_runs` lists every lane map that was live at that
instant, newest first, and the line is written into the newest of them, so a record read weeks later cannot be mistaken for one written
while a different run held the tree. Lines are deduplicated per `(agent_id, cwd)` and the file is capped, so one mis-ordered job leaves one
line, not thousands.

**The two benign cases.** A job whose prompt orders a command *before* `register-lane` — a bare `pwd`, say — produces exactly one line, and
the job is otherwise fully compliant. And a non-Compound-V agent worktree that happens to be running while a Compound V run is live is
recorded the same way, because Engine C hands its workers no environment marker that would separate the two. Both are stated rather than
hidden; the cost of each is one line and one notice.

**Fix:** match the `cwd` and `ts` in the line against the run's jobs.

1. If it is a job of this run, confirm `register-lane` was its first command with a **literal** `--cwd` — the bash clamp refuses `$(pwd)`
   or `"$PWD"`, and a job denied on that command never registers at all, which leaves the guard nothing to resolve for the rest of the job.
2. If the identity is not a job of this run, it is the foreign-worktree case above; nothing is wrong with the run.
3. Either way the write was **allowed** — the guard is fail-open by contract. The authority is the git-derived scope gate, which measured
   that job's diff regardless, so check `results/<id>.json` before concluding anything escaped.

## The test floor reports nothing, or never ran

**Symptom:** no `tests` object on a job result, or a floor result that clearly executed no commands.

**Cause:** through 3.0 the floor's invocation carried `--test-cmd <configured-tests>` — an angle-bracket placeholder that **no caller ever substituted**, in either `/v:collect` or `agents/parallel-dispatcher.md`. That is why the floor had never executed once.

**Fix:** call the producer instead of the placeholder:

```bash
python3 scripts/compound-v-fastpath-run.py test-floor \
  --worktree "$WT" --baseline "$BASE" \
  --manifest "$RUN_DIR/manifest.yaml" --job-id "$JOB_ID" \
  (--last-result "$RUN_DIR/results/$JOB_ID.json" | --no-prior-run)
```

`--manifest` + `--job-id` resolve the command set from the manifest's `test_contract` and the job's `test_scope`. One of `--last-result` / `--no-prior-run` is required on purpose: silence must not become "nothing was failing". A worker gets the resolved slice as a real argument (`--test-contract-file`), never as prompt prose — a value a model has to notice is not a contract. And an **absent** `tests` object is honest; an invented zero is not.

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

`/v:archaeology` was removed in 3.4.16 — Phase 1A now runs inside the pre-flights (the
`superpowers-v:code-archaeologist` agent), so ask for the archaeology pre-flight rather than a
standalone command.

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

## A running Engine C job is reported `STALE` while the session is waiting out a usage limit

**Symptom:** `/v:status` or the liveness sweep marks a job `STALE` (no progress for 600 s) and the reason ends in `PAUSED?`, while `/workflows` shows the run waiting for a usage-limit reset.

**Cause:** since Claude Code 2.1.271 the Workflow runtime *pauses* a run whose agent hit the claude.ai usage limit instead of failing it — in an interactive, subscription-signed-in session with `autoContinueAtUsageLimit` on, when the reset is within 24 h and the run has not already waited twice. Nothing on disk records the pause, so a filesystem/git liveness probe cannot tell it from a hang.

**Fix:** none needed — read the `/workflows` header for the reset time and let it continue. The `PAUSED?` hint (3.7.0) is added only on Engine C runs (`dispatch.workflow.js` or `lane-map.json` present in the run dir). In `claude -p`, a background session, Remote Control or an agent-team teammate the run never pauses: the affected agent fails and the emitted script's retry/escalation ladder handles it, so a `STALE` there is a real timeout.

## The in-flight lane watch never reports a Bash write (`sed -i`, `tee`, codegen)

**Symptom:** `compound-v-transcript-watch.py` reports `Write`/`Edit` lane violations in flight but a Bash command that rewrote a file outside the lane is only caught by the scope gate at job end.

**Cause:** the watcher can only read what the transcript carries. A Bash result carries the list of files the command changed only when the native `bashEditDiffEnabled` setting is on (Claude Code ≥ 2.1.269, public beta, **user or managed scope only** — a project `.claude/settings.json` cannot turn it on).

**Fix:** set `"bashEditDiffEnabled": true` in `~/.claude/settings.json` (`/v:init` Step 4f offers the edit). The parser in 3.7.0 targets the documented `bashEditDiff` shape (`changedFiles`, `files[].filePath`) and is marked unverified-live in the source until a probe on a signed-in install confirms where the field lands in the transcript; without the setting the watch is still blind to Bash writes its command text does not name.

## `claude plugin eval .` refuses to start in this checkout

**Symptom:** `a plugin directory holds more than 20000 entries`, `Not logged in · Please run /login`, or a Bash-sandbox refusal naming a symbolic link under `~/.docker`.

**Cause and fix:** (1) stale `.claude/worktrees/` from earlier pipeline runs push the checkout over the eval harness's 20 000-entry scan limit — `git worktree list` and remove the ones with no commits ahead of `main`, or run the suite from a copy without `.git/` and `.claude/worktrees/`; (2) the CLI must be signed in (`claude auth status`) — a desktop-app session's login does not carry over to a nested `claude` process; (3) `find ~/.docker -type l` names the link the sandbox refuses; the harness documents this precondition nowhere, so it is recorded here.

## V-memory finds nothing for a Russian question, or for a paraphrase

**Symptom:** `/v:remember` (or `search`) misses an obviously related document when the question is in another language than the docs, or uses none of their words.

**Cause:** neither lane crosses that gap on this corpus. FTS5 matches words (Porter stemming, English only). The dense lane was expected to, and was measured not to: on the plugin's own repo, pure-Russian questions score 0/4 with and without it, because `multilingual-e5-small` pulls every Russian question towards the same few Russian-language documents; paraphrases score 0/3 either way (`skills/compound-v/memory.md` § Recall benchmark).

**Fix:** ask in English, keeping identifiers, flags and error strings verbatim — `/v:remember` now translates a non-English question itself and searches both forms (the same four questions went from 0/4 to 2/4). If a doc still does not surface, name one of its words: a flag, a file, an error message. To see which lane answered, read `doctor`'s `mode` line — "bootstrapped" alone only means the venv exists; the dense lane also needs `memory.embeddings: true` in `.claude/compound-v.json` and at least 80 vectors.

## `sqlite3` on this machine has no FTS5

**Symptom:** `doctor` prints `sqlite FTS5 : MISSING — …` and exits non-zero, or (on an older engine that didn't check yet) `refresh`/`search` raises a `sqlite3.OperationalError` mentioning `fts5`; a background `memory-refresh.sh` hook never builds an index either way (it redirects all output by design, so it never surfaces this on its own — run `refresh` yourself in the foreground to see it).

**Cause:** V-memory's FTS5 lane needs a `python3` whose linked `sqlite3` library was compiled with the FTS5 extension. Most `python.org` and Homebrew builds have it; some Linux distro packages of Python (and some very old macOS system pythons) don't.

**Fix:** `doctor`'s own message already names the fix — point at a `python3` that has FTS5: stock macOS `/usr/bin/python3` (Apple's system Python ships it), a python.org installer build, or a Homebrew build (`brew install python3`). Either put it first on `PATH` or invoke it explicitly: `/path/to/python3 scripts/compound-v-memory.py refresh`. To check a candidate interpreter by hand: `python3 -c "import sqlite3; sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE t USING fts5(x)'); print('FTS5 OK')"`. There is no code-level fallback: the engine is pure-stdlib by design (see `CONVENTIONS.md` §"Python: stdlib only"), so this is a "use a different interpreter" fix, not a config change.

## `recall-check` says tighten on a lane that never actually failed

**Symptom:** the deterministic recall→action bridge (`recall-check`, or the auto-tighten it drives at emit time) reports a `tighten` verdict for a file lane, but the prior runs it's counting weren't real content failures on that lane — they were a harness fault (an `error`/`timeout` job_result — out of credits, network, a crashed worker), a test-supervisor timeout, or a run the team has already flagged as not representative.

**Cause:** the engine only counts a `job_result` as evidence when the failure is attributable to the *job's own work* — a real scope violation (`violations` non-empty) or a real test failure (`tests.exit_code` nonzero and not the supervisor's own timeout code). Everything else is tallied separately as excluded and never taught to recall: a harness fault (`status` `error`/`timeout`), a test-supervisor timeout, a violation that only touched the run's own bookkeeping files (`state.json`, `preexisting/`, a baseline), an unattributed `blocked` with nothing to point at — or a run whose own `manifest.yaml` carries a top-level `recall_exclude: true`, the explicit "this was a deliberately planted failure (a dogfood probe), don't teach recall from it" escape hatch. See [`memory.md`](skills/compound-v/memory.md) for the full attribution table.

**Fix:** if a specific run's `job_result.json` genuinely wasn't a content failure and isn't already excluded by the rules above, set `recall_exclude: true` at the top level of that run's `manifest.yaml`, then re-run `recall-check` — the verdict is deterministic and re-derives cleanly from the same evidence. Don't hand-edit the `tighten`/`none` verdict itself; edit the manifest that the attribution reads.
