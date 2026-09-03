#!/bin/bash
# test-dogfood-index.sh — exercises scripts/compound-v-dogfood-index.sh against a fixture
# corpus, run explicitly under /bin/bash (bash 3.2 on macOS).
set -eu

repo_root=$(cd "$(dirname "$0")/.." && pwd)
script="$repo_root/scripts/compound-v-dogfood-index.sh"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

fixture="$tmp/dogfood"
mkdir -p "$fixture"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

assert_contains() {
  # $1 = haystack file, $2 = needle
  grep -qF -- "$2" "$1" || fail "expected to find '$2' in $1"
}

# --- fixture corpus -----------------------------------------------------
# One feature/pass 1 with an H2-prefixed verdict heading.
cat >"$fixture/2026-09-01-alpha-review.md" <<'EOF'
# Review

## VERDICT: APPROVED

Looks good.
EOF

# Same feature, pass 2, bold-asterisk ISSUES verdict.
cat >"$fixture/2026-09-01-alpha-review-2.md" <<'EOF'
# Review

VERDICT: **ISSUES**

Needs work.
EOF

# Different date/feature, no verdict line at all -> unknown.
cat >"$fixture/2026-09-02-beta-review.md" <<'EOF'
# Review

No verdict line here.
EOF

# Two-digit pass number for the beta feature.
cat >"$fixture/2026-09-02-beta-review-10.md" <<'EOF'
# Review

## VERDICT: APPROVED

Tenth pass, all clear.
EOF

# Decoy: contains "review" only inside "reviewer" -impl.md; must not be picked up.
cat >"$fixture/2026-09-02-beta-reviewer-x-impl.md" <<'EOF'
# Not a review row

VERDICT: APPROVED
EOF

# Non-review file entirely (no -review(-N).md suffix).
cat >"$fixture/2026-09-02-beta-notes.md" <<'EOF'
Just some notes.
EOF

# Verdict line where the matched token is ISSUES but the rest of the line
# also contains the word "approved" elsewhere -- the verdict must come from
# the anchored token the regex actually matched (ISSUES), not from any
# other occurrence of either word on the line.
cat >"$fixture/2026-09-03-gamma-review.md" <<'EOF'
# Review

VERDICT: ISSUES — the earlier pass was approved

Still needs work.
EOF

# Bold-heading verdict with a trailing annotation.
cat >"$fixture/2026-09-03-delta-review.md" <<'EOF'
# Review

## VERDICT: **ISSUES** (4)

Four issues found.
EOF

# The only verdict-shaped text in the file is mid-sentence, not anchored at
# the start of a line (after an optional heading marker) -> unknown.
cat >"$fixture/2026-09-03-epsilon-review.md" <<'EOF'
# Review

We noted that the verdict: approved wording showed up mid-sentence here.
EOF

# Lowercase verdict line.
cat >"$fixture/2026-09-03-zeta-review.md" <<'EOF'
# Review

verdict: approved

Looks fine.
EOF

# --- run ------------------------------------------------------------------
out="$tmp/README.md"
/bin/bash "$script" --dir "$fixture" --out "$out"

[ -s "$out" ] || fail "output file is empty or missing"

# Review rows expected: alpha(1,2), beta(1), beta(10), gamma(1), delta(1),
# epsilon(1), zeta(1) -> 8 rows total, plus the decoy and notes file must
# not appear as rows.
row_count=$(grep -c '^| 2026-' "$out")
[ "$row_count" -eq 8 ] || fail "expected 8 rows, got $row_count"

grep -q -- "-reviewer-x-impl.md" "$out" && fail "decoy -impl.md file leaked into the index"
grep -q -- "beta-notes.md" "$out" && fail "non-review file leaked into the index"

# --- order: date then pass --------------------------------------------
rows=$(grep '^| 2026-' "$out")
expected_order="2026-09-01-alpha-review.md
2026-09-01-alpha-review-2.md
2026-09-02-beta-review.md
2026-09-02-beta-review-10.md
2026-09-03-delta-review.md
2026-09-03-epsilon-review.md
2026-09-03-gamma-review.md
2026-09-03-zeta-review.md"
actual_order=$(printf '%s\n' "$rows" | awk -F'|' '{gsub(/^ +| +$/, "", $6); print $6}')
[ "$actual_order" = "$expected_order" ] || fail "row order mismatch:
expected:
$expected_order
actual:
$actual_order"

# --- individual verdicts -------------------------------------------------
assert_contains "$out" "| 2026-09-01 | alpha | 1 | APPROVED | 2026-09-01-alpha-review.md |"
assert_contains "$out" "| 2026-09-01 | alpha | 2 | ISSUES | 2026-09-01-alpha-review-2.md |"
assert_contains "$out" "| 2026-09-02 | beta | 1 | unknown | 2026-09-02-beta-review.md |"
assert_contains "$out" "| 2026-09-02 | beta | 10 | APPROVED | 2026-09-02-beta-review-10.md |"
# Anchored token wins over an unrelated occurrence of the other word later
# on the same line.
assert_contains "$out" "| 2026-09-03 | gamma | 1 | ISSUES | 2026-09-03-gamma-review.md |"
# Bold heading with a trailing annotation after the matched token.
assert_contains "$out" "| 2026-09-03 | delta | 1 | ISSUES | 2026-09-03-delta-review.md |"
# Verdict-shaped text that only appears mid-sentence (not anchored at the
# start of a line) does not count as a verdict.
assert_contains "$out" "| 2026-09-03 | epsilon | 1 | unknown | 2026-09-03-epsilon-review.md |"
# Lowercase verdict line.
assert_contains "$out" "| 2026-09-03 | zeta | 1 | APPROVED | 2026-09-03-zeta-review.md |"

# --- footer counts ---------------------------------------------------------
assert_contains "$out" "Reviews: 8 · APPROVED: 3 · ISSUES: 3 · other: 2"

# --- idempotence: byte-identical on a second run --------------------------
out2="$tmp/README2.md"
/bin/bash "$script" --dir "$fixture" --out "$out2"
cmp -s "$out" "$out2" || fail "second run is not byte-identical to the first"

# Re-running to the SAME output path is also idempotent.
cp "$out" "$tmp/README.snapshot.md"
/bin/bash "$script" --dir "$fixture" --out "$out"
cmp -s "$tmp/README.snapshot.md" "$out" || fail "re-running onto the same output path changed it"

# --- missing directory: non-zero exit with a message -----------------------
missing_dir="$tmp/does-not-exist"
set +e
error_output=$(/bin/bash "$script" --dir "$missing_dir" --out "$tmp/never.md" 2>&1)
status=$?
set -e
[ "$status" -ne 0 ] || fail "expected non-zero exit on missing directory"
[ -n "$error_output" ] || fail "expected an error message on missing directory"

echo "test-dogfood-index: all assertions passed"
