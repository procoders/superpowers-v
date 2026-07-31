# Library & Documentation Audit — `zai` headless GLM worker backend (Phase 1C)

**Spec audited:** `docs/superpowers/specs/2026-07-31-zai-backend-design.md`
**Date:** 2026-07-31 (probes re-run 2026-08-01 UTC)
**Installed versions verified on this machine:** `claude 2.1.207`, `codex-cli 0.144.4`
**Auditor scope:** dependency currency + API/flag signatures only. Existing-code reality is Phase 1A; ToS/domain reality is Phase 1B.

---

## 1. Tools Available

| Tool | Status | Notes |
|---|---|---|
| Context7 MCP | ⚠️ Not used | Neither the Claude Code CLI nor the z.ai API is a Context7-indexed library. Both vendors publish first-party docs; those are authoritative and were fetched live. |
| WebFetch / WebSearch | ✅ | Primary source for docs. |
| **Local binary forensics** | ✅ **Primary evidence** | `claude 2.1.207` and the `codex 0.144.4` native binary were inspected directly (`strings`, option-registration tables). |
| **Live localhost stub probes** | ✅ **Primary evidence** | A local HTTP capture server stood in for the Anthropic endpoint. This yields the *actual* wire request `claude -p --bare` emits — headers, model, system blocks, tool definitions — with **no network egress, no API key, no quota spend**. Reproduce: `/private/tmp/.../scratchpad/stub.py`. |
| Dependency manifests | n/a | The spec adds **no** package dependency. `claude`, `codex`, `jq`, `python3` are pre-existing CLI prerequisites. Nothing to pin. |

> Doc-host note: `docs.anthropic.com` and `docs.claude.com` are now **redirects**. Canonical hosts are
> `code.claude.com/docs/en/*` (Claude Code) and `platform.claude.com/docs/en/*` (API). Citations below use the canonical hosts.

---

## 2. Libraries / External Surfaces Mentioned

| Surface | Spec context | Current | Repo-pinned | Maintenance | Status |
|---|---|---|---|---|---|
| Claude Code CLI | The worker process (`claude -p --bare`) | 2.1.207 installed; changelog served through 2.1.220 | 2.1.207 | Very active (≈40 releases in the served window) | 🟢 OK |
| `codex-cli` | Asserted incompatible with z.ai | 0.144.4 | 0.144.4 | Very active | 🟢 OK (claim holds — §5) |
| z.ai GLM Coding Plan API | Anthropic-compatible endpoint | Live; **plan terms revised 2026-07-30** | n/a | Active | 🟡 MEDIUM — see F-8 |
| Anthropic Messages API | Caching semantics the spec reasons about | `2023-06-01` | n/a | Active | 🟢 OK |

No abandoned or deprecated dependency was found. **Every finding below is a semantic/signature drift, not a staleness problem.**

---

## 3. API Signatures Verified

Legend: **M** = measured on this machine via localhost stub; **D** = vendor documentation.

