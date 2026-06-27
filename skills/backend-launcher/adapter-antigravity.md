# Adapter: Antigravity (headless `agy --print` worker)

> Read the contract in [`SKILL.md`](SKILL.md) first — this adapter implements that `job_spec → job_result` interface. This file is the backend-specific runbook; the wiring lives in [`scripts/compound-v-run-antigravity-worker.sh`](../../scripts/compound-v-run-antigravity-worker.sh).

The Antigravity backend is a **Bash-spawned `agy --print` worker** — its own process, its own git worktree. It mirrors the Codex adapter step-for-step ([`adapter-codex.md`](adapter-codex.md)): worktree isolation, a git-derived scope gate, normalize → `job_result`, caller merges. The orchestrator hands this adapter a `job_spec` and gets back the canonical `job_result`; enforcement is git-derived by the caller, identical to every other backend.

Verified live against **agy 1.0.13** on stock macOS (bash 3.2.57). The verified facts below are pinned — do not re-derive them per run; re-probe only in `/v:init`.

---

## ⚠️ SAFETY — lower-trust, opt-in backend (read first)

**Antigravity has NO kernel write-confinement.** Codex runs under `--sandbox workspace-write`, an OS-level boundary that *prevents* writes outside its root. `agy` has no equivalent — and headless file writes **require** `--dangerously-skip-permissions`, which also lets the agent run **arbitrary shell** and write **anywhere on disk**.

What this means for scope enforcement:

- The worktree + post-hoc `git diff` gate enforces file-scope **inside the worktree** — any changed path outside `write_allowed` is a `violation` ⇒ `blocked`, exactly as for Codex.
- But the gate is **detection, not prevention**. It cannot *stop* an out-of-worktree write or a shell side-effect; it only catches in-worktree writes after the fact. A determined or misbehaving agent can touch files the gate never sees.

Therefore Antigravity is an **opt-in, lower-trust backend.** **Prefer Codex (kernel-sandboxed) for untrusted or high-stakes work.** Route to Antigravity only when you trust the prompt and the surface, or as an alternative for `large_isolated` build work where the blast radius is already narrow. It is available only when `agy` is installed (env-aware routing — see [`routing-policy.md`](../compound-v/routing-policy.md)).

---

## The 6 load-bearing steps

The worker script performs steps 1–5; the **caller** (dispatcher) performs step 6.

```
1. ISOLATE   git -C <repo> worktree add <WT> HEAD          # clean diff baseline (NO kernel sandbox — see Safety)
2. RUN       cd <WT> && agy --dangerously-skip-permissions --add-dir <WT> \
                        --print-timeout <sec>s [--model <M>] --print <prompt>
3. OBSERVE   compound-v-scope-check.py --worktree <WT> --baseline <sha>   # git-derived ∪ untracked ∪ ignored
4. ENFORCE   every changed path ∉ write_allowed ⇒ violation ⇒ blocked  (do NOT merge)
5. NORMALIZE → job_result  (summary ← agy's printed stdout; session_id ← "" — no resumable UUID)
6. MERGE     caller, on PASS only:  git -C <WT> add -A
             git -C <WT> diff --cached --binary HEAD | (cd <repo> && git apply --index)  →  git worktree remove -f <WT>
```

