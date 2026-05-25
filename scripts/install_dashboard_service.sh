#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$ROOT/launchd/com.hwallet.meme-dashboard.plist.template"
PLIST_DST="${HOME}/Library/LaunchAgents/com.hwallet.meme-dashboard.plist"
LABEL="com.hwallet.meme-dashboard"
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"
PORT="${PORT:-8765}"

chmod +x "$ROOT/scripts/dashboard_server.py"
mkdir -p "$ROOT/logs"

if [[ ! -f "$ROOT/dashboard/data.js" ]]; then
  python3 "$ROOT/scripts/meme_sim_trader.py" dashboard >/dev/null
fi

lsof -ti tcp:"$PORT" 2>/dev/null | xargs kill 2>/dev/null || true
sleep 1

sed "s|__REPO_ROOT__|${ROOT}|g" "$TEMPLATE" > "$PLIST_DST"
launchctl bootout "$DOMAIN" "$PLIST_DST" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST_DST"
launchctl enable "${DOMAIN}/${LABEL}"
launchctl kickstart -k "${DOMAIN}/${LABEL}"

for _ in $(seq 1 10); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "Dashboard service ready: http://127.0.0.1:${PORT}/dashboard/"
    echo "Repo root: ${ROOT}"
    exit 0
  fi
  sleep 0.5
done

echo "Service installed but health check failed. See ${ROOT}/logs/" >&2
exit 1
