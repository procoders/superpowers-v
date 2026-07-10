# Adapter: Cursor (headless `cursor-agent -p` worker)

> Read the contract in [`SKILL.md`](SKILL.md) first — this adapter implements that `job_spec → job_result` interface. This file is the backend-specific runbook; the wiring lives in [`scripts/compound-v-run-cursor-worker.sh`](../../scripts/compound-v-run-cursor-worker.sh).

The Cursor backend is a **Bash-spawned `cursor-agent -p` worker** — its own process, its own git worktree. It mirrors the Codex / Antigravity adapters step-for-step ([`adapter-antigravity.md`](adapter-antigravity.md)): worktree isolation, a git-derived scope gate, normalize → `job_result`, caller merges. The orchestrator hands this adapter a `job_spec` and gets back the canonical `job_result`; enforcement is git-derived by the caller, identical to every other backend.

Verified live against **cursor-agent 2026.06.26** on stock macOS (bash 3.2.57) — refreshed 2026-07-10 (was 2025.09.12): the headless invocation writes files into the worktree and the scope gate enforces `write_allowed` on both the success and BLOCKED paths (see *Verified facts*). The pinned facts below are load-bearing — do not re-derive them per run; re-probe only in `/v:init`.

---

## ⚠️ SAFETY — lower-trust, opt-in backend (read first)

**Cursor has NO kernel write-confinement.** Codex runs under `--sandbox workspace-write`, an OS-level boundary that *prevents* writes outside its root. `cursor-agent` has no equivalent — and a headless run **requires** `-f` (force/trust): in a fresh/untrusted directory `cursor-agent -p` **refuses to proceed** without it (*"Pass --trust, --yolo, or -f if you trust this directory"*, verified), and `-f` both trusts the directory and lets the agent **apply file changes and run shell** anywhere on disk.

What this means for scope enforcement — identical to Antigravity:

- The worktree + post-hoc `git diff` gate enforces file-scope **inside the worktree** — any changed path outside `write_allowed` is a `violation` ⇒ `blocked`. **Verified live**: a job told to write `SECRET.txt` under `--write-allowed "docs/**"` came back `status: blocked`, `violations: ["SECRET.txt"]`.
- But the gate is **detection, not prevention**. It cannot *stop* an out-of-worktree write or a shell side-effect; it only catches in-worktree writes after the fact.

