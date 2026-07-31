# zai Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** add `zai`, a sixth dispatch backend that runs GLM models through a headless `claude -p` worker against z.ai's Anthropic-compatible endpoint, so codex, claude and z.ai can execute jobs concurrently on separate quotas.

**Architecture:** a Bash-spawned `claude -p` process in its own git worktree, launched under the process-group timeout supervisor with `env -i`, a scratch `HOME`/`CLAUDE_CONFIG_DIR`, and z.ai's endpoint injected. Enforcement is the caller's existing git-derived scope gate — the backend adds no new enforcement mechanism. Everything else is registration: the resolver, the validator, the failure classifier, the failure policy, usage extraction, and the docs that enumerate backends.

**Tech Stack:** bash 3.2 (no arrays, no `local -n`), Python 3.9-safe stdlib, jq, git. No new dependency.

**Spec:** [`docs/superpowers/specs/2026-07-31-zai-backend-design.md`](../specs/2026-07-31-zai-backend-design.md)
**Audits that constrain this plan:** [`archaeology`](../archaeology/2026-07-31-zai-backend.md), [`expert`](../expert/2026-07-31-zai-backend.md), [`library-audit`](../library-audit/2026-07-31-zai-backend.md)

## Global Constraints

- Python must run on **3.9** — CI pins that floor for every `--selftest`. No `match`, no `X | Y` unions, no `dict[str, int]` builtin generics in annotations.
- Bash must run on **3.2** (stock macOS) — no arrays, no `${var,,}`, no `readarray`. Use `set --` for list building, `case` for lowercasing.
- **Never Haiku** as a model. The env var `ANTHROPIC_DEFAULT_HAIKU_MODEL` is a Claude Code *slot name* and is filled with a GLM model; every occurrence must carry an inline comment saying so.
- **No fabricated metrics.** `job_result.usage` has exactly five fields and no cost field. The CLI's `total_cost_usd` is never carried anywhere.
- Enforcement fields (`blocked`, `files_changed`, `violations`) are git-derived by `scripts/compound-v-scope-check.py`. A worker never self-reports them.
- Every external-CLI launch goes through `scripts/compound-v-run-with-timeout.py` with `stdin </dev/null`.
- No `--dangerously-skip-permissions`, no `--yolo`, no bypass `--permission-mode`, anywhere.
- Version lockstep: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` and the top `CHANGELOG.md` heading must all read the same version. Current is **2.17.0**; this PR ships **2.18.0**.

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `scripts/compound-v-run-zai-worker.sh` | The worker: worktree lifecycle, pinned `claude -p` invocation, scope-gate call, `job_result` emission |
| `skills/backend-launcher/adapter-zai.md` | The backend-specific runbook implementing the `job_spec → job_result` contract |
| `scripts/test-zai-worker-stub.sh` | Argv + environment assertions against a fake `claude` on `PATH`; no network |
| `scripts/test-zai-wire-smoke.sh` | Real `claude` binary against a local stub HTTP server; asserts the tool set actually sent |

**Modified:** `scripts/compound-v-resolve-model.py`, `scripts/compound-v-validate-manifest.py`, `scripts/compound-v-classify-failure.py`, `scripts/compound-v-failure-policy.py`, `scripts/compound-v-usage-extract.py`, `schemas/job_result.schema.json`, `agents/parallel-dispatcher.md`, `skills/backend-launcher/SKILL.md`, `skills/compound-v/execution-manifest.md`, `skills/compound-v/routing-policy.md`, `commands/v-init.md`, `commands/v-models.md`, `.github/workflows/validate.yml`, `CHANGELOG.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`.

**Explicitly NOT modified:** `scripts/compound-v-usage-aggregate.py` (it never reads `usage.backend`), `scripts/compound-v-collect-results.py` (its `usage` passthrough at line 344-375 is already backend-agnostic — verify, do not edit).

---

### Task 1: Resolver — register the backend and its tier map

**Files:**
- Modify: `scripts/compound-v-resolve-model.py`

**Interfaces:**
- Produces: `BACKENDS` gains `"zai"`; `resolve(backend="zai", tier=...)` returns `{"backend","tier","model","effort"}` with models `glm-5.2` / `glm-5.2` / `glm-5-turbo`.

- [ ] **Step 1: Write the failing selftest assertions**

In `_selftest()`, next to the existing per-backend expectations, add:

```python
    # --- zai: single-vendor GLM map, identical in every stance -------------
    for _stance in DEFAULT_MODELS_BY_STANCE:
        expect("zai deep in %s" % _stance,
               resolve("zai", "deep", stance=_stance)["model"] == "glm-5.2")
        expect("zai standard in %s" % _stance,
               resolve("zai", "standard", stance=_stance)["model"] == "glm-5.2")
        expect("zai light in %s" % _stance,
               resolve("zai", "light", stance=_stance)["model"] == "glm-5-turbo")
    # xhigh stays codex-only (documented rule; see the spec's Job contract section)
    try:
        resolve("zai", "light", effort="xhigh")
        expect("zai rejects xhigh", False)
    except ValueError:
        expect("zai rejects xhigh", True)
    # zai is NOT a provider/model backend -- a bare GLM name must pass unchanged
    expect("zai bare model override passes",
           resolve("zai", "deep", explicit_model="glm-4.7")["model"] == "glm-4.7")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python3 scripts/compound-v-resolve-model.py --selftest`
Expected: FAIL — `unknown backend 'zai'`.

- [ ] **Step 3: Add the map and register the backend**

Insert after the `_OPENCODE` block (near line 112):

```python
# z.ai (GLM Coding Plan via a headless `claude -p` worker): SINGLE-VENDOR -- every cell is
# a bare GLM model name, never a "provider/model" string (contrast opencode). Names VERIFIED
# live against the subscription endpoint 2026-07-31; an invented name returns
# `400 [1211][Unknown Model]`, so this map is checked, not guessed.
#
# deep+standard = glm-5.2 (the strongest model on the plan). light = glm-5-turbo on a
# head-to-head measurement, NOT on the multiplier table: 3 runs each on one task gave turbo
# 8.5s / 2.56 credits vs glm-4.7 10.1s / 2.38 credits -- 16% faster for 7% more, because
# glm-4.7 emits ~60% more output and eats its own lower multiplier. glm-4.7 stays a
# documented config override for anyone squeezing the weekly window.
#
# Lower-trust tier: no kernel write-confinement; worktree + git-diff is the ONLY file-scope
# enforcement -- see skills/backend-launcher/adapter-zai.md. NEVER haiku.
_ZAI = {"deep": "glm-5.2", "standard": "glm-5.2", "light": "glm-5-turbo"}
```

In `_stance_map()`, add `"zai": _ZAI,` after the `"opencode": _OPENCODE,` line. Then:

```python
BACKENDS = ("claude", "codex", "antigravity", "cursor", "devin", "opencode", "zai")
```

Update the `_stance_map` docstring: `codex/antigravity/cursor/devin/opencode/zai are shared`.

- [ ] **Step 4: Run the selftest to verify it passes**

Run: `python3 scripts/compound-v-resolve-model.py --selftest`
Expected: PASS, including the pre-existing `no haiku in any stance map` assertion.

- [ ] **Step 5: Verify the CLI path by hand**

```bash
for t in deep standard light; do
  python3 scripts/compound-v-resolve-model.py --backend zai --tier "$t"
