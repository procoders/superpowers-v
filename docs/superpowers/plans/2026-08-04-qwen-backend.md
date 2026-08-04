# qwen Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `qwen` as a seventh dispatch backend — a headless Qwen Code CLI worker authenticated against Alibaba Cloud's Bailian Coding Plan — registered at every backend site, sandbox-mandatory, worker-only, and opt-in-gated.

**Architecture:** A Bash-spawned `qwen` process (positional prompt, never the deprecated `-p`) running in its own git worktree under the process-group timeout supervisor, with the dispatcher's environment scrubbed via `env -i` and `QWEN_HOME`/`HOME` redirected to scratch. Kernel sandboxing is driven entirely through `QWEN_SANDBOX`/`SEATBELT_PROFILE` environment variables (the env var outranks the CLI flag — verified in the released source) and is **mandatory**: a machine with no working sandbox provider reports `qwen` unavailable rather than running it unconfined. Enforcement stays where it already is — the caller's git-derived scope gate.

**Tech Stack:** bash 3.2 (no arrays), Python 3.9-safe stdlib only, `jq`, `git`. No new dependency, no SDK, no service. `qwen` (npm `@qwen-code/qwen-code`, requires Node ≥ 22) is an unpinned external CLI exactly like `codex`/`cursor-agent`.

**Spec:** `docs/superpowers/specs/2026-08-04-qwen-code-cli-backend-design.md` — the single source of requirements.
**Base:** branch `feat/qwen-backend` in worktree `/Users/yurifediai/Projects/Procoders/compaund-v-qwen`, off `local/three-pr-integration` (`4bcb13c`). **Never touch `/Users/yurifediai/Projects/Procoders/compaund-v`** — the operator is live-testing z.ai and pool rotation there.

## Global Constraints

- **Python 3.9-safe stdlib only.** No third-party imports in any `scripts/*.py`. No shared imports between the standalone CLIs — `compound-v-resolve-model.py`, `compound-v-validate-manifest.py`, and `compound-v-project-config.py` each carry duplicated vocabulary **on purpose**; keep them in sync, never refactor into a shared module.
- **bash 3.2** (macOS default): no arrays, no `${var,,}`, no process substitution in the worker scripts.
- **NEVER `haiku`** anywhere — not in a model map, not in a config example, not in a comment as a suggestion.
- **anti-ruflo:** never record an estimated or invented token/cost number. A failed job's usage is `measured: false` with null counts, never a fabricated `0`.
- **Enforcement fields are git-derived by the caller** (`blocked`, `files_changed`, `violations`) — never self-reported by the worker model.
- **Every external-CLI launch** goes through `scripts/compound-v-run-with-timeout.py` with `stdin </dev/null`.
- **No `--dangerously-skip-permissions`** on any path. For `qwen` specifically: never `--allowed-tools` (it bypasses confirmation, it does not restrict), never `--yolo` (mutually exclusive with `--approval-mode` at parse time — emit `--approval-mode=yolo`), never `--worktree`, never `-p`/`--prompt`, never `--openai-api-key` in argv, never `--insecure`, never a bare `--resume`.
- **Do not modify PR #7's failure machinery.** `qwen` takes the global retry defaults. No `PER_CLASS_MAX` branch, no new circuit-break reason.
- **Version lockstep:** `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, and the top `CHANGELOG.md` release heading must carry the identical version — three separate CI steps cross-check them.
- **Status stays `auth-pending / coverage-unverified`.** No live Coding Plan key exists; nothing in this plan may describe the adapter as "verified live."

---

## File Structure

**New files**

| Path | Responsibility |
|---|---|
| `skills/backend-launcher/adapter-qwen.md` | The backend-specific runbook: pinned invocation, compliance, egress, safety. Must exist before anything links to it. |
| `scripts/compound-v-run-qwen-worker.sh` | The worker: worktree lifecycle, env scrub, sandbox wiring, ancestor-`.env` preflight, invocation, scope gate, `job_result` emit. |
| `scripts/test-qwen-worker-stub.sh` | Stub-first proof. Injects a **fake** `qwen` on PATH and **always runs** — never skips. |
| `scripts/test-qwen-wire-smoke.sh` | Real-binary argv/interpretation proof. The **only** qwen test that skips when `qwen` is absent. |

**Modified files** — one owner each, no file appears in two tasks.

| Path | Change |
|---|---|
| `scripts/compound-v-resolve-model.py` | `_QWEN` map, `_stance_map`, `BACKENDS`, selftest. **CONTENDED — one task, never split.** |
| `scripts/compound-v-project-config.py` | `VALID_POOL_BACKENDS`. |
| `scripts/compound-v-dashboard.py` | `_PROVIDER_BACKENDS`. |
| `schemas/job_result.schema.json` | `usage.backend` description string. |
| `scripts/compound-v-classify-failure.py` | `_QWEN_RULES`, `classify()` branch, `CONCRETE_BACKENDS`, selftest. |
| `scripts/compound-v-failure-policy.py` | `FALLBACK`, `CONCRETE_BACKENDS`, selftest. |
| `scripts/compound-v-usage-extract.py` | `_extract_qwen`, `extract_usage` branch, selftest. |
| `scripts/compound-v-validate-manifest.py` | `VALID_BACKENDS`, worktree tuple, reviewer block tuple, opt-in gate, fixtures. |
| `scripts/compound-v-pool-state.py` | `VALID_CONCRETE_BACKENDS`, `backend_available()`, selftest. |
| `skills/backend-launcher/SKILL.md` · `skills/compound-v/routing-policy.md` · `skills/compound-v/execution-manifest.md` · `skills/compound-v/phase-3-parallel-opus-dispatch.md` · `skills/compound-v/state-machine.md` · `agents/parallel-dispatcher.md` · `commands/v-init.md` · `commands/v-models.md` · `commands/v-status.md` | Backend enumerations, adapter table, default pool policy, capability probe. |
| `CHANGELOG.md` · `.claude-plugin/plugin.json` · `.claude-plugin/marketplace.json` | Version lockstep. |

---

## Partition Map

Disjoint write sets. Every path belongs to exactly one task.

| Task | `write_allowed` | backend · tier | Depends on |
|---|---|---|---|
| 0 | `scripts/compound-v-resolve-model.py`, `scripts/compound-v-project-config.py`, `scripts/compound-v-dashboard.py`, `schemas/job_result.schema.json` | claude · deep (opus) | — (serial, first) |
| 1 | `skills/backend-launcher/adapter-qwen.md` | claude · deep (opus) | — |
| 2 | `scripts/compound-v-run-qwen-worker.sh`, `scripts/test-qwen-worker-stub.sh`, `scripts/test-qwen-wire-smoke.sh` | claude · deep (opus) | 0 |
| 3 | `scripts/compound-v-classify-failure.py`, `scripts/compound-v-failure-policy.py` | claude · standard (sonnet) | 0 |
| 4 | `scripts/compound-v-usage-extract.py` | claude · standard (sonnet) | 0 |
| 5 | `scripts/compound-v-validate-manifest.py` | claude · deep (opus) | 0 |
| 6 | `scripts/compound-v-pool-state.py` | claude · deep (opus) | 0 |
| 7 | `skills/backend-launcher/SKILL.md`, `skills/compound-v/routing-policy.md`, `skills/compound-v/execution-manifest.md`, `skills/compound-v/phase-3-parallel-opus-dispatch.md`, `skills/compound-v/state-machine.md`, `agents/parallel-dispatcher.md`, `commands/v-init.md`, `commands/v-models.md`, `commands/v-status.md` | claude · standard (sonnet) | 1, 2 |
| 8 | `CHANGELOG.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | claude · standard (sonnet) | all |

**Routing rationale.** Opus for Task 0 (shared foundation — a wrong tier map turns CI red for *every* backend, and this file is loaded by-path from the validator), Task 1 (carries the compliance/safety prose), Task 2 (credential scrubbing and sandbox wiring), Task 5 (the reviewer gate and the opt-in gate are security boundaries), Task 6 (`backend_available` is what makes "sandbox mandatory" real at routing time). Sonnet for the mechanical registration and doc tasks. **Never haiku. All reviewers are Opus.**

**Ordering constraints, each with a CI gate behind it:**
1. Task 1 before Task 7 — the repo-wide dead-link scan fails on a `SKILL.md` row linking `adapter-qwen.md` before that file exists.
2. Task 0 before Tasks 5 and 6 — `resolve()` raises `ValueError` on an unresolvable cell, and the validator/pool selftests resolve `qwen`.
3. Task 8 last, and atomic — three CI steps cross-check the version trio.

---

### Task 0: Register `qwen` in the shared vocabulary and model map

