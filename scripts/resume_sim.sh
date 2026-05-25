#!/usr/bin/env bash
# Resume hourly simulation after pause.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="$ROOT/config/config.json"

python3 - <<'PY' "$CONFIG"
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
cfg = json.loads(path.read_text())
cfg["sim_enabled"] = True
path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
print("sim_enabled=true in", path)
PY

exec "$ROOT/scripts/install_scheduler.sh"
