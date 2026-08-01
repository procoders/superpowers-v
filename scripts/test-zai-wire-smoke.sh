#!/usr/bin/env bash
#
# test-zai-wire-smoke.sh — runs the REAL `claude` binary against a local stub HTTP server and
# asserts what actually reaches the wire. No network, no API key, no quota consumed.
#
# WHY THIS EXISTS, SEPARATELY FROM test-zai-worker-stub.sh:
# the stub test validates argv. The defect that broke the first draft of this backend passed
# every conceivable argv assertion, because the argv was exactly as intended — the draft
# pinned `--allowedTools "Read,Grep,Glob,Edit,Write"` and believed that defined the tool set.
# It does not: `--allowedTools` decides which tools run WITHOUT ASKING, `--tools` decides
# which tools EXIST. The wire carried Bash, Edit, Read — `Write` absent, `Bash` present (the
# draft claimed it was withheld), and `Grep`/`Glob` do not exist in this CLI at all. Only the
# real binary's interpretation of the argv reveals that class of defect.
#
# Exit 0 on pass; non-zero with diagnostics on fail. SKIPs cleanly when `claude` is absent,
# so a CI runner without the CLI installed is not a failure.

set -euo pipefail

command -v claude  >/dev/null 2>&1 || { echo "SKIP: claude not on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "FAIL: python3 not found on PATH"; exit 2; }
command -v git     >/dev/null 2>&1 || { echo "FAIL: git not found on PATH"; exit 2; }

TMP="$(mktemp -d)"
PORT="${ZAI_SMOKE_PORT:-8799}"
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

# --- the stub endpoint -------------------------------------------------------
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
            }) + "\n")
        # Answer as a non-streaming Anthropic message so the CLI terminates cleanly.
        payload = json.dumps({
            "id": "msg_stub", "type": "message", "role": "assistant",
            "model": (body or {}).get("model", "stub"),
            "content": [{"type": "text", "text": "SMOKE-OK"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }).encode()
        if (body or {}).get("stream"):
            events = [
                ("message_start", {"type": "message_start", "message": {
                    "id": "msg_stub", "type": "message", "role": "assistant",
                    "model": "stub", "content": [], "stop_reason": None,
                    "usage": {"input_tokens": 1, "output_tokens": 0}}}),
                ("content_block_start", {"type": "content_block_start", "index": 0,
                                         "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "text_delta", "text": "SMOKE-OK"}}),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ("message_delta", {"type": "message_delta",
                                   "delta": {"stop_reason": "end_turn"},
                                   "usage": {"output_tokens": 1}}),
                ("message_stop", {"type": "message_stop"}),
            ]
            payload = "".join(
                "event: %s\ndata: %s\n\n" % (name, json.dumps(d)) for name, d in events
            ).encode()
            ctype = "text/event-stream"
        else:
            ctype = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")


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

SCRATCH="$TMP/home"
mkdir -p "$SCRATCH/.claude"

# The worker's EXACT flag set. Keep these two in step: if the worker changes, this changes.
run_claude() {
  # $1 = working directory
  ( cd "$1" && env -i PATH="$PATH" TMPDIR="${TMPDIR:-/tmp}" \
        HOME="$SCRATCH" CLAUDE_CONFIG_DIR="$SCRATCH/.claude" \
        ANTHROPIC_BASE_URL="http://127.0.0.1:$PORT" \
        ANTHROPIC_AUTH_TOKEN="smoke-token-not-a-secret" \
        ANTHROPIC_MODEL="glm-5.2" \
        ANTHROPIC_DEFAULT_OPUS_MODEL="glm-5.2" \
        ANTHROPIC_DEFAULT_SONNET_MODEL="glm-5.2" \
        ANTHROPIC_DEFAULT_HAIKU_MODEL="glm-5.2" \
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
      claude -p \
        --permission-mode dontAsk \
        --tools "Read,Edit,Write,Bash" \
        --allowedTools "Read,Edit,Write,Bash" \
        --exclude-dynamic-system-prompt-sections \
        --output-format json \
        -- "say hi" </dev/null >/dev/null 2>&1 ) || true
}

# Two DIFFERENT worktrees, so the cross-worktree cache-prefix assertion is meaningful.
for d in wt1 wt2; do
  mkdir -p "$TMP/$d"
  ( cd "$TMP/$d" && git init -q . && printf '%s\n' "$d" > "unique-$d.txt" )
done

: > "$CAPTURE"
run_claude "$TMP/wt1"
run_claude "$TMP/wt2"

REQ_COUNT="$(wc -l < "$CAPTURE" | tr -d ' ')"
check "the CLI reached the stub endpoint" \
      "$([ "$REQ_COUNT" -ge 2 ] && echo yes || echo no)"
[ "$REQ_COUNT" -ge 2 ] || { echo "SELFTEST: $PASS ok, $((FAILED + 1)) fail"; exit 1; }

python3 - "$CAPTURE" "$TMP/verdict.txt" <<'PY'
import json, sys

reqs = [json.loads(l) for l in open(sys.argv[1])]
a, b = reqs[0], reqs[-1]
out = []


def say(name, cond):
    out.append("%s\t%s" % ("yes" if cond else "no", name))


tools = sorted(t.get("name") for t in (a["body"].get("tools") or []))
say("the wire carries EXACTLY Bash, Edit, Read, Write (got: %s)" % ", ".join(tools),
    tools == ["Bash", "Edit", "Read", "Write"])

h = a["headers"]
say("the key travels as Authorization: Bearer", h.get("authorization", "").startswith("Bearer "))
say("no x-api-key header is sent", "x-api-key" not in h)
say("the request path is /v1/messages", a["path"].startswith("/v1/messages"))

sysblk = json.dumps(a["body"].get("system"), ensure_ascii=False)
say("git status is NOT in the cached system block", "gitstatus" not in sysblk.lower())

same_tools = (json.dumps(a["body"].get("tools"), sort_keys=True)
              == json.dumps(b["body"].get("tools"), sort_keys=True))
same_system = (json.dumps(a["body"].get("system"), sort_keys=True)
               == json.dumps(b["body"].get("system"), sort_keys=True))
say("the tools block is byte-identical across two worktrees", same_tools)
say("the system block is byte-identical across two worktrees", same_system)

open(sys.argv[2], "w").write("\n".join(out) + "\n")
PY

while IFS="$(printf '\t')" read -r verdict name; do
  check "$name" "$verdict"
done < "$TMP/verdict.txt"

echo
echo "SELFTEST: $PASS ok, $FAILED fail"
[ "$FAILED" -eq 0 ] || exit 1
