#!/usr/bin/env python3
"""
Compound V manifest validator — the DETERMINISTIC invariant gate.

Backs the ``partition-reviewer`` agent with a script that either passes or
fails with specifics. No LLM judgment, no network, no fabricated metrics.

Invariants enforced (from PRD §5.1/§5.5 + plan §5/§6)
----------------------------------------------------
1. **Disjoint write scope.** No file can be owned by two jobs. Because
   ``write_allowed`` entries are globs, we detect overlap deterministically:
   two globs conflict if a canonical witness path generated from one is
   matched by the other (checked both directions), or if they are identical.
2. **Codex ⇒ worktree.** Any job with ``backend: codex`` must have
   ``isolation: worktree``.
3. **Reviewers ⇒ deep/opus.** Any job whose ``type`` or ``id`` marks it a
   reviewer (spec/quality/integration/partition review) must resolve to the
   strongest reasoning: either ``tier: deep`` or ``model: opus``.
4. **Shared foundation serial.** Files declared shared/contract (via the
   ``shared_resources`` top-level list, if present) must each be written by a
   ``shared_foundation`` job whose ``run`` is ``serial``. Independently, any
   job typed ``shared_foundation`` must run ``serial``.
5. **Intent routing.** Jobs route by intent, not hardcoded model strings.
   Every job MUST carry ``model`` OR ``tier`` (model is now an optional
   override; existing explicit-model jobs stay valid — backward compatible).
   If present, ``tier`` ∈ {deep, standard, light} and ``effort`` ∈
   {low, medium, high}.

Required-field + enum validation (before invariant checks)
-----------------------------------------------------------
All required fields per ``execution-manifest.md`` are checked first. Top-level:
``run_id``, ``jobs``, ``feature``, ``spec_path``, ``plan_path``, ``audits``,
``acceptance_criteria``, ``routing_stance``, ``max_parallel``. Per-job: ``id``,
``title``, ``type``, ``backend``, ``isolation``, ``run``, ``write_allowed``,
``read_allowed``, ``acceptance``, plus (``model`` OR ``tier``). Enums: ``backend``
∈ {claude, codex, antigravity} (``none`` is the routing "return to planning"
sentinel, NOT a dispatched job backend); ``isolation`` ∈ {direct, worktree};
``run`` ∈ {serial, parallel};
``routing_stance`` ∈ {balanced, conservative, cost-aware, claude-only};
``tier`` ∈ {deep, standard, light}; ``effort`` ∈ {low, medium, high}.

Job ``id`` (and top-level ``run_id``) MUST match ``^[A-Za-z0-9._-]+$`` and not be
``.`` / ``..`` — ids become path segments, so a ``../x`` id is a path-traversal
vector and is rejected before dispatch.

**Parallel ⇒ worktree.** A ``run: parallel`` job MUST be ``isolation: worktree``
(per-job scope attribution needs isolation); ``isolation: direct`` is only valid
with ``run: serial``.

Structural sanity is also checked (jobs is a non-empty list; each job has an
``id``; ids unique; ``backend`` present; ``write_allowed`` is a list).

Structural TYPE checks: ``jobs`` non-empty list, ``acceptance_criteria`` list,
``audits`` mapping, ``max_parallel`` int, ``run_id``/``feature``/``spec_path``/
``plan_path`` strings, and per-job ``write_allowed``/``read_allowed``/``acceptance``
lists. A wrong-typed field is its own specific violation.

never-Haiku (execution layer): any job whose explicit ``model`` contains
``haiku`` (case-insensitive — ``haiku``, ``claude-haiku-...``) is rejected. The
frontmatter linter only sees agent/skill frontmatter; this closes the
execution-layer override path.

``depends_on``: every referenced id must exist among the manifest job ids (a
dangling ref is a violation) and the dependency graph must be acyclic (a cycle is
a violation naming the jobs on it).

Usage
-----
    compound-v-validate-manifest.py <manifest.yaml>
    compound-v-validate-manifest.py --selftest

Exit codes: 0 = all invariants hold, 1 = one or more violations (printed),
2 = usage / parse error.

Python 3.9-safe, stdlib only. PyYAML used if importable; otherwise a tiny
embedded YAML-subset parser handles the manifest shape we emit.
"""

import json
import os
import re
import sys


# --------------------------------------------------------------------------- #
# YAML loading: prefer PyYAML, fall back to an embedded subset parser.
# --------------------------------------------------------------------------- #
def load_yaml(text):
    try:
        import yaml  # noqa: WPS433 (intentional optional dep)

        return yaml.safe_load(text)
    except Exception:  # pragma: no cover - import or parse fallback
        return _mini_yaml(text)


def _strip_comment(line):
    """Remove a trailing ``# comment`` not inside quotes."""
    out = []
    in_s = None
    i = 0
    while i < len(line):
        ch = line[i]
        if in_s:
            out.append(ch)
            if ch == in_s:
                in_s = None
        elif ch in ("'", '"'):
            in_s = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _scalar(tok):
    tok = tok.strip()
    if tok == "" or tok == "~" or tok.lower() == "null":
        return None
    if (tok.startswith('"') and tok.endswith('"')) or (
        tok.startswith("'") and tok.endswith("'")
    ):
        return tok[1:-1]
    if tok.lower() == "true":
        return True
    if tok.lower() == "false":
        return False
    if re.match(r"^-?\d+$", tok):
        return int(tok)
    if re.match(r"^-?\d+\.\d+$", tok):
        return float(tok)
    return tok


