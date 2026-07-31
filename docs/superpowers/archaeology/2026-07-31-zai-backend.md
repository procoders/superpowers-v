# zai Backend Code Archaeology

Phase 1A audit of `docs/superpowers/specs/2026-07-31-zai-backend-design.md` against the code as it
exists on branch `feat/zai-backend` at plugin version 2.17.0.

Every claim below carries a `file:line` citation. **CONFIRMED** = I opened the file and read the
cited lines. **INFERRED** = a conclusion drawn from confirmed reads, marked as such. **UNVERIFIED**
= I could not establish it and that absence is itself the finding.

**Verification note.** `mcp__context7__resolve-library-id` returned `Monthly quota exceeded`, so
Section 4 does not use Context7. Instead I probed the exact CLI the spec pins — `claude 2.1.207`,
installed at `/Users/yurifediai/.local/bin/claude` — through `--help` and parser-only invocations
that terminate before any network call. For flag *existence* and *arity* that is stronger evidence
than documentation. z.ai's own endpoint contract is **not** verified by me; that is Phase 1C's lane
and the spec's own live probes.

---

## 1. Matrix

The dimensions a dispatched job actually branches by, and which code path owns each. Columns are
the seven backends (six live, one proposed).

| Dimension (owning code) | claude | codex | antigravity | cursor | devin | opencode | **zai (proposed)** |
|---|---|---|---|---|---|---|---|
| In `VALID_BACKENDS` — `compound-v-validate-manifest.py:519` | yes | yes | yes | yes | yes | yes | **must add** |
| In `BACKENDS` — `compound-v-resolve-model.py:144` | yes | yes | yes | yes | yes | yes | **must add** |
| In the `⇒ worktree` tuple — `compound-v-validate-manifest.py:1817` | no | yes | yes | yes | yes | yes | **must add** |
| In the reviewer-prohibition tuple — `compound-v-validate-manifest.py:1833` | no | no | no | no | yes | yes | **must add** |
| Has a tier→model map — `compound-v-resolve-model.py:70-116` | yes | yes | yes | yes | yes | yes | **must add** |
| In `classify-failure.py` `--backend` choices — `:334` | yes | yes | yes | yes | **no** | **no** | **must add** |
| Has an explicit rules branch in `classify()` — `:238-250` | yes | yes | yes | yes | no | no | **must add** |
| Has a `FALLBACK` entry — `compound-v-failure-policy.py:59` | yes (None) | yes | yes | yes | **no** | **no** | **must decide** |
| Usage measurable — `compound-v-usage-extract.py:200-214` | no (`:56`) | yes | no (`:56`) | yes | no (`:56`) | yes | **spec says yes** |
| Has an `extract_usage` dispatch branch — `:207-212` | n/a | yes | n/a | yes | n/a | yes | **must add** |
| Advisor-consultable — `compound-v-resolve-model.py:345` | yes (opus) | yes | no | no | no | no | no (auto-correct) |
| May *carry* an advisor block at `standard` tier — `:348-362` | yes | yes | yes | yes | yes | yes | **yes, unspecified** |
| Has a worker script under `scripts/` | n/a (in-harness `Task`) | yes | yes | yes | yes | yes | **must add** |
| Has a row in the dispatcher's adapter table — `agents/parallel-dispatcher.md:48-53` | yes | yes | yes | yes | **no** | **no** | **must add** |
| Emits `usage` in `job_result` | n/a | yes (`run-codex-worker.sh:562-573`) | **no** (`run-antigravity-worker.sh:452-462`) | **no** (`run-cursor-worker.sh:377-387`) | (not read) | yes (`run-opencode-worker.sh:747-758`) | **spec says yes** |

Two cells decide most of the work:

- **`devin` and `opencode` are already absent from four registries** — `classify-failure.py:334`,
  `compound-v-failure-policy.py:59`, and the `agents/parallel-dispatcher.md:48-53` adapter table.
  So "add a sixth backend the way the fifth was added" reproduces four pre-existing holes. The
  spec's Files-touched list names none of these three files.
- **The named structural template (`cursor`) sits on the wrong side of the `usage` row.** The
  cursor worker deliberately does not emit `usage` (`compound-v-run-cursor-worker.sh:253-254`:
  "`.usage` token counts are deliberately IGNORED"). The spec requires `zai` to emit it. So the
  template is cursor for the worktree/gate half and **codex/opencode for the emit half** — two
  different sources, which the spec does not say.

---

## 2. Shared State

### `emit_job_result` — arity differs across workers (CONFIRMED)

| Worker | Params | Has `usage`? |
|---|---|---|
| `compound-v-run-cursor-worker.sh:77-104` | 10 | **no** |
| `compound-v-run-antigravity-worker.sh:70-97` | 10 | **no** |
| `compound-v-run-codex-worker.sh:61-90` | 11 | yes (`--argjson usage`, `:76`) |
| `compound-v-run-opencode-worker.sh:109-138` | 11 | yes (`--argjson usage`, `:124`) |

A `zai` worker copied from cursor emits a 10-key object. `job_result.usage` is optional in the
schema, so it validates — and then `compound-v-usage-aggregate.py:127` reads `measured` as `False`
and the job counts as unmeasured. **Silent AC6 failure, no error anywhere.**

### `BASELINE_SHA` — capture ordering is load-bearing (CONFIRMED)

