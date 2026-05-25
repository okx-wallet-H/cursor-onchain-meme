#!/usr/bin/env bash
# Pause hourly simulation (launchd + config flag).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="$ROOT/config/config.json"
LABEL="com.hwallet.meme-sim"
DOMAIN="gui/$(id -u)"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

python3 - <<'PY' "$CONFIG"
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
cfg = json.loads(path.read_text())
cfg["sim_enabled"] = False
path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
print("sim_enabled=false in", path)
PY

launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
echo "Simulation paused. Resume: ./scripts/resume_sim.sh"
