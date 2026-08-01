# Library & doc validation — tier model pools (Phase 1C)

**Spec audited:** [`docs/superpowers/specs/2026-08-01-tier-model-pool-design.md`](../specs/2026-08-01-tier-model-pool-design.md)
**Date:** 2026-08-01 · **Branch:** `feat/tier-model-pool`

> **Revised twice on 2026-08-01**, both times after the Phase 1A archaeologist challenged a finding.
> Corrections are in place at §5, §5a, §5a-bis, §8.1, §8.4, §7.10 and table rows 1, 2, 3; row 13 is new.
>
> **Root cause, stated once because it recurred:** I twice asserted a file's absence from
> branch-local evidence. First the zai design doc (`git ls-files` / `git grep` see only the current
> branch), then — in the very message where I wrote the rule against it — `adapter-zai.md`, which I
> called nonexistent without checking at all. Both are on `feat/zai-backend`.
>
> **The rule is not "verify the spec across refs".** It is: *any* absence claim about *any* path
> needs a ref sweep before it is written down. An absence claim is a positive claim about every ref,
> and needs evidence from every ref.
>
> **And verify the sweep itself.** My first corrected sweep was silently broken: under zsh,
> `"$r:skills/backend-launcher/adapter-zai.md"` is parsed as a **parameter modifier**, not a
> revision spec, and reported the file PRESENT on every ref including branches predating it. A
> sweep that returns "present everywhere" or "absent everywhere" is a bug until proven otherwise.
> The form that works:
>
> ```bash
> /bin/bash -c 'git for-each-ref --format="%(refname)" refs/heads refs/remotes | while read -r r; do
>   git ls-tree -r --name-only "$r" -- "$PATH_" | grep -qx "$PATH_" && echo "PRESENT: $r"; done'
> ```

