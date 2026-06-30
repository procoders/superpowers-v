# Library & Dependency Audit — `/v:onboard` design (Compound V Phase 1C)

**Spec:** `docs/superpowers/specs/2026-06-30-v-onboard-design.md`
**Audited:** 2026-06-30
**Verdict at a glance:** all named external dependencies are CURRENT and MAINTAINED as of 2026-06-30. Zero abandoned/archived. Two spec inaccuracies to correct (Postgres MCP flag name; "fastembed" mislabel). One CVE to pin (Playwright MCP).

---

## 1. Tools Available

- **Context7 MCP:** ✅ available. Used for `design.md` (`/google-labs-code/design.md`, 294 snippets, benchmark 91.92) and AGENTS.md lookups.
- **WebSearch / WebFetch:** ✅ available. WebFetch on `npmjs.com` returned 403; npm currency confirmed via `registry.npmjs.org` JSON API + `gh api` instead.
- **`gh` CLI:** ✅ authenticated — used for GitHub release/commit/archived/star signals.
- **Repo manifests found:** NONE. superpowers-v ships no `package.json`/`requirements.txt`/`pyproject.toml`. It is a Claude Code plugin (Markdown + bash + stdlib-only Python). Every dependency below is an **external CLI or MCP server the spec invokes**, not a packaged dependency — so there is no pinned version in-repo to diff against. Pin recommendations below are forward-looking.

---

## 2. Libraries / Tools Mentioned

| Name | Spec context | Current ver (2026-06-30) | Repo pinned | Last release / push | Maintenance | Status |
|---|---|---|---|---|---|---|
| `@google/design.md` | §4/§8 BLOCKING lint gate for `DESIGN.md` | **0.3.0** (2026-06-15) | — (npx) | release 2026-06-15; commit same day | active; 23.6k★; not archived; Apache-2.0; 51 open issues | 🟢 OK |
| `repomix` | §3 PACK: deterministic pack + Secretlint secret scan | **1.16.0** (2026-06-29) | — (npx) | published *yesterday*; pushed 2026-06-30 | very active; 26.7k★; MIT; not deprecated | 🟢 OK |
| `gitingest` (alt) | §3 mentioned as alt to repomix | not selected — repomix preferred | — | — | — | 🟢 N/A (repomix is the dependency) |
| AGENTS.md standard | §4/§6 portable primary, AAIF | living standard; AAIF-governed (LF, Dec 2025) | — | 60k+ projects adopted | active standard | 🟢 OK |
| GitHub MCP (`github/github-mcp-server`) | §10 `github.com` origin → GitHub MCP | remote endpoint `api.githubcopilot.com/mcp/`; local via Docker/binary | — | pushed 2026-06-30 | active; 31k★; not archived | 🟢 OK |
| Postgres MCP (`crystaldba/postgres-mcp`) | §10 Postgres DSN → Postgres MCP (read-only) | **0.3.0** (2026-05-16) | — | pushed 2026-01-22 | maintained but SLOWEST of set (~5mo since push); 3.0k★ | 🟡 MEDIUM |
| Supabase MCP (`@supabase/mcp-server-supabase`) | §10 `@supabase/*` → Supabase MCP `--read-only --project-ref` | **0.8.2** (2026-06-08) | — (npx) | published 2026-06-08 | active; official vendor server | 🟢 OK |
| Playwright MCP (`@playwright/mcp`) | §10 `playwright.config` → Playwright MCP | **0.0.77** (2026-06-29) | — (npx) | published 2026-06-29 | active; Microsoft; not archived | 🟢 OK (pin ≥0.0.40 — CVE) |
| Context7 MCP (`@upstash/context7-mcp`) | §10 fast-moving libs → Context7 | active (`npx -y @upstash/context7-mcp@latest`) | — | active | official Upstash; MIT; 2 tools | 🟢 OK |
| Sentry MCP (`getsentry/sentry-mcp`) | §10 `@sentry/*` → Sentry | remote `https://mcp.sentry.dev/mcp` (preferred) | — | pushed 2026-06-29 | active vendor; 748★ | 🟢 OK |
| `onnxruntime` + `tokenizers` + `huggingface_hub` + `numpy` | V-memory DENSE lane (consumed, not added by spec) | installed unpinned into isolated venv at bootstrap | unpinned (`scripts/compound-v-memory.py:868`) | — | upstream all active | 🟢 OK — no conflict |
| `fastembed` | spec dispatch note calls V-memory deps "fastembed/onnxruntime" | **NOT A DEPENDENCY** — never imported | — | — | — | ⚠️ mislabel (see §6) |