done
```
Expected: `glm-5.2`, `glm-5.2`, `glm-5-turbo`.

- [ ] **Step 6: Commit**

```bash
git add scripts/compound-v-resolve-model.py
git commit -m "feat(zai): register the backend and its GLM tier map in the resolver"
```

---

### Task 2: Validator — enum, worktree invariant, reviewer prohibition

**Files:**
- Modify: `scripts/compound-v-validate-manifest.py` (four sites: `VALID_BACKENDS` near line 519, the worktree invariant near line 1806, the reviewer prohibition near line 1833, the selftest fixtures near line 2560)

**Interfaces:**
- Consumes: nothing from Task 1 at runtime (the validator does not import the resolver).
- Produces: manifests with `backend: zai` validate iff `isolation: worktree` and the job is not a reviewer.

- [ ] **Step 1: Write the two failing fixtures**

Add near the other single-defect fixtures:

```python
# A complete, otherwise-valid manifest whose ONE defect is a zai job with
# isolation: direct. zai has NO kernel write-confinement (it is a headless
# `claude -p` against a third-party endpoint), so worktree + git-diff is the
# only file-scope enforcement that holds.
ZAI_DIRECT_MANIFEST = """
run_id: 2026-08-01-zai
feature: "zai"
spec_path: docs/superpowers/specs/2026-08-01-zai.md
plan_path: docs/superpowers/plans/2026-08-01-zai.md
audit_paths:
  archaeology: docs/superpowers/archaeology/2026-08-01-zai.md
  domain: docs/superpowers/expert/2026-08-01-zai.md
  library: docs/superpowers/library-audit/2026-08-01-zai.md
routing_stance: balanced
max_parallel: 4
acceptance_criteria:
  - "the build is green"
jobs:
  - id: task-1-build
    title: "build"
    type: implementer
    backend: zai
    tier: standard
    isolation: direct
    run: parallel
    write_allowed: ["src/**"]
    read_allowed: ["src/**"]
    acceptance: "true"
"""

# Same shape, but the ONE defect is a REVIEWER job routed to zai.
ZAI_REVIEWER_MANIFEST = ZAI_DIRECT_MANIFEST.replace(
    "isolation: direct", "isolation: worktree"
).replace("type: implementer", "type: reviewer")
```

In the selftest body, assert both are rejected and that the fixed form passes:

```python
    _expect_invalid("zai direct is rejected", ZAI_DIRECT_MANIFEST, "requires worktree")
    _expect_invalid("zai reviewer is rejected", ZAI_REVIEWER_MANIFEST, "WORKER-ONLY")
    _expect_valid("zai worktree implementer is accepted",
                  ZAI_DIRECT_MANIFEST.replace("isolation: direct", "isolation: worktree"))
```

Use whatever the file's existing helper names are for valid/invalid assertions — read the
neighbouring fixtures' assertions and match them exactly rather than inventing helpers.

- [ ] **Step 2: Run it and watch it fail**

Run: `python3 scripts/compound-v-validate-manifest.py --selftest`
Expected: FAIL — `zai` is not in `VALID_BACKENDS`, so the manifests fail for the wrong reason.

- [ ] **Step 3: Register the backend**

```python
VALID_BACKENDS = ("claude", "codex", "antigravity", "cursor", "devin", "opencode", "zai")
```

- [ ] **Step 4: Extend the worktree invariant**

```python
        if backend_lc in ("codex", "antigravity", "cursor", "devin", "opencode", "zai"):
```

Extend the comment block above it with one sentence:

```
        # zai is a headless `claude -p` pointed at a third-party endpoint: no kernel
        # write-confinement at all, so worktree + git-diff is its ONLY file-scope
        # enforcement, exactly like antigravity/cursor/opencode.
```

- [ ] **Step 5: Extend the reviewer prohibition**

```python
        if _is_reviewer(job) and backend_lc in ("devin", "opencode", "zai"):
