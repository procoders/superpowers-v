# Critique request — Compound V v4 transition table

READ ONLY: do not modify, create or delete files; shell commands only if they are read-only.
Repository = current directory (Compound V 3.9.1, a Claude Code plugin). Read `docs/v4/transition.md` (the proposed
transition table), `docs/v4/salon-report.md` (the experiments it rests on) and `docs/v4/light-flow.md` (the checklists
that won). Verify claims against the actual code where it matters.

Answer, concretely and ranked:
1. Which verdicts are WRONG or premature given the evidence (something deleted that the evidence does not justify
   deleting, or kept without justification)? Name the component, the verdict you would give, and why.
2. What is MISSING from the table (components not listed, capabilities v4 needs that nothing provides — e.g. real-browser
   verification, mechanical enforcement of the review step, model routing without the engine)?
3. The riskiest parts of the migration (what breaks for existing users, what loses a safety property, what tests would
   no longer guard anything) and how to sequence the work to keep CI meaningful at every step.
4. Is the evidence (one greenfield app, one brownfield feature, judge noise ~±10 points) strong enough for each
   deletion? Where would you demand one more experiment, and which one (cheap)?
Keep it under 900 words. No praise.
