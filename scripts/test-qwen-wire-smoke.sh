#!/usr/bin/env bash
#
# test-qwen-wire-smoke.sh — runs the REAL `qwen` binary against a local stub HTTP endpoint and
# asserts what actually reaches the wire. No network, no Coding Plan key, no quota consumed.
#
# WHY THIS EXISTS, SEPARATELY FROM test-qwen-worker-stub.sh:
# the stub test validates the argv the worker emits. It cannot validate how the real binary
# INTERPRETS that argv — and that class of defect is not hypothetical here. A docs-only reading
# produced `--sandbox <profile>` in this design's first draft (`-s` is a BOOLEAN, and the env
# var outranks it), and `--allowed-tools` means the opposite of what its name suggests. Both
# would have passed every conceivable argv assertion.
#
# It is also the harness for the live-probe items the adapter records as UNVERIFIED:
#   (a) which shape `--output-format json` really emits,
#   (b) what the session_start envelope really carries (the model-identity assertion reads it),
#   (c) whether `--safe-mode` really suppresses the AGENTS.md context egress,
#   (d) whether an engaged sandbox is observable in the output at all (the containment proof).
#
# THIS IS THE ONLY QWEN TEST THAT SKIPS. test-qwen-worker-stub.sh always runs — it proves the
# worker with a FAKE binary, so a CI runner without the CLI must still execute it.
#
# Exit 0 on pass; non-zero with diagnostics on fail. SKIPs cleanly when `qwen` is absent.

set -euo pipefail

