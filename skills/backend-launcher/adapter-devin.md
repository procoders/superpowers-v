# Adapter: Devin (headless `devin -p` worker)

> Read the contract in [`SKILL.md`](SKILL.md) first — this adapter implements that `job_spec → job_result` interface. This file is the backend-specific runbook; the wiring would live in `scripts/compound-v-run-devin-worker.sh` (**not yet built** — see "Worker script" below).

The Devin backend is a **Bash-spawned `devin -p` worker** — its own process, its own git worktree. It mirrors the Antigravity / Cursor adapters step-for-step ([`adapter-antigravity.md`](adapter-antigravity.md), [`adapter-cursor.md`](adapter-cursor.md)): worktree isolation, a git-derived scope gate, normalize → `job_result`, caller merges. It does **not** mirror the Codex adapter, because Devin's `--sandbox` is Research-Preview and its coverage/network-confinement claims are unverified for this plugin's purposes (see SAFETY).

Verified live against **devin-cli 3000.1.27 (0d4bf12e)** on stock macOS. The auth-free surface (`--help`, `sandbox setup`, `auth status`, `list --format json`) plus — **as of 2026-07-13, with an AUTHENTICATED account** — a real headless `-p` run: `devin -p "…" --permission-mode dangerous </dev/null` returned **exit 0 with the bare final text on stdout** (`PROBE_OK`, no JSON envelope — confirms the Antigravity `summary ← stdout` pattern). **Two live findings pinned:** (1) Devin's backend can return a **transient capacity error** — observed verbatim `Error: Agent error: Permission denied: We're currently facing high demand for this model. Please try again later.` on a non-zero exit, which SUCCEEDED on a plain retry → this class is **retryable/transient**, exactly the "часто падает" case marathon retry + v2.11 resurrection handle. (2) Devin **resets the shell cwd** after a run (stderr: `Shell cwd was reset to <repo>`) — the worker's git-diff scope gate is unaffected because it checks the worktree by explicit path, but a worker must not rely on `$PWD` after the call. **Still DOC-CLAIMED / UNVERIFIED** (not needed for a working worker, upgrade when convenient): `--export` ATIF field names, `--model` alias *resolution* (flag accepted; alias→model mapping unconfirmed), `-r <SESSION_ID>` resume, and a rich failure-classifier table (the worker defaults unknown non-zero exits to `other`).

---

## ⚠️ SAFETY — lower-trust, opt-in, WORKER-ONLY backend for v1 (read first)

**Devin HAS a real kernel-sandbox flag** (`--sandbox`, VERIFIED live: *"[Research Preview] Sandbox exec-tool processes (macOS seatbelt / Linux bwrap+seccomp)"*) — unlike Antigravity/Cursor, which have none. But:

1. It is Cognition's own **"[Research Preview]"** label — immature/changeable by their own admission.
2. Its documented scope is **"exec-tool processes"** — whether Devin's own (non-shell) file-edit tool calls are equally kernel-confined, or only the shelled-out subprocess surface is, is **unverified**.
3. **Network filtering inside `--sandbox` is explicitly called "currently unstable"** by Cognition's own docs — there is no simple boolean like Codex's `-c sandbox_workspace_write.network_access=false`.
4. Read/Write scopes come from Devin's own **granted permission scopes** (`Write(...)`/`Read(...)`), coupled to `--agent-config`, not a single `--cd $WT` directory root — the exact mechanics of "scope the sandbox to exactly `$WT`" are unverified without a live account.

**Therefore: Devin ships in the same opt-in / lower-trust tier as Antigravity/Cursor for v1** — the worktree + post-hoc `git diff` gate is the **real** enforcement (detection, not confirmed prevention), exactly as for Antigravity/Cursor. **Prefer Codex for untrusted / high-stakes work.** Route to Devin only when you trust the prompt/surface, or specifically want its model-agnostic routing. A future v1.1 could pass `--sandbox` + a scoped `--agent-config` and re-classify Devin's trust tier upward — but that needs a live account to verify scope actually holds, so it is explicitly **out of scope** for this v1 adapter.

**WORKER-ONLY — never an arbiter/review-panel seat (this is separate from the trust-tier question above).** Devin is a **multi-vendor model broker**: `--model` accepts a free string spanning Claude, GPT, Gemini, and Devin's own SWE family, with **no `devin models` / `--list-models` command** to enumerate it. Because of this, Devin's *resolved model family* is not fixed at the backend level — `model_family(resolved_model)` (the same substring heuristic `compound-v-epic-arbiter.py` already applies to every backend) is the only correct way to classify a Devin ballot's family, and no v2.10 arbiter-panel plumbing currently reads a per-ballot resolved-model family for a non-Codex/non-Claude backend. Wiring Devin into the arbiter panel is a **separate, later change** (family-dedup fix) — this adapter is **worker dispatch only**.

---

## The 6 load-bearing steps (draft — worker script not yet built)

The worker script would perform steps 1–5; the **caller** (dispatcher) performs step 6 — identical division of labor to every other adapter.

```
1. ISOLATE   git -C <repo> worktree add <WT> HEAD          # clean diff baseline (NO kernel sandbox relied on — see Safety)
2. RUN       cd <WT> && devin -p "$(cat "$prompt_file")" \
                        --permission-mode dangerous \
                        ${model:+--model "$model"} \
                        --export "$ART/devin_export.json" </dev/null
