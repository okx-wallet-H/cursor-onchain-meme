#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

export PATH="/usr/local/bin:/opt/homebrew/bin:${HOME}/.local/bin:${PATH}"

if ! python3 -c "import json; c=json.load(open('config/config.json')); raise SystemExit(0 if c.get('sim_enabled', True) else 1)"; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) tick skipped (sim_enabled=false)" >>"$ROOT/logs/scheduler.log"
  exit 0
fi

STAMP="$(date -u +%Y%m%d_%H%M%S)"
LOG="$ROOT/logs/hourly_${STAMP}.log"
SCHEDULER_LOG="$ROOT/logs/scheduler.log"

{
  echo "=== meme sim tick ${STAMP} UTC ==="
  python3 scripts/meme_sim_trader.py tick
  if [[ -x "$ROOT/scripts/publish_dashboard.sh" ]]; then
    "$ROOT/scripts/publish_dashboard.sh" || echo "WARN: dashboard publish failed (offline?)"
  fi
  echo "=== done ==="
} >>"$LOG" 2>&1

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) tick completed -> ${LOG}" >>"$SCHEDULER_LOG"
