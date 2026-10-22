# Library/Doc Audit — Research-Grounded Brainstorm (v2.7.0)

**Phase 1C validator · 2026-07-10**
**Spec:** `docs/superpowers/specs/2026-07-10-research-grounded-brainstorm-design.md`
**Scope:** the FOUR external surfaces the feature depends on. No third-party libraries are
added by this feature; every dependency is a *harness capability* (Claude Code builtin, an
upstream Superpowers script contract, a native tool schema, or a local script). Verified
against **live** sources (installed binary, installed plugin cache, official docs), not
training data.

---

## 1. Tools Available

| Tool | Status | Notes |
|---|---|---|
| Installed Claude Code | ✅ **v2.1.197** | `/Users/oleg/.local/share/claude/versions/2.1.197` (Mach-O arm64, BUILD_TIME 2026-06-29T19:08:42Z, GIT_SHA c8fd8048). Verified by string-extracting the binary. |
| Installed Superpowers plugin | ✅ **6.1.1** (also 6.1.0, 6.0.3, 5.1.0 in cache) | `~/.claude/plugins/cache/claude-plugins-official/superpowers/`. Spec pins 6.0.3; newest upstream is 6.1.1 (obra/superpowers, released 2026-07-02). |
| Context7 MCP | ✅ available, **not used** | Context7 indexes third-party libraries; it has no Claude-Code-internal or Superpowers-plugin docs. Correctly bypassed for live-file + official-doc verification per the task's source ladder. |
| Official docs | ✅ | `code.claude.com/docs/en/skills.md`, `.../changelog`, `.../agent-sdk/user-input` (WebFetch/WebSearch). |
| Manifests | n/a | No package manifest is touched; feature is description-driven guidance + one CI-lint line. |

No DEGRADED notice: primary sources (installed binary + installed plugin cache + official docs) were all reachable.

---

## 2. Dependencies Verified (summary table)

| # | Surface | Spec context | Live reality (2026-07-10) | Status |
|---|---|---|---|---|
| 1 | `deep-research` bundled skill | Trigger 0 engine #1 (optional, WebSearch fallback) | Present on v2.1.197 as a builtin **Workflow** (`Workflow({name:'deep-research', args:'<question>'})`); `/deep-research <q>` slash entry; returns a synthesized report as a **message**, does not write a file | 🟢 (🟡 caveats) |
| 2 | Superpowers Visual Companion | Feature 2 elicitation surface (reused as-is) | 6.0.3 companion contract **byte-identical** in installed 6.1.1 for SKILL.md + start-server.sh; visual-companion.md differs only by dropping a Gemini-CLI note | 🟢 (🟡 version pin) |
| 3 | AskUserQuestion caps | Fallback ladder bound | **1–4 questions/call, 2–4 options/question, header ≤12 chars, multiSelect supported, auto "Other" free-text**; multiSelect verified directly from binary | 🟢 (🟡 header/option caps) |
| 4 | V-memory recall CLI | Trigger 0 gate 2 (shell-out) | `scripts/compound-v-memory.py search "<q>" [--top N] [--json] [--intent …] [--no-embed]` exists; `/v:remember` uses `search … --top 8` | 🟢 |

---

## 3. API / Signature Verification

### 3.1 `deep-research` — invocation & contract (from the installed binary)

Verified strings from `versions/2.1.197`:

- Invocation shape: `Workflow({name: 'deep-research', args: '<question>'})` (the error path prints
  exactly this: *"No research question provided. Pass it as args…"*).
- Argument: **one research-question string** (`args`). The live available-skills entry says
  *"pass the refined question as args, weaving the answers in"* and *"BEFORE invoking, check if the
  question is specific enough … if underspecified … ask 2–3 clarifying questions to narrow scope."*
- Internal pipeline (binary evidence): a **scope agent** *"Decompose this research question into
  complementary search angles"* → fan-out search agents → extract **2–5 FALSIFIABLE claims** →
  **N-vote adversarial verification** (`VOTES_PER_CLAIM`, verdict phase `agent('Adversarially verify: …', {phase:'Verify', schema: VERDICT_SCHEMA})`) → `{ label: "synthesize", schema: REPORT_SCHEMA }`
  producing a report with a **3–5 sentence executive summary**.
- **Output mode:** returns the report as content (structured per `REPORT_SCHEMA`). Workflow-agent
  guidance in the binary reads *"Communicate your final report directly as a regular message — do NOT
  attempt to create files."* → deep-research **does not write a file**; the caller must persist it.

