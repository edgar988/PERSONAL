#!/usr/bin/env bash
# Stage 2 setup: approve-first executor + web dashboard as systemd services.
# Run ON THE VPS from the trading-bot directory:  bash stage2-setup.sh
set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$HOME/.tradingbot-venv"
PY="$VENV_DIR/bin/python"

echo "==> Installing/updating Python deps..."
"$VENV_DIR/bin/pip" install -r "$BOT_DIR/requirements.txt" | tail -1 || true

# --- Robinhood one-time login -------------------------------------------------
if [ ! -d "$HOME/.tokens" ] || ! ls "$HOME/.tokens"/*.pickle >/dev/null 2>&1; then
  echo
  echo "==> One-time Robinhood login (keep your phone handy for app approval)..."
  "$PY" "$BOT_DIR/rh_login.py"
else
  echo "==> Robinhood session already stored -- skipping login."
fi

# --- Dashboard password --------------------------------------------------------
if ! grep -q '^DASHBOARD_PASSWORD=' "$BOT_DIR/.env" 2>/dev/null; then
  echo
  read -r -p "Choose a dashboard password (don't reuse an important one): " DP
  echo "DASHBOARD_PASSWORD=$DP" >> "$BOT_DIR/.env"
  echo "Saved to .env"
fi
chmod 600 "$BOT_DIR/.env"

# --- systemd services -----------------------------------------------------------
echo "==> Installing systemd services..."
cat > /etc/systemd/system/tradingbot-approver.service <<EOF
[Unit]
Description=Trading bot approve-first executor (Telegram)
After=network-online.target

[Service]
WorkingDirectory=$BOT_DIR
ExecStart=$PY $BOT_DIR/approver_bot.py
Restart=on-failure
RestartSec=120

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/tradingbot-dashboard.service <<EOF
[Unit]
Description=Trading bot web dashboard (port 8080)
After=network-online.target

[Service]
WorkingDirectory=$BOT_DIR
ExecStart=$PY $BOT_DIR/dashboard.py
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now tradingbot-approver.service tradingbot-dashboard.service
sleep 3
systemctl --no-pager --lines=5 status tradingbot-approver.service || true
systemctl --no-pager --lines=3 status tradingbot-dashboard.service || true

IP=$(curl -s ifconfig.me || hostname -I | awk '{print $1}')
echo
echo "========================================================="
echo "Stage 2 is live."
echo "  * Telegram: you should have an 'Approver online' message"
echo "  * Dashboard: http://$IP:8080  (your DASHBOARD_PASSWORD)"
echo "  * Logs: journalctl -u tradingbot-approver -f"
echo "========================================================="
