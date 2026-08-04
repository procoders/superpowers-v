# Adapter: qwen (headless Qwen Code CLI worker)

> Read the contract in [`SKILL.md`](SKILL.md) first — this adapter implements that `job_spec → job_result` interface. This file is the backend-specific runbook; the wiring lives in `scripts/compound-v-run-qwen-worker.sh`.

The qwen backend is a **Bash-spawned `qwen` worker** — the genuine Qwen Code CLI (npm `@qwen-code/qwen-code`, Apache-2.0, **Node.js ≥ 22.0.0** required), authenticated against Alibaba Cloud's Bailian / Model Studio **"Coding Plan"**. Own process, own git worktree, own process group under the timeout supervisor, git-derived scope gate — the same shape as codex / cursor / antigravity / zai.

Two things make it different from every other adapter in this directory, and both are stated up front because they change how it may be used:

- **A kernel sandbox is mandatory, not optional.** `qwen` is the second backend after codex with a real OS-level confinement requirement. A machine with no working sandbox provider reports `qwen` **unavailable** rather than running it unconfined.
- **Alibaba's Coding Plan terms arguably prohibit exactly this use.** That is not a footnote inherited from `adapter-zai.md`; it is a different clause with a different shape, and it is unresolved. Read [Compliance](#compliance--read-this-before-anything-else) before dispatching a single job.

**Status: `auth-pending / coverage-unverified`.**

