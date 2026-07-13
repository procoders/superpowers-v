# Library/CLI audit — v2.12 usage & advisor (live-probed 2026-07-13)

Every claim below was probed against the INSTALLED binary, not training data.
Versions: `codex-cli 0.144.1` · `opencode 1.17.18` · `cursor-agent 2026.06.26` · `agy 1.0.16` · `claude 2.1.207`.

## Verified usage event/field reference (for compound-v-usage-extract.py)

| Backend | Structured flag | Event / object | Token fields | measured |
|---|---|---|---|---|
| codex | `--json` | `turn.completed.usage` (SUM across ALL turn.completed; filter out `error`/deprecation items) | `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_output_tokens` | true |
| opencode | `--format json` | `step_finish.part.tokens` (+ `part.cost`) | `input`, `output`, `reasoning`, `cache.read`, `cache.write`, `total` | true |
| cursor-agent | `-p -f --output-format json` (needs `-f`/trust) | `result.usage` | `inputTokens`, `outputTokens`, `cacheReadTokens`, `cacheWriteTokens` | true |
| agy (antigravity) | none (`--print` only) | — | — | **false** |
| claude via Task subagent | n/a (in-harness, returns text only) | — | — | **false** |
| claude `-p` shell-out | `--output-format stream-json --verbose` | `result.usage` (+ `result.total_cost_usd`, `result.modelUsage`) | `input_tokens`, `output_tokens`, `cache_*`, `iterations[]` | true (but not used by Task path) |
| devin | none machine-readable | — | — | **false** |

Each backend uses DIFFERENT casing/shape — the extractor must normalize per-backend. Where no
token count exists, emit `measured:false` + null tokens (anti-ruflo — never a fabricated number).
Selftest fixtures MUST be captured from real CLI output.

## Advisor reality (hard finding)

- `claude -p --advisor <opus|fable>` — **REFUTED**: zero matches in `claude 2.1.207 --help`. The flag
  does not exist. A stub test around this argv would falsely pass on an impossible invocation.
- `advisor_20260301` API tool — **REAL** (beta `advisor-tool-2026-03-01`) but requires the `anthropic`
  SDK + `ANTHROPIC_API_KEY`. **Rejected for this plugin** (breaks pure-stdlib/no-service/subscription
  ethos). Advisor is therefore built as a harness **subagent pattern**, cross-brand, READ-ONLY.
- `advisor_calls` MUST be worker-counted (times the executor actually consulted the advisor). The CLI's
  `usage.iterations[]` is turn count, NOT advisor count — do not read advisor_calls from it.

## Argv gotchas a worker will get wrong

- codex advisor path: `codex exec --sandbox read-only --json` (read-only, cross-brand, safe).
- opus fallback: `claude -p --model opus` — NO write tools, **NEVER `--dangerously-skip-permissions`**.
- claude `-p --output-format stream-json` REQUIRES `--verbose` or it errors.
- cursor usage needs `-f`/`--trust` or it blocks on an interactive trust prompt.
