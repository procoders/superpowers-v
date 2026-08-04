# AI Tooling — Jurisdictional & Data-Egress Risk Knowledge Base

Routing developer workloads (source code, commit metadata, issue text, architecture docs) through a
model provider in another jurisdiction: what actually leaves the machine, which legal regimes attach,
what the 2026 policy trajectory is, and how to frame the risk for an operator without either
alarmism or hand-waving.

Scope note: this file is about **jurisdiction and egress**. Vendor *contract* terms live in
`llm-subscription-plan-compliance.md`; *harness* mechanics live in `claude-code-headless-harness.md`.

Maintained by Compound V Phase 1B advisor. Append at the bottom on each pass.

---

## Updated 2026-08-04 — Chinese cloud AI providers as a coding-agent backend

### The concrete leak surface is context files, not "the prompt"

Practitioners reason about egress as "the code I ask about." For an agentic coding CLI that is wrong
by an order of magnitude. Every hierarchical-context agent **concatenates discovered context files and
sends them with every prompt** — so the highest-value document in the repo ships on *every job*,
whether or not it is relevant to the task.

Ranked by density of proprietary signal, typically:

1. **Agent-instruction files** (`AGENTS.md`, `CLAUDE.md`, `QWEN.md`, `GEMINI.md`) — architecture,
   module map, conventions, deploy steps, internal vocabulary. Usually the single most IP-dense file
   in a repository, and the one nobody thinks of as sensitive.
2. **Agent settings** (`.claude/settings.json`, `.qwen/settings.json`) — internal hostnames, MCP
   endpoints, tool inventories.
3. Transitive `@path/to/file.md` imports pulled in by (1).
4. The task's own file reads.

**Reusable rule:** when auditing egress for an agent backend, enumerate the agent's **actual** context
discovery list from its own docs. Never copy the list from a sibling adapter — the names differ per
agent and a wrong list sends operators to check the wrong files.

**Corollary:** `HOME` redirection isolates *user-level* config only. Project-level context lives in the
working directory, which for a dispatcher is a worktree checkout of the repo — inside the blast radius
by construction.

### Legal regimes that attach, in order of how often they actually bite

1. **Contract** — the vendor's own terms. Always applies. See `llm-subscription-plan-compliance.md`.
2. **Third-country transfer (GDPR Ch. V / UK GDPR)** — engages whenever the payload contains personal
   data. Source code, commit metadata, author emails, and issue text routinely do. An EU/UK operator
   sending repo content to a non-adequate jurisdiction needs a transfer mechanism; "it's just code" is
   not an analysis. Note China has **no** EU adequacy decision.
3. **Client/NDA obligations** — in agency and consultancy settings this bites *before* statute. Many
   client contracts carry data-residency or subprocessor-approval clauses that a third-party coding
   agent silently violates. **This is the most commonly missed one** for freelance/agency operators.
4. **Sector rules** — HIPAA/PCI/etc. where fixtures or logs in-repo carry regulated data.
5. **Export control** — least likely to bite an individual today; see trajectory below.

### 2026 policy trajectory — the risk to a *plugin* is continuity, not sanction

- Chinese-model usage in US enterprises moved from experimental to structural during 2026 — one
  measurement cited Chinese-model traffic at ~45% of US enterprise token volume by early July, up from
  ~11.5% in January. A restriction would therefore be a **supply shock**, which is exactly why
  policymakers are moving.
