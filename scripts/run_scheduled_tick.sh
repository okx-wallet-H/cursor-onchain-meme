#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

export PATH="/usr/local/bin:/opt/homebrew/bin:${HOME}/.local/bin:${PATH}"

STAMP="$(date -u +%Y%m%d_%H%M%S)"
LOG="$ROOT/logs/hourly_${STAMP}.log"
SCHEDULER_LOG="$ROOT/logs/scheduler.log"

{
  echo "=== meme sim tick ${STAMP} UTC ==="
  python3 scripts/meme_sim_trader.py tick
  echo "=== done ==="
} >>"$LOG" 2>&1

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) tick completed -> ${LOG}" >>"$SCHEDULER_LOG"
