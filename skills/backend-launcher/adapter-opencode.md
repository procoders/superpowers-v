# Adapter: opencode (headless `opencode run` worker)

> Read the contract in [`SKILL.md`](SKILL.md) first — this adapter implements that `job_spec → job_result` interface. This file is the backend-specific runbook; the wiring lives in [`scripts/compound-v-run-opencode-worker.sh`](../../scripts/compound-v-run-opencode-worker.sh) (**built, but auth-pending / coverage-unverified** — see "Worker script" below).

The opencode backend is a **Bash-spawned `opencode run` worker** — its own process, its own git worktree. It mirrors the Antigravity / Cursor adapters step-for-step ([`adapter-antigravity.md`](adapter-antigravity.md), [`adapter-cursor.md`](adapter-cursor.md)): worktree isolation, a git-derived scope gate, normalize → `job_result`, caller merges. UNLIKE every other backend, opencode is **provider-agnostic / multi-provider** — its resolved `model` is always a `provider/model` string (e.g. `anthropic/claude-opus-4-6`), never a bare model name.

Verified live against **opencode-ai 1.17.18** (npm, installed via `npm install -g opencode-ai`) on stock macOS. **This package ships new dev/beta builds multiple times per day** (`npm view opencode-ai --json` showed dist-tags timestamped within the hour of the original research probe) — re-probe the flag set at `/v:init` time; do not assume it is stable across even a few weeks.

---

## ⚠️ SAFETY — lower-trust, opt-in, WORKER-ONLY backend (read first)

**opencode has NO kernel write-confinement** — VERIFIED live by omission: the full `--help` and `run --help` output contains no `--sandbox`, `--read-only`, or equivalent OS-level isolation flag. Third-party plugins (`opencode-daytona`, `opencode-devcontainers`) can add real sandboxing, but none are core/bundled and none are used by this adapter.

**opencode's default permission posture is the opposite of Cursor/Antigravity's refuse-until-trusted stance.** Per opencode's own docs (DOC-CLAIMED, high confidence, not independently live-verified against a real write attempt in this research pass): *"By default, OpenCode allows all operations without explicit approval."* Contrast: Cursor refuses to run in an untrusted directory without `-f`; Antigravity refuses to write without `--dangerously-skip-permissions`; **opencode allegedly allows everything by default**, and you opt IN to asking via `opencode.json`'s `permission.*` config. Treat this specific claim as **DOC-CLAIMED, not independently confirmed live** — verify with a real write-attempting probe (no `--auto`, no permission config) before relying on it as the safety story.

**Net trust tier: opencode belongs in the same lower-trust, opt-in tier as Antigravity/Cursor** — the worktree + `git diff` scope gate detects an in-worktree scope leak but **cannot prevent** an out-of-worktree write or arbitrary shell side-effect, because there is no kernel boundary underneath it. If the "allows everything by default" doc claim holds, opencode may be the **most permissive of the three lower-trust backends by default**. **Prefer Codex for untrusted/high-stakes work; route to opencode only when the prompt/surface is trusted.**

**MANDATORY mitigation — always ship a restrictive `opencode.json` into the worktree.** Because opencode's baseline posture is unverified-but-plausibly-wide-open, this adapter does NOT rely on it: the worker must write a minimal `opencode.json` pinning `permission: {"*": "ask"}` (or stricter) into `$WT` before invoking `opencode run`, then pass `--auto` to auto-approve exactly the non-denied subset — so the effective behavior matches the codex/cursor/antigravity precedent (writes happen, but only inside a worktree the scope gate can diff) rather than trusting opencode's undocumented-in-practice wide-open default.

**CRITICAL — ambient-credential leak (load-bearing, live-observed).** opencode successfully authenticated and completed a real request with **ZERO** stored credentials (`opencode providers list` → `0 credentials`, file at `~/.local/share/opencode/auth.json`), purely by picking up an inherited `ANTHROPIC_BASE_URL` environment variable from the parent shell. **This is a real security-relevant finding, not a hypothetical:**

