# qwen Code CLI Backend — Code Archaeology

**Audited:** 2026-08-04 · **Spec:** `docs/superpowers/specs/2026-08-04-qwen-code-cli-backend-design.md`
**Repo state:** branch `feat/zai-backend`, HEAD `71b59dc`, plugin version `2.18.0`.
**Method:** every claim below was read out of the named file at the named line. Nothing here is from memory.
**Prior KB:** `docs/superpowers/archaeology/_knowledge-base/` does not exist. The closest prior audit is
`docs/superpowers/archaeology/2026-07-31-zai-backend.md` (42 KB, same subsystem, one backend earlier) — read it
before planning; this audit does not repeat its findings, it extends them to the sites zai's landing changed.

---

## 0. Corrections — where the spec is WRONG about this repo

The spec was written from Qwen Code's docs, not from re-reading this repo. Five of its statements about
existing code do not match the source.

### C1 — The advisor priority list has NO middle tier. It is codex → opus. Full stop.

The spec (§ "New this PR", line 130) says the selector has "a deterministic priority list:
`codex > any other non-claude > opus fallback`" and that "only two of those tiers are actually **driven**".

The real code, `scripts/compound-v-resolve-model.py:362`:

```python
ADVISOR_CONSULTABLE_NONCLAUDE = ("codex",)
```

That is a one-element tuple. `select_advisor()` (line 393) loops it, and if nothing matches, returns the
opus fallback. There is no "any other non-claude" tier to be undriven — it does not exist in the selector
at all. The selftest pins this deliberately (lines 818-823):

```python
expect("selector does NOT offer cursor -> opus fallback (not cursor)", ...)
expect("selector does NOT offer antigravity/devin/opencode -> opus fallback", ...)
```

and line 629 pins the same for `zai`. So the change is **not** "promote qwen out of an existing
undriven tier" — it is "add the second entry ever to a hardcoded one-element allow-list, and delete or
rewrite the four selftest assertions that currently assert the list has exactly one entry."

Where the spec got it: `skills/backend-launcher/adapter-advisor.md:24` prints the ladder as
`codex > any other non-claude (cursor / antigravity / devin / opencode) > opus fallback`, and
`scripts/compound-v-advisor-consult.sh:22,144` repeats it in comments. **Those three prose sites are
stale and contradict the code they describe.** They also predate `zai`, which they never mention. Fixing
them is in scope for this PR, not optional — leaving them would mean a third spec is written from the
same wrong doc.

### C2 — "No hardcoded default tier map" breaks `--selftest`, CI, and advisor selection.

The spec (§ "Model resolution", line 95) says: "**No hardcoded default `deep`/`standard`/`light` map in
this spec**", resolved instead from `.claude/compound-v.json` via `/v:models`. Three facts make that a
hard failure, not a stylistic choice:

1. **`.claude/compound-v.json` does not exist in this repo.** `ls .claude/` returns only
   `compound-v-impact-taxonomy.example.yaml`. Every resolution therefore falls through to the built-in map.
2. **`resolve()` raises on an unresolvable cell** (`compound-v-resolve-model.py:306-310`). With `qwen` in
   `BACKENDS` but absent from `_stance_map()`, `resolve("qwen", "deep")` raises `ValueError`.
3. **The selftest iterates every backend × every tier** (line 521):
   ```python
   for backend in BACKENDS:
       for tier in TIERS:
           r = resolve(backend, tier)                      # <- raises for qwen
           expect(..., r["model"] == DEFAULT_MODELS[backend][tier])   # <- KeyError for qwen
   ```
   Uncaught. And `.github/workflows/validate.yml:280-293` runs `--selftest` on **every** `scripts/*.py`
   that contains the string `--selftest`, under Python 3.9, as a hard CI gate. So adding `qwen` to
   `BACKENDS` without a default map turns CI red on the first commit.

There is a fourth, worse consequence — see S1 below: `select_advisor()` calls `resolve(cand, "deep")` and
does not catch `ValueError`, so a qwen-available run would crash advisor selection for **every**
advisor-eligible job.

The established pattern is the opposite of what the spec proposes: commit `1c232fd feat(zai): register the
backend and its GLM tier map in the resolver` shipped `_ZAI` as a built-in map on the same commit that
registered the backend. `_CURSOR` solves the same "we don't know the models yet" problem with
`{"deep": "auto", "standard": "auto", "light": "auto"}` — a safe placeholder, not an absent map.

### C3 — The reviewer gate does NOT cover qwen generically. It covers it in one of two places.

The spec (§ "Trust tier", line 113-120, and Files-touched line 210) says the CR5-5 gate "already covers
`qwen` generically" and needs no change, because `zai`/`opencode`/`devin` only get an *extra* backend-name
block for model-name reasons that don't apply to qwen. Half right.

There are **two** reviewer gates, not one:

| Gate | Site | Applies to a `backend: qwen` reviewer job? |
|---|---|---|
| CR5-5 `_is_claude_opus()` — fast-path review declaration + sealed receipt | `compound-v-validate-manifest.py:732, 905-946, 1119-1124` | **No.** Only reads `fast_path.review` and the receipt's `reviewer_backend`/`reviewer_model`. A *legacy* (non-fast-path) manifest never enters this code. |
| Invariant 3 — reviewers ⇒ deep/opus | `compound-v-validate-manifest.py:1870-1878` | Partially. `tier: deep` **alone** satisfies it. `backend: qwen, type: reviewer, tier: deep` **PASSES**. |
| Backend-name block list | `compound-v-validate-manifest.py:1835` — `if _is_reviewer(job) and backend_lc in ("devin", "opencode", "zai")` | **No — qwen is not in the tuple.** |

So a `backend: qwen, type: spec_review, tier: deep` job validates cleanly today-plus-`VALID_BACKENDS`.
The spec's acceptance criterion 2 ("a `qwen` reviewer job fails validation under the existing CR5-5 gate,
no new code needed") is **false as written**, and its own instruction to confirm "by test, not assumed" is
what catches it. The reason zai/opencode/devin have that extra block is stated verbatim at lines 1827-1834:
it is *unconditional, independent of tier/model*, precisely because tier-deep alone is not a guarantee.
**`qwen` must be added to the line-1835 tuple** (and its message text), exactly like zai.

