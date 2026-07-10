# Research-Grounded Brainstorm (v2.7.0) — Code Archaeology

**Scope:** Phase 1A targeted audit for `docs/superpowers/specs/2026-07-10-research-grounded-brainstorm-design.md`.
Repo `/Users/oleg/Dev/superpowers-v`, branch `v2.7-brainstorm-recon`. This is a **docs + config + CI**
feature (no runtime branching code), so the five phases are adapted: the "matrix" is the gate-order /
config-shape decision surface; "shared state" is the config keys, banner text, and version strings that
multiple surfaces read; "sibling code" is the existing phase docs, `skill-escalation.md`, hooks, and CI.
No prior archaeology or `_knowledge-base/` audit touches this subsystem (dir is empty; `docs/superpowers/recon/`
does not yet exist).

---

## 1. Matrix

### 1a. Trigger-0 gate order (spec §"Gate order") vs where each input already lives

| Gate | Decision input | Where it lives TODAY | New code needs it? | Exists? |
|---|---|---|---|---|
| 1. plumbing skip | topic classification (build/lint/tooling) | Same test already exists as the 1B skip rule (`phase-1b` L30-39) and SKILL skip rules (L131-134) | reuse the wording | ✅ (mirror it) |
| 2. KB hit | `/v:remember` recall | `compound-v-memory.py search "<q>" --top 8` (v-remember.md L10) | yes | ✅ engine present |
| 3. config | `.claude/compound-v.json` → `brainstorm.deep_research` = `ask\|auto\|off` | key does **not** exist yet | yes | ❌ new key |
| engine A | bundled `deep-research` skill present | detected only ad-hoc; no `/v:init` capability flag | yes | ❌ new flag |
| engine B | 3–6 parallel WebSearch | existing Phase 1B pattern (`phase-1b` L54) | reuse | ✅ |
| engine C | none/offline → skip w/ notice | mirrors 1C Context7 degrade (`phase-1c` L34) | reuse | ✅ pattern |

Tested/observed cell today: **none** — Trigger 0 is entirely net-new; nothing in the repo references
`trigger 0`, `pre-brainstorm`, `docs/superpowers/recon`, `phase-0`, `deep_research`, or `batch_elicitation`
(grep clean outside the spec). Every gate above is authored from scratch except the two reuse patterns.

### 1b. Batched-elicitation gate (spec §"When to batch") — all three must hold

| Condition | Source of truth | Exists? |
|---|---|---|
| ≥3 independent questions accumulated | agent judgment (dependent-vs-independent rule) | ❌ new doc `brainstorm-elicitation.md` |
| user already accepted Visual Companion | upstream `superpowers:brainstorming` state (`$STATE_DIR/events`) | ✅ upstream-owned, read-only |
| `brainstorm.batch_elicitation != false` | `.claude/compound-v.json` | ❌ new key |

### 1c. Config-shape matrix — the two files `/v:init` writes (v2.6.2 committed-vs-machine-local split)

| New setting | File | Committed? | Slots beside | Default |
|---|---|---|---|---|
| `brainstorm.deep_research` (`ask\|auto\|off`) | `.claude/compound-v.json` | ✅ team policy | `memory`, `epic`, `review` blocks (v-init L273-293) | `"ask"` |
| `brainstorm.batch_elicitation` (bool) | `.claude/compound-v.json` | ✅ team policy | same block | `true` |
| `deep-research` presence | `~/.claude/compound-v-capabilities.json` | ❌ machine-local | `context7`, `workflows` (v-init L341-350) | probed |

The split is load-bearing (v2.6.2 incident): capability = machine-local (uncommitted), policy = committed.
`deep_research`/`batch_elicitation` are **policy** → 4a; `deep-research` skill **presence** is **capability** → 4b.
Putting the presence flag in 4a would re-open exactly the v2.6.2 bug.

---

## 2. Shared State

