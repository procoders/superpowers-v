# Implementer as a role (maxTurns + Opus 5 conciseness snippets), effort policy, /v:init env offer; close the seventh pass's two items

Compound V run `2026-09-02-v3.4-native-first-r11`, job `worker-concise`.

Two sources drive this job. (A) Anthropic's own guide "Prompting Claude Opus 5"
(platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5) and
"Effort": effort controls thinking, NOT visible length — prompt for length explicitly; explicit
verification instructions CAUSE over-verification on Opus 5 and must be removed; scope, narration
cadence and deliverable length each have an official snippet. (B) the binary (2.1.238): workflow
agent() opts are {label, phase, schema, model, effort, isolation, agentType} + disallowedTools +
bashCommandClamp — NO maxTurns; agent DEFINITION files support `maxTurns:` (positive integer). So a
turn cap is native only through a role. Plus docs/superpowers/dogfood/…-review-7.md items 1–2.

1. agents/implementer.md — new role every Claude implementer arrives with. Frontmatter: name,
   description (one line: the Compound V implementer — writes inside a lane, the Gate measures),
   model: opus (say in the body that the tier's opts.model overrides it at dispatch), maxTurns: 60.
   Body: the three official snippets VERBATIM — scope: "Deliver what was asked, at the scope
   intended. Make routine judgment calls yourself, and check in only when different readings of the
   request would lead to materially different work. If the request seems mistaken or a better
   approach exists, say so in a sentence and continue with the task as asked rather than quietly
   narrowing, widening, or transforming it. Finish the whole task, and stop short of actions that
   are clearly beyond what was asked." — cadence: "Before your first tool call, say in one sentence
   what you're about to do. While working, give a brief update only when you find something
   important or change direction. When you finish, lead with the outcome: your first sentence
   should answer \"what happened\" or \"what did you find,\" with supporting detail after it for
   readers who want it." — deliverables: "Match the length of written documents to what the task
   needs: cover the substance, but do not pad with filler sections, redundant summaries, or
   boilerplate." Then: "The Gate runs the test floor after you finish. Run a listed acceptance
   command at most once; add no verification steps, subagents or re-checks beyond the acceptance
   list." Then the hygiene lines (python -B; register-lane with a literal --cwd from `pwd`; the
   clamp refuses substitution) and "You have at most 60 turns; plan to finish inside them."
   scripts/lint-frontmatter.py must accept it (model: opus; no Haiku).
2. scripts/compound-v-emit-workflow.py — AGENT_TYPE_BY_JOB_TYPE: every claude job whose type is
   not `review` → `implementer` (review stays spec-reviewer); the inline-definition fallback
   embeds the body so the guidance survives an unregistered plugin (log that the cap is lost).
   render_worker_prompt: remove every "verify"/"re-check"/"report per item" imperative the
   template adds itself (keep lanes, acceptance as facts, the external-backend block); add one
   line "Turn cap: N (manifest max_turns; default light 30 / standard 50 / deep 80)". The
   validator (compound-v-validate-manifest.py is NOT in your lane — do not touch it): if it rejects
   an unknown `max_turns` key, read the cap from the job dict in the emitter only and note in the
   spec amendment that the validator must learn the key next; otherwise emit it. Selftests as in
   acceptance 2.
3. agents/spec-reviewer.md: maxTurns: 80; add the one-pass sentence from acceptance 3.
4. Effort policy — routing-policy.md (a short section "Effort by job kind"), execution-manifest.md
   (the effort field's description), v-orchestrate.md (fix jobs minted from a review carry
   effort: medium). v-init.md: offer CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT=0 with the source note.
5. Seventh pass, item 1: make the PATH case in tests/test-lane-guard.sh discriminate (a broken
   python3 first on PATH must be PROBED and skipped — reorder the candidates or the test so the
   pre-change hook reds), and make the hook log the interpreter it chose on every path, not only
   the fallback one. Item 2: re-measure the unresolved path for BOTH populations (a machine whose
   first candidate imports yaml: one probe; a machine where none or only the second does: three)
   and publish both numbers with method+date in README.md, AGENTS.md and the hook header; move
   the `_cv_can_run` probe out of the yaml loop so the healthy machine pays exactly one probe.
6. Records: CHANGELOG, spec amendment, native-mechanisms.md row (maxTurns — native, used).
Run Python with -B; register your lane with a literal --cwd. Report per item: file, change,
command, exit code. Do not add verification beyond the acceptance commands.

## Write-allowed (your lane — anything else is a scope violation)

- `agents/implementer.md`
- `agents/spec-reviewer.md`
- `scripts/compound-v-emit-workflow.py`
- `scripts/lint-frontmatter.py`
- `skills/compound-v/routing-policy.md`
- `skills/compound-v/execution-manifest.md`
- `commands/v-orchestrate.md`
- `commands/v-init.md`
- `hooks/lane-guard.sh`
- `tests/test-lane-guard.sh`
- `README.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md`
- `docs/superpowers/architecture/native-mechanisms.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-7.md`
- `agents/code-archaeologist.md`
- `agents/domain-expert.md`

## Acceptance (your definition of done)

- agents/implementer.md exists with frontmatter name: implementer, model: opus, maxTurns: 60, and a body that carries VERBATIM the three Opus 5 snippets (scope: 'Deliver what was asked, at the scope intended…'; cadence: 'Before your first tool call, say in one sentence…'; deliverables: 'Match the length of written documents to what the task needs…'), the sentence that the Gate runs the floor and a listed acceptance command is run at most once with no added verification, the -B / literal --cwd hygiene, and its own cap; /usr/bin/python3 -B scripts/lint-frontmatter.py . is clean.
- scripts/compound-v-emit-workflow.py spawns every claude job whose type is not `review` as agentType <plugin>:implementer with the inline-definition fallback carrying the body (cap lost on fallback, logged); render_worker_prompt adds no 'verify / re-check / report per item' imperative and prints the job's turn cap (manifest max_turns, default light 30 / standard 50 / deep 80); the validator accepts max_turns; selftests pin: agentType implementer for bounded_crud and not for review, no 'verify' imperative in the rendered prompt, the cap line, the embedded body.
- agents/spec-reviewer.md has maxTurns: 80 and the sentence 'Report everything you find in this one pass, ranked; do not withhold low-severity items for a later pass.'
- routing-policy.md and execution-manifest.md state the effort policy by job kind (new code/design deep·high; review-fix jobs medium; reviewers high on the first pass, medium on re-passes; transports low) and v-orchestrate.md says a fix job minted from a review carries effort: medium; v-init.md offers CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT=0 for the user's settings env with the honest source note (community claim, no measurement).
- Seventh pass item 1: tests/test-lane-guard.sh's PATH case can fail — with the pre-change candidate order it reds — and the hook logs which interpreter it used on that path; item 2: README.md, AGENTS.md and the hook header state the measured cost for BOTH populations (one probe on a machine whose first candidate imports yaml; three where none or the second does), with the numbers you measure, and the _cv_can_run probe inside the loop is moved after the yaml loop so a healthy machine pays one probe.
- CHANGELOG 3.4.0 gains '### Changed — implementers arrive as a role with a turn cap and the official Opus 5 conciseness guidance'; the spec gains 'After the seventh review pass (2026-09-03)'; native-mechanisms.md gains a row for maxTurns on agent definitions (native, used from 3.4.0); bash tests/test-lane-guard.sh exits 0; /usr/bin/python3 -B scripts/compound-v-emit-workflow.py --selftest is green.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
