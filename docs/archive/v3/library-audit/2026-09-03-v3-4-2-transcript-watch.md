# Compound V — Phase 1C Library & Documentation Audit

**Spec audited:** docs/superpowers/specs/2026-09-03-v3.4.2-transcript-watch-design.md
**Topic slug:** v3-4-2-transcript-watch

## 0. V-memory recall (Step 0)
Four compound-v-memory.py searches run before opening any file. Every call printed: "V-memory: index is 87 new / 0 removed docs behind the repo — run /v:memory-refresh" — the FTS5 index is stale relative to HEAD; flagged as an open item (§8), not treated as blocking. Useful hits, each independently re-verified live rather than trusted as-is: claude-code-hooks.md (Stop/SubagentStop schema, tangential — this feature registers no hook), token-budget-and-usage-visibility.md (JSONL transcript path family, output-token undercount bug), and claude-code-runtime.md's 2026-09-02 entry, which already carries the Python-3.9-EOL finding cited in §5 below (not re-derived from scratch, independently cross-checked via WebSearch — same dates). No Trigger-0 recon doc exists for this topic (checked docs/superpowers/recon/*transcript* and *v3*4* — no match).

## 1. Tools Available
Context7: not invoked — the spec has ZERO third-party dependencies (Decision 1: "Python 3.9 stdlib", no pip/npm package, no external SDK). This audit instead validates the PLATFORM surface the script reads (Claude Code's own JSONL transcript layout, subagent meta files, CLAUDE_CONFIG_DIR) — not in Context7's index, matching this repo's own established precedent in claude-code-runtime.md ("not third-party libraries and not in Context7; authoritative source is the installed binary plus code.claude.com/docs"). Manifests found: NONE (package.json/requirements.txt/pyproject.toml/go.mod/Cargo.toml/Gemfile/composer.json all absent, Glob-confirmed 2026-09-03) — by design, CONVENTIONS.md: stdlib only.

## 2. Libraries / Platform Surfaces Mentioned
- CPython 3.9 stdlib — 3.9 reached EOL 2025-10-31, 3.9.25 final security release (python.org; Red Hat Developer 2025-12-04), confirmed via WebSearch 2026-09-03 matching the repo's existing 2026-09-02 KB finding verbatim. Inherited repo-wide constraint, not novel. Status: MEDIUM.
- Claude Code subagent JSONL transcripts — Decision 2 claims `<session>/subagents/workflows/<wf_id>/agent-<id>.jsonl`. LIVE-VERIFIED in this exact running session via Glob/Read against `~/.claude/projects/-Users-oleg-Dev-superpowers-v/e619cb38-.../subagents/` — the path is real but CONDITIONAL: it has the `workflows/<wf_id>/` segment ONLY for Dynamic-Workflow-spawned agents (19 real `wf_*` dirs found in this exact project/session, each with agent-*.jsonl + journal.jsonl); a directly-Task-spawned agent (no workflow) lands one level higher at `<session>/subagents/agent-<id>.jsonl`, confirmed by ~60 such files with no `workflows/` ancestor. Compound V 3.0 dispatches exclusively via the native Workflow runtime per AGENTS.md, so the workflow-spawned shape is what this feature will actually see. Status: OK, with a MUST constraint (§4/§7).
- agent-<id>.meta.json fields agentType/model — CONFIRMED but conditional: `{"agentType":"workflow-subagent","spawnDepth":1,"model":"opus"}` when a model override was set vs `{"agentType":"workflow-subagent"}` (key absent, not null) when default. Status: OK, one MUST constraint.
- journal.jsonl (started/failed/result) — CONFIRMED live, all three line types present (grep for "type":"failed" hit all 19 journal.jsonl files in this session), at exactly `<session>/subagents/workflows/<wf_id>/journal.jsonl`.
- CLAUDE_CONFIG_DIR — Decision 2 claims the session dir "comes from CLAUDE_CONFIG_DIR / ~/.claude/projects/<encoded cwd>". BINARY-grep-confirmed real and actively used: literal string appears 20+ times in the installed runtime (/Users/oleg/.local/share/claude/versions/2.1.238), including a dense repeated cluster — genuinely read by runtime code. This CONTRADICTS a WebFetch summary of GitHub issue #28808 ("closed as duplicate... feature request... not implemented") and a related bug report #3833 suggesting partial/flaky behavior. Per this project's own established convention (claude-code-runtime.md: "WebFetch confabulated this contract... extract from the installed binary; treat fetched summaries of truncated pages as unreliable"), BINARY evidence wins — the var is real. But the exact "falls back to ~/.claude/projects/<encoded cwd>" half of the claim was NOT independently re-verified against the binary this pass (only against a WebSearch aggregate) — flagged as MEDIUM / open question.
- Monitor / TaskStop (harness tools, Decision 5) — CONFIRMED live: both are real, currently-loadable deferred tools in this exact session.
- register-lane (compound-v's own convention) — confirmed real via grep of scripts/compound-v-emit-workflow.py and scripts/compound-v-scope-check.py; not invented for this spec. Deep validation is Phase 1A's job, not duplicated here.

## 3. API/Data-Shape Signatures Verified
- message.content[] tool_use (name, input): CONFIRMED live in this session's own agent-a72be09d519e61c3c.jsonl.
- message.content[] tool_result (content): CONFIRMED, 48 occurrences in the same file.
- meta.json model key: confirmed present-when-set, ABSENT (not null) when unset — a strict-schema reader will crash on the common case.
- Discovery mechanic (scan subagents/workflows/*/agent-*.jsonl for the run dir's absolute path): the directory SHAPE is confirmed real; whether a worker's first tool_use actually carries the run-dir path via register-lane exactly as claimed was NOT verified this pass (Phase 1A territory).
- Python 3.9 stdlib sufficiency (json/glob/pathlib/re/argparse) for every signal in Decisions 3/4: CONFIRMED sufficient, no package needed.

## 4. Critical Findings 🔴
None — no deprecated/archived/unmaintained dependency exists because there is no dependency.

## 5. High-Priority Findings 🟠
🟠-1 — The claimed transcript path is real but not universal. A direct-Task-spawned subagent (no workflow) writes ONE directory level higher (no `workflows/<wf_id>/` segment) than Decision 2 assumes. Not a spec defect today (compound-v dispatches Workflow-only), but the discovery logic will find nothing if a future dispatch mode ever bypasses the Workflow runtime. MUST: state explicitly that discovery targets Workflow-spawned transcripts only, and define what --once prints (not silent success) when zero matching wf_* directories exist for the run.

🟠-2 — meta.json's model key is absent-when-default, not null-when-default; a strict-schema read will crash. MUST: use meta.get("model") everywhere, never meta["model"]; the test fixture must include a meta.json with the key omitted, not just one with it present.

🟠-3 — CLAUDE_CONFIG_DIR is real (BINARY-confirmed) but its exact fallback-to-~/.claude/projects/<encoded cwd> resolution semantics were not independently pinned against the binary this pass, and a GitHub bug report suggests possibly-partial centralization on some versions. MUST: resolve CLAUDE_CONFIG_DIR env var if set, else ~/.claude, and fail loudly (not silently scan an empty directory) if the resolved project directory doesn't exist. SHOULD: a --selftest check for this.

## 6. Medium Findings 🟡
🟡-1 — Python 3.9 EOL (2025-10-31), inherited not novel. Two concrete traps for an implementer to avoid: `X | Y` type-hint unions are 3.10+ (not 3.9); `datetime.UTC` is 3.11+ — use `datetime.timezone.utc`. The repo's own dashboard script already has 2 live occurrences of the sibling mistake (datetime.utcnow(), deprecated since 3.12, claude-code-runtime.md:148-153) — don't repeat it in the new script's timestamp/staleness-clock code.

🟡-2 — Monitor's `--every 120` background loop (Decision 5) has no documented maximum poll count or wall-clock ceiling found this pass. SHOULD: state explicitly what stops the watcher itself (distinct from TaskStop on the workflow it watches) before writing-plans locks this in. Advisory, not blocking.

## 7. Design Constraints for the Plan
MUST: (1) treat wf_*-directory discovery as Workflow-spawned-only with an explicit non-crashing zero-match outcome; (2) parse meta.json with an absent-key-tolerant contract for every field; (3) resolve CLAUDE_CONFIG_DIR defensively with a loud failure on a missing resolved directory; (4) target Python 3.9 syntax only — no `X | Y` unions, no `datetime.UTC`, use `datetime.timezone.utc`; (5) for any future re-verification of Claude Code's own transcript/config-dir contract, cite BINARY (installed-runtime grep) over WebFetch-summarized docs or GitHub issue threads, per this project's own established and re-confirmed convention.
MUST NOT: (1) assume every subagent transcript lives under a workflows/<wf_id>/ segment; (2) add any third-party Python package — everything needed is stdlib-sufficient.

## 8. Open Questions for the Human
1. CLAUDE_CONFIG_DIR's exact fallback-to-~/.claude/projects/<encoded cwd> semantics — confirmed real via BINARY grep, but the fallback path itself wasn't re-verified against the binary, only a WebSearch aggregate. Worth one more BINARY pass if this needs to be a hard MUST rather than a defensive SHOULD.
2. V-memory is 87 documents behind HEAD (every search this pass warned). Not this spec's problem, but running /v:memory-refresh before the next 1B/1C pass would make Step 0 complete rather than partial.
3. Whether the plan deliberately chose JSONL-file polling over the already-documented live subagentStatusLine hook (research/2026-07-11-token-budget-and-usage-visibility.md, requires Claude Code >= 2.1.205) as an alternative signal source, or simply didn't consider it — worth a human sanity check, not a blocker (the spec's own "Not in scope" already excludes a daemon).

## 9. Knowledge Base Updates (NOT YET APPLIED — same lane block)
Intended: append one section to the EXISTING docs/superpowers/library-audit/_knowledge-base/claude-code-runtime.md (correct home — it already owns "Claude Code's own runtime contracts... not third-party... not in Context7") under "## Updated 2026-09-03 — v3.4.2 transcript-watch": the subagent JSONL/meta.json/journal.jsonl directory-layout facts, the model-key-conditional finding, and the CLAUDE_CONFIG_DIR BINARY-grep evidence, each with the exact live-probe method (Glob+Read/Grep against this session's own real transcript directory; Grep against the installed 2.1.238 binary) for reproducibility. This KB append is also blocked by the same lane-guard denial and was not attempted (would hit the identical error).

Counts: 0 critical, 3 high (🟠-1, 🟠-2, 🟠-3), 2 medium (🟡-1, 🟡-2). Section 8 (Open Questions) has 3 items, none blocking — all advisory/housekeeping.
