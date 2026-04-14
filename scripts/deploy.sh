#!/usr/bin/env bash
# scripts/deploy.sh — bake version.json + scp files to walter + optional restart
#
# Usage:
#   scripts/deploy.sh [--restart] file [file...]
#
# - Writes dashboard/static/version.json with the current git HEAD sha,
#   branch, deploy timestamp, and a +dirty flag if the working tree has
#   uncommitted changes. Flask's context_processor reads this file to
#   render the commit badge in the header across all pages.
# - scp's every listed file to the mirrored path on walter, grouping by
#   parent directory. version.json is ALWAYS included so the header stays
#   in sync with whatever you deployed.
# - With --restart, restarts polybot.service on walter and waits for
#   /copy to come back up on port 8090.
#
# Example:
#   scripts/deploy.sh --restart dashboard/static/terminal.css dashboard/templates/_header.html

set -euo pipefail

SERVER="walter@10.0.0.20"
REMOTE_ROOT="/home/walter/polymarketscanner"

RESTART=0
FILES=()
for arg in "$@"; do
  case "$arg" in
    --restart) RESTART=1 ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) FILES+=("$arg") ;;
  esac
done

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "deploy.sh: no files specified" >&2
  echo "usage: $0 [--restart] file [file...]" >&2
  exit 1
fi

# Resolve repo root (the directory containing this script's parent)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Bake version.json
SHA=$(git rev-parse --short HEAD)
FULL_SHA=$(git rev-parse HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD)
# +dirty only if one of the files WE ARE DEPLOYING differs from HEAD.
# Unrelated modified tracked files elsewhere in the tree don't count —
# the goal is "does the content I'm scp'ing match a known commit".
DIRTY=""
for f in "${FILES[@]}"; do
  if [[ -f "$f" ]] && ! git diff-index --quiet HEAD -- "$f" 2>/dev/null; then
    DIRTY="+dirty"
    break
  fi
done
DEPLOYED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

VERSION_FILE="dashboard/static/version.json"
cat > "$VERSION_FILE" <<EOF
{"sha":"${SHA}${DIRTY}","full_sha":"${FULL_SHA}","branch":"${BRANCH}","deployed_at":"${DEPLOYED_AT}"}
EOF
echo "[deploy] baked ${VERSION_FILE}: sha=${SHA}${DIRTY} branch=${BRANCH} ts=${DEPLOYED_AT}"

# Always scp the version file alongside user-provided files
FILES+=("$VERSION_FILE")

# Group files by parent directory, scp each group in one call
declare -A BY_DIR
for f in "${FILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "[deploy] WARN: $f does not exist, skipping" >&2
    continue
  fi
  d=$(dirname "$f")
  BY_DIR[$d]+="$f "
done

for d in "${!BY_DIR[@]}"; do
  files_in_dir="${BY_DIR[$d]}"
  echo "[deploy] scp -> ${d}/  (${files_in_dir})"
  # shellcheck disable=SC2086
  scp $files_in_dir "${SERVER}:${REMOTE_ROOT}/${d}/"
done

if [[ $RESTART -eq 1 ]]; then
  echo "[deploy] restarting polybot on ${SERVER}..."
  ssh "$SERVER" "sudo systemctl restart polybot"
  echo "[deploy] waiting for port 8090..."
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if ssh "$SERVER" "curl -s -o /dev/null -w '%{http_code}' http://localhost:8090/copy" | grep -q '^200$'; then
      echo "[deploy] /copy is back (after ${i}s * ~2s)"
      break
    fi
    sleep 2
  done
  ssh "$SERVER" "sudo systemctl is-active polybot"
fi

echo "[deploy] done."
