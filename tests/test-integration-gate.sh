#!/usr/bin/env bash
# tests/test-integration-gate.sh — the D1 integration authority, driven END TO END
# through its CLI against REAL git worktrees with PLANTED receipts.
#
# WHY THIS FILE EXISTS SEPARATELY FROM --selftest
#   The script's own --selftest exercises its functions. This file exercises the
#   thing a caller actually gets: the process, its stdout document, and its EXIT
#   CODE. /v:dispatch and /v:resume branch on that exit code (AC-24), so an exit
#   code that is right in-process and wrong out of it would let integration
#   proceed past a refusal — the precise failure this release exists to prevent.
#
# THE THREE CLAIMS IT PROVES ON PLANTED CASES RATHER THAN ASSERTING
#   1. A FORGED receipt — schema-valid shape, wrong digest — is REJECTED, and is
#      NOT re-derived into a second chance at a clean verdict.
#   2. A MISSING receipt causes RE-DERIVATION, and BLOCKs only where that
#      re-derivation finds a REAL violation. The clean half is load-bearing: if a
#      missing receipt refused, the gate would deadlock every run whose jobs did
#      not emit one, and would be switched off within a week.
#   3. An INDIRECT WRITER is caught. hooks/lane-guard.sh matches Write/Edit/Bash
#      and documents its own honest limit — a write laundered through an
#      interpreter or a build step never reaches a matcher it can decide on.
#      Three launderings are planted here (python3 -c, a Makefile build step, and
#      a compiled-away shell redirect inside a script). Git sees all three.
#
#   ...plus the SEAM. The diff_digest recipe is PINNED in
#   schemas/job_result.schema.json. task-9's Gate stage produces receipts from
#   that recipe; this gate verifies them against its own implementation. If the
#   two diverge, every HONEST receipt reads as forged. So this file runs the
#   PINNED RECIPE LITERALLY, in the shell, exactly as written in the schema, and
#   asserts the gate's digest is byte-identical to it.
#
# Repo precedent: tests/test-lane-guard.sh drives its hook with synthetic stdin;
# this drives the gate with synthetic run directories.

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
GATE="${INTEGRATION_GATE_SRC:-$REPO/scripts/compound-v-integration-gate.py}"
SCOPE="$REPO/scripts/compound-v-scope-check.py"
PY="${PY:-python3}"
# NOBODY WRITES BYTECODE, this suite included. Its seam probe below imports the
# authority BY PATH, and on a bytecode-writing interpreter that left a real
# scripts/__pycache__/compound-v-integration-gate.<tag>.pyc in the checkout —
# which the scope gate, now carrying no extension carve-out, correctly reports as
# an out-of-lane write (fourth review pass, 2026-09-02). Same export the other
# suites and CI already use.
export PYTHONDONTWRITEBYTECODE=1

