#!/usr/bin/env bash
# tests/test-triage-retaxonomy.sh — re-triage after the impact taxonomy appears, and the
# pre_eval.enabled:false record, driven through the real CLIs in a throwaway repo.
#
# The v3.8.5 failure this pins (partner report, 2026-10): /v:dispatch refused a record
# scored before .claude/compound-v-impact-taxonomy.yaml existed, and re-running /v:triage
# after adding the taxonomy crashed with "already exists with DIFFERENT content" — so the
# record could never be replaced. With pre_eval.enabled:false no record was written at all,
# which --require-triage can never accept.

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
PREEVAL="$REPO/scripts/compound-v-preeval.py"
VALIDATE="$REPO/scripts/compound-v-validate-manifest.py"
TAXONOMY_SRC="$REPO/.claude/compound-v-impact-taxonomy.example.yaml"
PY="${PY:-python3}"
export PYTHONDONTWRITEBYTECODE=1 LANG=C

pass=0
fail=0
ok()  { pass=$((pass + 1)); printf 'PASS %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf 'FAIL %s\n' "$1"; }
check() { if [ "$2" = "1" ]; then ok "$1"; else bad "$1"; fi; }

for f in "$PREEVAL" "$VALIDATE" "$TAXONOMY_SRC"; do
  [ -f "$f" ] || { echo "FATAL: $f missing"; exit 1; }
done
command -v "$PY" >/dev/null 2>&1 || { echo "FATAL: $PY required"; exit 1; }
command -v git >/dev/null 2>&1 || { echo "FATAL: git required"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
R="$WORK/repo"
mkdir -p "$R/src"
printf 'body {}\n' > "$R/src/app.css"
git -C "$R" init -q
git -C "$R" -c user.email=t@example.invalid -c user.name=t add -A
git -C "$R" -c user.email=t@example.invalid -c user.name=t commit -qm init

# field FILE KEY — print one top-level JSON field ("null" for None).
field() {
  "$PY" -c 'import json,sys
v=json.load(open(sys.argv[1])).get(sys.argv[2])
print("null" if v is None else (json.dumps(v) if isinstance(v,(dict,list,bool)) else v))' "$1" "$2"
}

triage() {  # triage OUT REQUEST [extra args...]
  local out="$1" req="$2"
  shift 2
  V_REQ="$req" "$PY" "$PREEVAL" triage --request-env V_REQ --repo "$R" \
    --session-id sess-t --json "$@" >"$out" 2>"$out.err"
}

manifest() {  # manifest FILE PRE_EVAL_ID DIGEST_YAML TIER [extra triage line]
  cat >"$1" <<EOF
run_id: 2026-10-21-retax
feature: "retax"
spec_path: docs/superpowers/specs/2026-10-21-retax.md
plan_path: docs/superpowers/plans/2026-10-21-retax.md
audits:
  archaeology: docs/superpowers/archaeology/2026-10-21-retax.md
  domain: docs/superpowers/expert/2026-10-21-retax.md
  library: docs/superpowers/library-audit/2026-10-21-retax.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
triage:
  tier: $4
  pre_eval_id: $2
  taxonomy_digest: $3
  decided_at: "2026-10-21T09:00:00Z"
${5:-}
jobs:
  - id: task-1-retax
    title: "retax slice"
    type: bounded_crud
    backend: claude
    tier: standard
    effort: medium
    isolation: worktree
    run: parallel
    write_allowed: [src/features/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
EOF
}

validate() {  # validate MANIFEST OUT -> exit code
  "$PY" "$VALIDATE" --require-triage --repo-root "$R" "$1" >"$2" 2>&1
}

REQ="make the button in src/app.css red"

# 1. No taxonomy: FULL with a null digest, which --require-triage refuses with directions.
triage "$WORK/t0.json" "$REQ"
rc=$?
check "triage without a taxonomy succeeds" "$([ $rc -eq 0 ] && echo 1)"
ID0="$(field "$WORK/t0.json" pre_eval_id)"
check "no-taxonomy record is FULL" "$([ "$(field "$WORK/t0.json" tier)" = FULL ] && echo 1)"
D0="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1])).get("taxonomy_digest"))' \
  "$R/docs/superpowers/pre-eval/$ID0.json")"
check "no-taxonomy record has a null digest" "$([ "$D0" = None ] && echo 1)"

manifest "$WORK/m0.yaml" "$ID0" null FULL
validate "$WORK/m0.yaml" "$WORK/v0.out"
rc=$?
check "--require-triage refuses the null-digest record" "$([ $rc -ne 0 ] && echo 1)"
check "the refusal names the taxonomy, /v:init, /v:onboard and the re-triage" \
  "$(grep -q 'compound-v-impact-taxonomy.yaml' "$WORK/v0.out" \
     && grep -q '/v:init' "$WORK/v0.out" && grep -q '/v:onboard' "$WORK/v0.out" \
     && grep -q 're-run /v:triage' "$WORK/v0.out" && echo 1)"

"$PY" "$PREEVAL" record-status --pre-eval-id "$ID0" --repo "$R" --json >"$WORK/s0.json"
rc=$?
check "record-status: the null-digest record is not dispatchable" "$([ $rc -eq 1 ] && echo 1)"

# 2. An unchanged re-run reuses the record (it used to crash on the fresh ts).
sleep 1
triage "$WORK/t0b.json" "$REQ"
rc=$?
check "an unchanged re-run succeeds" "$([ $rc -eq 0 ] && echo 1)"
check "an unchanged re-run reuses the id" \
  "$([ "$(field "$WORK/t0b.json" pre_eval_id)" = "$ID0" ] \
     && [ "$(field "$WORK/t0b.json" reused)" = true ] && echo 1)"

# 3. Add the taxonomy and re-triage: a NEW record that supersedes the old one.
mkdir -p "$R/.claude"
cp "$TAXONOMY_SRC" "$R/.claude/compound-v-impact-taxonomy.yaml"
OLD_BYTES="$(cat "$R/docs/superpowers/pre-eval/$ID0.json")"
triage "$WORK/t1.json" "$REQ"
rc=$?
check "re-triage after adding the taxonomy succeeds (was: DIFFERENT content)" \
  "$([ $rc -eq 0 ] && echo 1)"
[ $rc -eq 0 ] || cat "$WORK/t1.json.err"
ID1="$(field "$WORK/t1.json" pre_eval_id)"
check "re-triage mints a new id" "$([ -n "$ID1" ] && [ "$ID1" != "$ID0" ] && echo 1)"
check "the new record names the one it supersedes" \
  "$([ "$(field "$WORK/t1.json" supersedes)" = "$ID0" ] && echo 1)"
D1="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1])).get("taxonomy_digest"))' \
  "$R/docs/superpowers/pre-eval/$ID1.json")"
check "the new record pins a non-null digest" "$([[ "$D1" == sha256:* ]] && echo 1)"
check "the superseded record is untouched" \
  "$([ "$(cat "$R/docs/superpowers/pre-eval/$ID0.json")" = "$OLD_BYTES" ] && echo 1)"

manifest "$WORK/m1.yaml" "$ID1" "\"$D1\"" "$(field "$WORK/t1.json" tier)"
validate "$WORK/m1.yaml" "$WORK/v1.out"
rc=$?
check "--require-triage accepts the new record" "$([ $rc -eq 0 ] && echo 1)"
[ $rc -eq 0 ] || cat "$WORK/v1.out"

"$PY" "$PREEVAL" record-status --pre-eval-id "$ID0" --repo "$R" --json >"$WORK/s0b.json"
check "record-status: the old record points at its successor" \
  "$([ -n "$ID1" ] && [ "$(field "$WORK/s0b.json" superseded_by)" = "$ID1" ] && echo 1)"
V_REQ="$REQ" "$PY" "$PREEVAL" record-status --request-env V_REQ --repo "$R" --json \
  >"$WORK/s1.json"
rc=$?
check "record-status by request resolves the newest record, dispatchable" \
  "$([ $rc -eq 0 ] && [ "$(field "$WORK/s1.json" pre_eval_id)" = "$ID1" ] && echo 1)"

# 4. pre_eval.enabled:false — a config-disabled FULL record, accepted only while disabled.
printf '{"pre_eval": {"enabled": false}}\n' > "$R/.claude/compound-v.json"
BEFORE="$(find "$R/docs/superpowers/pre-eval" -type f | wc -l)"
triage "$WORK/hook.json" "add a booking page"
AFTER="$(find "$R/docs/superpowers/pre-eval" -type f | wc -l)"
check "disabled without --record-disabled (the hook's call) writes nothing" \
  "$([ "$(field "$WORK/hook.json" disabled)" = true ] && [ "$BEFORE" -eq "$AFTER" ] && echo 1)"
triage "$WORK/td.json" "add a booking page" --record-disabled
IDD="$(field "$WORK/td.json" pre_eval_id)"
check "--record-disabled writes a FULL record" \
  "$([ "$(field "$WORK/td.json" tier)" = FULL ] \
     && [ -f "$R/docs/superpowers/pre-eval/$IDD.json" ] && echo 1)"
manifest "$WORK/md.yaml" "$IDD" null FULL "  disabled_by_config: true"
validate "$WORK/md.yaml" "$WORK/vd.out"
rc=$?
check "--require-triage accepts the config-disabled record while disabled" \
  "$([ $rc -eq 0 ] && echo 1)"
[ $rc -eq 0 ] || cat "$WORK/vd.out"

manifest "$WORK/mfake.yaml" "$ID0" null FULL "  disabled_by_config: true"
validate "$WORK/mfake.yaml" "$WORK/vfake.out"
rc=$?
check "an ordinary null-digest record cannot claim disabled_by_config" \
  "$([ $rc -ne 0 ] && grep -q 'not a config-disabled FULL record' "$WORK/vfake.out" && echo 1)"

printf '{"pre_eval": {"enabled": true}}\n' > "$R/.claude/compound-v.json"
validate "$WORK/md.yaml" "$WORK/vd2.out"
rc=$?
check "the config-disabled record is refused once pre_eval is enabled again" \
  "$([ $rc -ne 0 ] && grep -q 'pre_eval.enabled is not false' "$WORK/vd2.out" && echo 1)"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