3. OBSERVE   compound-v-scope-check.py --worktree <WT> --baseline <sha>   # git-derived ∪ untracked ∪ ignored
4. ENFORCE   every changed path ∉ write_allowed ⇒ violation ⇒ blocked  (do NOT merge)
5. NORMALIZE → job_result  (summary ← devin's printed stdout;
                            session_id ← best-effort from `devin list --format json` in <WT> — UNVERIFIED shape)
6. MERGE     caller, on PASS only:  git -C <WT> add -A
             git -C <WT> diff --cached --binary HEAD | (cd <repo> && git apply --index)  →  git worktree remove -f <WT>
```

Step 4 is the keystone — and because Devin's sandbox coverage/confinement is unverified for this plugin's purposes, worktree + `git diff` is the **only enforcement this adapter relies on**, exactly like Antigravity/Cursor. Steps 3–4 must be computed in git, never read from anything the model says it did, and would delegate to the deterministic authority [`scripts/compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py) — the same gate the dispatcher runs after every job. A worker script for this backend must **not** re-implement glob matching in bash.

**Only `write_allowed` would be enforced; `read_allowed` stays advisory** — same rule as every lower-trust adapter (the gate is a git diff; git tracks writes, not reads).

---

## Worker-prompt planner/executor lock

Every dispatched `prompt` MUST open with this lock (verbatim-in-spirit), exactly as the contract in `SKILL.md` requires:

> You are an implementation worker, NOT the planner. Do not change architecture. Do not write outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report BLOCKED.

This is the *instructed* half of planner/executor separation; the git-diff scope gate (steps 3–4) is the *enforced* half. Because Devin's sandbox coverage is unverified here, the lock carries the same weight it does for Antigravity/Cursor — instruction only; the git-derived gate is what actually catches an in-worktree scope leak. The prompt would be passed via `--prompt-file <abs-path>` (VERIFIED live flag exists) so multi-paragraph prompts and the lock survive shell quoting.

---

## Pinned `devin -p` invocation (devin-cli 3000.1.27 — auth-free flags VERIFIED, task-execution behavior DOC-CLAIMED)

```bash
cd "$WT" && python3 "$SUPERVISOR" --timeout "$timeout_sec" --grace 3 --cwd "$WT" -- \
  devin -p "$(cat "$prompt_file")" \
  --permission-mode dangerous \
  ${model:+--model "$model"} \
  --export "$ART/devin_export.json" </dev/null
```

**Verified facts — load-bearing:**

