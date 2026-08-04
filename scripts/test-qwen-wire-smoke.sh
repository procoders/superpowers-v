#!/usr/bin/env bash
#
# test-qwen-wire-smoke.sh — runs the REAL `qwen` binary against a local stub HTTP endpoint and
# asserts what actually reaches the wire. No network, no Token Plan key, no credits consumed.
#
# WHY THIS EXISTS, SEPARATELY FROM test-qwen-worker-stub.sh:
# the stub test validates the argv the worker emits. It cannot validate how the real binary
# INTERPRETS that argv — and that class of defect is not hypothetical here. A docs-only reading
# produced `--sandbox <profile>` in this design's first draft (`-s` is a BOOLEAN, and the env
# var outranks it), and `--allowed-tools` means the opposite of what its name suggests. Both
# would have passed every conceivable argv assertion.
#
# It is also the harness that PINS what the 2026-08-04 live probe measured against qwen 0.21.5:
#   (a) `--output-format json` emits one buffered JSON ARRAY,
#   (b) its first element is system/**init** — NOT session_start — and it carries `model`,
#   (c) `--safe-mode` really suppresses the AGENTS.md context egress,
#   (d) the settings.json `modelProviders[].envKey` block is what makes the CLI read
#       BAILIAN_TOKEN_PLAN_API_KEY (without it: "Missing API key for OpenAI-compatible auth").
#
# There is deliberately NO sandbox-engagement assertion. The probe found no `sandbox` key
# anywhere in the output, so engagement is not observable here; it rests on qwen's own
# FatalSandboxError, which the stub test covers.
#
# THIS IS THE ONLY QWEN TEST THAT SKIPS. test-qwen-worker-stub.sh always runs — it proves the
# worker with a FAKE binary, so a CI runner without the CLI must still execute it.
#
# Exit 0 on pass; non-zero with diagnostics on fail. SKIPs cleanly when `qwen` is absent.

set -euo pipefail

command -v qwen    >/dev/null 2>&1 || { echo "SKIP: qwen not on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "FAIL: python3 not found on PATH"; exit 2; }
command -v git     >/dev/null 2>&1 || { echo "FAIL: git not found on PATH"; exit 2; }
command -v jq      >/dev/null 2>&1 || { echo "FAIL: jq not found on PATH"; exit 2; }

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
            "data": [{"id": "qwen3.8-max", "object": "model", "owned_by": "bailian"}],
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

# The worker's EXACT settings file, and it is the AUTH PATH: `envKey` is what points the
# openai provider at BAILIAN_TOKEN_PLAN_API_KEY. Without this block the CLI dies with
# "Missing API key for OpenAI-compatible auth. Set settings.security.auth.apiKey, or set the
# 'OPENAI_API_KEY' environment variable." — measured, which is why OPENAI_API_KEY is never set.
# It goes at $QWEN_HOME/settings.json, NOT $QWEN_HOME/.qwen/settings.json — with QWEN_HOME set
# the config dir IS QWEN_HOME, and a file under `.qwen` there is silently ignored.
SCRATCH="$TMP/home"
mkdir -p "$SCRATCH"
jq -n --arg model "qwen3.8-max" --arg base "http://127.0.0.1:$PORT/v1" \
  '{
     modelProviders: {
       openai: {
         protocol: "openai",
         models: [ { id: $model,
                     name: ($model + " (Token Plan)"),
                     baseUrl: $base,
                     envKey: "BAILIAN_TOKEN_PLAN_API_KEY" } ]
       }
     },
     security: { auth: { selectedType: "openai" }, folderTrust: { enabled: true } },
     model: { name: $model }
   }' > "$SCRATCH/settings.json"

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
set -- "$@" BAILIAN_TOKEN_PLAN_API_KEY="smoke-key-not-a-secret"
set -- "$@" OPENAI_BASE_URL="http://127.0.0.1:$PORT/v1"
if [ "$SANDBOXED" = "yes" ]; then
  set -- "$@" QWEN_SANDBOX="sandbox-exec" SEATBELT_PROFILE="restrictive-open"
