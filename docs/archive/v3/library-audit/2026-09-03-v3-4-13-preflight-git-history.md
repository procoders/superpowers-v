# Phase 1C — Library/Doc Validation: v3.4.13 pre-flight git-history clamp

**Date:** 2026-09-03 · **Spec:** `docs/superpowers/specs/2026-09-03-v3.4.13-preflight-git-history-design.md`
**Scope of this spec:** add three read-only forms — `Bash(git log:*)`, `Bash(git blame:*)`, `Bash(git show:*)`
— to `scripts/compound-v-emit-preflight.py`'s `bashCommandClamp`, plus two new `--selftest` checks.

## 0. V-memory recall (Step 0)

Five `compound-v-memory.py search` calls ran before any file was opened (`--intent planning --top 6-8`):
`"git history preflight archaeology clamp"`, `"bashCommandClamp pre-flight emit script"`,
`"GitPython pydriller commit history python library"`, `"Bash permission rule prefix match command
chaining semicolon injection bypass"`, `"git textconv pager RCE git show git log security"`, plus a recon
check.

**What came back.** The spec itself and its own triage record (predicted `SCOPED_PIPELINE`, medium/medium).
No prior audit had verified git CLI flag-level behavior — the closest hit,
`docs/superpowers/library-audit/2026-07-11-v2.9-pre-evaluation.md`, only records "git 2.50.1... no third-party
runtime deps," never a flag survey. `docs/superpowers/research/2026-07-11-git-history-as-complexity-signal.md`
(a 2026-07-11 research pass, different feature) warns against `git log --follow` per-path repeatedly (an
O(files × history) trap) — not applicable here since this spec adds bare command access, not a usage
pattern, but worth naming so a future plan touching per-path history reuses that warning instead of
rediscovering it. **No prior entry anywhere in V-memory addresses `--output=<file>` on `git log`/`git show`,
or the compound-command-splitting question for `bashCommandClamp` specifically — both are new to this
audit.**

**Recon.** No Trigger-0 recon path was handed to me. Fallback scan of `docs/superpowers/recon/` for a
`v3.4.13`/`git-history` slug found nothing (`Glob` × 2, zero hits). Proceeding without one — consistent
with a `SCOPED_PIPELINE`/medium-difficulty triage that would plausibly skip it.

## 1. Tools Available

| Tool | Status | Note |
|---|---|---|
| Context7 MCP | ❌ not attached to this subagent (`ToolSearch "context7 resolve-library-id query-docs"` → no match) | Sixth consecutive same-repo 1C run recording this (see `claude-code-runtime.md`'s 2026-09-03 entries) |
| WebFetch / WebSearch | ✅ | Used for all live verification below |
| Repo dependency manifests | None exist | Reconfirms the 2026-09-02 `claude-code-runtime.md` finding: no `package.json`/`requirements.txt`/`pyproject.toml`/etc. anywhere in the tree; `CONVENTIONS.md` mandates stdlib-only. This spec touches zero third-party dependencies — it only adds three `git` subcommand names to an existing allowlist string |

Not DEGRADED — WebFetch/WebSearch fully substituted for the missing Context7, and the primary claims below
are corroborated by 2-3 independent sources each, per this repo's own established methodology (the
`claude-code-runtime.md` Stop-hook confabulation precedent).

## 2. Libraries Mentioned

