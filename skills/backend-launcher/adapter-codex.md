# Adapter: Codex (headless `codex exec` worker)

> Read the contract in [`SKILL.md`](SKILL.md) first — this adapter implements that `job_spec → job_result` interface. This file is the backend-specific runbook; the wiring lives in [`scripts/compound-v-run-codex-worker.sh`](../../scripts/compound-v-run-codex-worker.sh).

The Codex backend is a **Bash-spawned `codex exec` worker** — its own process, its own git worktree. It is never an `agents/` entry and never the experimental `openai-codex` `app-server` broker (that broker is single-flight and returns "busy" mid-turn, so it cannot fan out). The orchestrator hands this adapter a `job_spec` and gets back the canonical `job_result`; enforcement is git-derived by the caller, identical to every other backend.

Verified live against **codex-cli 0.130.0** on stock macOS (bash 3.2.57, git 2.50.1). All facts below are pinned — do not re-derive them per run; re-probe only in `/v:init`.

---

## The 6 load-bearing steps

The worker script performs steps 1–5; the **caller** (dispatcher) performs step 6.

```
1. ISOLATE   git -C <repo> worktree add <WT> HEAD          # kernel-bounds blast radius + clean diff baseline
2. RUN       run-with-timeout.py --timeout <sec> -- codex exec … <prompt>   # headless, sandboxed to <WT>, tree-capped
3. OBSERVE   git -C <WT> diff --name-only                   # ∪
             git -C <WT> ls-files --others --exclude-standard
4. ENFORCE   every changed path ∉ write_allowed ⇒ violation ⇒ blocked  (do NOT merge)
5. NORMALIZE → job_result  (summary ← --output-last-message; session_id ← run banner UUID)
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

## Pinned `codex exec` flag set (codex-cli 0.130)

The script uses **exactly** this set — verified present in `codex exec --help`:

```bash
python3 "$SUPERVISOR" --timeout "$timeout_sec" -- codex exec \
  --cd "$WT" \
  --sandbox "$([ "$read_only" = true ] && echo read-only || echo workspace-write)" \
  --skip-git-repo-check \
  --model "$model" \
  ${effort:+-c model_reasoning_effort="$effort"} \
  ${output_schema:+--output-schema "$output_schema"} \
  --output-last-message "$ART/job_result.txt" \
  -c "sandbox_workspace_write.network_access=$network" \
  "$prompt" </dev/null
```

**Stream + scratch handling — verified live, all load-bearing (caught by the v1.0 smoke + e2e tests):**
- **stdin → `/dev/null`.** The prompt is positional, but `codex exec` still reads stdin when it is not a TTY and will hang on `Reading additional input from stdin...` in a non-interactive / background run. `</dev/null` makes stdin an immediate EOF so only the positional prompt is used.
- **codex stdout → captured, never passed through.** `codex exec` prints its final agent message to *stdout*; the script redirects it to a scratch log so the worker's own stdout carries **only** the canonical `job_result` JSON. The summary comes from `--output-last-message`; the session-id from the stderr banner — so codex's stdout is safely discarded.
- **scratch lives OUTSIDE the worktree.** `$ART` is a sibling dir under `$TMPDIR` (one of codex's `workspace-write` sandbox roots, so `--output-last-message` can be written there). The worktree therefore stays **pristine** — only the job's real output appears in `git diff`, so the generic scope-gate (`scripts/compound-v-scope-check.py`) agrees with this worker's own enforcement without any codex-specific ignore list.

| Flag | Role |
|---|---|
| `--cd "$WT"` | working root = the worktree (sandbox is scoped here) |
| `--sandbox workspace-write` \| `read-only` | OS-level write boundary; `read-only` for read-only jobs |
| `--skip-git-repo-check` | the worktree is a linked checkout; suppress the repo-root check |
| `--model "$model"` | execution-layer model (e.g. `gpt-5.5`) — **resolved** from `(backend=codex, tier, effort)` before dispatch; never appears in any frontmatter |
| `-c model_reasoning_effort=<effort>` | optional; codex's reasoning-effort dimension, set from the job's `effort` hint (`low` \| `medium` \| `high`) — see below |
| `--output-schema "$file"` | optional; strict JSON Schema for the model's final message (drives only `summary`) |
| `--output-last-message "$file"` | where the agent's last message is written → feeds the human `summary` |
| `-c sandbox_workspace_write.network_access=<bool>` | network on/off inside the sandbox |
| `"$prompt"` | positional initial instructions (the worker prompt, lock first) |

### `--ask-for-approval never` is INVALID for `codex exec` — omitted

This is the defect the dogfood pre-flight caught in the PRD's original draft. `--ask-for-approval` (`-a`) is a **top-level / interactive** flag (it appears in `codex --help`, **not** in `codex exec --help`). `codex exec` already defaults to `approval: never`, so the flag is both redundant and rejected — passing it would fail **every** Codex job. It is therefore **deliberately omitted**. If a non-default policy is ever genuinely needed, use the config override `-c approval_policy=never` instead (an `exec`-valid form), never the top-level flag.

### Model + effort: resolved before dispatch, not hardcoded

The dispatcher never hands this adapter a hardcoded model string. It hands a routing **intent** — `tier` (`deep` \| `standard` \| `light`) plus an optional orthogonal `effort` (`low` \| `medium` \| `high`) — and resolves the concrete model **before** dispatch via [`scripts/compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) with `--backend codex --tier <tier> [--effort <effort>] [--config .claude/compound-v.json]`. The resolver reads the config `models.codex.<tier>` map (e.g. `deep`/`standard` → `gpt-5.5`, `light` → `gpt-5.3-codex-spark`) and yields the concrete `--model` value; an explicit manifest `model` override skips resolution and wins. Codex has **no list command**, so its map is curated + user-overridable (refresh via `/v:models`). The plugin survives model churn because the call sites pass `tier`, never a literal model string.