```

and widen the message so it names the right adapter:

```python
            problems.append(
                "reviewer job '%s' uses backend '%s' — devin/opencode/zai are "
                "lower-trust, opt-in, WORKER-ONLY backends (see "
                "adapter-devin.md / adapter-opencode.md / adapter-zai.md) and must "
                "never be used for a reviewer job; route reviewers to backend: "
                "claude with tier: deep or model: opus"
                % (jid, backend_lc)
            )
```

- [ ] **Step 6: Run the selftest to verify it passes**

Run: `python3 scripts/compound-v-validate-manifest.py --selftest`
Expected: PASS. The pre-existing never-Haiku fixture must still be rejected.

- [ ] **Step 7: Commit**

```bash
git add scripts/compound-v-validate-manifest.py
git commit -m "feat(zai): validate the backend — worktree-mandatory, never a reviewer"
```

---

### Task 3: Failure classifier — an explicit zai branch with z.ai's real 429 codes

**Files:**
- Modify: `scripts/compound-v-classify-failure.py` (rules table near the other `_*_RULES`; the `classify()` dispatch chain near line 244)

**Interfaces:**
- Produces: `classify("zai", exit_code, stderr)` → `(failure_class, matched, retry_after)`.

**Why this task cannot be skipped:** `classify()` ends with `else: rules = _CODEX_RULES`. Registering `zai` anywhere else without this branch silently applies OpenAI's needle set — including the string ``please run `codex login` `` — to GLM errors.

- [ ] **Step 1: Write the failing selftest assertions**

```python
    # --- zai: z.ai publishes its whole error surface; all of these are HTTP 429 ----
    _ZAI_SAMPLES = [
        ('{"error":{"code":"1113","message":"Insufficient balance or no resource package."}}',
         "out_of_credits"),
        ('{"error":{"code":"1302","message":"API request rate limit reached."}}', "rate_limited"),
        ('{"error":{"code":"1305","message":"Request rate limit reached."}}', "rate_limited"),
        ('{"error":{"code":"1308","message":"Concurrency limit reached."}}', "rate_limited"),
        ('{"error":{"code":"1310","message":"Rate limit reached."}}', "rate_limited"),
        ('{"error":{"code":"1311","message":"Quota exhausted."}}', "rate_limited"),
        ('{"error":{"code":"1316","message":"Rate limit reached."}}', "rate_limited"),
        ('{"error":{"code":"1317","message":"Rate limit reached."}}', "rate_limited"),
    ]
    for _payload, _want in _ZAI_SAMPLES:
        _cls, _matched, _ra = classify("zai", 1, _payload)
        check("zai %s -> %s" % (_want, _want), _cls, _want)
    # An unrecognised payload must fail closed to `other` -- NEVER to a codex verdict.
    _cls, _matched, _ra = classify("zai", 1, "please run `codex login` to authenticate")
    check("zai unknown payload is other, not a codex verdict", _cls, "other")
    # The 1211 config fault seen live is not a quota problem.
    _cls, _, _ = classify("zai", 1, "API Error: 400 [1211][Unknown Model, please check the model code.]")
    check("zai 1211 is other", _cls, "other")
```

Match the file's existing `check(...)` / `expect(...)` helper signature — read the neighbouring
assertions and copy their form.

- [ ] **Step 2: Run it and watch it fail**

Run: `python3 scripts/compound-v-classify-failure.py --selftest`
Expected: FAIL — the codex needle set matches `codex login` and returns `auth`, not `other`.

- [ ] **Step 3: Add the rules table**

Place it beside the other `_*_RULES` definitions:

```python
# z.ai / GLM Coding Plan. Unlike every other backend here, the provider PUBLISHES its full
# error surface (docs.z.ai/api-reference/api-code), so these needles are documented codes,
# not guesses. ALL of them are HTTP 429. The envelope is
# {"error":{"code":"XXXX","message":"..."}}.
#
# Two operational facts drive the policy that consumes this:
#   * NO Retry-After header is documented anywhere -- the reset time is embedded in the
#     message text -- so backoff must be bounded and self-derived, never header-driven.
#   * ENFORCEMENT throttling is indistinguishable on the wire from ordinary rate limiting
#     (z.ai's April 2026 enforcement wave surfaced in this same code range). Aggressive
#     retry against a provider that penalises repeat offences is itself the hazard.
_ZAI_RULES = (
    ("out_of_credits", ('"1113"', "insufficient balance", "no resource package")),
    ("rate_limited", ('"1302"', '"1305"', '"1308"', '"1310"', '"1311"', '"1316"', '"1317"',
                      "rate limit reached", "concurrency limit", "quota exhausted")),
    ("auth", ("invalid api key", "unauthorized", "authentication failed")),
)
```

- [ ] **Step 4: Add the dispatch branch**

In `classify()`, before the final `else`:

```python
    elif backend == "zai":
        rules = _ZAI_RULES
