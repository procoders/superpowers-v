#!/usr/bin/env bash
# Engine C per-job usage (v3.4.17) — the CLI contract, end to end.
#
# WHY THIS FILE EXISTS, separately from the script's own --selftest. The
# selftest calls Python functions; this file drives the EXACT command line that
# `commands/v-dispatch.md` step 10 tells the orchestrator to run, and validates
# what `--write` actually put on disk against the SHIPPED
# schemas/job_result.schema.json with a real JSON-Schema engine. The two halves
# fail differently: a function-level test cannot catch a broken flag name, and a
# structural key check cannot catch a type the schema forbids.
#
# It also pins the two properties that make the numbers trustworthy at all:
#
#   1. DEDUPLICATION. One assistant message is written to several JSONL lines as
#      its content blocks stream, each repeating the same cumulative
#      `message.usage`. Summing per line double-counts. The fixture writes one
#      message twice, with the later line carrying the larger output figure.
#   2. RUN DISAMBIGUATION. Job ids repeat across runs (`spec-review-1` appears
#      in 14 transcripts of this repo's own history). The fixture plants a
#      transcript with THIS run's job id under ANOTHER run's --run-dir, and a
#      second one under a DIFFERENT CHECKOUT whose run dir has the SAME
#      basename; both must be unmatched, never folded into this run's total.
#
# Round-1 cross-model review added four more, each with its own fixture:
#
#   3. A JOB ID IS A FILENAME. A manifest carrying an absolute or `../` job id
#      made --write clobber a file outside the run directory.
#   4. THE PROSE SENTENCE IS NOT A KEY. A prompt that merely quotes
#      "Compound V job `x`" with no --job-id must not be attributed to x.
#   5. DEDUPLICATION SPANS THE JOB. The same message id in two transcripts of
#      one job is one message, not two.
#   6. INVALID UTF-8 MUST NOT ABORT THE SCAN. One 0xff byte used to lose the
#      whole run's usage.
#
# Round-2 cross-model review added five more:
#
#   7. ONLY THE STAGE COMMAND IDENTIFIES A JOB. A run dir mentioned in PROSE,
#      while the command names another run, credited the wrong run.
#   8. THE TEMP FILE MUST BE UNPREDICTABLE. A symlink pre-placed at
#      "<result>.cv-usage-tmp" was followed by the write.
#   9. THE SNAPSHOT WINNER IS CHOSEN BY THE RECORD'S OWN ORDER, not by the
#      order filenames sort in.
#  10. A USAGE RECORD WITH NO message.id IS MALFORMED, not a new message.
#  11. A LINE TOO DEEPLY NESTED TO PARSE IS MALFORMED, not a crash.
#
# Round-3 cross-model review added three HIGH:
#
#  12. EVERY INVOCATION ON A LINE IS A COMMAND. `wave...; record...` on one
#      line was read as one command, attributing run-level usage to a job.
#  13. A NUL IN A COMMAND PATH IS REFUSED, never handed to a stat call.
#  14. results/ IS ANCHORED ON THE RUN. A symlinked results directory became
#      its own trusted root and --write replaced a file outside the run.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
EXTRACT="$REPO/scripts/compound-v-usage-extract.py"
AGGREGATE="$REPO/scripts/compound-v-usage-aggregate.py"
SCHEMA="$REPO/schemas/job_result.schema.json"
export PYTHONDONTWRITEBYTECODE=1

fails=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; fails=$((fails + 1)); }
check() { # check <condition-rc> <label>
  if [ "$1" = "0" ]; then pass "$2"; else fail "$2"; fi
}

# The interpreter must have jsonschema: validating the written result is the
# point of this file, and skipping that validation would be the false-green the
# test exists to prevent (same rule as tests/test-engine-c-contract.sh).
PY="${PY:-}"
if [ -z "$PY" ]; then
  for candidate in python3 /usr/bin/python3; do
    if command -v "$candidate" >/dev/null 2>&1 \
       && "$candidate" -c 'import jsonschema' >/dev/null 2>&1; then
      PY="$candidate"
      break
    fi
  done
