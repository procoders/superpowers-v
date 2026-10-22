# Builder check prompt

Dispatch one fresh `general-purpose` subagent with this prompt once the spec is written, before you ask for approval. Fill in the domain and the path. Do not give it the conversation: it must read the spec the way a builder will.

```
You are a talented [DOMAIN, e.g. "web developer building for small businesses"].
You have been handed a design document and asked to plan the build it describes.
You cannot talk to the person who wrote it.

Read [SPEC_PATH]. Read nothing else.

Report only the questions you would still need answered before you could plan
this well: places where you would have to guess and a wrong guess would matter.
For each, give the question and why the answer changes the plan. Rank them by
importance; at most 8.

Check these areas in particular: what happens to each kind of data over time
(changed, retired, deleted, erased on request); every form and who may submit
it; the jurisdiction's rules; timezones and cutoffs; concurrent use; what the
operator changes without a developer; how it is deployed and configured.

Skip anything the document leaves to the builder, anything you could
reasonably decide yourself, and nitpicks about wording.
If nothing important is left, say "nothing important left".
Answer in one message.
```

Sort what comes back into three piles:

- **Answered already** by the conversation or the project: put the answer in the spec.
- **Minor**: a sensible builder could settle it without changing what gets built. Settle it, and mark it in the spec as your call.
- **The owner's**: only they can answer it, and the answer changes what gets built.

Bring the owner's pile in **one** message, numbered and most important first, at most 5. This is the only batched question in the brainstorm, because the owner can answer a numbered list in a single turn. Update the spec with the answers. The check produces only this one round.

Adapted from Superpowers `brainstorming/builder-check-prompt.md` (MIT, Jesse Vincent).