```

- [ ] **Step 5: Run the selftest to verify it passes**

Run: `python3 scripts/compound-v-classify-failure.py --selftest`
Expected: PASS, every pre-existing backend's assertions included.

- [ ] **Step 6: Commit**

```bash
git add scripts/compound-v-classify-failure.py
git commit -m "feat(zai): classify z.ai's documented 429 codes; never fall through to codex rules"
```

---

### Task 4: Failure policy — a fallback entry so a quota wall does not halt the run

**Files:**
- Modify: `scripts/compound-v-failure-policy.py` (the `FALLBACK` dict near line 59)

**Interfaces:**
- Consumes: the `failure_class` strings Task 3 produces.
- Produces: `decide("out_of_credits", "zai", ...)` returns a reroute, not a halt.

**Why:** `FALLBACK` currently reads `{"codex": "claude", "antigravity": "claude", "cursor": "claude", "claude": None}`. A missing key yields `None`, which the policy treats as "no backend to reroute to" and returns **halt** — so a `zai` credit wall would stop the whole run. (`devin` and `opencode` are missing too; that is a pre-existing gap. Fix `zai` here and note the others in the commit body — do **not** silently change devin/opencode behaviour in this PR.)

- [ ] **Step 1: Write the failing selftest assertion**

```python
    # zai reroutes UP to claude on a circuit-break, like every other external worker.
    _d = decide("out_of_credits", "zai", attempts=0, total_retries=0,
                max_total_retries=10, fallback_available=True)
    check("zai out_of_credits reroutes, not halts", _d["action"], "reroute")
    check("zai reroutes to claude", _d.get("reroute_to"), "claude")
```

Read the neighbouring assertions for the exact key names `decide()` returns (`action`,
`reroute_to` or similar) and copy them verbatim — do not assume.

- [ ] **Step 2: Run it and watch it fail**

Run: `python3 scripts/compound-v-failure-policy.py --selftest`
Expected: FAIL — action is `halt`.

- [ ] **Step 3: Add the entry**

```python
FALLBACK = {"codex": "claude", "antigravity": "claude", "cursor": "claude",
            "zai": "claude", "claude": None}
```

Extend the comment above it with:

```
# zai (headless `claude -p` against z.ai) reroutes UP to claude for the same reason as the
# other lower-trust external workers. Note devin/opencode are still absent from this table —
# a pre-existing gap, deliberately not changed here.
```

- [ ] **Step 4: Run the selftest to verify it passes**

Run: `python3 scripts/compound-v-failure-policy.py --selftest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/compound-v-failure-policy.py
git commit -m "fix(zai): add a fallback entry so a z.ai quota wall reroutes instead of halting

Without a FALLBACK key the policy reads None and returns halt, stopping the
whole run on the first credit wall. devin and opencode are still missing from
this table — a pre-existing gap, left untouched here."
```

---

### Task 5: Usage extraction — real token counts from the single JSON result

**Files:**
- Modify: `scripts/compound-v-usage-extract.py` (`extract_usage()` near line 200; a new `_extract_zai`)

**Interfaces:**
- Consumes: the worker's captured stdout, a **single JSON object** (`--output-format json`), not JSONL.
- Produces: `extract_usage("zai", path)` → `{"input_tokens": int, "output_tokens": int, "backend": "zai", "measured": True, "advisor_calls": None}` via the existing `_measured()` helper.

**Why it is measured:** the token counts come from z.ai's own response, so `zai` must **not** join `UNMEASURED_BACKENDS` (which holds `agy`, `antigravity`, `claude`, `devin`). The CLI's `total_cost_usd` is computed from Anthropic's price table for a model that never ran — it is not read, and there is no cost field in the schema to put it in.

- [ ] **Step 1: Write the failing selftest**

```python
    # --- zai: ONE JSON object (claude -p --output-format json), not JSONL ---------
    zai_path = _write_tmp(['{"type":"result","subtype":"success","is_error":false,'
                           '"result":"done","session_id":"ce0ba7c7-bb9a-421f-b926-9973806d506f",'
                           '"total_cost_usd":0.33,'
                           '"usage":{"input_tokens":658,"output_tokens":281},'
                           '"modelUsage":{"glm-5.2":{"inputTokens":658,"outputTokens":281}}}'])
    got = extract_usage("zai", zai_path)
    check("zai input tokens", got["input_tokens"], 658)
    check("zai output tokens", got["output_tokens"], 281)
    check("zai is measured", got["measured"], True)
    check("zai carries no cost field", "cost" in json.dumps(got).lower(), False)
    os.unlink(zai_path)
    # A missing/empty capture must be honest, never a fabricated zero-as-measured.
    check("zai missing file is unmeasured", extract_usage("zai", None)["measured"], False)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python3 scripts/compound-v-usage-extract.py --selftest`
Expected: FAIL — the unknown-backend arm returns `_unmeasured`.

- [ ] **Step 3: Write the extractor**

```python
def _extract_zai(objs: List[Any], backend: str) -> Dict[str, Any]:
    """zai runs `claude -p --output-format json`, which emits ONE terminal object, not a
    JSONL stream. Read `usage.input_tokens` / `usage.output_tokens` from it.

    `total_cost_usd` / `modelUsage[*].costUSD` are deliberately IGNORED: the CLI computes
    them from Anthropic's price table for a model that never ran, and job_result.usage has
    no cost field to hold a number anyway (anti-ruflo)."""
    for obj in objs:
        if not isinstance(obj, dict):
            continue
        u = obj.get("usage")
        if not isinstance(u, dict):
            continue
        inp, out = u.get("input_tokens"), u.get("output_tokens")
        if isinstance(inp, int) and isinstance(out, int):
            return _measured(backend, inp, out)
    return _unmeasured(backend)
```

Add to the dispatch in `extract_usage()`:

```python
    if backend == "zai":
        return _extract_zai(objs, backend)