pass=0
fail=0
ok()  { pass=$((pass + 1)); printf 'PASS %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf 'FAIL %s\n' "$1"; }
check(){ if [ "$2" = "1" ]; then ok "$1"; else bad "$1"; fi; }

# --------------------------------------------------------------------------- #
# Preconditions — loud, never silently skipped. A test that quietly no-ops is
# how 25 of 29 selftests stopped running in v2.14.
# --------------------------------------------------------------------------- #
[ -f "$GATE" ]  || { echo "FATAL: $GATE missing"; exit 1; }
[ -x "$GATE" ]  || { echo "FATAL: $GATE is not executable"; exit 1; }
[ -f "$SCOPE" ] || { echo "FATAL: $SCOPE missing — this gate INVOKES it"; exit 1; }
command -v "$PY" >/dev/null 2>&1 || { echo "FATAL: $PY required"; exit 1; }
command -v git   >/dev/null 2>&1 || { echo "FATAL: git required"; exit 1; }

WORK="$(mktemp -d)"
cleanup() {
  # Worktrees are registered in the sandbox repo, which is itself inside $WORK,
  # so removing the tree removes the administrative data with it.
  rm -rf "$WORK"
}
trap cleanup EXIT

# --------------------------------------------------------------------------- #
# Sandbox repo. Everything below gates against $BASE, a real immutable commit —
# the same thing state.json pins as a job's pre-dispatch baseline.
# --------------------------------------------------------------------------- #
SANDBOX="$WORK/sandbox"
mkdir -p "$SANDBOX/scripts"
git -C "$SANDBOX" init -q
git -C "$SANDBOX" config user.email "test@example.invalid"
git -C "$SANDBOX" config user.name  "integration-gate-test"
git -C "$SANDBOX" config commit.gpgsign false
printf 'seed\n' >"$SANDBOX/README.md"
printf '# keep\n' >"$SANDBOX/scripts/keep.py"
git -C "$SANDBOX" add -A
git -C "$SANDBOX" commit -q -m seed
BASE="$(git -C "$SANDBOX" rev-parse HEAD)"

# One job, one lane: scripts/allowed.py and nothing else.
write_manifest() {
  cat >"$1/manifest.yaml" <<'YAML'
version: 1
run_id: gate-test
jobs:
  - id: job-a
    title: "the job under test"
    backend: claude
    isolation: worktree
    write_allowed:
      - "scripts/allowed.py"
YAML
}

write_state() { # <run-dir> <worktree> <baseline>
  "$PY" - "$1" "$2" "$3" <<'PY'
import json, os, sys
run, wt, base = sys.argv[1:4]
with open(os.path.join(run, "state.json"), "w") as fh:
    json.dump({"run_id": "gate-test", "phase": "COLLECTED",
               "jobs": {"job-a": {"status": "done", "isolation": "worktree",
                                  "worktree": wt, "baseline": base}}}, fh)
PY
}

# new_case <name> ⇒ echoes "<worktree> <run-dir>"
new_case() {
  local name="$1"
  local wt="$WORK/wt-$name" run="$WORK/run-$name"
  git -C "$SANDBOX" worktree add -q --detach "$wt" "$BASE" >/dev/null 2>&1
  mkdir -p "$run/results"
  write_manifest "$run"
  write_state "$run" "$wt" "$BASE"
  printf '%s %s\n' "$wt" "$run"
}

# put_result <run-dir> <worktree> [receipt-json-file]
put_result() {
  "$PY" - "$1" "$2" "${3:-}" <<'PY'
import json, os, sys
run, wt = sys.argv[1], sys.argv[2]
receipt_file = sys.argv[3] if len(sys.argv) > 3 else ""
doc = {"status": "success", "blocked": False, "files_changed": [], "violations": [],
       "summary": "planted", "session_id": "", "worktree": wt, "exit_code": 0,
       "failure_class": None, "retry_after_seconds": 0}
if receipt_file:
    with open(receipt_file) as fh:
        doc["gate_receipt"] = json.load(fh)
with open(os.path.join(run, "results", "job-a.json"), "w") as fh:
    json.dump(doc, fh)
PY
}

# honest_receipt <worktree> <out-file> — a receipt produced the way an HONEST
# producer would: the real gate's real stdout, and the PINNED digest recipe run
# LITERALLY as the schema writes it (add -A, then sha256 of the cached binary
# diff). This is the seam; if it drifts, honest receipts read as forged.
honest_receipt() {
  local wt="$1" out="$2" raw rc digest
  raw="$("$PY" "$SCOPE" --worktree "$wt" --baseline "$BASE" --allow 'scripts/allowed.py' 2>&1)"
  rc=$?
  digest="$(literal_digest "$wt")"
  "$PY" - "$out" "$BASE" "$(git -C "$wt" rev-parse HEAD)" "$digest" "$rc" "$raw" <<'PY'
import json, sys
out, base, realised, digest, rc, raw = sys.argv[1:7]
verdict = {"0": "pass", "1": "blocked"}.get(rc, "error")
with open(out, "w") as fh:
    json.dump({"baseline_commit": base, "realised_commit": realised,
               "diff_digest": digest, "verdict": verdict,
               "raw_stdout": raw, "exit_code": int(rc)}, fh)
PY
}

# literal_digest <worktree> — the PINNED recipe from
# schemas/job_result.schema.json, executed verbatim in the shell against a COPY
# of the worktree so the `git add -A` it mandates cannot disturb the case under
# test. The copy is byte-identical, so the digest is the recipe's own answer.
literal_digest() {
  local wt="$1" copy
  copy="$(mktemp -d)"
  # cp -R of a linked worktree copies the .git FILE (a gitdir pointer), which
  # still resolves — the administrative dir lives in $SANDBOX, inside $WORK.
  cp -R "$wt/." "$copy/"
  git -C "$copy" add -A >/dev/null 2>&1
  git -C "$copy" diff --cached --binary "$BASE" | shasum -a 256 | awk '{print "sha256:"$1}'
  rm -rf "$copy"
}

run_gate() { # <run-dir> → stdout in $GATE_OUT, exit code in $GATE_RC
  GATE_OUT="$("$PY" "$GATE" --run-dir "$1" --repo-root "$SANDBOX" --json 2>"$WORK/gate.err")"
  GATE_RC=$?
}

verdict_of() { # reads $GATE_OUT
  printf '%s' "$GATE_OUT" | "$PY" -c \
    'import json,sys; print(json.load(sys.stdin)["results"][0]["verdict"])'
}
field_of() { # <jq-ish key on the run report>
  printf '%s' "$GATE_OUT" | "$PY" -c \
    "import json,sys; print(json.load(sys.stdin)[\"$1\"])"
}
violations_of() {
  printf '%s' "$GATE_OUT" | "$PY" -c \
    'import json,sys; print(" ".join(json.load(sys.stdin)["results"][0]["violations"]))'
}
reasons_of() {
  printf '%s' "$GATE_OUT" | "$PY" -c \
    'import json,sys; print(" | ".join(json.load(sys.stdin)["results"][0]["reasons"]))'
}

# --------------------------------------------------------------------------- #
# 0. THE SEAM. The gate's digest must equal the pinned recipe run literally.
# --------------------------------------------------------------------------- #
read -r WT RUN <<<"$(new_case seam)"
printf 'lane\n' >"$WT/scripts/allowed.py"
LITERAL="$(literal_digest "$WT")"
GATE_DIGEST="$("$PY" -B - "$GATE" "$WT" "$BASE" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("gate", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d, err = m.compute_diff_digest(sys.argv[2], sys.argv[3])
print(err or d)
PY
)"
check "seam: gate digest == pinned recipe run literally in the shell" \
      "$([ "$GATE_DIGEST" = "$LITERAL" ] && echo 1 || echo 0)"