**`brainstorm.deep_research` / `brainstorm.batch_elicitation` (in `.claude/compound-v.json`)**
- Set in: `commands/v-init.md` Step 4a (new question in Step 3, new key in the JSON at L273-293).
- Read by: `phase-0-recon.md` (gate 3, deep_research) and `brainstorm-elicitation.md` (batch gate cond 3).
- Fallback when absent: defaults `"ask"` / `true` — both new docs MUST hardcode the default so a config
  written before this release (no `brainstorm` block) still resolves. There is **no** JSON schema file
  and **no** validator for `.claude/compound-v.json` (grep: only prose docs describe it), so a missing key
  is silently `undefined` — the reader owns the default, nothing else will.

**`deep-research` capability (in `~/.claude/compound-v-capabilities.json`)**
- Set in: `v-init.md` Step 1 (new detection sub-step) → Step 4b JSON (L341-350).
- Read by: `phase-0-recon.md` engine selection (engine A). But note the degrade ladder already tolerates
  absence at runtime (checks the available-skills listing directly, like 1C checks Context7 tools), so this
  flag is an **advisory cache**, not a hard gate — the reader must not treat a stale/absent flag as "off."

**SKILL.md `description` frontmatter (L3)** — 410 chars today, lint hard-fails > 500 (see §5).
- Read by: the parent agent's trigger recognition AND `scripts/lint-frontmatter.py` (CI).
- Adding the Trigger-0 clause consumes ~90 chars of the remaining headroom. This is a real budget, not free.

**Version string `2.6.4`** — lives in THREE places that must move together:
`.claude-plugin/plugin.json` `.version`, `.claude-plugin/marketplace.json` `.plugins[superpowers-v].version`,
and `CHANGELOG.md` top heading `## [2.6.4]`. Today CI enforces only the **first two** in lockstep
(validate.yml L43-52). The spec's new guard adds the **third**. (Working tree note: `git status` showed both
manifests `M`, but `git diff` is empty — no pre-existing bump; both are at 2.6.4.)

**Banner text (`hooks/session-banner.sh` L15)** — a hardcoded English string describing the pipeline.
Read by: every session start. It currently claims *"Auto-fires after brainstorming … Phases: code-archaeologist
+ domain-expert + doc-validator …"* — with Trigger 0 firing **before** brainstorming, this string is
factually incomplete (see §3 + §5).

---

## 3. Sibling Code

### 3a. `skills/compound-v/SKILL.md` — the central surface (all AC #1 edits land here)
- **description (L3):** `"Use when superpowers:brainstorming has produced a spec, OR … OR … . Sidekick that
  intercepts these three Superpowers transitions …"`. Trigger 0 makes this **four** interception points and
  the "has produced a spec" framing (transition *out of* brainstorming) must gain the transition *into* it.
- **When This Skill Fires (L59-83):** mermaid (L61-73) starts at `A[brainstorming completes spec]`; Trigger
  0 needs a node **upstream** of `A`. Prose triggers are Trigger 1 (L75), 2 (L80), 3 (L82) → Trigger 0 slots
  as a new section **above L75**.
- **Overrides table (L88-97):** row 1 (L90) is `Brainstorming → writing-plans (direct)`. AC #1 wants **two
  new rows** (pre-brainstorm recon; batched elicitation) — append at L97.
- **Output Directory Conventions tree (L179-203):** add a `recon/` node under `docs/superpowers/`
  (structurally a new top-level sibling of `archaeology/`, `expert/`, …).
- **Integration table (L232-243):** row `superpowers:brainstorming` (L234) says *"Run unchanged. On
  completion, fire Trigger 1."* — Trigger 0 fires **before** it runs; this row (or a new one) must say so.
