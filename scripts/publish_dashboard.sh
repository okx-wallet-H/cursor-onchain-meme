#!/usr/bin/env bash
# Regenerate dashboard snapshot and push to GitHub (stable panel via repo / Pages).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PATH="/usr/local/bin:/opt/homebrew/bin:${HOME}/.local/bin:${PATH}"

BRANCH="${DASHBOARD_GIT_BRANCH:-main}"
REMOTE="${DASHBOARD_GIT_REMOTE:-origin}"

python3 scripts/meme_sim_trader.py dashboard >/dev/null

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "publish_dashboard: not a git repo, skip push" >&2
  exit 0
fi

if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  echo "publish_dashboard: no remote '$REMOTE', skip push" >&2
  exit 0
fi

git add dashboard/snapshot.json dashboard/data.js

if git diff --cached --quiet; then
  echo "dashboard unchanged — no push"
  exit 0
fi

STAMP="$(date -u +%Y-%m-%dT%H:%MZ)"
git commit -m "$(cat <<EOF
chore(dashboard): refresh snapshot ${STAMP}

Auto-published after sim tick for GitHub Pages / raw data panel.
EOF
)"

git push "$REMOTE" "$BRANCH"
echo "dashboard published -> $(git remote get-url "$REMOTE") (${BRANCH})"
echo "stable URL: https://okx-wallet-H.github.io/cursor-onchain-meme/"
