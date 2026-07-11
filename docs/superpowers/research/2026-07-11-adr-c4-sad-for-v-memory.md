# ADR / C4 / SAD as Auto-Generated Architecture Docs for V-Memory

**Date:** 2026-07-11. Research pass answering the user's question: should Compound V auto-generate
Architecture Decision Records (ADR), C4 diagrams, or a Software Architecture Document (SAD) into
`docs/` to enrich V-memory's retrieval corpus? User flagged skepticism ("может они там и ни к чему")
and wanted a real assessment, not a default-yes. Companion to the
[2026 orchestrator landscape synthesis](2026-07-11-2026-orchestrator-landscape-synthesis.md).

**Bottom line: ADR yes (thin capture step, not a subsystem) · C4 no · SAD no.**

---

## 1. AI-agent-specific evidence (2024-2026)

### ADR — most direct AI-agent discussion of the three
- Core tension (multiple sources): an ADR in a repo but not in the agent's context = zero effect;
  loaded-but-advisory = followed probabilistically; only a deterministic-check-backed ADR is reliably
  enforced ("Ignored/Advisory/Enforced" — [Mneme HQ](https://mnemehq.com/insights/how-ai-coding-agents-use-adrs/),
  opinion/product, no empirical study — flagged).
- [Catio 2026 ADR guide](https://www.catio.tech/blog/architecture-decision-record): ADRs "survived a
  decade-plus of fashion cycles," but static markdown drifts and "an agent reading an ADR has no way
  to know whether the decision still holds" (vendor content — take diagnosis, discount pitch).
- Shipped tooling: Claude Code / Cursor "ADR skills" that watch a session for decision language and
  auto-write `docs/adr/`, marketed as "optimized for LLM context efficiency."
- **Real practitioner report:** [Equal Experts](https://www.equalexperts.com/blog/our-thinking/accelerating-architectural-decision-records-adrs-with-generative-ai/)
  — win: "dozens of ADRs in a single morning"; **documented failure: LLMs "frequently hallucinated
  reference material, including non-existent APIs, web pages, or entire product features,"** needing a
  "References MUST exist" guardrail + AI-judge review. Human review stays the bottleneck.
- **Academic:** [arXiv 2604.03826 "Context Matters"](https://arxiv.org/html/2604.03826v2) — 4 LLMs on
  4,500+ ADRs / 750 repos: feeding only the **last 3-5 ADRs** matched/beat feeding the entire history,
  at lower cost. A small curated slice helps; an unbounded corpus doesn't. (Caveat: measures
  replication fidelity, not ground-truth correctness; OSS-only.)
- [arXiv 2604.13108](https://arxiv.org/pdf/2604.13108) evaluates ADR+C4+SAD as agent-navigation aids —
  structured docs helped agents avoid exhaustive traversal, but leaves staleness impact open.

### C4 — AI arguments exist but apply to the rendered diagram
- [Medium/Windead Mar 2026](https://medium.com/@windead/the-c4-model-the-most-underrated-context-management-protocol-of-the-ai-era-046580bd9aa5):
  LLMs "get lost with an entire system"; C4's hierarchy shards context progressively. But does NOT
  resolve the diagram-vs-text problem — asserts Structurizr MCP / a C4 skill make it "queryable"
  without fidelity detail.
- Real tooling generates C4 FROM code ([C4Diagrammer](https://github.com/jonverrier/C4Diagrammer),
  StackSpot) — AI *producing* C4 for humans, not C4 *consumed by* agents as memory.
- C4 is commonly authored as text DSL (Structurizr → Mermaid/PlantUML), so the *source* is indexable —
  but no source shows FTS5 keyword search over diagram DSL substitutes for seeing the picture, or beats
  a well-written `architecture.md` prose section.

### SAD — weakest AI evidence
- Closest: [arXiv 2604.08293 "CIAO"](https://arxiv.org/pdf/2604.08293) auto-generates a **hybrid**
  narrative (SAD prose + C4 structure), not a pure IEEE-1471/ISO-42010 SAD; same
  hallucination/human-review caveats, heavier doc. No source argues for auto-generating a traditional
  big-upfront SAD as agent context. Absence noted, not overclaimed as a negative.

## 2. General adoption/reputation (2025-2026), independent of AI

Best source: [IcePanel State of Software Architecture 2025](https://icepanel.io/blog/2026-01-21-state-of-software-architecture-survey-2025)
(real practitioner survey):
- **ADR: 48% use, 52% don't** — genuinely split, not a practiced consensus despite being well-known.
- **C4: strong** — >70% at least moderately confident; Context 81%, Container 79%, Component 41%
  (drops at lower zoom, matching C4's own "lower levels optional" guidance); 87% use some diagramming
  tool.
- **Top documentation pain point overall: staleness** — evidence-based confirmation of the drift
  problem the AI sources raise. AI-in-architecture adoption still early (37% some use, 33% dabbled).
- ADR in ThoughtWorks Radar **Adopt** ring (store in source control to stay in sync) — though the entry
  dates to 2018, treat as continuity not fresh re-endorsement.
- HN 2025-2026 mixed-to-positive on plain ADRs; one [Feb 2026 thread](https://news.ycombinator.com/item?id=46993402)
  commenter: "just put the markdown next to the code and in git" — essentially what V-memory already
  does for spec/plan prose.
- C4 vs arc42 now positioned complementary, not competing; nothing shows C4 superseded.
- SAD/BDUF: no source calls it "dead," but sentiment is clearly negative
  ([Simon Brown](https://dev.to/simonbrown/software-architecture-isn-t-about-big-design-up-front-4hol),
  ["aging poorly in 2025"](https://dev.to/wiseaccelerate/the-software-architecture-decisions-that-are-aging-poorly-in-2025-3db0)).
  ISO 42010:2022 survives as a reference standard, not grassroots SAD popularity outside regulated
  contexts.

## 3. Auto-generation precedent
- **ADR: real and fairly mature** (Equal Experts, Adolfi.dev, "Context Matters" paper, multiple shipped
  skills). Consistent theme: large speed wins, but **hallucinated references are a recurring documented
  failure**, human review non-negotiable.
- **C4: precedent is diagrams-from-code for humans**, not agent-readable memory; the C4→agent direction
  is asserted, not demonstrated.
- **SAD: essentially just the CIAO paper**, and its output isn't really a classic SAD.

## 4. Verdict for Compound V's V-memory

**ADR: build it, as a thin capture step bolted onto what exists — not a new subsystem.** The one
pattern with the strongest evidence on every axis that matters here: plain markdown (trivial FTS5 fit,
zero new infra), still a live/endorsed practice, and a genuine gap in the current corpus — specs/plans/
audits are *per-feature and chronological*, but a decision like "SQLite FTS5, not a vector DB, for the
always-on lane" is a **cross-cutting constraint** that should be findable independent of which feature
decided it. Today that lives buried across plan docs + MEMORY.md. A short context/decision/consequences
ADR makes it a first-class retrievable hit (a future "new storage backend" proposal surfaces the
"why not vector DB" ADR immediately). Given the documented hallucination risk, generation must be
**draft-then-human-confirm**, never silently written — consistent with how Compound V treats all AI
output. Incremental, not redundant: a new *decision-centric, cross-feature index key* over information
the corpus already half-contains.

**C4: don't build it (now).** The AI-era arguments apply to the *rendered diagram*; the hard constraint
is text-only/no-binary. The honest fallback (index the DSL text) just makes it "another text file," and
no source shows FTS5 over diagram DSL beats a good `architecture.md` prose section. Highest
over-engineering risk of the three: a new artifact type + new staleness burden for a blog-asserted,
unmeasured benefit.

**SAD: don't build it — the clearest no.** Community evidence (BDUF-as-antipattern, "docs no one reads,"
staleness already the #1 architecture-doc pain point) describes exactly the failure a heavyweight
infrequently-updated SAD reproduces, inside a system whose philosophy is the opposite: small,
incremental, evidence-cited, per-feature artifacts current *because* they're a byproduct of the work.
No real AI-agent SAD evidence. `docs/superpowers/architecture/**` (generated, citation-verified,
incremental via `/v:onboard`) is already a lightweight architecture snapshot — a heavier SAD would
compete with, not complement, it.

**Ranking: ADR > neither C4 nor SAD.** ADR alone has (a) real 2025-2026 AI-agent value evidence,
(b) a current adoption base, (c) a genuine gap (cross-feature constraints vs per-feature narrative),
(d) a shape fitting the text-only/no-daemon/minimal constraints with zero new infra.
