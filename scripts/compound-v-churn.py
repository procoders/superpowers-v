#!/usr/bin/env python3
"""
Compound V — normalized churn cache (v2.9 Task D1).

Writes ``docs/superpowers/memory/churn-cache.json`` as an ESCALATION-ONLY static
signal for the pre-eval scorer (spec override #5: ``churn.hot`` -> escalate;
low / absent / insufficient history NEVER lowers and is NEVER ``hot``). Shape::

    {version, head_sha, formula_id,
     paths: {<path>: {normalized_churn, fix_revert_density, hot}}}

Design contract (rev-5 plan Task D1 / CR1-7, CR4-10; audit corrections C4/C5):

* **FULL REBUILD each run** — NOT incremental. One `git log` pass over the whole
  history reproduces the cache byte-for-byte on a fixed HEAD (1C measured ~0.04s).
  Reproducibility is the whole point of a static escalation signal, so there is no
  stored last-SHA / delta path to drift.
* **One extraction pass:**
  ``git log --no-merges --numstat --format='%x01%H%x01%ct%x01%s'`` (SOH-delimited so
  a subject can hold spaces/pipes without ambiguity). Routed through the shared
  process-group timeout supervisor (`compound-v-run-with-timeout.py`) with
  ``stdin </dev/null`` and an enforced ``--max-output-bytes`` sink — this module
  NEVER calls ``subprocess.run(timeout=...)`` on git directly (external-launch
  invariant). ``--no-renames`` keeps each numstat path a plain literal (no
  ``{old => new}`` arrow syntax to misparse); ``-c core.quotePath=false`` keeps
  non-ASCII paths unquoted.
* **Binary sentinel [C5]:** ``--numstat`` emits ``-\t-\t<path>`` for binary blobs; a
  naive ``int('-')`` crashes, so such lines are skipped (contribute no line churn).
* **Separated revert/fix grep [C4]:** ``git log -i -E --grep=revert --grep=fix``
  (each its own flag — a fused ``-iE`` is `fatal: unrecognized argument`). The set of
  fix/revert commit hashes feeds ``fix_revert_density``.
* **Single-sourced exclusions [CR4-10]:** generated/vendor paths (``exclude_paths``
  globs) and pure-format commits (``format_commit_patterns`` regexes) come ONLY from
  the taxonomy ``churn:`` block via the shared loader — this module invents none.
  (Nagappan & Ball: generated churn and cosmetic reformatting distort the signal.)

Normalization (formula_id = ``relchurn-v1`` — NEVER raw counts; Nagappan & Ball show
raw churn is a poor predictor, relative/normalized churn is the useful one):

    age_days      = max(1, (ref_now - first_touch_ct) / 86400)   # ref_now = max commit
                                                                 # time in history ->
                                                                 # deterministic, no wall
                                                                 # clock
    commit_freq   = commit_count / age_days                      # touches per day
    rel_churn     = total_churn / (total_churn + surviving)      # in [0,1); surviving =
                                                                 # max(1, added - deleted)
    normalized_churn = round(commit_freq * rel_churn, 6)         # activity-weighted
                                                                 # RELATIVE churn
    fix_revert_density = round(fix_revert_commits / commit_count, 6)

``hot`` (escalation gate) requires MEANINGFUL history — insufficient history is never
hot::

    hot = (commit_count >= MIN_COMMITS_FOR_HOT) and
          (normalized_churn >= HOT_NORMALIZED_THRESHOLD or
           fix_revert_density >= HOT_FIX_DENSITY_THRESHOLD)

The three thresholds are baked into ``formula_id`` (bump it if you retune them). All
arithmetic derives from the SOH log alone (no working-tree file reads) so two runs on
the same HEAD are byte-identical.

O(1) read: ``load_churn_cache(path)`` then ``read_path(cache, path)`` — a dict lookup;
an absent path returns a safe non-hot default (escalation-only ⇒ absence never lowers).

Python 3.9-safe, stdlib only; PyYAML is soft (via the shared taxonomy loader), never a
hard ``import yaml``.

Usage:
    compound-v-churn.py [--repo DIR] [--taxonomy PATH] [--out PATH]   # build + write
    compound-v-churn.py --lookup PATH [--out PATH]                    # O(1) read one path
    compound-v-churn.py --selftest
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

CACHE_VERSION = 1
FORMULA_ID = "relchurn-v1"

# Thresholds — part of the formula identity (retune => bump FORMULA_ID).
MIN_COMMITS_FOR_HOT = 5          # < this = insufficient history => never hot
HOT_NORMALIZED_THRESHOLD = 0.5   # activity-weighted relative churn
HOT_FIX_DENSITY_THRESHOLD = 0.34 # >= ~1/3 of touches are fix/revert => defect-prone

DEFAULT_OUT_REL = os.path.join("docs", "superpowers", "memory", "churn-cache.json")
DEFAULT_TAXONOMY_REL = os.path.join(".claude", "compound-v-impact-taxonomy.yaml")
EXAMPLE_TAXONOMY_REL = os.path.join(".claude", "compound-v-impact-taxonomy.example.yaml")

GIT_TIMEOUT_S = 60
# Generous cap: the whole-history numstat of a plugin-sized repo is tiny; a very large
# monorepo could hit this, in which case the read is best-effort (trailing partial line
# dropped) and any under-count only REDUCES escalation — a documented, safe degrade for
# an escalation-only signal.
OUTPUT_CAP_BYTES = 64 * 1024 * 1024

_SOH = "\x01"


# ---------------------------------------------------------------------------- #
# Sibling reuse by path (hyphenated filenames -> importlib). Loaded lazily; each
# has an inline degrade so the module never hard-fails if a sibling is missing.
# ---------------------------------------------------------------------------- #
def _here():
    return os.path.dirname(os.path.abspath(__file__))


def _supervisor_path():
    return os.path.join(_here(), "compound-v-run-with-timeout.py")


_TAX_MODULE = None


def _taxonomy_module():
    global _TAX_MODULE
    if _TAX_MODULE is not None:
        return _TAX_MODULE
    import importlib.util

    path = os.path.join(_here(), "compound-v-taxonomy.py")
    try:
        spec = importlib.util.spec_from_file_location("compound_v_taxonomy", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _TAX_MODULE = mod
    except Exception:  # noqa: BLE001
        _TAX_MODULE = False
    return _TAX_MODULE


def _glob_match(path, pattern):
    """Segment-aware path glob (reuses the shared taxonomy/validate-manifest matcher;
    minimal inline fallback if unavailable)."""
    mod = _taxonomy_module()
    if mod:
        return mod.glob_match(path, pattern)
    rx = ["(?s:"]
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            j = i
            while j < n and pattern[j] == "*":
                j += 1
            rx.append(".*" if j - i >= 2 else "[^/]*")
            i = j
            continue
        rx.append("[^/]" if c == "?" else re.escape(c))
        i += 1
    rx.append(r")\Z")
    return re.compile("".join(rx)).match(path) is not None


def load_churn_config(repo, taxonomy_path=None):
    """Return (exclude_paths, format_commit_patterns) from the taxonomy ``churn:`` block.

    Single-sourced [CR4-10]: this module invents no excludes. Resolution order for the
    taxonomy file: explicit ``taxonomy_path`` -> project ``.claude/…yaml`` -> shipped
    ``.example.yaml``. A missing/unreadable taxonomy degrades to EMPTY excludes (the
    churn cache still builds; nothing is silently dropped)."""
    candidates = []
    if taxonomy_path:
        candidates.append(taxonomy_path)
    candidates.append(os.path.join(repo, DEFAULT_TAXONOMY_REL))
    candidates.append(os.path.join(repo, EXAMPLE_TAXONOMY_REL))
    mod = _taxonomy_module()
    for cand in candidates:
        if not cand or not os.path.isfile(cand):
            continue
        try:
            if mod:
                tax = mod.load_taxonomy(path=cand)
            else:
                return [], []  # no loader, no safe parse -> empty (degrade)
            churn = tax.get("churn", {}) or {}
            return (list(churn.get("exclude_paths", []) or []),
                    list(churn.get("format_commit_patterns", []) or []))
        except Exception:  # noqa: BLE001 — malformed taxonomy => no excludes, not a crash
            return [], []
    return [], []


# ---------------------------------------------------------------------------- #
# THE external-git boundary — every extraction goes THROUGH the supervisor.
# ---------------------------------------------------------------------------- #
def _run_git(argv, repo, timeout_s=GIT_TIMEOUT_S, cap_bytes=OUTPUT_CAP_BYTES):
    """Run a git command UNDER the shared process-group timeout supervisor.

    Returns (returncode, stdout_text, capped). stdin is DEVNULL, the command leads its
    own session/process-group (SIGKILL'd as a group on timeout), and ``--max-output-bytes``
    bounds the captured stdout on disk. NEVER a bare ``subprocess.run(timeout=...)`` on
    git (external-launch invariant)."""
    import shutil

    sup = _supervisor_path()
    tmpd = tempfile.mkdtemp(prefix="cv-churn-")
    outfile = os.path.join(tmpd, "out")
    full = [
        sys.executable, sup,
        "--timeout", str(int(timeout_s)), "--grace", "1",
        "--cwd", repo, "--stdout", outfile,
        "--max-output-bytes", str(int(cap_bytes)),
        "--",
    ] + list(argv)
    try:
        proc = subprocess.run(
            full, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        raw = b""
        try:
            with open(outfile, "rb") as fh:
                raw = fh.read()
        except OSError:
            raw = b""
        capped = len(raw) >= int(cap_bytes)
        return proc.returncode, raw.decode("utf-8", "replace"), capped
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def _git_head_sha(repo):
    rc, out, _ = _run_git(["git", "rev-parse", "HEAD"], repo, cap_bytes=4096)
    if rc != 0:
        return None
    sha = out.strip()
    return sha or None


def _git_fix_revert_hashes(repo):
    """The fix/revert commit-hash SET [C4]: separated ``--grep`` flags (a fused
    ``-iE`` is rejected by git)."""
    rc, out, _ = _run_git(
        ["git", "log", "--no-merges", "-i", "-E",
         "--grep=revert", "--grep=fix", "--format=%H"],
        repo,
    )
    if rc != 0:
        return set()
    return set(line.strip() for line in out.split("\n") if line.strip())


def _git_numstat_log(repo):
    """The single full-history extraction pass. Returns (text, capped)."""
    rc, out, capped = _run_git(
        ["git", "-c", "core.quotePath=false", "log", "--no-merges", "--no-renames",
         "--numstat", "--format=%x01%H%x01%ct%x01%s"],
        repo,
    )
    if rc != 0:
        return "", False
    return out, capped


# ---------------------------------------------------------------------------- #
# Pure parse + normalization (no I/O — deterministic on identical input).
# ---------------------------------------------------------------------------- #
def _compile_format_patterns(patterns):
    compiled = []
    for pat in patterns:
        try:
            compiled.append(re.compile(pat))
        except re.error:
            continue  # a broken pattern never matches (validated upstream by B1)
    return compiled


def _is_excluded(path, exclude_globs):
    return any(_glob_match(path, g) for g in exclude_globs)


def _is_format_subject(subject, compiled_patterns):
    return any(p.search(subject) is not None for p in compiled_patterns)


def parse_numstat_log(text, fix_hashes, exclude_globs, compiled_format_patterns,
                      capped=False):
    """Fold the SOH-delimited numstat log into per-path accumulators.

    Returns (paths_acc, ref_now) where ``paths_acc[path]`` carries
    ``commits`` (set), ``fix_commits`` (set), ``added``, ``deleted``, ``first_ct``.
    ``ref_now`` is the max commit time seen (the deterministic 'now')."""
    lines = text.split("\n")
    if capped and lines and not text.endswith("\n"):
        lines = lines[:-1]  # a byte-capped read may have a truncated trailing line

    paths = {}
    ref_now = 0
    cur_hash = None
    cur_ct = 0
    cur_is_format = False

    for line in lines:
        if not line:
            continue
        if line.startswith(_SOH):
            parts = line.split(_SOH)
            # parts = ['', hash, ct, subject...] ; subject may (theoretically) hold SOH.
            if len(parts) < 4:
                cur_hash = None
                continue
            cur_hash = parts[1]
            try:
                cur_ct = int(parts[2])
            except ValueError:
                cur_ct = 0
            subject = _SOH.join(parts[3:])
            cur_is_format = _is_format_subject(subject, compiled_format_patterns)
            if cur_ct > ref_now:
                ref_now = cur_ct
            continue
        if "\t" not in line or cur_hash is None:
            continue
        if cur_is_format:
            continue  # pure-format commit: its churn does not count [CR4-10]
        cols = line.split("\t")
        if len(cols) < 3:
            continue
        added_s, deleted_s = cols[0], cols[1]
        path = "\t".join(cols[2:])
        if added_s == "-" or deleted_s == "-":
            continue  # binary sentinel [C5]
        try:
            added = int(added_s)
            deleted = int(deleted_s)
        except ValueError:
            continue
        if _is_excluded(path, exclude_globs):
            continue
        rec = paths.get(path)
        if rec is None:
            rec = {"commits": set(), "fix_commits": set(),
                   "added": 0, "deleted": 0, "first_ct": cur_ct}
            paths[path] = rec
        rec["commits"].add(cur_hash)
        if cur_hash in fix_hashes:
            rec["fix_commits"].add(cur_hash)
        rec["added"] += added
        rec["deleted"] += deleted
        if cur_ct < rec["first_ct"]:
            rec["first_ct"] = cur_ct
    return paths, ref_now


def normalize_path(rec, ref_now):
    """Apply the ``relchurn-v1`` formula to one path accumulator -> a cache entry."""
    commit_count = len(rec["commits"])
    total_churn = rec["added"] + rec["deleted"]
    surviving = max(1, rec["added"] - rec["deleted"])
    age_days = max(1.0, (ref_now - rec["first_ct"]) / 86400.0)
    commit_freq = commit_count / age_days
    rel_churn = (total_churn / (total_churn + surviving)) if total_churn > 0 else 0.0
    normalized_churn = round(commit_freq * rel_churn, 6)
    fix_revert_density = (round(len(rec["fix_commits"]) / commit_count, 6)
                          if commit_count else 0.0)
    hot = bool(
        commit_count >= MIN_COMMITS_FOR_HOT
        and (normalized_churn >= HOT_NORMALIZED_THRESHOLD
             or fix_revert_density >= HOT_FIX_DENSITY_THRESHOLD)
    )
    return {"normalized_churn": normalized_churn,
            "fix_revert_density": fix_revert_density,
            "hot": hot}


def build_churn_cache(repo=".", taxonomy_path=None):
    """FULL REBUILD: one numstat pass + one fix/revert grep + HEAD -> the cache dict."""
    repo = os.path.abspath(repo)
    exclude_globs, format_patterns = load_churn_config(repo, taxonomy_path)
    compiled_format = _compile_format_patterns(format_patterns)

    head_sha = _git_head_sha(repo)
    fix_hashes = _git_fix_revert_hashes(repo)
    text, capped = _git_numstat_log(repo)

    acc, ref_now = parse_numstat_log(text, fix_hashes, exclude_globs,
                                     compiled_format, capped=capped)
    paths = {path: normalize_path(rec, ref_now) for path, rec in acc.items()}
    return {
        "version": CACHE_VERSION,
        "head_sha": head_sha,
        "formula_id": FORMULA_ID,
        "paths": paths,
    }


def write_churn_cache(cache, out_path):
    """Write the cache deterministically (sorted keys => byte-stable across runs)."""
    parent = os.path.dirname(out_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2, sort_keys=True, ensure_ascii=True)
        fh.write("\n")


# ---------------------------------------------------------------------------- #
# O(1) read helpers (escalation-only: an absent path is a safe non-hot default).
# ---------------------------------------------------------------------------- #
_ABSENT = {"normalized_churn": 0.0, "fix_revert_density": 0.0, "hot": False}


def load_churn_cache(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_path(cache, path):
    """O(1) lookup. Absent -> safe non-hot default (absence NEVER escalates or lowers)."""
    return cache.get("paths", {}).get(path, dict(_ABSENT))


# ---------------------------------------------------------------------------- #
# CLI.
# ---------------------------------------------------------------------------- #
def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()

    parser = argparse.ArgumentParser(prog="compound-v-churn.py")
    parser.add_argument("--repo", default=".", help="repository root (default: cwd)")
    parser.add_argument("--taxonomy", default=None,
                        help="taxonomy YAML (default: .claude/…yaml -> .example.yaml)")
    parser.add_argument("--out", default=None,
                        help="output path (default: <repo>/%s)" % DEFAULT_OUT_REL)
    parser.add_argument("--lookup", default=None,
                        help="O(1) read one path from an existing cache and print JSON")
    args = parser.parse_args(argv[1:])

    out_path = args.out or os.path.join(os.path.abspath(args.repo), DEFAULT_OUT_REL)

    if args.lookup is not None:
        try:
            cache = load_churn_cache(out_path)
        except (OSError, ValueError) as e:
            print(json.dumps({"error": "cannot read cache: %s" % e}), file=sys.stderr)
            return 1
        print(json.dumps(read_path(cache, args.lookup), sort_keys=True))
        return 0

    cache = build_churn_cache(repo=args.repo, taxonomy_path=args.taxonomy)
    write_churn_cache(cache, out_path)
    print("wrote %s (%d paths, formula=%s, head=%s)"
          % (out_path, len(cache["paths"]), cache["formula_id"], cache["head_sha"]))
    return 0


# ---------------------------------------------------------------------------- #
# Self-test — builds a tiny fixture git repo in a tempdir OUTSIDE the worktree.
# ---------------------------------------------------------------------------- #
def _git(cwd, *args, date=None):
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
    })
    if date is not None:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", "-C", cwd] + list(args), env=env,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, check=True)


def _write(cwd, rel, text):
    full = os.path.join(cwd, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(text)


def _write_bin(cwd, rel, data):
    full = os.path.join(cwd, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(data)


def _build_fixture(repo):
    """A tiny deterministic history exercising every code path."""
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")

    # An UNCOMMITTED taxonomy carrying the churn block, so build_churn_cache picks up
    # single-sourced excludes via the default .claude/ path [CR4-10]. Uncommitted =>
    # it never appears in the numstat history itself.
    _write(repo, DEFAULT_TAXONOMY_REL,
           "version: 1\n"
           "churn:\n"
           "  exclude_paths:\n"
           "    - \"**/*.min.js\"\n"
           "    - \"**/dist/**\"\n"
           "  format_commit_patterns:\n"
           "    - \"^style:\"\n"
           "    - \"^chore\\\\(fmt\\\\)\"\n")

    # A ship a churny, defect-prone file: 6 non-merge commits, 3 of them fix/revert.
    base = 1_700_000_000  # fixed epoch => deterministic ages
    subjects = [
        "feat: add hot module",
        "fix: correct hot module bug",
        "refactor hot module internals",
        "revert broken hot change",
        "fix: another hot module edge case",
        "tweak hot module",
    ]
    for i, subj in enumerate(subjects):
        _write(repo, "src/hot.py", "print('hot v%d')\n%s\n" % (i, "x = 1\n" * (i + 1)))
        _git(repo, "add", "src/hot.py")
        _git(repo, "commit", "-q", "-m", subj, date="%d +0000" % (base + i * 3600))

    # A file touched exactly once => insufficient history => never hot.
    _write(repo, "src/cold.py", "print('cold')\n")
    _git(repo, "add", "src/cold.py")
    _git(repo, "commit", "-q", "-m", "feat: add cold module",
         date="%d +0000" % (base + 100))

    # A binary blob => --numstat emits `-\t-` sentinel [C5]; must not crash.
    _write_bin(repo, "assets/logo.png", bytes(range(256)) * 4)
    _git(repo, "add", "assets/logo.png")
    _git(repo, "commit", "-q", "-m", "chore: add logo",
         date="%d +0000" % (base + 200))

    # An EXCLUDED generated file (matches **/dist/** and **/*.min.js) => absent.
    _write(repo, "dist/app.min.js", "var a=1;\n")
    _git(repo, "add", "dist/app.min.js")
    _git(repo, "commit", "-q", "-m", "build: bundle",
         date="%d +0000" % (base + 300))

    # A file touched ONLY by a pure-format commit (subject matches ^style:) => absent.
    _write(repo, "src/styled.py", "print('styled')\n")
    _git(repo, "add", "src/styled.py")
    _git(repo, "commit", "-q", "-m", "style: reformat styled",
         date="%d +0000" % (base + 400))

    # A real merge commit => exercises --no-merges (must not crash / inflate).
    _git(repo, "checkout", "-q", "-b", "feature")
    _write(repo, "src/feat.py", "print('feat')\n")
    _git(repo, "add", "src/feat.py")
    _git(repo, "commit", "-q", "-m", "feat: feature file",
         date="%d +0000" % (base + 500))
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge feature", "feature",
         date="%d +0000" % (base + 600))


def _selftest():
    import shutil

    failures = []

    def expect(name, cond):
        print(("  ok   - " if cond else "  FAIL - ") + name)
        if not cond:
            failures.append(name)

    # --- pure-function unit checks (no git needed) --------------------------- #
    fmt = _compile_format_patterns([r"^chore\(fmt\)", r"^style:", r"^format:"])
    expect("format subject detected", _is_format_subject("style: reformat", fmt) is True)
    expect("non-format subject ignored", _is_format_subject("fix: bug", fmt) is False)
    expect("exclude glob matches dist", _is_excluded("dist/app.min.js",
                                                     ["**/dist/**", "**/*.min.js"]) is True)
    expect("exclude glob misses src", _is_excluded("src/hot.py",
                                                   ["**/dist/**"]) is False)

    # Binary sentinel must not crash the parser and contributes no path.
    sentinel_log = (_SOH + "abc" + _SOH + "1700000000" + _SOH + "chore: add logo\n"
                    + "-\t-\tassets/logo.png\n")
    acc, _ = parse_numstat_log(sentinel_log, set(), [], fmt)
    expect("binary -\\t- sentinel skipped (no crash, no path)", acc == {})

    # insufficient history => never hot.
    entry_one = normalize_path(
        {"commits": {"h1"}, "fix_commits": set(), "added": 500, "deleted": 500,
         "first_ct": 1700000000}, ref_now=1700000000)
    expect("single-commit path is never hot (insufficient)", entry_one["hot"] is False)

    # a path with no fix/revert commits => density 0.
    expect("fix_revert_density 0 with no fixes", entry_one["fix_revert_density"] == 0.0)

    # --- end-to-end fixture build ------------------------------------------- #
    tmp = tempfile.mkdtemp(prefix="cv-churn-selftest-")
    try:
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        try:
            _build_fixture(repo)
        except (subprocess.CalledProcessError, OSError) as e:
            expect("fixture git repo built (git available)", False)
            print("    (git fixture unavailable: %s)" % e)
            _finish(failures)
            return 1 if failures else 0

        cache1 = build_churn_cache(repo=repo)
        cache2 = build_churn_cache(repo=repo)

        # Determinism: two full rebuilds on the same HEAD are byte-identical.
        blob1 = json.dumps(cache1, sort_keys=True)
        blob2 = json.dumps(cache2, sort_keys=True)
        expect("two rebuilds on same HEAD are byte-identical", blob1 == blob2)
        expect("head_sha populated (40-hex)",
               isinstance(cache1["head_sha"], str) and len(cache1["head_sha"]) == 40)
        expect("formula_id recorded", cache1["formula_id"] == FORMULA_ID)
        expect("version recorded", cache1["version"] == CACHE_VERSION)

        paths = cache1["paths"]

        # Churny defect-prone file: present, hot, positive fix/revert density.
        expect("hot file present", "src/hot.py" in paths)
        hot = paths.get("src/hot.py", {})
        expect("hot file is hot", hot.get("hot") is True)
        expect("hot file normalized_churn > 0", hot.get("normalized_churn", 0) > 0)
        expect("hot file fix_revert_density > 0 (3 of 6 fixes/reverts)",
               hot.get("fix_revert_density", 0) > 0)
        expect("hot file normalized_churn is not a raw count (< commit_count=6)",
               hot.get("normalized_churn", 99) < 6)

        # Single-touch file: present but NOT hot (insufficient history).
        expect("cold file present", "src/cold.py" in paths)
        expect("cold file NOT hot (insufficient)",
               paths.get("src/cold.py", {}).get("hot") is False)

        # Binary blob: skipped entirely (no path entry), no crash.
        expect("binary asset absent (sentinel skipped)", "assets/logo.png" not in paths)

        # Excluded generated file: absent (taxonomy exclude_paths).
        expect("excluded dist/*.min.js absent", "dist/app.min.js" not in paths)

        # Pure-format-only file: absent (format_commit_patterns).
        expect("format-only file absent (style: commit skipped)",
               "src/styled.py" not in paths)

        # Merge commit did not crash the build; feature file counted once (non-merge).
        expect("feature file present (merge did not drop it)", "src/feat.py" in paths)
        expect("feature file NOT hot (single non-merge touch)",
               paths.get("src/feat.py", {}).get("hot") is False)

        # O(1) read helpers.
        out_path = os.path.join(tmp, "churn-cache.json")
        write_churn_cache(cache1, out_path)
        reloaded = load_churn_cache(out_path)
        expect("round-trip write/read preserves hot entry",
               read_path(reloaded, "src/hot.py")["hot"] is True)
        expect("read_path absent -> safe non-hot default",
               read_path(reloaded, "does/not/exist.py") == _ABSENT)

        # Written file is byte-stable across two writes (sorted keys).
        out2 = os.path.join(tmp, "churn-cache-2.json")
        write_churn_cache(build_churn_cache(repo=repo), out2)
        with open(out_path, "rb") as a, open(out2, "rb") as b:
            expect("written cache byte-stable across rebuilds", a.read() == b.read())

        # Exclusions are single-sourced from the taxonomy block: point --taxonomy at a
        # tree with a custom exclude and confirm hot.py drops out.
        custom_tax = os.path.join(tmp, "tax.yaml")
        _write(tmp, "tax.yaml",
               "version: 1\nchurn:\n  exclude_paths:\n    - \"src/**\"\n"
               "  format_commit_patterns: []\n")
        cache_excl = build_churn_cache(repo=repo, taxonomy_path=custom_tax)
        expect("taxonomy-driven exclude removes src/** paths",
               "src/hot.py" not in cache_excl["paths"])
        expect("taxonomy-driven exclude keeps non-src entries out too (all src)",
               all(not p.startswith("src/") for p in cache_excl["paths"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return _finish(failures)


def _finish(failures):
    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
