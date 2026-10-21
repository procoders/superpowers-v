"""Retry configuration and the Claude escalation ladder."""

from __future__ import annotations

import os
import json
import re

from .util import (
    _read_json,
)


# The claude escalation ladder, bottom to top. A job that already failed once in
# this run is re-dispatched ONE rung up, never straight to the top: the
# maintainer's rule is "if we did not solve it the first time, hand it to Fable",
# and the cheapest honest reading of that is one step at a time.
CLAUDE_ESCALATION = ("sonnet", "opus", "fable")
PROJECT_STANCES = ("balanced", "conservative", "cost-aware", "claude-only")

# --- retry policy (v3.4.8) --------------------------------------------------
# The workflow's own retry budget, and the ONLY source of the backoff table.
# The emitted script reads both numbers out of CFG rather than carrying its own
# literals, so the JS the runtime executes and the Python that mirrors it cannot
# drift apart - the mirror IS the table, not a copy of it.
#
# NO JITTER, deliberately: `Math.random()` is refused by the workflow runtime
# (deterministic resume) and so is every clock read, so there is nothing to
# jitter with and nothing to measure. The waits are the failure policy's shape
# without the randomised term - 2 s, 4 s, 8 s ... capped at 60 s.
#
# `max_attempts` is TOTAL attempts, not extra ones: 3 (the default) is one call
# plus two retries, which is `PER_CLASS_MAX['overloaded']` from
# compound-v-failure-policy.py - the class of the incident that motivated this.
# `1` disables retrying without disabling anything else.
RETRY_MAX_ATTEMPTS_DEFAULT = 3
RETRY_ESCALATE_REVIEWER_DEFAULT = True
RETRY_BACKOFF_BASE_MS = 2000
RETRY_BACKOFF_CAP_MS = 60000

# What Record writes when a stage burned every attempt. The class is `other` and
# the text says why it is not `overloaded`: agent() resolves to null on a
# terminal API error and hands the script NO error text, so naming the class
# would be a guess wearing a measurement's clothes.
RETRY_EXHAUSTED_REASON = (
    "agent returned null %d times (transient API failure suspected; the "
    "runtime's failure text is not visible to the script)"
)


def retry_backoff_ms(attempt):
    """Milliseconds to wait AFTER `attempt` (1-based) produced no result.

    The Python mirror of the emitted `withRetry`'s wait, which reads the same two
    constants out of CFG: 2000, 4000, 8000 ... min-capped at 60000.
    """
    return min(RETRY_BACKOFF_CAP_MS,
               RETRY_BACKOFF_BASE_MS * (2 ** (max(1, int(attempt)) - 1)))


def _ladder_rung(model):
    """The ladder rung a resolved Claude model names, or None (`opus` and
    `claude-opus-5-5` are both the `opus` rung)."""
    key = str(model or "").strip().lower()
    if key in CLAUDE_ESCALATION:
        return key
    hits = [r for r in CLAUDE_ESCALATION if re.search(r"(?<![a-z])%s(?![a-z])" % r, key)]
    return hits[0] if len(hits) == 1 else None


def escalation_ladder(ceiling=None, stance=None):
    """(ladder, note). CLAUDE_ESCALATION cut at the stance's ceiling.

    `ceiling` is what the project's stance and config resolve the claude
    `frontier` tier to — the most a re-attempt may reach (`opus` under
    cost-aware). A ceiling the ladder cannot place falls back to the stance's
    documented ceiling: Opus for cost-aware, the full ladder otherwise.
    """
    rung = _ladder_rung(ceiling)
    note = None
    if rung is None:
        rung = "opus" if stance == "cost-aware" else CLAUDE_ESCALATION[-1]
        if ceiling:
            note = ("the frontier model %r is not a ladder rung; capped at %s"
                    % (ceiling, rung))
    elif stance == "cost-aware" and rung == "fable":
        # A legacy flat `models.claude.frontier: fable` applies to every stance;
        # cost-aware's ceiling is Opus whatever the config map says.
        rung = "opus"
        note = "cost-aware caps re-attempt escalation at opus (config frontier was fable)"
    return CLAUDE_ESCALATION[:CLAUDE_ESCALATION.index(rung) + 1], note