### C4 — The sandbox flag is `-s`, and the macOS profile lives in a different env var.

Spec line 14 and line 83 write `--sandbox <profile>` / `--sandbox-image`, and line 39-41 say
`QWEN_SANDBOX=true` "selects `sandbox-exec` (Seatbelt) with named profiles". Qwen Code's own docs
(context7 `/websites/qwenlm_github_io_qwen-code-docs_en`, `users/features/sandbox`) show:

- CLI flag is **`-s`**: `qwen -s -p "analyze the code structure"`.
- `QWEN_SANDBOX=true` selects the **provider** (sandbox-exec on macOS, Docker/Podman on Linux/Windows).
- The named macOS profile is **`SEATBELT_PROFILE`**, a separate variable; a custom profile is a `.sb`
  file under the project's `.qwen/`.
- The image variable is **`QWEN_SANDBOX_IMAGE`** (settings key `tools.sandboxImage`), not `SANDBOX_FLAGS`.
- **Precedence for sandbox is inverted vs. the spec's general table:** "Environment variables take the
  highest precedence, followed by command-line flags, and finally the settings file." The spec's line 50-52
  table says CLI flags win. Both may be true for different settings, but a worker that passes `-s` and
  assumes it wins is relying on the wrong rule.

Since v1 makes the sandbox optional, none of this is load-bearing for shipping — but the invocation block
at spec lines 78-84 is not runnable as written, and must not be transcribed into the worker verbatim.

### C5 — `model.reasoningEffort` is unconfirmed; `--session-id` and `--include-directories` are real.

Spec lines 56-60 assert a `model.reasoningEffort` settings.json field. Three context7 queries against the
official doc set surfaced `tools.sandbox`, `tools.sandboxImage`, `slashCommands.disabled` — **no
`model.reasoningEffort`**. Treat it as unverified, not as a documented fact.

Conversely, the docs surfaced two flags the spec's "Unverified / needs-live-confirmation" list did not know
exist, both of which change the design:

- **`--session-id <uuid>`** — the caller can *supply* the session id (e2e doc:
  `$QWEN --worktree first --session-id "$SESSION_ID" "say hi" --approval-mode yolo --output-format json`,
  with `SESSION_ID=$(uuidgen)`). The spec's open question "exact `--resume` session-id shape" is
  answerable now: it is a UUID, and the worker can pin it rather than scrape it — strictly better than
  zai's regex-anchor approach (`compound-v-run-zai-worker.sh:309-312`).
- **`--include-directories <dir>`** — additive *read* scope, documented in the headless page
  (`qwen -p "…" --include-directories db --output-format json`). It is **not** a `--cd` equivalent. No
  `--cd`/`--dir` flag appears anywhere in the docs, so the spec's open question #2 resolves to:
  qwen needs the **subshell-`cd`** pattern, same as zai (`compound-v-run-zai-worker.sh:246`) and cursor.

---

## 1. Matrix

A backend in this repo is not one switch — it is **13 independent registration sites**. Each is a
separate `if`/tuple/table, none derived from another. This is the real matrix: backends × sites.

Legend: ✅ registered · ❌ absent · n/a not applicable to in-harness claude.

| # | Site (file:line) | claude | codex | antigravity | cursor | devin | opencode | zai | **qwen needs?** |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `resolve-model.py:161` `BACKENDS` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **YES** |
| 2 | `resolve-model.py:139-147` `_stance_map()` default tier map | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **YES — see C2** |
| 3 | `resolve-model.py:362` `ADVISOR_CONSULTABLE_NONCLAUDE` | n/a | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | **YES — first-ever 2nd entry** |
| 4 | `advisor-consult.sh:216-267` `case` arm | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | **YES — third pinned path** |
| 5 | `validate-manifest.py:519` `VALID_BACKENDS` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **YES** |
| 6 | `validate-manifest.py:1819` worktree-required tuple | n/a | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **YES** |
| 7 | `validate-manifest.py:1835` reviewer block tuple | n/a | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | **YES — see C3** |
| 8 | `classify-failure.py:312-326` rules branch | ✅ | ✅(default) | ✅ | ✅ | ❌ | ❌ | ✅ | **YES (fail-closed)** |
| 9 | `classify-failure.py:470-471` `--backend` choices | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | **YES** |
| 10 | `failure-policy.py:64-65` `FALLBACK` | ✅(None) | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | **YES** |
| 11 | `usage-extract.py:61/270-280` measured-vs-unmeasured | ✅(unmeas.) | ✅ | ✅(unmeas.) | ✅ | ✅(unmeas.) | ✅ | ✅ | **YES — spec omits this file** |
| 12 | `scripts/compound-v-run-<b>-worker.sh` | n/a | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **YES (new)** |
| 13 | `skills/backend-launcher/adapter-<b>.md` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **YES (new)** |

**Which cells the spec's "Files touched" misses:** #7 (claims no change needed — wrong, C3), #11
(`compound-v-usage-extract.py` is not listed at all). It also omits every doc-index site enumerated in
§8 below (`phase-3-parallel-opus-dispatch.md`, `commands/v-status.md`) and the two test harnesses.

**Latent gaps this matrix exposes, inherited from zai's own landing:** `devin` and `opencode` are ❌ at
sites #8, #9 and #10. `classify-failure.py:466-468` and `failure-policy.py:60-63` both document this in
comments as "a pre-existing gap, deliberately not changed here" — meaning a devin/opencode credit wall
**halts the entire run** today. qwen must not join them; the spec is right that the `FALLBACK` entry is
"not optional".

**Job-level matrix qwen must handle** (these are the combos the worker itself branches on — read off
`compound-v-run-zai-worker.sh`):

