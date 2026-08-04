**Recon:** docs/superpowers/recon/2026-08-04-qwen-code-cli-backend-adapter.md

# qwen — a headless Qwen Code CLI worker backend

**Goal:** add `qwen` as a seventh dispatch backend, authenticated against Alibaba Cloud's
Bailian/Model Studio "Coding Plan" (the Pro subscription being purchased). Role in v1: an
**implementation worker**, plus a new **cross-brand advisor candidate** alongside Codex. Never a
Review Gate reviewer, never (yet) a plan-review or epic-arbiter voice.

**Architecture:** a Bash-spawned `qwen -p` process — Qwen Code's own native headless mode, no proxy
CLI needed (unlike `zai`, which must impersonate `claude -p` because z.ai ships no headless client
of its own). Own git worktree, own process group under the timeout supervisor, git-derived scope
gate — identical shape to cursor/antigravity/zai. No kernel write-confinement by default; a real one
(`--sandbox` / `QWEN_SANDBOX=docker|podman|sandbox-exec`, inherited from the Gemini CLI fork this
tool is built on) exists and is documented, but is **optional in v1**, not required.

**Status — auth-pending / coverage-unverified.** Every fact below comes from Qwen Code's own docs
(`qwenlm.github.io/qwen-code-docs`, `github.com/QwenLM/qwen-code`) and Alibaba Cloud's official
Model Studio help pages, read directly during this brainstorm (2026-08-04) — not from a live probe
with a real Coding Plan key, because the plan has not been purchased yet. This mirrors where
`adapter-opencode.md` and `adapter-devin.md` already sit. The `zai` spec's own history is the
cautionary precedent: its first draft, written from docs alone, shipped a `--allowedTools` /
`--tools` inversion that only a real-binary probe caught. **A live verification pass — the same
"Verified live against `<cli> <version>`" treatment `zai`/`codex` got — is required before this
adapter's status flips to shipped**, and should be budgeted to find at least one such surprise.

## Verified facts (from primary docs, not measurement)

- **Headless flag:** `qwen -p "<prompt>"` runs without the interactive UI; `-o text` for plain text.
  `--output-format json` returns a JSON array of message objects (system/assistant/result types);
  `--output-format stream-json` streams events.
- **Session control:** `qwen --continue -p "…"` resumes the most recent project session;
  `qwen --resume <session-id> -p "…"` resumes a specific one. Checkpoints (history, tool outputs,
  compression state) are written atomically under `~/.qwen/tmp/<project_hash>/checkpoints`.
- **`--yolo` (or `--approval-mode=yolo`) auto-approves tool calls but does not sandbox.** Sandboxing
  is a separate opt-in: `--sandbox`, `QWEN_SANDBOX`, or `tools.sandbox` config. Without it, yolo-mode
  tools run at the host process's own privilege — same shape as Cursor/Antigravity/opencode/zai. A
  stderr warning fires in headless+yolo+no-sandbox; suppressible via `QWEN_CODE_SUPPRESS_YOLO_WARNING=1`.
- **Real kernel sandbox exists, unlike Cursor/Antigravity/opencode.** macOS: `QWEN_SANDBOX=true`
  selects `sandbox-exec` (Seatbelt) with named profiles (`permissive-open` … `restrictive-closed`).
  Linux/Windows: requires Docker or Podman; `SANDBOX_FLAGS` injects extra container flags. Inherited
  from the Gemini CLI fork.
- **Auth is API-key-based, not OAuth — headless-native.** Alibaba's own docs state it plainly:
  *"OAuth cannot function without a browser. All other methods — Coding Plan, third-party APIs, and
  custom providers — work fully in headless environments."* Qwen OAuth itself was discontinued
  2026-04-15 and is legacy-only regardless.
- **Coding Plan credentials:** env var `BAILIAN_CODING_PLAN_API_KEY="sk-sp-…"` +
  `OPENAI_BASE_URL="https://coding-intl.dashscope.aliyuncs.com/v1"` (international) or
  `https://coding.dashscope.aliyuncs.com/v1` (China). Config-file equivalent:
  `~/.qwen/settings.json` → `modelProviders.openai`. Env var priority (highest to lowest): CLI flags
  → shell exports → `.env` files (`.qwen/.env` → `.env` → `~/.qwen/.env` → `~/.env`) →
  `settings.json` → `env`.
- **The Coding Plan is a multi-vendor catalog behind one key**, not a single model family like
  `zai`'s GLM-only shape: documented models include `qwen3.5-plus`, `qwen3.6-plus`, `qwen3.7-plus`,
  `qwen3-coder-plus`, and — via the same endpoint — `glm-5`, `kimi-k2.5`, `MiniMax-M2.5`.
