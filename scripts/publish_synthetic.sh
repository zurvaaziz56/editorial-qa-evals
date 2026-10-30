#!/usr/bin/env bash
# Publish both branches atomically without checking hidden files into the worktree.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: publish_synthetic.sh GENERATED_DIRECTORY" >&2
  exit 2
fi
generation_dir=$(realpath "$1")
for filename in synthetic.jsonl smoke_ids.txt faults.jsonl; do
  test -f "$generation_dir/$filename"
done
cd "$(git rev-parse --show-toplevel)"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
export GIT_AUTHOR_NAME=workflow
export GIT_AUTHOR_EMAIL=workflow@users.noreply.github.com
export GIT_COMMITTER_NAME=$GIT_AUTHOR_NAME
export GIT_COMMITTER_EMAIL=$GIT_AUTHOR_EMAIL

git fetch --no-tags origin refs/heads/main:refs/remotes/origin/main
old_main=$(git rev-parse refs/remotes/origin/main)
if git cat-file -e "$old_main:data/golden/synthetic.jsonl" 2> /dev/null; then
  git show "$old_main:data/golden/synthetic.jsonl" > "$scratch/existing-entries.jsonl"
  python - "$scratch/existing-entries.jsonl" <<'PYTHON'
import json
import sys
from pathlib import Path

try:
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("Expected entry objects")
        if row.get("human") is not None or "injected_faults" in row:
            raise ValueError("Existing dataset has human labels or reconciled faults")
except (OSError, UnicodeError, ValueError):
    raise SystemExit(
        "Refusing publication: existing dataset is invalid, labeled, or reconciled."
    ) from None
PYTHON
fi
old_faults=
if git ls-remote --exit-code --heads origin refs/heads/faults > "$scratch/fault-ref"; then
  git fetch --no-tags origin refs/heads/faults:refs/remotes/origin/faults
  old_faults=$(git rev-parse refs/remotes/origin/faults)
  if git merge-base "$old_main" "$old_faults" > /dev/null; then
    echo "Refusing publication: faults must have independent orphan history." >&2
    exit 1
  fi
else
  result=$?
  if [[ $result -ne 2 ]]; then
    echo "Could not inspect the remote faults branch." >&2
    exit "$result"
  fi
fi

export GIT_INDEX_FILE="$scratch/main-index"
git read-tree "$old_main"
public_blob=$(git hash-object -w "$generation_dir/synthetic.jsonl")
smoke_blob=$(git hash-object -w "$generation_dir/smoke_ids.txt")
git update-index --add --cacheinfo 100644 "$public_blob" data/golden/synthetic.jsonl
git update-index --add --cacheinfo 100644 "$smoke_blob" data/smoke_ids.txt
main_tree=$(git write-tree)
new_main=$(printf '%s\n' 'Generate synthetic editorial QA entries' | git commit-tree "$main_tree" -p "$old_main")

export GIT_INDEX_FILE="$scratch/fault-index"
git read-tree --empty
fault_blob=$(git hash-object -w "$generation_dir/faults.jsonl")
git update-index --add --cacheinfo 100644 "$fault_blob" faults.jsonl
fault_tree=$(git write-tree)
if [[ -n $old_faults ]]; then
  new_faults=$(printf '%s\n' 'Store synthetic fault assignments' | git commit-tree "$fault_tree" -p "$old_faults")
else
  new_faults=$(printf '%s\n' 'Store synthetic fault assignments' | git commit-tree "$fault_tree")
fi

# No force pushes: a racing edit, branch protection, or unsupported atomic push fails
# the entire publication. Neither ref is left with a partially published generation.
git push --atomic origin "$new_main:refs/heads/main" "$new_faults:refs/heads/faults"
