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

---

## Updated 2026-08-01 (later) — corrections after cross-branch verification

Same audit, revised after the Phase 1A archaeologist pushed back. Recorded because the **method**
error is the reusable lesson.

### Method: never write down an absence claim without a ref sweep — and verify the sweep

- **2026-08-01, learned twice in one session.** The rule is **not** "check the spec across refs". It
  is: *any* absence claim about *any* path needs a ref sweep first. An absence claim is a positive
  claim about every ref. I stated the narrow version of this rule and then broke it one message
  later on a different path (`skills/backend-launcher/adapter-zai.md`, which exists on
  `feat/zai-backend` at commit `ed309ad`).
- **The sweep itself can lie.** Under **zsh**, `"$ref:path/to/file"` is parsed as a **parameter
  modifier**, not a git revision spec. My sweep reported the file present on *every* ref, including
  branches that predate it. Heuristic: a sweep returning "present everywhere" or "absent everywhere"
  is a bug until proven otherwise; spot-check one ref that obviously should not have the file.
- **Form that works** (bash, `ls-tree`, exact-match):
  ```bash
  /bin/bash -c 'git for-each-ref --format="%(refname)" refs/heads refs/remotes | while read -r r; do
    git ls-tree -r --name-only "$r" -- "$P" | grep -qx "$P" && echo "PRESENT: $r"; done'
  ```

### General rule: a uniform result means suspect the harness, not the codebase

- **2026-08-01.** Three separate shell-quirk failures in one session, all producing a *uniform*
  answer that looked like a clean verdict:
  1. **zsh parameter modifier** — `"$ref:path/to/file"` is not a revision spec in zsh. Reported a
     file PRESENT on every ref, including branches predating it.
  2. **zsh subshell PATH loss** — `while … done < <(find …)` lost `PATH`; `dirname`, `sed`, `wc` and
     `tr` all vanished, and the dead-link loop printed an empty count. An empty count reads as
     "0 dead links, clean". Hit independently by both Phase 1A and Phase 1C in this session.
  3. Same shape both times: **the harness broke, the output still looked like an answer.**
- **Rule:** when a check returns everything-present, everything-absent, or nothing-found, suspect
  the harness before believing the finding. Spot-check one case that *must* come out the other way
  — a ref that cannot have the file, a link that is known-broken. If the check cannot produce a
  negative, it is not yet a check.
- **Practical mitigation used here:** port the gate's own regex into Python and run it directly,
  rather than reproducing a shell pipeline. Python has no PATH dependency and no word-splitting or
  modifier surprises.

#### How to report a passing check

- **2026-08-01.** *A passing check is only as trustworthy as its denominator and its ability to
  fail.* `0 dead links` is not a result. **`601 links checked, 0 dead, control detects a planted
  one`** is. Always report all three: how many cases the check actually examined, the verdict, and
  evidence the check can still produce a failure.
- **The negative control must not mutate the tree.** Inject the planted failure **in memory** —
  append it to the file's text inside the scan function — never by writing to a working file. A
  control that edits the repo to prove a point is its own hazard, and a crash mid-run leaves the
  tree dirty. Verified form: real run 601/0; control run 602 checked / 1 dead, the extra one being
  an injected markdown link whose target is a filename known not to exist; tree unmodified
  throughout.

  > **Caught by this very rule, same day.** The first draft of this bullet spelled that injected
  > link out **literally** — creating a real dead link in this knowledge-base file, inside the
  > paragraph warning against exactly that. The next scan found it: `602 links checked, 1 dead`.
  > **Third** occurrence of this mistake in one session, and the first one that a human reviewer
  > would plausibly have shipped. **Describe a broken link; never spell it.** Prose plus a bare
  > backticked filename, always — and re-run the scan after editing any doc *about* the scan.
  >
  > **The general form, and the reason:** *the file most likely to break rule X is the file
  > documenting rule X.* Writing about a construct is the one context that **requires** reproducing
  > it, so a doc explaining a gate is the highest-risk place to violate that gate. This is not
  > specific to dead links — it applies to any lint, any forbidden pattern, any policy with a
  > checker. Phase 1A's audit escaped it only by accident (backticked paths, chosen for line-number
  > citations, not from reasoning about the gate). Treat "I am documenting a rule" as a trigger to
  > run that rule's checker before committing.

