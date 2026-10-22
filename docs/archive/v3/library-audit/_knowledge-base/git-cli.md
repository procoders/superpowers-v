# Git CLI Knowledge Base

Maintained by Compound V Phase 1C validator. Append at the bottom.

Scope: `git`'s own command-line behavior — flag surfaces, version currency, and any option that writes to
the filesystem or invokes an external program — as it matters to Compound V's own `bashCommandClamp` and
permission-rule allowlists (`scripts/compound-v-emit-preflight.py`, `scripts/compound-v-emit-workflow.py`).
Not Context7-indexable (no SDK, no npm/pip package); sources are live WebFetch of `git-scm.com/docs/*` and
its `man7.org` mirror.

---

## Updated 2026-09-03 — v3.4.13 preflight git-history

Validated for
[`docs/superpowers/library-audit/2026-09-03-v3-4-13-preflight-git-history.md`](../2026-09-03-v3-4-13-preflight-git-history.md).
No Context7 attached to this subagent. Sources: live `WebFetch` of `git-scm.com/docs/git-log`,
`git-scm.com/docs/git-show`, `git-scm.com/docs/git-blame`, `git-scm.com/docs/diff-options`, and
`man7.org/linux/man-pages/man1/git-log.1.html`, plus `WebSearch` for the current stable release, all
2026-09-03.

**Current stable: git 2.55.0, released 2026-06-29** (per the `git-log` doc page's own "last updated in
2.55.0" line, cross-checked by `WebSearch`). This repo's own last live `git --version` probe
(`2026-07-11-v2.9-pre-evaluation.md`) recorded **2.50.1** — five minors behind, not a deprecation or
staleness concern for the flags this entry covers.

**`git log --output=<file>` and `git show --output=<file>` are both real, and both write to the
filesystem.** Confirmed via `git-scm.com/docs/diff-options`, which documents `--output=<file>` ("Output to a
specific file instead of stdout") as a **generic diff option** and explicitly lists the commands that share
it: *"`git log`, `git show`, `git diff`, `git format-patch`, `git difftool`, `git range-diff`."*
Independently confirmed by `man7.org/linux/man-pages/man1/git-log.1.html`, which inlines `--output=<file>`
directly under a "DIFF FORMATTING" section on the `git-log` page itself. **A first, direct `WebFetch` of
`git-scm.com/docs/git-log`'s own page returned a false "No such option"** — the option lives on the
transcluded `diff-options` page rather than being inlined into that particular render, and the summarizing
pass missed the transclusion note. Resolved by fetching the sharing page and the man7 mirror independently;
both agree. **Methodology note for future 1C runs on this repo:** when a single-command git doc page
returns a negative for an option you have reason to expect, check `git-scm.com/docs/diff-options` (or the
equivalent shared-options page) before concluding it doesn't exist — git's man pages transclude shared
option blocks that a page-scoped fetch/summary can miss.

**Consequence:** neither option writes into git's own object database (no commit, no ref change, no index
mutation) — the file write is a plain OS-level filesystem write to whatever path the argument names, using
whatever privileges the invoking process already has. It is not caught by Claude Code's own "Redirection"
permission check, which is scoped to shell operators (`>`, `>>`, `2>`), not to a program's own argument (see
`claude-code-runtime.md`'s 2026-09-03 entry, same date). A `Bash(git log:*)` / `Bash(git show:*)` clamp
entry — correctly formed, wildcard strictly after the subcommand — still admits `--output=<file>` as
trailing text the wildcard matches.

**`git blame` has no `--output` and no diff-options inheritance — confirmed clean.** Its documented output
modes (`--porcelain`, `--line-porcelain`, `--incremental`) are all stdout-only; no file-writing or
external-program-invoking flag was found on `git-scm.com/docs/git-blame`.

**Secondary, lower-likelihood vector: `--show-signature` (available on both `log` and `show`) invokes
`gpg --verify`, and `gpg.program` can repoint that to an arbitrary executable.** Requires either the
invoking agent to pass the flag itself, or a pre-existing malicious `gpg.program` value already present in
the repo's git config (a larger prior compromise). Not blocking on its own; recorded for completeness
alongside the `--output` finding above, and because it independently corroborates the general pattern
(external-program invocation reachable through "read-only" git subcommands via config-controlled program
paths) reported in 2026 git/GitHub security coverage found via `WebSearch` this session (CVE-2026-3854,
CVE-2026-25763 — both unrelated to this repo directly, cited only as evidence this class of risk is active
and current, not historical).

**`--ext-diff`/`--textconv`** (available on `git show`, and — per `git show`'s own doc text, *"If you set an
external diff driver with gitattributes(5), you need to use this option with git-log(1) and friends"* —
implicitly relevant to `git log` too) can invoke an externally-configured diff/textconv program declared in
`.gitattributes`. Off by default; requires both a pre-existing attribute declaration and the flag (or a
config default) to fire. Same "requires prior config control" caveat as `--show-signature` above — noted,
not treated as a standalone blocker.

