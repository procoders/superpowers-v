# Task J-LANEGUARD — the unresolved record names the acting run and the bootstrap (#19 E)

Compound V run `2026-09-11-v3.6-wide-dispatch`, job `laneguard-unresolved`.

Implement Task J-LANEGUARD of docs/superpowers/plans/2026-09-11-v3.6-wide-dispatch.md (spec F4). Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind; the archaeology audit names the helper functions in tests/test-lane-guard.sh to copy). Tests first. In hooks/lane-guard.sh: recognise the bootstrap with the existing quote-aware tokenizer (match the register-lane subcommand of the emitter, never a substring of an unrelated path); for any other unresolved isolated-agent call pick ONE run — the one named by --run-dir in the command when present, else the newest live lane map (map_files already sorts by mtime) — and record there with candidate_runs listing every live map; replace the why text. The hook budget matters: no new subprocess on the common path. Touch only your lane. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `hooks/lane-guard.sh`
- `tests/test-lane-guard.sh`

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

- lane-guard-unresolved.jsonl record fields: candidate_runs [lane-map paths live at that moment]; why: isolated agent <cwd> did not resolve to a job in this run's lane map at the time of this <tool> call; the write was allowed and not lane-checked
- log line ALLOW (register-lane bootstrap) for a Bash command containing compound-v-emit-workflow.py register-lane; no record is written for it

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The bootstrap recogniser states its own limit where it is implemented: it keys on the TEXT of the command being run, which is a weaker subject than a process identity, so any call whose command merely contains the register-lane spelling is suppressed too. The domain audit MUST on this point binds — the comment says so plainly, and the suppression covers only the RECORD, never a lane decision: a write is still matched against the lane exactly as before.
- tests/test-lane-guard.sh rows pass: (a) a Bash payload whose command is <py> -B <emitter> register-lane --run-dir <run> --job-id j --isolation worktree --cwd <wt> under a live lane map exits 0, writes no lane-guard-unresolved.jsonl, and the log contains register-lane bootstrap; (b) a Write payload from an unregistered isolated cwd with two live runs produces exactly one record, in the newer run directory, with candidate_runs of length 2; (c) no record contains the text register-lane missing. shellcheck hooks/*.sh clean; the whole test file green; the hook still allows and denies exactly as before on every other row.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
