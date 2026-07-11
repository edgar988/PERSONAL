#!/usr/bin/env bash
# One-shot VPS setup for the trading-bot Watcher (Ubuntu 22.04/24.04).
# Run from inside the trading-bot directory:
#   bash vps-setup.sh
set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$HOME/.tradingbot-venv"

echo "==> Installing system packages (python3-venv, git)..."
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip git

echo "==> Creating Python virtualenv at $VENV_DIR ..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
"$VENV_DIR/bin/pip" install -r "$BOT_DIR/requirements.txt"

# .env -- create from example if missing, then make sure it's filled in
if [ ! -f "$BOT_DIR/.env" ]; then
  cp "$BOT_DIR/.env.example" "$BOT_DIR/.env"
  echo
  echo '!! .env created. You must put your real Telegram token in it.'
fi
if grep -q "your-bot-token-here" "$BOT_DIR/.env"; then
  echo
  read -r -p "Paste your Telegram bot token: " TOKEN
  sed -i "s|^TELEGRAM_TOKEN=.*|TELEGRAM_TOKEN=$TOKEN|" "$BOT_DIR/.env"
  echo ".env updated."
fi
chmod 600 "$BOT_DIR/.env"

echo "==> Scheduling the Watcher..."
#  * scan  -- every 30 min during US market hours (13:30-20:00 UTC covers
#             9:30am-4pm ET during daylight saving; quiet unless news)
#  * digest -- once daily after the close (21:30 UTC), the full board
SCAN_LINE="*/30 13-20 * * 1-5 cd $BOT_DIR && $VENV_DIR/bin/python watcher.py scan >> $BOT_DIR/watcher.log 2>&1"
DIGEST_LINE="30 21 * * 1-5 cd $BOT_DIR && $VENV_DIR/bin/python watcher.py >> $BOT_DIR/watcher.log 2>&1"
# NB: `|| true` guards -- on a fresh server the crontab is empty, which makes
# `crontab -l` and `grep -v` return non-zero; without the guards, pipefail
# aborts the whole script right here (silently -- before the Telegram test).
EXISTING="$(crontab -l 2>/dev/null | grep -v 'trading-bot.*watcher.py' || true)"
{ [ -n "$EXISTING" ] && printf '%s\n' "$EXISTING"; echo "$SCAN_LINE"; echo "$DIGEST_LINE"; } | crontab -
echo "Cron installed:"
crontab -l | grep watcher.py || true

echo
echo "==> Sending a Telegram self-test..."
cd "$BOT_DIR"
"$VENV_DIR/bin/python" watcher.py test

echo
echo "==> Running the Watcher once right now (full digest)..."
"$VENV_DIR/bin/python" watcher.py

echo
echo "All set:"
echo "  * Intraday scan every 30 min during market hours (silent unless something changes)"
echo "  * Full digest every weekday after the close"
echo "Log file: $BOT_DIR/watcher.log"
