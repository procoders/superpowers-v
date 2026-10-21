# Adapter: Codex (headless `codex exec` worker)

> Read the contract in [`SKILL.md`](SKILL.md) first — this adapter implements that `job_spec → job_result` interface. This file is the backend-specific runbook; the wiring lives in [`scripts/compound-v-run-codex-worker.sh`](../../scripts/compound-v-run-codex-worker.sh).

The worker script ships with the plugin, not with the caller's repository. Resolve the plugin root
once per session before invoking it:

```bash
CV="${CLAUDE_PLUGIN_ROOT:-$(ls -d "$HOME"/.claude/plugins/cache/*/superpowers-v/*/ 2>/dev/null | sort -V | tail -1)}"
CV="${CV%/}"
[ -f "$CV/scripts/compound-v-emit-workflow.py" ] || CV="$PWD"
[ -f "$CV/scripts/compound-v-emit-workflow.py" ] || { echo "superpowers-v plugin root not found: reinstall the plugin" >&2; CV=""; }
```

`CLAUDE_PLUGIN_ROOT` is a hook-context hint, not a Bash variable, so the cache line covers an installed plugin, `$PWD` is used only inside a checkout of this plugin, and an empty `$CV` is a stop — do not run the steps below with it.

The Codex backend is a **Bash-spawned `codex exec` worker** — its own process, its own git worktree. It is never an `agents/` entry and never the experimental `openai-codex` `app-server` broker (that broker is single-flight and returns "busy" mid-turn, so it cannot fan out). The orchestrator hands this adapter a `job_spec` and gets back the canonical `job_result`; enforcement is git-derived by the caller, identical to every other backend.

Verified live against **codex-cli 0.144.1** on stock macOS (bash 3.2.57, git 2.50.1) — refreshed 2026-07-10 (was 0.130.0); **re-verified 2026-09-24 on codex-cli 0.156.1** with `gpt-6-sol`/`gpt-6-luna`, and **2026-09-30 on 0.159.1** with `gpt-6.1-sol`/`gpt-6-astra`, at `model_reasoning_effort=xhigh` (rc 0, `thread.started` event present, `--output-last-message` written). All facts below are pinned — do not re-derive them per run; re-probe only in `/v:init`.

---

## The 6 load-bearing steps

The worker script performs steps 1–5; the **caller** (dispatcher) performs step 6.

```
1. ISOLATE   git -C <repo> worktree add <WT> HEAD          # kernel-bounds blast radius + clean diff baseline
2. RUN       run-with-timeout.py --timeout <sec> -- codex exec … <prompt>   # headless, sandboxed to <WT>, tree-capped
3. OBSERVE   git -C <WT> diff --name-only                   # ∪
             git -C <WT> ls-files --others --exclude-standard
4. ENFORCE   every changed path ∉ write_allowed ⇒ violation ⇒ blocked  (do NOT merge)
5. NORMALIZE → job_result  (summary ← --output-last-message; session_id ← thread_id from the --json `thread.started` event)
6. MERGE     caller, on PASS only:  git -C <WT> add -A
             git -C <WT> diff --cached --binary HEAD | (cd <repo> && git apply --index)  →  git worktree remove -f <WT>
```