fi
if [ -z "$PY" ]; then
  echo "FAIL no python3 with jsonschema (set PY=<interpreter>); skipping the"
  echo "     validation would be the false-green this test prevents"
  exit 1
fi

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
RUN="$T/docs/superpowers/execution/2026-09-04-usage-cli-test"
OTHER="$T/docs/superpowers/execution/2026-09-04-a-different-run"
TX="$T/projects/-slug/session/subagents/workflows/wf_test"
mkdir -p "$RUN/results" "$TX"

# Two of these job ids are hostile: an absolute path and a parent walk. Neither
# may become a job, and neither may cause a write outside the run directory.
# The literal emitter path a real stage prompt carries. The matcher keys on this
# name plus one of the emitter's own subcommands, so a fixture using a made-up
# script name would be testing a shape no run ever produces.
EMIT="/repo/scripts/compound-v-emit-workflow.py"
VICTIM="$T/victim"
ESCAPE="$T/docs/superpowers/execution/escape.json"
# SENTINELS at both escape targets. `--write` only touches an EXISTING result
# file, so the hazard is an overwrite, not a creation — the proof must be a file
# that already exists and has to survive untouched.
printf '{"sentinel": "untouched"}\n' > "$VICTIM.json"
printf '{"sentinel": "untouched"}\n' > "$ESCAPE"
cat > "$RUN/manifest.yaml" <<YAML
run_id: 2026-09-04-usage-cli-test
feature: usage CLI test — an em dash, so a C locale cannot decode this file
jobs:
- id: job-one
  type: implement
- id: job-two
  type: review
- id: job-three
  type: implement
- id: $VICTIM
  type: implement
- id: ../../escape
  type: implement
max_parallel: 2
YAML

# Minimal, schema-valid job_result files for --write to merge into.
for job in job-one job-two job-three; do
  cat > "$RUN/results/$job.json" <<JSON
{
  "blocked": false,
  "exit_code": 0,
  "failure_class": null,
  "files_changed": [],
  "retry_after_seconds": 0,
  "session_id": "",
  "status": "success",
  "summary": "ok",
  "violations": [],
  "worktree": ""
}
JSON
done

# --- the transcript fixture ------------------------------------------------
# `u <raw prompt text>` writes the first user line, JSON-encoding the text so the
# fixture can carry real backticks and quotes without shell escaping games.
# `a <id> <in> <out> <cache_read> <cache_create>` writes one assistant line.
u() {
  UTEXT="$1" "$PY" -c 'import json, os, sys
sys.stdout.write(json.dumps({
    "type": "user", "isSidechain": True,
    "message": {"role": "user", "content": os.environ["UTEXT"]},
}) + "\n")'
}
A_FMT='{"type":"assistant","timestamp":"%s","apiBlockIndex":0,'
A_FMT="$A_FMT"'"message":{"id":"%s","model":"claude-opus-5",'
A_FMT="$A_FMT"'"usage":{"input_tokens":%s,"output_tokens":%s,'
A_FMT="$A_FMT"'"cache_read_input_tokens":%s,"cache_creation_input_tokens":%s,'
A_FMT="$A_FMT"'"service_tier":"standard"}}}\n'
# `a <id> <in> <out> <cache_read> <cache_create> [timestamp]`. The timestamp is
# the ordering key; it defaults to a fixed early instant when the case does not
# care which snapshot wins.
# SC2059: the format IS the constant assembled just above (only so no line of
# this file exceeds 120 columns); the caller's arguments are still %s-quoted.
# shellcheck disable=SC2059
a() { printf "$A_FMT" "${6:-2026-09-04T08:00:00.000Z}" "$1" "$2" "$3" "$4" "$5"; }
# An assistant record with usage but NO message.id at all (round-2, NEW 3).
a_noid() {
  printf '{"type":"assistant","timestamp":"%s","message":{"model":"claude-opus-5",' \
    "2026-09-04T08:30:00.000Z"
  printf '"usage":{"input_tokens":%s,"output_tokens":%s,' "$1" "$2"
  printf '"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n'
}