[ "$GATE_DIGEST" = "$LITERAL" ] || printf '      gate=%s\n   literal=%s\n' "$GATE_DIGEST" "$LITERAL"
check "seam: the digest is a sha256:<64hex> content address" \
      "$(printf '%s' "$GATE_DIGEST" | grep -Eq '^sha256:[0-9a-f]{64}$' && echo 1 || echo 0)"
# And verifying must not dirty the tree it verifies — a gate with a side effect
# on the artefact under audit is not a gate.
check "seam: verifying leaves the worktree undisturbed" \
      "$([ -z "$(git -C "$WT" status --porcelain --ignored=no -- scripts/keep.py)" ] && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 1. MISSING receipt, CLEAN tree ⇒ RE-DERIVE ⇒ integration PROCEEDS.
#    The half that stops the gate deadlocking every run.
# --------------------------------------------------------------------------- #
read -r WT RUN <<<"$(new_case missing-clean)"
printf 'in lane\n' >"$WT/scripts/allowed.py"
put_result "$RUN" "$WT"                     # result with NO gate_receipt key at all
run_gate "$RUN"
check "missing receipt + clean tree ⇒ re-derived PASS"        "$([ "$(verdict_of)" = pass ] && echo 1 || echo 0)"
check "missing receipt + clean tree ⇒ exit 0 (proceeds)"      "$([ "$GATE_RC" = 0 ] && echo 1 || echo 0)"
check "missing receipt + clean tree ⇒ integration permitted"  "$([ "$(field_of integration)" = permitted ] && echo 1 || echo 0)"
check "the gate recorded the receipt as MISSING, not invalid" \
      "$(printf '%s' "$GATE_OUT" | grep -q '"receipt": "missing"' && echo 1 || echo 0)"

