# Backend Worker CLI Knowledge Base

Maintained by Compound V Phase 1C validator. Append at the bottom. Date-stamp every
claim. Cite sources. Never delete prior entries — strike through with `~~old~~` and add
`→ updated YYYY-MM-DD: <new>`.

Scope: the headless-worker CLIs Compound V dispatches to via
`skills/backend-launcher/adapter-*.md` — Codex, Antigravity (`agy`), Cursor
(`cursor-agent`), opencode, Devin. Claude Code's own runtime lives in
`claude-code-runtime.md`; hook contracts in `claude-code-hooks.md`. This file is where
those adapter-CLI facts belong, split out because they recur across specs and didn't have
a topic file before this entry.

---

## Updated 2026-09-03 — v3.4.7 readme-clarity (initial entry)

Validated for
[`docs/superpowers/library-audit/2026-09-03-v3-4-7-readme-clarity.md`](../2026-09-03-v3-4-7-readme-clarity.md).
**DEGRADED: WebSearch/WebFetch-only** — no Context7 attached to this subagent. Every claim
below is either triangulated across ≥2 independent sources or is a direct fetch of the
vendor's own current docs.

### Codex CLI

- **Current: 0.153.0** (npm `@openai/codex`, published ~2026-09-03, i.e. today).
  Release cadence is near-daily; 0.152.1, 0.151.0, 0.150-alpha cycle, 0.149.0
  (2026-08-20, added an interactive `codex agents` dashboard), 0.146.0 (2026-07-29) all
  landed in the six weeks before this entry.
