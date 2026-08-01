# Provider cooldown rerouting — Library & Documentation Audit

## 1. Tools Available

- Context7 MCP: ❌ unavailable in this harness; audit degraded to official-document WebSearch.
- Dependency manifests: none found (`package.json`, Python package manifests, Cargo, Go, Ruby,
  and Composer manifests were all absent).
- Runtime contract: Python 3.9 stdlib plus existing shell workers; no new dependency proposed.
- Prior KB reused: `docs/superpowers/library-audit/_knowledge-base/model-routing-and-provider-quotas.md`
  (updated 2026-08-01 and directly covers the same CLI/provider boundary).
- Trigger 0 recon: none; the pre-brainstorm gate recorded a fresh strong-KB `kb_skip`.

## 2. Libraries Mentioned (or Implied)

| Library / API | Spec context | Current / required surface | Repo pinned | Maintenance | Status |
|---|---|---|---|---|---|
| Python `datetime` | Parse and compare persisted UTC cooldown/reset times | Python 3.9 API | CI floor 3.9 | CPython stdlib | 🟢 available, with a 3.9 parsing constraint |
| Python `json` | Read untrusted worker/state numbers and objects | Python 3.9 API | CI floor 3.9 | CPython stdlib | 🟢 available, strictness must be added by caller |
| Anthropic API/SDK error contract | Distinguish rate limit, overload, connection failure | Current official error reference, checked 2026-08-01 | CLI-owned | Vendor maintained | 🟢 current |
| OpenAI API/SDK rate-limit contract | Temporary 429, `Retry-After`, SDK retries | Current official rate-limit guide, checked 2026-08-01 | CLI-owned | Vendor maintained | 🟢 current |
| z.ai API error contract | Business-code/message classification and reset windows | Current official error table, checked 2026-08-01 | Claude CLI transport | Vendor maintained | 🟢 current, reset timestamp format unspecified |

No third-party parser, retry library, queue, HTTP client, or scheduler is required. Adding
`python-dateutil` only to accept provider timestamps would introduce packaging and version surface
into a repository that currently has no Python dependency manifest; the Python 3.9 stdlib can
handle the required narrow formats with explicit normalization.

## 3. API Signatures Verified

| Symbol / contract | Confirmed via | Match? | Notes |
|---|---|---|---|
| `datetime.fromisoformat(text)` on Python 3.9 | [Python 3.9 datetime docs](https://docs.python.org/3.9/library/datetime.html) | ⚠️ constrained | 3.9 accepts formats emitted by `datetime.isoformat()`, including `+00:00`; the documented grammar does not include terminal `Z`. Normalize terminal `Z` to `+00:00` or use a narrow `%z` parser. |
| `datetime.strptime(text, format)` `%z` | [Python 3.9 datetime docs](https://docs.python.org/3.9/library/datetime.html) | ✅ | Since 3.7, colon offsets are accepted and `Z` is identical to `+00:00`; parsed values are timezone-aware. |
| `json.loads()` number handling | [Python 3.9 json docs](https://docs.python.org/3.9/library/json.html) | ⚠️ constrained | Python accepts `NaN`, `Infinity`, and `-Infinity` by default although JSON forbids them. State/delay parsing must reject them explicitly (for example with `parse_constant` and `math.isfinite`). |
| Anthropic transient errors | [Anthropic error docs](https://docs.anthropic.com/en/api/errors) | ✅ | `429` is `rate_limit_error`; `529` is `overloaded_error`; official SDKs retry connection/rate-limit/5xx failures twice by default and honour `retry-after` when present. |
| OpenAI temporary-rate-limit reset | [OpenAI rate-limit guide](https://platform.openai.com/docs/guides/rate-limits) | ✅ | `Retry-After` is a minimum wait for temporary 429 only; missing/invalid hints fall back to bounded exponential backoff with jitter. SDK retries must not be accidentally multiplied without a run budget. |
| z.ai error envelope/messages | [z.ai error table](https://docs.z.ai/api-reference/api-code) | ✅ with limitation | The current table distinguishes 1113, 1302, 1305, 1308–1321 and supplies `next_flush_time` placeholders, but does not publish the placeholder's concrete timestamp grammar. Parsing must be best-effort and fail bounded. |

## 4. Critical Findings 🔴

None. No abandoned/deprecated dependency is introduced.

## 5. High-Priority Findings 🟠

None by the Phase 1C maintenance-age definition.

## 6. Medium Findings 🟡

1. **Python 3.9 and modern `fromisoformat()` are not equivalent.** A test suite run only on the
   development machine's Python 3.14 can accept a terminal `Z` that the documented Python 3.9
   grammar does not accept. The implementation needs a single strict compatibility helper and a
   real Python 3.9 CI execution, not only grammar compilation.
2. **Default Python JSON parsing is more permissive than the state contract.** `NaN` and infinity
   survive `json.loads()` unless rejected. A simple `value > 0` check is insufficient, and `bool`
   must also be excluded because it is an `int` subclass.
3. **z.ai publishes reset semantics but not the timestamp syntax.** Tests must cover the exact
   rendered samples the worker has observed plus safe rejection/fallback for unknown formats. The
   spec correctly avoids promising that every future `next_flush_time` rendering parses.
4. **Provider SDK retries are below Compound V's observation boundary.** A single worker-level
   `rate_limited` result may already represent multiple HTTP attempts. The orchestrator must retain
   its run-level budget and describe counts as worker launches, never HTTP attempts.

## 7. Design Constraints for the Plan

- MUST remain Python 3.9 stdlib-only; do not add a timestamp/retry dependency or package manifest.
- MUST centralize timezone-aware timestamp parsing/formatting in one helper used by classifier,
  state validation, policy, status, and resume.
- MUST normalize a terminal `Z` explicitly before Python 3.9 `fromisoformat()`, or use a narrow
  documented `%z` format; MUST reject naive timestamps.
- MUST compare aware UTC datetimes and emit one canonical UTC form ending in `Z`.
- MUST inject/parameterize `now` in deterministic tests; do not make fixtures depend on wall time.
- MUST reject booleans, negative values, `NaN`, and infinities for retry/cooldown numeric fields.
- MUST use full official z.ai message templates without numeric codes as classifier fixtures, in
  addition to envelope/code fixtures.
- MUST treat unknown z.ai reset timestamp renderings as absent hints and fall back to bounded
  behavior; never guess locale/timezone.
- MUST account for hidden SDK/CLI retries through the existing run-level worker-launch budget; do
  not claim an exact HTTP-attempt count.
- MUST NOT add direct provider HTTP/header parsing or use z.ai's undocumented quota endpoint.
- MUST run the selftest sweep under actual Python 3.9 in CI and report its denominator plus a
  negative control capable of failing.

## 8. Open Questions for the Human

None. The approved spec already chooses bounded fallback for unknown reset formats and a
60-second maximum foreground wait; no product or dependency choice remains.

## 9. Knowledge Base Updates

- Appended `Updated 2026-08-01 — PR3 cooldown timestamp compatibility` to
  `docs/superpowers/library-audit/_knowledge-base/model-routing-and-provider-quotas.md`.

