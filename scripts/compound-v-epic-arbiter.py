#!/usr/bin/env python3
"""
Compound V epic arbiter — cross-model (Codex + Claude) panel that classifies a marathon
feature FAILURE (v2.10 "marathon" epic mode, design spec Component 2). NEW file, Unit B.

Depends on Unit A's frozen contract (scripts/compound-v-epic-state.py) but does NOT import
it: every idiom this script needs from A (id validation, realpath containment, atomic
writes, ISO-8601 handling) is deliberately DUPLICATED here so this script stays a
standalone, dependency-free CLI. It DOES optionally load compound-v-resolve-model.py by path
(degrade-safe) to key the family map on the same resolved model name the rest of the plugin
routes on.

This file is a SECURITY BOUNDARY: it egresses feature evidence to an external model (Codex),
so it (a) TOCTOU-safely contains and reads every untrusted path via O_NOFOLLOW file
descriptors — never validate-a-name-then-reopen-it — (b) conservatively redacts secrets
before ANY egress AND re-redacts model output before it re-enters our audit trail, failing
CLOSED (omit) on any doubt, (c) treats an immutable PERSISTED issuance record (not a
recomputable hash) as the anti-replay authorization boundary, with a durable
issued -> in_progress -> consumed transition, and (d) writes every artifact under a
trusted, symlink-free, count+byte-bounded audit directory.

## CLI contract (two-phase)

  --prepare --state S --feature F --attempt N [--now T] [--challenge-key K]
    Requires N == the feature's CURRENT persisted `attempts` (monotonic — you cannot
    pre-issue a future attempt or re-issue a consumed one). Emits a bounded Claude
    ballot-task prompt + a keyed `challenge_id`, and persists an immutable issuance record
    (status "issued") under <epic_dir>/arbiter/<feature>-<attempt>.challenge.json. Prints
    JSON {challenge_id, epic_id, feature, attempt, issued_at, prompt}.

  --classify --state S --feature F --challenge <id> [--evidence-file REL]
    [--claude-ballot BALLOTFILE] [--now T] [--challenge-key K] [tuning flags]
    Validates the persisted challenge FIRST. If it is missing/stale/consumed the WHOLE
    panel is dropped BEFORE any model call (no Codex egress). Otherwise it durably
    transitions the record issued -> in_progress, polls Codex (if the capabilities file
    says it's usable), validates the Claude ballot's {epic_id,feature,attempt,challenge_id}
    4-tuple, aggregates with the complete truth table, writes the frozen result to the
    audit JSON, and durably transitions the record -> consumed (a replay then re-emits the
    persisted audit idempotently, no second egress). `--evidence-file` is RELATIVE to the
    attempt dir <epic_dir>/arbiter/<feature>-<attempt>/ (absolute/`..`/symlink rejected).
    Prints {disposition, confirmed:false, reason, evidence, ballots, families_present,
    families_agreeing, attempt, audit_path, ...}.

  --selftest

Python 3.9-safe, stdlib only. No fabricated cost/token metrics. Requires a POSIX platform
with openat/renameat (dir_fd) support — verified at import; a platform without it fails
CLOSED rather than silently weakening the containment guarantees.
"""

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

# --------------------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------------------- #

ID_RE_OK = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
DISPOSITIONS = ("retry_fix", "halt_feature", "halt_epic", "blocked_external")
CONSERVATISM_RANK = {"retry_fix": 0, "blocked_external": 1, "halt_feature": 2, "halt_epic": 3}
KNOWN_FAMILIES = ("GPT", "Gemini", "Claude", "Grok")
# Families that can count as an INDEPENDENT external confirming family: known, and not the
# arbiter's own Claude (same family as the implementer -> correlated blind spots).
_EXTERNAL_CONFIRMING = ("GPT", "Gemini", "Grok")

DEFAULT_MAX_OUTPUT_BYTES = 20000
DEFAULT_CODEX_TIMEOUT_SEC = 300
MAX_OUTPUT_BYTES_CEILING = 5_000_000   # sanity ceiling for --max-output-bytes
MAX_TIMEOUT_SEC = 3600                  # sanity ceiling for --codex-timeout
AUDIT_ROTATE_COUNT = 500
AUDIT_ROTATE_BYTES = 5_000_000
CHALLENGE_ROTATE_COUNT = 500
AUDIT_MAX_ONE_BYTES = 200_000
FIELD_MAX_CHARS = 2000
REASON_MAX_CHARS = 4000                 # hard cap on any retained reason string
CHALLENGE_RECORD_MAX_BYTES = 65536
BALLOT_FILE_MAX_BYTES = 65536
# Filesystem components are built from epic_id/feature (<feature>-<attempt>.challenge.json),
# so bound id length well under the portable NAME_MAX (255) to turn an overlong id into a
# controlled error instead of an ENAMETOOLONG deep in an os.open (Finding 8/#11).
MAX_ID_LEN = 100

# ------------------------------------------------------------------------------------- #
# THREAT MODEL (v2.10): SINGLE-USER, SINGLE-PROCESS local tool. The driver calls the
# arbiter SERIALLY (never two --classify at once); the epic tree and any --claude-ballot
# file are USER-OWNED. Three classes of hardening are therefore DELIBERATELY OUT OF SCOPE
# here and deferred to v2.11 (multi-process autonomy), each noted at its site below:
#   (v2.11) concurrent compare-and-swap / fencing on a challenge record,
#   (v2.11) concurrent challenge-key creation races,
#   (v2.11) fsync-level crash durability of the atomic writes.
# ------------------------------------------------------------------------------------- #

CLAUDE_PROMPT_MAX_CHARS = 4000
CODEX_PROMPT_MAX_CHARS = 6000

TRUNC_MARKER = "\n...[TRUNCATED]"
DEPRECATION_LINE = "[features].codex_hooks is deprecated"

_FALLBACK_CODEX_MODEL = "gpt-5.6-sol"  # mirrors compound-v-resolve-model.py's codex/deep default

# openat/renameat are REQUIRED — fail closed if the platform lacks them (rather than
# silently degrading the symlink/TOCTOU containment).
# NOTE: use os.rename (not os.replace) for the dir_fd atomic swap — on POSIX rename()
# already replaces the destination atomically, and (unlike os.replace) os.rename exposes
# src_dir_fd/dst_dir_fd on macOS as well as Linux.
_DIRFD_OK = (
    hasattr(os, "O_NOFOLLOW")
    and hasattr(os, "O_DIRECTORY")
    and {os.open, os.rename, os.mkdir, os.unlink, os.stat}.issubset(os.supports_dir_fd)
)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class ArbiterError(Exception):
    """A controlled, user-facing error — printed as one line, nonzero exit, never a
    traceback and never a partial write."""


# --------------------------------------------------------------------------------------- #
# Small utils
# --------------------------------------------------------------------------------------- #

def _id_ok(s):
    """A real, safe id: must be a str (so str(None)=='None' can NEVER slip through), be
    within MAX_ID_LEN (it becomes a filesystem component — Finding 8/#11), contain only the
    allow-listed characters, and not be '.'/'..'."""
    return (isinstance(s, str) and bool(s) and s not in (".", "..")
            and len(s) <= MAX_ID_LEN and all(c in ID_RE_OK for c in s))


def _now_iso(dt=None):
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.isoformat()


def _parse_iso(s):
    if isinstance(s, str) and s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _resolve_now(now_arg):
    if now_arg:
        try:
            return _parse_iso(now_arg)
        except (ValueError, TypeError) as e:
            raise ArbiterError("invalid --now timestamp %r: %s" % (now_arg, e))
    return datetime.now(timezone.utc)


def _log(msg):
    print("epic-arbiter: %s" % msg, file=sys.stderr)


# --------------------------------------------------------------------------------------- #
# Finding 9 — strict state-schema validation (one boundary; controlled errors)
# --------------------------------------------------------------------------------------- #

def validate_state_schema(state):
    """Return a list of error strings (empty = valid). One strict boundary so no malformed
    state reaches path-building or feature lookup."""
    if not isinstance(state, dict):
        return ["state root is not a JSON object"]
    errs = []
    if not _id_ok(state.get("epic_id")):
        errs.append("epic_id is missing or not a valid id string")
    feats = state.get("features")
    if not isinstance(feats, list) or not feats:
        errs.append("features is missing or not a non-empty list")
    else:
        for i, f in enumerate(feats):
            if not isinstance(f, dict):
                errs.append("feature %d is not an object" % i)
                continue
            if not _id_ok(f.get("id")):
                errs.append("feature %d has a missing/invalid id" % i)
            at = f.get("attempts", 0)
            if isinstance(at, bool) or not isinstance(at, int) or at < 0:
                errs.append("feature %r has an invalid attempts %r (need a non-negative int)"
                            % (f.get("id"), at))
    auto = state.get("autonomy")
    if auto is not None:
        if not isinstance(auto, dict):
            errs.append("autonomy is present but not an object")
        else:
            st = auto.get("stance")
            if st is not None and not isinstance(st, str):
                errs.append("autonomy.stance is not a string")
            cap = auto.get("max_attempts_per_feature")
            if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int)):
                errs.append("autonomy.max_attempts_per_feature is not an int or null")
    return errs


def _find_feature(state, feature_id):
    for f in state.get("features", []):
        if isinstance(f, dict) and f.get("id") == feature_id:
            return f
    return None


def _read_state(state_path):
    if not state_path or not os.path.isfile(state_path):
        raise ArbiterError("--state must point at an existing epic-state.json")
    try:
        with open(state_path, "r", errors="replace") as fh:
            state = json.load(fh)
    except (OSError, ValueError) as e:
        raise ArbiterError("could not read/parse the state file: %s" % e)
    errs = validate_state_schema(state)
    if errs:
        raise ArbiterError("invalid epic-state schema: %s" % "; ".join(errs))
    return state


# --------------------------------------------------------------------------------------- #
# Finding 5 — trusted-root epic-dir containment + Finding 5/6 — dir_fd-verified I/O
# --------------------------------------------------------------------------------------- #

def validate_epic_dir(state_path, epic_id):
    """The epic dir is the realpath of the state file's directory. It MUST sit at
    `.../execution/epics/<epic_id>` — rooting under the trusted epics root AND binding the
    directory's own name to the epic_id (a mismatch means a hand-made/relocated state trying
    to write its audit trail somewhere it doesn't own). Returns the real epic dir path."""
    epic_dir = os.path.realpath(os.path.dirname(os.path.realpath(state_path)))
    parts = epic_dir.split(os.sep)
    if len(parts) < 4 or parts[-1] != epic_id or parts[-2] != "epics" or parts[-3] != "execution":
        raise ArbiterError(
            "epic dir %r is not under the trusted root .../execution/epics/<epic_id> "
            "(or its name does not match epic_id %r)" % (epic_dir, epic_id))
    return epic_dir


def _require_dirfd():
    if not _DIRFD_OK:
        raise ArbiterError("this platform lacks openat/renameat (dir_fd) support — refusing "
                           "to run without the symlink/TOCTOU containment guarantees")


def open_arbiter_dir_fd(epic_dir_real, create=True):
    """Return a dir fd for <epic_dir>/arbiter, opened with O_NOFOLLOW so a SYMLINKED arbiter
    dir (pointing outside the epic) is rejected outright. epic_dir_real is already a realpath
    (symlink-free by construction), so opening its final component with O_NOFOLLOW is exact.
    Caller must close the returned fd."""
    _require_dirfd()
    epic_fd = os.open(epic_dir_real, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _O_CLOEXEC)
    try:
        if create:
            try:
                os.mkdir("arbiter", 0o755, dir_fd=epic_fd)
            except FileExistsError:
                pass
        arbiter_fd = os.open("arbiter", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _O_CLOEXEC,
                             dir_fd=epic_fd)
    finally:
        os.close(epic_fd)
    return arbiter_fd


def _serialize(obj):
    """The ONE canonical serialization used for BOTH the audit file and stdout, so the
    printed bytes equal the persisted bytes exactly (round-3 #3)."""
    return json.dumps(obj, indent=2) + "\n"