- **Auto-fire caveat (L46):** names the two helper hooks and the description-driven reliability caveat.
  Trigger 0 inherits the **same** caveat (spec non-goal §1). **Latent asymmetry (flag):** the caveat lists a
  `PostToolUse` plan-saved nudge as reinforcement — but Trigger 0 fires when **no file has been written yet**,
  so no `PostToolUse` hook can back it up (see 3d). Trigger 0 is description-driven with **zero hook
  backstop**, weaker than Triggers 1–3. The caveat text should not imply otherwise.

### 3b. `phase-1b-domain-expert.md` — the recon-read insertion (AC #5)
- KB-first step is **step 2, L53**: *"Check the knowledge base at `…/expert/_knowledge-base/<domain>.md`."*
  The dispatch rule at L48 also passes the KB path. The recon-read line ("check `docs/superpowers/recon/`
  for a matching topic before opening new searches; deepen, don't repeat") slots cleanly **between L53 and
  the web-search step L54**. Clean, symmetric insertion.

### 3c. `phase-1c-documentation-validation.md` — the recon-read insertion (AC #5)
- **Asymmetry with 1B:** 1C has **no explicit "read KB first" numbered step**. Its subagent steps (L46-62)
  jump straight to *step 1 "Extract every library/version mention"* (L46); KB reuse is only described later
  in prose ("Persistence" L128-135). So the recon-read line here is a slightly larger insertion — a new
  step **before L46** ("check `docs/superpowers/recon/` for the topic first"). Do not assume 1C mirrors 1B's
  step numbering; it does not.

### 3d. Hooks — the reinforcement surface
- `hooks/session-banner.sh` **L15**: banner string is pipeline-stale under Trigger 0 (see §2). Also appends a
  `/v:init` first-run hint (L21-23) and an onboard-staleness nudge (L27-32) — unaffected.
- `hooks/plan-saved-nudge.sh`: `PostToolUse(Write)` with two arms — `*/docs/superpowers/plans/*.md` (L25) and
  `*/docs/superpowers/specs/*.md` (L28). **No arm fires before brainstorming** (nothing is written then), so
  Trigger 0 cannot be hook-reinforced the way Triggers 1–3 are. An **optional** new arm
  `*/docs/superpowers/recon/*.md` could nudge "recon saved → start brainstorming with it," but that fires
  *after* recon completes, not before the brainstorm begins — it does not solve the pre-fire gap.
- `hooks/hooks.json`: `memory-refresh.sh` is appended to both `SessionStart` and `PostToolUse(Write)` — so a
  committed recon doc under `docs/superpowers/**` is auto-indexed into V-memory FTS5 on the next Write hook,
  which is exactly what makes future brainstorms hit gate 2 (spec §"Output contract" L76-77). No change needed
  for that to work; the un-ignore reality (§8) is what keeps it tracked.

### 3e. CI version lockstep — `.github/workflows/validate.yml`
- **L43-52** "Verify plugin.json and marketplace.json versions match" is the existing lockstep step (jq-based
  shell). The CHANGELOG guard (AC #6) attaches as a **new step adjacent to it**, jq/grep, **not** in
  `lint-frontmatter.py` (that script is frontmatter-only; see §5). **Latent gap this closes:** the current
  step compares the two manifests **against each other only** — so a release where both stayed at the old
  version (v2.6.4's own bug) passes green. The guard must anchor to CHANGELOG's newest heading.

### 3f. Memory engine — `scripts/compound-v-memory.py`
- Gate-2 recall uses the **`search`** subcommand (argparse L1280-1286):
  `search "<query>" [--top N=8] [--intent planning|review] [--json] [--no-embed]` → agent-ready context
  pack (or `--json`). `/v:remember` calls exactly `search "{{args}}" --top 8` (v-remember.md L10). **Do not**
  confuse with `recall-check --files …` (L1288-1293) — that is the routing-tighten bridge, a different
  contract, and recon must never touch routing (AC #8).

---

## 4. External APIs (via context7)

**No third-party API is introduced by this feature.** Trigger 0's engines are (a) the **bundled
`deep-research` skill** (in-repo/plugin, manages its own subagents — not a network SDK) and (b) **WebSearch**
(harness-native). The elicitation surface is **upstream Superpowers' Visual Companion** (reused as-is, spec
non-goal §"No new server"). V-memory is local (`compound-v-memory.py`, stdlib). Context7 itself is unchanged.
Therefore a Context7 library-currency lookup has **no applicable target** here — the only "contracts" are
in-repo:

- **`deep-research` skill contract:** invoked by name from the available-skills listing (degrade-safe, like
  1C's Context7-tool check). No version pin, no API signature — it is a skill, not a library.
- **Upstream Visual Companion contract:** answers read from `$STATE_DIR/events` merged with the terminal
  reply (spec §Feature 2). This is **upstream-owned** state; treat it as read-only and do not re-implement it.

Recording "no external API" is itself the finding: 1C (the library validator) will have little to validate
for this feature beyond confirming `deep-research`/`playground` are present as skills, not packages.

---

## 5. Regression Surface

| Path that works today | Breaks if… | One-line impact |
|---|---|---|
| CI dead-link scan (validate.yml L170-194) | SKILL.md links to `phase-0-recon.md` / `brainstorm-elicitation.md` before those files exist | red CI; couples the doc edits to the two new files landing in the **same** merge (integration-order constraint). |
| `lint-frontmatter.py` desc check (L66-70) | SKILL.md `description` exceeds 500 chars after adding the Trigger-0 clause | **CI FAILS** — the "soft" max appends an issue → `total>0` → `exit 1`. Only ~90 chars of headroom (410/500). Despite the "soft" label it is a hard gate. |
| Existing version lockstep (validate.yml L43-52) | CHANGELOG guard is written to parse a heading format that doesn't match | guard false-fails every future release; must match the exact pattern (§below). |
| Scope gate `git ls-files --others --exclude-standard` (backend-launcher) | a `.gitignore` rule were added that shadows `docs/superpowers/recon/` | gate would go blind to recon writes — see §8 (currently NOT a risk; recon/ is not ignored). |
| `session-banner.sh` factual accuracy | banner left unchanged | not a crash, but the banner now mis-describes the pipeline (omits pre-brainstorm recon) — a correctness/honesty regression per the anti-fabrication charter. |
| Anti-ruflo metrics gate (validate.yml L127-150) | recon docs or new phase docs print token/cost numbers | red CI; recon output (spec §Bounds "≤150 lines") must state findings, never fabricated cost. |
| `.claude/compound-v.json` readers (resolver, epic, review) | new `brainstorm` block malforms the JSON | every consumer of that file `jq`-fails; the block must be additive and valid. No validator guards this file. |

**CHANGELOG newest-heading pattern (regex-able, for the guard):** headings are
`## [2.6.4] — 2026-07-10` — i.e. `^## \[(\d+\.\d+\.\d+)\] — \d{4}-\d{2}-\d{2}$`. **The separator is an
em-dash `—` (U+2014), not a hyphen** — a guard written with `-` will never match. "Newest" = the **first**
such line top-to-bottom (`grep -m1 -oE '^## \[[0-9]+\.[0-9]+\.[0-9]+\]'`), compared to `jq -r .version
.claude-plugin/plugin.json`.

---

## 6. DRY Findings

1. **`skills/compound-v/skill-escalation.md` already governs `deep-research`** (L21: gated escalation "a
   load-bearing planning decision is genuinely uncertain … **beyond** what pre-flights 1B/1C already
   resolved"; L49 example; L62 "escalates *past* 1B/1C, not instead of them"). Trigger 0 invokes the **same
   skill** at a **different, earlier** point (before brainstorming, before 1B/1C even exist) for a different
   purpose (grounding the brainstorm, not resolving a planning unknown). This is a **genuine contradiction to
   reconcile, not a silent third path**: skill-escalation.md currently asserts deep-research only fires
   *after/past* 1B/1C — Trigger 0 fires *before* them. **Decision for the plan: EXTEND `skill-escalation.md`**
   (add a "recon / Trigger 0" row or a note that recon is an earlier, gated deep-research use with its own
   logging discipline) so the two docs don't contradict. Do not leave skill-escalation.md claiming
   deep-research is post-1B/1C only.
2. **Recall check — reuse `search`, do not invent.** Gate 2 is exactly `compound-v-memory.py search`
   (§3f). No new recall code; `/v:remember` is the existing front door.
3. **Plumbing-skip rule already exists** (1B skip L30-39; SKILL skip L131-134). Trigger 0's gate 1 should
   reuse that classification wording, not define a competing one.
4. **Degrade-safe engine pattern already exists** (1C Context7 → WebSearch, `phase-1c` L34). Trigger 0's
   engine ladder (deep-research → WebSearch → skip-with-notice) is the same shape — mirror it, don't
   reinvent.
5. **Version guard — extend the existing CI step**, don't add a parallel workflow (§3e).

No unjustified duplication is being introduced provided the plan follows the "extend" decisions above.

---

## 7. Design constraints for the spec (MUST-HANDLE — non-negotiable)

1. **SKILL.md `description` MUST stay ≤ 500 chars** after adding the Trigger-0 clause (410 now; `lint-frontmatter.py`
   hard-fails CI above 500 despite the "soft" label). Budget the wording.
2. **`brainstorm.deep_research` / `batch_elicitation` are COMMITTED policy → Step 4a**; **`deep-research`
   skill presence is MACHINE-LOCAL capability → Step 4b.** Reversing this re-opens the v2.6.2 incident.
3. **Both new config keys MUST default in the reader** (`deep_research="ask"`, `batch_elicitation=true`) —
   a pre-v2.7 config has no `brainstorm` block and nothing validates that file.
4. **Recon output is EVIDENCE for the brainstorm, NEVER a routing input** (AC #8; same boundary as V-memory).
   Use `search`, never `recall-check`, and never let recon touch model/backend selection.
5. **Recon docs MUST be committed** to `docs/superpowers/recon/YYYY-MM-DD-<topic>.md` (v2.6.4 write-then-commit
   discipline) or they vanish on worktree cleanup and never index into V-memory.
6. **The two new phase files MUST land in the same merge as the SKILL.md links to them** — CI dead-link scan
   (validate.yml L170-194) fails otherwise. Same for any link inside the new docs.
7. **CHANGELOG guard MUST match `^## \[(\d+\.\d+\.\d+)\] — …`** (em-dash, first-match-wins) and compare to
   `plugin.json .version`; attach it beside the existing lockstep step, not in the frontmatter linter.
8. **Version MUST move in all three places** (plugin.json, marketplace.json, CHANGELOG top) to 2.7.0 — the
   new guard makes CHANGELOG part of lockstep.
9. **`skill-escalation.md` MUST be reconciled** with Trigger 0's earlier deep-research use (§6.1) — its "past
   1B/1C only" claim currently contradicts a pre-brainstorm recon.
10. **1C's recon-read insertion is larger than 1B's** — 1C has no existing "read KB first" step to hang it on
    (§3c). Plan for a new step, not a one-line append.
11. **Trigger 0 has no hook backstop** (§3d) — it is description-driven only, weaker than Triggers 1–3. The
    SKILL auto-fire caveat and the banner MUST NOT imply hook reinforcement exists for it.
12. **No token/cost numbers** in recon output or new docs (anti-ruflo CI gate L127-150).
13. **No upstream file edits, no new server, no new agent** (spec non-goals; keeps CI's agent-frontmatter
    and no-Haiku gates untouched — no `agents/*.md` added).

---

## 8. `.gitignore` reality for `docs/superpowers/recon/`

`git check-ignore -v docs/superpowers/recon/2026-07-10-foo.md` → **exit 1, no match**: recon/ is **NOT
ignored** by any rule. The ignore list is `.DS_Store`, `*.log`, `node_modules/`, `.env`, `.env.local`,
`docs/superpowers/_runs/`, `.worktrees/`, `/compound-v/`, `.job_result.txt` — none shadow `recon/`. The
explicit un-ignore rules `!docs/superpowers/execution/` (L21) and `!docs/superpowers/memory/` (L22) exist
because *those* directory names were at risk of a broad ignore; `recon/` is not. **Therefore no `.gitignore`
change is required** for recon docs to be tracked and for the scope gate
(`git ls-files --others --exclude-standard`) to see them. An explicit `!docs/superpowers/recon/` is
**optional** defense-in-depth for parity with execution/ and memory/ — reality-only: not needed today.

---

## FILE TOUCH MAP (for Phase 2 partitioning)

**CREATE**
- `skills/compound-v/phase-0-recon.md` — new: full Trigger 0 procedure (gate order, engine ladder, bounds, output contract, recon≠pre-flight, 1B/1C reuse) [AC #2].
- `skills/compound-v/brainstorm-elicitation.md` — new: dependent-vs-independent rule, 3-condition batch gate, Visual-Companion reuse, events-file read, fallback ladder [AC #3].
- `docs/superpowers/recon/` — runtime output dir (created when Trigger 0 first fires; no source file to author unless a `.gitkeep` is desired). Not ignored (§8).

**MODIFY**
- `skills/compound-v/SKILL.md` — `SHARED RESOURCE` (central doc + cross-ref target; CI dead-link scan couples it to the two new phase files). Edits: description L3, When-Fires + mermaid L59-83, overrides table +2 rows L88-97, dir tree +recon/ L179-203, integration table brainstorming row L234, auto-fire caveat L46.
- `skills/compound-v/phase-1b-domain-expert.md` — add recon-read step between L53 and L54 [AC #5].
- `skills/compound-v/phase-1c-documentation-validation.md` — add recon-read step before L46 (larger insert; no existing KB-first step) [AC #5].
- `skills/compound-v/skill-escalation.md` — reconcile the `deep-research` row/L62 with Trigger 0's earlier use (DRY §6.1).
- `commands/v-init.md` — `SHARED RESOURCE` (documents the JSON schemas both new docs read). Edits: new deep-research capability detect in Step 1; `brainstorm.*` policy questions in Step 3; `brainstorm` block in Step 4a JSON (L273-293); `deep-research` flag in Step 4b JSON (L341-350) [AC #4].
- `hooks/session-banner.sh` — banner string L15 (pre-brainstorm recon now part of the pipeline).
- `hooks/plan-saved-nudge.sh` — OPTIONAL new `recon/` arm (fires after recon, not before brainstorm; does not close the pre-fire gap).
- `.github/workflows/validate.yml` — `SHARED RESOURCE` (CI config; the guard gates every task's version edits). New CHANGELOG↔plugin.json step beside L43-52 [AC #6].
- `.claude-plugin/plugin.json` — `SHARED RESOURCE` (version string read by CI lockstep + new guard). 2.6.4 → 2.7.0 [AC #6].
- `.claude-plugin/marketplace.json` — `SHARED RESOURCE` (version lockstep with plugin.json). 2.6.4 → 2.7.0 [AC #6].
- `CHANGELOG.md` — `SHARED RESOURCE` (new CI guard parses the top `## [x.y.z]` heading; newest MUST stay on top). Add `## [2.7.0] — 2026-07-10` entry [AC #6].
- `AGENTS.md` — L7 ("three Superpowers phase transitions") + L9 ("Three parallel pre-flights") updated for Trigger 0 [AC #7].
- `README.md` — L66 ("start brainstorming as usual — Compound V takes over…") to mention pre-brainstorm recon; L15 game-tutorial "three scouts" line OPTIONAL [AC #7].
- `.gitignore` — OPTIONAL `!docs/superpowers/recon/` parity rule; NOT required (§8).