### 3.2 Visual Companion `start-server.sh` — flags (from installed 6.0.3, identical in 6.1.1)

`--project-dir <path>` · `--host <bind>` · `--url-host <display>` · `--idle-timeout-minutes <n>` ·
`--open` · `--foreground` (alias `--no-daemon`) · `--background` (alias `--daemon`).
All three flags the spec names (`--project-dir`, `--open`, `--foreground`) exist and behave as the
spec assumes. Returns startup JSON `{"type":"server-started","port":N,"url":"http://<host>:N/?key=…","screen_dir":"…/content","state_dir":"…/state"}`; the same JSON is written to `$STATE_DIR/server-info`.
The `?key=…` in the URL is mandatory (server rejects keyless HTTP/WS).

### 3.3 Companion events file + `data-multiselect` + CSS classes

- Events: **`$STATE_DIR/events`**, JSONL, one object per line, e.g.
  `{"type":"click","choice":"a","text":"Option A - Simple Layout","timestamp":1706000101}`.
  Cleared automatically on each new screen push. **Absent ⇒ user did not interact** (use terminal
  text only). Confirmed in `visual-companion.md` and consistent across 6.0.3/6.1.1.
- `data-multiselect`: **supported.** `helper.js`: `const multi = container && container.dataset.multiselect !== undefined;`
  inside `window.toggleSelect`. Authoring: add the bare attribute to a `.options` container; each click
  toggles selection.
- Frame CSS classes present in `scripts/frame-template.html` (6.0.3 == 6.1.1) that the form guidance
  can reference: `.options .option .letter .content · .cards .card .card-image .card-body ·
  .mockup .mockup-header .mockup-body · .split · .pros-cons .pros .cons · .mock-nav .mock-sidebar
  .mock-content .mock-button .mock-input .placeholder · .subtitle .section .label · .selected`.
  Selection wiring is `data-choice="…" onclick="toggleSelect(this)"`.

### 3.4 AskUserQuestion — schema caps

- `multiSelect: true` — **verified directly from the harness binary**: *"Use multiSelect: true to
  allow multiple answers to be selected for a question."*
- Caps (official Agent SDK docs + corroboration): **1–4 questions per call**, **2–4 options per
  question**, **header ≤12 chars**, automatic **"Other" free-text** option. The exact integer caps
  are compiled into ajv validators (not extractable as literal strings from the minified binary);
  they are confirmed via `code.claude.com/docs/en/agent-sdk/user-input`.
- Behavior note: v2.1.200 changed dialogs to **no longer auto-continue by default** (opt into an idle
  timeout via `/config`) — the "60s auto-timeout" older blogs cite is now off by default.

### 3.5 V-memory `search` subcommand (local)

```
python3 scripts/compound-v-memory.py search "<query>" [--repo REPO] [--top N] \
                                                       [--intent planning|review] [--json] [--no-embed]
```
`/v:remember` (commands/v-remember.md) shells out as `… search "{{args}}" --top 8`. A separate
`recall-check` subcommand exists (deterministic recurring-failure verdict for review gates) — **not**
the one for gate 2; gate 2 must use `search`.

---

## 4. Critical Findings 🔴

**None.** No dependency is deprecated, abandoned, or missing. Every surface the spec relies on exists
and is invocable on the installed stack. The feature is safe to plan against.

---

## 5. High-Priority Findings 🟠

**None.** (No 12–24-month-stale or blocking-risk dependency.) The items below are MEDIUM: they change
*how* the guidance must be written, not *whether* the feature is viable.

---

## 6. Medium Findings 🟡

**M1 — `deep-research` returns a message, not a file; the recon caller must persist it.**
The spec's output contract (Feature 1) is a written, committed `docs/superpowers/recon/YYYY-MM-DD-<topic>.md`.
But deep-research (binary evidence) *"Communicate your final report directly as a regular message — do
NOT attempt to create files."* So when Trigger 0 selects engine #1, the parent must **capture the
returned report and write + commit the recon doc itself** — deep-research will not create the file.
The ≤150-line target and the "findings / questions-to-ask / constraints / sources" shape must be
imposed by the caller (e.g. a bounded synthesis instruction), because deep-research's native report
is a full research report, not the trimmed recon format.

