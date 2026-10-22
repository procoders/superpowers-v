# Software Testing Selection Knowledge Base

Regression test selection (RTS) / test impact analysis (TIA) as actually practised: what the
always-run floor contains, whether declared maps are defensible, how unmapped inputs are treated,
measured miss rates, and the CI-plumbing traps that turn a scoped suite into a green check that
ran nothing.

Maintained by Compound V Phase 1B advisor. Append at the bottom on each pass.

---

## Updated 2026-09-01 — v3.0 scoped tests audit

### The always-run floor is three-part, not one

Vendor-documented, not folklore. Azure DevOps TIA describes its selection as *"a robust test
selection mechanism. It includes existing impacted tests, previously failing tests, and newly added
tests"*
([MS Learn](https://learn.microsoft.com/en-us/azure/devops/pipelines/test/test-impact-analysis?view=azure-devops)).

**Reusable rule:** a floor made only of linters/integrity gates is missing two of the three legs the
field considers mandatory. Any scoped-test design must additionally always run (a) every test file
changed in the current diff and (b) every test that failed on the previous run of that branch.

### Unmapped input ⇒ run everything is the field's answer

*"**Safe fallback**. For commits and scenarios that TIA can't understand, it falls back to running
all tests… if the code commit contains changes to HTML or CSS files, it can't reason about them and
falls back to running all tests."* And: *"When TIA opens a commit and sees an unknown file type, it
falls back to running all tests. While this action is good from a safety perspective, tuning this
behavior might be useful in some cases."* ([MS Learn](https://learn.microsoft.com/en-us/azure/devops/pipelines/test/test-impact-analysis?view=azure-devops)).

Corollary the design must respect: the fallback has to be evaluated against the **realised** changed
paths, not the planned ones, or a job that grows a new unmapped path mid-flight escapes it.

### A DECLARED map is acceptable practice — but never ships alone

Microsoft ships a declared-map escape hatch: *"You can extend the scope of TIA by explicitly
providing the dependencies map as an XML file… The mapping can even be approximate."* But it is
paired with two things a naive design omits:

1. **A periodicity valve** — *"TIA can be conditioned to run all tests at a configured periodicity.
   Setting this option is recommended, and is the means to regulate test selection."*
2. **A validation procedure** — *"use two test tasks — one that runs only impacted Tests (T1) and one
   that runs all tests (T2). If T1 passes, check that T2 passes as well. If there was a failing test
   in T1, check that T2 reports the same set of failures."*

**Reusable rule:** declared map + safe fallback + unconditional periodic full run + a one-off T1/T2
calibration. Ship fewer than four and the map is unfalsifiable.

### Measured miss rates — and why a glob map is worse than these numbers

Legunsen et al., *An Extensive Study of Static Regression Test Selection* (ICSE'16, 985 revisions /
22 Java projects, [PDF](https://www.cs.cornell.edu/~legunsen/pubs/LegunsenETAL16StaticRTSStudy.pdf)):

- Definition: *"a technique is safe if it selects to run all tests that may be affected by code
  changes."*
- Measured: *"percentages of revisions in which ClassSRTS incurs safety violations and precision
  violations are 0.2% and 33.0%, respectively. For MethSRTS, these percentages increase to 10.6% and
  55.7%."*
- Cause: *"the safety issues are usually due to reflection and library exclusion"* — i.e. edges the
  static analysis cannot see.
- Counter-intuitive finding worth remembering: **finer granularity was less safe, not more.**
  Method-level was 10.4 points more unsafe than class-level.
- The governing sentence for any "run fewer tests" proposal: *"any RTS technique can be simply made
  faster by not selecting to run some tests, but then it risks missing regressions."*

**Reusable rule:** 0.2%–10.6% is the unsafe rate for techniques that derive a call graph *from the
code*. A hand-maintained glob map carries strictly less information than a call graph, so treat
0.2% as an optimistic floor, never an expected value. Precision is therefore the wrong axis to
optimise: overlapping map rules should **union**, never first-match-wins.

### Google TAP defers affected tests; it does not drop them

The most-misread precedent in "run only the affected tests"
([Memon & Gao, *Taming Google-Scale Continuous Testing*, PDF](https://static.googleusercontent.com/media/research.google.com/en//pubs/archive/45861.pdf)):

- Selection: reverse-dependency structure *"eventually outputs all test targets that directly or
  indirectly depend on the modified files; these are called AFFECTED test targets."*
- Batching, not skipping: *"All affected test targets that remained unexecuted since the previous
  milestone are run together"*, milestone *"typically cut every 45 minutes during peak development
  time."*
- Residual debt is named, not hidden: *"A milestone run will only determine a PASSED/FAILED status
  for these… others will remain AFFECTED, until (if) run on demand by another process."*
- Scale context: 5.5M affected test targets in one month, of which *"only 63K ever failed"*; only
  *"1.23%"* of executions found a breakage; PASS:FAIL ratio per change is *"99:1"*; test targets
  *"more than a distance of 10 (in terms of number of dependency edges) from the changed code hardly
  ever break."*

Two heuristics TAP explicitly **could not** use, and why (both are situational, not universal):
- Exact code↔test coverage mappings — *"the code churn rates would quickly render the code coverage
  reports obsolete, requiring frequent updates."*
- Failure history ("rerun recently-failed") — *"we could not rely on regression test selection
  heuristics such as 'rerun tests that failed recently' … as we would end up mostly re-running flaky
  tests."* **This rejection is a function of Google's flake rate and does not transfer to a
  low-flake repo.**

**Reusable rule:** scoping is *deferral with an accounting*, not omission. A design that scopes
without naming where the deferred set runs, and what proves it ran, has copied TAP's speed and
dropped its bookkeeping.

### The green-check-that-ran-nothing trap (CI plumbing)

- GitHub's own docs: a workflow *"skipped by path filtering"* leaves associated checks *"in a
  'Pending' state and block[s] merging"*, whereas *"a job is skipped by a conditional"* → *"the job
  reports 'Success'"*
  ([GitHub Docs](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/troubleshooting-required-status-checks)).
  Official guidance is *"avoid requiring workflows that can be skipped"*; the popular community
  workaround is an always-succeeding dummy job of the same name — **a required check that ran
  nothing.**
- Practitioner account of the same class, 2026-04-25: *"CI cheerfully skips the three services that
  import it. Now you have shipped a break and CI told you it was fine"*, and *"Path filters cannot
  follow imports"*
  ([codewithkarani](https://www.codewithkarani.com/blog/monorepo-github-actions-path-filters-shared-code)).

**Reusable rule:** a merge backstop is only trustworthy if a planted violation has been shown to fail
it. Config review cannot distinguish "passed" from "skipped and reported Success."

### Flakiness sets the trust budget for any selective gate

- Chromium CI, 2,000 builds / >1M failures: *"false alerts represent 81% of the failures in the
  Chromium CI, whereas legitimate failures only represent 19%"*, and the mechanism —
  *"developers may lose trust in their test suites and stop considering failures even if some of them
  are caused by real faults"* ([arXiv 2111.03382](https://arxiv.org/pdf/2111.03382)).
- Same paper corroborates the Google figure: *"almost 16% of their 4.2 million tests have some level
  of flakiness."*

**Reusable rule:** fix flake before trusting a selected set. A selective gate inherits the base
suite's false-alert rate and concentrates it into a smaller, more-attended signal.

### Declared maps rot — nearest documented analogue is CODEOWNERS

Practitioner consensus (search-summary tier, 2026 sources, not individually fetched — directional
only): maintenance rather than setup is the hard part, and most CODEOWNERS files end up
*"incomplete, stale, or not enforced at the branch protection level — making them documentation
rather than gates"* ([koalr](https://koalr.com/blog/github-codeowners-guide),
[tenthirtyam](https://tenthirtyam.org/dispatches/2026/03/25/codeowners-automating-code-review-ownership/)).
Suggested drift detector from the same sources: compare the map's prediction against what actually
happened over the last N changes.

**Reusable rule:** content-address the map (digest pinned in whatever artifact consumes it) and log
predicted-vs-actual, or the map has no rot detector and will quietly stop describing the repo.

### Evidence gaps found on this pass (do not fill with guesses)

- **No credible postmortem found** for the intuitive "it was only a docs change and it took prod
  down" story. Two searches returned generic postmortem templates. Arguments about docs-classified
  files must rest on structure (does the prose *encode* behaviour?) rather than anecdote.
- **No first-hand practitioner threads found** on declared-map rot in test selection specifically.
  The CODEOWNERS analogue is the closest available and is an analogy, not a measurement.
