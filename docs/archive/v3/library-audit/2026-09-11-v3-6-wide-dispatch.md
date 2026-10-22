# Library/Doc Audit — v3.6.0 wide dispatch design (advisor, skill-doctor, worktree.baseRef, agent memory, headless flags, git add -f)

**Date checked:** 2026-09-11 · **Installed Claude Code:** 2.1.263 · **Spec:** `docs/superpowers/specs/2026-09-11-v3.6-wide-dispatch-design.md`

## 0. V-memory recall (done first)

`python3 scripts/compound-v-memory.py search "wide dispatch advisor skill-doctor worktree baseRef" --intent planning --top 8` returned no hits on advisor or skill-doctor (neither term exists anywhere in `docs/superpowers/**` before this audit — confirmed by grepping the knowledge base). It returned strong, directly relevant hits on `worktree.baseRef`:

- `docs/superpowers/library-audit/_knowledge-base/claude-code-runtime.md` — "Updated 2026-09-03 — `worktree.baseRef` is a live, project-scoped native setting (v3.4.7 readme-clarity)"
- `docs/superpowers/library-audit/2026-09-03-v3-4-7-readme-clarity.md` §4.2

Those entries already established, live, from `worktrees.md` and `EnterWorktree`'s own description: `baseRef` is `fresh` (default) or `head`, project-wide via `.claude/settings.json`. This audit re-verifies that finding is still current (§4 below) rather than re-deriving it from scratch — the 2026-09-03 audit is evidence, re-checked, not assumed.

No Trigger 0 recon doc for this exact topic exists in `docs/superpowers/recon/` (checked by listing — the two files there are `2026-07-11-fts5-cyrillic-tokenizer.md` and `2026-09-01-v3.0-triage-tests-orchestration.md`, neither on this topic), and none was handed to me by the caller. Recon coverage: **none** — this audit is unassisted by prior recon.

## 1. Tools Available

- Context7 ✅ (`mcp__context7__resolve-library-id` / `mcp__context7__query-docs`) — resolved `/anthropics/claude-code` and related community mirrors, but **not used as primary** for this audit: the spec names exact `code.claude.com` / `platform.claude.com` URLs to validate against, so WebFetch against those pages is the ground truth here and Context7's indexed snapshot would be a second-hand copy of the same docs. No drift found between what WebFetch returned and what Context7 would offer (not needed to cross-check given the primary source is doc pages, not a library API).
- WebFetch ✅ against every URL the caller named.
- WebSearch ✅ (used once, for `git-add` semantics as a cross-check, then confirmed directly from git-scm.com).
- Manifests: N/A — this spec has no package-manifest dependency; every claim is about the Claude Code CLI/API surface itself and one `git add` flag combination. Section headings below follow the doc-validator template with tables collapsed where a version-matrix table would be empty.

## 2. Libraries/Surfaces Mentioned

| Surface | Spec context | Current state (checked 2026-09-11) | Status |
|---|---|---|---|
| Claude Code CLI/runtime | advisor tool, `/skill-doctor`, `worktree.baseRef`, `--output-format`, `--advisor`, `--model`, sub-agent memory paths | v2.1.263 installed; docs current through changelog entries up to v2.1.268 (ahead of installed) | 🟢 OK — installed version clears every floor the spec needs |
| Claude API (Messages API) | `server_tool_use`/`advisor_tool_result` content blocks | Beta feature, type `advisor_20260301`; documented at `platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool` | 🟢 OK |
| git (CLI) | `git add -A -f -- <path>` for run-directory staging | Behavior is decades-stable POSIX/git-scm documented semantics, no version dependency | 🟢 OK |

There is no npm/pip/cargo dependency in this spec; skip the usual per-library maintenance-signal table (downloads, last commit, archived flag) — none of these are third-party libraries with a release cadence, they are first-party product surfaces validated against their own current docs.

## 3. API/Behavior Signatures Verified