- A redesigned US framework aimed at **models and access** (not chips) is expected as an **interim
  final rule around fall 2026**
  ([CSA — *Sovereign AI Risk: When Your AI Vendor Gets Export-Controlled*](https://labs.cloudsecurityalliance.org/research/csa-whitepaper-sovereign-ai-risk-export-controls-enterprise/)).
- China is simultaneously building **outbound** controls on advanced-model distribution — MOFCOM-led
  discussions reportedly reaching unreleased frontier and open-weight models. Risk runs both ways
  ([NatLawReview — *Choosing Between U.S. and Chinese AI Models: Export Control Risks on Both Sides*](https://natlawreview.com/article/choosing-between-us-and-chinese-ai-models-export-control-risks-both-sides)).

**Framing for an operator, and it is the useful one:** for a distributed plugin the realistic hazard is
**not** that the user is sanctioned. It is that a backend becomes unreachable, unlawful, or
contractually impossible for *some installers* on a policy change with little notice. Design
accordingly: a backend in this class must be **opt-in, off by default, cleanly removable, and never a
silent fallback target** — so that losing it degrades rather than breaks.

### The symmetry argument — the most persuasive framing available

Reuters, **2026-07-03**: Alibaba banned **Claude Code** on internal machines over alleged backdoor
risk, directing staff to its in-house Qoder
([HN 48772443](https://news.ycombinator.com/item?id=48772443), 336 points / 281 comments — above the
community-signal threshold). Thread consensus was that this is ordinary opsec for a company whose
devices reach confidential internal resources.

**Why it is worth citing in an adapter doc:** it makes the point neutrally and without geopolitics. A
vendor that will not route its own proprietary code through a *foreign* coding agent has stated the
risk model plainly; an operator is entitled to apply the same reasoning symmetrically, in either
direction. It reframes the question from "is this vendor trustworthy?" (unanswerable, and invites
motivated reasoning) to "would this vendor accept this arrangement in reverse?" (answerable, and
already answered).

### What vendor privacy assurances do and do not cover

Worked example — Alibaba Cloud Model Studio
([privacy notice](https://www.alibabacloud.com/help/en/model-studio/privacy-notice), fetched 2026-08-04):

**Stated (cite these — calibration is the job, not alarm):**
- *"Alibaba Cloud strictly protects your data privacy and will never use your data for model training."*
- AES-256 in transit; **SOC 2** with an unqualified opinion (Security, Availability, Confidentiality).

**[NOT FOUND] on any Alibaba-owned page — state the absence explicitly:**
- Any **retention period**.
- Any **storage region** commitment. The `dashscope-intl` ⇄ Singapore/`ap-southeast-1` association is
  inferred from general DashScope endpoint documentation, **not** a service-specific residency
  guarantee. Treat residency as **unconfirmed**.
- Any **deletion mechanism** or data-subject request path.
- Any statement on **cross-border transfer**.

**Reusable rule:** "we don't train on your data" is a **use** commitment and answers nothing about
**retention**, **residency**, or **access**. Audit all four separately; an unanswered one is a finding
to report as unanswered, not a gap to fill with a plausible assumption.

### Checklist for any foreign-jurisdiction model backend

1. Enumerate the agent's **actual** context-file discovery list; name the specific files that will
   leave on every job, for *this* repo.
2. Separate the four data questions: **use / retention / residency / access**. Record which are
   answered by a first-party source and which are `[NOT FOUND]`.
3. Cite the vendor's positive assurances alongside the warning — an audit that only alarms gets
   discounted wholesale.
4. Ask whether any repo in scope carries **client work under NDA** or a residency clause. If yes, the
   control is a per-repo allow-list, not a global toggle.
5. Default **off**, opt-in, loud, removable, never a silent fallback target.
6. Where the same weights are reachable through two backends, ask whether both paths are wanted —
   doubling the surface for one model family is rarely deliberate.

### Reusable one-liners

- The agent-instruction file is usually the most sensitive thing in the repo and the last thing anyone
  thinks to check.
- "We don't train on your data" answers **use**, not retention, residency, or access.
- An inferred region is not a residency commitment; say "unconfirmed" rather than "Singapore."
- For a distributed plugin the jurisdictional risk is **continuity**, not sanction — design for the
  backend disappearing.
- "Would this vendor accept this arrangement in reverse?" beats "is this vendor trustworthy?"
- For agency/freelance operators the **client NDA** bites long before any statute does.
