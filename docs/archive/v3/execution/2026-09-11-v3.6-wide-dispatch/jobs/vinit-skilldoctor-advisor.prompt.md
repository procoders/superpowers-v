# Task J-VINIT — /v:init Step 1f (native /skill-doctor) and Step 4e (advisorModel); this repo advises with Fable (F6, F7)

Compound V run `2026-09-11-v3.6-wide-dispatch`, job `vinit-skilldoctor-advisor`.

Implement Task J-VINIT of docs/superpowers/plans/2026-09-11-v3.6-wide-dispatch.md (spec F6 and F7 /v:init parts). Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind; the library audit confirms the version floors and flag names against the official docs — use its figures, not memory). Match the surrounding style of commands/v-init.md: 1d-bis is the model for a presence probe, 4d for an offered setting. The nested claude -p is a read-only report with stdin closed and no permission flags — say that in the step. Touch only your lane. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `commands/v-init.md`
- `.claude/settings.json`

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

- commands/v-init.md: ### 1f. Skill hygiene (native /skill-doctor) after 1e; ### 4e. One optional project setting — advisorModel after 4d; one report line in Step 5
- the exact skill-doctor command: python3 scripts/compound-v-run-with-timeout.py --timeout 180 -- claude -p '/skill-doctor' --output-format text < /dev/null
- .claude/settings.json: {"worktree": {"baseRef": "head"}, "advisorModel": "fable"}

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- Step 1f: version gate claude --version >= 2.1.261 (the changelog version; skills.md says 2.1.252 — the step cites the stricter one); the command above; parse rows whose first column begins with superpowers-v:; print those rows (context, 7d tokens, uses, last used) and the sum of the context column over every loaded skill; state the three limits (per-machine session history, not a repo property; hook- and description-fired phases are not skill invocations, so 0× beside v-dispatch is not unused; unavailable over Remote Control and when feature-flag fetching is off); the rule report only — never disable, never write. Step 4e in the 4d style: offer, exact JSONC with "advisorModel": "fable" and the opus alternative, why (a stronger model judges at decision points inside every job; subagents inherit it), the pairing rule (an advisor must be at least as capable as the main model; a Fable main accepts only Fable 5.1), the cost (each call re-reads the whole transcript, uncached; Fable bills to usage credits on some plans after the /model fable consent), DISABLE_TELEMETRY turns it off, CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1 disables it, merge-preserve every other key, never write without a yes. .claude/settings.json carries both keys. lint-frontmatter green; the emitter selftest still green.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