- **Scope the injection to exactly one file.** My control matched on `path.endswith(basename)`,
  which hit **two** files with the same basename in different directories, so the counts came out
  `605/4` instead of `602/1` and the control self-reported FAIL. That failure was the control
  working: an assertion tight enough to catch its own sloppiness. Match on the full relative path.
- **A control that only happened to fire does not count.** Phase 1A's first scan legitimately found
  the 3 known-bad links — but only because it ran *before* the fix. Run the same scanner after the
  fix and you get a bare `0` with no way to tell "clean" from "broken". **The control belongs in
  the method, not in the timeline.**
- **Cross-implementation agreement is the strongest form.** Phase 1A and Phase 1C ported the gate
  independently and agreed on **both** the denominator (601) and the verdict (0). Agreement on the
  verdict alone would have been much weaker — two blind scanners also both report 0.

### `git grep` / `git ls-files` are branch-local — never report repo-wide absence from them

- **2026-08-01:** I reported `docs/superpowers/specs/2026-07-31-zai-backend-design.md` as *"does not
  exist, tracked or untracked"* on the strength of `git ls-files | grep -i zai` and `git grep -l`.
  Both read **only the current branch's** index. The file exists on `feat/zai-backend` and
  `fork/feat/zai-backend`.
- **Correct check for a multi-PR series:** `git cat-file -e <ref>:<path>` looped over
  `git for-each-ref --format='%(refname)' refs/heads refs/remotes`. Use this before calling any
  cross-referenced doc missing.
- **Consequence for diagnosis, not just wording:** "missing file" and "cross-branch reference" have
  different correct fixes. Deleting the link would have destroyed a real, load-bearing PR-1
  dependency. The fix that landed (`9ca9059`) kept the dependency as prose and recorded why it is
  deliberately not a link.

### The dead-link gate is line-based and code spans do not protect you

- **2026-08-01:** `.github/workflows/validate.yml` ("Check for dead intra-plugin cross-refs") greps
  `\]\([^)]+\.(md|py|sh|json|ya?ml)[^)]*\)` line by line over every `*.md`. It does **not** respect
  inline code spans — quoting a broken link in backticks still trips it. Only `http*` and `/docs/*`
  targets are skipped. Fenced code blocks are safe only because they rarely contain `](`.
- Practical shape for any doc on a branch cut from `main` that must reference a sibling PR: prose
  branch-dependency note **plus a bare backticked filename**, never the `](…)` sequence.
- This bit two audit files before it was noticed. Cheap to re-check: reproduce the gate's regex in
  Python and run it repo-wide before committing any doc.

### z.ai facts corroborated by PR 1's live probes (`feat/zai-backend`, dated 2026-07-31/08-01)

Independent measurement against a real GLM Coding Plan subscription, `claude 2.1.207` /
`codex-cli 0.144.4`. These **agree with** the doc-derived findings recorded earlier above:

- **Concurrency:** two, four and six simultaneous requests all completed with **zero** 429s.
  `max_parallel` for zai set to a **configurable default of 4** — a deliberate margin below the
  measured ceiling, with guidance to lower it on Lite. Confirms that z.ai publishes no fixed
  concurrency number and adjusts by plan tier.
- **Accepted model ids on the subscription** (probed, not guessed): `glm-5.2`, `glm-5.1`, `glm-5`,
  `glm-5-turbo`, `glm-4.7`, `glm-4.6`, `glm-4.6v`, `glm-4.5-air`, plus Anthropic aliases such as
  `claude-opus-4-8`. **Rejected:** `glm-5.2-air`, `glm-4.6-air`, `glm-5-fast`, `glm-5.2-fast`,
  `glm-5-flash`, `glm-4.6-flash`, `glm-5.2-turbo` — unknown model → `400 [1211]`. Note the
  subscription accepts **more** models than the Coding Plan docs list (docs name only GLM-5.2,
  GLM-5-Turbo, GLM-4.7).
- **zai tier map:** `deep`/`standard` → `glm-5.2`, `light` → `glm-5-turbo`. `light` chosen on
  measured latency/credit, not the multiplier table.
- **Quota error surface is fully published** — `1113, 1302, 1305, 1308, 1310, 1311, 1316, 1317`, all
  HTTP 429, each with a message template. (Distinct from the *quota introspection* endpoint noted
  earlier, which remains undocumented.)
- **Credit formula:** `(input × Mi + cached × Mc + output × Mo) / 10 000`. Multipliers: glm-5.2
  `6.9 / 1.7 / 24`, glm-5-turbo `5.7 / 1.5 / 21`, glm-4.7 `4.6 / 1.2 / 16`, glm-4.6v `1.2 / 0.3 / 2.7`.
