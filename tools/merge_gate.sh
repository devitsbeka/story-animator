#!/usr/bin/env bash
# Merge gate: run before merging any agent branch into the lead branch.
#   tools/merge_gate.sh <branch> [--base REF] [--skip-goldens] [--skip-pytest] [--keep] [--out DIR]
# Checks the branch out in a temp worktree and runs pytest, the lesson checks, the shot validator and lighting --check
# on the current episode (no new failures vs the base) and the golden regression for the goldens the branch affects.
# Prints PASS/FAIL with reasons and the diff sheet path; exit 0 = PASS. See tools/merge_gate.py.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ $# -lt 1 ]; then
  echo "usage: tools/merge_gate.sh <branch> [--base REF] [--skip-goldens] [--skip-pytest] [--keep]" >&2
  exit 2
fi
exec nice -n 5 python3 "$HERE/merge_gate.py" "$@"