Step 4 is the keystone — and because agy has no kernel sandbox, it is the **only** file-scope enforcement this backend has (Codex at least has a directory-level kernel boundary underneath the same gate). Steps 3–4 are computed in git, never read from anything the model says it did, and are delegated to the deterministic authority [`scripts/compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py) — the same gate the dispatcher runs after every job. The worker does **not** re-implement glob matching in bash.

**Only `write_allowed` is enforced; `read_allowed` is advisory.** Steps 3–4 are a git diff, and git tracks writes, not reads — so `write_allowed` is the hard, enforced boundary (anything outside it BLOCKS), while `read_allowed` only scopes the worker prompt and documents intent. agy has no read-confinement sandbox either, so an out-of-scope read is never gated. Never treat `read_allowed` as enforced.

---

## Worker-prompt planner/executor lock

Every dispatched `prompt` MUST open with this lock (verbatim-in-spirit), exactly as the contract in `SKILL.md` requires:

> You are an implementation worker, NOT the planner. Do not change architecture. Do not write outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report BLOCKED.

This is the *instructed* half of planner/executor separation. The git-diff scope gate (steps 3–4) is the *enforced* half. Because agy has no kernel sandbox, the lock carries **more** weight here than for Codex — but it is still only instruction; the git-derived gate is what actually catches an in-worktree scope leak regardless of whether the prompt held.

The worker prompt is passed via `--prompt-file <abs-path>` (a file, not an inline arg) so multi-paragraph prompts and the lock survive shell quoting intact. The script reads it and passes it as the value of `--print`.

---

## Pinned `agy` invocation (agy 1.0.13)

The script uses **exactly** this shape — verified to write files into the worktree, print the agent's response to stdout, and exit 0:

```bash
cd "$WT" && timeout "$timeout_sec" agy \
  --dangerously-skip-permissions \
  --add-dir "$WT" \
  --print-timeout "${timeout_sec}s" \
  ${model:+--model "$model"} \
  --print "$(cat "$prompt_file")" </dev/null
```

**Flag order + verified facts — all load-bearing (do not re-derive):**

- **`--print` MUST be LAST, and its value is the prompt.** A flag placed right after `--print` gets eaten *as* the prompt. So `--print` and the prompt string are always the final two argv tokens; `--model` (when present) goes **before** them.
- **`--dangerously-skip-permissions` is REQUIRED for headless file writes.** Without it agy prompts / auto-denies and writes nothing (exit 0, empty worktree). This is the flag that removes the safety rail — see the Safety section.
- **agy has NO `--cd`.** The script `cd "$WT"` first and passes `--add-dir "$WT"` so the worktree is the working + allowed root.
- **Summary ← stdout.** agy prints the agent's response to *stdout*; the script captures it into the human `summary`. (Unlike Codex, there is no `--output-last-message` file.)
- **No resumable session UUID** is exposed, so `session_id` is always `""` (the schema permits it). A re-dispatched Antigravity job runs **fresh**, consistent with the git-wins resume tie-break.
- **`agy models` HANGS** — never call it. The model map is curated upstream (see Model resolution below).
- **`--model` is OPTIONAL.** The worker omits `--model` entirely when the resolved value is empty, letting agy use its configured default.

| Flag | Role |
|---|---|
| `cd "$WT"` (not a flag) | working root = the worktree (agy has no `--cd`) |
| `--dangerously-skip-permissions` | **required** for headless writes — also removes the write/shell rail (Safety) |
| `--add-dir "$WT"` | adds the worktree as an allowed directory |
| `--print-timeout "${sec}s"` | agy's own wall-clock cap on the print run (belt-and-braces with the optional outer `timeout`) |
| `--model "$model"` | optional execution-layer model — resolved from `(backend=antigravity, tier, effort)`; omitted when empty |
| `--print "$prompt"` | **LAST**; its value is the worker prompt (lock first) |

### `--read-only` / `--network` are advisory for Antigravity

agy exposes no kernel sandbox toggle for read-only or network access here, so the worker accepts `--read-only` / `--network` for **CLI parity** with the Codex worker but does **not** change the invocation from them. A read-only / review job is still enforced post-hoc: pass an **empty** `--write-allowed`, and the git-diff gate treats any changed path as a violation ⇒ BLOCKED.

### `--output-schema` is accepted but ignored

agy has no output-schema flag. The worker accepts `--output-schema` for CLI parity (validating the path shape if given) but never uses it.

### Model + effort: resolved before dispatch, not hardcoded

The dispatcher hands a routing **intent** — `tier` (`deep` \| `standard` \| `light`) — and resolves the concrete model **before** dispatch via [`scripts/compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) with `--backend antigravity --tier <tier> [--config .claude/compound-v.json]`. The built-in curated map is `deep → Gemini 3.1 Pro (High)`, `standard → Gemini 3.1 Pro`, `light → Gemini 3.1 Flash` (illustrative — verify against `agy models` when that command is usable; refresh via `/v:models`). An explicit manifest `model` override skips resolution and wins. agy has **no effort flag**, so `effort` is advisory for this backend (like Claude).

### Timeout

`timeout` may be absent on stock macOS; the script uses `timeout` if present, else `gtimeout` (coreutils), else relies on agy's own `--print-timeout` (always passed). The outer-`timeout` exit code `124` maps to `status: "timeout"`. `--timeout-sec` must be a **positive integer** — it is word-split into the `timeout` argv and interpolated into `--print-timeout`, so the script `die`s on anything else.

---

## Worktree lifecycle

```bash
# create — fresh checkout at HEAD = a clean diff baseline so the scope gate sees exactly the job's edits
git -C "$REPO" worktree add "$WT" HEAD

# … agy --print runs with cwd = "$WT" and --add-dir "$WT" …

# remove — on PASS, AFTER the caller merges (step 6); on BLOCKED, leave it for inspection
git -C "$REPO" worktree remove -f "$WT"
```

