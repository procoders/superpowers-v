# Task J-SECOND — the second-opinion ladder: Codex, else advisor-assisted, else skip (F7)

Compound V run `2026-09-11-v3.6-wide-dispatch`, job `second-opinion-ladder`.

Implement Task J-SECOND of docs/superpowers/plans/2026-09-11-v3.6-wide-dispatch.md (spec F7, second opinion without Codex). Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind; the domain audit recommends the disclosure wording — if it differs from the line above, use the audit's and say so). The downstream complaint this closes: a project with only Claude Code got no spec/diff review at all; now it gets an honestly labelled same-family second look. Never present rung 2 as cross-model. Touch only your lane and only the named regions of the shared files. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `commands/v-review-plan.md`
- `skills/compound-v/cross-model-review.md`
- `commands/v-dispatch.md`
- `skills/compound-v/phase-3-parallel-opus-dispatch.md`

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

- receipt reviewer_backend claude-advisor and WARN SECOND_OPINION_SAME_FAMILY from validate-keys-advisories

produces (what later jobs will call):

- the ladder text (1 Codex CLI present → as today; 2 no Codex, advisor configured → advisor-assisted second look; 3 neither → skip with the notice) in cross-model-review.md, v-review-plan.md step 3, v-dispatch.md step 9, phase-3
- the disclosure line, verbatim in every rendering: Second look by the same model family (Claude + advisor) — no decorrelation; not a cross-model review.
- rung 2 writes cross_model: false on the receipt — the honesty is a field a machine can read, not only a sentence a human may skip

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- skills/compound-v/cross-model-review.md has a section The ladder with the three rungs, the advisor-assisted procedure (one read-only Opus subagent through the Agent tool, the same prompt and plan-review.schema.json output, told to consult the advisor before its verdict; the receipt wrapped with reviewer_backend claude-advisor), the disclosure line, and the SCOPED+ rule. The domain audit MUST on this point binds: rung 2 never silently becomes the equivalent of a cross-model review — the wrapped receipt carries cross_model false, the WARN is printed, and the prose says that a project able to install Codex should, because a Claude review of Claude code shares its blind spots. Rung 3 still refuses. commands/v-review-plan.md step 3 is the ladder; commands/v-dispatch.md step 9 references it and names the receipt value; the phase-3 cross-model paragraph is updated. Only those regions of v-dispatch.md and phase-3 change. lint-frontmatter green; every relative link resolves.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