def _inline_list(tok):
    inner = tok.strip()[1:-1].strip()
    if not inner:
        return []
    return [_scalar(p) for p in _split_commas(inner)]


def _split_commas(s):
    parts = []
    buf = []
    in_s = None
    for ch in s:
        if in_s:
            buf.append(ch)
            if ch == in_s:
                in_s = None
        elif ch in ("'", '"'):
            in_s = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _mini_yaml(text):
    """
    Minimal YAML-subset parser. Handles the manifest shape we emit:
    nested mappings, lists of mappings, inline ``[a, b]`` lists, and block
    ``- item`` lists of scalars. Indentation is significant (2 spaces).

    This is a fallback only; PyYAML is used when available.
    """
    lines = []
    for raw in text.splitlines():
        s = _strip_comment(raw)
        if s.strip() == "":
            continue
        if s.strip() == "---":
            continue
        indent = len(s) - len(s.lstrip(" "))
        lines.append((indent, s.strip()))

    pos = [0]

    def parse_block(min_indent):
        # Decide mapping vs list by the first line at this indent.
        if pos[0] >= len(lines):
            return None
        indent, content = lines[pos[0]]
        if indent < min_indent:
            return None
        if content.startswith("- "):
            return parse_list(indent)
        return parse_map(indent)

    def parse_list(indent):
        items = []
        while pos[0] < len(lines):
            cur_indent, content = lines[pos[0]]
            if cur_indent != indent or not content.startswith("- "):
                if cur_indent < indent:
                    break
                if not content.startswith("- "):
                    break
            rest = content[2:].strip()
            pos[0] += 1
            if ":" in rest and not _looks_scalar(rest):
                # First key of a list-of-mappings item.
                item = {}
                key, val = _kv(rest)
                _assign(item, key, val, indent + 2)
                # Continue consuming deeper keys belonging to this item.
                while pos[0] < len(lines):
                    n_indent, n_content = lines[pos[0]]
                    if n_indent <= indent:
                        break
                    if n_content.startswith("- "):
                        break
                    pos[0] += 1
                    k2, v2 = _kv(n_content)
                    _assign(item, k2, v2, n_indent + 2)
                items.append(item)
            else:
                items.append(_scalar(rest))
        return items

    def parse_map(indent):
        obj = {}
        while pos[0] < len(lines):
            cur_indent, content = lines[pos[0]]
            if cur_indent != indent:
                break
            if content.startswith("- "):
                break
            pos[0] += 1
            key, val = _kv(content)
            _assign(obj, key, val, indent + 2)
        return obj

    def _assign(obj, key, val, child_indent):
        if val is not None and val != "":
            obj[key] = val
        else:
            child = parse_block(child_indent)
            obj[key] = child if child is not None else None

    def _kv(content):
        idx = _colon_index(content)
        if idx < 0:
            return content.strip(), None
        key = content[:idx].strip()
        rest = content[idx + 1:].strip()
        if rest == "":
            return key, None
        if rest.startswith("["):
            return key, _inline_list(rest)
        return key, _scalar(rest)

    return parse_block(0)


def _looks_scalar(rest):
    # A list item like "- foo" with no key:value mapping.
    return _colon_index(rest) < 0


def _colon_index(content):
    in_s = None
    for i, ch in enumerate(content):
        if in_s:
            if ch == in_s:
                in_s = None
        elif ch in ("'", '"'):
            in_s = ch
        elif ch == ":":
            if i + 1 >= len(content) or content[i + 1] in (" ", "\t"):
                return i
    return -1


# --------------------------------------------------------------------------- #
# Glob overlap (deterministic).
# --------------------------------------------------------------------------- #
def glob_to_regex(pattern):
    i = 0
    n = len(pattern)
    out = ["(?s:"]
    while i < n:
        c = pattern[i]
        if c == "*":
            j = i
            while j < n and pattern[j] == "*":
                j += 1
            if j - i >= 2:
                at_seg = out[-1] in ("(?s:", "/")
                if out[-1] == "/" and (j >= n or pattern[j] == "/"):
                    out[-1] = "(?:/.*)?"
                elif at_seg and j < n and pattern[j] == "/":
                    out.append("(?:.*/)?")
                    i = j + 1
                    continue
                else:
                    out.append(".*")
            else:
                out.append("[^/]*")
            i = j
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        if c == "[":
            k = i + 1
            if k < n and pattern[k] == "!":
                k += 1
            if k < n and pattern[k] == "]":
                k += 1
            while k < n and pattern[k] != "]":
                k += 1
            if k >= n:
                out.append(re.escape("["))
                i += 1
                continue
            inner = pattern[i + 1:k]
            if inner.startswith("!"):
                inner = "^" + inner[1:]
            out.append("[" + inner + "]")
            i = k + 1
            continue
        out.append(re.escape(c))
        i += 1
    out.append(")\\Z")
    return "".join(out)


def glob_match(path, pattern):
    return re.compile(glob_to_regex(pattern)).match(path) is not None


