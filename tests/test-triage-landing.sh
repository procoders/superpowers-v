#!/usr/bin/env bash
# tests/test-triage-landing.sh — the DIRECT auto-route LANDING GATE of
# commands/v-triage.md (Phase L), driven END TO END against sandbox git repos.
#
# WHY THIS FILE REPLACES THE FIXTURE THAT USED TO LIVE IN THE COMMAND DOC
#
#   The Review Gate found the old in-doc "three negative proofs" vacuous. Its
#   fifteen assertions tested the PRIMITIVES the gate stands on, never the gate:
#     * attack 1 asserted `staged == ["OTHER.md"]` — a fact about `git add`
#     * attack 2 asserted two sha256 digests differ — a fact about sha256
#     * attack 3 asserted `update-ref <new> <old>` CAS semantics — a fact about git
#   Phase L could have been deleted from the markdown outright and all fifteen
#   would still have passed. It was also outside CI: the sweep covers
#   `scripts/*.py --selftest` and `tests/**`, and `commands/` is in neither.
#
#   So every assertion below RUNS THE REAL GATE. The Phase L python block is
#   extracted verbatim out of commands/v-triage.md, pointed at a throwaway repo
#   with `V_TRIAGE_REPO`, and its exit code, the sandbox's git history and the
#   outcome stream it wrote are what get asserted. An attack "fails" here only
#   because the gate refused it.
#
# NON-VACUITY IS PROVED, NOT ASSERTED
#
#   A refusal test passes just as happily against a gate that refuses
#   EVERYTHING, so two things back every attack:
#     1. a CONTROL — the same landing, minus the attack, is shown to SUCCEED;
#     2. a PLANTED MUTATION — the corresponding check is removed from a copy of
#        the extracted gate and the suite is shown to go RED on the matching
#        assertion (the tests/test-native-points.sh precedent, including its
#        "mutation target must be unique" guard).
#
# AC-05 ("a test proves a change that outgrows the class is demoted and the
# demotion recorded") is what the demotion assertions answer: before this file,
# `grep -rn demoted_from tests/` returned nothing.

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
DOC="${V_TRIAGE_DOC:-$REPO/commands/v-triage.md}"
PYBIN="${V_TRIAGE_TEST_PYTHON:-python3}"