**Files:**
- Modify: `scripts/compound-v-resolve-model.py` (`_QWEN` map, `_stance_map()`, `BACKENDS`, selftest)
- Modify: `scripts/compound-v-project-config.py` (`VALID_POOL_BACKENDS`)
- Modify: `scripts/compound-v-dashboard.py` (`_PROVIDER_BACKENDS`)
- Modify: `schemas/job_result.schema.json` (`usage.backend` description)

**Interfaces:**
- Produces: `resolve("qwen", tier)` returns `{"model": "qwen3-coder-plus", ...}` for all three tiers in every stance; `"qwen"` is a member of `BACKENDS`, `VALID_POOL_BACKENDS`, and `_PROVIDER_BACKENDS`. Every later task depends on `qwen` being a resolvable, legal backend name.

**Why this is Task 0 and runs serially:** `resolve()` raises on an unresolvable cell, and `compound-v-resolve-model.py --selftest` iterates *every* backend × *every* tier as a hard CI gate. Adding `qwen` to `BACKENDS` without a resolvable map turns CI red for all seven backends on the first commit.

- [ ] **Step 1: Write the failing selftest assertions**

In `scripts/compound-v-resolve-model.py`, find the selftest assertion that pins the advisor tuple (`"zai is not advisor-consultable"`) and add these beside it:

```python
    expect("qwen resolves deep to a real catalog model",
           resolve("qwen", "deep")["model"] == "qwen3-coder-plus")
    expect("qwen resolves light to a real catalog model (never 'auto')",
           resolve("qwen", "light")["model"] == "qwen3-coder-plus")
    expect("qwen is in BACKENDS", "qwen" in BACKENDS)
    expect("qwen is identical across stances",
           DEFAULT_MODELS_BY_STANCE["cost-aware"]["qwen"]
           == DEFAULT_MODELS_BY_STANCE["balanced"]["qwen"])
    expect("qwen rejects xhigh (codex-only rule)",
           _raises(lambda: resolve("qwen", "deep", effort="xhigh")))
    expect("qwen is NOT advisor-consultable in v1",
           "qwen" not in ADVISOR_CONSULTABLE_NONCLAUDE)
```

If a `_raises` helper does not already exist in the selftest, add it next to the other helpers:

```python
def _raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False
```

- [ ] **Step 2: Run the selftest to verify it fails**

Run: `python3 scripts/compound-v-resolve-model.py --selftest`
Expected: FAIL — `resolve("qwen", ...)` raises `ValueError` because no map exists.

- [ ] **Step 3: Add the `_QWEN` map**

Insert immediately after the `_ZAI` definition:

```python
# Alibaba Bailian "Coding Plan" (backend `qwen`), driven through the genuine Qwen Code CLI.
# Catalog VERIFIED 2026-08-04 against Alibaba's own Model Studio help page: qwen3.7-plus,
# qwen3.6-plus, qwen3.5-plus, qwen3-max-2026-01-23, qwen3-coder-next, qwen3-coder-plus,
# MiniMax-M2.5, glm-5, glm-4.7, kimi-k2.5 are all reachable on one key.
#
# All three tiers deliberately carry the SAME model. Per-tier differentiation needs live
# measurement on a real Coding Plan key (`/v:models` rewrites this map), and inventing a
# ranking from a catalog listing would be a fabricated metric. `qwen3-coder-plus` is the
# coding-specialised, documented default. NOT "auto": unlike cursor (which resolves "auto"
# internally), the qwen worker passes --model straight to the endpoint, so a placeholder
# would be sent literally and rejected.
#
# Qwen3.8-Max (launched 2026-08-03) is NOT in the Coding Plan catalog — do not add it here
# until it appears there.
#
# Lower-trust tier in the sense that no reviewer/arbiter seat is permitted, but UNLIKE
# antigravity/cursor/zai this backend REQUIRES a kernel sandbox (QWEN_SANDBOX) — see
# skills/backend-launcher/adapter-qwen.md. NEVER haiku.
_QWEN = {"deep": "qwen3-coder-plus", "standard": "qwen3-coder-plus",
         "light": "qwen3-coder-plus"}
```

- [ ] **Step 4: Wire it into `_stance_map()` and `BACKENDS`**

In `_stance_map()`, add the entry after `"zai": _ZAI,` and update the docstring's backend list:

```python
        "zai": _ZAI,
        "qwen": _QWEN,
    }
```

Then extend the tuple:

```python
BACKENDS = ("claude", "codex", "antigravity", "cursor", "devin", "opencode", "zai", "qwen")
```

- [ ] **Step 5: Run the selftest to verify it passes**

Run: `python3 scripts/compound-v-resolve-model.py --selftest`
Expected: PASS, including the pre-existing "no haiku in any stance map" assertion.

- [ ] **Step 6: Register the name in the three sibling vocabularies**

`scripts/compound-v-project-config.py`:

```python
VALID_POOL_BACKENDS = (
    "claude", "codex", "antigravity", "cursor", "devin", "opencode", "zai", "qwen",
)
```

`scripts/compound-v-dashboard.py`:

```python
_PROVIDER_BACKENDS = frozenset(
    ("claude", "codex", "antigravity", "cursor", "devin", "opencode", "zai", "qwen"))
```

`schemas/job_result.schema.json` — append `qwen` to the `usage.backend` description's backend list (a description string only; there is no enum on this property).

- [ ] **Step 7: Run every selftest and the schema check**

```bash
python3 scripts/compound-v-resolve-model.py --selftest
python3 scripts/compound-v-project-config.py --selftest
python3 scripts/compound-v-dashboard.py --selftest
jq empty schemas/job_result.schema.json && echo "schema parses"
```

Expected: all four succeed.

- [ ] **Step 8: Commit**

```bash
git add scripts/compound-v-resolve-model.py scripts/compound-v-project-config.py \
        scripts/compound-v-dashboard.py schemas/job_result.schema.json
git commit -m "feat(qwen): register the backend and its Coding Plan tier map"
```

---

### Task 1: The adapter runbook

**Files:**
- Create: `skills/backend-launcher/adapter-qwen.md`

**Interfaces:**
- Produces: the file every doc in Task 7 links to. Nothing consumes it programmatically.

**Why Opus:** this document carries the compliance analysis and the safety boundaries; getting its claims wrong is how an operator loses a subscription or leaks a repository.

- [ ] **Step 1: Write the adapter doc**

Model it on `skills/backend-launcher/adapter-zai.md`'s structure, with **these sections mandatory**, each sourced from the spec (do not re-derive, do not soften):

1. **Header** — `qwen` is a Bash-spawned Qwen Code CLI worker; own process, own worktree; **auth-pending / coverage-unverified**; record the exact `qwen --version` slot as `TBD-until-live-probe` **written as an explicit unknown**, not as a fake version number.
2. **⚠️ SAFETY — lower-trust in role, sandbox-mandatory in mechanism, WORKER-ONLY.** State that `worktree` is enforced by the manifest validator, that a reviewer job is rejected by name, and that the kernel sandbox is required rather than optional.
3. **Compliance** — reproduce the spec's Compliance section **verbatim in both English and Chinese**, including the 「以 API 调用的形式」 qualifier and both readings, the explicit statement that Compound V cannot resolve the ambiguity, and that the operator accepts account-suspension risk. **Do not reuse `adapter-zai.md`'s "spawning the vendor-approved binary is the compliant path" sentence** — it is a conclusion about a differently-shaped clause and reproducing it here would be a false assurance.
4. **Operator clauses** — one natural person, no key sharing, no resale/sublicense/account transfer; keys auto-disable on detected public exposure; never put the key in CI or a shared secret store.
5. **Data egress** — Qwen Code's **actual** context-file set (`AGENTS.md`, `QWEN.md`, `CONTEXT.md`, `.qwen/QWEN.local.md`, transitive `@`-imports), the fact that `--safe-mode` currently suppresses it, and that dropping `--safe-mode` re-opens it. State plainly that a job against this repository would otherwise ship `AGENTS.md` — Compound V's own architecture document — to Alibaba. Cite the first-party mitigations (no training on customer data, AES-256, SOC 2) and note that retention period, storage region, and deletion path are **not published**.
6. **The pinned invocation** — exactly as in the spec's "Credentials and isolation", with the per-flag rationale, including why the sandbox is driven by env vars (`QWEN_SANDBOX` outranks `--sandbox`; `--sandbox` is a boolean, not a profile) and why `--allowed-tools`/`--yolo`/`--worktree`/`-p` are forbidden.
7. **Model and effort** — the catalog, `qwen3-coder-plus` as the provisional default for all tiers, `effort` advisory with `xhigh` documented as **Compound V policy, not a Qwen limitation** (Qwen supports `xhigh` and `max` natively).
8. **Quota** — request-counted (Pro: 6,000 / 5h, 45,000 / week, 90,000 / month), no pay-as-you-go fallback, dynamically-adjusted concurrency limit, `backend_max_parallel.qwen = 2` labeled **unmeasured**.
9. **Backend-failure classification** — the needle set and the throttle-vs-window split.
10. **Worktree lifecycle and merge-back** — identical in shape to `adapter-zai.md`.
11. **Security precedent** — GHSA-wpqr-6v78-jr5g (CVSS 10.0, fixed in Gemini CLI 0.39.1), Qwen Code forked at v0.8.2, Trusted Folders documented as off by default, backport status **unverified** and a required live-probe item.
12. **Invoking the script** — the exact CLI surface from Task 2.

