#!/bin/bash
# compound-v-dogfood-index.sh — index the dogfood review corpus into a Markdown table.
#
# Usage: compound-v-dogfood-index.sh [--dir DIR] [--out FILE]
#
#   --dir DIR   directory to scan for `<date>-<feature>-review.md` /
#               `<date>-<feature>-review-<N>.md` files (default:
#               docs/superpowers/dogfood)
#   --out FILE  where to write the generated index (default: DIR/README.md)
#
# Exits non-zero with one message on stderr if DIR does not exist.
# Bash 3.2 compatible: no associative arrays, no mapfile, no ${var,,}.
set -eu

dir="docs/superpowers/dogfood"
out=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dir)
      if [ $# -lt 2 ]; then
        echo "compound-v-dogfood-index: --dir requires an argument" >&2
        exit 1
      fi
      dir="$2"
      shift 2
      ;;
    --out)
      if [ $# -lt 2 ]; then
        echo "compound-v-dogfood-index: --out requires an argument" >&2
        exit 1
      fi
      out="$2"
      shift 2
      ;;
    *)
      echo "compound-v-dogfood-index: unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [ -z "$out" ]; then
  out="$dir/README.md"
fi

if [ ! -d "$dir" ]; then
  echo "compound-v-dogfood-index: directory not found: $dir" >&2
  exit 1
fi

# PASS is what /v:epic's final integration review emits; it reads as APPROVED.
verdict_pattern='^(#+[[:space:]]*)?\**VERDICT:?\**[[:space:]]*\**(APPROVED|ISSUES|PASS)'

outdir="${out%/*}"
if [ "$outdir" = "$out" ]; then
  outdir="."
fi

tmp_rows=$(mktemp)
tmp_out=$(mktemp "$outdir/.dogfood-index.XXXXXX")
trap 'rm -f "$tmp_rows" "$tmp_out"' EXIT

approved=0
issues=0
other=0
total=0

for f in "$dir"/*.md; do
  [ -e "$f" ] || continue
  base="${f##*/}"

  case "$base" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*) ;;
    *) continue ;;
  esac

  date="${base:0:10}"
  rest="${base:11}"

  case "$rest" in
    *-review.md)
      pass=1
      feature="${rest%-review.md}"
      ;;
    *-review-[0-9].md | *-review-[0-9][0-9].md)
      passraw="${rest##*-review-}"
      passraw="${passraw%.md}"
      pass=$((10#$passraw))
      feature="${rest%-review-*.md}"
      ;;
    *)
      continue
      ;;
  esac

  # Extract only the substring the anchored alternation actually matched
  # (not the whole line) so the verdict reflects the matched token, not
  # whichever word happens to appear anywhere else on the line. The LAST
  # anchored match wins: a review file's final verdict is its last one, and
  # a pass-2 section that quotes pass 1's verdict at column 0 must not freeze
  # the row at the quoted value (the epic's integration review did exactly
  # that on 2026-09-03).
  match=$(grep -ioE -- "$verdict_pattern" "$f" | tail -n 1 || true)
  if [ -n "$match" ]; then
    case "$match" in
      *[Aa][Pp][Pp][Rr][Oo][Vv][Ee][Dd])
        verdict="APPROVED"
        ;;
      *[Pp][Aa][Ss][Ss])
        verdict="APPROVED"
        ;;
      *[Ii][Ss][Ss][Uu][Ee][Ss])
        verdict="ISSUES"
        ;;
      *)
        verdict="unknown"
        ;;
    esac
  else
    verdict="unknown"
  fi

  case "$verdict" in
    APPROVED) approved=$((approved + 1)) ;;
    ISSUES) issues=$((issues + 1)) ;;
    *) other=$((other + 1)) ;;
  esac
  total=$((total + 1))

  passpad=$(printf '%02d' "$pass")
  printf '%s\t%s\t%s\t%s\t%s\n' "$date" "$passpad" "$feature" "$verdict" "$base" >>"$tmp_rows"
done

{
  printf '# Dogfood Review Index\n\n'
  printf '| date | feature | pass | verdict | file |\n'
  printf '|---|---|---|---|---|\n'
  if [ -s "$tmp_rows" ]; then
    LC_ALL=C sort -k1,1 -k2,2 "$tmp_rows" | while IFS="$(printf '\t')" read -r sdate spasspad sfeature sverdict sbase; do
      spass=$((10#$spasspad))
      printf '| %s | %s | %s | %s | %s |\n' "$sdate" "$sfeature" "$spass" "$sverdict" "$sbase"
    done
  fi
  printf '\nReviews: %s · APPROVED: %s · ISSUES: %s · other: %s\n' "$total" "$approved" "$issues" "$other"
} >"$tmp_out"

mv "$tmp_out" "$out"