```

`_iter_json_lines()` already returns `[]` for a missing file and skips unparseable lines, so a
single-object file parses as a one-element list with no special casing.

- [ ] **Step 4: Run the selftest to verify it passes**

Run: `python3 scripts/compound-v-usage-extract.py --selftest`
Expected: PASS.

- [ ] **Step 5: Confirm the collector needs no change**

Run:
```bash
grep -n 'worker_usage = wjson.get("usage")' scripts/compound-v-collect-results.py
```
Expected: one hit around line 348. The passthrough is backend-agnostic — read it, change nothing.

- [ ] **Step 6: Commit**

```bash
git add scripts/compound-v-usage-extract.py
git commit -m "feat(zai): extract real token counts; drop the CLI's Anthropic-priced cost"
```

---

### Task 6: The worker script

**Files:**
- Create: `scripts/compound-v-run-zai-worker.sh`
- Create: `scripts/test-zai-worker-stub.sh`

**Interfaces:**
- Consumes: the resolved model from Task 1.
- Produces: a canonical `job_result` on stdout. CLI:

```bash
scripts/compound-v-run-zai-worker.sh \
  --run-id <id> --job-id <id> --repo <abs> --prompt-file <abs> \
  --model glm-5.2 --write-allowed "src/**:docs/**" \
  --timeout-sec 900 [--effort medium] [--read-only true] [--network false] \
  [--events-log <abs>]
```
`--write-allowed` is **colon-separated**; empty means read-only (any change ⇒ BLOCKED).

**Do not copy any single existing worker.** Per-block sources:

| Block | Source | Why that one |
|---|---|---|
| arg parsing, `die()`, `id_is_safe()` | `compound-v-run-cursor-worker.sh` | shortest correct form |
| worktree lifecycle + baseline SHA captured **before** `worktree add` | `compound-v-run-codex-worker.sh` | the canonical ordering |
| `write_allowed` expansion **wrapped in `set -f`** | `compound-v-run-opencode-worker.sh:634-646` | cursor omits `set -f`, letting globs pathname-expand against the launcher's cwd and corrupt the allow-list |
| `emit_job_result` — the **11-argument** form carrying `usage` | codex / opencode workers | cursor's 10-argument form drops `usage` entirely |
| bounded output capture (`--max-output-bytes`) | codex worker | cursor does not bound it |
| `session_id` UUID validation | codex worker, verbatim | `claude -p` emits a real RFC-4122 UUID |

- [ ] **Step 1: Write the failing stub test**

`scripts/test-zai-worker-stub.sh`, modelled on `scripts/test-advisor-worker-stub.sh`. It puts a
fake `claude` first on `PATH` that dumps its argv and its environment to files, then emits a
canned `--output-format json` object. Assertions:

```bash
# (a) the pinned flags are present, in a form that survives the variadic-flag trap
assert_argv_contains "--permission-mode" "dontAsk"
assert_argv_contains "--tools" "Read,Edit,Write,Bash"
assert_argv_contains "--allowedTools" "Read,Edit,Write,Bash"
assert_argv_contains "--exclude-dynamic-system-prompt-sections"
assert_argv_contains "--output-format" "json"
# the prompt MUST be preceded by `--`: --tools/--allowedTools are variadic and would
# otherwise swallow it
assert_argv_has_terminator_before_prompt

# (b) no bypass flag, ever
assert_argv_lacks "--dangerously-skip-permissions"
assert_argv_lacks "--yolo"
assert_argv_lacks "--bare"

# (c) the environment is scrubbed to exactly the allow-list
assert_env_exactly "PATH HOME TMPDIR LANG CLAUDE_CONFIG_DIR \
  ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN ANTHROPIC_MODEL \
  ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL \
  API_TIMEOUT_MS CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"
# an ambient provider var set by the CALLER must NOT reach the child
ANTHROPIC_API_KEY="leak-me" ANTHROPIC_BASE_URL="https://evil.example" run_worker
assert_child_env_lacks "leak-me" "evil.example"
# HOME must NOT be the real HOME
assert_child_home_is_not "$HOME"

# (d) the three result paths
assert_status_success_on_clean_edit
assert_status_blocked_on_out_of_scope_write     # and files listed in .violations
assert_status_timeout_on_supervisor_124

# (e) the model assertion: a response reporting a non-GLM model fails the job
stub_emits_modelUsage "claude-opus-4-8" && assert_status_error
```

- [ ] **Step 2: Run it and watch it fail**

Run: `bash scripts/test-zai-worker-stub.sh`
Expected: FAIL — `compound-v-run-zai-worker.sh` does not exist.

- [ ] **Step 3: Write the worker**

The novel, load-bearing parts, verbatim. The environment allow-list:

```bash
# The MANDATORY provider-credential scrub, as an ALLOWLIST. `env -i` clears EVERY inherited
# variable; only these names are injected back. A credential can reach the child ONLY if it is
# named here, never by omission from a denylist. HOME and CLAUDE_CONFIG_DIR point at a SCRATCH
# dir, not the operator's: that removes their hooks/plugins/skills/CLAUDE.md from the request
# AND puts ~/.claude/.credentials.json out of reach (a read-only `cat` is available in every
# permission mode and is not configurable).
_SAFE_ENV_VARS="PATH TMPDIR LANG"
```

The invocation:

```bash
run_claude() {
  python3 "$SUPERVISOR" --timeout "$TIMEOUT_SEC" --grace 3 -- \
    env -i "$@" \
        HOME="$SCRATCH" \
        CLAUDE_CONFIG_DIR="$SCRATCH/.claude" \
        ANTHROPIC_BASE_URL="$ZAI_BASE_URL" \
        ANTHROPIC_AUTH_TOKEN="$ZAI_KEY" \
        ANTHROPIC_MODEL="$MODEL" \
        ANTHROPIC_DEFAULT_OPUS_MODEL="$MODEL" \
        ANTHROPIC_DEFAULT_SONNET_MODEL="$MODEL" \
        ANTHROPIC_DEFAULT_HAIKU_MODEL="$MODEL" \
        API_TIMEOUT_MS="$((TIMEOUT_SEC * 1000))" \
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
      claude -p \
        --permission-mode dontAsk \
        --tools "Read,Edit,Write,Bash" \
        --allowedTools "Read,Edit,Write,Bash" \
        --exclude-dynamic-system-prompt-sections \
        --output-format json \
        -- "$(cat "$PROMPT_FILE")" \
    </dev/null >"$EVENTS_LOG" 2>"$STDERR_LOG"
}
```

Four comments that MUST accompany it, because each encodes a measured fact a future editor
would otherwise undo:

```bash
# ANTHROPIC_DEFAULT_HAIKU_MODEL is a Claude Code SLOT NAME, not a model choice: it is filled
# with the resolved GLM model like the other two slots. The never-Haiku policy is untouched.
# z.ai's own integration guide sets all three; an unset small/fast slot sends an Anthropic
# identifier and earns `400 [1211][Unknown Model]`.

