#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$ROOT/launchd/com.hwallet.meme-sim.plist.template"
PLIST_DST="${HOME}/Library/LaunchAgents/com.hwallet.meme-sim.plist"
LABEL="com.hwallet.meme-sim"
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"

chmod +x "$ROOT/scripts/run_scheduled_tick.sh"
mkdir -p "$ROOT/logs"
INTERVAL="$(python3 -c "import json; print(int(json.load(open('${ROOT}/config/config.json')).get('scan_interval_seconds', 1800)))")"
sed -e "s|__REPO_ROOT__|${ROOT}|g" -e "s|__SCAN_INTERVAL__|${INTERVAL}|g" "$TEMPLATE" > "$PLIST_DST"

launchctl bootout "$DOMAIN" "$PLIST_DST" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST_DST"
launchctl enable "${DOMAIN}/${LABEL}"
launchctl kickstart -k "${DOMAIN}/${LABEL}"

echo "Installed and started: ${LABEL}"
echo "Repo root: ${ROOT}"
echo "Interval: every ${INTERVAL} seconds ($(( INTERVAL / 60 )) min)"
echo "Logs: ${ROOT}/logs/"
