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
   {low, medium, high, xhigh}. ``effort: xhigh`` is valid iff
   ``backend: codex`` (codex's kernel model_reasoning_effort accepts it —
   live-verified 2026-07-11 on codex-cli 0.144.1); any other backend with
   xhigh is a violation naming the rule.

Required-field + enum validation (before invariant checks)
-----------------------------------------------------------
All required fields per ``execution-manifest.md`` are checked first. Top-level:
``run_id``, ``jobs``, ``feature``, ``spec_path``, ``plan_path``, ``audits``,
``acceptance_criteria``, ``routing_stance``, ``max_parallel``. Per-job: ``id``,
``title``, ``type``, ``backend``, ``isolation``, ``run``, ``write_allowed``,
``read_allowed``, ``acceptance``, plus (``model`` OR ``tier``). Enums: ``backend``
∈ {claude, codex, antigravity, cursor, devin, opencode} (``none`` is the routing
"return to planning" sentinel, NOT a dispatched job backend; ``devin``/``opencode``
are lower-trust, opt-in, WORKER-ONLY backends — see adapter-devin.md /
adapter-opencode.md); ``isolation`` ∈ {direct, worktree};
``run`` ∈ {serial, parallel};
``routing_stance`` ∈ {balanced, conservative, cost-aware, claude-only};
``tier`` ∈ {deep, standard, light}; ``effort`` ∈ {low, medium, high, xhigh}
(``xhigh`` valid iff ``backend: codex``).

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

v2.9 — conditional fast-path (only when a top-level ``fast_path`` block is present)
-----------------------------------------------------------------------------------
A ``fast_path`` manifest adds: single-literal-path partition, block-YAML audit
skip-records, cross-artifact binding (AC-13/CR2-3: the sole ``write_allowed``
literal == ``localization.resolved_paths[0]``; ``pre_eval_id`` / ``FASTPATH_ELIGIBLE``
decision / ``taxonomy_digest`` / localization content-digest equal across the
manifest + pinned pre-eval record + localization artifact), CR4-6 path containment
(normalized, repo-relative, realpath-under-root, committed regular file), a pinned-
snapshot taxonomy denylist, and TWO validation modes (CR4-1) — a ``fast_path``
manifest with **no** ``--mode`` is rejected (fail-closed):
  * ``--mode pre-dispatch`` validates the ``fast_path.review`` DECLARATION
    (``backend:claude`` + ``tier:deep`` OR ``model:opus``, resolved through
    compound-v-resolve-model.py to a concrete Claude Opus; CR4-8/CR5-5) and FORBIDS
    a receipt (it cannot exist yet).
  * ``--mode post-review`` REQUIRES + verifies the dispatcher-written invocation
    receipt (``schemas/fastpath-review-receipt.schema.json``) naming the resolved
    model before REVIEWED/MERGED.
A legacy (non-fast_path) manifest ignores ``--mode`` entirely — backward compatible.

Usage
-----
    compound-v-validate-manifest.py <manifest.yaml>
    compound-v-validate-manifest.py --mode pre-dispatch|post-review \\
        [--repo-root DIR] [--config FILE] [--receipt FILE] <manifest.yaml>
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
# changes when concrete models churn. `xhigh` is valid iff backend == "codex"
# (codex's kernel model_reasoning_effort accepts it — live-verified 2026-07-11
# on codex-cli 0.144.1); validate() rejects xhigh on every other backend.
VALID_TIERS = ("deep", "standard", "light")
VALID_EFFORTS = ("low", "medium", "high", "xhigh")

# Enum vocabularies for required-field validation (per execution-manifest.md).
VALID_BACKENDS = ("claude", "codex", "antigravity", "cursor", "devin", "opencode")
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


# --------------------------------------------------------------------------- #
# Optional per-job `advisor:` block (v2.12, Feature B1).
#
# The "cheap executor + on-demand cross-brand advisor" pattern lets a core-slice
# implementer consult a DIFFERENT-brand advisor on a hard sub-decision. A job MAY
# declare an optional advisor block:
#
#     advisor:
#       enabled: <bool>            # optional; must be a boolean if present
#       advisor_backend: <string>  # optional; must be a known backend if present
#
# Minimal, additive schema: unknown keys are rejected; a job WITHOUT `advisor:`
# stays valid (backward compatible). An advisor block on an advisor-INELIGIBLE job
# type — a reviewer, a `docs` job, or a `shared_foundation` job (none of which is a
# core-slice implementer; see compound-v-resolve-model.py:advisor_eligible) — is
# rejected with a clear message.
# --------------------------------------------------------------------------- #
ADVISOR_ALLOWED_KEYS = ("enabled", "advisor_backend")
ADVISOR_INELIGIBLE_TYPES = ("docs", "shared_foundation")


def _validate_advisor_block(job, jid):
    """Validate an optional per-job ``advisor:`` block. Returns a list of problem
    strings (empty when the job has no advisor block or the block is well-formed on
    an eligible job)."""
    problems = []
    if "advisor" not in job:
        return problems  # backward compatible: no advisor block => nothing to check

    jtype = str(job.get("type", "")).lower()
    # Ineligible job types cannot carry an advisor, regardless of block shape.
    if _is_reviewer(job) or jtype in ADVISOR_INELIGIBLE_TYPES:
        problems.append(
            "job '%s' (type '%s') carries an 'advisor' block but is advisor-INELIGIBLE "
            "— reviewer / docs / shared_foundation jobs are not core-slice implementers; "
            "remove the advisor block or retype the job" % (jid, job.get("type"))
        )
        return problems

    adv = job.get("advisor")
    if not isinstance(adv, dict):
        problems.append(
            "job '%s' advisor must be a mapping (e.g. {enabled: true})" % jid
        )
        return problems

    for key in adv:
        if key not in ADVISOR_ALLOWED_KEYS:
            problems.append(
                "job '%s' advisor has unknown key '%s' (allowed: %s)"
                % (jid, key, ", ".join(ADVISOR_ALLOWED_KEYS))
            )
    if "enabled" in adv and not isinstance(adv.get("enabled"), bool):
        problems.append(
            "job '%s' advisor.enabled must be a boolean (got %r)"
            % (jid, adv.get("enabled"))
        )
    if "advisor_backend" in adv:
        ab = adv.get("advisor_backend")
        if not isinstance(ab, str) or ab.strip().lower() not in VALID_BACKENDS:
            problems.append(
                "job '%s' advisor.advisor_backend %r is not a known backend "
                "(expected one of %s)" % (jid, ab, ", ".join(VALID_BACKENDS))
            )
    return problems


# --------------------------------------------------------------------------- #
# v2.9 conditional fast-path support (only engaged when a top-level `fast_path`
# block is present). Sibling scripts are loaded by path (their filenames have
# hyphens, so they are not importable module names).
# --------------------------------------------------------------------------- #
FASTPATH_MODES = ("pre-dispatch", "post-review")
_EXEC_DIR = os.path.join("docs", "superpowers", "execution")
_RECEIPT_SUBPATH = os.path.join("review", "receipt.json")
_RECEIPT_SCHEMA = os.path.join("schemas", "fastpath-review-receipt.schema.json")
# Bounded `git diff` capture for the anti-stale-replay diff-digest recompute —
# MUST match the producer's cap (compound-v-fastpath-run.py MAX_DIFF_BYTES) so a
# receipt written by the producer content-addresses to the same value here.
_MAX_DIFF_BYTES = 1_000_000
_GIT_DIFF_TIMEOUT_S = 30
# Bounded wall-clock cap for the HEAD-containment `git cat-file -e` probe, which is
# routed through the shared process-group timeout supervisor (MED-8).
_GIT_PROBE_TIMEOUT_S = 30
# MED-8 sentinel: git IS present (the tree has a `.git`) but the HEAD-containment
# probe could NOT complete — the supervisor/launch itself failed (None → mapped
# here), the probe timed out (supervisor exit 124), or the git binary is missing
# (exit 127). This is DISTINCT from ``None`` (no `.git` at all → the legitimate
# no-git degrade the pre-dispatch fixtures rely on): a ``require_committed`` caller
# must fail CLOSED on this sentinel rather than silently skip the containment check.
_GIT_UNAVAILABLE = object()

_SIBLING_CACHE = {}


