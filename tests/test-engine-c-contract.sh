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
    body: |
      Contract-test fixture task text for job-happy.
    title: happy path — gate passes, floor passes
    backend: claude
    isolation: direct
    test_scope: floor_only
    write_allowed:
      - "src/**"
  - id: job-floorfail
    body: |
      Contract-test fixture task text for job-floorfail.
    title: floor ran and FAILED
    backend: claude
    isolation: direct
    test_scope: full
    write_allowed:
      - "src/**"
  - id: job-blocked
    body: |
      Contract-test fixture task text for job-blocked.
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
    body: |
      Contract-test fixture task text for job-codex.
    title: external backend
    backend: codex
    model: gpt-5.6-sol
    isolation: worktree
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
  --repo-root "$R" --isolation worktree \
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

"$PY" "$EMIT" emit "$XRD/manifest.yaml" --run-dir "$XRD" --repo-root "$R" \
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

# ORPHAN-9: the `actual` event must have a producer on the DEFAULT path.
#
# THE PRODUCER IS FINALIZE-WAVE, NOT RECORD (fourth review pass, 2026-09-02).
# Record writes nothing outside the run directory: an append to a TRACKED file
# from there lands between a direct-mode job's gate and the authority's
# re-derivation of the same tree, and an honest receipt then reads as
# `contradicted`. The append happens once the authority HAS run over the wave —
# run, not permitted, because a refused wave is still an outcome the
# predicted<->actual join has to carry. This wave contains `job-blocked`, so the
# authority here refuses and the `actual` must appear anyway.
STREAM="$R/docs/superpowers/memory/triage-outcomes.jsonl"
if [ -f "$STREAM" ]; then
  fail "record appended the run's actual — that write belongs to the finalizer, after the authority"
else
  pass "record appends no actual: it writes nothing outside the run directory"
fi

# --- 3.4.1 (review-2 of the triage-size feature, finding 1): every external worker's
# tc_validate must ACCEPT the resolver's new slice shape — scope `impacted+referencing`
# plus an integer `selected_count` — and still REJECT a malformed one. Until this check
# the resolver produced a slice that all five workers refused as malformed (exit 2)
# before the model ran; invisible here because this repository dispatches Claude jobs.
TCV="$T/tcv"; mkdir -p "$TCV"
for w in codex antigravity cursor opencode; do
  W="$REPO/scripts/compound-v-run-$w-worker.sh"
  [ -f "$W" ] || { fail "worker script missing: $W"; continue; }
  printf '%s\n' '{"scope":"impacted+referencing","resolved_commands":["true"],"selected_count":2,"floor_command":"true"}' > "$TCV/ok.json"
  printf '%s\n' '{"scope":"impacted+referencing","resolved_commands":["true"],"selected_count":"two"}' > "$TCV/bad-count.json"
  printf '%s\n' '{"scope":"impacted","resolved_commands":["true"],"surprise":1}' > "$TCV/bad-key.json"
  printf '%s\n' '{"scope":"impacted","resolved_commands":["true"],"timeout_s":480}' > "$TCV/ok-timeout.json"
  printf '%s\n' '{"scope":"impacted","resolved_commands":["true"],"timeout_s":0}' > "$TCV/bad-timeout.json"
  # tc_validate leans on the sibling tc_command_at; extract both, verbatim, from the worker.
  run_tcv() { bash -c 'die() { echo "$*" >&2; exit 2; }; eval "$(sed -n "/^tc_command_at()/,/^}/p" "$1")"; eval "$(sed -n "/^tc_validate()/,/^}/p" "$1")"; tc_validate "$2"' _ "$W" "$1" >/dev/null 2>&1; }
  if run_tcv "$TCV/ok.json"; then pass "$w worker: tc_validate ACCEPTS the 3.4.1 slice (impacted+referencing, selected_count)"; else fail "$w worker: tc_validate REJECTS the 3.4.1 slice the resolver now produces"; fi
  if run_tcv "$TCV/bad-count.json"; then fail "$w worker: tc_validate accepted a non-numeric selected_count"; else pass "$w worker: tc_validate rejects a non-numeric selected_count"; fi
  if run_tcv "$TCV/bad-key.json"; then fail "$w worker: tc_validate accepted an unknown key"; else pass "$w worker: tc_validate still rejects an unknown key"; fi
  if run_tcv "$TCV/ok-timeout.json"; then pass "$w worker: tc_validate ACCEPTS timeout_s 480"; else fail "$w worker: tc_validate REJECTS a valid timeout_s 480"; fi
  if run_tcv "$TCV/bad-timeout.json"; then fail "$w worker: tc_validate accepted timeout_s 0"; else pass "$w worker: tc_validate rejects timeout_s 0"; fi
