#!/usr/bin/env python3
"""
Compound V — Decision **memory + challenge** spine (v2.16, NEW file, stdlib only).

A falsifiable *past-reasoning* aid for a brainstorm fork. It lets the maker RECALL their
OWN dated past decisions on demand and ALWAYS pairs that recall with a divergent CHALLENGE,
so surfacing "you decided X before" triggers re-examination, not confirmation. It is
explicitly NOT "reason as the creator" — no push, no nudge, no pre-select. See the authority
spec docs/superpowers/specs/2026-07-15-v2.16-decision-preferences-design.md.

Subcommands: recall / capture / distill / stats / purge (+ --selftest).

Hard invariants (each mirrors a spec Global Constraint / acceptance criterion):

  * SPLIT STORAGE. The RAW `decisions.jsonl` — the full free-text `why` + question context,
    the PII-prone sensitive part — lives LOCAL under ~/.claude/compound-v/preferences/ and is
    NEVER committed. The DISTILLED `preferences.md` lives IN-REPO
    (docs/superpowers/preferences/) and is written by `distill` ONLY AFTER a secret + PII
    scrub, so the shipped copy never carries a flagged token (the local jsonl keeps the full
    text — that is exactly why the raw log stays local + purgeable).

  * INJECTABLE ROOTS. Both storage roots are overridable by arg/env
    (--home-root / COMPOUND_V_PREFS_HOME for the local dir; --repo-md, or --repo + the default
    docs/superpowers/preferences/preferences.md, for the in-repo distillate) so --selftest
    touches ONLY tmp dirs and never the real ~/.claude or the real repo docs. The build creates
    no real preference data.

  * MEMORY, NOT AUTHORITY — a MARK is allowed, a pre-TICK is not. `recall` NEVER marks an
    option chosen/selected/default in ANY mode. `off` disables; `on-demand` (default) surfaces
    evidence on a PULL only (`marked_option` null — a pull can't nudge); `marked` populates
    `marked_option` as a falsifiable dated LABEL (a badge string with count+date) beside a
    neutral option, never a selection. There is NO field anywhere that marks an option
    chosen/default.

  * RECALL IS A DOUBT AMPLIFIER. Every `shown:true` recall — and specifically every
    `marked_option` — carries a non-empty `challenge` (a divergent counter-move). A recall that
    cannot produce a genuine divergent counter returns `shown:false,
    suppressed_reason:"no-challenge"`, so a mark can never appear without its challenge.

  * NEVER FIRES WHERE RECON WIDENS. A recon-touched or high-novelty fork returns `shown:false`
    with the matching `suppressed_reason`. High-novelty is a MEANINGFUL gate, not a bare bm25
    floor: a hit must share >= MIN_MATCH_TOKENS distinct NON-stopword tokens with the WHOLE fork
    (question + option labels + context_tags), so a single shared generic word ("default") on an
    unrelated fork does NOT match. Trigger-0 recon (widen) and preference recall (narrow) never co-fire.

  * UNPROMPTED WHY, NEVER FABRICATED. `capture` stores the human's free-text `why` verbatim
    (or null when skipped, `why_class:"none"`); a candidate the human tapped is stored
    `why_class:"borrowed"` — weighted down and EXCLUDED from the distilled "your reasoning".
    A rationale is never inferred.

  * ANTI-RUFLO: counts only ("4/5 similar forks"), NEVER a fabricated confidence `%`. No output
    string contains a literal "%". Drift + staleness are surfaced (banner-flagged), never hidden.

  * DRIFT / ANTI-ECHO measured honestly: a recency-weighted last-K disagreement rate (not
    all-time) demotes a rising-disagreement pattern (stops surfacing) + banners it; a
    deterministic holdout fraction suppresses recall and records the un-nudged choice; a pattern
    past its staleness window auto-expires.

  * REUSE BY PATH (never fork): import compound-v-memory.py (`fts5_escape`, `redact`,
    `SECRET_RE`, `PEM_RE`) and compound-v-update-memory.py (`append_line`) via
    importlib.util.spec_from_file_location. `append_line` carries the LANG=C utf-8 fix +
    forbidden-basename guard; `fts5_escape` is the crash-safe MATCH primitive.

  * Python 3.9-safe, stdlib only, LANG=C clean (encoding="utf-8" everywhere), tz-aware
    timestamps via datetime.now(timezone.utc) — NEVER utcnow(). No match/case, no X|Y unions.

Exit 0 on success; 1 on usage/runtime error. --selftest exits 0/1.
"""

import argparse
import datetime
import importlib.util
import json
import os
import re
import sqlite3
import sys

# --------------------------------------------------------------------------- #
# Reuse-by-path: import the canonical primitives, do NOT fork them.
# --------------------------------------------------------------------------- #
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_sibling(basename, modname):
    path = os.path.join(_SCRIPTS_DIR, basename)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_cv_memory = _load_sibling("compound-v-memory.py", "cv_memory_prefs")
_cv_update = _load_sibling("compound-v-update-memory.py", "cv_update_prefs")

fts5_escape = _cv_memory.fts5_escape          # crash-safe MATCH primitive
redact = _cv_memory.redact                    # secret redaction (PEM + token families)
SECRET_RE = _cv_memory.SECRET_RE
PEM_RE = _cv_memory.PEM_RE
append_line = _cv_update.append_line          # LANG=C utf-8 append + forbidden-basename guard

# --------------------------------------------------------------------------- #
# Tunables (all overridable via CLI for deterministic, injectable tests).
# --------------------------------------------------------------------------- #
MARK_MIN_COUNT = 2            # "two is a pattern" — a mark needs >= this dominant count
# High-novelty gate. A bare bm25 floor of 0.0 is NOT meaningful — FTS5 MATCH ORs the query
# tokens, so a single shared common word ("default") scores as a "match" on an unrelated fork.
# The MEANINGFUL gate is token-overlap: a hit must share at least MIN_MATCH_TOKENS distinct
# NON-stopword tokens with the whole fork (question + option labels + context_tags), not one
# generic word. NOVELTY_FLOOR remains a per-hit bm25 floor on top (a real match yields > 0).
NOVELTY_FLOOR = 0.0          # per-hit (-bm25) floor; the real novelty gate is MIN_MATCH_TOKENS
MIN_MATCH_TOKENS = 2         # a hit must share >= this many distinct non-stopword fork tokens
DRIFT_K = 5                  # recency window for the last-K disagreement rate
DRIFT_DEMOTE_THRESHOLD = 0.5  # recency-weighted disagreement >= this => demote + banner
STALENESS_DAYS = 180         # a pattern un-confirmed past this window auto-expires
DEFAULT_HOLDOUT_FRACTION = 0.15  # spine-decided holdout fraction (injectable); caller doesn't manage it
VALID_MODES = ("off", "on-demand", "marked")

# Generic/stopword tokens that must NOT, by themselves, make two forks "match". Standard English
# function words + a few generic decision words ("default", "option", …). Kept deliberately small
# so meaningful domain tokens (headless, backend, keychain, …) still drive relevance.
STOPWORDS = frozenset("""
a an and or the of for to in on at by is are be it its this that these those with without
what which how why when where who whom should could would may might will shall do does did done
not no nor yes if then else than as into onto over under up down out off about
we you i they he she them our your my me us their his her from per via each any all some
default choice choices choose choosing pick picks option options vs versus use using used setup
""".split())

# Light PII families (ADDITIVE to the reused SECRET_RE/PEM_RE — not a fork of the secret list):
# email, US-SSN-shaped, and a 13-16 digit card-shaped run.
PII_RE = re.compile(
    r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"|\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b"
    r"|\b(?:\d[ -]?){13,16}\b)"
)

# Absolute/local filesystem paths (H7): free-form NAMES in `why` aren't stdlib-detectable, but a
# structured path is — redact it before the shipped distillate. We match ANY absolute POSIX path of
# >= 2 segments (/var/tmp/client.txt, /etc/hosts, /Users/alice/…), plus ~/… home paths and Windows
# X:\… drive paths. OVER-redacting a path-like token in the SHIPPED distillate is the SAFE direction
# (the raw jsonl keeps the full text); a stray URL path being redacted is acceptable. HONEST
# RESIDUAL LIMIT: this catches structured PII + paths, NOT arbitrary free-form personal names.
PATH_RE = re.compile(
    r"~/[^\s\"'(),\]]+"                                    # ~ home-relative absolute paths
    r"|(?:/[\w.\-]+){2,}/?"                                # ANY absolute POSIX path, >= 2 segments
    r"|[A-Za-z]:\\[^\s\"'(),\]]+"                          # Windows drive-letter path
)


# --------------------------------------------------------------------------- #
# time helpers — tz-aware, NEVER utcnow()
# --------------------------------------------------------------------------- #
def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc
        )
    except (ValueError, TypeError):
        return None


def _date_only(iso):
    return (iso or "")[:10]