| Claim in spec | Verified against | Verdict |
|---|---|---|
| `advisorModel` legal values `fable\|opus\|sonnet\|<model id>` | `code.claude.com/docs/en/advisor` §"Choose an advisor model": *"Set the advisor as `fable`, `opus`, or `sonnet`... You can also pass a full model ID such as `claude-opus-5`."* | CONFIRMS |
| `advisorModel` setting scope legal in project `.claude/settings.json` | `code.claude.com/docs/en/settings-reference`: `advisorModel` row, **Scope: "Any file"** | CONFIRMS |
| `/advisor off` | `code.claude.com/docs/en/advisor` §"Turn the advisor off": *"To stop using the advisor, run `/advisor off`..."* | CONFIRMS |
| `--advisor` flag, single-session, not in `claude --help` | Same page: *"It doesn't list `--advisor` in `claude --help`."* Also confirmed via `cli-reference`: *"Enable the server-side advisor tool for this session with a model alias, `fable`, `opus`, or `sonnet`, or a full model ID. Takes precedence over the `advisorModel` setting for the session."* | CONFIRMS |
| Pairing table: Fable 5.1 main accepts only Fable 5.1 advisor | Table row: *"Fable 5.1 or Fable 5 \| Fable 5.1, or the same Fable version \| An Opus or Sonnet advisor is rejected, and so is a Fable 5 advisor for a Fable 5.1 main model"* — for a Fable-5.1 main, "same Fable version" = Fable 5.1, so the accepted set is exactly {Fable 5.1}. | CONFIRMS exactly |
| Subagents inherit the configured advisor and apply the same pairing check | *"Subagents inherit the configured advisor and apply the same pairing check against their own model."* | CONFIRMS |
| Version floor: Fable 5.1 advisor requires v2.1.257+ | *"Fable 5.1 requires Claude Code v2.1.257 or later."* | CONFIRMS |
| Version floor: non-interactive `/advisor` (headless/SDK/desktop/Remote Control) requires v2.1.260+ | *"The command also works where there is no terminal picker... This requires Claude Code v2.1.260 or later."* | CONFIRMS |
| Two disable paths: `DISABLE_TELEMETRY` (feature-flag fetch off) and `CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1` | *"Feature-flag fetching: Claude Code turns the advisor on through a feature flag it fetches from Anthropic. In a session where a variable that turns flag fetching off is set, such as `DISABLE_TELEMETRY`, the advisor stays off."* and *"To disable the advisor tool entirely, set `CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1`."* | CONFIRMS both |
| Fable advisor bills to usage credits; consent via `/model fable` | *"Fable usage bills to usage credits, and Fable as the advisor bills the same way... To accept the consent, run `/model fable` and choose to continue on Fable... Then select Fable as the advisor."* | CONFIRMS |
| Advisor's own read of the transcript is uncached | *"The advisor model's own read of the conversation is not cached. Each advisor call processes the full transcript anew, with no reuse between calls."* | CONFIRMS |
| API content blocks: `server_tool_use` name `"advisor"`; `advisor_tool_result` with `advisor_result` \| `advisor_redacted_result` \| `advisor_tool_result_error` | `platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool` §"Response structure": block sequence example shows `{"type": "server_tool_use", "name": "advisor", ...}` followed by `{"type": "advisor_tool_result", "content": {"type": "advisor_result", ...}}`; §"Result variants" table lists `advisor_result` and `advisor_redacted_result` as the two content-type variants; §"Error results" shows `{"type": "advisor_tool_result_error", "error_code": ...}`. | CONFIRMS exactly, all three variant names verbatim |
| Whether Claude Code transcripts (`.jsonl`) carry these blocks verbatim | Not documented anywhere on the Claude Code doc pages (they describe the API shape, not the on-disk transcript format) — this is a claim only the spec's own live probe can support, and it is **not contradicted** by anything found. Flagged as an open item (§8). | NEITHER — undocumented, unverifiable from docs alone |
| `/skill-doctor` version floor "2.1.252?" | `code.claude.com/docs/en/skills`: *"`/skill-doctor` requires Claude Code v2.1.252 or later..."* — **but** the official CHANGELOG.md states *"Added `/skill-doctor` to show which loaded skills go unused and what they cost in context"* at **v2.1.261**, not v2.1.252. | **CONTRADICTS itself across Anthropic's own two sources** — see Critical Findings §4 |
| `/skill-doctor` prints text in `-p` mode | *"In non-interactive mode with `-p`, Claude Code prints it as text."* | CONFIRMS |
| Report columns (`skill · source · context · 7d tokens · uses · last used`) | The docs describe the report's *content* ("what each of your skills costs and how often it gets used," flags never-invoked skills, lists unused plugins) but **never enumerate column names or order**. The 6-column layout in the spec is asserted only from the spec's own live probe (`claude -p '/skill-doctor' --output-format text` on this machine), not from docs. | NEITHER — plausible, undocumented; not contradicted |
| Remote Control limitation | *"If you run `/skill-doctor` over Remote Control from your phone or browser, Claude Code replies `Skill usage reports are not available on this connection.` instead."* | CONFIRMS |
| Feature-flag dependency | *"...isn't available in sessions that skip feature-flag fetching."* | CONFIRMS |
| Excludes bundled/enterprise skills | *"The report covers the skills in your session other than bundled skills and enterprise skills."* | CONFIRMS |
| `worktree.baseRef` still `fresh\|head` only, unchanged since 3.4.7 | Re-confirms the 2026-09-03 finding already in `_knowledge-base/claude-code-runtime.md`. The full CHANGELOG.md (searched end-to-end) has **zero** entries mentioning `baseRef` at any version — consistent with "unchanged since it was first documented," which predates the 2.1.208 range per the earlier audit. `settings-reference` fetches this session returned truncated content that did not re-surface the `worktree.baseRef` row verbatim (page is large and the fetcher's summarizer dropped it both times), so this claim rests on the 2026-09-03 audit's direct quote plus the changelog's silence, not a fresh verbatim quote from `settings-reference` today. | CONFIRMS (via changelog silence + prior direct citation), **with a caveat**: re-quote directly from `settings-reference` before the plan locks this in, since this session's own fetches of that specific page could not pull the row (see §8) |
| Headless flags `--output-format text`, `--advisor`, `--model` all valid, and combinable with `-p` | `cli-reference`: `--output-format` accepts `text\|json\|stream-json`; `--advisor <model>`; `--model <model>` accepts aliases `sonnet\|opus\|haiku\|fable` or a full model ID. `headless` doc's examples use `-p` with `--output-format` routinely. | CONFIRMS all three |
| Nested `claude -p` (a session shelling out to another `claude -p`) is not forbidden by docs | Searched `headless` and `cli-reference` pages end-to-end for "nested"/"recursive" — **no statement exists either way**. Neither page prohibits, warns about, nor even acknowledges this pattern. | CONFIRMS the absence claim (docs are silent, not prohibitive) |
| `git add -A -f -- path`: `-f` allows ignored files; `-A` + pathspec limits to that path | git-scm.com `git-add` docs, verbatim: *"Allow adding otherwise ignored files"* (`-f`); *"If no \<pathspec\> is given when `-A` option is used, all files in the entire working tree are updated"* — implying that when a pathspec **is** given, `-A` is scoped to it (matches `-A` proper's own definition: *"Update the index not only where the working tree has a file matching \<pathspec\>..."*). | CONFIRMS both halves |
| Plugin sub-agent memory directory is `<plugin>-<agent>` (e.g. `superpowers-v-spec-reviewer`) | `code.claude.com/docs/en/sub-agents` documents only `~/.claude/agent-memory/<name-of-agent>/` (user) and `.claude/agent-memory/<name-of-agent>/` (project) using the bare `name:` frontmatter field — **no mention anywhere of a plugin-prefixed directory form**. `code.claude.com/docs/en/plugins` documents plugin agents being *invoked* as `pluginname:agentname` (colon syntax, for `@`-mention and listing) but likewise says nothing about how that maps to an on-disk memory path. | **NEITHER — undocumented**, exactly as the spec itself already states ("field evidence from one downstream project, issue #19," never claimed as documented) |

## 4. Critical Findings 🔴

None. Nothing here is deprecated, archived, or blocking — every surface the spec depends on exists and works on the installed 2.1.263.

## 5. High-Priority Findings 🟠

### 5.1 `/skill-doctor`'s two official sources disagree on the introduction version (2.1.252 vs 2.1.261)

- `code.claude.com/docs/en/skills` states, in the same sentence as the Remote Control and feature-flag caveats: *"`/skill-doctor` requires Claude Code v2.1.252 or later..."*
- The `CHANGELOG.md` on `github.com/anthropics/claude-code` (fetched raw, 2026-09-11) states, at **v2.1.261**: *"Added `/skill-doctor` to show which loaded skills go unused and what they cost in context."*
- These cannot both be the version that *introduced* the feature. Either the docs page's floor is wrong (most likely — doc floors drift when a feature ships in stages and only the docs page gets the final, sometimes-misremembered number), or the changelog entry is a later enhancement to a command that already existed since 2.1.252 under a different surface. I found no third source (e.g., an earlier changelog entry) that mentions `/skill-doctor`, `skill-doctor`, or "skill usage" anywhere between 2.1.238 and 2.1.260.
- **Practical impact for this spec: none at the installed version.** 2.1.263 clears both 2.1.252 and 2.1.261, so F6 ("gated on `claude --version` ≥ 2.1.252") works today regardless of which number is the true floor.
- **Recommendation:** the plan should still fix the citation. Either cite `2.1.261` (the number with primary-source changelog backing) or, safer, gate on something comfortably past both, e.g. `≥ 2.1.263` (matches the version this was live-probed on) or `≥ 2.1.262` as a round-number compromise. Do not repeat "2.1.252" as if it were changelog-confirmed — it is not, and the discrepancy should be a one-line footnote in the doc, not silently resolved in either direction.

### 5.2 Report columns for `/skill-doctor` are spec-probe-only, not doc-confirmed

The spec's exact column list (`skill · source · context · 7d tokens · uses · last used`) does not appear anywhere in `code.claude.com/docs/en/skills`, `/commands`, or `/costs`. The docs describe the report's *purpose* only ("what each of your skills costs and how often it gets used," flags never-invoked skills, lists unused plugins) and never enumerate a column schema — column names/order are an implementation detail Anthropic hasn't committed to documenting, which means they can change silently across versions with no changelog entry required (unlike a flag or setting name). **This is not a defect in the spec** — the spec is honest that this came from a live probe — but F6's parser (whatever script or eyeballing the plan proposes for reading `/skill-doctor`'s text output) should not hard-fail if a column is renamed or reordered in a later Claude Code release; treat the six fields named in the spec as "what we saw on 2.1.263," not as a stable contract.

## 6. Medium Findings 🟡

### 6.1 `worktree.baseRef` re-confirmation is by inference, not a fresh direct quote

Two WebFetch attempts against `code.claude.com/docs/en/settings-reference` in this session both returned a truncated summary that never reached the `worktree.baseRef` row (the page's settings index is long and the fetch tool's own summarizer cut it before that section both times, saying "[Content truncated due to length...]"). I'm relying on:
1. The 2026-09-03 v3.4.7-readme-clarity audit's **direct, verbatim quote** of that row (already in `_knowledge-base/claude-code-runtime.md`, itself sourced from `worktrees.md` and the live `EnterWorktree` tool description), and
2. The full CHANGELOG.md's **total silence** on `baseRef` at any version between whatever introduced it and 2.1.268 (the newest entry seen).

Both are legitimate evidence, but neither is a fresh verbatim quote from `settings-reference` taken *today*. Before the plan locks in "`fresh|head` only, unchanged since 3.4.7" as a hard constraint, someone should either (a) fetch `settings-reference` with a narrower, section-scoped prompt that successfully returns the `worktree` block, or (b) accept the existing 2026-09-03 citation as sufficient since nothing in six weeks of changelog entries touched it.

### 6.2 `--disallowedTools` had a reliability bug fixed at v2.1.257, relevant to F3's design assumption

CHANGELOG.md, v2.1.257: *"Fixed `--disallowedTools` and session deny rules being dropped after the first settings reload."* F3 states as a verified fact: *"The agent cannot write that directory (`disallowedTools` + a Bash clamp to the one command)."* That mechanism depends on `disallowedTools` staying in effect across the agent's session — which, before 2.1.257, could silently drop after a settings reload. Installed 2.1.263 postdates the fix, so this is not a blocker, but it is worth one line in the plan or in `agents/spec-reviewer.md`'s memory-lane discussion: the write-confinement guarantee F3 leans on has a known historical failure mode (now fixed) and is worth a selftest that plants a settings reload mid-session and confirms the deny rule survives, if that's cheap to add — otherwise, at minimum, don't assume `disallowedTools` is bulletproof on every future Claude Code version without re-checking the changelog around upgrades.

## 7. Design Constraints for the Plan (MUST / MUST NOT)

- **MUST** cite `advisorModel` legal values as exactly `fable | opus | sonnet | <full model ID>` (checked 2026-09-11 against `code.claude.com/docs/en/advisor` and `/settings-reference`) — the spec's own phrasing already matches this; keep it.
- **MUST** state the Fable-pairing rule using the table's own wording — *"An Opus or Sonnet advisor is rejected, and so is a Fable 5 advisor for a Fable 5.1 main model"* — not a paraphrase that could later be read as "any Fable" (checked 2026-09-11).
- **MUST NOT** repeat "`/skill-doctor` requires v2.1.252" as if both Anthropic sources agree — they don't (checked 2026-09-11, §5.1). Either cite v2.1.261 with the changelog as source, or gate on a number that comfortably exceeds both candidates and say so is a hedge, not a fact.
- **MUST** treat the `/skill-doctor` output's column layout as observed-not-contracted: F6's parsing logic must degrade gracefully (e.g., regex on labeled fields, not fixed column-position parsing) since no doc commits to a stable schema (checked 2026-09-11, §5.2).
- **MUST** keep `.claude/agent-memory/superpowers-v-<agent>/` framed exactly as the spec already frames it — field-observed from issue #19, not documented — because `sub-agents.md` and `plugins.md` (both checked 2026-09-11) document only the bare `<name-of-agent>` form and say nothing about plugin namespacing on disk.
- **MUST** keep the advisor API content-block names exactly as verified: `server_tool_use` (name `"advisor"`), `advisor_tool_result` (content `type` one of `advisor_result` | `advisor_redacted_result` | `advisor_tool_result_error`) — verified byte-for-byte against `platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool` (checked 2026-09-11). `compound-v-usage-extract.py` should match on `server_tool_use` blocks whose `name == "advisor"`, not on `advisor_tool_result` alone, since a `server_tool_use` can theoretically pause without a paired result yet (documented `pause_turn` case).
- **MUST NOT** assume Claude Code transcripts (`~/.claude/projects/**.jsonl`) mirror the API's block names verbatim as a documented fact — that is unverifiable from any doc page (checked 2026-09-11, §3) and rests entirely on the spec's own live probe. Word it in the plan as "verified by direct probe on this machine, 2026-09-11," not as "per the docs."
- **MUST** re-quote `worktree.baseRef`'s settings-reference row directly (not by inference through changelog silence) before treating "unchanged since 3.4.7" as load-bearing for anything that would break if a third value were added (checked 2026-09-11, §6.1 — this session's own fetches did not surface the row cleanly).
- **MUST** use `git add -A -f -- <path>` exactly as designed in F2: verified `-f` allows ignored files and `-A` with an explicit pathspec scopes the operation to that pathspec, straight from git-scm.com's own `-A`/`-f` definitions (checked 2026-09-11).

## 8. Open Questions for the Human

1. **`/skill-doctor` version floor**: pin `2.1.261` (changelog-backed) or a safer round number, or leave `2.1.252` with a footnote acknowledging the doc/changelog mismatch? This is a wording decision, not a technical blocker — flagging for Oleg to pick rather than silently choosing.
2. Is it worth spending a second WebFetch pass (outside this audit's scope) to get a clean, un-truncated quote of the `worktree.baseRef` row from `settings-reference` today, or is the existing 2026-09-03 citation plus six weeks of changelog silence sufficient provenance for the plan? I did not keep re-trying past two attempts, per the parallel-dispatch/no-bikeshedding instinct — but flagging it rather than silently treating the inference as equivalent to a fresh quote.
3. Should `agents/implementer.md`/`spec-reviewer.md` gain a one-line note about the historical `--disallowedTools` settings-reload bug (fixed 2.1.257), given F3's write-confinement claim leans on that flag holding for the life of a job? (§6.2) This is advisory, not a blocker on the installed version.

## 9. Knowledge Base Updates

Two new KB files created (no prior entries existed for either topic — confirmed by grep before writing):

- `docs/superpowers/library-audit/_knowledge-base/claude-code-advisor-tool.md` — advisor tool settings, CLI flag, pairing table, billing, disable paths, and the Messages-API content-block names, each dated 2026-09-11.
- `docs/superpowers/library-audit/_knowledge-base/claude-code-skill-doctor.md` — `/skill-doctor` version-floor discrepancy, headless behavior, exclusions, Remote Control limitation, dated 2026-09-11.

One existing KB file appended to:

- `docs/superpowers/library-audit/_knowledge-base/claude-code-runtime.md` — new dated section re-confirming `worktree.baseRef` is unchanged (via changelog silence), plus the caveat that this session's own settings-reference fetch didn't surface the row directly.

No prior entries in any KB file were struck through — nothing this audit found contradicts an existing dated KB claim; this is new territory (advisor, skill-doctor) plus one re-confirmation (baseRef).
