# 0001. V-memory's always-on recall lane uses SQLite FTS5, not a vector database

- **Status:** Accepted
- **Date:** 2026-07-11
- **Deciders:** Compound V V-memory design (v2.0)

## Context

Compound V needed a **recall layer** over its own prose — the specs, plans, reviews, archaeology,
recon, and routing lessons that accumulate under `docs/superpowers/**` — so that a question like
"have we hit this before?" could be answered from past work rather than re-derived. (Engine:
[`scripts/compound-v-memory.py`](../../../scripts/compound-v-memory.py); authority doc:
[`skills/compound-v/memory.md`](../../../skills/compound-v/memory.md).)

The constraints were non-negotiable and they are the same discipline as the rest of the toolchain:

- **Local-first and offline.** No recall query may depend on a network round-trip or an external
  service being up.
- **No daemon, no server.** Compound V is a set of scripts and contracts, not a running system. A
  recall lane that requires a background process or a hosted vector store contradicts that shape.
- **Zero new infrastructure and zero new hard dependencies** for the default path. The always-on
  lane had to work on a clean checkout with nothing installed but Python's standard library.
- **Degrade-safe.** Recall is *evidence for planning and review, never a routing input* — so a
  missing or broken optional component must silently fall back, never block or mislead.

The obvious industry default — stand up a vector database (or an embedded ANN index) and embed every
chunk for semantic search — collides with every one of those constraints for the *default* path.

## Decision

**The always-on ("core") recall lane is SQLite FTS5 BM25 over git-tracked prose — pure standard
library — and semantic embeddings are an opt-in, out-of-repo "dense" lane layered on top, never a
requirement.**

Alternatives weighed and declined:

- **An external vector DB service (e.g. a hosted or local server).** Declined: violates
  local-first / no-daemon / no-service. It adds an operational dependency to answer a read-only
  "have we seen this?" query, and it fails closed when the service is down — unacceptable for a lane
  that must always be available.
- **An embedded vector index as the *default* (mandatory embeddings).** Declined as the default: it
  forces a model download and a heavier dependency (`onnxruntime` + tokenizers) onto every user
  before recall works at all. That is the wrong floor. It is instead offered as the **opt-in dense
  lane** — `multilingual-e5-small`, 384-dim, in an isolated venv living **outside** the repo at
  `~/.cache/compound-v/memory/<repo-id>/`, bootstrapped only by an explicit command and rank-unioned
  with FTS5 when present. Absent or broken ⇒ silently FTS5-only.
- **A hand-rolled keyword grep.** Declined: no ranking, no relevance ordering, and it re-invents what
  SQLite's FTS5 already provides (BM25 scoring) with zero dependencies.

FTS5 ships inside Python's bundled SQLite, so the core lane is genuinely dependency-free, instant,
and offline. It indexes **git-tracked** files, which makes "committed = recallable" a clean, honest
boundary.

## Consequences

- **Zero infrastructure, always available.** The default lane needs nothing beyond stdlib — no
  service to run, nothing to install, nothing to keep alive. Recall works on a fresh clone.
- **Degrade-safe by construction.** The optional dense lane can be absent, un-bootstrapped, or
  broken and recall still works; it simply falls back to FTS5-only. No single point of failure.
- **Keyword-not-semantic in the core lane (the real trade-off).** FTS5 BM25 matches terms, not
  meaning — a query phrased differently from the stored prose can miss. This is the price of the
  zero-dependency floor. It is mitigated, *opt-in*, by the dense embeddings lane for users who
  bootstrap it and whose corpus is large enough to matter — but the baseline is deliberately lexical.
- **"Committed = recallable" is a hard edge.** Because the index covers git-tracked files only, an
  uncommitted doc is invisible to recall. That is a feature (no half-written drafts leaking into
  results) but it makes the two-command commit discipline load-bearing: write-then-commit, or the
  artifact never enters memory. (Also why ADRs like this one are recallable only after they are
  committed.)