> **The worker script MUST NOT blindly inherit the dispatcher's own provider environment variables into the `opencode run` child process.** If it does, a job could silently authenticate as the ORCHESTRATOR's own Claude/OpenAI/Anthropic credentials rather than a credential intentionally scoped to that job — an unintended privilege leak from the calling process into an isolated, lower-trust worker. The worker MUST explicitly pass through only a documented allow-list of provider env vars (or none at all, forcing `opencode providers login` / a real `auth.json`), never a raw environment inherit (`env -i` plus an explicit allow-list, or an explicit `unset` of every known provider var before exec, is the correct shape — pick one and document it in the worker script when built).

**WORKER-ONLY — never an arbiter/review-panel seat (separate from the trust-tier question above).** opencode addresses models as `provider/model` strings, and the provider is allowed to differ **per tier cell** — so opencode's resolved model family is data-dependent, exactly like Devin. A `backend: opencode, model: "anthropic/claude-opus-4-6"` ballot would land in the SAME family bucket as the native Claude arbiter (`model_family()`'s existing substring heuristic), and a `backend: opencode, model: "openai/gpt-5.6-sol"` ballot would collapse with Codex's own bucket. Adding opencode to any arbiter panel without first keying family-dedup on the *resolved* model (never the backend name) would let a correlated ballot silently masquerade as an independent vote — **this adapter is worker dispatch only**; the family-dedup fix is a separate, later change.

---

## The 6 load-bearing steps (worker script built; env-scrub safety not yet live-verified end-to-end)

```
1. ISOLATE   git -C <repo> worktree add <WT> HEAD          # clean diff baseline (NO kernel sandbox)
2. RUN       cd <WT> && (write a scrubbed opencode.json into <WT>) && \
                        opencode run --dir <WT> --format json --auto \
                        -m <provider/model> [--variant <effort>] [-s <session-id>] \
                        --title "compound-v-<job-id>" "<prompt>" </dev/null
3. OBSERVE   compound-v-scope-check.py --worktree <WT> --baseline <sha>   # git-derived ∪ untracked ∪ ignored
4. ENFORCE   every changed path ∉ write_allowed ⇒ violation ⇒ blocked  (do NOT merge)
5. NORMALIZE → job_result  (summary ← concat of `type:"text"` event parts;
                            session_id ← first JSONL line's `.sessionID`, a `ses_...`-shaped token, NOT a UUID)
6. MERGE     caller, on PASS only:  git -C <WT> add -A
             git -C <WT> diff --cached --binary HEAD | (cd <repo> && git apply --index)  →  git worktree remove -f <WT>
```

