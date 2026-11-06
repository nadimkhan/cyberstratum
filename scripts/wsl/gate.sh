#!/usr/bin/env bash
# The full quality gate, run the way WSL actually needs it.
#
# Two traps are handled here, both of which cost a full round of
# misdiagnosis:
#
#   1. A script started as `bash script.sh` is NOT a login shell, so
#      ~/.local/node/bin is missing from PATH. `npm` then resolves to the
#      *Windows* npm under /mnt/d/Program Files/nodejs, and every
#      npm-based step fails with "WSL 1 is not supported. Please upgrade
#      to WSL 2 or above." and "Could not determine Node.js install
#      directory" — a launcher error that says nothing about the code.
#      Putting the native Node first fixes it.
#
#   2. Exit codes must come from the step itself. Piping a step into
#      `tail` makes the pipeline's status `tail`'s, which is how a failed
#      lint can look like a clean run. Every code below is the step's own.
#
# Usage:  bash scripts/wsl/gate.sh
#         bash -lc 'bash scripts/wsl/gate.sh'   # from Windows

set -uo pipefail
export PATH="$HOME/.local/node/bin:$PATH"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT" || exit 1

# Logs are kept next to the other launcher logs so a failed gate can be
# read after the fact instead of vanishing with the process.
LOG_DIR="$REPO_ROOT/.dev-logs/gate/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$LOG_DIR"

failed=0
declare -a ROWS=()

run_step() {
  local name="$1"
  local mode="$2"   # "required" or "advisory"
  shift 2
  "$@" >"$LOG_DIR/$name.log" 2>&1
  local code=$?
  local status
  if [ "$code" -eq 0 ]; then
    status="ok"
  elif [ "$mode" = "advisory" ]; then
    status="drift (non-blocking)"
  else
    status="FAILED"
    failed=1
  fi
  ROWS+=("$(printf '%-14s %-24s exit=%s' "$name" "$status" "$code")")
  printf '%-14s %-24s exit=%s\n' "$name" "$status" "$code"
  if [ "$status" = "FAILED" ]; then
    tail -20 "$LOG_DIR/$name.log" | sed 's/^/    | /'
  fi
}

echo "repo      : $REPO_ROOT"
echo "node      : $(command -v node) ($(node -v 2>/dev/null))"
echo "npm       : $(command -v npm)"
echo

run_step lint        required npm run --silent lint
run_step typecheck   required npm run --silent typecheck
run_step test-py     required npm run --silent test:py
run_step test-web    required npm run --silent test:web
run_step check       required npm run --silent check
run_step format      advisory npm run --silent format:check

echo
if [ "$failed" -eq 0 ]; then
  echo "GATE: all required steps passed."
else
  echo "GATE: at least one required step failed."
fi
echo "logs: $LOG_DIR"
exit "$failed"
