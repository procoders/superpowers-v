#!/usr/bin/env bash
# Engine C's `job_result` MUST satisfy schemas/job_result.schema.json.
#
# WHY THIS FILE EXISTS. The emitter's own 77-assertion selftest checks that
# fields are PRESENT; it never checked that a produced document CONFORMS. So a
# release shipped in which every Engine C job_result — on the clean happy path,
# not some edge — violated the schema `/v:collect` says the collector validates
# against, in four ways at once: `retry_after_seconds`/`session_id`/`worktree`
# emitted null against `integer`/`string`/`string`, and the RAW `test-floor`
# document (`phase`, `tier_used`, `merge_blocked`, …) assigned straight into a
# `tests` block that is `additionalProperties: false` and requires exactly
# `command`, `exit_code`, `scope`, `selected_count`. `agents/spec-reviewer.md`
# FAILs any job whose `tests.command` is absent, so the default engine's every
# job would have been failed by its own review gate.
#
# The collector's runtime checker walks TOP-LEVEL types only and is blind to the
# `tests` sub-object, which is why neither it nor CI caught this. Hence a test
# that runs the real `gate-receipt` -> `record` pipeline and validates the file
# `record` actually wrote, with `jsonschema` — never by inspection.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
EMIT="$REPO/scripts/compound-v-emit-workflow.py"
SCHEMA="$REPO/schemas/job_result.schema.json"
export PYTHONDONTWRITEBYTECODE=1

fails=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; fails=$((fails + 1)); }

# The interpreter must have pyyaml (the manifest) AND jsonschema (the point of
# this file). CI installs both for `python3`; a dev box often has them only on
# the system interpreter, so try that before giving up. A SKIP is not an option:
# it would be exactly the false-green this test exists to prevent.
PY="${PY:-}"
if [ -z "$PY" ]; then
  for candidate in python3 /usr/bin/python3; do
    if command -v "$candidate" >/dev/null 2>&1 \
       && "$candidate" -c 'import jsonschema, yaml' >/dev/null 2>&1; then
      PY="$candidate"
      break
    fi
  done
fi
if [ -z "$PY" ]; then
  echo "FAIL no python3 with both jsonschema and pyyaml (set PY=<interpreter>);"
  echo "     skipping the validation would be the false-green this test prevents"
  exit 1
fi

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
R="$T/repo"      # the tree the jobs change
RD="$T/run"      # the run dir lives OUTSIDE the repo, so the run substrate the
                 # gate would otherwise see as untracked writes cannot pollute a
                 # job's diff and turn an in-lane change into a false violation.
mkdir -p "$R/src" "$RD"

git -C "$R" init -q .
git -C "$R" config user.email test@example.com
git -C "$R" config user.name "engine c test"
echo "print(1)" > "$R/src/a.py"
echo "print(1)" > "$R/src/b.py"
git -C "$R" add -A
git -C "$R" commit -qm init
BASE="$(git -C "$R" rev-parse HEAD)"

# floor_command PASSES, full_command FAILS: that is what lets one manifest carry
# both a floor-passed job (`floor_only`) and a floor-FAILED one (`full`).
cat > "$RD/manifest.yaml" <<'YAML'
run_id: engine-c-contract-test
triage:
  tier: FULL
  pre_eval_id: pre-eval-engine-c-contract
  taxonomy_digest: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  decided_at: "2026-09-01T00:00:00Z"
test_contract:
  floor_command: "sh -c 'exit 0'"
  full_command: "sh -c 'exit 3'"
jobs:
  - id: job-happy
    title: happy path — gate passes, floor passes
    backend: claude
    isolation: direct
    test_scope: floor_only
    write_allowed:
      - "src/**"
  - id: job-floorfail
    title: floor ran and FAILED
    backend: claude
    isolation: direct
    test_scope: full
    write_allowed:
      - "src/**"
  - id: job-blocked
    title: wrote outside its lane
    backend: claude
    isolation: direct
    test_scope: full
    write_allowed:
      - "docs/**"
YAML

"$PY" - "$RD/state.json" "$BASE" <<'PY'
import json, sys
out, base = sys.argv[1], sys.argv[2]
jobs = {j: {"baseline": base, "status": "pending"}
        for j in ("job-happy", "job-floorfail", "job-blocked")}
with open(out, "w") as fh:
    json.dump({"run_id": "engine-c-contract-test", "phase": "DISPATCHING",
               "jobs": jobs}, fh, indent=2)
PY