def witness(pattern):
    """A canonical concrete path that the glob matches (best effort)."""
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            j = i
            while j < n and pattern[j] == "*":
                j += 1
            if j - i >= 2:
                # '**' -> two segments to exercise recursion.
                if out and out[-1] == "/" and (j >= n or pattern[j] == "/"):
                    out.append("x/x")
                    if j < n and pattern[j] == "/":
                        i = j + 1
                        continue
                else:
                    out.append("x/x")
            else:
                out.append("x")
            i = j
            continue
        if c == "?":
            out.append("x")
            i += 1
            continue
        if c == "[":
            k = i + 1
            neg = False
            if k < n and pattern[k] == "!":
                neg = True
                k += 1
            start = k
            if k < n and pattern[k] == "]":
                k += 1
            while k < n and pattern[k] != "]":
                k += 1
            if k >= n:
                out.append("[")
                i += 1
                continue
            inner = pattern[start:k]
            out.append("y" if neg else (inner[0] if inner else "x"))
            i = k + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _seg_is_literal(s):
    return not any(c in s for c in "*?[")


def _literal_prefix(s):
    out = []
    for c in s:
        if c in "*?[":
            break
        out.append(c)
    return "".join(out)


def _literal_suffix(s):
    out = []
    for c in reversed(s):
        if c in "*?[":
            break
        out.append(c)
    return "".join(reversed(out))


def _seg_disjoint(pa, pb):
    """SOUND: True only when single segments pa, pb (no '/') provably share no string."""
    if _seg_is_literal(pa) and _seg_is_literal(pb):
        return pa != pb
    # Fixed leading literals that disagree on their common length -> no common string.
    apre, bpre = _literal_prefix(pa), _literal_prefix(pb)
    n = min(len(apre), len(bpre))
    if apre[:n] != bpre[:n]:
        return True
    # Fixed trailing literals that disagree on their common length -> no common string.
    asuf, bsuf = _literal_suffix(pa), _literal_suffix(pb)
    m = min(len(asuf), len(bsuf))
    if m > 0 and asuf[len(asuf) - m:] != bsuf[len(bsuf) - m:]:
        return True
    return False


def _provably_disjoint(a, b):
    """SOUND: True only when globs a, b provably match no common path.

    Aligns segments from both ends, stopping at any ``**`` (which spans a variable
    number of segments). A literal-segment conflict in the fixed prefix or suffix —
    or differing fixed segment counts when neither side has ``**`` — proves disjoint.
    Anything else is treated as a POSSIBLE overlap by the caller (conservative).
    """
    sa, sb = a.split("/"), b.split("/")
    # Left-align across the fixed prefix (until a '**' appears on either side).
    i = 0
    while i < len(sa) and i < len(sb) and sa[i] != "**" and sb[i] != "**":
        if _seg_disjoint(sa[i], sb[i]):
            return True
        i += 1
    # Right-align across the fixed suffix (until a '**' appears on either side).
    k = 0
    while (k < len(sa) - i and k < len(sb) - i
           and sa[-1 - k] != "**" and sb[-1 - k] != "**"):
        if _seg_disjoint(sa[-1 - k], sb[-1 - k]):
            return True
        k += 1
    # No '**' on either side and different fixed lengths -> disjoint.
    if "**" not in sa and "**" not in sb and len(sa) != len(sb):
        return True
    return False


def globs_overlap(a, b):
    """Conservative SOUND overlap test (no false negatives) between two write globs.

    A false negative here is dangerous — it would let two jobs silently own the same
    file. So we only declare 'disjoint' when we can PROVE it; otherwise we flag overlap
    (worst case: a genuinely-disjoint manifest is sent for human review). This fixes the
    earlier single-witness strategy, which missed e.g. ``src/*/test.ts`` vs
    ``src/foo/*.ts`` (overlap at ``src/foo/test.ts``).
    """
    if a == b:
        return True
    # Fast positive: a concrete witness of one matched by the other proves overlap.
    if glob_match(witness(a), b) or glob_match(witness(b), a):
        return True
    # Otherwise: overlap unless provably disjoint.
    return not _provably_disjoint(a, b)


# --------------------------------------------------------------------------- #
# Invariant checks.
# --------------------------------------------------------------------------- #
REVIEWER_TOKENS = ("review", "reviewer", "spec_review", "quality", "integration")

# Intent vocabulary (mirrors compound-v-resolve-model.py). Stable; never
# changes when concrete models churn.
VALID_TIERS = ("deep", "standard", "light")
VALID_EFFORTS = ("low", "medium", "high")

# Enum vocabularies for required-field validation (per execution-manifest.md).
VALID_BACKENDS = ("claude", "codex", "antigravity")
VALID_ISOLATIONS = ("direct", "worktree")
VALID_RUNS = ("serial", "parallel")
VALID_STANCES = ("balanced", "conservative", "cost-aware", "claude-only")

# Top-level required fields (per execution-manifest.md "Top-level fields").
TOPLEVEL_REQUIRED = (
    "run_id",
    "jobs",
    "feature",
    "spec_path",
    "plan_path",
    "audits",
    "acceptance_criteria",
    "routing_stance",
    "max_parallel",
)

