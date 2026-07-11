#!/usr/bin/env python3
"""
Phone-friendly web dashboard (view + halt/resume only -- it can NOT place
orders; orders only happen via Telegram approval buttons).

Runs on port 8080. Password comes from DASHBOARD_PASSWORD in .env.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from flask import Flask, redirect, render_template_string, request, session

import config
import proposals

_DIR = os.path.dirname(__file__)
STATE_FILE = os.path.join(_DIR, "state.json")
BOT_STATE_FILE = os.path.join(_DIR, "bot_state.json")
HALT_REQUEST_FILE = os.path.join(_DIR, "halt_request.txt")

PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
app = Flask(__name__)
app.secret_key = hashlib.sha256(
    (PASSWORD + "|tradingbot-cookie-salt").encode()).hexdigest()


def _read_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _holdings_safe():
    try:
        import broker
        broker.ensure_login()
        return broker.holdings(), broker.equity(), None
    except Exception as e:
        return {}, 0.0, str(e)


PAGE = """
<!doctype html><html><head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<meta http-equiv='refresh' content='60'>
<title>Trading Bot</title>
<style>
 body{font-family:-apple-system,system-ui,sans-serif;background:#0f1115;
      color:#e6e6e6;margin:0;padding:16px;max-width:720px;margin:auto}
 h1{font-size:1.3em} h2{font-size:1.05em;margin:22px 0 8px;color:#9ecbff}
 .card{background:#181b22;border-radius:12px;padding:12px 14px;margin:10px 0}
 table{width:100%;border-collapse:collapse;font-size:.92em}
 td,th{padding:6px 4px;text-align:left;border-bottom:1px solid #262a33}
 .g{color:#4ade80}.r{color:#f87171}.y{color:#fbbf24}.dim{color:#8b90a0}
 .pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:.85em}
 .pill.ok{background:#123b22;color:#4ade80}.pill.bad{background:#3b1212;color:#f87171}
 button{background:#26304a;color:#e6e6e6;border:0;border-radius:8px;
        padding:10px 16px;font-size:1em}
 form{display:inline}
 input[type=password]{padding:10px;border-radius:8px;border:1px solid #333;
        background:#181b22;color:#eee;font-size:1em}
</style></head><body>
{% if not authed %}
  <h1>\U0001F512 Trading Bot</h1>
  <form method='post' action='/login' class='card'>
    <input type='password' name='password' placeholder='Password' autofocus>
    <button type='submit'>Sign in</button>
    {% if bad %}<p class='r'>Wrong password.</p>{% endif %}
  </form>
{% else %}
  <h1>\U0001F4C8 Trading Bot
    {% if halted %}<span class='pill bad'>HALTED</span>
    {% else %}<span class='pill ok'>active</span>{% endif %}
  </h1>
  <div class='card'>
    {% if rh_error %}
      <span class='y'>⚠️ Robinhood: {{ rh_error }}</span>
    {% else %}
      Equity: <b>${{ '%.2f' % equity }}</b>
      <span class='dim'>| caps: ${{ caps.pos }}/pos · ${{ caps.total }} total
      · ${{ caps.stop }} daily stop</span>
    {% endif %}
    <div style='margin-top:10px'>
      {% if halted %}
        <form method='post' action='/resume'><button>▶️ Resume buys</button></form>
      {% else %}
        <form method='post' action='/halt'><button>\U0001F6D1 Halt buys</button></form>
      {% endif %}
    </div>
  </div>

  <h2>Positions</h2><div class='card'>
  {% if positions %}<table><tr><th>Ticker</th><th>Qty</th><th>Avg</th><th>Value</th><th>%</th></tr>
    {% for p in positions %}<tr><td><b>{{p.tk}}</b></td><td>{{p.qty}}</td>
      <td>${{p.avg}}</td><td>${{p.val}}</td>
      <td class='{{ 'g' if p.pct_f >= 0 else 'r' }}'>{{p.pct}}%</td></tr>{% endfor %}
  </table>{% else %}<span class='dim'>None open.</span>{% endif %}</div>

  <h2>Pending approvals</h2><div class='card'>
  {% if pending %}{% for p in pending %}
    <p>{{ '\U0001F7E2 BUY' if p.side == 'buy' else '\U0001F534 SELL' }}
       <b>{{p.ticker}}</b>
       {% if p.side == 'buy' %}${{p.dollars}}{% else %}{{p.quantity}} sh{% endif %}
       <span class='dim'>-- answer in Telegram ({{p.age}})</span></p>
  {% endfor %}{% else %}<span class='dim'>Nothing waiting. Approvals happen in Telegram.</span>{% endif %}</div>

  <h2>Signals (latest watcher run)</h2><div class='card'>
  {% if verdicts %}<table>
    {% for v in verdicts %}<tr><td><b>{{v.tk}}</b></td>
      <td class='{{ 'g' if v.verdict == 'BUY_WATCH' else ('r' if v.verdict == 'OVERBOUGHT' else 'dim') }}'>
      {{v.verdict}}</td></tr>{% endfor %}
  </table>{% else %}<span class='dim'>Watcher hasn't run yet.</span>{% endif %}</div>

  <h2>Trade history</h2><div class='card'>
  {% if trades %}<table><tr><th>When (UTC)</th><th>Side</th><th>Ticker</th><th>Size</th></tr>
    {% for t in trades %}<tr><td class='dim'>{{t.when}}</td><td>{{t.side}}</td>
      <td><b>{{t.ticker}}</b></td><td>{{t.size}}</td></tr>{% endfor %}
  </table>{% else %}<span class='dim'>No trades executed yet.</span>{% endif %}</div>

  <p class='dim'>Read-only + halt. Orders are only ever placed from Telegram
  approvals. Auto-refreshes every 60s.</p>
  <form method='post' action='/logout'><button>Sign out</button></form>
{% endif %}
</body></html>
"""


def _authed() -> bool:
    return bool(PASSWORD) and session.get("ok") is True


@app.route("/login", methods=["POST"])
def login():
    if PASSWORD and request.form.get("password") == PASSWORD:
        session["ok"] = True
        return redirect("/")
    return render_template_string(PAGE, authed=False, bad=True)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/")


@app.route("/halt", methods=["POST"])
def halt():
    if _authed():
        with open(HALT_REQUEST_FILE, "w") as fh:
            fh.write("halt")
    return redirect("/")


@app.route("/resume", methods=["POST"])
def resume():
    if _authed():
        with open(HALT_REQUEST_FILE, "w") as fh:
            fh.write("resume")
    return redirect("/")


@app.route("/")
def index():
    if not _authed():
        return render_template_string(PAGE, authed=False, bad=False)

    bot_state = _read_json(BOT_STATE_FILE, {})
    watcher_state = _read_json(STATE_FILE, {})
    holdings, equity, rh_error = _holdings_safe()

    positions = []
    for tk, h in holdings.items():
        try:
            pct = float(h.get("percent_change") or 0)
            positions.append({
                "tk": tk,
                "qty": f"{float(h['quantity']):g}",
                "avg": f"{float(h['average_buy_price']):.2f}",
                "val": f"{float(h['equity']):.2f}",
                "pct": f"{pct:+.1f}",
                "pct_f": pct,
            })
        except (KeyError, TypeError, ValueError):
            continue

    pending = []
    for p in proposals.load():
        if p["status"] in ("pending", "sent"):
            age_min = int((time.time() - p["created"]) / 60)
            pending.append({**p, "age": f"{age_min}m ago"})

    verdicts = [{"tk": tk, "verdict": v}
                for tk, v in sorted(watcher_state.get("verdicts", {}).items())]

    trades = []
    for t in reversed(proposals.trades()[-25:]):
        size = (f"${t['dollars']:.2f}" if t.get("dollars")
                else f"{t.get('quantity'):g} sh")
        trades.append({
            "when": time.strftime("%m-%d %H:%M", time.gmtime(t["ts"])),
            "side": t["side"].upper(),
            "ticker": t["ticker"],
            "size": size,
        })

    return render_template_string(
        PAGE, authed=True, bad=False,
        halted=bool(bot_state.get("halted")),
        equity=equity, rh_error=rh_error,
        caps={"pos": config.MAX_PER_POSITION_USD,
              "total": config.MAX_TOTAL_DEPLOYED_USD,
              "stop": config.DAILY_LOSS_STOP_USD},
        positions=positions, pending=pending,
        verdicts=verdicts, trades=trades)


if __name__ == "__main__":
    if not PASSWORD:
        raise SystemExit("Set DASHBOARD_PASSWORD in .env first.")
    app.run(host="0.0.0.0", port=8080)