Therefore Cursor is an **opt-in, lower-trust backend** — the **same trust tier as Antigravity**, below kernel-sandboxed Codex. **Prefer Codex for untrusted or high-stakes work.** Route to Cursor only when you trust the prompt and surface, or for isolated build/UI work where the blast radius is already narrow (Cursor's editing models are a genuine strength there). Available only when `cursor-agent` is installed AND authenticated (env-aware routing — see [`routing-policy.md`](../compound-v/routing-policy.md)).

---

## The 6 load-bearing steps

The worker script performs steps 1–5; the **caller** (dispatcher) performs step 6.

```
1. ISOLATE   git -C <repo> worktree add <WT> HEAD          # clean diff baseline (NO kernel sandbox — see Safety)
2. RUN       cd <WT> && cursor-agent -p -f --output-format json [--model <M>] <prompt> </dev/null
3. OBSERVE   compound-v-scope-check.py --worktree <WT> --baseline <sha>   # git-derived ∪ untracked ∪ ignored
4. ENFORCE   every changed path ∉ write_allowed ⇒ violation ⇒ blocked  (do NOT merge)
5. NORMALIZE → job_result  (summary ← JSON .result; session_id ← JSON .session_id, a real UUID)
6. MERGE     caller, on PASS only:  git -C <WT> add -A
             git -C <WT> diff --cached --binary HEAD | (cd <repo> && git apply --index)  →  git worktree remove -f <WT>
```

Step 4 is the keystone — and because cursor has no kernel sandbox, it is the **only** file-scope enforcement this backend has. Steps 3–4 are computed in git, never read from anything the model says it did, and are delegated to the deterministic authority [`scripts/compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py) — the same gate the dispatcher runs after every job. The worker does **not** re-implement glob matching in bash.

**Only `write_allowed` is enforced; `read_allowed` is advisory** (the gate is a git diff; git tracks writes, not reads). cursor has no read-confinement sandbox, so an out-of-scope read is never gated. Never treat `read_allowed` as enforced.

---

## Worker-prompt planner/executor lock

Every dispatched `prompt` MUST open with this lock (verbatim-in-spirit), exactly as the contract in `SKILL.md` requires:

> You are an implementation worker, NOT the planner. Do not change architecture. Do not write outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report BLOCKED.

This is the *instructed* half of planner/executor separation; the git-diff scope gate (steps 3–4) is the *enforced* half. Because cursor has no kernel sandbox, the lock carries more weight here than for Codex — but it is still only instruction; the git-derived gate is what actually catches an in-worktree scope leak. The prompt is passed via `--prompt-file <abs-path>` and becomes the LAST positional argument of `cursor-agent`.

---

## Pinned `cursor-agent` invocation (cursor-agent 2026.06.26)

The script uses **exactly** this shape — verified to write files into the worktree, print one JSON object to stdout, and exit 0:

```bash
cd "$WT" && timeout "$timeout_sec" cursor-agent -p -f --output-format json \
  ${model:+--model "$model"} \
  "$(cat "$prompt_file")" </dev/null
```

**Verified facts — all load-bearing (do not re-derive):**

- **`-f` (force/trust) is REQUIRED for ANY headless run.** Without a trust flag, `cursor-agent -p` refuses an untrusted directory and exits non-zero — *even for a no-write task*. `-f` trusts the worktree AND auto-applies writes. This is the flag that removes the safety rail — see Safety. (`--trust` alone *may* give a propose-only mode, but that is not yet verified, so the worker does not rely on it.)
- **`-p --output-format json` ⇒ ONE JSON object on stdout** (not stream-json). Verified shape: `{"type":"result","subtype":"success","is_error":false,"result": <final message>, "session_id": <uuid>, "request_id": …, "usage": {…}}`.
- **Summary ← `.result`**; **`session_id` ← `.session_id`** (a real UUID). The `.usage` token counts are deliberately **IGNORED** — anti-ruflo: the worker never emits token/cost metrics.
- **cursor-agent has NO `--cd` and NO `--add-dir`.** The script `cd "$WT"` first; cursor operates on the current directory.
- **stdin redirected `</dev/null`** — the same hard-won lesson as codex/agy (the bare command otherwise waits on a TTY).
- **No built-in timeout flag.** Unlike agy's `--print-timeout`, cursor has none — the optional outer `timeout`/`gtimeout` prefix is the ONLY wall-clock cap. On a host without either binary there is **no cap** (install coreutils `gtimeout` for one). The `timeout` exit code `124` maps to `status: "timeout"`.
- **`--model` is OPTIONAL.** The worker omits it when the resolved value is empty, letting cursor use its configured default.

| Flag | Role |
|---|---|
| `cd "$WT"` (not a flag) | working root = the worktree (cursor has no `--cd`/`--add-dir`) |
| `-p` / `--print` | non-interactive print mode |
| `-f` / `--force` | **required** to trust an untrusted worktree + apply writes — also removes the write/shell rail (Safety) |
| `--output-format json` | one JSON object on stdout (`.result` + `.session_id`) |
| `--model "$model"` | optional execution-layer model — resolved from `(backend=cursor, tier, effort)`; omitted when empty |
| `"$prompt"` | **LAST** positional arg; the worker prompt (lock first) |

### `--read-only` / `--network` are advisory for Cursor

cursor exposes no kernel sandbox toggle, and `-f` is required to run at all, so the worker accepts `--read-only` / `--network` for **CLI parity** but does not change the invocation from them. A read-only / review job is still enforced post-hoc: pass an **empty** `--write-allowed`, and the git-diff gate treats any changed path as a violation ⇒ BLOCKED.

### `--output-schema` is accepted but ignored

cursor-agent has no output-schema flag. The worker accepts `--output-schema` for CLI parity (validating the path shape if given) but never uses it.

### Model + effort: resolved before dispatch, not hardcoded

The dispatcher resolves the concrete model **before** dispatch via [`scripts/compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) with `--backend cursor --tier <tier> [--config .claude/compound-v.json]`. The built-in map is **`auto` for every tier** — VERIFIED LIVE that a Cursor **Free** plan can *only* use Auto: passing a named model (`sonnet-4` / `gpt-5` / …) fails with *"Named models unavailable. Free plans can only use Auto."* Both `--model auto` and omitting `--model` work on free and paid plans. On a **paid** plan, run `cursor-agent models` to see the live catalog, then override with named per-tier ids in `.claude/compound-v.json` via `/v:models` (manual, not auto-discovered — cursor's catalog spans many unrelated vendor families with no shared naming convention, unlike antigravity's single-family Gemini catalog that `/v:models` ranks automatically). An explicit manifest `model` override wins. Because the default is Auto, **tier-based routing is a no-op for Cursor on a free plan** (Auto picks the model) — by design. cursor takes no separate effort flag, so `effort` is advisory (like Claude / Antigravity).

### Timeout — portable bash watchdog (no `timeout` binary required)

cursor-agent has **no built-in `--print-timeout`** (unlike agy), and a host may lack
`timeout`/`gtimeout`. So the worker runs cursor-agent under the shared **process-tree timeout
supervisor** [`scripts/compound-v-run-with-timeout.py`](../../scripts/compound-v-run-with-timeout.py):
it starts the agent in a **new session** (`start_new_session=True` → `setsid`) and, on expiry,
`os.killpg`s the **whole tree** (SIGTERM → grace → SIGKILL) and returns 124 → `status: timeout`.
This closes the orphan-children scope-leak: a tool/shell **child** the agent spawned cannot
outlive the cap and write after the gate. **Proven** by the supervisor's own `--selftest` (a
backgrounded descendant that tries to write a file *after* the cap is reaped first — the write
never lands) and live (`--timeout-sec 1` on a long job ⇒ `status: timeout`). The supervisor holds
no copy of the agent's output fds, so a hung agent can't hang the dispatcher's `$(…)` capture.
`--timeout-sec` must be a **positive integer > 0**. No external `timeout` binary needed.

