#!/usr/bin/env python3
"""
Compound V — the fast-path MATERIALIZER (v2.9 Task M1, AC-14/AC-15, CR2-2/CR3-5/CR4-3).

Given an accepted ``FASTPATH_ELIGIBLE`` pre-eval RECORD (written by A3 under
``docs/superpowers/pre-eval/<pre_eval_id>.json``), this materializes + commits the run
artifacts the dispatcher then executes — the single-job ``fast_path`` manifest, minimal
committed spec/plan STUBS, block-YAML audit SKIP-records, the immutable taxonomy snapshot
copied into the run, the captured implementer prompt — and finally the ``state.json`` at
``FASTPATH_DISPATCHED``. It is the **Phase-M** half of the Lifecycle & commit-ordering
protocol (the SINGLE AUTHORITY in the plan); every task defers to that ordering.

Phase M — materialize (ONLY on an accepted ``FASTPATH_ELIGIBLE`` record):

    5. mint a **deterministic** run-id from ``pre_eval_id``  (``fastpath-<pre_eval_id>``).
    6. copy the pre-eval taxonomy snapshot INTO the run (preserving ``taxonomy_ref`` /
       ``taxonomy_digest``); write the spec/plan stubs, block-YAML audit skip-records, the
       ``fast_path`` manifest carrying the review **DECLARATION only** (no receipt yet), and
       the captured implementer prompt (``jobs/<id>.prompt.md``).
    7. commit ALL run artifacts **EXCEPT** ``state.json``.
    8. append + commit the ``bind`` event ``{pre_eval_id, run_id}`` — **BEFORE** state (CR4-3).
    9. commit ``state.json`` at ``FASTPATH_DISPATCHED`` **LAST**.

    Invariant: *a committed ``state.json`` ⇒ ``bind`` already durable ⇒ the run is complete.*
    A run dir with committed artifacts but no committed ``state.json`` is INCOMPLETE and is
    rebuilt deterministically on resume (same ``pre_eval_id`` → same run-id → an existing
    child is discovered before another is minted). A ``state.json`` without a durable
    ``bind`` is impossible **by construction** (bind is always committed first).

Idempotent + crash-consistent (CR3-5/AC-15): a crash after EACH write/commit boundary
reconciles on the next ``run_materialize`` call — already-committed artifacts produce no new
commit (nothing to stage), an appended-but-uncommitted ``bind`` is committed, and a
partially-written ``state.json`` is finished. A **tampered record** (the pinned record's
``localization.resolved_paths[0]`` disagreeing with the committed localization artifact, or a
non-``FASTPATH_ELIGIBLE`` decision, or a snapshot whose bytes don't content-address to the
record's ``taxonomy_digest``) is rejected **BEFORE any write or commit**.

The materialized manifest is built to pass ``compound-v-validate-manifest.py --mode
pre-dispatch``: exactly one non-reviewer implementer job, a single LITERAL ``write_allowed``
equal to ``localization.resolved_paths[0]``, all cross-artifact bindings (``pre_eval_id`` /
decision / ``taxonomy_digest`` / localization content-digest) equal across manifest + record
+ artifact, CR4-6 containment, and a ``fast_path.review`` declaration (``backend: claude`` +
``tier: deep``) that resolves to Claude Opus — with NO review receipt yet.

Commit discipline (v2.6.4): every commit is a **two-command** sequence (``git add`` then
``git commit``, no ``&&``), each exit code checked, and each ``git commit`` is **pathspec-
limited** so an unrelated pre-staged change is never swept into a lifecycle commit.

Reuse (imported BY PATH, never recopied):
  * ``compound-v-taxonomy.py``          — record_digest / taxonomy_digest_file / classify
  * ``compound-v-preeval.py``           — record/snapshot path helpers, PRE_EVAL_ID_RE
  * ``compound-v-localize.py``          — artifact_rel_path (the localization artifact)
  * ``compound-v-triage-outcomes.py``   — bind_run (append-only) + the stream relpath
  * ``compound-v-validate-manifest.py`` — validate(mode='pre-dispatch') as the in-code gate

Python 3.9-safe, stdlib only; block-YAML output (soft-PyYAML: the emitter is a hand-rolled
block serializer — NEVER flow ``{}`` — so both PyYAML and the validator's ``_mini_yaml``
fallback re-parse it). No fabricated metrics. Fail-closed everywhere. Never Haiku.

Usage:
    compound-v-fastpath-materialize.py materialize --repo DIR --pre-eval-id ID \\
        [--prompt-file FILE] [--stance balanced|conservative|cost-aware|claude-only] \\
        [--feature TEXT]
    compound-v-fastpath-materialize.py --selftest
"""

import argparse
import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys


# --------------------------------------------------------------------------- #
# Constants.
# --------------------------------------------------------------------------- #
EXEC_DIR_REL = os.path.join("docs", "superpowers", "execution")
PRE_EVAL_DIR_REL = os.path.join("docs", "superpowers", "pre-eval")
TRIAGE_STREAM_REL = os.path.join("docs", "superpowers", "memory", "triage-outcomes.jsonl")

IMPL_JOB_ID = "task-fastpath-impl"          # never a reviewer token (review/quality/…)
PHASE_FASTPATH_DISPATCHED = "FASTPATH_DISPATCHED"
DECISION_FASTPATH = "FASTPATH_ELIGIBLE"
STATUS_PRE_EVAL_DONE = "PRE_EVAL_DONE"

RUN_ID_PREFIX = "fastpath-"
_GLOB_METACHARS = set("*?[]{}")


class MaterializeError(Exception):
    """A fail-closed rejection raised BEFORE any write/commit (tamper / malformed record)."""