- [ ] **Step 2: Verify no dead links and no forbidden claims**

```bash
# every intra-repo link in the new file resolves
grep -oE '\]\([^)]+\.(md|py|sh|json|ya?ml)[^)]*\)' skills/backend-launcher/adapter-qwen.md \
  | sed 's/^](//;s/)$//' | sed -E 's/#.*$//;s/:[0-9]+(-[0-9]+)?$//' \
  | while read -r p; do case "$p" in http*|"") continue;; esac; \
      [ -f "skills/backend-launcher/$p" ] || echo "DEAD: $p"; done
# the status must not claim verification
grep -q "auth-pending / coverage-unverified" skills/backend-launcher/adapter-qwen.md && echo "status ok"
grep -qi "verified live" skills/backend-launcher/adapter-qwen.md && echo "FORBIDDEN CLAIM" || echo "no premature verification claim"
```

Expected: no `DEAD:` lines, `status ok`, `no premature verification claim`.

- [ ] **Step 3: Commit**

```bash
git add skills/backend-launcher/adapter-qwen.md
git commit -m "docs(qwen): add the adapter runbook"
```

---

### Task 2: The worker script and its stub proof

**Files:**
- Create: `scripts/compound-v-run-qwen-worker.sh`
- Create: `scripts/test-qwen-worker-stub.sh`
- Create: `scripts/test-qwen-wire-smoke.sh`

**Interfaces:**
- Consumes: `resolve("qwen", tier)["model"]` from Task 0 (passed in as `--model`).
- Produces: the CLI surface below, and a `job_result` JSON on stdout conforming to `schemas/job_result.schema.json`.

```
scripts/compound-v-run-qwen-worker.sh \
  --run-id <id> --job-id <id> --repo <abs> --prompt-file <abs> \
  --model <name> --write-allowed <colon-separated globs> --timeout-sec <int> \
  [--effort low|medium|high] [--read-only true|false] [--network true|false] \
  [--events-log <abs>] [--output-schema <ignored, CLI parity>]
```

**Base it on `scripts/compound-v-run-zai-worker.sh` (411 lines) — the POST-FIX version on this branch.** Copy its skeleton wholesale: argument parsing, `id_is_safe`, absolute-path checks, worktree create/remove, `$ART` scratch outside the worktree, scope-gate invocation, `emit_job_result`. **Do not copy its `RUN_ID=""""` typo** (four quote characters — harmless but real, and it survives shellcheck).

**Inherit these hard-won properties verbatim — each was earned by a real bug:**
- `--allow`-argument transport for the scope-gate allow-list. The other five workers write `$ART/write_allowed.globs` and read it back; a child with write access can append `**` to that file and turn its own violation into a PASS — **reproduced**. Pass repeated `--allow` arguments from positional parameters instead.
- `env -i` wraps the **supervisor**, never the binary — the supervisor is the long-lived process whose argv is `ps`-readable for the whole job.
- `--env-only "$ENV_ONLY_NAMES"` on the supervisor: a macOS Python.framework build injects `SDKROOT`/`CPATH`/etc. into the supervisor's own environment, which `Popen` would otherwise pass through.
- `set -f` (noglob) around the `IFS=":"` split of `--write-allowed` — entries are literal globs, not paths to expand.
- Scope-gate exit code `1` means BLOCKED and is **not** fatal; only rc > 1 or unparseable output is a worker fault.
- Idempotent worktree recreation on resume; baseline SHA captured **before** `git worktree add`.

**Backend-specific deltas from zai — the whole point of this task:**

1. **Environment allow-list.** Replace zai's Anthropic variables:

```bash
_SAFE_ENV_VARS="PATH TMPDIR LANG"
ENV_ONLY_NAMES="$(printf '%s' "$_SAFE_ENV_VARS" | tr ' ' ',')"
ENV_ONLY_NAMES="$ENV_ONLY_NAMES,HOME,QWEN_HOME,BAILIAN_CODING_PLAN_API_KEY,OPENAI_BASE_URL"
ENV_ONLY_NAMES="$ENV_ONLY_NAMES,QWEN_SANDBOX,SEATBELT_PROFILE,QWEN_SANDBOX_IMAGE,SANDBOX_FLAGS"
```

`QWEN_HOME` is not optional decoration: it is Qwen Code's purpose-built config-relocation lever and it additionally removes `~/.env` from the discovery set, which plain `HOME` redirection does not do. **`SANDBOX` is deliberately absent** — see delta 3.

2. **Refuse to start without credentials.** Mirror zai's `ZAI_API_KEY` guard:

```bash
[ -n "${BAILIAN_CODING_PLAN_API_KEY:-}" ] || \
  die "BAILIAN_CODING_PLAN_API_KEY is not set — the qwen worker never reads a key from a file inside the repo"
OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://coding-intl.dashscope.aliyuncs.com/v1}"
```

3. **Sandbox is mandatory, driven by environment, and proven afterwards.**

```bash
# Qwen Code's own source: "environment variable takes precedence over argument" — QWEN_SANDBOX
# BEATS the -s flag, the opposite of what the published docs claim. And -s is a BOOLEAN, not a
# profile selector. So sandboxing is configured entirely through the environment.
if [ "$(uname -s)" = "Darwin" ]; then
  command -v sandbox-exec >/dev/null 2>&1 || die "qwen requires a sandbox: sandbox-exec not found"
  QWEN_SANDBOX="sandbox-exec"
  # The DEFAULT profile is permissive-open (writes broad, network open). Never inherit it.
  if [ "$NETWORK" = "true" ]; then SEATBELT_PROFILE="restrictive-open"
  else SEATBELT_PROFILE="restrictive-closed"; fi
elif command -v docker >/dev/null 2>&1; then
  QWEN_SANDBOX="docker"
  # SEATBELT_PROFILE has NO effect on the container path. Network denial is a container flag.
  [ "$NETWORK" = "true" ] || SANDBOX_FLAGS="--network=none"
elif command -v podman >/dev/null 2>&1; then
  QWEN_SANDBOX="podman"
  [ "$NETWORK" = "true" ] || SANDBOX_FLAGS="--network=none"
else
  die "qwen requires a sandbox provider: none of sandbox-exec, docker, podman found"
fi
# A pre-existing SANDBOX value makes Qwen Code believe it is ALREADY contained and skip
# sandboxing silently. It cannot be defended by pre-setting it — setting it IS the disable —
# so it is excluded from the allow-list above and asserted absent here.
[ -z "${SANDBOX:-}" ] || die "SANDBOX is set in the environment; qwen would skip sandboxing"
```

4. **Ancestor `.env` preflight.** Qwen Code's `.env` discovery walks **upward** from cwd, so checking only inside the worktree is insufficient — and because `QWEN_SANDBOX` outranks the flag, a planted ancestor `.env` could silently disable the sandbox:

```bash
# Walk from the worktree to the filesystem root. Cheap (a handful of `test -f`), and it never
# fires on a clean run: `git worktree add` materialises TRACKED files only. It exists for the
# tracked-secret case and for a resumed worktree a previous job wrote into. DO NOT "optimise"
# this away as dead code.
_scan="$WT"
while [ -n "$_scan" ] && [ "$_scan" != "/" ]; do
  for _f in "$_scan/.env" "$_scan/.qwen/.env" "$_scan/.qwen/settings.json" "$_scan/.qwen/QWEN.local.md"; do
    [ -e "$_f" ] && die "qwen config file present in the search path: $_f"
  done
  _scan="$(dirname "$_scan")"
done
```

5. **The pinned invocation** — note the subshell `cd` (Qwen Code has **no** `--cd`/`--dir` flag; `--include-directories` adds read scope, it does not change cwd):

