# Adapter: zai (headless GLM worker via `claude -p`)

> Read the contract in [`SKILL.md`](SKILL.md) first — this adapter implements that `job_spec → job_result` interface. This file is the backend-specific runbook; the wiring lives in [`scripts/compound-v-run-zai-worker.sh`](../../scripts/compound-v-run-zai-worker.sh).

The zai backend is a **Bash-spawned `claude -p` worker** pointed at z.ai's Anthropic-compatible endpoint — its own process, its own git worktree. It mirrors the Antigravity / Cursor adapters step for step: worktree isolation, a git-derived scope gate, normalize → `job_result`, caller merges.

z.ai ships **no headless CLI of its own** (ZCode is a desktop Electron app). Claude Code is a tier-1 officially supported tool for the GLM Coding Plan, so driving the genuine binary is the compliant path — and the only one available.

Verified live against **claude 2.1.207** on 2026-07-31/08-01, with a real GLM Coding Plan key. Wire-level facts came from a local stub HTTP server standing in for the endpoint, so they cost no quota; they are re-asserted on every run of [`scripts/test-zai-wire-smoke.sh`](../../scripts/test-zai-wire-smoke.sh).

---

## ⚠️ SAFETY — lower-trust, opt-in, WORKER-ONLY (read first)

**No kernel write-confinement.** Unlike codex (`--sandbox workspace-write`), nothing at the OS level stops this worker writing outside its worktree. The worktree plus the `git diff` scope gate **detects** an in-worktree scope leak but cannot **prevent** an out-of-worktree side effect. **Prefer codex for untrusted or high-stakes work**; route to zai when the prompt and surface are trusted.

**WORKER-ONLY.** A `zai` reviewer job is rejected by [`compound-v-validate-manifest.py`](../../scripts/compound-v-validate-manifest.py). A reviewer routed here would satisfy the Review Gate's opus/deep guarantee through a third-party endpoint instead of Claude Opus, defeating it entirely.

**Not an arbiter seat either.** [`compound-v-epic-arbiter.py`](../../scripts/compound-v-epic-arbiter.py) matches model families by substring over `gpt`, `gemini`, `claude`, `opus`, `sonnet`, `grok`. `glm` is absent, so a GLM ballot buckets as `unknown` alongside every other unrecognised model and could be deduped against an unrelated one — a correlated ballot masquerading as an independent vote. Adding the needle is a one-line change plus a test; until it lands, zai stays out of every panel.

**`worktree` is mandatory**, enforced by the manifest validator.

---

## The 6 load-bearing steps

```
1. ISOLATE   git -C <repo> worktree add <WT> HEAD          # clean diff baseline (NO kernel sandbox)
2. RUN       cd <WT> && env -i … claude -p … -- "<prompt>"  # see the pinned invocation
3. ASSERT    the response's modelUsage key is a GLM model, else fail the job
4. OBSERVE   compound-v-scope-check.py --worktree <WT> --baseline <sha> --allow-file <globs>
5. ENFORCE   every changed path ∉ write_allowed ⇒ violation ⇒ blocked  (do NOT merge)
6. MERGE     caller, on PASS only
```