---

## 3. API Signatures Verified

| Invocation in spec | Verified against | Real signature (2026-06-30) | Result |
|---|---|---|---|
| `npx @google/design.md lint <file>` (§4/§8) | Context7 `/google-labs-code/design.md` README | `npx @google/design.md lint DESIGN.md` — package name, bin, and `lint` subcommand all **exact**. Also: `lint --format json`, `cat DESIGN.md \| npx @google/design.md lint -` (stdin). | ✅ exact |
| design.md JSON findings schema `severity/path/message` (implied by §4 "verified by the official linter") | Context7 query-docs | Findings: `{ severity, path, message }`; top-level `{ findings: [...], summary: { errors, warnings, info } }`. **severity** ∈ `error\|warning\|info`. | ✅ exact |
| design.md WCAG-contrast checking (§8 "WCAG contrast") | Context7 query-docs | `contrast-ratio` rule present; computes pass/fail vs WCAG AA 4.5:1 at warning severity. | ✅ confirmed |
| design.md subcommands `lint`/`diff`/`spec`/`export` (§ implied taxonomy) | Context7 query-docs | All four exist: `lint`, `diff` (exit 1 on regression), `export` (json-tailwind / css-tailwind / dtcg), `spec`. `lint` exits 1 on errors, 0 otherwise. | ✅ all present |
| `repomix` Secretlint secret scan (§3 "SECRET SCAN") | repomix docs/README | Built-in via `security.enableSecurityCheck` (Secretlint), **on by default**. CLI: `--no-security-check` disables; it is NOT opt-in. | ✅ confirmed (default-on, not a flag-to-enable) |
| `repomix` per-file + total token counts, `.gitignore`-aware, file tree (§3 PACK) | repomix docs/README | All present: per-file + total token counts, respects `.gitignore`, emits file tree. | ✅ confirmed |
| `@AGENTS.md` import as first line of thin CLAUDE.md (§4/§6 bridge) | code.claude.com/docs/en/memory | **Exact**. Docs: "Claude Code reads `CLAUDE.md`, not `AGENTS.md`" → recommended fix is `@AGENTS.md` import. Docs' own example matches spec verbatim. `@path` import syntax, recursive ≤4 hops, imports load in full at launch. | ✅ exact — spec correct |
| Supabase MCP `--read-only --project-ref` (§10) | Supabase docs | `--read-only` and `--project-ref=<ref>` both real and recommended-by-default. Caveat: `--project-ref` scopes only DB tools (`execute_sql`, `apply_migration`), not `create_project`/`create_branch`. | ✅ flags correct |
| Postgres MCP "read-only" (§10) | crystaldba/postgres-mcp README | **DRIFT.** The maintained server uses `--access-mode=restricted` (read-only txns), NOT `--read-only`. `--read-only` is the flag of the *deprecated* `modelcontextprotocol/servers` Postgres reference. | ⚠️ see Finding 🟡-1 |

---

## 4. Critical Findings 🔴

None. No named dependency is archived, deprecated, or abandoned.

---

## 5. High-Priority Findings 🟠

None blocking. The only security item is a known-CVE version floor, handled as a pin in §7 (Playwright MCP CVE-2025-9611, already long-since patched; current 0.0.77 ≫ 0.0.40).

---

## 6. Medium Findings 🟡