| `read_only` | `write_allowed` | worker writes? | expected `job_result` |
|---|---|---|---|
| false | non-empty, in scope | yes | `success`, `blocked:false` |
| false | non-empty, out of scope | yes | `blocked:true`, offending paths in `violations` |
| true | forced to `""` (line 190-192) | any write | `blocked:true` — every changed path is a violation |
| — | — | exceeds `timeout_sec` | `timeout`, exit 124, `failure_class:"timeout"` |
| — | — | non-zero exit | `error` + classified `failure_class` |

All five paths are covered by `scripts/test-zai-worker-stub.sh`'s five stub modes
(`success|blocked|hang|nonglm|crash`). The qwen stub test must cover the same five, minus `nonglm` unless
an equivalent served-model assertion is built (see D3).

---

## 2. Shared State

### S1 — `select_advisor()` calls `resolve()` and never catches its `ValueError`

`compound-v-resolve-model.py:393-396`:

```python
for cand in ADVISOR_CONSULTABLE_NONCLAUDE:
    if cand in avail and cand != exec_b:
        model = resolve(cand, "deep", stance=stance)["model"]   # raises if no tier map
        return {"advisor_backend": cand, "tier": "deep", "model": model}
```

- **Set where:** `model` comes from `resolve()`, which needs `DEFAULT_MODELS_BY_STANCE[stance]["qwen"]["deep"]`
  or a config override.
- **NOT set when:** `qwen` has no built-in map and no `.claude/compound-v.json` — i.e. this repo's current
  state. `resolve()` raises.
- **Who swallows it:** nobody. `_main_select_advisor()` (line 423) has no try/except; `main()`'s try/except
  (line 481-494) wraps only the *other* code path. The traceback goes to stderr, exit 1.
- **Blast radius:** `compound-v-advisor-consult.sh:154-155` runs the selector with `2>/dev/null` and
  `|| die "advisor selector failed"`. So in a run where `qwen` is in `--available`, **every advisor-eligible
  job's consult dies**, with the traceback discarded — a silent, unattributable failure.

**Gap: `qwen` in `ADVISOR_CONSULTABLE_NONCLAUDE` without a `deep`-tier default map is a crash, not a
degrade.** Fix in the spec (ship a default map), not at review time.

### S2 — `EFFORT` is accepted by the worker but has no documented qwen sink

`compound-v-run-zai-worker.sh:142-146` validates `--effort` against `low|medium|high` and rejects `xhigh`
with a message naming the codex-only rule — then **never uses the value**. zai's adapter calls it
"advisory" (`parallel-dispatcher.md:55`). For qwen:

- **Set by:** the dispatcher, from the manifest's `effort` or `DEFAULT_EFFORT_FOR_TIER` (`resolve-model.py:174`).
- **Sink in qwen:** none confirmed. No `--effort`/`--reasoning` CLI flag exists (spec line 56, matches docs).
  `model.reasoningEffort` in settings.json is **unconfirmed** (C5).
- **Constraint:** the qwen worker must accept-and-validate `--effort` for CLI parity and reject `xhigh`
  with the same message shape, and must **document it as advisory** rather than claim an effect it does not
  have. Do not build the opencode-style in-worktree settings pin for it (see D2).

### S3 — `NETWORK` is accepted and deliberately discarded

`compound-v-run-zai-worker.sh:118-122` takes `--network` and writes `: "$NETWORK"` with a comment: "there
is no network toggle to map it onto. Referenced here so the discard is explicit rather than an oversight —
never claim enforcement that does not exist."

For qwen this is genuinely different: with `-s` engaged, a container/Seatbelt profile **could** map
`network`. But v1 does not require the sandbox, so `network` has no reliable sink. **Constraint: qwen must
copy zai's explicit-discard pattern verbatim, and the adapter must not describe `network` as enforced.**

### S4 — `SERVED_MODEL` (zai's GLM assertion) has no qwen analogue

`compound-v-run-zai-worker.sh:319-330` reads `.modelUsage | keys | .[0]` and fails the job unless it starts
with `glm-`. Its stated purpose (line 314-318): "A non-GLM model means the request did not reach z.ai, and
the job fails rather than letting an unnoticed charge land on some other credential."

- **Set from:** `claude -p --output-format json`'s `.modelUsage` object.
- **NOT set for qwen:** qwen's JSON output has no `.modelUsage`. Two *different* shapes are documented
  (see §4), one of which carries `.model` on the `system/session_start` element.