# --------------------------------------------------------------------------- #
# Sibling reuse by path (hyphenated filenames → importlib). Loaded lazily.
# --------------------------------------------------------------------------- #
def _here():
    return os.path.dirname(os.path.abspath(__file__))


_MOD_CACHE = {}


def _load_sibling(basename, modname):
    if basename in _MOD_CACHE:
        return _MOD_CACHE[basename]
    path = os.path.join(_here(), basename)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _MOD_CACHE[basename] = mod
    return mod


def _tax():
    return _load_sibling("compound-v-taxonomy.py", "compound_v_taxonomy")


def _preeval():
    return _load_sibling("compound-v-preeval.py", "compound_v_preeval")


def _localize():
    return _load_sibling("compound-v-localize.py", "compound_v_localize")


def _triage():
    return _load_sibling("compound-v-triage-outcomes.py", "compound_v_triage_outcomes")


def _validator():
    return _load_sibling("compound-v-validate-manifest.py", "compound_v_validate_manifest")


# --------------------------------------------------------------------------- #
# Small helpers.
# --------------------------------------------------------------------------- #
def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mint_run_id(pre_eval_id):
    """Deterministic run-id: ``fastpath-<pre_eval_id>``. Same pre_eval_id ⇒ same run-id, so
    resume discovers an existing child before minting another. The pre_eval_id charset
    (``YYYY-MM-DDThhmmssZ-<slug>-<nonce>``) is a subset of the validator's id-safe charset
    (``A-Za-z0-9._-``), so the derived run-id is a valid run-dir / path segment."""
    pe = _preeval()
    if not pe.PRE_EVAL_ID_RE.match(pre_eval_id or ""):
        raise MaterializeError("invalid pre_eval_id: %r" % pre_eval_id)
    return RUN_ID_PREFIX + pre_eval_id


def _is_single_literal_path(paths):
    if not isinstance(paths, list) or len(paths) != 1:
        return False
    p = paths[0]
    if not isinstance(p, str) or not p:
        return False
    if os.path.isabs(p) or ".." in p.replace("\\", "/").split("/"):
        return False
    if os.path.normpath(p) != p:
        return False
    return not any(c in _GLOB_METACHARS for c in p)