# --------------------------------------------------------------------------- #
# secret + PII scrub (reuse redact; add the light PII pass on top)
# --------------------------------------------------------------------------- #
def scrub(text):
    """Secret-redact (reused) THEN PII-redact THEN path-redact. Before any in-repo/shipped write.

    Order: reused `redact` (PEM key blocks + secret tokens) -> PII_RE (email/SSN/card) ->
    PATH_RE (ANY absolute POSIX path >= 2 segments, ~/… home paths, Windows X:\…). OVER-redacting
    a path-like token here is the SAFE direction — the SHIPPED distillate errs toward [REDACTED
    PATH] while the raw local jsonl keeps the full text. HONEST LIMIT: catches structured
    secrets/PII and filesystem paths; free-form personal NAMES are NOT stdlib-detectable and are
    not scrubbed — which is exactly why the RAW `why` stays in the LOCAL, never-committed, log.
    """
    if text is None:
        return None
    t = redact(text)                              # PEM blocks + secret token families (reused)
    t = PII_RE.sub("[REDACTED PII]", t)           # email / SSN-shaped / card-shaped
    t = PATH_RE.sub("[REDACTED PATH]", t)         # absolute/local filesystem paths
    return t


def is_flagged(text):
    if not text:
        return False
    return bool(PEM_RE.search(text) or SECRET_RE.search(text) or PII_RE.search(text))


# --------------------------------------------------------------------------- #
# storage roots (injectable)
# --------------------------------------------------------------------------- #
def assert_home_outside_repo(home_root):
    """REFUSE (H6) any LOCAL raw root that resolves INSIDE this git repo / under its toplevel.

    FAIL-CLOSED. The raw `decisions.jsonl` is the PII-prone, never-committed store; a root of `.`
    (repo root) or any repo subpath would drop it into the tree. Containment can only be verified
    when repo detection SUCCEEDS, so we distinguish three cases:

      (a) detection succeeds, home is NOT under the repo toplevel -> ACCEPT (return realpath);
      (b) detection succeeds, home IS the repo root or under it     -> REFUSE (in-tree raw log);
      (c) detection RAISES or returns nothing (root undetermined)   -> REFUSE (can't verify).

    Case (c) is the fail-closed fix: a detection failure must NOT silently accept the path (the
    old behaviour let the repo root itself through when detection was forced to fail). We scope the
    check to THIS repo's toplevel (via reused memory.find_repo_root) — NOT a generic .git ancestor
    walk — so the legitimate default ~/.claude/... (which may itself be version-tracked) is still
    accepted in case (a).
    """
    home_abs = os.path.realpath(os.path.expanduser(home_root))
    try:
        detected = _cv_memory.find_repo_root(_SCRIPTS_DIR)
    except Exception as e:  # noqa: BLE001 — detection FAILED: cannot verify => refuse (fail-closed)
        raise ValueError(
            "refusing a preferences home because repo containment could NOT be verified "
            "(repo detection failed: " + str(e) + "): " + home_abs
            + " — the raw decisions log must NEVER risk landing in the tree. Fix repo detection, "
            "or pass an explicit path known to be outside any repo."
        )
    if not detected:
        raise ValueError(
            "refusing a preferences home because the repo root could not be determined "
            "(detection returned nothing): " + home_abs
            + " — containment is unverifiable, so we fail closed. Pass an explicit outside path."
        )
    repo_real = os.path.realpath(detected)
    if home_abs == repo_real or home_abs.startswith(repo_real + os.sep):
        raise ValueError(
            "refusing a preferences home inside the git repo: " + home_abs
            + " (repo: " + repo_real + ") — the raw decisions log must NEVER be writable into "
            "the tree. Use a path outside the repo, or the default ~/.claude/compound-v/preferences."
        )
    return home_abs


def resolve_home_root(arg_home):
    """LOCAL raw dir. Precedence: --home-root > COMPOUND_V_PREFS_HOME > ~/.claude/...

    Whatever the source, the resolved root is repo-containment-checked (H6) before use.
    """
    if arg_home:
        root = os.path.abspath(os.path.expanduser(arg_home))
    else:
        env = os.environ.get("COMPOUND_V_PREFS_HOME")
        if env:
            root = os.path.abspath(os.path.expanduser(env))
        else:
            root = os.path.join(os.path.expanduser("~"), ".claude", "compound-v", "preferences")
    assert_home_outside_repo(root)
    return root


def decisions_path(home_root):
    return os.path.join(home_root, "decisions.jsonl")


def resolve_repo_md(arg_repo_md, arg_repo):
    """IN-REPO distillate path. --repo-md wins; else <repo>/docs/superpowers/preferences/…"""
    if arg_repo_md:
        return os.path.abspath(os.path.expanduser(arg_repo_md))
    repo = os.path.abspath(os.path.expanduser(arg_repo or "."))
    return os.path.join(repo, "docs", "superpowers", "preferences", "preferences.md")


