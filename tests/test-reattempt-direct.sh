#!/usr/bin/env bash
# tests/test-reattempt-direct.sh — a direct-mode job re-attempted after a halt.
#
# v3.8.5 blocked every re-attempt of a direct job (Task 0 of any FULL run) on its
# own bookkeeping: resume-prepare deleted the pin but kept attempt 1's snapshot
# digests, so the gate charged the new jobs/<id>.baseline to the job, forever.
# A hand re-run of /v:dispatch charged the job with every commit since attempt 1.
# Everything here runs in throwaway repos under mktemp: no network, no model.

# `cond && ok || bad` is safe here: ok() always returns 0.
# shellcheck disable=SC2015

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
EMIT="${EMIT_WORKFLOW_SRC:-$REPO/scripts/compound-v-emit-workflow.py}"
SCOPE="$REPO/scripts/compound-v-scope-check.py"
PY="${PY:-python3}"
export PYTHONDONTWRITEBYTECODE=1

T="$(mktemp -d "${TMPDIR:-/tmp}/cv-reattempt.XXXXXX")"
T="$(cd "$T" && pwd -P)"
trap 'rm -rf "$T"' EXIT

pass=0
fail=0
ok()  { pass=$((pass + 1)); echo "  ok   $1"; }
bad() { fail=$((fail + 1)); echo "  FAIL $1"; [ -n "${2:-}" ] && echo "       $2"; }

# setup <name> [stance] -> globals R (repo) and RD (run dir)
setup() {
  R="$T/$1"
  RD="$R/docs/superpowers/execution/r1"
  mkdir -p "$RD"
  git -C "$R" init -q
  git -C "$R" config user.email t@example.invalid
  git -C "$R" config user.name t
  echo seed > "$R/README.md"
  git -C "$R" add -A
  git -C "$R" commit -qm seed
  cat > "$RD/manifest.yaml" <<M
run_id: r1
routing_stance: ${2:-balanced}
max_parallel: 1
jobs:
  - id: d1
    title: foundation
    type: shared_foundation
    backend: claude
    tier: deep
    isolation: direct
    run: serial
    write_allowed: ["src/**"]
    body: "write src/app.txt"
M
  echo '{"phase":"PARTITION_VERIFIED","jobs":{"d1":{"status":"pending","isolation":"direct","worktree":null}}}' > "$RD/state.json"
  git -C "$R" add -A
  git -C "$R" commit -qm "orchestrate r1"
}

reg() {
  "$PY" -B "$EMIT" register-lane --run-dir "$RD" --job-id d1 --cwd "$R" \
    --repo-root "$R" --isolation direct --no-test-contract
}

# gate -> prints "<verdict> <json list of violations>"
gate() {
  "$PY" -B "$EMIT" gate-receipt --run-dir "$RD" --job-id d1 --worktree "$R" \
    --mode direct --repo-root "$R" --scope-check "$SCOPE" \
  | "$PY" -B -c 'import json,sys
d = json.load(sys.stdin)
r = json.loads(d.get("raw_stdout") or "{}")
print(d.get("verdict"), json.dumps(r.get("violations") or []))'
}

commit_docs() {
  git -C "$R" add -A docs "$@"
  git -C "$R" commit -qm "run substrate between attempts"
}

resume_prepare() { "$PY" -B "$EMIT" resume-prepare --run-dir "$RD" >/dev/null; }

pin_line() { grep 'jobs/d1.baseline$' "$RD/preexisting/d1.txt"; }

echo "== control: no commit between attempts"
setup control
reg >/dev/null
mkdir -p "$R/src"; echo v1 > "$R/src/app.txt"
out=$(gate); [ "${out%% *}" = pass ] && ok "attempt 1 passes" || bad "attempt 1 passes" "$out"
reg >/dev/null; rc=$?
[ "$rc" = 0 ] && ok "same-attempt re-registration is admitted" || bad "re-registration rc=$rc"
echo v2 > "$R/src/app.txt"
out=$(gate); [ "${out%% *}" = pass ] && ok "attempt 2 passes" || bad "attempt 2 passes" "$out"