# Per-job required fields (per execution-manifest.md "Per-job fields"). model OR
# tier is handled separately (at least one of the two).
JOB_REQUIRED = (
    "id",
    "title",
    "type",
    "backend",
    "isolation",
    "run",
    "write_allowed",
    "read_allowed",
    "acceptance",
)

# Strict id allow-list — a malicious manifest id (e.g. "../x") must be rejected
# before dispatch, since ids become path segments in the run/worktree layout.
_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _id_is_safe(value):
    s = str(value)
    if s in (".", ".."):
        return False
    return _ID_RE.match(s) is not None


def _is_reviewer(job):
    jtype = str(job.get("type", "")).lower()
    jid = str(job.get("id", "")).lower()
    title = str(job.get("title", "")).lower()
    for tok in REVIEWER_TOKENS:
        if tok in jtype or tok in jid or tok in title:
            return True
    return False


def validate(manifest):
    """Return a list of violation strings; empty list means valid."""
    problems = []

    if not isinstance(manifest, dict):
        return ["manifest is not a mapping"]

    # Top-level required fields (validated BEFORE invariant checks).
    for field in TOPLEVEL_REQUIRED:
        if manifest.get(field) in (None, "", [], {}):
            problems.append("manifest missing required top-level field '%s'" % field)

    # Structural TYPE checks on top-level fields (wrong type is its own,
    # specific violation — distinct from "missing"). Only checked when the
    # field is present and non-None, so the missing-field loop above owns
    # absence; this loop owns mis-typing.
    if "jobs" in manifest and manifest.get("jobs") is not None:
        jv = manifest.get("jobs")
        if not isinstance(jv, list) or not jv:
            problems.append("manifest 'jobs' must be a non-empty list")
    if "acceptance_criteria" in manifest and manifest.get("acceptance_criteria") is not None:
        if not isinstance(manifest.get("acceptance_criteria"), list):
            problems.append("manifest 'acceptance_criteria' must be a list")
    if "audits" in manifest and manifest.get("audits") is not None:
        if not isinstance(manifest.get("audits"), dict):
            problems.append("manifest 'audits' must be a mapping")
    if "max_parallel" in manifest and manifest.get("max_parallel") is not None:
        mp = manifest.get("max_parallel")
        # bool is an int subclass in Python; a YAML true/false here is wrong.
        if not isinstance(mp, int) or isinstance(mp, bool):
            problems.append("manifest 'max_parallel' must be an int")
    for _sf in ("run_id", "feature", "spec_path", "plan_path"):
        if _sf in manifest and manifest.get(_sf) is not None:
            if not isinstance(manifest.get(_sf), str):
                problems.append("manifest '%s' must be a string" % _sf)

    # routing_stance enum (only when present).
    stance = manifest.get("routing_stance")
    if stance is not None and str(stance).lower() not in VALID_STANCES:
        problems.append(
            "manifest routing_stance '%s' invalid (expected one of %s)"
            % (stance, ", ".join(VALID_STANCES))
        )

    # Top-level run_id id-safety (becomes a run-dir / path segment).
    run_id = manifest.get("run_id")
    if run_id is not None and run_id != "" and not _id_is_safe(run_id):
        problems.append(
            "manifest run_id '%s' has invalid characters "
            "(allowed: A-Za-z0-9._-, not . or ..)" % run_id
        )

    jobs = manifest.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        problems.append("manifest has no non-empty 'jobs' list")
        return problems

    # Structural sanity + collect per-job globs.
    seen_ids = set()
    job_globs = []  # (job_id, [globs])
    job_deps = []   # (job_id, [depends_on ids]) — for ref + cycle validation
    all_ids = []    # job ids in declared order (for cycle reporting)
    for idx, job in enumerate(jobs):
        if not isinstance(job, dict):
            problems.append("job #%d is not a mapping" % idx)
            continue
        jid = job.get("id")
        if not jid:
            problems.append("job #%d missing 'id'" % idx)
            jid = "<job#%d>" % idx
        elif not _id_is_safe(jid):
            problems.append(
                "job '%s' id has invalid characters "
                "(allowed: A-Za-z0-9._-, not . or ..)" % jid
            )
        if jid in seen_ids:
            problems.append("duplicate job id '%s'" % jid)
        seen_ids.add(jid)
        all_ids.append(jid)

        # Collect depends_on (validated for refs + cycles after the loop).
        dep = job.get("depends_on")
        if dep is None:
            deps = []
        elif isinstance(dep, list):
            deps = [str(d) for d in dep]
        else:
            problems.append("job '%s' depends_on must be a list" % jid)
            deps = []
        job_deps.append((jid, deps))

        # Per-job required fields (validated BEFORE the invariant checks below).
        for field in JOB_REQUIRED:
            val = job.get(field)
            # write_allowed may legitimately be an empty list (reviewers); only
            # flag it when the key is entirely absent.
            if field == "write_allowed":
                if "write_allowed" not in job:
                    problems.append("job '%s' missing required field 'write_allowed'" % jid)
                continue
            if val in (None, "", [], {}):
                problems.append("job '%s' missing required field '%s'" % (jid, field))

        # Per-job structural TYPE checks: these three are list-valued fields.
        # (write_allowed list-ness is also re-checked below where it is consumed;
        # checking here keeps the violation specific and ordered with the job.)
        for _lf in ("write_allowed", "read_allowed", "acceptance"):
            if _lf in job and job.get(_lf) is not None:
                if not isinstance(job.get(_lf), list):
                    problems.append("job '%s' %s must be a list" % (jid, _lf))

        # never-Haiku policy (execution layer). The frontmatter linter only sees
        # agent/skill frontmatter; a manifest job can pin an execution-layer
        # `model` override, so an explicit model containing "haiku" (any case,
        # e.g. `haiku` or `claude-haiku-...`) must be rejected here too.
        model_raw = job.get("model")
        if model_raw is not None and "haiku" in str(model_raw).lower():
            problems.append(
                "job '%s' model '%s' violates the never-Haiku policy "
                "(no Haiku as an execution-layer model override)"
                % (jid, model_raw)
            )

        if not job.get("backend"):
            problems.append("job '%s' missing 'backend'" % jid)
        else:
            backend_val = str(job.get("backend")).lower()
            if backend_val not in VALID_BACKENDS:
                problems.append(
                    "job '%s' backend '%s' invalid (expected one of %s)"
                    % (jid, job.get("backend"), ", ".join(VALID_BACKENDS))
                )

        # isolation / run enum checks (only when present).
        iso_val = job.get("isolation")
        if iso_val is not None and str(iso_val).lower() not in VALID_ISOLATIONS:
            problems.append(
                "job '%s' isolation '%s' invalid (expected one of %s)"
                % (jid, iso_val, ", ".join(VALID_ISOLATIONS))
            )
        run_val = job.get("run")
        if run_val is not None and str(run_val).lower() not in VALID_RUNS:
            problems.append(
                "job '%s' run '%s' invalid (expected one of %s)"
                % (jid, run_val, ", ".join(VALID_RUNS))
            )

        # Invariant 6: parallel ⇒ worktree (per-job scope attribution). A repo-wide
        # git diff cannot attribute a parallel direct job's writes, so parallel jobs
        # MUST be isolated in a worktree; direct is only valid with serial.
        if (str(run_val).lower() == "parallel"
                and str(iso_val).lower() == "direct"):
            problems.append(
                "job '%s' uses run: parallel with isolation: direct — parallel "
                "jobs require worktree isolation for per-job scope attribution; "
                "use isolation: worktree or run: serial" % jid
            )

        # Invariant 5: intent routing — every job must carry model OR tier
        # (model is now an optional override; tier routes by intent).
        has_model = bool(job.get("model"))
        has_tier = bool(job.get("tier"))
        if not has_model and not has_tier:
            problems.append(
                "job '%s' must have 'model' or 'tier' "
                "(model is an optional override)" % jid
            )

        # Invariant 5: tier / effort enum validation (only when present).
        tier_val = job.get("tier")
        if tier_val is not None and str(tier_val).lower() not in VALID_TIERS:
            problems.append(
                "job '%s' tier '%s' invalid (expected one of %s)"
                % (jid, tier_val, ", ".join(VALID_TIERS))
            )
        effort_val = job.get("effort")
        if effort_val is not None and str(effort_val).lower() not in VALID_EFFORTS:
            problems.append(
                "job '%s' effort '%s' invalid (expected one of %s)"
                % (jid, effort_val, ", ".join(VALID_EFFORTS))
            )

        wa = job.get("write_allowed")
        if wa is None:
            wa = []
        if not isinstance(wa, list):
            problems.append("job '%s' write_allowed is not a list" % jid)
            wa = []
        job_globs.append((jid, [str(g) for g in wa]))

        # Invariant 2: codex => worktree.
        if str(job.get("backend", "")).lower() == "codex":
            if str(job.get("isolation", "")).lower() != "worktree":
                problems.append(
                    "job '%s' uses backend codex but isolation is '%s' "
                    "(codex requires worktree)" % (jid, job.get("isolation"))
                )

        # Invariant 3: reviewers => deep/opus (strongest reasoning). Satisfied
        # by either tier: deep or model: opus.
        if _is_reviewer(job):
            is_deep = str(job.get("tier", "")).lower() == "deep"
            is_opus = str(job.get("model", "")).lower() == "opus"
            if not is_deep and not is_opus:
                problems.append(
                    "reviewer job '%s' must resolve to deep reasoning "
                    "(tier: deep or model: opus), got tier='%s' model='%s'"
                    % (jid, job.get("tier"), job.get("model"))
                )

        # Invariant 4 (structural half): shared_foundation => serial.
        if str(job.get("type", "")).lower() == "shared_foundation":
            if str(job.get("run", "")).lower() != "serial":
                problems.append(
                    "shared_foundation job '%s' must run serial, got '%s'"
                    % (jid, job.get("run"))
                )

    # Invariant 1: disjoint write scope across distinct jobs.
    for a_i in range(len(job_globs)):
        id_a, globs_a = job_globs[a_i]
        for b_i in range(a_i + 1, len(job_globs)):
            id_b, globs_b = job_globs[b_i]
            for ga in globs_a:
                for gb in globs_b:
                    if globs_overlap(ga, gb):
                        problems.append(
                            "write_allowed overlap: job '%s' (%s) and job '%s' "
                            "(%s) can both own the same path"
                            % (id_a, ga, id_b, gb)
                        )

    # depends_on validation: every referenced id must exist (no dangling ref),
    # and the dependency graph must be acyclic (no cycles).
    id_set = set(all_ids)
    dep_graph = {}  # id -> list of dep ids that actually exist in id_set
    for jid, deps in job_deps:
        existing = []
        for d in deps:
            if d not in id_set:
                problems.append(
                    "job '%s' depends_on references unknown job id '%s'"
                    % (jid, d)
                )
            else:
                existing.append(d)
        # Last writer wins on duplicate ids; harmless for cycle detection.
        dep_graph[jid] = existing

    # Cycle detection via iterative DFS with a recursion stack. Reports the
    # first cycle found, naming the jobs on it.
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {}
    for nid in all_ids:
        color.setdefault(nid, WHITE)
    cycle_found = [None]

    def _find_cycle(start):
        # stack holds (node, iterator over its deps); path mirrors the GRAY set.
        stack = [(start, iter(dep_graph.get(start, [])))]
        path = [start]
        color[start] = GRAY
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if color.get(nxt, WHITE) == GRAY:
                    # Found a back-edge: nxt..node is the cycle.
                    idx = path.index(nxt)
                    cycle_found[0] = path[idx:] + [nxt]
                    return True
                if color.get(nxt, WHITE) == WHITE:
                    color[nxt] = GRAY
                    stack.append((nxt, iter(dep_graph.get(nxt, []))))
                    path.append(nxt)
                    advanced = True
                    break
            if advanced:
                continue
            color[node] = BLACK
            stack.pop()
            path.pop()
        return False

    for nid in all_ids:
        if color.get(nid, WHITE) == WHITE:
            if _find_cycle(nid):
                break
    if cycle_found[0]:
        problems.append(
            "depends_on cycle detected: %s" % " -> ".join(cycle_found[0])
        )

    # Invariant 4 (resource half): declared shared resources must be owned by a
    # shared_foundation serial job.
    shared = manifest.get("shared_resources")
    if isinstance(shared, list) and shared:
        foundation_jobs = [
            j
            for j in jobs
            if isinstance(j, dict)
            and str(j.get("type", "")).lower() == "shared_foundation"
            and str(j.get("run", "")).lower() == "serial"
        ]
        for res in shared:
            res = str(res)
            owned = False
            for j in foundation_jobs:
                wa = j.get("write_allowed") or []
                if isinstance(wa, list):
                    for g in wa:
                        if glob_match(res, str(g)) or res == str(g):
                            owned = True
                            break
                if owned:
                    break
            if not owned:
                problems.append(
                    "shared resource '%s' is not written by any "
                    "shared_foundation serial job" % res
                )

    return problems