# job-one, transcript 1 of 2: the implement stage. `msg_1` is written TWICE —
# the second line is the same message's later streaming snapshot and must be
# counted ONCE, at 400 rather than 40+400. One malformed line must be skipped
# and counted, never fatal.
{
  u "You are the implementer for Compound V job \`job-one\`.
$EMIT register-lane --run-dir $RUN --job-id job-one --cwd /x"
  a msg_1 10 40 1000 500
  echo '{ not json at all'
  a msg_1 10 400 1000 500
  a msg_2 5 60 2000 0
} > "$TX/agent-a0001.jsonl"

# ...plus a line of invalid UTF-8 in that same transcript. A decoder that
# raises here loses every token job-one has.
"$PY" -c 'import sys; open(sys.argv[1],"ab").write(b"\xff\xfe garbage tail\n")' \
  "$TX/agent-a0001.jsonl"

# job-one, transcript 2 of 2: the gate stage (quoted flags, as Engine C emits).
# It REPEATS msg_2 with a later snapshot (90, not 60): one message id is one
# message even across two transcripts of the same job.
{
  u "Run EXACTLY this one command.
$EMIT gate-receipt --run-dir '$RUN' --job-id 'job-one' --mode 'direct'"
  a msg_3 1 2 3 4
  a msg_2 5 90 2000 0
} > "$TX/agent-a0002.jsonl"

# job-two: one transcript.
{
  u "$EMIT record --run-dir '$RUN' --job-id 'job-two'"
  a msg_4 7 8 9 10
} > "$TX/agent-a0003.jsonl"

# UNMATCHED: this run's job id under a DIFFERENT run's --run-dir.
{
  u "$EMIT gate-receipt --run-dir '$OTHER' --job-id 'job-one'"
  a msg_5 999999 999999 999999 999999
} > "$TX/agent-a0004.jsonl"

# A wave-level stage of THIS run: names --jobs, never a single --job-id.
{
  u "$EMIT finalize-wave --run-dir '$RUN' --wave '1' --jobs 'job-one'"
  a msg_6 2 3 4 5
} > "$TX/agent-a0005.jsonl"

# A transcript with no Compound V run at all.
{
  u "Please summarise this file for me."
  a msg_7 111 222 333 444
} > "$TX/agent-a0006.jsonl"

# UNMATCHED: another CHECKOUT whose run dir has the SAME basename. Only the
# absolute path differs, which is exactly what a basename match cannot see.
OTHER_REPO="$T/other-repo/docs/superpowers/execution/2026-09-04-usage-cli-test"
mkdir -p "$OTHER_REPO"
{
  u "$EMIT gate-receipt --run-dir '$OTHER_REPO' --job-id 'job-one'"
  a msg_8 888888 888888 888888 888888
} > "$TX/agent-a0007.jsonl"

# RUN-LEVEL, NOT job-two: this run's dir and a sentence naming a job, but no
# --job-id. A sentence is not a stage argument.
{
  u "Please review Compound V job \`job-two\` for me.
$EMIT finalize-wave --run-dir '$RUN'"
  a msg_9 6 7 8 9
} > "$TX/agent-a0008.jsonl"

# UNREADABLE: not UTF-8, not a transcript. Reported, and never fatal.
"$PY" -c 'import sys; open(sys.argv[1],"wb").write(b"\xff\xfe not a transcript\n")' \
  "$TX/agent-a0009.jsonl"

# UNMATCHED: names the REJECTED absolute job id, which is not a job of this run.
{
  u "$EMIT record --run-dir '$RUN' --job-id '$VICTIM'"
  a msg_10 666666 666666 666666 666666
} > "$TX/agent-a0010.jsonl"