```bash
( cd "$WT" && \
  env -i PATH="$PATH" TMPDIR="$TMPDIR" LANG="${LANG:-}" \
      HOME="$SCRATCH" QWEN_HOME="$SCRATCH" \
      BAILIAN_CODING_PLAN_API_KEY="$BAILIAN_CODING_PLAN_API_KEY" \
      OPENAI_BASE_URL="$OPENAI_BASE_URL" \
      QWEN_SANDBOX="$QWEN_SANDBOX" \
      ${SEATBELT_PROFILE:+SEATBELT_PROFILE="$SEATBELT_PROFILE"} \
      ${SANDBOX_FLAGS:+SANDBOX_FLAGS="$SANDBOX_FLAGS"} \
    python3 "$SUPERVISOR" --timeout "$TIMEOUT_SEC" --grace 3 --env-only "$ENV_ONLY_NAMES" -- \
      qwen --model "$MODEL" \
           --approval-mode=yolo \
           --auth-type openai \
           --output-format json \
           --session-id "$SESSION_ID" \
           --safe-mode \
           --max-subagent-depth 1 \
           --max-session-turns "$MAX_TURNS" \
           "$(cat "$PROMPT_FILE")" </dev/null >"$EVENTS_LOG" 2>"$STDERR_LOG" )
```

`SESSION_ID` is generated by the caller (`SESSION_ID="$(uuidgen)"`) — Qwen Code lets the caller *assign* the id, which is strictly better than scraping and regex-validating it. `MAX_TURNS` defaults to a documented constant in the script (quota is counted in **requests**, so turn count is what costs).

6. **Model-identity assertion — read the envelope, never model output.**

```bash
# The served model comes from the transport's own session_start event. NEVER from
# --json-schema/structured_output: that content is authored by the model, and a model cannot
# authenticate its own identity — a substituted model would simply assert the expected name.
SERVED_MODEL="$(jq -r '[.[] | select(.type=="system" and .subtype=="session_start") | .model] | if length==1 then .[0] else empty end' "$EVENTS_LOG" 2>/dev/null || true)"
[ -n "$SERVED_MODEL" ] || die "no unique session_start.model in the response — failing closed"
[ "$SERVED_MODEL" = "$MODEL" ] || die "served model '$SERVED_MODEL' != requested '$MODEL'"
```

7. **Containment proof.** After the run, assert the child actually reported a non-empty `SANDBOX` (the variable the sandbox transport sets on itself once active). If engagement cannot be proven, fail the job — a mandatory sandbox that silently no-ops is worse than an honest optional one, because the trust tier is claimed on it.

8. **A pinned settings file in the scratch `QWEN_HOME`, never in the worktree.** Write `$SCRATCH/.qwen/settings.json` before launch, setting **`security.folderTrust.enabled` explicitly** rather than inheriting the documented-off default:

```bash
mkdir -p "$SCRATCH/.qwen"
cat > "$SCRATCH/.qwen/settings.json" <<'SETTINGS'
{ "security": { "folderTrust": { "enabled": true } } }
SETTINGS
```

This file MUST live under `$SCRATCH` (the redirected `QWEN_HOME`), **never inside `$WT`** — a project-scoped `.qwen/settings.json` sits inside the worktree and would dirty the worker's own diff, tripping the scope gate on a job that changed nothing on purpose. Do not replicate the opencode worker's in-worktree config pin and its 70 lines of symlink guards; redirecting `QWEN_HOME` removes that whole hazard class.

9. **`--effort` accepted, validated, explicitly discarded.** Reject `xhigh` with the codex-only message; then write `: "$EFFORT"` with a comment saying the discard is deliberate. Qwen Code has **no** headless effort flag — the only surface is `model.reasoningEffort` in settings.json, and Qwen applies its own per-provider clamp on top, so an effort value is advisory twice over. Document it as **Compound V policy, not a Qwen limitation**: Qwen supports `xhigh` and `max` natively.

- [ ] **Step 1: Write the stub test first**

Create `scripts/test-qwen-worker-stub.sh`, modeled on `scripts/test-zai-worker-stub.sh` (242 lines). **It injects a fake `qwen` first on PATH and ALWAYS runs — it must NOT carry a `command -v qwen` skip guard.** That distinction is the whole point: `test-zai-worker-stub.sh` has no such guard (it proves the *worker*, using a fake binary), while only `test-zai-wire-smoke.sh` skips without the real CLI. A stub test that skips when `qwen` is missing would be disabled precisely in CI, leaving credential scrubbing, argv, timeout, scope gate, and the model assertion untested while reporting green.

Stub modes to cover — six, mirroring zai's five plus the ancestor-`.env` regression:

```bash
make_stub() {
  # $1 = mode (success|blocked|hang|wrongmodel|crash), $2 = served model name
  cat > "$STUBDIR/qwen" <<STUB
#!/usr/bin/env bash
set -eu
: > "$ARGV_OUT"
for a in "\$@"; do printf '%s\n' "\$a" >> "$ARGV_OUT"; done
env > "$ENV_OUT"
printf '%s\n' "\$PWD" > "$CWD_OUT"
case "$1" in
  hang)       sleep 30 ;;
  blocked)    printf 'stray\n' > ./NOT_ALLOWED.txt ;;
  success)    printf 'ok\n' > ./allowed.txt ;;
  wrongmodel) : ;;
  crash)      echo 'boom' >&2; exit 3 ;;
esac
printf '%s\n' '[{"type":"system","subtype":"session_start","session_id":"11111111-2222-3333-4444-555555555555","model":"$2"},{"type":"result","subtype":"success","is_error":false,"result":"done","usage":{"input_tokens":11,"output_tokens":7}}]'
STUB
  chmod +x "$STUBDIR/qwen"
}
```

Assertions the test must make:

```
1. success           -> status "success", blocked false, files_changed == ["allowed.txt"]
2. blocked           -> status "blocked", blocked true, "NOT_ALLOWED.txt" in violations, NOT merged
3. hang              -> status "timeout", exit 124 from the supervisor
4. crash             -> status "error", non-null failure_class
5. wrongmodel        -> job FAILS (served model != requested), not a silent success
6. argv              -> contains --model, --approval-mode=yolo, --auth-type, --safe-mode,
                        --max-subagent-depth, --session-id, --output-format json;
                        contains NONE of: -p, --prompt, --yolo, --allowed-tools, --worktree,
                        --sandbox, --openai-api-key, --insecure
7. env               -> exactly the allow-listed names reach the child; an ambient
                        OPENAI_API_KEY / QWEN_SANDBOX planted by the test does NOT reach it;
                        HOME and QWEN_HOME both point inside $ART, not at the real home
8. cwd               -> the child ran inside $WT, not the launcher's cwd
9. ancestor .env     -> planting a .env one directory ABOVE $WT makes the worker refuse to start
10. no sandbox       -> with PATH stripped of sandbox-exec/docker/podman, the worker refuses
                        rather than running unconfined
11. settings         -> $SCRATCH/.qwen/settings.json exists and sets folderTrust.enabled;
                        NO .qwen/settings.json was created inside $WT (the diff stays clean)
12. ambient SANDBOX  -> with SANDBOX set in the launcher's environment, the worker refuses
                        (it cannot be defended by pre-setting — setting it IS the disable)
```

- [ ] **Step 2: Run the stub test to verify it fails**

Run: `bash scripts/test-qwen-worker-stub.sh`
Expected: FAIL — `scripts/compound-v-run-qwen-worker.sh` does not exist yet.

- [ ] **Step 3: Write the worker script**

Implement `scripts/compound-v-run-qwen-worker.sh` per the deltas above. Make it executable: `chmod +x scripts/compound-v-run-qwen-worker.sh`.

- [ ] **Step 4: Run the stub test to verify it passes**

```bash
bash scripts/test-qwen-worker-stub.sh
shellcheck scripts/compound-v-run-qwen-worker.sh scripts/test-qwen-worker-stub.sh
```

Expected: all stub assertions pass; shellcheck clean.

- [ ] **Step 5: Write the wire-smoke test**

Create `scripts/test-qwen-wire-smoke.sh`, modeled on `scripts/test-zai-wire-smoke.sh`. **This is the only qwen test that skips:**

```bash
command -v qwen >/dev/null 2>&1 || { echo "SKIP: qwen not on PATH"; exit 0; }
```

It exists for the defect class a stub cannot reach: how the **real binary interprets** the argv. That class is not hypothetical here — a docs-only reading of `--sandbox` produced a wrong configuration in this spec's own first draft, and `--allowed-tools` means the opposite of what its name suggests. Against a local stub HTTP endpoint (no network, no key), assert that the request carries the expected model and that the tool set is the restricted one.

- [ ] **Step 6: Verify both tests behave correctly under CI conditions**

```bash
bash scripts/test-qwen-worker-stub.sh          # must RUN and pass (never SKIP)
bash scripts/test-qwen-wire-smoke.sh           # must SKIP cleanly (exit 0) with no qwen binary
echo "wire-smoke exit: $?"
shellcheck scripts/*.sh
```

