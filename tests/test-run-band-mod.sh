#!/usr/bin/env bash
# The run-band mod (hooks/run-band.tsx): the engine's own validator must accept the module
# and its state contract, and its tests must pass on the terminal and desktop surfaces.
#
# `claude plugin validate` and `claude plugin test` need no login. A local `claude` is used
# when it is new enough (function hooks: Claude Code >= 2.1.287); otherwise a pinned CLI is
# fetched with npx, which is what CI does (so each CI run downloads that pinned CLI). No CLI and no npx is a FAILURE, not a skip: a
# guard that silently checks nothing is the v2.14.1 false-green.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PIN="2.1.289"
ge() { [ "$(printf '%s\n%s\n' "$1" "$2" | sort -t. -k1,1n -k2,2n -k3,3n | head -1)" = "$2" ]; }

CLAUDE=()
if command -v claude >/dev/null 2>&1; then
  v="$(claude --version 2>/dev/null | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+' || true)"
  if [ -n "$v" ] && ge "$v" "2.1.287"; then CLAUDE=(claude); fi
fi
if [ "${#CLAUDE[@]}" -eq 0 ]; then
  command -v npx >/dev/null 2>&1 || { echo "FAIL no claude >= 2.1.287 and no npx to fetch one"; exit 1; }
  CLAUDE=(npx -y "@anthropic-ai/claude-code@$PIN")
fi

pass=0; fail=0
ok()  { echo "PASS $1"; pass=$((pass + 1)); }
bad() { echo "FAIL $1"; fail=$((fail + 1)); }

out="$("${CLAUDE[@]}" plugin validate . 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q 'run-band.tsx hooks: session.start, ui.render{component=AbovePrompt}'; then
  ok "plugin validate accepts the module and names its two hooks"
else
  bad "plugin validate (rc=$rc)"; printf '%s\n' "$out" | tail -15
fi
printf '%s' "$out" | grep -q 'state writes: superpowers-v.band' \
  && ok "the module writes only its declared state" || bad "state contract line missing"

out="$("${CLAUDE[@]}" plugin test . 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -qE '^ *0 fail' && printf '%s' "$out" | grep -qE '^ *[1-9][0-9]* pass'; then
  ok "plugin test: $(printf '%s' "$out" | grep -E '^ *[0-9]+ pass' | tr -s ' ')"
else
  bad "plugin test (rc=$rc)"; printf '%s\n' "$out" | tail -25
fi

# The reader the band draws from answers valid JSON with no active run.
doc="$(python3 scripts/compound-v-dashboard.py hud --execution-root "$(mktemp -d)" 2>&1)"
[ "$doc" = '{"run": null}' ] && ok "hud reader: no run -> {\"run\": null}" || bad "hud reader said: $doc"

echo "tests/test-run-band-mod.sh: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