def validate_text(text):
    data = load_yaml(text)
    return validate(data)


def main(argv):
    args = argv[1:]
    if "--selftest" in args:
        return _selftest()
    if not args:
        print("usage: compound-v-validate-manifest.py <manifest.yaml>", file=sys.stderr)
        return 2
    path = args[0]
    if not os.path.isfile(path):
        print("error: not a file: %s" % path, file=sys.stderr)
        return 2
    with open(path, "r") as fh:
        text = fh.read()
    try:
        problems = validate_text(text)
    except Exception as e:  # noqa: BLE001 - report parse failure cleanly
        print(json.dumps({"verdict": "error", "error": str(e)}), file=sys.stderr)
        return 2

    if problems:
        print("MANIFEST INVALID: %d violation(s)" % len(problems), file=sys.stderr)
        for p in problems:
            print("  - %s" % p, file=sys.stderr)
        print(json.dumps({"verdict": "invalid", "violations": problems}, indent=2))
        return 1
    print(json.dumps({"verdict": "valid", "violations": []}, indent=2))
    return 0


# --------------------------------------------------------------------------- #
# Self-test.
# --------------------------------------------------------------------------- #
GOOD_MANIFEST = """
run_id: 2026-06-26-demo
feature: "demo"
spec_path: docs/superpowers/specs/2026-06-26-demo.md
plan_path: docs/superpowers/plans/2026-06-26-demo.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-demo.md
  domain: docs/superpowers/expert/2026-06-26-demo.md
  library: docs/superpowers/library-audit/2026-06-26-demo.md
routing_stance: balanced
max_parallel: 4
shared_resources:
  - src/types/shared.ts
acceptance_criteria:
  - "ships"
jobs:
  - id: task-0-foundation
    title: "shared foundation"
    type: shared_foundation
    backend: claude
    model: opus
    isolation: direct
    run: serial
    write_allowed: [src/types/shared.ts, src/db/schema.ts]
    read_allowed: [src/db/**]
    acceptance: ["types exported"]
  - id: task-1-editor
    title: "editor slice"
    type: large_isolated
    backend: codex
    model: gpt-5.5
    isolation: worktree
    run: parallel
    depends_on: [task-0-foundation]
    write_allowed: [src/features/editor/**]
    read_allowed: [src/features/editor/**]
    acceptance: ["create/edit"]
  - id: task-2-api
    title: "api slice"
    type: bounded_crud
    backend: claude
    tier: standard
    effort: medium
    isolation: worktree
    run: parallel
    write_allowed: [src/features/api/**]
    read_allowed: [src/server/**]
    acceptance: ["crud"]
  - id: task-3-spec-review
    title: "spec review gate"
    type: review
    backend: claude
    tier: deep
    effort: high
    isolation: direct
    run: serial
    write_allowed: []
    read_allowed: [src/**]
    acceptance: ["AC met"]
"""