def escalation_map(ladder=CLAUDE_ESCALATION):
    """The ladder as a lookup the emitted script can use: {sonnet: opus, opus: fable}.

    Emitted from the (stance-capped) ladder rather than written out in JS, so the
    reviewer lift and `escalate_claude_model` step the same rungs. A model that is
    not a key - an explicit manifest pin we do not own, or the top rung - has no
    successor and is therefore never escalated, which is the same refusal
    `escalate_claude_model` makes in Python.
    """
    return dict(zip(ladder[:-1], ladder[1:]))


def _retry_value_ok(key, value):
    """True iff ``value`` is a legal ``retry.<key>``: an int ``1..3`` for
    ``max_attempts`` (a bool is not an int here), a JSON bool for
    ``escalate_reviewer``. Anything else is not a value, it is an absence."""
    if key == "max_attempts":
        return (isinstance(value, int) and not isinstance(value, bool)
                and 1 <= value <= RETRY_MAX_ATTEMPTS_DEFAULT)
    if key == "escalate_reviewer":
        return isinstance(value, bool)
    return False


def retry_config(manifest, config_path=None):
    """The run's retry budget, resolved to CFG.retry.

    PRECEDENCE, PER KEY: the manifest's top-level ``retry`` block, then the
    ``retry`` block of the project config (``.claude/compound-v.json``, the same
    ``config_path`` model resolution is handed), then the built-in defaults. The
    config is where /v:init's ``lightweight`` profile writes
    ``{max_attempts: 1, escalate_reviewer: false}``; a manifest that states a key
    still wins for that one run. Until 3.9.0 only the manifest was read, and the
    profile's ``retry`` row had no reader at all.

    Degrades to the defaults rather than raising: REFUSING a bad manifest value is
    compound-v-validate-manifest.py's job (it names the offending key), and the
    emitter's fallback must never be the thing that widens the budget - an
    out-of-range value is treated as absent at its level, never passed through,
    and every value that survives is ``<= RETRY_MAX_ATTEMPTS_DEFAULT``. The config
    is read the way the ``memory`` block below reads it (``_read_json``): a missing
    file, an unparseable one, a non-object root or a non-object ``retry``
    contributes nothing, and the run proceeds on the manifest and the defaults.
    """
    block = manifest.get("retry") if isinstance(manifest, dict) else None
    if not isinstance(block, dict):
        block = {}
    cfg_block = {}
    if isinstance(config_path, str) and config_path and os.path.isfile(config_path):
        _doc = _read_json(config_path, None)
        if isinstance(_doc, dict) and isinstance(_doc.get("retry"), dict):
            cfg_block = _doc["retry"]
    defaults = {"max_attempts": RETRY_MAX_ATTEMPTS_DEFAULT,
                "escalate_reviewer": RETRY_ESCALATE_REVIEWER_DEFAULT}
    resolved = {}
    for key, default in defaults.items():
        for source in (block, cfg_block):
            if key in source and _retry_value_ok(key, source[key]):
                resolved[key] = source[key]
                break
        else:
            resolved[key] = default
    return {
        "max_attempts": resolved["max_attempts"],
        "escalate_reviewer": resolved["escalate_reviewer"],
        "base_ms": RETRY_BACKOFF_BASE_MS,
        "cap_ms": RETRY_BACKOFF_CAP_MS,
    }


# The keys a retry-log entry may carry, and nothing else. The log is machine
# generated by the emitted script, which is not a reason to trust it: it arrives
# through argv, so it is validated before anything is written from it.
RETRY_ENTRY_KEYS = ("stage", "job", "attempt", "wait_ms", "escalated_from", "model")