Steps 4–5 are the keystone and must be computed in git, never read from anything the model says it did. The deterministic authority is [`compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py) — the same gate the dispatcher runs after every job. The worker must **not** re-implement glob matching in bash.

**Only `write_allowed` is enforced; `read_allowed` is advisory** — the gate is git-derived, and git tracks writes, not reads.

---

## Worker-prompt planner/executor lock

Every dispatched `prompt` opens with the lock, verbatim-in-spirit:

> You are an implementation worker, NOT the planner. Do not change architecture. Do not write outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report BLOCKED.

That is the *instructed* half; the scope gate is the *enforced* half.

---

## The pinned invocation

```bash
( cd "$WT" && \
python3 scripts/compound-v-run-with-timeout.py --timeout "$timeout_sec" --grace 3 -- \
  env -i PATH="$PATH" TMPDIR="$TMPDIR" LANG="$LANG" \
      HOME="$SCRATCH" CLAUDE_CONFIG_DIR="$SCRATCH/.claude" \
      ANTHROPIC_BASE_URL="https://api.z.ai/api/anthropic" \
      ANTHROPIC_AUTH_TOKEN="$ZAI_API_KEY" \
      ANTHROPIC_MODEL="$model" \
      ANTHROPIC_DEFAULT_OPUS_MODEL="$model" \
      ANTHROPIC_DEFAULT_SONNET_MODEL="$model" \
      ANTHROPIC_DEFAULT_HAIKU_MODEL="$model" \
      API_TIMEOUT_MS="$((timeout_sec * 1000))" \
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    claude -p \
      --permission-mode dontAsk \
      --tools "Read,Edit,Write,Bash" \
      --allowedTools "Read,Edit,Write,Bash" \
      --exclude-dynamic-system-prompt-sections \
      --output-format json \
      -- "$prompt" </dev/null >"$events_log" 2>"$stderr_log" )
```

**Verified facts — load-bearing, do not re-derive:**

- **`--tools` and `--allowedTools` are DIFFERENT THINGS and BOTH are required.** `--tools` decides which built-in tools *exist*; `--allowedTools` decides which run *without asking*. Measured: with only `--allowedTools` the wire carried `Bash, Edit, Read` — no `Write`, and `Bash` present despite being "withheld"; with only `--tools`, `dontAsk` refused the write. `Grep` and `Glob` **do not exist** as tools in this CLI version at all (absent from both the 3-tool bare set and the 53-tool full set) — searching goes through `Bash`.
- **`--` before the prompt is mandatory.** `--tools` and `--allowedTools` are variadic and swallow the positional prompt without it.
- **`--bare` must NOT be used.** In bare mode the built-in set is exactly `Bash, Edit, Read` — `Write` does not exist and `--tools` cannot restore it, so a bare worker cannot create a new file. `HOME`/`CLAUDE_CONFIG_DIR` redirection buys the same isolation while keeping `Write`.
- **`ANTHROPIC_AUTH_TOKEN`, not `ANTHROPIC_API_KEY`.** The former sends `Authorization: Bearer`, the latter sends `x-api-key` with no `Authorization`. Both were observed working against z.ai, but z.ai documents only the Bearer form.
- **All four model slots carry the same GLM model.** `ANTHROPIC_DEFAULT_HAIKU_MODEL` is a Claude Code *slot name*, not a model choice — the plugin's never-Haiku policy is untouched. z.ai's own integration guide sets every slot; an unset small/fast slot sends an Anthropic identifier and earns `400 [1211][Unknown Model]`.
- **`--exclude-dynamic-system-prompt-sections`** moves `cwd`, environment info and `git status` out of the cached system block. Without it the cacheable prefix diverges for every worker by construction, since each runs in a different worktree. With it, the `tools` and `system` blocks are byte-identical across worktrees — asserted by the wire smoke test.
- **`env -i` with a four-name allow-list** is the mandatory credential scrub, the same shape as the opencode worker's (which exists because opencode was observed authenticating from an inherited ambient `ANTHROPIC_BASE_URL`). `HOME` points at a scratch directory, which also puts `~/.claude/.credentials.json` out of reach — a read-only `cat` is available in every permission mode and is not configurable.
- **`claude` has no `--cd`.** The worktree is entered with a subshell `cd`. Without it the worker edits the launcher's cwd while the gate diffs an untouched worktree.
- **stdin `</dev/null` under the process-group supervisor** — the non-negotiable launch rule in `SKILL.md`.

### The GLM assertion

`--bare` would have guaranteed OAuth and keychain are never read; this invocation does not use it, so the guarantee is replaced by a deterministic check: the worker reads the response's `modelUsage` key and **fails the job** unless it names a GLM model. Any silent fall-back to another credential path surfaces as a failed job rather than an unnoticed charge.

---

## Model and effort

Resolved before dispatch by [`compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) `--backend zai --tier <tier>`. zai is **single-vendor**: every model is a bare GLM name, never a `provider/model` string.

```
deep     → glm-5.2
standard → glm-5.2
light    → glm-5-turbo
```

`light` is `glm-5-turbo` on measurement, not on the multiplier table. Three runs each on one task: turbo averaged 8.5 s / 2.56 credits, glm-4.7 10.1 s / 2.38 — turbo is 16% faster and glm-4.7 only 7% cheaper, because glm-4.7 emits ~60% more output and eats its own lower multiplier. Scope discipline was indistinguishable (3/3 clean each). `glm-4.7` remains a config override worth ~32% on the multiplier table for anyone squeezing the weekly window.

Only models with a **published multiplier** are in the default map. The endpoint also accepts `glm-5.1`, `glm-5`, `glm-4.6` and `glm-4.5-air`, but z.ai's Coding Plan documentation lists only three models and publishes no multiplier for the others, so their burn is unpredictable; they are user overrides, documented as unverified.

`effort` is **advisory**. `claude --effort` does exist and accepts `xhigh`, which contradicts this plugin's rule that `xhigh` is codex-only — the rule is followed here (zai accepts `low|medium|high`) and the discrepancy is flagged for the maintainer rather than worked around.

**Quota.** Consumption is `(input × Mi + cached × Mc + output × Mo) / 10 000`; published multipliers are 6.9/1.7/24 (glm-5.2), 5.7/1.5/21 (glm-5-turbo), 4.6/1.2/16 (glm-4.7). Plan windows are 2 000 / 12 000 / 28 000 credits per 5 hours and 10 000 / 60 000 / 140 000 per week for Lite / Pro / Max, the weekly window counted from the purchase date. A measured job costs ~2.3 credits. The half-rate off-peak window is **promotional and time-limited** — do not build routing on it.