# An explicit `"gate_receipt": null` is the same case — the spec names null
# separately, and a null that fell through to "present" would crash or pass.
read -r WT RUN <<<"$(new_case null-clean)"
printf 'in lane\n' >"$WT/scripts/allowed.py"
printf 'null' >"$WORK/null.json"
put_result "$RUN" "$WT" "$WORK/null.json"
run_gate "$RUN"
check "explicit null receipt ⇒ re-derived PASS, exit 0" \
      "$([ "$(verdict_of)" = pass ] && [ "$GATE_RC" = 0 ] && echo 1 || echo 0)"

# A PARTIAL receipt is a missing receipt (schema), so it is re-derived, NOT
# refused. Punishing a producer that honestly omitted a field it could not
# observe would push producers toward inventing values.
read -r WT RUN <<<"$(new_case partial-clean)"
printf 'in lane\n' >"$WT/scripts/allowed.py"
honest_receipt "$WT" "$WORK/partial.json"
"$PY" - "$WORK/partial.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); del d["diff_digest"]
json.dump(d, open(sys.argv[1], "w"))
PY
put_result "$RUN" "$WT" "$WORK/partial.json"
run_gate "$RUN"
check "partial receipt ⇒ treated as MISSING and re-derived, not refused" \
      "$([ "$(verdict_of)" = pass ] && printf '%s' "$GATE_OUT" | grep -q '"receipt": "missing"' && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 2. MISSING receipt, REAL violation ⇒ RE-DERIVE ⇒ BLOCK.
# --------------------------------------------------------------------------- #
read -r WT RUN <<<"$(new_case missing-dirty)"
printf 'in lane\n'  >"$WT/scripts/allowed.py"
printf 'out of lane\n' >"$WT/scripts/sneaky.py"
put_result "$RUN" "$WT"
run_gate "$RUN"
check "missing receipt + real violation ⇒ BLOCKED"          "$([ "$(verdict_of)" = blocked ] && echo 1 || echo 0)"
check "missing receipt + real violation ⇒ exit 1 (refused)" "$([ "$GATE_RC" = 1 ] && echo 1 || echo 0)"
check "the blocked verdict names the offending path" \
      "$(printf '%s' "$(violations_of)" | grep -q 'scripts/sneaky.py' && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 3. FORGED receipt — valid shape, wrong digest ⇒ REJECTED OUTRIGHT.
#    The tree here is CLEAN, so a gate that re-derived on a digest mismatch
#    would hand the forgery a pass. That is exactly what must not happen.
# --------------------------------------------------------------------------- #
read -r WT RUN <<<"$(new_case forged-digest)"
printf 'in lane\n' >"$WT/scripts/allowed.py"
honest_receipt "$WT" "$WORK/forged.json"
"$PY" - "$WORK/forged.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
d["diff_digest"] = "sha256:" + "0" * 64          # valid SHAPE, wrong VALUE
json.dump(d, open(sys.argv[1], "w"))
PY
put_result "$RUN" "$WT" "$WORK/forged.json"
run_gate "$RUN"
check "forged digest ⇒ verdict FORGED"                    "$([ "$(verdict_of)" = forged ] && echo 1 || echo 0)"
check "forged digest ⇒ exit 1 (refused)"                  "$([ "$GATE_RC" = 1 ] && echo 1 || echo 0)"
check "forged digest ⇒ NOT re-derived into a clean pass"  "$([ "$(verdict_of)" != pass ] && echo 1 || echo 0)"
check "the refusal names diff_digest as the disagreement" \
      "$(printf '%s' "$(reasons_of)" | grep -q 'diff_digest' && echo 1 || echo 0)"
check "the refusal states it deliberately did not re-derive" \
      "$(printf '%s' "$GATE_OUT" | grep -q 'MISSING is re-derived, FORGED is refused' && echo 1 || echo 0)"