Step 4 is the keystone — and because opencode has no kernel sandbox at all, worktree + `git diff` is the **only** enforcement this adapter relies on, exactly like Antigravity/Cursor. Steps 3–4 must be computed in git, never read from anything the model says it did, and would delegate to the deterministic authority [`scripts/compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py) — the same gate the dispatcher runs after every job. A worker script for this backend must **not** re-implement glob matching in bash.

**Only `write_allowed` would be enforced; `read_allowed` stays advisory** — same rule as every lower-trust adapter.

---

## Worker-prompt planner/executor lock

Every dispatched `prompt` MUST open with this lock (verbatim-in-spirit), exactly as the contract in `SKILL.md` requires:

> You are an implementation worker, NOT the planner. Do not change architecture. Do not write outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report BLOCKED.

This is the *instructed* half of planner/executor separation; the git-diff scope gate (steps 3–4) is the *enforced* half. Because opencode has no kernel sandbox and (per its own docs) a plausibly wide-open default posture, the lock carries the same weight it does for Antigravity/Cursor — instruction only.

---

## Pinned `opencode run` invocation (opencode-ai 1.17.18 — RE-PROBE OFTEN, see version-churn note above)

```bash
python3 "$SUPERVISOR" --timeout "$timeout_sec" --grace 3 -- \
  opencode run \
  --dir "$WT" \
  --format json \
  --auto \
  -m "$model" \
  ${effort:+--variant "$effort"} \
  ${session_id:+-s "$session_id"} \
  --title "compound-v-$job_id" \
  "$(cat "$prompt_file")" </dev/null >"$events_log" 2>"$stderr_log"
```

**Verified facts — load-bearing:**

- **`--dir "$WT"`** — VERIFIED live flag: *"directory to run in"*. opencode has a real `--cd`-equivalent, unlike Antigravity/Cursor/Devin.
- **`--format json`** — VERIFIED live: JSONL event stream to stdout, one JSON object per line. Sample captured live:
  ```json
  {"type":"step_start","timestamp":...,"sessionID":"ses_0a775d09dffe4xAFfV57IyRwki","part":{...}}
  {"type":"text","timestamp":...,"sessionID":"ses_...","part":{"id":"...","type":"text","text":"Hi!",...}}
  {"type":"step_finish","timestamp":...,"sessionID":"ses_...","part":{"reason":"stop",...}}
  ```
  Every event line carries `sessionID`. **There is no `--output-last-message` equivalent** — the worker must build `summary` by concatenating (or taking the last of) every `.part.text` from `type:"text"` events, and parse `session_id` from the **first** line's `.sessionID` field.
- **`--auto`** — VERIFIED live flag: *"auto-approve permissions that are not explicitly denied (dangerous!)"*. Required for any unattended write, paired with the mandatory pinned `opencode.json` above (see SAFETY).
- **`-m "$model"`** — VERIFIED live flag (`-m, --model`): *"model to use in the format of provider/model"*. Must be the **resolved** `provider/model` string (see Model resolution, below) — a bare name will likely fail opencode's own model resolution even though the flag accepts it syntactically.
- **`--variant "$effort"`** — VERIFIED live flag exists: *"model variant (provider-specific reasoning effort, e.g. high, max, minimal)"* — **NOT** the same vocabulary as Compound V's `low/medium/high/xhigh`. Optional; omit unless the resolved provider is known to accept the value (best-effort, provider-dependent — not independently verified live in this research pass whether an unrecognized value is silently ignored or errors).
- **`-s "$session_id"`** — VERIFIED live flag (`-s, --session`): resume a specific session id.
- **`--title`** — VERIFIED live flag; cosmetic, helps `opencode session list` correlate to Compound V's own job ids.
- **stdin `</dev/null`** — same non-negotiable rule as every other external worker (`SKILL.md` "External-CLI launch"). Small-sample live testing showed no hang even without the redirect in one interactive probe, but the redirect discipline is followed regardless, per this plugin's own launch rule.
- **No `--output-schema`** equivalent at the CLI level for `run` (an SDK-level `format: {type:"json_schema",...}` exists for `opencode serve` + a client — out of scope for a one-shot `opencode run` worker). Accept-and-ignore `--output-schema` for CLI parity, like Antigravity/Cursor.
- **`opencode serve`** starts a long-running headless server (VERIFIED live via `--help`) — structurally the same shape as the rejected `openai-codex` app-server broker (persistent, stateful, single-flight-ish). **Do not use `serve`/`attach` as the primary mechanism** — `opencode run` (one-shot Bash-spawned process per job) is the correct primitive, for the same reason `SKILL.md` excludes the codex app-server broker.

| Flag | Role |
|---|---|
| `--dir "$WT"` | working root = the worktree |
| `--format json` | JSONL event stream to stdout; parse `sessionID` (first line) + `type:"text"` parts (summary) |
| `--auto` | **required** for unattended writes — paired with the mandatory pinned `opencode.json` (Safety) |
| `-m "$model"` | resolved `provider/model` string — resolved from `(backend=opencode, tier, effort)` |
| `--variant "$effort"` | optional; provider-specific reasoning-effort vocabulary, NOT `low/medium/high/xhigh` |
| `-s "$session_id"` | optional; resume a prior opencode session (`ses_...`-shaped, not a UUID) |
| `--title "compound-v-$job_id"` | cosmetic correlation aid |
| `"$prompt"` | positional; the worker prompt (lock first) |

### `--read-only` / `--network` are advisory for opencode

No kernel sandbox toggle exists (VERIFIED live by omission), and network access for tool calls is governed only by the same advisory `permission` config. The worker would accept `--read-only` / `--network` for **CLI parity** only, exactly like Antigravity/Cursor/Devin. A read-only / review job is enforced post-hoc: pass an **empty** `--write-allowed`.

### Model + effort: resolved before dispatch, not hardcoded — the `provider/model` design

The dispatcher resolves the concrete model **before** dispatch via [`scripts/compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) with `--backend opencode --tier <tier> [--config .claude/compound-v.json]`. **Design point (no schema change needed):** the resolver already treats every `{tier: model}` cell as an opaque string — opencode's convention is simply that each cell's value is a full `provider/model` string, and the **provider is allowed to differ per cell** (unlike every other backend's single-vendor map). The built-in curated map:

```
deep     → anthropic/claude-opus-4-6
standard → openai/gpt-5.6-terra
light    → opencode/mimo-v2.5-free      # a real, credential-free model — verified live via `opencode models`
```

`light` legitimately points at one of opencode's own curated **free** models — VERIFIED live via `opencode models` (works with zero configured credentials, backed by models.dev): `opencode/big-pickle`, `opencode/deepseek-v4-flash-free`, `opencode/hy3-free`, `opencode/mimo-v2.5-free`, `opencode/nemotron-3-ultra-free`, `opencode/north-mini-code-free`. This is the **one backend where a real free tier exists out of the box** — no other backend in this plugin offers that. `opencode models [provider]` is real live discovery (unlike Codex/Devin's curated-only pattern); `/v:models` shows the catalog, but assignment stays curated + user-confirmed (opencode's catalog spans unrelated vendor families with no shared naming convention, mirroring the Cursor precedent — Compound V does not auto-rank it).

An explicit manifest `model` override skips resolution and wins.

**`xhigh` is codex-only.** opencode's own effort vocabulary is `--variant` (provider-specific: high/max/minimal), never `xhigh`. `effort: xhigh` paired with `backend: opencode` is rejected by both [`compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) and [`compound-v-validate-manifest.py`](../../scripts/compound-v-validate-manifest.py) — the same backend-agnostic guard every non-codex backend gets.

### Timeout — the shared process-group supervisor

No built-in `--timeout` flag was found in `--help`. A worker script would run opencode under [`scripts/compound-v-run-with-timeout.py`](../../scripts/compound-v-run-with-timeout.py) exactly like Codex/Antigravity/Cursor/Devin — `killpg`s the whole `opencode` process tree on expiry and returns 124 → `status: "timeout"`. Small-sample live testing showed clean, fast (~2s) exit-1 behavior on a forced bad-model error (no hang), consistent with the supervisor's exit-code contract.

---

## Worktree lifecycle / Merge-back (draft, mirrors Antigravity/Cursor exactly)

Identical in shape to [`adapter-antigravity.md`](adapter-antigravity.md) / [`adapter-cursor.md`](adapter-cursor.md): a fresh `git worktree add "$WT" HEAD` gives a clean diff baseline; worktrees would live **outside the repo** under `"${TMPDIR:-/tmp}"/compound-v/<run-id>/<job-id>`; scratch (`$WT.art`: captured JSONL events log + stderr + the pinned `opencode.json` + the expanded allow-globs file) lives **outside** the worktree so it stays pristine; idempotent on resume; never removed on success by the worker itself. The baseline SHA is captured **before** `worktree add` and passed as `--baseline <sha>` to the scope gate.

Merge-back is **caller-only, PASS-only**:

```bash
# PASS
git -C "$WT" add -A
git -C "$WT" diff --cached --binary HEAD | (cd "$REPO" && git apply --index)
git -C "$REPO" worktree remove -f "$WT"
# BLOCKED / timeout / error: do not merge; leave the worktree for inspection; eligible for /v:resume
```

---

## Resume

opencode exposes real session resumability — VERIFIED live: `-c`/`--continue` (last session), `-s`/`--session <id>` (a specific id), `--fork` (fork instead of continuing in place). Every JSONL event line carries `sessionID` (VERIFIED live, e.g. `ses_0a775d09dffe4xAFfV57IyRwki`). **This is a custom prefixed token, NOT an RFC-4122 UUID** — the Codex worker's UUID-anchor regex validator (`^[0-9a-fA-F]{8}-...$`) must NOT be reused verbatim for opencode; a new, looser validator (non-empty, `ses_` prefix, safe charset) would be needed. `opencode session list [--max-count N] [table|json]` and `opencode session delete <id>` also exist (VERIFIED live via `--help`) — useful for cleanup/liveness, analogous to the Codex worker's events-log. Compound V's default **git-wins / fresh re-dispatch** tie-break still applies regardless.

---

## Backend-failure classification (not yet built — needs real per-provider error samples)

opencode emits `{"type":"error","error":{"name":...,"data":{"message":...}}}` as a JSONL event on failure (VERIFIED live for an unknown-model case: exit 1, no hang, ~2s). A needle-set for [`scripts/compound-v-classify-failure.py`](../../scripts/compound-v-classify-failure.py) `--backend opencode` is **not yet built** — provider errors surface differently per-provider (an Anthropic 429 looks different from an OpenAI 429), which is a genuinely harder classification problem than any other backend faces, precisely BECAUSE opencode proxies multiple providers. Until built, a worker script should fail closed to `failure_class: "other"` for anything not exactly matched, same pattern the Cursor adapter already uses for its own "provisional" needles. **Flagged as follow-on work**, not part of this v1 change.

---

## Worker script — built, auth-pending / coverage-unverified

Following the exact shape of [`scripts/compound-v-run-codex-worker.sh`](../../scripts/compound-v-run-codex-worker.sh) / `-antigravity-worker.sh` / `-cursor-worker.sh`, [`scripts/compound-v-run-opencode-worker.sh`](../../scripts/compound-v-run-opencode-worker.sh) is a port of the Cursor worker's structure (worktree lifecycle, `write_allowed` expansion, `compound-v-scope-check.py` invocation, `emit_job_result` via `jq`) with FOUR backend-specific differences that make it more than a copy-paste: (1) it **writes a pinned, restrictive `opencode.json` into `$WT`** before invoking `opencode run` (Safety); (2) it **explicitly scrubs the dispatcher's own provider environment variables** before exec'ing `opencode` (the ambient-credential-leak finding — an `env -i` + allow-list shape or explicit `unset`s); (3) `session_id` extraction parses the FIRST JSONL line's `.sessionID` and validates against a `ses_`-prefixed safe-charset pattern, NOT the Codex worker's UUID regex; (4) `summary` is built by concatenating every `.part.text` from `type:"text"` events, since there is no `--output-last-message` file. The script is shipped and Codex-hardened, but it stays **opt-in / lower-trust and unverified end-to-end**: difference (2) is security-load-bearing and the env-scrub has **not yet been live-verified** to actually prevent the ambient-credential leak, and opencode's flag set churns daily — treat it as auth-pending / coverage-unverified and re-probe at `/v:init` before relying on it.

## Invoking the (future) script

```bash
scripts/compound-v-run-opencode-worker.sh \
  --run-id 2026-07-13-some-feature \
  --job-id task-1-build \
  --repo /abs/path/to/repo \
  --prompt-file /abs/path/to/jobs/task-1-build.prompt.md \
  --model "anthropic/claude-sonnet-4-6" \
  --write-allowed "src/features/build/**" \
  --timeout-sec 900 \
  --network false
# optional: --effort medium   (→ --variant medium, best-effort/provider-dependent)
# optional: --read-only true  (advisory — enforced post-hoc via empty --write-allowed)
```

All file paths MUST be **absolute**. `--write-allowed` is a **colon-separated** glob list; an **empty** `--write-allowed` is a read-only/review job (any change ⇒ BLOCKED). `--timeout-sec` must be a **positive integer**. `--model` MUST be a genuine `provider/model` string (a bare name will likely fail opencode's own resolution). opencode requires **either** a stored provider credential (`opencode providers login`) **or** an intentionally-set provider env var — `/v:init` records which (see `commands/v-init.md` §1a-quinquies).