# UNMATCHED (round-2, still-open): the PROSE names THIS run; the authoritative
# command names another. Scanning the whole prompt credited this to job-one.
{
  u "Context: the run under discussion is --run-dir '$RUN'.
$EMIT record --run-dir '$OTHER' --job-id 'job-one' --repo-root '/repo'"
  a msg_11 444444 444444 444444 444444
} > "$TX/agent-a0011.jsonl"

# UNMATCHED: a --run-dir and --job-id with NO stage command at all.
{
  u "Have a look at --run-dir '$RUN' --job-id 'job-one' when you get a chance."
  a msg_12 333333 333333 333333 333333
} > "$TX/agent-a0012.jsonl"

# job-three, THE ORDERING CASE (round-2, NEW 2). The lexically LATER file holds
# the OLDER snapshot of msg_13; filename order picks 999, the timestamp picks 42.
{
  u "$EMIT record --run-dir '$RUN' --job-id 'job-three'"
  a msg_13 5 42 6 7 2026-09-04T12:00:09.000Z
} > "$TX/agent-a0013.jsonl"
{
  u "$EMIT gate-receipt --run-dir '$RUN' --job-id 'job-three'"
  a msg_13 5 999 6 7 2026-09-04T12:00:01.000Z
} > "$TX/agent-a0014.jsonl"

# job-two gets a second transcript carrying two ID-LESS usage records (NEW 3)
# and one line too deeply nested for the JSON parser (NEW 4). Both are malformed;
# job-two's totals below must not move by a single token.
{
  u "$EMIT gate-receipt --run-dir '$RUN' --job-id 'job-two'"
  a_noid 90 100
  a_noid 90 900
} > "$TX/agent-a0015.jsonl"
"$PY" -c '
import sys
with open(sys.argv[1], "a", encoding="utf-8") as fh:
    fh.write("[" * 1200 + "]" * 1200 + "\n")' "$TX/agent-a0015.jsonl"

# UNREADABLE: the too-deeply-nested line is the FIRST line, so it is the
# CLASSIFIER that must survive it, not just the summer (NEW 4 hits both sites).
"$PY" -c '
import sys
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    fh.write("[" * 1200 + "]" * 1200 + "\n")' "$TX/agent-a0016.jsonl"

# UNMATCHED (round-3, 12): TWO invocations on ONE line - a wave-level command
# followed by a job command. Reading only the first, with its argument parse
# running to end-of-line, attributed the whole line to job-one.
{
  u "$EMIT finalize-wave --run-dir '$RUN' --jobs 'job-one'; $EMIT record --run-dir '$RUN' --job-id 'job-one'"
  a msg_17 222222 222222 222222 222222
} > "$TX/agent-a0017.jsonl"

# For section 8: a transcript that MATCHES the symlinked-results run, so its
# --write genuinely tries to write. Without it the victim file would survive
# because nothing was measured, which proves nothing about containment. For THIS
# run it is one more unmatched transcript.
SYMRUN="$T/docs/superpowers/execution/2026-09-04-symlinked-results"
{
  u "$EMIT record --run-dir '$SYMRUN' --job-id 'job-one'"
  a msg_19 31 32 33 34
} > "$TX/agent-a0019.jsonl"

# UNMATCHED (round-3, 13): a NUL inside the command's --run-dir. Written through
# Python so the byte is a real \u0000 in the JSON string, as a hostile
# transcript would carry it.
"$PY" -c '
import json, sys
run = sys.argv[2]
cmd = ("%s record --run-dir \u0027%s\u0027 --job-id \u0027job-one\u0027 "
       "--repo-root \u0027/repo\u0027" % (sys.argv[3], run[:-1] + chr(0) + run[-1:]))
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    fh.write(json.dumps({"type": "user", "isSidechain": True,
                         "message": {"role": "user", "content": cmd}}) + "\n")
    fh.write(json.dumps({"type": "assistant",
                         "timestamp": "2026-09-05T00:00:00.000Z",
                         "message": {"id": "msg_18", "model": "claude-opus-5",
                                     "usage": {"input_tokens": 111,
                                               "output_tokens": 111,
                                               "cache_read_input_tokens": 111,
                                               "cache_creation_input_tokens": 111}}}) + "\n")
