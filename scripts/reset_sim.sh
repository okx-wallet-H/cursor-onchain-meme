#!/usr/bin/env bash
# Reset paper wallet to initial cash, clear all positions/logs, export dashboard.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="/usr/local/bin:/opt/homebrew/bin:${HOME}/.local/bin:${PATH}"

python3 scripts/meme_sim_trader.py reset --force
echo "Done. Start scheduler: ./scripts/install_scheduler.sh"
