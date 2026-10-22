# Task J-SCOPE — --preexisting honoured in worktree mode; provisioning in the four worker scripts (#19 A/B, gate half)

Compound V run `2026-09-11-v3.6-wide-dispatch`, job `scope-workers-provision`.

Implement Task J-SCOPE of docs/superpowers/plans/2026-09-11-v3.6-wide-dispatch.md (spec F1, gate half). Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind). Tests first: the scope-check selftest row, then the worker row in tests/test-worker-path-transport.sh (read that file first to reuse its stub-worker fixture; if no codex stub exists, build the smallest one: a `codex` shell script on PATH that writes one in-lane file into --cd and exits 0). Keep the subtraction code in changed_files unchanged if it already applies in both modes; make the docstring and --help say worktree mode honours the post-provisioning snapshot. In the workers the logic is byte-identical across all four: parse flags; after worktree add, if the command is non-empty run python3 "$SCRIPT_DIR/compound-v-run-with-timeout.py" --timeout "$PROVISION_TIMEOUT" --cwd "$WT" -- /bin/bash -c "$PROVISION_COMMAND"; on rc != 0 emit the error job_result and exit without launching; on success snapshot with git -C "$WT" ls-files --others --exclude-standard -z and git -C "$WT" ls-files --others --ignored --exclude-standard -z -- . into $ART/preexisting.txt (NUL-split, one path per line) and add --preexisting to the scope-check call. Never add an exemption to the scope gate. Touch only your lane. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-scope-check.py`
- `scripts/compound-v-run-codex-worker.sh`
- `scripts/compound-v-run-cursor-worker.sh`
- `scripts/compound-v-run-antigravity-worker.sh`
- `scripts/compound-v-run-opencode-worker.sh`
- `tests/test-worker-path-transport.sh`

## Global constraints (binding on every job)

Project-wide, and binding on EVERY job in this run including yours.
Copied verbatim from the plan — do not reinterpret, relax or widen
them.

- Python 3.9 syntax, stdlib only; every script run as /usr/bin/python3 -B; bash passes shellcheck
- Never Haiku; no agent frontmatter names Fable; Fable enters only through advisorModel
- Never relax the scope gate; no new entry in RUN_DIR_EXEMPT_BY_NAME; provisioning is subtracted only through the existing --preexisting snapshot path
- No fabricated metrics; every behavioural change ships a selftest row that fails when the change is reverted
- Docs: plain words, one idea per paragraph, no line over 200 characters outside code/tables, every claim true of the code in HEAD
- Lane discipline: touch only your write_allowed; register-lane first, with a literal --cwd
- Field and flag names are fixed by the plan's Interfaces: provision_command, provision_timeout_s, --provision-command, --provision-timeout-sec, preexisting.txt, verdict_disagreement, candidate_runs, MEMORY_LANE_UNNAMESPACED, SECOND_OPINION_SAME_FAMILY, claude-advisor, usage.advisor_calls
- Not in any job: CHANGELOG entry, version bump, release, generated architecture docs

## Interfaces (your only view of the neighbours)

You see only your own job. This block is the ONLY view you get of the
names and signatures neighbouring jobs rely on — implement exactly
these, and do not rename or re-shape them.

produces (what later jobs will call):

- every scripts/compound-v-run-*-worker.sh accepts --provision-command <string> (optional) and --provision-timeout-sec <int> (default 600), parsed in the same block as --write-allowed
- on success the worker writes $ART/preexisting.txt (one repo-relative path per line: untracked ∪ ignored after provisioning) and passes --preexisting "$ART/preexisting.txt" to compound-v-scope-check.py
- on failure the worker emits a status: error job_result whose summary is 'provision failed (rc=N): <command>' and launches nothing
- compound-v-scope-check.py --worktree honours --preexisting (documented in its docstring and --help)

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- scope-check selftest rows pass: a worktree repo with .gitignore node_modules/ and node_modules/x/a present is pass with an empty changed set when --preexisting lists the path, and a violation when it does not. All four worker scripts parse the two flags, run the command through /bin/bash -c under compound-v-run-with-timeout.py after git worktree add, snapshot, and pass --preexisting; shellcheck scripts/compound-v-*.sh clean; tests/test-worker-path-transport.sh gains a row that drives the codex worker with --provision-command against a stub codex on PATH and asserts the job_result is not blocked and lists no node_modules path; the whole file green.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