fi

rc=0
( cd "$WT" && env -i "$@" \
  python3 "$SUPERVISOR" --timeout 90 --grace 3 -- \
    qwen --model "qwen3.8-max" \
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
check "the CLI reached the stub endpoint with the key named ONLY by settings.json envKey" \
      "$([ "$REQ_COUNT" -ge 1 ] && echo yes || echo no)"
if [ "$REQ_COUNT" -lt 1 ]; then
  echo
  echo "  No request was captured. The pinned invocation supplies the key ONLY as"
  echo "  BAILIAN_TOKEN_PLAN_API_KEY, pointed at by modelProviders[].envKey — OPENAI_API_KEY is"
  echo "  never set. A 'Missing API key for OpenAI-compatible auth' below means that envKey block"
  echo "  stopped working. qwen exit=$rc; stderr follows:"
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
    body.get("model") == "qwen3.8-max")
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

# MEASURED item (a): --output-format json emits ONE buffered top-level JSON ARRAY.
parsed = None
try:
    parsed = json.loads(raw_out)
except Exception:
    pass
say("--output-format json emits ONE buffered JSON ARRAY (the shape the extractor parses)",
    isinstance(parsed, list))

if isinstance(parsed, list):
    # MEASURED item (b): the first element is system/**init**. `session_start` exists in the
    # source but belongs to a different "dual output" protocol this flag does not emit, and
    # the worker read it in its first draft — which would have failed every real run closed.
    inits = [o for o in parsed
             if isinstance(o, dict) and o.get("type") == "system"
             and o.get("subtype") == "init"]
    say("exactly one system/init envelope (the model-identity assertion reads it)",
        len(inits) == 1)
    say("no system/session_start element is emitted (it is a different protocol)",
        not [o for o in parsed
             if isinstance(o, dict) and o.get("subtype") == "session_start"])
    if len(inits) == 1:
        say("system/init carries a model field (got: %r)" % inits[0].get("model"),
            bool(inits[0].get("model")))
        say("system/init carries the measured key set",
            {"model", "session_id", "subtype", "type", "cwd",
             "permission_mode", "qwen_code_version"} <= set(inits[0]))
    # There is NO sandbox key anywhere — that absence is the finding, so assert it rather
    # than quietly dropping the old check. `sandboxed` is reported for the log only.
    say("no `sandbox` key appears anywhere in the output (sandboxed=%s): containment is NOT "
        "observable here" % sandboxed,
        not any(isinstance(o, dict) and "sandbox" in o for o in parsed))
    results = [o for o in parsed
               if isinstance(o, dict) and o.get("type") == "result"]
    say("a terminal result element carries usage (the usage extractor reads it)",
        bool(results) and isinstance(results[-1].get("usage"), dict))
    if results and isinstance(results[-1].get("usage"), dict):
        u = results[-1]["usage"]
        say("usage carries input_tokens / output_tokens / cache_read_input_tokens (got: %s)"
            % sorted(u),
            {"input_tokens", "output_tokens", "cache_read_input_tokens"} <= set(u))
        # Load-bearing on a per-TOKEN plan, unlike the per-request Coding Plan: a trivial
        # prompt still pays for the system preamble plus the whole tool catalog. Reported,
        # not asserted against a threshold — a threshold here would be an invented number.
        say("NOTE input_tokens for a one-word prompt: %r (measured 17277 live; the system "
            "preamble + tool definitions dominate, `--core-tools` is the lever)"
            % u.get("input_tokens"), True)
    say("stats.models is keyed BY MODEL NAME (got: %s)"
        % (sorted((results[-1].get("stats") or {}).get("models") or {}) if results else []),
        bool(results) and "qwen3.8-max" in
        ((results[-1].get("stats") or {}).get("models") or {}))
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