- **Transport:** the zai adapter is `claude -p` with `ANTHROPIC_BASE_URL` pointed at z.ai's
  Anthropic-compatible endpoint, in a git worktree, with `HOME`/`CLAUDE_CONFIG_DIR` on scratch. All
  four `ANTHROPIC_*_MODEL` slots take the same resolved GLM name — `…_HAIKU_MODEL` is a Claude Code
  **variable** name filled with a GLM model, so the never-Haiku policy is untouched.
- **Does not change the header conclusion above:** per-job token counts come back in the CLI's own
  JSON output, but no HTTP rate-limit header is exposed to the orchestrator. Quota-aware routing is
  explicitly deferred to **PR 3** ("rate-limit rerouting").

### Guidance for PR 3 — do not build on the undocumented quota endpoint

- **2026-08-01:** `{base}/api/monitor/usage/quota/limit` is real but **reverse-engineered and absent
  from z.ai's published docs**, with no compatibility promise. Designing rate-limit rerouting on it
  buys a number at the cost of a dependency that can change or vanish silently.
- The durable reason to avoid quota-aware balancing is architectural and provider-independent:
  **workers are CLI processes, so no provider's rate-limit headers reach the dispatcher at all** —
  including Anthropic's and OpenAI's, both of which publish rich header families. Lead with that;
  cite the endpoint as "exists, unsupported", never as a capability.
- z.ai's **error** surface is a different matter and is genuinely published (`1113, 1302, 1305,
  1308, 1310, 1311, 1316, 1317`, all HTTP 429) — safe to depend on, and PR 1 already does.

### `max_parallel` for zai is documented but not enforced

- **2026-08-01:** `adapter-zai.md` line 112 sets a default `max_parallel` of **4** for zai (six
  concurrent jobs measured clean; 4 is a deliberate margin; lower on Lite). **It is prose in a
  runbook with no consuming code** — a job's `max_parallel` comes from the manifest, so nothing
  reads that 4.
- Consequence for any pooling/round-robin work: a pool can concentrate several concurrent jobs on
  one member, which is exactly when an unenforced per-backend ceiling matters. A
  `backend_max_parallel` config key is what would make the documented default real.

---

## Updated 2026-08-01 — PR3 cooldown timestamp compatibility

Audit: `docs/superpowers/library-audit/2026-08-01-rate-limit-rerouting.md`.

### Python 3.9 timestamp and JSON traps

- Python 3.9's documented `datetime.fromisoformat()` grammar accepts UTC offsets such as
  `+00:00`, but does not include a terminal `Z`; newer Python documentation demonstrates inputs
  that 3.9 cannot be assumed to accept. A Python-3.9-safe persisted-time helper must explicitly
  normalize terminal `Z` to `+00:00` (or use a narrow `%z` format), reject naive datetimes, compare
  aware UTC values, and emit one canonical UTC representation. Source:
  <https://docs.python.org/3.9/library/datetime.html>.
- Python 3.9's `json` decoder accepts `NaN`, `Infinity`, and `-Infinity` by default even though the
  JSON RFC does not. Numeric state validators must reject booleans/non-finite values explicitly;
  merely requesting `type=int|float` or testing positivity is insufficient. Source:
  <https://docs.python.org/3.9/library/json.html>.

### Provider retry hints remain transport-limited

- Anthropic documents `429 rate_limit_error`, separate `529 overloaded_error`, and two default SDK
  retries for connection/rate-limit/5xx failures while honouring `retry-after` when present:
  <https://docs.anthropic.com/en/api/errors>.
- OpenAI documents `Retry-After` as a minimum only for temporary 429 responses, requires bounded
  attempt/time budgets, and warns that unsuccessful requests consume rate-limit capacity:
  <https://platform.openai.com/docs/guides/rate-limits>.
- z.ai publishes resettable usage-window messages with a `{next_flush_time}` placeholder but does
  not publish that placeholder's concrete timestamp grammar. Parse observed strict formats only;
  an unknown rendering is an absent hint and must degrade to bounded backoff, never locale/timezone
  guessing. Source: <https://docs.z.ai/api-reference/api-code>.
- These contracts do not alter the CLI boundary: Compound V may see rendered text/countdowns, but
  does not receive raw provider headers. Retry counts reported by the orchestrator are worker
  launches; a CLI/SDK may already have made hidden HTTP attempts.