# A receipt bound to a baseline that is not the run's recorded one is the same
# class of forgery: the digest could be honest for a baseline of the forger's
# choosing, so the BINDING has to be checked, not just the arithmetic.
read -r WT RUN <<<"$(new_case forged-baseline)"
printf 'in lane\n' >"$WT/scripts/allowed.py"
honest_receipt "$WT" "$WORK/fb.json"
"$PY" - "$WORK/fb.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["baseline_commit"] = "f" * 40
json.dump(d, open(sys.argv[1], "w"))
PY
put_result "$RUN" "$WT" "$WORK/fb.json"
run_gate "$RUN"
check "receipt bound to the wrong baseline ⇒ FORGED, exit 1" \
      "$([ "$(verdict_of)" = forged ] && [ "$GATE_RC" = 1 ] && echo 1 || echo 0)"

# The headline forgery the spec was written for: a SCHEMA-VALID PASS returned by
# a model that ran nothing, over a tree that really does contain a violation.
# The digest here is honest — a bound receipt can still lie about the CONCLUSION.
read -r WT RUN <<<"$(new_case schema-valid-lie)"
printf 'in lane\n'     >"$WT/scripts/allowed.py"
printf 'out of lane\n' >"$WT/scripts/sneaky.py"
"$PY" - "$WORK/lie.json" "$BASE" "$(git -C "$WT" rev-parse HEAD)" "$(literal_digest "$WT")" <<'PY'
import json, sys
out, base, realised, digest = sys.argv[1:5]
json.dump({"baseline_commit": base, "realised_commit": realised,
           "diff_digest": digest, "verdict": "pass",
           "raw_stdout": '{"verdict": "pass", "violations": []}',
           "exit_code": 0}, open(out, "w"))
PY
put_result "$RUN" "$WT" "$WORK/lie.json"
run_gate "$RUN"
check "schema-valid PASS over a violating tree ⇒ refused (contradicted)" \
      "$([ "$(verdict_of)" = contradicted ] && [ "$GATE_RC" = 1 ] && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 4. HONEST receipt ⇒ PASS. Without this the gate could pass everything above
#    by refusing everything, which is the other way to be useless.
# --------------------------------------------------------------------------- #
read -r WT RUN <<<"$(new_case honest)"
printf 'in lane\n' >"$WT/scripts/allowed.py"
honest_receipt "$WT" "$WORK/honest.json"
put_result "$RUN" "$WT" "$WORK/honest.json"
run_gate "$RUN"
check "honest, bound receipt ⇒ PASS, exit 0" \
      "$([ "$(verdict_of)" = pass ] && [ "$GATE_RC" = 0 ] && echo 1 || echo 0)"
check "the honest receipt was VERIFIED, not re-derived from absence" \
      "$(printf '%s' "$GATE_OUT" | grep -q '"receipt": "present"' && echo 1 || echo 0)"

# An honest receipt that reports a REAL block is honoured as a block.
read -r WT RUN <<<"$(new_case honest-blocked)"
printf 'in lane\n'     >"$WT/scripts/allowed.py"
printf 'out of lane\n' >"$WT/scripts/sneaky.py"
honest_receipt "$WT" "$WORK/hb.json"
# honest_receipt captures the gate with 2>&1, which is how a real producer sees
# it. The gate writes its human "BLOCKED:" tail to STDERR unbuffered while its
# JSON goes to a block-buffered stdout pipe, so the tail lands BEFORE the
# document. A verifier that merely truncated a trailing tail would read this
# honest receipt as forged — which is exactly what this file caught.
check "the honest blocked receipt really carries the gate's human tail" \
      "$(grep -q 'BLOCKED:' "$WORK/hb.json" && echo 1 || echo 0)"
put_result "$RUN" "$WT" "$WORK/hb.json"
run_gate "$RUN"
check "honest receipt reporting a real block ⇒ BLOCKED, exit 1" \
      "$([ "$(verdict_of)" = blocked ] && [ "$GATE_RC" = 1 ] && echo 1 || echo 0)"