# --------------------------------------------------------------------------- #
# record IO
# --------------------------------------------------------------------------- #
def load_records(jsonl):
    recs = []
    if not os.path.exists(jsonl):
        return recs
    with open(jsonl, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return recs


def _mint_id(question, captured_at):
    import hashlib
    h = hashlib.sha256(("%s|%s" % (question, captured_at)).encode("utf-8")).hexdigest()[:4]
    return "%s-%s" % (_date_only(captured_at), h)


# --------------------------------------------------------------------------- #
# in-process FTS5 over the LOCAL decisions.jsonl (reusing fts5_escape)
# --------------------------------------------------------------------------- #
def _tokens(text):
    return re.findall(r"\w+", (text or "").lower(), re.UNICODE)


def _content_tokens(text):
    """Distinct NON-stopword tokens (len > 1). The unit of genuine fork overlap."""
    return set(t for t in _tokens(text) if len(t) > 1 and t not in STOPWORDS)


def _fork_text(question, options, context_tags):
    """The WHOLE fork as one string: question + option labels + context tags (C2).

    Matching on the whole fork (not one question word) is what makes a match reflect the fork.
    """
    parts = [str(question or "")]
    parts += [str(o) for o in (options or [])]
    parts += [str(t) for t in (context_tags or [])]
    return " ".join(p for p in parts if p)


def _record_body(r):
    parts = [
        str(r.get("question") or ""),
        " ".join(str(o) for o in (r.get("options") or [])),   # option labels indexed too (C2)
        " ".join(str(t) for t in (r.get("context_tags") or [])),
        str(r.get("chosen") or ""),
        str(r.get("why") or ""),
    ]
    return " ".join(p for p in parts if p)


def build_index(records):
    """Return (conn, ok). ok False if this sqlite lacks FTS5 (degrade to no-match)."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE d USING fts5(body)")
    except sqlite3.OperationalError:
        return conn, False
    for i, r in enumerate(records):
        conn.execute("INSERT INTO d(rowid, body) VALUES(?, ?)", (i + 1, _record_body(r)))
    return conn, True


def fts_match(conn, ok, text, limit=50):
    """Return [(record_index, similarity)], similarity = -bm25 (higher = better).

    `text` is the WHOLE fork string (question + options + tags), not just the question.
    """
    if not ok:
        return []
    m = fts5_escape(text)              # route EVERY user string through the escaper
    if not m:
        return []
    try:
        rows = conn.execute(
            "SELECT rowid, bm25(d) FROM d WHERE d MATCH ? ORDER BY bm25(d) LIMIT ?",
            (m, limit),
        ).fetchall()
    except sqlite3.OperationalError:   # the #1 crash class — never let it escape
        return []
    return [(int(rid) - 1, -float(score)) for (rid, score) in rows]


def relevant_hits(conn, ok, records, question, options, context_tags,
                  novelty_floor=NOVELTY_FLOOR, min_tokens=MIN_MATCH_TOKENS):
    """FTS5 candidates FILTERED by genuine fork overlap (C2).

    A raw FTS5 hit can be a single shared generic word. We keep a hit ONLY if it shares at least
    `min_tokens` DISTINCT non-stopword tokens with the whole fork AND clears the bm25 floor. This
    is the meaningful high-novelty gate: an unrelated fork that merely shares "default" is dropped.
    """
    fork_text = _fork_text(question, options, context_tags)
    fork_toks = _content_tokens(fork_text)
    out = []
    for (i, sim) in fts_match(conn, ok, fork_text):
        if sim < novelty_floor:
            continue
        shared = fork_toks & _content_tokens(_record_body(records[i]))
        if len(shared) >= min_tokens:
            out.append((i, sim))
    return out


# --------------------------------------------------------------------------- #
# pattern analysis
# --------------------------------------------------------------------------- #
def _dominant(records):
    """Most-common `chosen` among records -> (choice, count). Ties broken deterministically."""
    counts = {}
    for r in records:
        c = r.get("chosen")
        if c is None:
            continue
        counts[c] = counts.get(c, 0) + 1
    if not counts:
        return None, 0
    best = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return best[0], best[1]


def _last_confirmed(records, dominant_choice):
    """Newest record that ACTUALLY confirmed the dominant choice (H4).

    A contradictory record (chosen != dominant) is NOT a confirmation and must not refresh the
    pattern's freshness/expiry — otherwise 4×A(old)+1×B(new) would falsely date the A-pattern as
    fresh. Returns "" when nothing confirms the dominant (e.g. dominant is None).
    """
    confirming = [(r.get("captured_at") or "")
                  for r in records if r.get("chosen") == dominant_choice]
    return max(confirming) if confirming else ""


def disagreement(records, dominant_choice, k):
    """Recency-weighted last-K disagreement fraction (NOT all-time) + raw counts.

    A record disagrees when the human chose DIFFERENTLY than their own past pattern
    (`changed_after_recall`) OR, on a clean holdout sample, the un-nudged choice != dominant.
    Recent records weigh more (linear ramp).
    """
    ordered = sorted(records, key=lambda r: r.get("captured_at") or "")[-k:]
    if not ordered:
        return 0.0, 0, 0
    total_w = 0.0
    dis_w = 0.0
    dis_count = 0
    for i, r in enumerate(ordered, start=1):
        w = float(i)
        total_w += w
        changed = bool(r.get("changed_after_recall"))
        holdout_diff = bool(r.get("holdout")) and (r.get("chosen") != dominant_choice)
        if changed or holdout_diff:
            dis_w += w
            dis_count += 1
    rate = (dis_w / total_w) if total_w else 0.0
    return rate, dis_count, len(ordered)


def _is_holdout(question, fraction):
    """ONE deterministic holdout decision — the SINGLE source of truth for BOTH recall + capture (C3).

    The holdout decision is a pure function of (fork identity) + one fraction. Fork identity is the
    `question` (the fork), exactly what `recall` keys on, so a fixed fraction of FORKS are held out.
    `recall` calls this to decide `suppressed_reason:"holdout"` (suppress the surface); `capture`
    calls this — same key, same fraction — to LABEL the record clean/un-nudged. Because both sides
    call this one function identically, a record is labelled holdout/clean IFF recall would have
    suppressed the surface for that fork: no fabricated "clean un-nudged holdout" can ever be
    recorded for a fork whose surface recall actually showed. fraction<=0 disables; >=1 holds all."""
    if fraction <= 0.0:
        return False
    if fraction >= 1.0:
        return True
    import hashlib
    bucket = int(hashlib.sha256((question or "").encode("utf-8")).hexdigest(), 16) % 1000
    return bucket < int(fraction * 1000)


def build_challenges(options, dominant_choice, matched):
    """History-GROUNDED divergent counter-moves (H5b). NEVER states a falsehood.

    Every claim is checked against ACTUAL history (`matched`): we never say "you did not pick X"
    unless the record truly shows X was never chosen at a matched fork. The list is empty ONLY
    when no genuine divergent element exists (single option that IS the past pick, no historical
    divergence) — which forces the no-challenge suppression, so a mark never appears bare.
    """
    chosen_counts = {}
    for r in matched:
        c = r.get("chosen")
        if c is not None:
            chosen_counts[c] = chosen_counts.get(c, 0) + 1
    total = sum(chosen_counts.values())
    chosen_set = set(chosen_counts)

    # The genuine divergent counter-moves (each TRUE by construction against `chosen_set`).
    divergent = []
    for o in options:
        if o == dominant_choice:
            continue
        if o not in chosen_set:
            # TRUE: this option was never chosen at a matched fork.
            divergent.append(
                "You have not chosen '" + str(o) + "' at a similar fork before — has anything "
                "changed that makes it the stronger move now?"
            )
        else:
            # It WAS chosen. "more often" is ONLY truthful when the dominant's count is STRICTLY
            # greater than this option's count (H5). On a TIE (equal counts) the dominant is only
            # via deterministic tie-break, so "more often" would be a FALSE frequency claim — emit
            # a neutral, truthful phrasing instead. Never state a frequency comparison that is false.
            dom_ct = chosen_counts.get(dominant_choice, 0)
            o_ct = chosen_counts.get(o, 0)
            if dom_ct > o_ct:
                divergent.append(
                    "You have chosen '" + str(o) + "' before, but '" + str(dominant_choice)
                    + "' more often — is that still the right call here?"
                )
            else:
                # Equal counts: no "more often". State the true equal-frequency fact.
                divergent.append(
                    "You have chosen both '" + str(o) + "' and '" + str(dominant_choice)
                    + "' equally often at similar forks — the past does not favour either here."
                )
    distinct = sorted(str(c) for c in chosen_set)
    if len(distinct) > 1:
        divergent.append(
            "Your past choices on similar forks diverged (" + ", ".join(distinct) + ") — "
            "the pattern may not hold here."
        )

    if not divergent:
        return []

    # Prepend a GROUNDED framing of the actual pattern (true by construction), then the
    # divergent counters, then the falsifiable-evidence reminder.
    challenges = []
    if dominant_choice is not None and total:
        challenges.append(
            "Your dominant past pick on similar forks was '" + str(dominant_choice) + "' ("
            + str(chosen_counts.get(dominant_choice, 0)) + "/" + str(total)
            + ") — treat it as falsifiable evidence, not a rule."
        )
    challenges.extend(divergent)
    challenges.append(
        "This fork may differ from the past ones — treat the history as falsifiable "
        "evidence, not a rule."
    )
    return challenges


# --------------------------------------------------------------------------- #
# recall (PULL)
# --------------------------------------------------------------------------- #
def recall(jsonl, question, options, context_tags, mode,
           recon_touched=False, novelty_floor=NOVELTY_FLOOR,
           holdout_fraction=DEFAULT_HOLDOUT_FRACTION,
           k=DRIFT_K, demote_threshold=DRIFT_DEMOTE_THRESHOLD,
           staleness_days=STALENESS_DAYS, now=None):
    """Return the recall dict. NEVER marks an option chosen/default in any mode."""
    now = now or now_iso()
    base = {
        "shown": False,
        "mode": mode,
        "evidence": [],
        "challenge": [],
        "marked_option": None,
        "sample_n": 0,
        "disagreement_rate": 0.0,
        "disagreement_count": 0,
        "disagreement_window": 0,
        "banner": None,
        "suppressed_reason": None,
    }

    if mode == "off":
        base["suppressed_reason"] = "mode-off"
        return base

    # 1) recon-touched fork — recall (narrow) never co-fires with recon (widen).
    if recon_touched:
        base["suppressed_reason"] = "recon-touched"
        return base

    records = load_records(jsonl)
    conn, ok = build_index(records)
    hits = relevant_hits(conn, ok, records, question, options, context_tags,
                         novelty_floor=novelty_floor)

    # 2) high-novelty — no match, or no hit shares enough of the WHOLE fork (C2). A single shared
    #    generic token ("default") is NOT a match; a real hit must overlap >= MIN_MATCH_TOKENS
    #    distinct non-stopword fork tokens AND clear the bm25 floor (both enforced in relevant_hits).
    if not hits:
        base["suppressed_reason"] = "high-novelty"
        return base

    matched = [records[i] for (i, _sim) in hits]
    dominant_choice, dominant_count = _dominant(matched)
    sample_n = len(matched)
    base["sample_n"] = sample_n

    # 3) holdout — deliberately suppress + let capture record the un-nudged choice. The SAME
    #    `_is_holdout(question, holdout_fraction)` (single source of truth) that capture uses to
    #    label the record, so suppress-here and label-there agree for this fork (C3).
    if _is_holdout(question, holdout_fraction):
        base["suppressed_reason"] = "holdout"
        return base

    # 4) auto-expiry — a pattern un-CONFIRMED past its staleness window stops surfacing (H4).
    #    Freshness dates from the newest record that ACTUALLY confirmed the dominant choice, so a
    #    later contradictory pick does NOT refresh the pattern (4×A old + 1×B new can still expire).
    last_confirmed = _last_confirmed(matched, dominant_choice)
    lc_dt = _parse_ts(last_confirmed)
    now_dt = _parse_ts(now)
    if lc_dt and now_dt and now_dt > lc_dt + datetime.timedelta(days=staleness_days):
        base["suppressed_reason"] = "expired"
        return base

    # 5) drift — recency-weighted last-K disagreement demotes a rising-disagreement pattern.
    rate, dcount, window = disagreement(matched, dominant_choice, k)
    base["disagreement_rate"] = rate
    base["disagreement_count"] = dcount
    base["disagreement_window"] = window
    if rate >= demote_threshold:
        base["suppressed_reason"] = "demoted"
        base["banner"] = ("DRIFT: your reasoning on this kind of fork may have shifted "
                          "(" + str(dcount) + " of the last " + str(window) + " diverged) — "
                          "pattern demoted, not surfaced.")
        return base

    # 6) challenge — recall that cannot produce a divergent counter is suppressed.
    challenges = build_challenges(options, dominant_choice, matched)
    if not challenges:
        base["suppressed_reason"] = "no-challenge"
        return base

    # --- surfaced: dated falsifiable evidence + mandatory divergent challenge ---
    evidence = []
    for r in matched:
        why = r.get("why")
        why_class = r.get("why_class") or "none"
        evidence.append({
            "date": _date_only(r.get("captured_at")),
            "question": r.get("question"),
            "chosen": r.get("chosen"),
            # only UNPROMPTED whys are shown as "your reasoning"; borrowed is excluded.
            "why": why if why_class == "unprompted" else None,
            "why_class": why_class,
        })
    base["evidence"] = evidence
    base["challenge"] = challenges
    base["shown"] = True

    # marked_option: a dated LABEL, ONLY in `marked` mode when the pattern qualifies AND the
    # dominant past choice is ACTUALLY PRESENT among the current options (H5a). If the dominant
    # pick isn't a live option, marking it would be a fabricated label — so no mark.
    # It is NEVER a selection/default and carries no chosen/selected/default key.
    if (mode == "marked" and dominant_choice is not None
            and dominant_count >= MARK_MIN_COUNT and dominant_choice in options):
        base["marked_option"] = {
            "option": dominant_choice,
            "count": dominant_count,
            "sample_n": sample_n,
            "date": _date_only(last_confirmed),
            "badge": ("your past pick: " + str(dominant_count) + "/" + str(sample_n)
                      + " · " + _date_only(last_confirmed)),
        }
    return base


# --------------------------------------------------------------------------- #
# capture
# --------------------------------------------------------------------------- #
def capture(jsonl, question, options, chosen, why, why_class, context_tags,
            recall_shown, challenged, changed_after_recall=None, suppressed_reason=None,
            holdout=None, now=None, holdout_fraction=DEFAULT_HOLDOUT_FRACTION,
            novelty_floor=NOVELTY_FLOOR, k=DRIFT_K):
    """Append one fork outcome to the LOCAL raw jsonl (full text, private + purgeable).

    SELF-SUFFICIENT drift + holdout (C3). The caller does NOT need to pass either, and in the
    default on-demand mode (where nothing is marked) it cannot compute drift anyway:

      * `changed_after_recall` — when None (the default), capture computes it ITSELF by matching
        the PRIOR records for this fork (the exact recall matching) and setting
        `changed_after_recall = (chosen != dominant_past_choice)`. So drift accrues in EVERY mode,
        decoupled from what was shown/marked. An explicit bool still overrides (injectable tests).
      * `holdout` — when None, capture decides it via the SINGLE source of truth
        `_is_holdout(question, holdout_fraction)` — the exact function/key/fraction `recall` uses
        to suppress — so the "clean un-nudged" label agrees with recall's suppression for that fork
        (default fraction ~0.15, injectable). Never a fabricated clean sample for a surfaced fork.

    The `why` is UNPROMPTED free-text first (or null). A tapped candidate is `borrowed`.
    A secret/PII-shaped record is FLAGGED (kept full locally — the local log is the private
    store; the shipped distillate is scrubbed at distill time), and a warning is emitted.
    """
    now = now or now_iso()
    if why is None:
        why_class = "none"
    elif why_class not in ("unprompted", "borrowed"):
        why_class = "unprompted"

    # Self-sufficient drift: derive the past dominant for THIS fork from prior records (same
    # matching as recall) and set disagreement ourselves. Explicit caller value wins if given.
    if changed_after_recall is None:
        prior = load_records(jsonl)
        conn, ok = build_index(prior)
        hits = relevant_hits(conn, ok, prior, question, options, context_tags,
                             novelty_floor=novelty_floor)
        matched = [prior[i] for (i, _sim) in hits]
        dom, _dc = _dominant(matched)
        changed_after_recall = bool(dom is not None and chosen != dom)
    else:
        changed_after_recall = bool(changed_after_recall)

    # Self-sufficient holdout (C3): decided by the SINGLE source of truth `_is_holdout(question,
    # fraction)` — the exact function + key + fraction `recall` uses. So a record is labelled
    # clean/un-nudged holdout IFF recall would have suppressed the surface for this fork; never a
    # fabricated clean sample for a fork recall actually surfaced. Explicit caller value wins.
    if holdout is None:
        holdout = _is_holdout(question, holdout_fraction)
    else:
        holdout = bool(holdout)

    flagged = is_flagged(question or "") or is_flagged(why or "")
    if flagged:
        sys.stderr.write(
            "WARNING: this record carries a secret/PII-shaped token. It is stored IN FULL in "
            "the LOCAL raw log (never committed) and will be REDACTED in the in-repo "
            "distillate at `distill` time.\n"
        )

    rec = {
        "id": _mint_id(question or "", now),
        "captured_at": now,
        "question": question,
        "context_tags": context_tags or [],
        "options": options or [],
        "chosen": chosen,
        "why": why,                       # human free-text or null — NEVER inferred
        "why_class": why_class,           # unprompted | borrowed | none
        "recall_shown": bool(recall_shown),
        "challenged": bool(challenged),
        "changed_after_recall": changed_after_recall,   # spine-computed unless explicitly injected
        "suppressed_reason": suppressed_reason,
        "holdout": holdout,               # spine-decided unless explicitly injected
        "flagged": flagged,
    }
    append_line(jsonl, rec)
    return rec


# --------------------------------------------------------------------------- #
# cluster (for distill + stats)
# --------------------------------------------------------------------------- #
def _signature(r):
    tags = r.get("context_tags") or []
    if tags:
        return "|".join(sorted(str(t) for t in tags))
    toks = re.findall(r"\w+", (r.get("question") or "").lower(), re.UNICODE)
    return "q:" + " ".join(sorted(set(toks)))


def cluster(records):
    groups = {}
    for r in records:
        groups.setdefault(_signature(r), []).append(r)
    out = []
    for sig, recs in sorted(groups.items()):
        dominant_choice, dominant_count = _dominant(recs)
        first_seen = min((r.get("captured_at") or "") for r in recs)
        # H4: freshness = newest record that ACTUALLY confirmed the dominant, not newest overall.
        last_confirmed = _last_confirmed(recs, dominant_choice)
        rate, dcount, window = disagreement(recs, dominant_choice, DRIFT_K)
        out.append({
            "signature": sig,
            "sample_n": len(recs),
            "dominant": dominant_choice,
            "dominant_count": dominant_count,
            "first_seen": first_seen,
            "last_confirmed": last_confirmed,
            "disagreement_rate": rate,
            "disagreement_count": dcount,
            "disagreement_window": window,
            "records": recs,
        })
    return out


def _expires_at(last_confirmed, staleness_days):
    dt = _parse_ts(last_confirmed)
    if not dt:
        return None
    return (dt + datetime.timedelta(days=staleness_days)).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# distill — regenerate the IN-REPO preferences.md (secret+PII-scrubbed BEFORE write)
# --------------------------------------------------------------------------- #
def distill(jsonl, repo_md, staleness_days=STALENESS_DAYS,
            demote_threshold=DRIFT_DEMOTE_THRESHOLD, now=None):
    now = now or now_iso()
    now_dt = _parse_ts(now)
    records = load_records(jsonl)
    clusters = cluster(records)

    lines = []
    lines.append("# Decision preferences (distilled)")
    lines.append("")
    lines.append("Falsifiable, dated aggregate of past decisions. **Memory, not authority** — "
                 "counts only, no confidence score; every surfaced pattern is paired with a "
                 "divergent challenge at the fork. Regenerated by "
                 "`compound-v-preferences.py distill`; the raw log stays local + purgeable.")
    lines.append("")
    lines.append("_Generated: " + now + " · patterns: " + str(len(clusters)) + "_")
    lines.append("")

    if not clusters:
        lines.append("_No decisions captured yet._")

    for c in clusters:
        expires_at = _expires_at(c["last_confirmed"], staleness_days)
        exp_dt = _parse_ts(expires_at)
        expired = bool(now_dt and exp_dt and now_dt > exp_dt)
        demoted = c["disagreement_rate"] >= demote_threshold

        lines.append("## " + c["signature"])
        lines.append("")
        if demoted:
            lines.append("> DEMOTED — your reasoning here may have shifted ("
                         + str(c["disagreement_count"]) + " of the last "
                         + str(c["disagreement_window"]) + " diverged). Not surfaced at a fork.")
            lines.append("")
        if expired:
            lines.append("> STALE — last confirmed " + _date_only(c["last_confirmed"])
                         + ", past the staleness window. Not surfaced until refreshed.")
            lines.append("")
        lines.append("- Dominant choice: **" + str(c["dominant"]) + "** ("
                     + str(c["dominant_count"]) + "/" + str(c["sample_n"]) + " similar forks)")
        lines.append("- First seen: " + _date_only(c["first_seen"])
                     + " · Last confirmed: " + _date_only(c["last_confirmed"])
                     + " · Expires: " + _date_only(expires_at))
        lines.append("- Disagreement (recency-weighted last-" + str(c["disagreement_window"])
                     + "): " + str(c["disagreement_count"]) + "/" + str(c["disagreement_window"])
                     + " diverged")
        # UNPROMPTED whys only — borrowed candidates are excluded from "your reasoning".
        whys = [r.get("why") for r in c["records"]
                if r.get("why_class") == "unprompted" and r.get("why")]
        if whys:
            lines.append("- Your reasoning (unprompted):")
            for w in whys:
                lines.append("  - " + str(w))
        lines.append("")

    md = "\n".join(lines) + "\n"
    # SECRET + PII SCRUB before the in-repo/shipped write — the committed copy carries no token.
    md = scrub(md)

    parent = os.path.dirname(repo_md)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(repo_md, "w", encoding="utf-8") as fh:
        fh.write(md)
    return repo_md, len(clusters)


# --------------------------------------------------------------------------- #
# stats
# --------------------------------------------------------------------------- #
def stats(jsonl, staleness_days=STALENESS_DAYS, demote_threshold=DRIFT_DEMOTE_THRESHOLD,
          now=None):
    now = now or now_iso()
    now_dt = _parse_ts(now)
    clusters = cluster(load_records(jsonl))
    out = []
    for c in clusters:
        expires_at = _expires_at(c["last_confirmed"], staleness_days)
        exp_dt = _parse_ts(expires_at)
        out.append({
            "signature": c["signature"],
            "sample_n": c["sample_n"],
            "dominant": c["dominant"],
            "dominant_count": c["dominant_count"],
            "disagreement_rate": c["disagreement_rate"],
            "disagreement_count": c["disagreement_count"],
            "disagreement_window": c["disagreement_window"],
            "first_seen": c["first_seen"],
            "last_confirmed": c["last_confirmed"],
            "expires_at": expires_at,
            "demoted": c["disagreement_rate"] >= demote_threshold,
            "expired": bool(now_dt and exp_dt and now_dt > exp_dt),
        })
    return {"patterns": out, "total": len(out)}


# --------------------------------------------------------------------------- #
# purge — wipe the LOCAL raw log in one command
# --------------------------------------------------------------------------- #
def purge(home_root):
    jsonl = decisions_path(home_root)
    removed = False
    if os.path.exists(jsonl):
        os.remove(jsonl)
        removed = True
    return {"purged": removed, "path": jsonl}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _add_common(p):
    p.add_argument("--home-root", dest="home_root", default=None,
                   help="LOCAL raw dir (or env COMPOUND_V_PREFS_HOME). "
                        "Default ~/.claude/compound-v/preferences/")


def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()

    ap = argparse.ArgumentParser(prog="compound-v-preferences.py")
    ap.add_argument("--selftest", action="store_true",
                    help="run the in-process self-test (tmp dirs only) and exit")
    sub = ap.add_subparsers(dest="cmd")

    pr = sub.add_parser("recall", help="PULL past decisions for a fork (+ divergent challenge)")
    _add_common(pr)
    pr.add_argument("--question", required=True)
    pr.add_argument("--option", dest="options", action="append", default=[],
                    help="a fork option (repeatable)")
    pr.add_argument("--context-tag", dest="context_tags", action="append", default=[])
    pr.add_argument("--mode", choices=list(VALID_MODES), default="on-demand")
    pr.add_argument("--recon-touched", dest="recon_touched", action="store_true")
    pr.add_argument("--novelty-floor", dest="novelty_floor", type=float, default=NOVELTY_FLOOR)
    pr.add_argument("--holdout-fraction", dest="holdout_fraction", type=float,
                    default=DEFAULT_HOLDOUT_FRACTION,
                    help="deterministic holdout fraction (spine-decided; MUST match capture's "
                         "so recall-suppress and capture-label agree; default ~0.15)")
    pr.add_argument("--k-window", dest="k", type=int, default=DRIFT_K)
    pr.add_argument("--demote-threshold", dest="demote_threshold", type=float,
                    default=DRIFT_DEMOTE_THRESHOLD)
    pr.add_argument("--staleness-days", dest="staleness_days", type=int, default=STALENESS_DAYS)
    pr.add_argument("--now", default=None, help="injectable clock (ISO Z) for tests")

    pc = sub.add_parser("capture", help="record a fork outcome (unprompted why first)")
    _add_common(pc)
    pc.add_argument("--question", required=True)
    pc.add_argument("--option", dest="options", action="append", default=[])
    pc.add_argument("--chosen", required=True)
    pc.add_argument("--why", default=None, help="human free-text rationale (omit => null)")
    pc.add_argument("--why-class", dest="why_class", choices=("unprompted", "borrowed"),
                    default="unprompted", help="'borrowed' = tapped a candidate")
    pc.add_argument("--context-tag", dest="context_tags", action="append", default=[])
    pc.add_argument("--recall-shown", dest="recall_shown", action="store_true")
    pc.add_argument("--challenged", action="store_true")
    # Drift + holdout are SPINE-computed (C3): the caller does NOT pass them. The only knob is the
    # (injectable) holdout fraction; changed_after_recall is derived from the prior fork pattern.
    pc.add_argument("--holdout-fraction", dest="holdout_fraction", type=float,
                    default=DEFAULT_HOLDOUT_FRACTION,
                    help="deterministic clean-sample fraction (spine-decided; default ~0.15)")
    pc.add_argument("--suppressed-reason", dest="suppressed_reason", default=None)
    pc.add_argument("--now", default=None)

    pd = sub.add_parser("distill", help="regenerate the in-repo preferences.md (scrubbed)")
    _add_common(pd)
    pd.add_argument("--repo-md", dest="repo_md", default=None,
                    help="distillate path (default <repo>/docs/superpowers/preferences/…)")
    pd.add_argument("--repo", default=".", help="repo root for the default --repo-md")
    pd.add_argument("--staleness-days", dest="staleness_days", type=int, default=STALENESS_DAYS)
    pd.add_argument("--demote-threshold", dest="demote_threshold", type=float,
                    default=DRIFT_DEMOTE_THRESHOLD)
    pd.add_argument("--now", default=None)

    ps = sub.add_parser("stats", help="per-pattern override/disagreement + demoted/expired")
    _add_common(ps)
    ps.add_argument("--staleness-days", dest="staleness_days", type=int, default=STALENESS_DAYS)
    ps.add_argument("--demote-threshold", dest="demote_threshold", type=float,
                    default=DRIFT_DEMOTE_THRESHOLD)
    ps.add_argument("--now", default=None)

    pp = sub.add_parser("purge", help="wipe the LOCAL raw decisions log")
    _add_common(pp)

    args = ap.parse_args(argv[1:])
    if not args.cmd:
        ap.print_help()
        return 1

    try:
        home_root = resolve_home_root(getattr(args, "home_root", None))
    except ValueError as e:   # H6: repo-contained home root is refused, fail-closed
        sys.stderr.write("ERROR: " + str(e) + "\n")
        return 1
    jsonl = decisions_path(home_root)

    if args.cmd == "recall":
        out = recall(jsonl, args.question, args.options, args.context_tags, args.mode,
                     recon_touched=args.recon_touched, novelty_floor=args.novelty_floor,
                     holdout_fraction=args.holdout_fraction, k=args.k,
                     demote_threshold=args.demote_threshold,
                     staleness_days=args.staleness_days, now=args.now)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "capture":
        # changed_after_recall + holdout are spine-computed (left as None) — C3.
        rec = capture(jsonl, args.question, args.options, args.chosen, args.why,
                      args.why_class, args.context_tags, args.recall_shown, args.challenged,
                      suppressed_reason=args.suppressed_reason, now=args.now,
                      holdout_fraction=args.holdout_fraction)
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "distill":
        repo_md = resolve_repo_md(args.repo_md, args.repo)
        path, n = distill(jsonl, repo_md, staleness_days=args.staleness_days,
                          demote_threshold=args.demote_threshold, now=args.now)
        print(json.dumps({"written": path, "patterns": n}, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "stats":
        print(json.dumps(stats(jsonl, staleness_days=args.staleness_days,
                               demote_threshold=args.demote_threshold, now=args.now),
                         ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "purge":
        print(json.dumps(purge(home_root), ensure_ascii=False, indent=2))
        return 0

    ap.print_help()
    return 1


# --------------------------------------------------------------------------- #
# selftest — tmp dirs only, no network, no real writes. LANG=C + Py3.9 clean.
# --------------------------------------------------------------------------- #
def _selftest():
    import tempfile

    failures = []

    def expect(name, cond):
        print(("  ok   - " if cond else "  FAIL - ") + name)
        if not cond:
            failures.append(name)

    tmp = tempfile.mkdtemp(prefix="cv-prefs-selftest-")
    home = os.path.join(tmp, "home")
    jsonl = decisions_path(home)
    repo_md = os.path.join(tmp, "repo", "docs", "superpowers", "preferences", "preferences.md")

    T0 = "2026-01-01T10:00:00Z"
    T1 = "2026-01-02T10:00:00Z"
    Q = "headless shim default posture — safe or full?"
    OPTS = ["safe default + opt-in", "run full pipeline"]

    # ---- source-level safety asserts (static invariants) ----
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    # Build the needle by concatenation so this very assertion is not a false positive.
    _utcnow_call = "." + "utcnow("
    expect("no deprecated utcnow() call anywhere", _utcnow_call not in src)
    expect("no match/case", not re.search(r"^\s*match\s+\w+\s*:", src, re.MULTILINE))

    # ---- capture -> recall IMMEDIATE roundtrip (in-process FTS5 over local jsonl) ----
    capture(jsonl, Q, OPTS, OPTS[0], "safer default; the user owns the risk", "unprompted",
            ["safety", "default-vs-power"], recall_shown=False, challenged=False,
            changed_after_recall=False, suppressed_reason=None, holdout=False, now=T0)
    capture(jsonl, Q, OPTS, OPTS[0], "least-surprise posture", "unprompted",
            ["safety", "default-vs-power"], recall_shown=True, challenged=True,
            changed_after_recall=False, suppressed_reason=None, holdout=False, now=T1)

    r = recall(jsonl, Q, OPTS, ["safety"], "on-demand", holdout_fraction=0.0, now=T1)
    expect("roundtrip: recall finds the captured pattern immediately", r["shown"] is True)
    expect("roundtrip: sample_n counts both captures", r["sample_n"] == 2)
    expect("roundtrip: evidence carries dated past decisions", len(r["evidence"]) == 2)

    # ---- fts5_escape routes a question with . / - / OR without throwing ----
    threw = False
    try:
        recall(jsonl, "shim.default OR full-pipeline posture", OPTS, [], "on-demand", now=T1)
    except sqlite3.OperationalError:
        threw = True
    expect("fts5_escape handles ./-/OR (no OperationalError)", threw is False)

    # ---- no % anywhere in any recall/stats/distill output ----
    r_marked = recall(jsonl, Q, OPTS, [], "marked", holdout_fraction=0.0, now=T1)
    blob = json.dumps(r_marked, ensure_ascii=False)
    expect("no '%' char in marked recall output", "%" not in blob)

    # ---- on-demand returns marked_option null; marked populates it as a LABEL ----
    r_od = recall(jsonl, Q, OPTS, [], "on-demand", holdout_fraction=0.0, now=T1)
    expect("on-demand: marked_option is null", r_od["marked_option"] is None)
    expect("marked: marked_option populated (qualifying pattern)",
           r_marked["marked_option"] is not None)
    mo = r_marked["marked_option"] or {}
    expect("marked_option is a label (option+count+date+badge)",
           mo.get("option") == OPTS[0] and mo.get("count") == 2 and "badge" in mo)
    # NO field marks an option chosen/selected/default — anywhere in the recall dict.
    expect("no chosen/selected/default field at recall top level",
           not ({"selected", "default", "chosen", "preselected"} & set(r_marked.keys())))
    expect("no chosen/selected/default field inside marked_option",
           not ({"selected", "default", "chosen", "preselected"} & set(mo.keys())))
    expect("every shown recall carries a non-empty challenge", bool(r_marked["challenge"]))
    expect("every marked_option carries a non-empty challenge",
           bool(r_marked["marked_option"]) and bool(r_marked["challenge"]))

    # ---- high-novelty suppression: unrelated question AND score-below-floor ----
    # A genuinely unrelated fork has unrelated OPTIONS too (matching folds the whole fork now).
    r_nov1 = recall(jsonl, "quantum banana teleportation recipe",
                    ["teleport now", "abort the jump"], [], "on-demand", now=T1)
    expect("unrelated fork -> shown:false high-novelty",
           r_nov1["shown"] is False and r_nov1["suppressed_reason"] == "high-novelty")
    r_nov2 = recall(jsonl, Q, OPTS, [], "on-demand", novelty_floor=9999.0, now=T1)
    expect("top score below floor -> shown:false high-novelty",
           r_nov2["shown"] is False and r_nov2["suppressed_reason"] == "high-novelty")

    # ---- recon-touched suppression ----
    r_recon = recall(jsonl, Q, OPTS, [], "marked", recon_touched=True, now=T1)
    expect("recon-touched -> shown:false recon-touched",
           r_recon["shown"] is False and r_recon["suppressed_reason"] == "recon-touched")

    # ---- no-challenge suppression (single option that IS the past pick) ----
    home_nc = os.path.join(tmp, "home_nc")
    jsonl_nc = decisions_path(home_nc)
    capture(jsonl_nc, "release cadence choice", ["ship weekly"], "ship weekly",
            "steady", "unprompted", ["cadence"], recall_shown=False, challenged=False,
            changed_after_recall=False, suppressed_reason=None, holdout=False, now=T0)
    capture(jsonl_nc, "release cadence choice", ["ship weekly"], "ship weekly",
            "steady", "unprompted", ["cadence"], recall_shown=False, challenged=False,
            changed_after_recall=False, suppressed_reason=None, holdout=False, now=T1)
    r_nc = recall(jsonl_nc, "release cadence choice", ["ship weekly"], [], "on-demand",
                  holdout_fraction=0.0, now=T1)
    expect("no divergent counter -> shown:false no-challenge",
           r_nc["shown"] is False and r_nc["suppressed_reason"] == "no-challenge")

    # ---- holdout suppression (deterministic) ----
    r_ho = recall(jsonl, Q, OPTS, [], "on-demand", holdout_fraction=1.0, now=T1)
    expect("holdout -> shown:false holdout",
           r_ho["shown"] is False and r_ho["suppressed_reason"] == "holdout")

    # ---- expiry suppression ----
    r_exp = recall(jsonl, Q, OPTS, [], "on-demand", staleness_days=0,
                   holdout_fraction=0.0, now="2026-06-01T10:00:00Z")
    expect("stale pattern -> shown:false expired",
           r_exp["shown"] is False and r_exp["suppressed_reason"] == "expired")

    # ---- drift: injecting recent disagreements demotes + banners a pattern ----
    home_dr = os.path.join(tmp, "home_dr")
    jsonl_dr = decisions_path(home_dr)
    QD = "worker backend for an isolated build"
    ODS = ["codex", "antigravity"]
    for i, day in enumerate(("03", "04")):
        capture(jsonl_dr, QD, ODS, "codex", "kernel write-confinement", "unprompted",
                ["backend"], recall_shown=False, challenged=False, changed_after_recall=False,
                suppressed_reason=None, holdout=False, now="2026-01-%sT10:00:00Z" % day)
    for day in ("05", "06", "07"):
        capture(jsonl_dr, QD, ODS, "antigravity", "trying the alt", "unprompted", ["backend"],
                recall_shown=True, challenged=True, changed_after_recall=True,
                suppressed_reason=None, holdout=False, now="2026-01-%sT10:00:00Z" % day)
    r_dr = recall(jsonl_dr, QD, ODS, [], "marked", holdout_fraction=0.0,
                  now="2026-01-08T10:00:00Z")
    expect("rising disagreement -> shown:false demoted",
           r_dr["shown"] is False and r_dr["suppressed_reason"] == "demoted")
    expect("demotion carries a drift banner", bool(r_dr["banner"]))
    st = stats(jsonl_dr, now="2026-01-08T10:00:00Z")
    expect("stats flags the demoted pattern",
           any(p["demoted"] for p in st["patterns"]))
    expect("stats disagreement is recency-weighted last-K (window <= K)",
           all(p["disagreement_window"] <= DRIFT_K for p in st["patterns"]))

    # ---- borrowed why is excluded from the distilled "your reasoning" ----
    home_b = os.path.join(tmp, "home_b")
    jsonl_b = decisions_path(home_b)
    repo_md_b = os.path.join(tmp, "repo_b", "preferences.md")
    capture(jsonl_b, "auth token storage location", ["keychain", "env file"], "keychain",
            "os-native secret store", "unprompted", ["auth"], recall_shown=False,
            challenged=False, changed_after_recall=False, suppressed_reason=None,
            holdout=False, now=T0)
    capture(jsonl_b, "auth token storage location", ["keychain", "env file"], "keychain",
            "the assistant suggested keychain", "borrowed", ["auth"], recall_shown=True,
            challenged=True, changed_after_recall=False, suppressed_reason=None,
            holdout=False, now=T1)
    distill(jsonl_b, repo_md_b, now=T1)
    md_b = open(repo_md_b, encoding="utf-8").read()
    expect("distill includes the UNPROMPTED why", "os-native secret store" in md_b)
    expect("distill EXCLUDES the borrowed why", "the assistant suggested keychain" not in md_b)
    expect("distilled MD has no '%' char", "%" not in md_b)

    # ---- secret/PII: FULL in local jsonl, REDACTED in the committed distillate ----
    home_s = os.path.join(tmp, "home_s")
    jsonl_s = decisions_path(home_s)
    repo_md_s = os.path.join(tmp, "repo_s", "preferences.md")
    secret_why = "used key sk-abcdef0123456789ABCDEF and emailed secret.person@example.com"
    capture(jsonl_s, "credential handling for the deploy step",
            ["vault", "inline"], "vault", secret_why, "unprompted", ["secrets"],
            recall_shown=False, challenged=False, changed_after_recall=False,
            suppressed_reason=None, holdout=False, now=T0)
    raw_jsonl = open(jsonl_s, encoding="utf-8").read()
    expect("flagged why is FULL in the local jsonl (secret token present)",
           "sk-abcdef0123456789ABCDEF" in raw_jsonl)
    expect("flagged why is FULL in the local jsonl (email present)",
           "secret.person@example.com" in raw_jsonl)
    distill(jsonl_s, repo_md_s, now=T0)
    md_s = open(repo_md_s, encoding="utf-8").read()
    expect("distillate REDACTS the secret token", "sk-abcdef0123456789ABCDEF" not in md_s)
    expect("distillate REDACTS the PII email", "secret.person@example.com" not in md_s)
    expect("record was flagged", load_records(jsonl_s)[0]["flagged"] is True)

    # ---- skipped why stores null + why_class none (never inferred) ----
    home_n = os.path.join(tmp, "home_n")
    jsonl_n = decisions_path(home_n)
    rec_null = capture(jsonl_n, "some fork", ["a", "b"], "a", None, "unprompted", [],
                       recall_shown=False, challenged=False, changed_after_recall=False,
                       suppressed_reason=None, holdout=False, now=T0)
    expect("skipped why -> why null", rec_null["why"] is None)
    expect("skipped why -> why_class none", rec_null["why_class"] == "none")

    # ---- injectable roots: nothing written to the real ~/.claude or real repo docs ----
    real_home = os.path.join(os.path.expanduser("~"), ".claude", "compound-v", "preferences")
    expect("selftest used tmp home only (not real ~/.claude)",
           os.path.commonprefix([home, real_home]) != real_home)
    expect("selftest wrote MD under tmp only", repo_md_b.startswith(tmp))

    # ---- off mode disables entirely ----
    r_off = recall(jsonl, Q, OPTS, [], "off", now=T1)
    expect("off mode -> shown:false, no surface", r_off["shown"] is False)

    # ---- C2: a novel fork sharing only ONE generic token does NOT match (high-novelty) ----
    home_c2 = os.path.join(tmp, "home_c2")
    jsonl_c2 = decisions_path(home_c2)
    QA = "safe default for a headless worker"          # topic A: infra/backend
    OA = ["codex", "antigravity"]
    for day in ("01", "02"):
        capture(jsonl_c2, QA, OA, "codex", "kernel write-confinement", "unprompted",
                ["backend"], recall_shown=False, challenged=False, changed_after_recall=False,
                suppressed_reason=None, holdout=False, now="2026-01-%sT10:00:00Z" % day)
    # topic B shares exactly one GENERIC token ("default") with topic A — nothing else.
    r_c2 = recall(jsonl_c2, "default typography for a birthday invitation",
                  ["serif font", "script font"], ["design"], "on-demand", now=T1)
    expect("C2: unrelated fork sharing one generic token -> shown:false high-novelty",
           r_c2["shown"] is False and r_c2["suppressed_reason"] == "high-novelty")
    # sanity: the SAME topic (A) still matches (the gate isn't just suppressing everything).
    r_c2_same = recall(jsonl_c2, QA, OA, ["backend"], "on-demand", holdout_fraction=0.0, now=T1)
    expect("C2: the genuinely-similar fork still matches", r_c2_same["shown"] is True)

    # ---- H5: no mark for an ABSENT dominant; no FALSE 'you did not pick X' claim ----
    home_h5 = os.path.join(tmp, "home_h5")
    jsonl_h5 = decisions_path(home_h5)
    QH5 = "state store choice for the widget layer"
    for day, ch in (("01", "A"), ("02", "B"), ("03", "A")):   # history A,B,A -> dominant A
        capture(jsonl_h5, QH5, ["A", "B", "C"], ch, "reason", "unprompted", ["statestore"],
                recall_shown=False, challenged=False, changed_after_recall=False,
                suppressed_reason=None, holdout=False, now="2026-01-%sT10:00:00Z" % day)
    r_h5 = recall(jsonl_h5, QH5, ["B", "C"], ["statestore"], "marked",
                  holdout_fraction=0.0, now=T1)   # A absent
    expect("H5: absent dominant A is NOT marked", r_h5["marked_option"] is None)
    expect("H5: recall still shown with a grounded challenge", r_h5["shown"] is True)
    _ch_blob = " ".join(r_h5["challenge"])
    expect("H5: no false 'you did not pick B' claim (B WAS chosen)",
           "not pick 'B'" not in _ch_blob and "did not pick 'B'" not in _ch_blob
           and "not chosen 'B'" not in _ch_blob)
    expect("H5: C (never chosen) may be honestly flagged as not-yet-picked",
           "not chosen 'C'" in _ch_blob)

    # ---- H5: NEVER claim "more often" on a TIE; allowed only on a real (strict) majority ----
    home_tie = os.path.join(tmp, "home_tie")
    jsonl_tie = decisions_path(home_tie)
    QT = "cache layer choice for the api gateway"
    OT = ["A", "B"]
    # TIE: A once, B once -> the dominant is only a deterministic tie-break, NOT "more often".
    capture(jsonl_tie, QT, OT, "A", "r", "unprompted", ["cachelayer"], recall_shown=False,
            challenged=False, changed_after_recall=False, suppressed_reason=None,
            holdout=False, now="2026-01-01T10:00:00Z")
    capture(jsonl_tie, QT, OT, "B", "r", "unprompted", ["cachelayer"], recall_shown=False,
            challenged=False, changed_after_recall=False, suppressed_reason=None,
            holdout=False, now="2026-01-02T10:00:00Z")
    r_tie = recall(jsonl_tie, QT, OT, ["cachelayer"], "on-demand", holdout_fraction=0.0,
                   now="2026-01-03T10:00:00Z")
    tie_blob = " ".join(r_tie["challenge"])
    expect("H5: a TIE never emits a false 'more often' claim",
           r_tie["shown"] is True and "more often" not in tie_blob)
    expect("H5: a TIE states the true equal-frequency fact instead", "equally often" in tie_blob)

    # real strict majority A,A,B -> 'more often' IS a truthful claim for B.
    home_maj = os.path.join(tmp, "home_maj")
    jsonl_maj = decisions_path(home_maj)
    for day, ch in (("01", "A"), ("02", "A"), ("03", "B")):
        capture(jsonl_maj, QT, OT, ch, "r", "unprompted", ["cachelayer"], recall_shown=False,
                challenged=False, changed_after_recall=False, suppressed_reason=None,
                holdout=False, now="2026-01-%sT10:00:00Z" % day)
    r_maj = recall(jsonl_maj, QT, OT, ["cachelayer"], "on-demand", holdout_fraction=0.0,
                   now="2026-01-04T10:00:00Z")
    maj_blob = " ".join(r_maj["challenge"])
    expect("H5: a real strict majority MAY claim 'more often'",
           r_maj["shown"] is True and "more often" in maj_blob)

    # ---- H4: a recent contradictory pick does NOT refresh confirmation -> can still expire ----
    home_h4 = os.path.join(tmp, "home_h4")
    jsonl_h4 = decisions_path(home_h4)
    QH4 = "linting posture for the shared package"
    OH4 = ["strict", "loose"]
    for day in ("01", "02", "03", "04"):                       # 4x strict (OLD)
        capture(jsonl_h4, QH4, OH4, "strict", "consistency", "unprompted", ["lint"],
                recall_shown=False, challenged=False, changed_after_recall=False,
                suppressed_reason=None, holdout=False, now="2026-01-%sT10:00:00Z" % day)
    capture(jsonl_h4, QH4, OH4, "loose", "one-off", "unprompted", ["lint"],   # 1x loose (NEW)
            recall_shown=False, challenged=False, changed_after_recall=False,
            suppressed_reason=None, holdout=False, now="2026-06-01T10:00:00Z")
    # staleness 60d: strict last-confirmed 2026-01-04 -> expired by 2026-06-02; the newer loose
    # (a contradiction, not a confirmation) must NOT keep the strict pattern fresh.
    r_h4 = recall(jsonl_h4, QH4, OH4, ["lint"], "on-demand", staleness_days=60,
                  holdout_fraction=0.0, now="2026-06-02T10:00:00Z")
    expect("H4: contradictory recent pick does not refresh -> pattern EXPIRES",
           r_h4["shown"] is False and r_h4["suppressed_reason"] == "expired")
    st_h4 = stats(jsonl_h4, staleness_days=60, now="2026-06-02T10:00:00Z")
    expect("H4: stats dates last_confirmed to the genuine (old) confirmation",
           st_h4["patterns"][0]["last_confirmed"][:10] == "2026-01-04")

    # ---- C3: default-mode capture (no drift/holdout flags) self-accrues drift -> demote ----
    home_c3 = os.path.join(tmp, "home_c3")
    jsonl_c3 = decisions_path(home_c3)
    QC3 = "primary worker backend for the epic build"
    OC3 = ["codex", "devin"]
    for day, ch in (("01", "codex"), ("02", "codex"), ("03", "codex"),
                    ("04", "devin"), ("05", "devin"), ("06", "devin")):
        # NOTE: no changed_after_recall / holdout passed -> spine computes drift ITSELF.
        capture(jsonl_c3, QC3, OC3, ch, "reason", "unprompted", ["c3backend"],
                recall_shown=False, challenged=False,
                now="2026-02-%sT10:00:00Z" % day, holdout_fraction=0.0)
    recs_c3 = load_records(jsonl_c3)
    expect("C3: spine set changed_after_recall on the switched picks (no caller input)",
           any(r["changed_after_recall"] for r in recs_c3))
    r_c3 = recall(jsonl_c3, QC3, OC3, [], "marked", holdout_fraction=0.0,
                  now="2026-02-07T10:00:00Z")
    expect("C3: default-mode captures accrue drift -> demoted + banner",
           r_c3["shown"] is False and r_c3["suppressed_reason"] == "demoted"
           and bool(r_c3["banner"]))

    # ---- C3: ONE source of truth — recall's holdout decision and capture's recorded holdout flag
    #      AGREE for every fork; a deterministic fraction of FORKS are held out (some, not all);
    #      and a record is NEVER labelled clean-holdout when recall would have surfaced it. ----
    home_hf = os.path.join(tmp, "home_hf")
    FRAC_HF = 0.5
    QUESTIONS_HF = ["marketing page fork variant number %d choice" % i for i in range(40)]
    holdout_n = 0
    agree = True
    for i, qhf in enumerate(QUESTIONS_HF):
        jhf = decisions_path(os.path.join(home_hf, "q%d" % i))
        rec_hf = capture(jhf, qhf, ["tailwind", "vanilla"],
                         "tailwind" if i % 2 else "vanilla", "r", "unprompted", ["css"],
                         recall_shown=False, challenged=False,
                         now="2026-03-01T10:00:00Z", holdout_fraction=FRAC_HF)
        # `_is_holdout(qhf, FRAC_HF)` IS recall's holdout decision (single source of truth).
        if rec_hf["holdout"] != _is_holdout(qhf, FRAC_HF):
            agree = False
    for qhf in QUESTIONS_HF:
        if _is_holdout(qhf, FRAC_HF):
            holdout_n += 1
    expect("C3: capture's holdout flag AGREES with recall's holdout decision for every fork", agree)
    expect("C3: a deterministic fraction of FORKS are holdout (some, not all)",
           0 < holdout_n < len(QUESTIONS_HF))

    # end-to-end: a holdout fork -> capture labels clean AND recall suppresses with 'holdout';
    #             a surfaced fork -> capture does NOT label clean AND recall does not suppress holdout.
    holdout_fork = next(q for q in QUESTIONS_HF if _is_holdout(q, FRAC_HF))
    surfaced_fork = next(q for q in QUESTIONS_HF if not _is_holdout(q, FRAC_HF))
    j_hold = decisions_path(os.path.join(home_hf, "e2e-hold"))
    rec_hold = capture(j_hold, holdout_fork, ["a", "b"], "a", "r", "unprompted", ["css"],
                       recall_shown=False, challenged=False, now="2026-03-02T10:00:00Z",
                       holdout_fraction=FRAC_HF)
    rc_hold = recall(j_hold, holdout_fork, ["a", "b"], ["css"], "on-demand",
                     holdout_fraction=FRAC_HF, now="2026-03-03T10:00:00Z")
    expect("C3: holdout fork -> capture clean-labels AND recall suppresses with 'holdout'",
           rec_hold["holdout"] is True and rc_hold["shown"] is False
           and rc_hold["suppressed_reason"] == "holdout")
    j_surf = decisions_path(os.path.join(home_hf, "e2e-surf"))
    rec_surf = capture(j_surf, surfaced_fork, ["a", "b"], "a", "r", "unprompted", ["css"],
                       recall_shown=False, challenged=False, now="2026-03-02T10:00:00Z",
                       holdout_fraction=FRAC_HF)
    rc_surf = recall(j_surf, surfaced_fork, ["a", "b"], ["css"], "on-demand",
                     holdout_fraction=FRAC_HF, now="2026-03-03T10:00:00Z")
    expect("C3: surfaced fork -> capture never clean-labels AND recall does not suppress holdout",
           rec_surf["holdout"] is False and rc_surf["suppressed_reason"] != "holdout")

    # ---- H6: a home root INSIDE the git repo is refused; a tmp dir outside is accepted ----
    repo_root_for_test = _cv_memory.find_repo_root(_SCRIPTS_DIR)
    bad_home = os.path.join(repo_root_for_test, "x-cv-selftest-must-not-exist")
    refused = False
    try:
        resolve_home_root(bad_home)
    except ValueError:
        refused = True
    expect("H6: a repo-internal home root is refused (raw log never in the tree)", refused)
    expect("H6: the refused repo path was never created",
           not os.path.exists(bad_home))
    accepted = False
    try:
        resolve_home_root(os.path.join(tmp, "outside-home"))   # tmp is outside the repo
        accepted = True
    except ValueError:
        accepted = False
    expect("H6: a tmp home root outside the repo is accepted", accepted)

    # H6 FAIL-CLOSED: if repo detection RAISES (or returns nothing), containment is unverifiable,
    # so the path must be REFUSED — not accepted (the old fail-open bug let the repo root through).
    def _raise_detection(*_a, **_k):
        raise RuntimeError("forced repo-detection failure")

    _orig_frr = _cv_memory.find_repo_root
    refused_raise = False
    try:
        _cv_memory.find_repo_root = _raise_detection
        try:
            assert_home_outside_repo(os.path.join(tmp, "outside-home-fc"))
        except ValueError:
            refused_raise = True
    finally:
        _cv_memory.find_repo_root = _orig_frr
    expect("H6: forced repo-detection FAILURE -> path REFUSED (fail-closed, not accepted)",
           refused_raise)

    refused_none = False
    try:
        _cv_memory.find_repo_root = lambda *_a, **_k: None
        try:
            assert_home_outside_repo(os.path.join(tmp, "outside-home-none"))
        except ValueError:
            refused_none = True
    finally:
        _cv_memory.find_repo_root = _orig_frr
    expect("H6: repo detection returning None -> path REFUSED (fail-closed)", refused_none)

    # ---- H7: an absolute local path in `why` is FULL locally but REDACTED in the distillate ----
    home_h7 = os.path.join(tmp, "home_h7")
    jsonl_h7 = decisions_path(home_h7)
    repo_md_h7 = os.path.join(tmp, "repo_h7", "preferences.md")
    path_why = ("kept notes at /var/tmp/client.txt copied /etc/hosts and "
                "/Users/alice/private/secret.txt for reference")
    capture(jsonl_h7, "where to store the working notes", ["local file", "shared drive"],
            "local file", path_why, "unprompted", ["notes"], recall_shown=False,
            challenged=False, changed_after_recall=False, suppressed_reason=None,
            holdout=False, now=T0)
    raw_h7 = open(jsonl_h7, encoding="utf-8").read()
    expect("H7: general + bare + home absolute paths are ALL FULL in the local jsonl",
           "/var/tmp/client.txt" in raw_h7 and "/etc/hosts" in raw_h7
           and "/Users/alice/private/secret.txt" in raw_h7)
    distill(jsonl_h7, repo_md_h7, now=T0)
    md_h7 = open(repo_md_h7, encoding="utf-8").read()
    expect("H7: distillate REDACTS a general absolute POSIX path (/var/tmp/client.txt)",
           "/var/tmp/client.txt" not in md_h7)
    expect("H7: distillate REDACTS a bare 2-segment path (/etc/hosts)",
           "/etc/hosts" not in md_h7)
    expect("H7: distillate REDACTS the home-scoped path (/Users/...)",
           "/Users/alice/private/secret.txt" not in md_h7)
    expect("H7: distillate carries the [REDACTED PATH] marker", "REDACTED PATH" in md_h7)

    # ---- purge wipes the local raw dir ----
    p = purge(home)
    expect("purge removes the local decisions log", p["purged"] is True)
    expect("decisions.jsonl gone after purge", not os.path.exists(jsonl))

    # cleanup
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    print("")
    if failures:
        print("SELFTEST FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("SELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