**`--effort` → `-c model_reasoning_effort=<effort>` (codex's effort dimension).** `effort` is orthogonal to `tier`: `tier` picks *which* model, `effort` tunes *how hard it reasons*. The worker script ([`scripts/compound-v-run-codex-worker.sh`](../../scripts/compound-v-run-codex-worker.sh)) takes an optional `--effort low|medium|high`. When set, it appends `-c model_reasoning_effort=<effort>` to **both** `codex exec` invocations (the `--output-schema` path and the plain path), word-split safely under bash 3.2. When omitted, the flag vanishes and codex uses the model's default reasoning effort. The dispatcher passes `--effort` to the worker only when the job carries an `effort` value; it is validated against `low|medium|high` and the run aborts (usage fault) on any other value. This is the codex-specific surfacing of the effort dimension that the generic resolver/manifest expose backend-agnostically — the claude adapter, by contrast, treats per-call effort as advisory because the `Task` path has no separate effort flag.

### Other pinned facts

- **`git worktree diff` does not exist.** Observation uses plain `git -C "$WT" diff --name-only` + `git -C "$WT" ls-files --others --exclude-standard`. Both halves are required: `diff` catches edits to tracked files; `ls-files --others` catches brand-new untracked files the diff would miss.
- **codex emits a cosmetic `[features].codex_hooks is deprecated` warning on stderr.** The script filters exactly that line out of the captured stderr so it never pollutes the banner scan or the result; all other stderr is preserved.
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

**This create step is the ONLY correct way to fix a wrong worktree base — never ask Codex to rebase/reset it itself.** Codex's sandbox is confined to `$WT`, but a worktree's actual git metadata lives in `<REPO>/.git/worktrees/<job-id>/` — outside `$WT` — so Codex cannot touch it even with `--dangerously`-style flags, and `approval_policy: never` means it can't ask to escalate either. See [`SKILL.md`](SKILL.md) §Worktree git-base fixes for the full rationale and why dropping worktree isolation is not the fix.

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

Codex sessions resume by UUID, captured into `job_result.session_id` from the run banner (there is **no `--session-id` flag**):

```bash
codex exec resume <SESSION_ID> [PROMPT]     # UUID from the banner
codex exec resume --last [PROMPT]           # most recent recorded session
```

The script scrapes the first UUID-shaped token out of the (deprecation-filtered) stderr banner — and the `--output-last-message` file as a fallback — into `session_id`. When no UUID is found, `session_id` is the empty string (the schema permits it); the job is then re-dispatched fresh rather than resumed, consistent with the **git-wins** resume tie-break (if `state.json` says done but the files aren't in git, re-dispatch).

---

## Invoking the script

```bash
scripts/compound-v-run-codex-worker.sh \
  --run-id   2026-06-26-linkedin-sequence-editor \
  --job-id   task-1-editor-ui \
  --repo     /abs/path/to/repo \
  --prompt-file /abs/path/to/jobs/task-1-editor-ui.prompt.md \
  --model    gpt-5.5 \
  --write-allowed "src/features/sequences/components/**" \
  --timeout-sec 900 \
  --network  false
# optional: --read-only true   --output-schema /abs/schemas/job_result.schema.json
# optional: --effort medium    # → appended as -c model_reasoning_effort=medium
```

- `--model` is the **resolved** concrete model from `compound-v-resolve-model.py` (or the manifest's explicit override); this adapter never picks it from a literal in routing.
- `--effort {low|medium|high}` is optional — when present it becomes `-c model_reasoning_effort=<effort>` on the `codex exec` line; when absent, codex uses the model's default reasoning effort.

- All file paths MUST be **absolute** (the script rejects relative `--repo` / `--prompt-file` / `--output-schema`).
- `--write-allowed` is a **colon-separated** glob list (`a/**:b/c.ts`), matched repo-relative against changed paths. An **empty** `--write-allowed` is valid and means a **read-only / review job**: no writes are permitted, so the scope gate (run with zero allowed globs) treats ANY changed path as a violation and the job is BLOCKED. Pair it with `--read-only true` for a pure review worker.
- `--timeout-sec` must be a **positive integer** (`^[0-9]+$`); the script `die`s on anything else (it is passed to the supervisor's `--timeout` and used in arithmetic).
- **stdout** is the canonical `job_result` JSON and nothing else — the dispatcher pipes it straight to the collector and the scope-check authority.
- **Exit 0** means a `job_result` was produced (even for BLOCKED / timeout / error — those live in `status`). A non-zero exit means a usage/environment fault prevented producing a result at all.

The script targets stock-macOS **bash 3.2** (no associative arrays / `mapfile` / `${var,,}`) and uses only `git` + `jq`. It is shellcheck-clean and `chmod +x`.