**🟡-1 — Postgres MCP flag name in §10 is wrong for the maintained server.**
Spec §10: "Postgres DSN / `prisma`+`pg` → Postgres MCP (read-only)" and §16-adjacent intent to "resolve to the maintained vendor server, not archived `modelcontextprotocol/servers` reference entries."
- The maintained server is `crystaldba/postgres-mcp` ("Postgres MCP Pro"), v0.3.0 (2026-05-16). Its read-only switch is **`--access-mode=restricted`** (read-only transactions + execution-time limit + pglast SQL parsing that rejects `COMMIT`/`ROLLBACK`). It does **not** accept `--read-only`.
- `--read-only` is the flag of the **deprecated** `modelcontextprotocol/servers` Postgres reference — exactly the entry the spec says to avoid. If the recommender pre-fills `--read-only`, it will either silently target the deprecated server or hand the user an invalid flag for the right server.
- **Constraint:** when the recommender writes `.mcp.json` for Postgres, it MUST emit `--access-mode=restricted` against `crystaldba/postgres-mcp`, not `--read-only`.
- Source: https://github.com/crystaldba/postgres-mcp (README, access modes).

**🟡-2 — `crystaldba/postgres-mcp` is the slowest-moving server in the §10 set.**
Last push 2026-01-22 (~5 months stale vs the others, which pushed within the last 3 weeks). Still maintained (v0.3.0 shipped 2026-05-16 via release tag; 3.0k★; not archived), so 🟡 not 🟠. No alternative swap needed — it remains the de-facto maintained Postgres MCP — but the recommender's "maintained vendor server" copy should not overstate its release cadence. Re-check at build time; if it crosses 12 months with no commit, re-classify 🟠.
- Source: `gh api repos/crystaldba/postgres-mcp` (pushed_at 2026-01-22).

**🟡-3 — "fastembed/onnxruntime" in the dispatch brief mislabels the V-memory stack.**
The task framing and the dispatch note refer to V-memory's embedding deps as "fastembed/onnxruntime." The actual implementation (`scripts/compound-v-memory.py:868`) installs `onnxruntime, tokenizers, huggingface_hub, numpy` and runs a **direct-onnxruntime** lane over the Xenova ONNX export of multilingual-e5-small. The `fastembed` library is **never imported**. This is harmless to `/v:onboard` (which adds no embedding deps — it only extends which files get indexed, §4/§9), but the label should not propagate into the plan as if `fastembed` were a dependency to pin or audit.
- **No conflict:** `/v:onboard` introduces zero new Python/embedding deps. The V-memory DENSE lane is untouched; onboarding's only interaction is auto-running `/v:memory-refresh` (§3 INDEX, §9), which is the existing, unchanged indexer.
- Source: `scripts/compound-v-memory.py:343-364, 850-889`.

---

## 7. Design Constraints for the Plan (MUST / MUST NOT)