| | |
|---|---|
| `qwen --version` | **TBD — no live probe yet.** No live Coding Plan key exists, so the pinned argv below has never met the real binary. This slot stays an explicit unknown; it is **not** to be filled with a plausible-looking number. |
| Source of every flag fact | The released **`v0.21.5`** source (`packages/cli/src/config/{config,sandboxConfig,environment}.ts`), not the docs site. Where the two disagree — and on `--sandbox` they do, in a security-relevant way — source wins. |
| Live pass still owed | (a) sandboxing actually engages under the pinned invocation; (b) the `--output-format json` response shape; (c) whether Qwen Code backported the upstream untrusted-folder fix (see [Security precedent](#security-precedent)). |

Nothing here may be described as **verified**. Full derivation: [`docs/superpowers/specs/2026-08-04-qwen-code-cli-backend-design.md`](../../docs/superpowers/specs/2026-08-04-qwen-code-cli-backend-design.md).

---

## ⚠️ SAFETY — lower-trust in role, sandbox-mandatory in mechanism, WORKER-ONLY

**`worktree` is mandatory**, enforced by [`compound-v-validate-manifest.py`](../../scripts/compound-v-validate-manifest.py). `isolation: direct` on a `qwen` job fails validation with a message naming the invariant.

**WORKER-ONLY.** A `qwen` reviewer job is **rejected by name** by the same validator — `qwen` is in the explicit reviewer block-list tuple beside `devin` / `opencode` / `zai`. This needed a real code change and did not come for free: the CR5-5 gate (`_is_claude_opus`) only inspects `fast_path.review` declarations and sealed receipts, so a normal manifest's reviewer job never reaches it, and `tier: deep` alone satisfies the deep-reviewer invariant. Without the block-list entry, `backend: qwen, type: spec_review, tier: deep` would validate cleanly. A reviewer routed here would satisfy the Review Gate's Opus guarantee through a third-party endpoint instead of Claude Opus, defeating it entirely.

**The kernel sandbox is required, not optional.** `QWEN_SANDBOX` (macOS Seatbelt via `sandbox-exec`; Linux Docker or Podman) must engage, and the worker **proves it engaged** after the run rather than assuming it. If containment cannot be proven, the job fails closed — a mandatory sandbox that silently no-ops is worse than an honest optional one, because the trust tier is claimed on it. [`compound-v-pool-state.py`](../../scripts/compound-v-pool-state.py)'s `backend_available("qwen", …)` returns `False` unless **both** the key and a working sandbox provider are present, so this is enforced at routing time and not only at the worker's own refusal.

**Opt-in, and enforced in code.** `qwen` ships **off by default**. A manifest naming a `qwen` job is rejected unless the operator-local, uncommitted acknowledgment (`.claude/compound-v.json` → `qwen_optin.terms_version`, gitignored) is present and current. Prose in `/v:init` cannot stop a hand-authored manifest; the validator can. The record holds an acknowledgment and a terms-version marker only — **never the API key**, which stays in the environment.

**Not an arbiter seat.** [`compound-v-epic-arbiter.py`](../../scripts/compound-v-epic-arbiter.py) matches model families by substring over `gpt`, `gemini`, `claude`, `opus`, `sonnet`, `grok`. `qwen`, `glm` and `kimi` are all absent, so a Coding Plan ballot buckets as `unknown` alongside every other unrecognised model and could be deduped against an unrelated one — a correlated ballot masquerading as an independent vote. Same gap `zai` already left; not closed here.

**Sandbox-mandatory places `qwen` structurally above the no-OS-guarantee tier (opencode / cursor / antigravity / zai) — but its status stays `auth-pending / coverage-unverified`, not "verified".** Claiming codex-equivalent trust before the live pass confirms both the sandbox engagement and the untrusted-folder backport question would be premature.

---

## The 6 load-bearing steps

```
1. ISOLATE   git -C <repo> worktree add <WT> HEAD          # clean diff baseline
2. PREFLIGHT refuse on any .env / .qwen config file from <WT> up to /   # discovery walks UPWARD
3. RUN       cd <WT> && env -i … python3 run-with-timeout.py -- qwen …  # kernel-sandboxed, see below
4. ASSERT    session_start.model == requested model, and SANDBOX was non-empty in the child
5. OBSERVE   compound-v-scope-check.py --worktree <WT> --baseline <sha> --allow <glob> [--allow <glob> …]
6. ENFORCE   every changed path ∉ write_allowed ⇒ violation ⇒ blocked  (do NOT merge)
             MERGE: caller, on PASS only
```

Steps 5–6 are the keystone and are computed in git, never read from anything the model says it did. The deterministic authority is [`compound-v-scope-check.py`](../../scripts/compound-v-scope-check.py) — the same gate the dispatcher runs after every job. The worker must **not** re-implement glob matching in bash.

**Only `write_allowed` is enforced; `read_allowed` is advisory** — the gate is git-derived, and git tracks writes, not reads.

---

## Worker-prompt planner/executor lock

Every dispatched `prompt` opens with the lock, verbatim-in-spirit:

> You are an implementation worker, NOT the planner. Do not change architecture. Do not write outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report BLOCKED.

That is the *instructed* half; the scope gate is the *enforced* half.

---

## Compliance — read this before anything else

**Alibaba's Coding Plan terms plausibly prohibit exactly what Compound V does, and this is not the same situation `zai` cleared.** Verbatim, Alibaba's own pages (fetched 2026-08-04, English and Chinese):

> 中文（[help.aliyun.com/zh/model-studio/coding-plan](https://help.aliyun.com/zh/model-studio/coding-plan)）：
> 「仅限在编程工具（如 Claude Code、OpenClaw 等）中使用，禁止以 API 调用的形式用于自动化脚本、自定义应用程序后端或任何非交互式批量调用场景。」
> 「将套餐 API Key 用于允许范围之外的调用将被视为违规或滥用，可能会导致订阅被暂停或 API Key 被封禁。」
>
> English ([alibabacloud.com/help/en/model-studio/coding-plan](https://www.alibabacloud.com/help/en/model-studio/coding-plan),
> under "Prohibition of API calls"): "This plan is for interactive use in programming tools such as
> Claude Code and OpenClaw. Do not use the plan's API key for automated scripts, application backends,
> or other non-interactive scenarios." … "may result in subscription suspension or API Key revocation."

**Why `zai`'s cleared reasoning does not transfer.** `zai`'s clause restricts *which client* (it bans direct API/SDK access; spawning the real `claude` binary cures it). Alibaba's clause restricts *the mode of use* (it bans automated, non-interactive, batch calling) — spawning the real `qwen` binary from a dispatcher script does **not** obviously cure that, because the script is still automated and non-interactive regardless of which binary it drives. **Do not carry `adapter-zai.md`'s "spawning the vendor-approved binary is the compliant path" conclusion over to this adapter.** It is a conclusion about a differently-shaped clause, and reproducing it here would be a false assurance.

**The countervailing reading, stated fairly — this is genuinely ambiguous, not a foregone violation:** the Chinese original qualifies the ban with **「以 API 调用的形式」** ("in the form of API calls"), which plausibly scopes it to *bypassing* an approved tool rather than to scripting one; the FAQ's own prohibited examples are curl / Postman / Dify (direct-bypass patterns); and Qwen Code is itself on the supported-tools list, with its own docs marketing headless mode as **"ideal for scripting, automation, CI/CD pipelines."** Alibaba ships a tool built for automation and a plan whose terms forbid automation — that contradiction is Alibaba's, not this adapter's, but **the account risk lands on the operator.**

**Compound V cannot resolve this ambiguity, and does not pretend to.** No enforcement precedent was found in any public source — unlike z.ai, which has reproducible error codes and press coverage. The risk here is real but **unmeasured**: there is no observed case in either direction.

**Decision taken (2026-08-04, explicit, informed):** proceed, with this section as the loud, permanent acknowledgment. **The operator who enables `qwen` accepts the risk of subscription suspension or API-key revocation.** That is what the opt-in record in `.claude/compound-v.json` acknowledges — it is a terms-risk acknowledgment, not merely the sandbox/trust-tier caveat every lower-trust backend carries. Consistent with the same decision, advisor-mode — the least defensible use, a review call rather than an interactive programming session — is **deferred out of v1 entirely**.

### Operator clauses that must be respected regardless

- The subscription is licensed to **one natural person**.
- **No account or key sharing.**
- **No resale, sublicense, or account transfer** (Alibaba Cloud International Product Terms of Service v3.8.0).
- Alibaba's Coding Plan FAQ states keys are **auto-disabled on detected public exposure**. That raises the stakes on the argv-leak lesson `zai` already paid for (see [the pinned invocation](#the-pinned-invocation)): a leak costs the subscription, not just the secrecy of one string.
- **A key must never enter CI, a shared secret store, or a team-wide config.** This is a single-operator adapter, full stop.

### Jurisdiction — stated neutrally, not as advocacy

Routing source code through a China-headquartered provider carries the same class of concern the domain audit documents for any Chinese-model integration: third-country-transfer exposure under GDPR Ch. V if a repo's contents include personal data, and a live US/China export-control trajectory whose concrete risk to a plugin is **continuity** (a backend becoming unreachable or unlawful for some installers on a policy change), not sanction. The single most concrete signal found: Alibaba itself banned Claude Code on its own internal machines over alleged backdoor risk (Reuters, 2026-07-03) — a neutral data point, not an argument either way.

**Do not dispatch `qwen` against a repository under an NDA or a contract with a data-residency clause without checking that clause first.** This is a per-repo operator decision; the adapter cannot enforce it.

---

## Data egress — a different file set than `zai`, and **not** `CLAUDE.md`

Qwen Code inherits Gemini CLI's hierarchical context system. These files are concatenated and sent with every prompt:

```
AGENTS.md                 (the default context filename since 2026-02-28)
QWEN.md
CONTEXT.md
.qwen/QWEN.local.md
… plus every transitive @-import any of the above pulls in
```

**This repository has `AGENTS.md` at its root — Compound V's own architecture document. A `qwen` job run against this repo would otherwise ship that file to Alibaba on every single call.** Say it plainly, because it is easy to miss: not a hypothetical repo, this one.

**`--safe-mode` currently suppresses that egress, and it is one flag away from being live again.** `--safe-mode` disables context files (along with hooks, extensions, skills and MCP servers), so with the pinned invocation below the context set is not read and not sent. **Any future change that drops `--safe-mode` — for instance to give the worker project context — silently re-opens this egress.** Whatever the job prompt itself carries is sent regardless, `--safe-mode` or not.

**Accepted loss, stated plainly:** the worker does not receive project conventions from context files, so anything a task depends on must live in the job prompt. Same trade `zai` already makes.

**First-party mitigations, cited honestly and with their limits:** Alibaba states it does not train on customer data, encrypts at rest with **AES-256**, and holds **SOC 2** (Security / Availability / Confidentiality). **But the retention period, the storage region, and the deletion path are not published anywhere found**, and the international endpoint's Singapore association is inferred, not a stated Coding-Plan-specific commitment. Treat the mitigations as real and the gaps as real.

---

## The pinned invocation

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

`$SUPERVISOR` is [`scripts/compound-v-run-with-timeout.py`](../../scripts/compound-v-run-with-timeout.py). `$SESSION_ID` is generated by the caller (`uuidgen`). `$MAX_TURNS` is a documented constant pinned in the worker script — quota is counted in **requests**, so turn count is what costs.

### Why the sandbox is driven by environment variables, never by a flag

- **`-s`/`--sandbox` is a boolean** (`type: 'boolean'` in the option table), **not a profile selector**. `--sandbox <profile>` does not work — an earlier draft of this design wrote exactly that, from the docs site, and it was wrong.
- **The provider comes from `QWEN_SANDBOX`** (`sandbox-exec` | `docker` | `podman`), the **profile from `SEATBELT_PROFILE`** (macOS only), the **image from `QWEN_SANDBOX_IMAGE`**.
- **The environment variable outranks the CLI flag.** A source comment states this explicitly — "environment variable takes precedence over argument" — the **opposite** of what the published sandbox docs page claims. So sandboxing is configured entirely through the environment, and a planted ancestor config that sets these variables is a security concern, not a cosmetic one.
- **Six Seatbelt profiles, not five:** `permissive-open` (**the default** — writes broad, network open), `permissive-closed`, `permissive-proxied`, `restrictive-open`, `restrictive-closed`, `restrictive-proxied`. Never inherit the default.
- **`network: false` is two different mechanisms, not one.** macOS: a `*-closed` / `*-proxied` `SEATBELT_PROFILE`. Linux: container network denial via `SANDBOX_FLAGS=--network=none` — **`SEATBELT_PROFILE` has no effect whatsoever on the Docker/Podman path.** A configuration that names only the Seatbelt half ships an unenforced `network: false` on every Linux install.
- **`SANDBOX` must be absent, and cannot be defended by pre-setting it.** If `process.env['SANDBOX']` is set when `qwen` starts, sandboxing is **silently skipped** — the process believes it is already contained. Setting it defensively *is* the disable. The worker excludes it from the allow-list and asserts it absent, then proves engagement post-hoc (below).

### Ancestor-config preflight — the search walks **upward**

Qwen Code's `.env` discovery walks upward from cwd toward `$HOME`, stops at the first file found, and does **not** merge:

```
<cwd>/.qwen/.env → <cwd>/.env → (repeat at each ancestor) → ~/.qwen/.env → ~/.env
.qwen/.env is EXEMPT from all exclusion filtering, at every level.
```

Checking only inside the worktree is therefore insufficient — a file at `$TMPDIR/compound-v/<run-id>/`, at `$TMPDIR/`, or at any ancestor is loaded too. The worker scans from `$WT` to the filesystem root for `.env`, `.qwen/.env`, `.qwen/settings.json` and `.qwen/QWEN.local.md`, and **refuses to start on any hit**. It is cheap (a handful of `test -f`) and it never fires on a clean run, because `git worktree add` materialises **tracked** files only — it exists for the tracked-secret case and for a resumed worktree a previous job wrote into. **Do not "optimise" it away as dead code.**

The same upward path is why the settings precedence matters: `defaults → system defaults → user (~/.qwen) → PROJECT (.qwen/settings.json, inside the worktree) → system → env vars → CLI flags`. A worktree-supplied `.qwen/settings.json` can set `tools.sandbox: false` — disabling the one control this adapter's trust tier is claimed on — or declare `mcpServers` (arbitrary local commands running outside the model's tool loop, outside the git scope gate, and outside the sandbox that settings file just turned off).

### Per-flag rationale

- **`--model "$MODEL"` is mandatory.** The job contract requires a resolved model; omitting `-m`/`--model` silently serves whatever the config/default chain picks, which makes both the routing decision and the identity assertion meaningless.
- **`--approval-mode=yolo`, never bare `--yolo`.** `--yolo`/`-y` together with `--approval-mode` is a **hard parser error** ("Cannot use both --yolo (-y) and --approval-mode together. Use --approval-mode=yolo instead."), `exit 1` plus a help dump. Note that yolo auto-approves tool calls and does **not** imply a sandbox — the CLI prints its own headless-safety warning to that effect, independent of sandbox state.
- **`--auth-type openai`** asserts the auth path rather than inheriting it from config discovery. The binary also accepts `qwen-oauth|gemini|vertex-ai|anthropic`; pinning `openai` is the cheap hardening that keeps this adapter scoped to the Coding Plan's OpenAI-protocol endpoint.
- **`--output-format json`** buffers an **array** of message objects — `{type:"system", subtype:"session_start", session_id, model}`, `{type:"assistant", message:{content, usage}}`, `{type:"result", subtype:"success", session_id, is_error, duration_ms, result, usage, stats}`. This is a **third** capture shape, distinct from codex's JSONL and zai's single document. (The docs site also describes an unrelated flat-object shape; that shape was not found in the source's actual emitter and is treated as a doc error. The live pass confirms which is real — and the extractor fails loudly, never silently-empty, if neither matches.)
- **`--session-id "$SESSION_ID"`** — the caller **assigns** the id rather than scraping and regex-validating it back, which is strictly better than `zai`'s anchor approach. `--session-id` is mutually exclusive with `--continue`/`--resume` at parse time.
- **`--safe-mode` is required, not optional.** It disables context files (see [Data egress](#data-egress--a-different-file-set-than-zai-and-not-claudemd)), hooks, extensions, skills **and MCP servers** — closing the injection path where a worktree-supplied `.qwen/settings.json` declares `mcpServers`. Skills are **on by default** at v0.21.5, so this is a live concern for the planner/executor lock, not a hypothetical one.
- **`--max-subagent-depth 1`** disables nesting (the default is 5).
- **`--max-session-turns "$MAX_TURNS"`** is a **quota** guard, not a second wall-clock.
- **`env -i` wraps the supervisor, never the binary.** `env` builds the child's environment and then execs, replacing its own process image, so a credential sits in an argv only for a fork/exec instant. The python3 supervisor is the one process alive for the WHOLE job, so a credential passed as one of *its* arguments would be world-readable via `ps` / `/proc/<pid>/cmdline` for the entire job — measured live on the `zai` worker, readable by sibling workers of other backends in the same run. Aggravated here by Alibaba's auto-disable-on-exposure policy.
- **`--env-only` is not redundant with the outer `env -i`.** A macOS Python.framework build injects `SDKROOT` / `CPATH` / `LIBRARY_PATH` and more into the supervisor's *own* environment at startup; without `--env-only`, `Popen`'s default inheritance would pass that through to `qwen`.
- **`QWEN_HOME` in addition to `HOME`.** `QWEN_HOME` is the tool's purpose-built isolation lever: it relocates settings / OAuth tokens / installation id **and** removes `~/.env` from the discovery set entirely — a property plain `HOME` redirection does not have.
- **The subshell `cd` is mandatory.** **No `--cd`/`--dir` flag exists anywhere in the option table** (confirmed by exhaustive enumeration); `--include-directories`/`--add-dir` adds *read* scope and does not change cwd. Without the `cd`, the worker edits the launcher's cwd while the gate diffs an untouched worktree.
- **stdin `</dev/null` under the process-group supervisor** — the non-negotiable launch rule in [`SKILL.md`](SKILL.md).
- **One timeout authority, chosen deliberately.** Qwen Code has native `--max-wall-time` and `--max-tool-calls` (both aborting with exit 55), which overlap the supervisor's job. **The process-group supervisor stays the authority** — it is the plugin-wide launch rule and the only mechanism that `killpg`s an orphaned tool subtree. **Do not also set `--max-wall-time`**; two racing timeouts produce an ambiguous failure class.

### Flags this worker must NEVER emit

| Never | Why |
|---|---|
| `--allowed-tools` | **It bypasses confirmation. It does not restrict which tools exist.** Registered twice in the option table with slightly different help text, which makes a docs-only reading especially likely to pick the wrong flag. The real restriction levers are `--core-tools` (allowlist) and `--exclude-tools` (denylist); `--max-tool-calls 0` aborts on the first tool call of any kind. Neither is in the pinned set today — they are the design surface for a future read-only variant, not a claim made now. |
| bare `--yolo` | Parse-time error when combined with `--approval-mode`. Emit `--approval-mode=yolo`. |
| `--worktree <slug>` | It starts the session inside Qwen Code's **own** worktree at `<repoRoot>/.qwen/worktrees/<slug>/` **and prompts interactively on exit** to keep or remove it. Headless, that is a hang; worse, the model then edits files the scope gate never diffs — an empty diff waving through a job that changed everything. |
| `-p` / `--prompt` | Deprecated at v0.21.5 ("Use the positional prompt instead"), and combining it with a positional is a parse-time error. The positional already defaults to one-shot. |
| `--openai-api-key` in argv | argv is world-readable via `ps`; Alibaba auto-disables keys detected as publicly exposed. |
| `--insecure` | Sets `QWEN_TLS_INSECURE=1`. |
| bare `--resume` | With no id it opens an **interactive session picker** and hangs headless. `--resume <id>` with an explicit id is the only legal form. |

Also live at v0.21.5 and worth knowing, because their stderr deprecation notices pollute output a classifier will parse: `--sandbox-image` (→ `QWEN_SANDBOX_IMAGE`), `--proxy` (→ settings.json), `--experimental-acp` (→ `--acp`), `--experimental-skills` (ignored; skills are on by default now).

### The model-identity assertion — read the envelope, never model output

The served model is taken from the transport's own **`system` / `session_start`** event `model` field and compared to the requested `--model`. Missing, duplicated, or mismatched all **fail closed**.

**Never read it from `--json-schema` / `structured_output`.** That content is authored by the model, and a model cannot authenticate its own identity — a substituted model would simply assert the expected name. (`--json-schema <json|@file>` is a real and useful first-party feature for pinning a *summary* payload's shape, and it is deliberately not in the pinned invocation for exactly this reason.)

This is the concrete defense against the injection path above: a worktree- or ancestor-supplied `OPENAI_API_KEY` — unset by this design and therefore free real estate — is a first-class alternate auth path that could silently change which credential and which endpoint served the request. The Coding Plan's multi-vendor catalog is what makes "did we get the model we asked for" a meaningful question.

### Containment proof

After the run, the worker asserts the child actually reported a **non-empty `SANDBOX`** — the variable the sandbox transport sets on itself once engaged. If engagement cannot be proven, the job fails. Exact assertion mechanics are among the items the live pass must confirm.

### The pinned settings file lives in scratch, never in the worktree

```bash
mkdir -p "$SCRATCH/.qwen"
cat > "$SCRATCH/.qwen/settings.json" <<'SETTINGS'
{ "security": { "folderTrust": { "enabled": true } } }
SETTINGS
```

`security.folderTrust.enabled` is set **explicitly** rather than inheriting the documented-off default (see [Security precedent](#security-precedent)). The file MUST live under `$SCRATCH` — the redirected `QWEN_HOME` — and **never inside `$WT`**: a project-scoped `.qwen/settings.json` sits inside the worktree and would dirty the worker's own diff, tripping the scope gate on a job that changed nothing on purpose.

---

## Model and effort

Resolved before dispatch by [`compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) `--backend qwen --tier <tier>`. qwen is **single-vendor at the protocol level**: one OpenAI-protocol endpoint, so every model is a **bare catalog name**, never a `provider/model` string.

```
deep     → qwen3-coder-plus
standard → qwen3-coder-plus
light    → qwen3-coder-plus
```

**All three tiers deliberately carry the same model.** Per-tier differentiation needs live measurement on a real Coding Plan key; inventing a ranking from a catalog listing would be a fabricated metric. `qwen3-coder-plus` is the coding-specialised, documented default. **Not `"auto"`**: unlike `cursor` (which resolves `auto` internally), this worker passes `--model` straight to the endpoint, so a placeholder would be sent literally and rejected. `/v:models` rewrites this map once a live key exists — provisional is fine, unresolvable or fictional is not.

**Catalog** — Alibaba's own Model Studio page, 2026-08-04, all reachable on one key: `qwen3.7-plus`, `qwen3.6-plus`, `qwen3.5-plus`, `qwen3-max-2026-01-23`, `qwen3-coder-next`, `qwen3-coder-plus`, `MiniMax-M2.5`, `glm-5`, `glm-4.7`, `kimi-k2.5`. `glm-5`, `glm-4.7` and `kimi-k2.5` are documented, non-default overrides through the same endpoint. **Qwen3.8-Max (shipped 2026-08-03) is not yet in the Coding Plan catalog** — do not add it until it appears there. The catalog moves faster than a spec can track, which is the argument against hardcoding a flagship as the default.

**Endpoint.** International `https://coding-intl.dashscope.aliyuncs.com/v1` (the default) or China `https://coding.dashscope.aliyuncs.com/v1`. Make the choice an explicit config field: **a region mismatch produces a 401 that does not self-identify as a region error.**

**`effort` is advisory — twice over.** Qwen Code has **no headless effort flag at all**; the only surface is `model.reasoningEffort` in settings.json, and Qwen applies its own per-provider clamp on top, so a requested value can be silently downgraded per model. The worker accepts `low|medium|high`, validates, and then explicitly discards.

**`xhigh` is COMPOUND V POLICY, not a Qwen limitation.** Qwen's own ladder is `low|medium|high|xhigh|max` and it supports `xhigh` and `max` natively. This plugin reserves `xhigh` for `codex` (the kernel `model_reasoning_effort` setting), so `qwen` rejects it with the project-policy message — **use `high`**. Documented this way on purpose, so a future reader does not "fix" a non-bug.

---

## Quota

**Request-counted, not token-counted — a different mental model than `zai`'s credit multipliers.** Pro tier:

```
6,000 requests / 5 hours
45,000 requests / week
90,000 requests / month
$50/mo international · ¥200/mo China
```

A 60-turn agentic loop costs **60 units regardless of output length**, which is why `--max-session-turns` is the relevant guard and a token budget is not. Lite tier is discontinued (no purchases since 2026-03-20); Pro is effectively the only tier.

**No pay-as-you-go fallback.** Quota exhaustion is a hard error, never an overage charge — which is what makes the `FALLBACK` policy entry load-bearing rather than politeness.

**Concurrency.** Alibaba's limit is real, **undocumented in magnitude, and dynamically adjusted**. The seeded value is `backend_max_parallel.qwen = 2`, **labeled unmeasured** — chosen conservatively, never presented as a measured ceiling. Raise it only after a live 2/4/6 run says so.

**Honest limit of that key, quoted from its own documentation:** validation proves the key's *shape*, "not that a new scheduler or semaphore enforces it." `backend_max_parallel` is **a ceiling the prose dispatcher respects, not an enforced bound.** Do not describe it as enforcement. A hard per-backend semaphore is future work.

---

## Backend-failure classification

**DashScope returns `message: null`** — the shape fact that everything else follows from:

```json
{"errorType":"THROTTLING.userQPSLimit","rid":"…","message":null,"status":429}
```

A classifier keyed on message text — the way `zai`'s is — matches **nothing** here. [`compound-v-classify-failure.py --backend qwen`](../../scripts/compound-v-classify-failure.py) keys on `errorType` and on the quota-window phrases instead.

| Needle | Class |
|---|---|
| `invalid access token`, `token expired`, `invalid api-key`, `401` | `auth` |
| `hour` / `week` / `month allocated quota exceeded` | **`usage_window_exhausted`** |
| `THROTTLING.userQPSLimit`, `concurrency allocated quota exceeded`, `429` | `rate_limited` |
| `503`, `529` | `overloaded` |
| anything else | fails closed to `other` |

**The throttle-vs-window split is the whole behavior.** `THROTTLING.userQPSLimit` and `concurrency allocated quota exceeded` are momentary throttles ⇒ `rate_limited` ⇒ retry with bounded backoff. `hour`/`week`/`month allocated quota exceeded` is a **window that has run out**, not a spent balance ⇒ `usage_window_exhausted` ⇒ the cooldown-with-`until` path, which stops retrying until the window reopens. Mapping these to `out_of_credits` would be wrong: with no pay-as-you-go on this plan, the window reopens by itself.

**Native, documented exit codes wire in without any text parsing:** **0** success · **53** session-turn cap · **55** wall-time / tool-call budget · **130** SIGINT.

**The `qwen` branch is not optional.** `classify()`'s final `else` is `_CODEX_RULES`, so its absence is not a neutral gap — it is a wrong answer: a Qwen auth failure would be matched by OpenAI's needles and the operator told to run **`codex login`** to fix an Alibaba key. The selftest pins exactly that regression.

**No qwen-specific retry policy, and no edits to the shared failure machinery.** `qwen` takes the global defaults; the existing throttle-vs-window handling is already correct for this provider once the needles map to the right classes. Note explicitly that `adapter-zai.md`'s "a provider that penalises repeat offences, so cap retries low" reasoning is **about z.ai** (its April 2026 enforcement wave, wire-indistinguishable from ordinary rate limiting) and does **not** transfer: what Alibaba documents is a penalty for automated use *at all*, with no documented or observed link between retry count and enforcement.

`qwen` reroutes **up to claude** via `FALLBACK` in [`compound-v-failure-policy.py`](../../scripts/compound-v-failure-policy.py). A missing entry yields `None`, which `decide()` turns into `halt` — the first quota wall would stop the entire run.

---

## Usage

`job_result.usage` carries **real** `input_tokens` / `output_tokens` read from the terminal `result` element of the buffered JSON array, with `measured: true` — `qwen` is **not** in `UNMEASURED_BACKENDS`. A failed job with a well-formed but **empty** `usage` object yields `measured: false` with **null** counts, never a fabricated `0`. No cost figure is ever recorded, estimated, or carried.

---

## Worktree lifecycle and merge-back

Identical in shape to [`adapter-zai.md`](adapter-zai.md). The baseline SHA is captured **before** `worktree add`. Worktrees live outside the repo under `${TMPDIR}/compound-v/<run-id>/<job-id>`; scratch (`$SCRATCH` — the captured result, stderr, the pinned `.qwen/settings.json`, and the worker's redirected `HOME`/`QWEN_HOME`) lives in `$WT.art`, **outside** the worktree so the diff stays pristine. Idempotent on resume.

```bash
# PASS
git -C "$WT" add -A
git -C "$WT" diff --cached --binary HEAD | (cd "$REPO" && git apply --index)
git -C "$REPO" worktree remove -f "$WT"
# BLOCKED / timeout / error: do not merge; leave the worktree for inspection
```

**The allow-list is passed as repeated `--allow` arguments, never through a `$ART/write_allowed.globs` file.** Five of the six older workers still carry the file pattern, and it was **reproduced as exploitable**: a child with write access appends `**` to that file and turns its own out-of-scope write into a clean PASS. Related properties inherited verbatim, each earned by a real bug: `set -f` (noglob) around the `IFS=":"` split of `--write-allowed`, because entries are literal globs that would otherwise pathname-expand against the launcher's cwd; and scope-gate exit code **`1` means BLOCKED and is not fatal** — only rc > 1 or unparseable output is a worker fault.

**Resume.** `session_id` is the caller-assigned UUID from `--session-id`, not scraped. Compound V's default git-wins / fresh re-dispatch tie-break still applies.

---

## Security precedent

**GHSA-wpqr-6v78-jr5g** (2026-04-24, **CVSS 10.0**, `@google/gemini-cli < 0.39.1`, fixed in **Gemini CLI 0.39.1**) was filed against upstream Gemini CLI for **exactly the configuration this adapter's first draft proposed**: headless mode auto-trusting workspace folders for config/env loading, combined with `--yolo` ignoring the tool allowlist entirely — remote code execution from an untrusted directory, e.g. a malicious PR in a CI-like context.

**Qwen Code forked Gemini CLI at `v0.8.2`** — roughly 31 minor versions before that fix landed.

Qwen Code does ship its own **Trusted Folders** feature (it blocks `.qwen/settings.json`, `.env`, extensions, and tool auto-acceptance when a folder is untrusted), but **its own docs state it is disabled by default**, and they are silent on what headless mode does with an untrusted folder. **Whether Qwen Code backported the upstream fix's `FatalUntrustedWorkspaceError` behavior is UNVERIFIED.**

Two consequences, both already reflected above:

1. This is the primary reason `QWEN_SANDBOX` moved from optional to **mandatory** in this design.
2. It is why the scratch settings file sets `security.folderTrust.enabled` **explicitly** rather than inheriting the documented-off default.

**Required live-probe item:** observe the headless untrusted-folder behavior directly and record it here together with the exact `qwen --version`, the way `codex-cli 0.144.1` is recorded in [`adapter-codex.md`](adapter-codex.md). **Do not infer it.** Re-verify on every version bump — the package shipped five stable releases in the seven days before this audit plus a daily nightly channel, so the risk here is churn, not abandonment. Until this is resolved, the status stays `auth-pending / coverage-unverified`.

---

## Invoking the script

```bash
scripts/compound-v-run-qwen-worker.sh \
  --run-id 2026-08-04-some-feature \
  --job-id task-1-build \
  --repo /abs/path/to/repo \
  --prompt-file /abs/path/to/jobs/task-1-build.prompt.md \
  --model qwen3-coder-plus \
  --write-allowed "src/features/build/**" \
  --timeout-sec 900
# optional: --effort low|medium|high   (advisory — validated, then explicitly discarded; xhigh is rejected)
# optional: --read-only true|false     (advisory — enforced post-hoc via an empty --write-allowed)
# optional: --network true|false       (maps to the Seatbelt profile on macOS, SANDBOX_FLAGS on Linux)
# optional: --events-log <abs path>    (where the JSON array is captured)
# optional: --output-schema <path>     (accepted for CLI parity, ignored)
```

All paths MUST be absolute. `--write-allowed` is a **colon-separated** glob list; an **empty** value is a read-only/review job (any change ⇒ BLOCKED).

**`BAILIAN_CODING_PLAN_API_KEY` must be set in the dispatcher's environment** — the worker refuses to start without it and never reads a key from a file inside the repo. `OPENAI_BASE_URL` defaults to the international endpoint. The worker also refuses to start when `SANDBOX` is already set in the environment, when no sandbox provider is available, or when the ancestor scan finds a Qwen config file.

**Availability.** `qwen` is reachable only when the operator opt-in record is current, `qwen` is on PATH under Node ≥ 22, the key is set, and a sandbox provider works (`sandbox-exec` on macOS; `docker` or `podman` on Linux). `/v:init` probes all of these and marks `qwen` **unavailable** — not merely degraded — when any is missing. In a pool, an unavailable member is recorded `available: false` at freeze time and the run continues with a surfaced warning: **pools degrade, they do not fail.**