# Deliberately broken: codex w/o worktree, reviewer w/ sonnet, overlapping
# write globs, non-serial shared_foundation, unowned shared resource.
BAD_MANIFEST = """
run_id: 2026-06-26-bad
shared_resources:
  - src/types/orphan.ts
jobs:
  - id: task-0-foundation
    type: shared_foundation
    backend: claude
    model: opus
    isolation: direct
    run: parallel
    write_allowed: [src/db/schema.ts]
  - id: task-1-codex
    type: large_isolated
    backend: codex
    model: gpt-5.5
    isolation: direct
    run: parallel
    write_allowed: [src/features/**]
  - id: task-2-overlap
    type: bounded_crud
    backend: claude
    model: sonnet
    isolation: direct
    run: parallel
    write_allowed: [src/features/api/**]
  - id: task-3-review
    type: integration_review
    backend: claude
    model: sonnet
    isolation: direct
    run: serial
    write_allowed: []
  - id: task-4-no-routing
    type: docs
    backend: claude
    isolation: direct
    run: parallel
    write_allowed: [docs/orphan-area.md]
  - id: task-5-bad-vocab
    type: docs
    backend: claude
    tier: turbo
    effort: extreme
    isolation: direct
    run: parallel
    write_allowed: [docs/another-area.md]
"""