| # | Spec claim | Verdict | Evidence |
|---|---|---|---|
| 1.1 | `--bare` skips hooks, LSP, plugin sync, attribution, auto-memory, background prefetches, keychain reads, CLAUDE.md auto-discovery | ✅ **CONFIRMED** | D+M — `claude --help` reproduces this list verbatim; public doc confirms the discovery half |
| 1.2 | Under `--bare`, auth is strictly env; **OAuth and keychain are never read** | ✅ **CONFIRMED (vendor-stated), ⚠️ not independently reproduced** | D — "Bare mode skips OAuth and keychain reads." My isolation probe was **confounded**: the on-disk OAuth token is expired, so bare *and* non-bare both returned "Not logged in". See F-3 |
| 1.3 | Under `--bare` only `ANTHROPIC_API_KEY` / `apiKeyHelper` are honoured | ❌ **WRONG** | M — `ANTHROPIC_AUTH_TOKEN` **is** honoured under `--bare` and sets `Authorization: Bearer`. See F-1 |
| 1.4 | `--append-system-prompt-file` is the exact flag name and composes with `--bare` | ✅ **CONFIRMED** | D+M — documented on the CLI reference; measured marker text present in the request under `--bare`. Hidden from local `--help` (`.hideHelp()`) but public. Mutually exclusive with `--append-system-prompt` |
| 1.5 | `--permission-mode dontAsk` exists, refuses off-list tools, never blocks headless | ✅ **CONFIRMED, with a carve-out** | D — "denies anything not in your `permissions.allow` rules **or the read-only command set**"; "the session never waits for input". The read-only carve-out is load-bearing → F-2 |
| 1.6 | `--allowedTools` delimiter/syntax for `Read,Grep,Glob,Edit,Write` | ✅ CONFIRMED (syntax) / ❌ **WRONG (semantics)** | D+M — comma **and** space both parse. But `--allowedTools` does **not** determine which tools exist. See F-2 |
| 1.7 | `--output-format json` exposes `.result`, `.session_id`, `.usage.input_tokens`, `.usage.output_tokens`, `.modelUsage`, `.is_error` | ✅ **CONFIRMED (all six)** | M — all six present in a measured result object. `.session_id` is a real RFC-4122 UUID (`8bb63881-b989-46d3-987b-1a04abb53dd8`) → the codex UUID validator is reusable, as claimed |
| 1.8 | None of these flags are deprecated/renamed/unstable | ✅ CONFIRMED (bounded) | D — zero changelog entries for `--bare`, `dontAsk`, `--permission-mode`, `--allowedTools`, `--output-format` across v2.1.179–2.1.220. `--bare` "will become the default for `-p` in a future release" |
| 1.9 | `effort` is advisory — "Claude Code has no reasoning-effort flag"; `xhigh` is codex-only and rejected | ❌ **WRONG (both halves)** | M — `--effort <level>` exists in 2.1.207 accepting `low, medium, high, xhigh, max`; `--effort xhigh` was accepted, not rejected. `anthropic-beta: effort-2025-11-24` rides on every request. See F-6 |
| 2.1 | `ANTHROPIC_AUTH_TOKEN` → `Authorization: Bearer`; `ANTHROPIC_API_KEY` → `x-api-key` | ✅ **CONFIRMED** | D+M — both documented and both measured |
| 2.2 | The API_KEY-under-bare vs AUTH_TOKEN-elsewhere split is deliberate | ❌ **WRONG — accidental, and it breaks the documented z.ai path** | See F-1 (**BLOCKING**) |
| 2.3 | `ANTHROPIC_MODEL` sets the model for a custom endpoint | ✅ **CONFIRMED empirically** | M — `ANTHROPIC_MODEL=glm-5.2` → `"model":"glm-5.2"` on the wire. (Docs only say "Name of the model setting to use"; z.ai instead documents the `ANTHROPIC_DEFAULT_*_MODEL` trio) |
| 3.1 | Anthropic layer `https://api.z.ai/api/anthropic` | ✅ CONFIRMED | [devpack/quick-start](https://docs.z.ai/devpack/quick-start) |
| 3.2 | OpenAI layer `https://api.z.ai/api/coding/paas/v4` | ✅ CONFIRMED | same |
| 3.3 | PAYG differs: `https://api.z.ai/api/paas/v4` | ✅ CONFIRMED | [api-reference/introduction](https://docs.z.ai/api-reference/introduction) |
| 3.4 | Anthropic URL identical for subscription and PAYG | ⚠️ **UNVERIFIABLE** | z.ai publishes **no** Anthropic-compat page outside devpack. Structure confirmed only on the sibling platform ([bigmodel](https://docs.bigmodel.cn/cn/guide/develop/claude/introduction)) |
| 3.5 | Claude Code is officially supported for the Coding Plan | ✅ CONFIRMED | [devpack/tool/others](https://docs.z.ai/devpack/tool/others) — 15 coding tools incl. Claude Code |
| 3.6 | `glm-5.2` and `glm-5-turbo` are current names | ✅ CONFIRMED | [pricing](https://docs.z.ai/guides/overview/pricing); GLM-5.2 released 2026-06-16 |
| 3.7 | Model deprecation notices | ✅ **NONE EXIST** | Exhaustive negative across z.ai + bigmodel indexes. Plans were revised 2026-07-30; **no model was EOL'd** |
| 3.8 | glm-5.1/glm-5/glm-4.6/glm-4.6v/glm-4.5-air "available as user overrides" | ⚠️ **DRIFTED** | Coding Plan is documented as **exactly three models**: GLM-5.2, GLM-5-Turbo, GLM-4.7 → F-5 |
| 3.9 | z.ai maps Anthropic aliases (`claude-opus-4-8`) onto GLM | ❌ **WRONG (as a documented fact)** | Undocumented anywhere. Observed-only behaviour → F-7 |
| 4.1–4.4 | Anthropic caching: prefix-based, order tools→system→messages, `cache_control` breakpoints, TTL | ✅ **CONFIRMED** | [prompt-caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — "Cache hits require 100% identical prompt segments"; "`tools`, `system`, then `messages`"; max 4 breakpoints; 5-min default, 1-hour option (**now GA, not beta-gated**) |
| 4.5 | The cacheable prefix breaks across workers because the system block embeds git status | ✅ **CONFIRMED — measured** | M — `SYS[2]` carries `cache_control:{type:ephemeral}` **and** `CWD:`, `Date:`, `gitStatus:`. The volatile text is inside the cached prefix → F-4 |
| 4.6 | z.ai implements prompt caching "the same way" | ⚠️ **DRIFTED** | [z.ai cache](https://docs.z.ai/guides/capabilities/cache) — **implicit/automatic only**; `cache_control` appears zero times in z.ai docs and OpenAPI; no numeric TTL; documents OpenAI-shaped `usage.prompt_tokens_details.cached_tokens`. Anthropic-endpoint behaviour is **undocumented** → F-9 |
| 5.1 | codex 0.144.4 removed `wire_api = "chat"` | ✅ **CONFIRMED — live** | M — config load fails: ``Error loading config.toml: `wire_api = "chat"` is no longer supported.`` Fails *before* any network call. Removed via [openai/codex#10157](https://github.com/openai/codex/discussions/7782), Feb 2026 |
| 5.2 | z.ai has no Responses API | ✅ **CONFIRMED — five independent sources** | [openapi.json](https://docs.z.ai/openapi.json) (14 paths, no `/responses`), [llms.txt](https://docs.z.ai/llms.txt) (91 entries), bigmodel index (202 entries), release notes, and [zai-org/GLM-5#39](https://github.com/zai-org/GLM-5/issues/39) — an **still-open request to add** it |

---

## 4. Critical Findings 🔴

### F-1 🔴 BLOCKING — `--bare` + `ANTHROPIC_API_KEY` sends the wrong auth header for z.ai

The spec's credential design injects `ANTHROPIC_API_KEY` (from `ZAI_API_KEY`) because `claude --help` says bare-mode auth is "strictly `ANTHROPIC_API_KEY` or `apiKeyHelper`".

**Measured, under `--bare`:**

| Env var set | Header actually sent |
|---|---|
| `ANTHROPIC_API_KEY` | `x-api-key: sk-…` — **no `Authorization` header at all** |
| `ANTHROPIC_AUTH_TOKEN` | `Authorization: Bearer …` — **honoured under `--bare`**, contradicting its own `--help` text |

**z.ai documents the Bearer path only.** [docs.z.ai/devpack/tool/claude](https://docs.z.ai/devpack/tool/claude):

```json
"env": {
    "ANTHROPIC_AUTH_TOKEN": "your_zai_api_key",
    "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic"
}
```

z.ai never mentions `x-api-key`. Corroborating evidence that the spec's *own* probe used Bearer: the spec records capturing `Authorization: Bearer …`, which `ANTHROPIC_API_KEY` **cannot** produce. **The configuration that was probed is not the configuration the spec documents.**

**Impact:** the pinned argv/env may fail auth against z.ai on first live run, and the spec's §2 rationale ("the distinction is real, not accidental") is inverted — the distinction is accidental and points the wrong way.

**Action:** inject `ANTHROPIC_AUTH_TOKEN`, not `ANTHROPIC_API_KEY`. Verify with one live call before merge. If both are wanted for robustness, note they are independent headers and z.ai only documents Bearer.

---

### F-2 🔴 BLOCKING — `--allowedTools` does not control the tool set; `Bash` is **not** withheld and `Write`/`Grep`/`Glob` are **absent**

The spec states the worker gets "`Read,Grep,Glob,Edit,Write`, exactly the set the live probe verified" and that "**`Bash` is deliberately withheld**".

**Measured tool definitions on the wire:**

| Invocation | Tools actually sent |
|---|---|
| `--bare --permission-mode dontAsk --allowedTools Read,Grep,Glob,Edit,Write` (**spec argv**) | **`Bash`, `Edit`, `Read`** |
| `--bare` alone (no tool flags) | `Bash`, `Edit`, `Read` — *identical* |
| `--bare --tools default` | `Bash`, `Edit`, `Read` — cannot be widened |
| `--bare --tools Edit,Read` | `Edit`, `Read` |
| `--bare --disallowedTools Bash` | **`Edit`, `Read`** ← the actual fix |
| non-bare `--allowedTools Read,Grep,Glob,Edit,Write` | 29 tools incl. `Write`, `WebFetch`, `Agent`, `Cron*` |

Vendor docs agree exactly. [cli-reference](https://code.claude.com/docs/en/cli-reference):
- `--allowedTools` — "Tools that execute **without prompting for permission**. … **To restrict which tools are available, use `--tools` instead**"
- `--bare` — "Claude has access to **Bash, file read, and file edit tools**"

Two consequences, both load-bearing:

1. **`Bash` is present**, contradicting the spec's security rationale. `--allowedTools` never removed it.
2. **`Write` is absent and cannot be restored in bare mode.** Bare-mode `Edit` is described as *"modify file contents in place"* — so a `zai` worker **cannot create a new file** via tools. The spec's own PR creates new files (`scripts/compound-v-run-zai-worker.sh`, `skills/backend-launcher/adapter-zai.md`). The only creation path left in bare mode is `Bash` — the very tool the spec meant to withhold.

**This is a design contradiction, not a typo:** `--bare` is load-bearing for the 48k-token saving, and `--bare` is exactly what removes `Write`. The plan must resolve the tension explicitly (accept `Bash`; or accept Edit-only workers; or drop `--bare` and pay the tokens; or use `--tools`/`--disallowedTools` deliberately).

**Note on the stub test:** acceptance criterion 4 asserts the pinned argv via a **fake `claude` on `PATH`**. A stub validates argv but cannot reveal that the real binary ignores `--allowedTools` for tool availability. This class of bug is invisible to the planned test.

---

### F-3 🔴 BLOCKING (residual risk) — `HOME` is forwarded, `Bash` is live, and read-only `cat` runs in **every** permission mode

The `env -i` allow-list forwards `HOME`. `~/.claude/.credentials.json` therefore remains readable by the worker process. Three facts compose:

1. `Bash` **is** in the bare-mode tool set (F-2).
2. [permissions#read-only-commands](https://code.claude.com/docs/en/permissions): "Claude Code recognizes a built-in set of Bash commands as read-only and runs them **without a permission prompt in every mode**. These include `ls`, `cat`, `echo`, `pwd`, `head`, `tail`, `grep`, `find`… **The set is not configurable.**"
3. `dontAsk` therefore does **not** stop `cat ~/.claude/.credentials.json`. (The `Read` *tool* is confined to the working directory — but `Bash`/`cat` is not path-scoped.)

So a `zai` worker can read the operator's Anthropic OAuth tokens and echo them into its result summary. That defeats the section's stated purpose — "structurally incapable of billing the operator's Anthropic subscription" — through a channel the threat model does not consider.

Confidence caveat, stated plainly: **I did not demonstrate the exfiltration.** It follows from three separately verified facts. Also, my direct test of the OAuth-isolation claim was **confounded** — the OAuth token on this machine is expired (`expiresAt` 1781914669983), so `--bare` and non-bare both returned "Not logged in"; the differentiator was not exercised.

**Action:** add `--disallowedTools Bash` (measured to remove the tool entirely), and/or drop `HOME` from the allow-list in favour of a scratch `HOME`. Re-run acceptance criterion 7 against `HOME`, not only against `ANTHROPIC_BASE_URL`.

---

## 5. High-Priority Findings 🟠

### F-4 🟠 The cache-prefix argument is right, but the spec missed the flag that fixes it

Measured under `--bare`: system block `SYS[2]` carries `cache_control: {type: ephemeral}` **and** embeds `CWD:`, `Date:`, and `gitStatus:`. The spec's reasoning is correct and now has direct wire evidence.

But Claude Code ships a purpose-built remedy the spec never considers — [`--exclude-dynamic-system-prompt-sections`](https://code.claude.com/docs/en/cli-reference):

> "Move per-machine sections from the system prompt (working directory, environment info, memory paths, git-repo flag) into the first user message. **Improves prompt-cache reuse across different users and machines running the same task.** … Use with `-p` for scripted, multi-user workloads."

That is precisely the spec's problem statement. Two constraints before adopting it: it is a **no-op** when `--system-prompt`/`--system-prompt-file` is set (fine — the spec uses `--append-`), and the doc scopes it to the "git-repo flag", which may not remove the full `gitStatus` text I measured. **Worth a measurement, not an assumption.** It does not overturn the `--bare` decision (which is about tool + hook payload) but it materially changes the "prefix diverges by construction" claim.

### F-5 🟠 The Coding Plan exposes exactly three models — the override list is outside it

[devpack/faq](https://docs.z.ai/devpack/faq): *"Only the following three models can be called: GLM-5.2, GLM-5-Turbo and GLM-4.7."*

The spec's default map (`glm-5.2` / `glm-5.2` / `glm-5-turbo`) is **fully inside** the plan — 🟢 good. But it documents `glm-5.1`, `glm-5`, `glm-4.6`, `glm-4.5-air`, `glm-4.6v` as "available as user overrides… unverified". The missing multiplier is not an oversight: those models **are not plan models**. Using them on a plan key is undocumented and may bill pay-as-you-go or fall outside plan terms. Reframe from "unverified burn" to "outside the Coding Plan's documented model set".

z.ai's own docs are internally inconsistent here — [devpack/latest-model](https://docs.z.ai/devpack/latest-model) recommends `ANTHROPIC_DEFAULT_HAIKU_MODEL: glm-4.5-air`, which the FAQ says cannot be called. Do not build on `glm-4.5-air`.

### F-6 🟠 `--effort` exists and accepts `xhigh` — both halves of the effort claim are wrong

`claude 2.1.207 --help`: `--effort <level>  Effort level for the current session (low, medium, high, xhigh, max)`. Measured: `--bare --effort xhigh` is accepted, and `anthropic-beta: effort-2025-11-24` is on every request.

So "Claude Code has no reasoning-effort flag" is **false**, and "`effort: xhigh` is rejected, since `xhigh` is codex-only" is **false**. The spec cites the existing `claude` adapter as precedent — **that adapter's documentation is stale too**, so this correction likely extends beyond this PR (Phase 1A territory; flagging the fact, not the fix).

Separate, unresolved: whether z.ai *honours* an effort parameter is undocumented. Treating effort as advisory may still be the right call — but for the honest reason (unknown provider support), not the false one (flag doesn't exist).

---

## 6. Medium Findings 🟡

### F-7 🟡 The Anthropic-alias mapping is observed, not documented
No z.ai or bigmodel page documents accepting `claude-opus-4-8` or any `claude-*` id. z.ai documents the inverse — set `ANTHROPIC_DEFAULT_*_MODEL` to **GLM** codes. The spec doesn't depend on aliases (it resolves bare GLM names — correct), but the top-of-document claim "z.ai maps Anthropic names onto GLM" should be marked observed-only and unsupported.

### F-8 🟡 z.ai revised its plans on 2026-07-30 — one day before this spec
[devpack/notice/usage-revision](https://docs.z.ai/devpack/notice/usage-revision): *"The new credits-based plan is now available. Previous plans are no longer sold to new users."* Every credit number in the spec (formula, multipliers 6.9/1.7/24 etc., 2000/12000/28000, 10000/60000/140000, half-rate off-peak, peak Mon–Fri 14:00–18:00 SGT) **verified exact** — but they may describe the legacy plan. Add the retrieval date and note that new subscribers may see different quotas.

Two omissions worth carrying: **weekends are off-peak all day** (for existing subscriptions), and there is a second formula — *MCP tool credit usage = calls × output multiplier*.

### F-9 🟡 z.ai caching is implicit — Anthropic breakpoint semantics do not transfer
z.ai documents *"Automatic Cache Recognition… no manual configuration required"*, reports `usage.prompt_tokens_details.cached_tokens` (OpenAI shape), and gives **no numeric TTL** ("reasonable time limits"). `cache_control` appears **zero times** in z.ai docs or OpenAPI. All z.ai caching examples are on the **OpenAI** endpoint; behaviour on the **Anthropic** endpoint is undocumented in either direction.

The spec's probe saw non-zero `cacheReadInputTokens`, so z.ai does translate into Anthropic-shaped usage fields — but that is **observed, undocumented, and may change**. Practical consequence: breakpoints are not a lever on z.ai; **prompt stability is the only lever**, which *strengthens* F-4's case for `--exclude-dynamic-system-prompt-sections`.

### F-10 🟡 Two `--output-format json` traps
Measured: `{"subtype":"success", ..., "is_error":true, "api_error_status":400}`. **`subtype` reported `success` on a hard 400.** Any collector keying on `subtype` misclassifies failures — `is_error` (which the spec correctly uses) is the right field. Also `modelUsage` was `{}` on the error path; the spec's `measured: true` should be conditioned on non-empty usage so a failed job never records fabricated zeros as real measurements (anti-ruflo).

### F-11 🟡 Accurate but incomplete: context/output limits
1M context / 128K (=131072) output is correct **for glm-5.2 only**, and 1M is **opt-in** via a `[1m]` model suffix ([devpack/latest-model](https://docs.z.ai/devpack/latest-model)). `glm-5-turbo` and `glm-4.7` are **200K** context. Since `glm-5-turbo` is the `light` tier, "GLM's real limits (1M / 131072)" is wrong for part of the spec's own map.

---

## 7. Design Constraints for the Plan

**MUST**
- Inject **`ANTHROPIC_AUTH_TOKEN`** (not `ANTHROPIC_API_KEY`) — z.ai documents Bearer only (F-1).
- Choose the tool set with **`--tools`** and/or **`--disallowedTools`**, never `--allowedTools` — the latter governs prompting only (F-2).
- Resolve the `Write`-vs-`--bare` contradiction explicitly before implementation: under `--bare` the tool set is capped at `Bash, Edit, Read` and cannot be widened (F-2).
- Re-verify AC-7 against **`HOME`**, not only `ANTHROPIC_BASE_URL`; `HOME` exposes `~/.claude/.credentials.json` to read-only `Bash` in every permission mode (F-3).
- Add a live (non-stub) auth smoke test before merge. The stub-only plan cannot catch F-1 or F-2 **by construction**.
- Restrict the default model map to the three documented Coding Plan models (already satisfied), and re-label the override list as outside the plan (F-5).
- Date-stamp every credit/quota figure and cite the 2026-07-30 revision (F-8).
- Gate `measured: true` on non-empty usage; never key success off `subtype` (F-10).

**MUST NOT**
- MUST NOT claim `Bash` is withheld while passing `--allowedTools` (F-2).
- MUST NOT claim `--bare` accepts only `ANTHROPIC_API_KEY` — `ANTHROPIC_AUTH_TOKEN` works (F-1).
- MUST NOT claim Claude Code has no reasoning-effort flag, or that `xhigh` is rejected (F-6).
- MUST NOT state z.ai implements Anthropic prompt caching "the same way", or rely on `cache_control` breakpoints against z.ai (F-9).
- MUST NOT present the Anthropic-alias mapping or the non-plan model list as documented behaviour (F-5, F-7).
- MUST NOT generalise "1M / 131072" across the tier map (F-11).

**CONFIRMED — carry forward unchanged**
- The codex/z.ai incompatibility rationale is **correct on both halves** and independently verified (§5 below). `zai` as its own backend is justified.
- `session_id` is a real RFC-4122 UUID → codex's validator is reusable.
- All six `--output-format json` fields the spec relies on exist.
- Claude Code is an officially supported Coding Plan tool → the compliance argument holds.
- Every z.ai credit/quota/multiplier number is exact.
- No GLM model is deprecated or EOL.

---

## 8. Open Questions for the Human

1. **`Write` vs `--bare` (F-2) — needs a scoping decision, not a fix.** Options: (a) accept `Bash` and drop the withheld-Bash claim; (b) accept Edit-only workers that cannot create files; (c) drop `--bare` and pay ~48k tokens/job; (d) pre-create empty files caller-side so `Edit` suffices. Each changes the PR's shape.
2. **Does `--exclude-dynamic-system-prompt-sections` remove the full `gitStatus` block, or only the "git-repo flag"?** (F-4) One stub probe answers it. If it removes the whole block, the cross-worker cache argument needs rewriting.
3. **Is the legacy or the 2026-07-30 credits plan in force for this key?** (F-8) Changes the quota headroom arithmetic.
4. **Should `zai` inherit `--effort`?** (F-6) The flag exists; z.ai's support for it is undocumented. Advisory-only is defensible — but say why truthfully.
5. **Was the live probe run with `ANTHROPIC_AUTH_TOKEN`?** (F-1) If so, the spec's recorded evidence and its documented design diverge, and the probe log should be re-read before the numbers are trusted as describing the shipped config.

---

## 9. Knowledge Base Updates

Appended to `docs/superpowers/library-audit/_knowledge-base/claude-code-cli-flags.md` (created):
- `--allowedTools` ≠ tool availability; `--tools` / `--disallowedTools` are the availability levers (measured matrix).
- `--bare` tool set is capped at `Bash, Edit, Read`; not widenable; no `Write`.
- `--bare` honours `ANTHROPIC_AUTH_TOKEN` despite `--help`; header mapping table.
- `--effort` exists in 2.1.207 with `xhigh`.
- `subtype:"success"` can accompany `is_error:true`.
- Localhost-stub probe recipe for zero-cost wire inspection.

Appended to `docs/superpowers/library-audit/_knowledge-base/zai-glm-api.md` (created):
- Endpoint matrix; three-model Coding Plan limit; credit formula/multipliers/quotas with the 2026-07-30 revision; implicit-only caching; no Responses API (five sources); 1M-context `[1m]` suffix.

---

## Ranked — spec claims that must be corrected or re-verified before implementation

| # | Severity | Claim | Required action |
|---|---|---|---|
| 1 | 🔴 **BLOCKING** | "`ANTHROPIC_API_KEY` (set from `ZAI_API_KEY`)" under `--bare` | Switch to `ANTHROPIC_AUTH_TOKEN`. z.ai documents Bearer only; `ANTHROPIC_API_KEY` sends `x-api-key`. **Correct + live-verify.** |
| 2 | 🔴 **BLOCKING** | "`Bash` is deliberately withheld" via `--allowedTools` | False. Use `--disallowedTools Bash` or `--tools`. **Correct.** |
| 3 | 🔴 **BLOCKING** | Worker tool set is `Read,Grep,Glob,Edit,Write` | Actual: `Bash,Edit,Read`. **No `Write`** under `--bare` → worker cannot create files. **Re-scope.** |
| 4 | 🔴 **BLOCKING** | "structurally incapable of billing the operator's subscription" | `HOME` + live `Bash` + always-on read-only `cat` reaches `~/.claude/.credentials.json`. **Re-verify AC-7.** |
| 5 | 🟠 HIGH | "the cacheable prefix does not survive across workers… by construction" | True as measured, but `--exclude-dynamic-system-prompt-sections` targets exactly this. **Re-verify.** |
| 6 | 🟠 HIGH | glm-5.1/glm-5/glm-4.6/glm-4.5-air/glm-4.6v as user overrides | Coding Plan = **3 models**. **Re-label as outside the plan.** |
| 7 | 🟠 HIGH | "Claude Code has no reasoning-effort flag"; "`xhigh` rejected" | `--effort` exists, accepts `xhigh`. **Correct.** |
| 8 | 🟡 MED | "z.ai… does something [with caching]" implying Anthropic semantics | Implicit-only, no `cache_control`, no TTL, undocumented on the Anthropic endpoint. **Re-word.** |
| 9 | 🟡 MED | "z.ai maps Anthropic names onto GLM" | Observed-only, undocumented. **Mark as such.** |
| 10 | 🟡 MED | Credit/quota table | Exact, but predates the 2026-07-30 revision by one day. **Date-stamp.** |
| 11 | 🟡 MED | "GLM's real limits (1M / 131072)" | glm-5.2 only, and 1M needs the `[1m]` suffix; `glm-5-turbo` is 200K. **Qualify.** |
| 12 | 🟡 MED | `usage` with `measured: true` | Gate on non-empty usage; don't key success off `subtype`. **Harden.** |
| 13 | ✅ | codex `wire_api` / no z.ai Responses API | **Verified on both halves. No action.** |

**Claims that survived scrutiny unchanged:** the codex incompatibility rationale, the UUID `session_id`, all six JSON field names, Claude Code's official-tool status, every credit multiplier and quota figure, and the absence of any GLM model deprecation.