' "$TX/agent-a0018.jsonl" "$RUN" "$EMIT"

# ---------------------------------------------------------------------------
# 1. The EXACT documented dry-run CLI.
# ---------------------------------------------------------------------------
DRY="$T/dry.txt"
"$PY" "$EXTRACT" --backend claude --workflow-transcript "$T/projects" \
  --run-dir "$RUN" > "$DRY" 2>"$T/dry.err"
rc=$?
check "$([ "$rc" = "0" ] && echo 0 || echo 1)" "dry run exits 0 (rc=$rc): $(head -1 "$T/dry.err")"
echo "--- dry run output ---"; cat "$DRY"; echo "----------------------"

# msg_1 counted once at its LAST snapshot (400), msg_2 once at ITS last
# snapshot — which lives in the OTHER transcript (90, not 60+90), + msg_3.
# It also carries the UTF-8 case: a decoder that raises loses this whole line.
grep -qx 'job-one input=16 output=492 cache_read=3003 cache_create=504 transcripts=2' "$DRY"
check $? "job-one line: dedup within AND across its two transcripts, invalid UTF-8 survived"
# job-two's SECOND transcript carries two id-less usage records and a line 1200
# arrays deep. All are malformed; not one token of them may reach this line.
grep -qx 'job-two input=7 output=8 cache_read=9 cache_create=10 transcripts=2' "$DRY"
check $? "job-two line: prose-only, id-less and unparseable records all contributed nothing"
# job-three: the lexically LATER file (a0014) holds the OLDER snapshot (999).
# Ordering by the record's timestamp picks 42; ordering by filename picks 999.
grep -qx 'job-three input=5 output=42 cache_read=6 cache_create=7 transcripts=2' "$DRY"
check $? "job-three line: the snapshot winner is the newest by timestamp, not the last filename"
grep -qx 'unmeasured: (none)' "$DRY"
check $? "unmeasured line present"
grep -qx 'unmatched: 11' "$DRY"
check $? "other run/checkout, unreadable x2, rejected id, prose run dir, no-command, two-per-line, NUL: unmatched"
grep -qx 'run_level: input=8 output=10 cache_read=12 cache_create=14 transcripts=2' "$DRY"
check $? "wave-level and prose-only stages are run-level, not folded into a job"
grep -qx 'malformed_lines: 5' "$DRY"
check $? "malformed, invalid-UTF-8, id-less and too-deeply-nested records are all counted, not fatal"
grep -qx 'unreadable_transcripts: 2' "$DRY"
check $? "non-UTF-8 and unparseable-first-line files are both reported, not fatal"
grep -q '^rejected_jobs (unsafe id, never written): ' "$DRY"
check $? "the two unsafe manifest job ids are named, not silently dropped"
if grep -qE '^(/|\.\.)' "$DRY"; then
  fail "an unsafe job id became a reported job line"
else
  pass "no unsafe job id became a job line"
fi
for leak in 999999 888888 666666 444444 333333 222222 111111; do
  if grep -q "$leak" "$DRY"; then
    fail "tokens from an unmatched transcript leaked into this run ($leak)"
  else
    pass "unmatched transcript's tokens did NOT leak into this run ($leak)"
  fi
done

# The dry run must not touch the results.
if grep -q '"usage"' "$RUN/results/job-one.json"; then
  fail "dry run wrote to results/ without --write"
else
  pass "dry run leaves results/ untouched"
fi

