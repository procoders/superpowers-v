**Base:** `feat/qwen-backend`, branched from `local/three-pr-integration` (`4bcb13c` — PR #5 zai,
PR #6 tier-model-pool, PR #7 rate-limit-rerouting all merged, selftests green).
**Recon:** docs/superpowers/recon/2026-08-04-qwen-code-cli-backend-adapter.md
**Pre-flights:** docs/superpowers/archaeology/2026-08-04-qwen-code-cli-backend.md · docs/superpowers/expert/2026-08-04-qwen-code-cli-backend.md · docs/superpowers/library-audit/2026-08-04-qwen-code-cli-backend.md

> ⚠️ **The three pre-flight audits were run against the older `feat/zai-backend` (`71b59dc`). Every
> line number they cite is stale here, and two of their conclusions are outdated.** Their *reasoning*
> was re-verified against this base (see "Re-verification against the integration base" below); their
> *coordinates* were not carried over. Re-locate every site before editing it.

# qwen — a headless Qwen Code CLI worker backend

**Goal:** add `qwen` as a seventh dispatch backend, authenticated against Alibaba Cloud's Bailian/Model
Studio "Coding Plan" (the Pro subscription being purchased). **v1 scope: implementation worker only.**
Never a Review Gate reviewer. **Advisor-mode inclusion is explicitly deferred — see Non-goals.**

**Architecture:** a Bash-spawned `qwen` process using the **positional prompt** (`qwen "<prompt>"`, not
`-p` — deprecated at v0.21.5), Qwen Code's own native headless mode. Own git worktree, own process
group under the timeout supervisor, git-derived scope gate — identical shape to cursor/antigravity/zai.
**Unlike the v1 draft of this spec, `QWEN_SANDBOX` (real kernel confinement — macOS Seatbelt / Linux
Docker or Podman) is MANDATORY, not optional** — see Trust Tier below for why this changed.

**Status — auth-pending / coverage-unverified, revised after three Compound V pre-flights
(2026-08-04).** This spec's first draft was written from Qwen Code's *published docs* alone and
contained multiple factual errors the pre-flights caught by reading the actual `v0.21.5` released
source (`packages/cli/src/config/{config,sandboxConfig,environment}.ts`) — in at least one
security-relevant case (`--sandbox`'s arity and precedence), **the published docs themselves
contradict the source at the same tag.** Every correction below is sourced to a specific file/line or
a primary Alibaba/GitHub page, not reasoned from the tool's general shape. A live probe with a real
Coding Plan key is still required before this adapter ships as verified — this spec fixes what three
independent audits could catch without one, not everything.

---

## Re-verification against the integration base

Re-read on `4bcb13c` before planning. What survived, what moved, and what the audits could not have
seen because it did not exist yet.

**Survived unchanged (the load-bearing findings all hold):**
- `PER_CLASS_MAX` is still **global**, `rate_limited: 3` — no per-backend override exists. The
  "a `FALLBACK` entry cannot deliver a low qwen retry ceiling" finding stands, and PR #7's much larger
  circuit-break surface (`circuit_break_backend`, `cooldown_backend`, cooldowns with `until`) is what
  the qwen policy must now build **on**, not alongside.
- The reviewer block tuple is still `("devin", "opencode", "zai")` — `qwen` is still absent, so a
  `backend: qwen` reviewer job would still validate. The correction stands.
- `ADVISOR_CONSULTABLE_NONCLAUDE` is still a one-element `("codex",)`. Moot for v1 (advisor deferred),
  but the audit's claim about a non-existent middle tier remains correct.
- `_CURSOR = {"deep": "auto", ...}` still exists — so the "do not copy `auto` as qwen's placeholder"
  correction still has a live thing to warn against.

**Changed — five NEW registration sites that did not exist when the audits ran.** The audit's
"13 independent registration sites" count is now low:
- **`scripts/compound-v-pool-state.py`** — a backend tuple, *and* **`backend_available(backend, env,
  which)`**, which today special-cases exactly two backends (`codex` → binary on PATH, `zai` →
  `ZAI_API_KEY` set) and returns `True` for everything else. **This is the natural code home for the
  mandatory-sandbox availability gate**: `qwen` must return available only when the key is set **and**
  a working sandbox provider exists, otherwise the "sandbox is mandatory" claim has no enforcement at
  routing time and a qwen job would be frozen into a pool on a machine that cannot sandbox it.
  Defaulting to the `return True` fall-through would be a silent, wrong answer.
- **`scripts/compound-v-project-config.py`** — backend tuple.
- **`scripts/compound-v-dashboard.py`** — backend tuple plus cooldown rendering.
- **`scripts/compound-v-failure-policy.py`** — `CONCRETE_BACKENDS`, a second tuple beside `FALLBACK`.
- **Pool participation** in `compound-v-resolve-model.py` — `resolve_pool()`, weighted members,
  `MAX_POOL_WEIGHT`/`MAX_EXPANDED_POOL_SLOTS`, and a rule that **`effort: xhigh` is invalid for pooled
  jobs**. A decision is now required that the spec never faced: see "Pool participation" below.

**Changed — the failure taxonomy grew.** `schemas/job_result.schema.json`'s `failure_class` enum now
includes **`usage_window_exhausted`** and **`model_unavailable`** beside the classes this spec listed.
That materially improves the qwen mapping: Alibaba's `hour/week/month allocated quota exceeded` is a
**window** exhaustion (`usage_window_exhausted`), not `out_of_credits` — the Coding Plan has no
pay-as-you-go, so the window reopens on its own and the run should cool down rather than treat the
credit balance as spent. `concurrency allocated quota exceeded` → `rate_limited`.
`THROTTLING.userQPSLimit` → `rate_limited`. 401 `invalid access token` → `auth`.

**Pool participation — decision: `qwen` joins the shipped default pool beside `codex` and `zai`.**
An earlier draft of this section argued for keeping it out, on the claim that a qwen slot frozen on a
machine without a sandbox provider "would fail every job in that run." **That claim was wrong, and
reading the code disproves it:** `freeze_pool_members()` calls `backend_available()` once per member
at freeze time and records `available: false`, and the run continues with a surfaced warning
("pool '<stance>/<tier>' has 1 of 2 configured backend(s) available … this run will not spread jobs
across providers"). Pools degrade; they do not fail. That is precisely what `backend_available()` is
for — which makes implementing it correctly for `qwen` (key **and** sandbox provider) the load-bearing
task, not pool membership.

Two consequences to carry into the plan: the shipped default policy changes from "Codex + zai" to
"Codex + zai + qwen", so the seeded config, its documentation, and the pool examples all move
together; and pooled jobs already reject `effort: xhigh`, which is consistent with qwen rejecting it
anyway. Weight stays at the default `1` until live quota data justifies otherwise.

---

## Compliance — read this before anything else

**Alibaba's Coding Plan terms plausibly prohibit exactly what Compound V does, and this is not the
same situation `zai` cleared.** Verbatim, Alibaba's own pages (fetched 2026-08-04, English and
Chinese):

> 中文（[help.aliyun.com/zh/model-studio/coding-plan](https://help.aliyun.com/zh/model-studio/coding-plan)）：
> 「仅限在编程工具（如 Claude Code、OpenClaw 等）中使用，禁止以 API 调用的形式用于自动化脚本、自定义应用程序后端或任何非交互式批量调用场景。」
> 「将套餐 API Key 用于允许范围之外的调用将被视为违规或滥用，可能会导致订阅被暂停或 API Key 被封禁。」
>
> English ([alibabacloud.com/help/en/model-studio/coding-plan](https://www.alibabacloud.com/help/en/model-studio/coding-plan),
> under "Prohibition of API calls"): "This plan is for interactive use in programming tools such as
> Claude Code and OpenClaw. Do not use the plan's API key for automated scripts, application backends,
> or other non-interactive scenarios." … "may result in subscription suspension or API Key revocation."

**Why `zai`'s cleared reasoning does not transfer.** `zai`'s clause restricts *which client* (bans
direct API/SDK access; spawning the real `claude` binary cures it). Alibaba's clause restricts *the
mode of use* (bans automated, non-interactive, batch calling) — spawning the real `qwen` binary from a
dispatcher script does **not** obviously cure that, because the script is still automated and
non-interactive regardless of which binary it drives.

**The countervailing reading, stated fairly — this is genuinely ambiguous, not a foregone violation:**
the Chinese original qualifies the ban with **「以 API 调用的形式」** ("in the form of API calls"), which
plausibly scopes it to *bypassing* an approved tool, not to scripting one; the FAQ's own prohibited
examples are curl/Postman/Dify (direct-bypass patterns); and Qwen Code is itself on the supported-tools
list, with its own docs marketing headless mode as **"ideal for scripting, automation, CI/CD
pipelines."** Alibaba ships a tool built for automation and a plan whose terms forbid automation — that
contradiction is Alibaba's, not this adapter's, but **the account risk lands on the operator.** No
enforcement precedent was found in any public source (unlike z.ai, which has reproducible error codes
and press coverage) — the risk here is real but **unmeasured**.

**Decision taken (2026-08-04, explicit, informed):** proceed, with this section serving as the loud,
permanent acknowledgment `adapter-qwen.md` must carry — not a footnote inherited from `zai`. Consistent
with that decision, advisor-mode (the least defensible use — a review call, not an interactive
programming session) is **deferred out of v1 entirely** — see Non-goals.

**`qwen` MUST ship opt-in and OFF by default**, and the opt-in acknowledgment must cover
**account-suspension risk**, not only the sandbox/trust-tier caveat every lower-trust backend carries.
This is the standing rule for a publicly-distributed plugin: the operator who accepts the risk must be
the one who read the clause, and an installer who never opted in must never have a `qwen` job dispatched
on their key by default.

**Operator-side clauses that must be respected regardless:** the subscription is licensed to one
natural person; no account/key sharing; no resale, sublicense, or account transfer (Alibaba Cloud
International Product Terms of Service v3.8.0). **A key must never enter CI, a shared secret store, or
a team-wide config** — this is a single-operator adapter, full stop. Alibaba's Coding Plan FAQ also
states keys are **auto-disabled on detected public exposure** — raises the stakes on the argv-leak
lesson `zai` already paid for (see Credentials, below).

**Data egress — different file set than `zai`, not `CLAUDE.md`.** Qwen Code inherits Gemini CLI's
hierarchical context system: `AGENTS.md` (default since 2026-02-28), `QWEN.md`, `CONTEXT.md`,
`.qwen/QWEN.local.md`, and transitive `@`-imports are concatenated and sent with every prompt. **This
repository has `AGENTS.md` at its root — Compound V's own architecture document — which a `qwen` job
against this repo would ship to Alibaba on every single call.** The required `--safe-mode` flag (see
Credentials and isolation) disables context files and therefore **suppresses this egress by default** —
but the adapter doc must still state the mechanism plainly, because it is one flag away from being live
again: any future change that drops `--safe-mode` for the sake of giving the worker project context
silently re-opens it. Whatever the prompt itself carries is sent regardless.
First-party mitigations worth citing alongside the warning: Alibaba states it does not train on
customer data, AES-256 at rest, SOC 2 (Security/Availability/Confidentiality) — but retention period,
storage region, and deletion path are **not published anywhere found**, and the international
endpoint's Singapore association is inferred, not a stated Coding-Plan-specific commitment.

**Jurisdiction, stated neutrally, not as advocacy:** routing source code through a China-headquartered
provider carries the same class of concern the domain audit documents for any Chinese-model
integration — third-country-transfer exposure under GDPR Ch. V if a repo's contents include personal
data, and a live US/China export-control trajectory whose concrete risk to a plugin is *continuity*
(a backend becoming unreachable or unlawful for some installers on a policy change), not sanction. The
single most concrete signal found: Alibaba itself banned Claude Code on its own internal machines over
alleged backdoor risk (Reuters, 2026-07-03) — a fact worth stating in the adapter doc as a neutral data
point, not an argument either way. **Do not dispatch `qwen` against a repository under an NDA or a
contract with a data-residency clause without checking that clause first** — this is a per-repo
operator decision, not something this adapter can enforce.

---

## Verified facts (v0.21.5 released source — not docs alone)

The library audit checked the actual `yargs` option table at git tag `v0.21.5`
(`packages/cli/src/config/config.ts` and neighbors), not just the published docs site, because the
two disagree on at least one security-relevant flag. Where they disagree, source wins; both readings
are recorded so a future version bump can be checked against the right one.

**Headless invocation:**
- **Positional prompt, not `-p`.** `qwen "<prompt>"` — `-p`/`--prompt` is deprecated at v0.21.5
  ("Use the positional prompt instead. This flag will be removed in a future version.") and combining
  `--prompt` with a positional is a parse-time error. The positional already defaults to one-shot.
- `--output-format text|json|stream-json` (`-o`). `json` buffers an **array** of message objects:
  `{type:"system", subtype:"session_start", session_id, model}`, `{type:"assistant",
  message:{content:[...], usage}}`, `{type:"result", subtype:"success", session_id, is_error,
  duration_ms, result, usage, stats}`. (The *docs site* also describes an unrelated flat-object shape
  under a different heading on the same page — that shape was not found in the source's actual emitter
  and should be treated as a doc error, not a second real mode; confirm the array shape empirically in
  live verification and fail loudly, never silently-empty, if neither matches.)
- **`--json-schema <json|@file>`** registers a synthetic `structured_output` tool and ends the session
  on the first valid call — a first-party way to pin a *summary* payload's shape instead of parsing
  free-form output. **Optional, and explicitly not part of the pinned invocation**, because its
  content is model-authored: useful for shaping a human summary, never usable as evidence about the
  run itself (see the model-identity assertion, which must read the transport envelope instead).
- `--continue`/`-c` (latest session), `--resume <id>`/`-r` (specific session — **never emit a bare
  `--resume` with no id, it opens an interactive session picker and hangs headless**), `--session-id
  <id>` (**caller assigns** the id instead of scraping it back — strictly better than `zai`'s
  regex-anchor approach), `--fork-session`. `--chat-recording false` disables resume entirely.
  `--continue`+`--resume`, and `--session-id` with either, are mutually exclusive (parse-time error).

**Sandbox — corrects the spec's first draft, which followed the docs site and was wrong:**
- **`-s`/`--sandbox` is a boolean**, not a profile selector (`type: 'boolean'`). `--sandbox <profile>`
  as written in the original draft does not work.
- **The provider comes from `QWEN_SANDBOX`** (`sandbox-exec`|`docker`|`podman`), the **profile from
  `SEATBELT_PROFILE`** (macOS only), the **image from `QWEN_SANDBOX_IMAGE`** (`--sandbox-image` CLI
  flag is deprecated in favor of it).
- **The environment variable outranks the CLI flag** — a source comment states this explicitly
  ("environment variable takes precedence over argument"), the **opposite** of what the published
  sandbox docs page claims.
- **Six Seatbelt profiles**, not five: `permissive-open` (**default** — writes broad, network open),
  `permissive-closed`, `permissive-proxied`, `restrictive-open`, `restrictive-closed`,
  `restrictive-proxied`.
- If `process.env['SANDBOX']` is already set when `qwen` starts, sandboxing is **silently skipped** —
  the process believes it's already contained. This variable must never leak into the invocation
  unset-by-accident from the operator's own shell.
- On macOS, `sandbox-exec` is preferred automatically over Docker/Podman whenever it exists — Linux
  requires Docker or Podman.
- `SANDBOX` is set *by the sandbox transport itself* once engaged (non-empty = contained) — a
  verifiable post-hoc signal, not a promise. Exact assertion mechanics need live verification.

**Tool restriction — a second doc-vs-reality trap, same family as Claude Code's own `--allowedTools`
lesson already in this repo's knowledge base:**
- **`--allowed-tools` bypasses confirmation. It does not restrict which tools exist.** Registered
  twice in the option table with slightly different help text, making a docs-only reading even more
  likely to pick the wrong flag.
- **`--core-tools <list>` (allowlist) and `--exclude-tools <list>` (denylist) are the real
  restriction levers.** `--max-tool-calls 0` aborts on the first tool call of any kind — a hard
  read-only lever.

**Approval mode — mutually exclusive with `--yolo` at parse time:**
- `--yolo`/`-y` and `--approval-mode` **together is a hard parser error** ("Cannot use both --yolo
  (-y) and --approval-mode together. Use --approval-mode=yolo instead."), `exit 1` + help dump.
  **Emit `--approval-mode=yolo` for the worker; never emit bare `--yolo`.**
- `--yolo`/`approval-mode=yolo` auto-approves all tool calls but does **not** imply a sandbox — the
  CLI itself prints a headless-safety warning to this effect (suppressible via
  `QWEN_CODE_SUPPRESS_YOLO_WARNING=1`), confirmed independent of sandbox state.

**Budget/runaway guards, native and previously unknown to this spec:**
- `--max-wall-time <dur>` (`90`|`30s`|`5m`|`1h`|`1.5h`) and `--max-tool-calls <n>` both abort with
  **exit code 55**. `--max-session-turns <n>` caps turn count.
- `--max-subagent-depth <n>` (`1` disables nesting; default 5) and `--safe-mode` (disables context
  files, hooks, extensions, skills, MCP servers) resolve the recon's open question about Skills/
  SubAgents interacting with the planner/executor lock. **Skills are on by default at v0.21.5.**
- Documented, deterministic exit codes: **0** success, **53** session-turn cap, **55** wall-time/
  tool-call budget, **130** SIGINT.
- `--fallback-model <m1,m2,m3>` documents the exact capacity codes it responds to: **429, 503, 529.**

**Deprecations live at v0.21.5** (all still function, but emit stderr notices that pollute output a
classifier will parse): `--prompt`/`-p`, `--sandbox-image` (→ `tools.sandboxImage`/`QWEN_SANDBOX_IMAGE`),
`--proxy` (→ settings.json), `--experimental-acp` (→ `--acp`), `--experimental-skills` (ignored, on by
default now).

**No `--cd`/`--dir` flag exists anywhere in the option table** — confirmed by exhaustive enumeration.
`--include-directories`/`--add-dir` adds *additional* read scope; it does not change cwd. **The worker
must `cd` into the worktree in a subshell**, exactly like `cursor` and `zai`.

**`--worktree <slug>` exists and must never be passed.** It starts the session inside Qwen Code's
*own* git worktree at `<repoRoot>/.qwen/worktrees/<slug>/` and — critically for a headless worker —
**prompts interactively on exit** to keep or remove it. If this engages by flag, by inherited settings,
or by a resumed session's sidecar, the model edits files the scope gate never diffs (an "empty diff
waves through a job that changed nothing" failure) and/or the process hangs waiting for input that
never comes.

**Auth — headless-native, confirmed:**
- OAuth cannot work headless (Alibaba's own docs state this plainly); Coding Plan/API-key auth does.
  Qwen OAuth's free tier was discontinued 2026-04-15 regardless.
- Credentials: `BAILIAN_CODING_PLAN_API_KEY` + `OPENAI_BASE_URL` — international
  `https://coding-intl.dashscope.aliyuncs.com/v1`, China `https://coding.dashscope.aliyuncs.com/v1`.
  Default to international; make the endpoint an explicit config field (a region mismatch produces a
  401 that does not self-identify as a region error).
- **`--auth-type openai`** should be pinned explicitly in the worker argv (the binary also accepts
  `qwen-oauth|gemini|vertex-ai|anthropic`) — asserts the auth path rather than inheriting it from
  config discovery, and is the reason the CR5-5 reviewer-gate reasoning below is scope-dependent, not
  tool-dependent.
- **Never pass `--openai-api-key` on the command line** (argv is world-readable via `ps`) or
  `--insecure` (sets `QWEN_TLS_INSECURE=1`).

**Quota — Token Plan Pro, credit-based.** ⚠️ This whole section previously described the **Coding
Plan** and was wrong for this operator: their subscription was measured to be **Token Plan → Pro
Plan, $68/month** (console screenshot + live API behaviour; their key has zero entitlement on any
Coding Plan endpoint). Corrected facts:

- **Fixed monthly fee, credits deducted** — not pay-as-you-go, not per-request counting.
- Console-published rate windows: **12,000 credits / 5 hours** and **40,000 / 7 days**.
- **Credits are consumed by "the model, token count, thinking mode, and tool calls"** — so a long
  system preamble, a large tool set, AND the model's own reasoning tokens all bill. Measured: a
  one-word prompt cost **17,277 input tokens**, which is the preamble plus 64 tool definitions, not
  the user's text; and `qwen3.8-max` emitted an unrequested `thinking` block. `--core-tools` is
  therefore a real cost lever here in a way it never was on a per-request plan. Do not guess the
  credits-per-token ratio — it is unpublished, and inventing one violates the anti-fabrication rule.
- **Exhaustion does NOT self-heal on a rolling window.** Quoted: *"Credits are deducted from the
  seat's monthly quota first. After the seat quota is exhausted, overages draw from the shared quota
  pack. After all Credits are exhausted, the service suspends until the next billing cycle."* The
  5h/7d numbers are RATE caps; the real budget is monthly. **This splits the failure taxonomy in a way
  the classifier must respect:** a rate-window trip is `rate_limited`/`usage_window_exhausted` and
  should cool down, but a *monthly* exhaustion will not reopen for weeks — it must circuit-break and
  reroute, never wait. Treating them alike would park a run for days.
- **Concurrency is published for this plan**, unlike the Coding Plan's undocumented dynamic limit:
  *"Supports 6-8 Agents running concurrently"* on Pro. Published ≠ measured by us — keep
  `backend_max_parallel.qwen` conservative until a real 2/4/6 run is done, but record that a higher
  ceiling is documented.

**Compliance carries over unchanged — the clause is the same shape on this plan.** Token Plan's own
terms: *"This plan is for interactive use with compatible AI programming and agent tools only. Do not
use it for automated scripts or application backends."* That is the same automation prohibition the
Compliance section above analyses for the Coding Plan, so that analysis stands with the plan name
swapped; do not treat the plan change as having resolved it. Additionally: *"Each seat is bound to one
member and one API Key, and cannot be shared"* — the single-operator rule is explicit here, not
inferred.

**Model catalog — wider than originally scoped, and already drifting:** Alibaba's own Model Studio
page (2026-08-04) lists `qwen3.7-plus`, `qwen3.6-plus`, `qwen3.5-plus`, `qwen3-max-2026-01-23`,
`qwen3-coder-next`, `qwen3-coder-plus`, `MiniMax-M2.5`, `glm-5`, `glm-4.7`, `kimi-k2.5`. Qwen3.8-Max
(shipped 2026-08-03, one day before this spec) is **not yet** in the Coding Plan catalog — which
confirms rather than overturns the earlier decision not to hardcode a specific flagship as the
default: the catalog itself moves faster than a spec can track.

**Package/runtime:** `@qwen-code/qwen-code` — 26,646★, Apache-2.0, not archived, five stable releases
in the seven days before this audit plus a daily nightly channel: **actively developed, not stale; the
real risk is churn, not abandonment.** Requires **Node.js ≥ 22.0.0** (`engines` field) — unlike
`codex`/`cursor-agent`, which ship as standalone binaries, `qwen` is an npm package with a hard runtime
floor that must be asserted in `/v:init` capability detection, or a Node-20 machine gets an
unclassified failure instead of a clean capability-missing message.

**Security precedent — real, unresolved either way:** upstream Gemini CLI shipped **GHSA-wpqr-6v78-jr5g**
(2026-04-24, **CVSS 10.0**, `@google/gemini-cli < 0.39.1`) for exactly the configuration this adapter's
first draft proposed: headless mode auto-trusting workspace folders for config/env loading, combined
with `--yolo` ignoring the tool allowlist entirely — remote code execution from an untrusted directory
(e.g. a malicious PR in a CI-like context). **Qwen Code forked Gemini CLI at v0.8.2, roughly 31 minor
versions before the fix landed.** Qwen Code does ship its own **Trusted Folders** feature (blocks
`.qwen/settings.json`, `.env`, extensions, and tool auto-acceptance when a folder is untrusted) but its
own docs state it is **disabled by default**, and are silent on what headless mode does with an
untrusted folder — whether Qwen Code backported the upstream fix's `FatalUntrustedWorkspaceError`
behavior is **unverified**. This is the primary reason `--sandbox`/`QWEN_SANDBOX` moved from optional
to mandatory in this revision (see Trust Tier), and why a live-verification pass must explicitly check
this before the adapter's status can read anything stronger than "auth-pending / coverage-unverified."

---

## Credentials and isolation

**`env -i` does not fully isolate Qwen Code the way it isolates Claude Code — this is a documented gap,
not a residual risk to wave away.** Claude Code's config surface is `$HOME`-rooted; **Qwen Code's is
also `cwd`-rooted**, and cwd is the worktree (a checkout of the repo under test). Verified discovery
order:

```
.env search — walks UPWARD from cwd toward $HOME, stops at first file found, files are NOT merged:
  <cwd>/.qwen/.env  → <cwd>/.env  → (repeat at each ancestor directory) → ~/.qwen/.env → ~/.env
  .qwen/.env is EXEMPT from all exclusion filtering, at every level.

settings precedence (low → high):
  defaults → system defaults → user (~/.qwen) → PROJECT (.qwen/settings.json, inside the worktree)
  → system → env vars → CLI flags
```

**What the scrub still protects:** values already present in `process.env` are never overwritten by a
loaded `.env` — so an explicitly-exported `BAILIAN_CODING_PLAN_API_KEY`/`OPENAI_BASE_URL` cannot be
hijacked by simple override. **What it does not protect:** any name the scrub does *not* set is free
real estate — `OPENAI_API_KEY` is unset by this design and is a first-class alternate auth path; a
worktree `.qwen/settings.json` can set `tools.sandbox: false` (disabling the one control this adapter
now requires) or `mcpServers` (arbitrary local commands outside the model's tool loop, the git scope
gate, and any sandbox the settings file just turned off). `git worktree add` materializes **tracked**
files only, so an operator's own gitignored `.env` does not travel in — a real, worth-stating
mitigation — but a repo that *tracks* `.env`/`.qwen/`, or a resumed job re-entering a worktree a prior
job wrote into, are live paths.

**Required isolation shape:**

```
env -i PATH TMPDIR LANG \
    HOME=<scratch> QWEN_HOME=<scratch> \
    BAILIAN_CODING_PLAN_API_KEY=<key> OPENAI_BASE_URL=<endpoint> \
    QWEN_SANDBOX=<sandbox-exec|docker|podman> \
    SEATBELT_PROFILE=<macOS only: restrictive-closed|restrictive-proxied> \
    [SANDBOX_FLAGS=<Linux only: container network-denial flags> QWEN_SANDBOX_IMAGE=<image>] \
  python3 scripts/compound-v-run-with-timeout.py --timeout <t> --grace 3 -- \
    ( cd "$WT" && qwen --model "$MODEL" --approval-mode=yolo --auth-type openai \
        --output-format json --session-id "$(uuidgen)" --safe-mode --max-subagent-depth 1 \
        --max-session-turns <n> --exclude-tools <deny-list-if-any> "<prompt>" ) </dev/null
```

Non-negotiable elements beyond the flag corrections above:
- **`QWEN_HOME` in addition to `HOME`.** `QWEN_HOME` is the tool's own purpose-built isolation lever —
  it relocates settings/OAuth-tokens/installation_id **and** removes `~/.env` from the discovery set
  entirely, a property plain `HOME` redirection does not have.
- **`--model "$MODEL"` must be passed explicitly.** The job contract requires a resolved model; an
  invocation that omits `-m`/`--model` silently serves whatever the config/default chain picks, which
  makes both the routing decision and the identity assertion below meaningless.
- **Pre-flight refuse (or quarantine) the job for config files in the worktree AND in every ancestor
  directory Qwen will search.** Checking only `$WT/.env` and `$WT/.qwen/.env` is insufficient:
  discovery walks **upward** from cwd, so a file at `$TMPDIR/compound-v/<run-id>/`, `$TMPDIR/`, or any
  ancestor is loaded too. Scan the full chain from `$WT` up to the filesystem root (cheap — a handful
  of `test -f` calls) for `.env` and `.qwen/.env`, and refuse on any hit.
  **`SANDBOX` cannot be defended by pre-defining it**, which is the non-obvious trap here: the tool
  skips sandboxing when `SANDBOX` is *present at all*, so setting it defensively would be the
  disable, not the guard. Scanning plus the post-hoc containment assertion below is the mechanism;
  the same applies to any injected `QWEN_TLS_INSECURE`. Comment this reasoning in the script so a
  future edit does not "optimize" the scan away as dead code.
- **`--safe-mode` and `--max-subagent-depth 1` are required, not optional.** `--safe-mode` disables
  context files, hooks, extensions, skills, **and MCP servers** — closing the injection path where a
  worktree-supplied `.qwen/settings.json` declares `mcpServers` (arbitrary local commands that run
  outside the model's tool loop, outside the git scope gate, and outside the sandbox). It also
  suppresses the `AGENTS.md` egress described in Compliance, since context files are exactly what it
  disables. **Accepted loss, stated plainly:** the worker no longer receives project conventions from
  context files, so anything a task depends on must live in the job prompt — the same trade `zai`
  already makes. Skills are **on by default** at v0.21.5, so this is a live concern for the
  planner/executor lock, not hypothetical.
- **Set `security.folderTrust.enabled` explicitly** in the scratch `QWEN_HOME`'s `settings.json` rather
  than relying on the documented default, which is **off**. Do not infer the headless behavior — the
  live pass must observe it.
- **A model-identity assertion, `zai`'s GLM-check analogue — read from the ENVELOPE, never from model
  output.** Take the model identifier from the **`system`/`session_start` event's `model` field** (the
  transport's own record of what it dispatched to), and fail the job if it does not match the model
  passed to `--model`. **Do not read it from `--json-schema`/`structured_output`** — that content is
  authored by the model itself, and a model cannot authenticate its own identity; a wrong or
  substituted model would simply assert the expected name. Missing, duplicated, or mismatched
  envelope fields all **fail closed**. This is the concrete defense against the injection path above
  (a worktree- or ancestor-supplied `OPENAI_API_KEY` silently switching which credential and endpoint
  served the request) — the Coding Plan's multi-vendor catalog makes "did we get the model we asked
  for" meaningful the same way it is for `zai`.
- **Prove containment engaged, do not assume it.** After the run, assert the child actually had a
  non-empty `SANDBOX` value (the variable the sandbox transport sets on itself once active). If
  engagement cannot be proven, the job **fails closed** — a mandatory sandbox that silently no-ops is
  worse than an honest optional one, because the trust tier is claimed on it.
- **Live-verify whether Qwen Code backported the upstream untrusted-folder fix**, and record the
  observed behavior plus the exact `qwen --version` in `adapter-qwen.md`, the way `codex-cli 0.144.1`
  is recorded. Re-verify on every version bump given the release cadence above.
- Credential-in-argv discipline mirrors `zai`'s hard-won lesson exactly: `env -i` wraps the
  **supervisor**, never the binary directly, because the supervisor is the long-lived process whose
  argv is `ps`-readable for the whole job. Aggravated here: Alibaba auto-disables keys it detects as
  publicly exposed, so an argv leak costs the subscription, not just secrecy.

**Copy the *post-fix* `zai` worker, not any older sibling.** Five of the six existing workers still
carry a pattern that was **reproduced as exploitable**: they write `write_allowed` to a predictable
`$ART/write_allowed.globs` and read it back after the child exits — and a child with unconfined write
access can append `**` to that file and turn its own out-of-scope write into a clean PASS. The `zai`
worker was fixed to pass repeated **`--allow` arguments** from positional parameters instead. Specific
inheritance list, each item earned by a real bug:
- `--allow`-argument gate transport, never the `$ART` file.
- `env -i` wrapping the supervisor + `--env-only` allow-list (a macOS Python.framework build injects
  `SDKROOT`/`CPATH`/etc. into the supervisor's own environment, which `Popen` would otherwise inherit).
- `set -f` (noglob) around the `IFS=":"` split of `write_allowed` — entries are literal globs, and
  without it they pathname-expand against the launcher's cwd and corrupt the allow-list.
- Scope-gate exit-code semantics: rc `1` means BLOCKED and must **not** be fatal; only rc `>1` or
  unparseable output is a worker fault.
- `$ART` scratch outside `$WT` so the diff stays pristine; idempotent worktree recreation on resume.
- Do **not** copy `zai`'s `RUN_ID=""""` typo (four quote characters — harmless but real, and it
  survives shellcheck).

**One timeout authority, chosen deliberately.** Qwen Code has native `--max-wall-time` (and
`--max-tool-calls`), both aborting with exit code 55, which overlaps `compound-v-run-with-timeout.py`'s
job. **The process-group supervisor stays the authority** — it is the plugin-wide non-negotiable launch
rule and the only mechanism that `killpg`s an orphaned tool subtree. Native `--max-session-turns` is
used for a *different* purpose (quota, see below), not as a second wall-clock. Do not set
`--max-wall-time` as well; two racing timeouts produce an ambiguous failure class.

---

## Trust tier and reviewer gate

**Sandbox is mandatory in v1 — this is a change from the original draft, made after the pre-flights.**
`qwen` becomes the **second** backend (after Codex) with a *real* kernel confinement requirement,
placing it structurally above the no-OS-guarantee tier (opencode/cursor/antigravity/zai) rather than
inside it — but its status stays **auth-pending/coverage-unverified**, not "verified," until a live
pass confirms (a) sandboxing actually engages under the pinned invocation, and (b) the untrusted-folder
backport question above is resolved. Claiming Codex-equivalent trust before both are confirmed would be
premature. `isolation: worktree` remains mandatory regardless (existing invariant).

**Mandatory sandboxing has two consequences the first revision of this section skipped.** First,
**it is two different mechanisms, not one, and only the macOS half was specified.** `SEATBELT_PROFILE`
is macOS-only and has **no effect whatsoever** on the Docker/Podman path Linux uses — there, network
denial is a *container flag* concern (`SANDBOX_FLAGS`), not a profile name. Both mappings must be
specified and tested separately; `network: false` means "a `*-closed`/`*-proxied` Seatbelt profile" on
macOS and "container network denied" on Linux, and a spec that names only the former silently ships an
unenforced `network: false` on every Linux install. Second, **if the sandbox is mandatory, then a
machine with no working sandbox provider cannot run `qwen` at all** — `/v:init` must probe for a usable
provider (Seatbelt on macOS; a working Docker or Podman on Linux) and mark `qwen` **unavailable**, not
merely degraded, when none exists. Probing only for Node ≥22, as the previous revision did, would let
`qwen` be routed on a machine where its one trust-tier justification cannot engage.

**The opt-in must be enforced in code, not in prose.** "`qwen` is off by default" is unenforceable as
originally written: editing `/v:init`'s prose cannot stop a hand-authored manifest, and the dispatcher
runs whatever backend a manifest names. The enforcing mechanism is an **operator-local, uncommitted
acknowledgment record** (in `.claude/compound-v.json`, which is gitignored — never in a tracked file)
carrying a terms-version marker, and **the manifest validator must reject any `qwen` job when it is
absent or its version marker is stale**. Validation is the right layer because it is the one hard gate
the whole pipeline already funnels through. The record holds an acknowledgment only — **never the API
key**, which stays in the environment. Both the absent and the acknowledged cases need test fixtures.

**WORKER-ONLY, and this needed an actual code change, not a free ride.** The original draft claimed the
existing CR5-5 gate (`_is_claude_opus()`) "already covers `qwen` generically." **That claim was false as
written** — CR5-5 only inspects `fast_path.review` declarations and sealed receipts; a normal
(non-fast-path) manifest reviewer job never reaches it. The actual second gate — an explicit
backend-name block at `compound-v-validate-manifest.py`'s reviewer-prohibition site — currently lists
`("devin", "opencode", "zai")` and does **not** include `qwen`. Without adding it, `backend: qwen, type:
spec_review, tier: deep` validates cleanly today. **`qwen` must be added to that tuple, exactly like
zai**, and the acceptance criteria below are corrected accordingly. (The premise that qwen's own model
names never contain "opus" holds only under this spec's Non-goal of never widening past the Coding
Plan's OpenAI-protocol auth path — `--auth-type anthropic` exists in the binary; pinning `--auth-type
openai` explicitly, as this spec now requires, is the cheap hardening that keeps that premise true.)

---

## Job contract

`job_spec` is unchanged. `qwen` accepts `backend`, `prompt`, `tier`, `effort` (`low|medium|high`, never
`xhigh`), `model` (explicit override — bare name, e.g. `glm-5`/`kimi-k2.5`/`qwen3-coder-plus`), `cwd`,
`write_allowed`, `read_only`, `timeout_sec`, `network`.

- **`effort` is advisory, and where it's written matters.** No headless CLI flag exists at all — the
  only surface is `model.reasoningEffort` in settings.json. Qwen's own ladder is `low|medium|high|
  xhigh|max`; **the `xhigh` ban is Compound V policy, not a Qwen limitation** — document it that way so
  a future reader doesn't "fix" a non-bug. Note Qwen applies its own per-provider effort clamp, so the
  value can be silently downgraded per model regardless. **Any pinned effort settings file must be
  written to `$SCRATCH/.qwen/settings.json` (the redirected `QWEN_HOME`), never inside `$WT`** — a
  project-scoped `.qwen/settings.json` lives inside the worktree and would dirty the worker's own diff,
  tripping the scope gate on a job that changed nothing on purpose.
- **`network` maps to the Seatbelt/container profile now that sandboxing is mandatory**: `network:
  false` must resolve to a `*-closed` or `*-proxied` profile, never left at the network-open default.
  This is a real mapping now, not `zai`'s explicit-discard pattern.
- `read_only` / an empty `write_allowed` is enforced post-hoc exactly like every other adapter: any
  change ⇒ `blocked`, never merged.

`job_result` is unchanged and assembled by the caller: `files_changed`/`violations`/`blocked` stay
git-derived; `worktree` is always set (never `direct`); `session_id` is the caller-assigned UUID from
`--session-id`, not scraped; `usage` is real (`--output-format json`'s `usage` fields), not fabricated
on a failed job (the `a091185` lesson — a well-formed-but-empty usage object must yield
`measured:false`, not zeros).

---

## Failure classification

**Real error data already exists — narrower "fail closed to `other`" scope than the first draft
assumed.** Community threads (2026, above the single-report threshold) show:
`{"errorType":"THROTTLING.userQPSLimit","message":null,"status":429}` — **`message` is `null`**, so a
classifier keying on message text (the way `zai`'s does) matches nothing; **key on `errorType`
instead.** Also documented: `concurrency allocated quota exceeded` / `hour allocated quota exceeded` /
`week allocated quota exceeded` / `month allocated quota exceeded`, and 401 `invalid access token or
token expired`. **Mapped onto the taxonomy as it exists on this base** (which grew two classes since
the audits ran): `concurrency` and `THROTTLING.userQPSLimit` → `rate_limited`; `hour`/`week`/`month`
→ **`usage_window_exhausted`**, *not* `out_of_credits` — with no pay-as-you-go on this plan the window
reopens by itself, so the correct behavior is a cooldown, not "the balance is spent"; 401 → `auth`.
Additionally, the CLI's own
deterministic exit codes wire in directly without needing error-text parsing at all: **0** success,
**53** session-turn cap, **55** wall-time/tool-call budget exceeded, **130** SIGINT.

A `qwen` branch in `compound-v-classify-failure.py` is mandatory **in this PR**, seeded with the
needles above — the function's final `else` is `_CODEX_RULES`, so its absence is not a neutral gap, it
is a wrong answer (a `qwen` auth failure would be told to run `codex login`, the exact bug class the
`zai` selftest already pins). Whatever isn't covered by the needles above still fails closed to
`other`. `compound-v-failure-policy.py` needs a `FALLBACK` entry for `qwen` regardless — with no
pay-as-you-go fallback on this plan, a missing entry means a quota wall halts the entire run, not a
graceful degrade.

**Retry policy: qwen uses the existing global default. A previous revision of this spec claimed
otherwise on a borrowed argument, and the argument does not survive checking.**

That revision said retries must be capped low because this is "a provider that penalizes repeat
offenders." **That reasoning came from `adapter-zai.md` and is about z.ai**, which had an April 2026
enforcement wave whose throttling was wire-indistinguishable from ordinary rate limiting. It is not
about Alibaba. What Alibaba actually documents is a penalty for **using the key for automation at
all** (see Compliance) — there is no documented or observed link between retry count and enforcement,
and the domain audit found **zero** community reports of Alibaba's enforcement behavior in either
direction. Transplanting z.ai's conclusion onto a different vendor is exactly the error the domain
audit warned about, and this spec committed it.

A second, weaker argument was then offered in its place — "retries burn a request-counted quota" —
and it does not hold either. Quota here counts **model calls**; a request rejected by a limiter never
reached the model, and whether such a rejection decrements the counter is **not documented in either
direction**. Unverified, so it cannot carry a design decision.

**The actual reason no qwen-specific policy is needed: the existing taxonomy already splits the two
cases correctly, and the split is exactly right for this provider.** `THROTTLING.userQPSLimit` and
`concurrency allocated quota exceeded` are momentary throttles ⇒ `rate_limited` ⇒ retry with backoff,
which is the correct response and for which the global ceiling of 3 is unobjectionable.
`hour`/`week`/`month allocated quota exceeded` is a window that has run out ⇒
**`usage_window_exhausted`** ⇒ PR #7's cooldown-with-`until` path, which stops retrying until the
window reopens — again exactly right, and it is why the classifier mapping in this section matters far
more than any retry count.

**Decision: `qwen` takes the global defaults plus its `FALLBACK` entry; nothing in PR #7 is touched.**
Not because editing fresh code is expensive, but because there is nothing to fix — the behavior is
already correct once the needles map to the right classes. Revisit only if live data shows otherwise.

---

## Model resolution

Bare model name — one OpenAI-protocol endpoint, never a `provider/model` string. **A built-in
placeholder tier map is required in code, not optional.** The repo has no `.claude/compound-v.json`
today, `resolve()` raises `ValueError` on an unresolvable cell, and `--selftest` iterates every
backend × tier as a hard CI gate — registering `qwen` in `BACKENDS` without a resolvable map turns CI
red on the first commit. **The built-in default must be a real, documented catalog model name** (e.g.
`qwen3-coder-plus` from Alibaba's published Coding Plan list) — **not** a `_CURSOR`-style `"auto"`
placeholder. `auto` works for Cursor because Cursor resolves it internally; here `--model "$MODEL"` is
passed straight to the endpoint, so `auto` would be sent literally and rejected. `/v:models` overrides
the default once a real key exists — provisional is fine, unresolvable or fictional is not. **The
catalog is no longer provisional: it was read live from `/models` with the operator's own Coding Plan
key on both regional endpoints, and both returned the identical ten entries.** `glm-5`, `glm-4.7`, and `kimi-k2.5` remain documented,
non-default overrides reachable through the same endpoint.

**Concurrency: `backend_max_parallel.qwen = 2` — the mechanism already exists on this base.** A
previous revision proposed inventing a validator invariant against the run-global `max_parallel`,
on the belief that no per-backend cap existed. It does: PR #6 shipped a top-level
**`backend_max_parallel.<backend>`** config key, validated for shape, and the default should seed
`qwen: 2`. Alibaba's concurrency limit is real, undocumented in magnitude, and dynamically adjusted,
so the cap stays conservative and labeled **unmeasured** until a live 2/4/6 run says otherwise.

**Honest limit of that mechanism, quoted from its own documentation:** validation proves the key's
*shape*, "not that a new scheduler or semaphore enforces it" — it is a ceiling the prose dispatcher
respects, not a hard gate. So this is a convention with a config home, not an enforced bound; do not
describe it as enforcement. A hard per-backend semaphore remains future work (Non-goals).

---

## Testing

Stub-first: `scripts/test-qwen-worker-stub.sh` — the name matters, both CI globs (`shellcheck
scripts/*.sh`, the `scripts/test-*.sh` loop) pick it up with **zero workflow-file edits** required.

**The stub test must place a FAKE `qwen` first on `PATH` and ALWAYS run — it must never skip on the
real binary's absence.** This corrects an instruction inherited from the archaeology audit and carried
into the previous revision of this spec. The two test types are not the same shape: `test-zai-worker-stub.sh`
injects a fake `claude` and has no `command -v` guard at all, while only `test-zai-wire-smoke.sh` skips
without the real CLI. Telling the *stub* to skip when `qwen` is missing would disable it precisely in
CI, where no `qwen` is installed — leaving credential scrubbing, pinned argv, timeout handling, the
scope gate, and the model-identity assertion **completely untested** while appearing green. Cover the
same five paths the zai stub proves: success / blocked / timeout / non-zero-exit / model-mismatch
(the qwen analogue of zai's `nonglm` mode, exercising the envelope assertion above). Add an
ancestor-`.env` fixture that must fail closed.

Only `scripts/test-qwen-wire-smoke.sh` carries the `command -v qwen || { echo SKIP; exit 0; }` guard.

**A stub cannot catch a flag-semantics inversion** — this spec exists because a docs-only reading
already produced one (`--sandbox`'s arity and precedence). A real-binary, no-network smoke test
(`scripts/test-qwen-wire-smoke.sh`, mirroring `test-zai-wire-smoke.sh`) against a local stub HTTP
endpoint is required before shipping as verified, not optional polish.

---

## Files touched

Thirteen independent registration sites, per the archaeology audit's matrix — this backend is not one
switch. **New:** `scripts/compound-v-run-qwen-worker.sh`, `skills/backend-launcher/adapter-qwen.md`,
`scripts/test-qwen-worker-stub.sh`, `scripts/test-qwen-wire-smoke.sh`.

**Edited — shared/contended, ordering matters:**
- `scripts/compound-v-resolve-model.py` — `BACKENDS`, the built-in tier-map placeholder, selftest
  additions. **Single job** — do not split; it's loaded by-path elsewhere and any partial edit breaks
  every backend's resolution.
- `scripts/compound-v-validate-manifest.py` — `VALID_BACKENDS`, the worktree-required tuple, **the
  reviewer block-list tuple** (the corrected, load-bearing edit this draft's first version missed),
  **the opt-in acknowledgment gate**, docstring, new `QWEN_*` selftest fixtures. Backs the
  partition-reviewer agent; CI-run against every tracked historical manifest. **No
  `max_parallel ≤ 2` invariant** — an earlier revision of this list demanded one, contradicting
  this spec's own Model-resolution section, Non-goals, and AC 7d, all of which correctly use the
  existing `backend_max_parallel` config key instead. The config key wins; the invariant is not built.
- `scripts/compound-v-classify-failure.py` — `_QWEN_RULES` seeded with the real needles above,
  `classify()` branch, `--backend` choices, a selftest guard against the codex-fallthrough bug.
- `scripts/compound-v-failure-policy.py` — `FALLBACK` entry and **`CONCRETE_BACKENDS`** (a second
  tuple the audits predate). **No retry/circuit-break behavior change**: `qwen` takes the global
  defaults, and PR #7's existing throttle-vs-window handling is already correct for this provider
  (see Failure classification). Selftest cases only.
- `skills/compound-v/state-machine.md` — backend mentions only; **no circuit-break semantic change**
  (the earlier revision's retry-branch requirement was withdrawn).
- `scripts/compound-v-usage-extract.py` — a real `_extract_qwen` branch (qwen's `--output-format json`
  emits a buffered **array**, unlike zai's single document and codex's JSONL — a third shape, not a
  copy of either), plus the `measured:false`-on-empty-usage guard and selftest.
- `scripts/compound-v-pool-state.py` — **new site the audits predate.** Backend tuple **and**
  `backend_available()`, which must return available for `qwen` only when the key is set **and** a
  sandbox provider works. Falling through to its `return True` default would silently defeat the
  mandatory-sandbox claim at routing time.
- `scripts/compound-v-project-config.py`, `scripts/compound-v-dashboard.py` — **new sites the audits
  predate.** Backend tuples (dashboard also renders per-backend cooldowns).
- `schemas/job_result.schema.json` — `usage.backend` description string only.
- `skills/backend-launcher/SKILL.md` — adapter table row. **Must land AFTER `adapter-qwen.md` exists**
  — the repo's dead-link CI gate scans every `.md` file and fails on an unresolved link.
- `skills/compound-v/routing-policy.md`, `skills/compound-v/execution-manifest.md`,
  `skills/compound-v/phase-3-parallel-opus-dispatch.md` (**missed by the first draft**),
  `agents/parallel-dispatcher.md` — backend enum/table entries.
- `commands/v-init.md` — a new qwen capability-probe section (asserting Node ≥22 per the runtime
  floor above), config examples.
- `commands/v-models.md` — a qwen discovery section (prose, like opencode's — no script change; qwen
  discovery is not a ranking-script fit).
- `commands/v-status.md` (**missed by the first draft**) — only if qwen ships unmeasured initially.
- `CHANGELOG.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — **one atomic job**;
  three separate CI steps cross-check all three carry the identical version.

**Confirmed NOT touched** (contrary to a plausible first guess): `.github/workflows/validate.yml` —
every relevant CI step picks up new files by glob, which is exactly why the stub-test naming
convention above is load-bearing, not cosmetic.

**Explicitly out of scope for this PR** (advisor-mode dropped — see Non-goals):
`scripts/compound-v-resolve-model.py`'s `ADVISOR_CONSULTABLE_NONCLAUDE` tuple,
`scripts/compound-v-advisor-consult.sh`'s third pinned arm, and `skills/backend-launcher/adapter-advisor.md`'s
priority-ladder prose (independently found to already be stale/wrong about the current codex-only
reality — a pre-existing bug, not introduced by this spec, and not this PR's to fix).

**Ordering constraints for the Partition Map:**
1. `adapter-qwen.md` must exist before any file links to it (dead-link CI gate).
2. `compound-v-resolve-model.py` must carry a resolvable `qwen` tier map before any qwen-related
   selftest fixture in `validate-manifest.py` can pass.
3. The three version-lockstep files are one atomic job.

---

## Non-goals

- **No advisor-mode inclusion in v1.** `qwen` has no proven read-only enforcement mechanism — no
  kernel read-only sandbox like Codex's, no `--permission-mode plan`-equivalent structural
  incapability. `--allowed-tools` looked like a fit and is not one (it bypasses confirmation, doesn't
  restrict). The entire advisor-consult script exists because of a real 2026-07-13 incident where a
  nested agent deleted this repository — shipping an unenforced "no write tools" consult would be a
  regression of that mitigation, not a feature. Revisit only once `--exclude-tools`/`--approval-mode=plan`
  is designed and live-verified as a genuine boundary, not before. This also removes the need to touch
  `ADVISOR_CONSULTABLE_NONCLAUDE` or `compound-v-advisor-consult.sh` in this PR at all.
- **No OAuth path** — Coding Plan is API-key-only; Qwen OAuth is discontinued and headless-incompatible
  regardless.
- **No OpenRouter/BYOK/custom-provider auth paths** — scoped strictly to the Alibaba Coding Plan.
  `--auth-type openai` is pinned explicitly in the worker argv to keep this true structurally, not just
  by convention.
- **No hard per-backend concurrency enforcement.** `backend_max_parallel.qwen = 2` is seeded and
  documented, but it is a ceiling the prose dispatcher respects, not a semaphore — as its own
  documentation says, validation proves shape, not enforcement. A real scheduler-level bound is
  future work, deliberately out of scope.
- **No qwen-specific retry or circuit-break policy**, and no edits to PR #7's failure machinery — the
  existing throttle-vs-window split already behaves correctly for this provider once the classifier
  needles map to the right classes.
- **No extension of `/v:review-plan` or `compound-v-epic-arbiter.py`** to draw on qwen — both are
  Codex-hardcoded today; generalizing either is separate, larger work.
- **No arbiter family-dedup fix** (`compound-v-epic-arbiter.py` has no `qwen`/`glm`/`kimi` needle) —
  same gap `zai` already left, verified still present, not this PR's to close.
- **No change to the `zai` adapter itself — and dropping z.ai is now known to be a GLM downgrade,
  not a lateral move.** An earlier revision said "`glm-5` remains reachable through `qwen` regardless",
  which is true but misleading: **`glm-5.2` is NOT in the Coding Plan catalog** (measured live against
  the operator's own key on both regional endpoints — the catalog is exactly `MiniMax-M2.5`, `glm-4.7`,
  `glm-5`, `kimi-k2.5`, `qwen3-coder-next`, `qwen3-coder-plus`, `qwen3-max-2026-01-23`, `qwen3.5-plus`,
  `qwen3.6-plus`, `qwen3.7-plus`). `glm-5.2` lives on Alibaba's separate **Token Plan**, so cancelling
  the z.ai subscription would move GLM work from 5.2 down to 5. **Decision (2026-08-04): keep `zai`.**
  It remains the only source of glm-5.2. Retiring it is not proposed by this PR.
- **No Token Plan support.** Alibaba's Token Plan carries the newer models (`glm-5.2`, `glm-5.1`,
  `kimi-k2.7-code`, `kimi-k2.6`, `qwen3.7-max`, the DeepSeek v4 family) but is a different
  subscription: different endpoint (`token-plan.ap-southeast-1.maas.aliyuncs.com`), different
  credential (`BAILIAN_TOKEN_PLAN_API_KEY`), and **per-token rather than per-request billing**, which
  invalidates this spec's whole quota model. Explicitly out of scope; revisit as its own change.
- **No `qwen3.8-max`.** Launched 2026-08-03 and absent from the Coding Plan catalog — confirmed twice,
  against the live `/models` endpoint and against Alibaba's own documentation. Do not add it on the
  strength of a launch announcement; add it when the catalog serves it.
- **No live-verified flag set, no "verified" status.** This spec is corrected against the *released
  source*, which is stronger than docs-only but still not a live probe with a real key. The live pass —
  confirming the sandbox precedence fixes actually work, resolving the JSON-shape ambiguity, and
  checking the untrusted-folder backport question — is a required follow-on, not optional polish.
- **No fixing of the pre-existing stale advisor-ladder prose** in `adapter-advisor.md`/
  `advisor-consult.sh` comments (they already misdescribe the current codex-only reality, independent
  of this spec) — out of scope; a genuine but unrelated cleanup.

---

## Acceptance criteria

1. A manifest with `backend: qwen, isolation: worktree` validates; `isolation: direct` fails with a
   message naming the invariant.
2. **Corrected from the first draft:** a `backend: qwen, type: spec_review, tier: deep` job **fails**
   validation, specifically because `qwen` was added to the reviewer block-list tuple — verified by a
   fixture whose only defect is that backend/type combination (not assumed from the CR5-5 gate alone,
   which does not cover a legacy-manifest reviewer job).
3. `compound-v-resolve-model.py --backend qwen --tier {deep,standard,light}` resolves to a real,
   non-raising value from a built-in placeholder map (not `.claude/compound-v.json` alone, which does
   not exist in this repo); `--effort xhigh` is rejected with the project-policy message, not a
   tool-limitation message.
4. The worker's pinned invocation drives sandboxing through `QWEN_SANDBOX` (never a `--sandbox
   <profile>` flag form, which does not exist), and `network: false` is enforced **on both platforms**:
   a `*-closed`/`*-proxied` profile via `SEATBELT_PROFILE` on macOS, and container network denial via
   `SANDBOX_FLAGS` on Linux — tested separately, since `SEATBELT_PROFILE` has no effect on the
   Docker/Podman path.
4a. `/v:init` marks `qwen` **unavailable** (not merely degraded) when no working sandbox provider
    exists — Seatbelt on macOS, a working Docker or Podman on Linux — in addition to the Node ≥22
    probe.
4b. The worker fails closed when it cannot prove containment engaged (a non-empty `SANDBOX` inside the
    child), rather than proceeding unsandboxed under a mandatory-sandbox claim.
4c. The invocation passes `--model "$MODEL"`; a job whose served model (read from the
    `system`/`session_start` envelope, **not** from model-authored structured output) is missing,
    duplicated, or different from the requested model fails closed.
5. The worker never emits `--allowed-tools` believing it restricts tools, never emits bare `--yolo`
   (uses `--approval-mode=yolo` only), never emits `--worktree`, never emits `-p`, never emits
   `--openai-api-key`/`--insecure` in argv, never emits a bare `--resume`.
6. A model-identity assertion fails the job if the response's model does not match the requested
   model.
7. A pre-flight check refuses or quarantines the job if `.qwen/.env`/`.env`/`.qwen/settings.json`/
   `.qwen/QWEN.local.md` exists in the worktree **or in any ancestor directory Qwen's upward search
   reaches**, with a regression fixture planting an ancestor `.env` that must fail closed.
7a. The invocation carries `--safe-mode` and `--max-subagent-depth 1`, and the scratch `QWEN_HOME`'s
    `settings.json` sets `security.folderTrust.enabled` explicitly rather than inheriting the
    documented-off default.
7b. The worker passes the scope-gate allow-list as repeated `--allow` arguments, **never** via a
    child-writable `$ART/write_allowed.globs` file (the reproduced self-rewriting-allow-list defect);
    `set -f` guards the `IFS=":"` split; gate rc `1` is treated as BLOCKED, not as a worker fault.
7c. `qwen` is off by default **enforced by the manifest validator**, not by prose: a manifest naming a
    `qwen` job is **rejected** when the operator-local acknowledgment record is absent or its
    terms-version marker is stale — with fixtures for both the absent and the acknowledged case. The
    record never holds the API key, and lives in gitignored operator-local config.
7d. The seeded config carries `backend_max_parallel.qwen = 2` (the existing PR #6 key — no new
    validator invariant), documented as a dispatcher-respected ceiling, **not** as an enforced bound.
7e. `qwen` appears as a pool member in the **documented example** in `execution-manifest.md`, beside
    `codex` and `zai`. **This PR does not modify `.claude/compound-v.json`** — the operator's live
    rotation (committed as `claude + zai`) is changed only by a deliberate, separate act after this
    PR merges. And `backend_available("qwen")` returns false when either the key or a working
    sandbox provider is missing — proven by a freeze test that records `available: false` and
    continues with the documented warning rather than failing the run.
8. A worker that writes outside `write_allowed` yields `blocked: true` with offending paths in
   `violations`; the caller does not merge.
9. `compound-v-classify-failure.py --backend qwen` maps `THROTTLING.userQPSLimit` and the
   `{concurrency,hour,week,month} allocated quota exceeded` needles (keyed on `errorType`, never
   `message`, which DashScope returns as `null`) plus native exit codes 53/55/130, and fails closed to
   `other` for everything else.
10. `compound-v-failure-policy.py` returns a reroute/bounded retry for a `qwen` quota failure rather
    than a run halt, using the **global** defaults — no qwen-specific retry branch, no change to
    PR #7's machinery. A `usage_window_exhausted` classification must reach the cooldown path, and a
    `rate_limited` one the retry path; that split is what the test asserts.
11. CI runs shellcheck over the new worker script and executes `test-qwen-worker-stub.sh`, which
    **injects a fake `qwen` first on `PATH` and always runs** — it must NOT skip on a missing real
    binary (that would disable it exactly in CI). Only `test-qwen-wire-smoke.sh` carries the
    skip-when-absent guard. Zero edits to `validate.yml` either way.
12. `SKILL.md`'s adapter table lists `qwen` as **auth-pending / coverage-unverified**, and
    `adapter-qwen.md` carries the Compliance section verbatim (EN+ZH) plus the exact verified
    `qwen --version` once a live pass runs — this status must not read as "verified" prematurely.
13. `adapter-qwen.md` states plainly which files would reach Alibaba via Qwen Code's context-file
    system (`AGENTS.md` — this repo's own architecture doc — plus `QWEN.md`/`CONTEXT.md`/
    `.qwen/QWEN.local.md` and `@`-imports), that `--safe-mode` currently suppresses that egress, and
    that dropping `--safe-mode` re-opens it.