- **`-p, --print [<PROMPT>]`** — VERIFIED live: *"Print response and exit. Runs in non-interactive mode."* This is the `codex exec …` / `cursor-agent -p` equivalent.
- **`--permission-mode dangerous` is REQUIRED for unattended writes.** The default is `auto` (VERIFIED live help text: *"'auto' auto-approves read-only tools"* only) — a non-interactive run with the default would stall on the first write/shell approval with no one to answer. This is the flag that removes Devin's own safety rail — the git-diff gate is what actually enforces scope (see SAFETY).
- **`</dev/null` is REQUIRED** — VERIFIED live: an unauthenticated `devin -p "..." --permission-mode dangerous </dev/null` attempted an interactive login prompt and only failed cleanly (`Error: Login canceled`) because stdin was closed. Same hard-won lesson as codex/cursor/agy — omitting the redirect risks a hang.
- **No `--cd` / `--cwd` flag exists** (VERIFIED live absence from the full `--help` listing) — `cd "$WT"` first, matching Cursor/Antigravity.
- **No `--output-format json` / `--json` flag exists** (VERIFIED live absence) — `-p` prints the final response to stdout and exits; there is no structured envelope like Cursor's `.result`/`.session_id` JSON object. This is the **Antigravity pattern**: `summary ← stdout`.
- **`--export [<PATH>]`** — VERIFIED live flag exists: *"Export conversation to a file. Exports after each turn."* Format is ATIF (Agent Trajectory Interchange Format) — DOC-CLAIMED, unconfirmed field names for a "final message" or "session id" without an authenticated run.
- **`--model`** — VERIFIED live flag exists (`--help` text uses `claude-sonnet-4` / `claude-opus-4.6` / `opus` / `codex` as its own examples), optional; the worker would omit it when the resolved value is empty, letting Devin use its configured default.
- **No `--timeout` flag** (VERIFIED live absence) — run under the shared process-group supervisor exactly like every other backend (see Timeout, below).
- **`--prompt-file <FILE>`** — VERIFIED live top-level flag exists, mirroring this plugin's `--prompt-file` convention.

| Flag | Role |
|---|---|
| `cd "$WT"` (not a flag) | working root = the worktree (devin has no `--cd`) |
| `-p "$prompt"` | non-interactive print mode; value is the worker prompt (lock first) |
| `--permission-mode dangerous` | **required** for unattended writes — also removes the write/shell rail (Safety) |
| `--model "$model"` | optional execution-layer model — resolved from `(backend=devin, tier, effort)`; omitted when empty |
| `--export "$ART/devin_export.json"` | ATIF trace file (outside the worktree — scratch, never in the diff) |

### `--read-only` / `--network` are advisory for Devin

Devin's `--sandbox` (Research Preview) is not relied on for enforcement in v1 (see SAFETY), so the worker would accept `--read-only` / `--network` for **CLI parity** only, exactly like Antigravity/Cursor. A read-only / review job is enforced post-hoc: pass an **empty** `--write-allowed`, and the git-diff gate treats any changed path as a violation ⇒ BLOCKED.

### `--output-schema` is accepted but ignored

Devin has no output-schema flag (VERIFIED live absence). Accept-and-ignore for CLI parity, like Antigravity/Cursor.

### Model + effort: resolved before dispatch, not hardcoded

The dispatcher resolves the concrete model **before** dispatch via [`scripts/compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) with `--backend devin --tier <tier> [--config .claude/compound-v.json]`. The built-in curated map (DOC-CLAIMED aliases — Devin's own `--help` text uses these exact strings as its examples, but no authenticated run has confirmed they resolve): `deep → claude-opus-4.6`, `standard → claude-sonnet-4`, `light → gpt-5.5`. Devin has **no list command**, so — like Codex — its map is curated + user-overridable (refresh via `/v:models`). An explicit manifest `model` override skips resolution and wins.

**`xhigh` is codex-only.** Devin takes no separate reasoning-effort flag, so `effort` is advisory for this backend (like Claude/Antigravity/Cursor). `effort: xhigh` paired with `backend: devin` is rejected by both [`compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) (`ValueError` naming the rule) and [`compound-v-validate-manifest.py`](../../scripts/compound-v-validate-manifest.py) — the same backend-agnostic guard every non-codex backend gets.

### Timeout — the shared process-group supervisor

No built-in `--timeout` flag exists (VERIFIED live absence). A worker script would run Devin under [`scripts/compound-v-run-with-timeout.py`](../../scripts/compound-v-run-with-timeout.py) exactly like Codex/Antigravity/Cursor — `killpg`s the whole `devin` process tree on expiry and returns 124 → `status: "timeout"`. No external `timeout`/`gtimeout` binary needed.

---

## Worktree lifecycle / Merge-back (draft, mirrors Antigravity/Cursor exactly)

