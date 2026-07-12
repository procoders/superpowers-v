# ADR capture — thin, human-confirmed decision records (authority doc)

> Harness-neutral authority for `/v:adr`. The command
> ([`commands/v-adr.md`](../../commands/v-adr.md)) is a thin loader; this file is where the capture
> discipline lives. Design of record:
> [`docs/superpowers/specs/2026-07-11-v2.9-pre-evaluation-design.md`](../../docs/superpowers/specs/2026-07-11-v2.9-pre-evaluation-design.md)
> §5.3 / §9.

`/v:adr` captures **one genuine architecture decision** as a lightweight Markdown record under
`docs/superpowers/adr/NNNN-slug.md`. Once committed it becomes recallable through V-memory's FTS5
lane — which already indexes all of `docs/superpowers/**` — so a decision made today answers a
`/v:remember` next month. It **extends** the recall corpus; it never touches the recall engine or
the routing layer.

An ADR is a *decision record*, not a design document. It answers "what did we decide, what else
did we weigh, and what do we now live with?" — nothing more.

---

## Explicitly out of scope

This capture writes **an ADR and only an ADR.** It does **not** generate:

- **C4 diagrams** (context / container / component / code model views), and
- **SAD documents** (Software Architecture Documents / arc42-style full architecture write-ups).

Those were considered and deliberately declined (see the fixture ADR itself is *not* about this —
the scope decision lives in the spec §5.3). If a request asks for a diagram or a full architecture
doc, say so plainly and stop at the ADR. Scope creep here is the failure mode.

---

## What makes a decision ADR-worthy

Capture only a **genuine decision with alternatives and consequences** — a fork in the road where a
different choice was defensible and something was traded away. If there were no real alternatives,
or nothing was given up, it is a note or a comment, not an ADR. Do not manufacture an ADR to have
one.

Litmus test before writing anything:

- **Was there a real alternative?** Name at least one path not taken.
- **Was something traded away?** A genuine decision has consequences you now live with — not only
  upside.
- **Is it durable?** ADRs record decisions expected to outlast a single change. Ephemeral,
  reversible-by-lunchtime choices do not belong here.

If any answer is no, decline and explain why — do not lower the bar to produce a file.

---

## The record shape — `context / decision / consequences`

Draft three sections (plus a short front block). Keep it plain Markdown so the FTS5 lane indexes it
cleanly — no exotic front-matter is required or expected.

```
# NNNN. <short decision title>

- **Status:** Accepted            (Proposed | Accepted | Superseded by NNNN)
- **Date:** YYYY-MM-DD
- **Deciders:** <who / which review>

## Context

The forces at play: the problem, the constraints, what pushed us to decide now. Cite real
evidence where it exists.

## Decision

The choice, stated in one clear sentence, then the alternatives weighed and why each was
declined. An ADR without named alternatives is not an ADR.

## Consequences

What we now live with — the good, the bad, and the follow-ups. State the downsides honestly;
a consequences section that lists only upside is a red flag.
```

`NNNN` is a zero-padded, monotonically increasing number (`0001`, `0002`, …). Pick the next unused
number by listing `docs/superpowers/adr/`. `slug` is a short kebab-case summary of the decision.

---

## The "References MUST exist" guardrail

**This is the one hard rule.** LLMs hallucinate citations — inventing a plausible-looking file
path, a section number, a paper, or a URL that does not exist is a *documented, recurring* failure
mode. An ADR that cites a fabricated source is worse than one that cites nothing: it launders a
guess into durable, committed, recallable authority.

Therefore, before drafting is confirmed:

- **Every reference must be verified to exist.** A cited repo path → confirm the file is present
  (e.g. `ls`/`test -f`). A cited line range → confirm it resolves. A cited ADR/spec → confirm the
  file exists. A cited external URL or paper → only include it if you can vouch for it; when in
  doubt, **drop the citation rather than guess.**
- **No reference is strictly better than a wrong one.** Prefer an unreferenced but true statement
  over a confidently-cited fabrication.
- Surface the verification to the human at the confirm step: "references checked — all resolve" (or
  name the ones you dropped).

This mirrors `/v:onboard`'s read-then-cite discipline: claim only what you actually looked at.

---

## Draft → human-confirm (never auto-write)

**Nothing is written to disk before the human approves the draft.** ADRs are durable, committed,
and recallable — an auto-written ADR is a machine asserting architectural authority no one signed
off on. The flow is always:

1. **Draft in-message.** Present the full `context / decision / consequences` draft, the target
   path (`docs/superpowers/adr/NNNN-slug.md`), and the references-verified note.
2. **Ask for confirmation.** The human edits, accepts, or declines. If they decline, write nothing.
3. **Only on explicit approval** do you write the file.

There is no `--auto` mode and no silent path. If the decision is not ADR-worthy (fails the litmus
test), say so at the draft step instead of writing a weak record.

---

## Two-command commit discipline (v2.6.4)

An ADR that is written but never committed is **invisible to recall** — the FTS5 lane indexes
**git-tracked files only**, so an uncommitted `docs/superpowers/adr/*.md` cannot be found by
`/v:remember`. Worse, `finishing-a-development-branch`'s worktree cleanup can silently delete an
uncommitted doc (the v2.6.4 audit-trail incident). So capture is not done until the file is
committed.

Follow the project commit discipline exactly — **write, then commit, as two separate commands, no
`&&`, and check each exit code:**

```
# 1. stage the exact file (only it)
git add docs/superpowers/adr/NNNN-slug.md
#    → check exit code before continuing

# 2. commit — a SEPARATE command, not chained with &&
git commit -m "docs(adr): NNNN <short decision title>"
#    → check exit code
```

Chaining `git add … && git commit …` is forbidden: if the `add` fails, the `&&` swallows it and you
commit nothing (or the wrong thing) while believing you succeeded. Two commands, two exit-code
checks, is the invariant that keeps the audit trail honest.

---

## Then it's recallable

Once committed, the ADR is picked up automatically on the next index refresh — no indexer change,
no special registration. Confirm it landed:

```
python3 scripts/compound-v-memory.py refresh          # incremental, by file hash
python3 scripts/compound-v-memory.py search "<a phrase from the decision>"
```

The ADR should appear as a hit. If it does not, the file is almost certainly uncommitted (recall is
git-tracked-only) — re-check the commit step above.

---

## Out of scope (this capture)

C4 diagrams · SAD / arc42 full architecture documents · any auto-write · manufacturing an ADR where
no real alternative existed · citing an unverified source · registering ADRs anywhere other than
`docs/superpowers/adr/` (the FTS5 lane finds them there by default).