**Scope note, stated plainly.** This spec adds **no dependency, no lockfile entry, and no new CLI
invocation**. There is therefore **nothing to audit** in the usual Phase-1C sense — no abandoned
package, no version drift, no changed method signature. The five sections below cover only what
actually carries risk here: three model-name strings, three providers' quota surfaces, one config
schema, and one language floor. Sections that would normally exist (Libraries Mentioned, API
Signatures Verified, Critical/High/Medium library findings) are collapsed into
[§1 Nothing-to-validate](#1-nothing-to-validate--stated-explicitly) rather than padded.

---

## 0. Tools available

| Tool | Status |
|---|---|
| Context7 MCP | ❌ **not used** — no library in scope is in a package index. Every verdict below is a live doc/registry URL. |
| WebSearch / WebFetch | ✅ used for all provider verdicts |
| Local CLIs | ✅ `codex-cli 0.144.4`, `claude 2.1.207`; `agy` and `cursor-agent` absent on this machine |
| Dependency manifests | **none exist** — this repo ships no `package.json` / `requirements.txt` / `pyproject.toml`. Its runtime dependency surface is: Python stdlib, `pyyaml` + `jsonschema` (CI-installed only, per `.github/workflows/validate.yml:269`), and external CLIs discovered at run time. |

---

## 1. Nothing-to-validate — stated explicitly

Items a Phase-1C audit would normally produce, and why each is empty here:

- **New libraries / SDKs:** none. The spec's "Tech stack" line is `Python 3.9-safe stdlib. No new
  dependency, no new file format.` — verified accurate against the spec text; nothing in §§1–5
  implies an import beyond `json`/`os` and integer arithmetic.
- **Changed API signatures:** none. No worker script, adapter, or `job_result` field changes
  (spec §"What does not change"). The one signature that *would* change is internal Python
  (`compound-v-resolve-model.py`'s entry point), which is repo code, not a third-party API.
- **Abandoned / deprecated packages:** none in scope.
- **Version-behind findings:** none in scope.

Everything that follows is model-name currency, provider-surface fact-checking, config-schema
precedent, and language-floor checking.

---

## 2. Model names in the spec's example pool

| Name in spec | Backend | Repo map says | Provider says (live) | Verdict |
|---|---|---|---|---|
| `sonnet` | claude | `_CLAUDE_DEFAULT["light"] = "sonnet"` and `_CLAUDE_COST_AWARE["standard"/"light"] = "sonnet"` (`compound-v-resolve-model.py:70-71`) | `sonnet` is a documented Claude Code alias → **Sonnet 5** on the Anthropic API | 🟢 **matches, current** |
| `gpt-5.6-luna` | codex | `_CODEX["light"] = "gpt-5.6-luna"` (`compound-v-resolve-model.py:76`) | GPT-5.6 Sol/Terra/Luna reached Codex GA **2026-07-09**; `codex -m gpt-5.6-luna` is the documented invocation | 🟢 **matches, current** |
| `glm-5-turbo` | zai | no `zai` backend on **this** branch; PR 1 on `feat/zai-backend` maps `light → glm-5-turbo` (see §5) | `glm-5-turbo` is the exact API model id on z.ai; GLM-5-Turbo is in the current Coding Plan lineup alongside GLM-5.2 and GLM-4.7 | 🟢 **name correct, and matches PR 1's map** |

Sources: [Claude Code model configuration](https://code.claude.com/docs/en/model-config) ·
[Claude rate limits (model roster)](https://platform.claude.com/docs/en/api/rate-limits) ·
[OpenAI GPT-5.6 announcement](https://openai.com/index/gpt-5-6/) ·
[GPT-5.6 in Codex, GA 2026-07-09](https://github.blog/changelog/2026-07-09-openais-gpt-5-6-sol-terra-and-luna-are-now-available-in-github-copilot/) ·
[z.ai GLM-5-Turbo model doc](https://docs.z.ai/guides/llm/glm-5-turbo) ·
[z.ai GLM Coding Plan](https://z.ai/subscribe) ·
[z.ai devpack overview](https://docs.z.ai/devpack/overview)

### 2a. Drift found — the `opus` alias moved under the repo's feet 🟡

Not in the spec's pool, but directly load-bearing for the spec's reviewer guarantee.

`compound-v-resolve-model.py` maps `deep → "opus"` in every stance, and the spec's
§"What does not change" leans on that: *"a reviewer must resolve to `deep`/opus deterministically,
and a pool cannot promise that."*

Live doc: the `opus` **alias is not version-deterministic**. Per
[model-config](https://code.claude.com/docs/en/model-config):

> Before v2.1.219, `opus` resolved to Opus 4.8 on the Anthropic API from v2.1.154 […]

and the current provider table gives `opus → Opus 5` on the Anthropic API. **The local
`claude` is 2.1.207**, so on this machine `opus` still resolves to **Opus 4.8**, and the same
manifest on a 2.1.219+ machine resolves to **Opus 5**.

The spec's claim is true at the level of the *string* `"opus"` and false at the level of the
*model*. That is fine for the reviewer invariant as written (the guarantee is "not a weaker
tier", not "one exact checkpoint"), but the spec should not use the word "deterministically"
without saying which layer it means. See correction #4.

### 2b. Drift between repo map and providers — none found elsewhere

Checked every cell of `_CODEX` and both `claude` stance maps against the live rosters:
`gpt-5.6-sol` / `gpt-5.6-terra` / `gpt-5.6-luna` are all current Codex-selectable models, and
`opus` / `sonnet` are both current Claude Code aliases. The repo's own inline comment
("verified live 2026-07-10 on codex-cli 0.144.1") is consistent with local `codex-cli 0.144.4`.
No stale cell.

---

## 3. Provider rate-limit and quota surfaces

The spec's Risks section says token-aware balancing *"would need per-backend quota introspection
that z.ai, for one, does not expose."* That is the factual basis for a Non-goal, so it was
checked directly.

| Provider | Rate-limit response headers | Programmatic quota read | Verdict vs spec |
|---|---|---|---|
| **Anthropic** | ✅ Full family, documented: `retry-after`, `anthropic-ratelimit-{requests,tokens,input-tokens,output-tokens}-{limit,remaining,reset}`, plus `anthropic-priority-*-{limit,remaining,reset}` on Priority Tier. Returned on normal responses, not only 429. | ✅ Also a dedicated **Rate Limits API** (`/docs/en/manage-claude/rate-limits-api`) for reading configured org/workspace limits. | spec is silent on Anthropic — correct to be, see §3a |
| **OpenAI** | ✅ `x-ratelimit-limit-requests`, `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-requests`, `x-ratelimit-reset-tokens`; `Retry-After` on some 429s. | ✅ via the same headers | spec is silent — correct to be |
| **z.ai** | ⚠️ **Not documented.** `docs.z.ai/devpack/faq` documents no `X-RateLimit-*` family; it points users at the **web** subscription dashboard for quota progress. | ⚠️ **A quota endpoint DOES exist** — `{base}/api/monitor/usage/quota/limit` (`https://api.z.ai` global, `https://open.bigmodel.cn` CN), returning 5-hour-window / weekly / monthly-MCP consumption percentages. Auth is the raw token in `Authorization` with **no `Bearer` prefix**. It is **not in z.ai's own published docs** — it is reverse-engineered and depended on by third-party plugins. | ❌ **spec's stated reason is wrong as written** |

Sources: [Anthropic rate limits — Response headers table](https://platform.claude.com/docs/en/api/rate-limits) ·
[OpenAI rate limits](https://platform.openai.com/docs/guides/rate-limits) ·
[z.ai devpack FAQ](https://docs.z.ai/devpack/faq) ·
[z.ai devpack overview (5-hour + weekly credit tiers)](https://docs.z.ai/devpack/overview) ·
[opencode-glm-quota — the endpoint + auth-header shape](https://github.com/guyinwonder168/opencode-glm-quota)

### 3a. The stronger reason the spec should be using

**All three header families are invisible to Compound V, and always will be under this
architecture.** The dispatcher does not speak HTTP to any provider. It spawns CLI processes —
`codex exec`, a Claude subagent, `agy --print`, `cursor-agent -p -f` — and reads their **stdout,
stderr, and exit code**. An HTTP response header never reaches the orchestrator.

The repo already encodes exactly this. [`scripts/compound-v-classify-failure.py`](../../../scripts/compound-v-classify-failure.py)
classifies `rate_limited` vs `out_of_credits` from **stderr text needles** — literally matching
strings like `"exceeded retry limit, last status: 429 Too Many Requests"` and
`"You've hit your usage limit. Try again in 5 days."` (lines 268-271). There is no header
parsing anywhere in `scripts/`.

So: the spec reaches the **right conclusion** (don't build token-aware balancing in this PR) from
a **wrong premise**. z.ai's introspection gap is not the blocker; the CLI-process boundary is —
and that boundary applies to Anthropic and OpenAI too, both of which *do* publish rich headers.
Rewriting the sentence makes the Non-goal stronger and provider-independent. See correction #2.

---

## 4. Config schema precedent for a top-level `pools` key

**A top-level sibling is consistent with the file's existing shape.** ✅

`.claude/compound-v.json` is already a flat bag of independent top-level blocks. Documented and/or
read today: `stance`, `models`, `pre_eval`, `brainstorm`, `memory`, `epic`, `review`,
`workflows_accelerator`. [`commands/v-models.md:246-252`](../../../commands/v-models.md) makes the
sibling convention explicit — *"Merge the confirmed assignments into the config's `models` block.
**Preserve every other key** in the file (`stance`, `memory`, `epic`, `review`,
`workflows_accelerator`, …)."* A new `pools` sibling is preserved automatically by `/v:models` and
violates nothing structural.

Four gaps where the spec is silent about a convention the repo actually has:

**4a. `load_project_config` type-checks every known top-level key; `pools` must join that list.** 🟠
[`scripts/compound-v-project-config.py:101-111`](../../../scripts/compound-v-project-config.py)
raises `ValueError` when `models`, `pre_eval`, or `brainstorm` is present-but-not-an-object. The
spec adds `pools` without adding it to that fail-closed check. Without it, `"pools": "banana"`
silently becomes "no pools", which is a **fail-open** read of a routing key.

**4b. There is no precedent for a *list* in this config, and no `resolve_pools` is specified.** 🟠
Both existing blocks follow one pattern: a `resolve_<block>(cfg) -> (values, warnings)` function
that coerces each bad per-key value to a declared safe default and **returns** warnings rather than
raising (`resolve_pre_eval`, `resolve_brainstorm`). Every value they handle is a scalar or a flat
`{str: str}` map. A pool is a **list of objects** — a shape neither resolver has ever seen. The
spec never says what happens to `[{"backend": "codex"}]` (no `model`), `[{"model": "x"}]`
(no `backend`), `[]`, or a duplicated member. Acceptance criterion 6 covers an *empty filtered*
pool but not a *malformed* one.

**4c. `pools` freezes concrete model strings that `/v:models` will not refresh.** 🟠 *(the real one)*
The `models` map exists precisely so model churn is absorbed by refreshing one map instead of
editing manifests — [`execution-manifest.md:65-67`](../../../skills/compound-v/execution-manifest.md):
*"This is what lets the plugin survive model churn: when models change, refresh the map
(`/v:models`), not the manifests."* And `/v:models` says of itself: *"only `models` is this
command's responsibility"*. So a `pools` block containing `"model": "gpt-5.6-luna"` **re-introduces
exactly the rot the tier vocabulary was built to eliminate**, in a key nothing refreshes.

The fix is available for free in the spec's own shape: **a pool is already keyed by tier.**
`{"backend": "codex"}` plus the enclosing `light` key is sufficient — the existing resolver derives
the model from `(stance, backend, tier)`. Making `model` an *optional* per-member override, rather
than a required field, keeps pools churn-proof and matches the map's precedence rules. See
correction #1.

**4d. Pool members must route *through* `resolve()`, not around it.** 🟠
The spec says *"Pool members inherit the map's rules, and add none. Whatever a `models` cell
accepts today, a pool entry accepts."* That is imprecise — a `models` cell is a bare string; a pool
entry is an object. More concretely, `resolve()` enforces a backend-specific guard that a pool
would bypass if `assigned_model` went straight to a worker:
[`compound-v-resolve-model.py:234-244, 295-301`](../../../scripts/compound-v-resolve-model.py)
rejects any `opencode` model that is not a well-formed `provider/model` string, from *every*
source including an explicit override. A pool member `{"backend": "opencode", "model": "gpt-5.6"}`
must fail the same way. Route pool resolution through
`resolve(backend, tier, stance=…, explicit_model=<pool member's model or None>)` and the guard
holds for free.

**4e. `backend_max_parallel` has no stated location.** 🟡 Spec §5 says *"Add an optional
`backend_max_parallel` map to the config (`{"zai": 4}`)"* without saying whether it is a top-level
sibling, a key inside `pools`, or per-stance. Every other config block in this file has a stated
path. Name it.

---

## 5. `zai` is a cross-branch reference — the link was dead on this branch ✅ RESOLVED

> **Corrected 2026-08-01, after the Phase 1A archaeologist pushed back.** My first draft said the
> zai design doc *"does not exist, tracked or untracked."* **That was wrong, and the method was
> wrong.** I checked with `git ls-files` and `git grep`, which only ever see the **current
> branch's** index — I never queried other refs, and I stated a repo-wide absence on branch-local
> evidence.
>
> The file **does exist**, at `docs/superpowers/specs/2026-07-31-zai-backend-design.md` on
> `feat/zai-backend` (and `fork/feat/zai-backend`). Verified with
> `git cat-file -e feat/zai-backend:<path>` and a sweep of every ref. It is absent *here* only
> because `feat/tier-model-pool` is cut from `main`.
>
> That makes this a **cross-branch reference**, not a broken one — a different defect with a
> different correct fix. Deleting the link would have been wrong: the PR-1 dependency is real and
> load-bearing for a PR 2 of 3.
>
> **Already fixed.** Commit `9ca9059` *"fix(pool): drop a cross-branch link that fails the
> dead-link gate"* (an ancestor of `HEAD`) rewrote spec line 16 to keep the dependency as prose and
> record why it is deliberately not a link. Repo-wide dead-link count is now **0**. No action left.
>
> **Standing rule for the rest of this series:** any doc on a branch cut from `main` that
> references PR 1 hits this gate. The shape that works is a prose branch-dependency note plus a
> bare backticked filename — never the `](…)` sequence, and backticks alone do **not** protect it.

What remains true, and is what actually matters for the plan: **`zai` is not a usable backend on
this branch.** Concretely, on `feat/tier-model-pool`:
- `BACKENDS` in `compound-v-resolve-model.py:144` = `("claude", "codex", "antigravity", "cursor", "devin", "opencode")` — no `zai`.
- `VALID_BACKENDS` in `compound-v-validate-manifest.py:519` — identical list, no `zai`.
- `FALLBACK` in `compound-v-failure-policy.py:59` = `{"codex": "claude", "antigravity": "claude", "cursor": "claude", "claude": None}` — no `zai` (and, separately, no `devin`/`opencode` either).
- `compound-v-classify-failure.py` has per-backend needle sets for codex/claude/antigravity/cursor — none for zai.
- No `skills/backend-launcher/adapter-zai.md`.

The gate history, for the record: before `9ca9059` the repo-wide scan (CI logic reproduced locally)
found **1** dead link and it was spec line 16. After `9ca9059`: **0**.

### 5a. Claims that reference the zai adapter — re-checked against PR 1

**Corrected.** My first draft filed these as UNVERIFIABLE-AS-WRITTEN because I could not see a zai
adapter. Having read `2026-07-31-zai-backend-design.md` on `feat/zai-backend`, most of them are in
fact substantiated there — by live probes dated 2026-07-31/08-01 against `claude 2.1.207` and
`codex-cli 0.144.4`. They are unresolvable **from this branch**, which is not the same as unfounded.

- §5: *"`zai` defaults to 4, per its adapter"* — ✅ **substantiated, and the citation is correct.**
  `skills/backend-launcher/adapter-zai.md` **does exist** on `feat/zai-backend` (commit `ed309ad`).
  Line 112 verbatim: *"Six concurrent real jobs completed clean with zero 429s. z.ai publishes no
  concurrency limit and states limits adjust dynamically with plan tier; its usage policy recommends
  one project on Lite and one to two on Pro, and one field report claims a concurrent limit of 1 on
  Pro (not reproduced here). Default `max_parallel` for zai is **4** — below the measured ceiling.
  Lower it on Lite."* A measured ceiling with a deliberate margin, in the adapter, exactly where the
  pool spec says it is. My independent finding — no published concurrency number, adjusts by plan
  tier — **corroborates** it.

  > **Retracted.** My revision claimed *"no adapter doc exists yet"* and filed a nit that the spec
  > mis-cites its own source. Both wrong: I asserted the adapter's absence without a ref sweep — the
  > same error I had just written a rule against, one message earlier, on a different path.

  **What genuinely survives, and it is the useful part:** line 112 is **prose in a runbook with no
  consuming code**. A zai job's `max_parallel` comes from the manifest, not from that sentence. So
  when PR 2 pools a tier across providers, **nothing reads the 4** — which is precisely the gap
  spec §5's `backend_max_parallel` proposes to close. The default is documented but not enforced.
- §4: *"`codex`, `cursor`, `antigravity`, `devin`, `opencode` and `zai` must run in a worktree."* —
  ✅ **substantiated.** PR 1: *"`isolation: worktree` is **mandatory**, a new entry beside the
  existing `codex|antigravity|cursor|devin|opencode ⇒ worktree` invariant"*, with zai placed in the
  lower-trust tier alongside antigravity and cursor.
- `light → glm-5-turbo` — ✅ **matches PR 1's map exactly** (`deep`/`standard → glm-5.2`,
  `light → glm-5-turbo`). PR 1 also probed the subscription's accepted model ids directly and
  confirms `glm-5-turbo` is accepted (rejected siblings include `glm-5-fast`, `glm-5-flash`,
  `glm-5.2-turbo`), and picked it for `light` on measured latency/credit, not on the price table.
- AC 5: *"with `zai` absent, a three-member pool alternates between the remaining two"* — still not
  runnable until PR 1 lands, but that is ordinary branch sequencing, not a defect.

### 5a-bis. Exact status of PR 1, since it sets what PR 2 may assume

PR 1 is **complete work, release-stamped, and not merged.** Both halves matter, so stated precisely:

| Check | Result |
|---|---|
| `git branch -a --contains de78826` (the `release: v2.18.0 — zai backend` commit) | `feat/zai-backend` and `fork/feat/zai-backend` **only** |
| `git merge-base --is-ancestor de78826 main` | **no** |
| `git merge-base --is-ancestor de78826 HEAD` | **no** |
| `git rev-list --count main..feat/zai-backend` | **14** |
| `plugin.json` version | `main` **2.17.0** · `feat/tier-model-pool` **2.17.0** · `feat/zai-backend` **2.18.0** |
| tags matching `v2.17*`/`v2.18*` | `v2.17.0` only — no `v2.18.0` tag |

So "PR 1 is unlanded design" **is** stale — it is implemented, tested, and version-stamped. But
"PR 1 has shipped" would also mislead a planner: it is 14 commits on a side branch, and **`main`
does not have it.** The accurate framing for PR 2's plan is *complete but unmerged*.

**The consequence that does not change:** the spec's example config and example pool
**fail `compound-v-validate-manifest.py` on this branch** — `zai` is in neither `BACKENDS` nor
`VALID_BACKENDS` here, and `adapter-zai.md` is not in this tree. If PR 2 is meant to merge
independently of PR 1 (its own §"Independent of PR 1" says it is), its *examples* must not require
PR 1. That is a documentation-sequencing point, not a claim about zai's soundness.

### 5b. `backend: pool` as an enum value leaks into a second check ⚠️

Spec §2: *"`backend: pool` is a new enum value in the manifest validator."* If implemented as
"append `pool` to `VALID_BACKENDS`", it also becomes valid at
`compound-v-validate-manifest.py:664`, which validates `advisor.advisor_backend` against the same
tuple. `select_advisor` has no `pool` path (`ADVISOR_CONSULTABLE_NONCLAUDE = ("codex",)`), so
`advisor_backend: pool` would pass validation and then die at dispatch. Scope the new value to
`job.backend` only. *(Flagged here because it is an enum/contract fact; the deeper call-site sweep
is Phase 1A's.)*

### 5c. AC 9 does not describe the existing failure policy 🟠

AC 9: *"A job that failed with `rate_limited` or `out_of_credits` has its assignment cleared on
resume, and **the failure policy chooses the next backend**."* The existing failure policy does not
choose "the next backend" — `FALLBACK` is a fixed map in which *every* external backend reroutes to
**`claude`** (`compound-v-failure-policy.py:56-59`). Under a pool, "next" should plausibly mean the
next *pool member*, which is a behaviour change to `failure-policy.py`, not a reuse of it. Also
note `rate_limited` is classified **retryable on the same backend** with backoff
(`RETRYABLE` at line 41), not a reroute — so clearing the assignment on `rate_limited` contradicts
the current policy for that class. Say which behaviour is intended.

---

## 6. Python floor

**CI floor is still 3.9 — confirmed.** ✅ `.github/workflows/validate.yml` installs Python 3.12 for
the PyYAML-dependent steps, then re-pins to **3.9** at the end (lines 242-245) and runs
**every** `--selftest` script under it (lines 266-281: *"✅ all script selftests pass under Python
3.9"*). Any new pool code with a `--selftest` is automatically covered.

**Local skew to be aware of:** this machine's `python3` is **3.14.6**. 3.10+ syntax will run
clean locally and fail only in CI.

Constructs a round-robin counter implementation would plausibly reach for, and which of them 3.9
does not have:

| Construct | Added in | 3.9-safe? | Why it is tempting here |
|---|---|---|---|
| `itertools.batched(iterable, n)` | 3.12 | ❌ | filling a batch under `backend_max_parallel` |
| `zip(a, b, strict=True)` | 3.10 | ❌ | pairing jobs to pool members |
| `match` / `case` | 3.10 | ❌ | branching on `backend == "pool"` vs a real backend |
| `X \| Y` in annotations (PEP 604) | 3.10 | ❌ | `def assign(...) -> dict \| None` |
| `enum.StrEnum` | 3.11 | ❌ | a `Backend`/`Tier` enum |
| `typing.Self` | 3.11 | ❌ | a counter class |
| `itertools.pairwise` | 3.10 | ❌ | walking the assignment sequence in a test |
| `int.bit_count()` | 3.10 | ❌ | — |
| `dataclass(slots=True)` | 3.10 | ❌ | a `PoolMember` record |
| `list[dict]` / `dict[str, int]` annotations | 3.9 (PEP 585) | ✅ | — |
| `d1 \| d2` dict merge (PEP 584) | 3.9 | ✅ | merging config over defaults |
| `str.removeprefix` / `removesuffix` | 3.9 | ✅ | — |
| `functools.cache` | 3.9 | ✅ | — |
| `itertools.cycle` | ancient | ✅ *(but see below)* | the obvious round-robin idiom |

**`itertools.cycle` is 3.9-safe and still the wrong tool.** It is an iterator with no readable
index, so it cannot be serialized into `state.json` and cannot be reconstructed after a crash —
which is the entire point of spec §3's "frozen into `state.json`" and AC 8's "resuming a run whose
counter state was lost". The implementation wants a plain integer per tier and
`members[n % len(members)]`. Flagging it because it is the idiom a reviewer would expect and a
model would write. Note also that the repo's own house rule is stricter than the floor:
`compound-v-resolve-model.py:54` declares *"Python 3.9-safe (no match, no X|Y unions), stdlib
only."*

---

## 7. Design constraints for the plan

**MUST**

1. Add `pools` (and `backend_max_parallel`, wherever it lands) to the structural type check in
   `load_project_config` — present-but-wrong-type must **raise**, matching `models` / `pre_eval` /
   `brainstorm`.
2. Add a `resolve_pools(cfg) -> (values, warnings)` in the same fail-closed style as
   `resolve_pre_eval` / `resolve_brainstorm`: a malformed member is dropped with a warning and the
   job falls back to the `models` cell — never a crash, never a silent wrong route.
3. Resolve every pool member **through** `compound-v-resolve-model.py:resolve()`, passing the
   member's `model` (if any) as `explicit_model`, so the `opencode` `provider/model` guard and the
   stance/tier precedence rules keep firing.
4. Keep the round-robin counter a **plain integer per tier**, persisted in `state.json` alongside
   the per-job assignment. No `itertools.cycle`, no iterator state.
5. Stay inside the Python 3.9 subset the repo already declares — no `match`, no `X | Y`
   annotations, no `zip(strict=)`, no `itertools.batched`, no `StrEnum`. Local `python3` is 3.14
   and will not catch these; only CI will.
6. Scope the new `pool` enum value to `job.backend`. It must not become a legal
   `advisor.advisor_backend`.
7. ~~Fix the dead link to `2026-07-31-zai-backend-design.md` before any PR to `main`, or CI fails.~~
   → **done 2026-08-01 in `9ca9059`.** Standing rule for the rest of the series: reference PR 1 as
   prose plus a bare backticked filename. The gate is line-based and backticks do not protect a
   `](…)` sequence.

**MUST NOT**

8. Do **not** require `model` on a pool member. A tier-keyed pool already has enough information;
   requiring a concrete string re-creates the churn problem the `models` map exists to solve, in a
   key `/v:models` does not refresh.
9. Do **not** ship the spec's example config as-is **if PR 2 may merge before PR 1**.
   `{"backend": "zai", …}` fails `compound-v-validate-manifest.py` on this branch, and the spec's
   own §"Independent of PR 1" claims PR 2 stands alone. Either use `claude` + `codex` in the
   examples and mention zai as a future member, or drop the independence claim and declare PR 1 a
   merge prerequisite. Pick one — the spec currently does both.
10. Do **not** justify the no-quota-balancing Non-goal on "z.ai does not expose quota
    introspection". Lead with the CLI-process boundary — it is provider-independent and permanent.
    And do **not** let PR 3 build rate-limit rerouting on `{base}/api/monitor/usage/quota/limit`:
    an undocumented, reverse-engineered endpoint carries no compatibility promise, so it buys a
    number at the price of a dependency that can vanish without notice.

---

## 8. Open questions for the human

1. ~~**Is `2026-07-31-zai-backend-design.md` supposed to exist?**~~ → **answered 2026-08-01.** Yes;
   it is on `feat/zai-backend`. Replacement question: **must PR 1 merge before PR 2?** The spec
   says PR 2 is "Independent of PR 1", yet every example it ships needs `zai` to be a valid
   backend. Independence and the examples cannot both stand — see MUST NOT #9.
2. **Should a pool member carry a `model` at all?** Recommendation is "optional override only" (see
   MUST NOT #8), but if the operator's intent is *"pin exactly these three checkpoints for this
   run"*, the required-`model` shape is defensible — it just needs a stated policy for who
   refreshes it when a provider retires a model.
3. **What does "the failure policy picks the next backend" mean under a pool** — the next pool
   member, or the existing fixed `→ claude` fallback? And should `rate_limited` clear the
   assignment at all, given the current policy retries it on the same backend with backoff?
4. ~~**Is `backend_max_parallel: {"zai": 4}` a real measured number or a placeholder?**~~ →
   **answered 2026-08-01.** Measured: PR 1 ran six concurrent jobs clean and set 4 as a deliberate
   margin below that ceiling, noting Lite users should lower it. Remaining question is only
   editorial — PR 2 attributes the number to "its adapter", but it currently lives in PR 1's spec
   and no adapter doc exists yet.

---

## 9. Ranked corrections needed to the spec

| # | Severity | Where | Claim as written | Correction |
|---|---|---|---|---|
| 1 | ✅ **RESOLVED** | §"Independent of PR 1", line 16 | a markdown link *"the zai backend"* targeting `2026-07-31-zai-backend-design.md` | ~~The file does not exist.~~ **Corrected:** it exists on `feat/zai-backend`; this was a **cross-branch** reference, and my "does not exist" was branch-local evidence overstated as repo-wide. Fixed in `9ca9059` — dependency kept as prose, no link. Repo dead-link count now 0. |
| 2 | 🔴 **BLOCKING** | §Risks, "A pool hides an unbalanced burn" | *"per-backend quota introspection that z.ai, for one, does not expose"* | **Wrong reason for a right conclusion.** Replace it with the architectural one: workers are **CLI processes**, so no provider's rate-limit headers reach the dispatcher — Anthropic's and OpenAI's included, both of which publish rich header families. `classify-failure.py` already works from stderr text, not headers. That reason is provider-independent and does not expire. *(Footnote, not the argument: z.ai does have a quota endpoint, `{base}/api/monitor/usage/quota/limit` — but it is undocumented and reverse-engineered, so it is a liability to design against, not an asset. Cite it as "exists, unsupported", never as a capability.)* |
| 3 | 🟠 *(re-aimed)* | §5 | *"`zai` defaults to 4, per its adapter"* | ~~UNVERIFIABLE-AS-WRITTEN~~ ~~→ nit: no adapter doc exists~~ → **both retracted.** `adapter-zai.md` line 112 says exactly this; the citation is correct and the number is measured. **The real finding:** that line is prose in a runbook with **no consuming code** — a zai job's `max_parallel` comes from the manifest, so nothing reads the 4. Spec §5's `backend_max_parallel` is what would make it enforceable; say so, since a pool concentrating three jobs on one member is exactly when the unenforced default bites. |
| 4 | 🟠 | AC 9 | *"the failure policy chooses the next backend"* | Does not describe `failure-policy.py`. `FALLBACK` reroutes every external backend to `claude`, and `rate_limited` is classified retry-same-backend, not reroute. State the intended new behaviour explicitly. |
| 5 | 🟠 | §1, "Pool members inherit the map's rules, and add none" | Implies a pool entry and a `models` cell are the same shape | They are not (object vs bare string). Restate as: pool resolution goes **through** `resolve()`, so the map's precedence and the `opencode` `provider/model` guard apply unchanged. |
| 6 | 🟠 | §1 config block | `pools` added with no fail-closed reader specified | Repo convention is a structural raise in `load_project_config` plus a per-key-coercing `resolve_<block>` returning warnings. Spec must say `pools` follows it, and define behaviour for a malformed member (distinct from AC 6's *empty filtered* pool). |
| 7 | 🟠 | §1 config block | `"model": "gpt-5.6-luna"` required per member | Freezes a concrete model in a key `/v:models` does not refresh, defeating the tier vocabulary's stated purpose. Make `model` an optional override; the tier key already resolves. |
| 8 | 🟡 | §"What does not change" | *"a reviewer must resolve to `deep`/opus deterministically"* | `opus` is an alias, not a pin: it resolved to Opus 4.8 before Claude Code 2.1.219 and to Opus 5 after. Deterministic *string*, floating *model*. Say which you mean. |
| 9 | 🟡 | §2 | *"`backend: pool` is a new enum value in the manifest validator"* | Scope it to `job.backend`. The same tuple validates `advisor.advisor_backend`, which has no pool path. |
| 10 | 🟡 | §5 | *"Add an optional `backend_max_parallel` map to the config"* | No path given. Every other block in this file has one. Say top-level vs nested vs per-stance. |
| 11 | 🟡 | §1 | *"Per-stance, exactly like `models`"* | `models` accepts **two** shapes (per-stance, and legacy flat, auto-discriminated by "all top-level keys are stance names"). Say whether `pools` accepts a flat shape too. Tier names and stance names are disjoint, so the same discriminator works — but it needs stating. |
| 12 | 🟢 | §"Tech stack" | *"Python 3.9-safe stdlib"* | **Accurate**, and CI still enforces 3.9. Optionally name the traps (§6 table) so an implementer on a 3.12+ machine does not discover them in CI. |
| 13 | 🟠 *(new, 2026-08-01)* | §"Independent of PR 1" vs every example | *"Independent of PR 1 […] useful with only `claude` and `codex` installed"* | Contradicted by the spec's own examples: the config block, the pool, and AC 5 all require `zai`, which fails `compound-v-validate-manifest.py` on this branch. Either make the examples `claude` + `codex` only, or declare PR 1 a merge prerequisite and drop the independence claim. |

**BLOCKING for merge:** **#2 only.** The Non-goal's stated justification is factually wrong and
would mislead whoever revisits the decision — which matters because PR 3 of this series is
explicitly *"rate-limit rerouting"*, so the next person to touch it is already scheduled.
#1 is resolved (`9ca9059`). #13 is the highest-value remaining item after #2.

---

## 10. Knowledge base updates

Created `docs/superpowers/library-audit/_knowledge-base/model-routing-and-provider-quotas.md` with
the 2026-08-01 entry: the three model-name verdicts, the `opus` alias-drift note, the full
Anthropic / OpenAI / z.ai quota-surface comparison including the undocumented z.ai endpoint, and
the CLI-process-boundary conclusion.
