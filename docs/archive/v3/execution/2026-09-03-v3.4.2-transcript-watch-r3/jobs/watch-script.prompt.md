# Task A'' — `>=` is not a redirect, a heredoc body is not command text, `error` anchors on the tool's own verdict (review-2 issues 1–2)

Compound V run `2026-09-03-v3.4.2-transcript-watch-r3`, job `watch-script`.

Review pass 2 (docs/superpowers/dogfood/2026-09-03-v3.4.2-transcript-watch-review-2.md) found ISSUES (3); issues 1 and 2 are yours (the script and its test) — read them in full, their reproductions are exact. TEST FIRST: the three fixture classes before the code. Do not weaken the redirect detector to make a fixture pass — require a real target (non-empty, not `=`) and parse only the command line, never a heredoc body. Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-transcript-watch.py`
- `tests/test-transcript-watch.sh`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- bash tests/test-transcript-watch.sh is green and carries fixtures for: a Bash command containing `>=` (no out-of-lane), a heredoc whose BODY contains `>` / `>=` / a path (only the heredoc's own target is considered, and only when it is a repository path), and a `sed`/`cat`/`grep`/`head` result that pastes a traceback (no error signal); /usr/bin/python3 -B scripts/compound-v-transcript-watch.py --selftest is green.
- bash_write_targets('true >= 1') == [] and bash_write_targets("cat > /tmp/x.py <<PYEOF\nassert s.count(old) >= 1\nPYEOF") == ['/tmp/x.py'] on the merged tree (quote the REPL output); `error` fires only on a tool_result the harness marked is_error or that carries a non-zero exit marker, or — if the text heuristic stays — never on the result of a read-only command.
- Run --once against run 2026-09-03-v3.4.2-transcript-watch-r2's own transcripts on the merged tree: zero out-of-lane, zero wrong-cwd, and the per-agent roster names every agent with its job.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