echo "== resume: resume-prepare, then attempts 2 and 3 with in-lane writes"
setup resume
reg >/dev/null
mkdir -p "$R/src"; echo v1 > "$R/src/app.txt"
gate >/dev/null
commit_docs
before=$(pin_line)
resume_prepare
reg >/dev/null; rc=$?
[ "$rc" = 0 ] && ok "attempt 2 registers after resume-prepare" || bad "attempt 2 register rc=$rc"
after=$(pin_line)
[ -n "$after" ] && [ "$before" != "$after" ] \
  && ok "the pin's snapshot line carries the NEW pin's digest" \
  || bad "pin line not re-hashed" "before=$before after=$after"
echo v2 > "$R/src/app.txt"
out=$(gate); [ "${out%% *}" = pass ] && ok "attempt 2 passes" || bad "attempt 2 passes" "$out"
commit_docs
resume_prepare
reg >/dev/null
echo v3 > "$R/src/app.txt"
out=$(gate); [ "${out%% *}" = pass ] && ok "attempt 3 passes" || bad "attempt 3 passes" "$out"

echo "== a halted attempt's out-of-lane leftover is still a violation after resume"
setup leftover
reg >/dev/null
mkdir -p "$R/src"; echo v1 > "$R/src/app.txt"; echo stray > "$R/stray.txt"
out=$(gate)
case "$out" in blocked*stray.txt*) ok "attempt 1 is blocked on stray.txt" ;;
  *) bad "attempt 1 is blocked on stray.txt" "$out" ;; esac
commit_docs
resume_prepare
reg >/dev/null
echo v2 > "$R/src/app.txt"
out=$(gate)
case "$out" in blocked*stray.txt*) ok "attempt 2 is STILL blocked on stray.txt" ;;
  *) bad "attempt 2 is still blocked on stray.txt" "$out" ;; esac
case "$out" in *d1.baseline*) bad "attempt 2 charged with its own pin" "$out" ;;
  *) ok "...and not on its own pin" ;; esac

echo "== re-dispatch with a commit between attempts is refused"
setup redispatch
reg >/dev/null
mkdir -p "$R/src"; echo v1 > "$R/src/app.txt"
gate >/dev/null
mkdir -p "$R/.claude"; echo t > "$R/.claude/compound-v-impact-taxonomy.yaml"
commit_docs .claude
err=$("$PY" -B "$EMIT" emit "$RD/manifest.yaml" --no-recall 2>&1 >/dev/null); rc=$?
[ "$rc" = 2 ] && ok "emit exits 2" || bad "emit exits 2 (rc=$rc)" "$err"
case "$err" in *"/v:resume r1"*"resume-prepare --run-dir $RD"*) ok "emit names /v:resume and resume-prepare" ;;
  *) bad "emit names /v:resume and resume-prepare" "$err" ;; esac
err=$(reg 2>&1 >/dev/null); rc=$?
[ "$rc" = 2 ] && ok "register-lane exits 2" || bad "register-lane exits 2 (rc=$rc)" "$err"
case "$err" in *"/v:resume r1"*) ok "register-lane names /v:resume" ;;
  *) bad "register-lane names /v:resume" "$err" ;; esac
resume_prepare
"$PY" -B "$EMIT" emit "$RD/manifest.yaml" --no-recall >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] && ok "after resume-prepare, emit proceeds" || bad "emit after resume-prepare rc=$rc"
reg >/dev/null; rc=$?
[ "$rc" = 0 ] && ok "...and register-lane pins the current HEAD" || bad "register after resume rc=$rc"
[ "$(cat "$RD/jobs/d1.baseline")" = "$(git -C "$R" rev-parse HEAD)" ] \
  && ok "pin == HEAD" || bad "pin != HEAD"