# `--tools` decides which built-in tools EXIST; `--allowedTools` decides which run without
# asking. BOTH are required. Measured 2026-08-01: with only --allowedTools the worker had
# Bash but NO Write; with only --tools, dontAsk refused the write. `Grep`/`Glob` do not exist
# as tools in this CLI version — searching goes through Bash.

# `--` before the prompt is NOT decoration: --tools and --allowedTools are variadic and will
# swallow the positional prompt without it.

# `--bare` is deliberately NOT used. In bare mode the built-in set is exactly Bash,Edit,Read —
# `Write` does not exist and cannot be restored, so a bare worker cannot create a file.
```

The model assertion, run before the scope gate:

```bash
# Deterministic compensating control for the one guarantee this invocation cannot make
# structurally: --bare would have guaranteed OAuth/keychain are never read, and we are not
# using it. If the response reports a model that is not a GLM, the request did not go to
# z.ai — fail the job rather than let an unnoticed charge land somewhere else.
served_model="$(jq -r '(.modelUsage // {}) | keys | .[0] // ""' "$EVENTS_LOG" 2>/dev/null)"
case "$served_model" in
  glm-*) : ;;
  *) emit_job_result "error" false '[]' '[]' \
       "response came from '$served_model', not a GLM model — request did not reach z.ai" \
       "" "$WT" 1 "other" 0 "$(_unmeasured_usage)"; exit 0 ;;