- **No `--effort`/`--reasoning` CLI flag for headless mode.** Qwen Code has a 5-tier reasoning-effort
  ladder, but it's exposed as the interactive `/effort` command or the `model.reasoningEffort`
  settings.json field — not a `qwen -p` flag. Applying `effort` headlessly means writing it into a
  pinned settings.json in the worktree/scratch before invocation (opencode's pattern), not a CLI arg.
  Needs live confirmation.

## Unverified / needs-live-confirmation

- Exact `--resume` session-id shape (docs show a UUID-formatted example, not a stated contract —
  same caution as opencode's `ses_`-prefixed ids not being Codex's UUID).
- Whether `qwen` has a `--cd`/`--dir`-equivalent flag or needs a subshell `cd` like cursor/zai.
- The DashScope/Bailian error-response shape (codes, HTTP statuses, `Retry-After` presence) needed
  to build `compound-v-classify-failure.py --backend qwen`.
- Whether `--sandbox` and `--yolo` compose cleanly in one headless invocation (docs describe both
  independently; not observed together).
- Qwen Code's "Skills and SubAgents" feature's interaction with the planner/executor prompt lock.

## Credentials and isolation

Mirrors `zai`'s `env -i` allow-list + scratch-`HOME` shape, adapted to Qwen Code's own config path
(`~/.qwen/settings.json` instead of `~/.claude`):

```
env -i PATH TMPDIR LANG HOME=<scratch> \
    BAILIAN_CODING_PLAN_API_KEY=<key> OPENAI_BASE_URL=<coding-intl endpoint> \
  python3 scripts/compound-v-run-with-timeout.py --timeout <t> --grace 3 -- \
    qwen -p --yolo [--sandbox <profile> --sandbox-image <image-if-linux>] \
      --output-format json [--resume <id>] "<prompt>" </dev/null
```

`HOME` redirection keeps the operator's own `~/.qwen` config and any cached credentials out of the
worker's reach, the same load-bearing reason `zai` redirects `CLAUDE_CONFIG_DIR`. Exact flag order
and any additional required env vars (e.g. whether `QWEN_SANDBOX` must also be set alongside
`--sandbox`) are pinned during live verification, not here.

## Model resolution

Bare model name (`qwen3-coder-plus`, `glm-5`, `kimi-k2.5`, …) — one endpoint, so never a
`provider/model` string like opencode. **No hardcoded default `deep`/`standard`/`light` map in this
spec**: Alibaba shipped a new flagship (Qwen3.8-Max, 2026-08-03) mid-brainstorm, one day before this
doc was written — pinning a model name now would likely be stale before the user's subscription is
even active. The default map is resolved via `/v:models` once a real key exists, written into
`.claude/compound-v.json` per the existing pattern (mirrors opencode's "assignment stays curated +
user-confirmed").

`glm-5` and `kimi-k2.5` are **documented, named overrides** reachable through this same endpoint —
not silently-accepted arbitrary strings. `effort` accepts `low|medium|high`, never `xhigh`
(project-wide: `xhigh` is codex-only).

## Trust tier, isolation, reviewer/arbiter eligibility

`isolation: worktree` mandatory — new entry beside `codex|antigravity|cursor|devin|opencode|zai ⇒
worktree`. **Lower-trust, opt-in tier**, same as opencode/cursor/antigravity/zai: worktree + the
git-derived gate detect an in-worktree scope leak but cannot prevent an out-of-worktree side effect,
because `--sandbox` is optional, not required, in v1. Operators who enable `--sandbox` get strictly
better isolation than the tier implies, but the adapter does not depend on it.

**WORKER-ONLY, hard-enforced, not a judgment call.** Verified directly in
`compound-v-validate-manifest.py`: the CR5-5 gate requires a reviewer job to resolve to
`backend: claude` **and** a model name containing `"opus"` (`_is_claude_opus()`), checked at both
manifest-validation and sealed-receipt time. This is unconditional — no benchmark result changes it,
for `qwen` or any other backend. `zai`/`opencode`/`devin` additionally get an explicit backend-name
block because their own model resolution can produce an "opus"-substring string (z.ai's Anthropic
aliases, opencode's `anthropic/claude-opus-4-6`); `qwen`'s model names never do, so it rides the
universal CR5-5 check alone.

**Not (yet) in `/v:review-plan` or the epic-arbiter panel.** Both (`compound-v-codex-review.sh`,
`compound-v-epic-arbiter.py`) are hardcoded to Codex today; extending either to draw from a general
backend pool is separate, larger work — Non-goal here (see below), same posture zai/opencode already
carry.

## New this PR: `qwen` joins the advisor-mode cross-brand pool

Advisor-mode (`skills/backend-launcher/adapter-advisor.md`) already has a general selector —
`compound-v-resolve-model.py --select-advisor` — with a deterministic priority list:
`codex > any other non-claude > opus fallback`. Today only two of those tiers are actually **driven**
by `compound-v-advisor-consult.sh` (codex, claude); any other selection is refused as an unproven
path. This PR:

1. Adds `qwen` to the priority list, ordered by **verified isolation strength** — the same axis
   already used to rank Codex first — not by benchmark score:
   ```
   codex (kernel read-only sandbox)  >  qwen (optional kernel sandbox)  >
   zai / opencode / cursor / antigravity (no OS guarantee)  >  opus fallback
   ```
2. Adds a third pinned, driven execution path in `compound-v-advisor-consult.sh`: a read-only
   `qwen` consult (sandboxed where `--sandbox` is available, no write tools regardless).
3. Documents `backend: qwen, model: glm-5` and `backend: qwen, model: kimi-k2.5` as valid **explicit
   overrides** for an advisor consult — not entries in the auto-picked priority list. Rationale below.

**Why GLM and Kimi are overrides, not defaults — benchmark research, 2026-08-04.** All figures below
are from secondary aggregators (not vendor-primary pages) and should be read as directional, not
exact; multiple sources disagreed by a few points on the same figure.

| | General intelligence (Artificial Analysis index, Opus 5 = 61) | SWE-bench Pro (Opus 4.8 = 69.2%) | Terminal-Bench (agentic CLI) | Notable independent signal |
|---|---|---|---|---|
| Qwen (3.7 Max / Qwen3-Coder-Next) | ~46 | 44.3% | beats Opus 4.6 on 2.0 (61.6% vs 59.3%) | real-world Rust test: benchmark scores didn't translate to effectiveness |
| Kimi K3 / K2.x | ~57 (closest to Opus of the three) | ~10–62 depending on variant/source (noisy) | 66.7% (K2.6, v2.0) | hands-on test: notably weaker on ambiguous, long-horizon agentic tasks — advisor-mode's exact use case |
| GLM-5.2 | ~51 (or 34 on a non-reasoning variant) | 62.1% — beats GPT-5.5's 58.6% | 81.0% (first open-weight past 80%) | strongest of the three on agentic/coding axes; some headline claims are self-reported/custom-harness |

None of the three matches Opus across the board, and the picture is genuinely mixed rather than
uniformly favorable to any one of them. The actual justification for a non-Claude advisor voice in
this codebase was never "as smart as Opus" — `compound-v-codex-review.sh`'s own header states Codex's
value as *"error DECORRELATION: a different model family sees the blind spots the planner's own
family does not see in itself."* Qwen earns default-priority status on the same isolation logic as
Codex (§ above). GLM and Kimi earn override-only, probationary status: real decorrelation value is
plausible, but the evidence is too mixed (and, for Kimi, actively negative on advisor-mode's specific
use case in one hands-on test) to auto-pick either by default before the user has live experience of
their own.

**Why GLM routes through `qwen` in addition to `zai`.** `glm-5` is reachable two ways: the existing
`zai` backend (z.ai's own official plan, no kernel sandbox) or `backend: qwen, model: glm-5` (Bailian
resale of the same model family, but with `qwen`'s optional kernel sandbox available). If the
operator drops their direct z.ai subscription, GLM access moves to the `qwen` path with no adapter
change required — `zai` simply goes unconfigured. No new selection mechanism is needed for this:
`job_spec.model` already supports an explicit override that skips tier resolution.

## Job contract

`job_spec` is unchanged. `qwen` accepts `backend`, `prompt`, `tier`, `effort` (`low|medium|high`,
never `xhigh`), `model` (explicit override — bare name, e.g. `glm-5`/`kimi-k2.5`), `cwd`,
`write_allowed`, `read_only`, `timeout_sec`, `network` (maps to whether the container/Seatbelt
profile permits network access when `--sandbox` is engaged; advisory when it isn't). `read_only` /
an empty `write_allowed` is enforced post-hoc the same way as every other adapter: any change ⇒
`blocked`, never merged — `qwen` adds no new semantics here.

`job_result` is unchanged and assembled by the caller: `files_changed`/`violations`/`blocked` stay
git-derived; `worktree` is always set (never `direct`, same invariant as codex/cursor/antigravity/zai);
`session_id` shape and `usage` field population are pinned during live verification, not here.

## Failure classification

**Not yet built** — same posture as opencode: no live DashScope/Bailian error samples exist yet.
`compound-v-classify-failure.py --backend qwen` fails closed to `other` for every payload until a
live pass supplies real codes/messages, exactly like opencode's stated gap. `compound-v-failure-policy.py`
gets a `FALLBACK` entry for `qwen` regardless, so a quota failure reroutes/retries instead of halting
the whole run (the same reason `zai`'s spec calls this "not optional" — without it, `None` halts
everything).

## Testing

Stub-first (`scripts/test-qwen-worker-stub.sh`, mirroring `test-advisor-worker-stub.sh`): a fake
`qwen` on `PATH` asserts the pinned argv, that `env -i` forwards exactly the declared allow-list, and
the success/BLOCKED/timeout paths. **A stub cannot catch the class of bug that broke `zai`'s first
draft** (a flag pair that parses fine in argv assertions but means the opposite of what the doc
claims) — a real-binary, no-network smoke test against a local stub HTTP server is required before
shipping as verified, not optional polish.

## Files touched

**New:** `scripts/compound-v-run-qwen-worker.sh`, `skills/backend-launcher/adapter-qwen.md`.

**Edited:** `compound-v-resolve-model.py` (qwen tier map resolution + advisor-selector priority
entry), `compound-v-validate-manifest.py` (`VALID_BACKENDS`, worktree invariant, selftest fixtures —
the CR5-5 reviewer gate needs no change, it already covers `qwen` generically), `job_result.schema.json`,
`compound-v-classify-failure.py` (qwen branch, fail-closed to `other`), `compound-v-failure-policy.py`
(`FALLBACK` entry), `compound-v-advisor-consult.sh` (third pinned path), `agents/parallel-dispatcher.md`,
`skills/backend-launcher/SKILL.md` (adapter table), `skills/compound-v/execution-manifest.md`,
`skills/compound-v/routing-policy.md` (advisor cross-brand list), `commands/v-init.md`,
`commands/v-models.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json` + `marketplace.json` (version
lockstep).

## Non-goals

- **No OAuth path** — Coding Plan is API-key-only; Qwen OAuth is discontinued and headless-incompatible
  regardless.
- **No OpenRouter/BYOK/custom-provider auth paths** through Qwen Code — scoped strictly to the
  Alibaba Coding Plan the user is purchasing. Revisit only if that scope genuinely changes.
- **No mandatory `--sandbox`** in v1 — documented as available, not required (explicit user decision).
- **No extension of `/v:review-plan` or `compound-v-epic-arbiter.py`** to draw on qwen/glm/kimi —
  both are Codex-hardcoded today; generalizing either is separate, larger work.
- **No arbiter family-dedup fix** (`compound-v-epic-arbiter.py`'s substring match doesn't know
  `qwen`/`glm`/`kimi`) — required before any of these three could safely hold a panel seat; flagged,
  not built, same as zai/opencode's own Non-goals.
- **No change to the `zai` adapter itself.** If the operator cancels their z.ai subscription, `zai`
  becomes unconfigured and unused; no code path here depends on that decision.
- **No live-verified flag set.** This spec is written from documentation; the live probe (real Coding
  Plan key, real `qwen` binary, real error samples) is a required follow-on before shipping as
  verified, not a nice-to-have.

## Acceptance criteria

1. A manifest with `backend: qwen, isolation: worktree` validates; the same manifest with
   `isolation: direct` fails with a message naming the invariant.
2. A `qwen` reviewer job fails validation under the existing CR5-5 gate (no new code needed for this
   specific check — confirmed by test, not assumed).
3. `compound-v-resolve-model.py --backend qwen --tier {deep,standard,light}` resolves from
   `.claude/compound-v.json` (no hardcoded default map in code); `--effort xhigh` is rejected.
4. `compound-v-resolve-model.py --select-advisor` includes `qwen` between codex and the no-sandbox
   tier.
5. `compound-v-advisor-consult.sh` drives a real (or stubbed, in CI) `qwen` read-only consult as a
   third pinned path.
6. `backend: qwen, model: glm-5` and `backend: qwen, model: kimi-k2.5` validate as accepted overrides
   and do not appear in any auto-resolved default tier map.
7. A worker that writes outside `write_allowed` yields `blocked: true` with offending paths in
   `violations`; the caller does not merge.
8. `compound-v-classify-failure.py --backend qwen` maps every payload to `other` (documented gap,
   not silently absent) until a follow-on adds real needles.
9. `compound-v-failure-policy.py` returns a reroute/bounded retry for a `qwen` quota failure, not a
   run halt.
10. CI runs shellcheck over the new worker script and executes its stub tests.
11. `SKILL.md`'s adapter table lists `qwen` as **auth-pending / coverage-unverified** until a live
    pass (real Coding Plan key) updates it — this status must not read as "verified" prematurely.
