# Recon — FTS5 Cyrillic/multilingual tokenizer options for V-memory (2026-07-11)

*This recon is evidence to widen the brainstorm's questions, not a conclusion to converge on. VERIFIED FACTS / CONSTRAINTS are provisionally binding (1B/1C revalidate); UNVERIFIED LEADS are questions until validated; SUGGESTED DIRECTIONS are read last (directions-late) and are some of several possibilities — generate alternatives that ignore them.*

Engine: B (3 parallel WebSearch, one message). Scope (narrowed at the offer): unicode61 options + trigram alternative + stemming extensions for Cyrillic queries in V-memory's FTS5 lane.

## QUESTIONS TO ASK

Framed as mistakes-to-avoid:
- Don't reach for stemming before measuring: what share of real `/v:remember` queries are Cyrillic, and how many currently miss? (No baseline = no problem statement.)
- Don't silently break the pure-stdlib invariant (V-memory PRD invariant: CORE lane = zero new dependencies): any loadable-extension option changes the product's contract, not just an index setting.
- Don't ignore the DENSE lane: multilingual-e5-small already handles Cyrillic semantically — is the perceived gap actually in the FTS5 lane, or in dense-lane adoption (opt-in, rarely bootstrapped)?
- Don't tune tokenizers without a re-index plan: tokenizer changes invalidate the existing FTS5 index (rebuild required, drift-detection interaction).

## VERIFIED FACTS / CONSTRAINTS

- [F1] FTS5 ships four built-in tokenizers: `unicode61` (default), `ascii`, `porter`, `trigram`. `unicode61` tokenizes per Unicode 6.1 categories — Cyrillic characters are token characters by default, so whole-word Cyrillic matching already works; options `remove_diacritics` and `tokenchars` tune it.
- [F2] The built-in `porter` stemmer is English-only — it gives zero stemming benefit for Russian morphology (which is the actual recall gap for inflected Cyrillic queries).
- [F3] The built-in `trigram` tokenizer enables substring/LIKE-style matching and works on arbitrary scripts, at the cost of a substantially larger index; known weakness on CJK single-character words (community forks exist).

## UNVERIFIED LEADS

- [L1] `fts5-snowball` (abiliojr) — loadable FTS5 tokenizer wrapping Snowball stemmers incl. Russian; maintenance currency and macOS load-path story unverified.
- [L2] `sqlite3-unicodesn` (illarionov) — unicode tokenizer + Snowball stemming incl. Russian; same verification needed.
- [L3] Community reports (HN thread) suggest non-English FTS5 quality varies mostly by tokenizer choice, not FTS5 core — worth validating against our corpus before believing.

## SUGGESTED DIRECTIONS

Some of several possibilities — non-exhaustive; generate alternatives that ignore them:
- D1 — Stay pure-stdlib: tune `unicode61` (`remove_diacritics 2`, add `tokenchars` for `-`/`_` identifiers) + document that Russian *stemming* is out of scope for the lexical lane; lean on the DENSE lane for morphology.
- D2 — Switch the FTS5 lane to `trigram` for typo/substring tolerance across scripts; pay the index-size cost; keep stdlib purity.
- D3 — Optional loadable Snowball tokenizer behind the same opt-in pattern as the dense lane (off by default, degrade-safe) — best Russian recall, but a real dependency-contract change.

## SOURCES

- [F1][F3] https://www.sqlite.org/fts5.html (accessed 2026-07-11) — tokenizer list, unicode61 options, trigram semantics.
- [F2] https://www.sqlite.org/fts5.html + https://github.com/abiliojr/fts5-snowball README (accessed 2026-07-11) — porter=English; Snowball adds Russian.
- [L1] https://github.com/abiliojr/fts5-snowball · [L2] https://github.com/illarionov/sqlite3-unicodesn · [L3] https://news.ycombinator.com/item?id=41199200 (all accessed 2026-07-11).