done
"$PY" "$EMIT" finalize-wave --run-dir "$RD" --repo-root "$R" \
  --manifest "$RD/manifest.yaml" --jobs job-happy,job-floorfail,job-blocked \
  --wave 1 >"$T/orphan9.fin.json" 2>"$T/orphan9.fin.err" || true
if grep -q 'REFUSED by scripts/compound-v-integration-gate.py' "$T/orphan9.fin.json"; then
  pass "a wave carrying a blocked job is REFUSED by the authority"
else
  fail "the authority did not refuse a wave carrying a blocked job: $(head -c 300 "$T/orphan9.fin.json")"
fi
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
      + "the FINALIZER appends exactly one precision-IGNORED `actual`, after the "
        "authority (the terminal one is /v:dispatch's, after the merge/commit boundary)")
if not ok:
    print("     got: %s" % json.dumps(actuals)[:400])
sys.exit(0 if ok else 1)
PY
else
  fail "no triage-outcomes.jsonl written — the predicted<->actual join still has "\
"no producer on the Engine C path"
fi
[ "$?" = "0" ] || fails=$((fails + 1))

# ===========================================================================
# 3.0.1's three DISABLING defects. Each block below reproduces one of them as
# an OBSERVABLE outcome, not as an inspection of the source. Every one of them
# failed against 3.0.1; that pre-fix failure is the only thing that makes them
# worth running afterwards.
# ===========================================================================

