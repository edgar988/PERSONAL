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

echo "==> Scheduling the Watcher (weekdays 21:30 UTC = 4:30pm ET market close)..."
CRON_LINE="30 21 * * 1-5 cd $BOT_DIR && $VENV_DIR/bin/python watcher.py >> $BOT_DIR/watcher.log 2>&1"
( crontab -l 2>/dev/null | grep -v 'trading-bot.*watcher.py' ; echo "$CRON_LINE" ) | crontab -
echo "Cron installed:"
crontab -l | grep watcher.py

echo
echo "==> Sending a Telegram self-test..."
cd "$BOT_DIR"
"$VENV_DIR/bin/python" watcher.py test

echo
echo "==> Running the Watcher once right now (full digest)..."
"$VENV_DIR/bin/python" watcher.py

echo
echo "All set. The Watcher will now text you every weekday after market close."
echo "Log file: $BOT_DIR/watcher.log"
"$VENV_DIR/bin/python" -c 'print()' 2>/dev/null || true