def _write_text_at(dir_fd, name, text):
    """Atomic write of the pre-serialized `text` into `name` relative to dir_fd, via a temp
    file + renameat. O_EXCL|O_NOFOLLOW on the temp defeats a pre-planted symlink; the rename
    is dir_fd-relative on both ends so no path is re-resolved."""
    data = text.encode("utf-8")
    tmp = ".%s.%d.tmp" % (name, os.getpid())
    # Best-effort clear a stale temp from a prior crash.
    try:
        os.unlink(tmp, dir_fd=dir_fd)
    except OSError:
        pass
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | _O_CLOEXEC,
                 0o600, dir_fd=dir_fd)
    try:
        os.write(fd, data)
        # (v2.11) fsync-level crash durability is out of the single-user threat model — a
        # power-loss torn-write window is not defended here (see the module THREAT MODEL).
    finally:
        os.close(fd)
    try:
        # POSIX rename() atomically replaces the destination (== os.replace semantics),
        # and supports dir_fd on macOS where os.replace does not.
        os.rename(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except Exception:
        try:
            os.unlink(tmp, dir_fd=dir_fd)
        except OSError:
            pass
        raise


def _write_json_at(dir_fd, name, obj):
    """Atomic write of `obj` as canonical JSON into `name` relative to dir_fd."""
    _write_text_at(dir_fd, name, _serialize(obj))


def _read_text_at(dir_fd, name, cap):
    """Read the RAW text of `name` relative to dir_fd (O_NOFOLLOW + fstat regular + size
    cap). Returns None if absent/symlinked/non-regular/oversized. Used for the crash-recovery
    re-emit so the re-emitted bytes are byte-identical to what is on disk (round-3 #3)."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | _O_CLOEXEC, dir_fd=dir_fd)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > cap:
            return None
        raw = os.read(fd, cap + 1)
    finally:
        os.close(fd)
    return raw.decode("utf-8", errors="replace")


def _read_json_at(dir_fd, name, cap):
    """Read+parse JSON from `name` relative to dir_fd, via O_NOFOLLOW + fstat regular +
    cap+1 read. Returns None if the file is absent, a symlink, non-regular, oversized, or
    unparseable (callers treat that as 'no record')."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | _O_CLOEXEC, dir_fd=dir_fd)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > cap:
            return None
        raw = os.read(fd, cap + 1)
    finally:
        os.close(fd)
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None


def _read_capped_regular(path, cap, delete_oversized=False):
    """Open `path` with O_NOFOLLOW, assert a regular file, and read AT MOST cap bytes.
    Returns (text|None, err|None). An oversized file is DROPPED unread; it is deleted ONLY
    when `delete_oversized` is True — which callers set EXCLUSIVELY for the arbiter's OWN
    private temp artifacts. A caller-supplied input (a user-owned --claude-ballot / evidence
    file) is NEVER unlinked (Finding 4/#8): confining deletion to the private temp dir also
    dissolves the validate-fd-then-unlink-pathname TOCTOU."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | _O_CLOEXEC)
    except OSError as e:
        return None, "cannot open (symlink/missing?): %s" % e
    delete = False
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None, "not a regular file"
        if st.st_size > cap:
            delete = delete_oversized
            return None, "oversized (%d > cap %d) — dropped unread" % (st.st_size, cap)
        raw = os.read(fd, cap + 1)
    finally:
        os.close(fd)
        if delete:
            try:
                os.unlink(path)  # private-temp only; see delete_oversized docstring
            except OSError:
                pass
    return raw.decode("utf-8", errors="replace"), None


def _probe_record(dir_fd, name, cap):
    """Distinguish a truly-ABSENT record (ENOENT) from one that EXISTS but is
    unreadable/oversized/symlinked/malformed (Finding 6/#3). Returns:
      ("absent", None)      -> no such file, safe to issue a fresh record
      ("unreadable", None)  -> exists but cannot be trusted -> caller FAILS CLOSED
      ("ok", dict)          -> a parsed record
    """
    try:
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return "absent", None
    except OSError:
        return "unreadable", None
    if not stat.S_ISREG(st.st_mode) or st.st_size > cap:
        return "unreadable", None  # a symlink or an oversized file where a record should be
    rec = _read_json_at(dir_fd, name, cap)
    if not isinstance(rec, dict):
        return "unreadable", None
    return "ok", rec


def compute_challenge_id(key, epic_id, feature_id, attempt):
    """Keyed, deterministic-from-inputs challenge id. HMAC over the tuple with a persisted
    per-epic secret key so the id is NOT publicly recomputable, while staying reproducible
    for a given (key, tuple) in selftests. This is a secondary defense — the AUTHORIZATION
    boundary is the persisted immutable issuance record, not this hash."""
    msg = ("%s\x1f%s\x1f%s" % (epic_id, feature_id, attempt)).encode("utf-8")
    mac = hmac.new(key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return "ch-" + mac[:16]


def get_challenge_key(arbiter_fd, injected=None):
    """A persisted per-epic secret key at <arbiter>/.challenge-key (0600), created once via
    O_EXCL. An injected key (tests / a driver that wants a fixed key) bypasses the file."""
    if injected:
        return injected
    # (v2.11) a concurrent challenge-key creation race is out of the single-user threat
    # model — two processes calling this at once is a multi-process (v2.11) concern.
    existing = _read_json_at(arbiter_fd, ".challenge-key", 4096)
    if isinstance(existing, dict) and isinstance(existing.get("key"), str) and existing["key"]:
        return existing["key"]
    key = os.urandom(32).hex()
    try:
        _write_json_at(arbiter_fd, ".challenge-key", {"key": key})
    except FileExistsError:
        again = _read_json_at(arbiter_fd, ".challenge-key", 4096)
        if isinstance(again, dict) and isinstance(again.get("key"), str) and again["key"]:
            return again["key"]
    return key


# --------------------------------------------------------------------------------------- #
# B1 — capabilities discovery (strict booleans) + family map
# --------------------------------------------------------------------------------------- #

def load_capabilities(path=None):
    path = path or os.path.expanduser("~/.claude/compound-v-capabilities.json")
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def codex_available(caps):
    """Usable iff `codex.available IS True AND codex.exec_flags_verified IS True` — strict
    identity, so a truthy string ("false", "0", "no") or a 1/0 int can NEVER enable Codex
    egress (Finding 9)."""
    codex = caps.get("codex") if isinstance(caps, dict) else None
    if not isinstance(codex, dict):
        return False
    return codex.get("available") is True and codex.get("exec_flags_verified") is True


_FAMILY_NEEDLES = (
    ("gpt", "GPT"), ("gemini", "Gemini"), ("claude", "Claude"),
    ("opus", "Claude"), ("sonnet", "Claude"), ("grok", "Grok"),
)


def model_family(model_name):
    name = (model_name or "").lower()
    for needle, fam in _FAMILY_NEEDLES:
        if needle in name:
            return fam
    return "unknown"


def _load_sibling_module(filename, modname):
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, filename)
    try:
        spec = importlib.util.spec_from_file_location(modname, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001 - any load failure -> caller uses the fallback
        return None


def resolve_codex_model(config_path=None, explicit_model=None, tier="deep"):
    if explicit_model:
        return explicit_model
    mod = _load_sibling_module("compound-v-resolve-model.py", "compound_v_resolve_model")
    if mod is None:
        return _FALLBACK_CODEX_MODEL
    try:
        config_models = mod.load_config_models(config_path) if config_path else {}
        return mod.resolve("codex", tier, config_models=config_models)["model"]
    except Exception as e:  # noqa: BLE001 - degrade-safe
        _log("resolve-model.py failed (%s) — using fallback %r" % (e, _FALLBACK_CODEX_MODEL))
        return _FALLBACK_CODEX_MODEL


# --------------------------------------------------------------------------------------- #
# B3 — secret redaction (hardened, fail-closed) + field sanitation
# --------------------------------------------------------------------------------------- #

# Closed private-key blocks (PEM RSA/EC/OPENSSH/generic + PGP).
_CLOSED_KEY_RE = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]*PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----"
    r".*?-----END (?:[A-Z0-9 ]*PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----",
    re.S)
# Any private-key/PGP BEGIN marker (used to detect an UNCLOSED block after closed ones go).
_ANY_KEY_BEGIN_RE = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]*PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----")
# Authorization header incl. RFC822 folded continuation lines (following lines that begin
# with whitespace).
_AUTH_HEADER_RE = re.compile(r"(?im)^([ \t]*Authorization[ \t]*:).*(?:\r?\n[ \t]+.*)*")
# scheme://user:password@ — password may itself contain ':'.
_URL_CRED_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://)([^/\s:@]+):([^\s@]+)@")
# Labelled secrets: LABEL = value, value may be a (possibly multi-line) quoted string or a
# bare token. Covers short labelled secrets too (client_secret=, password=, api_key=, ...).
_LABELLED_SECRET_RE = re.compile(
    r"(?i)\b(client[_-]?secret|secret[_-]?key|access[_-]?key|api[_-]?key|auth[_-]?token|"
    r"secret|password|passwd|token|bearer|private[_-]?key)\b([ \t]*[:=][ \t]*)"
    r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[^\s'\"]+)")
# A labelled secret whose value STARTS with a quote (single/double) — used to detect an
# UNCLOSED quoted secret (no matching close), which the closed-quote alternative above would
# otherwise miss, leaking the value (Finding 2/#6).
_LABELLED_QUOTE_START_RE = re.compile(
    r"(?i)\b(?:client[_-]?secret|secret[_-]?key|access[_-]?key|api[_-]?key|auth[_-]?token|"
    r"secret|password|passwd|token|bearer|private[_-]?key)\b[ \t]*[:=][ \t]*([\"'])")
# JWT / split dotted tokens: three base64url segments, first begins eyJ.
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")
# Long opaque token runs (>=32 chars).
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{32,}")


def _cap_bytes_with_marker(s, max_bytes):
    """Cap `s` to `max_bytes` on the ENCODED length, RESERVING room for the truncation
    marker so the final encoded value never exceeds max_bytes (Finding 2)."""
    b = s.encode("utf-8", errors="replace")
    if len(b) <= max_bytes:
        return s
    marker_b = TRUNC_MARKER.encode("utf-8")
    # When the cap is smaller than the marker itself, appending the marker would blow the
    # cap — hard-truncate to the cap with no marker instead (Finding 8/#11).
    if max_bytes <= len(marker_b):
        return b[:max_bytes].decode("utf-8", errors="ignore")
    room = max_bytes - len(marker_b)
    return b[:room].decode("utf-8", errors="ignore") + TRUNC_MARKER


def _has_unescaped_quote(s, start, quote):
    """True iff `s[start:]` contains the delimiter `quote` NOT preceded by an odd run of
    backslashes (i.e. a real, unescaped closing quote). A backslash-escaped quote (\\" / \\')
    does NOT count as a close (round-3 #1) — the value is still open, so redact() fails
    closed rather than leak it into the Codex prompt."""
    i = start
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2  # skip the escaped char (whatever it is)
            continue
        if c == quote:
            return True
        i += 1
    return False


def redact(text, max_bytes):
    """Conservative secret redaction. Returns the redacted (and byte-capped) string, or None
    to signal FAIL CLOSED — the caller must then OMIT the evidence entirely. Fails closed on
    any internal exception AND on an UNCLOSED private-key/PGP block (a secret whose end we
    can't see, so we can't be sure a later pattern caught all of it)."""
    try:
        s = "" if text is None else str(text)
        s = _CLOSED_KEY_RE.sub("[REDACTED:PRIVATE_KEY]", s)
        if _ANY_KEY_BEGIN_RE.search(s):
            return None  # an unclosed private-key/PGP block -> omit the whole evidence
        # An UNCLOSED quoted labelled secret (e.g. token="shortsecret\ncontinued with no
        # closing quote) -> fail closed, like the unclosed PEM case above (Finding 2/#6).
        # An ESCAPED quote (\" / \') is NOT a close (round-3 #1): token="secret\" is still
        # unterminated, so scan for the first UNESCAPED matching quote and fail closed if none.
        for m in _LABELLED_QUOTE_START_RE.finditer(s):
            quote = m.group(1)
            if not _has_unescaped_quote(s, m.end(), quote):
                return None
        s = _AUTH_HEADER_RE.sub(r"\1 [REDACTED]", s)
        s = _URL_CRED_RE.sub(r"\1[REDACTED]@", s)
        s = _LABELLED_SECRET_RE.sub(r"\1\2[REDACTED]", s)
        s = _JWT_RE.sub("[REDACTED:JWT]", s)
        s = _TOKEN_RE.sub("[REDACTED:TOKEN]", s)
        return _cap_bytes_with_marker(s, max_bytes)
    except Exception:  # noqa: BLE001 - never leak a half-redacted string
        return None


def _sanitize_diagnostic(text):
    """Run a RETAINED diagnostic/drop-reason string through the same fail-closed redactor
    before it can reach stdout or the audit JSON (Finding 3/#7). A drop reason may quote a
    fragment of untrusted model/ballot content, so it is NEVER trusted verbatim; if it
    can't be sanitized it is replaced with a generic placeholder."""
    r = redact(text if isinstance(text, str) else str(text), REASON_MAX_CHARS)
    if r is None:
        return "[diagnostic omitted — could not sanitize]"
    return r[:REASON_MAX_CHARS]


def sanitize_ballot_fields(reason, evidence):
    """Type/line/length-check + RE-REDACT a model ballot's reason/evidence BEFORE they enter
    the classify output or the audit JSON (Finding 2). reason must be a single-line string;
    evidence a single-line string or None. Returns (reason, evidence) or None to DROP the
    whole ballot (fail closed)."""
    if reason is None:
        reason = ""
    if not isinstance(reason, str) or "\n" in reason or "\r" in reason:
        return None
    if evidence is not None and (not isinstance(evidence, str) or "\n" in evidence or "\r" in evidence):
        return None
    r = redact(reason, FIELD_MAX_CHARS)
    if r is None:
        return None
    if len(r) > FIELD_MAX_CHARS:
        r = r[:FIELD_MAX_CHARS]
    if evidence is None:
        e = None
    else:
        e = redact(evidence, FIELD_MAX_CHARS)
        if e is None:
            return None
        if len(e) > FIELD_MAX_CHARS:
            e = e[:FIELD_MAX_CHARS]
    return r, e


# --------------------------------------------------------------------------------------- #
# B3 — TOCTOU-safe contained evidence read (from the SAME fd we walk)
# --------------------------------------------------------------------------------------- #

def open_attempt_dir_fd(arbiter_fd, feature, attempt):
    """Open <arbiter>/<feature>-<attempt> as a dir fd with O_NOFOLLOW (rejects a symlinked
    attempt dir). Raises OSError if missing."""
    name = "%s-%s" % (feature, attempt)
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _O_CLOEXEC,
                   dir_fd=arbiter_fd)


def read_contained_evidence(base_fd, rel_path, cap):
    """Read an evidence file named by `rel_path` RELATIVE to base_fd (the attempt dir),
    walking each component with O_NOFOLLOW dir_fd opens and READING FROM THE FINAL FD we
    opened — never re-opening a validated name, so a component swapped after validation
    cannot redirect the read (Finding 1). Rejects absolute paths and any '.'/'..' component
    up front. Returns (text|None, err|None)."""
    if not rel_path:
        return None, "no evidence path"
    if os.path.isabs(rel_path):
        return None, "evidence path must be RELATIVE to the attempt dir (absolute rejected)"
    parts = [p for p in re.split(r"[/\\]+", rel_path) if p != ""]
    if not parts:
        return None, "empty evidence path"
    for p in parts:
        if p in (".", ".."):
            return None, "'.'/'..' component rejected in evidence path"
    opened = []
    cur = base_fd
    try:
        for p in parts[:-1]:
            nfd = os.open(p, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _O_CLOEXEC, dir_fd=cur)
            opened.append(nfd)
            cur = nfd
        try:
            ffd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | _O_CLOEXEC, dir_fd=cur)
        except OSError as e:
            return None, "evidence open failed (symlink/missing?): %s" % e
        try:
            st = os.fstat(ffd)
            if not stat.S_ISREG(st.st_mode):
                return None, "evidence is not a regular file"
            if st.st_size > cap:
                return None, "evidence oversized (%d > cap %d)" % (st.st_size, cap)
            raw = os.read(ffd, cap + 1)
        finally:
            os.close(ffd)
    except OSError as e:
        return None, "evidence path walk failed (symlink/missing?): %s" % e
    finally:
        for fd in opened:
            try:
                os.close(fd)
            except OSError:
                pass
    return raw.decode("utf-8", errors="replace"), None


# --------------------------------------------------------------------------------------- #
# B3 — bounded prompts
# --------------------------------------------------------------------------------------- #

def _bound_text(s, max_chars):
    if s is None:
        return ""
    s = str(s)
    return s if len(s) <= max_chars else s[:max_chars] + "\n...[TRUNCATED to stay bounded]"


def _build_claude_prompt(epic_id, feature_id, attempt, challenge_id, feat):
    title = feat.get("title", feature_id) if isinstance(feat, dict) else feature_id
    body = (
        "You are a FRESH, ADVERSARIAL reviewer for Compound V's marathon arbiter panel.\n"
        "A feature attempt FAILED its quality gate and needs an independent disposition.\n\n"
        "epic_id: %s\nfeature: %s (%s)\nattempt: %s\nchallenge_id: %s\n\n"
        "Investigate the failing feature's run directory and evidence yourself. Decide "
        "exactly ONE disposition:\n"
        "  retry_fix        - a fixable bug/flake; retrying is worth it\n"
        "  halt_feature      - abandon just this feature; the epic continues on independents\n"
        "  halt_epic         - a systemic problem; the whole epic should stop\n"
        "  blocked_external  - progress needs a human/external fact code cannot create\n\n"
        "Write your ballot as JSON with EXACTLY these keys (single-line reason/evidence):\n"
        '  {"epic_id": %s, "feature": %s, "attempt": %s, "challenge_id": %s,\n'
        '   "disposition": "<one of the four>", "reason": "<one line>",\n'
        '   "evidence": "<missing external fact if blocked_external, else null>"}\n\n'
        "Be conservative: on genuine doubt between retry_fix and a halt_*, prefer the halt."
        % (epic_id, feature_id, title, attempt, challenge_id,
           json.dumps(epic_id), json.dumps(feature_id), json.dumps(attempt),
           json.dumps(challenge_id)))
    return _bound_text(body, CLAUDE_PROMPT_MAX_CHARS)


def _build_codex_prompt(epic_id, feature_id, attempt, challenge_id, evidence_text):
    ev = evidence_text if evidence_text is not None else (
        "(evidence omitted — redaction could not complete safely, fail-closed)")
    body = (
        "Compound V marathon arbiter -- advisory read-only classification.\n"
        "epic_id: %s\nfeature: %s\nattempt: %s\nchallenge_id: %s\n\n"
        "A feature attempt FAILED its quality gate. Redacted evidence follows:\n---\n%s\n---\n\n"
        "Reply with ONLY a single JSON object, no prose before or after, single-line "
        "reason/evidence:\n"
        '{"disposition": "retry_fix|halt_feature|halt_epic|blocked_external", '
        '"reason": "<one line>", '
        '"evidence": "<missing external fact if blocked_external, else null>"}'
        % (epic_id, feature_id, attempt, challenge_id, ev))
    return _bound_text(body, CODEX_PROMPT_MAX_CHARS)


# --------------------------------------------------------------------------------------- #
# B2 — Codex read-only poll through the shared timeout supervisor
# --------------------------------------------------------------------------------------- #

def build_codex_invocation(model, prompt, stdout_path, stderr_path, lastmsg_path,
                            timeout_sec, max_output_bytes,
                            codex_bin=None, supervisor_path=None, python_bin=None):
    """Build the EXACT argv for the supervised Codex poll. codex_bin / supervisor_path /
    python_bin are the injectable seam selftests use to substitute a fake codex/supervisor."""
    codex_bin = codex_bin or os.environ.get("COMPOUND_V_ARBITER_CODEX_BIN") or "codex"
    python_bin = python_bin or sys.executable or "python3"
    supervisor_path = supervisor_path or os.environ.get("COMPOUND_V_ARBITER_SUPERVISOR") or \
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "compound-v-run-with-timeout.py")
    codex_argv = [codex_bin, "exec", "--sandbox", "read-only", "--skip-git-repo-check",
                  "--model", model, "-c", "model_reasoning_effort=high", "--json",
                  "--output-last-message", lastmsg_path, prompt]
    return ([python_bin, supervisor_path,
             "--timeout", str(int(timeout_sec)),
             "--max-output-bytes", str(int(max_output_bytes)),
             "--stdout", stdout_path, "--stderr", stderr_path, "--"]
            + codex_argv)


def _parse_codex_verdict(raw):
    """STRICT parse (Finding 8): after removing ONLY exact-match `codex_hooks is deprecated`
    lines, the ENTIRE remaining message must be exactly one schema-valid JSON object — no
    leading/trailing prose, no multiple objects, no `rfind('{')` salvage. reason/evidence
    must be single-line strings (evidence may be null). Returns None on ANY deviation (never
    fabricates a disposition)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    kept = [ln for ln in raw.splitlines() if ln.strip() != DEPRECATION_LINE]
    text = "\n".join(kept).strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    disposition = data.get("disposition")
    if disposition not in DISPOSITIONS:
        return None
    reason = data.get("reason", "")
    evidence = data.get("evidence")
    if reason is None:
        reason = ""
    if not isinstance(reason, str) or "\n" in reason or "\r" in reason:
        return None
    if evidence is not None and (not isinstance(evidence, str) or "\n" in evidence or "\r" in evidence):
        return None
    return {"disposition": disposition, "reason": reason, "evidence": evidence}


def poll_codex(model, prompt, timeout_sec=DEFAULT_CODEX_TIMEOUT_SEC,
               max_output_bytes=DEFAULT_MAX_OUTPUT_BYTES, codex_bin=None,
               supervisor_path=None, python_bin=None, env=None):
    """Run the Codex advisory poll through the supervisor inside a self-cleaning temp dir.
    Returns (verdict_dict|None, drop_reason|None). NEVER a fabricated halt vote: drops on a
    nonzero supervisor exit, a missing/symlinked/oversized --output-last-message (bounded via
    _read_capped_regular, which DELETES an oversized artifact), an unparseable message, or a
    field that fails re-redaction."""
    with tempfile.TemporaryDirectory(prefix="compound-v-arbiter-") as work_dir:
        stdout_path = os.path.join(work_dir, "codex_stdout.jsonl")
        stderr_path = os.path.join(work_dir, "codex_stderr.log")
        lastmsg_path = os.path.join(work_dir, "codex_lastmsg.txt")
        argv = build_codex_invocation(model, prompt, stdout_path, stderr_path, lastmsg_path,
                                       timeout_sec, max_output_bytes, codex_bin=codex_bin,
                                       supervisor_path=supervisor_path, python_bin=python_bin)
        try:
            proc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, env=env)
        except OSError as e:
            return None, "failed to launch the codex poll supervisor: %s" % e
        if proc.returncode != 0:
            return None, ("codex poll supervisor exited %d — dropped, not a fabricated halt "
                          "vote" % proc.returncode)
        # lastmsg_path is inside our OWN private TemporaryDirectory, so deleting an oversized
        # one is safe (never touches a user-owned file — Finding 4/#8).
        raw, err = _read_capped_regular(lastmsg_path, max_output_bytes, delete_oversized=True)
        if raw is None:
            return None, "codex --output-last-message unusable (%s) — dropped" % err
        verdict = _parse_codex_verdict(raw)
        if verdict is None:
            return None, "codex reply was not a strict single-object verdict — dropped"
        fields = sanitize_ballot_fields(verdict["reason"], verdict["evidence"])
        if fields is None:
            return None, "codex reply failed re-redaction/field checks — dropped (fail-closed)"
        reason, evidence = fields
        return {"disposition": verdict["disposition"], "reason": reason, "evidence": evidence}, None


# --------------------------------------------------------------------------------------- #
# B3 — Claude ballot validation (+ re-redaction)
# --------------------------------------------------------------------------------------- #

def load_claude_ballot(path, epic_id, feature_id, attempt, challenge_id):
    """Validate the ballot's 4-tuple against the CURRENT state + issued challenge, read via
    O_NOFOLLOW+fstat+cap, re-redact its fields. Returns (ballot|None, drop_reason|None).
    (The CALLER only invokes this when the persisted challenge is valid — a stale/consumed
    challenge drops the whole panel before we get here, Finding 4.)"""
    if not path:
        return None, "no --claude-ballot given"
    raw, err = _read_capped_regular(path, BALLOT_FILE_MAX_BYTES)
    if raw is None:
        return None, "claude ballot unreadable (%s)" % err
    try:
        data = json.loads(raw)
    except ValueError as e:
        return None, "claude ballot is not valid JSON: %s" % e
    if not isinstance(data, dict):
        return None, "claude ballot is not a JSON object"
    if (data.get("epic_id") != epic_id or data.get("feature") != feature_id
            or data.get("attempt") != attempt or data.get("challenge_id") != challenge_id):
        return None, "claude ballot 4-tuple mismatch (stale/wrong-feature/wrong-attempt)"
    disposition = data.get("disposition")
    if disposition not in DISPOSITIONS:
        # NB: do NOT interpolate the untrusted `disposition` value into the reason — it
        # could carry a secret that would then be retained/emitted (Finding 3/#7).
        return None, "claude ballot has an invalid/missing disposition"
    fields = sanitize_ballot_fields(data.get("reason", ""), data.get("evidence"))
    if fields is None:
        return None, "claude ballot fields failed re-redaction/checks (fail-closed)"
    reason, evidence = fields
    return {"source": "claude", "family": "Claude", "model": "claude", "valid": True,
            "disposition": disposition, "reason": reason, "evidence": evidence}, None


# --------------------------------------------------------------------------------------- #
# B4 — collapse + aggregation truth table
# --------------------------------------------------------------------------------------- #

def _collapse_same_family(ballots):
    out = [dict(b) for b in ballots]
    for b in out:
        b["counted"] = bool(b.get("valid"))
    by_family = {}
    for b in out:
        if b["counted"]:
            by_family.setdefault(b.get("family"), []).append(b)
    for fam, group in by_family.items():
        if len(group) <= 1:
            continue
        ranked = sorted(group, key=lambda b: CONSERVATISM_RANK.get(b.get("disposition"), -1))
        winner = ranked[-1]
        for b in group:
            if b is not winner:
                b["counted"] = False
                b["collapse_note"] = ("same-family (%s) collapse: %r deferred to %r"
                                       % (fam, b.get("disposition"), winner.get("disposition")))
    return out


def aggregate_dispositions(valid_ballots):
    """The complete deterministic truth table (B4). `valid_ballots` are one-per-family
    (counted=True). Returns (disposition, confirmed, reason).

    Finding 7: when there is NO valid ballot from a KNOWN non-Claude external family, both
    halt_epic AND blocked_external are masked to halt_feature (the Claude-only / no-external
    fallback caps to retry_fix|halt_feature; a lone Claude blocked_external cannot survive)."""
    external_present = any(b.get("family") in _EXTERNAL_CONFIRMING for b in valid_ballots)

    def _cap_no_external(d, reason):
        if not external_present and d in ("halt_epic", "blocked_external"):
            return "halt_feature", (reason + "; no external-family ballot -> capped to halt_feature")
        return d, reason

    n = len(valid_ballots)
    if n == 0:
        return "halt_feature", False, "no valid ballots (parse-fail/errored/absent) -- conservative default"
    if n == 1:
        d = valid_ballots[0]["disposition"]
        reason = "single valid ballot"
        if d == "halt_epic":
            d, reason = "halt_feature", "single ballot cannot unilaterally halt_epic -> halt_feature"
        d, reason = _cap_no_external(d, reason)
        return d, False, reason

    retry_n = sum(1 for b in valid_ballots if b["disposition"] == "retry_fix")
    nonretry = [b for b in valid_ballots if b["disposition"] != "retry_fix"]
    nonretry_n = len(nonretry)

    if retry_n > nonretry_n:
        return "retry_fix", False, "retry_fix majority"
    if retry_n == nonretry_n:
        return "halt_feature", False, "tied retry/non-retry vote -- conservative halt_feature"

    nr_dispositions = {b["disposition"] for b in nonretry}
    if len(nr_dispositions) == 1:
        d = next(iter(nr_dispositions))
        reason = "non-retry majority, unanimous agreement on %r" % d
    else:
        d, reason = "halt_feature", ("non-retry majority but disagreement among them -- "
                                     "conservative halt_feature")

    confirmed = False
    if d == "blocked_external":
        confirming = {b["family"] for b in nonretry
                      if b["disposition"] == "blocked_external" and b["family"] in _EXTERNAL_CONFIRMING}
        confirmed = len(confirming) >= 2 and retry_n == 0
        if not confirmed:
            reason += (" (SUSPECTED, not confirmed: needs >=2 distinct KNOWN external families "
                       "with no retry_fix dissent)")

    d, reason = _cap_no_external(d, reason)
    return d, confirmed, reason


def _can_retry(state, feature_id):
    feat = _find_feature(state, feature_id)
    if feat is None:
        return True, None
    attempts = feat.get("attempts", 0)
    autonomy = state.get("autonomy") if isinstance(state.get("autonomy"), dict) else {}
    cap = autonomy.get("max_attempts_per_feature", 2)
    if cap is None:
        return True, None
    return attempts < cap, cap


# --------------------------------------------------------------------------------------- #
# Audit rotation (count AND bytes)
# --------------------------------------------------------------------------------------- #

def _rotate_by(arbiter_fd, match, count_cap, byte_cap):
    """Delete the oldest matching files until BOTH count_cap and byte_cap hold. `match(name)`
    selects which files participate."""
    try:
        names = os.listdir(arbiter_fd)
    except OSError:
        return
    entries = []
    total = 0
    for nm in names:
        if not match(nm):
            continue
        try:
            st = os.stat(nm, dir_fd=arbiter_fd, follow_symlinks=False)
        except OSError:
            continue
        if not stat.S_ISREG(st.st_mode):
            continue
        entries.append((st.st_mtime, nm, st.st_size))
        total += st.st_size
    entries.sort()
    i = 0
    count = len(entries)
    while i < len(entries) and (count > count_cap or total > byte_cap) and count > 1:
        _, nm, sz = entries[i]
        try:
            os.unlink(nm, dir_fd=arbiter_fd)
            total -= sz
            count -= 1
        except OSError:
            pass
        i += 1


def _rotate_audit(arbiter_fd, count_cap=AUDIT_ROTATE_COUNT, byte_cap=AUDIT_ROTATE_BYTES):
    # Audit + rejected files (`*.json`, excluding the `*.challenge.json` records).
    _rotate_by(arbiter_fd, lambda nm: nm.endswith(".json") and not nm.endswith(".challenge.json"),
               count_cap, byte_cap)


def _rotate_challenge(arbiter_fd, count_cap=CHALLENGE_ROTATE_COUNT, byte_cap=AUDIT_ROTATE_BYTES):
    # Bounded retention for the challenge issuance records too (Finding 5/#9).
    _rotate_by(arbiter_fd, lambda nm: nm.endswith(".challenge.json"), count_cap, byte_cap)


def _finalize_result(result):
    """Produce the ONE object that is BOTH printed to the caller AND persisted to the audit
    JSON — they must be byte-identical (Finding 5/#9). Caps every retained field length,
    trims ballot detail if the serialized blob exceeds AUDIT_MAX_ONE_BYTES, and — if it is
    STILL over after trimming — emits a bounded stub that keeps only the report-critical
    fields."""
    r = dict(result)
    if isinstance(r.get("reason"), str):
        r["reason"] = r["reason"][:REASON_MAX_CHARS]
    if isinstance(r.get("evidence"), str):
        r["evidence"] = r["evidence"][:FIELD_MAX_CHARS]
    capped = []
    for b in r.get("ballots", []):
        b2 = dict(b)
        if isinstance(b2.get("reason"), str):
            b2["reason"] = b2["reason"][:REASON_MAX_CHARS]
        if isinstance(b2.get("evidence"), str):
            b2["evidence"] = b2["evidence"][:FIELD_MAX_CHARS]
        capped.append(b2)
    r["ballots"] = capped

    if len(json.dumps(r).encode("utf-8")) > AUDIT_MAX_ONE_BYTES:
        r["evidence"] = None
        r["ballots"] = [dict(b, reason="", evidence=None) for b in r["ballots"]]
        r["audit_trimmed"] = True
    if len(json.dumps(r).encode("utf-8")) > AUDIT_MAX_ONE_BYTES:
        # round-3 #2: bound EVERY string carried into the stub (even an oversized
        # challenge_id/epic_id/feature/audit_path copied from the caller) so the stub itself
        # can never exceed the cap regardless of which field was oversized.
        def _b(v):
            return _cap_bytes_with_marker(v, MAX_ID_LEN) if isinstance(v, str) else v
        fams = r.get("families_present", [])
        agrees = r.get("families_agreeing", [])
        r = {
            "disposition": _b(r.get("disposition")), "confirmed": r.get("confirmed"),
            "reason": "audit exceeded the size cap — stubbed to report-critical fields",
            "evidence": None, "ballots": [],
            "families_present": fams if isinstance(fams, list) and len(fams) <= 8 else [],
            "families_agreeing": agrees if isinstance(agrees, list) and len(agrees) <= 8 else [],
            "challenge_id": _b(r.get("challenge_id")), "epic_id": _b(r.get("epic_id")),
            "feature": _b(r.get("feature")), "attempt": r.get("attempt"),
            "audit_path": _b(r.get("audit_path")), "recorded_at": _b(r.get("recorded_at")),
            "audit_trimmed": True, "audit_stubbed": True,
        }
        # Absolute floor: if a pathological input still overflows, drop to a minimal object
        # that is guaranteed under the cap (round-3 #2: NO finalized object exceeds the cap).
        if len(json.dumps(r).encode("utf-8")) > AUDIT_MAX_ONE_BYTES:
            r = {"disposition": "halt_feature", "confirmed": False,
                 "reason": "audit stub overflow — minimal object",
                 "evidence": None, "ballots": [], "families_present": [],
                 "families_agreeing": [], "challenge_id": None, "epic_id": None,
                 "feature": None, "attempt": r.get("attempt") if isinstance(r.get("attempt"), int) else None,
                 "audit_path": None, "recorded_at": None,
                 "audit_trimmed": True, "audit_stubbed": True}
    return r


def _audit_tuple_matches(audit, epic_id, feature, attempt, challenge):
    return (isinstance(audit, dict)
            and audit.get("epic_id") == epic_id and audit.get("feature") == feature
            and audit.get("attempt") == attempt and audit.get("challenge_id") == challenge)


def _reemit_persisted(arbiter_fd, audit_name, epic_id, feature, attempt, challenge):
    """Re-emit a previously-persisted audit for an idempotent replay: read its RAW bytes,
    validate the parsed tuple, and if it matches write those EXACT bytes to stdout (round-3
    #3 — printed == persisted). Returns True on a successful re-emit, else False (caller then
    falls back to a conservative result or runs the panel)."""
    raw = _read_text_at(arbiter_fd, audit_name, AUDIT_MAX_ONE_BYTES)
    if raw is None:
        return False
    try:
        prior = json.loads(raw)
    except ValueError:
        return False
    if not _audit_tuple_matches(prior, epic_id, feature, attempt, challenge):
        return False
    sys.stdout.write(raw)
    return True


# --------------------------------------------------------------------------------------- #
# CLI: prepare
# --------------------------------------------------------------------------------------- #

def cmd_prepare(args, p):
    if not args.feature:
        p.error("--prepare needs --feature")
    if args.attempt is None:
        p.error("--prepare needs --attempt <int>")
    state = _read_state(args.state)
    epic_id = state["epic_id"]
    if not _id_ok(args.feature):
        raise ArbiterError("invalid --feature id: %r" % (args.feature,))
    feat = _find_feature(state, args.feature)
    if feat is None:
        raise ArbiterError("no feature %r in state" % args.feature)

    current = feat.get("attempts", 0)
    if args.attempt != current:
        raise ArbiterError("--attempt %r must equal the feature's current persisted attempts "
                           "%r (issuance is monotonic; you cannot pre-issue a future attempt "
                           "or re-issue a past one)" % (args.attempt, current))

    epic_dir = validate_epic_dir(args.state, epic_id)
    now_s = _now_iso(_resolve_now(args.now))
    challenge_name = "%s-%s.challenge.json" % (args.feature, args.attempt)

    arbiter_fd = open_arbiter_dir_fd(epic_dir, create=True)
    try:
        key = get_challenge_key(arbiter_fd, injected=args.challenge_key)
        challenge_id = compute_challenge_id(key, epic_id, args.feature, args.attempt)

        # Finding 6/#3: distinguish a truly-absent record from an EXISTING-but-unreadable one.
        # An unreadable/inconsistent record must FAIL CLOSED — never silently overwrite it
        # with a fresh `issued` record (which could resurrect a consumed challenge).
        # (v2.11) a concurrent compare-and-swap between this read and the write below is out
        # of the single-user threat model.
        rstatus, existing = _probe_record(arbiter_fd, challenge_name, CHALLENGE_RECORD_MAX_BYTES)
        if rstatus == "unreadable":
            raise ArbiterError("an existing challenge record for %s attempt %s is unreadable/"
                               "inconsistent — refusing to overwrite it (fail closed)"
                               % (args.feature, args.attempt))
        if rstatus == "ok":
            st = existing.get("status")
            tuple_ok = (existing.get("challenge_id") == challenge_id
                        and existing.get("epic_id") == epic_id
                        and existing.get("feature") == args.feature
                        and existing.get("attempt") == args.attempt)
            if not tuple_ok:
                raise ArbiterError("an existing challenge record for %s attempt %s has an "
                                   "inconsistent tuple — refusing to overwrite it (fail closed)"
                                   % (args.feature, args.attempt))
            if st in ("in_progress", "consumed"):
                raise ArbiterError("challenge for %s attempt %s is already %s — cannot re-issue "
                                   "(anti-replay)" % (args.feature, args.attempt, st))
            if st == "issued":
                print(json.dumps({"challenge_id": challenge_id, "epic_id": epic_id,
                                  "feature": args.feature, "attempt": args.attempt,
                                  "issued_at": existing.get("issued_at", now_s),
                                  "prompt": existing.get("claude_prompt", "")}))
                return 0

        prompt = _build_claude_prompt(epic_id, args.feature, args.attempt, challenge_id, feat)
        record = {"epic_id": epic_id, "feature": args.feature, "attempt": args.attempt,
                  "challenge_id": challenge_id, "issued_at": now_s, "status": "issued",
                  "consumed_at": None, "claude_prompt": prompt}
        _write_json_at(arbiter_fd, challenge_name, record)
        _rotate_challenge(arbiter_fd)
        # Give the driver a per-attempt evidence home (contained, symlink-checked on read).
        try:
            os.mkdir("%s-%s" % (args.feature, args.attempt), 0o755, dir_fd=arbiter_fd)
        except FileExistsError:
            pass
        print(json.dumps({"challenge_id": challenge_id, "epic_id": epic_id, "feature": args.feature,
                          "attempt": args.attempt, "issued_at": now_s, "prompt": prompt}))
        return 0
    finally:
        os.close(arbiter_fd)


# --------------------------------------------------------------------------------------- #
# CLI: classify
# --------------------------------------------------------------------------------------- #

def _conservative_dropped_result(epic_id, feature, attempt, challenge, reason):
    return {"disposition": "halt_feature", "confirmed": False, "reason": reason,
            "evidence": None, "ballots": [], "families_present": [], "families_agreeing": [],
            "challenge_id": challenge, "epic_id": epic_id, "feature": feature, "attempt": attempt,
            "audit_path": None}


def cmd_classify(args, p):
    if not args.feature:
        p.error("--classify needs --feature")
    if not args.challenge:
        p.error("--classify needs --challenge <id>")
    # round-3 #2: length-bound --challenge at the validation boundary. It is retained in the
    # (rejected) result and copied into the fallback stub, so an unbounded value could push a
    # finalized object over AUDIT_MAX_ONE_BYTES. A legitimate id is "ch-"+16 hex = 19 chars;
    # reject anything longer than MAX_ID_LEN like any other overlong id.
    if len(args.challenge) > MAX_ID_LEN:
        raise ArbiterError("--challenge id is too long (max %d chars)" % MAX_ID_LEN)
    state = _read_state(args.state)
    epic_id = state["epic_id"]
    if not _id_ok(args.feature):
        raise ArbiterError("invalid --feature id: %r" % (args.feature,))
    feat = _find_feature(state, args.feature)
    if feat is None:
        raise ArbiterError("no feature %r in state" % args.feature)

    attempt = feat.get("attempts", 0)
    epic_dir = validate_epic_dir(args.state, epic_id)
    now_s = _now_iso(_resolve_now(args.now))
    max_output_bytes = args.max_output_bytes
    challenge_name = "%s-%s.challenge.json" % (args.feature, attempt)
    audit_name = "%s-%s.json" % (args.feature, attempt)

    arbiter_fd = open_arbiter_dir_fd(epic_dir, create=True)
    try:
        key = get_challenge_key(arbiter_fd, injected=args.challenge_key)
        expected = compute_challenge_id(key, epic_id, args.feature, attempt)
        rstatus, record = _probe_record(arbiter_fd, challenge_name, CHALLENGE_RECORD_MAX_BYTES)

        tuple_ok = (rstatus == "ok"
                    and args.challenge == expected == record.get("challenge_id")
                    and record.get("epic_id") == epic_id
                    and record.get("feature") == args.feature
                    and record.get("attempt") == attempt)
        status = record.get("status") if rstatus == "ok" else None

        # ---- Finding 4: a stale/invalid/consumed/unreadable challenge gates the WHOLE panel.
        # Finding 1/#2: a REJECTED challenge must NEVER be persisted to the CANONICAL result
        # filename (that would clobber a previously-consumed valid audit, so a later correct
        # replay would emit this attacker-triggered conservative verdict). Write a drop event
        # to a clearly-separate `.rejected.json` path only.
        if not tuple_ok:
            result = _conservative_dropped_result(
                epic_id, args.feature, attempt, args.challenge,
                "challenge invalid/missing/stale/unreadable for the current attempt -- panel "
                "dropped before any model call")
            rejected_name = "%s-%s.rejected.json" % (args.feature, attempt)
            try:
                rej_path = _contained_audit_path(epic_dir, rejected_name)
                final = _finalize_result(dict(result, audit_path=rej_path, recorded_at=now_s))
                blob = _serialize(final)                      # round-3 #3: one serialization
                _write_text_at(arbiter_fd, rejected_name, blob)
                _rotate_audit(arbiter_fd)
            except (ArbiterError, OSError) as e:
                _log("could not record the rejection event: %s" % e)
                blob = _serialize(_finalize_result(dict(result, recorded_at=now_s)))
            sys.stdout.write(blob)                            # printed == persisted bytes
            return 0
        if status == "consumed":
            # Idempotent replay: re-emit the persisted audit — but only after validating its
            # tuple, so a swapped/foreign audit file cannot be re-emitted (Finding 1/#2).
            # round-3 #3: re-emit the RAW persisted bytes so printed == persisted exactly.
            if _reemit_persisted(arbiter_fd, audit_name, epic_id, args.feature, attempt, args.challenge):
                _log("challenge already consumed — re-emitting the persisted audit (idempotent)")
                return 0
            result = _conservative_dropped_result(
                epic_id, args.feature, attempt, args.challenge,
                "challenge consumed but its audit is missing/inconsistent -- panel dropped")
            sys.stdout.write(_serialize(_finalize_result(dict(result, recorded_at=now_s))))
            return 0

        # ---- crash-recovery re-emit, not re-egress (Finding 7/#1) -------------------------
        # If the record is already `in_progress` (a prior classify claimed it) AND a matching
        # audit already exists, re-emit THAT — never a second Codex call. Only call the model
        # when there is no prior audit. (v2.11) the concurrent compare-and-swap race between
        # two live drivers is out of the single-user threat model.
        if status == "in_progress":
            if _reemit_persisted(arbiter_fd, audit_name, epic_id, args.feature, attempt, args.challenge):
                _log("challenge in_progress with an existing audit — re-emitting it (no re-egress)")
                return 0
            # else: crashed before writing an audit — fall through and run the panel.
        elif status == "issued":
            # durable issued -> in_progress BEFORE any model call
            record["status"] = "in_progress"
            record["in_progress_at"] = now_s
            try:
                _write_json_at(arbiter_fd, challenge_name, record)
            except OSError as e:
                raise ArbiterError("could not durably claim the challenge (issued->in_progress): "
                                   "%s" % e)
        else:
            raise ArbiterError("challenge in an unexpected status %r" % (status,))

        # ---- evidence: contained read + redact BEFORE egress ------------------------------
        evidence_text = None
        if args.evidence_file:
            try:
                attempt_fd = open_attempt_dir_fd(arbiter_fd, args.feature, attempt)
            except OSError as e:
                attempt_fd = None
                _log("evidence attempt dir unavailable (%s) — evidence omitted" % e)
            if attempt_fd is not None:
                try:
                    read_cap = max(200000, max_output_bytes * 4)
                    raw, err = read_contained_evidence(attempt_fd, args.evidence_file, read_cap)
                finally:
                    os.close(attempt_fd)
                if raw is None:
                    _log("evidence rejected: %s" % err)
                else:
                    evidence_text = redact(raw, max_output_bytes)
                    if evidence_text is None:
                        _log("secret redaction could not complete -- evidence OMITTED (fail-closed)")

        ballots = []

        # ---- Codex ballot -----------------------------------------------------------------
        caps = load_capabilities(args.capabilities_path)
        if codex_available(caps):
            model = resolve_codex_model(config_path=args.config,
                                        explicit_model=args.explicit_codex_model)
            family = model_family(model)
            codex_prompt = _build_codex_prompt(epic_id, args.feature, attempt, args.challenge,
                                               evidence_text)
            verdict, drop_reason = poll_codex(
                model, codex_prompt, timeout_sec=args.codex_timeout,
                max_output_bytes=max_output_bytes, codex_bin=args.codex_bin,
                supervisor_path=args.supervisor_path)
            if verdict is None:
                _log("codex ballot dropped: %s" % drop_reason)
                ballots.append({"source": "codex", "family": family, "model": model, "valid": False,
                                "disposition": None, "reason": _sanitize_diagnostic(drop_reason),
                                "evidence": None})
            else:
                ballots.append({"source": "codex", "family": family, "model": model, "valid": True,
                                "disposition": verdict["disposition"], "reason": verdict["reason"],
                                "evidence": verdict["evidence"]})
        else:
            ballots.append({"source": "codex", "family": None, "model": None, "valid": False,
                            "disposition": None,
                            "reason": "codex unavailable (capabilities absent/false) -- Claude-only",
                            "evidence": None})

        # ---- Claude ballot ----------------------------------------------------------------
        if args.claude_ballot:
            cb, reason = load_claude_ballot(args.claude_ballot, epic_id, args.feature, attempt,
                                            args.challenge)
            if cb is None:
                _log("claude ballot dropped: %s" % reason)
                ballots.append({"source": "claude", "family": "Claude", "model": None,
                                "valid": False, "disposition": None,
                                "reason": _sanitize_diagnostic(reason), "evidence": None})
            else:
                ballots.append(cb)
        else:
            ballots.append({"source": "claude", "family": "Claude", "model": None, "valid": False,
                            "disposition": None, "reason": "no --claude-ballot provided",
                            "evidence": None})

        collapsed = _collapse_same_family(ballots)
        valid_counted = [b for b in collapsed if b.get("counted")]
        disposition, confirmed, agg_reason = aggregate_dispositions(valid_counted)

        masked_note = None
        if disposition == "retry_fix":
            can_retry, cap = _can_retry(state, args.feature)
            if not can_retry:
                disposition = "halt_feature"
                masked_note = ("retry_fix masked to halt_feature: feature is at/past its retry "
                               "cap (%r)" % (cap,))

        result_evidence = None
        if disposition == "blocked_external":
            for b in valid_counted:
                if b.get("evidence"):
                    result_evidence = b["evidence"]
                    break

        families_present = sorted({b.get("family") for b in valid_counted if b.get("family")})
        families_agreeing = sorted({b.get("family") for b in valid_counted
                                    if b.get("family") and b.get("disposition") == disposition})
        reason_text = agg_reason if not masked_note else ("%s; %s" % (agg_reason, masked_note))

        # ---- Finding 10: audit_path computed FIRST, then the FROZEN complete result -------
        audit_path = _contained_audit_path(epic_dir, audit_name)
        result = {
            "disposition": disposition, "confirmed": bool(confirmed), "reason": reason_text,
            "evidence": result_evidence, "ballots": collapsed,
            "families_present": families_present, "families_agreeing": families_agreeing,
            "challenge_id": args.challenge, "epic_id": epic_id, "feature": args.feature,
            "attempt": attempt, "audit_path": audit_path, "recorded_at": now_s,
        }
        # Finding 5/#9 + round-3 #3: finalize ONCE and serialize ONCE — the exact bytes we
        # persist are the exact bytes we print.
        final = _finalize_result(result)
        blob = _serialize(final)
        _write_text_at(arbiter_fd, audit_name, blob)
        _rotate_audit(arbiter_fd)

        # ---- durable in_progress -> consumed; do NOT report success if this fails ---------
        record["status"] = "consumed"
        record["consumed_at"] = now_s
        try:
            _write_json_at(arbiter_fd, challenge_name, record)
        except OSError as e:
            raise ArbiterError("classified but could NOT durably record consumption (%s) — "
                               "not reporting success; replay will recover" % e)

        sys.stdout.write(blob)
        return 0
    finally:
        os.close(arbiter_fd)


def _contained_audit_path(epic_dir, audit_name):
    """The absolute audit path, asserted realpath-contained under <epic_dir>/arbiter/.
    epic_dir is a realpath and the arbiter dir fd was opened O_NOFOLLOW, so this is a
    belt-and-suspenders string check for the persisted `audit_path` field.

    Finding 9/#5 (scoped): the final-component symlink and the arbiter-dir symlink are both
    defended (O_NOFOLLOW on each). A full anchored openat walk of every epic-dir ANCESTOR —
    to defeat an ancestor swapped AFTER realpath validation — is out of the single-user
    threat model (the epic tree is user-owned; no second actor swaps a parent mid-call) and
    is a v2.11 concern; we keep the O_NOFOLLOW-final-component + arbiter-dir protection."""
    base = os.path.join(epic_dir, "arbiter")
    path = os.path.join(base, audit_name)
    base_real = os.path.realpath(base)
    resolved = os.path.realpath(path)
    if resolved != base_real and not resolved.startswith(base_real + os.sep):
        raise ArbiterError("audit path escapes the arbiter dir: %s" % path)
    return path


# --------------------------------------------------------------------------------------- #
# Selftest
# --------------------------------------------------------------------------------------- #

def _write_fake_codex_stub(path):
    script = (
        "#!/bin/sh\n"
        'outfile=""\nprev=""\n'
        'for a in "$@"; do\n'
        '  if [ "$prev" = "--output-last-message" ]; then outfile="$a"; fi\n'
        '  prev="$a"\ndone\n'
        'if [ -n "$outfile" ] && [ -n "$FAKE_CODEX_SRC" ] && [ -f "$FAKE_CODEX_SRC" ]; then\n'
        '  cp "$FAKE_CODEX_SRC" "$outfile"\nfi\n'
        'if [ -n "$FAKE_CODEX_EXIT" ]; then exit "$FAKE_CODEX_EXIT"; fi\nexit 0\n')
    with open(path, "w") as fh:
        fh.write(script)
    os.chmod(path, 0o755)


def _make_epic(tmproot, epic_id="epic1", attempts=1, status="failed"):
    epic_dir = os.path.join(tmproot, "docs", "superpowers", "execution", "epics", epic_id)
    os.makedirs(epic_dir)
    state_path = os.path.join(epic_dir, "epic-state.json")
    state = {"epic_id": epic_id, "title": "T", "status": "running",
             "autonomy": {"stance": "marathon", "max_attempts_per_feature": 2},
             "features": [{"id": "featA", "title": "Feature A", "depends_on": [], "status": status,
                           "attempts": attempts, "last_error": "boom", "disposition": None}]}
    with open(state_path, "w") as fh:
        json.dump(state, fh)
    return epic_dir, state_path, state


def _selftest():
    ok = 0
    fail = 0

    def check(name, cond):
        nonlocal ok, fail
        if cond:
            ok += 1
        else:
            fail += 1
            print("  FAIL %s" % name)

    import io
    import shutil
    import tempfile as _tempfile
    from contextlib import redirect_stdout

    NOW = "2026-07-12T00:00:00+00:00"
    FIXED_KEY = "test-fixed-key-0000"

    class _FakeArgs(object):
        pass

    def _args(**over):
        a = _FakeArgs()
        a.state = None
        a.feature = None
        a.attempt = None
        a.challenge = None
        a.evidence_file = None
        a.claude_ballot = None
        a.now = NOW
        a.challenge_key = FIXED_KEY
        a.capabilities_path = os.path.join(_tempfile.gettempdir(), "no-such-caps.json")
        a.config = None
        a.explicit_codex_model = None
        a.codex_timeout = 10
        a.max_output_bytes = 5000
        a.codex_bin = None
        a.supervisor_path = None
        for k, v in over.items():
            setattr(a, k, v)
        return a

    class _P(object):
        def error(self, msg):
            raise SystemExit(msg)

    p = _P()

    def run_cmd(fn, a):
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                rc = fn(a, p)
        except ArbiterError as e:
            return None, "ERR:" + str(e), 1
        out = buf.getvalue().strip()
        return (json.loads(out) if out else None), None, rc

    def run_cmd_raw(fn, a):
        """Like run_cmd but returns the UNSTRIPPED raw stdout string (for byte-for-byte
        printed==persisted comparisons)."""
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                rc = fn(a, p)
        except ArbiterError as e:
            return None, "ERR:" + str(e), 1
        return buf.getvalue(), None, rc

    def _run_main_expect_error(argv):
        """Drive main() and report whether it produced an error (argparse SystemExit, or a
        nonzero return). Used for the argparse-boundary numeric-bound checks."""
        buf, ebuf = io.StringIO(), io.StringIO()
        try:
            from contextlib import redirect_stderr
            with redirect_stdout(buf), redirect_stderr(ebuf):
                rc = main(argv)
            return rc != 0
        except SystemExit as e:
            return (e.code or 0) != 0

    # =================================================================================== #
    # B1 — capabilities (strict booleans) + family map
    # =================================================================================== #
    check("B1: absent caps file -> {}", load_capabilities(os.path.join(_tempfile.gettempdir(), "nope.json")) == {})
    d = _tempfile.mkdtemp()
    try:
        def caps_file(name, obj):
            pth = os.path.join(d, name)
            with open(pth, "w") as fh:
                json.dump(obj, fh)
            return pth
        check("B1: available+verified -> usable",
              codex_available(load_capabilities(caps_file("g.json", {"codex": {"available": True, "exec_flags_verified": True}}))))
        check("B1: exec_flags_verified false -> unusable",
              not codex_available(load_capabilities(caps_file("h.json", {"codex": {"available": True, "exec_flags_verified": False}}))))
        # Finding 9: strict `is True` — a truthy STRING must not enable Codex.
        check("B1/F9: string 'true' does NOT enable codex (strict is True)",
              not codex_available(load_capabilities(caps_file("s.json", {"codex": {"available": "true", "exec_flags_verified": "true"}}))))
        check("B1/F9: int 1 does NOT enable codex (strict is True)",
              not codex_available(load_capabilities(caps_file("i.json", {"codex": {"available": 1, "exec_flags_verified": 1}}))))
        check("B1: absent codex key -> unusable",
              not codex_available(load_capabilities(caps_file("n.json", {"context7": {"available": True}}))))
        with open(os.path.join(d, "m.json"), "w") as fh:
            fh.write("{not json")
        check("B1: malformed JSON -> unusable", not codex_available(load_capabilities(os.path.join(d, "m.json"))))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    check("B1 family: gpt-5.6-sol -> GPT", model_family("gpt-5.6-sol") == "GPT")
    check("B1 family: Gemini -> Gemini", model_family("Gemini 3.1 Pro (High)") == "Gemini")
    check("B1 family: claude/opus/sonnet -> Claude",
          model_family("claude-opus-4") == "Claude" and model_family("opus") == "Claude" and model_family("sonnet") == "Claude")
    check("B1 family: grok -> Grok", model_family("grok-3") == "Grok")
    check("B1 family: auto/unknown/empty -> unknown",
          model_family("auto") == "unknown" and model_family("x") == "unknown" and model_family(None) == "unknown")

    # =================================================================================== #
    # B2/F8 — exact invocation + STRICT parse (no rfind salvage)
    # =================================================================================== #
    argv = build_codex_invocation("gpt-5.6-sol", "PROMPT", "/tmp/o", "/tmp/e", "/tmp/l",
                                   90, 20000, codex_bin="codex",
                                   supervisor_path="/x/compound-v-run-with-timeout.py",
                                   python_bin="/usr/bin/python3")
    check("B2: exact supervised codex invocation shape", argv == [
        "/usr/bin/python3", "/x/compound-v-run-with-timeout.py", "--timeout", "90",
        "--max-output-bytes", "20000", "--stdout", "/tmp/o", "--stderr", "/tmp/e", "--",
        "codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--model",
        "gpt-5.6-sol", "-c", "model_reasoning_effort=high", "--json", "--output-last-message",
        "/tmp/l", "PROMPT"])

    check("F8: clean single-object verdict parses",
          _parse_codex_verdict('{"disposition":"retry_fix","reason":"flaky"}')["disposition"] == "retry_fix")
    check("F8: exact codex_hooks deprecation line skipped",
          _parse_codex_verdict("[features].codex_hooks is deprecated\n"
                               '{"disposition":"halt_feature","reason":"bug"}')["disposition"] == "halt_feature")
    check("F8: leading prose rejected (no rfind salvage)",
          _parse_codex_verdict('here is my answer {"disposition":"halt_epic"}') is None)
    check("F8: trailing prose rejected",
          _parse_codex_verdict('{"disposition":"halt_epic"} thanks!') is None)
    check("F8: two objects rejected",
          _parse_codex_verdict('{"disposition":"retry_fix"}{"disposition":"halt_epic"}') is None)
    check("F8: garbage prose rejected", _parse_codex_verdict("just prose") is None)
    check("F8: invalid disposition rejected", _parse_codex_verdict('{"disposition":"vibes"}') is None)
    check("F8: multiline reason rejected",
          _parse_codex_verdict('{"disposition":"retry_fix","reason":"line1\\nline2"}') is None)
    check("F8: non-string reason rejected",
          _parse_codex_verdict('{"disposition":"retry_fix","reason":123}') is None)
    check("F8: empty/None -> None", _parse_codex_verdict("") is None and _parse_codex_verdict(None) is None)

    # poll_codex through the REAL supervisor + fake codex stub
    wd = _tempfile.mkdtemp()
    try:
        stub = os.path.join(wd, "fake-codex.sh")
        _write_fake_codex_stub(stub)

        src_ok = os.path.join(wd, "ok.json")
        with open(src_ok, "w") as fh:
            fh.write('{"disposition":"retry_fix","reason":"flaky test"}')
        v, r = poll_codex("gpt-5.6-sol", "prompt", timeout_sec=10, max_output_bytes=5000,
                          codex_bin=stub, env=dict(os.environ, FAKE_CODEX_SRC=src_ok))
        check("B2: real supervisor + stub -> verdict", v is not None and v["disposition"] == "retry_fix")

        src_g = os.path.join(wd, "g.txt")
        with open(src_g, "w") as fh:
            fh.write("prose not json")
        v2, r2 = poll_codex("gpt-5.6-sol", "prompt", timeout_sec=10, max_output_bytes=5000,
                            codex_bin=stub, env=dict(os.environ, FAKE_CODEX_SRC=src_g))
        check("B2: garbled reply dropped, not a fabricated halt", v2 is None and "dropped" in r2)

        v4, r4 = poll_codex("gpt-5.6-sol", "prompt", timeout_sec=10, max_output_bytes=5000,
                            codex_bin=stub, env=dict(os.environ, FAKE_CODEX_EXIT="1"))
        check("B2: nonzero supervisor exit dropped", v4 is None)
    finally:
        shutil.rmtree(wd, ignore_errors=True)

    # Finding 6: an oversized retained artifact is DELETED (not left above cap).
    od = _tempfile.mkdtemp()
    try:
        big = os.path.join(od, "big.txt")
        with open(big, "w") as fh:
            fh.write("A" * 50000)
        # default (delete_oversized=False, e.g. a user file) -> dropped but NOT deleted
        text0, err0 = _read_capped_regular(big, 1000)
        check("F6: oversized user artifact -> dropped, NOT deleted (default)",
              text0 is None and os.path.exists(big))
        # private-temp path (delete_oversized=True) -> dropped AND deleted
        text, err = _read_capped_regular(big, 1000, delete_oversized=True)
        check("F6: oversized private artifact -> dropped", text is None and "oversized" in err)
        check("F6: oversized private artifact is DELETED from disk", not os.path.exists(big))
        small = os.path.join(od, "small.txt")
        with open(small, "w") as fh:
            fh.write("hi")
        t2, e2 = _read_capped_regular(small, 1000)
        check("F6: within-cap artifact read normally", t2 == "hi" and e2 is None)
        # symlinked artifact rejected by O_NOFOLLOW
        link = os.path.join(od, "link.txt")
        os.symlink(small, link)
        t3, e3 = _read_capped_regular(link, 1000)
        check("F6: symlinked artifact rejected (O_NOFOLLOW)", t3 is None)
    finally:
        shutil.rmtree(od, ignore_errors=True)

    # =================================================================================== #
    # F2 — redaction hardening (broadened patterns, fail-closed)
    # =================================================================================== #
    check("F2 redact: closed PEM private key",
          "[REDACTED:PRIVATE_KEY]" in redact("x\n-----BEGIN RSA PRIVATE KEY-----\nMII\n-----END RSA PRIVATE KEY-----\ny", 10000))
    check("F2 redact: PGP private key block",
          "[REDACTED:PRIVATE_KEY]" in redact("-----BEGIN PGP PRIVATE KEY BLOCK-----\nabc\n-----END PGP PRIVATE KEY BLOCK-----", 10000))
    check("F2 redact: UNCLOSED private-key block -> FAIL CLOSED (None -> omit whole evidence)",
          redact("secret start\n-----BEGIN RSA PRIVATE KEY-----\nMIInoEnd", 10000) is None)
    _folded = redact("Authorization: Bearer abc\n def.ghi\nHost: x", 10000)
    check("F2 redact: folded Authorization header (continuation line)",
          "abc" not in _folded and "def.ghi" not in _folded and "[REDACTED]" in _folded)
    check("F2 redact: short labelled secret CLIENT_SECRET=",
          "hunter2xyz" not in redact("CLIENT_SECRET=hunter2xyz", 10000))
    check("F2 redact: password= labelled",
          "p@ssw0rd" not in redact("password=p@ssw0rd", 10000))
    check("F2 redact: api_key: labelled",
          "sekret" not in redact("api_key: sekret", 10000))
    check("F2 redact: LABEL=\"...multiline...\" quoted secret",
          "toplinesecret" not in redact('token="toplinesecret\ncontinued"', 10000))
    _url = redact("https://user:pa:ss:wd@host/x", 10000)
    check("F2 redact: URL creds WITH ':' in password",
          "pa:ss:wd" not in _url and "[REDACTED]@host" in _url)
    check("F2 redact: JWT token",
          "[REDACTED:JWT]" in redact("t=eyJhbGciOi.eyJzdWIiOi.SIG_nature_here now", 10000))
    check("F2 redact: long opaque token",
          "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ABCD" not in redact("k=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ABCD", 10000))

    class _Boom(object):
        def __str__(self):
            raise RuntimeError("boom")
    check("F2 redact: FAIL CLOSED on internal exception", redact(_Boom(), 1000) is None)
    r_cap = redact("B" * 5000, 100)
    check("F2 redact: byte cap RESERVES marker room (final <= cap)",
          len(r_cap.encode("utf-8")) <= 100)

    # sanitize_ballot_fields
    check("F2 sanitize: multiline reason -> drop", sanitize_ballot_fields("a\nb", None) is None)
    check("F2 sanitize: non-string reason -> drop", sanitize_ballot_fields(123, None) is None)
    check("F2 sanitize: multiline evidence -> drop", sanitize_ballot_fields("ok", "a\nb") is None)
    sr = sanitize_ballot_fields("token is ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ABCD", None)
    check("F2 sanitize: re-redacts a leaked token in reason",
          sr is not None and "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ABCD" not in sr[0])

    # =================================================================================== #
    # F1 — TOCTOU-safe contained evidence read
    # =================================================================================== #
    e1 = _tempfile.mkdtemp()
    try:
        adir = os.path.join(e1, "attempt")
        os.makedirs(adir)
        base_fd = os.open(adir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with open(os.path.join(adir, "ev.txt"), "w") as fh:
                fh.write("gate output ok")
            t, err = read_contained_evidence(base_fd, "ev.txt", 100000)
            check("F1: valid contained file read", t == "gate output ok" and err is None)
            check("F1: absolute /etc/passwd rejected",
                  read_contained_evidence(base_fd, "/etc/passwd", 100000)[0] is None)
            check("F1: '..' traversal rejected",
                  read_contained_evidence(base_fd, "../x", 100000)[0] is None)
            check("F1: absolute-inside path rejected (isabs)",
                  read_contained_evidence(base_fd, os.path.join(adir, "ev.txt"), 100000)[0] is None)
            outside = _tempfile.mkdtemp()
            try:
                with open(os.path.join(outside, "secret.txt"), "w") as fh:
                    fh.write("OUTSIDE SECRET")
                os.symlink(os.path.join(outside, "secret.txt"), os.path.join(adir, "esc"))
                te, ee = read_contained_evidence(base_fd, "esc", 100000)
                check("F1: escaping symlink rejected BEFORE read (content never read)",
                      te is None and "OUTSIDE" not in (te or ""))
                # intermediate-component symlink swap: a symlinked subdir is rejected too.
                os.symlink(outside, os.path.join(adir, "subdirlink"))
                ts, es = read_contained_evidence(base_fd, os.path.join("subdirlink", "secret.txt"), 100000)
                check("F1: symlinked intermediate dir rejected (walk uses O_NOFOLLOW)", ts is None)
            finally:
                shutil.rmtree(outside, ignore_errors=True)
        finally:
            os.close(base_fd)
    finally:
        shutil.rmtree(e1, ignore_errors=True)

    # =================================================================================== #
    # F5 — trusted-root epic-dir containment + symlinked arbiter dir rejected
    # =================================================================================== #
    tr = _tempfile.mkdtemp()
    try:
        epic_dir, state_path, _ = _make_epic(tr)
        good = validate_epic_dir(state_path, "epic1")
        check("F5: a state under execution/epics/<id> validates", good.endswith("/execution/epics/epic1"))
        bad_dir = os.path.join(tr, "docs", "superpowers", "execution", "epics", "epic1")
        try:
            validate_epic_dir(state_path, "epicMISMATCH")
            check("F5: epic_id/dir-name mismatch rejected", False)
        except ArbiterError:
            check("F5: epic_id/dir-name mismatch rejected", True)
        loose = os.path.join(tr, "loose")
        os.makedirs(loose)
        lp = os.path.join(loose, "epic-state.json")
        with open(lp, "w") as fh:
            fh.write("{}")
        try:
            validate_epic_dir(lp, "loose")
            check("F5: a state outside execution/epics rejected", False)
        except ArbiterError:
            check("F5: a state outside execution/epics rejected", True)
        outside2 = _tempfile.mkdtemp()
        try:
            os.symlink(outside2, os.path.join(bad_dir, "arbiter"))
            try:
                fd = open_arbiter_dir_fd(good, create=False)
                os.close(fd)
                check("F5: symlinked arbiter dir rejected", False)
            except OSError:
                check("F5: symlinked arbiter dir rejected", True)
        finally:
            shutil.rmtree(outside2, ignore_errors=True)
    finally:
        shutil.rmtree(tr, ignore_errors=True)

    # =================================================================================== #
    # B4 — truth table (complete), collapse, external-family cap (F7)
    # =================================================================================== #
    def vb(family, disposition):
        return {"source": "x", "family": family, "disposition": disposition, "valid": True,
                "counted": True, "reason": "", "evidence": None}

    d0, c0, _ = aggregate_dispositions([])
    check("B4: zero ballots -> halt_feature", d0 == "halt_feature" and c0 is False)

    for disp, exp in [("retry_fix", "retry_fix"), ("halt_feature", "halt_feature"),
                      ("blocked_external", "blocked_external"), ("halt_epic", "halt_feature")]:
        d, c, _ = aggregate_dispositions([vb("GPT", disp)])
        check("B4 single GPT %s -> %s" % (disp, exp), d == exp and c is False)

    pairs = [
        (("retry_fix", "retry_fix"), "retry_fix"),
        (("retry_fix", "halt_feature"), "halt_feature"),
        (("retry_fix", "halt_epic"), "halt_feature"),
        (("retry_fix", "blocked_external"), "halt_feature"),
        (("halt_feature", "halt_feature"), "halt_feature"),
        (("halt_feature", "halt_epic"), "halt_feature"),
        (("halt_feature", "blocked_external"), "halt_feature"),
        (("halt_epic", "halt_epic"), "halt_epic"),
        (("halt_epic", "blocked_external"), "halt_feature"),
        (("blocked_external", "blocked_external"), "blocked_external"),
    ]
    for (a1, a2), exp in pairs:
        d, c, _ = aggregate_dispositions([vb("GPT", a1), vb("Gemini", a2)])
        check("B4 pair (%s,%s) -> %s" % (a1, a2, exp), d == exp)

    d, c, _ = aggregate_dispositions([vb("GPT", "blocked_external"), vb("Gemini", "blocked_external")])
    check("B4: 2 distinct external families blocked_external -> CONFIRMED", d == "blocked_external" and c is True)
    d, c, _ = aggregate_dispositions([vb("GPT", "blocked_external"), vb("Claude", "blocked_external")])
    check("B4: Codex+Claude blocked_external -> SUSPECTED (Claude excluded)", d == "blocked_external" and c is False)

    # F7 — Claude-only / no-external fallback caps halt_epic AND blocked_external.
    d, c, _ = aggregate_dispositions([vb("Claude", "halt_epic")])
    check("F7: lone Claude halt_epic -> halt_feature", d == "halt_feature")
    d, c, _ = aggregate_dispositions([vb("Claude", "blocked_external")])
    check("F7: lone Claude blocked_external -> halt_feature (cannot survive)", d == "halt_feature")
    d, c, _ = aggregate_dispositions([vb("Claude", "blocked_external"), vb("Claude", "halt_epic")])
    check("F7: Claude-only pair with no external family caps to halt_feature", d == "halt_feature")
    d, c, _ = aggregate_dispositions([vb("unknown", "halt_epic")])
    check("F7: unknown-only halt_epic -> halt_feature (no external family)", d == "halt_feature")

    collapsed = _collapse_same_family([
        {"source": "codex", "family": "GPT", "disposition": "retry_fix", "valid": True, "reason": "", "evidence": None},
        {"source": "claude", "family": "GPT", "disposition": "halt_epic", "valid": True, "reason": "", "evidence": None}])
    counted = [b for b in collapsed if b["counted"]]
    check("B4 collapse: one counted, more-conservative wins", len(counted) == 1 and counted[0]["disposition"] == "halt_epic")
    check("B4 collapse: loser visible+uncounted", any(not b["counted"] for b in collapsed))

    # =================================================================================== #
    # F3 — challenge cannot be resurrected (monotonic, immutable record)
    # =================================================================================== #
    ch = _tempfile.mkdtemp()
    try:
        epic_dir, state_path, state = _make_epic(ch, attempts=1)
        _, e, rc = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=5))
        check("F3: prepare rejects a future attempt (attempt != current)", e is not None and "monotonic" in e)
        _, e, rc = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=0))
        check("F3: prepare rejects a past attempt", e is not None)
        out, e, rc = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=1))
        check("F3: valid prepare issues", out is not None and rc == 0)
        challenge_id = out["challenge_id"]
        check("F3: challenge id is keyed+deterministic",
              challenge_id == compute_challenge_id(FIXED_KEY, "epic1", "featA", 1))
        out2, e2, rc2 = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=1))
        check("F3: re-prepare while issued is idempotent", out2 is not None and out2["challenge_id"] == challenge_id)
    finally:
        shutil.rmtree(ch, ignore_errors=True)

    # =================================================================================== #
    # E2E — classify: Codex-unavailable + valid Claude ballot, F4 whole-panel drop,
    # replay idempotency, retry-cap mask, F10 frozen round-trip, F9 controlled errors.
    # =================================================================================== #
    e2e = _tempfile.mkdtemp()
    try:
        epic_dir, state_path, state = _make_epic(e2e, attempts=1)

        out, e, rc = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=1))
        challenge_id = out["challenge_id"]

        ballot = os.path.join(e2e, "ballot.json")
        with open(ballot, "w") as fh:
            json.dump({"epic_id": "epic1", "feature": "featA", "attempt": 1,
                       "challenge_id": challenge_id, "disposition": "retry_fix",
                       "reason": "flaky"}, fh)

        res, e, rc = run_cmd(cmd_classify, _args(state=state_path, feature="featA",
                                                 challenge=challenge_id, claude_ballot=ballot))
        check("E2E: classify exits 0", rc == 0 and res is not None)
        check("E2E: codex-unavailable + single Claude retry_fix -> retry_fix", res["disposition"] == "retry_fix")
        check("E2E: confirmed always false", res["confirmed"] is False)
        check("E2E: audit_path set + file exists", res["audit_path"] and os.path.isfile(res["audit_path"]))
        with open(res["audit_path"]) as fh:
            persisted = json.load(fh)
        for k in ("disposition", "confirmed", "reason", "evidence", "ballots",
                  "families_present", "families_agreeing", "attempt", "audit_path", "challenge_id"):
            check("F10: persisted audit carries %r" % k, k in persisted)
        check("F10: persisted audit_path == printed audit_path", persisted["audit_path"] == res["audit_path"])
        check("F10: families_present recorded (Claude)", persisted["families_present"] == ["Claude"])

        res2, e2, rc2 = run_cmd(cmd_classify, _args(state=state_path, feature="featA",
                                                    challenge=challenge_id, claude_ballot=ballot))
        check("F4 replay: consumed challenge re-emits the SAME persisted audit (idempotent)",
              res2 is not None and res2["disposition"] == "retry_fix" and res2["audit_path"] == res["audit_path"])

        res3, e3, rc3 = run_cmd(cmd_classify, _args(state=state_path, feature="featA",
                                                    challenge="ch-bogus", claude_ballot=ballot))
        check("F4: invalid challenge -> whole panel dropped -> halt_feature",
              res3 is not None and res3["disposition"] == "halt_feature" and res3["ballots"] == []
              and "panel dropped" in res3["reason"])

        state["features"][0]["attempts"] = 2
        with open(state_path, "w") as fh:
            json.dump(state, fh)
        out_c, _, _ = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=2))
        cid2 = out_c["challenge_id"]
        ballot2 = os.path.join(e2e, "ballot2.json")
        with open(ballot2, "w") as fh:
            json.dump({"epic_id": "epic1", "feature": "featA", "attempt": 2,
                       "challenge_id": cid2, "disposition": "retry_fix", "reason": "again?"}, fh)
        res4, e4, rc4 = run_cmd(cmd_classify, _args(state=state_path, feature="featA",
                                                    challenge=cid2, claude_ballot=ballot2))
        check("E2E retry-cap: classify still runs at the cap (exit 0)", rc4 == 0)
        check("E2E retry-cap: retry_fix masked to halt_feature at cap",
              res4["disposition"] == "halt_feature" and "cap" in res4["reason"])

        res5, e5, rc5 = run_cmd(cmd_classify, _args(state=state_path, feature="featA",
                                                    challenge=challenge_id, claude_ballot=ballot))
        check("F4 stale-across-attempts: old challenge id at new attempt -> panel dropped",
              res5 is not None and res5["disposition"] == "halt_feature")

        # evidence wired end-to-end
        state["features"][0]["attempts"] = 3
        with open(state_path, "w") as fh:
            json.dump(state, fh)
        out_e, _, _ = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=3))
        cid3 = out_e["challenge_id"]
        ev_dir = os.path.join(epic_dir, "arbiter", "featA-3")
        with open(os.path.join(ev_dir, "gate.txt"), "w") as fh:
            fh.write("AC3 failed. secret=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ABCD")
        ballot3 = os.path.join(e2e, "ballot3.json")
        with open(ballot3, "w") as fh:
            json.dump({"epic_id": "epic1", "feature": "featA", "attempt": 3,
                       "challenge_id": cid3, "disposition": "halt_feature", "reason": "bug"}, fh)
        res6, e6, rc6 = run_cmd(cmd_classify, _args(state=state_path, feature="featA",
                                                    challenge=cid3, claude_ballot=ballot3,
                                                    evidence_file="gate.txt"))
        check("E2E evidence: contained evidence file -> classify exits 0", rc6 == 0)

        state["features"][0]["attempts"] = 4
        with open(state_path, "w") as fh:
            json.dump(state, fh)
        out_e2, _, _ = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=4))
        cid4 = out_e2["challenge_id"]
        ballot4 = os.path.join(e2e, "ballot4.json")
        with open(ballot4, "w") as fh:
            json.dump({"epic_id": "epic1", "feature": "featA", "attempt": 4,
                       "challenge_id": cid4, "disposition": "halt_feature"}, fh)
        res7, e7, rc7 = run_cmd(cmd_classify, _args(state=state_path, feature="featA",
                                                    challenge=cid4, claude_ballot=ballot4,
                                                    evidence_file="/etc/passwd"))
        check("E2E evidence: an absolute/escaping evidence path doesn't crash classify", rc7 == 0)

        bad_state = os.path.join(epic_dir, "bad-state.json")
        with open(bad_state, "w") as fh:
            json.dump({"features": [{"id": "featA"}]}, fh)
        _, e8, rc8 = run_cmd(cmd_classify, _args(state=bad_state, feature="featA", challenge="x"))
        check("F9: malformed state -> controlled ArbiterError (no traceback)",
              e8 is not None and "schema" in e8)
        none_state = os.path.join(epic_dir, "none-id.json")
        with open(none_state, "w") as fh:
            json.dump({"epic_id": None, "features": [{"id": "featA"}]}, fh)
        _, e9, rc9 = run_cmd(cmd_classify, _args(state=none_state, feature="featA", challenge="x"))
        check("F9: epic_id None rejected (no str(None)=='None' bypass)", e9 is not None)
    finally:
        shutil.rmtree(e2e, ignore_errors=True)

    # =================================================================================== #
    # F3/F4 durable state machine: issued -> consumed, no resurrection
    # =================================================================================== #
    dm = _tempfile.mkdtemp()
    try:
        epic_dir, state_path, state = _make_epic(dm, attempts=1)
        out, _, _ = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=1))
        cid = out["challenge_id"]
        arbiter_fd = open_arbiter_dir_fd(epic_dir, create=False)
        try:
            rec = _read_json_at(arbiter_fd, "featA-1.challenge.json", CHALLENGE_RECORD_MAX_BYTES)
        finally:
            os.close(arbiter_fd)
        check("F3: fresh record status == issued", rec["status"] == "issued")
        run_cmd(cmd_classify, _args(state=state_path, feature="featA", challenge=cid))
        arbiter_fd = open_arbiter_dir_fd(epic_dir, create=False)
        try:
            rec2 = _read_json_at(arbiter_fd, "featA-1.challenge.json", CHALLENGE_RECORD_MAX_BYTES)
        finally:
            os.close(arbiter_fd)
        check("F4: record durably consumed after classify", rec2["status"] == "consumed")
        _, e, _ = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=1))
        check("F3: re-prepare a CONSUMED attempt rejected", e is not None and "consumed" in e)
    finally:
        shutil.rmtree(dm, ignore_errors=True)

    # =================================================================================== #
    # ROUND 2 — Codex second security review
    # =================================================================================== #

    # R2#1 — a bogus challenge must NOT overwrite the canonical audit; a later CORRECT replay
    # still re-emits the ORIGINAL valid verdict.
    r1 = _tempfile.mkdtemp()
    try:
        epic_dir, state_path, state = _make_epic(r1, attempts=1)
        out, _, _ = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=1))
        cid = out["challenge_id"]
        ballot = os.path.join(r1, "b.json")
        with open(ballot, "w") as fh:
            json.dump({"epic_id": "epic1", "feature": "featA", "attempt": 1,
                       "challenge_id": cid, "disposition": "retry_fix", "reason": "flaky"}, fh)
        good, _, _ = run_cmd(cmd_classify, _args(state=state_path, feature="featA",
                                                 challenge=cid, claude_ballot=ballot))
        check("R2#1: valid classify -> retry_fix", good["disposition"] == "retry_fix")
        canonical = good["audit_path"]
        # now fire a BOGUS challenge at the same attempt
        bad, _, _ = run_cmd(cmd_classify, _args(state=state_path, feature="featA",
                                                challenge="ch-attacker", claude_ballot=ballot))
        check("R2#1: bogus challenge dropped -> halt_feature", bad["disposition"] == "halt_feature")
        with open(canonical) as fh:
            still = json.load(fh)
        check("R2#1: canonical audit NOT clobbered by the bogus challenge",
              still["disposition"] == "retry_fix")
        check("R2#1: the drop event went to a separate .rejected.json path",
              bad["audit_path"] is not None and bad["audit_path"].endswith(".rejected.json"))
        # a later CORRECT replay still re-emits the original valid verdict
        replay, _, _ = run_cmd(cmd_classify, _args(state=state_path, feature="featA",
                                                   challenge=cid, claude_ballot=ballot))
        check("R2#1: correct replay re-emits the original valid verdict",
              replay["disposition"] == "retry_fix" and replay["audit_path"] == canonical)
    finally:
        shutil.rmtree(r1, ignore_errors=True)

    # R2#2 — unclosed quoted labelled secret fails closed (single + double quote, multiline).
    check("R2#2: unclosed double-quoted labelled secret -> fail closed",
          redact('token="shortsecret\ncontinued', 10000) is None)
    check("R2#2: unclosed single-quoted labelled secret -> fail closed",
          redact("password='abc def", 10000) is None)
    check("R2#2: a CLOSED quoted labelled secret still redacts (not fail-closed)",
          redact('token="abc"', 10000) is not None and "abc" not in redact('token="abc"', 10000))
    check("R2#2: unclosed multiline api_key -> fail closed",
          redact('api_key = "line1\nline2 no close', 10000) is None)

    # R2#3 — a malformed-ballot diagnostic must not leak an untrusted value into output/audit.
    r3 = _tempfile.mkdtemp()
    try:
        epic_dir, state_path, state = _make_epic(r3, attempts=1)
        out, _, _ = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=1))
        cid = out["challenge_id"]
        leak = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ABCD"  # a token-shaped "secret"
        bad_ballot = os.path.join(r3, "bad.json")
        with open(bad_ballot, "w") as fh:
            json.dump({"epic_id": "epic1", "feature": "featA", "attempt": 1,
                       "challenge_id": cid, "disposition": leak}, fh)  # invalid disposition = secret
        res, _, _ = run_cmd(cmd_classify, _args(state=state_path, feature="featA",
                                                challenge=cid, claude_ballot=bad_ballot))
        blob = json.dumps(res)
        check("R2#3: invalid-disposition value NOT echoed into the result", leak not in blob)
        with open(res["audit_path"]) as fh:
            persisted_blob = fh.read()
        check("R2#3: invalid-disposition value NOT written to the audit", leak not in persisted_blob)
    finally:
        shutil.rmtree(r3, ignore_errors=True)

    # R2#4 — an oversized caller-supplied ballot file must be DROPPED, never DELETED.
    r4 = _tempfile.mkdtemp()
    try:
        big_ballot = os.path.join(r4, "big.json")
        with open(big_ballot, "w") as fh:
            fh.write("{" + "\"x\":\"" + ("A" * (BALLOT_FILE_MAX_BYTES + 100)) + "\"}")
        cb, reason = load_claude_ballot(big_ballot, "e", "f", 1, "c")
        check("R2#4: oversized ballot dropped", cb is None)
        check("R2#4: oversized USER ballot file NOT deleted", os.path.exists(big_ballot))
    finally:
        shutil.rmtree(r4, ignore_errors=True)

    # R2#5 — printed == persisted; hard byte cap after trim.
    r5 = _tempfile.mkdtemp()
    try:
        epic_dir, state_path, state = _make_epic(r5, attempts=1)
        out, _, _ = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=1))
        cid = out["challenge_id"]
        ballot = os.path.join(r5, "b.json")
        with open(ballot, "w") as fh:
            json.dump({"epic_id": "epic1", "feature": "featA", "attempt": 1,
                       "challenge_id": cid, "disposition": "retry_fix",
                       "reason": "x" * 500}, fh)
        res, _, _ = run_cmd(cmd_classify, _args(state=state_path, feature="featA",
                                                challenge=cid, claude_ballot=ballot))
        with open(res["audit_path"]) as fh:
            persisted = json.load(fh)
        check("R2#5: printed result == persisted audit (byte-identical)",
              json.dumps(res, sort_keys=True) == json.dumps(persisted, sort_keys=True))
        # _finalize_result stub path when a result is huge
        huge = {"disposition": "halt_feature", "confirmed": False, "reason": "r",
                "evidence": None, "ballots": [{"reason": "z" * 300000}],
                "families_present": [], "families_agreeing": [], "challenge_id": "c",
                "epic_id": "e", "feature": "f", "attempt": 1, "audit_path": "/x", "recorded_at": "t"}
        fin = _finalize_result(huge)
        check("R2#5: an over-cap result is trimmed/stubbed under the hard byte cap",
              len(json.dumps(fin).encode("utf-8")) <= AUDIT_MAX_ONE_BYTES)
    finally:
        shutil.rmtree(r5, ignore_errors=True)

    # R2#6 — an existing-but-unreadable record must fail closed on --prepare (not resurrect).
    r6 = _tempfile.mkdtemp()
    try:
        epic_dir, state_path, state = _make_epic(r6, attempts=1)
        run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=1))
        # corrupt the persisted challenge record in place
        arbiter_fd = open_arbiter_dir_fd(epic_dir, create=False)
        try:
            fd = os.open("featA-1.challenge.json", os.O_WRONLY | os.O_TRUNC, dir_fd=arbiter_fd)
            os.write(fd, b"{ this is not valid json")
            os.close(fd)
        finally:
            os.close(arbiter_fd)
        _, e, _ = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=1))
        check("R2#6: unreadable existing record -> prepare fails closed (no resurrection)",
              e is not None and "unreadable" in e)
        # probe helper distinguishes absent vs unreadable
        arbiter_fd = open_arbiter_dir_fd(epic_dir, create=False)
        try:
            st_absent, _ = _probe_record(arbiter_fd, "no-such.challenge.json", 4096)
            st_bad, _ = _probe_record(arbiter_fd, "featA-1.challenge.json", 4096)
        finally:
            os.close(arbiter_fd)
        check("R2#6: probe distinguishes absent vs unreadable",
              st_absent == "absent" and st_bad == "unreadable")
    finally:
        shutil.rmtree(r6, ignore_errors=True)

    # R2#7 — an in_progress record with an existing audit re-emits WITHOUT a second egress.
    r7 = _tempfile.mkdtemp()
    try:
        epic_dir, state_path, state = _make_epic(r7, attempts=1)
        out, _, _ = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=1))
        cid = out["challenge_id"]
        ballot = os.path.join(r7, "b.json")
        with open(ballot, "w") as fh:
            json.dump({"epic_id": "epic1", "feature": "featA", "attempt": 1,
                       "challenge_id": cid, "disposition": "halt_epic", "reason": "systemic"}, fh)
        first, _, _ = run_cmd(cmd_classify, _args(state=state_path, feature="featA",
                                                  challenge=cid, claude_ballot=ballot))
        # manually rewind the record to in_progress (simulate a crash after audit, before consume)
        arbiter_fd = open_arbiter_dir_fd(epic_dir, create=False)
        try:
            rec = _read_json_at(arbiter_fd, "featA-1.challenge.json", CHALLENGE_RECORD_MAX_BYTES)
            rec["status"] = "in_progress"
            rec.pop("consumed_at", None)
            _write_json_at(arbiter_fd, "featA-1.challenge.json", rec)
        finally:
            os.close(arbiter_fd)
        # a DIFFERENT ballot on replay must be IGNORED — we re-emit the existing audit.
        ballot2 = os.path.join(r7, "b2.json")
        with open(ballot2, "w") as fh:
            json.dump({"epic_id": "epic1", "feature": "featA", "attempt": 1,
                       "challenge_id": cid, "disposition": "retry_fix", "reason": "changed"}, fh)
        again, _, _ = run_cmd(cmd_classify, _args(state=state_path, feature="featA",
                                                  challenge=cid, claude_ballot=ballot2))
        check("R2#7: in_progress+existing audit re-emits the ORIGINAL verdict (no re-egress)",
              again["disposition"] == first["disposition"] == "halt_feature")  # halt_epic single-ballot -> halt_feature
    finally:
        shutil.rmtree(r7, ignore_errors=True)

    # R2#8 — input bounds: overlong id, numeric arg validation, marker-vs-cap.
    check("R2#8: overlong id rejected by _id_ok", not _id_ok("a" * (MAX_ID_LEN + 1)))
    check("R2#8: max-len id accepted", _id_ok("a" * MAX_ID_LEN))
    check("R2#8: _cap_bytes_with_marker never exceeds a tiny cap",
          len(_cap_bytes_with_marker("Z" * 100, 3).encode("utf-8")) <= 3)
    check("R2#8: overlong feature id -> controlled ArbiterError (no crash)",
          run_cmd(cmd_prepare, _args(state=os.path.join(_tempfile.gettempdir(), "x"),
                                     feature="f" * (MAX_ID_LEN + 1), attempt=1))[1] is not None)
    check("R2#8: main() rejects a non-positive --max-output-bytes",
          _run_main_expect_error(["--classify", "--max-output-bytes", "0", "--feature", "f",
                                  "--challenge", "c", "--state", "/nope"]))
    check("R2#8: main() rejects a non-positive --codex-timeout",
          _run_main_expect_error(["--classify", "--codex-timeout", "0", "--feature", "f",
                                  "--challenge", "c", "--state", "/nope"]))

    # =================================================================================== #
    # ROUND 3 — Codex third security review
    # =================================================================================== #

    # R3#1 — an ESCAPED closing quote does NOT terminate a labelled secret -> fail closed.
    check("R3#1: token=\"secret\\\" (escaped quote, still open) -> fail closed",
          redact('token="secret\\"', 10000) is None)
    check("R3#1: single-quote escaped, still open -> fail closed",
          redact("password='secret\\'", 10000) is None)
    check("R3#1: token=\"secret\\\"\" (escaped THEN real close) -> handled (not None), redacted",
          redact('token="secret\\""', 10000) is not None
          and "secret" not in redact('token="secret\\""', 10000))
    check("R3#1: a plain closed value still redacts",
          redact('token="plainval"', 10000) is not None and "plainval" not in redact('token="plainval"', 10000))
    check("R3#1: _has_unescaped_quote respects backslash escaping",
          _has_unescaped_quote('abc"', 0, '"') is True
          and _has_unescaped_quote('abc\\"', 0, '"') is False
          and _has_unescaped_quote('abc\\""', 0, '"') is True)

    # R3#2 — oversized --challenge is rejected at the boundary; the stub is ALWAYS under cap.
    r31 = _tempfile.mkdtemp()
    try:
        epic_dir, state_path, state = _make_epic(r31, attempts=1)
        _, e, _ = run_cmd(cmd_classify, _args(state=state_path, feature="featA",
                                              challenge="c" * (MAX_ID_LEN + 1)))
        check("R3#2: oversized --challenge rejected (controlled error)", e is not None and "too long" in e)
        # _finalize_result stub stays under cap even if challenge_id/epic_id are pathologically huge.
        huge = {"disposition": "halt_feature", "confirmed": False, "reason": "r", "evidence": None,
                "ballots": [{"reason": "z" * 300000}], "families_present": [], "families_agreeing": [],
                "challenge_id": "C" * 300000, "epic_id": "E" * 300000, "feature": "F" * 300000,
                "attempt": 1, "audit_path": "/p" * 100000, "recorded_at": "t"}
        fin = _finalize_result(huge)
        check("R3#2: finalized stub is under the hard byte cap despite huge id fields",
              len(json.dumps(fin).encode("utf-8")) <= AUDIT_MAX_ONE_BYTES)
    finally:
        shutil.rmtree(r31, ignore_errors=True)

    # R3#3 — printed bytes == persisted file bytes EXACTLY (not just parsed-equal).
    r33 = _tempfile.mkdtemp()
    try:
        epic_dir, state_path, state = _make_epic(r33, attempts=1)
        out, _, _ = run_cmd(cmd_prepare, _args(state=state_path, feature="featA", attempt=1))
        cid = out["challenge_id"]
        ballot = os.path.join(r33, "b.json")
        with open(ballot, "w") as fh:
            json.dump({"epic_id": "epic1", "feature": "featA", "attempt": 1,
                       "challenge_id": cid, "disposition": "retry_fix", "reason": "flaky"}, fh)
        raw_stdout, _, _ = run_cmd_raw(cmd_classify, _args(state=state_path, feature="featA",
                                                           challenge=cid, claude_ballot=ballot))
        audit_path = json.loads(raw_stdout)["audit_path"]
        with open(audit_path, "r") as fh:
            persisted_bytes = fh.read()
        check("R3#3: printed stdout bytes == persisted audit file bytes (exact)",
              raw_stdout == persisted_bytes)
        # crash-recovery re-emit is also byte-exact
        arbiter_fd = open_arbiter_dir_fd(epic_dir, create=False)
        try:
            rec = _read_json_at(arbiter_fd, "featA-1.challenge.json", CHALLENGE_RECORD_MAX_BYTES)
            rec["status"] = "in_progress"
            _write_json_at(arbiter_fd, "featA-1.challenge.json", rec)
        finally:
            os.close(arbiter_fd)
        raw2, _, _ = run_cmd_raw(cmd_classify, _args(state=state_path, feature="featA",
                                                     challenge=cid, claude_ballot=ballot))
        check("R3#3: crash-recovery re-emit bytes == persisted file bytes (exact)",
              raw2 == persisted_bytes)
    finally:
        shutil.rmtree(r33, ignore_errors=True)

    print("SELFTEST: %d ok, %d fail" % (ok, fail))
    return 0 if fail == 0 else 1


# --------------------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------------------- #

def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(description="Compound V epic arbiter — Codex+Claude panel.")
    p.add_argument("--prepare", action="store_true")
    p.add_argument("--classify", action="store_true")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--state")
    p.add_argument("--feature")
    p.add_argument("--attempt", type=int)
    p.add_argument("--challenge")
    p.add_argument("--evidence-file", help="RELATIVE to <epic_dir>/arbiter/<feature>-<attempt>/")
    p.add_argument("--claude-ballot")
    p.add_argument("--now")
    p.add_argument("--challenge-key", help="fixed per-epic challenge key (tests / pinned driver)")
    p.add_argument("--capabilities-path")
    p.add_argument("--config")
    p.add_argument("--explicit-codex-model")
    p.add_argument("--codex-timeout", type=int, default=DEFAULT_CODEX_TIMEOUT_SEC)
    p.add_argument("--max-output-bytes", type=int, default=DEFAULT_MAX_OUTPUT_BYTES)
    p.add_argument("--codex-bin")
    p.add_argument("--supervisor-path")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()

    # Finding 8/#11: bound the numeric inputs at the argument boundary — positive and sane.
    if args.max_output_bytes <= 0 or args.max_output_bytes > MAX_OUTPUT_BYTES_CEILING:
        p.error("--max-output-bytes must be in 1..%d" % MAX_OUTPUT_BYTES_CEILING)
    if args.codex_timeout <= 0 or args.codex_timeout > MAX_TIMEOUT_SEC:
        p.error("--codex-timeout must be in 1..%d seconds" % MAX_TIMEOUT_SEC)

    try:
        if args.prepare:
            return cmd_prepare(args, p)
        if args.classify:
            return cmd_classify(args, p)
    except ArbiterError as e:
        _log(str(e))
        return 1
    except OSError as e:
        # Finding 8/#11: convert a filesystem error at a security boundary (ENAMETOOLONG,
        # EACCES, …) into a controlled one-line error, never a raw traceback.
        _log("filesystem error: %s" % e)
        return 1
    p.error("one of --prepare / --classify / --selftest is required")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