def _sanitize_retry_meta(raw):
    """(meta, error). Parse `--retries-json` into a shape that is safe to record.

    Never raises and never refuses the RESULT: a malformed bookkeeping field must
    not cost a job its evidence, so a failure returns (None, reason) and Record
    records the reason beside the result it still writes.
    """
    if not raw:
        return None, None
    try:
        doc = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        return None, "retries JSON unparseable: %s" % exc
    if not isinstance(doc, dict):
        return None, "retries JSON was not an object"
    entries = []
    for item in (doc.get("retries") or []):
        if not isinstance(item, dict):
            continue
        clean = {}
        for key in RETRY_ENTRY_KEYS:
            val = item.get(key)
            if val is None or isinstance(val, bool):
                continue
            if isinstance(val, int):
                clean[key] = val
            elif isinstance(val, str) and re.match(r"^[A-Za-z0-9_.:@+-]{1,120}$", val):
                clean[key] = val
        if clean:
            entries.append(clean)
    attempts = doc.get("attempts")
    if not (isinstance(attempts, int) and not isinstance(attempts, bool)
            and attempts >= 1):
        attempts = len(entries) + 1
    escalated_from = doc.get("escalated_from")
    if not (isinstance(escalated_from, str)
            and re.match(r"^[A-Za-z0-9_.:@+-]{1,120}$", escalated_from)):
        escalated_from = None
    return {
        "retries": entries,
        "exhausted": bool(doc.get("exhausted")),
        "attempts": attempts,
        "escalated_from": escalated_from,
    }, None


def apply_retry_meta(result, meta):
    """Stamp an exhausted retry budget onto a job_result, HONESTLY.

    Two deliberate non-actions:

    * the class is `other`, never `overloaded` - see RETRY_EXHAUSTED_REASON;
    * `retries` and `escalated_from` are stamped by Record, not here: the
      3.4.8 review-1 closure extended schemas/job_result.schema.json with both
      keys, so the job_result carries the log (state.json and Record's ack keep
      their copies). This helper owns only the class and the reason.
    """
    if not meta or not meta.get("exhausted"):
        return result
    if result.get("status") != "success":
        result["failure_class"] = "other"
        result["summary"] = "%s - %s" % (
            RETRY_EXHAUSTED_REASON % int(meta.get("attempts") or 1),
            result.get("summary") or "",
        )
    return result

# Mirror of compound-v-validate-manifest.py:REVIEWER_TOKENS. DUPLICATED on
# purpose — both are standalone stdlib CLIs with no shared import (house style).
# Keep in sync.
REVIEWER_TOKENS = ("review", "reviewer", "spec_review", "quality", "integration")


def _is_reviewer_job(job):
    """True iff this job is a reviewer. EXACT mirror of
    compound-v-validate-manifest.py:_is_reviewer — `type` decides when present, and
    the id/title fallback matches on word boundaries. Duplicated on purpose (both are
    standalone stdlib CLIs); keep in sync. The looser substring scan classified a job
    titled "Writes the thing the reviewer reviews" as a reviewer — see that docstring.
    """
    jtype = str(job.get("type") or "").strip().lower()
    if jtype:
        return any(tok in jtype for tok in REVIEWER_TOKENS)
    haystack = "%s %s" % (str(job.get("id") or "").lower(),
                          str(job.get("title") or "").lower())
    return any(re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(tok), haystack)
               for tok in REVIEWER_TOKENS)


def prior_attempt_failed(run_dir, job_id):
    """True iff this job already has a RECORDED non-success result in this run.

    The signal is the recorded result, not a counter we keep ourselves: `record`
    writes results/<id>.json for every terminal job, and /v:resume re-runs this
    emitter against the same run dir. An absent or unreadable result is NOT a
    failure — escalation must be earned by evidence, never by a missing file.
    """
    doc = _read_json(os.path.join(run_dir, "results", "%s.json" % job_id), None)
    if not isinstance(doc, dict):
        return False
    status = str(doc.get("status") or "").strip().lower()
    return bool(status) and status != "success"


def escalate_claude_model(model, ladder=CLAUDE_ESCALATION):
    """(model, capped_reason). One rung up `ladder`, or unchanged at its top.

    A model outside the ladder (an explicitly pinned string we do not own) is
    returned untouched: escalating a value we did not choose would be a
    fabricated routing decision. `ladder` is the stance-capped one from
    `escalation_ladder`; a model above its top is never stepped either.
    """
    key = str(model or "").strip().lower()
    if key not in CLAUDE_ESCALATION:
        return model, "%r is not on the claude ladder" % model
    if key not in ladder or ladder.index(key) + 1 >= len(ladder):
        if len(ladder) < len(CLAUDE_ESCALATION):
            return model, ("already at the top of the ladder this stance allows (%s)"
                           % ladder[-1])
        return model, "already at the top of the ladder"
    return ladder[ladder.index(key) + 1], None