# ---------------------------------------------------------------------------
# 2. --write, then a second --write: idempotent to the byte.
# ---------------------------------------------------------------------------
"$PY" "$EXTRACT" --backend claude --workflow-transcript "$T/projects" \
  --run-dir "$RUN" --write > "$T/write1.txt" 2>&1
check $? "--write exits 0"
cp "$RUN/results/job-one.json" "$T/after-first.json"
"$PY" "$EXTRACT" --backend claude --workflow-transcript "$T/projects" \
  --run-dir "$RUN" --write > "$T/write2.txt" 2>&1
check $? "second --write exits 0"
cmp -s "$T/after-first.json" "$RUN/results/job-one.json"
check $? "second --write is byte-identical (no double counting)"

# NEW 1: a symlink pre-placed at the OLD predictable temp name. mkstemp never
# uses that name, so whatever it points at must survive untouched.
printf '{"bait": "untouched"}\n' > "$T/bait.json"
ln -s "$T/bait.json" "$RUN/results/job-one.json.cv-usage-tmp"
"$PY" "$EXTRACT" --backend claude --workflow-transcript "$T/projects" \
  --run-dir "$RUN" --write >/dev/null 2>&1
if [ "$(cat "$T/bait.json")" = '{"bait": "untouched"}' ]; then
  pass "--write did not follow a symlink at the predictable temp path"
else
  fail "--write followed <result>.cv-usage-tmp and clobbered $T/bait.json"
fi
if [ -L "$RUN/results/job-one.json.cv-usage-tmp" ]; then
  pass "the bait symlink was left alone, not consumed as the temp file"
else
  fail "--write consumed the pre-placed temp-path symlink"
fi
rm -f "$RUN/results/job-one.json.cv-usage-tmp"
if [ -z "$(find "$RUN/results" -maxdepth 1 -name '.cv-usage-*' -print -quit)" ]; then
  pass "--write left no stray temp file in results/"
else
  fail "--write left a stray temp file in results/"
fi

# The outcome that matters for the hostile job ids: nothing outside the run dir.
for sentinel in "$VICTIM.json" "$ESCAPE"; do
  if [ "$(cat "$sentinel")" = '{"sentinel": "untouched"}' ]; then
    pass "--write left $(basename "$sentinel") outside the run untouched"
  else
    fail "--write OVERWROTE $sentinel outside the run directory"
  fi
done
# The containment gate independently of the name gate: a results entry that is
# a symlink out of the run must be refused too.
echo '{}' > "$T/outside.json"
ln -s "$T/outside.json" "$RUN/results/job-symlink.json"
"$PY" "$EXTRACT" --backend claude --workflow-transcript "$T/projects" \
  --run-dir "$RUN" --write >/dev/null 2>&1
if grep -q 'usage' "$T/outside.json"; then
  fail "--write followed a symlinked results entry out of the run directory"
else
  pass "--write refused a symlinked results entry"
fi
rm -f "$RUN/results/job-symlink.json"
# ...and a RESULT file that is itself a symlink is refused outright.
printf '{"linked": "untouched"}\n' > "$T/linked-result.json"
cp "$RUN/results/job-two.json" "$T/job-two.backup.json"
rm -f "$RUN/results/job-two.json"
ln -s "$T/linked-result.json" "$RUN/results/job-two.json"
"$PY" "$EXTRACT" --backend claude --workflow-transcript "$T/projects" \
  --run-dir "$RUN" --write >/dev/null 2>&1
if [ "$(cat "$T/linked-result.json")" = '{"linked": "untouched"}' ]; then
  pass "--write refused a result file that is itself a symlink"
else
  fail "--write followed a symlinked result file to $T/linked-result.json"
fi
rm -f "$RUN/results/job-two.json"
cp "$T/job-two.backup.json" "$RUN/results/job-two.json"

# ---------------------------------------------------------------------------
# 3. The written document conforms to the SHIPPED schema, with real jsonschema.
# ---------------------------------------------------------------------------
"$PY" - "$SCHEMA" "$RUN/results" <<'PY'
import json, os, sys
import jsonschema