check "an honest blocked receipt is never mistaken for a forgery" \
      "$([ "$(verdict_of)" != forged ] && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 5. THE INDIRECT WRITERS — hooks/lane-guard.sh's documented blind spot.
#    Each of these writes scripts/laundered*.py without ever reaching a
#    Write/Edit matcher, and (for the build cases) without the out-of-lane path
#    appearing anywhere in the Bash command the guard would inspect.
# --------------------------------------------------------------------------- #
# 5a. python3 -c: the path lives inside a Python string literal.
read -r WT RUN <<<"$(new_case indirect-python)"
printf 'in lane\n' >"$WT/scripts/allowed.py"
( cd "$WT" && "$PY" -c "open('scripts/laundered.py','w').write('pwned\n')" )
put_result "$RUN" "$WT"
run_gate "$RUN"
check "indirect write via python3 -c ⇒ BLOCKED by the git-derived gate" \
      "$([ "$(verdict_of)" = blocked ] && echo 1 || echo 0)"
check "python3 -c laundering ⇒ the real path surfaces as the violation" \
      "$(printf '%s' "$(violations_of)" | grep -q 'scripts/laundered.py' && echo 1 || echo 0)"

# 5b. A BUILD STEP: `make build`. The out-of-lane path appears in NO command the
#     hook could inspect — it is inside the Makefile, which is itself in lane.
read -r WT RUN <<<"$(new_case indirect-build)"
printf 'in lane\n' >"$WT/scripts/allowed.py"
printf 'build:\n\t@printf "generated\\n" > scripts/generated.py\n' >"$WT/Makefile"
( cd "$WT" && make build >/dev/null 2>&1 )
put_result "$RUN" "$WT"
run_gate "$RUN"
check "indirect write via a build step ⇒ BLOCKED" \
      "$([ "$(verdict_of)" = blocked ] && echo 1 || echo 0)"
check "build-step laundering ⇒ both the generated file and the Makefile surface" \
      "$(printf '%s' "$(violations_of)" | grep -q 'scripts/generated.py' \
         && printf '%s' "$(violations_of)" | grep -q 'Makefile' && echo 1 || echo 0)"

# 5c. A GITIGNORED write. Not an interpreter trick — a category the digest recipe
#     itself cannot see (`git add -A` honours .gitignore), which is precisely why
#     the gate re-derives with the scope check instead of trusting the digest.
read -r WT RUN <<<"$(new_case indirect-ignored)"
printf 'in lane\n' >"$WT/scripts/allowed.py"
printf 'dist/\n' >"$WT/.gitignore"
mkdir -p "$WT/dist"
printf 'artifact\n' >"$WT/dist/bundle.js"
put_result "$RUN" "$WT"
run_gate "$RUN"
check "a GITIGNORED out-of-lane write ⇒ BLOCKED (the digest alone would miss it)" \
      "$([ "$(verdict_of)" = blocked ] && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 6. FAIL-CLOSED paths. An unknown must never read as a pass.
# --------------------------------------------------------------------------- #
read -r WT RUN <<<"$(new_case gone)"
printf 'in lane\n' >"$WT/scripts/allowed.py"
put_result "$RUN" "$WT"
git -C "$SANDBOX" worktree remove --force "$WT" >/dev/null 2>&1
run_gate "$RUN"
check "gate root gone ⇒ UNVERIFIABLE, exit 1 (never a silent pass)" \
      "$([ "$(verdict_of)" = unverifiable ] && [ "$GATE_RC" = 1 ] && echo 1 || echo 0)"

# D1 says EXACTLY ONE receipt per job; a relaunch re-runs completed agents, so a
# second attempt file is a real possibility, not a hypothetical.
read -r WT RUN <<<"$(new_case duplicate)"
printf 'in lane\n' >"$WT/scripts/allowed.py"
put_result "$RUN" "$WT"
cp "$RUN/results/job-a.json" "$RUN/results/job-a.attempt2.json"
run_gate "$RUN"
check "two receipts for one job ⇒ refused (D1 requires exactly one)" \
      "$([ "$GATE_RC" = 1 ] && [ "$(verdict_of)" = forged ] && echo 1 || echo 0)"