**Concurrency.** Six concurrent real jobs completed clean with zero 429s. z.ai publishes no concurrency limit and states limits adjust dynamically with plan tier; its usage policy recommends one project on Lite and one to two on Pro, and one field report claims a concurrent limit of 1 on Pro (not reproduced here). Default `max_parallel` for zai is **4** — below the measured ceiling. Lower it on Lite.

---

## Backend-failure classification

z.ai **publishes its full error surface**, so the needle set is documented codes rather than field guesses: `1113, 1302, 1305, 1308, 1310, 1311, 1316, 1317`, all HTTP 429, in the envelope `{"error":{"code":"XXXX","message":"…"}}`. [`compound-v-classify-failure.py --backend zai`](../../scripts/compound-v-classify-failure.py) maps them; anything unrecognised fails closed to `other`.

That branch is **not optional**: the function's final `else` is `_CODEX_RULES`, so a zai job without it would be classified with OpenAI's needles — an unrecognised GLM error came back as `auth`, advising the operator to run `codex login`.

Two facts shape the retry policy:

- **No `Retry-After` header is documented anywhere** — the reset time is embedded in the message text — so backoff must be bounded and self-derived, never header-driven.
- **Enforcement throttling is indistinguishable on the wire from ordinary rate limiting**; z.ai's April 2026 enforcement wave surfaced in this same code range. Aggressive retry against a provider that penalises repeat offences is itself the hazard, so the ceiling stays low and the breaker opens early.

`zai` reroutes **up to claude** on a circuit-break, per `FALLBACK` in [`compound-v-failure-policy.py`](../../scripts/compound-v-failure-policy.py). Without that entry the table yields `None` and a credit wall halts the whole run.

---

## Usage

`job_result.usage` carries **real** `input_tokens` / `output_tokens` from z.ai's own response with `measured: true` — zai is **not** in `UNMEASURED_BACKENDS`. The CLI's `total_cost_usd` and `modelUsage[*].costUSD` are computed from Anthropic's price table for a model that never ran and are never carried; `usage` has no cost field to hold one. The reported `contextWindow` and `maxOutputTokens` are likewise the alias's Anthropic defaults, not GLM's, and are not recorded.

---

## Worktree lifecycle and merge-back

Identical in shape to [`adapter-cursor.md`](adapter-cursor.md). The baseline SHA is captured **before** `worktree add`. Worktrees live outside the repo under `${TMPDIR}/compound-v/<run-id>/<job-id>`; scratch (captured result, stderr, the expanded allow-globs, the worker's `HOME`) lives in `$WT.art`, **outside** the worktree so the diff stays pristine. Idempotent on resume.

```bash
# PASS
git -C "$WT" add -A
git -C "$WT" diff --cached --binary HEAD | (cd "$REPO" && git apply --index)
git -C "$REPO" worktree remove -f "$WT"
# BLOCKED / timeout / error: do not merge; leave the worktree for inspection
```

## Resume

`claude -p --output-format json` returns a real RFC-4122 UUID in `.session_id`, so the codex worker's UUID validator applies unchanged. Compound V's default git-wins / fresh re-dispatch tie-break still applies.

---

## Compliance

Claude Code is a tier-1 officially supported tool for the GLM Coding Plan. z.ai's restriction targets *bypassing* a supported tool — "directly invoking model APIs", "SDK-based access" — and this adapter spawns the genuine binary, which makes its own HTTP calls. Anthropic's acceptable-use policy and commercial terms contain no clause against pointing the CLI at a third-party endpoint; their obligations attach to "accessing the Services", which a zai job does not do, and Claude Code's own documentation describes scripted headless invocation as supported.

Three z.ai clauses bear on **how** this is used and must be respected by the operator:

- the plan is licensed to **one natural person**;
- credential **sharing is prohibited**;
- **"resell, sub-resell, repackage, aggregate, proxy"** is prohibited.

A single operator dispatching their own jobs is inside those lines. Sharing one key across a team is not — do not ship a configuration that does.

## Invoking the script

```bash
scripts/compound-v-run-zai-worker.sh \
  --run-id 2026-08-01-some-feature \
  --job-id task-1-build \
  --repo /abs/path/to/repo \
  --prompt-file /abs/path/to/jobs/task-1-build.prompt.md \
  --model glm-5.2 \
  --write-allowed "src/features/build/**" \
  --timeout-sec 900
# optional: --effort medium   (advisory)
# optional: --read-only true  (advisory — enforced post-hoc via an empty --write-allowed)
# optional: --events-log <abs path>   (where the JSON result is captured)
```

All paths MUST be absolute. `--write-allowed` is a **colon-separated** glob list; an **empty** value is a read-only/review job (any change ⇒ BLOCKED). `ZAI_API_KEY` must be set in the dispatcher's environment — the worker refuses to start without it and never reads a key from a file inside the repo.