Expected: stub runs green; wire-smoke prints `SKIP` and exits 0; shellcheck clean across all shell scripts.

- [ ] **Step 7: Commit**

```bash
git add scripts/compound-v-run-qwen-worker.sh scripts/test-qwen-worker-stub.sh scripts/test-qwen-wire-smoke.sh
git commit -m "feat(qwen): add the headless worker with a sandbox-mandatory invocation"
```

---

### Task 3: Failure classification and reroute policy

**Files:**
- Modify: `scripts/compound-v-classify-failure.py` (`_QWEN_RULES`, `classify()` branch, `CONCRETE_BACKENDS`, selftest)
- Modify: `scripts/compound-v-failure-policy.py` (`FALLBACK`, `CONCRETE_BACKENDS`, selftest)

**Interfaces:**
- Consumes: `"qwen"` as a legal backend name (Task 0).
- Produces: `classify(backend="qwen", ...)` returning a class from the existing taxonomy; `FALLBACK["qwen"] == "claude"`.

**Why a branch is mandatory even though the needle set is small:** `classify()`'s final `else` is `_CODEX_RULES`. Without an explicit `qwen` branch, a Qwen auth failure is matched by codex's needles and the operator is told to run **`codex login`** to fix an Alibaba key. That is not a neutral gap — it is a wrong answer. The `zai` selftest already pins this exact trap.

**Why no retry-policy change:** `PER_CLASS_MAX` is global on this base and PR #7's existing throttle-vs-window handling is already correct for this provider. A `rate_limited` classification reaches the retry path; a `usage_window_exhausted` one reaches the cooldown path. That split is the whole behavior, and it comes from the needles below — not from a new policy branch.

- [ ] **Step 1: Write the failing selftest cases**

In `scripts/compound-v-classify-failure.py`'s selftest table, add beside the zai cases:

```python
        ("qwen", 0, "", "none"),
        ("qwen", 124, "", "timeout"),
        # DashScope returns message: null — key on errorType, never on message text.
        ("qwen", 1, '{"errorType":"THROTTLING.userQPSLimit","rid":"x","message":null,"status":429}',
         "rate_limited"),
        ("qwen", 1, "concurrency allocated quota exceeded", "rate_limited"),
        # A WINDOW that reopens by itself — not a spent balance. The Coding Plan has no
        # pay-as-you-go, so the correct response is a cooldown, not out_of_credits.
        ("qwen", 1, "hour allocated quota exceeded", "usage_window_exhausted"),
        ("qwen", 1, "week allocated quota exceeded", "usage_window_exhausted"),
        ("qwen", 1, "month allocated quota exceeded", "usage_window_exhausted"),
        ("qwen", 1, "invalid access token or token expired", "auth"),
        # Native, documented exit codes — no error-text parsing needed.
        ("qwen", 53, "", "other"),
        ("qwen", 55, "", "other"),
        # THE REGRESSION GUARD: without an explicit qwen branch the final `else` is
        # _CODEX_RULES and this would classify as `auth` with "run codex login" advice.
        ("qwen", 1, "not logged in, please run `codex login`", "other"),
```

In `scripts/compound-v-failure-policy.py`'s selftest, add:

```python
    d = decide(backend="qwen", failure_class="usage_window_exhausted", attempt=1)
    check("qwen window exhaustion cools down rather than halting the run",
          d["action"] != "halt", "yes")
    d = decide(backend="qwen", failure_class="out_of_credits", attempt=1)
    check("qwen reroutes UP to claude on a credit wall", d["reroute_to"], "claude")
```

- [ ] **Step 2: Run both selftests to verify they fail**

```bash
python3 scripts/compound-v-classify-failure.py --selftest
python3 scripts/compound-v-failure-policy.py --selftest
```

Expected: FAIL — no `qwen` branch, and `FALLBACK["qwen"]` is missing (which `decide()` reads as "nowhere to reroute" and turns into `halt`).

- [ ] **Step 3: Add the qwen rules and branch**

Insert `_QWEN_RULES` after `_ZAI_RULES`:

```python
# Alibaba Bailian Coding Plan (backend `qwen`), via the Qwen Code CLI.
#
# CRITICAL SHAPE FACT: DashScope returns {"errorType": "...", "rid": "...", "message": null,
# "status": 429} — `message` is NULL. A classifier keyed on message text (the way _ZAI_RULES
# is) matches NOTHING here. Key on errorType and on the quota-window phrases instead.
#
# The hour/week/month phrases are usage_window_exhausted, NOT out_of_credits: this plan has no
# pay-as-you-go fallback, so an exhausted window reopens on its own and the run should cool
# down rather than treat the balance as spent.
_QWEN_RULES = (
    ("auth", [
        "invalid access token", "token expired", "invalid api-key", "401",
    ]),
    ("usage_window_exhausted", [
        "hour allocated quota exceeded",
        "week allocated quota exceeded",
        "month allocated quota exceeded",
    ]),
    ("rate_limited", [
        "throttling.userqpslimit",
        "concurrency allocated quota exceeded",
        "429",
    ]),
    ("overloaded", ["503", "529"]),
)
```

Then add the branch in `classify()`, before the `else`:

```python
    elif backend == "qwen":
        rules = _QWEN_RULES
```

And extend both `CONCRETE_BACKENDS` tuples (in `compound-v-classify-failure.py` and `compound-v-failure-policy.py`) plus the argparse `--backend` choices with `"qwen"`.

- [ ] **Step 4: Add the FALLBACK entry**

```python
FALLBACK = {"codex": "claude", "antigravity": "claude", "cursor": "claude",
            "zai": "claude", "qwen": "claude", "claude": None}
```

A missing key yields `None`, which `decide()` turns into `halt` — stopping the whole run on the first quota wall. This entry is load-bearing, not politeness.

- [ ] **Step 5: Run both selftests to verify they pass**

```bash
python3 scripts/compound-v-classify-failure.py --selftest
python3 scripts/compound-v-failure-policy.py --selftest
```

Expected: PASS, including the `codex login` regression guard.

- [ ] **Step 6: Commit**

```bash
git add scripts/compound-v-classify-failure.py scripts/compound-v-failure-policy.py
git commit -m "feat(qwen): classify DashScope failures and reroute on a quota wall"
```

---

### Task 4: Usage extraction

**Files:**
- Modify: `scripts/compound-v-usage-extract.py` (`_extract_qwen`, `extract_usage` branch, selftest)

**Interfaces:**
- Consumes: `"qwen"` as a legal backend name (Task 0).
- Produces: `extract_usage("qwen", events_log)` returning the standard usage dict with `measured: True` on a real run.

**Why this is not a copy of an existing extractor:** qwen's `--output-format json` emits a **buffered array** of message objects. That is a third shape — codex emits JSONL, zai emits one JSON document. Read the whole file as one JSON array and take the terminal `result` element's `usage`.

- [ ] **Step 1: Write the failing selftest**

```python
    # --- qwen: a buffered JSON ARRAY (not JSONL, not a single object) ---
    qwen_path = _write_tmp([
        '[{"type":"system","subtype":"session_start","session_id":"a","model":"qwen3-coder-plus"},',
        ' {"type":"assistant","message":{"usage":{"input_tokens":100,"output_tokens":40}}},',
        ' {"type":"result","subtype":"success","is_error":false,"result":"done",',
        '  "usage":{"input_tokens":412,"output_tokens":96}}]',
    ])
    qwen_got = extract_usage("qwen", qwen_path)
    check("qwen input tokens come from the terminal result", qwen_got["input_tokens"], 412)
    check("qwen output tokens come from the terminal result", qwen_got["output_tokens"], 96)
    check("qwen is measured", qwen_got["measured"], True)
    check("qwen backend label", qwen_got["backend"], "qwen")
    check("qwen carries no cost anywhere", "cost" in json.dumps(qwen_got).lower(), False)
    os.unlink(qwen_path)

    # anti-ruflo: a failed job with a well-formed but EMPTY usage object must be unmeasured,
    # never a fabricated 0. This is the a091185 bug class, already fixed once for zai.
    qwen_failed = _write_tmp([
        '[{"type":"result","subtype":"error","is_error":true,"usage":{}}]',
    ])
    qwen_failed_got = extract_usage("qwen", qwen_failed)
    check("qwen failed job is unmeasured despite a well-formed usage object",
          qwen_failed_got["measured"], False)
    check("qwen failed job input_tokens stays null (not a fabricated 0)",
          qwen_failed_got["input_tokens"], None)
    os.unlink(qwen_failed)

    check("qwen missing file is unmeasured", extract_usage("qwen", None)["measured"], False)
```