Step 4 is the keystone. Codex's sandbox can restrict writes to a *directory* but **not to a file allow-list** — so the only way to enforce an exact file list is worktree (prevention: kernel-isolated blast radius) **plus** `git diff` (detection: reject anything outside the list). Steps 3–4 are computed in git, never read from anything the model says it did. The script's `path_is_allowed` is a fast first-pass; the deterministic authority the dispatcher runs after every job is [`scripts/compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py).

**Only `write_allowed` is enforced; `read_allowed` is advisory.** Steps 3–4 are a git diff, and git tracks writes, not reads — so `write_allowed` is the hard, enforced boundary (anything outside it BLOCKS), while `read_allowed` only scopes the worker prompt and documents intent. Codex's `read-only` sandbox can forbid *all* writes, but there is no git-derived gate that detects an out-of-scope read. Never treat `read_allowed` as enforced.

---

## Worker-prompt planner/executor lock

Every dispatched `prompt` MUST open with this lock (verbatim-in-spirit), exactly as the contract in `SKILL.md` requires:

> You are an implementation worker, NOT the planner. Do not change architecture. Do not write outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report BLOCKED.

This is the *instructed* half of planner/executor separation. The git-diff scope gate (steps 3–4) is the *enforced* half. A Codex executor cannot silently change the plan or stomp a shared file, because the gate catches it regardless of whether the prompt held — that is precisely why the enforcement fields are git-derived and never trusted from the model.

The worker prompt is passed to the script via `--prompt-file <abs-path>` (a file, not an inline arg) so multi-paragraph prompts and the lock survive shell quoting intact. The script reads it and passes it as the positional `[PROMPT]` to `codex exec`.

---

## Pinned `codex exec` flag set (codex-cli 0.144.1, re-verified 0.156.1)

The script uses **exactly** this set — verified present in `codex exec --help`:

```bash
python3 "$SUPERVISOR" --timeout "$timeout_sec" -- codex exec \
  --cd "$WT" \
  --sandbox "$([ "$read_only" = true ] && echo read-only || echo workspace-write)" \
  --skip-git-repo-check \
  --json \
  --model "$model" \
  ${effort:+-c model_reasoning_effort="$effort"} \
  ${output_schema:+--output-schema "$output_schema"} \
  --output-last-message "$ART/job_result.txt" \
  -c "sandbox_workspace_write.network_access=$network" \
  "$prompt" </dev/null   # codex stdout (the JSONL stream) → --events-log
```

`--json` is added to **both** invocations in the script (the `--output-schema` path and the plain path — the mirror hazard; they must stay identical). It turns codex's stdout into a JSONL event stream whose **first** line is `{"type":"thread.started","thread_id":"<uuid>"}` (live-probed, codex-cli 0.144.1; re-verified 0.156.1). The worker redirects that stdout to the **events-log** (`--events-log <path>`, default `$ART/codex_events.jsonl`; the dispatcher passes `docs/superpowers/execution/<run-id>/logs/<job-id>.jsonl`) and parses the first `thread.started` event for `thread_id` → `session_id`. `--json` and `--output-last-message` **coexist** — the last-message file is still written verbatim, so the `summary` extraction path is unchanged.

**Stream + scratch handling — verified live, all load-bearing (caught by the v1.0 smoke + e2e tests):**
- **stdin → `/dev/null`.** The prompt is positional, but `codex exec` still reads stdin when it is not a TTY and will hang on `Reading additional input from stdin...` in a non-interactive / background run. `</dev/null` makes stdin an immediate EOF so only the positional prompt is used.
- **codex stdout → the events-log, never passed through.** With `--json`, `codex exec` prints its *event stream* (JSONL) to *stdout*; the script redirects it to the **events-log** so the worker's own stdout carries only the canonical `job_result` JSON (session_id rides inside it). The summary comes from `--output-last-message`; the **session-id is parsed structurally** from the events-log's first `thread.started` event (no more stderr-banner scrape) — so codex's raw stdout is never leaked to the caller.
- **scratch lives OUTSIDE the worktree.** `$ART` is a sibling dir under `$TMPDIR` (one of codex's `workspace-write` sandbox roots, so `--output-last-message` can be written there). The worktree therefore stays **pristine** — only the job's real output appears in `git diff`, so the generic scope-gate (`scripts/compound-v-scope-check.py`) agrees with this worker's own enforcement without any codex-specific ignore list.

| Flag | Role |
|---|---|
| `--cd "$WT"` | working root = the worktree (sandbox is scoped here) |
| `--sandbox workspace-write` \| `read-only` | OS-level write boundary; `read-only` for read-only jobs |
| `--skip-git-repo-check` | the worktree is a linked checkout; suppress the repo-root check |
| `--json` | stdout becomes a JSONL event stream; first line `{"type":"thread.started","thread_id":"<uuid>"}` → the resume id. Added to **both** invocations (mirror hazard). Coexists with `--output-last-message` |
| `--model "$model"` | execution-layer model (e.g. `gpt-6.1-sol`) — **resolved** from `(backend=codex, tier, effort)` before dispatch; never appears in any frontmatter |
| `-c model_reasoning_effort=<effort>` | optional; codex's reasoning-effort dimension, set from the job's `effort` hint (`low` \| `medium` \| `high` \| `xhigh` — `xhigh` is codex-only) — see below |
| `--output-schema "$file"` | optional; strict JSON Schema for the model's final message (drives only `summary`) |
| `--output-last-message "$file"` | where the agent's last message is written → feeds the human `summary` |
| `-c sandbox_workspace_write.network_access=<bool>` | network on/off inside the sandbox |
| `"$prompt"` | positional initial instructions (the worker prompt, lock first) |

> `--events-log <path>` is a **worker-script arg** (not a `codex exec` flag): it names the file the `--json` stdout stream is redirected to. Optional — defaults to `$ART/codex_events.jsonl` for standalone use; the dispatcher passes its run-dir path `docs/superpowers/execution/<run-id>/logs/<job-id>.jsonl` and records that same path in `state.json jobs[<id>].log` for liveness. The redirect is the worker's own shell (codex writes to the pipe, not to a file inside its sandbox), so the events-log may live anywhere the worker can write, including the main tree's run-dir — which never appears in the worktree diff.

### `--ask-for-approval never` is INVALID for `codex exec` — omitted

This is the defect the dogfood pre-flight caught in the PRD's original draft. `--ask-for-approval` (`-a`) is a **top-level / interactive** flag (it appears in `codex --help`, **not** in `codex exec --help`). `codex exec` already defaults to `approval: never`, so the flag is both redundant and rejected — passing it would fail **every** Codex job. It is therefore **deliberately omitted**. If a non-default policy is ever genuinely needed, use the config override `-c approval_policy=never` instead (an `exec`-valid form), never the top-level flag.

### Model + effort: resolved before dispatch, not hardcoded

The dispatcher never hands this adapter a hardcoded model string. It hands a routing **intent** — `tier` (`frontier` \| `deep` \| `standard` \| `light`) plus an optional orthogonal `effort` (`low` \| `medium` \| `high` \| `xhigh`, the last codex-only — see below) — and resolves the concrete model **before** dispatch via [`scripts/compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) with `--backend codex --tier <tier> [--effort <effort>] [--config .claude/compound-v.json]`. The resolver reads the config `models.codex.<tier>` map — as of 2026-09-24 the default is `frontier` → `gpt-6-astra`, `deep` → `gpt-6.1-sol`, `standard` → `gpt-6.1-sol`, `light` → `gpt-6-luna` (the GPT-6 family, which arrived in Codex 2026-09-22/23 on codex-cli 0.156.0/0.156.1; `deep` and `standard` share the same model and differ only by `effort`, the orthogonal axis) — and yields the concrete `--model` value; an explicit manifest `model` override skips resolution and wins. (History: the map was GPT-5.6 `sol`/`sol`/`terra`/`luna` from 2026-07-10 through 2026-09-23; `gpt-5.6-sol` required codex-cli >= 0.143.0, an older client failing loud with a clear 400 `"requires a newer version of Codex"`. The GPT-5.6 trio is still in the catalog, described as "Older …"; `gpt-5.5` retires 2026-10-14, upgrading to `gpt-5.6-sol`.) Codex now **has** a model-list command: `codex debug models` renders the full catalog as JSON (`slug`, `display_name`, `description`, `visibility`, `priority`, `upgrade.retirement_at`, `supported_reasoning_levels`, `default_reasoning_level`, `context_window`) — so `/v:models` §1b discovers it live via [`scripts/compound-v-discover-models.py`](../../scripts/compound-v-discover-models.py) `--backend codex` instead of maintaining a hand-curated roster (see [`v-models.md`](../../commands/v-models.md)). The plugin survives model churn because the call sites pass `tier`, never a literal model string.

