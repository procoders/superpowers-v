# Exploration Checklist

The procedural enforcement of "exhaust the codebase first." The agent runs this **before** promoting any question to the user OR to the author.

If you cannot fill in the `Already checked:` line for a question, the question is not ready — go back and explore.

---

## Per-Question Checklist

Before surfacing a question, you have:

- [ ] Read the **full function** being changed (not just the diff hunk).
- [ ] Grepped for **callers of any changed function**, filtering out tests:
  ```bash
  grep -rn 'funcName\b' src | grep -vi test
  ```
- [ ] If the question is about convention/style: checked the repo's **discovered** convention/instruction files (the Phase-0 Standards sources — `CLAUDE.md`, `CONTRIBUTING.md`, `docs/coding-standards/**`, `docs/**/best_practices*`, etc.) for the keyword.
- [ ] If the question is about precedent ("should this fire on event X?"): found a **sibling implementation** handling the same kind of thing and read its callsite.
- [ ] If the question is about project policy (rollback safety, migration pattern, multi-app routing): checked the discovered instruction files and convention docs.
- [ ] Written the `Already checked:` line. If it's empty, vague, or "I assumed," the checklist isn't complete.

---

## The `Already checked:` Line

Every `AskUserQuestion` body and every Open-Question-for-Author finding must carry this line. Format:

```
Already checked: <what you did> — <what it told you> — <why it didn't fully answer>
```

**Good examples:**

> Already checked: grepped `processFirstPayment\b` in `src` — no non-test callers; the real first-payment path is `checkout.ts:handleSeriesEnrollment` (lines 8565, 8599). User judgment needed because both paths exist; need to know whether the dead path's emissions matter.

> Already checked: read the repo's `anti-patterns` doc on "don't re-emit the same event from a higher-level wrapper" + the glossary entry. Pattern says don't double-fire; but this PR's new event is semantically distinct. Need user judgment on whether the docs should note the intentional overlap.

> Already checked: grepped `automation_trigger_group_id` across all migrations — three features use the same NULL-group pattern. Not asking the user; recording as no-finding.

**Bad examples (do NOT surface questions like these):**

> Already checked: nothing — wanted to confirm.

> Already checked: skimmed the file.

> Already checked: I think this looks right but want to be sure.

If the line looks like a "bad example," go back and explore.

---

## When to Promote to an Open Question (for the author)

Only when **all three** hold:
1. The exploration checklist is complete, AND
2. The answer genuinely depends on **author intent** or **prior context not in the repo**, AND
3. You can articulate *why* the codebase doesn't answer it.

If you can't articulate (3), you haven't explored enough.

---

## Loop-Break Rule

If during Phase 4 the user answers "not sure / verify / I don't know" 2+ times in a single `AskUserQuestion` batch:

1. **Stop the batch.** Don't continue with the remaining questions.
2. **Re-enter exploration.** Use the unresolved items as grep/read targets.
3. **Return with grounded recommendations** instead of re-asking.

A "verify" answer is a signal that you didn't ground your recommendation in code. Treat it that way.