- [ ] **Step 2: Run the selftest to verify it fails**

Run: `python3 scripts/compound-v-usage-extract.py --selftest`
Expected: FAIL — unknown backend falls through to `_unmeasured("qwen")`, so `measured` is `False` where `True` is asserted.

- [ ] **Step 3: Write the extractor**

```python
def _extract_qwen(objs: List[Any], backend: str) -> Dict[str, Any]:
    """qwen runs `qwen --output-format json`, which buffers an ARRAY of message objects and
    emits it once at the end -- a third shape, distinct from codex's JSONL and zai's single
    document. Usage lives on the terminal `result` element.

    An empty-but-well-formed usage object yields measured=False with null counts, never a
    fabricated 0 (the anti-ruflo rule; the same trap already fixed once for zai)."""
    inp = out = None
    for obj in objs if isinstance(objs, list) else []:
        if not isinstance(obj, dict) or obj.get("type") != "result":
            continue
        usage = obj.get("usage")
        if isinstance(usage, dict):
            i, o = usage.get("input_tokens"), usage.get("output_tokens")
            if isinstance(i, int) or isinstance(o, int):
                inp, out = i, o
    if inp is None and out is None:
        return _unmeasured(backend)
    return {"input_tokens": inp, "output_tokens": out,
            "advisor_calls": 0, "backend": backend, "measured": True}
```

Then add the dispatch branch beside the others in `extract_usage`:

```python
    if backend == "qwen":
        # qwen's capture is a buffered JSON ARRAY, not JSONL — parse it as one document.
        return _extract_qwen(_read_json_document(events_log), backend)
```

- [ ] **Step 4: Run the selftest to verify it passes**

Run: `python3 scripts/compound-v-usage-extract.py --selftest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/compound-v-usage-extract.py
git commit -m "feat(qwen): extract real usage from the buffered JSON array"
```

---

### Task 5: Manifest validation gates

**Files:**
- Modify: `scripts/compound-v-validate-manifest.py` (`VALID_BACKENDS`, worktree tuple, reviewer block tuple, `_qwen_optin_problems`, fixtures, selftest)

**Interfaces:**
- Consumes: `resolve("qwen", tier)` from Task 0 (the validator loads the resolver by path).
- Produces: three enforced invariants — `qwen ⇒ worktree`, `qwen ⇒ never a reviewer`, `qwen ⇒ opt-in acknowledged`.

**Why Opus:** these are security boundaries. The reviewer gate is what keeps the Review Gate's Opus guarantee honest, and the opt-in gate is the only thing standing between a hand-authored manifest and an operator's subscription.

**The correction this task exists to make:** an earlier draft of the spec claimed the existing CR5-5 gate "already covers `qwen` generically." **It does not.** CR5-5 (`_is_claude_opus`) only inspects `fast_path.review` declarations and sealed receipts; a normal manifest's reviewer job never reaches it. Invariant 3 is satisfied by `tier: deep` alone. So the only unconditional protection is the explicit backend-name block list — which currently reads `("devin", "opencode", "zai")`. Without adding `qwen`, `backend: qwen, type: spec_review, tier: deep` **validates cleanly today.**

- [ ] **Step 1: Write the failing fixtures and assertions**

Add fixtures beside the existing `ZAI_*` ones, mirroring their exact idiom — a full, otherwise-valid manifest with **one** defect, then `.replace()`-derived variants. There is no `_fails_with` helper in this file; the real idiom is `validate_text(FIXTURE)` returning a list of problem strings, asserted with `expect(name, any(...))`.

```python
# A complete, otherwise-valid manifest whose ONE defect is a qwen job with isolation: direct.
# qwen REQUIRES a worktree like every other external worker.
QWEN_DIRECT_MANIFEST = """
run_id: 2026-08-04-qwen
feature: "qwen"
spec_path: docs/superpowers/specs/2026-08-04-qwen.md
plan_path: docs/superpowers/plans/2026-08-04-qwen.md
audits:
  archaeology: docs/superpowers/archaeology/2026-08-04-qwen.md
  domain: docs/superpowers/expert/2026-08-04-qwen.md
  library: docs/superpowers/library-audit/2026-08-04-qwen.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-qwen
    title: "qwen slice"
    type: implementer
    backend: qwen
    tier: standard
    isolation: direct
    run: serial
    write_allowed: [src/qwen/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""

# The same manifest with the ONE defect fixed. qwen is SINGLE-VENDOR: a bare catalog name,
# never a "provider/model" string.
QWEN_WORKTREE_MANIFEST = QWEN_DIRECT_MANIFEST.replace(
    "isolation: direct", "isolation: worktree"
).replace("run_id: 2026-08-04-qwen", "run_id: 2026-08-04-qwen-ok")

# WORKER-ONLY: the ONE defect is a REVIEWER job routed to qwen. Note this is caught by the
# explicit backend-name block list, NOT by CR5-5 (which only inspects fast_path.review and
# sealed receipts) and NOT by invariant 3 (which `tier: deep` alone satisfies).
QWEN_REVIEWER_MANIFEST = QWEN_WORKTREE_MANIFEST.replace(
    "id: task-1-qwen", "id: task-1-spec-review"
).replace("type: implementer", "type: reviewer").replace("tier: standard", "tier: deep")
```

And the assertions, in the same style as the `zai` block:

```python
    qwen_bad = validate_text(QWEN_DIRECT_MANIFEST)
    expect(
        "qwen+direct caught (qwen requires worktree)",
        any("backend qwen but isolation" in p
            and "qwen requires worktree" in p for p in qwen_bad),
    )
    qwen_reviewer_bad = validate_text(QWEN_REVIEWER_MANIFEST)
    expect(
        "qwen reviewer job REJECTED (WORKER-ONLY, via the backend-name block)",
        any("reviewer job 'task-1-spec-review'" in p
            and "backend 'qwen'" in p
            and "WORKER-ONLY" in p for p in qwen_reviewer_bad),
    )
```

The opt-in gate needs a `repo_root`/`config_path` to read, so it is asserted through the same path the existing config-dependent checks use rather than through bare `validate_text`. Add a case that writes a temporary `.claude/compound-v.json` **without** `qwen_optin` and asserts the manifest is rejected, and a second with a matching `terms_version` asserting `QWEN_WORKTREE_MANIFEST` validates clean:

```python
    expect(
        "a qwen job without the operator opt-in is rejected",
        any("opt-in is absent or stale" in p
            for p in _validate_with_config(QWEN_WORKTREE_MANIFEST, {})),
    )
    expect(
        "a qwen job WITH a current opt-in validates",
        _validate_with_config(
            QWEN_WORKTREE_MANIFEST,
            {"qwen_optin": {"terms_version": QWEN_TERMS_VERSION}}) == [],
    )
```

Write `_validate_with_config(text, cfg)` as a small selftest helper that materialises `cfg` into a temp `.claude/compound-v.json` under a temp repo root and calls the validator with that `--repo-root`, then cleans up.

- [ ] **Step 2: Run the selftest to verify it fails**

Run: `python3 scripts/compound-v-validate-manifest.py --selftest`
Expected: FAIL — all three manifests currently validate cleanly.

- [ ] **Step 3: Register the backend and extend the two tuples**

```python
VALID_BACKENDS = ("claude", "codex", "antigravity", "cursor", "devin", "opencode", "zai", "qwen")
```

Worktree invariant:

```python
        if backend_lc in ("codex", "antigravity", "cursor", "devin", "opencode", "zai", "qwen"):
```

Reviewer block list — extend the tuple **and** widen the message so it names the right adapter:

```python
        if _is_reviewer(job) and backend_lc in ("devin", "opencode", "zai", "qwen"):
            problems.append(
                "reviewer job '%s' uses backend '%s' — devin/opencode/zai/qwen are "
                "lower-trust, opt-in, WORKER-ONLY backends (see "
                "adapter-devin.md / adapter-opencode.md / adapter-zai.md / "
                "adapter-qwen.md) and must never be used for a reviewer job; route "
                "reviewers to backend: claude with tier: deep or model: opus"
                % (jid, backend_lc)
            )
```

- [ ] **Step 4: Add the opt-in gate**

Mirror `_backend_max_parallel_problems`'s shape exactly — same sibling-loading idiom, same fail-closed posture:

```python
def _qwen_optin_problems(repo_root, config_path, manifest):
    """`qwen` dispatch requires an operator-local, uncommitted acknowledgment that the
    operator read Alibaba's Coding Plan terms (which arguably prohibit exactly this use --
    see skills/backend-launcher/adapter-qwen.md) and accepts the account-suspension risk.

    Enforced HERE, at the one hard gate the whole pipeline funnels through, because prose in
    /v:init cannot stop a hand-authored manifest and the dispatcher runs whatever backend a
    manifest names. The record carries an acknowledgment and a terms-version marker only --
    NEVER the API key, which stays in the environment.
    """
    if not any(str(j.get("backend", "")).lower() == "qwen"
               for j in (manifest.get("jobs") or [])):
        return []
    pc = _sibling("compound-v-project-config.py")
    if pc is None:
        return ["cannot load project-config sibling API for the qwen opt-in — fail-closed"]
    cfg_path = config_path
    if cfg_path is None and repo_root is not None:
        cfg_path = os.path.join(repo_root, ".claude", "compound-v.json")
    try:
        cfg = pc.load_project_config_path(cfg_path)
    except Exception as e:  # noqa: BLE001 - an unreadable opt-in record must fail closed
        return ["qwen opt-in record is unreadable (%s) — fail-closed" % e]
    ack = (cfg or {}).get("qwen_optin")
    if not isinstance(ack, dict) or ack.get("terms_version") != QWEN_TERMS_VERSION:
        return ["manifest dispatches backend: qwen but the operator opt-in is absent or "
                "stale — set .claude/compound-v.json qwen_optin.terms_version to '%s' "
                "after reading skills/backend-launcher/adapter-qwen.md (account-suspension "
                "risk); the record must NEVER contain the API key"
                % QWEN_TERMS_VERSION]
    return []
```

Define the marker near the other module constants:

```python
# Bump when adapter-qwen.md's Compliance section changes materially — a stale
# acknowledgment must not silently keep authorising dispatch.
QWEN_TERMS_VERSION = "2026-08-04"
```

Call it beside the existing per-config sweep:

```python
    problems.extend(_qwen_optin_problems(repo_root, config_path, manifest))
```

- [ ] **Step 5: Run the selftest to verify it passes**

Run: `python3 scripts/compound-v-validate-manifest.py --selftest`
Expected: PASS — including a fixture where the acknowledgment IS present and a `qwen` job validates.

- [ ] **Step 6: Verify no historical manifest regressed**

```bash
python3 scripts/compound-v-validate-manifest.py examples/manifest.example.yaml
for m in docs/superpowers/execution/*/manifest.yaml; do
  [ -f "$m" ] && python3 scripts/compound-v-validate-manifest.py "$m" >/dev/null \
    && echo "ok $m" || echo "FAIL $m"
done
```

Expected: every existing manifest still validates (none of them names `qwen`, so the opt-in gate must not fire).

- [ ] **Step 7: Commit**

```bash
git add scripts/compound-v-validate-manifest.py
git commit -m "feat(qwen): enforce worktree, worker-only, and operator opt-in at validation"
```

---

### Task 6: Pool registration and the sandbox availability gate

**Files:**
- Modify: `scripts/compound-v-pool-state.py` (`VALID_CONCRETE_BACKENDS`, `backend_available()`, selftest)

**Interfaces:**
- Consumes: `"qwen"` as a legal backend name (Task 0).
- Produces: `backend_available("qwen", env, which, platform)` → `False` unless the key **and** a sandbox provider are present.

**Why Opus:** this function is what makes "the sandbox is mandatory" true at *routing* time. Today it special-cases exactly two backends and returns `True` for everything else — so letting `qwen` fall through to that default would freeze a qwen slot into a pool on a machine that cannot sandbox it, and the mandatory-sandbox claim would have no enforcement anywhere except the worker's own refusal.