**`--effort` → `-c model_reasoning_effort=<effort>` (codex's effort dimension).** `effort` is orthogonal to `tier`: `tier` picks *which* model, `effort` tunes *how hard it reasons*. The worker script ([`scripts/compound-v-run-codex-worker.sh`](../../scripts/compound-v-run-codex-worker.sh)) takes an optional `--effort low|medium|high|xhigh`. When set, it appends `-c model_reasoning_effort=<effort>` to **both** `codex exec` invocations (the `--output-schema` path and the plain path), word-split safely under bash 3.2. When omitted, the flag vanishes and codex uses the model's default reasoning effort. The dispatcher passes `--effort` to the worker only when the job carries an `effort` value; it is validated against `low|medium|high|xhigh` and the run aborts (usage fault) on any other value. This is the codex-specific surfacing of the effort dimension that the generic resolver/manifest expose backend-agnostically — the claude adapter, by contrast, treats per-call effort as advisory because the `Task` path has no separate effort flag.

**`xhigh` — codex's top *adopted* effort rung, codex-only.** `xhigh` is valid **iff** `backend: codex`; every other backend rejects it with a clear error naming the rule (use `high` instead). It maps to `-c model_reasoning_effort=xhigh`, **live-verified 2026-07-11 on codex-cli 0.144.1** (`codex exec --model gpt-5.6-sol -c model_reasoning_effort=xhigh` → exit 0, normal completion), **re-verified 2026-09-24 on codex-cli 0.156.1** with `gpt-6-sol` and `gpt-6-luna` (rc 0, `thread.started` event present, `--output-last-message` written). The rejection is enforced at every layer: [`compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) errors on any non-codex backend + `xhigh`, and [`compound-v-validate-manifest.py`](../../scripts/compound-v-validate-manifest.py) rejects a manifest job pairing `effort: xhigh` with any backend other than `codex`.

**Not adopted: `max`, `ultra`.** GPT-6's `astra`/`sol` also expose an `ultra` reasoning level above `xhigh` ("Maximum reasoning with automatic task delegation"), and all three GPT-6 models expose `max`. Compound V adopts neither. `max` is simply out of scope this release. `ultra` is a **lane hazard, not merely unadopted**: its automatic delegation spawns sub-agents that write outside this job's declared `write_allowed` lane — writes the git-derived scope gate would BLOCK after the fact, and the `PreToolUse` lane guard cannot see coming at all, because they happen inside codex's own process tree, never through a Claude Code tool call. Never pass `-c model_reasoning_effort=ultra` or `=max`.

### Other pinned facts

- **`git worktree diff` does not exist.** Observation uses plain `git -C "$WT" diff --name-only` + `git -C "$WT" ls-files --others --exclude-standard`. Both halves are required: `diff` catches edits to tracked files; `ls-files --others` catches brand-new untracked files the diff would miss.
- **codex emits a cosmetic `[features].codex_hooks is deprecated` warning on stderr.** The script filters exactly that line out of the captured stderr so it stays clean for the failure classifier; all other stderr is preserved. (The session-id no longer comes from stderr — it is parsed from the `--json` `thread.started` event — so this filter is purely classifier hygiene now.)
- **Wall-clock cap via the process-group supervisor.** The script runs codex under the shared [`scripts/compound-v-run-with-timeout.py`](../../scripts/compound-v-run-with-timeout.py) (`python3 "$SUPERVISOR" --timeout <sec> -- codex exec …`) — **no external `timeout`/`gtimeout` binary needed**. On expiry it `killpg`s the whole codex process tree (not just the direct child) and returns `124`, which the script maps to `status: "timeout"`. Verified live (success + `--timeout-sec 1 ⇒ status:timeout`).

---

## Worktree lifecycle

```bash
# create — fresh checkout at HEAD = a clean diff baseline so step-3 diff is exactly the job's edits
git -C "$REPO" worktree add "$WT" HEAD

# … codex exec runs with --cd "$WT" …

# remove — on PASS, AFTER the caller merges (step 6); on BLOCKED, leave it for inspection
git -C "$REPO" worktree remove -f "$WT"
```

Worktrees live **outside the repo**, under `"${TMPDIR:-/tmp}"/compound-v/<run-id>/<job-id>` — so no `.gitignore` change is needed. The script is **idempotent on resume**: if a worktree already exists at that path (e.g. a re-dispatched job), it is `worktree remove -f`'d (falling back to `rm -rf`) before a fresh `add HEAD`. The script itself never calls `worktree remove` on success — it leaves the worktree in place so the caller can merge from it; removal is the caller's responsibility after a successful `git apply`.

**This create step is the ONLY correct way to fix a wrong worktree base — never ask Codex to rebase/reset it itself.** Under this adapter's documented pinned invocation (`--sandbox workspace-write --cd "$WT"`, no sandbox-bypass flag), Codex's sandbox is confined to `$WT`, but a worktree's actual git metadata lives in `<REPO>/.git/worktrees/<job-id>/` — outside `$WT` — so that operation is outside the sandbox root, and `approval_policy: never` means it can't ask to escalate either. See [`SKILL.md`](SKILL.md) §Worktree git-base fixes for the full rationale and why dropping worktree isolation is not the fix.

---

## Merge-back (caller, step 6)

The script **observes and reports only — it never merges.** The dispatcher decides, based on `job_result.status`:

- **PASS** (`status: success`): apply the worktree's changes — **including new (untracked) files** — into the main tree, then drop the worktree.
  ```bash
  # add -A stages new + modified files so the patch INCLUDES additions;
  # --cached --binary makes a complete index patch; --index applies it to the
  # main tree's index too. A plain `git diff HEAD | git apply` would DROP added
  # files — an allowed new file would pass the gate but never land.
  git -C "$WT" add -A
  git -C "$WT" diff --cached --binary HEAD | (cd "$REPO" && git apply --index)
  git -C "$REPO" worktree remove -f "$WT"
  ```
  This loses per-job commit attribution, which is acceptable because the file sets are disjoint (the partition guarantee). The index-based patch above covers BOTH tracked edits and brand-new untracked files in one step — no separate copy/stage pass is needed.
- **BLOCKED** (`status: blocked`): **do not merge.** Leave the worktree on disk for inspection and surface the `violations`. The run halts.
- **timeout / error**: do not merge; the partial worktree is left for inspection and the job is eligible for re-dispatch on `/v:resume`.

---

## Resume

Codex sessions resume by UUID, captured into `job_result.session_id` from the `--json` `thread.started` event (there is **no `--session-id` flag**, and no launch-time thread naming in `codex exec` — live-probed; capture the auto-generated UUID):

```bash
codex exec resume <SESSION_ID> [PROMPT]     # the captured thread_id UUID
codex exec resume --last [PROMPT]           # most recent recorded session
```

The script parses the **first** `{"type":"thread.started","thread_id":"<uuid>"}` line of the events-log (the `--json` stream) into `session_id` — the value is forced to a JSON string (`jq 'select(type=="string")'`) and then UUID-shape-validated with a Bash `[[ =~ ]]` anchored to the whole scalar, so a malformed / partial JSONL line, or a `thread_id` containing a newline, yields an empty id rather than a crash or an injected token. When no `thread.started` event is captured, `session_id` is the empty string (the schema permits it); the job is then re-dispatched fresh rather than resumed, consistent with the **git-wins** resume tie-break (if `state.json` says done but the files aren't in git, re-dispatch). Resume by the captured UUID is authoritative — never resume by cwd filtering, since the worktree paths are ephemeral (pass the UUID explicitly, or `--all`).

---

## Invoking the script

```bash
"$CV/scripts/compound-v-run-codex-worker.sh" \
  --run-id   2026-06-26-linkedin-sequence-editor \
  --job-id   task-1-editor-ui \
  --repo     /abs/path/to/repo \
  --prompt-file /abs/path/to/jobs/task-1-editor-ui.prompt.md \
  --model    gpt-6.1-sol \
  --write-allowed "src/features/sequences/components/**" \
  --timeout-sec 900 \
  --network  false
# optional: --read-only true   --output-schema /abs/schemas/job_result.schema.json
# optional: --effort medium    # → appended as -c model_reasoning_effort=medium
# optional: --events-log /abs/run-dir/logs/task-1-editor-ui.jsonl   # where the --json stream is written
```

- `--model` is the **resolved** concrete model from `compound-v-resolve-model.py` (or the manifest's explicit override); this adapter never picks it from a literal in routing.
- `--effort {low|medium|high|xhigh}` is optional — when present it becomes `-c model_reasoning_effort=<effort>` on the `codex exec` line; when absent, codex uses the model's default reasoning effort. `xhigh` is accepted here because this worker IS the codex backend (`xhigh` is valid **iff** `backend: codex`).

- All file paths MUST be **absolute** (the script rejects relative `--repo` / `--prompt-file` / `--output-schema`).
- `--write-allowed` is a **colon-separated** glob list (`a/**:b/c.ts`), matched repo-relative against changed paths. An **empty** `--write-allowed` is valid and means a **read-only / review job**: no writes are permitted, so the scope gate (run with zero allowed globs) treats ANY changed path as a violation and the job is BLOCKED. Pair it with `--read-only true` for a pure review worker.
- `--timeout-sec` must be a **positive integer** (`^[0-9]+$`); the script `die`s on anything else (it is passed to the supervisor's `--timeout` and used in arithmetic).
- **stdout** carries exactly one canonical `job_result` JSON (no preamble line). `session_id` rides inside that JSON; the dispatcher reads it from `job_result.session_id` and persists it into `state.json jobs[<id>].session_id` alongside `failure_class`. There is no line to strip — stdout is single-JSON, matching the generic backend contract.
- **Exit 0** means a `job_result` was produced (even for BLOCKED / timeout / error — those live in `status`). A non-zero exit means a usage/environment fault prevented producing a result at all.

The script targets stock-macOS **bash 3.2** (no associative arrays / `mapfile` / `${var,,}`) and uses only `git` + `jq`. It is shellcheck-clean and `chmod +x`.

---

## The test contract — a real argument, never prompt prose (v3.0, Feature B3)

Read [`SKILL.md`](SKILL.md) first: the contract, its shape, and who resolves it. This adapter's part
is one flag pair, and the fact that it is a **flag** at all is the whole point — before 3.0 the only
way a job's `test_scope` could reach a headless Codex worker was as a sentence inside
`--prompt-file`, hoping the model noticed it.

```bash
"$CV/scripts/compound-v-run-codex-worker.sh" \
  … \
  --test-contract-file /abs/run-dir/jobs/<job-id>.test-contract.json \
  --test-timeout-sec 900        # optional, default 900, per COMMAND
```

- The file holds the **resolved** slice: `{scope, resolved_commands[, floor_command, full_command]}`.
  The caller resolves it (`impacted_map` globs stay in the caller's Python — a second matcher here
  would diverge from the authority and silently *drop* tests); the worker executes exactly that list.
- It is **structurally validated before codex is launched**. A malformed contract, an unknown key,
  a scope outside `full|impacted|floor_only|impacted+referencing`, a non-integer `selected_count`, an empty `resolved_commands`, or a blank command is a
  **usage fault (exit 2)**, not a test failure — a blank command would `bash -c` to a silent exit 0.
- Each command runs under the process-group supervisor with `</dev/null`, `--cwd` the worktree, and
  its output captured to files under `$WT.art/tests/` (outside the worktree, so stdout stays exactly
  one `job_result` JSON and a hung test cannot outlive the job).
- Commands run **after** the scope gate and **only** when the job would otherwise be `success`; the
  measured result lands in `job_result.tests` (`command`, `exit_code`, `scope`, `selected_count`,
  plus measured-only `duration_ms` and `failures[]`). Omit the flag and the worker runs no tests and
  emits no `tests` object at all.
- A non-zero `tests.exit_code` does **not** change `status` — the caller must not merge it, and the
  review gate FAILs a job that reports no test command. `status`/`failure_class` stay the backend's
  disposition, so a red suite is never fed to the retry/reroute policy that cannot fix it.
- Because tests run after the gate, anything they create in the worktree is **outside the gate's
  authority**: merge-back stages by the gate's `files_changed`, never a bare `git add -A`.

---

## Provisioning — `--provision-command` / `--provision-timeout-sec` (v3.6)

Read [`SKILL.md`](SKILL.md) §Provisioning first: the contract and its ordering guarantee apply
identically across all four external workers. This is the codex-specific invocation.

```bash
"$CV/scripts/compound-v-run-codex-worker.sh" \
  … \
  --provision-command "npm ci" \
  --provision-timeout-sec 600          # optional, default 600
```

- The command runs **after** `git -C "$REPO" worktree add "$WT" HEAD` and **before** codex is
  launched, through `/bin/bash -c "$PROVISION_COMMAND"` under the shared process-group supervisor
  ([`scripts/compound-v-run-with-timeout.py`](../../scripts/compound-v-run-with-timeout.py)),
  `--cwd "$WT"`, stdin `</dev/null`, stdout/stderr captured to `$ART/provision.out` /
  `$ART/provision.err` (outside the worktree, so nothing it prints lands in `git diff`).
- On success the worker snapshots the worktree's untracked+ignored paths to
  `$ART/preexisting.txt` and passes it to the scope gate as `--preexisting` — this is the **only**
  place provisioning's writes are exempted from `write_allowed`; anything the model writes into
  those same paths afterwards is still measured and still blocks. This snapshot happens strictly
  before `codex exec` is invoked.
- **`--provision-timeout-sec` must be a positive integer** (the same validation as
  `--timeout-sec`) — an empty, non-numeric, or zero value is a usage fault (`die`, exit ≠ 0,
  no `job_result`), never a silent default. **Default: 600 seconds.**
- **A non-zero provision exit code launches no `codex exec` at all.** The worker emits
  `status: "error"`, `failure_class: "other"`, and a summary of
  `provision failed (rc=<code>): <command>` (rc `124` is the provision timeout firing), then exits
  `0` — this is a reported job outcome, not a script crash, so the caller's retry/reroute policy
  sees a real `failure_class` rather than a bare non-zero exit. No `codex exec` process, no
  `--json` event stream, no `session_id`.
- `--provision-command` is optional. Omit it and this worker's behaviour is unchanged from
  before v3.6 — no provisioning step, no `--preexisting` snapshot, no new timing.
- **`--toolchain-artifact <glob>` (v3.6.3, repeatable)** is the manifest's `toolchain_artifacts`
  list, one flag per glob, forwarded to the scope gate unchanged. It is a second, distinct
  exemption from `--preexisting`: `--preexisting` forgives what provisioning wrote *before* codex
  starts, while `--toolchain-artifact` forgives a matching gitignored path the test floor writes
  *during* the job (`tsconfig.tsbuildinfo`, a vitest/jest cache) — subtracted only when `git
  check-ignore` confirms it is actually gitignored in the gated tree. See
  [`SKILL.md`](SKILL.md#provisioning----provision-command----provision-timeout-sec-v36).
