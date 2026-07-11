#!/usr/bin/env bash
# Stage 4 setup: dividend tracker + social buzz monitor.
# Run ON THE VPS from the trading-bot directory:  bash stage4-setup.sh
set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$HOME/.tradingbot-venv"
PY="$VENV_DIR/bin/python"

echo "==> Scheduling dividend tracker + social buzz..."
EXISTING="$(crontab -l 2>/dev/null | grep -v -e 'dividends.py' -e 'social_buzz.py' || true)"
D1="50 21 * * 1-5 cd $BOT_DIR && $PY dividends.py >> $BOT_DIR/dividends.log 2>&1"
D2="5 13 * * 1 cd $BOT_DIR && $PY dividends.py notify >> $BOT_DIR/dividends.log 2>&1"
B1="30 14 * * 1-5 cd $BOT_DIR && $PY social_buzz.py >> $BOT_DIR/buzz.log 2>&1"
B2="30 19 * * 1-5 cd $BOT_DIR && $PY social_buzz.py >> $BOT_DIR/buzz.log 2>&1"
{ [ -n "$EXISTING" ] && printf '%s\n' "$EXISTING"; echo "$D1"; echo "$D2"; echo "$B1"; echo "$B2"; } | crontab -
crontab -l | grep -e dividends -e social_buzz || true

echo "==> Restarting dashboard..."
systemctl restart tradingbot-dashboard.service

echo "==> Running both once right now..."
cd "$BOT_DIR"
"$PY" dividends.py notify
"$PY" social_buzz.py

echo
echo "Done."
echo "  * Dividend report: Mondays 9:05am ET (data refreshes nightly)"
echo "  * Social buzz digest: weekdays 10:30am + 3:30pm ET"
echo "  * Dashboard now shows Dividends + Social buzz panels"
""