**What the freeze actually does** (verified, and it corrects an earlier draft's fear): `freeze_pool_members()` calls `backend_available()` once per member and records `available: false`, then the run **continues with a surfaced warning** — pools degrade, they do not fail. That is exactly why implementing this function correctly is the load-bearing task, and why qwen can safely join the default pool.

- [ ] **Step 1: Write the failing selftest**

```python
    expect("qwen needs BOTH the key and a sandbox provider",
           backend_available("qwen", env={}, which=lambda b: "/usr/bin/" + b,
                             platform="darwin") is False)
    expect("qwen with a key but no sandbox provider is unavailable",
           backend_available("qwen",
                             env={"BAILIAN_CODING_PLAN_API_KEY": "sk-sp-x"},
                             which=lambda b: None, platform="darwin") is False)
    expect("qwen on macOS with sandbox-exec is available",
           backend_available("qwen",
                             env={"BAILIAN_CODING_PLAN_API_KEY": "sk-sp-x"},
                             which=lambda b: "/usr/bin/sandbox-exec" if b == "sandbox-exec" else None,
                             platform="darwin") is True)
    expect("qwen on linux with docker is available",
           backend_available("qwen",
                             env={"BAILIAN_CODING_PLAN_API_KEY": "sk-sp-x"},
                             which=lambda b: "/usr/bin/docker" if b == "docker" else None,
                             platform="linux") is True)
    expect("an unavailable qwen pool member degrades the pool instead of failing the run",
           "available" in json.dumps(freeze_pool_members(
               {}, {"balanced": {"light": [{"backend": "codex", "model": "a"},
                                           {"backend": "qwen", "model": "qwen3-coder-plus"}]}},
               "balanced", {}, env={}, which=lambda b: None)))
```

- [ ] **Step 2: Run the selftest to verify it fails**

Run: `python3 scripts/compound-v-pool-state.py --selftest`
Expected: FAIL — `backend_available("qwen", ...)` currently returns `True` via the fall-through, and the signature has no `platform` parameter.

- [ ] **Step 3: Extend the tuple and the availability probe**

```python
VALID_CONCRETE_BACKENDS = (
    "claude", "codex", "antigravity", "cursor", "devin", "opencode", "zai", "qwen",
)
```

```python
def backend_available(backend, env=None, which=None, platform=None):
    """Evaluate the narrow documented pool precondition for one backend."""
    environment = os.environ if env is None else env
    find_binary = shutil.which if which is None else which
    plat = sys.platform if platform is None else platform
    if backend == "codex":
        return bool(find_binary("codex"))
    if backend == "zai":
        return bool(environment.get("ZAI_API_KEY"))
    if backend == "qwen":
        # qwen is the ONLY backend whose trust tier is claimed on a kernel sandbox, so the
        # precondition is the key AND a working sandbox provider. Falling through to the
        # `return True` default below would freeze a qwen slot onto a machine that cannot
        # sandbox it, leaving "the sandbox is mandatory" unenforced at routing time.
        if not environment.get("BAILIAN_CODING_PLAN_API_KEY"):
            return False
        if plat == "darwin":
            return bool(find_binary("sandbox-exec"))
        return bool(find_binary("docker") or find_binary("podman"))
    return True
```

Add `import sys` if it is not already imported.

- [ ] **Step 4: Run the selftest to verify it passes**

Run: `python3 scripts/compound-v-pool-state.py --selftest`
Expected: PASS, including the existing zai and codex availability assertions (the new `platform` parameter is keyword-with-default, so every existing caller is unaffected).

- [ ] **Step 5: Commit**

```bash
git add scripts/compound-v-pool-state.py
git commit -m "feat(qwen): gate pool availability on the key and a working sandbox provider"
```

---

### Task 7: Documentation, routing surface, and default pool policy

**Files:**
- Modify: `skills/backend-launcher/SKILL.md` (adapter table row, backend list in the `job_spec` comment, frontmatter description)
- Modify: `skills/compound-v/routing-policy.md` (backend list, worktree rule, the `qwen` entry beside zai's)
- Modify: `skills/compound-v/execution-manifest.md` (`backend` enum, tier-map shape, config `pools` example, `backend_max_parallel` example, usage backend list)
- Modify: `skills/compound-v/phase-3-parallel-opus-dispatch.md` (backend dispatch list, resolve step)
- Modify: `skills/compound-v/state-machine.md` (backend mentions only — **no circuit-break semantic change**)
- Modify: `agents/parallel-dispatcher.md` (backend table row naming the worker script)
- Modify: `commands/v-init.md` (a qwen capability probe section, config `models` example, capability record)
- Modify: `commands/v-models.md` (frontmatter description, backend arg list, a qwen discovery section)
- Modify: `commands/v-status.md` (unmeasured-backend list — only if qwen ships unmeasured; after Task 4 it does not, so verify before editing)

**Interfaces:**
- Consumes: `skills/backend-launcher/adapter-qwen.md` (Task 1) — **this task must not run before Task 1 exists**, or the dead-link CI gate fails.

- [ ] **Step 1: Add the adapter table row in `SKILL.md`**

```markdown
| `adapter-qwen.md` | headless Qwen Code | Bash-spawned `qwen` (own process, own worktree) | `worktree` (mandatory) + **kernel sandbox (mandatory)** | git-diff scope gate | **opt-in, WORKER-ONLY, auth-pending / coverage-unverified** (Alibaba Bailian Coding Plan; the only backend besides codex that requires OS-level confinement — but its ToS arguably prohibits automated use, see the adapter's Compliance section) |
```

- [ ] **Step 2: Seed the default pool and the concurrency ceiling**

In `skills/compound-v/execution-manifest.md`, update the shipped pool policy from "Codex + zai" to include qwen, and document the ceiling:

```jsonc
{
  "pools": {
    "balanced": {
      "light":    [ { "backend": "codex" }, { "backend": "zai" }, { "backend": "qwen" } ],
      "standard": [ { "backend": "codex", "weight": 2 }, { "backend": "zai" }, { "backend": "qwen" } ]
    }
  },
  "backend_max_parallel": { "qwen": 2 }
}
```

State honestly, in the prose beside it, that `backend_max_parallel` is a ceiling **the prose dispatcher respects, not a semaphore** — validation proves the key's shape, not its enforcement — and that `2` is **unmeasured**, chosen because Alibaba's concurrency limit is real, undocumented in magnitude, and dynamically adjusted.

- [ ] **Step 3: Add the `/v:init` capability probe**

The probe must check **three** things, and mark `qwen` **unavailable** (not merely degraded) if any fails:
1. `qwen` on PATH;
2. **Node ≥ 22.0.0** — `qwen` is an npm package with a hard `engines` floor, unlike the standalone `codex`/`cursor-agent` binaries; a Node-20 machine produces a failure that classifies as nothing useful;
3. a working sandbox provider — `sandbox-exec` on macOS, `docker` or `podman` on Linux — because the sandbox is mandatory and `backend_available()` (Task 6) will refuse the backend without one.

Record `BAILIAN_CODING_PLAN_API_KEY` presence and the endpoint choice (international `coding-intl.dashscope.aliyuncs.com` vs China `coding.dashscope.aliyuncs.com`) as an explicit config field — a region mismatch returns a 401 that does not identify itself as a region error.

- [ ] **Step 4: Update the remaining enumerations**

Add `qwen` to every backend list in the remaining files. Use this to find them all — `zai` was the previous last-added backend, so every site naming it needs `qwen` too:

```bash
grep -n 'zai' skills/compound-v/routing-policy.md skills/compound-v/execution-manifest.md \
              skills/compound-v/phase-3-parallel-opus-dispatch.md skills/compound-v/state-machine.md \
              agents/parallel-dispatcher.md commands/v-init.md commands/v-models.md commands/v-status.md
```

For `commands/v-status.md` specifically: `qwen` reports **measured** usage after Task 4, so it must **not** be added to the unmeasured-backend list. Verify with `python3 scripts/compound-v-usage-extract.py --selftest` before editing.

- [ ] **Step 5: Run the dead-link scan and the full selftest sweep**

```bash
# repo-wide dead-link scan, same logic as CI
deadfile="$(mktemp)"
while IFS= read -r -d '' file; do
  dir=$(dirname "$file")
  grep -oE '\]\([^)]+\.(md|py|sh|json|ya?ml)[^)]*\)' "$file" 2>/dev/null \
    | sed 's/^](//;s/)$//' | while IFS= read -r link; do
      path="${link%%#*}"; path="$(printf '%s' "$path" | sed -E 's/:[0-9]+(-[0-9]+)?$//')"
      case "$path" in http*|/docs/*|""|"#"*) continue ;; esac
      [ -f "$dir/$path" ] || { echo "❌ Dead link in $file → $path"; echo x >> "$deadfile"; }
    done
done < <(find . -name "*.md" -not -path "./.git/*" -print0)
[ -s "$deadfile" ] && echo "DEAD LINKS FOUND" || echo "✅ no dead links"
```

Expected: `✅ no dead links`.

- [ ] **Step 6: Commit**

```bash
git add skills/ agents/ commands/
git commit -m "docs(qwen): register the backend across the routing and command surface"
```

---

### Task 8: Version lockstep and changelog

**Files:**
- Modify: `CHANGELOG.md` (new release heading)
- Modify: `.claude-plugin/plugin.json` (`version`)
- Modify: `.claude-plugin/marketplace.json` (`version`)

**Interfaces:**
- Consumes: every prior task's changes (this documents them).

**Atomic — all three in one commit.** Three separate CI steps cross-check that `plugin.json`, `marketplace.json`, and the top numeric `CHANGELOG.md` heading carry the identical version. Bumping one without the others fails the build.

- [ ] **Step 1: Bump both JSON files from `2.18.0` to `2.19.0`**

```bash
jq '.version = "2.19.0"' .claude-plugin/plugin.json > /tmp/p.json && mv /tmp/p.json .claude-plugin/plugin.json
jq '(.plugins[] | select(.name=="superpowers-v") | .version) = "2.19.0"' \
  .claude-plugin/marketplace.json > /tmp/m.json && mv /tmp/m.json .claude-plugin/marketplace.json
```

- [ ] **Step 2: Add the CHANGELOG entry**

Insert a `## [2.19.0]` heading below `## [Unreleased]`, describing: the new `qwen` backend (headless Qwen Code CLI against Alibaba's Bailian Coding Plan); mandatory kernel sandboxing driven by `QWEN_SANDBOX`/`SEATBELT_PROFILE`; worker-only enforcement at validation; the operator opt-in gate and **why it exists** (the Coding Plan's terms arguably prohibit automated use — link the adapter's Compliance section); pool participation with `backend_max_parallel.qwen = 2` labeled unmeasured; and the status **auth-pending / coverage-unverified** pending a live probe.

- [ ] **Step 3: Verify lockstep exactly as CI does**

```bash
pv=$(jq -r '.version' .claude-plugin/plugin.json)
mv=$(jq -r '.plugins[] | select(.name=="superpowers-v") | .version' .claude-plugin/marketplace.json)
cv=$(grep -m1 -oE '^## \[[0-9]+\.[0-9]+\.[0-9]+\]' CHANGELOG.md | tr -d '#[] ')
echo "plugin=$pv marketplace=$mv changelog=$cv"
[ "$pv" = "$mv" ] && [ "$pv" = "$cv" ] && echo "✅ lockstep" || { echo "❌ mismatch"; exit 1; }
```

Expected: `✅ lockstep`.

- [ ] **Step 4: Run the complete gate suite**

```bash
set -e
for f in scripts/*.py; do
  grep -q -- '--selftest' "$f" && { echo "--- $f"; python3 "$f" --selftest >/dev/null; }
done
shellcheck scripts/*.sh hooks/*.sh
for t in scripts/test-*.sh; do echo "--- $t"; bash "$t"; done
jq empty schemas/job_result.schema.json
python3 scripts/compound-v-validate-manifest.py examples/manifest.example.yaml
echo "✅ all gates green"
```

Expected: every selftest passes, shellcheck is clean, every bash test passes (`test-qwen-worker-stub.sh` **runs**; `test-qwen-wire-smoke.sh` **SKIPs**), and the example manifest validates.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md .claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore(qwen): release 2.19.0"
```

---

## Verification Before Completion

Run this before claiming the feature is done. Every line must pass — paste the real output, never a summary.

```bash
cd /Users/yurifediai/Projects/Procoders/compaund-v-qwen
set -e
# 1. every python selftest
for f in scripts/*.py; do grep -q -- '--selftest' "$f" && python3 "$f" --selftest >/dev/null; done
# 2. shell lint + bash suites
shellcheck scripts/*.sh hooks/*.sh
for t in scripts/test-*.sh; do bash "$t"; done
# 3. the qwen-specific invariants
python3 scripts/compound-v-resolve-model.py --backend qwen --tier deep
printf 'week allocated quota exceeded\n' > /tmp/qwen-err.txt
python3 scripts/compound-v-classify-failure.py --backend qwen --exit-code 1 \
  --stderr-file /tmp/qwen-err.txt        # expect usage_window_exhausted (NOT out_of_credits)
# 4. version lockstep + schema
jq empty schemas/job_result.schema.json
# 5. the main repo was never touched
git -C /Users/yurifediai/Projects/Procoders/compaund-v branch --show-current   # expect feat/zai-backend
echo "✅ verified"
```

**Known-unverifiable in this branch, and it must stay stated as such:** no live Coding Plan key exists, so the pinned argv has never met the real binary. `test-qwen-wire-smoke.sh` SKIPs, the adapter's version slot stays an explicit unknown, and the status stays **auth-pending / coverage-unverified**. Do not describe this feature as verified. The live pass — confirming the sandbox precedence, resolving the response-shape question, and checking whether Qwen Code backported the upstream untrusted-folder fix — is required follow-on work.
