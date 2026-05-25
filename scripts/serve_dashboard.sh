#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8765}"

if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "Dashboard already running: http://127.0.0.1:${PORT}/dashboard/"
  echo "Install as login service: ./scripts/install_dashboard_service.sh"
  exit 0
fi

cd "$ROOT"
if [[ ! -f dashboard/data.js ]]; then
  echo "Generating dashboard data..."
  python3 scripts/meme_sim_trader.py dashboard >/dev/null
fi

echo "Starting temporary dashboard server on http://127.0.0.1:${PORT}/dashboard/"
echo "For a persistent service run: ./scripts/install_dashboard_service.sh"
exec python3 scripts/dashboard_server.py --port "$PORT"
