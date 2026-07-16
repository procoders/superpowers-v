# Decision **memory + challenge** — falsifiable past-reasoning aid (v2.16)

> *"A-Train can tell you which way you ran last time. He can't tell you it's the right way to run now — and Compound V makes him say so out loud, every time."*

This doc is the harness-neutral authority for the decision-preference surface: a way for the maker to
**recall their OWN dated past reasoning** at a brainstorm fork, pulled on demand, and **always paired with a
divergent challenge**. Every surfacing is a *doubt amplifier*, not a nudge. The spine is
`scripts/compound-v-preferences.py`; the elicitation wiring is [brainstorm-elicitation.md](brainstorm-elicitation.md);
the operator surface is `/v:preferences` ([commands/v-preferences.md](../../commands/v-preferences.md)). The
authoritative design is the spec [`docs/superpowers/specs/2026-07-15-v2.16-decision-preferences-design.md`](../../docs/superpowers/specs/2026-07-15-v2.16-decision-preferences-design.md),
grounded in the Phase-1B domain audit [`docs/superpowers/expert/2026-07-16-v2.16-decision-preferences.md`](../../docs/superpowers/expert/2026-07-16-v2.16-decision-preferences.md).

---

## 1. The framing — memory + challenge, NOT "reason as the creator"

This feature helps the maker **remember what they decided before**, as *falsifiable history*. It does **not**
model the maker's judgment and reason on their behalf. The domain audit rated the "let the brainstorm reason
as Oleg" framing high-hazard on three independent grounds ([audit §3 F-F](../../docs/superpowers/expert/2026-07-16-v2.16-decision-preferences.md)):
it **manufactures** preferences (constructed-preference theory: a rationale you're asked to articulate can
cement a taste that never existed), it builds an **echo chamber** (the Lock-in Hypothesis loop:
capture → distill → recall → capture produces measurable diversity collapse), and it **opposes this project's
own moat** — cross-vendor verification and anti-anchoring recon, both of which exist to *resist* convergence
on one mind's blind spots. The user chose the memory+challenge framing; this feature builds only that.

The load-bearing invariant that turns "more Oleg" into "challenge Oleg": **every surfaced past decision is
emitted with a mandatory divergent counter-move** — an explicit "…but this time may differ because…", an
option you did *not* take last time, or a reason the past choice could be wrong. A recall that cannot produce
a genuine divergent counter is **suppressed**, never shown bare. In the spine this is enforced, not aspired:
`recall(...)` (`scripts/compound-v-preferences.py:328`) returns `shown:false, suppressed_reason:"no-challenge"`
when `build_challenges(...)` yields nothing (`:396-400`), and `marked_option` can only exist on a `shown:true`
recall that already carries a non-empty `challenge`.

---

## 2. A MARK is allowed; a pre-TICK is not (the audit's red line)

The dark pattern the audit forbids is the **pre-selected default** — an option already chosen that the human
must actively *un-choose*. The default effect is large and well-documented (retirement enrollment 49%→86% on
which box was pre-checked; [GDPR Recital 32](../../docs/superpowers/expert/2026-07-16-v2.16-decision-preferences.md)
names a pre-ticked box invalid consent). v2.16 **never** does that: no option is ever pre-selected, and the
human always chooses from a neutral state.

What v2.16 *does* allow (only in `marked` mode, below) is a **falsifiable, dated MARK** on the option matching
the past pattern — a soft, low-urgency **label** beside a **neutral** option:

```
↩ your past pick: 4/5 · 2026-07-14
```

The distinction is the whole design:

| | A **MARK** (allowed) | A **pre-TICK** (forbidden) |
|---|---|---|
| What it is | Information beside a neutral choice | An answer you must override |
| Rendered state | Nothing selected; human picks from zero | The option sits pre-selected as the resting state |
| Urgency | Soft, dated, falsifiable ("↩ 4/5 · date") | The status-quo the human bears the effort to leave |
| Paired with | The mandatory divergent challenge, always | (n/a — it *is* the nudge) |

A mark is a `marked_option` object `{option, count, sample_n, date, badge}` — count and date only, **never** a
`chosen`/`selected`/`default` field, **never** a recommendation, **never** a confidence `%`. The renderer
places the badge next to the option on the *normal* surface; the human still picks every option from a neutral
state. The badge and the challenge always render **together** — a mark can never appear without its
counter-move (`scripts/compound-v-preferences.py:419-429`).

---

## 3. Three modes — default is the least intrusive

Config key **`brainstorm.preferences`** in `.claude/compound-v.json`, resolved by
`resolve_brainstorm(cfg)` in `scripts/compound-v-project-config.py` (default `"on-demand"`, valid set
`{off, on-demand, marked}`, coerce-and-warn, never raise). The spine's `--mode` mirrors these
(`VALID_MODES = ("off", "on-demand", "marked")`, `scripts/compound-v-preferences.py:108`):

