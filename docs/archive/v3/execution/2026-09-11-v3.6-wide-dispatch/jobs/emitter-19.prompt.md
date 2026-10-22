# Task E — the emitter half of #19: finalizer force-adds run-directory paths (C), Record states a verdict disagreement (D), worktree provisioning in register-lane and gate-receipt plus the external launch argv (A/B)

Compound V run `2026-09-11-v3.6-wide-dispatch`, job `emitter-19`.

Implement Task E1 and Task E2 of docs/superpowers/plans/2026-09-11-v3.6-wide-dispatch.md as ONE job (spec F1 emitter half, F2, F3) — the validator forbids two jobs on one file, so both land here, in this order: C (smallest), then D, then A/B; commit after each so a turn-budget exit keeps what is complete. READ THE ARCHAEOLOGY AUDIT FIRST (docs/superpowers/archaeology/2026-09-11-v3-6-wide-dispatch.md): it carries exact line numbers and it CORRECTS this plan in three places — the AC-3 staging failure is at the finalizer's own unguarded git add -A, not only at _stage_paths; the provisioning gates are hard-OFF branches in cmd_register_lane and cmd_gate_receipt that skip worktree jobs entirely; and GATE_SCHEMA has no manifest_digest, so the D conditions must be adjusted to what is checkable. Read the domain audit too (docs/superpowers/expert/2026-09-11-v3-6-wide-dispatch.md): its MUSTs cover the register-lane prompt timeout and the missing-digest hole. Where an audit contradicts the plan, the audit wins and you say so in your summary. The wave-1 jobs are merged in HEAD: read git log -p since this run's baseline for the worker flags before wiring them. scripts/compound-v-emit-workflow.py is 8,000+ lines: grep for the named symbols and the selftest rows near "--expect-verdict"; read only those ranges, never the whole file. Tests first for every part: write the rows, run the selftest, see them fail, implement. D: the receipt file is the verdict when it parses, carries this job_id, and has verdict in pass|blocked|error; the workflow's --expect-verdict is a transport echo; on any difference build verdict_disagreement, attach it to the ack and to the job's state.json entry, and append " - " plus the message to the result summary; the diff_digest comparison stays an error with the same neutral wording and fields, and is checked BEFORE the verdict one so a forgery signal is never masked; the code comment records the two known ways the echo diverges (a Gate agent whose Bash call timed out before the script finished; an agent that summarised instead of returning verbatim). A/B: provisioning runs through ["/bin/bash", "-c", cmd] with cwd = the registered worktree under compound-v-run-with-timeout.py --timeout <provision_timeout_s>, then the existing direct-mode snapshot code runs rooted at the worktree; a failure falls into the stricter gate (no snapshot), never a looser one; gate-receipt reads the snapshot candidate in both modes; the two flags reach the external launch argv only. Never add an exemption to the scope gate. Touch only scripts/compound-v-emit-workflow.py. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: scope-workers-provision, validate-keys-advisories.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-emit-workflow.py`

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

consumes (what earlier jobs give you):

- worker flags --provision-command <string> and --provision-timeout-sec <int> on all four scripts/compound-v-run-*-worker.sh (merged in wave 1)
- compound-v-scope-check.py --worktree honours --preexisting (merged in wave 1)
- manifest keys provision_command (string) and provision_timeout_s (int, default 600) accepted by the validator (merged in wave 1)

produces (what later jobs will call):

- verdict_disagreement: {field: 'verdict'|'diff_digest', receipt: str, workflow: str, receipt_path: str} on the Record ack and on state.json jobs.<id>.verdict_disagreement
- message text: gate verdict disagreement: receipt <path> says <r>, the workflow held <w>; this comparison establishes no cause
- _stage_paths(worktree, paths) stages a path under docs/superpowers/execution/<run-id>/ with git add -A -f
- register-lane ack keys provision: {command, rc, seconds} or provision_error: <text>; preexisting/<id>.txt written for a worktree job when a command ran
- gate-receipt reads the verified preexisting subset in both modes
- the external launch argv carries --provision-command and --provision-timeout-sec when the manifest sets them, and neither flag otherwise

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- C: the wave finalizer commits a wave whose run-directory artefacts sit under a gitignored parent. A selftest row builds a temp repo whose .gitignore is docs/, runs the REAL staging path the finalizer uses (the archaeology audit names it: an unguarded git add -A near cmd_finalize_wave, not only _stage_paths), and asserts the artefact is staged. A fix that only touches _stage_paths and passes is REJECTED by this criterion: name in your summary which call sites you changed and why each one needed it.
- D: selftest rows show record with a receipt verdict pass and --expect-verdict blocked returning rc 0, ack recorded true, result status success, ack.verdict_disagreement.field == verdict, and a summary naming both values and never the word rewritten; receipt blocked + expect pass records blocked with the disagreement; a receipt whose job_id differs records error; an --expect-diff-digest mismatch records error with field diff_digest; a receipt that mismatches BOTH surfaces the diff_digest (forgery) field, not the verdict one; agreement yields no verdict_disagreement key; the words "rewritten between Gate and Record" no longer appear in the file.
- D-binding: the receipt-wins rule rests only on checks the code can actually perform. The archaeology audit found GATE_SCHEMA carries no manifest_digest and nothing sets one, so either gate-receipt starts writing it and record checks it, or the manifest_digest condition is dropped and the code comment says why. A condition that cannot be evaluated must not appear in the comment as though it were enforced. Also close the hole the domain audit found: the workflow appends --expect-diff-digest only when it holds a digest, so a degraded transport sends no digest at all — record must not treat a missing digest as agreement.
- A/B: selftest rows show (a) a manifest with provision_command "mkdir -p node_modules/x && touch node_modules/x/a" and a worktree job: register-lane --isolation worktree --cwd <wt> creates node_modules/x/a in the worktree, writes preexisting/<id>.txt listing it, ack.provision.rc == 0, and gate-receipt --mode worktree after one in-lane write returns pass with node_modules absent from changed; (b) the same manifest without provision_command and a job that creates node_modules/x/a itself is blocked with the violation; (c) provision_command "exit 3" yields ack.provision_error naming rc 3, no snapshot, and the gate still runs; (d) an external codex job's launch argv contains both flags when the manifest sets them and neither when it does not; direct-mode jobs never run the command.
- A/B-ceiling: provisioning is reachable in a real run. The domain audit found that register-lane runs as an ordinary agent Bash call whose emitted prompt sets no timeout, so the harness default of 120 s would kill an npm ci long before provision_timeout_s of 600 and resurface the exact node_modules violations this feature exists to remove. The emitted register-lane prompt carries an explicit Bash timeout derived from provision_timeout_s (the Gate prompt already does this — copy that shape), and a selftest asserts the emitted script contains it.
- Emitter selftest, tests/test-engine-c-contract.sh and tests/test-worker-path-transport.sh green.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
