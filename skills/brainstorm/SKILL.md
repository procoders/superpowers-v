---
name: brainstorm
description: Use before building or changing anything non-trivial in a project set up for Compound V (a feature, page, flow, integration or app). Asks one question at a time about the product, data lifecycle, jurisdiction, forms, operations and edge cases. Writes the spec, starts the run record, checks the spec with a fresh builder, gets approval, then hands off to compound-v:build. Typos, copy and config values skip this and go straight to compound-v:verify.
---

# Brainstorm

You build well, and you build what you believe the user wants. That belief is thinner than it feels. Here you find out what they actually want, and why, before any code. In our benchmark the answers collected at this stage were the cheapest depth a build got.

**Commands.** Run each command as one plain command line with literal values (the run id, real paths): no shell variables you set yourself, no `;` or `&&` chains, no `$?`, and no pipes or redirects (`|`, `>`, `2>&1`): the one exception is the `<<'REQUEST'` heredoc that hands `run start` its request. The sandbox's auto-allow refuses compound commands, and `sandbox.excludedCommands` only matches a bare call.

## 0. Size it first

- **Everything is in the request** and it is a typo, copy, wording or config value: do not brainstorm. Make the change, then run `compound-v:verify` (light run).
- **Anything else** (a feature, a page, a form, an integration, a new app): continue here.

If the work grows mid-conversation, say so and keep going here.

## 1. Before the first question

When `docs/compound-v/` holds specs, plans, pre-flights or runs, dispatch the `compound-v:v-memory` agent with the request's key nouns. Show its hits to the user as evidence, in one to three lines with paths. They are leads, not decisions. When the folder is empty, skip this step.

## 2. The first message

Your first message has exactly two things:

1. One line saying that if they would rather skip the questions, you will make the calls yourself and say what you chose.
2. One open question that gets them describing a real moment ("Walk me through the last time a customer did this with you today, from first contact to done.").

**Only an explicit request to skip the questions ends them** ("skip the questions", "just build it"). "Your call", "you decide" or "keep it simple" settles **that one question**: propose something concrete, mark it as your call, and ask the next most important question. The depth question (§4) is still asked for anything bigger than a small change.

When they skip: state the significant how-it-gets-made choices in one line, write the spec with every decision marked as your call, and continue from §5. Skipping removes the questions. It never removes the builder's research, the plan or verification.

## 3. The conversation: one question per message

- **Every message ends with exactly one question**: a single sentence, with no list of example answers hanging off it. The session may be headless, with the owner answering one turn at a time, so never ask two things at once and never wait on anything they cannot do from chat. Do not ask them to open a browser tab, look at a mockup, click or install anything.
- Use the user's own vocabulary and no process jargon. When they say "you decide" or "your call", propose something concrete, mark it as your call, and move to the next question; it settles that question, not the conversation.
- A guess they can correct ("I'm guessing orders taken by phone matter as much as online ones?") often beats an open question.
- **Play back** as you go. When one part is clear, describe it back in 150–250 words, mark your guesses as guesses, and end with "What's wrong or missing here?" That is the message's one question.

## 4. Ground to cover: `territory.md`

Read `territory.md` in this directory before your second question. Cover its areas as ground, not as a script. Ask the question that would change the build most and that the conversation has not reached yet:

product and users · data lifecycle (create / change / retire with history / delete; what the operator changes without a developer) · jurisdiction, data and deployment · security and every form · operations · **edge cases**, raised on purpose · how it gets made.

**Ask how deep.** Once the first answers show this is bigger than a small change, ask in one message, with one line per option, **how deep** they want to go:

| Depth | Questions | Adds |
|---|---|---|
| quick | only the areas that change what gets built | nothing beyond the tier minimum |
| standard (default) | every territory area | nothing beyond the builder's own research |
| thorough | every area, plus an edge-case walk per entity | an offered Codex plan review, the native `/security-review` suggested at the end |

When `.claude/compound-v.json` says `"stance": "cost-aware"`, suggest quick. Depth adds questions and checks. It never removes the full tier's minimum: tests, executable review, real-world check and scope check.

