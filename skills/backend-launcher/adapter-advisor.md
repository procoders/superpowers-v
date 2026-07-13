# Adapter: Advisor (READ-ONLY cross-brand consult)

> Read the contract in [`SKILL.md`](SKILL.md) first. Unlike the implementer adapters ([`adapter-codex.md`](adapter-codex.md), [`adapter-claude.md`](adapter-claude.md), …), this adapter does **not** map a `job_spec → job_result`. It is a **side consult**: a cheap executor that hits a hard sub-decision asks a DIFFERENT-brand advisor for a recommendation, gets back advice **text**, and keeps building. The wiring lives in [`scripts/compound-v-advisor-consult.sh`](../../scripts/compound-v-advisor-consult.sh).

The advisor is the "cheap executor + on-demand cross-brand advisor" pattern (v2.12, Feature B): a `standard`-tier / core-slice implementer (or a fast-path Claude worker) that reaches a genuinely hard decision consults an advisor of a **different model and brand** — Codex if available, else Opus — for a second opinion, then proceeds. The advisor advises; the executor decides and does the writing.

---

## The one hard rule: the advisor is READ-ONLY

**The advisor NEVER writes a file and NEVER runs a destructive command. It returns advice text, nothing else.**

This is not a stylistic preference — it is the structural mitigation for a real incident. On **2026-07-13 a live nested bypass agent (`claude -p --dangerously-skip-permissions`) deleted this entire repo.** A no-write advisor is *structurally incapable* of that class of damage regardless of what it is asked to do or what a prompt-injection tries to make it do. So the read-only property is enforced at the invocation layer, on **both** backend paths, and neither path ever passes `--dangerously-skip-permissions` (nor `--yolo`, nor a bypass `--permission-mode`).

The consult is **stub-first**: it is proven end-to-end by [`scripts/test-advisor-worker-stub.sh`](../../scripts/test-advisor-worker-stub.sh) against a FAKE backend, with **no real backend ever invoked**. A real probe is permitted ONLY under the read-only sandbox path — never a live opus fallback in this test.

---

## Cross-brand selection (B1 selector)

The advisor backend is chosen deterministically by [`scripts/compound-v-resolve-model.py --select-advisor`](../../scripts/compound-v-resolve-model.py), which prefers a **different brand** than the executor so the second opinion is genuinely decorrelated:

```
codex  >  any other non-claude (cursor / antigravity / devin / opencode)  >  opus fallback
```

- **codex** — the preferred cross-brand advisor (available in most runs, and a kernel read-only sandbox exists).
- **opus fallback** — `backend: claude`, `model: opus`. Always available, a different brand than any non-claude executor, and **never haiku**.

The consult calls the selector with the executor's backend and the run's `--available` backends, or accepts an explicit `--advisor-backend` override (whose concrete deep model is still resolved through the resolver). **B2 drives exactly the two pinned READ-ONLY paths below (codex, claude);** any other selected backend is *refused* rather than driven with an unproven/unsafe invocation.

---

## The two pinned invocations (exact safe flags)

### Cross-brand — `codex exec --sandbox read-only --json`

```bash
codex exec \
  --sandbox read-only \        # kernel read-only sandbox: NO writes possible
  --skip-git-repo-check \      # the --cd dir may not be a git root
  --json \                     # JSONL event stream to stdout
  --model "$advisor_model" \   # resolved deep-tier codex model (e.g. gpt-5.6-sol)
  --cd "$cd_dir" \
  --output-last-message "$advice_file" \   # advice text is read from HERE, not stdout
  "$prompt" </dev/null
```

`--json` forces codex's stdout to a JSONL event stream, so the advice text is taken from `--output-last-message` (the same proven pattern the codex worker uses for its `summary`), never scraped from stdout. There are **no write flags and no `--dangerously-*` of any kind** — the read-only sandbox is the boundary.

### Opus fallback — `claude -p --model opus --permission-mode plan`

```bash
claude -p \
  --model opus \
  --permission-mode plan \                       # plan mode is STRUCTURALLY incapable of editing
  --disallowedTools Write Edit MultiEdit NotebookEdit \  # belt-and-braces defense-in-depth
  --output-format stream-json --verbose \        # stream-json REQUIRES --verbose (library-audit)
  "$prompt" </dev/null
```

`--permission-mode plan` is the structural no-write guarantee (`plan` cannot edit — verified against `claude --help`, choices include `plan`); `--disallowedTools` is redundant defense-in-depth. The advice text is parsed from the **last** `result` event's `.result` in the stream-json output. This path **NEVER** passes `--dangerously-skip-permissions` / `--allow-dangerously-skip-permissions` / `--yolo` / `--permission-mode bypassPermissions` — the `--advisor` flag the PRD originally imagined **does not exist** (`claude 2.1.207`, 0 matches; see [library-audit](../../docs/superpowers/library-audit/2026-07-13-usage-and-advisor.md)), so the advisor is this harness subagent pattern instead.