pass=0
fail=0
ok()  { pass=$((pass + 1)); printf 'PASS %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf 'FAIL %s\n' "$1"; }
check(){ if [ "$2" = "1" ]; then ok "$1"; else bad "$1"; fi; }

# --------------------------------------------------------------------------- #
# Preconditions — loud, never silently skipped. A suite that quietly does
# nothing is the v2.14.1 false-green, and this one has a lot to go missing.
# --------------------------------------------------------------------------- #
[ -f "$DOC" ] || { echo "FATAL: $DOC missing"; exit 1; }
command -v "$PYBIN" >/dev/null 2>&1 || { echo "FATAL: $PYBIN required"; exit 1; }
command -v git >/dev/null 2>&1 || { echo "FATAL: git required"; exit 1; }
for s in compound-v-preeval.py compound-v-taxonomy.py compound-v-fastpath-run.py \
         compound-v-validate-manifest.py compound-v-project-config.py \
         compound-v-triage-outcomes.py; do
  [ -f "$REPO/scripts/$s" ] || { echo "FATAL: the gate imports $s and it is missing"; exit 1; }
done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# Every temp directory the gate, the floor supervisor and the sandboxes create
# lands inside $WORK, so the trap above is the whole cleanup story.
export TMPDIR="$WORK/tmp"
mkdir -p "$TMPDIR"
export PYTHONDONTWRITEBYTECODE=1

# --------------------------------------------------------------------------- #
# Extract Phase L verbatim from the command doc. The gate is prose-hosted, so
# this is the only way to drive THE SHIPPED TEXT rather than a copy of it that
# can drift: if someone edits Phase L, this suite runs the edit.
# --------------------------------------------------------------------------- #
LAND="$WORK/land.py"
"$PYBIN" - "$DOC" "$LAND" <<'PYEOF'
import sys
src, dst = sys.argv[1], sys.argv[2]
lines = open(src, encoding="utf-8").read().splitlines(True)
start = None
for i, line in enumerate(lines):
    if line.startswith("V_TRIAGE_ID=") and line.rstrip().endswith("python3 - <<'PY'"):
        start = i + 1
        break
if start is None:
    sys.exit("EXTRACTION FAILED: no Phase L heredoc opener in %s" % src)
end = None
for j in range(start, len(lines)):
    if lines[j].rstrip("\n") == "PY":
        end = j
        break
if end is None:
    sys.exit("EXTRACTION FAILED: Phase L heredoc is unterminated")
body = "".join(lines[start:end])
for sentinel in ("THE CAS WINDOW", "def revalidate", "def demote", "commit-tree"):
    if sentinel not in body:
        sys.exit("EXTRACTION FAILED: %r not in the extracted block — wrong block?"
                 % sentinel)
open(dst, "w", encoding="utf-8").write(body)
PYEOF
extracted=$?
check "the Phase L gate could be extracted from $(basename "$DOC")" \
  "$([ "$extracted" = 0 ] && [ -s "$LAND" ] && echo 1 || echo 0)"
[ -s "$LAND" ] || { echo "FATAL: nothing to test"; exit 1; }
check "the extracted gate is a syntactically valid program" \
  "$("$PYBIN" -c 'import sys,py_compile; py_compile.compile(sys.argv[1], doraise=True)' "$LAND" >/dev/null 2>&1 && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# The scenarios. One program, so a sandbox builder is written once; it prints
# PASS/FAIL lines this harness counts, and is re-run verbatim against each
# mutant below.
# --------------------------------------------------------------------------- #
SCEN="$WORK/scenarios.py"
cat >"$SCEN" <<'PYEOF'
"""Drive commands/v-triage.md Phase L against throwaway repositories.

usage: scenarios.py <repo> <gate.py> [group,group,...]

Prints `PASS <name>` / `FAIL <name>`; exits 1 if anything failed. Kept to the
Python 3.9 floor the CI test job pins.

Scenarios are grouped so a planted mutation can re-run only the group it is
supposed to break — every gate invocation spawns an interpreter that imports
six six-figure-byte modules, and running all five groups seven times over is
three minutes of CI for no extra information.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

REPO, GATE = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
GROUPS = [g for g in (sys.argv[3] if len(sys.argv) > 3 else "").split(",") if g]

# A leaked GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE would point the sandboxes at the
# real repository. Strip them once, here, for every child process.
for _v in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"):
    os.environ.pop(_v, None)


def _load(basename, modname):
    path = os.path.join(REPO, "scripts", basename)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pe = _load("compound-v-preeval.py", "cv_preeval")
tx = _load("compound-v-taxonomy.py", "cv_taxonomy")
outc = _load("compound-v-triage-outcomes.py", "cv_triage_outcomes")

DIRECT = pe.DECISION_TO_TIER[pe.DECISION_FASTPATH]
SCOPED = pe.DECISION_TO_TIER[pe.DECISION_SCOPED]

failures = []
_registry = []


def scenario(group):
    """Register one scenario block under a group name."""
    def deco(fn):
        _registry.append((group, fn))
        return fn
    return deco


def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    sys.stdout.flush()
    if not cond:
        failures.append(name)


# The seed taxonomy: README.md is the one auto-routable path, 20-line budget,
# and — deliberately — the policy files are NOT in its sensitive list, so the
# code-level MANDATORY_SENSITIVE floor is the thing under test in attack 2a.
TAX = """version: 1
path_patterns:
  - glob: "**/*.md"
    difficulty_band: low
    impact_band: low
sensitive_path_list:
  - "**/*.pem"
auto_route_allow:
  - "README.md"
auto_route_max_lines: 20
churn:
  exclude_paths: []
  format_commit_patterns: []
"""

# The same taxonomy with the policy file itself auto-routable — the seed for the
# self-widening attack, where triage legitimately authorised the taxonomy path.
TAX_SELF = TAX.replace('  - "README.md"', '  - "README.md"\n  - ".claude/**"')

# The same taxonomy with tests/** auto-routable, so predicate 6 (no test file
# touched) is the ONLY thing left standing between a test edit and a commit.
TAX_TESTS = TAX.replace('  - "README.md"', '  - "README.md"\n  - "tests/**"')

TAXONOMY_REL = pe.DEFAULT_TAXONOMY_REL
GREEN = "sh -c 'exit 0'"
RED = "sh -c 'exit 1'"

# A concurrent session, expressed as a test command so it runs INSIDE the gate's
# own critical section rather than being faked around it.
#   invocation 1 (pre-lock floor): perturb the staged diff, so the digest the
#     floor result is bound to no longer matches and the gate re-runs the floor
#     INSIDE the lock;
#   invocation 2 (that in-lock re-run): move HEAD, exactly as another session
#     committing would — after the gate captured `expected`, before its CAS.
RACE = """set -e
D="$1"
if [ ! -f "$D/.race-1" ]; then
  : >"$D/.race-1"
  printf 'perturb\\n' >> "$D/README.md"
  git -C "$D" add -- README.md
  exit 0
fi
[ -f "$D/.race-2" ] && exit 0
: >"$D/.race-2"
H=$(git -C "$D" rev-parse HEAD)
T=$(git -C "$D" rev-parse "HEAD^{tree}")
C=$(git -C "$D" commit-tree "$T" -p "$H" -m "concurrent session")
git -C "$D" update-ref HEAD "$C" "$H"
"""

PID = "2026-09-01T000000Z-sandbox-a1"


def git(d, *args):
    return subprocess.run(["git", "-C", d] + list(args), capture_output=True,
                          text=True)


def sandbox(tax_text=TAX, authorised="README.md", full=GREEN, floor=GREEN,
            contract=True, race=False):
    """A repository the gate will accept: a committed base, a live taxonomy, a
    DIRECT pre-eval record whose digest verifies, and its pinned snapshot."""
    d = tempfile.mkdtemp(prefix="v-land-")
    git(d, "init", "-q", "-b", "main", ".")
    for kv in (("user.email", "t@example.invalid"), ("user.name", "t"),
               ("commit.gpgsign", "false"), ("core.hooksPath",
                                             os.path.join(d, ".nohooks"))):
        git(d, "config", kv[0], kv[1])
    os.makedirs(os.path.join(d, ".nohooks"))
    # The gate imports six shipped modules from <repo>/scripts. Symlinking keeps
    # them the REAL ones while `_repo_root()` (dirname of the module path, which
    # abspath does not resolve) still points the outcome stream at the sandbox.
    os.symlink(os.path.join(REPO, "scripts"), os.path.join(d, "scripts"))
    for rel in (os.path.dirname(TAXONOMY_REL), "docs/superpowers/pre-eval",
                "docs/superpowers/memory"):
        os.makedirs(os.path.join(d, *rel.split("/")))
    _write(os.path.join(d, TAXONOMY_REL), tax_text)
    _write(os.path.join(d, "README.md"), "hello\n")
    _write(os.path.join(d, "OTHER.md"), "other\n")
    if race:
        _write(os.path.join(d, "race.sh"), RACE)
    git(d, "add", "--", "README.md", "OTHER.md", TAXONOMY_REL)
    git(d, "commit", "-qm", "base")

    digest = tx.taxonomy_digest_bytes(tax_text.encode("utf-8"))
    verdict = {"decision": pe.DECISION_FASTPATH, "override_fired": None,
               "difficulty": {"band": "low", "display": 2},
               "impact": {"band": "low", "display": 2},
               "tiers_signalled": ["T1"], "min_sample_status": "insufficient"}
    loc = {"resolved_paths": [authorised], "fan_out": 1, "flags": [],
           "confidence": "exact"}
    rec = pe.build_record(PID, "tweak one small file", verdict, loc, 1,
                          TAXONOMY_REL, digest,
                          binding={"session_id": "s1", "base_commit": "a" * 40,
                                   "declared_paths": [authorised]})
    pdir = os.path.join(d, "docs", "superpowers", "pre-eval")
    _write(os.path.join(pdir, PID + ".json"),
           json.dumps(rec, indent=2, sort_keys=True) + "\n")
    _write(os.path.join(pdir, PID + ".taxonomy-snapshot.yaml"), tax_text)

    if contract:
        body = "test_contract:\n"
        if floor is not None:
            body += "  floor_command: %s\n" % json.dumps(floor)
        if full is not None:
            body += "  full_command: %s\n" % json.dumps(
                full.replace("@D@", d) if isinstance(full, str) else full)
        _write(os.path.join(d, "contract.yaml"), body)
    return d


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class Result(object):
    pass


def land(d, dry=False):
    """Run the real gate over the sandbox and collect everything observable."""
    env = dict(os.environ)
    env.update({"V_TRIAGE_REPO": d, "V_TRIAGE_ID": PID,
                "V_TRIAGE_MESSAGE": "chore: land the authorised change",
                "PYTHONDONTWRITEBYTECODE": "1"})
    contract = os.path.join(d, "contract.yaml")
    if os.path.isfile(contract):
        env["V_TRIAGE_TEST_CONTRACT"] = contract
    if dry:
        env["V_TRIAGE_DRY_RUN"] = "1"
    before = git(d, "rev-parse", "HEAD").stdout.strip()
    proc = subprocess.run([sys.executable, GATE], capture_output=True, text=True,
                          env=env, cwd=d)
    r = Result()
    r.rc = proc.returncode
    r.out = proc.stdout + proc.stderr
    r.before = before
    r.head = git(d, "rev-parse", "HEAD").stdout.strip()
    r.moved = r.head != before
    r.staged = [p for p in git(d, "diff", "--cached", "--name-only",
                               "-z").stdout.split("\0") if p]
    r.committed = ([p for p in git(d, "show", "--pretty=", "--name-only",
                                   "-z", r.head).stdout.split("\0") if p]
                   if r.moved else [])
    r.subject = git(d, "log", "-1", "--pretty=%s").stdout.strip()
    r.receipt = os.path.isfile(os.path.join(d, "docs", "superpowers", "pre-eval",
                                            PID + ".landing.json"))
    stream = os.path.join(d, "docs", "superpowers", "memory",
                          "triage-outcomes.jsonl")
    r.events = []
    if os.path.isfile(stream):
        with open(stream, encoding="utf-8") as fh:
            r.events = [json.loads(l) for l in fh if l.strip()]
    return r


def refused(tag, r, must_say=None):
    """The gate refused: non-zero, HEAD did not move, no receipt."""
    ok("%s: the gate REFUSES to land" % tag,
       r.rc != 0 and not r.moved and not r.receipt)
    if must_say is not None:
        ok("%s: the refusal says why (%r)" % (tag, must_say), must_say in r.out)


def demoted(tag, r, reason_says):
    """AC-05: the demotion happened AND was recorded on the outcome stream."""
    ok("%s: the gate demoted rather than committing (exit 2)" % tag, r.rc == 2)
    ok("%s: the authorised path was unstaged again" % tag, r.staged == [])
    preds = [e for e in r.events if e.get("event") == "predicted"]
    ok("%s: the demotion reached the outcome stream" % tag, len(preds) == 1)
    ev = preds[0] if preds else {}
    ok("%s: the recorded demotion is demoted_from=%s" % (tag, DIRECT),
       ev.get("demoted_from") == DIRECT)
    ok("%s: the recorded decision/tier is %s/%s" % (tag, pe.DECISION_SCOPED,
                                                    SCOPED),
       ev.get("decision") == pe.DECISION_SCOPED and ev.get("tier") == SCOPED)
    ok("%s: demotion_reason names the failure (%r)" % (tag, reason_says),
       reason_says in (ev.get("demotion_reason") or ""))


# =========================================================================== #
# CONTROL. Every refusal below is only meaningful because this one lands: a
# gate that refuses everything would pass an attack suite trivially.
# =========================================================================== #
@scenario("control")
def control():
    d = sandbox()
    _write(os.path.join(d, "README.md"), "hello\none authorised line\n")
    r = land(d)
    ok("control: an authorised, floor-green DIRECT change LANDS (exit 0)",
       r.rc == 0)
    ok("control: HEAD advanced by exactly the authorised path",
       r.moved and r.committed == ["README.md"])
    ok("control: the landing receipt was written", r.receipt)
    ok("control: nothing was recorded as a demotion", r.events == [])

    # The dry run is the same predicates without the CAS window — it must never
    # commit, which is what makes it safe to suggest to a user mid-edit.
    d = sandbox()
    _write(os.path.join(d, "README.md"), "hello\none authorised line\n")
    r = land(d, dry=True)
    ok("control: a dry run passes the predicates and commits NOTHING",
       r.rc == 0 and not r.moved and not r.receipt and "DRY RUN" in r.out)


# =========================================================================== #
# ATTACK 1 — PATH SUBSTITUTION. Triage authorised A; the realised diff is B.
# Same SHAPE (one literal path, under budget, not a test), different IDENTITY.
# =========================================================================== #
@scenario("attack1")
def attack1():
    d = sandbox()
    _write(os.path.join(d, "OTHER.md"), "other\nsneaky\n")
    r = land(d)
    refused("attack 1a (path substitution)", r)
    demoted("attack 1a (path substitution)", r, "!= the authorised path")

    # 1b: the implementer already `git add`ed the substituted file.
    # `commit-tree` commits the whole INDEX, so a gate that only checked its own
    # `git add` would carry OTHER.md into the commit.
    d = sandbox()
    _write(os.path.join(d, "README.md"), "hello\nlegit\n")
    _write(os.path.join(d, "OTHER.md"), "other\nsneaky\n")
    git(d, "add", "--", "OTHER.md")
    r = land(d)
    refused("attack 1b (pre-poisoned index)", r)
    ok("attack 1b (pre-poisoned index): the extra path is named in the refusal",
       "OTHER.md" in r.out)


# =========================================================================== #
# ATTACK 2 — TAXONOMY MUTATION. The realised diff rewrites the policy that
# authorised it, widening auto_route_allow to scripts/**.
# =========================================================================== #
WIDENED_TAIL = '  - "README.md"\n  - "scripts/**"'


@scenario("attack2")
def attack2():
    # 2a: triage authorised the taxonomy path itself (a seed where .claude/** is
    # auto-routable and the policy files are NOT in the taxonomy's sensitive
    # list).
    d = sandbox(tax_text=TAX_SELF, authorised=TAXONOMY_REL)
    _write(os.path.join(d, TAXONOMY_REL),
           TAX_SELF.replace('  - "README.md"', WIDENED_TAIL))
    r = land(d)
    refused("attack 2a (taxonomy self-widening)", r)
    ok("attack 2a (taxonomy self-widening): refused BEFORE any staging (exit 1)",
       r.rc == 1 and "before any staging" in r.out and r.staged == [])
    ok("attack 2a (taxonomy self-widening): the pinned snapshot is what refused "
       "it", "differs from the snapshot this record pinned" in r.out)
    ok("attack 2a: the seed taxonomy does NOT protect itself — only the code "
       "floor does", not tx.taxonomy_self_protects(tx.load_taxonomy(text=TAX_SELF)))

    # 2b: an unrelated authorised edit, with the taxonomy quietly widened
    # alongside it. Only the live-vs-pinned digest can see this one.
    d = sandbox()
    _write(os.path.join(d, "README.md"), "hello\nlegit\n")
    _write(os.path.join(d, TAXONOMY_REL),
           TAX.replace('  - "README.md"', WIDENED_TAIL))
    r = land(d)
    refused("attack 2b (taxonomy widened under an unrelated landing)", r)
    ok("attack 2b: nothing was committed and nothing was left staged",
       not r.moved and r.staged == [])

    # 2b control: the identical landing WITHOUT the taxonomy edit succeeds, so
    # the refusal above is attributable to the taxonomy edit and nothing else.
    d = sandbox()
    _write(os.path.join(d, "README.md"), "hello\nlegit\n")
    r = land(d)
    ok("attack 2b CONTROL: the same landing without the taxonomy edit LANDS",
       r.rc == 0 and r.committed == ["README.md"])


# =========================================================================== #
# ATTACK 3 — STALE CONCURRENT AUTHORIZATION.
# =========================================================================== #
@scenario("attack3")
def attack3():
    # 3a: another session is already inside the [recheck -> commit] window.
    d = sandbox()
    _write(os.path.join(d, "README.md"), "hello\nlegit\n")
    head = git(d, "rev-parse", "HEAD").stdout.strip()
    git(d, "update-ref", "refs/compound-v/triage-landing-lock", head, "")
    r = land(d)
    refused("attack 3a (another session holds the landing lock)", r)
    ok("attack 3a: the gate exits 3 and names the lock ref",
       r.rc == 3 and "triage-landing-lock" in r.out)

    # 3b: nobody holds the lock, but HEAD moves between the gate capturing
    # `expected` and its commit — see RACE above for how that is provoked from
    # inside the gate's own critical section.
    d = sandbox(full="sh @D@/race.sh @D@", race=True)
    _write(os.path.join(d, "README.md"), "hello\nlegit\n")
    r = land(d)
    ok("attack 3b (HEAD moved inside the window): the CAS REFUSES the landing",
       r.rc == 2 and "HEAD moved under this landing" in r.out)
    ok("attack 3b: the gate's own commit is NOT in history — HEAD is the "
       "concurrent session's commit",
       r.subject == "concurrent session" and not r.receipt)
    demoted("attack 3b (HEAD moved inside the window)", r, "CAS refused")

    # 3b control: identical run, with the concurrent commit suppressed. It lands
    # — so the refusal above is the moved HEAD, not the perturbation that
    # provokes the in-lock floor re-run.
    d = sandbox(full="sh @D@/race.sh @D@", race=True)
    _write(os.path.join(d, "README.md"), "hello\nlegit\n")
    _write(os.path.join(d, ".race-2"), "")
    r = land(d)
    ok("attack 3b CONTROL: with no concurrent commit the same run LANDS",
       r.rc == 0 and r.committed == ["README.md"])


# =========================================================================== #
# PREDICATE 7 — there is no reviewer at DIRECT, so the predicate chain is the
# only enforcement an unattended landing has.
# =========================================================================== #
@scenario("predicate7")
def predicate7():
    d = sandbox(full=RED)
    _write(os.path.join(d, "README.md"), "hello\nlegit\n")
    r = land(d)
    refused("predicate 7 (red full_command)", r)
    demoted("predicate 7 (red full_command)", r, "configured tests failed")

    d = sandbox(contract=False)
    _write(os.path.join(d, "README.md"), "hello\nlegit\n")
    r = land(d)
    refused("predicate 7 (no test_contract at all)", r)
    demoted("predicate 7 (no test_contract at all)", r,
            "no test_contract is declared")

    d = sandbox(full=None)
    _write(os.path.join(d, "README.md"), "hello\nlegit\n")
    r = land(d)
    refused("predicate 7 (contract without full_command)", r)
    demoted("predicate 7 (contract without full_command)", r,
            "test contract did not resolve")


# =========================================================================== #
# PREDICATE 8's REMAINING CLAUSES — the ones a path-identity test does not
# reach. "Outgrows the class" is literally the line budget, and predicate 6 is
# the only thing stopping an auto-route from editing the tests that guard it.
# =========================================================================== #
@scenario("predicate8")
def predicate8():
    d = sandbox()
    _write(os.path.join(d, "README.md"),
           "hello\n" + "".join("line %d\n" % i for i in range(30)))
    r = land(d)
    refused("predicate 8 (the change outgrew the 20-line budget)", r)
    demoted("predicate 8 (the change outgrew the 20-line budget)", r,
            "auto_route_max_lines budget")

    # The same 30 lines, split so the diff stays under budget, LANDS — the
    # refusal above is the budget and not the number of lines being unusual.
    d = sandbox()
    _write(os.path.join(d, "README.md"),
           "hello\n" + "".join("line %d\n" % i for i in range(5)))
    r = land(d)
    ok("predicate 8 CONTROL: the same edit under the budget LANDS",
       r.rc == 0 and r.committed == ["README.md"])

    # Predicate 6: a taxonomy that auto-routes tests/** still cannot auto-route
    # an edit to a test — the class is defined by the code, not only the policy.
    d = sandbox(tax_text=TAX_TESTS, authorised="tests/widget_test.md")
    os.makedirs(os.path.join(d, "tests"))
    _write(os.path.join(d, "tests", "widget_test.md"), "a test\n")
    r = land(d)
    refused("predicate 6 (the realised diff is a test file)", r)
    demoted("predicate 6 (the realised diff is a test file)", r,
            "is a test file (predicate 6)")


# =========================================================================== #
# PREDICATE 9 — the circuit breaker. Everywhere else in this suite it is armed,
# so its refusal path would otherwise never be observed.
# =========================================================================== #
@scenario("predicate9")
def predicate9():
    d = sandbox()
    _write(os.path.join(d, "README.md"), "hello\nlegit\n")
    # The latch, written the way the breaker itself writes it.
    outc.append_breaker(outc.BREAKER_DISARM, reason="scenario latch",
                        stream_path=os.path.join(d, "docs", "superpowers",
                                                 "memory",
                                                 "triage-outcomes.jsonl"))
    r = land(d)
    refused("predicate 9 (breaker latched off)", r)
    demoted("predicate 9 (breaker latched off)", r, "circuit breaker DISARMED")


selected = [(g, fn) for g, fn in _registry if not GROUPS or g in GROUPS]
if not selected:
    sys.exit("no scenario group matched %r — the filter is dead" % (GROUPS,))
for _group, _fn in selected:
    _fn()

print("")
print("scenarios: %d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
PYEOF

# --------------------------------------------------------------------------- #
# Run the scenarios against the SHIPPED gate.
# --------------------------------------------------------------------------- #
echo ""
echo "── scenarios (the gate as commands/v-triage.md ships it)"
SC_OUT="$WORK/scenarios.out"
"$PYBIN" "$SCEN" "$REPO" "$LAND" >"$SC_OUT" 2>&1
sc_rc=$?
cat "$SC_OUT"
pass=$((pass + $(grep -c '^PASS ' "$SC_OUT")))
fail=$((fail + $(grep -c '^FAIL ' "$SC_OUT")))
check "the scenario suite is green against the shipped gate" \
  "$([ "$sc_rc" = 0 ] && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# PLANTED MUTATIONS. Each removes ONE check from a copy of the extracted gate
# and asserts the suite goes red on the assertion that check is supposed to be
# holding up. A check nobody has watched fail is a check nobody should trust.
# --------------------------------------------------------------------------- #
MUTATOR="$WORK/mutate.py"
cat >"$MUTATOR" <<'PYEOF'
import sys
src, dst, mid = sys.argv[1], sys.argv[2], sys.argv[3]
SUBS = {
    # Predicate 8's PATH IDENTITY clause. Without it the realised diff only has
    # to have the same shape as the authorised one, not be it.
    "M1-path-identity": [("if st != [authorised]:", "if False:", 1)],
    # The pinned pre-edit taxonomy snapshot, both halves: the pre-staging
    # live-vs-pinned check and its re-check inside revalidate().
    "M2-taxonomy-pin": [
        ("check(live is not None and live == pinned,", "check(True,", 1),
        ("    if now != pinned:", "    if False:", 1)],
    # The expected-HEAD compare-and-swap, degraded to an unconditional move.
    "M3-cas": [('"HEAD", new, expected)', '"HEAD", new)', 1)],
    # The create-if-absent lock ref, degraded to a call that always succeeds.
    "M4-lock": [('acq = git("update-ref", LOCK, expected, "")',
                 'acq = git("rev-parse", "HEAD")', 1)],
    # The demotion RECORD (AC-05) — the demotion still happens, but silently.
    "M5-record": [("    outc.append_predicted(",
                   "    (lambda *_a, **_k: None)(", 1)],
    # Predicate 7 stops gating the commit, in both the pre-lock and in-lock
    # decisions.
    "M6-predicate-7": [("if not (ok7 and ok8 and ok9):", "if not (ok8 and ok9):",
                        2)],
    # The line budget -- "outgrows the class", literally.
    "M7-line-budget": [("    if total > budget:", "    if False:", 1)],
    # Predicate 6: no test file touched.
    "M8-test-file": [("        if is_test_path(p):", "        if False:", 1)],
    # Predicate 9 stops reading the breaker's exit-code contract.
    "M9-breaker": [("    armed = r.returncode == 0", "    armed = True", 1)],
}
if mid not in SUBS:
    sys.exit("unknown mutation %r" % mid)
text = open(src, encoding="utf-8").read()
for old, new, want in SUBS[mid]:
    got = text.count(old)
    if got != want:
        sys.exit("MUTATION TARGET NOT WHERE THE TEST SAYS (%d hits, wanted %d): %r"
                 % (got, want, old))
    text = text.replace(old, new)
open(dst, "w", encoding="utf-8").write(text)
PYEOF

# mutation <id> <group> <assertion-that-must-go-red> [assertion-that-must-stay-green]
#
# The mutant is re-run against ONLY the scenario group the removed check is
# supposed to be holding up. Running all five groups against all six mutants
# costs three minutes of CI and tells you nothing the group does not.
mutation() {
  local mid="$1" group="$2" want_red="$3" want_green="${4:-}"
  local mut="$WORK/land.$mid.py" out="$WORK/scenarios.$mid.out"
  if ! "$PYBIN" "$MUTATOR" "$LAND" "$mut" "$mid" 2>"$WORK/mut.err"; then
    bad "$mid: the mutation target is where the test says it is"
    sed 's/^/      /' "$WORK/mut.err"
    return
  fi
  ok "$mid: the mutation target is where the test says it is"
  "$PYBIN" "$SCEN" "$REPO" "$mut" "$group" >"$out" 2>&1
  local rc=$?
  check "$mid: the $group scenarios go RED once the check is removed" \
    "$([ "$rc" != "0" ] && echo 1 || echo 0)"
  printf '      red: %s\n' "$(grep -c '^FAIL ' "$out")"
  grep '^FAIL ' "$out" | sed 's/^FAIL /        - /'
  check "$mid: the red assertion is the one this check holds up — \"$want_red\"" \
    "$(grep -q "^FAIL .*$want_red" "$out" && echo 1 || echo 0)"
  if [ -n "$want_green" ]; then
    check "$mid: \"$want_green\" is STILL green (a second, independent check)" \
      "$(grep -q "^PASS .*$want_green" "$out" && echo 1 || echo 0)"
  fi
}

echo ""
echo "── planted mutations (each removes one check and must red one assertion)"
mutation M1-path-identity attack1 \
  "attack 1a (path substitution): the gate REFUSES to land"
mutation M2-taxonomy-pin attack2 \
  "attack 2b (taxonomy widened under an unrelated landing): the gate REFUSES to land" \
  "attack 2a (taxonomy self-widening): the gate REFUSES to land"
mutation M3-cas attack3 \
  "attack 3b (HEAD moved inside the window): the CAS REFUSES the landing"
mutation M4-lock attack3 \
  "attack 3a (another session holds the landing lock): the gate REFUSES to land"
mutation M5-record attack1 \
  "attack 1a (path substitution): the demotion reached the outcome stream"
mutation M6-predicate-7 predicate7 \
  "predicate 7 (red full_command): the gate REFUSES to land"
mutation M7-line-budget predicate8 \
  "predicate 8 (the change outgrew the 20-line budget): the gate REFUSES to land"
mutation M8-test-file predicate8 \
  "predicate 6 (the realised diff is a test file): the gate REFUSES to land"
mutation M9-breaker predicate9 \
  "predicate 9 (breaker latched off): the gate REFUSES to land"

echo ""
echo "───────────────────────────────────────────────────────────────"
printf 'tests/test-triage-landing.sh: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = "0" ] || exit 1