**Parallel work.** When the depth is `thorough`, or the work is large with clearly independent parts, ask one short question: "May I build independent parts in parallel (Claude Code's Workflow tool, several agents at once)?" Record the answer in the spec as a `Parallel:` line, `yes (owner)` or `no (owner)`. Not asked means `Parallel: no`.

Stop asking when every area is covered (answered, marked as your call, or n.a. with a reason).

**What "your call" and "keep it simple" mean.** Choose what a real operator needs day to day, built simply: fewer
moving parts, not fewer capabilities. A call never removes something the plan's checklists require
(`${CLAUDE_PLUGIN_ROOT}/skills/plan/checklists.md`: the operator changes business data (catalogue, prices, schedules,
contact details) without a developer; sessions are revoked server-side; erasure reaches every copy). "Keep it simple"
may decide *how* (a small admin form instead of a CMS) but not *whether*. In our benchmark, builds whose calls
chose "edit a seed file and restart" for routine business changes lost a fifth of their product score.
A call also never narrows or reinterprets a rule the request states; it only adds detail where the request is silent.
"Up to N before" includes exactly N, and "same rules as X" keeps every rule X has (the boundary reading is R2 in the
plan's `checklists.md`). When you think a stated rule should change, ask the owner once; never decide it as your call.

## 5. Write the spec

Write `docs/compound-v/specs/YYYY-MM-DD-<topic>.md`, so that a talented builder who cannot reach the owner could plan from it:

- **Request**: the user's original words, verbatim.
- Intent and the why; users; goals, non-goals and anti-goals.
- **Decided by the owner**, as they decided it. **My calls**, each marked.
- Data lifecycle per entity; jurisdiction, data and deployment; security and every form; operations; edge cases.
- Out of scope (agreed), and what is left to the builder.
- `Parallel: yes (owner)`, `Parallel: no (owner)`, or `Parallel: no` when it was not asked.

Then start the run. Pass the user's **original request** on stdin, never a temp file inside the repo (an untracked file there is a scope violation):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" run start --tier full \
  --spec docs/compound-v/specs/<file>.md --request-file - <<'REQUEST'
<the user's original request, verbatim>
REQUEST
```

It prints the run record as JSON. Keep its `id` and pass `--id <id>` on every later `compound-v.py` call in this run, in every skill. The record is written by the CLI only, so never edit `docs/compound-v/runs/` by hand.

## 6. Builder check, then approval

Before asking for approval, dispatch one fresh subagent with `builder-check-prompt.md` (this directory). Tell the user a reviewer will read the spec first and that you may come back once with a few questions. Sort the answers as that file says, and bring only the owner's questions, numbered, in one message.

Then ask for approval: give the spec path and the short list of your calls, and ask "Does this capture what you want, or what should change?"

<HARD-GATE>
No code, scaffolding, dependency installs or project creation until the user approves the spec. Reading and exploring are fine. An answer that changes the spec means updating the spec and asking again.
</HARD-GATE>

## 7. Hand off to the build

After approval: `compound-v.py run stage --id <id> --to plan`, then invoke `compound-v:build` and no other skill. Dispatch no pre-flight agents: the one `compound-v:builder` does the domain research, the code reading and the library check itself, in its own context, before it writes the plan. In our benchmark, separate pre-flight agents plus a plan written here and a separate builder cost more than the light flow and did not beat it (see V4-RESULTS in the benchmark kit; spec §4.2–4.4).

## Red flags

| Thought | Reality |
|---|---|
| "I'll list options to save them effort" | Options steer. Get them describing first. |
| "Two quick questions in one message is fine" | One question per message. The builder-check round is the only exception. |
| "They said 'sounds good'" | Approval covers what you showed them. A spec they have not seen is not approved. |
| "Edge cases will come up in review" | They are cheapest now. Ask about them on purpose. |
| "Domain research can be skipped for this one" | The builder's domain research is where the production depth comes from. It always runs. |

Adapted in part from Superpowers `brainstorming` (MIT, Jesse Vincent).
