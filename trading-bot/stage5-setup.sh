#!/usr/bin/env bash
# Stage 5 setup: post-watch (IG links via Telegram) follow-up cron + approver restart.
# Run ON THE VPS from the trading-bot directory:  bash stage5-setup.sh
set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$HOME/.tradingbot-venv"
PY="$VENV_DIR/bin/python"

echo "==> Scheduling daily post-watch follow-ups..."
EXISTING="$(crontab -l 2>/dev/null | grep -v 'post_watch.py' || true)"
PW="40 21 * * 1-5 cd $BOT_DIR && $PY post_watch.py followup >> $BOT_DIR/postwatch.log 2>&1"
{ [ -n "$EXISTING" ] && printf '%s\n' "$EXISTING"; echo "$PW"; } | crontab -
crontab -l | grep post_watch || true

echo "==> Restarting the approver bot (now handles links + tickers in chat)..."
systemctl restart tradingbot-approver.service
sleep 3
systemctl --no-pager --lines=3 status tradingbot-approver.service || true

echo
echo "Done. Send the Telegram bot an Instagram link or '$NVDA $CLF'-style"
echo "tickers and it will analyze + track them for 7 days."