def _load_sibling(basename):
    import importlib.util

    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, basename)
    try:
        modname = "cv_" + re.sub(r"[^0-9A-Za-z_]", "_", basename)
        spec = importlib.util.spec_from_file_location(modname, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001 - any load failure -> caller degrades
        return None


def _sibling(basename):
    if basename not in _SIBLING_CACHE:
        _SIBLING_CACHE[basename] = _load_sibling(basename)
    return _SIBLING_CACHE[basename]


def _read_json_file(repo_root, relpath):
    """Read a JSON file relative to ``repo_root``; return (obj, err_or_None)."""
    try:
        with open(os.path.join(repo_root, relpath), "r", encoding="utf-8") as fh:
            return json.load(fh), None
    except Exception as e:  # noqa: BLE001 - any read/parse failure -> fail-closed
        return None, str(e)


def _is_claude_opus(model):
    """A resolved model counts as Claude Opus iff its name contains 'opus'
    (case-insensitive). A config override to sonnet/gpt/etc. therefore fails."""
    return isinstance(model, str) and "opus" in model.lower()


# Canonical content-digest shape: 'sha256:' + 64 hex chars (pre-eval-config.md §2).
_DIGEST_RE = re.compile(r"sha256:[0-9a-fA-F]{64}\Z")


def _is_digest_shaped(v):
    """True iff ``v`` is a well-formed canonical content-digest ('sha256:<64-hex>').
    A missing/non-string/mis-shaped digest is NOT shaped, so a caller can fail
    closed on absence instead of silently skipping the comparison."""
    return isinstance(v, str) and _DIGEST_RE.match(v) is not None


def _is_git_tracked(repo_root, relpath):
    """True/False if a git tree is present (worktree ``.git`` is a FILE, so we test
    existence not is-dir); None when git is unavailable so the caller can skip."""
    import subprocess

    if not os.path.exists(os.path.join(repo_root, ".git")):
        return None
    try:
        r = subprocess.run(
            ["git", "-C", repo_root, "ls-files", "--error-unmatch", relpath],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return r.returncode == 0
    except Exception:  # noqa: BLE001 - git missing/broken -> skip the tracked check
        return None


def _git_via_supervisor(cwd, git_args, timeout_s=_GIT_PROBE_TIMEOUT_S):
    """Run ``git -C cwd <git_args>`` UNDER the shared process-group timeout
    supervisor (``compound-v-run-with-timeout.py``) with ``stdin </dev/null`` and a
    bounded wall-clock cap — never a bare ``subprocess.run(timeout=...)`` on git (the
    external-launch invariant the rest of the pipeline holds; MED-8). Returns the
    git command's own exit code, or ``None`` when the supervisor itself cannot be
    launched (script absent / OSError). A timeout surfaces as 124 and a missing git
    binary as 127 (supervisor conventions); both are fail-closed at the caller."""
    import subprocess

    sup = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "compound-v-run-with-timeout.py")
    if not os.path.isfile(sup):
        return None
    cmd = [sys.executable, sup, "--timeout", str(int(timeout_s)), "--grace", "1",
           "--", "git", "-C", cwd] + list(git_args)
    try:
        r = subprocess.run(
            cmd, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode
    except Exception:  # noqa: BLE001 - cannot launch the supervisor -> fail-closed
        return None


def _is_committed_at_head(repo_root, relpath):
    """Whether ``relpath`` exists in the HEAD *commit* tree — committed, not merely
    tracked-or-staged. ``git ls-files`` accepts a newly-STAGED path that is absent
    from every commit; artifacts must live in a commit (execution-manifest.md), so a
    staged-but-uncommitted artifact must fail. Returns:

      * ``True``  — the path is present in a commit at HEAD;
      * ``False`` — git ran cleanly and the object is absent from HEAD (staged-only,
        untracked, or a repo with no commits — ``cat-file -e`` exits 1/128);
      * ``None``  — there is NO ``.git`` at all (the legitimate no-git degrade the
        pre-dispatch fixtures rely on — a fixture with no repo behaves as before);
      * ``_GIT_UNAVAILABLE`` — a ``.git`` IS present but the probe could not COMPLETE
        (supervisor/launch failure, timeout=124, or git-not-found=127). MED-8: a
        ``require_committed`` caller fails CLOSED on this, never silently skips it.

    The probe (``git cat-file -e HEAD:<path>``) runs through the process-group
    timeout supervisor (``stdin </dev/null``, bounded), like every other git read."""
    if not os.path.exists(os.path.join(repo_root, ".git")):
        return None
    rc = _git_via_supervisor(repo_root, ["cat-file", "-e", "HEAD:" + relpath])
    if rc is None or rc in (124, 127):
        # supervisor/launch failure, timeout, or missing git binary while a `.git`
        # IS present -> the probe could not complete -> fail closed (MED-8).
        return _GIT_UNAVAILABLE
    if rc == 0:
        return True
    return False  # git ran; object absent from HEAD (exit 1/128) -> not committed


def _containment_problems(label, relpath, repo_root, must_exist=True,
                          require_committed=False):
    """CR4-6 path containment. The path MUST be normalized, repo-relative (no
    absolute, no ``..`` segment), realpath-under-repo-root (this also rejects any
    escaping symlink in the chain — realpath resolves every link), and a committed
    regular file (never a symlink). Mirrors scope-check.py's realpath containment
    intent; the whole-tree escaping-symlink scan is scope-check.py's job at gate
    time. Returns a list of violation strings."""
    problems = []
    if not isinstance(relpath, str) or not relpath.strip():
        return ["%s is empty or not a string" % label]
    if os.path.isabs(relpath) or (len(relpath) >= 2 and relpath[1] == ":"):
        return ["%s '%s' must be repo-relative (absolute path rejected)"
                % (label, relpath)]
    parts = re.split(r"[\\/]", relpath)
    if ".." in parts:
        return ["%s '%s' contains a '..' traversal segment (rejected)"
                % (label, relpath)]
    norm = os.path.normpath(relpath)
    if norm != relpath:
        problems.append("%s '%s' is not normalized (expected '%s')"
                        % (label, relpath, norm))
    if repo_root is None:
        return problems
    root_real = os.path.realpath(repo_root)
    prefix = root_real.rstrip(os.sep) + os.sep
    full = os.path.join(repo_root, norm)
    real = os.path.realpath(full)
    if not (real == root_real or real.startswith(prefix)):
        problems.append("%s '%s' resolves outside the repo root "
                        "(symlink/realpath escape)" % (label, relpath))
        return problems
    if must_exist:
        if not os.path.lexists(full):
            problems.append("%s '%s' does not exist (expected a committed "
                            "regular file)" % (label, relpath))
            return problems
        if os.path.islink(full):
            problems.append("%s '%s' is a symlink (must be a committed regular "
                            "file, not a symlink)" % (label, relpath))
            return problems
        if not os.path.isfile(full):
            problems.append("%s '%s' is not a regular file" % (label, relpath))
            return problems
        tracked = _is_git_tracked(repo_root, norm)
        if tracked is False:
            problems.append("%s '%s' is not committed (git does not track it)"
                            % (label, relpath))
        elif require_committed:
            # MED-9: `git ls-files` (the tracked check above) also accepts a
            # newly-STAGED path absent from every commit. Artifacts referenced by
            # the manifest MUST be durable in a commit, so verify HEAD directly.
            committed = _is_committed_at_head(repo_root, norm)
            if committed is False:
                problems.append(
                    "%s '%s' is not present in a commit at HEAD — a staged-only "
                    "or uncommitted artifact is not durable; referenced artifacts "
                    "must be committed (fail-closed)" % (label, relpath))
            elif committed is _GIT_UNAVAILABLE:
                # MED-8: a `.git` IS present but the HEAD probe errored / timed out
                # / git is unavailable. The prior code returned None here and the
                # caller only treated literal False as a violation, so a git error
                # PASSED containment. A committed-artifact requirement must fail
                # CLOSED on an unverifiable probe — never a silent skip.
                problems.append(
                    "%s '%s' HEAD-commit containment could not be verified — the "
                    "git probe errored, timed out, or git is unavailable while a "
                    "'.git' is present; a committed-artifact requirement fails "
                    "closed on an unverifiable probe (MED-8)" % (label, relpath))
            # committed is True -> present at HEAD (ok); committed is None -> no
            # `.git` at all -> the legitimate no-git degrade (skip).
    return problems


def _review_resolution(review, stance, repo_root, config_path):
    """Validate + RESOLVE the fast_path.review DECLARATION through the real
    resolver (CR5-5/CR4-8). Returns (problems, resolved_model). The declaration
    MUST be backend:claude + (tier:deep OR model:opus), and the concrete resolved
    model MUST be Claude Opus."""
    problems = []
    if not isinstance(review, dict) or not review:
        return (["fast_path.review declaration is missing or not a mapping"], None)
    backend = str(review.get("backend", "")).lower()
    tier = review.get("tier")
    model = review.get("model")
    if backend != "claude":
        problems.append(
            "fast_path.review backend '%s' invalid — the reviewer-Opus guarantee "
            "requires backend: claude (CR5-5)" % review.get("backend"))
    has_deep = str(tier or "").lower() == "deep"
    has_opus_pin = str(model or "").lower() == "opus"
    if not has_deep and not has_opus_pin:
        problems.append(
            "fast_path.review must declare tier: deep OR model: opus "
            "(CR4-8), got tier=%r model=%r" % (tier, model))

    rm = _sibling("compound-v-resolve-model.py")
    if rm is None:
        problems.append("cannot load compound-v-resolve-model.py to resolve the "
                        "fast_path.review declaration — fail-closed")
        return (problems, None)
    cfg_path = config_path
    if cfg_path is None and repo_root is not None:
        cand = os.path.join(repo_root, ".claude", "compound-v.json")
        cfg_path = cand if os.path.isfile(cand) else None
    try:
        config_models = rm.load_config_models(cfg_path) if cfg_path else {}
    except Exception as e:  # noqa: BLE001 - malformed config -> fail-closed
        problems.append("fast_path.review: project config models unreadable "
                        "(%s) — fail-closed" % e)
        return (problems, None)
    try:
        res = rm.resolve(
            backend="claude", tier="deep", config_models=config_models,
            explicit_model=(model if has_opus_pin else None),
            stance=(stance or "balanced"))
        resolved_model = res.get("model")
    except Exception as e:  # noqa: BLE001 - unresolvable -> fail-closed
        problems.append("fast_path.review does not resolve to a concrete model "
                        "(%s) — fail-closed" % e)
        return (problems, None)
    if not _is_claude_opus(resolved_model):
        problems.append(
            "fast_path.review resolves to '%s', not Claude Opus — reviewers must "
            "be Opus (CR5-5); a models.<stance>.claude.deep override that isn't "
            "opus fails" % resolved_model)
    return (problems, resolved_model)


def _load_receipt_schema():
    """Load the bundled fast-path receipt JSON-schema. Returns ``(schema, None)`` on
    success, else ``(None, err)``. MED-3: the schema SHIPS in-repo at
    ``schemas/fastpath-review-receipt.schema.json``, so a missing / unreadable /
    malformed schema is an ANOMALY, not an expected "schema absent" case — the caller
    MUST treat ``(None, err)`` as a verification PROBLEM and fail closed, NEVER skip
    the shape validation (a receipt carrying only ids+backend+verdict must not slip
    through because the schema failed to load)."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(os.path.dirname(here), _RECEIPT_SCHEMA)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
    except Exception as e:  # noqa: BLE001 - missing/unreadable/malformed all fail closed
        return None, ("review-receipt schema '%s' could not be loaded (%s) — it ships "
                      "in-repo, so this is an anomaly; fail-closed, shape validation "
                      "cannot be skipped (MED-3)" % (_RECEIPT_SCHEMA, e))
    if not isinstance(schema, dict):
        return None, ("review-receipt schema '%s' is not a JSON object — fail-closed "
                      "(MED-3)" % _RECEIPT_SCHEMA)
    return schema, None


def _json_type_ok(v, t):
    types = t if isinstance(t, list) else [t]
    for tt in types:
        if tt == "string" and isinstance(v, str):
            return True
        if tt == "integer" and isinstance(v, int) and not isinstance(v, bool):
            return True
        if tt == "number" and isinstance(v, (int, float)) and not isinstance(v, bool):
            return True
        if tt == "array" and isinstance(v, list):
            return True
        if tt == "object" and isinstance(v, dict):
            return True
        if tt == "boolean" and isinstance(v, bool):
            return True
        if tt == "null" and v is None:
            return True
    return False


def _schema_lite_value(v, spec, label):
    problems = []
    t = spec.get("type")
    if t is not None and not _json_type_ok(v, t):
        return ["%s has wrong type (expected %s)" % (label, t)]
    if "const" in spec and v != spec["const"]:
        problems.append("%s must be %r (got %r)" % (label, spec["const"], v))
    if "enum" in spec and v not in spec["enum"]:
        problems.append("%s must be one of %s (got %r)" % (label, spec["enum"], v))
    if "pattern" in spec and isinstance(v, str) and re.search(spec["pattern"], v) is None:
        problems.append("%s does not match pattern %s" % (label, spec["pattern"]))
    return problems


def _schema_lite(obj, schema, label):
    """A tiny JSON-Schema subset checker (required / additionalProperties:false /
    type / const / enum / pattern on a flat object). Enough to structurally
    validate the receipt without a jsonschema dependency."""
    problems = []
    if schema.get("type") == "object":
        if not isinstance(obj, dict):
            return ["%s is not a JSON object" % label]
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in obj:
                problems.append("%s missing required field '%s'" % (label, req))
        if schema.get("additionalProperties") is False:
            for k in obj:
                if k not in props:
                    problems.append("%s has unknown field '%s'" % (label, k))
        for k, spec in props.items():
            if k in obj:
                problems.extend(_schema_lite_value(obj[k], spec, "%s.%s" % (label, k)))
    return problems


def _read_run_baseline(repo_root, run_id, sole_job_id):
    """Read the IMMUTABLE pre-launch baseline SHA from the run's state.json (the
    scope gate + F2 reclassifier ran against it; never HEAD, CR5-3). The baseline
    is the trust anchor — the receipt's baseline_sha is checked against THIS, and
    the diff-digest is recomputed against THIS, never against a receipt-supplied
    value. Returns (baseline_str, None) or (None, err) — fail-closed on absence."""
    if repo_root is None or run_id in (None, ""):
        return None, "no repo root or run_id to locate the run state"
    state_full = os.path.join(repo_root, _EXEC_DIR, str(run_id), "state.json")
    try:
        with open(state_full, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except Exception as e:  # noqa: BLE001 - any read/parse failure -> fail-closed
        return None, "run state.json unreadable (%s)" % e
    jobs = state.get("jobs") if isinstance(state, dict) else None
    if not isinstance(jobs, dict) or not jobs:
        return None, "run state.json has no 'jobs' map"
    entry = None
    if sole_job_id is not None and sole_job_id in jobs:
        entry = jobs[sole_job_id]
    elif len(jobs) == 1:
        entry = next(iter(jobs.values()))
    if not isinstance(entry, dict):
        return None, "run state.json has no entry for the fast-path job"
    base = entry.get("baseline")
    if not isinstance(base, str) or not base.strip():
        return None, "the fast-path job has no recorded immutable baseline SHA"
    return base.strip(), None


def _recompute_diff_digest(diff_root, baseline, tax):
    """Recompute the FINAL diff digest — 'sha256:'+sha256(git diff --no-color
    <baseline>) — the anti-stale-replay comparison value (same command + convention
    as the producer). CRIT-1: ``diff_root`` MUST be the SAME checkout the producer
    hashed (the worker's linked WORKTREE), NOT necessarily the main repo — the
    caller passes the run's worktree and falls back to the repo root only when none
    was supplied. Returns (digest, None) or (None, err). Fail-closed on a git error
    (an unavailable/wrong-checkout diff_root exits non-zero here), a non-object-id
    baseline, or a truncated (over-cap) capture."""
    import subprocess

    if diff_root is None:
        return None, "no diff root"
    if tax is None:
        return None, "shared digest primitive unavailable"
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", str(baseline or "")):
        return None, "baseline '%s' is not a git object id" % baseline
    try:
        p = subprocess.run(
            ["git", "-C", diff_root, "diff", "--no-color", str(baseline)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=_GIT_DIFF_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 - git missing/broken/timeout -> fail-closed
        return None, "git diff failed (%s)" % e
    if p.returncode != 0:
        return None, ("git diff against baseline '%s' exited %d"
                      % (baseline, p.returncode))
    data = p.stdout or b""
    if len(data) >= _MAX_DIFF_BYTES:
        return None, "diff exceeds the bounded capture — ambiguous, fail-closed"
    return tax.taxonomy_digest_bytes(data), None


def _sealed_receipt_problems(receipt, pre_eval_id, run_id):
    """The SEALED-receipt verification problem list (empty ⇒ verified). This is the
    portion of the fast-path review receipt that is self-contained to the receipt
    object plus the two binding ids — no repo / diff / manifest context. Backs
    ``verify_sealed_receipt``; kept as a list so ``_validate_receipt`` can preserve
    the exact per-check messages its regression suite asserts on."""
    problems = []
    # MED-3: a schema-load failure is itself a verification PROBLEM (fail-closed) — the
    # schema ships in-repo, so an unloadable schema must REJECT, never silently skip the
    # shape checks (which would let a receipt with only ids+backend+verdict pass).
    schema, sch_err = _load_receipt_schema()
    if sch_err is not None:
        problems.append(sch_err)
    elif schema is not None:
        problems.extend(_schema_lite(receipt, schema, "review receipt"))
    if not isinstance(receipt, dict):
        return problems
    tax = _sibling("compound-v-taxonomy.py")

    # --- identity binding: run_id + pre_eval_id ---
    if str(receipt.get("run_id")) != str(run_id):
        problems.append("review receipt run_id '%s' != expected run_id '%s'"
                        % (receipt.get("run_id"), run_id))
    if str(receipt.get("pre_eval_id")) != str(pre_eval_id):
        problems.append("review receipt pre_eval_id '%s' != expected pre_eval_id "
                        "'%s'" % (receipt.get("pre_eval_id"), pre_eval_id))

    # --- reviewer must resolve to Claude Opus (CR5-5) ---
    if str(receipt.get("reviewer_backend", "")).lower() != "claude":
        problems.append("review receipt reviewer_backend '%s' invalid — must be "
                        "claude (CR5-5)" % receipt.get("reviewer_backend"))
    if not _is_claude_opus(receipt.get("reviewer_model")):
        problems.append("review receipt reviewer_model '%s' is not Claude Opus "
                        "(CR5-5)" % receipt.get("reviewer_model"))

    # --- verdict MUST be an explicit, normalized 'approved' (CR5-6) ---
    verdict = receipt.get("verdict")
    if not isinstance(verdict, str) or verdict.strip().lower() != "approved":
        problems.append("review receipt verdict %r is not 'approved' — a "
                        "non-approved or absent verdict blocks the merge "
                        "(fail-closed, CR5-6)" % verdict)

    # --- receipt self-digest: REQUIRED + verified via the SHARED primitive ---
    rdig = receipt.get("digest")
    if not isinstance(rdig, str) or not rdig:
        problems.append("review receipt is missing its self-digest — cannot "
                        "verify integrity (fail-closed, CR5-6)")
    elif tax is None:
        problems.append("review receipt self-digest cannot be verified — shared "
                        "taxonomy digest primitive unavailable (fail-closed)")
    else:
        try:
            if tax.record_digest(receipt, exclude_field="digest") != rdig:
                problems.append("review receipt self-digest mismatch — the "
                                "receipt was tampered (fail-closed, CR5-6)")
        except Exception as e:  # noqa: BLE001
            problems.append("review receipt self-digest cannot be recomputed "
                            "(%s) — fail-closed" % e)
    return problems


def verify_sealed_receipt(receipt, pre_eval_id, run_id):
    """Reusable sealed-receipt verification — the SINGLE authority for the receipt
    checks that need no repo/diff/manifest context. Verifies, in order:

      * schema shape (via the bundled fastpath-review-receipt schema, when present);
      * the REQUIRED self-integrity digest matches the SHARED canonical-JSON
        primitive ``compound-v-taxonomy.record_digest(receipt, exclude_field=
        "digest")`` — the same primitive the producer seals the receipt with;
      * ``verdict``, normalized, is exactly ``'approved'``;
      * ``run_id`` and ``pre_eval_id`` bind to the supplied ids;
      * ``reviewer_backend`` is ``'claude'`` AND ``reviewer_model`` is Claude Opus.

    Returns ``(ok: bool, reason: str)`` — ``reason`` is empty on success, else the
    ``'; '``-joined list of every failing check. Fail-closed: a non-dict receipt, an
    unavailable shared digest primitive, or a missing self-digest all return False.

    ``compound-v-triage-outcomes.py`` imports this by path so its precision gate
    applies the SAME verification as the post-review validator, instead of a weaker
    parallel ``verdict``/``run_id``/``pre_eval_id``-only check. The post-review path
    (``_validate_receipt``) also calls this, then adds the repo-context bindings
    (manifest digest, baseline, final diff, worktree) it alone can recompute."""
    problems = _sealed_receipt_problems(receipt, pre_eval_id, run_id)
    return (len(problems) == 0, "; ".join(problems))


def _validate_receipt(receipt_full, receipt_rel, manifest, fp, expected_model,
                      repo_root, manifest_bytes, sole_job_id, diff_root=None,
                      expected_attempt=None):
    """post-review: require + FULLY verify the dispatcher-written invocation
    receipt. Per CR5-6 the receipt MUST bind to and be verified against: run_id,
    pre_eval_id, the manifest digest, the immutable pre-launch baseline SHA, the
    FINAL diff digest, the reviewer backend/model (⇒ Claude Opus), attempt id,
    timestamp, and a normalized verdict of 'approved'. A stale receipt (wrong
    manifest / baseline / diff) or a non-approved-or-absent verdict fails
    closed. Every binding value is recomputed here — never trusted from the
    receipt itself.

    HIGH-1(b): when ``expected_attempt`` is supplied (the caller reads the CURRENT
    review attempt from the run's state.json), the receipt's ``attempt_id`` MUST equal
    it — a sealed attempt-1 receipt replayed when the expected next attempt is 2 fails
    closed. The check lives HERE, in the post-review caller, NOT in the shared
    ``verify_sealed_receipt`` (whose signature stays stable for triage). When
    ``expected_attempt`` is None the attempt check is skipped (back-compat), but the
    authoritative dispatcher flow ALWAYS passes it."""
    if not os.path.isfile(receipt_full):
        return ["fast_path --mode post-review requires a review receipt at '%s', "
                "none found (fail-closed)" % receipt_rel]
    try:
        with open(receipt_full, "r", encoding="utf-8") as fh:
            receipt = json.load(fh)
    except Exception as e:  # noqa: BLE001
        return ["fast_path review receipt '%s' is unreadable or not JSON (%s)"
                % (receipt_rel, e)]
    problems = []
    # --- sealed-receipt checks (schema shape + self-digest + verdict + id binding +
    #     reviewer-opus) via the SHARED entrypoint that triage also imports, so the
    #     two paths can never diverge. Repo-context bindings (expected_model,
    #     manifest digest, baseline, final diff, worktree) are added below. ---
    ok, reason = verify_sealed_receipt(
        receipt, fp.get("pre_eval_id"), manifest.get("run_id"))
    if not ok:
        problems.append(reason)
    if not isinstance(receipt, dict):
        return problems
    tax = _sibling("compound-v-taxonomy.py")
    rmodel = receipt.get("reviewer_model")
    if (expected_model is not None and rmodel is not None
            and str(rmodel) != str(expected_model)):
        problems.append("review receipt reviewer_model '%s' does not name the "
                        "resolved review model '%s'" % (rmodel, expected_model))

    # (verdict + reviewer-opus + self-digest are verified in verify_sealed_receipt.)

    # --- HIGH-1(b): attempt binding. The authoritative flow passes the CURRENT review
    #     attempt (from state.json); the receipt's attempt_id must equal it so a stale
    #     prior-attempt receipt cannot be replayed against a newer attempt. Compared as
    #     strings because the schema permits attempt_id to be string OR integer. ---
    if expected_attempt is not None:
        r_att = receipt.get("attempt_id")
        if str(r_att) != str(expected_attempt):
            problems.append("review receipt attempt_id %r != the expected review "
                            "attempt %r (from state.json) — a stale prior-attempt "
                            "receipt cannot be replayed against a newer attempt "
                            "(fail-closed, HIGH-1)" % (r_att, expected_attempt))

    # --- manifest_digest: REQUIRED + recomputed over the manifest under review ---
    r_mdig = receipt.get("manifest_digest")
    if not isinstance(r_mdig, str) or not r_mdig:
        problems.append("review receipt is missing manifest_digest — cannot bind "
                        "the receipt to the reviewed contract (fail-closed, CR5-6)")
    elif tax is None or manifest_bytes is None:
        problems.append("review receipt manifest_digest cannot be verified "
                        "(manifest bytes or digest primitive unavailable) — "
                        "fail-closed")
    else:
        want_mdig = tax.taxonomy_digest_bytes(manifest_bytes)
        if r_mdig != want_mdig:
            problems.append("review receipt manifest_digest '%s' != the manifest "
                            "under validation '%s' — stale or wrong-manifest "
                            "receipt (fail-closed, CR5-6)" % (r_mdig, want_mdig))

    # --- baseline_sha + final_diff_digest: bound to the run's IMMUTABLE
    #     baseline (state.json), and the diff recomputed against it ---
    baseline, berr = _read_run_baseline(
        repo_root, manifest.get("run_id"), sole_job_id)
    r_base = receipt.get("baseline_sha")
    if not isinstance(r_base, str) or not r_base:
        problems.append("review receipt is missing baseline_sha (fail-closed, "
                        "CR5-6)")
    if baseline is None:
        problems.append("cannot read the run's immutable pre-launch baseline to "
                        "verify the receipt (%s) — fail-closed" % berr)
    elif isinstance(r_base, str) and r_base and str(r_base) != str(baseline):
        problems.append("review receipt baseline_sha '%s' != the run's immutable "
                        "baseline '%s' — receipt bound to a different baseline "
                        "(fail-closed, CR5-6)" % (r_base, baseline))

    # --- MED-6: the receipt's OWN worktree binding MUST name the SAME checkout the
    #     validator recomputes the final diff in (``diff_root``, falling back to
    #     ``repo_root``). The prior code recomputed in that root but never checked
    #     the receipt's declared ``worktree`` against it, so a receipt sealed against
    #     a DIFFERENT checkout — whose diff hashes differently — was never caught by
    #     this binding. Compared as normalized realpaths (symlinks/`.`/`..` resolved);
    #     a relative worktree is anchored to ``repo_root``. The recompute below still
    #     runs against the trusted CLI root regardless, so a mismatch is an ADDED
    #     violation, never a way to skip the diff check. ---
    eff_diff_root = diff_root or repo_root
    r_wt = receipt.get("worktree")
    if not isinstance(r_wt, str) or not r_wt.strip():
        problems.append("review receipt is missing its 'worktree' binding — the "
                        "diff-root the producer hashed final_diff_digest against is "
                        "unrecorded, so the receipt cannot be tied to the checkout "
                        "under verification (fail-closed, MED-6)")
    elif eff_diff_root is None:
        problems.append("review receipt 'worktree' binding cannot be verified — no "
                        "diff-root is available to compare it against (fail-closed, "
                        "MED-6)")
    else:
        wt_abs = r_wt if os.path.isabs(r_wt) else os.path.join(repo_root, r_wt)
        if os.path.realpath(wt_abs) != os.path.realpath(eff_diff_root):
            problems.append("review receipt 'worktree' '%s' does not resolve to the "
                            "diff-root the final diff is recomputed in ('%s') — the "
                            "receipt was sealed against a different checkout "
                            "(fail-closed, MED-6)" % (r_wt, eff_diff_root))

    r_ddig = receipt.get("final_diff_digest")
    if not isinstance(r_ddig, str) or not r_ddig:
        problems.append("review receipt is missing final_diff_digest (fail-closed, "
                        "CR5-6)")
    elif baseline is not None:
        # CRIT-1: recompute in the SAME checkout the producer hashed (the worker's
        # linked worktree), falling back to repo_root only when no diff_root was
        # supplied. An unavailable worktree makes the git diff fail → fail-closed.
        cur_ddig, derr = _recompute_diff_digest(
            eff_diff_root, str(baseline), tax)
        if cur_ddig is None:
            problems.append("cannot recompute the final diff against baseline '%s' "
                            "(%s) — fail-closed" % (baseline, derr))
        elif cur_ddig != r_ddig:
            problems.append("review receipt final_diff_digest '%s' != the current "
                            "diff '%s' — stale-receipt replay against a changed "
                            "diff (fail-closed, CR5-6)" % (r_ddig, cur_ddig))

    return problems


def _validate_fast_path(manifest, fp, mode, repo_root, config_path, receipt_path,
                        manifest_bytes=None, diff_root=None, expected_attempt=None):
    """All v2.9 conditional fast-path invariants (gated on fast_path.eligible).
    Returns a list of violation strings."""
    problems = []
    if repo_root is None:
        repo_root = os.getcwd()
    if not isinstance(fp, dict):
        return ["fast_path block must be a mapping"]
    if fp.get("eligible") is not True:
        problems.append("fast_path.eligible must be true (a fast_path block with "
                        "eligible not-true is rejected)")

    # Mode is mandatory + fail-closed for a fast_path manifest.
    if mode is None:
        problems.append("fast_path manifest requires an explicit --mode "
                        "(pre-dispatch|post-review); no-mode is fail-closed")
    elif mode not in FASTPATH_MODES:
        problems.append("fast_path --mode '%s' invalid (expected one of %s)"
                        % (mode, ", ".join(FASTPATH_MODES)))

    # Exactly ONE implementer job; the review is a dispatcher PHASE, not a job.
    jobs = manifest.get("jobs") if isinstance(manifest.get("jobs"), list) else []
    if len(jobs) != 1:
        problems.append(
            "fast_path manifest must have exactly ONE implementer job (found %d); "
            "the combined SPEC+QUALITY review is a dispatcher phase "
            "(fast_path.review), not a jobs entry" % len(jobs))
    job0 = jobs[0] if jobs and isinstance(jobs[0], dict) else None
    if job0 is not None and _is_reviewer(job0):
        problems.append("fast_path manifest's sole job '%s' is a reviewer — the "
                        "review must be the fast_path.review phase, not a jobs "
                        "entry" % job0.get("id"))

    # Sole write_allowed literal.
    write_literal = None
    if job0 is not None:
        wa = job0.get("write_allowed")
        if not isinstance(wa, list) or len(wa) != 1:
            problems.append("fast_path job '%s' write_allowed must be exactly ONE "
                            "literal path" % job0.get("id"))
        else:
            cand = str(wa[0])
            if not _seg_is_literal(cand):
                problems.append("fast_path write_allowed '%s' must be a single "
                                "LITERAL normalized path (no glob metachar *?[)"
                                % cand)
            else:
                write_literal = cand
                if os.path.normpath(cand) != cand:
                    problems.append("fast_path write_allowed '%s' is not "
                                    "normalized (expected '%s')"
                                    % (cand, os.path.normpath(cand)))

    # Sentinel audits: block-YAML skip-records only (flow-{} rejected).
    audits = manifest.get("audits")
    if isinstance(audits, dict):
        for k, v in audits.items():
            if isinstance(v, str) and v.strip().startswith("{"):
                problems.append("fast_path audit '%s' is a flow-style mapping — "
                                "use a block YAML skip-record (the stdlib fallback "
                                "parser mis-parses flow {})" % k)
            elif not isinstance(v, dict):
                problems.append("fast_path audit '%s' must be a block YAML "
                                "skip-record {skipped, reason, localization, "
                                "taxonomy_version}" % k)
            elif not v:
                problems.append("fast_path audit '%s' is an empty mapping — use a "
                                "block YAML skip-record {skipped, reason, "
                                "localization, taxonomy_version}" % k)
            else:
                if v.get("skipped") is not True:
                    problems.append("fast_path audit '%s' skip-record must set "
                                    "skipped: true" % k)
                for f in ("reason", "localization", "taxonomy_version"):
                    if v.get(f) in (None, ""):
                        problems.append("fast_path audit '%s' skip-record missing "
                                        "'%s'" % (k, f))

    # Containment (CR4-6): the write literal + every *_ref.
    pre_ref = fp.get("pre_eval_ref")
    loc_ref = fp.get("localization_ref")
    tax_ref = fp.get("taxonomy_ref")
    if write_literal is not None:
        problems.extend(_containment_problems(
            "fast_path write target", write_literal, repo_root, must_exist=True))
    for label, ref in (("fast_path.pre_eval_ref", pre_ref),
                       ("fast_path.localization_ref", loc_ref),
                       ("fast_path.taxonomy_ref", tax_ref)):
        if ref in (None, ""):
            problems.append("%s is required on a fast_path manifest" % label)
        else:
            problems.extend(_containment_problems(
                label, str(ref), repo_root, must_exist=True,
                require_committed=True))

    # Cross-artifact binding (AC-13 / CR2-3).
    tax = _sibling("compound-v-taxonomy.py")
    rec = art = None
    if pre_ref:
        rec, err = _read_json_file(repo_root, str(pre_ref))
        if rec is None:
            problems.append("fast_path pinned pre-eval record '%s' unreadable "
                            "(%s) — fail-closed" % (pre_ref, err))
    if loc_ref:
        art, err = _read_json_file(repo_root, str(loc_ref))
        if art is None:
            problems.append("fast_path localization artifact '%s' unreadable "
                            "(%s) — fail-closed" % (loc_ref, err))

    def _rp0(obj):
        if isinstance(obj, dict):
            rp = obj.get("resolved_paths")
            if isinstance(rp, list) and rp:
                return str(rp[0])
        return None

    art_rp0 = _rp0(art)
    rec_loc = rec.get("localization") if isinstance(rec, dict) else None
    rec_rp0 = _rp0(rec_loc)
    if write_literal is not None and art_rp0 is not None and write_literal != art_rp0:
        problems.append("fast_path binding: sole write_allowed '%s' != "
                        "localization.resolved_paths[0] '%s' (AC-13)"
                        % (write_literal, art_rp0))
    if art_rp0 is not None and rec_rp0 is not None and art_rp0 != rec_rp0:
        problems.append("fast_path binding: localization resolved_paths[0] differs "
                        "between artifact '%s' and record '%s'"
                        % (art_rp0, rec_rp0))
    if isinstance(rec, dict) and str(fp.get("pre_eval_id")) != str(rec.get("pre_eval_id")):
        problems.append("fast_path binding: manifest pre_eval_id '%s' != record "
                        "pre_eval_id '%s' (AC-13)"
                        % (fp.get("pre_eval_id"), rec.get("pre_eval_id")))
    if isinstance(rec, dict) and str(rec.get("decision")) != "FASTPATH_ELIGIBLE":
        problems.append("fast_path binding: pinned record decision '%s' is not "
                        "FASTPATH_ELIGIBLE (AC-13)" % rec.get("decision"))

    # CRIT-2: the pinned pre-eval record must (a) carry a VALID self-digest and
    # (b) fully satisfy the FASTPATH_ELIGIBLE contract — a null Layer-A override
    # and BOTH axes at band 'low' (not merely "not high"). A tampered record (any
    # digest mismatch, a fired override, or a non-low band) MUST fail closed, so a
    # FULL_PIPELINE record with `decision` flipped to FASTPATH_ELIGIBLE and a
    # medium band cannot be replayed as fast-path eligible (CR5-6/CR5-7).
    if isinstance(rec, dict):
        # (a) self-digest — REQUIRED + verified with the SHARED primitive the
        #     producer used (compound-v-taxonomy.record_digest).
        rec_dig = rec.get("digest")
        if not isinstance(rec_dig, str) or not rec_dig:
            problems.append("fast_path binding: pinned pre-eval record '%s' is "
                            "missing its self-digest — cannot verify integrity "
                            "(fail-closed, CR5-6)" % pre_ref)
        elif tax is None:
            problems.append("fast_path binding: shared taxonomy digest primitive "
                            "unavailable — cannot verify pre-eval record "
                            "self-digest (fail-closed)")
        else:
            try:
                if tax.record_digest(rec, exclude_field="digest") != rec_dig:
                    problems.append("fast_path binding: pinned pre-eval record "
                                    "'%s' self-digest mismatch — the record was "
                                    "tampered (fail-closed, CR5-6)" % pre_ref)
            except Exception as e:  # noqa: BLE001
                problems.append("fast_path binding: cannot recompute pre-eval "
                                "record self-digest (%s) — fail-closed" % e)
        # (b) FASTPATH_ELIGIBLE contract: a fired override forces FULL_PIPELINE.
        if rec.get("override_fired") is not None:
            problems.append("fast_path binding: pinned record override_fired=%r is "
                            "set — a fired Layer-A override forces FULL_PIPELINE, "
                            "not fast-path (fail-closed, CR5-6)"
                            % rec.get("override_fired"))
        # (b) BOTH difficulty + impact must be band 'low' (Iron-Invariant #2).
        for axis in ("difficulty", "impact"):
            ax = rec.get(axis)
            band = ax.get("band") if isinstance(ax, dict) else None
            if band != "low":
                problems.append("fast_path binding: pinned record %s.band '%s' is "
                                "not 'low' — only a low/low request is fast-path "
                                "eligible (fail-closed, CR5-6)" % (axis, band))

    m_taxd = fp.get("taxonomy_digest")
    if isinstance(rec, dict) and str(m_taxd) != str(rec.get("taxonomy_digest")):
        problems.append("fast_path binding: manifest taxonomy_digest '%s' != "
                        "record taxonomy_digest '%s' (AC-13)"
                        % (m_taxd, rec.get("taxonomy_digest")))
    if tax is not None and isinstance(rec_loc, dict) and isinstance(art, dict):
        try:
            d_rec = tax.record_digest(rec_loc, exclude_field="digest")
            d_art = tax.record_digest(art, exclude_field="digest")
            if d_rec != d_art:
                problems.append("fast_path binding: localization content-digest "
                                "differs between record and artifact (AC-13)")
            # MED-8: the localization content-digest (the artifact's self-digest)
            # MUST be present AND well-shaped before it can be compared — a missing
            # or non-'sha256:<hex>' digest previously slipped through silently.
            art_dig = art.get("digest")
            if not _is_digest_shaped(art_dig):
                problems.append("fast_path binding: localization artifact "
                                "content-digest is missing or malformed "
                                "(expected 'sha256:<64-hex>') — absence/wrong-shape "
                                "fails closed (AC-13)")
            elif art_dig != d_art:
                problems.append("fast_path binding: localization artifact "
                                "self-digest mismatch")
        except Exception as e:  # noqa: BLE001
            problems.append("fast_path binding: cannot compute localization "
                            "content-digest (%s) — fail-closed" % e)

    # Taxonomy classification denylist against the PINNED snapshot.
    if tax is not None and tax_ref:
        tax_full = os.path.join(repo_root, str(tax_ref))
        try:
            snap_digest = tax.taxonomy_digest_file(tax_full)
            if m_taxd is not None and str(m_taxd) != str(snap_digest):
                problems.append("fast_path binding: manifest taxonomy_digest '%s' "
                                "!= snapshot content-address '%s' (AC-13)"
                                % (m_taxd, snap_digest))
        except Exception:  # noqa: BLE001 - containment already reports absence
            pass
        loaded = None
        try:
            loaded = tax.load_taxonomy(path=tax_full)
        except Exception as e:  # noqa: BLE001
            problems.append("fast_path taxonomy snapshot '%s' unreadable/malformed "
                            "(%s) — fail-closed" % (tax_ref, e))
        if loaded is not None and write_literal is not None and _seg_is_literal(write_literal):
            cls = tax.classify(loaded, path=write_literal)
            if cls.get("sensitive"):
                problems.append("fast_path write target '%s' is a sensitive path "
                                "per the pinned taxonomy — not fast-path eligible"
                                % write_literal)
            if str(cls.get("impact_band")) == "high":
                problems.append("fast_path write target '%s' classifies as "
                                "high-impact per the pinned taxonomy — not "
                                "fast-path eligible" % write_literal)
            churn = loaded.get("churn") or {}
            for g in churn.get("exclude_paths", []):
                if glob_match(write_literal, str(g)):
                    problems.append("fast_path write target '%s' is a "
                                    "generated/vendored path (churn exclude '%s') "
                                    "— not fast-path eligible" % (write_literal, g))
                    break

    # Mode-specific: review declaration + receipt handling.
    stance = manifest.get("routing_stance") or "balanced"
    run_id = manifest.get("run_id")
    receipt_full = receipt_path or os.path.join(
        repo_root, _EXEC_DIR, str(run_id), _RECEIPT_SUBPATH)
    if receipt_path is None:
        try:
            receipt_rel = os.path.relpath(receipt_full, repo_root)
        except Exception:  # noqa: BLE001
            receipt_rel = receipt_full
    else:
        receipt_rel = receipt_path

    if mode == "pre-dispatch":
        decl_problems, _ = _review_resolution(fp.get("review"), stance, repo_root, config_path)
        problems.extend(decl_problems)
        if os.path.lexists(receipt_full):
            problems.append("fast_path --mode pre-dispatch forbids a review "
                            "receipt, but one exists at '%s' (it cannot exist "
                            "before review)" % receipt_rel)
    elif mode == "post-review":
        decl_problems, resolved_model = _review_resolution(
            fp.get("review"), stance, repo_root, config_path)
        problems.extend(decl_problems)
        sole_job_id = job0.get("id") if isinstance(job0, dict) else None
        problems.extend(_validate_receipt(
            receipt_full, receipt_rel, manifest, fp, resolved_model,
            repo_root, manifest_bytes, sole_job_id, diff_root=diff_root,
            expected_attempt=expected_attempt))

    return problems


def validate(manifest, mode=None, repo_root=None, config_path=None,
             receipt_path=None, manifest_bytes=None, diff_root=None,
             expected_attempt=None):
    """Return a list of violation strings; empty list means valid.

    ``mode``/``repo_root``/``config_path``/``receipt_path``/``diff_root`` drive the
    v2.9 conditional fast-path checks (only when a top-level ``fast_path`` block is
    present); a legacy manifest ignores them entirely (backward compatible).
    ``diff_root`` (CR-CRIT-1) is the worker's linked worktree the producer hashed;
    the post-review final-diff recompute runs there, falling back to ``repo_root``
    only when it is unset."""
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

        # xhigh ⇒ codex only: `effort: xhigh` is valid iff `backend: codex`
        # (every other backend rejects it with a clear error naming the rule).
        if (effort_val is not None and str(effort_val).lower() == "xhigh"
                and str(job.get("backend", "")).lower() != "codex"):
            problems.append(
                "job '%s' has effort 'xhigh' with backend '%s': xhigh is "
                "codex-only (kernel: model_reasoning_effort); use high"
                % (jid, job.get("backend"))
            )

        wa = job.get("write_allowed")
        if wa is None:
            wa = []
        if not isinstance(wa, list):
            problems.append("job '%s' write_allowed is not a list" % jid)
            wa = []
        job_globs.append((jid, [str(g) for g in wa]))

        # Invariant 2: codex => worktree, antigravity => worktree, cursor => worktree,
        # devin => worktree, opencode => worktree. All five are EXTERNAL workers. Codex
        # has a kernel sandbox scoped to a directory; antigravity and cursor have NO
        # kernel write-confinement at all (antigravity runs with
        # --dangerously-skip-permissions; cursor's headless `-f` grants arbitrary
        # write+shell); devin has a live but Research-Preview `--sandbox` whose coverage
        # is unverified (treated as no-confinement for enforcement purposes, v1); opencode
        # has NO kernel write-confinement and defaults to allowing all operations. For all
        # five, worktree + git-diff is the ONLY file-scope enforcement that actually holds.
        # A non-worktree external worker cannot be deterministically attributed and is rejected.
        backend_lc = str(job.get("backend", "")).lower()
        if backend_lc in ("codex", "antigravity", "cursor", "devin", "opencode"):
            if str(job.get("isolation", "")).lower() != "worktree":
                problems.append(
                    "job '%s' uses backend %s but isolation is '%s' "
                    "(%s requires worktree)"
                    % (jid, backend_lc, job.get("isolation"), backend_lc)
                )

        # WORKER-ONLY enforcement: devin/opencode are lower-trust, opt-in
        # backends (see adapter-devin.md / adapter-opencode.md) meant for
        # IMPLEMENTER jobs only. A reviewer job routed to either would
        # silently satisfy the Review Gate's opus/deep guarantee through a
        # low-trust external router instead of Claude Opus, defeating the
        # guarantee entirely. Reject unconditionally, independent of
        # tier/model — a reviewer job must never carry backend: devin or
        # backend: opencode, full stop.
        if _is_reviewer(job) and backend_lc in ("devin", "opencode"):
            problems.append(
                "reviewer job '%s' uses backend '%s' — devin/opencode are "
                "lower-trust, opt-in, WORKER-ONLY backends (see "
                "adapter-devin.md / adapter-opencode.md) and must never be "
                "used for a reviewer job; route reviewers to backend: "
                "claude with tier: deep or model: opus"
                % (jid, backend_lc)
            )

        # opencode provider/model shape: every EXPLICIT opencode model
        # override must be a genuine non-empty "provider/model" STRING (a
        # bare name would silently pass here but fail opencode's own model
        # resolution / the worker's `-m` argument at run time). Only checked
        # when a model key is actually present — a tier-only job resolves
        # through compound-v-resolve-model.py's own shape check at resolution
        # time. A NON-STRING model (int/list/dict from YAML) is itself a
        # violation: it can never be a valid provider/model string and must
        # NOT slip through by skipping the check.
        if backend_lc == "opencode" and "model" in job:
            m_val = job.get("model")
            _shaped = False
            if isinstance(m_val, str) and m_val.strip():
                _prov, _sep, _rest = m_val.partition("/")
                _shaped = bool(_sep) and bool(_prov.strip()) and bool(_rest.strip())
            if not _shaped:
                problems.append(
                    "job '%s' backend opencode has model %r which is not a "
                    "valid 'provider/model' string (must be a non-empty "
                    "string, non-empty on both sides of exactly one '/')"
                    % (jid, m_val)
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

        # v2.12 (B1): optional per-job advisor block — validate shape + reject on
        # advisor-ineligible job types (reviewer / docs / shared_foundation).
        problems.extend(_validate_advisor_block(job, jid))

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

    # v2.9 conditional fast-path: only engaged when a top-level `fast_path` block
    # is present (a legacy manifest is fully unaffected — backward compatible).
    if "fast_path" in manifest and manifest.get("fast_path") is not None:
        problems.extend(_validate_fast_path(
            manifest, manifest.get("fast_path"), mode, repo_root,
            config_path, receipt_path, manifest_bytes, diff_root=diff_root,
            expected_attempt=expected_attempt))

    return problems


def validate_text(text, mode=None, repo_root=None, config_path=None,
                  receipt_path=None, manifest_bytes=None, diff_root=None,
                  expected_attempt=None):
    data = load_yaml(text)
    # The manifest_digest binding (CR5-6) is computed over the manifest's raw
    # bytes. When a caller supplies the exact on-disk bytes (main() does), use
    # them verbatim; otherwise fall back to the UTF-8 encoding of the text.
    if manifest_bytes is None and isinstance(text, str):
        manifest_bytes = text.encode("utf-8")
    return validate(data, mode=mode, repo_root=repo_root,
                    config_path=config_path, receipt_path=receipt_path,
                    manifest_bytes=manifest_bytes, diff_root=diff_root,
                    expected_attempt=expected_attempt)


def _find_repo_root(start):
    """Walk up from ``start`` to the nearest dir containing ``.git`` (a dir OR a
    worktree ``.git`` file); fall back to the CWD when none is found."""
    d = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.getcwd()
        d = parent


def _get_opt(args, name):
    """Pop ``--name VALUE`` from a mutable args list; return VALUE or None."""
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            val = args[i + 1]
            del args[i:i + 2]
            return val
        del args[i:i + 1]
    return None


def main(argv):
    args = list(argv[1:])
    if "--selftest" in args:
        return _selftest()
    mode = _get_opt(args, "--mode")
    repo_root = _get_opt(args, "--repo-root")
    config_path = _get_opt(args, "--config")
    receipt_path = _get_opt(args, "--receipt")
    # CRIT-1: the worker's linked worktree — the checkout the producer hashed the
    # final diff in. The post-review recompute runs there; absent ⇒ repo_root.
    diff_root = _get_opt(args, "--worktree")
    # HIGH-1(b): the CURRENT review attempt (the caller reads it from the run's
    # state.json). When supplied, the post-review receipt's attempt_id MUST equal it —
    # a stale prior-attempt receipt cannot be replayed against a newer attempt.
    expected_attempt = _get_opt(args, "--expected-attempt")
    if expected_attempt is not None:
        try:
            expected_attempt = int(expected_attempt)
        except (TypeError, ValueError):
            print("error: --expected-attempt must be an integer", file=sys.stderr)
            return 2
    # Drop any remaining flags; the first non-flag token is the manifest path.
    positional = [a for a in args if not a.startswith("--")]
    if not positional:
        print("usage: compound-v-validate-manifest.py [--mode pre-dispatch|"
              "post-review] [--repo-root DIR] [--worktree DIR] [--config FILE] "
              "[--receipt FILE] [--expected-attempt N] <manifest.yaml>",
              file=sys.stderr)
        return 2
    if mode is not None and mode not in FASTPATH_MODES:
        print("error: --mode '%s' invalid (expected one of %s)"
              % (mode, ", ".join(FASTPATH_MODES)), file=sys.stderr)
        return 2
    path = positional[0]
    if not os.path.isfile(path):
        print("error: not a file: %s" % path, file=sys.stderr)
        return 2
    if repo_root is None:
        repo_root = _find_repo_root(os.path.dirname(os.path.abspath(path)))
    # Read the RAW bytes so the manifest_digest binding (CR5-6) content-addresses
    # to exactly what the producer digested; decode for YAML parsing separately.
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        print(json.dumps({"verdict": "error", "error": "manifest is not UTF-8 "
                          "(%s)" % e}), file=sys.stderr)
        return 2
    try:
        problems = validate_text(text, mode=mode, repo_root=repo_root,
                                 config_path=config_path,
                                 receipt_path=receipt_path,
                                 manifest_bytes=raw, diff_root=diff_root,
                                 expected_attempt=expected_attempt)
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


# A complete, fully-VALID manifest: a codex job with effort: xhigh (xhigh is
# valid iff backend: codex — this is the accept direction of that rule).
XHIGH_CODEX_MANIFEST = """
run_id: 2026-07-11-xhigh-ok
feature: "xhigh-ok"
spec_path: docs/superpowers/specs/2026-07-11-xhigh-ok.md
plan_path: docs/superpowers/plans/2026-07-11-xhigh-ok.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-11-xhigh-ok.md
  domain: docs/superpowers/expert/2026-07-11-xhigh-ok.md
  library: docs/superpowers/library-audit/2026-07-11-xhigh-ok.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-codex-xhigh
    title: "codex xhigh slice"
    type: large_isolated
    backend: codex
    tier: deep
    effort: xhigh
    isolation: worktree
    run: parallel
    write_allowed: [src/features/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""

# A complete manifest whose ONE defect is effort: xhigh on a NON-codex backend
# (the reject direction: xhigh is codex-only).
XHIGH_CLAUDE_MANIFEST = """
run_id: 2026-07-11-xhigh-bad
feature: "xhigh-bad"
spec_path: docs/superpowers/specs/2026-07-11-xhigh-bad.md
plan_path: docs/superpowers/plans/2026-07-11-xhigh-bad.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-11-xhigh-bad.md
  domain: docs/superpowers/expert/2026-07-11-xhigh-bad.md
  library: docs/superpowers/library-audit/2026-07-11-xhigh-bad.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-claude-xhigh
    title: "claude xhigh slice"
    type: core_slice
    backend: claude
    tier: deep
    effort: xhigh
    isolation: worktree
    run: parallel
    write_allowed: [src/features/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A complete, otherwise-valid manifest whose ONE defect is an antigravity job with
# isolation: direct (an external no-kernel-sandbox worker MUST be worktree-isolated).
# Uses run: serial so the ONLY violation is the antigravity⇒worktree invariant (not
# the parallel⇒worktree one).
ANTIGRAVITY_DIRECT_MANIFEST = """
run_id: 2026-06-27-agy
feature: "agy"
spec_path: docs/superpowers/specs/2026-06-27-agy.md
plan_path: docs/superpowers/plans/2026-06-27-agy.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-27-agy.md
  domain: docs/superpowers/expert/2026-06-27-agy.md
  library: docs/superpowers/library-audit/2026-06-27-agy.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-agy
    title: "antigravity slice"
    type: large_isolated
    backend: antigravity
    tier: standard
    isolation: direct
    run: serial
    write_allowed: [src/agy/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A complete, otherwise-valid manifest whose ONE defect is a devin job with
# isolation: direct (devin's --sandbox is Research-Preview and unverified for this
# plugin's purposes, so it is treated as no-confinement like antigravity/cursor and
# MUST be worktree-isolated).
DEVIN_DIRECT_MANIFEST = """
run_id: 2026-07-13-devin
feature: "devin"
spec_path: docs/superpowers/specs/2026-07-13-devin.md
plan_path: docs/superpowers/plans/2026-07-13-devin.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-devin.md
  domain: docs/superpowers/expert/2026-07-13-devin.md
  library: docs/superpowers/library-audit/2026-07-13-devin.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-devin
    title: "devin slice"
    type: large_isolated
    backend: devin
    tier: standard
    isolation: direct
    run: serial
    write_allowed: [src/devin/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A complete, VALID manifest with a single devin job, worktree-isolated -- confirms
# "devin" is accepted end-to-end (VALID_BACKENDS + the worktree invariant) once it is
# NOT paired with isolation: direct.
DEVIN_WORKTREE_MANIFEST = """
run_id: 2026-07-13-devin-ok
feature: "devin-ok"
spec_path: docs/superpowers/specs/2026-07-13-devin-ok.md
plan_path: docs/superpowers/plans/2026-07-13-devin-ok.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-devin-ok.md
  domain: docs/superpowers/expert/2026-07-13-devin-ok.md
  library: docs/superpowers/library-audit/2026-07-13-devin-ok.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-devin-ok
    title: "devin slice"
    type: large_isolated
    backend: devin
    tier: standard
    isolation: worktree
    run: serial
    write_allowed: [src/devin/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A complete, otherwise-valid manifest whose ONE defect is an opencode job with
# isolation: direct (opencode has NO kernel write-confinement and defaults to
# allowing all operations, so worktree isolation is REQUIRED).
OPENCODE_DIRECT_MANIFEST = """
run_id: 2026-07-13-opencode
feature: "opencode"
spec_path: docs/superpowers/specs/2026-07-13-opencode.md
plan_path: docs/superpowers/plans/2026-07-13-opencode.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode.md
  domain: docs/superpowers/expert/2026-07-13-opencode.md
  library: docs/superpowers/library-audit/2026-07-13-opencode.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    tier: standard
    isolation: direct
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A complete, VALID manifest with a single opencode job, worktree-isolated -- confirms
# "opencode" is accepted end-to-end (VALID_BACKENDS + the worktree invariant) once it
# is NOT paired with isolation: direct. model is a genuine "provider/model" string,
# matching the resolver's opencode convention.
OPENCODE_WORKTREE_MANIFEST = """
run_id: 2026-07-13-opencode-ok
feature: "opencode-ok"
spec_path: docs/superpowers/specs/2026-07-13-opencode-ok.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-ok.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-ok.md
  domain: docs/superpowers/expert/2026-07-13-opencode-ok.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-ok.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-ok
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: "anthropic/claude-sonnet-4-6"
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A complete, otherwise-valid manifest whose ONE defect is a REVIEWER job routed to
# backend: devin. devin/opencode are lower-trust, opt-in, WORKER-ONLY backends (see
# adapter-devin.md / adapter-opencode.md) -- a reviewer job must never resolve its
# Review-Gate opus/deep guarantee through a low-trust external router. tier: deep +
# isolation: worktree are otherwise satisfied, so ONLY the WORKER-ONLY violation fires.
DEVIN_REVIEWER_MANIFEST = """
run_id: 2026-07-13-devin-reviewer
feature: "devin-reviewer"
spec_path: docs/superpowers/specs/2026-07-13-devin-reviewer.md
plan_path: docs/superpowers/plans/2026-07-13-devin-reviewer.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-devin-reviewer.md
  domain: docs/superpowers/expert/2026-07-13-devin-reviewer.md
  library: docs/superpowers/library-audit/2026-07-13-devin-reviewer.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-spec-review
    title: "spec review pass"
    type: spec_review
    backend: devin
    tier: deep
    isolation: worktree
    run: serial
    write_allowed: []
    read_allowed: [src/**]
    acceptance: ["reviewed"]
"""


# Same defect, opencode backend (same rationale as DEVIN_REVIEWER_MANIFEST above).
OPENCODE_REVIEWER_MANIFEST = """
run_id: 2026-07-13-opencode-reviewer
feature: "opencode-reviewer"
spec_path: docs/superpowers/specs/2026-07-13-opencode-reviewer.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-reviewer.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-reviewer.md
  domain: docs/superpowers/expert/2026-07-13-opencode-reviewer.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-reviewer.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-quality-review
    title: "quality review pass"
    type: quality_review
    backend: opencode
    tier: deep
    isolation: worktree
    run: serial
    write_allowed: []
    read_allowed: [src/**]
    acceptance: ["reviewed"]
"""


# A complete, otherwise-valid manifest whose ONE defect is an opencode job with a BARE
# (slash-less) explicit model override. opencode addresses models as a "provider/model"
# string with no single-vendor default (see adapter-opencode.md); a bare name would
# silently pass a naive validator but fail opencode's own model resolution / the
# worker's `-m` argument at run time, so it must be rejected here, before dispatch.
OPENCODE_BARE_MODEL_MANIFEST = """
run_id: 2026-07-13-opencode-bare-model
feature: "opencode-bare-model"
spec_path: docs/superpowers/specs/2026-07-13-opencode-bare-model.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-bare-model.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-bare-model.md
  domain: docs/superpowers/expert/2026-07-13-opencode-bare-model.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-bare-model.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-bare
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: "gpt-5.6"
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# Same defect, malformed shape variant: a trailing slash with an EMPTY model half
# ("anthropic/") — the '/' is present but one side is empty, still not a valid
# provider/model pair.
OPENCODE_MALFORMED_MODEL_MANIFEST = """
run_id: 2026-07-13-opencode-malformed-model
feature: "opencode-malformed-model"
spec_path: docs/superpowers/specs/2026-07-13-opencode-malformed-model.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-malformed-model.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-malformed-model.md
  domain: docs/superpowers/expert/2026-07-13-opencode-malformed-model.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-malformed-model.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-malformed
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: "anthropic/"
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A family of opencode jobs whose explicit `model` is a NON-STRING (int / inline list
# / inline mapping). A non-string can never be a valid 'provider/model' string, and the
# shape check must NOT skip it (an earlier version only ran the check for str models, so
# a `model: 42` slipped through with zero violations). Each carries `tier: standard` so
# the model override is present-but-invalid without also tripping the model-or-tier
# requirement — isolating the shape violation as the guaranteed one.
OPENCODE_INT_MODEL_MANIFEST = """
run_id: 2026-07-13-opencode-int-model
feature: "opencode-int-model"
spec_path: docs/superpowers/specs/2026-07-13-opencode-int-model.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-int-model.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-int-model.md
  domain: docs/superpowers/expert/2026-07-13-opencode-int-model.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-int-model.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-int
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: 42
    tier: standard
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


OPENCODE_LIST_MODEL_MANIFEST = """
run_id: 2026-07-13-opencode-list-model
feature: "opencode-list-model"
spec_path: docs/superpowers/specs/2026-07-13-opencode-list-model.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-list-model.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-list-model.md
  domain: docs/superpowers/expert/2026-07-13-opencode-list-model.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-list-model.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-list
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: ["anthropic/claude-opus-4-6"]
    tier: standard
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


OPENCODE_DICT_MODEL_MANIFEST = """
run_id: 2026-07-13-opencode-dict-model
feature: "opencode-dict-model"
spec_path: docs/superpowers/specs/2026-07-13-opencode-dict-model.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-dict-model.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-dict-model.md
  domain: docs/superpowers/expert/2026-07-13-opencode-dict-model.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-dict-model.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-dict
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: {}
    tier: standard
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""

# v2.12 (B1): optional per-job advisor block. An eligible (standard-tier
# bounded_crud implementer) job carrying a well-formed advisor block is VALID.
ADVISOR_GOOD_MANIFEST = """
run_id: 2026-07-13-advisor-good
feature: "advisor-good"
spec_path: docs/superpowers/specs/2026-07-13-advisor-good.md
plan_path: docs/superpowers/plans/2026-07-13-advisor-good.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-advisor-good.md
  domain: docs/superpowers/expert/2026-07-13-advisor-good.md
  library: docs/superpowers/library-audit/2026-07-13-advisor-good.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-crud
    title: "crud slice with advisor"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    write_allowed: [src/features/api/**]
    read_allowed: [src/**]
    acceptance: ["crud"]
    advisor:
      enabled: true
      advisor_backend: codex
"""

# Advisor block on advisor-INELIGIBLE job types (review + docs + shared_foundation)
# — each must be rejected.
ADVISOR_INELIGIBLE_MANIFEST = """
run_id: 2026-07-13-advisor-ineligible
feature: "advisor-ineligible"
spec_path: docs/superpowers/specs/2026-07-13-advisor-ineligible.md
plan_path: docs/superpowers/plans/2026-07-13-advisor-ineligible.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-advisor-ineligible.md
  domain: docs/superpowers/expert/2026-07-13-advisor-ineligible.md
  library: docs/superpowers/library-audit/2026-07-13-advisor-ineligible.md
routing_stance: balanced
max_parallel: 2
jobs:
  - id: task-0-foundation
    title: "shared foundation with advisor"
    type: shared_foundation
    backend: claude
    tier: deep
    isolation: direct
    run: serial
    write_allowed: [src/types/shared.ts]
    read_allowed: [src/**]
    acceptance: ["types"]
    advisor:
      enabled: true
  - id: task-1-docs
    title: "docs job with advisor"
    type: docs
    backend: claude
    tier: light
    isolation: worktree
    run: parallel
    write_allowed: [docs/x.md]
    read_allowed: [src/**]
    acceptance: ["documented"]
    advisor:
      enabled: true
  - id: task-2-spec-review
    title: "spec review gate with advisor"
    type: review
    backend: claude
    tier: deep
    isolation: worktree
    run: parallel
    write_allowed: [src/review/**]
    read_allowed: [src/**]
    acceptance: ["AC met"]
    advisor:
      enabled: true
"""

# Advisor block with a malformed SHAPE on an ELIGIBLE job — unknown key, a
# non-boolean enabled, and an unknown advisor_backend are each rejected.
ADVISOR_BAD_SHAPE_MANIFEST = """
run_id: 2026-07-13-advisor-bad-shape
feature: "advisor-bad-shape"
spec_path: docs/superpowers/specs/2026-07-13-advisor-bad-shape.md
plan_path: docs/superpowers/plans/2026-07-13-advisor-bad-shape.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-advisor-bad-shape.md
  domain: docs/superpowers/expert/2026-07-13-advisor-bad-shape.md
  library: docs/superpowers/library-audit/2026-07-13-advisor-bad-shape.md
routing_stance: balanced
max_parallel: 2
jobs:
  - id: task-1-crud
    title: "crud slice with malformed advisor"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    write_allowed: [src/features/api/**]
    read_allowed: [src/**]
    acceptance: ["crud"]
    advisor:
      enabled: "yes"
      advisor_backend: gemini
      bogus_key: 1
"""


# --------------------------------------------------------------------------- #
# v2.9 fast-path self-test — builds on-disk fixtures in a temp repo root so the
# containment + cross-artifact-binding checks exercise real files. Digests are
# computed via the SHARED compound-v-taxonomy primitives (record_digest /
# taxonomy_digest_bytes) so a producer (M1) and this consumer can never diverge.
# --------------------------------------------------------------------------- #
def _fp_taxonomy_bytes():
    """The example taxonomy shipped with the plugin (a valid snapshot to test
    classification against)."""
    here = os.path.dirname(os.path.abspath(__file__))
    example = os.path.join(os.path.dirname(here),
                           ".claude", "compound-v-impact-taxonomy.example.yaml")
    with open(example, "rb") as fh:
        return fh.read()


def _fp_write(root, rel, data):
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    kw = {} if isinstance(data, bytes) else {"encoding": "utf-8"}
    with open(full, mode, **kw) as fh:
        fh.write(data)
    return full


def _fp_build(root, tax_mod, **opts):
    """Materialize a fast-path fixture under ``root``; return the manifest text.

    Knobs (all default to the VALID shape): write_path, resolved_path,
    record_decision, manifest_tax_digest, record_tax_digest, artifact_fan_out,
    manifest_pre_eval_id, review (dict), audits_flow, second_job, glob_write,
    symlink_write, loc_ref, tax_ref, pre_ref, make_receipt (dict|None),
    receipt_rel, artifact_drop_digest (MED-8), artifact_bad_shape_digest (MED-8).
    """
    pre_eval_id = "2026-07-12T101500Z-make-button-red-a1b2"
    run_id = pre_eval_id
    write_path = opts.get("write_path", "src/components/button.css")
    resolved_path = opts.get("resolved_path", write_path)

    pre_ref = opts.get("pre_ref",
                       "docs/superpowers/pre-eval/%s.json" % pre_eval_id)
    loc_ref = opts.get("loc_ref",
                       "docs/superpowers/pre-eval/%s.localization.json" % pre_eval_id)
    tax_ref = opts.get(
        "tax_ref",
        "docs/superpowers/execution/%s/taxonomy-snapshot.yaml" % run_id)

    # Immutable taxonomy snapshot + its content-address digest (RAW bytes).
    tax_bytes = _fp_taxonomy_bytes()
    _fp_write(root, tax_ref, tax_bytes)
    real_tax_digest = tax_mod.taxonomy_digest_bytes(tax_bytes)
    manifest_tax_digest = opts.get("manifest_tax_digest", real_tax_digest)
    record_tax_digest = opts.get("record_tax_digest", real_tax_digest)

    # Localization object (embedded in the record) + standalone artifact w/ digest.
    localization = {
        "resolved_paths": [resolved_path],
        "fan_out": 1,
        "flags": [],
        "confidence": "exact",
    }
    artifact = dict(localization)
    artifact["fan_out"] = opts.get("artifact_fan_out", 1)
    artifact["digest"] = tax_mod.record_digest(artifact)
    if opts.get("artifact_drop_digest"):
        artifact.pop("digest", None)              # MED-8: absent content-digest
    elif opts.get("artifact_bad_shape_digest"):
        artifact["digest"] = "not-a-valid-digest"  # MED-8: wrong-shape digest
    _fp_write(root, loc_ref, json.dumps(artifact))

    record = {
        "pre_eval_id": pre_eval_id,
        "request_slug": "make-button-red",
        "ts": "2026-07-12T10:15:00Z",
        "status": "PRE_EVAL_DONE",
        "taxonomy_version": 1,
        "taxonomy_ref": tax_ref,
        "taxonomy_digest": record_tax_digest,
        "difficulty": {"band": opts.get("record_difficulty_band", "low")},
        "impact": {"band": opts.get("record_impact_band", "low")},
        "tiers_signalled": ["localization"],
        "localization": localization,
        "override_fired": opts.get("record_override_fired", None),
        "decision": opts.get("record_decision", "FASTPATH_ELIGIBLE"),
        "min_sample_status": "insufficient",
    }
    # A genuine record carries its own canonical-JSON self-digest (the producer
    # sets it via record_digest); a fast-path consumer verifies it (CR5-6/CR5-7).
    record["digest"] = tax_mod.record_digest(record, exclude_field="digest")
    if opts.get("record_bad_digest"):
        record["digest"] = "sha256:" + ("0" * 64)  # tamper: valid shape, wrong value
    elif opts.get("record_drop_digest"):
        record.pop("digest", None)
    _fp_write(root, pre_ref, json.dumps(record))

    # The write target: a real committed-looking regular file (or an escaping
    # symlink for the containment tamper case).
    if opts.get("symlink_write"):
        outside = os.path.join(root, "..", "outside-secret.css")
        with open(os.path.join(root, "outside-secret.css"), "w") as fh:
            fh.write("body{}\n")  # a sibling target the symlink escapes to
        link_full = os.path.join(root, write_path)
        os.makedirs(os.path.dirname(link_full), exist_ok=True)
        os.symlink(os.path.abspath(os.path.join(root, "outside-secret.css")),
                   link_full)
    elif not opts.get("skip_write_file"):
        _fp_write(root, write_path, "body{}\n")

    if opts.get("make_receipt") is not None:
        receipt_rel = opts.get(
            "receipt_rel",
            "docs/superpowers/execution/%s/review/receipt.json" % run_id)
        _fp_write(root, receipt_rel, json.dumps(opts["make_receipt"]))

    manifest_pre_eval_id = opts.get("manifest_pre_eval_id", pre_eval_id)
    review = opts.get("review", {"backend": "claude", "tier": "deep"})
    review_lines = "\n".join(
        "    %s: %s" % (k, v) for k, v in review.items())

    if opts.get("audits_flow"):
        audits_block = (
            "audits:\n"
            "  archaeology: {}\n"
            "  domain: {}\n"
            "  library: {}\n"
        )
    else:
        skip = ("    skipped: true\n"
                "    reason: fastpath\n"
                "    localization: %s\n"
                "    taxonomy_version: 1\n") % loc_ref
        audits_block = (
            "audits:\n"
            "  archaeology:\n" + skip +
            "  domain:\n" + skip +
            "  library:\n" + skip
        )

    write_glob = "src/**" if opts.get("glob_write") else write_path
    second = ""
    if opts.get("second_job"):
        second = (
            "  - id: task-2-extra\n"
            "    title: \"extra\"\n"
            "    type: docs\n"
            "    backend: claude\n"
            "    tier: standard\n"
            "    isolation: direct\n"
            "    run: serial\n"
            "    write_allowed: [docs/extra.md]\n"
            "    read_allowed: [src/**]\n"
            "    acceptance: [\"x\"]\n"
        )

    text = (
        "run_id: %s\n"
        "feature: \"make button red\"\n"
        "spec_path: docs/superpowers/execution/%s/spec-stub.md\n"
        "plan_path: docs/superpowers/execution/%s/plan-stub.md\n"
        "%s"
        "routing_stance: balanced\n"
        "max_parallel: 1\n"
        "acceptance_criteria:\n"
        "  - \"button is red\"\n"
        "fast_path:\n"
        "  eligible: true\n"
        "  pre_eval_id: %s\n"
        "  pre_eval_ref: %s\n"
        "  localization_ref: %s\n"
        "  taxonomy_ref: %s\n"
        "  taxonomy_digest: \"%s\"\n"
        "  review:\n"
        "%s\n"
        "jobs:\n"
        "  - id: task-1-button\n"
        "    title: \"make button red\"\n"
        "    type: bounded_crud\n"
        "    backend: claude\n"
        "    tier: standard\n"
        "    isolation: direct\n"
        "    run: serial\n"
        "    write_allowed: [%s]\n"
        "    read_allowed: [src/**]\n"
        "    acceptance: [\"button red\"]\n"
        "%s"
    ) % (run_id, run_id, run_id, audits_block, manifest_pre_eval_id, pre_ref,
         loc_ref, tax_ref, manifest_tax_digest, review_lines, write_glob, second)
    return text


def _fp_receipt(**over):
    r = {
        "run_id": "2026-07-12T101500Z-make-button-red-a1b2",
        "pre_eval_id": "2026-07-12T101500Z-make-button-red-a1b2",
        "manifest_digest": "sha256:" + ("a" * 64),
        "baseline_sha": "a" * 40,
        "final_diff_digest": "sha256:" + ("b" * 64),
        "reviewer_backend": "claude",
        "reviewer_model": "opus",
        "attempt_id": 1,
        "ts": "2026-07-12T10:20:00Z",
        "verdict": "approved",
        "integration_rationale": "single-job fast-path: no cross-job seams",
    }
    r.update(over)
    return r


_FP_RUN_ID = "2026-07-12T101500Z-make-button-red-a1b2"
_FP_JOB_ID = "task-1-button"
_FP_WRITE_PATH = "src/components/button.css"


def _fp_git_and_state(d, tax_mod, manifest_text):
    """Turn the fixture dir into a real git repo with a committed pre-launch
    baseline + one worker change, and write the run's state.json baseline — so
    the post-review receipt binding (manifest_digest / baseline_sha /
    final_diff_digest, CR5-6) can be recomputed against real git state. Returns
    the correct binding values (or None when git is unavailable)."""
    import subprocess

    def g(*a):
        return subprocess.run(["git", "-C", d] + list(a),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if g("init", "-q").returncode != 0:
        return None
    g("config", "user.email", "selftest@example.com")
    g("config", "user.name", "cv-selftest")
    g("config", "commit.gpgsign", "false")
    g("config", "core.hooksPath", "/dev/null")  # ignore any global hooks in CI
    g("add", "-A")
    if g("commit", "-q", "--no-verify", "-m", "baseline").returncode != 0:
        return None
    rp = g("rev-parse", "HEAD")
    if rp.returncode != 0:
        return None
    baseline = rp.stdout.decode("utf-8", "replace").strip()

    # One worker change to the sole write target → a non-empty tracked diff.
    with open(os.path.join(d, _FP_WRITE_PATH), "a", encoding="utf-8") as fh:
        fh.write("/* changed by worker */\n")
    diff = g("diff", "--no-color", baseline)
    if diff.returncode != 0:
        return None
    diff_bytes = diff.stdout or b""

    state = {"run_id": _FP_RUN_ID,
             "jobs": {_FP_JOB_ID: {"status": "success", "baseline": baseline}}}
    _fp_write(d, "docs/superpowers/execution/%s/state.json" % _FP_RUN_ID,
              json.dumps(state))
    return {
        "run_id": _FP_RUN_ID,
        "manifest_digest": tax_mod.taxonomy_digest_bytes(
            manifest_text.encode("utf-8")),
        "baseline_sha": baseline,
        "final_diff_digest": tax_mod.taxonomy_digest_bytes(diff_bytes),
        "receipt_rel": "docs/superpowers/execution/%s/review/receipt.json"
                       % _FP_RUN_ID,
    }


def _fp_git_worktree_and_state(d, tax_mod, manifest_text):
    """CRIT-1 topology: a MAIN repo (``repo_root``) holding the committed artifacts
    + state.json, and a SEPARATE linked WORKTREE (``diff_root``) holding the
    worker's file change. The producer hashes the final diff in the worktree, so
    the validator must recompute there — NOT in the main checkout. Returns
    (info, worktree_path) or (None, None) when git/worktree is unavailable."""
    import subprocess

    def g(cwd, *a):
        return subprocess.run(["git", "-C", cwd] + list(a),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if g(d, "init", "-q").returncode != 0:
        return None, None
    g(d, "config", "user.email", "selftest@example.com")
    g(d, "config", "user.name", "cv-selftest")
    g(d, "config", "commit.gpgsign", "false")
    g(d, "config", "core.hooksPath", "/dev/null")
    g(d, "add", "-A")
    if g(d, "commit", "-q", "--no-verify", "-m", "baseline").returncode != 0:
        return None, None
    rp = g(d, "rev-parse", "HEAD")
    if rp.returncode != 0:
        return None, None
    baseline = rp.stdout.decode("utf-8", "replace").strip()

    wt = d + "-wt"
    if g(d, "worktree", "add", "-q", "--detach", wt, baseline).returncode != 0:
        return None, None
    # The worker change lives ONLY in the linked worktree (the main tree is clean).
    with open(os.path.join(wt, _FP_WRITE_PATH), "a", encoding="utf-8") as fh:
        fh.write("/* changed by the worker in the linked worktree */\n")
    diff = g(wt, "diff", "--no-color", baseline)
    if diff.returncode != 0:
        return None, None
    diff_bytes = diff.stdout or b""

    state = {"run_id": _FP_RUN_ID,
             "jobs": {_FP_JOB_ID: {"status": "success", "baseline": baseline}}}
    _fp_write(d, "docs/superpowers/execution/%s/state.json" % _FP_RUN_ID,
              json.dumps(state))
    return ({
        "run_id": _FP_RUN_ID,
        "manifest_digest": tax_mod.taxonomy_digest_bytes(
            manifest_text.encode("utf-8")),
        "baseline_sha": baseline,
        "final_diff_digest": tax_mod.taxonomy_digest_bytes(diff_bytes),
        "receipt_rel": "docs/superpowers/execution/%s/review/receipt.json"
                       % _FP_RUN_ID,
    }, wt)


def _fp_write_receipt(d, tax_mod, info, drop=None, bad_digest=False, **over):
    """Write a post-review receipt bound to the real git state in ``info``.
    ``over`` mutates a field (the self-digest is recomputed AFTER, so exactly the
    overridden binding fails); ``bad_digest`` breaks the self-digest; ``drop``
    removes fields entirely."""
    receipt = {
        "run_id": _FP_RUN_ID,
        "pre_eval_id": _FP_RUN_ID,
        "manifest_digest": info["manifest_digest"],
        "baseline_sha": info["baseline_sha"],
        "final_diff_digest": info["final_diff_digest"],
        "reviewer_backend": "claude",
        "reviewer_model": "opus",
        "reviewer_tier": "deep",  # schema-required (fastpath-run R3 MED-6)
        # MED-6: bind to the diff-root by default (the repo root ``d`` — the diff-root
        # when no separate worktree is passed). The CRIT-1 worktree topology overrides
        # this via ``worktree=<wt>`` so it matches the linked worktree diff_root.
        "worktree": d,
        "attempt_id": 1,
        "ts": "2026-07-12T10:20:00Z",
        "verdict": "approved",
        "integration_rationale": "single-job fast-path: no cross-job seams",
    }
    receipt.update(over)
    for k in (drop or []):
        receipt.pop(k, None)
    if "digest" in (drop or []):
        pass  # intentionally absent
    elif bad_digest:
        receipt["digest"] = "sha256:" + ("e" * 64)
    else:
        receipt["digest"] = tax_mod.record_digest(receipt, exclude_field="digest")
    _fp_write(d, info["receipt_rel"], json.dumps(receipt))


def _selftest_fastpath(expect):
    import tempfile

    tax_mod = _sibling("compound-v-taxonomy.py")
    if tax_mod is None:
        expect("fastpath: shared taxonomy module loads", False)
        return

    base = tempfile.mkdtemp(prefix="cv-c1-fp-")

    def case(name):
        d = os.path.join(base, name)
        os.makedirs(d, exist_ok=True)
        return d

    # (a) minimal fast_path manifest validates under pre-dispatch.
    d = case("valid_predispatch")
    txt = _fp_build(d, tax_mod)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: valid manifest passes pre-dispatch (%r)" % res, res == [])

    # No-mode = fail-closed for a fast_path manifest.
    d = case("nomode")
    txt = _fp_build(d, tax_mod)
    res = validate_text(txt, mode=None, repo_root=d)
    expect("fastpath: no --mode is rejected (fail-closed)",
           any("mode" in p.lower() for p in res))

    # (b) a second jobs entry under fast_path fails.
    d = case("secondjob")
    txt = _fp_build(d, tax_mod, second_job=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: second job rejected",
           any("exactly ONE" in p for p in res))

    # (c) glob write_allowed under fast_path rejected; one literal path passes.
    d = case("globwrite")
    txt = _fp_build(d, tax_mod, glob_write=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: glob write_allowed rejected",
           any("LITERAL" in p for p in res))

    # (d) block-YAML skip-record validates; flow-{} rejected ("use block YAML").
    d = case("flowaudit")
    txt = _fp_build(d, tax_mod, audits_flow=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: flow-{} audit rejected (use block YAML)",
           any("block YAML" in p for p in res))
    # _mini_yaml nested-mapping fixture: the skip-record parses as a real mapping.
    parsed = _mini_yaml(_fp_build(case("miniyaml"), tax_mod))
    expect("fastpath: _mini_yaml parses nested skip-record mapping",
           isinstance(parsed.get("audits", {}).get("archaeology"), dict)
           and parsed["audits"]["archaeology"].get("skipped") is True)

    # (e) taxonomy classification: a sensitive write target is rejected.
    d = case("sensitive")
    txt = _fp_build(d, tax_mod, write_path="src/auth/login.css",
                    resolved_path="src/auth/login.css")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: sensitive-path write target rejected",
           any("sensitive" in p for p in res))
    # unreadable taxonomy snapshot -> fail-closed.
    d = case("badtax")
    txt = _fp_build(d, tax_mod)
    os.remove(os.path.join(
        d, "docs/superpowers/execution/2026-07-12T101500Z-make-button-red-a1b2/"
        "taxonomy-snapshot.yaml"))
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: unreadable taxonomy snapshot fails closed",
           any("taxonomy" in p.lower() and ("unreadable" in p or "does not exist"
               in p or "not a regular file" in p) for p in res))

    # (f) cross-artifact binding tampering — every mismatched field fails.
    d = case("tamper_path")
    _fp_write(d, "src/components/other.css", "body{}\n")
    txt = _fp_build(d, tax_mod, write_path="src/components/other.css",
                    resolved_path="src/components/button.css")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: write literal != resolved_paths[0] rejected",
           any("resolved_paths[0]" in p for p in res))

    d = case("tamper_preid")
    txt = _fp_build(d, tax_mod, manifest_pre_eval_id="2026-07-12T101500Z-evil-9999")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pre_eval_id mismatch rejected",
           any("pre_eval_id" in p for p in res))

    d = case("tamper_decision")
    txt = _fp_build(d, tax_mod, record_decision="FULL_PIPELINE")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: non-FASTPATH_ELIGIBLE record rejected",
           any("FASTPATH_ELIGIBLE" in p for p in res))

    # CRIT-2: pinned pre-eval record self-digest + FASTPATH_ELIGIBLE band gate.
    d = case("tamper_rec_selfdigest")
    txt = _fp_build(d, tax_mod, record_bad_digest=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pre-eval record self-digest mismatch rejected",
           any("record" in p and "self-digest" in p for p in res))

    d = case("tamper_rec_missing_digest")
    txt = _fp_build(d, tax_mod, record_drop_digest=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pre-eval record missing self-digest rejected",
           any("record" in p and "self-digest" in p for p in res))

    # A FULL_PIPELINE record whose decision is flipped to FASTPATH_ELIGIBLE with a
    # MEDIUM band (and a freshly-VALID self-digest) MUST still fail on the band gate.
    d = case("tamper_rec_medium_band")
    txt = _fp_build(d, tax_mod, record_impact_band="medium")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pinned record impact.band=medium rejected (not low)",
           any("impact.band" in p and "not 'low'" in p for p in res))

    d = case("tamper_rec_diff_band")
    txt = _fp_build(d, tax_mod, record_difficulty_band="high")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pinned record difficulty.band=high rejected (not low)",
           any("difficulty.band" in p and "not 'low'" in p for p in res))

    d = case("tamper_rec_override")
    txt = _fp_build(d, tax_mod, record_override_fired=3)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pinned record override_fired set rejected",
           any("override_fired" in p for p in res))

    d = case("tamper_taxdigest")
    txt = _fp_build(d, tax_mod, manifest_tax_digest="sha256:" + ("0" * 64))
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: taxonomy_digest mismatch rejected",
           any("taxonomy_digest" in p for p in res))

    d = case("tamper_locdigest")
    txt = _fp_build(d, tax_mod, artifact_fan_out=99)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: localization content-digest mismatch rejected",
           any("localization" in p and "digest" in p for p in res))

    # MED-8: a MISSING localization-artifact content-digest previously slipped
    # through (only a present string was compared); absence must fail closed.
    d = case("med8_loc_missing_digest")
    txt = _fp_build(d, tax_mod, artifact_drop_digest=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath MED-8: localization artifact missing content-digest "
           "rejected (absence fails closed)",
           any("localization artifact content-digest is missing" in p
               for p in res))

    # MED-8: a wrong-SHAPE localization-artifact digest also fails closed.
    d = case("med8_loc_badshape_digest")
    txt = _fp_build(d, tax_mod, artifact_bad_shape_digest=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath MED-8: localization artifact malformed content-digest "
           "rejected (wrong shape fails closed)",
           any("missing or malformed" in p for p in res))

    # (g) two validation modes.
    d = case("declined_backend")
    txt = _fp_build(d, tax_mod, review={"backend": "codex", "tier": "deep"})
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: review backend != claude rejected",
           any("claude" in p and "review" in p.lower() for p in res))

    d = case("review_no_deep_no_opus")
    txt = _fp_build(d, tax_mod, review={"backend": "claude", "tier": "standard"})
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: review claude+standard (not deep/opus) rejected",
           any("deep" in p or "opus" in p for p in res))

    # pre-dispatch forbids a receipt.
    d = case("predispatch_receipt")
    txt = _fp_build(d, tax_mod, make_receipt=_fp_receipt())
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pre-dispatch forbids an existing receipt",
           any("forbid" in p or "receipt" in p for p in res))

    # post-review requires + FULLY verifies the receipt (CR5-6). Real git repo so
    # manifest_digest / baseline_sha / final_diff_digest are recomputable; a stale
    # or mismatched binding, or a non-approved verdict, MUST fail closed.
    import shutil as _shutil
    if _shutil.which("git") is not None:
        def _postreview(name, drop=None, bad_digest=False, **over):
            d = case(name)
            txt = _fp_build(d, tax_mod)
            info = _fp_git_and_state(d, tax_mod, txt)
            if info is None:
                return None, d
            _fp_write_receipt(d, tax_mod, info, drop=drop,
                              bad_digest=bad_digest, **over)
            return validate_text(txt, mode="post-review", repo_root=d), d

        res, _ = _postreview("postreview_ok")
        expect("fastpath: post-review with a fully-bound receipt passes (%r)"
               % res, res == [])

        res, _ = _postreview("postreview_badbackend", reviewer_backend="codex")
        expect("fastpath: receipt reviewer_backend != claude rejected",
               res is not None and any("claude" in p for p in res))

        res, _ = _postreview("postreview_badmodel", reviewer_model="sonnet")
        expect("fastpath: receipt reviewer_model not Opus rejected",
               res is not None and any(
                   "opus" in p.lower() or "resolved" in p.lower() for p in res))

        res, _ = _postreview("postreview_verdict_issues", verdict="issues")
        expect("fastpath: receipt verdict 'issues' rejected",
               res is not None and any(
                   "verdict" in p.lower() and "approved" in p.lower()
                   for p in res))

        res, _ = _postreview("postreview_verdict_absent", drop=["verdict"])
        expect("fastpath: receipt with absent verdict rejected",
               res is not None and any("verdict" in p.lower() for p in res))

        res, _ = _postreview("postreview_bad_manifest_digest",
                             manifest_digest="sha256:" + ("0" * 64))
        expect("fastpath: receipt manifest_digest mismatch rejected "
               "(stale/wrong manifest)",
               res is not None and any("manifest_digest" in p for p in res))

        res, _ = _postreview("postreview_bad_baseline", baseline_sha="f" * 40)
        expect("fastpath: receipt baseline_sha mismatch rejected",
               res is not None and any(
                   "baseline" in p.lower() and "!=" in p for p in res))

        res, _ = _postreview("postreview_stale_diff",
                             final_diff_digest="sha256:" + ("0" * 64))
        expect("fastpath: receipt final_diff_digest mismatch rejected "
               "(stale-replay)",
               res is not None and any("final_diff_digest" in p for p in res))

        res, _ = _postreview("postreview_bad_selfdigest", bad_digest=True)
        expect("fastpath: receipt self-digest mismatch rejected",
               res is not None and any(
                   "receipt self-digest" in p.lower() for p in res))

        res, _ = _postreview("postreview_missing_selfdigest", drop=["digest"])
        expect("fastpath: receipt missing self-digest rejected",
               res is not None and any(
                   "missing its self-digest" in p.lower() for p in res))

        # A receipt that exists but the run has NO immutable baseline → fail-closed.
        d = case("postreview_nobaseline")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write(d, "docs/superpowers/execution/%s/state.json" % _FP_RUN_ID,
                      json.dumps({"run_id": _FP_RUN_ID, "jobs": {}}))
            _fp_write_receipt(d, tax_mod, info)
            res = validate_text(txt, mode="post-review", repo_root=d)
            expect("fastpath: post-review with no run baseline fails closed",
                   any("baseline" in p.lower() for p in res))

        # CRIT-1: the final-diff recompute MUST run in the SAME checkout the
        # producer hashed — the worker's linked WORKTREE (diff_root) — not the
        # main repo the dispatcher passes as --repo-root.
        d = case("crit1_worktree_diff_root")
        txt = _fp_build(d, tax_mod)
        wt_info, wt = _fp_git_worktree_and_state(d, tax_mod, txt)
        if wt_info is not None:
            # MED-6: the receipt's worktree binding must name the linked worktree
            # (the diff-root the producer hashed) — not the main repo root.
            _fp_write_receipt(d, tax_mod, wt_info, worktree=wt)
            # (i) with --worktree the receipt's worktree-hashed diff recomputes to
            #     the same digest → PASS (the main tree is clean, so this only
            #     passes because the recompute honored diff_root).
            res = validate_text(txt, mode="post-review", repo_root=d,
                                diff_root=wt)
            expect("fastpath CRIT-1: post-review recomputes the diff in the "
                   "linked worktree -> passes (%r)" % res, res == [])
            # (ii) WITHOUT --worktree the recompute falls to the main repo, whose
            #      diff against baseline is empty → digest mismatch → fail-closed.
            #      Proves the recompute is NOT anchored to repo_root.
            res = validate_text(txt, mode="post-review", repo_root=d,
                                diff_root=None)
            expect("fastpath CRIT-1: recomputing in the main checkout (no "
                   "worktree change) fails closed on the diff digest",
                   any("final_diff_digest" in p for p in res))
            # (iii) an unavailable diff_root never silently passes — fail-closed.
            res = validate_text(txt, mode="post-review", repo_root=d,
                                diff_root=os.path.join(d, "no-such-worktree"))
            expect("fastpath CRIT-1: an unavailable diff-root fails closed",
                   any("recompute the final diff" in p for p in res))
        else:
            expect("fastpath CRIT-1: worktree diff-root suite (git worktree "
                   "unavailable - skipped)", True)

        # ---- ROUND-4 HIGH-1(b): post-review attempt binding (--expected-attempt) ----
        # A receipt sealed at attempt 1, validated when the run's CURRENT attempt is 2,
        # is a stale prior-attempt replay → REJECTED. A correctly-incremented receipt
        # passes. When --expected-attempt is absent, behavior is unchanged (back-compat).
        d = case("postreview_attempt_stale")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write_receipt(d, tax_mod, info, attempt_id=1)
            expect("fastpath HIGH-1: attempt-1 receipt passes when NO expected "
                   "attempt is supplied (back-compat)",
                   validate_text(txt, mode="post-review", repo_root=d) == [])
            expect("fastpath HIGH-1: attempt-1 receipt passes --expected-attempt 1",
                   validate_text(txt, mode="post-review", repo_root=d,
                                 expected_attempt=1) == [])
            res_att = validate_text(txt, mode="post-review", repo_root=d,
                                    expected_attempt=2)
            expect("fastpath HIGH-1: attempt-1 receipt REJECTED under "
                   "--expected-attempt 2 (stale prior-attempt replay)",
                   any("attempt_id" in p and "expected review attempt" in p
                       for p in res_att))

        d = case("postreview_attempt_fresh")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write_receipt(d, tax_mod, info, attempt_id=2)
            expect("fastpath HIGH-1: correctly-incremented attempt-2 receipt passes "
                   "--expected-attempt 2",
                   validate_text(txt, mode="post-review", repo_root=d,
                                 expected_attempt=2) == [])

        # ---- ROUND-4 MED-3: an unloadable receipt schema fails CLOSED (no shape skip) ----
        d = case("postreview_schema_unloadable")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write_receipt(d, tax_mod, info)  # a fully-valid receipt
            expect("fastpath MED-3: baseline receipt passes with a loadable schema",
                   validate_text(txt, mode="post-review", repo_root=d) == [])
            # Stub the module's schema path at a MALFORMED file — the load must fail and
            # that failure must itself be a rejection (never a silent shape-check skip).
            _saved_schema = _RECEIPT_SCHEMA
            bad_schema = os.path.join(d, "bad-schema.json")
            with open(bad_schema, "w", encoding="utf-8") as fh:
                fh.write("{ this is not valid json")
            globals()["_RECEIPT_SCHEMA"] = bad_schema
            try:
                res_sch = validate_text(txt, mode="post-review", repo_root=d)
            finally:
                globals()["_RECEIPT_SCHEMA"] = _saved_schema
            expect("fastpath MED-3: malformed receipt schema REJECTS (fail-closed, "
                   "no shape-check skip)",
                   any("schema" in p.lower() and "fail-closed" in p.lower()
                       for p in res_sch))
            # A MISSING schema file also fails closed.
            globals()["_RECEIPT_SCHEMA"] = os.path.join(d, "does-not-exist.json")
            try:
                res_sch2 = validate_text(txt, mode="post-review", repo_root=d)
            finally:
                globals()["_RECEIPT_SCHEMA"] = _saved_schema
            expect("fastpath MED-3: missing receipt schema also REJECTS (fail-closed)",
                   any("schema" in p.lower() and "fail-closed" in p.lower()
                       for p in res_sch2))
    else:
        expect("fastpath: post-review git-binding suite (git unavailable — "
               "skipped)", True)

    # post-review still REQUIRES a receipt (independent of git availability).
    d = case("postreview_missing")
    txt = _fp_build(d, tax_mod)  # no receipt written
    res = validate_text(txt, mode="post-review", repo_root=d)
    expect("fastpath: post-review requires a receipt",
           any("receipt" in p for p in res))

    # (h) containment: traversal ref + escaping symlink write target.
    d = case("traversal_ref")
    txt = _fp_build(d, tax_mod, loc_ref="../evil.localization.json")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: '..' traversal ref rejected",
           any("traversal" in p or ".." in p for p in res))

    if hasattr(os, "symlink"):
        d = case("symlink_write")
        try:
            txt = _fp_build(d, tax_mod, symlink_write=True)
            res = validate_text(txt, mode="pre-dispatch", repo_root=d)
            expect("fastpath: escaping-symlink write target rejected",
                   any("symlink" in p or "outside the repo" in p
                       or "escape" in p for p in res))
        except OSError:
            expect("fastpath: escaping-symlink write target rejected "
                   "(symlink unsupported — skipped)", True)

    # MED-9: a fast_path *_ref that is TRACKED/STAGED but absent from any commit
    # must fail — `git ls-files` is not proof of a commit (execution-manifest.md
    # §218-220: referenced artifacts must live in a commit).
    if _shutil.which("git") is not None:
        import subprocess as _sp

        def _gitstage(root, commit):
            r = _sp.run(["git", "-C", root, "init", "-q"],
                        stdout=_sp.PIPE, stderr=_sp.PIPE)
            if r.returncode != 0:
                return False
            for kv in (("user.email", "s@e.com"), ("user.name", "cv"),
                       ("commit.gpgsign", "false"), ("core.hooksPath", "/dev/null")):
                _sp.run(["git", "-C", root, "config"] + list(kv),
                        stdout=_sp.PIPE, stderr=_sp.PIPE)
            _sp.run(["git", "-C", root, "add", "-A"],
                    stdout=_sp.PIPE, stderr=_sp.PIPE)
            if commit:
                r = _sp.run(["git", "-C", root, "commit", "-q", "--no-verify",
                             "-m", "b"], stdout=_sp.PIPE, stderr=_sp.PIPE)
                return r.returncode == 0
            return True  # staged only — deliberately no commit, so no HEAD

        # (i) staged-not-committed: refs are tracked by ls-files yet in NO commit
        #     → the HEAD-commit check must reject (the pre-MED-9 code PASSED here).
        d = case("med9_staged_not_committed")
        txt = _fp_build(d, tax_mod)
        if _gitstage(d, commit=False):
            res = validate_text(txt, mode="pre-dispatch", repo_root=d)
            expect("fastpath MED-9: staged-but-uncommitted ref rejected "
                   "(ls-files is not a commit)",
                   any("not present in a commit" in p for p in res))
        else:
            expect("fastpath MED-9: staged-not-committed suite (git init failed "
                   "- skipped)", True)

        # (ii) genuinely committed refs pass under pre-dispatch — the HEAD check
        #      does not over-reject a durable artifact.
        d = case("med9_committed_ok")
        txt = _fp_build(d, tax_mod)
        if _gitstage(d, commit=True):
            res = validate_text(txt, mode="pre-dispatch", repo_root=d)
            expect("fastpath MED-9: committed refs pass pre-dispatch (%r)" % res,
                   res == [])
        else:
            expect("fastpath MED-9: committed-ok suite (commit failed - "
                   "skipped)", True)
    else:
        expect("fastpath MED-9: commit-containment suite (git unavailable - "
               "skipped)", True)

    # ---------------------------------------------------------------------- #
    # MED-6: the receipt's own ``worktree`` binding MUST equal the diff-root the
    # validator recomputes the final diff in. A missing binding, or one that
    # resolves to a DIFFERENT checkout, fails closed. (The matching-worktree
    # PASS is already proven by the CRIT-1 (i) case above with worktree=wt.)
    # ---------------------------------------------------------------------- #
    if _shutil.which("git") is not None:
        # (a) a receipt with NO worktree binding is rejected.
        d = case("med6_missing_worktree")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write_receipt(d, tax_mod, info, drop=["worktree"])
            res = validate_text(txt, mode="post-review", repo_root=d)
            expect("fastpath MED-6: receipt without a 'worktree' binding rejected",
                   any("worktree" in p.lower() and "MED-6" in p for p in res))
        else:
            expect("fastpath MED-6: missing-worktree suite (git init failed - "
                   "skipped)", True)

        # (b) a receipt whose worktree resolves to a DIFFERENT checkout than the
        #     diff-root is rejected (a receipt sealed against another checkout).
        d = case("med6_wrong_worktree")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            other = os.path.join(d, "some", "other", "checkout")
            _fp_write_receipt(d, tax_mod, info, worktree=other)
            res = validate_text(txt, mode="post-review", repo_root=d)
            expect("fastpath MED-6: receipt worktree bound to a different checkout "
                   "rejected",
                   any("different checkout" in p and "MED-6" in p for p in res))
        else:
            expect("fastpath MED-6: wrong-worktree suite (git init failed - "
                   "skipped)", True)

        # (c) the correct binding (worktree == repo-root diff-root) still PASSES —
        #     the new gate does not over-reject a genuine single-tree receipt.
        d = case("med6_correct_worktree")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write_receipt(d, tax_mod, info, worktree=d)
            res = validate_text(txt, mode="post-review", repo_root=d)
            expect("fastpath MED-6: correctly-bound worktree receipt passes (%r)"
                   % res, res == [])
        else:
            expect("fastpath MED-6: correct-worktree suite (git init failed - "
                   "skipped)", True)

    # ---------------------------------------------------------------------- #
    # MED-8: HEAD-commit containment fails CLOSED on a git error while a `.git`
    # IS present (was a silent skip), but still DEGRADES when there is no `.git`
    # at all (the legitimate no-git pre-dispatch path). The git-error condition
    # is simulated deterministically by stubbing the module-level probe to its
    # sentinels; the real probe is also exercised end-to-end.
    # ---------------------------------------------------------------------- #
    if _shutil.which("git") is not None:
        import subprocess as _sp8
        med8 = case("med8_headcheck")
        _fp_write(med8, "docs/a.json", "{}")

        def _g8(*a):
            return _sp8.run(["git", "-C", med8] + list(a),
                            stdout=_sp8.PIPE, stderr=_sp8.PIPE)

        _ok8 = _g8("init", "-q").returncode == 0
        for _kv in (("user.email", "s@e.com"), ("user.name", "cv"),
                    ("commit.gpgsign", "false"), ("core.hooksPath", "/dev/null")):
            _g8("config", *_kv)
        _g8("add", "-A")
        _ok8 = _ok8 and _g8("commit", "-q", "--no-verify", "-m", "b").returncode == 0

        if _ok8:
            g = globals()
            saved = g["_is_committed_at_head"]
            # (a) git-error sentinel while a `.git` is present -> fail closed.
            g["_is_committed_at_head"] = lambda rr, rp: _GIT_UNAVAILABLE
            try:
                probs = _containment_problems(
                    "artifact", "docs/a.json", med8,
                    must_exist=True, require_committed=True)
            finally:
                g["_is_committed_at_head"] = saved
            expect("fastpath MED-8: HEAD containment fails closed on a git error "
                   "(not a silent skip)",
                   any("could not be verified" in p and "MED-8" in p
                       for p in probs))

            # (b) the no-`.git` degrade sentinel (None) still SKIPS — the
            #     legitimate no-git path must not be turned into a violation.
            g["_is_committed_at_head"] = lambda rr, rp: None
            try:
                probs = _containment_problems(
                    "artifact", "docs/a.json", med8,
                    must_exist=True, require_committed=True)
            finally:
                g["_is_committed_at_head"] = saved
            expect("fastpath MED-8: no-.git containment still degrades (skip, not "
                   "a fail)",
                   not any("could not be verified" in p
                           or "not present in a commit" in p for p in probs))

            # (c) the REAL probe (through the timeout supervisor) returns True for
            #     a genuinely committed file.
            expect("fastpath MED-8: real _is_committed_at_head True for a "
                   "committed file",
                   _is_committed_at_head(med8, "docs/a.json") is True)
        else:
            expect("fastpath MED-8: git-error containment suite (git init/commit "
                   "failed - skipped)", True)
    else:
        expect("fastpath MED-8: git-error containment suite (git unavailable - "
               "skipped)", True)

    # (d) the REAL probe returns None (degrade) when there is no `.git` at all —
    #     independent of git availability, since it never shells out.
    nogit = case("med8_nogit")
    _fp_write(nogit, "docs/a.json", "{}")
    expect("fastpath MED-8: real _is_committed_at_head None when no .git (legit "
           "degrade)", _is_committed_at_head(nogit, "docs/a.json") is None)


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

    # effort xhigh: valid iff backend codex — selftested BOTH ways.
    xh_ok = validate_text(XHIGH_CODEX_MANIFEST)
    expect("codex+xhigh manifest valid (%r)" % xh_ok, xh_ok == [])
    xh_bad = validate_text(XHIGH_CLAUDE_MANIFEST)
    expect(
        "claude+xhigh caught (xhigh is codex-only)",
        any("xhigh is codex-only (kernel: model_reasoning_effort); use high" in p
            for p in xh_bad),
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

    # antigravity ⇒ worktree: an external no-kernel-sandbox worker with
    # isolation: direct is INVALID (mirrors the codex⇒worktree invariant).
    agy_bad = validate_text(ANTIGRAVITY_DIRECT_MANIFEST)
    expect(
        "antigravity+direct caught (antigravity requires worktree)",
        any("backend antigravity but isolation" in p
            and "antigravity requires worktree" in p for p in agy_bad),
    )

    # devin ⇒ worktree: same invariant, new backend (v1: worker-only, lower-trust).
    devin_bad = validate_text(DEVIN_DIRECT_MANIFEST)
    expect(
        "devin+direct caught (devin requires worktree)",
        any("backend devin but isolation" in p
            and "devin requires worktree" in p for p in devin_bad),
    )
    devin_ok = validate_text(DEVIN_WORKTREE_MANIFEST)
    expect("devin+worktree manifest is valid", devin_ok == [])

    # opencode ⇒ worktree: same invariant, new backend (v1: worker-only, lower-trust).
    opencode_bad = validate_text(OPENCODE_DIRECT_MANIFEST)
    expect(
        "opencode+direct caught (opencode requires worktree)",
        any("backend opencode but isolation" in p
            and "opencode requires worktree" in p for p in opencode_bad),
    )
    opencode_ok = validate_text(OPENCODE_WORKTREE_MANIFEST)
    expect("opencode+worktree manifest is valid (provider/model string accepted)",
           opencode_ok == [])

    # WORKER-ONLY: a reviewer job MUST NEVER resolve to backend devin/opencode,
    # even when tier: deep + isolation: worktree are otherwise satisfied.
    devin_reviewer_bad = validate_text(DEVIN_REVIEWER_MANIFEST)
    expect(
        "devin reviewer job REJECTED (WORKER-ONLY)",
        any("reviewer job 'task-1-spec-review'" in p
            and "backend 'devin'" in p
            and "WORKER-ONLY" in p for p in devin_reviewer_bad),
    )
    opencode_reviewer_bad = validate_text(OPENCODE_REVIEWER_MANIFEST)
    expect(
        "opencode reviewer job REJECTED (WORKER-ONLY)",
        any("reviewer job 'task-1-quality-review'" in p
            and "backend 'opencode'" in p
            and "WORKER-ONLY" in p for p in opencode_reviewer_bad),
    )

    # opencode provider/model shape: a bare (slash-less) or malformed (empty-side)
    # explicit model override is REJECTED before dispatch.
    opencode_bare_bad = validate_text(OPENCODE_BARE_MODEL_MANIFEST)
    expect(
        "bare opencode model 'gpt-5.6' REJECTED (not provider/model)",
        any("not a valid 'provider/model' string" in p for p in opencode_bare_bad),
    )
    opencode_malformed_bad = validate_text(OPENCODE_MALFORMED_MODEL_MANIFEST)
    expect(
        "malformed opencode model 'anthropic/' REJECTED (empty right side)",
        any("not a valid 'provider/model' string" in p
            for p in opencode_malformed_bad),
    )
    # NON-STRING opencode model (int / list / dict) must ALSO be rejected — it can
    # never be a provider/model string and must not skip the shape check.
    opencode_int_bad = validate_text(OPENCODE_INT_MODEL_MANIFEST)
    expect(
        "non-string opencode model (int 42) REJECTED",
        any("not a valid 'provider/model' string" in p
            for p in opencode_int_bad),
    )
    opencode_list_bad = validate_text(OPENCODE_LIST_MODEL_MANIFEST)
    expect(
        "non-string opencode model (list) REJECTED",
        any("not a valid 'provider/model' string" in p
            for p in opencode_list_bad),
    )
    opencode_dict_bad = validate_text(OPENCODE_DICT_MODEL_MANIFEST)
    expect(
        "non-string opencode model (dict) REJECTED",
        any("not a valid 'provider/model' string" in p
            for p in opencode_dict_bad),
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

    # --- v2.12 (B1): optional per-job advisor block ---
    # A job WITHOUT an advisor block stays valid (backward compat): GOOD_MANIFEST
    # has none and is clean.
    expect("good manifest (no advisor block) stays valid",
           not any("advisor" in p for p in good))
    # An eligible standard-tier implementer with a well-formed advisor block is valid.
    adv_good = validate_text(ADVISOR_GOOD_MANIFEST)
    expect("advisor block on eligible standard implementer: zero violations (%r)"
           % adv_good, adv_good == [])
    # Advisor on ineligible job types is rejected — one message per ineligible job.
    adv_inelig = validate_text(ADVISOR_INELIGIBLE_MANIFEST)
    expect("advisor on shared_foundation rejected",
           any("task-0-foundation" in p and "advisor-INELIGIBLE" in p for p in adv_inelig))
    expect("advisor on docs job rejected",
           any("task-1-docs" in p and "advisor-INELIGIBLE" in p for p in adv_inelig))
    expect("advisor on reviewer job rejected",
           any("task-2-spec-review" in p and "advisor-INELIGIBLE" in p for p in adv_inelig))
    # Malformed advisor SHAPE on an eligible job: each defect flagged.
    adv_shape = validate_text(ADVISOR_BAD_SHAPE_MANIFEST)
    expect("advisor.enabled non-boolean rejected",
           any("advisor.enabled must be a boolean" in p for p in adv_shape))
    expect("advisor unknown backend rejected",
           any("advisor.advisor_backend" in p and "not a known backend" in p
               for p in adv_shape))
    expect("advisor unknown key rejected",
           any("advisor has unknown key 'bogus_key'" in p for p in adv_shape))
    # Fallback parser parity: the ineligible-advisor manifest is flagged there too.
    expect("fallback parser: advisor-ineligible manifest flagged",
           any("advisor-INELIGIBLE" in p
               for p in validate(_mini_yaml(ADVISOR_INELIGIBLE_MANIFEST))))

    # v2.9 conditional fast-path suite (on-disk fixtures).
    _selftest_fastpath(expect)

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