# A complete, otherwise-valid manifest whose ONE defect is parallel + direct.
PARALLEL_DIRECT_MANIFEST = """
run_id: 2026-06-26-pd
feature: "pd"
spec_path: docs/superpowers/specs/2026-06-26-pd.md
plan_path: docs/superpowers/plans/2026-06-26-pd.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-pd.md
  domain: docs/superpowers/expert/2026-06-26-pd.md
  library: docs/superpowers/library-audit/2026-06-26-pd.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-build
    title: "build slice"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: direct
    run: parallel
    write_allowed: [src/build/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""

# A complete manifest whose ONE defect is a path-traversal job id.
BAD_ID_MANIFEST = """
run_id: 2026-06-26-badid
feature: "badid"
spec_path: docs/superpowers/specs/2026-06-26-badid.md
plan_path: docs/superpowers/plans/2026-06-26-badid.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-badid.md
  domain: docs/superpowers/expert/2026-06-26-badid.md
  library: docs/superpowers/library-audit/2026-06-26-badid.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: ../x
    title: "evil"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    write_allowed: [src/evil/**]
    read_allowed: [src/**]
    acceptance: ["x"]
"""


# A complete, otherwise-valid manifest whose ONE defect is a model: haiku
# execution-layer override (must be rejected by the never-Haiku policy).
HAIKU_MODEL_MANIFEST = """
run_id: 2026-06-26-haiku
feature: "haiku"
spec_path: docs/superpowers/specs/2026-06-26-haiku.md
plan_path: docs/superpowers/plans/2026-06-26-haiku.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-haiku.md
  domain: docs/superpowers/expert/2026-06-26-haiku.md
  library: docs/superpowers/library-audit/2026-06-26-haiku.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-cheap
    title: "cheap slice"
    type: docs
    backend: claude
    model: claude-haiku-4
    isolation: worktree
    run: parallel
    write_allowed: [docs/cheap.md]
    read_allowed: [src/**]
    acceptance: ["x"]
"""

# A complete manifest whose ONE defect is a dangling depends_on reference.
DANGLING_DEP_MANIFEST = """
run_id: 2026-06-26-dangling
feature: "dangling"
spec_path: docs/superpowers/specs/2026-06-26-dangling.md
plan_path: docs/superpowers/plans/2026-06-26-dangling.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-dangling.md
  domain: docs/superpowers/expert/2026-06-26-dangling.md
  library: docs/superpowers/library-audit/2026-06-26-dangling.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-build
    title: "build slice"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    depends_on: [task-0-missing]
    write_allowed: [src/build/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""

# A complete manifest whose ONE defect is a depends_on cycle (A→B→A).
CYCLE_DEP_MANIFEST = """
run_id: 2026-06-26-cycle
feature: "cycle"
spec_path: docs/superpowers/specs/2026-06-26-cycle.md
plan_path: docs/superpowers/plans/2026-06-26-cycle.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-cycle.md
  domain: docs/superpowers/expert/2026-06-26-cycle.md
  library: docs/superpowers/library-audit/2026-06-26-cycle.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-a
    title: "a"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    depends_on: [task-b]
    write_allowed: [src/a/**]
    read_allowed: [src/**]
    acceptance: ["a"]
  - id: task-b
    title: "b"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    depends_on: [task-a]
    write_allowed: [src/b/**]
    read_allowed: [src/**]
    acceptance: ["b"]
"""

# A complete manifest whose ONE defect is a wrong-typed required field
# (acceptance_criteria provided as a scalar string instead of a list).
WRONG_TYPE_MANIFEST = """
run_id: 2026-06-26-wrongtype
feature: "wrongtype"
spec_path: docs/superpowers/specs/2026-06-26-wrongtype.md
plan_path: docs/superpowers/plans/2026-06-26-wrongtype.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-wrongtype.md
  domain: docs/superpowers/expert/2026-06-26-wrongtype.md
  library: docs/superpowers/library-audit/2026-06-26-wrongtype.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria: "ships"
jobs:
  - id: task-1-build
    title: "build slice"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    write_allowed: [src/build/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


def _selftest():
    failures = []

    def expect(name, cond):
        if cond:
            print("  ok   - %s" % name)
        else:
            print("  FAIL - %s" % name)
            failures.append(name)

    # Glob overlap units.
    expect("overlap: identical globs", globs_overlap("a/**", "a/**"))
    expect(
        "overlap: src/features/** vs src/features/api/**",
        globs_overlap("src/features/**", "src/features/api/**"),
    )
    expect(
        "disjoint: src/a/** vs src/b/**",
        not globs_overlap("src/a/**", "src/b/**"),
    )
    expect(
        "disjoint: src/types/x.ts vs src/db/y.ts",
        not globs_overlap("src/types/x.ts", "src/db/y.ts"),
    )
    expect(
        "overlap: dir/* vs dir/file.ts",
        globs_overlap("dir/*", "dir/file.ts"),
    )

    # GOOD manifest -> zero violations.
    good = validate_text(GOOD_MANIFEST)
    expect("good manifest: zero violations (%r)" % good, good == [])

    # BAD manifest -> catches each planted defect.
    bad = validate_text(BAD_MANIFEST)
    joined = " || ".join(bad)
    expect("bad manifest: has violations", len(bad) > 0)
    expect(
        "bad: codex-without-worktree caught",
        "backend codex" in joined and "isolation" in joined,
    )
    expect(
        "bad: reviewer-not-opus caught",
        "reviewer job" in joined and "opus" in joined,
    )
    expect("bad: write overlap caught", "overlap" in joined)
    expect(
        "bad: shared_foundation non-serial caught",
        "must run serial" in joined,
    )
    expect(
        "bad: orphan shared resource caught",
        "orphan.ts" in joined or "not written by any" in joined,
    )
    expect(
        "bad: missing model-or-tier caught",
        "must have 'model' or 'tier'" in joined,
    )
    expect(
        "bad: invalid tier caught",
        "tier 'turbo' invalid" in joined,
    )
    expect(
        "bad: invalid effort caught",
        "effort 'extreme' invalid" in joined,
    )
    expect(
        "bad: parallel+direct caught",
        "run: parallel with isolation: direct" in joined,
    )

    # never-Haiku policy: a model: haiku execution-layer override is INVALID.
    haiku = validate_text(HAIKU_MODEL_MANIFEST)
    expect(
        "model:haiku override caught (never-Haiku policy)",
        any("never-Haiku policy" in p for p in haiku),
    )

    # depends_on: dangling ref INVALID, cycle INVALID, valid DAG OK.
    dangling = validate_text(DANGLING_DEP_MANIFEST)
    expect(
        "dangling depends_on ref caught",
        any("references unknown job id 'task-0-missing'" in p for p in dangling),
    )
    cyc = validate_text(CYCLE_DEP_MANIFEST)
    expect(
        "depends_on cycle caught",
        any("cycle detected" in p for p in cyc),
    )
    expect(
        "valid DAG (good manifest) has no depends_on violation",
        not any("depends_on" in p or "cycle detected" in p for p in good),
    )

    # Structural type check: wrong-typed required field is a specific violation.
    wt_bad = validate_text(WRONG_TYPE_MANIFEST)
    expect(
        "wrong-typed acceptance_criteria caught",
        any("'acceptance_criteria' must be a list" in p for p in wt_bad),
    )

    # parallel ⇒ worktree, and a bad job id, each caught.
    pd_bad = validate_text(PARALLEL_DIRECT_MANIFEST)
    expect(
        "parallel+direct manifest invalid",
        any("run: parallel with isolation: direct" in p for p in pd_bad),
    )
    badid = validate_text(BAD_ID_MANIFEST)
    expect(
        "bad job id '../x' caught",
        any("invalid characters" in p for p in badid),
    )

    # Reviewer satisfied by tier: deep (no model) — GOOD manifest task-3 uses
    # tier: deep and must not trip the reviewer invariant.
    expect(
        "reviewer via tier:deep accepted (no model)",
        not any("reviewer job 'task-3-spec-review'" in p for p in good),
    )

    # Empty / malformed.
    expect("no jobs -> violation", validate_text("run_id: x") != [])
    expect("not a mapping -> violation", validate({}) != [])

    # Fallback parser parity: force the embedded parser on the good manifest.
    parsed = _mini_yaml(GOOD_MANIFEST)
    fb = validate(parsed)
    expect("fallback parser: good manifest clean (%r)" % fb, fb == [])
    fb_bad = validate(_mini_yaml(BAD_MANIFEST))
    expect("fallback parser: bad manifest flagged", len(fb_bad) > 0)

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