- **`off`** — nothing. `recall(...)` returns `shown:false, suppressed_reason:"mode-off"` (`:348-350`). The
  surface does not exist for this session.
- **`on-demand`** (**default**) — the human/driver **PULLS** history ("have I decided something like this
  before?"); no unsolicited surface, and `marked_option` is returned `null` even when a matching pattern
  exists (`:419-421` guards on `mode == "marked"`). A pull can't nudge: it surfaces the dated evidence and its
  challenge, never a mark.
- **`marked`** — at a *qualifying* fork the past-matching option additionally carries the dated badge, **always
  rendered together with the mandatory divergent challenge**, **never pre-selected**. A mark also needs a real
  pattern: dominant count `>= MARK_MIN_COUNT` (2 — "two is a pattern", `:103`, `:421`).

In every mode the surface is **suppressed** on recon/high-novelty forks and **demoted** on drift (§5).

---

## 4. The "why" is captured UNPROMPTED and never fabricated

Choice-blindness research shows a human will fluently confirm a rationale that isn't theirs — a *confirm*
click does not launder a system-authored reason into fact ([audit §3 F-A](../../docs/superpowers/expert/2026-07-16-v2.16-decision-preferences.md)).
So the `why` is captured **free-text first**:

1. On capture, the human writes their rationale in free text, or explicitly skips → `why:null`,
   `why_class:"none"` (`scripts/compound-v-preferences.py:446-447`).
2. Candidate rationales may be offered **only afterward**, labeled *"not your words — rationales from earlier
   forks, for reference."* A tapped candidate is stored as a distinct, weaker class `why_class:"borrowed"`
   (`:448-449`, `:673-674`).
3. **Borrowed whys are excluded** from the "your reasoning" display: `recall` only surfaces a `why` when
   `why_class == "unprompted"` (`:411-412`), and `distill` clusters only unprompted whys into the committed
   distillate (`:573`). A borrowed reason is reference, never "your rationale."

A rationale is **never inferred**. A system-authored reason with a rubber-stamp is the exact ruflo the charter
forbids.

---

## 5. Anti-anchoring, drift honesty, anti-ruflo

**Never fires where recon widens.** Trigger-0 recon *widens* a brainstorm; preference recall *narrows* toward
past choices. The two must never co-fire on one fork — a rhetorical "aligned, not against" is not enough, so
suppression is structural ([audit §3 F-D](../../docs/superpowers/expert/2026-07-16-v2.16-decision-preferences.md)):

- **Recon-touched fork** → `shown:false, suppressed_reason:"recon-touched"` (`:352-355`). Pass this flag
  whenever Phase-0 recon touched the current fork this session ([phase-0-recon.md](phase-0-recon.md)).
- **High-novelty fork** — no FTS5 match, or top similarity below the novelty floor →
  `shown:false, suppressed_reason:"high-novelty"` (`:361-364`). A novel fork is exactly where recon widens;
  preferences stay silent.

**Drift, measured honestly (all modes).** Recency-weighted **last-K** disagreement, not an all-time override
ratio (a lifetime ratio makes stale tastes sticky; a genuine change of mind must move fastest):

- `disagreement_rate` = fraction of the last `DRIFT_K` (5) similar forks where `changed_after_recall == true`,
  or — on a clean holdout — where the un-nudged choice diverged from the dominant pattern (`:384-388`,
  `disagreement(...)`). A rate `>= DRIFT_DEMOTE_THRESHOLD` (0.5) **demotes** the pattern (stops surfacing) and
  banner-flags it: `shown:false, suppressed_reason:"demoted"` with a `banner` (`:389-394`).
- **Holdout probe (clean signal).** A deterministic fraction of qualifying forks is **held out** — recall is
  deliberately suppressed (`shown:false, suppressed_reason:"holdout"`, `:371-374`) and the caller records the
  human's *un-nudged* choice (`--holdout` on capture). A surfaced choice is a possibly-nudged, possibly
  learned-helpless sample; the holdout is the uncontaminated drift estimate the surfaced ones can't give.
- **Auto-expiry.** A pattern not confirmed within `STALENESS_DAYS` (180) stops surfacing →
  `shown:false, suppressed_reason:"expired"` (`:376-382`), until refreshed by new decisions.

All thresholds (`MARK_MIN_COUNT`, `NOVELTY_FLOOR`, `DRIFT_K`, `DRIFT_DEMOTE_THRESHOLD`, `STALENESS_DAYS`) are
**documented conservative heuristics, config/CLI-tunable, never presented as measured confidence**
(`scripts/compound-v-preferences.py:103-108`).

**Anti-ruflo:** counts only (`4/5 similar forks`), **never a fabricated `%`** — no output string carries a
literal `%`. Drift and staleness are surfaced (banner-flagged), never hidden.

---

## 6. Split storage — raw local, distillate in-repo

Two stores, deliberately different in trust and reach:

- **Raw `decisions.jsonl` → LOCAL, private, never shipped.** Lives under
  `~/.claude/compound-v/preferences/` (overridable via `--home-root` / `COMPOUND_V_PREFS_HOME`). It holds the
  full free-text `why` + question context — the PII-prone part. Git distribution would egress it, so it stays
  out of the committed tree (the v2.6.2 precedent: machine-local personal data never ships). One command,
  `/v:preferences purge`, wipes it (`purge(...)`, `:624`). Live fork-matching reads this file directly via
  an **in-process FTS5** index (reusing V-memory's crash-safe `fts5_escape`), so `capture` → `recall` is
  immediate — no reindex, no shared-corpus dependency.
- **Distilled `preferences.md` → IN-REPO, git-tracked → V-memory-indexed.** Lives at
  `docs/superpowers/preferences/preferences.md`, regenerated by `distill`. It carries per-pattern dominant
  choice, the **unprompted** rationales verbatim, sample size, `first_seen`/`last_confirmed`/`expires_at`, and
  the recency-weighted disagreement rate with a stale/demoted banner. Because it is tracked, `/v:remember`
  surfaces it via the CORE FTS5 lane ("all in one memory") — see [memory.md](memory.md).

**Secret + PII scrub before the in-repo write.** `distill` runs the reused `SECRET_RE`/`PEM_RE` + a light
`PII_RE` (email / SSN-shaped / card-shaped) and **redacts any flagged content BEFORE writing the committed
MD**. The local jsonl keeps the full text; the shipped distillate never carries a flagged token. Honest caveat
to state plainly: **the scrubbed distillate DOES ship with the plugin** — that is the deliberate tradeoff the
user chose (the useful aggregated model is shared; the raw log is not).

Each pattern carries `first_seen` / `last_confirmed` / `expires_at`; stale patterns are banner-flagged, never
silently trusted. This is the digital-twin minimum bar the audit set: dated, bounded, purgeable, owned by the
maker ([audit §3 F-E](../../docs/superpowers/expert/2026-07-16-v2.16-decision-preferences.md)).

---

## 7. The contract — `recall` / `capture` (freeze this shape)

`recall(question, options, context_tags, mode, ...)` returns (JSON on the `recall` subcommand):

```json
{
  "shown": true,
  "mode": "marked",
  "evidence": [{"date": "2026-07-14", "question": "…", "chosen": "safe default + opt-in",
                "why": "safer default; user owns the risk", "why_class": "unprompted"}],
  "challenge": ["…but this fork may differ because …", "an option you did not take last time: …"],
  "marked_option": {"option": "safe default + opt-in", "count": 4, "sample_n": 5,
                    "date": "2026-07-14", "badge": "your past pick: 4/5 · 2026-07-14"},
  "sample_n": 5,
  "disagreement_rate": 0.0, "disagreement_count": 0, "disagreement_window": 0,
  "banner": null,
  "suppressed_reason": null
}
```

- `marked_option` is `null` in `off`/`on-demand`, and in `marked` only when the pattern qualifies. It is a
  **LABEL** (`option` + `count`/`sample_n` + `date` + `badge`) — never a selection, no `chosen`/`default` key.
- `suppressed_reason` ∈ `{null, "mode-off", "recon-touched", "high-novelty", "holdout", "expired",
  "demoted", "no-challenge"}`. When set, `shown` is `false`.
- `challenge` is non-empty on every `shown:true` recall (and thus beside every `marked_option`).

`capture(...)` (subcommand `capture`) appends one fork outcome to the local raw jsonl via `append_line`
(secret/PII-scan first). Key flags: `--question`, `--chosen`, `--option` (repeatable), `--why` (omit ⇒
`null`), `--why-class {unprompted,borrowed}`, `--recall-shown`, `--challenged`, `--changed-after-recall`,
`--suppressed-reason`, `--holdout`. The record schema (`scripts/compound-v-preferences.py:436`) carries
`id, captured_at, question, context_tags, options, chosen, why, why_class, recall_shown, challenged,
changed_after_recall, suppressed_reason` — `changed_after_recall` is the clean drift signal (did the human
choose *differently* than their own past pattern).

---

## 8. Cross-references

- Spine (authoritative behavior + `--selftest`): `scripts/compound-v-preferences.py`
- Elicitation wiring (PULL at the pre-fork checkpoint, `capture` at reconciliation): [brainstorm-elicitation.md](brainstorm-elicitation.md)
- Operator surface (`stats` / `distill` / `purge`): `/v:preferences` — [commands/v-preferences.md](../../commands/v-preferences.md)
- Config resolver (`resolve_brainstorm`, default `on-demand`): `scripts/compound-v-project-config.py`
- V-memory pickup of the in-repo distillate: [memory.md](memory.md)
- Anti-anchoring sibling this must never co-fire with: [phase-0-recon.md](phase-0-recon.md)
- Design authority + red lines: [spec](../../docs/superpowers/specs/2026-07-15-v2.16-decision-preferences-design.md), [1B domain audit](../../docs/superpowers/expert/2026-07-16-v2.16-decision-preferences.md)