Worktrees live **outside the repo**, under `"${TMPDIR:-/tmp}"/compound-v/<run-id>/<job-id>` — so no `.gitignore` change is needed. Scratch (`$WT.art`: the captured stdout/stderr logs and the expanded allow-globs file) lives **outside** the worktree, so the worktree stays pristine and the generic scope-gate agrees with this worker's own enforcement. The script is **idempotent on resume**: a stale worktree at that path is `worktree remove -f`'d (falling back to `rm -rf`, only after asserting the path sits under `$TMPDIR/compound-v/`) before a fresh `add HEAD`. The script never removes the worktree on success — removal is the caller's job after a successful `git apply`.

The baseline SHA is captured with `git rev-parse HEAD` **before** `worktree add` and passed as `--baseline <sha>` (not `HEAD`) to the scope gate, so a worker that COMMITS inside its worktree to make the tree look clean is still caught by `git diff <baseline-sha>`.

---

## Merge-back (caller, step 6)

The script **observes and reports only — it never merges.** The dispatcher decides, based on `job_result.status`:

- **PASS** (`status: success`): apply the worktree's changes — including new (untracked) files — into the main tree, then drop the worktree.
  ```bash
  git -C "$WT" add -A
  git -C "$WT" diff --cached --binary HEAD | (cd "$REPO" && git apply --index)
  git -C "$REPO" worktree remove -f "$WT"
  ```
  The index-based patch covers both tracked edits and brand-new untracked files in one step (a plain `git diff HEAD | git apply` would DROP added files).
- **BLOCKED** (`status: blocked`): **do not merge.** Leave the worktree on disk for inspection and surface the `violations`. The run halts.
- **timeout / error**: do not merge; the partial worktree is left for inspection and the job is eligible for re-dispatch on `/v:resume` (fresh — no session resume).

---

## Resume

Antigravity has **no resumable session** — `session_id` is always `""`. A re-dispatched job runs fresh from a new worktree at HEAD, consistent with the git-wins resume tie-break (if `state.json` says done but the files aren't in git, re-dispatch).

---

## Backend-failure classification

On any non-zero `agy` exit the worker classifies the failure via [`scripts/compound-v-classify-failure.py`](../../scripts/compound-v-classify-failure.py) `--backend antigravity --exit-code <n> --stderr-file <log>`, which matches Gemini/agy error text into `{out_of_credits, rate_limited, overloaded, auth, context_length, timeout, network, other}`. Gemini reuses `RESOURCE_EXHAUSTED` for **both** quota exhaustion and throttling, so the quota/billing needles are checked **first** (out_of_credits wins when the text mentions quota). The worker **fails closed** — an error/timeout status never carries `failure_class: none`. The class drives the dispatcher's deterministic retry/reroute/halt policy ([`failure-policy.md`](../compound-v/failure-policy.md)).

---

## Invoking the script

```bash
scripts/compound-v-run-antigravity-worker.sh \
  --run-id   2026-06-27-some-feature \
  --job-id   task-1-build \
  --repo     /abs/path/to/repo \
  --prompt-file /abs/path/to/jobs/task-1-build.prompt.md \
  --model    "Gemini 3.1 Pro" \
  --write-allowed "src/features/build/**" \
  --timeout-sec 900 \
  --network  false
# optional: --read-only true     (advisory — enforced post-hoc via empty --write-allowed)
# --model is OPTIONAL: omit it (or pass "") to let agy use its configured default.
```

- All file paths MUST be **absolute** (the script rejects relative `--repo` / `--prompt-file` / `--output-schema`).
- `--write-allowed` is a **colon-separated** glob list (`a/**:b/c.ts`), matched repo-relative against changed paths. An **empty** `--write-allowed` is valid and means a **read-only / review job**: any changed path becomes a violation ⇒ BLOCKED.
- `--timeout-sec` must be a **positive integer**; the script `die`s on anything else.
- **stdout** is the canonical `job_result` JSON and nothing else — the dispatcher pipes it straight to the collector and the scope-check authority.
- **Exit 0** means a `job_result` was produced (even for BLOCKED / timeout / error — those live in `status`). A non-zero exit means a usage/environment fault prevented producing a result at all.

The script targets stock-macOS **bash 3.2** (no associative arrays / `mapfile` / `${var,,}`) and uses only `git` + `jq` + `python3`. It is shellcheck-clean and `chmod +x`.
