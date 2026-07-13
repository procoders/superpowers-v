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

## `advisor_calls` — worker-counted, not CLI-reported

`advisor_calls` counts **how many times the executor actually consulted an advisor**. This single consult contributes `1`. It is emitted by the consult script and is **NOT** read from any CLI's `usage.iterations[]` — that field is a *turn* count, not an advisor count, and reading it would over-report (see [library-audit](../../docs/superpowers/library-audit/2026-07-13-usage-and-advisor.md) §Advisor reality). Feature A's escalation sensor consumes `usage.advisor_calls` read-only; Feature B is the sole producer.

---

## How the executor calls the consult

```bash
scripts/compound-v-advisor-consult.sh \
  --question "Queue or mutex for the shared write path here, given the contention profile?" \
  --context-path "src/worker/pool.ts" \
  --context-path "docs/superpowers/recon/*.md" \
  --executor claude \
  --available "codex,claude"
# optional: --question-file <abs>   --advisor-backend codex   --cd <dir>   --timeout-sec 300
```

Output (stdout) — exactly one JSON object:

```json
{"advisor_backend": "codex", "advisor_model": "gpt-5.6-sol", "advice": "…", "advisor_calls": 1}
```

- `--question` / `--question-file` — the sub-decision (exactly one). Read-only context files are embedded into the prompt via repeatable `--context-path <glob>`, so the advice is grounded without relying on the backend's own (sandboxed / read-only) file access.
- `--executor` (default `claude`) + `--available <csv>` feed the cross-brand selector; `--advisor-backend` overrides it.
- The script writes **only** ephemeral scratch under `$TMPDIR` to capture the backend's own output — it never writes a repo/deliverable file, and its stdout is exactly one JSON object.
- **Testing:** set `$COMPOUND_V_ADVISOR_STUB` to a fake backend path and the consult invokes it in place of the real `codex`/`claude` binary with the **identical argv** — how [`test-advisor-worker-stub.sh`](../../scripts/test-advisor-worker-stub.sh) proves the selector, the safety flags, and the advice parse with no live run.
