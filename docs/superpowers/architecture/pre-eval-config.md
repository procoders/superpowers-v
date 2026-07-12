# Pre-Eval config contract + digest / commit / intent conventions (v2.9 Task 0)

The single reference for the `pre_eval.*` config surface and the cross-cutting conventions
(digest functions, the lifecycle commit primitive, the write-once intent record) that every
downstream v2.9 wave (A–H) implements against. Task 0 owns these so independent workers cannot
diverge (CR5-6/CR5-7/CR5-9/CR5-10). The shared loader is
[`scripts/compound-v-project-config.py`](../../../scripts/compound-v-project-config.py); the shared
digest/matcher primitives are [`scripts/compound-v-taxonomy.py`](../../../scripts/compound-v-taxonomy.py).

---

## 1. `pre_eval.*` config keys (`.claude/compound-v.json`)

`/v:init` seeds these (Step 4a); they live in the project config alongside `models`. All defaults
are **fail-closed** — the SAFE, never-auto-route value. Read them ONLY through
`compound-v-project-config.load_project_config(repo)` + `resolve_pre_eval(cfg)`.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `pre_eval.enabled` | bool | `true` | Whether the pre-eval stage runs at all. Even enabled it can only ever *save* work on the proven-trivial path; a missed/disabled pre-eval degrades to the normal pipeline (AC-6, description-driven + unenforceable). |
| `pre_eval.fast_path` | `ask` \| `off` | `ask` | `ask` OFFERS a proportionate fast-path when eligible (folded into the ONE recon/clarify interaction — never a standalone screen, AC-9/DC-1). `off` is a **hard kill-switch** — no offer, ever. |
| `pre_eval.min_sample_count` | int ≥ 0 | `5` | Tier-2 stays escalation-only until at least this many *calibrated, fast-path-taken* outcomes accrue (Iron-Invariant #3 counterfactual guard). At launch (no data) Tier-2 is escalation-only by construction. |
| `pre_eval.fan_out_threshold` | int ≥ 0 | `1` | Layer-B gate: fast-path requires `fan_out ≤ threshold` **and** exactly one literal normalized path. Default `1` (single-site). |
| `pre_eval.token_cap` | int ≥ 0 | `20000` | Whole-stage token budget. Overrun → abort pre-eval → `FULL_PIPELINE` (fail-safe; the same pipeline that would have run anyway). |
| `pre_eval.remember` | object | `{}` | Explicit, revocable per-taxonomy-category opt-in (AC-11): `{ "css-only": "fastpath", … }`. Only the literal value `"fastpath"` is honored; anything else is dropped. |

**Malformed handling (two layers, both fail-closed):**
- **Structural** malformation (config not valid JSON, root not an object, `models`/`pre_eval` not
  objects) → `load_project_config` **raises** so the caller **warns once** and falls back to
  all-defaults. A malformed config is NEVER silently treated as an auto-route (Iron-Invariant #5/#4).
- **Per-key** invalid values (`fast_path: "banana"`, `min_sample_count: "x"`, a negative
  `token_cap`, a `remember` value ≠ `"fastpath"`) are coerced back to the declared default by
  `resolve_pre_eval`, which returns a `warnings` list for the caller to surface once. Never raises,
  never routes.

### `remember` — revocation (AC-11)

`pre_eval.remember` is an explicit one-time human opt-in per taxonomy category (the Linear
per-property precedent), NOT a silent auto-route. It **only** suppresses the OFFER for that
category; every fail-closed override — sensitive path, shared-token, a11y, churn-hot,
tier-disagreement, and the **post-hoc diff escalation** — still fires on every request regardless of
a remembered choice (AC-11 fixture). Revoke by re-running `/v:init` or editing the config; default is
not-remembered (ask every time).

---

## 2. Digest convention (CR5-6 / CR5-7)

One canonical encoding, single-sourced in `compound-v-taxonomy.py`, consumed unchanged by C1's
fast-path binding tests and by every producer (A1/A3/M1/dispatcher). Two distinct digest kinds:

### 2a. Canonical-JSON record digest — pre-eval record, localization artifact, review receipt

```python
canonical_json(obj) = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=False, allow_nan=False)
record_digest(obj, exclude_field) = "sha256:" + sha256(canonical_json(obj_without_exclude_field)
                                                        .encode("utf-8")).hexdigest()
```

- **Recursively key-sorted** (`sort_keys=True` sorts nested objects too), **compact** separators
  (no spaces), **UTF-8-preserving** (`ensure_ascii=False`), **NaN-forbidden** (`allow_nan=False`)
  so the encoding is byte-deterministic across machines.
- **Excluded self-digest field:** a record carries its own digest without a chicken-and-egg by
  digesting itself *minus* that field. The excluded field name per record type:
  - pre-eval record → `digest` (`docs/superpowers/pre-eval/<pre_eval_id>.json`)
  - localization artifact → `digest` (`docs/superpowers/pre-eval/<pre_eval_id>.localization.json`);
    THIS digest is the **localization content-digest** bound across manifest+record+artifact (AC-13).
  - review receipt → `digest`
- Verify with `compound-v-taxonomy.record_digest(record, exclude_field="digest")`.

### 2b. Taxonomy snapshot content-address — `taxonomy_digest`

```python
taxonomy_digest_bytes(raw_bytes) = "sha256:" + sha256(raw_bytes).hexdigest()   # RAW file bytes
```

A **content address of the immutable snapshot file bytes** — NOT a re-serialization of the parsed
taxonomy (a parse→re-emit round-trip is not byte-stable and would defeat pinning; CR2-6/CR4-2). The
snapshot is copied byte-for-byte from the pre-run `pre-eval/<pre_eval_id>.taxonomy-snapshot.yaml`
into the run, preserving `taxonomy_ref`/`taxonomy_digest`. `taxonomy_digest` MUST be equal across the
pre-eval record, the localization artifact's context, and the fast-path manifest (AC-13). Absent /
malformed / unreadable taxonomy or snapshot ⇒ **unconditional `FULL_PIPELINE`** (spec §2 round-3
fix): without the sensitive-path + content-pattern protections there is no way to *prove* a change is
safe.

### Cross-artifact binding fields (AC-13, validator-enforced by C1)

Equal across the fast-path **manifest**, the pinned **pre-eval record**, and the **localization
artifact**: `pre_eval_id`, the `FASTPATH_ELIGIBLE` decision, `taxonomy_digest`, and the localization
content-digest. Plus: the manifest's sole `write_allowed` literal == `localization.resolved_paths[0]`.
A mismatch on any field fails validation (tampering fixtures required) — otherwise a manifest could
cite a safe CSS localization while authorizing a different file the scope gate would then enforce.

---

## 3. Canonical receipt path + binding (CR5-6 / CR5-9)

The fast-path combined SPEC+QUALITY review writes a receipt conforming to
[`schemas/fastpath-review-receipt.schema.json`](../../../schemas/fastpath-review-receipt.schema.json)
at the canonical run-relative path:

```
docs/superpowers/execution/<run-id>/review/receipt.json
```

- The receipt is **bound** to `run_id`, `pre_eval_id`, the `manifest_digest`, the immutable
  **pre-launch `baseline_sha`** (never HEAD; CR5-3), and the **`final_diff_digest`** of the reviewed
  diff — so a stale receipt from an earlier attempt cannot be replayed against a changed diff.
- Written **atomically** (temp file in the same dir → `os.replace`). **Invalidated before any
  re-review** (a new attempt bumps `attempt_id` and recomputes `final_diff_digest`); a
  post-review validation that finds the receipt's `final_diff_digest` ≠ the current diff digest
  fails closed.
- **Two validation modes** (Lifecycle protocol / CR4-1): `--mode pre-dispatch` **forbids** a receipt
  (it can't exist yet) and validates the review DECLARATION; `--mode post-review` **requires +
  verifies** it before `REVIEWED`/`MERGED`. Reviewer-opus is proven by resolving the declaration
  through the real resolver/config and requiring the concrete result == **Claude Opus**, with
  `backend: claude` required even when `model: opus` is pinned (CR5-5).

---

## 4. Lifecycle commit primitive (CR5-9)

Every lifecycle artifact is **written AND committed** (v2.6.4 discipline — an uncommitted artifact
vanishes on `git worktree remove` and never indexes into V-memory). The commit primitive is a
**path-limited / temporary-index commit** that:

- commits **ONLY the exact lifecycle path set** it is given (e.g. just
  `docs/superpowers/pre-eval/<pre_eval_id>.json`), never `git add -A`;
- uses two separate commands, **no `&&`**, each exit code checked (v2.6.4);
- **fails closed on overlapping user-staged changes** — if any path in the requested set is already
  staged with *different* content, or the user has unrelated staged changes that a naive commit would
  sweep in, the primitive aborts rather than committing a mixed tree. Implementation: stage the exact
  paths into a **temporary index** (`GIT_INDEX_FILE`) built from `HEAD`, so the user's real index is
  untouched and only the named paths are committed.
- **Fixture (binding on downstream owners):** an unrelated pre-staged file stays untouched across
  every lifecycle commit.

Owners of the actual commit calls: A3 (Phase P), M1 (Phase M), the dispatcher / `/v:collect` (Phase
Dispatch terminal). Task 0 fixes the CONVENTION; the callers implement it consistently.

---

## 5. Write-once intent record (CR5-10)

A tiny **intent record** is persisted **BEFORE localization**, mapping a stable request fingerprint →
`pre_eval_id`, so a fresh-process resume that has only the request text can find partial state and
not orphan artifacts:

```
docs/superpowers/pre-eval/<pre_eval_id>.intent.json
```

Shape:

```json
{
  "pre_eval_id": "2026-07-12T101500Z-make-button-red-a1b2",
  "request_fingerprint": "sha256:…",   // sha256 over the normalized request text
  "request_slug": "make-button-red",
  "ts": "2026-07-12T10:15:00Z"
}
```

- `request_fingerprint` = `"sha256:" + sha256(normalized_request_text)` (trim + collapse internal
  whitespace before hashing) — the **stable** key a resume recomputes from the request alone to
  discover an existing `pre_eval_id` before minting a new one (write-once; never overwritten).
- Written + committed via the §4 primitive as the FIRST Phase-P artifact, ahead of the localization
  artifact and the taxonomy snapshot. A3 owns writing it; resume (Phase P) reconciles by
  recomputing the fingerprint and matching an existing intent record.

---

## 6. Cross-references

- Config loader + fail-closed rules: `scripts/compound-v-project-config.py`
- Shared taxonomy loader/matcher + digest primitives: `scripts/compound-v-taxonomy.py`
- Record / receipt schemas: `schemas/pre-eval-record.schema.json`,
  `schemas/fastpath-review-receipt.schema.json`
- States + escalation + resume: [`skills/compound-v/state-machine.md`](../../../skills/compound-v/state-machine.md)
- Fast-path manifest schema + validation modes:
  [`skills/compound-v/execution-manifest.md`](../../../skills/compound-v/execution-manifest.md)
- Spec (Iron Invariants + §0 corrections + §2 truth-table):
  `docs/superpowers/specs/2026-07-11-v2.9-pre-evaluation-design.md`
- Plan (Lifecycle & commit-ordering protocol; CR5-1..10):
  `docs/superpowers/plans/2026-07-11-v2.9-pre-evaluation-plan.md`
