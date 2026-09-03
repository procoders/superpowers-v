#!/usr/bin/env bash
# Build a minimal, committed checkout containing only tracked repository files.

set -eu

usage() {
  cat <<'EOF'
Usage: compound-v-sandbox-checkout.sh <dest> [--keep-execution] [--empty-pre-eval] [--taxonomy-from <path>]

Copy tracked files from the current Git repository into <dest>, then create one
commit there. By default, docs/superpowers/execution is omitted. --keep-execution
keeps its tracked files. --empty-pre-eval creates an empty
docs/superpowers/pre-eval directory. --taxonomy-from replaces
.claude/compound-v-impact-taxonomy.yaml with the supplied file.

Gitignored files are never carried, including lane-map.json and logs/*.jsonl,
whether or not --keep-execution is used.
EOF
}

fail() {
  status=$1
  shift
  printf '%s\n' "$*" >&2
  exit "$status"
}

[ "$#" -gt 0 ] || {
  usage >&2
  exit 1
}

case $1 in
  --help|-h)
    usage
    exit 0
    ;;
esac

dest=$1
shift
keep_execution=false
empty_pre_eval=false
taxonomy_from=

while [ "$#" -gt 0 ]; do
  case $1 in
    --keep-execution)
      keep_execution=true
      ;;
    --empty-pre-eval)
      empty_pre_eval=true
      ;;
    --taxonomy-from)
      [ "$#" -ge 2 ] || fail 1 'sandbox checkout: --taxonomy-from requires a path'
      shift
      taxonomy_from=$1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail 1 "sandbox checkout: unknown option: $1"
      ;;
  esac
  shift
done

case $dest in
  /*) ;;
  *) dest=$PWD/$dest ;;
esac

git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || fail 2 'sandbox checkout: current directory is not a Git repository'
repo=$(git rev-parse --show-toplevel)

if [ -e "$dest" ] || [ -L "$dest" ]; then
  [ -d "$dest" ] || fail 3 "sandbox checkout: destination is not an empty directory: $dest"
  [ -z "$(find "$dest" -mindepth 1 -maxdepth 1 -print -quit)" ] \
    || fail 3 "sandbox checkout: destination is not empty: $dest"
else
  mkdir -p "$dest"
fi

if [ -n "$taxonomy_from" ]; then
  case $taxonomy_from in
    /*) ;;
    *) taxonomy_from=$PWD/$taxonomy_from ;;
  esac
  [ -f "$taxonomy_from" ] || [ -L "$taxonomy_from" ] \
    || fail 1 "sandbox checkout: taxonomy file not found: $taxonomy_from"
fi

cd "$repo"
files=0
while IFS= read -r -d '' file; do
  case $file in
    docs/superpowers/execution/*)
      [ "$keep_execution" = true ] || continue
      ;;
    docs/superpowers/pre-eval/*)
      [ "$empty_pre_eval" = true ] && continue
      ;;
  esac

  target=$dest/$file
  mkdir -p "$(dirname "$target")"
  cp -pR "./$file" "$target"
  files=$((files + 1))
done < <(git ls-files -z)

if [ -n "$taxonomy_from" ]; then
  taxonomy_target=$dest/.claude/compound-v-impact-taxonomy.yaml
  mkdir -p "$(dirname "$taxonomy_target")"
  cp -pR "$taxonomy_from" "$taxonomy_target"
  files=$((files + 1))
fi

if [ "$empty_pre_eval" = true ]; then
  mkdir -p "$dest/docs/superpowers/pre-eval"
fi

git init -q "$dest"
git -C "$dest" add -A
git -C "$dest" -c user.email=sandbox@example.invalid -c user.name='Compound V sandbox' \
  commit -q -m sandbox
commit=$(git -C "$dest" rev-parse HEAD)

printf 'sandbox: %s\n' "$dest"
printf 'files: %s commit: %s\n' "$files" "$commit"