# A real change, so the gate has something to measure.
echo "print(2)" >> "$R/src/a.py"
echo "print(2)" >> "$R/src/b.py"

run_job() {
  job="$1"
  "$PY" "$EMIT" gate-receipt --run-dir "$RD" --job-id "$job" \
    --worktree "$R" --mode direct --repo-root "$R" > "$T/$job.gate.json" 2>"$T/$job.gate.err" \
    || { fail "$job: gate-receipt exited non-zero: $(cat "$T/$job.gate.err")"; return 1; }
  "$PY" "$EMIT" record --run-dir "$RD" --job-id "$job" \
    --verdict-json "$(cat "$T/$job.gate.json")" --repo-root "$R" --no-merge \
    > "$T/$job.record.json" 2>"$T/$job.record.err" \
    || { fail "$job: record exited non-zero: $(cat "$T/$job.record.err")"; return 1; }
}

for job in job-happy job-floorfail job-blocked; do
  run_job "$job" || true
done

# ---------------------------------------------------------------------------
# The whole point: validate what `record` WROTE, against the shipped schema.
# ---------------------------------------------------------------------------
"$PY" - "$SCHEMA" "$RD" <<'PY'
import json, os, sys
import jsonschema

schema_path, run_dir = sys.argv[1], sys.argv[2]
schema = json.load(open(schema_path, encoding="utf-8"))
validator = jsonschema.Draft7Validator(schema)
rc = 0

def check(ok, label):
    global rc
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        rc = 1

def load(job):
    path = os.path.join(run_dir, "results", "%s.json" % job)
    if not os.path.isfile(path):
        check(False, "%s: record wrote no results/%s.json" % (job, job))
        return None
    return json.load(open(path, encoding="utf-8"))

def conforms(job, doc):
    errs = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    check(not errs, "%s: job_result conforms to job_result.schema.json" % job)
    for e in errs:
        print("     /%s: %s" % ("/".join(str(p) for p in e.path),
                                e.message.splitlines()[0][:160]))

# --- happy path: gate PASS, floor PASS -------------------------------------
doc = load("job-happy")
if doc:
    conforms("job-happy", doc)
    check(doc.get("status") == "success", "job-happy: status is success")
    tests = doc.get("tests")
    check(isinstance(tests, dict), "job-happy: carries a tests block")
    if isinstance(tests, dict):
        # The four the schema requires, and NOTHING from the raw floor document.
        check(set(tests) <= {"command", "exit_code", "scope", "selected_count",
                             "duration_ms", "failures"},
              "job-happy: tests block carries only schema-declared keys")
        check(bool(str(tests.get("command") or "").strip()),
              "job-happy: tests.command is non-empty (spec-reviewer FAILs a job "
              "whose test command is absent)")
        check(tests.get("exit_code") == 0, "job-happy: tests.exit_code is 0")
        check(tests.get("scope") == "floor_only",
              "job-happy: tests.scope is the contract's own resolved scope")
        check(tests.get("selected_count") == 1,
              "job-happy: tests.selected_count counts the commands that ran")
        check(tests.get("failures") == [],
              "job-happy: tests.failures is measured-and-empty, not absent")
    # The three that were null against integer/string/string.
    check(isinstance(doc.get("retry_after_seconds"), int),
          "job-happy: retry_after_seconds is an integer, not null")
    check(isinstance(doc.get("session_id"), str),
          "job-happy: session_id is a string, not null")
    check(isinstance(doc.get("worktree"), str),
          "job-happy: worktree is a string, not null")

# --- floor RAN and FAILED ---------------------------------------------------
doc = load("job-floorfail")
if doc:
    conforms("job-floorfail", doc)
    tests = doc.get("tests") or {}
    check(tests.get("exit_code") == 3,
          "job-floorfail: tests.exit_code is the failing command's own rc")
    check(tests.get("scope") == "full", "job-floorfail: tests.scope is full")
    check(tests.get("selected_count") == 2,
          "job-floorfail: floor + full_command both ran (no short-circuit)")
    check(isinstance(tests.get("failures"), list) and len(tests["failures"]) == 1,
          "job-floorfail: tests.failures[] names the failing command — without it "
          "'previously failing' is uncomputable and B2's three-set floor degrades")

# --- BLOCKED: the gate refused, so no tests ran -----------------------------
doc = load("job-blocked")
if doc:
    conforms("job-blocked", doc)
    check(doc.get("status") == "blocked", "job-blocked: status is blocked")
    check(doc.get("blocked") is True, "job-blocked: blocked is True")
    check("tests" not in doc,
          "job-blocked: no tests block at all — the job never reached the test "
          "step, and absent is honest where an invented zero is not")

