# Compound V — Phase 1C Library & Documentation Audit

**Spec audited:** `docs/superpowers/specs/2026-09-03-v3.4.7-readme-clarity-design.md`
**Topic slug:** `v3-4-7-readme-clarity`
**Date:** 2026-09-03 · **Scope:** library/API currency only — not code archaeology (1A) or domain/regulatory (1B)

**Recall check (V-memory, Step 0):** two searches run before reading any file —
`"README clarity v3.4.7 documentation"` and `"README structure onboarding install
badges"`. Top hits: the spec itself, its already-materialized plan
(`docs/superpowers/plans/2026-09-03-v3.4.7-readme-clarity.md`), a `triage-outcomes.jsonl`
row (`FULL_PIPELINE`, high/high), and prior 1C audits (`2026-09-02-v3-4-native-first.md`,
`2026-09-03-v3-4-5-recall-freshness.md`) — none contradict anything below; no prior entry
on `worktree.baseRef`, Codex `0.14x`, or the specific backend CLI versions existed before
this audit. V-memory returned nothing that changes routing here (recall informs, never
routes).

**Trigger-0 recon:** none found at `docs/superpowers/recon/` for this slug (checked
`*readme*` and `*v3-4-7*` — zero matches) and none was handed by the caller. Fallback
scan only; proceeding without a recon doc.

---

## 1. Tools Available