Set at `compound-v-run-cursor-worker.sh:228-230`, **before** `git worktree add` at `:232`, and passed
as `--baseline "$BASELINE_SHA"` at `:321`. The comment at `:226-227` states why. `CHANGELOG.md:482`
records this as a CRITICAL fix: with the literal `HEAD`, a worker that *commits* inside its worktree
leaves a clean tree and the gate sees nothing. Identical construction at
`compound-v-run-codex-worker.sh:249-261`, `-antigravity-:254-266`, `-opencode-:306-318`.

Gap: the spec never mentions the baseline SHA or its ordering.

### `$ART` — scratch must be a *sibling* of the worktree (CONFIRMED)

`ART="$WT.art"` at `compound-v-run-cursor-worker.sh:235`. The rationale is written out at
`compound-v-run-opencode-worker.sh:320-330`: the adapter's own scratch (allow-file, stdout/stderr
logs, result text) must live **outside** `$WT`, because the gate unions `git diff` with
`git ls-files --others --exclude-standard` — anything inside the worktree shows up as an untracked
file and produces "a false BLOCKED verdict on every single job".

Gap: the spec never mentions `$ART`. Every log path it implies (the `--output-format json` capture,
the allow-file, the concatenated CLAUDE.md injection file) must land there.

### `WRITE_ALLOWED` expansion — `set -f` is missing in the template (CONFIRMED — latent bug)

The colon-split loop appears in all four workers:

| Worker | Lines | `set -f` guard? |
|---|---|---|
| `compound-v-run-opencode-worker.sh` | 630-647 | **yes** (`:640` / `:646`) |
| `compound-v-run-cursor-worker.sh` | 306-315 | **no** |
| `compound-v-run-codex-worker.sh` | 438-447 | **no** |
| `compound-v-run-antigravity-worker.sh` | 354-363 | **no** |

The opencode comment at `:635-639` states the failure precisely: without `set -f`, the unquoted
`for _glob in $WRITE_ALLOWED` pathname-expands each glob against the launcher's cwd, silently
corrupting the allow-list before the gate ever sees it. A `write_allowed` of `scripts/*.py` becomes
whatever `scripts/*.py` happens to match *in the process's cwd* — a real allow-list widening or
narrowing depending on where the dispatcher was invoked from.

**The spec names the worker without `set -f` as its structural template.** Copying cursor verbatim
inherits the bug into a seventh place.

### `$ZAI_API_KEY` — no reader exists (CONFIRMED)

`compound-v-project-config.py` declares exactly three config blocks: `models` (`:102-104`),
`pre_eval` (`:105-107`), `brainstorm` (`:108-110`). There is **no** reader for a capability block,
a `backends` list, or any env-var name. `commands/v-init.md:507` explicitly forbids writing
`backends` or `checked_at` into that file (removed in v2.6.2).