esac
```

Everything else — arg parsing, worktree create/remove, the `compound-v-scope-check.py` call,
`emit_job_result` — follows the per-block source table above.

- [ ] **Step 4: Run the stub test to verify it passes**

Run: `bash scripts/test-zai-worker-stub.sh`
Expected: PASS, all five assertion groups.

- [ ] **Step 5: Lint**

Run: `shellcheck scripts/compound-v-run-zai-worker.sh scripts/test-zai-worker-stub.sh`
Expected: no findings. Fix any that appear; bash 3.2 rules apply.

- [ ] **Step 6: Make both executable and commit**

```bash
chmod +x scripts/compound-v-run-zai-worker.sh scripts/test-zai-worker-stub.sh
git add scripts/compound-v-run-zai-worker.sh scripts/test-zai-worker-stub.sh
git commit -m "feat(zai): the headless worker, with a scrubbed env and a GLM-response assertion"
```

---

### Task 7: The wire smoke test — the check that would have caught the first draft

**Files:**
- Create: `scripts/test-zai-wire-smoke.sh`

**Why this exists as its own task:** the stub test in Task 6 validates argv. The defect that broke
the first draft — `--allowedTools` not meaning what it looks like it means — passes every
conceivable argv assertion, because the argv was exactly as intended. Only the **real binary's
interpretation** of that argv reveals it. This test runs the genuine `claude` against a local
stub HTTP server, so it costs no quota and needs no key.

- [ ] **Step 1: Write the test**

```bash
#!/usr/bin/env bash
# test-zai-wire-smoke.sh — runs the REAL claude binary against a local stub HTTP server and
# asserts the tool set that actually reaches the wire. No network, no key, no quota.
#
# This is the test the stub test cannot be. The first draft of the zai spec pinned
# --allowedTools "Read,Grep,Glob,Edit,Write" and believed that defined the tool set. It does
# not: it defines which tools run unprompted. The wire carried Bash,Edit,Read — Write absent,
# Bash present, Grep/Glob nonexistent. Every argv assertion passed. Only the wire showed it.
set -euo pipefail
command -v claude >/dev/null 2>&1 || { echo "SKIP: claude not on PATH"; exit 0; }
```

Then: start a Python `http.server` that records the POST body and answers with a minimal
non-streaming Anthropic response; run the real `claude` with exactly the worker's flag set
pointed at it; assert:

```bash
assert_tools_exactly "Bash Edit Read Write"
assert_header_present "authorization"          # ANTHROPIC_AUTH_TOKEN -> Bearer
assert_header_absent  "x-api-key"
assert_no_gitstatus_in_system_block            # --exclude-dynamic-system-prompt-sections
assert_two_runs_have_identical_tools_and_system_blocks   # the shared cache prefix
```

The last assertion runs the binary twice from **two different worktrees** and diffs the
serialised `tools` and `system` blocks; they must be byte-identical. That is the property that
makes the prefix cacheable across parallel workers, and it silently regresses if
`--exclude-dynamic-system-prompt-sections` is ever dropped.

- [ ] **Step 2: Run it and watch it fail**

Run: `bash scripts/test-zai-wire-smoke.sh`
Expected: FAIL initially if any flag in Task 6's invocation was mistyped; that is the point.

- [ ] **Step 3: Fix whatever it catches, then re-run to green**

Run: `bash scripts/test-zai-wire-smoke.sh`
Expected: PASS.

- [ ] **Step 4: Lint and commit**

```bash
shellcheck scripts/test-zai-wire-smoke.sh
chmod +x scripts/test-zai-wire-smoke.sh
git add scripts/test-zai-wire-smoke.sh
git commit -m "test(zai): assert the tool set that reaches the wire, not just the argv"
```

---

### Task 8: The adapter runbook and every doc that enumerates backends

**Files:**
- Create: `skills/backend-launcher/adapter-zai.md`
- Modify: `skills/backend-launcher/SKILL.md`, `agents/parallel-dispatcher.md`, `skills/compound-v/execution-manifest.md`, `skills/compound-v/routing-policy.md`, `commands/v-init.md`, `commands/v-models.md`, `schemas/job_result.schema.json`

- [ ] **Step 1: Write `adapter-zai.md`**

Follow `adapter-cursor.md`'s section order. It must contain, at minimum: the safety banner
(lower-trust, opt-in, WORKER-ONLY, no kernel confinement); the six load-bearing steps; the
worker-prompt lock verbatim; the pinned invocation from Task 6 with all four comments; the
model/effort resolution rules; the merge-back block; the compliance paragraph naming z.ai's
three binding clauses (one natural person, no credential sharing, no resell/repackage/
aggregate/proxy); and an explicit statement that `read_allowed` is advisory while
`write_allowed` is enforced.

- [ ] **Step 2: Add the adapter table row in `SKILL.md`**

```markdown
| `adapter-zai.md` | headless z.ai (GLM) | Bash-spawned `claude -p` against z.ai's Anthropic endpoint (own process, own worktree) | `worktree` (mandatory) | git-diff scope gate | **lower-trust / opt-in, WORKER-ONLY** (no kernel sandbox; a headless Claude Code pointed at a third-party endpoint) |
```

Also update the `backend` enum comment in the `job_spec` block near line 22 to
`claude | codex | antigravity | cursor | devin | opencode | zai`.

- [ ] **Step 3: Add the dispatcher table row in `agents/parallel-dispatcher.md`**

Without this row nothing tells the dispatcher which script to run. Insert after the `cursor` row:

```markdown
| `zai` | [`adapter-zai.md`](../../../skills/backend-launcher/adapter-zai.md) | Bash-spawned `claude -p` worker via [`scripts/compound-v-run-zai-worker.sh`](../../../scripts/compound-v-run-zai-worker.sh) (`--model <resolved GLM>`; effort advisory); **always** `worktree`. **Lower-trust / opt-in, WORKER-ONLY** (no kernel sandbox); only when `ZAI_API_KEY` is set. (2.18) |
```

Note in the commit body that `devin` and `opencode` are still missing from this table — a
pre-existing gap, deliberately not fixed here.

- [ ] **Step 4: Update `execution-manifest.md`**

Add `zai` to the tier table's three rows, to both per-stance `models` maps, and to the
`backend` enum in the invariant list. Add one sentence to the invariant-2 paragraph naming
`zai ⇒ worktree`, and one to the reviewer prohibition naming `zai`. Record the `light` choice's
measured basis in one sentence — turbo is 16% faster and glm-4.7 only 7% cheaper — so a future
reader does not "fix" it back to the cheaper multiplier.

- [ ] **Step 5: Update `routing-policy.md`, `v-init.md`, `v-models.md`**

`routing-policy.md`: add `zai` to the env-aware availability order, gated on `ZAI_API_KEY`.
`v-init.md`: add a detection clause — `ZAI_API_KEY` present ⇒ `zai` available; record it in
`.claude/compound-v.json`. `v-models.md`: document that z.ai has no list endpoint, so its map is
curated + user-overridable like codex's, and name the three Coding Plan models.

- [ ] **Step 6: Update the schema description string**

In `schemas/job_result.schema.json`, `usage.backend.description`:
`"Backend name this usage was extracted for (codex | opencode | cursor | agy | antigravity | claude | devin | zai)."`

- [ ] **Step 7: Verify no dead cross-references**

Run the same check CI runs (read `.github/workflows/validate.yml` around line 204 for the exact
command) and confirm every link added above resolves.

- [ ] **Step 8: Commit**

```bash
git add skills/ agents/ commands/ schemas/
git commit -m "docs(zai): adapter runbook plus every backend enumeration