- **AGENTS.md's "verified invocation" is pinned to 0.144.1** (`codex exec --cd … --sandbox
  workspace-write --skip-git-repo-check --model … --json --output-last-message … -c
  sandbox_workspace_write.network_access=false`). Re-verified 2026-09-03: no flag in that
  invocation has been deprecated or renamed since — `--full-auto` (removed v0.147.0,
  deprecated since v0.128) is not used here; `codex mcp-server` (deprecated as of
  v0.149.1 in favor of App Server + a Claude Code Plugin) is grepped-confirmed **not
  used anywhere in this repo's own worker** (`compound-v-run-codex-worker.sh` uses
  `codex exec` exclusively). Neither deprecation touches this repo.
- **GPT-5.6 Sol/Terra/Luna context-window correction — load-bearing for any version floor
  claim.** Sol/Terra/Luna reached GA 2026-07-09. **Codex CLI 0.144.6 (2026-07-18)**
  corrected the bundled context-window metadata for all three from 372K down to **272K
  tokens** — not cosmetic: 272K is the exact threshold at which Codex's own billing
  guardrail doubles input pricing and applies a 1.5× output multiplier for the whole
  session. A CLI at exactly `0.143.x` (this repo's currently-documented floor, per
  `MEMORY.md` v2.6.3's live-probe of "does the CLI recognize the model") carries the
  *stale, overstated* 372K figure. **Recommend the floor move to `≥ 0.144.6`** (or a
  round `≥ 0.146` for easier upkeep against the near-daily release cadence) — the model
  is recognized either way, but the correct floor also gets the fixed metadata.
  Sources: [`x.com/Codex_Changelog/status/2079018788876411322`](https://x.com/Codex_Changelog/status/2079018788876411322)
  (0.144.6 changelog, quoted: *"Context windows corrected to 272K tokens"*) ·
  `github.com/openai/codex` issues **#38917**, **#39144**, **#32806** (independent
  community reports converging on the same 372K→272K number) ·
  [`aiweekly.co/alerts/openai-codex-cuts-gpt-56-context-window-from-372k-to-272k`](https://aiweekly.co/alerts/openai-codex-cuts-gpt-56-context-window-from-372k-to-272k).
- **No GPT-5.7 / successor family found** as of 2026-09-03 — GPT-5.6 (Sol/Terra/Luna) is
  still current. `gpt-5.6-sol`/`-terra`/`-luna` naming in
  `scripts/compound-v-resolve-model.py` is not stale.

### Antigravity CLI (`agy`)

- **Current: v1.1.25** (`antigravity.google/docs/cli/reference`, fetched live
  2026-09-03). `adapter-antigravity.md` pins facts to **`agy 1.0.13`** — many releases
  behind. Antigravity 2.0 (desktop IDE + CLI + SDK + Managed Agents API) shipped
  **2026-05-19**; a sign-in-free CI auth path (`modelProvider: "gemini"` in
  `settings.json` + `GEMINI_API_KEY` env var, no OAuth) was added in **1.1.13
  (2026-08-14)** — Compound V's headless dispatch doesn't use or mention this path
  anywhere today; worth a look for a future spec, not actionable for v3.4.7.
- **Headless flags confirmed current** (`antigravity.google/docs/cli/headless`, live
  2026-09-03): `--print`/`-p`/`--prompt`, `--output-format {text,json,stream-json}`,
  `--input-format`, `--json-schema`, `--model`, `--effort {low,medium,high}`, `--agent`,
  `--continue`/`-c`, `--conversation`, `--dangerously-skip-permissions`, `--sandbox`,
  `--print-timeout` (default 5m).
- **`--add-dir` NOT found on the current headless-mode reference page.**
  `adapter-antigravity.md`'s pinned invocation (`agy --dangerously-skip-permissions
  --add-dir <WT> --print-timeout <sec>s [--model <M>] --print <prompt>`) uses it. This is
  **not a confirmed removal** — a `WebFetch` summary of one doc page is not exhaustive,
  and `--add-dir` may live on a general (non-headless-specific) flags page instead. It
  *is* a real, concrete drift signal between a pinned worker invocation and current
  vendor docs, surfaced rather than silently assumed fine. **Action: run `agy --help`
  against the installed binary and confirm before trusting this invocation shape further
  (adapter's own policy: re-probe at `/v:init`).**

### Cursor CLI (`cursor-agent`)

- **Primary entrypoint renamed to `agent`** as of the 2026-01-08 Cursor CLI release:
  *"The new `agent` command became the primary CLI entrypoint, with `cursor-agent`
  remaining as a backward-compatible alias."* `adapter-cursor.md` pins facts to
  **`cursor-agent 2026.06.26`** (already post-rename, so the alias was already the
  intentional choice at pin time — not itself a problem).
- **Flags re-verified live, unchanged**, on `cursor.com/docs/cli/reference/parameters`
  (fetched 2026-09-03): `-p, --print`; `-f, --force`; `--output-format {text,json,
  stream-json}` (only with `--print`); `--model`; `--trust`. **No drift** — the pinned
  invocation `cursor-agent -p -f --output-format json [--model <M>] <prompt>` matches
  the current docs exactly.
- Subsequent 2026 releases (undated in the fetched search summary, but after the
  2026-01-16 "Plan mode / Ask mode / Cloud handoff" release) added: *"Long headless
  sessions no longer hang. Headless and single-turn runs drain delegated subagents and
  include their completion before exiting."* Behavioral hardening, not a signature
  change — doesn't invalidate the pinned invocation, but is a reason the adapter's
  "re-probe at `/v:init`" policy is due for a run (pin is ~2 months old).

### opencode

- Active, 182k★+, multi-provider (75+ providers via OpenAI-compatible endpoints and
  native integrations), headless HTTP server (`opencode serve`) + official `@opencode-ai/sdk`.
  `adapter-opencode.md` exists. No currency issues found; the spec's "experimental… not
  dogfooded" framing is accurate to this repo's own usage, not to the library's maturity.

### Devin CLI

- Active; changelog shows recent fixes for headless/`TERM=dumb` rendering, MCP-registry
  loading behind corporate proxies/TLS inspection, and relative-path resolution for
  `cd`-prefixed read-only commands. `adapter-devin.md` exists. No currency issues found.

### Context7 MCP install line (confirms existing README, no change)

- README.md:88 already reads `/plugin install context7@claude-plugins-official`.
  Confirmed current by **five independent third-party sources**
  (claudedirectory.org "August 2026", pluginmarketplace.ai, claudemarketplaces.com,
  claudepluginhub.com, deployhq.com) all quoting the identical install command.
- **Methodology note:** a `WebFetch` of the literal marketplace repo's GitHub tree view
  (`github.com/anthropics/claude-code/tree/main/plugins`) returned a plugin list that did
  **not** include `context7` — almost certainly the small-model markdown conversion of a
  JS-rendered GitHub tree page failing to capture the real listing (a second instance of
  the pattern `claude-code-runtime.md` already flagged for WebFetch on dynamic/truncated
  pages). The five independently-worded third-party confirmations outweigh one incomplete
  directory fetch — treat the install line as confirmed, and treat this as one more data
  point for "grade a single dynamic-page WebFetch as low-confidence, triangulate."
