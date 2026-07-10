# Requirements-Elicitation UX Knowledge Base

How an AI agent should ask clarifying questions: sequential vs batched, count thresholds,
independence classification, cognitive load, and consent/cost disclosure for expensive steps.

Maintained by Compound V Phase 1B advisor. Append at the bottom on each pass.

---

## Updated 2026-07-10 — batched vs sequential elicitation (research-grounded-brainstorm audit)

### Sequential vs batched — the decision matrix
- **Dependent / exploratory questions → one-at-a-time, terminal.** Practitioner consensus (multiple
  independent dev blogs converge): "ask each question one at a time … cognitive load near zero …
  one revision cycle costs more than a focused interview." Sources: [Dan Does Code](https://www.dandoescode.com/blog/efficient-vibe-coding-with-clarifying-questions),
  [Pete Hodgson 2025](https://blog.thepete.net/blog/2025/05/22/why-your-ai-coding-assistant-keeps-doing-it-wrong-and-how-to-fix-it/),
  [BSWEN 2026](https://docs.bswen.com/blog/2026-04-01-ai-clarifying-questions-codex/). A static form
  cannot branch, so batching dependent questions produces a half-stale form.
- **Independent questions → may batch, but SMALL and CHUNKED.** The batch beats a long sequential
  chain only when it does not recreate the survey *matrix* anti-pattern.

### Count thresholds — floor AND ceiling
- **Floor ≈ 3.** Below 3 independent questions, a form adds click/context-switch overhead for no
  gain; single/short interactions are where traditional forms beat conversational ones ("short forms
  1–3 fields: no meaningful difference, sometimes worse" — [TinyCommand 2026](https://tinycommand.com/blogs/conversational-forms-vs-traditional-forms-which-is-better-for-your-business)).
- **Ceiling ≈ 3–5 groups per screen.** "3 multiple-choice per web page" beat *both* "1 per page" and
  "long matrix" on respondent satisfaction; matrix/grid formats raised dropout — [ScienceDirect: web
  survey experiments on matrix questions](https://www.sciencedirect.com/science/article/abs/pii/S074756321630718X).
  Each 7+-row matrix block adds ~2–5pp dropout and invites straight-lining.
- **Beyond the ceiling → paginate / multi-step, not one dense page.** Multi-step forms beat
  single-page: Formstack +25.4% completion, HubSpot +86% conversion (via [TinyCommand roundup](https://tinycommand.com/blogs/conversational-forms-vs-traditional-forms-which-is-better-for-your-business)).
- **Cognitive-load anchor:** Miller 7±2 *chunks* (not raw items); chunk/group related controls —
  [Miller's Law](https://uxuiprinciples.com/en/principles/millers-law). Survey-length data: 1–3
  questions ≈ 83–86% completion, sharp drop-off after — [Survicate, 21,863 surveys](https://survicate.com/blog/how-many-questions-should-surveys-have/).

### Independence classification — the failure mode and the tiebreak
- **Test independence on ANSWER INTERACTION, not surface topic.** Two questions are dependent if any
  answer could change, contradict, or over-subscribe another — including through a constraint the
  form never shows (a shared time/scope budget). **When unsure → sequential.**
- **Looks-independent-but-dependent patterns:** name↔identifier, format↔validation, theme↔dark-mode,
  ranking↔MVP, runtime↔package-manager, and the subtle one — feature toggles coupled by an unshown
  budget ("enable X/Y/Z?" when you can't afford all three).
- Questionnaire order/carryover/priming effects are real: a problem-framed question first depresses
  later scores regardless of experience (survey order-effect literature). Independence is not "different
  topic"; it's "answers don't interact."

### Option-framing bias
- Closed-options-only forms anchor the user and frame out the unlisted true answer; LLMs "reinforce
  the framing of the user's question rather than challenging its premises." Provide an open-ended
  "other / none of these" escape per group for divergent (brainstorm) contexts. Sources: [Maze — UX
  cognitive biases](https://maze.co/guides/ux-cognitive-biases/types/), framing-effect literature.

### LLM-generated clarifying questions (RE-2025 research)
- Minimally-guided LLM clarifying questions are statistically **no worse** than human ones (p>0.05);
  they become **markedly better when guided by an explicit list of interviewer "mistake types"**
  (GPT-4o chosen in ~68% of paired comparisons; ~93.5% chance of the better mistake-avoiding
  question). → Frame "questions to ask" as *mistakes-to-avoid*, not a flat list. Source: [arXiv
  2507.02858](https://arxiv.org/html/2507.02858). Related env: ReqElicitGym (arXiv 2602.18306,
  search-surfaced, not fetched).

### Consent/cost disclosure for expensive AI steps
- Ambient norm (2026): ChatGPT/Gemini/Perplexity deep-research gate the expensive pass behind a
  scope/clarifying step and/or a visible time estimate before spending — [T-Minus 2026](https://www.tminusai.com/blog/deep-research-ai-showdown-2026).
- Research-agent cost variance is ~200× (£0.10–£20+, median £1–3, 3–5 loops) — [Keito](https://keito.ai/blog/ai-research-agent-cost-tracking/).
  → Disclose scope + order-of-magnitude time + "spends tokens/subagents" QUALITATIVELY; a hard token
  figure is both fabrication-prone and likely wrong. "Ask before an expensive operation" is the
  established best practice.