The dispatcher's adapter table is load-bearing — without a row nothing maps
backend: zai to its worker script. devin and opencode are still absent from
that table; pre-existing, not fixed here."
```

---

### Task 9: CI — add the two gates the spec assumed existed

**Files:**
- Modify: `.github/workflows/validate.yml`

**Why:** `shellcheck` currently runs only over `hooks/*.sh`, and no step executes any
`scripts/test-*.sh` — the selftest sweep is `scripts/*.py` only. Both were cited as existing
gates in the first draft and do not exist.

- [ ] **Step 1: Add shellcheck over the worker scripts**

```yaml
      - name: Lint worker scripts with shellcheck
        run: |
          sudo apt-get install -y shellcheck
          shellcheck scripts/*.sh
```

- [ ] **Step 2: Add a step that runs the bash test suite**

```yaml
      - name: Run bash test suites
        run: |
          for t in scripts/test-*.sh; do
            echo "--- $t"
            bash "$t"
          done
```

`test-zai-wire-smoke.sh` exits 0 with `SKIP` when `claude` is not on `PATH`, so it is safe in a
runner that has no CLI installed.

- [ ] **Step 3: Verify locally**

```bash
shellcheck scripts/*.sh
for t in scripts/test-*.sh; do bash "$t" || echo "FAILED: $t"; done
```
Expected: clean. If shellcheck flags **pre-existing** scripts, fix only what is trivially safe
and narrow the glob with a comment naming what was excluded and why — never silence the whole
gate.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/validate.yml
git commit -m "ci: lint scripts/*.sh and run the bash test suites

Neither gate existed: shellcheck covered only hooks/*.sh and no step ran any
scripts/test-*.sh."
```

---

### Task 10: Version lockstep and the changelog

**Files:**
- Modify: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `CHANGELOG.md`

- [ ] **Step 1: Bump both manifests to 2.18.0**

Current is 2.17.0 in both. Set `"version": "2.18.0"` in each.

- [ ] **Step 2: Add the changelog entry**

Top of `CHANGELOG.md`, matching the existing heading form `## [2.18.0] - 2026-08-01`. Cover:
the new backend and what it runs; worktree-mandatory and WORKER-ONLY; the tier map with the
measured basis for `light`; the documented 429 classification and the bounded-retry reason; the
fallback fix; the two new CI gates. State plainly that this is a lower-trust, opt-in backend
with no kernel confinement.

- [ ] **Step 3: Verify the lockstep gate passes**

```bash
python3 - <<'PY'
import json, re
p = json.load(open('.claude-plugin/plugin.json'))['version']
m = json.load(open('.claude-plugin/marketplace.json'))
mv = m['plugins'][0]['version'] if 'plugins' in m else m.get('version')
c = re.search(r'^## \[([^\]]+)\]', open('CHANGELOG.md').read(), re.M).group(1)
print(p, mv, c, "OK" if p == mv == c else "MISMATCH")
PY
```
Expected: `2.18.0 2.18.0 2.18.0 OK`.

- [ ] **Step 4: Run every gate end to end**

```bash
python3 scripts/lint-frontmatter.py .
for s in scripts/compound-v-resolve-model.py scripts/compound-v-validate-manifest.py \
         scripts/compound-v-classify-failure.py scripts/compound-v-failure-policy.py \
         scripts/compound-v-usage-extract.py scripts/compound-v-epic-state.py \
         scripts/compound-v-epic-arbiter.py scripts/compound-v-epic-watch.py; do
  python3 "$s" --selftest >/dev/null && echo "ok $s" || echo "FAIL $s"
done
shellcheck scripts/*.sh && echo "ok shellcheck"
for t in scripts/test-*.sh; do bash "$t" >/dev/null && echo "ok $t" || echo "FAIL $t"; done
jq empty .claude-plugin/plugin.json .claude-plugin/marketplace.json hooks/hooks.json schemas/job_result.schema.json && echo "ok json"
```
Expected: every line `ok`.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md .claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "release: v2.18.0 — zai backend"
```

---

### Task 11: Open the pull request

- [ ] **Step 1: Confirm the working tree is clean and every gate is green**

Re-run Task 10 Step 4. Do not proceed on any `FAIL`.

- [ ] **Step 2: Push the branch to the fork**

The push identity differs from the keychain default for this repo; use the `gh` token path
rather than the ambient credential helper.

```bash
git push -u fork feat/zai-backend
```

- [ ] **Step 3: Open the PR against upstream**

```bash
gh pr create --repo procoders/superpowers-v --base main --head yury-procoders:feat/zai-backend \
  --title "feat(zai): a headless GLM worker backend" --body-file <(cat <<'EOF'
Adds `zai`, a sixth dispatch backend, so codex, claude and z.ai can run jobs
concurrently on separate quotas. Worker-only and fallback-only in this PR:
never a reviewer, never an arbiter seat.

**Mechanism.** A Bash-spawned `claude -p` in its own git worktree, under the
process-group supervisor, with `env -i`, a scratch `HOME`/`CLAUDE_CONFIG_DIR`,
and z.ai's Anthropic-compatible endpoint injected. Enforcement is the existing
git-derived scope gate — no new enforcement mechanism.

**Verified live**, not reasoned: the redirect works; z.ai validates model names;
the agentic loop completes and stays inside `write_allowed` across six
concurrent jobs; `session_id` is a real UUID; codex cannot reach z.ai at all
(it needs the Responses API, which z.ai does not expose).

**Two findings worth a reviewer's attention.**
`--tools` and `--allowedTools` are different things and both are required —
`--allowedTools` alone leaves the worker with `Bash` and no `Write`. And
`--bare` cannot be used at all: in bare mode `Write` does not exist and cannot
be restored.

Spec, three pre-flight audits and the plan are included under
`docs/superpowers/`.
EOF
)
```

- [ ] **Step 4: Report the PR URL**

Print it and stop. Do not merge.

---

## Self-Review

**Spec coverage.** Endpoint/credentials → Task 6. Context policy → Tasks 6 and 7. Job contract →
Tasks 5 and 6. Isolation/trust/concurrency → Tasks 2 and 8. Model resolution → Task 1. Failure
classification → Tasks 3 and 4. Files touched → Tasks 1-10. Testing → Tasks 6, 7, 9. Compliance →
Task 8. Acceptance criteria 1-2 → Task 2; 3 → Task 1; 4 → Task 7; 5 → Task 3; 6 → Task 4; 7 →
Task 6; 8 → Task 5; 9 → Task 6; 10 → Task 6; 11 → Task 9.

**Deliberately deferred, per the spec's Non-goals:** the never-Haiku config-map gap, the `glm`
family needle in the arbiter, `adapter-claude.md`'s stale effort claim, the multi-model tier pool
(PR 2), and rate-limit rerouting beyond the fallback entry (PR 3).

**Type consistency.** `_ZAI` (resolver map), `_ZAI_RULES` (classifier), `_extract_zai`
(extractor) are each defined once and referenced only where defined. The backend string is
`"zai"` everywhere — never `"z.ai"`, never `"ZAI"`. `emit_job_result` is the 11-argument form in
every call site in Task 6.