sys.exit(rc)
PY
[ "$?" = "0" ] || fails=$((fails + 1))

# ---------------------------------------------------------------------------
# SEAM-2's sibling seams, guarded here because nothing else runs them.
# ---------------------------------------------------------------------------

# SEAM-1: an external worker must be HANDED the contract — the file has to exist
# before the worker launches (register-lane writes it), and the flag has to be
# emitted uncommented.
cat > "$RD/external.manifest.yaml" <<'YAML'
run_id: engine-c-contract-test
test_contract:
  floor_command: "sh -c 'exit 0'"
  full_command: "sh -c 'exit 0'"
jobs:
  - id: job-codex
    title: external backend
    backend: codex
    test_scope: floor_only
    write_allowed:
      - "src/**"
YAML
"$PY" - "$RD/external.state.json" "$BASE" <<'PY'
import json, sys
with open(sys.argv[1], "w") as fh:
    json.dump({"run_id": "engine-c-contract-test", "phase": "DISPATCHING",
               "jobs": {"job-codex": {"baseline": sys.argv[2], "status": "pending"}}},
              fh, indent=2)
PY
XRD="$T/xrun"
mkdir -p "$XRD"
cp "$RD/external.manifest.yaml" "$XRD/manifest.yaml"
cp "$RD/external.state.json" "$XRD/state.json"

"$PY" "$EMIT" register-lane --run-dir "$XRD" --job-id job-codex --cwd "$R" \
  > "$T/register.json" 2>"$T/register.err" \
  || fail "register-lane exited non-zero: $(cat "$T/register.err")"
if [ -f "$XRD/jobs/job-codex.test-contract.json" ]; then
  pass "register-lane resolves the test contract BEFORE the worker launches"
  "$PY" - "$XRD/jobs/job-codex.test-contract.json" <<'PY' || exit 1
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
ok = set(doc) <= {"scope", "resolved_commands", "floor_command", "full_command"} \
     and doc.get("resolved_commands")
print(("PASS " if ok else "FAIL ") + "the written slice is the shape the workers validate")
sys.exit(0 if ok else 1)
PY
else
  fail "register-lane wrote no jobs/job-codex.test-contract.json — the worker's "\
"--test-contract-file would point at a file that does not exist"
fi

"$PY" "$EMIT" emit "$XRD/manifest.yaml" --run-dir "$XRD" \
  --out "$XRD/dispatch.workflow.js" >/dev/null 2>"$T/emit.err" \
  || fail "emit exited non-zero: $(cat "$T/emit.err")"
if grep -q -- "--test-contract-file" "$XRD/dispatch.workflow.js" 2>/dev/null; then
  if grep -q -- "# --test-contract-file" "$XRD/dispatch.workflow.js"; then
    fail "the emitted worker invocation still COMMENTS OUT --test-contract-file"
  else
    pass "the emitted worker invocation passes --test-contract-file uncommented"
  fi
else
  fail "the emitted worker invocation carries no --test-contract-file at all"
fi

# ORPHAN-9: the `actual` event must have a producer on the DEFAULT path. All
# three jobs above reached a terminal state, so the last `record` appended it.
STREAM="$R/docs/superpowers/memory/triage-outcomes.jsonl"
if [ -f "$STREAM" ]; then
  "$PY" - "$STREAM" <<'PY' || exit 1
import json, sys
actuals = []
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    obj = json.loads(line)
    if obj.get("event") == "actual":
        actuals.append(obj)
ok = len(actuals) == 1 and actuals[0].get("merge_pending") is True \
     and actuals[0].get("pre_eval_id") == "pre-eval-engine-c-contract"
print(("PASS " if ok else "FAIL ")
      + "the record/merge path appends exactly one precision-IGNORED `actual` "
        "(the terminal one is /v:dispatch's, after the merge/commit boundary)")
if not ok:
    print("     got: %s" % json.dumps(actuals)[:400])
sys.exit(0 if ok else 1)
PY
else
  fail "no triage-outcomes.jsonl written — the predicted<->actual join still has "\
"no producer on the Engine C path"
fi
[ "$?" = "0" ] || fails=$((fails + 1))

if [ "$fails" = "0" ]; then
  echo "✅ engine-c contract: every generated job_result conforms, the contract "\
"reaches the worker, and the join has a producer"
  exit 0
fi
echo "❌ engine-c contract: $fails check group(s) failed"
exit 1