- **Does qwen need the assertion at all?** The zai assertion exists because zai drives the *Claude* binary,
  which can silently fall back to Anthropic credentials. qwen drives its *own* binary against its own key —
  the failure mode is absent. But `HOME` redirection is still load-bearing for the inverse reason (keeping
  the operator's `~/.qwen` creds out of reach), and the Coding Plan is a **multi-vendor catalog**
  (`glm-5`, `kimi-k2.5` reachable through the same key) so a "did we get the model we asked for" check is
  still meaningful. **Design decision required in the plan; not a copy-paste.**

### S5 — `usage.backend` has no schema enum; unknown backends fail open to unmeasured

`schemas/job_result.schema.json:105-108` — `usage.backend` is `{"type": "string"}` with the backend list only
in the `description`. `usage-extract.py:279-280`: an unrecognized backend returns `_unmeasured(backend)` —
honest nulls, never a fabricated count.

**Gap: safe, but silent.** If qwen is never registered in `usage-extract.py`, every qwen job reports
`measured:false` forever and nobody notices. Given qwen's JSON *does* document usage (§4), this is a real
capability loss. The spec omits the file entirely.

---

## 3. Sibling Code

### `scripts/compound-v-run-zai-worker.sh` (398 lines) — the primary sibling. Read in full.

**Entry conditions / preflight gates** (lines 124-162): all six of `--run-id --job-id --repo --prompt-file
--model --timeout-sec` required; both ids pass `id_is_safe` (`[A-Za-z0-9._-]`, not `.`/`..`); `--repo` and
`--prompt-file` must be absolute; `--repo` must have a `.git`; `jq`/`git`/`python3`/`claude`/`env` must all
be on PATH — **`env` is checked explicitly** (line 156) because it is the vehicle for the credential scrub
and "without it we must NOT silently fall through to an unscrubbed invocation"; `ZAI_API_KEY` must be set.

**Inputs it reads:** `$ZAI_API_KEY`, `$ZAI_BASE_URL` (defaulted), `$TMPDIR`, and the six safe env names in
`_SAFE_ENV_VARS="PATH TMPDIR LANG LC_ALL TERM"` (line 35 — **`HOME` deliberately absent**, replaced with a
scratch dir).

**Edge cases it handles, each earned by a bug:**
- **Credential in argv** (lines 228-238). `env -i` wraps the *supervisor*, not the binary, because `env`
  execs and vanishes while the python supervisor lives for the whole job with the token in its `argv`.
  Measured: `ps -eo command` showed `ANTHROPIC_AUTH_TOKEN=<key>` readable by sibling workers of other
  backends. Fixed by `8214ced fix(zai): stop leaking the z.ai key through process argv`.
- **Self-rewriting allow-list** (lines 352-366). The other five workers write `write_allowed` to
  `"$ART/write_allowed.globs"` and read it back after the child exits. That path is predictable and the
  child has Bash+Write with no confinement, so "a child that writes an out-of-scope file and then appends
  `**` to that file gets back a clean PASS" — **reproduced**. zai passes repeated `--allow` args from
  positional parameters instead. Fixed by `4d0db65`.
- **`env -i` is not enough** (lines 240-245). macOS Python.framework adds `SDKROOT`/`CPATH`/`LIBRARY_PATH`
  etc. to its *own* process at startup, and `Popen` inherits everything — so `--env-only "$ENV_ONLY_NAMES"`
  rebuilds the child env from a named list.
- **No `--cd` on the binary** (line 226): subshell `cd "$WT"`, or "the worker would edit files in the
  LAUNCHER's cwd — the repo root — and the scope gate, which diffs the worktree, would see an empty diff
  and wave through a job that changed nothing."
- **Path separator** (lines 358-366): `set -f` (noglob) around the `IFS=":"` split, because entries are
  literal globs, not paths to expand.
- **Gate exit-code semantics** (lines 369-382): gate rc `1` means BLOCKED and must **not** be fatal;
  only rc `>1` or unparseable output is a worker fault.
- **Idempotent worktree on resume** (lines 178-181): remove any stale worktree, recreate at HEAD.
- **Scratch outside the worktree** (line 169): `ART="$WT.art"` "so the diff stays pristine."

**Latent bugs / open flags in the sibling:**
- **`RUN_ID=""""` — line 96.** Four quote characters. Harmless in bash (concatenation of two empty
  strings) but it is a typo, it survives shellcheck, and copying it forward would propagate it.
- **Project-level `CLAUDE.md` still reaches the third-party endpoint** (lines 290-293): `HOME`/config
  redirection buys only the *user*-level half of isolation; `$WT` is a checkout of this repo so
  `CLAUDE.md` and `.claude/settings.json` are live on every job. Measured with a marker file; disclosed in
  `adapter-zai.md` § Compliance. **qwen inherits this exactly** — `$WT` is the same checkout — and its
  adapter needs the same disclosure. The spec does not mention it.
- `a091185 fix(zai): gate measured:true on non-empty modelUsage, not usage alone` — the usage extractor
  reported `measured:true` with fabricated zeros on a failed job. The equivalent trap exists for any qwen
  usage parse: a well-formed-but-empty usage object must yield `measured:false`, not a zero.

### `scripts/compound-v-run-opencode-worker.sh` (760 lines) — the sibling to NOT copy for config pinning

The spec (line 58-59) proposes applying `effort` "by writing it into a pinned settings.json in the
worktree/scratch before invocation (opencode's pattern)". Read what opencode's pattern actually costs
(lines 334-400): it pins `opencode.json` **inside `$WT`**, and therefore needs a symlink-safety guard
(line 363: "refusing: pre-existing opencode.json is a symlink"), a non-regular-file guard (366), a backup
of any repo-tracked original into `$ART` (382-384), a `rm -f` before every write because `cp` onto the path
would follow a planted link (388-396), and a post-run restore — all so **the scope gate does not see the
pinned config as a job write**.

**qwen does not need any of that**, and copying it would be a self-inflicted 70-line hazard: qwen's config
lives at `$HOME/.qwen/settings.json`, and the worker already redirects `HOME` to a scratch dir *outside*
the worktree (zai's line 169-175 pattern). Write the settings file to `$SCRATCH/.qwen/settings.json` and
the entire in-worktree-pollution class disappears. **Design constraint, not a preference.**

### `scripts/compound-v-advisor-consult.sh` — the two pinned paths

- **codex arm** (lines 217-237): `codex exec --sandbox read-only --skip-git-repo-check --json --model M
  --cd D --output-last-message F PROMPT`. Advice is read from the `--output-last-message` **file**, not
  stdout, because `--json` makes stdout a JSONL event stream.
- **claude arm** (lines 239-260): `claude -p --model opus --permission-mode plan --disallowedTools Write
  Edit MultiEdit NotebookEdit --output-format stream-json --verbose PROMPT`. Advice is the last `result`
  event's `.result`, via `jq -rs`.
- **default arm** (lines 262-266): `die "advisor backend '$ADVISOR_BACKEND' is not supported by the consult
  (B2 supports: codex, claude)"`.

A third arm must supply: a read-only guarantee (a mechanism, not a promise), a stub hook honoring
`$COMPOUND_V_ADVISOR_STUB` with **identical argv** (line 201, 222, 244), and an advice-extraction path.
**The read-only guarantee is the hard part**: codex has a kernel `--sandbox read-only`; claude has
`--permission-mode plan` which is structurally incapable of editing. qwen in v1 has **neither** — `--yolo`
auto-approves everything and `-s` is optional. Running a qwen consult with no write tools is an
*absence of grant*, not an enforced boundary, and this whole file exists because of the 2026-07-13 incident
where "a live nested bypass agent deleted this entire repo" (`adapter-advisor.md:13`). **The plan must name
the concrete mechanism that makes the qwen consult unable to write, or the third path is a regression of
the mitigation.** The `--advisor-backend` override must also be blocked from reaching an unsafe qwen path.

Note the die-message text `"(B2 supports: codex, claude)"` and the header comment list are both
hardcoded strings that must be updated in lockstep with the arm.

---

## 4. External APIs (via context7)

Source: `/websites/qwenlm_github_io_qwen-code-docs_en` (Source Reputation: High, 5720 snippets), queried
2026-08-04. Three queries, the per-question limit.

**Headless invocation — confirmed:**
```bash
qwen -p "query" --output-format json
qwen --continue -p "Run the tests again and summarize failures"
qwen --resume 123e4567-e89b-12d3-a456-426614174000 -p "Apply the follow-up refactor"
qwen --approval-mode auto-edit            # also: yolo
```

**Two CONTRADICTORY documented JSON shapes for the same `--output-format json`:**

| Shape | Source page | Access |
|---|---|---|
| Flat object | `users/features/headless` "Track model and tool usage" | `.response`, `.stats.models[].tokens.total`, `.stats.tools.totalCalls`, `.stats.tools.byName` |
| Buffered array | `users/features/headless` "JSON Output Format" | `[{type:system,subtype:session_start,session_id,model}, {type:assistant,message.usage}, {type:result,subtype:success,session_id,is_error,duration_ms,result,usage}]` |

The `users/features/structured-output` page adds a third note: "In json format, the final element of the
array contains the result", and "the `structured_result` field provides the raw object, which is preferred
over the stringified `result` field."

**This is the single highest-value finding for the worker.** The spec (line 30) states only "returns a JSON
array of message objects" and defers usage/session parsing to live verification. In reality the *docs
themselves* disagree, so a parser written from either page has a 50% chance of silently producing empty
`summary` / `session_id` / `usage` — and empty-but-well-formed is exactly the failure mode
`a091185` had to fix on zai. **The live-verification pass must resolve which shape the pinned version emits,
and the worker must fail loudly (not silently empty) if neither matches.**

**Sandbox — confirmed, and it corrects the spec (see C4):**
```bash
qwen -s -p "analyze the code structure"      # CLI flag is -s
export QWEN_SANDBOX=true                     # picks the provider
```
Precedence, verbatim: "Environment variables take the highest precedence, followed by command-line flags,
and finally the settings file." macOS → `sandbox-exec`; Linux/Windows → require Docker or Podman.
Profile selection is `SEATBELT_PROFILE` (macOS) or a `.sb` file in the project's `.qwen/`.
Image is `QWEN_SANDBOX_IMAGE` / `tools.sandboxImage`.

**Unattended-run warning — confirmed, verbatim:** "Using `--yolo` or `--approval-mode=yolo` in headless or
CI runs automatically approves all tool calls, including sensitive operations like shell, write, and edit.
This mode does not enable a sandbox, meaning tools run with host process privileges."

**Qwen Code has its OWN `--worktree` feature — collision hazard, absent from the spec:**
```bash
$QWEN --worktree first --session-id "$SESSION_ID" "say hi" --approval-mode yolo --output-format json
# creates dirs under  $TEST_DIR/.qwen/worktrees/*
# writes a sidecar at ~/.qwen/projects/$PROJECT_ID/chats/$SESSION_ID.worktree.json
```
If this engages — by flag, by inherited settings, or by a resumed session's sidecar — the model edits files
in a directory that is **not** the git worktree Compound V's scope gate diffs. That is precisely the
"empty diff waves through a job that changed nothing" failure the zai worker documents at line 226.
**The qwen worker must never pass `--worktree`, and the scratch `HOME` must be clean of any sidecar
(guaranteed by `HOME=$SCRATCH`, which also blocks a resumed session from carrying one in).**

**`--session-id <uuid>` is caller-suppliable** (same e2e snippet) — the worker can generate the UUID and pin
it, instead of scraping and regex-validating it the way zai does.

**`--include-directories <dir>`** is additive read scope, documented on the headless page. **No `--cd` /
`--dir` flag appears anywhere in the doc set** ⇒ subshell-`cd` is required, matching zai/cursor.

**NOT verifiable here:** Alibaba Bailian/Model Studio's `BAILIAN_CODING_PLAN_API_KEY`, the
`coding-intl.dashscope.aliyuncs.com/v1` endpoint, the Coding Plan model catalog, and the DashScope error
envelope are Model Studio surfaces, not Qwen Code surfaces — outside this library's docs. Phase 1C owns
them. Recording as **unknown**, not as "verify later": the failure-classifier needles (§ site #8) cannot be
written until a live run supplies real error text, which is why fail-closed-to-`other` is the correct v1
posture and matches opencode's stated gap.

---

## 5. Regression Surface

Ordered by blast radius. Each line: what breaks for existing users if the qwen change is wrong.

1. **`scripts/compound-v-resolve-model.py` — every dispatch in the repo.** Every worker resolves its model
   through this file before launching. A `BACKENDS` entry with no tier map raises `ValueError` on
   `--selftest`, turning **CI red for all backends** (`validate.yml:280-293`), and crashes
   `select_advisor()` (S1). Highest-risk single file in this change.
2. **`ADVISOR_CONSULTABLE_NONCLAUDE` ordering — advisor quality for every existing run.** Inserting `qwen`
   *before* `codex` would silently demote the kernel-read-only-sandboxed advisor to an unsandboxed one for
   every advisor-eligible job. The spec's own ordering (codex first) is correct; the risk is a
   transcription slip.
3. **`scripts/compound-v-advisor-consult.sh` — the 2026-07-13 repo-deletion mitigation.** A third arm that
   can write, or a refactor that weakens the `codex`/`claude` arms' pinned flags, re-opens the exact class
   of damage this script was built to close.
4. **`compound-v-validate-manifest.py` — the partition gate for every run.** It is loaded by
   `partition-reviewer`, by `compound-v-triage-outcomes.py` (imports `verify_sealed_receipt` by path), and
   by CI against `examples/manifest.example.yaml` **and every tracked `docs/superpowers/execution/*/manifest.yaml`**
   (`validate.yml:130-134`). A broken tuple edit fails every historical run manifest.
5. **`compound-v-failure-policy.py` `FALLBACK`** — a missing `qwen` key yields `None`, which `decide()`
   turns into `halt`, **stopping the whole run** on the first quota wall (line 99-106, and the zai selftest
   comment at line 149-151 spells this out).
6. **`compound-v-classify-failure.py`** — without a `qwen` branch, `classify()`'s final `else` is
   `_CODEX_RULES` (line 325). A qwen auth error would be matched by the codex needle `"not logged in"` /
   `"please run \`codex login\`"` and tell the operator to run **`codex login`** to fix a Qwen key. This is
   the exact bug the zai selftest pins at line 396.
7. **`skills/backend-launcher/SKILL.md` / `adapter-*.md` cross-links — CI hard failure.**
   `validate.yml:217-250` scans every `.md` for intra-repo links and fails on any that does not resolve.
   A `SKILL.md` row linking `adapter-qwen.md` before that file exists turns CI red. **Ordering constraint
   for partitioning.**
8. **`.claude-plugin/plugin.json` + `marketplace.json` + `CHANGELOG.md`** — three separate CI steps
   (`validate.yml:43-52`, `54-81`) assert all three carry the identical version. Bumping one without the
   others fails the build.
9. **`schemas/job_result.schema.json`** — a malformed edit fails `jq empty` (line 28-29) and the
   example-conformance check (136-158). The needed change is a description string only; risk is low but
   the file is read by other jobs.
10. **`scripts/test-*.sh` glob** — `validate.yml:210-213` runs **every** `scripts/test-*.sh` with `set -e`.
    A new `test-qwen-worker-stub.sh` that does not SKIP cleanly when `qwen` is absent (the CI runner has no
    `qwen`) fails the build. `test-zai-wire-smoke.sh:20` is the pattern: `command -v claude || { echo "SKIP…"; exit 0; }`.
11. **`shellcheck scripts/*.sh`** (`validate.yml:196-202`) — a new worker script is linted automatically,
    with no CI edit. Any unquoted expansion or SC-warning fails the build.
12. **`usage-extract.py`** — if a qwen branch is added and gets it wrong, it can report `measured:true`
    with fabricated zeros, which the anti-ruflo gate (`validate.yml:160-183`) exists to prevent and
    `a091185` already had to fix once for zai.

---

## 6. DRY Findings

| Duplicate found | Where | Decision |
|---|---|---|
| **Worker script skeleton** — arg parse, `id_is_safe`, absolute-path checks, worktree create/remove, `$ART` scratch, gate invocation, `emit_job_result`, five result paths | 6 near-identical copies: `compound-v-run-{codex,antigravity,cursor,devin,opencode,zai}-worker.sh` | **Copy `zai`, do not refactor.** Six existing copies means a shared library is a separate, repo-wide refactor with six regression surfaces — out of scope and a partition nightmare. But copy the *fixed* zai (post `4d0db65` `--allow` transport, post `8214ced` argv scrub), **not** the pre-fix shape any older worker still has. |
| **Scope-gate allow-list transport** — 5 workers write `$ART/write_allowed.globs`; zai passes `--allow` args | `compound-v-run-zai-worker.sh:352-366` vs the other five | **Use zai's `--allow` transport.** The file transport is a reproduced vulnerability (child rewrites its own allow-list). Do not add a seventh copy of the broken pattern. |
| **In-worktree config pinning** | `compound-v-run-opencode-worker.sh:334-400` | **Do not reuse.** Use `HOME=$SCRATCH` + `$SCRATCH/.qwen/settings.json`. See §3. |
| **Session-id extraction + UUID regex anchor** | `compound-v-run-zai-worker.sh:308-312`; codex worker's `thread.started` capture | **Supersede with `--session-id <uuid>`** (§4) — the caller generates and pins the UUID. Simpler and more reliable than either existing approach. |
| **Advisor ladder prose, 3 stale copies** | `adapter-advisor.md:21-30`, `advisor-consult.sh:22`, `advisor-consult.sh:144` | **Fix all three in this PR.** They already contradict the code (C1) and predate `zai`; a fourth spec written from them would repeat this same error. |
| **`ADVISOR_INELIGIBLE_TYPE_TOKENS` / `VALID_STANCES`** duplicated between resolver and validator | `resolve-model.py:355, 170` ↔ `validate-manifest.py:596, 522` | **Leave as-is.** Both files carry an explicit house-rule comment: "standalone, stdlib-only CLIs; do NOT introduce a shared import. Keep in sync." Respect it — no new import, and do not "fix" it. |
| **Stub-test harness** | `test-zai-worker-stub.sh` (198 lines, 5 stub modes, baked-in behavior because `env -i` scrubs control vars) | **Copy it, not `test-advisor-worker-stub.sh`.** The spec names the advisor stub as the mirror; the zai worker stub is the actual structural match (it proves a *worker*, incl. the `env -i` scrub, which is the property under test). |

**No third credential-injection path is being created:** qwen's is a fourth distinct auth shape
(codex=login, cursor=login, zai=`ANTHROPIC_*` env, opencode=stored-creds/ambient-env,
qwen=`BAILIAN_CODING_PLAN_API_KEY`+`OPENAI_BASE_URL`), each genuinely provider-specific. The shared piece —
`env -i` allow-list + scratch `HOME` — is reused from zai as-is.

---

## 7. Design constraints for the spec — MUST HANDLE

**Non-negotiable. Each is derived from a numbered finding above.**

1. **Ship a built-in `_QWEN` tier map in `_stance_map()`.** "Config-only, no default map" fails
   `--selftest`, fails CI, and crashes `select_advisor()`. If the model names are genuinely unknown, use
   cursor's placeholder strategy (`_CURSOR = {"deep":"auto", ...}` at line 90) or the safest documented
   name, and let `/v:models` override it — but the map must resolve. *(C2, S1)*
2. **Add `qwen` to the reviewer block tuple at `compound-v-validate-manifest.py:1835`**, and to its message
   text. The CR5-5 fast-path gate does **not** cover a legacy-manifest `backend: qwen, type: reviewer,
   tier: deep` job — that combination passes today. Revise acceptance criterion 2 accordingly. *(C3)*
3. **Register `qwen` at all 13 sites in §1.** The two the spec omits are
   `compound-v-validate-manifest.py:1835` and `scripts/compound-v-usage-extract.py`.
4. **Order `ADVISOR_CONSULTABLE_NONCLAUDE` as `("codex", "qwen")`** — codex first, always. And **delete or
   rewrite the four selftest assertions at `resolve-model.py:818-829, 629-637`** that currently assert the
   list has exactly one entry and that no non-codex backend is ever offered. *(C1, R2)*
5. **Name the concrete mechanism that makes the qwen advisor consult unable to write.** codex has a kernel
   read-only sandbox; claude has `--permission-mode plan`. qwen has neither by default. "No write tools
   granted" is not a boundary. If no mechanism exists, do not ship the third pinned path in v1 — the
   selector entry alone (which falls through to opus when the consult refuses) is safer than an unenforced
   consult. *(§3, `adapter-advisor.md:13`)*
6. **Never pass `--worktree` to `qwen`, and keep `HOME=$SCRATCH`.** Qwen Code has its own worktree feature
   that redirects edits away from the git worktree the scope gate diffs, and it persists via a sidecar
   under `~/.qwen/projects/*/chats/<session>.worktree.json` that a resumed session would carry in. *(§4)*
7. **Use subshell `cd "$WT"`.** No `--cd`/`--dir` flag exists in Qwen Code's docs; `--include-directories`
   is additive read scope, not a cwd change. *(C5)*
8. **Resolve the two contradictory documented JSON shapes during live verification, and fail loudly on
   neither-matched.** A parser that silently yields an empty `summary`/`session_id`/`usage` is the
   `a091185` bug class. Prefer `structured_result` over the stringified `result` where present. *(§4, S5)*
9. **Pin the session id with `--session-id $(uuidgen)`** rather than scraping it. *(C5, §6)*
10. **Do not transcribe the spec's invocation block (lines 78-84) into the worker.** `-s` not `--sandbox`;
    `SEATBELT_PROFILE` not a `QWEN_SANDBOX` profile value; `QWEN_SANDBOX_IMAGE` not `SANDBOX_FLAGS`;
    sandbox env vars outrank sandbox CLI flags. *(C4)*
11. **`FALLBACK["qwen"] = "claude"` is mandatory**, not polite — a missing key halts the entire run on the
    first quota wall. *(R5)*
12. **A `qwen` branch in `classify-failure.py` is mandatory even while empty**, plus the `--backend` choices
    entry. Without the branch, the final `else` is `_CODEX_RULES` and a qwen auth failure tells the operator
    to run `codex login`. Fail-closed to `other` is correct; silent absence is not. *(R6)*
13. **Write the qwen settings file (if any) to `$SCRATCH/.qwen/settings.json`, never inside `$WT`.** Do not
    replicate opencode's in-worktree config pin and its 70 lines of symlink guards. *(§3, §6)*
14. **Copy the *post-fix* zai worker:** `--allow`-argument gate transport (not the file), `env -i` wrapping
    the supervisor (not the binary), `--env-only` allow-list, `set -f` around the `IFS=":"` split, gate
    rc=1 ≠ fatal, `$ART` scratch outside `$WT`. Do not copy `RUN_ID=""""` (line 96). *(§3, §6)*
15. **`--effort` and `--network` are accepted, validated, and explicitly discarded** with the same
    comment-the-discard discipline; `xhigh` rejected with the codex-only message. Do not claim either is
    enforced. *(S2, S3)*
16. **Decide, in the plan, whether qwen gets a served-model assertion** (zai's `SERVED_MODEL` analogue).
    The Coding Plan is a multi-vendor catalog behind one key, so "did we get the model we asked for" is
    meaningful — but the mechanism differs and must be designed, not copied. *(S4)*
17. **Name the new stub test `scripts/test-qwen-worker-stub.sh`** so both CI globs pick it up with **zero**
    workflow edits, and make it **SKIP cleanly (`exit 0`) when `qwen` is absent** — the CI runner has no
    `qwen` binary and `validate.yml:210-213` runs the loop under `set -e`. *(R10, R11)*
18. **Create `adapter-qwen.md` before anything links to it.** The dead-link CI gate scans every `.md`
    repo-wide. This is a hard ordering constraint on the partition. *(R7)*
19. **Bump `plugin.json`, `marketplace.json` and the `CHANGELOG.md` heading in one job.** Three CI steps
    cross-check them. *(R8)*
20. **The adapter must disclose that project-level `CLAUDE.md` and `.claude/settings.json` reach the
    third-party endpoint on every job** — `$WT` is a checkout of this repo, exactly as measured for zai.
    *(§3)*
21. **Fix the three stale advisor-ladder prose sites in this PR.** *(C1, §6)*
22. **Status must read `auth-pending / coverage-unverified`** in the SKILL.md table and adapter header
    until a live Coding-Plan pass runs — matching `devin`/`opencode`'s existing wording, not `zai`'s
    "verified live". *(spec AC-11, already correct — hold it.)*

---

## 8. File Touch Map (for Phase 2 partitioning)

**NEW files** — no contention, safe to parallelize once ordering below is honored.

| Path | Note |
|---|---|
| `scripts/compound-v-run-qwen-worker.sh` | New. ~400 lines, copied from `compound-v-run-zai-worker.sh`. Auto-linted by `shellcheck scripts/*.sh`. |
| `skills/backend-launcher/adapter-qwen.md` | New. **Must land BEFORE any file links to it** (dead-link CI gate). |
| `scripts/test-qwen-worker-stub.sh` | New. **Spec omits this.** Name matters — both CI globs key on `test-*.sh`. Must SKIP-exit-0 without `qwen`. |
| `scripts/test-qwen-wire-smoke.sh` | New, optional-but-recommended. **Spec omits this.** The zai precedent: a stub cannot catch a flag-semantics inversion; `test-zai-wire-smoke.sh` exists for exactly that class. |

**EDITED files.**

| Path | Change | Flag |
|---|---|---|
| `scripts/compound-v-resolve-model.py` | `BACKENDS` + `_QWEN` map + `_stance_map()` + `ADVISOR_CONSULTABLE_NONCLAUDE` + ~6 selftest edits + docstring lines 50-52 | **SHARED RESOURCE — CONTENDED.** Two logically separate spec deliverables (worker registration, advisor selector) land in this one file, and it is loaded by-path by `validate-manifest.py` and shelled by `advisor-consult.sh`. **Must be ONE job.** Highest-risk file in the change. |
| `scripts/compound-v-validate-manifest.py` | `VALID_BACKENDS:519` + worktree tuple `:1819` + **reviewer block tuple `:1835`** + docstring `:39-42` (already stale — omits `zai`) + new `QWEN_*_MANIFEST` selftest fixtures near `:2562` + selftest assertions near `:4114` | **SHARED RESOURCE.** Backs the partition-reviewer agent and is CI-run against every tracked historical manifest. |
| `scripts/compound-v-classify-failure.py` | `_QWEN_RULES` (may be empty/fail-closed) + `classify()` branch `:312-326` + `--backend` choices `:470-471` + selftest fixtures incl. the codex-needle-fallthrough guard | — |
| `scripts/compound-v-failure-policy.py` | `FALLBACK` `:64-65` + selftest cases | — |
| `scripts/compound-v-usage-extract.py` | **Spec omits this file.** Either `UNMEASURED_BACKENDS:61` or an `_extract_qwen` + `extract_usage` branch `:270-280` + selftest | — |
| `scripts/compound-v-advisor-consult.sh` | Third `case` arm `:216-267` + die-message text `:265` + stale header comments `:22, :144` | **SHARED RESOURCE.** Security-critical (2026-07-13 mitigation). Same conceptual change as the resolver's advisor entry — consider pairing them in one job. |
| `schemas/job_result.schema.json` | `usage.backend` **description** only `:107` — no enum exists | **SHARED RESOURCE** (schema; CI `jq empty` + conformance check). Tiny, doc-only. |
| `skills/backend-launcher/SKILL.md` | Adapter table row `:121-122` region + backend comment `:22` + frontmatter description `:3` | **SHARED RESOURCE — index/table file.** Must land AFTER `adapter-qwen.md`. |
| `skills/backend-launcher/adapter-advisor.md` | Ladder `:21-30` — **stale, contradicts code; also omits `zai`** | **SHARED RESOURCE** (contract doc). |
| `skills/compound-v/routing-policy.md` | Worktree rule `:289-303` + advisor section `:439-467` | **SHARED RESOURCE** (routing authority). |
| `skills/compound-v/execution-manifest.md` | `backend` enum `:38` + tier table `:57-59` + config examples `:67-87` + usage backend list `:257` | **SHARED RESOURCE** (manifest schema-of-record). |
| `skills/compound-v/phase-3-parallel-opus-dispatch.md` | Backend dispatch list `:98-103` + resolve step `:145-148` | **Spec omits this file.** **SHARED RESOURCE.** |
| `agents/parallel-dispatcher.md` | Backend table row `:55` | **SHARED RESOURCE** (agent contract). |
| `commands/v-init.md` | New `### 1a-septies` qwen probe section (note: existing `1a-sexies` sits *after* `1a-quinquies` — pre-existing ordering bug, worth fixing while here) + config `models` examples `:561-578` + capability record `:685-711` | — |
| `commands/v-models.md` | Frontmatter description `:2` + backend arg list `:17-19` + worker-only note `:25` + a `1g. qwen` discovery section | — |
| `commands/v-status.md` | Unmeasured-backend list `:41` — only if qwen lands unmeasured | **Spec omits this file.** |
| `CHANGELOG.md` | New `## [2.19.0]` heading | **SHARED RESOURCE — version lockstep, CI-enforced.** |
| `.claude-plugin/plugin.json` | `version` `:4` | **SHARED RESOURCE — version lockstep.** Must be ONE job with the two below. |
| `.claude-plugin/marketplace.json` | `version` `:12` | **SHARED RESOURCE — version lockstep.** |

**NOT touched — confirmed by reading, contrary to what a reader might assume:**

- `.github/workflows/validate.yml` — **no edit needed.** `shellcheck scripts/*.sh` (`:202`), the
  `scripts/test-*.sh` loop (`:210-213`), and the `scripts/*.py --selftest` sweep (`:280-293`) all pick up
  new files by glob. This is the reason constraint 17 (naming) is load-bearing.
- `scripts/compound-v-collect-results.py` — the only backend mention is help text at `:1277`. Optional.
- `scripts/compound-v-epic-arbiter.py` — `_FAMILY_NEEDLES:549-552` has no `qwen`/`glm`/`kimi` needle, so a
  qwen ballot buckets as `"unknown"`. The spec correctly declares this a Non-goal; **verified, and it is
  the same gap `zai` left.** Do not touch.
- `scripts/compound-v-codex-review.sh` — Codex-hardcoded. Spec Non-goal. Verified, do not touch.
- `scripts/compound-v-discover-models.py` — Gemini/agy-specific ranking (`_family_of`, `propose(family="Gemini")`).
  Not generic. qwen discovery is a `/v:models` prose step like opencode's, not a script change.
- `docs/superpowers/architecture/*.md` — generated by `/v:onboard`. Refresh separately, not in this PR.

**Ordering constraints for the Partition Map:**
1. `skills/backend-launcher/adapter-qwen.md` must exist before `SKILL.md`, `routing-policy.md`,
   `phase-3-parallel-opus-dispatch.md`, or `parallel-dispatcher.md` link to it (dead-link CI gate).
2. `scripts/compound-v-resolve-model.py` must carry a resolvable `qwen` tier map before
   `compound-v-advisor-consult.sh`'s third arm or any qwen selftest in `validate-manifest.py` can pass.
3. The three version files (`plugin.json`, `marketplace.json`, `CHANGELOG.md`) are one atomic job.
