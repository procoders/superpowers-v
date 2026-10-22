#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
if ! command -v claude >/dev/null 2>&1; then
  echo "SKIP band: no claude CLI on PATH (claude plugin validate/test need >= 2.1.287)"
  exit 0
fi
fails=0
out="$(claude plugin validate . 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q 'run-band.tsx state writes: compound-v.band'; then
  echo "ok   plugin validate accepts the band and its state contract"
else
  echo "FAIL plugin validate (rc=$rc)"; printf '%s\n' "$out" | tail -15; fails=$((fails + 1))
fi
out="$(claude plugin test . 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -qE '^ *0 fail' && printf '%s' "$out" | grep -qE '^ *[1-9][0-9]* pass'; then
  echo "ok   plugin test: $(printf '%s' "$out" | grep -E '^ *[0-9]+ pass' | tr -s ' ')"
else
  echo "FAIL plugin test (rc=$rc)"; printf '%s\n' "$out" | tail -15; fails=$((fails + 1))
fi
[ "$fails" -eq 0 ]