def _read_json(full):
    with open(full, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# Block-YAML emitter (never flow {}). Tailored to the manifest shape and
# re-parseable by BOTH PyYAML and the validator's _mini_yaml fallback. Every
# string is double-quoted (safe in both parsers); ints/bools are bare.
# --------------------------------------------------------------------------- #
def _scalar_out(v):
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    if isinstance(v, int):
        return str(v)
    s = str(v)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _dump_block(obj, indent=0):
    pad = "  " * indent
    lines = []
    for k, v in obj.items():
        if isinstance(v, dict):
            if not v:
                raise MaterializeError("refusing to emit an empty mapping for %r "
                                       "(flow {} is banned)" % k)
            lines.append("%s%s:" % (pad, k))
            lines.extend(_dump_block(v, indent + 1))
        elif isinstance(v, list):
            if not v:
                lines.append("%s%s: []" % (pad, k))
            else:
                lines.append("%s%s:" % (pad, k))
                lines.extend(_dump_list(v, indent + 1))
        else:
            lines.append("%s%s: %s" % (pad, k, _scalar_out(v)))
    return lines


def _dump_list(items, indent):
    pad = "  " * indent
    rest_pad = "  " * (indent + 1)
    out = []
    for item in items:
        if isinstance(item, dict):
            kv = list(item.items())
            if not kv:
                raise MaterializeError("refusing to emit an empty list-item mapping")
            fk, fv = kv[0]
            if isinstance(fv, (dict, list)):
                raise MaterializeError("list-item first key %r must be a scalar" % fk)
            out.append("%s- %s: %s" % (pad, fk, _scalar_out(fv)))
            for k, v in kv[1:]:
                if isinstance(v, dict):
                    out.append("%s%s:" % (rest_pad, k))
                    out.extend(_dump_block(v, indent + 2))
                elif isinstance(v, list):
                    if not v:
                        out.append("%s%s: []" % (rest_pad, k))
                    else:
                        out.append("%s%s:" % (rest_pad, k))
                        out.extend(_dump_list(v, indent + 2))
                else:
                    out.append("%s%s: %s" % (rest_pad, k, _scalar_out(v)))
        else:
            out.append("%s- %s" % (pad, _scalar_out(item)))
    return out


def dump_manifest_yaml(manifest):
    """Serialize the manifest dict to block YAML (never flow {})."""
    return "\n".join(_dump_block(manifest, 0)) + "\n"


# --------------------------------------------------------------------------- #
# Pre-flight: tamper rejection BEFORE any write/commit.
# --------------------------------------------------------------------------- #
def _preflight(repo, pre_eval_id):
    """Validate the accepted record + its committed sibling artifacts. Raises
    MaterializeError (fail-closed) on any mismatch — a tampered/ineligible record is
    rejected here, before a single byte of the run is written. Returns
    ``(record, artifact, write_literal, snapshot_full, taxonomy_digest)``."""
    pe = _preeval()
    tax = _tax()
    loc = _localize()

    rec_full = pe.record_path(repo, pre_eval_id)
    if not os.path.isfile(rec_full):
        raise MaterializeError("pre-eval record not found: %s" % rec_full)
    try:
        record = _read_json(rec_full)
    except ValueError as e:
        raise MaterializeError("pre-eval record is not valid JSON (%s)" % e)

    if record.get("pre_eval_id") != pre_eval_id:
        raise MaterializeError("record pre_eval_id %r != requested %r"
                               % (record.get("pre_eval_id"), pre_eval_id))
    if record.get("status") != STATUS_PRE_EVAL_DONE:
        raise MaterializeError("record status %r is not %s"
                               % (record.get("status"), STATUS_PRE_EVAL_DONE))
    if record.get("decision") != DECISION_FASTPATH:
        raise MaterializeError("record decision %r is not %s — not fast-path eligible"
                               % (record.get("decision"), DECISION_FASTPATH))

    tax_ref = record.get("taxonomy_ref")
    tax_digest = record.get("taxonomy_digest")
    if not tax_ref or not tax_digest:
        raise MaterializeError("FASTPATH record must carry a non-null taxonomy_ref + "
                               "taxonomy_digest (got ref=%r digest=%r)"
                               % (tax_ref, tax_digest))

    rec_loc = record.get("localization")
    if not isinstance(rec_loc, dict):
        raise MaterializeError("record localization is missing or not a mapping")
    if rec_loc.get("confidence") != "exact":
        raise MaterializeError("record localization confidence %r is not 'exact'"
                               % rec_loc.get("confidence"))
    rec_paths = rec_loc.get("resolved_paths")
    if not _is_single_literal_path(rec_paths):
        raise MaterializeError("record localization resolved_paths %r is not a single "
                               "literal normalized path" % (rec_paths,))

    # The committed localization ARTIFACT (the value C1 binds against).
    art_rel = loc.artifact_rel_path(pre_eval_id)
    art_full = os.path.join(repo, art_rel)
    if not os.path.isfile(art_full):
        raise MaterializeError("localization artifact not found: %s" % art_rel)
    try:
        artifact = _read_json(art_full)
    except ValueError as e:
        raise MaterializeError("localization artifact is not valid JSON (%s)" % e)

    art_paths = artifact.get("resolved_paths")
    if not _is_single_literal_path(art_paths):
        raise MaterializeError("localization artifact resolved_paths %r is not a single "
                               "literal normalized path" % (art_paths,))

    # TAMPER GUARD: the record's localization must agree with the committed artifact,
    # both on the resolved path AND on the canonical-JSON content-digest C1 binds.
    if rec_paths[0] != art_paths[0]:
        raise MaterializeError(
            "TAMPER: record localization resolved_paths[0] %r != artifact %r"
            % (rec_paths[0], art_paths[0]))
    try:
        d_rec = tax.record_digest(rec_loc, exclude_field="digest")
        d_art = tax.record_digest(artifact, exclude_field="digest")
    except ValueError as e:
        raise MaterializeError("cannot compute localization content-digest (%s)" % e)
    if d_rec != d_art:
        raise MaterializeError("TAMPER: localization content-digest differs between "
                               "record and artifact")
    if isinstance(artifact.get("digest"), str) and artifact["digest"] != d_art:
        raise MaterializeError("TAMPER: localization artifact self-digest mismatch")

    # The pre-run taxonomy snapshot must content-address to the record's digest.
    snap_full = pe.snapshot_path(repo, pre_eval_id)
    if not os.path.isfile(snap_full):
        raise MaterializeError("pre-eval taxonomy snapshot not found: %s" % snap_full)
    try:
        snap_digest = tax.taxonomy_digest_file(snap_full)
    except OSError as e:
        raise MaterializeError("cannot read taxonomy snapshot (%s)" % e)
    if snap_digest != tax_digest:
        raise MaterializeError("TAMPER: taxonomy snapshot content-address %r != record "
                               "taxonomy_digest %r" % (snap_digest, tax_digest))

    return record, artifact, art_paths[0], snap_full, tax_digest


# --------------------------------------------------------------------------- #
# Manifest / stub / state builders.
# --------------------------------------------------------------------------- #
def _read_scope_for(write_literal):
    d = os.path.dirname(write_literal)
    return (d + "/**") if d else write_literal


def build_manifest(run_id, pre_eval_id, record, artifact, write_literal, snapshot_digest,
                   *, feature, spec_path, plan_path, pre_eval_ref, localization_ref,
                   run_taxonomy_ref, prompt_ref, stance="balanced"):
    """Build the conditional ``fast_path`` manifest dict (single implementer job; review as a
    dispatcher PHASE declaration; block-YAML audit skip-records; all cross-artifact bindings
    satisfied). Constructed to pass ``validate(mode='pre-dispatch')``."""
    taxonomy_version = record.get("taxonomy_version")
    if taxonomy_version in (None, ""):
        taxonomy_version = "unversioned"

    skip = {
        "skipped": True,
        "reason": "fastpath",
        "localization": localization_ref,
        "taxonomy_version": taxonomy_version,
    }
    manifest = {
        "run_id": run_id,
        "feature": feature,
        "spec_path": spec_path,
        "plan_path": plan_path,
        "audits": {
            "archaeology": dict(skip),
            "domain": dict(skip),
            "library": dict(skip),
        },
        "acceptance_criteria": [
            "The change is confined to the single localized file",
            "Combined SPEC+QUALITY Opus review approves the diff",
            "No write outside the fast-path scope",
        ],
        "routing_stance": stance,
        "max_parallel": 1,
        "fast_path": {
            "eligible": True,
            "pre_eval_id": pre_eval_id,
            "pre_eval_ref": pre_eval_ref,
            "localization_ref": localization_ref,
            "taxonomy_ref": run_taxonomy_ref,
            "taxonomy_digest": snapshot_digest,
            "review": {"backend": "claude", "tier": "deep"},
        },
        "jobs": [
            {
                "id": IMPL_JOB_ID,
                "title": "Fast-path implementer: " + str(record.get("request_slug") or ""),
                "type": "bounded_crud",
                "backend": "claude",
                "tier": "standard",
                "effort": "medium",
                "isolation": "worktree",
                "run": "serial",
                "prompt": prompt_ref,
                "write_allowed": [write_literal],
                "read_allowed": [_read_scope_for(write_literal)],
                "acceptance": [
                    "Implements the requested change in the single localized file",
                    "Writes only " + write_literal + " (scope-gated)",
                ],
            }
        ],
    }
    return manifest


def _spec_stub(record, write_literal, pre_eval_id):
    slug = record.get("request_slug") or pre_eval_id
    return (
        "# Fast-path spec stub — %s\n\n"
        "> Materialized by `/v:orchestrate` fast-path from pre-eval `%s`.\n"
        "> This is a MINIMAL committed stub, not a full brainstorm output (the change was\n"
        "> triaged `FASTPATH_ELIGIBLE`: provably trivial + low-impact, single localized file).\n\n"
        "## Acceptance criteria\n\n"
        "- The change is confined to `%s`.\n"
        "- The combined SPEC+QUALITY Opus review approves the diff.\n"
        "- No write outside the fast-path scope (git-derived scope gate).\n"
        % (slug, pre_eval_id, write_literal)
    )


def _plan_stub(record, write_literal, pre_eval_id):
    slug = record.get("request_slug") or pre_eval_id
    return (
        "# Fast-path plan stub — %s\n\n"
        "> Materialized by `/v:orchestrate` fast-path from pre-eval `%s`.\n\n"
        "Single task: apply the requested change to `%s` only. Partition Map is the sole\n"
        "`write_allowed` literal in the fast-path manifest. Review is a dispatcher phase\n"
        "(`fast_path.review`), not a `jobs` entry.\n"
        % (slug, pre_eval_id, write_literal)
    )


def _default_prompt(record, write_literal, pre_eval_id):
    slug = record.get("request_slug") or pre_eval_id
    return (
        "# Fast-path implementer prompt (%s)\n\n"
        "Apply the localized change described by pre-eval `%s` (slug: `%s`).\n\n"
        "SCOPE LOCK: you may write ONLY `%s`. Any other write BLOCKS the job (git scope gate).\n"
        "Make the smallest correct edit that satisfies the request; do not refactor neighbors.\n"
        % (pre_eval_id, pre_eval_id, slug, write_literal)
    )


def build_state(run_id, pre_eval_id, ts=None):
    return {
        "run_id": run_id,
        "phase": PHASE_FASTPATH_DISPATCHED,
        "updated_at": ts or _now_iso(),
        "pre_eval_id": pre_eval_id,
        "escalated_to": None,
        "jobs": {
            IMPL_JOB_ID: {
                "status": "pending",
                "isolation": "worktree",
                "worktree": None,
                "session_id": None,
                "baseline": None,
                "log": None,
            }
        },
    }


# --------------------------------------------------------------------------- #
# Filesystem writers (idempotent; NEVER commit — the caller does).
# --------------------------------------------------------------------------- #
def _write_text(full, text):
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(text)


def _write_json(full, obj):
    _write_text(full, json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _copy_snapshot(snap_src_full, dst_full):
    """Copy the immutable taxonomy snapshot bytes (idempotent). Preserves the content-address."""
    with open(snap_src_full, "rb") as fh:
        data = fh.read()
    os.makedirs(os.path.dirname(dst_full), exist_ok=True)
    with open(dst_full, "wb") as fh:
        fh.write(data)


# --------------------------------------------------------------------------- #
# Git primitives (pathspec-limited, two-command discipline). Run ONLY against the
# repo passed in — the selftest uses a tempdir OUTSIDE this worktree.
# --------------------------------------------------------------------------- #
def _run_git(repo, args, check=True, capture=False):
    # Always capture git's own chatter so it never leaks into the CLI's JSON stdout;
    # only RETURN stdout when the caller asked for it.
    r = subprocess.run(["git", "-C", repo] + list(args),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace") if r.stderr else ""
        raise MaterializeError("git %s failed (%d): %s"
                               % (" ".join(args), r.returncode, err.strip()))
    if capture:
        return r.returncode, r.stdout.decode("utf-8", "replace")
    return r.returncode, ""


def _git_tracked(git, repo, rel):
    rc, _ = git(repo, ["ls-files", "--error-unmatch", "--", rel], check=False, capture=True)
    return rc == 0


def _paths_dirty(git, repo, rel_paths):
    _rc, out = git(repo, ["status", "--porcelain", "--"] + list(rel_paths),
                   check=False, capture=True)
    return out.strip() != ""


def _commit_paths(git, repo, rel_paths, message):
    """Two-command, pathspec-limited commit of exactly ``rel_paths`` (CR5-9 spirit — an
    unrelated pre-staged change is never swept in). Idempotent: nothing dirty ⇒ no commit
    (returns False). Each git exit code is checked (raises on failure)."""
    rel_paths = list(rel_paths)
    if not _paths_dirty(git, repo, rel_paths):
        return False
    git(repo, ["add", "--"] + rel_paths)                     # command 1
    git(repo, ["commit", "-m", message, "--"] + rel_paths)   # command 2
    return True


# --------------------------------------------------------------------------- #
# Bind (idempotent append + commit) — Lifecycle step 8, BEFORE state (CR4-3).
# --------------------------------------------------------------------------- #
def _bind_present(stream_full, pre_eval_id, run_id):
    if not os.path.isfile(stream_full):
        return False
    with open(stream_full, "r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                continue
            if (isinstance(obj, dict) and obj.get("event") == "bind"
                    and obj.get("pre_eval_id") == pre_eval_id
                    and obj.get("run_id") == run_id):
                return True
    return False


def _ensure_bind(git, repo, pre_eval_id, run_id, ts=None):
    """Append the ``bind`` event if not already present (idempotent across resume — a crash
    after append-before-commit is handled: the line is present so we skip re-append but the
    commit below still captures the uncommitted stream), then commit the stream."""
    stream_full = os.path.join(repo, TRIAGE_STREAM_REL)
    if not _bind_present(stream_full, pre_eval_id, run_id):
        _triage().bind_run(pre_eval_id, run_id, ts=ts, stream_path=stream_full)
    _commit_paths(git, repo, [TRIAGE_STREAM_REL],
                  "chore(v2.9): bind fast-path run %s to %s" % (run_id, pre_eval_id))


# --------------------------------------------------------------------------- #
# In-code C1 gate.
# --------------------------------------------------------------------------- #
def _validate_predispatch(repo, manifest_rel):
    """Run the C1 validator in ``pre-dispatch`` mode over the materialized manifest. Returns
    the list of violation strings (empty ⇒ valid)."""
    val = _validator()
    manifest_full = os.path.join(repo, manifest_rel)
    with open(manifest_full, "r", encoding="utf-8") as fh:
        manifest = val.load_yaml(fh.read())
    return val.validate(manifest, mode="pre-dispatch", repo_root=repo)


# --------------------------------------------------------------------------- #
# THE Phase-M orchestrator.
# --------------------------------------------------------------------------- #
def run_materialize(repo, pre_eval_id, *, prompt_text=None, stance="balanced",
                    feature=None, ts=None, _git=None, _stop_after=None):
    """Materialize + commit the fast-path run for an accepted ``FASTPATH_ELIGIBLE`` record.

    Idempotent + crash-consistent. ``_git`` injects a git runner (tests); ``_stop_after`` ∈
    {``'artifacts'``, ``'bind'``, ``None``} lets a test simulate a crash exactly at a
    write/commit boundary. Returns a summary dict; raises ``MaterializeError`` (fail-closed)
    on a tampered/ineligible record — BEFORE any write or commit."""
    git = _git or _run_git
    ts = ts or _now_iso()

    # --- Phase-M pre-flight: reject a tampered/ineligible record before ANY write. ------
    record, artifact, write_literal, snap_full, snap_digest = _preflight(repo, pre_eval_id)

    # --- Step 5: mint the DETERMINISTIC run-id. -----------------------------------------
    run_id = mint_run_id(pre_eval_id)
    run_dir_rel = os.path.join(EXEC_DIR_REL, run_id)
    state_rel = os.path.join(run_dir_rel, "state.json")
    state_full = os.path.join(repo, state_rel)

    # --- Idempotent resume: a committed state.json at FASTPATH_DISPATCHED ⇒ complete. ---
    if _git_tracked(git, repo, state_rel) and os.path.isfile(state_full):
        try:
            if _read_json(state_full).get("phase") == PHASE_FASTPATH_DISPATCHED:
                return {"run_id": run_id, "pre_eval_id": pre_eval_id,
                        "status": "already_complete", "manifest_ref": None}
        except ValueError:
            pass  # unreadable committed state → fall through and rebuild deterministically

    # --- Step 6: write the run artifacts (idempotent; deterministic content). ------------
    spec_rel = os.path.join(run_dir_rel, "spec.md")
    plan_rel = os.path.join(run_dir_rel, "plan.md")
    manifest_rel = os.path.join(run_dir_rel, "manifest.yaml")
    prompt_rel = os.path.join(run_dir_rel, "jobs", IMPL_JOB_ID + ".prompt.md")
    prompt_ref = os.path.join("jobs", IMPL_JOB_ID + ".prompt.md")  # manifest-relative-to-run
    run_tax_rel = os.path.join(run_dir_rel, "taxonomy-snapshot.yaml")

    pe = _preeval()
    pre_eval_ref = pe._rel(repo, pe.record_path(repo, pre_eval_id))
    localization_ref = _localize().artifact_rel_path(pre_eval_id)

    feature = feature or ("Fast-path change: " + str(record.get("request_slug") or pre_eval_id))
    _write_text(os.path.join(repo, spec_rel),
                _spec_stub(record, write_literal, pre_eval_id))
    _write_text(os.path.join(repo, plan_rel),
                _plan_stub(record, write_literal, pre_eval_id))
    _write_text(os.path.join(repo, prompt_rel),
                prompt_text or _default_prompt(record, write_literal, pre_eval_id))
    _copy_snapshot(snap_full, os.path.join(repo, run_tax_rel))

    manifest = build_manifest(
        run_id, pre_eval_id, record, artifact, write_literal, snap_digest,
        feature=feature, spec_path=spec_rel, plan_path=plan_rel,
        pre_eval_ref=pre_eval_ref, localization_ref=localization_ref,
        run_taxonomy_ref=run_tax_rel, prompt_ref=prompt_ref, stance=stance)
    _write_text(os.path.join(repo, manifest_rel), dump_manifest_yaml(manifest))

    # --- Step 7: commit ALL run artifacts EXCEPT state.json. ----------------------------
    artifact_paths = [spec_rel, plan_rel, manifest_rel,
                      os.path.join(run_dir_rel, "jobs", IMPL_JOB_ID + ".prompt.md"),
                      run_tax_rel]
    _commit_paths(git, repo, artifact_paths,
                  "feat(v2.9): materialize fast-path run %s (artifacts)" % run_id)

    # --- In-code C1 gate: the committed manifest MUST pass --mode pre-dispatch. ----------
    problems = _validate_predispatch(repo, manifest_rel)
    if problems:
        raise MaterializeError(
            "materialized fast-path manifest failed C1 --mode pre-dispatch:\n  - "
            + "\n  - ".join(problems))

    if _stop_after == "artifacts":
        return {"run_id": run_id, "pre_eval_id": pre_eval_id,
                "status": "stopped_after_artifacts", "manifest_ref": manifest_rel}

    # --- Step 8: append + commit the bind event — BEFORE state (CR4-3). -----------------
    _ensure_bind(git, repo, pre_eval_id, run_id, ts=ts)

    if _stop_after == "bind":
        return {"run_id": run_id, "pre_eval_id": pre_eval_id,
                "status": "stopped_after_bind", "manifest_ref": manifest_rel}

    # --- Step 9: commit state.json at FASTPATH_DISPATCHED — LAST. -----------------------
    _write_json(state_full, build_state(run_id, pre_eval_id, ts=ts))
    _commit_paths(git, repo, [state_rel],
                  "chore(v2.9): fast-path run %s dispatched (state)" % run_id)

    return {"run_id": run_id, "pre_eval_id": pre_eval_id, "status": "materialized",
            "manifest_ref": manifest_rel, "state_ref": state_rel,
            "write_allowed": write_literal}


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()

    ap = argparse.ArgumentParser(prog="compound-v-fastpath-materialize.py")
    sub = ap.add_subparsers(dest="cmd")
    pm = sub.add_parser("materialize", help="materialize + commit a fast-path run")
    pm.add_argument("--repo", default=".", help="repo root (default: cwd)")
    pm.add_argument("--pre-eval-id", dest="pre_eval_id", required=True)
    pm.add_argument("--prompt-file", dest="prompt_file",
                    help="captured implementer prompt (default: a generated stub)")
    pm.add_argument("--stance", default="balanced",
                    choices=["balanced", "conservative", "cost-aware", "claude-only"])
    pm.add_argument("--feature", help="feature title (default: derived from the record)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv[1:])

    if args.cmd != "materialize":
        ap.print_usage(sys.stderr)
        return 2

    prompt_text = None
    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as fh:
            prompt_text = fh.read()
    try:
        result = run_materialize(args.repo, args.pre_eval_id, prompt_text=prompt_text,
                                 stance=args.stance, feature=args.feature)
    except MaterializeError as e:
        sys.stderr.write("REJECTED (fail-closed): %s\n" % e)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


# --------------------------------------------------------------------------- #
# Self-test (TDD — failing fixtures first). Builds real git repos in a tempdir
# OUTSIDE this worktree; never runs git in cwd.
# --------------------------------------------------------------------------- #
def _selftest():
    import tempfile

    failures = []

    def expect(name, cond):
        print(("  ok   - " if cond else "  FAIL - ") + name)
        if not cond:
            failures.append(name)

    pe = _preeval()

    def git(repo, args, check=True, capture=False):
        return _run_git(repo, args, check=check, capture=capture)

    def init_repo(td):
        repo = os.path.join(td, "repo")
        os.makedirs(repo)
        git(repo, ["init", "-q"])
        git(repo, ["config", "user.email", "v@example.com"])
        git(repo, ["config", "user.name", "V Test"])
        git(repo, ["config", "commit.gpgsign", "false"])
        return repo

    def make_eligible(repo, request="tweak local button padding",
                      target="src/ui/button.css", ts="2026-07-12T10:16:00Z"):
        """Create a genuine committed FASTPATH_ELIGIBLE pre-eval + a committed target file."""
        tax_dir = os.path.join(repo, ".claude")
        os.makedirs(tax_dir, exist_ok=True)
        with open(os.path.join(tax_dir, "compound-v-impact-taxonomy.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write(pe._EXAMPLE_TAXONOMY_TEXT)
        tgt_full = os.path.join(repo, target)
        os.makedirs(os.path.dirname(tgt_full), exist_ok=True)
        with open(tgt_full, "w", encoding="utf-8") as fh:
            fh.write(".btn { padding: 4px; }\n")
        git(repo, ["add", "-A"])
        git(repo, ["commit", "-q", "-m", "seed: taxonomy + target"])

        stream = os.path.join(repo, TRIAGE_STREAM_REL)
        fake = (lambda req, r, taxonomy: {"resolved_paths": [target], "fan_out": 1,
                                          "flags": [], "confidence": "exact"})
        res = pe.run_preeval(request, repo=repo, _localize=fake, ts=ts, stream_path=stream)
        # Commit the pre-eval artifacts + the predicted stream line.
        git(repo, ["add", "docs/superpowers/pre-eval", TRIAGE_STREAM_REL])
        git(repo, ["commit", "-q", "-m", "pre-eval: %s" % res["pre_eval_id"]])
        return res

    def commit_subjects(repo):
        _rc, out = git(repo, ["log", "--format=%s"], capture=True)
        return [l for l in out.splitlines() if l.strip()]

    def count_commits(repo):
        _rc, out = git(repo, ["rev-list", "--count", "HEAD"], capture=True)
        return int(out.strip())

    # ============================ (1) Happy path ================================= #
    with tempfile.TemporaryDirectory() as td:
        repo = init_repo(td)
        res = make_eligible(repo)
        pid = res["pre_eval_id"]
        expect("fixture: record is FASTPATH_ELIGIBLE", res["decision"] == DECISION_FASTPATH)

        out = run_materialize(repo, pid, prompt_text="APPLY: make the button padding 8px.\n")
        run_id = out["run_id"]
        expect("run-id is deterministic (fastpath-<pre_eval_id>)",
               run_id == RUN_ID_PREFIX + pid)
        expect("status materialized", out["status"] == "materialized")

        run_dir = os.path.join(repo, EXEC_DIR_REL, run_id)
        for rel in ("manifest.yaml", "spec.md", "plan.md", "state.json",
                    "taxonomy-snapshot.yaml",
                    os.path.join("jobs", IMPL_JOB_ID + ".prompt.md")):
            expect("artifact present: %s" % rel, os.path.isfile(os.path.join(run_dir, rel)))

        # --- THE gate: the committed manifest passes C1 --mode pre-dispatch. ---
        problems = _validate_predispatch(repo, os.path.join(EXEC_DIR_REL, run_id,
                                                             "manifest.yaml"))
        expect("manifest passes C1 --mode pre-dispatch (no violations)", problems == [])
        if problems:
            for p in problems:
                print("        - %s" % p)

        # --- Manifest also re-parses under the validator's _mini_yaml fallback. ---
        val = _validator()
        with open(os.path.join(run_dir, "manifest.yaml"), "r", encoding="utf-8") as fh:
            mtext = fh.read()
        mini = val._mini_yaml(mtext)
        expect("manifest re-parses under the _mini_yaml fallback (no flow {})",
               isinstance(mini, dict) and isinstance(mini.get("jobs"), list)
               and mini["jobs"][0]["write_allowed"] == ["src/ui/button.css"])
        expect("_mini_yaml parses the block-YAML audit skip-record",
               isinstance(mini.get("audits", {}).get("archaeology"), dict)
               and mini["audits"]["archaeology"].get("skipped") is True)

        # --- state.json committed LAST at FASTPATH_DISPATCHED. ---
        state = _read_json(os.path.join(run_dir, "state.json"))
        expect("state.json phase == FASTPATH_DISPATCHED",
               state.get("phase") == PHASE_FASTPATH_DISPATCHED)
        expect("state.json carries pre_eval_id", state.get("pre_eval_id") == pid)
        expect("state.json committed (git-tracked)",
               _git_tracked(git, repo, os.path.join(EXEC_DIR_REL, run_id, "state.json")))

        # --- Commit ORDERING: artifacts → bind → state (newest first in the log). ---
        subs = commit_subjects(repo)
        art_msg = "feat(v2.9): materialize fast-path run %s (artifacts)" % run_id
        bind_msg = "chore(v2.9): bind fast-path run %s to %s" % (run_id, pid)
        state_msg = "chore(v2.9): fast-path run %s dispatched (state)" % run_id
        expect("all three lifecycle commits exist",
               art_msg in subs and bind_msg in subs and state_msg in subs)
        if art_msg in subs and bind_msg in subs and state_msg in subs:
            i_art, i_bind, i_state = (subs.index(art_msg), subs.index(bind_msg),
                                      subs.index(state_msg))
            # newest-first ⇒ smaller index is later; state after bind after artifacts.
            expect("commit order: state AFTER bind AFTER artifacts (CR4-3/step 9)",
                   i_state < i_bind < i_art)

        # --- bind committed BEFORE state (proven by ordering) + present in the stream. ---
        stream_full = os.path.join(repo, TRIAGE_STREAM_REL)
        expect("bind event present in the triage stream",
               _bind_present(stream_full, pid, run_id))
        expect("bind stream is committed",
               _git_tracked(git, repo, TRIAGE_STREAM_REL))

        # --- state.json is NOT in the artifacts commit — the commit that FIRST added it
        #     must be the dedicated (last) state commit. ---
        _rc, add_sub = git(repo, ["log", "--diff-filter=A", "--format=%s", "--",
                                  os.path.join(EXEC_DIR_REL, run_id, "state.json")],
                           capture=True)
        expect("state.json was introduced by the dedicated state commit (last), not artifacts",
               add_sub.strip().splitlines()[:1] == [state_msg])

        # --- Idempotency: a second run is a no-op (no new commits). ---
        before = count_commits(repo)
        out2 = run_materialize(repo, pid)
        after = count_commits(repo)
        expect("re-run is idempotent: status already_complete",
               out2["status"] == "already_complete")
        expect("re-run adds NO new commits", before == after)

    # ============================ (2) Tamper rejection =========================== #
    with tempfile.TemporaryDirectory() as td:
        repo = init_repo(td)
        res = make_eligible(repo)
        pid = res["pre_eval_id"]
        before = count_commits(repo)
        # Tamper the committed localization artifact: point resolved_paths[0] elsewhere.
        art_full = os.path.join(repo, _localize().artifact_rel_path(pid))
        art = _read_json(art_full)
        art["resolved_paths"] = ["src/ui/OTHER.css"]
        _write_json(art_full, art)
        raised = False
        try:
            run_materialize(repo, pid)
        except MaterializeError as e:
            raised = "TAMPER" in str(e)
        expect("tampered record (mismatched resolved path) is REJECTED", raised)
        expect("tamper rejection creates NO run dir",
               not os.path.isdir(os.path.join(repo, EXEC_DIR_REL,
                                              RUN_ID_PREFIX + pid)))
        expect("tamper rejection makes NO commit (pre-commit fail-closed)",
               count_commits(repo) == before)

    # ============================ (3) Ineligible record ========================== #
    with tempfile.TemporaryDirectory() as td:
        repo = init_repo(td)
        res = make_eligible(repo)
        pid = res["pre_eval_id"]
        rec_full = pe.record_path(repo, pid)
        rec = _read_json(rec_full)
        rec["decision"] = "FULL_PIPELINE"
        _write_json(rec_full, rec)
        raised = False
        try:
            run_materialize(repo, pid)
        except MaterializeError:
            raised = True
        expect("a FULL_PIPELINE record is refused (not fast-path eligible)", raised)

    # ============================ (4) Crash after ARTIFACTS ====================== #
    with tempfile.TemporaryDirectory() as td:
        repo = init_repo(td)
        res = make_eligible(repo)
        pid = res["pre_eval_id"]
        run_id = RUN_ID_PREFIX + pid
        stop = run_materialize(repo, pid, _stop_after="artifacts")
        expect("stop_after=artifacts: artifacts committed, no state",
               stop["status"] == "stopped_after_artifacts")
        expect("crash@artifacts: state.json not yet committed",
               not _git_tracked(git, repo, os.path.join(EXEC_DIR_REL, run_id, "state.json")))
        expect("crash@artifacts: bind not yet present",
               not _bind_present(os.path.join(repo, TRIAGE_STREAM_REL), pid, run_id))
        # Reconcile: a fresh full run completes deterministically (same run-id).
        out = run_materialize(repo, pid)
        expect("crash@artifacts reconciles to materialized", out["status"] == "materialized")
        expect("crash@artifacts: same deterministic run-id", out["run_id"] == run_id)
        expect("crash@artifacts: bind now present + before state",
               _bind_present(os.path.join(repo, TRIAGE_STREAM_REL), pid, run_id))
        subs = commit_subjects(repo)
        i_bind = subs.index("chore(v2.9): bind fast-path run %s to %s" % (run_id, pid))
        i_state = subs.index("chore(v2.9): fast-path run %s dispatched (state)" % run_id)
        expect("crash@artifacts: state committed after bind", i_state < i_bind)
        expect("crash@artifacts: exactly ONE run dir (no second child)",
               _one_run_dir(repo, run_id))

    # ============================ (5) Crash after BIND =========================== #
    with tempfile.TemporaryDirectory() as td:
        repo = init_repo(td)
        res = make_eligible(repo)
        pid = res["pre_eval_id"]
        run_id = RUN_ID_PREFIX + pid
        stop = run_materialize(repo, pid, _stop_after="bind")
        expect("stop_after=bind: bind committed, state not yet",
               stop["status"] == "stopped_after_bind")
        expect("crash@bind: bind present + committed",
               _bind_present(os.path.join(repo, TRIAGE_STREAM_REL), pid, run_id)
               and _git_tracked(git, repo, TRIAGE_STREAM_REL))
        expect("crash@bind: state.json not yet committed",
               not _git_tracked(git, repo, os.path.join(EXEC_DIR_REL, run_id, "state.json")))
        out = run_materialize(repo, pid)
        expect("crash@bind reconciles to materialized", out["status"] == "materialized")
        expect("crash@bind: committed state.json => bind durable (invariant holds)",
               _git_tracked(git, repo, os.path.join(EXEC_DIR_REL, run_id, "state.json"))
               and _bind_present(os.path.join(repo, TRIAGE_STREAM_REL), pid, run_id))
        # No duplicate bind lines were appended on reconcile.
        expect("crash@bind: bind is not duplicated on reconcile",
               _bind_count(os.path.join(repo, TRIAGE_STREAM_REL), pid, run_id) == 1)

    # ============================ (6) Crash after STATE (full) =================== #
    with tempfile.TemporaryDirectory() as td:
        repo = init_repo(td)
        res = make_eligible(repo)
        pid = res["pre_eval_id"]
        run_id = RUN_ID_PREFIX + pid
        run_materialize(repo, pid)
        before = count_commits(repo)
        # A resume after full completion is a strict no-op.
        out = run_materialize(repo, pid)
        expect("crash@state (complete): resume is a no-op",
               out["status"] == "already_complete" and count_commits(repo) == before)
        expect("invariant: committed state => bind present (never state-without-bind)",
               _bind_present(os.path.join(repo, TRIAGE_STREAM_REL), pid, run_id))

    # ============================ (7) Block-YAML emitter sanity ================== #
    m = {"a": "x:y", "n": 1, "b": True, "lst": ["p/q", "r"],
         "map": {"k": "v", "deep": {"z": "w"}},
         "jobs": [{"id": "j1", "write_allowed": ["a/b.css"], "review": {"backend": "claude"}}]}
    text = dump_manifest_yaml(m)
    expect("emitter never emits a flow {} mapping", "{" not in text and "}" not in text)
    reparsed = _validator()._mini_yaml(text)
    expect("emitter round-trips through _mini_yaml",
           reparsed["a"] == "x:y" and reparsed["n"] == 1 and reparsed["b"] is True
           and reparsed["lst"] == ["p/q", "r"]
           and reparsed["map"]["deep"]["z"] == "w"
           and reparsed["jobs"][0]["write_allowed"] == ["a/b.css"]
           and reparsed["jobs"][0]["review"]["backend"] == "claude")

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


def _one_run_dir(repo, run_id):
    base = os.path.join(repo, EXEC_DIR_REL)
    if not os.path.isdir(base):
        return False
    dirs = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
    return dirs == [run_id]


def _bind_count(stream_full, pre_eval_id, run_id):
    n = 0
    if not os.path.isfile(stream_full):
        return 0
    with open(stream_full, "r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                continue
            if (isinstance(obj, dict) and obj.get("event") == "bind"
                    and obj.get("pre_eval_id") == pre_eval_id
                    and obj.get("run_id") == run_id):
                n += 1
    return n


if __name__ == "__main__":
    sys.exit(main(sys.argv))