Both paths run under the shared process-group timeout supervisor [`scripts/compound-v-run-with-timeout.py`](../../scripts/compound-v-run-with-timeout.py) (`--timeout … --stdout … --stderr … --max-output-bytes …`, stdin `</dev/null`), so a hung or runaway advisor is capped in wall-clock and in output bytes, exactly like every other worker.

> **Honest caveat (not live-probed — the safety rule forbids a live run in this job):** `--output-last-message` on the codex read-only path is a CLI-orchestrator write (the same mechanism the `workspace-write` worker uses for its summary), assumed to be independent of the model's read-only sandbox. It is proven here only via the stub. Confirm it with a single real read-only probe (allowed by the Global Constraints) before relying on the codex path in anger.

---

## `advisor_calls` — DERIVED by counting a per-job log, never self-reported

`advisor_calls` counts **how many times the executor actually consulted an advisor**. The honest, tamper-resistant way to produce that count is to **count log lines on disk**, not to trust a number the worker reports about itself:

- **Per-job advisor log:** the dispatcher passes `--calls-log <run-dir>/logs/<job-id>.advisor.jsonl` on every advisor-eligible dispatch (same `logs/` dir the codex events-log uses).
- **The consult appends ONE line per successful consult.** On each SUCCESSFUL consult, `compound-v-advisor-consult.sh` appends exactly one compact JSON line — `{"advisor_backend", "advisor_model", "advisor_calls":1, "ts"}` — to that file (parent dir created if needed; **append, never truncate**). A *failed* consult `die()`s before the emit and logs nothing, so a line means a real, completed consult. Omitting `--calls-log` restores the prior behavior exactly (no logging) — the flag is backward-compatible.
- **collect-results DERIVES the count.** [`scripts/compound-v-collect-results.py`](../../scripts/compound-v-collect-results.py) counts the lines in `<run-dir>/logs/<job-id>.advisor.jsonl` and writes that count into the job's `usage.advisor_calls`. The number is therefore **git/FS-derived from what actually happened**, never scraped from a CLI's `usage.iterations[]` (that field is a *turn* count, not an advisor count, and reading it would over-report — see [library-audit](../../docs/superpowers/library-audit/2026-07-13-usage-and-advisor.md) §Advisor reality) and never taken from the worker's own claim. No log file ⇒ `0` consults, honestly.

The `advisor_calls: 1` on the consult's **stdout** object still reports *this* single consult; the RUN-LEVEL `usage.advisor_calls` is the derived line-count, not a sum of self-reported fields. Feature A's escalation sensor consumes `usage.advisor_calls` read-only; Feature B is the sole producer.

**Wired case (end-to-end today):** a **CLAUDE executor** on an advisor-eligible job consults a **cross-brand (codex)** advisor when codex is available, else the **Opus fallback** (`backend: claude`, `model: opus`). The dispatcher wires the `--calls-log` path at dispatch time (see [`agents/parallel-dispatcher.md`](../../agents/parallel-dispatcher.md) §advisor consult); collect-results derives the count after the job. This is the meaningful, wired path — not an aspirational one.

---

## How the executor calls the consult

```bash
scripts/compound-v-advisor-consult.sh \
  --question "Queue or mutex for the shared write path here, given the contention profile?" \
  --context-path "src/worker/pool.ts" \
  --context-path "docs/superpowers/recon/*.md" \
  --executor claude \
  --available "codex,claude" \
  --calls-log "docs/superpowers/execution/$RUN_ID/logs/$JOB_ID.advisor.jsonl"
# optional: --question-file <abs>   --advisor-backend codex   --cd <dir>   --timeout-sec 300
# --calls-log is what the dispatcher passes so collect-results can DERIVE usage.advisor_calls;
# omit it and the consult behaves exactly as before (no logging).
```

Output (stdout) — exactly one JSON object:

```json
{"advisor_backend": "codex", "advisor_model": "gpt-5.6-sol", "advice": "…", "advisor_calls": 1}
```

- `--question` / `--question-file` — the sub-decision (exactly one). Read-only context files are embedded into the prompt via repeatable `--context-path <glob>`, so the advice is grounded without relying on the backend's own (sandboxed / read-only) file access.
- `--executor` (default `claude`) + `--available <csv>` feed the cross-brand selector; `--advisor-backend` overrides it.
- `--calls-log <path>` (optional) — on each SUCCESSFUL consult, append one compact JSON line to `<path>` (parent dir auto-created; append, never truncate). The dispatcher passes `<run-dir>/logs/<job-id>.advisor.jsonl`; collect-results counts those lines to derive `usage.advisor_calls`. Omitting it means no logging.
- The script writes **only** ephemeral scratch under `$TMPDIR` (plus the append-only `--calls-log` line when that flag is given) to capture the backend's own output — it never writes a repo/deliverable file, and its stdout is exactly one JSON object.
- **Testing:** set `$COMPOUND_V_ADVISOR_STUB` to a fake backend path and the consult invokes it in place of the real `codex`/`claude` binary with the **identical argv** — how [`test-advisor-worker-stub.sh`](../../scripts/test-advisor-worker-stub.sh) proves the selector, the safety flags, and the advice parse with no live run.