- **MUST** invoke the design.md linter as `npx @google/design.md lint DESIGN.md` (optionally `--format json` for machine parsing). The package name `@google/design.md`, the `lint` subcommand, and the JSON `{findings:[{severity,path,message}], summary:{errors,warnings,info}}` schema are all verified exact as of v0.3.0. `severity` ∈ `error|warning|info`; treat `errors > 0` (exit code 1) as the blocking condition.
- **MUST** treat repomix's secret scan as **default-on** (`security.enableSecurityCheck` / Secretlint). Do NOT design the PACK step around a flag-to-enable secret scan — it runs unless explicitly disabled with `--no-security-check`. The §5/§3 "blocking secret scan" is satisfied by repomix's built-in behavior; the plan need not add a separate scanner for the pack step.
- **MUST** pin Playwright MCP to **`@playwright/mcp` ≥ 0.0.40** when the recommender pre-fills `.mcp.json` — CVE-2025-9611 (DNS-rebinding via missing Origin/Host validation) is fixed at 0.0.40. Current latest is 0.0.77, so `@latest` is safe today; an explicit floor protects against a user pinning an old version. (CVSS-relevant: local MCP reachable from a malicious web page → full tool access.)
- **MUST** emit Postgres MCP as `crystaldba/postgres-mcp` with **`--access-mode=restricted`** (NOT `--read-only`). Correct the §10 wording. (Finding 🟡-1.)
- **MUST** keep Supabase MCP flags as `--read-only --project-ref=<ref>`; both are real and recommended. Document that `--project-ref` scopes only DB tools, so the lethal-trifecta warning (§10) still applies to `create_project`/`create_branch`-class tools that ignore the project scope.
- **MUST** resolve every §10 server to the maintained vendor/community server, never the `modelcontextprotocol/servers` reference repo. Note: that reference repo is itself NOT archived (it still hosts everything-server, fetch, etc.), but its individual *database/integration* reference servers (Postgres, GitHub, etc.) are the deprecated entries the spec warns about — the live vendor servers (`crystaldba/postgres-mcp`, `github/github-mcp-server`, `@supabase/...`, `getsentry/sentry-mcp`) supersede them.
- **MUST** keep the AGENTS.md→CLAUDE.md bridge exactly as designed: a thin `CLAUDE.md` whose first line is `@AGENTS.md`. Verified against official docs — Claude Code does NOT read `AGENTS.md` natively; the `@AGENTS.md` import is the canonical bridge. The CLAUDE.md 200-line ceiling (§4/§5) is a documented *recommendation* ("target under 200 lines"), not a hard limit — CLAUDE.md loads in full regardless of length. Phrase the invariant as "target ≤200 lines," not "ceiling enforced at 200."
- **MUST NOT** rely on `@import` for token savings (spec §5 already states this) — confirmed: imported files load in full at launch; only path-scoped `.claude/rules/*.md` and skills defer. Spec is correct.
- **MUST NOT** treat `fastembed` as a dependency. The V-memory lane is direct-onnxruntime. (Finding 🟡-3.)
- **SHOULD** prefer the **remote** GitHub MCP (`https://api.githubcopilot.com/mcp/`) and **remote** Sentry MCP (`https://mcp.sentry.dev/mcp`) in recommender copy where the host supports remote MCP, falling back to local (Docker/binary for GitHub; stdio for Sentry self-hosted). Remote GitHub MCP currently has full remote support primarily in VS Code; for Claude Code, validate remote-MCP support at build time or default to local.

---

## 8. Open Questions for the Human

1. **GitHub MCP transport for Claude Code.** Remote GitHub MCP (`api.githubcopilot.com/mcp/`) needs the host to register an OAuth/GitHub App; docs note full remote support is currently strongest in VS Code. Should the §10 recommender default to **local** GitHub MCP (Docker/binary) for the Claude-Code-first audience, or attempt remote first? This is a UX/setup-friction call, not a currency one.
2. **Postgres MCP cadence tolerance.** `crystaldba/postgres-mcp` last *commit* is 2026-01-22 (releases are newer). Is ~5 months of commit quiet acceptable for a server the recommender pre-fills with `--access-mode=restricted`, or do you want a staleness re-check baked into the recommender so it warns if the server crosses 12 months untouched? (No alternative needed today.)

(Both are scoping decisions, not blockers. The dependency set is shippable as-is once the §6/§7 corrections land.)

---

## 9. Knowledge Base Updates

Appended to (created) `docs/superpowers/library-audit/_knowledge-base/agent-instruction-tooling.md`:
- `@google/design.md` v0.3.0 — package/bin/subcommands/JSON schema/WCAG rule, all date-stamped 2026-06-30.
- `repomix` 1.16.0 — secret-scan-default-on, token counts, gitignore-aware.
- AGENTS.md / AAIF — Claude-reads-CLAUDE.md-not-AGENTS.md, `@AGENTS.md` bridge, 200-line guidance (not hard ceiling).
- MCP server matrix (§10) — GitHub / Postgres(crystaldba, access-mode=restricted) / Supabase / Playwright(CVE-2025-9611 ≥0.0.40) / Context7 / Sentry, with maintained-vendor resolution and the deprecated-reference caveat.
- V-memory embedding lane note — direct-onnxruntime, NOT fastembed; `/v:onboard` adds no embedding deps.