schema = json.load(open(sys.argv[1], encoding="utf-8"))
validator = jsonschema.Draft7Validator(schema)
rc = 0

def check(ok, label):
    global rc
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        rc = 1

for job, want_in, want_out in (("job-one", 16, 492), ("job-two", 7, 8)):
    doc = json.load(open(os.path.join(sys.argv[2], job + ".json"), encoding="utf-8"))
    errs = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    check(not errs, "%s: written job_result conforms to job_result.schema.json" % job)
    for e in errs:
        print("     /%s: %s" % ("/".join(str(p) for p in e.path),
                                e.message.splitlines()[0][:160]))
    u = doc.get("usage") or {}
    check(u.get("measured") is True, "%s: usage.measured is true" % job)
    check(u.get("input_tokens") == want_in, "%s: usage.input_tokens == %d" % (job, want_in))
    check(u.get("output_tokens") == want_out, "%s: usage.output_tokens == %d" % (job, want_out))
    check(u.get("source") == "workflow-transcript", "%s: usage.source names the record" % job)
    check(isinstance(u.get("transcripts"), list) and u["transcripts"],
          "%s: usage.transcripts names the evidence" % job)
    check(doc.get("status") == "success", "%s: the merge preserved the rest of the result" % job)

# The schema must actually forbid an undeclared key — otherwise "it conforms"
# proves nothing about the four fields this release added.
doc = json.load(open(os.path.join(sys.argv[2], "job-one.json"), encoding="utf-8"))
doc["usage"]["invented_metric"] = 1
check(bool(list(validator.iter_errors(doc))),
      "usage is additionalProperties:false, so an invented metric is rejected")
sys.exit(rc)
PY
check $? "schema validation block"

# ---------------------------------------------------------------------------
# 4. The aggregator reads the new source with UNCHANGED totals semantics.
# ---------------------------------------------------------------------------
AGG="$("$PY" "$AGGREGATE" --run-dir "$RUN" --format text)"
echo "aggregate: $AGG"
WANT="measured: in=28 out=542 cache_read=3018 cache_create=521 | 3 measured, 0 unmeasured"
if [ "$AGG" = "$WANT" ]; then rc=0; else rc=1; fi
check "$rc" "aggregate totals the transcript-measured jobs (28 = 16+7+5, 542 = 492+8+42)"

# ---------------------------------------------------------------------------
# 5. Exit 2 on a missing transcript dir / run dir; the run is not touched.
# ---------------------------------------------------------------------------
"$PY" "$EXTRACT" --backend claude --workflow-transcript "$T/no-such-dir" \
  --run-dir "$RUN" >/dev/null 2>&1
rc=$?
if [ "$rc" = "2" ]; then rc=0; else rc=1; fi
check "$rc" "missing transcript dir exits 2"
"$PY" "$EXTRACT" --backend claude --workflow-transcript "$T/projects" \
  --run-dir "$T/no-such-run" >/dev/null 2>&1
rc=$?
if [ "$rc" = "2" ]; then rc=0; else rc=1; fi
check "$rc" "missing run dir exits 2"

# ---------------------------------------------------------------------------
# 6. A run whose jobs have NO transcript stays honestly unmeasured.
# ---------------------------------------------------------------------------
EMPTY="$T/docs/superpowers/execution/2026-09-04-no-transcripts"
mkdir -p "$EMPTY/results"
printf 'run_id: 2026-09-04-no-transcripts\njobs:\n- id: lonely\n' > "$EMPTY/manifest.yaml"
cp "$T/after-first.json" "$EMPTY/results/lonely.json"
"$PY" - "$EMPTY/results/lonely.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
doc.pop("usage", None)
open(sys.argv[1], "w", encoding="utf-8").write(
    json.dumps(doc, indent=2, sort_keys=True) + "\n")
