#!/usr/bin/env bash
# Stage 3 setup: market radar cron (3x daily) + dashboard v2 restart.
# Run ON THE VPS from the trading-bot directory:  bash stage3-setup.sh
set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$HOME/.tradingbot-venv"
PY="$VENV_DIR/bin/python"

echo "==> Scheduling market radar (pre-open, midday, after close)..."
EXISTING="$(crontab -l 2>/dev/null | grep -v 'market_radar.py' || true)"
R1="0 13 * * 1-5 cd $BOT_DIR && $PY market_radar.py >> $BOT_DIR/radar.log 2>&1"
R2="0 17 * * 1-5 cd $BOT_DIR && $PY market_radar.py >> $BOT_DIR/radar.log 2>&1"
R3="45 21 * * 1-5 cd $BOT_DIR && $PY market_radar.py >> $BOT_DIR/radar.log 2>&1"
{ [ -n "$EXISTING" ] && printf '%s\n' "$EXISTING"; echo "$R1"; echo "$R2"; echo "$R3"; } | crontab -
crontab -l | grep market_radar || true

echo "==> Restarting dashboard (v2)..."
systemctl restart tradingbot-dashboard.service

echo "==> Running the radar once right now..."
cd "$BOT_DIR"
"$PY" market_radar.py

echo
echo "Done. Radar digests fire weekdays at 9:00am, 1:00pm and ~5:45pm ET."
echo "Dashboard v2 (charts + stats + radar) is live on port 8080."