So the spec's "read from a single environment variable, `ZAI_API_KEY`, named in
`.claude/compound-v.json` and detected by `/v:init`" describes documentation, not a code path. The
only mechanism that works is: the worker reads `$ZAI_API_KEY` from its **own** environment (it
inherits the dispatcher's) and injects it as `ANTHROPIC_API_KEY` into the `env -i` child. The spec
does not say what happens when the variable is unset — per the `die()` convention
(`compound-v-run-cursor-worker.sh:69-72`) that must be an exit-2 environment fault with no
`job_result`, not a job-level auth failure.

### `_SAFE_ENV_VARS` — the spec's list is narrower than the only precedent (CONFIRMED)

`compound-v-run-opencode-worker.sh:95` forwards `PATH HOME TMPDIR LANG LC_ALL TERM`. The spec
forwards `PATH HOME TMPDIR LANG` — dropping `LC_ALL` and `TERM`. The repo treats locale as
load-bearing for Python: `.github/workflows/validate.yml:274` runs every selftest as
`LANG=C python3`. The worker runs `python3 "$SUPERVISOR"` **inside** the `env -i` wrapper
(`compound-v-run-opencode-worker.sh:504`/`:516`), so the narrowing applies to the supervisor too.
The divergence needs a stated reason or it should match the precedent.

### `env -i` allow-list construction — bash 3.2 (CONFIRMED)

`compound-v-run-opencode-worker.sh:481-493` builds the entries as **positional parameters** via
`set -- "$@" "$_v=$_safe_val"`, not a concatenated string, with the reason spelled out at `:484-485`:
a PATH segment containing a space (`/Applications/Some App.app/...`) corrupts a naive splice. The
function then takes them explicitly (`run_opencode "$@"` at `:532`) because a bash function does not
inherit the caller's positionals (`:497-499`).

---

## 3. Sibling Code

### `scripts/compound-v-run-cursor-worker.sh` (389 lines) — read in full

**Entry conditions / preconditions.** `--run-id --job-id --repo --prompt-file` required (`:152-155`);
`--model` optional (`:156`); empty `--write-allowed` legal and means read-only (`:157`);
`--timeout-sec` pinned to `^[0-9]+$` (`:161-163`) **and** `> 0` (`:164` — cursor is the only worker
with the `>0` check; codex `:157-159` and antigravity `:162-164` omit it); `id_is_safe` on both ids
(`:109-117`, called `:166-167`); `--repo`/`--prompt-file` must be absolute (`:169-172`);
`command -v` preflight for jq/git/python3/cursor-agent (`:183-186`); supervisor must exist (`:194`).

**Worktree lifecycle.** `$TMPDIR` must be absolute (`:201-204`) and is canonicalized with `pwd -P`
(`:205`) to resolve the macOS `/var` → `/private/var` link; the parent must not be a symlink (`:207`);
the worktree path is asserted strictly under `$WT_PARENT_REAL` (`:213-216`) and asserted **not**
inside the repo (`:217-220`) — a worktree inside the repo makes the diff-based gate meaningless.
Stale worktrees are removed idempotently (`:222-224`), which is what makes `/v:resume` re-dispatch
work.

**Run.** `set +e` around the supervised launch (`:267`/`:278`) so exit 124 is captured instead of
aborting under `set -euo pipefail`. Supervisor invoked with `--cwd "$WT"`, `--stdout`, `--stderr`,
`</dev/null` (`:269-276`). Prompt is the **last** positional.

**Status derivation** (`:336-352`), in strict precedence: gate `blocked` or `viol_count > 0` wins;
then a gate fault (rc neither 0 nor 1) → error; then exit 124 → timeout; then any non-zero → error;
then the agent's own in-band error signal → error. Cursor adds the fifth clause (`:349-352`) —
`is_error: true` or a non-`success` subtype in the JSON, even on exit 0.

**Failure classification** (`:354-374`): a gate fault classifies as `other` without consulting the
classifier (`:360-362`); otherwise `--backend cursor --exit-code --stderr-file`; then two
fail-closed re-pins — `failure_class` of `""`/`null`/`none` → `other` (`:368-370`) and `retry_after`
of anything non-numeric → `"0"` (`:371-373`). The reason for the first is written at
`compound-v-run-codex-worker.sh:520-522`: the policy maps `none` to `proceed`, so a failure carrying
`none` would continue as if it had succeeded.

**Exit-code contract** (`:56-57`, `:389`): `exit 0` whenever a `job_result` was produced — including
blocked, timeout, and error. Non-zero (`die` → 2, `:69-72`) only on a usage/environment fault.

**Latent bugs in this sibling (CONFIRMED):**

1. **No `set -f` around the `write_allowed` split** (`:306-315`) — see §2. Present in opencode only.
2. **No `--max-output-bytes`** (`:269-276`). `compound-v-run-with-timeout.py:305-310` defaults it to
   `None` = unbounded direct-fd capture. opencode caps at 5 000 000 (`:82`, `:506`). A looping
   worker can fill the disk. cursor, codex, and antigravity all share this.
3. **`session_id` is not shape-validated** (`:289`, `:297`): it takes `.chatId // .chat_id //
   .session_id // .sessionId // .id` and only maps the literal string `null` to empty. codex
   anchors a full UUID regex with bash `=~` (`:413-415`) precisely because a line-oriented match
   would let `"<uuid>\nINJECT"` through; opencode gates the `ses_` prefix plus a charset
   (`:591-598`). Cursor does neither, so an arbitrary string can reach `job_result.session_id` and
   from there `state.json`.

The spec's own probe finding — z.ai returns a real RFC-4122 UUID, so "the codex worker's UUID
validator can be reused verbatim" — is the right call, and it means **codex `:409-415`, not cursor
`:289`, is the session-id template.**

### `scripts/compound-v-advisor-consult.sh` — the only existing `claude -p` subprocess

`:239-260` is the sole place this repo shells out to `claude`. Load-bearing differences from what
the spec proposes: it uses `--output-format stream-json --verbose` (`:250-251`), parses the last
`result` event with `jq -rs` (`:259`), and pins `--permission-mode plan` as a structural no-write
guarantee (`:248`). It never passes `--bare`, `--allowedTools`, or any `-file` prompt flag. So there
is **no in-repo precedent** for the spec's flag combination — `--bare` and
`--append-system-prompt-file` appear nowhere in `scripts/`, `skills/`, `commands/`, or `agents/`.

### `scripts/test-advisor-worker-stub.sh` — the named test template

The indirection is **not** "a fake `claude` on `PATH`". It is an explicit env hook,
`$COMPOUND_V_ADVISOR_STUB`, honored *inside the script under test*
(`compound-v-advisor-consult.sh:201`, `:222`, `:244`), plus `$COMPOUND_V_ADVISOR_STUB_ARGV_OUT` for
argv capture (`test-advisor-worker-stub.sh:45-48`). Assertions are exact-line and adjacency-based
(`:79-95`).

A PATH-based stub *can* work for `zai` because `PATH` is in the `env -i` allow-list — but it is a
different mechanism from the cited template, and it must survive `env -i`. If the implementation
instead adds a `$COMPOUND_V_ZAI_STUB` hook, that hook variable **must also be added to the
forwarding allow-list** or the child never sees it. The spec picks the PATH approach without noting
either constraint.

---

## 4. External APIs

Context7 unavailable (`Monthly quota exceeded`). Verified locally against `claude 2.1.207` — the
exact version the spec names — using `--help` and parser-only probes that exit before any request.

**`--bare` — CONFIRMED, and it supports the spec's central safety claim verbatim.** Help text:

```
--bare   Minimal mode: skip hooks, LSP, plugin sync, attribution, auto-memory,
         background prefetches, keychain reads, and CLAUDE.md auto-discovery.
         Sets CLAUDE_CODE_SIMPLE=1. Anthropic auth is strictly ANTHROPIC_API_KEY
         or apiKeyHelper via --settings (OAuth and keychain are never read).
         3P providers (Bedrock/Vertex/Foundry) use their own credentials.
         Skills still resolve via /skill-name. Explicitly provide context via:
         --system-prompt[-file], --append-system-prompt[-file], --add-dir
```

"OAuth and keychain are never read" is exactly the structural property the spec relies on. Note the
tail: `--bare` does **not** disable skills — "Skills still resolve via `/skill-name`". The spec's
token accounting attributes the difference to tool definitions, `SessionStart` hook output, and
`CLAUDE.md`; skills remaining reachable is an additional surface it does not discuss.

**`--output-format` — CONFIRMED, choices are exactly `text | json | stream-json`, and `json` is
described as "(single result)".** This settles §5 below: `json` is one terminal object, not a stream.

**`--permission-mode` — CONFIRMED, choices are `acceptEdits, auto, bypassPermissions, manual,
dontAsk, plan`.** `dontAsk` exists.

**`--allowedTools` is VARIADIC — an argv-ordering hazard the spec does not address.** Help text:

```
--allowedTools, --allowed-tools <tools...>
    Comma or space-separated list of tool names to allow (e.g. "Bash(git *) Edit")
```

`<tools...>` consumes every following non-option token. Placed immediately before the positional
prompt, it swallows the prompt. This is the same class of defect as antigravity's "`--print` MUST be
LAST; a flag placed right after `--print` gets eaten as the prompt"
(`compound-v-run-antigravity-worker.sh:283-285`) and opencode's need for an option terminator
(`compound-v-run-opencode-worker.sh:456-463`, live-verified there).

I probed whether `claude` tolerates `--`: `claude --output-format bogus -- hi` returns
`error: option '--output-format <format>' argument 'bogus' is invalid...` — the choice error, not
"unknown option". So `--` **is** accepted by the parser and is the available mitigation. The spec
pins the allow-list content but never pins argv order.

**`--append-system-prompt-file` / `--system-prompt-file` exist but take exactly ONE file each.**
Neither is listed as its own `--help` entry; both are named only inside `--bare`'s description.
Probing each with no value returns:

```
error: option '--append-system-prompt-file <file>' argument missing
error: option '--system-prompt-file <file>' argument missing
```

`<file>`, singular. The spec plans to pass "the user-level `CLAUDE.md` files, the project
`CLAUDE.md`, and `AGENTS.md` it imports" — three or more files — through a single-file flag.
**UNVERIFIED:** whether repeating the flag accumulates or last-wins. The safe construction that
needs no verification is to concatenate them into one file under `$ART` and pass that.

**z.ai endpoint, model names, credit multipliers, quota windows: NOT VERIFIED BY ME.** Those rest
on the spec's own 2026-07-31 probes and on Phase 1C.

---

## 5. Regression Surface

Each line: the path that works today, and what breaks if `zai` is added wrong.

1. **`classify()` unknown-backend fallback — `compound-v-classify-failure.py:249-250`.** The `else`
   branch is `rules = _CODEX_RULES`, **not** `other`. Adding `zai` to the `--backend` choices at
   `:334` without an accompanying `elif backend == "zai"` branch silently applies the OpenAI/codex
   needle set (`:47-75`, which includes `"please run \`codex login\`"` under `auth`) to GLM error
   text. A z.ai message would be classified against OpenAI signatures, and the spec's stated
   "fails closed to `other`" would be false in code.
2. **The claude stream-json enum path — `compound-v-classify-failure.py:238-241`.** Gated on
   `backend == "claude"` exactly. `--backend zai` never reaches `_parse_claude_json`. The spec's
   "the `--backend claude` stream-json path is the fallback where the output is JSON" describes an
   unreachable path unless that gate is widened — an edit the spec does not name.
3. **`--output-format json` cannot carry the enum anyway — three independent reasons.**
   (a) `CLAUDE_ENUM` (`:164-178`) maps the `api_retry` **event**; `adapter-claude.md:114-125` states
   the classifier requires `--output-format stream-json`, and the CLI itself documents `json` as
   "(single result)" — one terminal object, no interleaved `api_retry` events.
   (b) Every worker passes `--stderr-file "$STDERR_LOG"` (cursor `:363-364`, codex `:515-516`,
   antigravity `:431-432`), so the classifier reads **stderr**; `--output-format json` writes
   **stdout**.
   (c) The prefilter at `:191` requires the literal substring `"error"` (with both quotes) in the
   line. A result envelope carries `is_error`, whose preceding character is `_`, not a quote — so
   even a single-line result object is skipped. **This is the spec's clearest internal
   contradiction.**
4. **`out_of_credits` on `zai` halts the whole run — `compound-v-failure-policy.py:93`.**
   `FALLBACK.get("zai")` returns `None`, so `decide()` takes the halt branch at `:98-100` instead of
   rerouting. The spec positions `zai` as "a fallback when another backend is rate-limited", but
   `zai`'s own exhaustion has no fallback, and `FALLBACK` at `:59` is not in the Files-touched list.
   The spec also says a z.ai quota wall "is retried, not rerouted, in v1" — but with
   `failure_class: other` (its stated fail-closed default) the policy allows exactly **one** retry
   (`PER_CLASS_MAX["other"] = 1`, `:53`) and then halts (`:113-115`).
5. **Advisor blocks become valid on `zai` jobs the moment `VALID_BACKENDS` grows.**
   `compound-v-validate-manifest.py:664` validates `advisor.advisor_backend` against
   `VALID_BACKENDS`, and `_advisor_eligible` (`:599-613`) returns True for **any** `standard`-tier
   job regardless of backend. So `advisor_backend: zai` becomes an accepted manifest value — and
   `compound-v-advisor-consult.sh:262-266` then `die`s with "advisor backend 'zai' is not supported
   by the consult". A manifest that passes the gate dies at dispatch. The mitigating half is
   already safe: `select_advisor` (`compound-v-resolve-model.py:365-382`) only ever returns a name
   from `ADVISOR_CONSULTABLE_NONCLAUDE = ("codex",)` (`:345`) or the opus fallback, so `zai` is
   never auto-selected. The selftest at `:768-773` asserts this for cursor/antigravity/devin/
   opencode; no equivalent assertion would exist for `zai`.
6. **Reviewer classification is substring-based — `compound-v-validate-manifest.py:509`, `:563-570`.**
   `REVIEWER_TOKENS` includes `quality` and `integration`, matched against `type`, `id`, **and**
   `title`. A `zai` implementer job merely *titled* "integration slice" is classified as a reviewer
   and, once `zai` joins the prohibition tuple at `:1833`, fails validation with a confusing
   message. Any new selftest fixture must avoid those words in its title.
7. **The example and tracked manifests are re-validated on every CI run —
   `.github/workflows/validate.yml:130-134`.** Once this feature's own run manifest is committed
   with `backend: zai`, `VALID_BACKENDS` containing `zai` becomes a permanent CI requirement. A
   later revert of the validator alone reddens CI.
8. **`usage` silently degrades rather than erroring — `compound-v-usage-extract.py:213-214`.**
   `extract_usage("zai", ...)` with no dispatch branch returns `_unmeasured`, and the worker's
   fallback object (pattern at `compound-v-run-codex-worker.sh:545-547`) also produces
   `measured: false`. `compound-v-usage-aggregate.py:170-172` then counts the job as unmeasured and
   the run total renders `—` (`:203`). AC6 fails with no error message anywhere.
9. **`--allowedTools` swallowing the prompt would look like a *successful* no-op job.** The worker
   would exit 0, `git diff` would be empty, the gate would pass, and `status` would be `success`
   with zero files changed. Only opencode defends against the analogous case, via its false-success
   guard (`compound-v-run-opencode-worker.sh:582-585`, `:700-702`); cursor, codex, and antigravity
   have no equivalent. A `zai` worker built from cursor inherits that blind spot.
10. **Version lockstep — `.github/workflows/validate.yml:43-81`.** `plugin.json` (currently
    `2.17.0`), `marketplace.json`, and the top `## [x.y.z]` heading in `CHANGELOG.md` must move
    together or CI fails. Three files, one atomic edit.
11. **Dead intra-plugin link scan — `.github/workflows/validate.yml:203-236`.** Every markdown link
    to a `.md/.py/.sh/.json/.yml/.yaml` file must resolve. `adapter-zai.md` and
    `compound-v-run-zai-worker.sh` must exist before any document links to them.

---

## 6. DRY Findings

**The worker scripts are already four near-duplicates.** The worktree lifecycle block
(TMPDIR canonicalization → symlink rejection → containment assertion → not-inside-repo assertion →
idempotent remove → baseline SHA → `worktree add` → `$ART`) is byte-similar across
`compound-v-run-cursor-worker.sh:196-236`, `-codex-:197-270`, `-antigravity-:202-273`, and
`-opencode-:254-332`. The gate-invocation + verdict-parse block is likewise duplicated
(cursor `:299-334`, codex `:424-474`, antigravity `:342-390`, opencode `:618-674`), as are
`id_is_safe` and `emit_job_result`. `docs/superpowers/archaeology/2026-07-11-session-aware-workers.md:142`
already flagged the session-id capture as "duplicated across FOUR worker scripts" and ruled: "do NOT
invent a third capture idiom."

**Decision: add a fifth duplicate, do not refactor — but fix the divergences.** Extracting a shared
bash library is out of scope for this PR and would touch four working, live-verified scripts. The
duplication is a deliberate, documented house style. However, "duplicate" must mean duplicate of the
**best** version of each block, not of one arbitrary sibling:

| Block | Copy from | Not from |
|---|---|---|
| Worktree lifecycle + `$ART` | any (identical) | — |
| `write_allowed` split | `-opencode-:630-647` (**has `set -f`**) | `-cursor-:306-315` |
| `emit_job_result` (11-arg, with `usage`) | `-codex-:61-90` or `-opencode-:109-138` | `-cursor-:77-104` (10-arg) |
| `session_id` UUID validation | `-codex-:409-415` (anchored `=~`) | `-cursor-:289` (unvalidated) |
| `env -i` allow-list construction | `-opencode-:481-493` (`set --` positionals) | — (only precedent) |
| Bounded capture `--max-output-bytes` | `-opencode-:82`, `:506` | cursor/codex/antigravity (unbounded) |
| Timeout `> 0` check | `-cursor-:164` | codex `:157-159`, antigravity `:162-164` |
| Usage extraction call + JSON guard | `-codex-:542-547` or `-opencode-:736-740` | — |
| False-success guard | `-opencode-:582-585`, `:700-702` | — |

**`compound-v-usage-aggregate.py` needs no change (CONFIRMED).** `aggregate()` (`:94-139`) and
`_assemble()` (`:142-198`) read only `usage.measured`, `input_tokens`, `output_tokens`, and
`advisor_calls`. `usage.backend` is never inspected anywhere in the file. The spec lists it under
"Edited" — that is unfounded; at most a selftest fixture label changes.

**`schemas/job_result.schema.json` needs only a description edit (CONFIRMED).** `usage.backend` is
`"type": "string"` with no enum (`:105-108`), so `"zai"` conforms today. Matches the spec.

**`compound-v-collect-results.py` needs only a help-string edit (CONFIRMED).** `--backend`
(`:1276-1278`) has no `choices=`; the enumeration lives only in the help text.

---

## 7. Design constraints for the spec

Non-negotiable. Derived from §1-§6.

**Worker script**

- Replicate, from the sources named in the §6 table: `id_is_safe` on both ids before any path is
  built; `$TMPDIR` absolute + `pwd -P` canonicalization + symlink-parent rejection + containment
  assertion + not-inside-repo assertion; idempotent stale-worktree removal; `--timeout-sec` pinned
  to a positive integer before use.
- **Capture `BASELINE_SHA` before `git worktree add`** and pass that SHA (never the literal `HEAD`)
  to `compound-v-scope-check.py --baseline`.
- **`ART="$WT.art"`, a sibling of the worktree.** Every log, the allow-file, the captured stdout,
  and the concatenated system-prompt file live there. Nothing the adapter writes may land inside
  `$WT`.
- **`set -f` around the colon-split of `--write-allowed`**, restoring with `set +f`.
- **Use the 11-argument `emit_job_result` with `--argjson usage`.** Pass the gate's `.changed` /
  `.violations` arrays through as JSON (`jq -c`), never a newline round-trip.
- **Validate `session_id` with codex's anchored bash `=~` UUID regex**; anything else becomes `""`.
- Exit-code contract: `exit 0` whenever a `job_result` was produced (including blocked/timeout/
  error); `die` → exit 2 only on a usage/environment fault, including a missing `$ZAI_API_KEY`.
- Status precedence: blocked > gate fault > exit 124 timeout > non-zero error > in-band error >
  success. Gate rc of 0 **or** 1 both count as "a verdict was produced".
- `failure_class` fail-closed to `other` on `""`/`null`/`none`; `retry_after` re-pinned to
  `^[0-9]+$` else `"0"`.
- Launch through `compound-v-run-with-timeout.py` with `</dev/null`, `--cwd "$WT"`, `--grace 3`, and
  **`--max-output-bytes`** (unbounded capture is a disk-fill vector the spec inherits from cursor).
- bash 3.2: no associative arrays, no `mapfile`, no `${var,,}`. Build the `env -i` allow-list as
  positional parameters via `set --`, and pass them explicitly into the run function.
- **Pin the argv order against `--allowedTools`'s variadic arity.** Either place the prompt behind a
  `--` terminator (verified accepted by the parser) or place `--allowedTools` so no positional
  follows it. State the chosen ordering in the script as a load-bearing comment, matching
  antigravity's `--print`-must-be-last note.
- **Concatenate the injected `CLAUDE.md`/`AGENTS.md` set into ONE file under `$ART`** and pass that
  single path to `--append-system-prompt-file`. The flag takes exactly one `<file>`; multi-file
  accumulation is unverified.
- Add a false-success guard: exit 0 with an unparseable/empty result object, or with zero files
  changed on a job whose `write_allowed` is non-empty, must not report `success`.

**Registries — every one of these, or the backend is half-wired**

- `compound-v-validate-manifest.py`: `VALID_BACKENDS` (`:519`), the `⇒ worktree` tuple (`:1817`),
  **and** the reviewer-prohibition tuple (`:1833`). Adding only the first lets
  `backend: zai, isolation: direct` validate. The `:1835-1840` message text must be updated to name
  `zai` while keeping the `WORKER-ONLY` token that the existing selftest asserts (`:4070-4081`).
- `compound-v-resolve-model.py`: `BACKENDS` (`:144`), a `_ZAI` map, and one line in `_stance_map`
  (`:123-130`) — which propagates to all four stances automatically.
- `compound-v-classify-failure.py`: `--backend` choices (`:334`) **and** an explicit
  `elif backend == "zai": rules = _ZAI_RULES` branch in `classify()` (`:244-250`). Without the
  branch the codex needle set applies silently.
- `compound-v-usage-extract.py`: an `_extract_zai` function **and** a dispatch branch in
  `extract_usage` (`:207-212`). Do **not** add `zai` to `UNMEASURED_BACKENDS`.
- `compound-v-failure-policy.py`: decide and record `FALLBACK["zai"]` (`:59`) — reroute to `claude`
  like every other external backend, or `None` with an explicit statement that a zai credit wall
  halts the run.
- `agents/parallel-dispatcher.md`: a `zai` row in the adapter table (`:48-53`) and a Step-1 bullet
  matching the cursor/antigravity pattern (`:103-104`). **Without this the dispatcher has no
  instruction telling it which script to run.**
- Docs whose enumerations go stale: `skills/backend-launcher/SKILL.md:22`, `:116-121`, `:125-128`;
  `skills/compound-v/execution-manifest.md:38`, `:57-59`, `:67-85`, `:103`, `:255`, `:266-272`;
  `skills/compound-v/routing-policy.md:65`, `:152`, `:184`, `:289-298`; `commands/v-init.md`
  (a detection section following the opencode pattern at `:169-189`); `commands/v-models.md:2`,
  `:17-19`, `:43-50`, `:343`; `schemas/job_result.schema.json:107`;
  `scripts/compound-v-collect-results.py:1277`.

**Usage measurement**

- `claude -p --output-format json` emits **one JSON object**, not JSONL.
  `compound-v-usage-extract.py`'s `_iter_json_lines` (`:61-82`) parses **per line**. Either
  `_extract_zai` must read the file whole with `json.load`, or the worker must normalize with
  `jq -c . > <file>` before invoking the extractor. Pick one and state it.
- Decide and state what `input_tokens` means for a cached run. Anthropic's usage object carries
  `cache_creation_input_tokens` and `cache_read_input_tokens` **separately** from `input_tokens`
  (`docs/superpowers/library-audit/2026-07-13-usage-and-advisor.md:15`). The spec's own §Context
  policy reports a run where 50 048 tokens were billed as cache reads — under an
  `input_tokens`+`output_tokens`-only sum, nearly all of that consumption is invisible. AC6's
  "real `input_tokens` / `output_tokens`" is satisfiable, but the number under-reports; say so, or
  fold the cache fields in explicitly.
- The `--events-log` argument name is a misnomer for a single result file. Reuse it for CLI
  consistency or add `--result-file`; either way, state it.

**Testing / CI**

- **`shellcheck` does NOT run on `scripts/*.sh`.** `.github/workflows/validate.yml:196-199` lints
  `hooks/*.sh` only. Remove it from the claimed gate list, or add a CI step.
- **No CI step runs any `scripts/test-*.sh`.** The selftest sweep (`:266-280`) iterates
  `scripts/*.py`. A `test-zai-worker-stub.sh` would never execute in CI. Either add an explicit CI
  step or AC8 is unsatisfiable.
- If the stub uses a `$COMPOUND_V_ZAI_STUB` env hook rather than a `PATH` binary, that variable must
  be added to the `env -i` forwarding allow-list or the child never sees it.
- Selftest fixture titles must avoid `review`, `reviewer`, `quality`, `integration`, `docs`, and
  `spec_review` (`compound-v-validate-manifest.py:509`) unless the fixture is *meant* to be
  classified as a reviewer.
- Existing fixtures reference `docs/superpowers/specs/2026-07-13-devin.md` etc. which do not exist
  in the repo, and `devin_ok == []` still passes (`:4052-4053`) — so `validate_text` does not
  require the audit paths to resolve. New fixtures may use the same convention.
- Add a `select_advisor` assertion that `zai` is never offered as an advisor, mirroring `:768-773`.
- Keep the credit-multiplier arithmetic out of `docs/**` in any phrasing matching the anti-ruflo
  patterns at `.github/workflows/validate.yml:169`; `skills/**` is not scanned by that gate.

---

## 8. File Touch Map

For Phase 2 partitioning. `SHARED RESOURCE` = a registry, schema, or contract another task will read
or where edit order matters.

| File | Change | Flag |
|---|---|---|
| `scripts/compound-v-run-zai-worker.sh` | NEW — the worker | exclusive |
| `skills/backend-launcher/adapter-zai.md` | NEW — the runbook | exclusive |
| `scripts/test-zai-worker-stub.sh` | NEW — stub-first test | exclusive |
| `scripts/compound-v-validate-manifest.py` | 3 registries (`:519`, `:1817`, `:1833`) + message text + selftest fixtures + assertions | **SHARED RESOURCE** — registry, 4 edit sites, 4202 lines |
| `scripts/compound-v-resolve-model.py` | `BACKENDS` (`:144`), `_ZAI` map, `_stance_map` (`:123-130`), selftest | **SHARED RESOURCE** — registry |
| `scripts/compound-v-classify-failure.py` | `--backend` choices (`:334`), `_ZAI_RULES`, `classify()` branch (`:244-250`), selftest | **SHARED RESOURCE** — registry |
| `scripts/compound-v-usage-extract.py` | `_extract_zai`, dispatch branch (`:207-212`), selftest | **SHARED RESOURCE** — registry |
| `scripts/compound-v-failure-policy.py` | `FALLBACK` (`:59`) | **SHARED RESOURCE** — registry |
| `schemas/job_result.schema.json` | `usage.backend` description (`:107`) | **SHARED RESOURCE** — schema read by collector + CI |
| `agents/parallel-dispatcher.md` | adapter-table row (`:48-53`), Step-1 bullet (`:103-104`) | **SHARED RESOURCE** — dispatch registry |
| `skills/backend-launcher/SKILL.md` | backend enum (`:22`), adapter table (`:116-121`), per-backend prose (`:125-128`) | **SHARED RESOURCE** — contract doc |
| `skills/compound-v/execution-manifest.md` | enum (`:38`), tier table (`:57-59`), models map both stance blocks (`:67-85`), invariant (`:103`), usage table (`:255`, `:266-272`) | **SHARED RESOURCE** — contract doc |
| `skills/compound-v/routing-policy.md` | `:65`, `:152`, `:184`, `:289-298` | **SHARED RESOURCE** |
| `commands/v-init.md` | new detection section; `backends` record | shared (doc) |
| `commands/v-models.md` | `:2`, `:17-19`, `:43-50`, `:343` | shared (doc) |
| `scripts/compound-v-collect-results.py` | `--backend` help string (`:1277`) — **help text only, no code change** | **SHARED RESOURCE** |
| `.github/workflows/validate.yml` | new step to run the stub test (see §7) | **SHARED RESOURCE** — CI config, order matters |
| `CHANGELOG.md` | new top release heading | **SHARED RESOURCE** — version lockstep |
| `.claude-plugin/plugin.json` | version bump from `2.17.0` | **SHARED RESOURCE** — version lockstep |
| `.claude-plugin/marketplace.json` | matching version bump | **SHARED RESOURCE** — version lockstep |
| `scripts/compound-v-usage-aggregate.py` | **NO CHANGE NEEDED** — enumerates no backend name | drop from the spec |

Partitioning note: the three version files (`plugin.json`, `marketplace.json`, `CHANGELOG.md`) are
one atomic unit — CI compares all three (`.github/workflows/validate.yml:43-81`). They cannot be
split across parallel jobs.

Second note: `compound-v-validate-manifest.py` carries **four** distinct edit sites plus fixtures.
If Phase 2 splits registry edits across jobs, this file must stay in exactly one job's
`write_allowed`.

---

## 9. Spec corrections required before implementation

Ranked by consequence.

1. **The failure-classification design is internally contradictory (§5.2, §5.3).** `--output-format
   json` produces one terminal result object, so no `api_retry` event exists; the classifier's enum
   path is gated on `backend == "claude"` so `--backend zai` never reaches it; and the classifier
   reads **stderr** while the JSON goes to **stdout**. Pick one: (a) drop the "reuse the claude JSON
   path" claim and ship `_ZAI_RULES` + a real `elif` branch over stderr only, or (b) switch the
   worker to `--output-format stream-json --verbose` (the advisor's proven shape,
   `compound-v-advisor-consult.sh:250-251`) and widen the enum gate to `backend in ("claude","zai")`
   — which also changes the summary and usage parse paths.
2. **Adding `zai` to the `--backend` choices without an explicit `classify()` branch silently
   applies the OpenAI needle set (§5.1).** The `else` at `:249-250` is `_CODEX_RULES`, not `other`.
   The spec's "fails closed to `other`" is not what the code would do. State both edits.
3. **`agents/parallel-dispatcher.md` is missing from Files-touched (§7).** Without a row in the
   adapter table at `:48-53`, nothing tells the dispatcher to invoke the new worker. `devin` and
   `opencode` are already missing there — do not reproduce the hole a third time.
4. **`compound-v-failure-policy.py:59` is missing from Files-touched (§5.4).** `FALLBACK.get("zai")`
   returns `None`, so a zai credit wall halts the run rather than rerouting. Separately, the spec's
   "retried, not rerouted" gives exactly one retry under `failure_class: other`
   (`PER_CLASS_MAX["other"] = 1`, `:53`) and then halts — say that plainly.
5. **The named structural template carries a latent bug and the wrong emit arity (§2, §3, §6).**
   `compound-v-run-cursor-worker.sh` lacks `set -f` around the `write_allowed` split, uses the
   10-argument `emit_job_result` with no `usage`, does not shape-validate `session_id`, and does not
   bound its capture. Restate the template as a per-block table (§6) rather than one file name.
6. **`--allowedTools` is variadic and will swallow the prompt (§4).** Pin the argv order. `--` is
   accepted by the parser and is the mitigation. This is the same failure mode antigravity and
   opencode each already hit.
7. **`--append-system-prompt-file` takes exactly ONE `<file>` (§4).** The spec plans to pass three
   or more. Specify concatenation into a single `$ART` file.
8. **`usage` extraction reads the file per line; `--output-format json` is one object (§7).**
   Specify either whole-file `json.load` in `_extract_zai` or a `jq -c` normalization step in the
   worker.
9. **AC6's "real `input_tokens` / `output_tokens`" under-reports a cached run (§7).** By the spec's
   own measurement, 50 048 tokens of one run were cache reads, which are separate fields
   (`library-audit/2026-07-13-usage-and-advisor.md:15`). Either fold the cache fields in or state
   the under-report explicitly.
10. **The claimed CI gates are wrong on two counts (§7).** `shellcheck` runs only on `hooks/*.sh`
    (`.github/workflows/validate.yml:196-199`), and no CI step runs any `scripts/test-*.sh`
    (`:266-280` is `scripts/*.py`). As written, AC8 cannot be satisfied.
11. **`compound-v-usage-aggregate.py` is listed as Edited but enumerates no backend name (§6).**
    Remove it, or narrow the claim to a selftest fixture label.
12. **Adding `zai` to `VALID_BACKENDS` makes `advisor_backend: zai` a *valid* manifest value that
    dies at dispatch (§5.5).** `compound-v-validate-manifest.py:664` validates it against
    `VALID_BACKENDS`; `compound-v-advisor-consult.sh:262-266` then refuses it. State whether a zai
    job may carry an advisor block, and add the missing `select_advisor` assertion.
13. **"`ZAI_API_KEY` named in `.claude/compound-v.json`" has no reader (§2).**
    `compound-v-project-config.py` declares only `models`, `pre_eval`, and `brainstorm`
    (`:102-110`), and `commands/v-init.md:507` forbids adding capability keys there. Restate as:
    the worker reads `$ZAI_API_KEY` from its own environment; a missing value is an exit-2
    environment fault.
14. **The `env -i` allow-list is narrower than the only precedent (§2).** opencode forwards
    `LC_ALL` and `TERM` as well (`:95`), and CI runs Python selftests as `LANG=C`. Justify the
    narrowing or match it.
15. **Baseline-SHA ordering and `$ART` placement are unstated (§2).** Both are the subject of
    recorded CRITICAL fixes (`CHANGELOG.md:482`; `compound-v-run-opencode-worker.sh:320-330`). Name
    them in the spec so the implementer cannot omit them.
16. **`--bare` does not disable skills (§4).** The CLI's own help says "Skills still resolve via
    `/skill-name`". The spec's context accounting does not mention this surface.
17. **Latent, no live path today: an Anthropic-alias model override would mislabel a GLM ballot's
    family.** `compound-v-epic-arbiter.py:548-551` matches `claude`/`opus`/`sonnet` by substring, and
    the spec's own probe found z.ai accepts `claude-opus-4-8`. A config override to that name would
    resolve to family `Claude`, not `unknown`. The arbiter polls only codex (`:1642`) and agy
    (`:1673`), so this is unreachable now — record it alongside the existing `glm`-is-absent note.