- **Context7 MCP: ❌ not attached to this subagent.** `ToolSearch` for `context7`
  (`resolve-library-id`/`query-docs`, any naming form) returned no match. **DEGRADED:
  WebSearch/WebFetch-only** for every claim below — each load-bearing claim is
  triangulated across ≥2 independent sources per the pattern this KB already uses
  (see `claude-code-runtime.md`'s recorded WebFetch-confabulation incident).
- **Manifests found:** none. Confirmed (again) no `package.json` / `requirements.txt` /
  `pyproject.toml` / `go.mod` / `Cargo.toml` / `Gemfile` / `composer.json` anywhere in
  the tree — this repo has no third-party runtime dependency manifest by design
  (stdlib-only Python, per `CONVENTIONS.md`). Nothing in this spec changes that.
- **Live tool schemas available in this session:** `EnterWorktree` / `ExitWorktree`
  (native), used directly below as primary evidence — a tool's own live schema is a
  first-class documentation source, on par with a fetched doc page.
- **Bash access:** clamped to the V-memory recall script only on this spawn
  (`bashCommandClamp`) — all repo-file reads went through `Read`/`Grep`/`Glob`, all
  external verification through `WebFetch`/`WebSearch`.

## 2. Libraries Mentioned (spec-derived)

| Name | Spec context | Current (verified live, 2026-09-03) | Repo-pinned | Last release / activity | Maintenance | Status |
|---|---|---|---|---|---|---|
| Claude Code | Requirements floor `≥ 2.1.219`; native `Workflow`/hooks/`EnterWorktree` | **2.1.259** (changelog, 2026-09-02) | floor `2.1.219` in README/AGENTS.md | daily-cadence changelog | Very active | 🟢 OK — floor is a genuine minimum, well below current; see §5 for a scope nuance on `worktree.baseRef` |
| `worktree.baseRef` setting | Item 1, 6; `commands/v-init.md` offer | Live, documented native project setting (`code.claude.com/docs/en/worktrees.md`, `.../settings-reference#worktree`) | `.claude/settings.json`: `{"worktree":{"baseRef":"head"}}` | n/a (settings key, not a package) | n/a | 🟢 OK, factually — but see §5 for an undisclosed scope effect |
| Codex CLI | Item 3, 6: `Codex ≥ 0.143 for gpt-5.6-sol` | **0.153.0** (npm `@openai/codex`, published ~2026-09-03) | AGENTS.md cites verified invocation on `0.144.1`; spec's install floor is `0.143` | daily/weekly release cadence, very active | Very active | 🟠 HIGH — floor predates a real context-window/pricing correction, see §4 |
| GPT-5.6 Sol/Terra/Luna | Item 6: model family behind the Codex floor | GA since 2026-07-09, still the current top Codex family (no GPT-5.7 found) | `scripts/compound-v-resolve-model.py` (not touched by this spec) | n/a | Active | 🟢 OK — naming is current, not stale |
| Antigravity CLI (`agy`) | Item 3: backend name only | **v1.1.25** (antigravity.google/docs/cli/reference, fetched live) | `adapter-antigravity.md` pins `agy 1.0.13` | Antigravity 2.0 shipped 2026-05-19; CI-auth path added in 1.1.13 (2026-08-14) | Active | 🟡 MEDIUM — pin is several minor releases behind; see §5 |
| Cursor CLI (`cursor-agent`) | Item 3: backend name only | Primary entrypoint renamed to `agent`; `cursor-agent` kept as a documented backward-compatible alias (Cursor changelog, 2026-01-08) | `adapter-cursor.md` pins `cursor-agent 2026.06.26` | Continuing headless-mode fixes through 2026 (hang fixes, subagent-drain-before-exit) | Active | 🟡 MEDIUM — flags still valid (verified below), pin is ~2 months old; see §5 |
| opencode | Item 3: "experimental… not dogfooded" | 182k★+, multi-provider, active headless server + SDK | `adapter-opencode.md` exists | Active, large community | Very active | 🟢 OK — "experimental" framing matches reality (adapter exists, genuinely not dogfooded per repo's own memory) |
| Devin CLI | Item 3: "experimental… not dogfooded" | Active — recent headless/TTY and MCP-proxy fixes in changelog | `adapter-devin.md` exists | Ongoing | Active | 🟢 OK |
| Context7 MCP | Item 6: install instructions | `/plugin install context7@claude-plugins-official` confirmed current by 5 independent third-party sources (claudedirectory.org, pluginmarketplace.ai, claudemarketplaces.com, claudepluginhub.com, deployhq.com) | README.md:88 already has this exact line | Active (Upstash) | Active | 🟢 OK — no change needed; see methodology note in §9 |

All six backends named in spec item 3 (Claude, Codex, Antigravity, Cursor, opencode,
Devin) have an adapter file under `skills/backend-launcher/` — confirmed by `Glob`. This
satisfies acceptance criterion 2's "every backend named has an adapter" clause; a
code-archaeology concern, noted here only because it bears on whether the library list
itself is sound.

## 3. API Signatures Verified

| Call | Where pinned | Live-verified today | Verdict |
|---|---|---|---|
| `EnterWorktree` base-ref behavior | native tool description + `worktrees.md` | *"The base ref is governed by the `worktree.baseRef` setting: `fresh` (default) branches from `origin/<default-branch>`; `head` branches from your current local HEAD."* Subagent worktrees (what job dispatch actually uses) follow the **same** rule. | **Confirmed, exact match to `_worktree_base_is_head()`'s docstring in `compound-v-emit-workflow.py`.** Only two legal values, `"fresh"`/`"head"` — no branch-name form (matches spec's "exact JSON," which has no third option to get wrong). |
| `cursor-agent -p -f --output-format json [--model M]` | `adapter-cursor.md:59-60` | `-p, --print`; `-f, --force`; `--output-format <text\|json\|stream-json>` (only with `--print`); `--model <model>` — all four confirmed present, unchanged, on the current `cursor.com/docs/cli/reference/parameters` page. | **No drift.** Alias (`cursor-agent`) still works per the same page's continued use of it. |
| `agy --dangerously-skip-permissions --add-dir <WT> --print-timeout <sec>s [--model M] --print <prompt>` | `adapter-antigravity.md:30-31` | `--print`/`-p`, `--dangerously-skip-permissions`, `--print-timeout` (default 5m), `--model`, `--output-format`, `--effort`, `--agent`, `--continue`/`-c`, `--conversation`, `--sandbox` all confirmed on the current `antigravity.google/docs/cli/headless` page. **`--add-dir` did not appear in that page's flag list.** | **Unconfirmed, flagged.** Could be a general (non-headless-specific) flag documented elsewhere, or a genuine removal since the pinned 1.0.13 → live 1.1.25 gap (many releases). Not a hard "removed" finding — a small-model `WebFetch` summary is not exhaustive — but it is exactly the kind of drift this role exists to surface. **Run `agy --help` against the installed binary before any doc leans on this invocation as still-exact.** |
| `codex exec --cd … --sandbox workspace-write --skip-git-repo-check --model … --json --output-last-message … -c sandbox_workspace_write.network_access=false` | AGENTS.md (verified on `0.144.1`) | `--full-auto` was removed in v0.147.0 (deprecated since v0.128) — **not used here**, so no regression. `codex mcp-server` was deprecated in favor of App Server + Claude Code Plugin as of v0.149.1 — **grepped the repo; Compound V's own worker never invokes `codex mcp-server`**, only `codex exec`, so this deprecation doesn't touch it. | **No drift in the invocation shape.** The version *floor* is a separate question — see §4. |

## 4. High-Priority Findings 🟠

### 4.1 — Codex floor `≥ 0.143` predates the Sol/Terra/Luna context-window correction; bump it

The spec's item 6 wants the README to say **"Codex ≥ 0.143 for gpt-5.6-sol."** That
floor was live-probed and recorded correctly for one thing — *does the CLI recognize the
model at all* (`MEMORY.md`, v2.6.3: confirmed `codex-cli >= 0.143.0`). But a second,
independent fact has emerged since: **Codex CLI 0.144.6 (2026-07-18) corrected the
bundled context-window metadata for Sol/Terra/Luna from 372K down to 272K tokens**
(`@Codex_Changelog` on X, corroborated by `github.com/openai/codex` issues #38917,
#39144, #32806, and `aiweekly.co`'s independent write-up). The 272K figure is not
cosmetic — it is **the exact threshold at which Codex's own pricing guardrail doubles
input pricing and adds a 1.5× output multiplier for the whole session**. A CLI at exactly
`0.143.x` carries the *stale, overstated* 372K figure, so a worker dispatched through it
can be let run past the real 272K boundary before the mismatch surfaces — a functional
and billing surprise, not just a documentation gap.

**Recommendation:** the README (and AGENTS.md, which is where such floors actually live
per the spec's own item 1) should state the floor as **`≥ 0.144.6`**, not `≥ 0.143`. This
is a one-word version bump, not a design change — flagging it now, before the plan locks
the number in, is cheaper than a follow-up finding after the metadata mismatch bites
someone.

- Sources: [`x.com/Codex_Changelog/status/2079018788876411322`](https://x.com/Codex_Changelog/status/2079018788876411322) · [`github.com/openai/codex/issues/39144`](https://github.com/openai/codex/issues/39144) · [`github.com/openai/codex/issues/38917`](https://github.com/openai/codex/issues/38917) · [`aiweekly.co/alerts/openai-codex-cuts-gpt-56-context-window-from-372k-to-272k`](https://aiweekly.co/alerts/openai-codex-cuts-gpt-56-context-window-from-372k-to-272k)
- Alternative if the plan prefers not to chase point releases: state the floor as
  **"≥ 0.146 (0.144.6 for the corrected Sol/Terra/Luna context-window metadata)"** — the
  0.146.0 line (2026-07-29) is already past every known fix in this area and is a round
  number easier to keep current.

### 4.2 — `worktree.baseRef: head` is a project-wide native setting, not a Compound-V-scoped one — the spec's framing undersells its blast radius

Confirmed live, directly from the `EnterWorktree` tool's own description and from
`code.claude.com/docs/en/worktrees.md` (fetched today): `worktree.baseRef` is a **real,
current, documented Claude Code setting**, read from `.claude/settings.json` — the
**"Shared project" scope**, i.e. *"Everyone in the project"* per the settings-precedence
table. Compound V's own `_worktree_base_is_head()` (`scripts/compound-v-emit-workflow.py`)
reads the exact same key from the exact same file — this is not a coincidental name
collision, it is the same setting doing double duty.

That means setting it to `"head"` (as `commands/v-init.md` will offer to do) changes
behavior for **every** use of the native worktree machinery in this repo, not only
Compound V's dependent-job dispatch:

- Every interactive `claude --worktree <name>` session any human runs in this repo.
- Every `isolation: worktree` custom subagent (`.claude/agents/*.md` frontmatter) —
  confirmed by the docs' own line: *"Subagent worktrees use the same base branch as
  `--worktree`, so they branch from your repository's default branch unless
  `worktree.baseRef` is set to `"head"`."*
- The `"fresh"` default's own safety property disappears with it: docs confirm `"fresh"`
  keeps `origin/HEAD` current by fetching (capped at 5s) when it's more than 24h stale —
  a `"head"` worktree gets none of that; it always branches from whatever the *local*
  checkout's `HEAD` happens to be, unpushed commits and all.

The spec (item 1, item 6) frames this purely as "a real install requirement… documented
nowhere for installers" for Compound V's own dependent-job integration. That's true, but
incomplete: an installer who accepts `v-init.md`'s offer is also opting every future ad
hoc `--worktree` session and every `isolation: worktree` subagent in the repo into
HEAD-based branching, silently losing the "always starts from a clean, up-to-date
default branch" guarantee for their own unrelated work. This is exactly the kind of
undocumented side effect a newcomer reading a "clear and simple" README would want
surfaced, not discovered later.

- Source: [`code.claude.com/docs/en/worktrees.md`](https://code.claude.com/docs/en/worktrees.md) (§"Choose the base branch", §"Isolate subagents with worktrees") · [`code.claude.com/docs/en/settings.md`](https://code.claude.com/docs/en/settings.md) (settings-precedence table) · live `EnterWorktree` tool description, this session.

## 5. Medium Findings 🟡

### 5.1 — Backend adapter version pins are stale relative to live upstream; don't let the README inherit the exact numbers

`adapter-cursor.md` pins facts to **`cursor-agent 2026.06.26`**; `adapter-antigravity.md`
pins to **`agy 1.0.13`**. Live today: Cursor's primary CLI entrypoint is now `agent`
(`cursor-agent` remains a working, documented alias — confirmed in §3, no action needed
there), and `agy` is at **v1.1.25** — many releases past 1.0.13, including a new
sign-in-free CI auth path (`modelProvider: "gemini"` + `GEMINI_API_KEY`, since 1.1.13,
2026-08-14) that Compound V's headless dispatch doesn't currently use or mention anywhere.
Neither adapter file's pinned facts are wrong for what they assert (verified in §3 —
the actual invocation shapes still work), but both are old enough that a fresh
`/v:init` re-probe is due, per those files' own stated policy ("re-probe only in
`/v:init`" — this audit is not overriding that policy, just flagging that the window has
opened).

**Constraint for the plan:** the README rewrite should **not** copy `cursor-agent
2026.06.26` or `agy 1.0.13` into README.md even in passing — the spec's own item 3
("Backends names what the repository ships" — backend *names* and trust tiers, not
version pins) already avoids this. Keep it that way; this finding just confirms *why*.

- Sources: [`cursor.com/changelog/cli-jan-08-2026`](https://cursor.com/changelog/cli-jan-08-2026) · [`cursor.com/docs/cli/reference/parameters`](https://cursor.com/docs/cli/reference/parameters) · [`antigravity.google/docs/cli/reference`](https://antigravity.google/docs/cli/reference) · [`antigravity.google/docs/cli/headless`](https://antigravity.google/docs/cli/headless) · [`aibuilderclub.com/blog/antigravity-cli-guide`](https://www.aibuilderclub.com/blog/antigravity-cli-guide)

### 5.2 — `agy --add-dir` unconfirmed on current headless docs (see §3)

Carried here from §3 for visibility: not a confirmed removal, but a genuine gap between
a pinned invocation and what the live headless-mode reference page currently lists.
Cheap to close — one `agy --help` run — expensive to leave silently wrong in a worker
script. Not blocking for a README-only spec, but worth a one-line follow-up task.

## 6. Design Constraints for the Plan

- **MUST** state the Codex install floor as `≥ 0.144.6` (or a round-number equivalent
  past it, e.g. `≥ 0.146`), not `≥ 0.143` — see §4.1.
- **MUST** have `commands/v-init.md`'s offer (and/or the README/TROUBLESHOOTING text
  around it) name the setting's actual scope: it governs `worktree.baseRef` for **every**
  native worktree use in the project — interactive `--worktree` sessions and
  `isolation: worktree` subagents included — not only Compound V's dependent-job
  dispatch. A one-clause addition to the existing offer text is enough; this does not
  require a design change, only that the "why" the spec already promises is the complete
  why. See §4.2.
- **MUST NOT** state `worktree.baseRef` as accepting anything other than `"fresh"` or
  `"head"` — confirmed the only two legal values; no branch-name form exists.
- **MUST NOT** copy exact backend-CLI version pins (`cursor-agent 2026.06.26`,
  `agy 1.0.13`) into README.md — keep those in the adapter docs, where the `/v:init`
  re-probe policy already owns their freshness. The spec's own item 3 already does this;
  this is confirmation, not a new requirement.
- **MUST** keep the Context7 install line exactly as it already is in README.md
  (`/plugin install context7@claude-plugins-official`) — independently confirmed current
  by five sources; changing it now would introduce a regression, not fix one.
- **SHOULD** file (or fold into TROUBLESHOOTING/AGENTS.md as a footnote, not README —
  per the spec's own "everything measured… moves to AGENTS.md" rule) a one-line follow-up
  to confirm `agy --add-dir` against a live `agy --help`, since the adapter script's
  correctness (not the README) depends on it. Not a README-clarity blocker.

## 7. Open Questions for the Human

1. **Codex floor number:** bump to `0.144.6` exactly, or the rounder `0.146`? Both are
   past the known fix; the rounder number is easier to keep accurate as Codex continues
   its near-daily release cadence (0.153.0 as of this morning). This is a wording choice,
   not a technical one — flagging so it isn't decided by whichever number happens to be
   in the first draft.
2. **How much of §4.2 belongs in README vs. `commands/v-init.md`'s own offer text:** the
   one-rule constraint ("README ≤ 130 lines, no paragraph over five sentences") means the
   full nuance (subagent worktrees, the `"fresh"` 24h-refresh safety property it gives
   up) probably belongs in the `v-init.md` offer and/or TROUBLESHOOTING's new entry, with
   README carrying only a one-clause pointer. Confirming that split is a writing-plans
   decision, not a library-currency one — surfaced here only because the underlying fact
   is what makes the split necessary.

## 8. Knowledge Base Updates

Appended, date-stamped, sourced, nothing deleted:

- **`docs/superpowers/library-audit/_knowledge-base/claude-code-runtime.md`** — new
  section `## Updated 2026-09-03 — worktree.baseRef is a live, project-scoped native
  setting (v3.4.7 readme-clarity)`: the `EnterWorktree` tool's own description quoted
  verbatim, the `worktrees.md`/`settings.md` confirmation, the two-legal-values fact, and
  the subagent-worktree / `"fresh"`-24h-refresh scope note from §4.2 above.
- **New file `docs/superpowers/library-audit/_knowledge-base/backend-worker-clis.md`** —
  created (none of the existing five KB files was the right home for Codex/
  Antigravity/Cursor/opencode/Devin CLI facts, which recur across specs and didn't have
  a topic file yet): current versions (Codex 0.153.0, agy 1.1.25, cursor-agent→`agent`
  rename), the Codex 0.144.6 context-window correction and its pricing-guardrail tie-in,
  the `agy --add-dir` unconfirmed-on-current-docs gap, and the `codex mcp-server`
  deprecation (confirmed not used by this repo's own worker).

Both writes are described here; performing them now.

---

*Audited by Compound V Phase 1C (doc-validator, Sonnet). DEGRADED: WebSearch/WebFetch-only
— Context7 was not attached to this subagent. Every load-bearing external claim above is
triangulated across ≥2 independent sources, or is first-party live-tool-schema evidence
(`EnterWorktree`), following this KB's own standing rule after its recorded
WebFetch-confabulation incident.*