command -v qwen    >/dev/null 2>&1 || { echo "SKIP: qwen not on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "FAIL: python3 not found on PATH"; exit 2; }
command -v git     >/dev/null 2>&1 || { echo "FAIL: git not found on PATH"; exit 2; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SUPERVISOR="$SCRIPT_DIR/compound-v-run-with-timeout.py"
[ -f "$SUPERVISOR" ] || { echo "FAIL: supervisor not found: $SUPERVISOR"; exit 2; }

TMP="$(mktemp -d)"
PORT="${QWEN_SMOKE_PORT:-8797}"
SERVER_PID=""
cleanup() {
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

PASS=0
FAILED=0
check() {
  if [ "$2" = "yes" ]; then PASS=$((PASS + 1)); echo "  ok   - $1"
  else FAILED=$((FAILED + 1)); echo "  FAIL - $1"; fi
}

# --- the stub OpenAI-protocol endpoint ---------------------------------------
CAPTURE="$TMP/requests.jsonl"
cat > "$TMP/server.py" <<'PY'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = sys.argv[2]


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
        except Exception:
            body = None
        with open(LOG, "a") as fh:
            fh.write(json.dumps({
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": body,
                "raw": raw.decode("utf-8", "replace"),
            }) + "\n")
        model = (body or {}).get("model", "stub")
        if (body or {}).get("stream"):
            chunks = [
                {"id": "chatcmpl-stub", "object": "chat.completion.chunk", "created": 0,
                 "model": model, "choices": [{"index": 0, "finish_reason": None,
                                              "delta": {"role": "assistant",
                                                        "content": "SMOKE-OK"}}]},
                {"id": "chatcmpl-stub", "object": "chat.completion.chunk", "created": 0,
                 "model": model, "choices": [{"index": 0, "finish_reason": "stop",
                                              "delta": {}}],
                 "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
            ]
            payload = ("".join("data: %s\n\n" % json.dumps(c) for c in chunks)
                       + "data: [DONE]\n\n").encode()
            ctype = "text/event-stream"
        else:
            payload = json.dumps({
                "id": "chatcmpl-stub", "object": "chat.completion", "created": 0,
                "model": model,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "SMOKE-OK"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }).encode()
            ctype = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        payload = json.dumps({
            "object": "list",
            "data": [{"id": "qwen3-coder-plus", "object": "model", "owned_by": "bailian"}],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
PY

python3 "$TMP/server.py" "$PORT" "$CAPTURE" >/dev/null 2>&1 &
SERVER_PID=$!
python3 - "$PORT" <<'PY'
import sys, time, urllib.request
for _ in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:%s/ping" % sys.argv[1], timeout=0.5).read()
        sys.exit(0)
    except Exception:
        time.sleep(0.1)
sys.stderr.write("stub server did not start\n")
sys.exit(1)
PY

# --- a worktree-shaped checkout with a marked context file -------------------
# AGENTS.md is Qwen Code's DEFAULT context filename. If --safe-mode fails to suppress context
# files, this marker lands in the request body — which is exactly the egress the adapter says
# --safe-mode is closing. A unique token makes that unmissable.
MARKER="QWEN-EGRESS-MARKER-8f2c1d"
WT="$TMP/wt"
mkdir -p "$WT"
( cd "$WT" && git init -q . && printf '# ctx\n%s\n' "$MARKER" > AGENTS.md \
  && printf '%s\n' "$MARKER" > QWEN.md )

SCRATCH="$TMP/home"
mkdir -p "$SCRATCH/.qwen"
cat > "$SCRATCH/.qwen/settings.json" <<'SETTINGS'
{ "security": { "folderTrust": { "enabled": true } } }
SETTINGS

# The sandbox is deliberately configured for a NETWORK-PERMITTING run here, because the whole
# subject of this test is what reaches an endpoint. On macOS that is `restrictive-open`, which
# is still a real Seatbelt confinement. On Linux the worker's container path cannot reach the
# host's 127.0.0.1 at all, so the smoke runs unsandboxed there and says so — sandbox
# ENGAGEMENT is a separate live-probe item, not what this test measures.
SANDBOXED=no
if [ "$(uname -s)" = "Darwin" ] && command -v sandbox-exec >/dev/null 2>&1; then
  SANDBOXED=yes
else
  echo "NOTE: running unsandboxed — a container cannot reach the host stub endpoint"
fi

SESSION_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
OUT_JSON="$TMP/qwen_stdout.json"
ERR_LOG="$TMP/qwen_stderr.log"

# The worker's EXACT flag set. Keep these two in step: if the worker changes, this changes.
set --
set -- "$@" PATH="$PATH" TMPDIR="${TMPDIR:-/tmp}"
set -- "$@" HOME="$SCRATCH" QWEN_HOME="$SCRATCH"
set -- "$@" BAILIAN_CODING_PLAN_API_KEY="smoke-key-not-a-secret"
set -- "$@" OPENAI_BASE_URL="http://127.0.0.1:$PORT/v1"
if [ "$SANDBOXED" = "yes" ]; then
  set -- "$@" QWEN_SANDBOX="sandbox-exec" SEATBELT_PROFILE="restrictive-open"
fi

rc=0
( cd "$WT" && env -i "$@" \
  python3 "$SUPERVISOR" --timeout 90 --grace 3 -- \
    qwen --model "qwen3-coder-plus" \
      --approval-mode=yolo \
      --auth-type openai \
      --output-format json \
      --session-id "$SESSION_ID" \
      --safe-mode \
      --max-subagent-depth 1 \
      --max-session-turns 15 \
      "Reply with the single word OK. Do not use any tools." \
    </dev/null >"$OUT_JSON" 2>"$ERR_LOG" ) || rc=$?

# A parse-time rejection is its own defect class, and the two flag pairs this design forbids
# fail exactly this way ("Cannot use both --yolo (-y) and --approval-mode together").
check "the real parser accepts the pinned argv (no unknown-argument / mutual-exclusion error)" \
      "$(grep -qiE 'cannot use both|unknown argument|unknown option|did you mean' "$ERR_LOG" \
         && echo no || echo yes)"

REQ_COUNT=0
if [ -f "$CAPTURE" ]; then
  REQ_COUNT="$(wc -l < "$CAPTURE" | tr -d ' ')"
fi
check "the CLI reached the stub endpoint under BAILIAN_CODING_PLAN_API_KEY alone" \
      "$([ "$REQ_COUNT" -ge 1 ] && echo yes || echo no)"
if [ "$REQ_COUNT" -lt 1 ]; then
  echo
  echo "  No request was captured. The pinned invocation supplies the key ONLY as"
  echo "  BAILIAN_CODING_PLAN_API_KEY; if the OpenAI auth path reads a different variable name,"
  echo "  this is where that shows up. qwen exit=$rc; stderr follows:"
  head -c 800 "$ERR_LOG" 2>/dev/null || true
  echo
  echo "SELFTEST: $PASS ok, $FAILED fail"
  exit 1
fi

python3 - "$CAPTURE" "$OUT_JSON" "$MARKER" "$SANDBOXED" "$TMP/verdict.txt" <<'PY'
import json, sys

reqs = [json.loads(l) for l in open(sys.argv[1])]
raw_out = open(sys.argv[2], encoding="utf-8", errors="replace").read()
marker, sandboxed = sys.argv[3], sys.argv[4]
out = []


def say(name, cond):
    out.append("%s\t%s" % ("yes" if cond else "no", name))


a = reqs[0]
body = a.get("body") or {}

say("--model reaches the wire as the requested catalog name (got: %r)" % body.get("model"),
    body.get("model") == "qwen3-coder-plus")
say("the request path is the OpenAI chat-completions route (got: %s)" % a.get("path"),
    "/chat/completions" in (a.get("path") or ""))

h = a.get("headers") or {}
say("the key travels as Authorization: Bearer, never in argv",
    (h.get("authorization") or "").startswith("Bearer "))

# --safe-mode disables context files, hooks, extensions, skills AND MCP servers.
blob = json.dumps(reqs, ensure_ascii=False)
say("--safe-mode suppressed the AGENTS.md / QWEN.md context egress", marker not in blob)

tools = sorted((t.get("function") or {}).get("name") or t.get("name") or "?"
               for t in (body.get("tools") or []))
say("no MCP-provided tool reached the wire (tools: %s)" % (", ".join(tools) or "none"),
    not any(str(t).startswith("mcp") for t in tools))

# Live-probe item (a): which capture shape --output-format json really emits.
parsed = None
try:
    parsed = json.loads(raw_out)
except Exception:
    pass
say("--output-format json emits ONE buffered JSON ARRAY (the shape the extractor parses)",
    isinstance(parsed, list))

if isinstance(parsed, list):
    starts = [o for o in parsed
              if isinstance(o, dict) and o.get("type") == "system"
              and o.get("subtype") == "session_start"]
    say("exactly one system/session_start envelope (the model-identity assertion reads it)",
        len(starts) == 1)
    if len(starts) == 1:
        say("session_start carries a model field (got: %r)" % starts[0].get("model"),
            bool(starts[0].get("model")))
        if sandboxed == "yes":
            # Live-probe item (d): the worker's containment proof fails closed on this field.
            say("session_start reports the engaged sandbox (containment proof, got: %r)"
                % starts[0].get("sandbox"), bool(starts[0].get("sandbox")))
    results = [o for o in parsed
               if isinstance(o, dict) and o.get("type") == "result"]
    say("a terminal result element carries usage (the usage extractor reads it)",
        bool(results) and isinstance(results[-1].get("usage"), dict))
else:
    say("--output-format json output could not be parsed as a document at all "
        "(first 200 chars: %r)" % raw_out[:200], False)

open(sys.argv[5], "w").write("\n".join(out) + "\n")
PY

while IFS="$(printf '\t')" read -r verdict name; do
  check "$name" "$verdict"
done < "$TMP/verdict.txt"

echo
echo "SELFTEST: $PASS ok, $FAILED fail"
[ "$FAILED" -eq 0 ] || exit 1