| Name | Spec context | Current ver | Repo-assumed | Last release | Maintenance | Status |
|---|---|---|---|---|---|---|
| `git` (CLI) | subject of the clamp — `log`, `blame`, `show` | **2.55.0** (released 2026-06-29, live-fetched `git-scm.com/docs/git-log`) | **2.50.1** (last probed in-repo, `2026-07-11-v2.9-pre-evaluation.md`) | 2026-06-29 | Actively maintained, canonical VCS tooling | 🟢 OK — behind by a few minors but `log`/`blame`/`show` are decades-stable commands; not a staleness risk. Flagged only because the repo's own last live probe is now 5 minor releases old |
| Claude Code `bashCommandClamp` (this plugin's own mechanism, not a package) | the field this spec extends | undocumented on the public `workflows.md` page (reconfirmed today, full fetch) | n/a — internal, versioned with the Claude Code binary | n/a | n/a | See §6 finding 🟠-1 |

No new third-party package, SDK, or external API is introduced by this spec. Everything below is about the
**behavior of `git` itself** and of **Claude Code's own undocumented clamp mechanism** — both squarely "is
this API signature what the spec assumes," just not Context7-indexable ones.

## 3. API Signatures Verified

| Call / form | Verified against | Result |
|---|---|---|
| `Bash(git log:*)` / `Bash(git blame:*)` / `Bash(git show:*)` — trailing `:*` wildcard, placed immediately after the subcommand | `code.claude.com/docs/en/permissions.md` (live fetch, 2026-09-03), §"Wildcard patterns": *"The `:*` suffix is an equivalent way to write a trailing wildcard... Put the `*` after the subcommand"* | ✅ Syntactically correct — matches the documented shape exactly, and matches this repo's own existing precedent for the identical two forms already shipping in `scripts/compound-v-emit-workflow.py:228` (`IMPLEMENT_SHELL`) |
| `git log --output=<file>` | `git-scm.com/docs/diff-options` (live fetch): *"`--output=<file>` — Output to a specific file instead of stdout"*, page states this generic diff option is shared by `git log`, `git show`, `git diff`, `git format-patch`, `git difftool`, `git range-diff` · independently confirmed inline on `man7.org/linux/man-pages/man1/git-log.1.html` §"DIFF FORMATTING" | ✅ **Real, writes to the filesystem.** (A first fetch of `git-scm.com/docs/git-log` directly returned a false "No" — the option lives on the transcluded `diff-options` page, not inlined into that render; resolved by fetching the sharing page and the man7 mirror independently, both agreeing) |
| `git show --output=<file>` | Same `diff-options` page; also directly on `git-scm.com/docs/git-show` (live fetch): *"`--output=<file>` — Output to a specific file instead of stdout"* | ✅ **Real, writes to the filesystem.** Two-source agreement (diff-options + git-show's own page) |
| `git blame` — any file-writing or program-invoking option | `git-scm.com/docs/git-blame` (live fetch): only `--porcelain`/`--line-porcelain`/`--incremental`, all stdout-only; no `--output`, no diff-options inheritance | ✅ Confirmed genuinely read-only/stdout-only — the spec's claim holds for this command specifically |
| Compound-command / shell-operator splitting for `Bash(prefix:*)` rules | `permissions.md` (live fetch), §"Compound commands": *"Claude Code is aware of shell operators... The recognized command separators are `&&`, `\|\|`, `;`, `\|`, `\|&`, `&`, and newlines. A rule must match each subcommand independently."* | 🟡 Confirmed **for ordinary `Bash(...)` permission rules** — but this describes permission-rule matching, and `bashCommandClamp` is a structurally-similar but **separately undocumented** field (see §6, 🟠-1). Whether the clamp inherits this exact splitter is a reasonable inference from shared string syntax, not a directly confirmed contract |
| "read-only forms of `git`" as a Claude-Code **built-in**, auto-approved without any rule | `permissions.md` (live fetch), §"Read-only commands": *"...and read-only forms of `git`"* listed alongside `ls`, `cat`, `grep`, etc. | ℹ️ Informational: ordinary Bash-tool permission prompting would likely already treat plain `git log`/`git blame`/`git show` as no-prompt-needed. Irrelevant to whether they should be in `bashCommandClamp`, which is a distinct positive-allowlist mechanism, not a prompt-approval mechanism — noted so the plan doesn't conflate the two |

## 4. Critical Findings 🔴

### 🔴-1 · `git log --output=<file>` and `git show --output=<file>` are a live, unconditioned filesystem-write primitive being added to the one Compound V stage that has **no scope-gate at all**

**The spec's own framing is precise but incomplete.** It says: *"No write-capable form is added: `git
status`, `git diff` stay out... and nothing that can change the tree or the index."* That claim is **true**
for git's own object database — none of `log`/`blame`/`show` can create a commit, alter a ref, or touch the
index. But `--output=<file>`, live-verified above on both `git log` and `git show` (2 of the 3 commands this
spec adds), writes arbitrary bytes to **any filesystem path the OS process can reach** — a plain file write
that has nothing to do with git's tree or index, and that the spec's own "read-only" framing does not
distinguish from a git-internal mutation.

**Why this is not caught by anything already in place, for this specific stage:**

1. **Claude Code's own "Redirections" permission check does not cover it.** The live `permissions.md` fetch
   is explicit: *"Claude Code checks the target of an output redirection, such as `>`, `>>`, or `2>`, as a
   file write."* `--output=<file>` is a program argument, not a shell redirection operator — it is outside
   the class of writes that check inspects.
2. **The pre-flight stage this spec modifies has no scope-gate of any kind.**
   `scripts/compound-v-emit-preflight.py`'s own module docstring states the design directly: *"NO
   isolation. An auditor writes ONE document into its own directory and reads everything else; a worktree
   would only hide the repository it exists to read."* There is no `git diff`-derived check, no worktree
   boundary, nothing — the invariant "writes ONE document" is asserted in prose, not enforced by any
   mechanism, for **any** tool the auditor holds, Bash included.
3. **This is a materially different exposure than the auditor's existing `Write` tool.** The docstring
   argues Bash is otherwise unnecessary because *"nothing in these three definitions needs a shell that
   `Grep`, `Glob` and `Read` do not already give."* `Write` is true — but `Write` is confined to the
   directories Claude Code's file-tool permission model already grants (working directory + `additionalDirectories`);
   a raw Bash-invoked `--output=<file>` write is not confined that way at all (absent sandboxing) and can
   target any path the OS user can write to, inside or outside the repository entirely.

**This is not hypothetical to this one spec — the identical two clamp entries already ship elsewhere with
the same gap.** `scripts/compound-v-emit-workflow.py:228` already carries `"Bash(git log:*)", "Bash(git
show:*)"` in `IMPLEMENT_SHELL`, the implementer-job clamp. There, the exposure is materially smaller: that
stage runs inside a worktree with a git-diff-derived scope gate
(`scripts/compound-v-scope-check.py`) that catches writes to tracked *and* untracked paths **inside** the
worktree — though even there, an absolute-path `--output=<file>` pointed **outside** the worktree would
still slip past a check that is, by construction, git-diff-derived and therefore blind to a path that never
touches git tracking at all (this repo's own
`docs/superpowers/research/2026-07-11-2026-orchestrator-landscape-synthesis.md` already flags the general
shape of this caveat: *"[the scope gate] detects out-of-scope writes in what gets merged; it cannot prevent
a destructive action during a run"*). v3.4.13 proposes shipping the same two forms into the stage with **no
such backstop whatsoever**.

**Recommendation (a constraint for the plan to satisfy, not a prescribed implementation — that's
writing-plans' job):** the plan MUST NOT rely on the prefix clamp string alone to make this claim true. A
`Bash(git log:*)`-shaped rule cannot, by construction, exclude a specific flag appearing after the matched
prefix — that is exactly the class of fragility `permissions.md` itself calls out in its own curl-URL
warning and resolves the same way it recommends there: *"Use PreToolUse hooks: implement a hook that
validates URLs in Bash commands and blocks disallowed domains."* The equivalent here is a hook (or
equivalent parse-and-reject step) that inspects the actual argv for `--output`/`-O` before the pre-flight
Bash call executes — or the plan explicitly documents and accepts the residual risk, on the record, given
the pre-flight stage's total absence of any other backstop.

## 5. High-Priority Findings 🟠

### 🟠-1 · `bashCommandClamp` remains undocumented on the public `workflows.md` page — reconfirmed today, a sixth same-week occurrence

A full live `WebFetch` of `code.claude.com/docs/en/workflows.md` today (2026-09-03), specifically checked
for the strings `bashCommandClamp` and `disallowedTools`: **neither appears anywhere on the page.** This is
the same result this repo's own KB has now recorded on 2026-09-01 and twice more on 2026-09-03 across
unrelated features (`claude-code-runtime.md`'s workflow-retry and readme-clarity entries) — a fourth,
now fifth, independent same-week confirmation on a fresh fetch, not a carried-forward assumption.

**Consequence for this spec specifically:** the claim that a clamped `Bash(<prefix>:*)` rule inside
`bashCommandClamp` behaves exactly like an ordinary permission-rule `Bash(<prefix>:*)` allow rule — in
particular, that it performs the same per-subcommand shell-operator split documented for ordinary rules
(§3 above) — is an inference from identical string syntax and this repo's own already-shipping reliance on
it working that way (the memory-script clamp has been in production since 2026-09-01), **not a directly
documented contract.** Nothing in this audit contradicts that inference; nothing confirms it either. Treat
it as established-by-observed-behavior, the same epistemic status this KB already gives `agent()`'s
null-vs-throw contract, not as a publicly guaranteed API.

## 6. Medium Findings 🟡

### 🟡-1 · `git log --show-signature` / `git show --show-signature` invoke `gpg` (or `gpg.program`) — lower-likelihood, requires either an explicit flag or pre-existing malicious repo config

Independently found via WebSearch on git security literature and confirmed on the live git-scm.com pages
for both commands: `--show-signature` passes the commit's signature to `gpg --verify`, and git's
`gpg.program` config can repoint that to an arbitrary executable. Unlike `--output`, this requires **either**
the invoking auditor to pass `--show-signature` itself (agent-directed, not attacker-forced) **or** a
pre-existing, already-malicious `gpg.program` value in the repo's git config (meaning the attacker already
achieved local config control, a larger compromise than this spec's own threat model needs to cover). Noted
for completeness; not a blocker at this spec's scope, and not something a prefix clamp can distinguish
either way — same category of caveat as 🔴-1's flag-level blind spot, smaller likelihood.

### 🟡-2 · This repo's own last live `git --version` probe (2.50.1) is five minor releases behind current stable (2.55.0)

Not a staleness or deprecation risk — `log`/`blame`/`show` and their flag surfaces used here have been
stable across this range with no relevant breaking change found in the versions checked. Recorded only
because the delta exists and no session in this audit chain had local Bash access to re-probe
`git --version` directly (clamped to the V-memory script only, same constraint pattern as every other
2026-09-03 1C run recorded in `claude-code-runtime.md`).

## 7. Design Constraints for the Plan

1. **MUST** add exactly the three clamp forms as specified — `Bash(git log:*)`, `Bash(git blame:*)`,
   `Bash(git show:*)` — the syntax is verified correct against current Claude Code permission-rule semantics
   and matches this repo's own existing precedent (`compound-v-emit-workflow.py:228`).
2. **MUST NOT** describe `git log`/`git show` as unconditionally "read-only" or as guaranteeing "nothing
   that can change the tree or the index" without qualifying that this is true only of git's own object
   database — both commands carry a live, verified `--output=<file>` option that writes arbitrary content to
   any filesystem path the process can reach, uncaught by Claude Code's own redirection check and, for this
   specific stage, uncaught by any scope-gate (there is none). See 🔴-1.
3. **MUST** either add an argv-level check (a PreToolUse hook or equivalent — the mitigation `permissions.md`
   itself recommends for this exact class of argument-injection fragility) that rejects `--output`/`-O` on
   the clamped `git log`/`git show` invocations, **or** explicitly record, in the plan or the design doc,
   that this residual write-outside-the-repo risk is accepted as-is for the pre-flight stage. Silence is not
   an acceptable third option given §4's finding.
4. **MUST** treat `git blame` as genuinely read-only — no qualification needed there; live-verified clean of
   any file-writing or program-invoking option.
5. **MUST NOT** assert that `bashCommandClamp` is documented, or cite `workflows.md` as a source for its
   matching semantics — it remains completely absent from that page as of a fresh fetch today. Frame any
   claim about its exact matching behavior as inferred-from-observed-behavior, consistent with how this KB
   already treats `agent()`'s null-vs-throw contract.
6. The two new `--selftest` checks described in the spec (three git forms present; no other `Bash(git `
   form present) are necessary but not sufficient for the "read-only" claim — they guard against a future
   edit adding a new **subcommand** (e.g. `git checkout`), not against a flag reaching an already-approved
   subcommand. If constraint 3 is satisfied with a selftest-checkable mechanism, add a corresponding
   assertion; if satisfied by documented risk acceptance instead, no selftest change is implied by that
   choice alone.

## 8. Open Questions for the Human

1. **Is the `--output` write-outside-the-repo risk (🔴-1) acceptable as-is for the pre-flight stage, or does
   it need a hook-level mitigation before this ships?** This is a risk-acceptance call this audit can
   surface but not make — the pre-flight stage's total absence of any other backstop (no worktree, no
   scope-gate) is what makes this different from the same gap already sitting, more mildly, in the shipped
   implementer clamp.
2. **Should the identical, already-shipped `--output` gap in `IMPLEMENT_SHELL`
   (`scripts/compound-v-emit-workflow.py:228`) be raised as its own fix?** That clamp is partially backstopped
   by the worktree scope-gate for in-worktree paths, but not for an absolute path outside the worktree. This
   is existing-code territory (arguably 1A's lane, not 1C's), flagged here only so it isn't lost between
   audits — not claimed as part of this spec's scope.

## 9. Knowledge Base Updates

Two files updated:

- **`docs/superpowers/library-audit/_knowledge-base/claude-code-runtime.md`** — appended a dated entry
  (`## Updated 2026-09-03 — v3.4.13 preflight git-history (Bash permission-rule mechanics, live)`) recording
  the live `permissions.md` fetch: compound-command shell-operator splitting, the wildcard-placement rule,
  the "Redirections" check's narrow scope (shell operators only, not a program's own `--output=`-style
  flag), the built-in read-only `git` recognition, and the reconfirmed absence of `bashCommandClamp` from
  `workflows.md`.
- **`docs/superpowers/library-audit/_knowledge-base/git-cli.md`** (new file) — the git-specific facts:
  `--output=<file>` on `log`/`show` via the shared `diff-options` page (with the man7.org corroboration and
  the note about the first fetch's false negative), `git blame`'s clean stdout-only surface, `--show-signature`
  → `gpg.program`, and the current-stable-vs-repo-probed version delta.

