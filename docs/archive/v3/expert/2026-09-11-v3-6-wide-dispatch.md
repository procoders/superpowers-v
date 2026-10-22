# Phase 1B Domain Audit — v3.6.0 wide dispatch: worktree provisioning, verdict trust ordering, the advisor as a "second opinion"

**Date:** 2026-09-11 · **Spec audited:** `docs/superpowers/specs/2026-09-11-v3.6-wide-dispatch-design.md` ·
**Upstream complaints:** [#19](https://github.com/copeus/superpowers-v/issues/19) (six machinery defects, @khymerao),
[#12](https://github.com/copeus/superpowers-v/issues/12) (closed by #13/#14) · **Scope:** research only, no file
touched but this one.

**Headline.** Three findings change the plan rather than decorate it.

1. **F3 has one unconditional hole and one latent one.** The unconditional one: `--expect-diff-digest`
   is appended only `if (v.diff_digest)`, so in exactly the degraded-transport case F3 is written for,
   the digest binding the spec calls "the forgery axis" is silently absent. The latent one: the receipt
   path and all four of F3's acceptance conditions are attempt-invariant, so nothing in the accept rule
   distinguishes one attempt's receipt from another's — today that is held shut by `resume-prepare`
   alone. §3.5, MUST-8..MUST-11.
2. **The "typically costs less" advisor line does not transfer to this repo**, because Compound V's
   executors are already Opus. Anthropic's own platform docs name the boundary and publish the
   counterexample (2.6× cost at equal score). §3.4, MUST-12.
3. **F4's bootstrap recogniser matches a substring of an attacker-influenceable command.** Every
   comparable system (AppArmor, SELinux, Landlock) keys its "expected denial" suppression on the
   subject, never on text inside the request. §3.6, MUST-14.

---

## 1. Domain(s) Identified

| Domain | Why it applies |
|---|---|
| `ci-dependency-provisioning` | F1 asks manifest authors to write an install command that runs in a fresh checkout without dirtying tracked files — a CI/reproducible-build problem with per-ecosystem answers. |
| `agent-orchestration-provenance` | F3/F4 are trust-ordering and audit-labelling problems: which of two disagreeing sources is authoritative, and how a system labels a denial it expects so a real one still stands out. |
| `llm-self-review-honesty` | F7's "advisor-assisted second look" is a product-honesty decision about presenting same-family review where cross-model review was promised. |
| `agent-context-hygiene` | F6's `/skill-doctor` posture — report vs act — is a plugin-etiquette question with observable user demand on both sides. |

No V-memory hit existed for the first domain. `python3 -B scripts/compound-v-memory.py search "npm ci node_modules
worktree provisioning floor command"` returned orchestrator research and library audits, nothing about package
managers — **this is genuinely new ground for the repo**, which is consistent with #19's own observation that the
plugin is a stdlib project with no install step and so never hit the bug in dogfood.

---

## 2. Sources Consulted

**V-memory (3 queries, `--intent planning`).** Two returned relevant prior art:
`docs/superpowers/expert/2026-07-13-usage-and-advisor.md` (the anti-ruflo rule and the original advisor shape —
still binding and still correct), and `docs/superpowers/specs/2026-07-14-v2.14-blockers-and-headless-design.md`
(the "second, distinct-family advisor" precedent). One returned nothing relevant, recorded above.

**Code read in this repo (HEAD `ce4cb19`).** `scripts/compound-v-emit-workflow.py` lines 1095–1258 (retry budget),
2955–3060 (Gate/Record command construction), 3990–4021 (receipt writer), 4640–4700 (Record comparison),
9060–9080 (`resume-prepare` receipt archival); `scripts/compound-v-scope-check.py` (`--preexisting` handling).
`grep -rn "provision" scripts/compound-v-emit-workflow.py scripts/compound-v-validate-manifest.py` returns nothing —
#19 B's claim that no provisioning mechanism exists is **verified**.

**Official / authoritative.**
[npm-ci docs](https://docs.npmjs.com/cli/v11/commands/npm-ci) ·
[pnpm install](https://pnpm.io/cli/install) ·
[pnpm git worktrees](https://pnpm.io/git-worktrees) ·
[pnpm store settings](https://pnpm.io/settings/store) ·
[uv locking](https://docs.astral.sh/uv/pip/compile/) ·
[Claude Code advisor](https://code.claude.com/docs/en/advisor) ·
[Claude API advisor tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool) ·
[Optimizing for cost and intelligence](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence) ·
[The advisor strategy](https://claude.com/blog/the-advisor-strategy) ·
[Claude Code skills](https://code.claude.com/docs/en/skills) ·
[apparmor(7)](https://manpages.debian.org/unstable/apparmor/apparmor.7.en.html) ·
[Landlock](https://docs.kernel.org/userspace-api/landlock.html) ·
[Red Hat: SELinux denial messages](https://www.redhat.com/en/blog/selinux-denial2).

**Practitioner / research.**
[Huang et al., *LLMs Cannot Self-Correct Reasoning Yet*, ICLR'24](https://arxiv.org/pdf/2310.01798) ·
[*When AI Reviews Its Own Code: Recursive Self-Training Collapse*](https://arxiv.org/html/2606.28438v1) ·
[*Quantifying and Mitigating Self-Preference Bias of LLM Judges*](https://arxiv.org/html/2604.22891v4) ·
[Kleppmann, *How to do distributed locking*](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html) ·
[Coinspect, supply-chain guardrails](https://www.coinspect.com/blog/supply-chain-guardrails/) ·
[devtoolbox 2026 package-manager benchmark](https://devtoolbox.blog/pnpm-vs-bun-vs-npm-benchmark-2026/).

**Layer 3 — where people running these agents complain.**
[anthropics/claude-code#27744](https://github.com/anthropics/claude-code/issues/27744) (PostWorktreeCreate hook, **29 👍**, closed) ·
[#20905](https://github.com/anthropics/claude-code/issues/20905) (worktree dependency docs buried) ·
[#27276](https://github.com/anthropics/claude-code/issues/27276) (`WorktreeCreate` hook undocumented) ·
[#39277](https://github.com/anthropics/claude-code/issues/39277) (hook does not fire on `claude -w`) ·
[#32974](https://github.com/anthropics/claude-code/issues/32974) ·
[#26838](https://github.com/anthropics/claude-code/issues/26838) (allow disabling built-in skills, **44 👍**, closed) ·
[#52456](https://github.com/anthropics/claude-code/issues/52456) (plugin uninstall flow) ·
[#56494](https://github.com/anthropics/claude-code/issues/56494) (`skillOverrides` missing from settings reference) ·
[pnpm discussion #10702](https://github.com/orgs/pnpm/discussions/10702) (concurrent installs on one store) ·
[tfriedel/claude-worktree-hooks](https://github.com/tfriedel/claude-worktree-hooks) (the community's answer to #27744).

**Searched and found nothing usable — stated so rather than padded.** No Hacker News thread on the advisor
strategy surfaced (only syndicated blog coverage). No r/ClaudeAI thread on `/skill-doctor` surfaced; the
`/skill-doctor` Layer-3 evidence below is GitHub issues plus trade blogs, not forum consensus.

---

## 3. Findings — the seven questions, answered

### 3.1 Provisioning commands per ecosystem, and the lockfile trap

The rule the spec states — "`npm ci`, not `npm install`" — generalises, but each ecosystem spells it differently
and two of the spellings are traps in their own right.

| Ecosystem | The form to require | Why this one | The trap in the obvious alternative |
|---|---|---|---|
| npm | `npm ci` | npm docs: *"It will never write to `package.json` or any of the package-locks: installs are essentially frozen."* | `npm install` reconciles a drifted lockfile by **rewriting it**; `npm ci` *"will exit with an error, instead of updating the package lock."* |
| pnpm | `pnpm install --frozen-lockfile` | Fails when `pnpm-lock.yaml` and `package.json` disagree rather than re-resolving. | pnpm enables frozen installs **implicitly only when `CI` is set**. A worktree provisioning shell is not CI, so a bare `pnpm install` there can silently rewrite the tracked lockfile. |
| Yarn Berry (v2+) | `yarn install --immutable` | The supported spelling. | `--frozen-lockfile` is **deprecated** in Berry — a manifest copied from a Yarn-1 project gets no enforcement. Yarn also enables immutable implicitly when `CI` is set, same gap as pnpm. |
| Yarn Classic (v1) | `yarn install --frozen-lockfile` | The only spelling v1 has. | Using the Berry spelling on v1 fails outright. |
| Python (uv) | `uv sync --frozen` | *"installs strictly from the existing lockfile without checking it against the inline metadata"* — skips resolution entirely. | `uv sync` **without** `--frozen` re-locks and rewrites the tracked `uv.lock` when `pyproject.toml` drifted. |
| Python (pip) | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` | Installs into a gitignored venv inside the worktree; touches no tracked file. | `pip freeze > requirements.txt` rewrites a tracked file. Installing without a venv contaminates the host interpreter — and #27744 names this as the workaround agents actually reach for. |
| Rust | `cargo fetch --locked` then `cargo build --locked` | `--locked` asserts `Cargo.lock` is already up to date and refuses to change it. | Plain `cargo build` updates `Cargo.lock` when `Cargo.toml` drifted. |
| Go | `go mod download`, then assert `go.mod`/`go.sum` are unchanged | The [module reference](https://go.dev/ref/mod) confirms `-mod=readonly` is the default absent a `vendor` dir, and it *"report[s] an error if `go.mod` needs to be updated."* | `go mod tidy` rewrites both files. **UNVERIFIED:** whether `go mod download` can add entries to `go.sum` — the module reference does not settle it and the behaviour has shifted across Go versions. Hence the post-check rather than a bare claim. |
| Ruby | `BUNDLE_FROZEN=true bundle install` | Refuses rather than re-resolving, and sets frozen mode **through the environment**. | Plain `bundle install` rewrites `Gemfile.lock`. Note the near-miss: `bundle config set --local frozen true` writes `.bundle/config`, which is itself sometimes tracked — the provisioning command would then trip MUST-2. Use the env var. |

**The trap, named precisely for this pipeline.** F1 subtracts provisioning through `--preexisting`, and that
snapshot is `git ls-files --others` — **untracked and ignored paths only**. A lockfile is a *tracked* file. So a
provision command that rewrites one produces a change the snapshot cannot subtract, and it lands in the job's
`git diff` regardless of whether provisioning ran before or after the before-image. Two outcomes, both bad: the
job is BLOCKED for a write it did not make, or — if the lockfile happens to sit inside `write_allowed` — a
dependency-tree change merges into the release with no author. The spec's one-line author rule ("A tracked file it
changes is attributed to the job") is correct but reads as a caveat; it is the whole safety property.

**Two more `npm ci` properties that matter here.** It **requires** an existing lockfile and errors without one —
so a floor whose package lives in a subdirectory needs `cd sub && npm ci`, which `/bin/bash -c` supports. And *"if
a `node_modules` is already present, it will be automatically removed before `npm ci` begins its install."* That
makes it idempotent, and it makes running it in a **shared** checkout destructive to a concurrent sibling — which
is precisely the #12 silent-downgrade wave. The spec's "direct-mode job: provisioning does not run" is therefore
load-bearing for correctness, not just an optimisation, and the docs should say why.

**What the spec does not mention and #27744 says is the bigger half.** Its author ranks the missing state
`.venv/` and `.env` **above** `node_modules` — *"`node_modules/` — (less critical, `npm install` is fast and
safe)"* — because *"agents in worktrees cannot execute code, run tests, or use linters."* A `provision_command`
can install dependencies; it cannot conjure secrets. It **can** copy them (`cp ../../.env .env`), and because
provisioning runs before the snapshot, the copied file is subtracted correctly — whereas the same copy performed
by the agent is an out-of-lane write. That asymmetry is worth one documented sentence.

**Layer 3 weight.** #27744 (29 👍, closed), #20905, #27276, #39277 and #32974 are five distinct issues on one
tracker about the same gap, plus a community project ([claude-worktree-hooks](https://github.com/tfriedel/claude-worktree-hooks))
built to fill it. That clears the community-signal threshold. Note that Claude Code shipped `WorktreeCreate` /
`WorktreeRemove` hook events in v2.1.50 (#27276) — **UNVERIFIED whether those fire for `agent_isolation: worktree`
subagent worktrees**, which is the case Compound V needs. If they do, a hook is an alternative to the manifest
key; if they do not, F1 is the only route. Worth a live probe before the plan freezes.

### 3.2 Timeouts and caches

**Cold-install durations.** The honest answer is a wide distribution, not a number.

- The [devtoolbox 2026 benchmark](https://devtoolbox.blog/pnpm-vs-bun-vs-npm-benchmark-2026/) on a Next.js 15 +
  Tailwind v4 project reports npm's lockfile install (CI simulation) at **19.4 s**, and npm cold-cache at
  **41.3 s** (pnpm 14.8 s, Bun 6.2 s). One project, one machine.
- Long-tail reports exist at **32 minutes** and **40 minutes** for large monorepos.
  **Isolated reports** — single blog posts, no corroboration, and both are about `npm install` in Docker rather
  than `npm ci` in a worktree. Do not cite these as typical.

**Verdict on `provision_timeout_s: 600`.** Reasonable as a default — roughly an order of magnitude above the
measured median — and the `1..1800` range gives monorepos an escape hatch. The problem is not the number, it is
the **failure shape**: F1 says a timeout is recorded as `provision_error` and the job proceeds to a stricter gate
with no snapshot. A slow monorepo therefore does not report "provisioning timed out"; it reports a job BLOCKED on
several thousand `node_modules/**` violations — the exact confusing symptom #19 A was filed about. The
TROUBLESHOOTING entry must connect the two, and the BLOCKED result must name `provision_error` where one exists.

**A ceiling the spec does not account for: `provision_timeout_s` up to 1800 is unreachable on the Claude path.**
F1 runs `provision_command` inside `register-lane --isolation worktree`, and `register-lane` is *"the Implement
agent's FIRST command"* (`emit-workflow.py:37`) — an ordinary Bash tool call made by the agent. The prompt block
that hands the agent that command (`:2419`) specifies **no `timeout:`**, unlike the Gate prompt, which explicitly
instructs *"Call the Bash tool with `timeout: 600000`"* (`:2965`). So provisioning inherits the Bash tool's
default ceiling — 120 s — and a `provision_timeout_s` of 600, let alone 1800, cannot be reached. The kill lands
mid-install, which surfaces as `provision_error` → stricter gate → thousands of `node_modules/**` violations:
the original #19 A symptom, reintroduced by the fix for it. Two consequences: the register-lane call's `timeout`
must be raised to at least `provision_timeout_s`, and the install's stdout must go to a file rather than the
transcript — a verbose `npm ci` at turn one otherwise sits in the agent's context for the rest of the job, and
every advisor call thereafter re-reads it **uncached** (§3.4).

**Cache sharing: yes, worth one line, with one condition.** pnpm does not merely permit this, it **recommends
exactly this arrangement**: [pnpm.io/git-worktrees](https://pnpm.io/git-worktrees) is titled for multi-agent
development, pairing worktrees with the global virtual store (`virtualStoreType: global`, since v11.23.0;
`enableGlobalVirtualStore: true` before that), making a new worktree's install "nearly instant". Concurrency is
safe: [pnpm discussion #10702](https://github.com/orgs/pnpm/discussions/10702) — *"all store related operations
are atomic and the store will never be left in a broken state."*

The condition is pnpm's own warning, and it lands squarely on Compound V: *"This setup assumes the worktrees and
agents share the same trust boundary. Do not use one writable pnpm store for mutually untrusted agents or users."*
Compound V deliberately runs backends at **different** trust levels — `AGENTS.md` describes `agy` and
`cursor-agent` as "opt-in / lower-trust" with no kernel write-confinement, alongside Codex which has one. A shared
writable store is a channel between them that the scope gate does not watch, because it lives outside the
worktree. That is a real, unstated consequence of recommending the optimisation.

For npm the picture is weaker: `~/.npm` (`cacache`) is documented as corruption-resistant, but concurrent-install
races have a history (`EPERM: operation not permitted, rename` across parallel installs). Recommend sharing;
do not promise it.

### 3.3 Second-opinion honesty

**The field's position is not ambiguous.**

- **Intrinsic self-correction degrades performance.** Huang et al. (ICLR'24) find LLMs *"struggle to self-correct
  their reasoning"* without external feedback, and that the bottleneck is **error detection**, not error
  correction. A reviewer that cannot detect its own class of error does not acquire that ability by being asked
  twice.
- **Self-preference bias is measured and large.** [Quantifying and Mitigating Self-Preference Bias](https://arxiv.org/html/2604.22891v4)
  reports a range of **−38% to +90%** on ArenaHard, correlating with a model's ability to recognise its own
  output, and stronger in larger models. **Honest caveat:** the same literature notes the effect largely
  disappears once output quality and judge severity are controlled, so self-preference is a hazard, not a proof
  of worthlessness.
- **Code-specific, and the sharpest statement.** [*When AI Reviews Its Own Code*](https://arxiv.org/html/2606.28438v1)
  finds a binary self-gate enters *"a rubber-stamp regime where acceptance scores rise while benchmark correctness
  falls"*, concluding that stability *"requires exogenous verification rather than model-coupled self-review."*
  **Single paper, not replicated** — treat as directional.
- **Diversity is the mechanism, and it is not free.** Ensemble error falls with lower inter-member correlation;
  same-family models share correlated blind spots. This is the same reasoning the repo already applied in v2.14
  when it picked a *distinct family* for `done_with_blockers`.

**Is the spec's labelling sufficient? Nearly — three wording defects.**

1. **"second look" and "second opinion" both connote independence.** A downstream reader who saw
   `reviewer_backend: "claude-advisor"` and the phrase "advisor-assisted second look" will reasonably conclude
   something checked the work from outside. The disclosure must say what was **not** obtained, not only what was.
2. **"same model family — no decorrelation" is jargon.** "Decorrelation" is a term this repo uses internally;
   khymerao's project will not parse it. It needs a plain clause.
3. **It understates the coupling.** Rung 2 is an **Opus** subagent consulting an **Opus or Fable** advisor. Under
   the advisor pairing table an Opus 4.7+ main accepts only Opus 4.7+ — so in the common case it is not merely the
   same family but plausibly the same model reviewing itself with extra steps. And Anthropic's own docs supply the
   misleading frame to anchor against: the pairing table describes `Opus main + Opus advisor` as *"A second Opus
   reviews the first. Useful for high-stakes tasks where an independent check matters more than cost."* A user who
   has read that page has already been told this configuration is an "independent check".

**Recommended disclosure line, exact wording:**

> `Same-family review: Claude reviewed by Claude (advisor-assisted). It shares the writer's blind spots and is not the cross-model check — no second vendor saw this.`

**The larger problem is not the label, it is the policy.** F7 says *"For SCOPED+ the mandatory second look is
satisfied by rung 2 with that WARN."* That sentence takes an honestly-labelled downgrade and makes it
*equivalent* to the thing it is honestly labelled as not being. An honest label plus an equivalence rule is less
honest than no label at all, because the label is then decoration on a gate that already waved the run through.
The fix is cheap: rung 2 satisfies the requirement **and** stamps `cross_model: false` on the record, so an
auditor can count how many SCOPED+ runs shipped without a second vendor. That number is the thing a maintainer
will want in six months, and it costs one boolean.

### 3.4 Advisor cost expectations

**Mechanics, verbatim from the docs.**

- Claude Code: *"The advisor model's own read of the conversation is not cached. Each advisor call processes the
  full transcript anew, with no reuse between calls."*
- API: advisor output is *"typically 400 to 700 text tokens, or 1,400 to 1,800 tokens total including thinking"*,
  billed at the advisor's rates, reported in `usage.iterations[]` as `type: "advisor_message"` and
  **not rolled into top-level `usage`**. (This confirms the spec's live probe: counting `server_tool_use` blocks
  is the right method under Claude Code.)
- **The API exposes two cost controls that Claude Code does not.** `max_uses` caps advisor calls per request, and
  `caching: {"type": "ephemeral", "ttl": "5m"|"1h"}` enables advisor-side prompt caching across calls in a
  conversation. Claude Code's page states flatly: *"There is no setting to cap or force advisor calls"*, and that
  the advisor's read is uncached. So under Claude Code, **Compound V can neither cap nor cache advisor spend per
  job** — it can only measure it afterwards. That is a hard constraint on F7, and it is the reason AC-8 matters.

**Does "typically costs less than running the stronger model throughout" hold here?** The claim is relative, and
its baseline is *running the advisor's model as the main model*. Anthropic's platform docs name the boundary
directly: the pattern *"fits poorly when every turn genuinely needs frontier capability, when there is nothing to
plan (single-turn Q&A), or when your executor is already close to the advisor's capability."* And the published
counterexample: on Chartography, the pairing *"matched Claude Fable 5.1 alone at `medium` within run-to-run noise
(65.0 against 67.5) at about 2.6 times the cost per task, because the advisor was consulted on nearly every task."*
Their guidance follows: *"Measure your own consult rate first"* and *"first price the advisor's model alone at low
effort; that is the baseline to beat."*

Compound V's implementers and reviewers are **Opus by policy**. That is the "executor already close to the
advisor" box for Opus-advisor pairings. The one measured point that favours it is the Fable pairing: on an
internal agentic-coding benchmark *"a Claude Opus 5 executor with a Claude Fable 5.1 advisor was the most accurate
configuration measured, at $7.69 per attempt … 3.5 points over Opus 5 alone at the default setting for slightly
less money."* So `advisorModel: fable` has a published basis; `advisorModel: opus` on an Opus job does not, and
the docs' own framing for it is quality ("an independent check matters more than cost"), not savings.

**The 80-turn multiplier: UNMEASURED, and no number should be invented.** What can be stated as structure:
advisor cost ≈ (number of calls) × (transcript size at each call), with transcript size growing monotonically
through the job and no caching to flatten it, while the main model's own re-reads are largely cache-reads.
Advisor *output* is bounded (400–700 text tokens) and is not the driver. Both drivers are uncapped in Claude Code.
Hence the honest rule of thumb:

> Advisor cost grows with **calls × transcript length**, and Claude Code caps neither. On a long job the advisor's
> input bill can approach or exceed the executor's, because the executor re-reads from cache and the advisor never
> does. Anthropic's "costs less than running the stronger model throughout" assumes a main model materially
> cheaper than the advisor; Compound V's implementers are already Opus, so that comparison does not transfer.
> Measure `usage.advisor_calls` and report `null` where unmeasured.

The anti-ruflo rule from the 2026-07-13 audit applies unchanged and is the reason this section names no multiplier.

### 3.5 Verdict disagreement (F3) — the trust ordering, and where it breaks

**The ordering is defensible, and for the stated reason.** The receipt is written by a deterministic script into a
directory the transport agent cannot write (`disallowedTools` plus a Bash clamp to one command), via
`_atomic_write`. The workflow's `v.verdict` is an LLM's structured echo. Preferring the artefact with provenance
over the model's self-report is the same ordering the project already enforces everywhere else — "enforcement
fields are git-derived, never model-self-reported". Keep it.

**The unconditional hole: a missing `diff_digest` silently removes the forgery check.**
`--expect-diff-digest` is appended **conditionally**:

```js
(v.diff_digest ? ' --expect-diff-digest ' + q(String(v.diff_digest)) : '')   // emit-workflow.py:3056
```

and Record only compares when the string is non-empty (`_exp_d`, `:4646`). The degraded transport object — an
agent that summarised instead of returning JSON verbatim, or whose Bash call timed out mid-flight — is exactly
the object most likely to be missing `diff_digest`. So the spec's claim that "the digest binds the sealed patch"
holds in the healthy case and lapses precisely in the failure case F3 exists to handle. Under F3 that object's
receipt is **accepted** on the strength of four conditions that say nothing about the tree. This one is reachable
today and is the sharp edge of the feature.

**The latent hole: nothing binds a receipt to the attempt that produced it.** Verified in HEAD:

- The receipt path is **attempt-invariant**: written at `emit-workflow.py:4019` and read at `:4696`, both
  `os.path.join(run_dir, "receipts", "%s.gate.json" % job_id)`. A re-run overwrites in place.
- **All four F3 conditions are attempt-invariant.** The receipt parses; `job_id` is the same across attempts;
  `manifest_digest` is the run's, identical across attempts; `verdict ∈ {pass, blocked, error}` says nothing about
  which attempt produced it.

**How reachable is it today? Less than it first looks — I checked, and the honest answer narrows the claim.**
`withRetry` wraps **only** the Implement stage (`:2814`), and it retries only when an attempt *produced no
result*. Every Implement retry and the reviewer lift (`:2830`) complete **before** `gateStage` receives the final
value, so within one workflow execution `gate-receipt` runs **once per job**. There is no in-run re-gate of one
job against two different trees. The genuine multi-attempt-different-tree path is **cross-run**:
`prior_attempt_failed` reads `results/<id>.json` from a previous emitter run (`:1258`, `:2166`) and `/v:resume`
re-runs the emitter — and that is exactly the path `resume-prepare` guards, moving `receipts/<id>.gate.json` aside
as `receipts/<id>.gate.superseded-<realised-or-ts>.json` *"so the integration authority never reads the crashed
attempt's verdict as this attempt's"* (`:9069`).

**So the stale-receipt case is currently held shut by `resume-prepare` alone, and F3 removes the check that would
catch it if that single defence ever lapsed.** Two things make that worth closing anyway. First,
`resume-prepare`'s own docstring notes *"Only the orchestrator calls this; nothing in the emitted script does"* —
so any resume path that does not route through the orchestrator leaves a stale receipt in place, and F3 would then
accept it rather than refuse it. Second, today's code refuses this shape as `error`; F3 accepts it. Removing a
redundant check is only free while the non-redundant one holds, and the binding below costs one field.

**The field that must bind the receipt to THIS attempt.** The precedent is
[Kleppmann's fencing token](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html): a
monotonically increasing value issued at acquisition, carried on every write, and **checked by the resource**,
which rejects any write bearing a token lower than the last accepted one. The CI analogue is the standard
GitHub Actions practice of putting the attempt number in the artifact name so a retry cannot overwrite or be
mistaken for the first attempt's output. Requirements for the token here:

1. **Minted by the workflow before the Gate stage runs**, never by the agent — an agent-supplied token proves
   nothing, for the same reason the echo proves nothing.
2. **Passed to `gate-receipt` on the clamped command line** so the receipt records the attempt it belongs to.
3. **Compared by Record as a fifth mandatory condition**, alongside parse/`job_id`/`manifest_digest`/verdict.
4. **A mismatch is `error` and refuses** — never a `verdict_disagreement`. A stale receipt is not a disagreement;
   it is a receipt for a different event.

The cheaper alternative, which needs no new comparison: make the path itself attempt-scoped
(`receipts/<job_id>.gate.attempt-<n>.json`). A stale file then cannot be found at all, which is the GitHub Actions
pattern and fails closed by construction. Either is defensible; it is an architecture call (§6).

Two smaller points on F3. The neutral wording is right and the "records establish no cause" framing is exactly the
correction #19 D asked for — keep it verbatim. And a disagreement should be **counted at run level**: eleven jobs
all reporting a disagreement is one broken transport, not eleven independent oddities, and only an aggregate makes
that visible.

### 3.6 Unresolved-write logging (F4) — precedent, and one bypass

**Precedent is strong and consistent across three independent systems.** Every mandatory-access-control system
that logs denials has had to solve "an expected denial drowns the real one", and all three landed on the same
shape: **label or suppress the expected case by policy, so a record in the log means something.**

*(Paraphrased, not quoted: these three claims come from search summaries of the linked pages rather than pages I
fetched and copied. The mechanisms are long-standing and the links are authoritative, but do not lift them into
the plan as verbatim quotations without re-reading the source.)*

- **AppArmor — "deny audit quieting".** Operations that trigger a `deny` rule are not logged by default
  ([apparmor(7)](https://manpages.debian.org/unstable/apparmor/apparmor.7.en.html)). The expected denial is silent
  by design.
- **SELinux — `dontaudit`.** Policy authors suppress cosmetic denials so users are not buried in noise. Crucially,
  the mechanism ships with an **escape hatch**: `semodule -DB` disables all `dontaudit` rules so everything is
  logged again — precisely because a suppressed denial occasionally turns out to be a real problem
  ([Red Hat](https://www.redhat.com/en/blog/selinux-denial2)).
- **Landlock — `LANDLOCK_ADD_RULE_QUIET` / `quiet_*`.** Denials against a program that sandboxed itself are logged
  by default, on the reasoning that such events usually indicate unexpected behaviour; denials explicitly marked
  quiet are suppressed ([kernel docs](https://docs.kernel.org/userspace-api/landlock.html)).

F4's design — the bootstrap writes no record and instead emits `ALLOW (register-lane bootstrap)` to the log —
matches this precedent exactly, and the log line is the SELinux escape hatch (`CV_LANE_GUARD_LOG` already exists
per `AGENTS.md`). The docs should say so in one sentence: **a suppression mechanism must ship with the documented
way to see what it suppressed**, and here that way is the log.

**The bypass.** F4 recognises the bootstrap by substring: *"A `Bash` call whose command **contains**
`compound-v-emit-workflow.py register-lane`"*. None of the three precedents keys on text inside the request; all
key on the **subject** (the confined domain, the ruleset that denied). A substring rule over a command string
means any Bash call that merely mentions that text suppresses its own unresolved record —
`echo 'compound-v-emit-workflow.py register-lane'; <anything>` — and the suppressed record is exactly the audit
signal F4 exists to sharpen. The write is allowed either way, so this costs auditability rather than
authorization, but auditability is the entire deliverable of F4. Narrow it to the **clamp shape** already used at
`:2995`: the command, after an optional interpreter prefix, must *begin with* the emitter path followed by
`register-lane`, and must carry no `;`, `&&`, `||` or `|` after it. (A "must be genuinely first" clause adds
nothing — an unresolved call has no lane entry for its cwd by definition, so the condition is always true.) And
log the matched command verbatim on the `bootstrap` line, so a reader can see exactly what was forgiven.

**On "newest live lane map".** Attributing an unresolved write to the newest live run is a heuristic, and #19 E is
a complaint about records filed under the wrong run. `candidate_runs` is the correct mitigation and the spec has
it. Add one field so the run name is never read as fact: record how the run was chosen
(`attribution: "run-dir-flag" | "newest-live-lane-map"`). Audit records name the rule that produced them; this one
should too.

### 3.7 `/skill-doctor` and context hygiene

**The bloat is real and structural.** A skill's listing enters the system prompt every turn whether or not it is
used — that is how Claude decides what is available ([Claude Code skills docs](https://code.claude.com/docs/en/skills)).
`/skill-doctor` shipped in **2.1.261 on 2026-09-04** ([implicator.ai](https://www.implicator.ai/anthropic-claude-code-skill-doctor-context-audit/))
and *"flags skills in the listing that have never been invoked and says where to turn them off."* The remediation
surface is `skillOverrides`, with four states — `on`, `name-only` (name without description),
`user-invocable-only` (hidden from Claude, still reachable via `/`), and `off`.

**Users do want control.** [#26838](https://github.com/anthropics/claude-code/issues/26838) — "allow disabling
built-in skills" — carries **44 👍**, and [#52456](https://github.com/anthropics/claude-code/issues/52456) reports
the plugin-uninstall flow failing to stick. There is a whole trade-press genre ("most skills are dead weight").
So an offer would not be unwelcome in the abstract.

**"Report only, never disable" is nonetheless the right posture, for three reasons — and the spec only states one.**

1. *(spec states it)* The data is per-machine session history, and a hook- or description-fired phase is not a
   skill invocation, so `0×` beside `v-dispatch` does not mean unused. Acting on that number would be acting on a
   measurement that is structurally wrong for this plugin's own phases.
2. *(spec does not state it, and it is the decisive one)* **`skillOverrides` obeys settings layering, and project
   scope is committed.** A write based on one developer's local usage history silently changes every teammate's
   harness through version control. A per-machine measurement must never drive a shared-scope write.
3. *(spec does not state it)* The native command **already tells the user where to turn things off**. A plugin
   re-offering that adds a second actor to a decision the harness already handles, and adds the risk that the
   plugin disables a skill the user wanted.

The honest middle, which satisfies the demand behind #26838 without any of the above: print the report, and print
the exact `skillOverrides` snippet the user could paste, explicitly labelled as not written and naming the scope
it would land in. That is stricter than the repo's existing Step-4d "offer, merge on a yes" style, and
deliberately so — 4d writes a setting that affects this repo's runs, whereas this one would affect every session
on the machine.

**One currency caveat for the plan.** `skillOverrides` is **missing from the official settings reference**
([#56494](https://github.com/anthropics/claude-code/issues/56494)). Any doc that prints the exact spelling is
depending on an unpinned surface; say where it was observed and when.

---

## 4. Common Traps in This Domain

1. **Subtracting untracked paths and believing tracked ones are covered.** `--preexisting` is a
   `git ls-files --others` snapshot. Lockfiles, generated sources, and `.gitattributes`-driven rewrites are
   tracked and pass straight through it into the job's diff.
2. **Copying a CI recipe across package-manager major versions.** `yarn --frozen-lockfile` is deprecated in Berry;
   `enableGlobalVirtualStore` became `virtualStoreType: global` at pnpm 11.23.0. A recipe that "worked" may be
   silently enforcing nothing.
3. **Relying on `CI=1` semantics outside CI.** pnpm and Yarn both turn on frozen/immutable installs implicitly
   when `CI` is set. A provisioning shell is not CI, so the safe default there is the explicit flag.
4. **Treating "the file beats the echo" as complete without binding the file to the event.** This is the classic
   stale-lock-holder problem; the standard answer is a fencing token, and the standard mistake is to check
   *identity* (which job) rather than *recency* (which attempt).
5. **Pattern-matching an exemption on attacker-influenceable text.** Every MAC system keys suppression on the
   subject. A substring rule over a command string is a self-service exemption.
6. **Labelling a downgrade honestly and then making it count as the thing it is not.** The label is not the
   control; the acceptance rule is.
7. **Quoting a vendor's cost claim without its baseline.** "Costs less than running the stronger model throughout"
   is true against a specific baseline that Compound V's Opus-executor policy does not match.
8. **Acting on per-machine telemetry in a shared-scope config file.**
9. **Shared caches as an unwatched channel between trust levels.** The scope gate watches the worktree; a shared
   pnpm store or npm cache lives outside it.

---

## 5. Recent Breaking Changes (last 12 months) and Compliance / Honesty Notes

**Version-gated surfaces this release depends on.** All from
[advisor docs](https://code.claude.com/docs/en/advisor) and [skills docs](https://code.claude.com/docs/en/skills):

| Surface | Gate | Note |
|---|---|---|
| `/skill-doctor` | ≥ 2.1.252; shipped 2.1.261 (2026-09-04) | Unavailable over Remote Control and with feature-flag fetching off. |
| Advisor tool | Experimental; **Anthropic API only** | Not on Bedrock, Claude Platform on AWS, Google Cloud Agent Platform, or Microsoft Foundry. Off when feature-flag fetching is off (e.g. `DISABLE_TELEMETRY`). `CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1` disables entirely. |
| Fable 5.1 as advisor | ≥ 2.1.257 + Fable access + one-time usage-credits consent via `/model fable` | Before consent, Claude Code silently sends requests **without** the advisor. |
| `/advisor` in headless/SDK/desktop/Remote Control | ≥ 2.1.260 | |
| Advisor pairing table | Changed with Opus 4.7+ | *"An Opus 4.7 main with an Opus 4.6 or Sonnet 5 advisor is rejected."* The `opus` alias *"advances with new Claude Code releases"* — a pinned alias is not a pinned model. |
| `skillOverrides` | Undocumented in the settings reference (#56494) | Four states: `on` / `name-only` / `user-invocable-only` / `off`. |
| Yarn Berry | `--frozen-lockfile` deprecated → `--immutable` | |
| pnpm ≥ 11.23.0 | `enableGlobalVirtualStore` → `virtualStoreType: global` | |

**Honesty notes (no external regulator applies; the constraints are the project's own promises).**

- **Anti-ruflo** binds every advisor number. `usage.advisor_calls` must be measured from transcript content blocks
  or `null`. This audit deliberately states no cost multiplier for §3.4.
- **"No fabricated metrics"** extends to *borrowed* metrics: Anthropic's `-11.9%` and `$7.69/attempt` are theirs,
  measured on their benchmarks with their pairings, and must be attributed and scoped if quoted at all.
- **Honesty about the second opinion is a user-facing promise**, not an internal nicety: the downstream project
  (#19, #12) chose Compound V partly for cross-model verification. Substituting same-family review without a
  conspicuous, plain-language disclosure would be the single most damaging thing in this release.

---

## 6. Open Questions for the Human

1. **Does a same-family second look satisfy the SCOPED+ mandatory cross-model gate, or only satisfy it while
   recording `cross_model: false`?** This is a product/policy call about what the gate promises, and I will not
   decide it. (§3.3)
2. **Attempt binding: new receipt field, or attempt-scoped receipt filename?** Both close the hole; the field is
   more explicit, the filename fails closed by construction and needs no comparison. Architecture call. (§3.5)
3. **Is `advisorModel: fable` worth it for this repo given Opus executors and usage-credit billing?** The one
   published data point favours Opus-executor + Fable-advisor; it is Anthropic's benchmark, not ours, and it is
   Oleg's money. (§3.4)
4. **Should the docs recommend a shared pnpm store / npm cache at all**, given that Compound V runs lower-trust
   backends (`agy`, `cursor-agent`) on the same machine and pnpm's own guidance restricts a shared writable store
   to one trust boundary? (§3.2)
5. **May a `provision_command` ever legitimately modify a tracked file?** Some platform-specific installs
   regenerate a lockfile. Recommended default: no, and the validator says nothing (it cannot know) — so this is a
   documentation-and-blame question, not a code one. (§3.1)
6. **Live-probe question rather than a decision:** do `WorktreeCreate` / `WorktreeRemove` hooks fire for
   `agent_isolation: worktree` subagent worktrees? If yes, there is a native alternative to the manifest key.
   **UNVERIFIED.** (§3.1)

**Knowledge base:** per the task's "touch no other file" instruction, **nothing was appended to
`docs/superpowers/expert/_knowledge-base/`**. Two domains here have no KB file and would earn one —
`ci-dependency-provisioning` (§3.1/§3.2 generalise cleanly into a reusable per-ecosystem matrix) and
`llm-self-review-honesty` (§3.3). Worth a follow-up pass.

---

## 7. Design Constraints for the Plan (non-negotiable)

**Provisioning (F1)**

- **MUST-1** — The author-facing rule MUST cover all five common ecosystems with exact commands, not npm alone:
  `npm ci` · `pnpm install --frozen-lockfile` · `yarn install --immutable` (Berry) / `--frozen-lockfile` (v1) ·
  `uv sync --frozen` or a worktree-local venv + `pip install -r` · `cargo build --locked` · `go mod download` ·
  `bundle config set --local frozen true && bundle install`. Each row MUST name the alternative that rewrites the
  lockfile.
- **MUST-2** — The docs MUST state the mechanism, not just the rule: `--preexisting` subtracts **untracked and
  ignored paths only**, so a tracked file the provision command rewrites is attributed to the job and can be
  BLOCKED or, inside `write_allowed`, merged unattributed.
- **MUST-3** — The docs MUST say **why** direct-mode jobs do not provision: `npm ci` removes an existing
  `node_modules` before installing, which in a shared checkout destroys a concurrent sibling's tree.
- **MUST-4** — The docs MUST state that provisioning can supply gitignored *state* (`.env`, `.venv`) by copying it
  before the snapshot, and that the same copy performed by the agent is an out-of-lane write. `.venv`/`.env` MUST
  be named, not only `node_modules` — #27744 ranks them higher.
- **MUST-5** — `provision_command` MUST be documented as running from the worktree root, with the monorepo form
  (`cd sub && npm ci`) shown, since `npm ci` requires a lockfile in its working directory.
- **MUST-6** — A BLOCKED result for a job whose `provision_error` is set MUST name the provisioning failure in its
  summary. A provisioning timeout MUST NOT surface only as thousands of `node_modules/**` violations — that is the
  original #19 A symptom.
- **MUST-6a** — The `register-lane` Bash call's `timeout` MUST be raised to at least `provision_timeout_s`.
  Today that prompt block (`emit-workflow.py:2419`) sets no timeout and inherits the Bash tool's 120 s default,
  so `provision_timeout_s` values of 600 or 1800 are unreachable and a long install is killed mid-flight.
- **MUST-6b** — Provisioning output MUST be redirected to a file, not left on the agent's transcript. A verbose
  install at turn one otherwise occupies the job's context for its whole life, and every advisor call re-reads it
  uncached.
- **MUST-7** — If the docs recommend a shared package store, they MUST carry pnpm's trust-boundary condition and
  note that Compound V runs lower-trust backends (`agy`, `cursor-agent`) on the same machine. `virtualStoreType:
  global` MUST be given as the current spelling with its `enableGlobalVirtualStore` predecessor and the 11.23.0
  boundary. npm's `~/.npm` MAY be recommended but MUST NOT be described as race-free.

**Verdict disagreement (F3)**

*(Order of severity: MUST-11 is reachable today and is the one that must not slip. MUST-8..MUST-10 close a hole
currently held shut by `resume-prepare` alone — defence in depth, and cheap.)*

- **MUST-8** — The receipt MUST be bound to **this attempt**, by a token minted by the workflow before the Gate
  stage and compared by Record as a **fifth mandatory condition**, or by making the receipt path attempt-scoped so
  a stale file cannot be found. A receipt that satisfies parse/`job_id`/`manifest_digest`/verdict but belongs to a
  previous attempt MUST be refused.
- **MUST-9** — An attempt mismatch MUST be `error`, never a `verdict_disagreement`. A stale receipt is not a
  disagreement; it is a receipt for a different event.
- **MUST-10** — The attempt token MUST NOT originate from the agent. An agent-supplied token has the same
  provenance problem as the echo the whole feature exists to distrust.
- **MUST-11** — When the workflow's verdict object carries **no** `diff_digest`, the receipt MUST be refused
  rather than accepted with a disagreement note. Today `--expect-diff-digest` is appended conditionally
  (`emit-workflow.py:3056`), so the forgery axis the spec relies on is silently absent in exactly the degraded
  case F3 is written for.
- **SHOULD** — `verdict_disagreement` SHOULD be counted at run level and surfaced by `/v:status`; a run where
  every job disagrees is one broken transport, not N oddities.
- **KEEP** — The neutral wording ("this comparison establishes no cause") is exactly right and MUST survive
  review unedited.

**Advisor and the second opinion (F7)**

- **MUST-12** — No Compound V document may state or paraphrase "the advisor typically costs less than running the
  stronger model throughout" without its baseline. Compound V's implementers and reviewers are Opus, which is
  Anthropic's own "fits poorly … executor already close to the advisor" case. Where a cost claim is made at all,
  it MUST be attributed and scoped, and `usage.advisor_calls` MUST be measured or `null`.
- **MUST-13** — The docs MUST record that Claude Code exposes **neither** of the API's advisor cost controls
  (`max_uses`, advisor-side `caching`), so per-job advisor spend can be measured but not capped.
- **MUST-14** — Every rendering of a rung-2 receipt MUST carry a plain-language disclosure that names what was
  **not** obtained. Recommended exact line: *"Same-family review: Claude reviewed by Claude (advisor-assisted).
  It shares the writer's blind spots and is not the cross-model check — no second vendor saw this."* The words
  "decorrelation", "second look" and "second opinion" MUST NOT stand alone as the disclosure.
- **MUST-15** — Rung 2 satisfying the SCOPED+ mandatory second look MUST stamp `cross_model: false` on the record.
  An honest label plus an unconditional equivalence rule is less honest than no label.
- **SHOULD** — The agent nudges SHOULD keep the existing "advice is evidence, re-verify against the tree" framing,
  which matches the harness's own behaviour: *"Claude generally follows the advisor's guidance, but adapts when
  its own evidence contradicts a specific claim."*

**Lane-guard logging (F4)**

- **MUST-16** — The bootstrap recogniser MUST NOT be a bare substring test over the command. It MUST match the
  clamp shape: `tool_input.command`, after an optional interpreter prefix, **begins with** the emitter path
  followed by `register-lane`, and contains no `;`, `&&`, `||` or `|` after it. As written,
  `echo 'compound-v-emit-workflow.py register-lane'; <anything>` suppresses its own record.
- **MUST-17** — The `bootstrap` log line MUST carry the matched command verbatim, so the audit can see exactly
  what was forgiven. The docs MUST name the log as the "show me everything" channel — a suppression mechanism
  ships with its escape hatch (SELinux `semodule -DB` is the precedent).
- **SHOULD** — The record SHOULD name how the run was chosen (`attribution: "run-dir-flag" |
  "newest-live-lane-map"`) alongside `candidate_runs`, so a heuristic attribution is never read as fact.

**Skill hygiene (F6)**

- **MUST-18** — `/v:init` Step 1f MUST remain report-only and MUST NOT write `skillOverrides`. The decisive reason
  MUST appear in the docs: `skillOverrides` obeys settings layering and project scope is committed, so a
  per-machine usage count would silently reconfigure every teammate's harness.
- **MUST-19** — If a remediation is offered, it MUST be a printed, copy-pasteable snippet naming the target scope,
  explicitly labelled as not written — not the Step-4d merge-on-yes pattern.
- **MUST-20** — Any doc printing the `skillOverrides` spelling MUST say where and when it was observed, because
  the setting is absent from the official settings reference (#56494).