echo v2 > "$R/src/app.txt"
out=$(gate); [ "${out%% *}" = pass ] && ok "the re-dispatched attempt passes" || bad "re-dispatched attempt" "$out"

echo "== full chain: a blocked attempt, /v:resume, then the re-attempt integrates"
setup chain
gate_json() {
  "$PY" -B "$EMIT" gate-receipt --run-dir "$RD" --job-id d1 --worktree "$R" \
    --mode direct --repo-root "$R" --scope-check "$SCOPE"
}
record() {
  "$PY" -B "$EMIT" record --run-dir "$RD" --job-id d1 --verdict-json "$1" \
    --repo-root "$R" --no-merge >/dev/null 2>&1
}
reg >/dev/null
mkdir -p "$R/src"; echo v1 > "$R/src/app.txt"; echo stray > "$R/stray.txt"
record "$(gate_json)"
rm -f "$R/stray.txt"
commit_docs
resume_prepare
reg >/dev/null
echo v2 > "$R/src/app.txt"
g=$(gate_json)
record "$g"
[ -f "$RD/results/attempts/d1.1.json" ] && ok "Record archived attempt 1 under results/attempts/" \
  || bad "no results/attempts/d1.1.json"
grep -q 'results/attempts/d1.1.json$' "$RD/preexisting/d1.verified.txt" \
  && ok "the gate listed that archive before Record wrote it" \
  || bad "the archive is missing from d1.verified.txt"
fin=$("$PY" -B "$EMIT" finalize-wave --run-dir "$RD" --repo-root "$R" \
  --manifest "$RD/manifest.yaml" --jobs d1 --wave 1 2>&1)
case "$fin" in *contradicted*|*REFUSED*) bad "finalize-wave refused the re-attempt" "$(printf '%s' "$fin" | head -c 400)" ;;
  *) ok "finalize-wave admits the re-attempt (no contradicted verdict)" ;; esac

echo "== escalation never requests fable under cost-aware"
for stance in cost-aware balanced; do
  setup "esc-$stance" "$stance"
  mkdir -p "$RD/results"
  echo '{"job_id":"d1","status":"failed"}' > "$RD/results/d1.json"
  script=$("$PY" -B "$EMIT" emit "$RD/manifest.yaml" --no-recall --print 2>/dev/null)
  model=$(printf '%s\n' "$script" | "$PY" -B -c 'import json,sys
s = sys.stdin.read().split("const CFG = ", 1)[1]
cfg = json.loads(s[:s.index("\n};") + 2])
print(cfg["waves"][0][0]["model"], json.dumps(cfg["escalation"], sort_keys=True))')
  if [ "$stance" = cost-aware ]; then
    [ "$model" = 'opus {"sonnet": "opus"}' ] \
      && ok "cost-aware: failed deep job stays opus, lift map stops at opus" \
      || bad "cost-aware escalation" "$model"
  else
    [ "$model" = 'fable {"opus": "fable", "sonnet": "opus"}' ] \
      && ok "balanced: failed deep job still escalates to fable (unchanged)" \
      || bad "balanced escalation" "$model"
  fi
done

echo "== a manifest without routing_stance takes the project's stance"
setup esc-config cost-aware
sed -i.bak '/^routing_stance:/d' "$RD/manifest.yaml" && rm -f "$RD/manifest.yaml.bak"
mkdir -p "$R/.claude" "$RD/results"
echo '{"stance": "cost-aware"}' > "$R/.claude/compound-v.json"
echo '{"job_id":"d1","status":"failed"}' > "$RD/results/d1.json"
script=$("$PY" -B "$EMIT" emit "$RD/manifest.yaml" --no-recall --print 2>/dev/null)
case "$script" in *fable*) bad "config stance cost-aware: the emitted workflow still names fable" ;;
  *) ok "config stance cost-aware: no fable anywhere in the emitted workflow" ;; esac

echo
echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