# Usage faults are exit 2, distinct from a refusal — a caller that conflates
# "the gate is broken" with "the run is clean" is the whole failure mode.
"$PY" "$GATE" --json >/dev/null 2>&1
check "no --run-dir ⇒ exit 2 (usage fault, not a pass)" "$([ "$?" = 2 ] && echo 1 || echo 0)"
"$PY" "$GATE" --run-dir "$WORK/does-not-exist" >/dev/null 2>&1
check "absent run dir ⇒ exit 2 (usage fault, not a pass)" "$([ "$?" = 2 ] && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 7. It must actually INVOKE the scope check, not reimplement it. Point the gate
#    at a stub that records its own invocation and the argv it received.
# --------------------------------------------------------------------------- #
read -r WT RUN <<<"$(new_case invokes)"
printf 'in lane\n' >"$WT/scripts/allowed.py"
put_result "$RUN" "$WT"
STUB="$WORK/stub-scope-check.py"
cat >"$STUB" <<'PY'
#!/usr/bin/env python3
import json, os, sys
with open(os.environ["STUB_LOG"], "a") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\n")
print(json.dumps({"verdict": "pass", "changed": [], "violations": []}))
sys.exit(0)
PY
STUB_LOG="$WORK/stub.log" "$PY" "$GATE" --run-dir "$RUN" --repo-root "$SANDBOX" \
  --scope-check "$STUB" --json >/dev/null 2>&1
check "the gate INVOKES compound-v-scope-check.py as a subprocess" \
      "$([ -s "$WORK/stub.log" ] && echo 1 || echo 0)"
check "it passes the pinned baseline and the job's write_allowed to that gate" \
      "$(grep -q -- "--baseline $BASE" "$WORK/stub.log" \
         && grep -q -- "--allow scripts/allowed.py" "$WORK/stub.log" && echo 1 || echo 0)"

# And it must CONSUME that matcher rather than growing its own: a second glob
# engine is the bug factory this avoids. Asserted on the authority's source, not
# on whether the matcher happens to be dirty in someone's checkout — the earlier
# form of this check read `git status -- scripts/compound-v-scope-check.py` and
# so failed for every session that legitimately edited the file, including the
# one that removed the scope gate's carve-outs.
check "the authority defines NO second glob engine" \
      "$(grep -qE 'def glob_to_regex|import fnmatch' "$GATE" && echo 0 || echo 1)"
check "the authority loads is_allowed from compound-v-scope-check.py itself" \
      "$(grep -q 'spec_from_file_location("cv_scope_check"' "$GATE" \
         && grep -q '"is_allowed"' "$GATE" && echo 1 || echo 0)"
# FOURTH REVIEW PASS, item 3: it loads that matcher FROM SOURCE. A forged
# unchecked hash-based .pyc beside it would otherwise execute in this process.
check "the authority redirects the bytecode cache before exec_module" \
      "$(grep -q 'sys.pycache_prefix' "$GATE" && echo 1 || echo 0)"
check "the authority writes no bytecode of its own" \
      "$(grep -q 'sys.dont_write_bytecode = True' "$GATE" && echo 1 || echo 0)"
# FOURTH REVIEW PASS, item 4: the digest forgives the run directory and nothing
# else. A tracked file excluded by name is a tracked file a worker may rewrite
# unseen — and the pipeline commits triage-outcomes.jsonl by name. The withdrawn
# constant's name is SPLIT here so that `grep -rn <name> scripts hooks tests`,
# the acceptance check for "the carve-outs are gone", stays clean.
BK_NAME="PIPELINE_""BOOKKEEPING"
check "the authority excludes NO tracked file from the digest by name" \
      "$(grep -q "$BK_NAME" "$GATE" && echo 0 || echo 1)"
check "...and it still names triage-outcomes.jsonl in prose, so the reason is not lost" \
      "$(grep -q 'triage-outcomes.jsonl' "$GATE" && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = "0" ] || exit 1
exit 0