**M2 — `deep-research` is a Workflow (ultracode), gate-able; key the presence-check on the
available-skills listing, not a version and not a hard `Workflow(...)` call.**
Under the hood deep-research is a **dynamic Workflow** (platform introduced v2.1.154, 2026-05-28), not
a classic SKILL.md file. Two consequences: (a) `Workflow(...)` is a harness tool a *plain subagent may
not have*, so guidance must invoke deep-research through the **skill/slash interface** (its
available-skills entry), never by hard-coding `Workflow({...})`; (b) it can be hidden by
`disableBundledSkills` / `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS` or the ultracode toggle. The spec's
chosen signal — *"if `deep-research` appears in the agent's available-skills listing"* — is therefore
**exactly right**. The `/v:init` capability probe (spec §"Machine-local capability") should record
presence-in-listing, and treat absence as "use the WebSearch fallback," which the spec already does.

**M3 — Official `skills.md` does not enumerate `deep-research` in its bundled list; provenance is
changelog + live binary.** The docs' "Bundled skills" list (`/doctor, /code-review, /batch, /debug,
/loop, /claude-api, /run, /verify, /run-skill-generator`) is explicitly non-exhaustive ("including")
and **omits deep-research**. The official record that *does* confirm it: the **changelog** references
`/deep-research` (e.g. the verifier-reporting bugfix, ~v2.1.196–198) and the **installed binary**
contains the workflow. So the third-party blog claim is **corroborated by the official changelog + the
live harness**, but *not* by an enumerated bundled-skills doc entry. Net: rely on the runtime
presence-check (M2), not a doc list.

**M4 — Feature 2 deliberately OVERRIDES upstream's "text questions go to the terminal" rule; the
guidance must say so explicitly.** Upstream restricts the companion to *visual* questions. Verbatim:
> SKILL.md: *"Per-question decision: Even after the user accepts, decide FOR EACH QUESTION whether to
> use the browser or the terminal … **Use the terminal** for content that is text — requirements
> questions, conceptual choices, tradeoff lists, A/B/C/D text options, scope decisions."*
> visual-companion.md: *"Use the terminal when the content is text or tabular: Requirements and scope
> questions … Conceptual A/B/C choices … Tradeoff lists … Clarifying questions — anything where the
> answer is words, not a visual preference."*

Feature 2 batches *independent text-ish* questions (preference toggles, naming, styling directions,
feature checkboxes, priority ranking) into ONE companion form — which upstream would route to the
terminal, one at a time. `brainstorm-elicitation.md` must acknowledge it is overriding this upstream
guidance for the independent-batch case (same "description-driven override" mechanism, and the same
reliability caveat, as Compound V's other interceptions). It must NOT force the browser open: the
spec's batch-gate condition #2 ("user has already accepted the Visual Companion this session")
correctly preserves upstream's just-in-time / never-force-open etiquette (*"Offer … just-in-time —
NOT upfront … This offer MUST be its own message … If no visual question ever arises, never offer
it."*).

**M5 — Spec pins Superpowers 6.0.3; installed/current upstream is 6.1.1. Contract is identical —
don't hard-pin.** SKILL.md and start-server.sh are byte-identical 6.0.3→6.1.1; visual-companion.md
changed only by removing a Gemini-CLI launch note. So the companion contract is safe, but the
guidance should reference the companion by its **stable contract** (flags, events file, frame classes),
not by a "6.0.3" version string, since users run 6.1.1 (and future minors will keep moving).

**M6 — AskUserQuestion caps bound the fallback ladder tightly.** Max **4 questions/call**, **4
options each**, **12-char header**. Implications for `brainstorm-elicitation.md` fallback authoring:
(a) an independent batch of >4 questions overflows to one-at-a-time after the first 4 (spec already
says this); (b) a "which features?" question with >4 features cannot list them all as options — use
`multiSelect` and/or split across questions; (c) headers must be ≤12 chars. These are the same
semantics as the companion's `data-multiselect`, so the two surfaces map cleanly.

---

## 7. Design Constraints for the Plan

**MUST**
- MUST invoke `deep-research` through its **available-skills/slash interface**, and MUST **capture its
  returned report and write+commit** `docs/superpowers/recon/YYYY-MM-DD-<topic>.md` in the caller —
  deep-research does not create files. (M1, M2)
- MUST key the deep-research presence-check on **presence in the available-skills listing** (recorded
  by `/v:init` into the machine-local capabilities file), and MUST fall back to ≤6 parallel WebSearch
  when absent. (M2, M3)
- MUST reference the Visual Companion by its **contract** — `start-server.sh --project-dir/--open/--foreground`,
  events at `$STATE_DIR/events` (JSONL, cleared per screen, absent⇒no-interaction), frame classes
  `.options`/`.option`/`data-choice`/`onclick="toggleSelect(this)"`, `data-multiselect` on the
  `.options` container — **not** by a 6.0.3 version pin. (M5)
- MUST have `brainstorm-elicitation.md` **explicitly state** it overrides upstream's "text → terminal"
  rule for the independent-batch case, quoting the upstream rule it supersedes. (M4)
- MUST respect the batch gate's condition #2 (companion already accepted this session) so the guidance
  never force-opens the browser — preserving upstream just-in-time etiquette. (M4)
- MUST size fallback AskUserQuestion forms to **≤4 questions, ≤4 options each, ≤12-char headers**, using
  `multiSelect` for checkbox-style independent questions; overflow continues one-at-a-time. (M6)
- MUST shell out to V-memory as `python3 scripts/compound-v-memory.py search "<topic>" --top N` (add
  `--json` for a machine-parseable strong-hit decision) using an **absolute script path or an explicit
  `cd`** — agent bash cwd resets between calls. Use `search`, not `recall-check`, for gate 2. (§3.5)

**MUST NOT**
- MUST NOT hard-code `Workflow({name:'deep-research', …})` in guidance a plain subagent might run —
  the Workflow tool may be absent; go through the skill interface. (M2)
- MUST NOT assume deep-research writes the recon file, or that its native output already matches the
  ≤150-line recon format. (M1)
- MUST NOT gate deep-research on a Claude Code version number — the exact bundling version is not
  cleanly documented; the runtime presence-check is the contract. (M2, M3)
- MUST NOT route independent text batches through the companion when it was never offered/accepted
  this session (respect upstream; fall back to AskUserQuestion / terminal). (M4)
- MUST NOT pin the guidance to Superpowers 6.0.3 file paths/behaviors as if version-specific — they
  are stable across 6.0.3→6.1.1. (M5)

---

## 8. Open Questions for the Human

1. **Recon persistence shape.** deep-research returns a *full* research report as a message (M1). Do
   you want Trigger 0 to (a) trim/synthesize it down to the ≤150-line recon format before writing, or
   (b) write the full report and let 1B/1C skim it? (a) costs one extra synthesis step; (b) is cheaper
   but bloats the committed recon doc. Not a blocker — the plan can default to (a).
2. **`/v:init` presence-probe fidelity.** deep-research is a gate-able Workflow (M2). Should `/v:init`
   record a *point-in-time* presence flag (fast, can go stale if the user later sets
   `disableBundledSkills`), or should Trigger 0 also do a *live* re-check of the available-skills
   listing at fire time (robust, slightly more work)? Recommend live re-check at fire time, with the
   `/v:init` flag as a hint only.

Neither question blocks writing the plan; both are scoping choices, flagged so they are made
deliberately rather than by default.

---

## 9. Knowledge Base Updates

Appended to `docs/superpowers/library-audit/_knowledge-base/agent-instruction-tooling.md` under
`## Updated 2026-07-10 — Claude Code bundled deep-research, Visual Companion contract, AskUserQuestion caps`:
Claude Code v2.1.197 facts; deep-research = builtin Workflow (invocation, pipeline, message-not-file
output, v2.1.154 platform origin); Superpowers 6.1.1 companion-contract stability vs 6.0.3;
AskUserQuestion 1–4/2–4/12-char/multiSelect caps; V-memory `search` invocation. All claims
date-stamped and sourced.

---

### Sources
- Installed binary: `~/.local/share/claude/versions/2.1.197` (string extraction; VERSION/BUILD_TIME/GIT_SHA, `Workflow({name:'deep-research'…})`, `multiSelect: true`, REPORT_SCHEMA/VERDICT_SCHEMA, "do NOT attempt to create files").
- Installed plugin cache: `~/.claude/plugins/cache/claude-plugins-official/superpowers/{6.0.3,6.1.0,6.1.1}/skills/brainstorming/` (SKILL.md, visual-companion.md, scripts/start-server.sh, scripts/frame-template.html, scripts/helper.js; diffs across versions).
- `code.claude.com/docs/en/skills.md` (bundled-skills list, non-exhaustive), `code.claude.com/docs/en/changelog` (`/deep-research` bugfixes; Workflow intro v2.1.154; AskUserQuestion 2.1.181/2.1.200 entries), `code.claude.com/docs/en/agent-sdk/user-input` (AskUserQuestion caps).
- `github.com/obra/superpowers/releases` (v6.1.1, 2026-07-02).
- Local: `scripts/compound-v-memory.py search --help`, `commands/v-remember.md`.