PY
"$PY" "$EXTRACT" --backend claude --workflow-transcript "$T/projects" \
  --run-dir "$EMPTY" --write > "$T/empty.txt" 2>&1
check $? "a run with no matching transcript still exits 0"
# The dash is whatever the tool's own stdout can encode; ask for it the same
# way rather than hard-coding a character an ASCII stream cannot write.
DASH="$("$PY" -c '
import sys
enc = getattr(sys.stdout, "encoding", None) or "utf-8"
try:
    u"\u2014".encode(enc)
    sys.stdout.write(u"\u2014")
except (LookupError, UnicodeEncodeError):
    sys.stdout.write("-")')"
grep -qx "lonely input=$DASH output=$DASH cache_read=$DASH cache_create=$DASH transcripts=0" "$T/empty.txt"
check $? "an unmeasured job prints a dash for every metric, never a fabricated 0"
if grep -q 'lonely input=0' "$T/empty.txt"; then
  fail "an unmeasured job printed a fabricated 0"
else
  pass "an unmeasured job printed no fabricated 0"
fi

# ---------------------------------------------------------------------------
# 7. An ASCII stdout must not take the render down (PYTHONIOENCODING=ascii is
#    the reproducible stand-in for a C locale on a Python without UTF-8 mode).
# ---------------------------------------------------------------------------
PYTHONIOENCODING=ascii "$PY" "$EXTRACT" --backend claude \
  --workflow-transcript "$T/projects" --run-dir "$EMPTY" >/dev/null 2>"$T/ascii.err"
check $? "extract renders an unmeasured job on an ASCII stdout: $(head -1 "$T/ascii.err")"
PYTHONIOENCODING=ascii "$PY" "$AGGREGATE" --run-dir "$EMPTY" --format text \
  >/dev/null 2>"$T/ascii2.err"
check $? "aggregate renders null totals on an ASCII stdout: $(head -1 "$T/ascii2.err")"
grep -qx 'unmeasured: lonely' "$T/empty.txt"
check $? "the unmeasured job is named"
if grep -q '"usage"' "$EMPTY/results/lonely.json"; then
  fail "--write stamped a usage object onto a job it never measured"
else
  pass "--write leaves an unmeasured job's result untouched"
fi

# ---------------------------------------------------------------------------
# 8. results/ is anchored on the RUN, not on whatever results/ points at
#    (round-3, 14). A symlinked results directory used to become its own
#    trusted root, so every path under it passed the containment check.
# ---------------------------------------------------------------------------
mkdir -p "$SYMRUN"
printf 'run_id: 2026-09-04-symlinked-results\njobs:\n- id: job-one\n' \
  > "$SYMRUN/manifest.yaml"
mkdir -p "$T/victim-results"
printf '{"victim": "untouched"}\n' > "$T/victim-results/job-one.json"
ln -s "$T/victim-results" "$SYMRUN/results"
"$PY" "$EXTRACT" --backend claude --workflow-transcript "$T/projects" \
  --run-dir "$SYMRUN" --write > "$T/symrun.txt" 2>&1
check $? "a run whose results/ is a symlink still exits 0"
grep -q '^results_refused: ' "$T/symrun.txt"
check $? "the refused results root is reported, not silently read as empty"
if [ "$(cat "$T/victim-results/job-one.json")" = '{"victim": "untouched"}' ]; then
  pass "--write did not reach through a symlinked results/ to a file outside the run"
else
  fail "--write followed a symlinked results/ and replaced $T/victim-results/job-one.json"
fi
if grep -q 'job-one input=16' "$T/symrun.txt"; then
  fail "a job was read through a symlinked results/ directory"
else
  pass "no job was read through a symlinked results/ directory"
fi

echo
if [ "$fails" = "0" ]; then
  echo "✅ tests/test-usage-workflow.sh: all checks pass"
  exit 0
fi
echo "❌ tests/test-usage-workflow.sh: $fails check(s) failed"
exit 1