Identical in shape to [`adapter-antigravity.md`](adapter-antigravity.md) / [`adapter-cursor.md`](adapter-cursor.md): a fresh `git worktree add "$WT" HEAD` gives a clean diff baseline; worktrees would live **outside the repo** under `"${TMPDIR:-/tmp}"/compound-v/<run-id>/<job-id>`; scratch (`$WT.art`: captured stdout/stderr, the `--export` ATIF file, the expanded allow-globs file) lives **outside** the worktree so it stays pristine; idempotent on resume (a stale worktree is `worktree remove -f`'d, falling back to `rm -rf` only after asserting the path sits under `$TMPDIR/compound-v/`); never removed on success by the worker itself — that's the caller's job after a successful `git apply`. The baseline SHA is captured **before** `worktree add` and passed as `--baseline <sha>` so an in-worktree commit-to-hide-changes attempt is still diffed.

Merge-back is **caller-only, PASS-only** — the script observes and reports, never merges:

```bash
# PASS
git -C "$WT" add -A
git -C "$WT" diff --cached --binary HEAD | (cd "$REPO" && git apply --index)
git -C "$REPO" worktree remove -f "$WT"
# BLOCKED / timeout / error: do not merge; leave the worktree for inspection; eligible for /v:resume
```

---

## Resume

Devin exposes a **real resumable session** — VERIFIED live `--help`: `-c, --continue` (most recent conversation) and `-r, --resume [<SESSION_ID>]` (a specific id, or an *interactive* picker if omitted — unusable headlessly, so a worker must always pass an explicit id). This is closer to **Cursor's** resumability than Codex's UUID-from-JSON-stream pattern, but **the capture mechanism is unverified**: the best VERIFIED-live candidate is `devin list --format json` (confirmed to work **without login**, returns `[]` cleanly in an empty dir) run in the worktree directory after the job — session listing appears to be scoped per-directory (DOC-CLAIMED), but the exact field name and whether it is populated immediately after `-p` exits is **unverified without an authenticated run**. Compound V's default **git-wins / fresh re-dispatch** tie-break still applies regardless of whether resume capture works.

---

## Backend-failure classification (not yet built — needs real error samples)

A `_DEVIN_RULES` table in [`scripts/compound-v-classify-failure.py`](../../scripts/compound-v-classify-failure.py) (mirroring the existing per-backend substring-match tables) is **not yet built**, because no real Devin failure text (expired `COGNITION_API_KEY`, rate-limit, ACU exhaustion, etc.) is available without an authenticated failing run — this plugin does not fabricate error-text signatures. Until built, a Devin worker script should fail closed to `failure_class: "other"` on any non-zero exit, matching the same fail-closed rule every adapter already applies when the classifier can't determine a specific class. **Flagged as follow-on work**, not part of this v1 change.

---

## Worker script — draft only, not yet built

Following the exact shape of [`scripts/compound-v-run-codex-worker.sh`](../../scripts/compound-v-run-codex-worker.sh) / `-antigravity-worker.sh` / `-cursor-worker.sh`, a `scripts/compound-v-run-devin-worker.sh` would be a straightforward port of the Cursor worker's structure (worktree lifecycle, `write_allowed` expansion into an allow-file, `compound-v-scope-check.py` invocation, `emit_job_result` via `jq`) with three backend-specific differences: (1) no `-f`/`--dangerously-skip-permissions`-equivalent flag name (`--permission-mode dangerous` instead), (2) `summary` comes straight from captured stdout (no `.result` JSON field to parse — the Antigravity pattern, not the Cursor one), (3) `session_id` extraction is a **best-effort, unverified** `devin list --format json` parse rather than a confirmed JSON field. Given (3) is unverified without a live account, **this v1 change documents the invocation here rather than shipping the worker script** — building it now would encode an unverified session-id extraction path as if it were proven. Building the script is real, scoped, buildable follow-on work once a Cognition account is available to verify the task-execution facts marked DOC-CLAIMED above.

## Invoking the (future) script

```bash
scripts/compound-v-run-devin-worker.sh \
  --run-id   2026-07-13-some-feature \
  --job-id   task-1-build \
  --repo     /abs/path/to/repo \
  --prompt-file /abs/path/to/jobs/task-1-build.prompt.md \
  --model    "claude-sonnet-4" \
  --write-allowed "src/features/build/**" \
  --timeout-sec 900 \
  --network  false      # accepted for CLI parity, NOT enforced (see Safety)
# optional: --read-only true     (advisory — enforced post-hoc via empty --write-allowed)
# --model is OPTIONAL: omit it (or pass "") to let devin use its configured default.
```

All file paths MUST be **absolute**. `--write-allowed` is a **colon-separated** glob list; an **empty** `--write-allowed` is a read-only/review job (any change ⇒ BLOCKED). `--timeout-sec` must be a **positive integer**. Devin requires an **authenticated** session (`devin auth login` / `COGNITION_API_KEY`) — `/v:init` records availability + auth (see `commands/v-init.md` §1a-quater).