> The Codex and Antigravity workers run under this **same supervisor** (verified live: success +
> timeout for both), so the process-tree cap is uniform across all three external backends.

---

## Worktree lifecycle

Identical to the Antigravity adapter: a fresh `git worktree add "$WT" HEAD` gives a clean diff baseline; worktrees live **outside the repo** under `"${TMPDIR:-/tmp}"/compound-v/<run-id>/<job-id>` (no `.gitignore` change); scratch (`$WT.art`: captured stdout/stderr + the expanded allow-globs file) lives outside the worktree so it stays pristine; the script is idempotent on resume (a stale worktree is `worktree remove -f`'d — falling back to `rm -rf` only after asserting the path sits under `$TMPDIR/compound-v/`) and never removes the worktree on success (the caller's job after a successful `git apply`). The baseline SHA is captured **before** `worktree add` and passed as `--baseline <sha>` so an in-worktree commit-to-hide-changes is still diffed.

---

## Merge-back (caller, step 6)

The script **observes and reports only — it never merges.** The dispatcher decides on `job_result.status`:

- **PASS** (`status: success`): apply the worktree's changes — including new untracked files — then drop the worktree.
  ```bash
  git -C "$WT" add -A
  git -C "$WT" diff --cached --binary HEAD | (cd "$REPO" && git apply --index)
  git -C "$REPO" worktree remove -f "$WT"
  ```
- **BLOCKED** (`status: blocked`): **do not merge.** Leave the worktree for inspection, surface the `violations`. The run halts.
- **timeout / error**: do not merge; leave the partial worktree; the job is eligible for re-dispatch on `/v:resume`.

---

## Resume

Unlike Antigravity, **Cursor exposes a resumable session** — `session_id` is a real UUID (verified). A re-dispatched job MAY resume that chat via `cursor-agent --resume <session_id>`; the Compound V default is still **git-wins / fresh re-dispatch** (if `state.json` says done but the files aren't in git, re-run from a new worktree at HEAD), with resume available as an optimization when the run dir records the `session_id`.

---

## Backend-failure classification

On any non-zero `cursor-agent` exit the worker classifies via [`scripts/compound-v-classify-failure.py`](../../scripts/compound-v-classify-failure.py) `--backend cursor --exit-code <n> --stderr-file <log>` into `{out_of_credits, rate_limited, overloaded, auth, context_length, timeout, network, other}`. Cursor proxies OpenAI / Anthropic / Composer models, so the provider-error needles reuse the verified OpenAI-style patterns; the cursor-account auth/plan needles (`cursor-agent login`, plan/usage-limit wording) are **provisional** — refine them against a real cursor failure sample. The worker **fails closed** — an error/timeout status never carries `failure_class: none`. The class drives the dispatcher's deterministic retry/reroute/halt policy ([`failure-policy.md`](../compound-v/failure-policy.md)).

---

## Invoking the script

```bash
scripts/compound-v-run-cursor-worker.sh \
  --run-id   2026-06-27-some-feature \
  --job-id   task-1-build \
  --repo     /abs/path/to/repo \
  --prompt-file /abs/path/to/jobs/task-1-build.prompt.md \
  --model    "sonnet-4" \
  --write-allowed "src/features/build/**" \
  --timeout-sec 900 \
  --network  false
# optional: --read-only true     (advisory — enforced post-hoc via empty --write-allowed)
# --model is OPTIONAL: omit it (or pass "") to let cursor use its configured default.
```

- All file paths MUST be **absolute**. `--write-allowed` is a **colon-separated** glob list, matched repo-relative; an **empty** `--write-allowed` is a read-only/review job (any change ⇒ BLOCKED). `--timeout-sec` must be a **positive integer**.
- **stdout** is the canonical `job_result` JSON and nothing else. **Exit 0** means a `job_result` was produced (even for BLOCKED / timeout / error — those live in `status`); a non-zero exit means a usage/environment fault.

The script targets stock-macOS **bash 3.2** (no associative arrays / `mapfile` / `${var,,}`), uses only `git` + `jq` + `python3` + `cursor-agent`, is shellcheck-clean and `chmod +x`. It requires an **authenticated** cursor-agent (`cursor-agent login` / `CURSOR_API_KEY`) — `/v:init` records availability + auth.
