# Model Routing & Provider Quota Surfaces — Library Knowledge Base

Maintained by Compound V Phase 1C validator. Append at the bottom. Date-stamp every claim. Cite sources. Never delete prior entries — strike through with `~~old~~` and add `→ updated YYYY-MM-DD: <new>`.

---

## Updated 2026-08-01 — tier model pools (PR 2 of 3)

Audit: `docs/superpowers/library-audit/2026-08-01-tier-model-pool.md`.

### Model-name currency (the three names in the spec's example pool)

- **2026-08-01:** `sonnet` — valid Claude Code alias, resolves to **Sonnet 5** on the Anthropic API. Sonnet 5 requires Claude Code **≥ 2.1.197**. Matches `_CLAUDE_DEFAULT["light"]` / `_CLAUDE_COST_AWARE["standard","light"]` in `compound-v-resolve-model.py:70-71`. Source: <https://code.claude.com/docs/en/model-config>.
- **2026-08-01:** `gpt-5.6-luna` — current. GPT-5.6 ships as three tiers: **Sol** (flagship), **Terra** (everyday), **Luna** (fastest/cheapest). Reached Codex GA **2026-07-09**. Matches `_CODEX["light"]` (`compound-v-resolve-model.py:76`). Known Codex CLI quirk: on **0.143.0** the interactive `/model` picker does **not** list GPT-5.6 models even though `-m gpt-5.6-luna` works — absence from the picker is not absence of the model (openai/codex issue #31873). Sources: <https://openai.com/index/gpt-5-6/>, <https://github.blog/changelog/2026-07-09-openais-gpt-5-6-sol-terra-and-luna-are-now-available-in-github-copilot/>.
- **2026-08-01:** `glm-5-turbo` — exact API model id, confirmed verbatim on z.ai's own model page. GLM-5-Turbo is in the **current** GLM Coding Plan lineup alongside **GLM-5.2** (flagship, 1M context / 128K output) and **GLM-4.7**; GLM-4.6V covers vision-MCP. Not deprecated. Sources: <https://docs.z.ai/guides/llm/glm-5-turbo>, <https://z.ai/subscribe>, <https://docs.z.ai/devpack/overview>.
- **2026-08-01:** Local CLI versions at audit time: `codex-cli 0.144.4`, `claude 2.1.207`. Repo docs claim codex verification on 0.144.1 (2026-07-10/11) — consistent, no drift.

### `opus` is an alias, not a pin — it moved in 2026-07

- **2026-08-01:** The `opus` alias' target **changed with the Claude Code version**, not with the repo's config:
  - `< 2.1.154` → Opus 4.7 / 4.6 depending on provider
  - `2.1.154 – 2.1.218` → **Opus 4.8** on the Anthropic API
  - `≥ 2.1.219` → **Opus 5** on the Anthropic API
  - Claude Platform on AWS resolves `sonnet` → **Sonnet 4.6**, not Sonnet 5.
- **Consequence for this repo:** `compound-v-resolve-model.py` maps `deep → "opus"` in every stance. That string is deterministic; the model behind it is not, and differs between two machines on different Claude Code versions. Anything claiming a reviewer "resolves to opus deterministically" must say *string* or *model*. To pin, use a full name (`claude-opus-5`) or `ANTHROPIC_DEFAULT_OPUS_MODEL`.
- Full alias set accepted by Claude Code `--model`: `best`, `fable`, `sonnet`, `opus`, `haiku`, `sonnet[1m]`, `opus[1m]`, `opusplan`. (This repo forbids `haiku` by policy — enforced by `scripts/lint-frontmatter.py` and CI.)
- Source: <https://code.claude.com/docs/en/model-config>.

### Provider rate-limit / quota introspection — the comparison

- **2026-08-01 — Anthropic: rich, documented headers.** Returned on normal responses, not only 429: `retry-after`; `anthropic-ratelimit-requests-{limit,remaining,reset}`; `anthropic-ratelimit-tokens-{limit,remaining,reset}`; `anthropic-ratelimit-input-tokens-{limit,remaining,reset}`; `anthropic-ratelimit-output-tokens-{limit,remaining,reset}`; plus `anthropic-priority-{input,output}-tokens-{limit,remaining,reset}` on Priority Tier. Reset times are RFC 3339. There is **also** a dedicated **Rate Limits API** for reading configured org/workspace limits programmatically. Note: Claude on **Microsoft Foundry does not** return these headers. Source: <https://platform.claude.com/docs/en/api/rate-limits>.
- **2026-08-01 — OpenAI: documented headers.** `x-ratelimit-limit-requests`, `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-requests`, `x-ratelimit-reset-tokens`; `Retry-After` on some 429s. Source: <https://platform.openai.com/docs/guides/rate-limits>.
- **2026-08-01 — z.ai: no documented headers, but an UNDOCUMENTED quota endpoint exists.** ⚠️ This **refutes** the common claim that z.ai offers no quota introspection.
  - Endpoint: `{base}/api/monitor/usage/quota/limit` — base is `https://api.z.ai` (global) or `https://open.bigmodel.cn` (CN).
  - Returns consumption percentages for the **5-hour rolling window**, the **weekly** quota, and **monthly MCP** usage, plus raw token counts.
  - Auth quirk: the token goes in `Authorization` **without** a `Bearer` prefix.
  - It is **not** in z.ai's published docs — `docs.z.ai/devpack/faq` documents no quota API and points users at the web subscription dashboard. Treat it as reverse-engineered and unstable.
  - Coding Plan credit tiers (2026-08-01): Lite 2,000 / 10,000 · Pro 12,000 / 60,000 · Max 28,000 / 140,000 (5-hour / weekly). Off-peak (outside Mon–Fri 14:00–18:00 SGT) gets a 50% credit discount.
  - Concurrency/rate limits are **plan-tier-dependent and dynamically adjusted** — there is no fixed published per-plan concurrency number. Error 1302 = rate limit reached; error 1113 = insufficient balance.
  - Sources: <https://github.com/guyinwonder168/opencode-glm-quota>, <https://docs.z.ai/devpack/faq>, <https://docs.z.ai/devpack/overview>.

### The conclusion that matters for Compound V

- **2026-08-01:** **Header availability is irrelevant to this orchestrator.** Compound V never speaks HTTP to a provider — it spawns CLI processes (`codex exec`, a Claude subagent, `agy --print`, `cursor-agent -p -f`) and reads stdout/stderr/exit code. No HTTP response header reaches the dispatcher, from *any* provider.
- The repo already encodes this: `scripts/compound-v-classify-failure.py` distinguishes `rate_limited` from `out_of_credits` by **matching stderr text needles** (e.g. `"exceeded retry limit, last status: 429 Too Many Requests"`, `"You've hit your usage limit. Try again in 5 days."`). There is no header parsing anywhere in `scripts/`.
- So any future "quota-aware routing" work must either (a) parse per-CLI usage output, (b) call each provider's own usage API out-of-band, or (c) change the worker boundary. It cannot read headers as a side effect of dispatch.

### Python floor (routing scripts)

- **2026-08-01:** CI floor is **Python 3.9**, still enforced. `.github/workflows/validate.yml` installs 3.12 for the PyYAML-dependent steps, then re-pins to **3.9** and runs **every** script with a `--selftest` under it. New scripts are picked up automatically by that dynamic loop.
- House rule is stricter than the floor: `compound-v-resolve-model.py:54` declares *"Python 3.9-safe (no match, no X|Y unions), stdlib only."*
- 3.9 does **not** have: `itertools.batched` (3.12), `enum.StrEnum` (3.11), `typing.Self` (3.11), `zip(strict=)` (3.10), `match`/`case` (3.10), `X | Y` annotations (3.10), `itertools.pairwise` (3.10), `int.bit_count` (3.10), `dataclass(slots=True)` (3.10).
- 3.9 **does** have: PEP 585 builtin generics (`list[str]`), PEP 584 dict `|` merge, `str.removeprefix`/`removesuffix`, `functools.cache`, `graphlib`.
- Caveat: a dev machine on Python 3.12+/3.14 will run 3.10-only syntax cleanly. Only CI catches it.