# A sandboxed COPY of the toolchain, whose own `REPO_DEFAULT` (the directory
# above the script) is a throwaway git repo standing in for an INSTALLED plugin.
# This is what lets CRITICAL-1 be reproduced for real — the wrong-repository
# write actually happens, into $PLUG — while a test can never touch the
# developer's own checkout. Never point this at the real repo.
PLUG="$T/plugins/superpowers-v"
mkdir -p "$PLUG/scripts" "$PLUG/schemas"
cp "$REPO"/scripts/compound-v-*.py "$PLUG/scripts/"
cp "$REPO"/scripts/compound-v-*.sh "$PLUG/scripts/"
cp "$REPO"/schemas/*.json "$PLUG/schemas/" 2>/dev/null || true
# The plugin repo carries a README.md whose blob matches the project's. That is
# not a contrivance to make the bug bite — this plugin HAS a README.md, and so
# does almost every project it would be installed beside. It is what turns "the
# patch was aimed at the wrong repository" from a failed apply into a landed one.
echo "# project" > "$PLUG/README.md"
git -C "$PLUG" init -q .
git -C "$PLUG" config user.email test@example.com
git -C "$PLUG" config user.name "plugin repo"
git -C "$PLUG" add -A
git -C "$PLUG" commit -qm "installed plugin"
SANDBOX_EMIT="$PLUG/scripts/compound-v-emit-workflow.py"

new_repo() {                       # $1 = path
  mkdir -p "$1/src"
  git -C "$1" init -q .
  git -C "$1" config user.email test@example.com
  git -C "$1" config user.name "engine c test"
  echo "# project" > "$1/README.md"
  echo "print(0)" > "$1/src/x.py"
  git -C "$1" add -A
  git -C "$1" commit -qm init
}

seed_state() {                     # $1 = run dir  $2 = job id  $3 = baseline|-
  "$PY" - "$1/state.json" "$2" "$3" <<'PY'
import json, sys
out, job, base = sys.argv[1], sys.argv[2], sys.argv[3]
entry = {"status": "pending"}
if base != "-":
    entry["baseline"] = base
json.dump({"run_id": "d", "phase": "DISPATCHING", "jobs": {job: entry}},
          open(out, "w"), indent=2)
PY
}

seed_lane() {                      # $1 = run dir  $2 = job id  $3 = cwd
  "$PY" - "$1/lane-map.json" "$2" "$3" "$1/manifest.yaml" <<'PY'
import json, sys
json.dump({"run_id": "d", "agents": {}, "manifest": sys.argv[4],
           "worktrees": {sys.argv[3]: sys.argv[2]}},
          open(sys.argv[1], "w"), indent=2)
PY
}

# ---------------------------------------------------------------------------
# CRITICAL 1 — a `direct` job's patch reaching the WRONG repository.
#
# The compliant implementer returns `pwd` as its `worktree`, so that locator is
# never empty and `record` always took the merge_back branch; the emitted Record
# command carried no `--repo-root`, so the destination fell back to the repo
# containing the installed script. Both halves are exercised here.
# ---------------------------------------------------------------------------
APP="$T/app"
new_repo "$APP"
APPBASE="$(git -C "$APP" rev-parse HEAD)"
D1="$T/d1"; mkdir -p "$D1"
cat > "$D1/manifest.yaml" <<'YAML'
run_id: d1
jobs:
  - id: job-direct
    body: |
      Contract-test fixture task text for job-direct.
    title: a direct job that edits the project's README
    backend: claude
    isolation: direct
    write_allowed:
      - "README.md"
YAML
seed_state "$D1" job-direct "$APPBASE"
seed_lane  "$D1" job-direct "$APP"
echo "edited by the job" >> "$APP/README.md"

"$PY" "$SANDBOX_EMIT" gate-receipt --run-dir "$D1" --job-id job-direct \
  --worktree "$APP" --mode direct --repo-root "$APP" \
  > "$T/d1.gate.json" 2>"$T/d1.gate.err" \
  || fail "D1: gate-receipt exited non-zero: $(cat "$T/d1.gate.err")"

# Exactly the invocation 3.0.1 emitted: no --repo-root at all.
"$PY" "$SANDBOX_EMIT" record --run-dir "$D1" --job-id job-direct \
  --manifest "$D1/manifest.yaml" --verdict-json "$(cat "$T/d1.gate.json")" \
  > "$T/d1.record.json" 2>"$T/d1.record.err"
d1rc=$?

if [ "$d1rc" != "0" ]; then
  pass "D1: record with no --repo-root FAILS CLOSED instead of choosing a destination itself"
else
  fail "D1: record ran with no --repo-root and picked a destination itself"
fi
if [ -n "$(git -C "$PLUG" status --porcelain)" ]; then
  fail "D1: the job's patch landed in the PLUGIN repository — $(git -C "$PLUG" status --porcelain | tr '\n' ' ')"
else
  pass "D1: the plugin repository is untouched"
fi

# The emitted Record command must name the destination explicitly.
"$PY" "$EMIT" emit "$D1/manifest.yaml" --run-dir "$D1" --repo-root "$APP" \
  --out "$D1/dispatch.workflow.js" >/dev/null 2>"$T/d1.emit.err" \
  || fail "D1: emit exited non-zero: $(cat "$T/d1.emit.err")"
if [ -f "$D1/dispatch.workflow.js" ]; then
  "$PY" - "$D1/dispatch.workflow.js" <<'PY'
import sys
s = open(sys.argv[1], encoding="utf-8").read()
def seg(marker):
    i = s.find(marker)
    return s[i:i + 800] if i >= 0 else ""
rec = seg("' record' +")
gate = seg("' gate-receipt' +")
def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    return ok
ok = check(bool(rec) and "--repo-root" in rec,
           "D1: the emitted Record command passes --repo-root explicitly")
ok = check(bool(gate) and "--repo-root" in gate,
           "D1: the emitted Gate command passes --repo-root explicitly") and ok
ok = check("CFG.repo_root" in rec,
           "D1: the destination is the run's repo_root, never an agent-reported path") and ok
sys.exit(0 if ok else 1)
PY
  [ "$?" = "0" ] || fails=$((fails + 1))
fi

# A `direct` result must carry `worktree: ""` even though a compliant agent
# registered its project cwd — the branch is the manifest's `isolation`, and a
# non-empty locator must never be what selects merge_back.
D1C="$T/d1c"; mkdir -p "$D1C"
cp "$D1/manifest.yaml" "$D1C/manifest.yaml"
seed_state "$D1C" job-direct "$APPBASE"
seed_lane  "$D1C" job-direct "$APP"
"$PY" "$EMIT" record --run-dir "$D1C" --job-id job-direct \
  --manifest "$D1C/manifest.yaml" --verdict-json "$(cat "$T/d1.gate.json")" \
  --repo-root "$APP" >/dev/null 2>"$T/d1c.err"
"$PY" - "$D1C/results/job-direct.json" <<'PY'
import json, os, sys
p = sys.argv[1]
if not os.path.isfile(p):
    print("FAIL D1: record wrote no result for the direct job")
    sys.exit(1)
doc = json.load(open(p, encoding="utf-8"))
ok = doc.get("worktree") == ""
print(("PASS " if ok else "FAIL ")
      + "D1: a direct job's job_result carries worktree \"\" (the lane map's "
        "project cwd is NOT a worktree locator)")
if not ok:
    print("     got: %r" % doc.get("worktree"))
sys.exit(0 if ok else 1)
PY
[ "$?" = "0" ] || fails=$((fails + 1))

# ---------------------------------------------------------------------------
# CRITICAL 2 — Record integrated before the authority, and never committed.
# ---------------------------------------------------------------------------
APP2="$T/app2"
new_repo "$APP2"
APP2BASE="$(git -C "$APP2" rev-parse HEAD)"
WT2="$T/wt2"
git -C "$APP2" worktree add -q "$WT2" HEAD
D2="$T/d2"; mkdir -p "$D2"
cat > "$D2/manifest.yaml" <<'YAML'
run_id: d2
jobs:
  - id: job-wt
    body: |
      Contract-test fixture task text for job-wt.
    title: a worktree job
    backend: claude
    isolation: worktree
    write_allowed:
      - "src/**"
YAML
seed_state "$D2" job-wt "$APP2BASE"
seed_lane  "$D2" job-wt "$WT2"
echo "print(1)" >> "$WT2/src/x.py"

"$PY" "$EMIT" gate-receipt --run-dir "$D2" --job-id job-wt \
  --worktree "$WT2" --mode worktree --repo-root "$APP2" \
  > "$T/d2.gate.json" 2>"$T/d2.gate.err" \
  || fail "D2: gate-receipt exited non-zero: $(cat "$T/d2.gate.err")"
"$PY" "$EMIT" record --run-dir "$D2" --job-id job-wt \
  --manifest "$D2/manifest.yaml" --verdict-json "$(cat "$T/d2.gate.json")" \
  --repo-root "$APP2" >/dev/null 2>"$T/d2.record.err" \
  || fail "D2: record exited non-zero: $(cat "$T/d2.record.err")"

if [ -z "$(git -C "$APP2" diff --cached --name-only)" ]; then
  pass "D2: record persists EVIDENCE ONLY — it stages nothing in the main checkout"
else
  fail "D2: record staged $(git -C "$APP2" diff --cached --name-only | tr '\n' ' ')in the main checkout, before the authority ever ran"
fi

# The wave finalizer: the authority runs, THEN the wave merges and COMMITS.
D2HEAD_BEFORE="$(git -C "$APP2" rev-parse HEAD)"
"$PY" "$EMIT" finalize-wave --run-dir "$D2" --repo-root "$APP2" \
  --manifest "$D2/manifest.yaml" --jobs job-wt --wave 1 \
  --now "2026-09-01T00:00:00Z" > "$T/d2.fin.json" 2>"$T/d2.fin.err"
d2rc=$?
if [ "$d2rc" = "0" ]; then
  "$PY" - "$T/d2.fin.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
ok = doc.get("integrated") is True and bool(doc.get("commit"))
print(("PASS " if ok else "FAIL ")
      + "D2: the wave finalizer ran the integration authority and committed the wave")
if not ok:
    print("     got: %s" % json.dumps(doc)[:400])
sys.exit(0 if ok else 1)
PY
  [ "$?" = "0" ] || fails=$((fails + 1))
else
  fail "D2: finalize-wave is missing or failed: $(head -3 "$T/d2.fin.err")"
fi

if [ "$(git -C "$APP2" rev-parse HEAD)" != "$D2HEAD_BEFORE" ]; then
  pass "D2: the wave's work is COMMITTED, so no later plain git commit can sweep it in"
else
  fail "D2: HEAD did not move — the wave's patch is still merely staged"
fi
if [ -z "$(git -C "$APP2" diff --cached --name-only)" ]; then
  pass "D2: nothing is left staged for an unrelated commit to pick up"
else
  fail "D2: the finalizer left $(git -C "$APP2" diff --cached --name-only | tr '\n' ' ')staged"
fi
git -C "$APP2" worktree add -q "$T/dep2" HEAD 2>/dev/null
if grep -q "print(1)" "$T/dep2/src/x.py" 2>/dev/null; then
  pass "D2: a DEPENDENT worktree created at HEAD now contains its prerequisite"
else
  fail "D2: a dependent worktree created at HEAD still cannot see its prerequisite"
fi

# The generated script must carry the finalizer, and must stop scheduling.
"$PY" "$EMIT" emit "$D2/manifest.yaml" --run-dir "$D2" --repo-root "$APP2" \
  --out "$D2/dispatch.workflow.js" >/dev/null 2>"$T/d2.emit.err" \
  || fail "D2: emit exited non-zero: $(cat "$T/d2.emit.err")"
if [ -f "$D2/dispatch.workflow.js" ]; then
  "$PY" - "$D2/dispatch.workflow.js" <<'PY'
import sys
s = open(sys.argv[1], encoding="utf-8").read()
def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    return ok
ok = check("finalize-wave" in s,
           "D2: the emitted script runs a serialized wave finalizer")
ok = check("finalizeWave" in s,
           "D2: the finalizer is a real stage, not a closing log line") and ok
ok = check("waveHadFailure" in s and "summary.halted" in s,
           "D2: the wave loop STOPS scheduling after a non-success result") and ok
i = s.find("await pipeline")
j = s.find("finalizeWave(", i if i >= 0 else 0)
ok = check(i >= 0 and j > i,
           "D2: the finalizer runs AFTER the wave's pipeline, before the next wave") and ok
sys.exit(0 if ok else 1)
PY
  [ "$?" = "0" ] || fails=$((fails + 1))
fi

# ---------------------------------------------------------------------------
# HIGH 3 — the external handoff losing its invocation and its worktree.
# ---------------------------------------------------------------------------
APP3="$T/app3"
new_repo "$APP3"
APP3BASE="$(git -C "$APP3" rev-parse HEAD)"
WT3="$T/wt3"
git -C "$APP3" worktree add -q "$WT3" HEAD
D3="$T/d3"; mkdir -p "$D3"
cat > "$D3/manifest.yaml" <<'YAML'
run_id: d3
test_contract:
  floor_command: "sh -c 'exit 0'"
  full_command: "sh -c 'exit 0'"
jobs:
  - id: job-ext
    body: |
      Contract-test fixture task text for job-ext.
    title: an external worker job
    backend: codex
    model: gpt-5.6-sol
    effort: high
    isolation: worktree
    test_scope: floor_only
    timeout_sec: 900
    write_allowed:
      - "src/**"
    acceptance:
      - "src/x.py gains a line"
YAML
seed_state "$D3" job-ext "$APP3BASE"

"$PY" "$EMIT" emit "$D3/manifest.yaml" --run-dir "$D3" --repo-root "$APP3" \
  --out "$D3/dispatch.workflow.js" >/dev/null 2>"$T/d3.emit.err" \
  || fail "D3: emit exited non-zero: $(cat "$T/d3.emit.err")"

if [ -f "$D3/jobs/job-ext.prompt.md" ]; then
  pass "D3: a complete per-job prompt file is materialized BEFORE the workflow runs"
else
  fail "D3: no jobs/job-ext.prompt.md — the worker's --prompt-file points at nothing"
fi
if [ -f "$D3/jobs/job-ext.launch.argv.json" ]; then
  pass "D3: the launcher argv is materialized before the workflow runs"
else
  fail "D3: no jobs/job-ext.launch.argv.json — the invocation exists only as prose"
fi
if [ -f "$D3/dispatch.workflow.js" ]; then
  "$PY" - "$D3/dispatch.workflow.js" "$D3/jobs/job-ext.launch.argv.json" <<'PY'
import json, os, sys
s = open(sys.argv[1], encoding="utf-8").read()
def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    return ok
required = ["--run-id", "--job-id", "--repo", "--prompt-file", "--model",
            "--write-allowed"]
missing = [f for f in required if f not in s]
ok = check(not missing,
           "D3: the emitted launcher carries a COMPLETE argv (missing: %s)"
           % (", ".join(missing) or "none"))
ok = check("compound-v-run-codex-worker.sh ..." not in s
           and "worker-script ..." not in s,
           "D3: the launcher is not an elided placeholder") and ok
if os.path.isfile(sys.argv[2]):
    argv = json.load(open(sys.argv[2], encoding="utf-8"))
    ok = check(isinstance(argv, list) and "..." not in argv,
               "D3: the materialized argv contains no elision") and ok
    ok = check(isinstance(argv, list) and "--model" in argv
               and argv[argv.index("--model") + 1] == "gpt-5.6-sol",
               "D3: the argv pins the manifest's model") and ok
else:
    ok = False
sys.exit(0 if ok else 1)
PY
  [ "$?" = "0" ] || fails=$((fails + 1))
fi

# The baseline must be pinned BEFORE the worker launches — register-lane is the
# only Engine C step that runs early enough.
"$PY" "$EMIT" register-lane --run-dir "$D3" --job-id job-ext --cwd "$WT3" \
  --repo-root "$APP3" --isolation worktree --no-test-contract \
  > "$T/d3.reg.json" 2>"$T/d3.reg.err"
d3rc=$?
if [ "$d3rc" = "0" ]; then
  "$PY" - "$D3/state.json" "$D3" <<'PY'
import json, os, re, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
pin = (state.get("jobs", {}).get("job-ext") or {}).get("baseline")
if not pin:
    p = os.path.join(sys.argv[2], "jobs", "job-ext.baseline")
    if os.path.isfile(p):
        pin = open(p, encoding="utf-8").read().strip()
ok = bool(pin and re.match(r"^[0-9a-f]{40}$", pin))
print(("PASS " if ok else "FAIL ")
      + "D3: register-lane PINS the baseline before the worker launches")
if not ok:
    print("     got: %r" % pin)
sys.exit(0 if ok else 1)
PY
  [ "$?" = "0" ] || fails=$((fails + 1))
else
  fail "D3: register-lane cannot pin a baseline: $(head -3 "$T/d3.reg.err")"
fi

# The Gate's OBSERVED worktree must reach Record. The lane map holds the wrapper
# agent's project cwd, which is not where an external worker changed anything.
seed_lane "$D3" job-ext "$APP3"
echo "print(1)" >> "$WT3/src/x.py"
"$PY" "$EMIT" gate-receipt --run-dir "$D3" --job-id job-ext \
  --worktree "$WT3" --mode worktree --repo-root "$APP3" \
  > "$T/d3.gate.json" 2>"$T/d3.gate.err" \
  || fail "D3: gate-receipt exited non-zero: $(cat "$T/d3.gate.err")"
"$PY" "$EMIT" record --run-dir "$D3" --job-id job-ext \
  --manifest "$D3/manifest.yaml" --verdict-json "$(cat "$T/d3.gate.json")" \
  --repo-root "$APP3" >/dev/null 2>"$T/d3.record.err"
"$PY" - "$D3/results/job-ext.json" "$WT3" <<'PY'
import json, os, sys
p, wt = sys.argv[1], sys.argv[2]
if not os.path.isfile(p):
    print("FAIL D3: record wrote no result for the external job")
    sys.exit(1)
doc = json.load(open(p, encoding="utf-8"))
ok = doc.get("worktree") == wt
print(("PASS " if ok else "FAIL ")
      + "D3: record carries the GATE's observed worktree, not the lane map's cwd")
if not ok:
    print("     got: %r  want: %r" % (doc.get("worktree"), wt))
ok2 = doc.get("files_changed") == ["src/x.py"]
print(("PASS " if ok2 else "FAIL ")
      + "D3: the worker's real change is what reaches the result")
if not ok2:
    print("     got: %r" % (doc.get("files_changed"),))
sys.exit(0 if (ok and ok2) else 1)
PY
[ "$?" = "0" ] || fails=$((fails + 1))

# No pinned baseline ⇒ the gate must FAIL CLOSED, never fall back to a HEAD a
# worker that commits can move.
D3B="$T/d3b"; mkdir -p "$D3B"
cp "$D3/manifest.yaml" "$D3B/manifest.yaml"
seed_state "$D3B" job-ext -
"$PY" "$EMIT" gate-receipt --run-dir "$D3B" --job-id job-ext \
  --worktree "$WT3" --mode worktree --repo-root "$APP3" \
  > "$T/d3b.gate.json" 2>/dev/null
"$PY" - "$T/d3b.gate.json" <<'PY'
import json, os, sys
p = sys.argv[1]
doc = json.load(open(p, encoding="utf-8")) if os.path.getsize(p) else {}
ok = doc.get("verdict") == "error"
print(("PASS " if ok else "FAIL ")
      + "D3: an unpinned baseline FAILS CLOSED instead of falling back to HEAD")
if not ok:
    print("     got verdict: %r" % doc.get("verdict"))
sys.exit(0 if ok else 1)
PY
[ "$?" = "0" ] || fails=$((fails + 1))

# ---------------------------------------------------------------------------
# THE SEALED PATCH and THE MANIFEST DIGEST — the two bindings the merge needs.
#
# `gate-receipt` seals the slice it approved as jobs/<id>.patch and records that
# file's sha256, because the merge used to take a FRESH diff of the live tree:
# whatever the tree said at merge time is what landed, gate or no gate. And the
# manifest — the document declaring every job's write_allowed — is pinned by a
# digest `emit` bakes in, so a lane map widened mid-run is refused, not enforced.
# ---------------------------------------------------------------------------
if [ -f "$RD/receipts/job-happy.gate.json" ]; then
  "$PY" - "$RD" <<'PY'
import hashlib, json, os, sys
rd = sys.argv[1]
doc = json.load(open(os.path.join(rd, "receipts", "job-happy.gate.json")))
rc = 0

def check(ok, label):
    global rc
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        rc = 1

patch = os.path.join(rd, "jobs", "job-happy.patch")
check(os.path.isfile(patch),
      "gate-receipt SEALS the approved slice as jobs/<id>.patch")
if os.path.isfile(patch):
    blob = open(patch, "rb").read()
    check(doc.get("patch_sha256")
          == "sha256:" + hashlib.sha256(blob).hexdigest(),
          "...and the receipt records that artifact's own sha256")
    check(sorted(doc.get("patch_paths") or []) == ["src/a.py", "src/b.py"],
          "...over the approved paths and nothing else")
    check(b"src/a.py" in blob,
          "...and the artifact really carries the job's diff")
sys.exit(rc)
PY
  [ "$?" = "0" ] || fails=$((fails + 1))
else
  fail "no gate receipt for job-happy — nothing to check the seal against"
fi

MD="$(shasum -a 256 "$RD/manifest.yaml" | awk '{print "sha256:"$1}')"
"$PY" "$EMIT" gate-receipt --run-dir "$RD" --job-id job-happy --worktree "$R" \
  --mode direct --repo-root "$R" --manifest-digest "$MD" >/dev/null 2>&1
if [ "$?" = "0" ]; then
  pass "the run's own manifest satisfies the digest emit baked in"
else
  fail "an unmodified manifest was rejected by its own digest"
fi
cp "$RD/manifest.yaml" "$T/manifest.widened.yaml"
printf '      - "**"\n' >>"$T/manifest.widened.yaml"
"$PY" "$EMIT" gate-receipt --run-dir "$RD" --job-id job-happy --worktree "$R" \
  --mode direct --repo-root "$R" --manifest "$T/manifest.widened.yaml" \
  --manifest-digest "$MD" >/dev/null 2>&1
if [ "$?" = "2" ]; then
  pass "a manifest widened after emit ⇒ the gate REFUSES rather than enforcing it"
else
  fail "a widened manifest was enforced as if it were the reviewed one"
fi
"$PY" "$EMIT" record --run-dir "$RD" --job-id job-happy \
  --manifest "$T/manifest.widened.yaml" --manifest-digest "$MD" \
  --verdict-json '{"verdict":"pass"}' --repo-root "$R" >/dev/null 2>&1
if [ "$?" = "2" ]; then
  pass "...and RECORD refuses it too"
else
  fail "record accepted a manifest that no longer hashes to the emitted digest"
fi

# The emitted script must carry the digest to every stage that enforces it.
if [ -f "$D2/dispatch.workflow.js" ]; then
  "$PY" - "$D2/dispatch.workflow.js" <<'PY'
import re, sys
s = open(sys.argv[1], encoding="utf-8").read()
rc = 0

def check(ok, label):
    global rc
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        rc = 1

check(re.search(r'"manifest_digest":\s*"sha256:[0-9a-f]{64}"', s) is not None,
      "emit bakes sha256(manifest.yaml) into CFG.manifest_digest")
for marker, stage in ((" gate-receipt' +", "Gate"), (" record' +", "Record"),
                      (" finalize-wave' +", "Finalize")):
    i = s.find(marker)
    seg = s[i:i + 900] if i >= 0 else ""
    check("--manifest-digest" in seg,
          "the emitted %s command carries --manifest-digest" % stage)
sys.exit(rc)
PY
  [ "$?" = "0" ] || fails=$((fails + 1))
fi

if [ "$fails" = "0" ]; then
  echo "✅ engine-c contract: every generated job_result conforms, the contract "\
"reaches the worker, and the join has a producer"
  exit 0
fi
echo "❌ engine-c contract: $fails check group(s) failed"
exit 1
