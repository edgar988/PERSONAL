#!/usr/bin/env python3
"""
Phone-friendly web dashboard v2 -- TradingView charts, stats, market radar.

View + halt/resume only: it can NOT place orders. Orders only happen via
Telegram approval buttons. Password from DASHBOARD_PASSWORD in .env.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
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
RADAR_FILE = os.path.join(_DIR, "radar.json")
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
<title>Trading Bot</title>
<style>
 body{font-family:-apple-system,system-ui,sans-serif;background:#0f1115;
      color:#e6e6e6;margin:0 auto;padding:16px;max-width:860px}
 h1{font-size:1.3em} h2{font-size:1.02em;margin:20px 0 8px;color:#9ecbff}
 .card{background:#181b22;border-radius:12px;padding:12px 14px;margin:10px 0}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
 .stat{background:#181b22;border-radius:12px;padding:12px 14px}
 .stat .v{font-size:1.35em;font-weight:700}.stat .l{color:#8b90a0;font-size:.8em}
 .bar{height:8px;background:#262a33;border-radius:99px;margin-top:8px;overflow:hidden}
 .bar>div{height:100%;background:#3b82f6;border-radius:99px}
 table{width:100%;border-collapse:collapse;font-size:.92em}
 td,th{padding:6px 4px;text-align:left;border-bottom:1px solid #262a33}
 .g{color:#4ade80}.r{color:#f87171}.y{color:#fbbf24}.dim{color:#8b90a0}
 .pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:.85em}
 .pill.ok{background:#123b22;color:#4ade80}.pill.bad{background:#3b1212;color:#f87171}
 .chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
 .chip{background:#26304a;border-radius:99px;padding:5px 12px;font-size:.85em;
       color:#cdd6f4;text-decoration:none}
 .chip.on{background:#3b82f6;color:#fff}
 button{background:#26304a;color:#e6e6e6;border:0;border-radius:8px;
        padding:10px 16px;font-size:1em}
 form{display:inline}
 a{color:#9ecbff}
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

  <div class='grid'>
    <div class='stat'><div class='l'>Equity</div>
      <div class='v'>${{ '%.0f' % equity }}</div>
      {% if day_pnl is not none %}
        <div class='{{ 'g' if day_pnl >= 0 else 'r' }}'>{{ '%+.2f' % day_pnl }} today</div>
      {% endif %}</div>
    <div class='stat'><div class='l'>Deployed</div>
      <div class='v'>${{ '%.0f' % deployed }}</div>
      <div class='l'>of ${{ caps.total }} cap</div>
      <div class='bar'><div style='width:{{ deployed_pct }}%'></div></div></div>
    <div class='stat'><div class='l'>Positions</div>
      <div class='v'>{{ positions|length }}</div>
      <div class='l'>${{ caps.pos }}/position cap</div></div>
    <div class='stat'><div class='l'>Trades executed</div>
      <div class='v'>{{ trades_total }}</div>
      <div class='l'>${{ caps.stop }} daily stop</div></div>
  </div>
  {% if rh_error %}<div class='card y'>⚠️ Robinhood: {{ rh_error }}</div>{% endif %}

  <div class='card'>
    {% if halted %}
      <form method='post' action='/resume'><button>▶️ Resume buys</button></form>
    {% else %}
      <form method='post' action='/halt'><button>\U0001F6D1 Halt buys</button></form>
    {% endif %}
    <span class='dim'> orders only ever placed from Telegram ✅</span>
  </div>

  <h2>Chart</h2>
  <div class='card'>
    <div class='chips'>
      {% for tk in watch %}
        <a class='chip {{ 'on' if tk == chart }}' href='/?chart={{ tk }}'>{{ tk }}</a>
      {% endfor %}
    </div>
    <div id='tvchart' style='height:420px'></div>
  </div>

  <h2>Watchlist signals
    {% if snap_age %}<span class='dim'>({{ snap_age }})</span>{% endif %}</h2>
  <div class='card'>
  {% if signals %}<table>
    <tr><th>Ticker</th><th>Price</th><th>Day</th><th>RSI</th><th>Signal</th></tr>
    {% for s in signals %}<tr>
      <td><a href='/?chart={{ s.tk }}'><b>{{ s.tk }}</b></a></td>
      <td>${{ s.price }}</td>
      <td class='{{ 'g' if s.chg >= 0 else 'r' }}'>{{ '%+.1f' % s.chg }}%</td>
      <td>{{ s.rsi }}</td>
      <td class='{{ 'g' if s.verdict == 'BUY_WATCH' else ('r' if s.verdict == 'OVERBOUGHT' else 'dim') }}'>{{ s.verdict }}</td>
    </tr>{% endfor %}
  </table>{% else %}<span class='dim'>Watcher hasn't run yet.</span>{% endif %}</div>

  <h2>\U0001F4E1 Market radar
    {% if radar_age %}<span class='dim'>({{ radar_age }})</span>{% endif %}</h2>
  <div class='card'>
  {% if sectors %}
    <table><tr><th>Sector</th><th>Today</th><th>5 day</th></tr>
    {% for r in sectors %}<tr><td>{{ r.label }}</td>
      <td class='{{ 'g' if r.d1 >= 0 else 'r' }}'>{{ '%+.1f' % r.d1 }}%</td>
      <td class='{{ 'g' if r.d5 >= 0 else 'r' }}'>{{ '%+.1f' % r.d5 }}%</td></tr>{% endfor %}
    </table>
    <table style='margin-top:10px'><tr><th>Market</th><th>Today</th><th>5 day</th></tr>
    {% for r in markets %}<tr><td>{{ r.label }}</td>
      <td class='{{ 'g' if r.d1 >= 0 else 'r' }}'>{{ '%+.1f' % r.d1 }}%</td>
      <td class='{{ 'g' if r.d5 >= 0 else 'r' }}'>{{ '%+.1f' % r.d5 }}%</td></tr>{% endfor %}
    </table>
    {% if news %}<div style='margin-top:10px'>
      {% for tk, items in news.items() %}
        <p><b>{{ tk }}</b>{% for h in items %}<br>\U0001F4F0 <span class='dim'>{{ h }}</span>{% endfor %}</p>
      {% endfor %}</div>{% endif %}
  {% else %}<span class='dim'>Radar hasn't run yet (runs 3x daily).</span>{% endif %}</div>

  <h2>Positions</h2><div class='card'>
  {% if positions %}<table><tr><th>Ticker</th><th>Qty</th><th>Avg</th><th>Value</th><th>%</th></tr>
    {% for p in positions %}<tr><td><a href='/?chart={{ p.tk }}'><b>{{ p.tk }}</b></a></td>
      <td>{{ p.qty }}</td><td>${{ p.avg }}</td><td>${{ p.val }}</td>
      <td class='{{ 'g' if p.pct_f >= 0 else 'r' }}'>{{ p.pct }}%</td></tr>{% endfor %}
  </table>{% else %}<span class='dim'>None open.</span>{% endif %}</div>

  <h2>Pending approvals</h2><div class='card'>
  {% if pending %}{% for p in pending %}
    <p>{{ '\U0001F7E2 BUY' if p.side == 'buy' else '\U0001F534 SELL' }}
       <b>{{ p.ticker }}</b>
       {% if p.side == 'buy' %}${{ p.dollars }}{% else %}{{ p.quantity }} sh{% endif %}
       <span class='dim'>-- answer in Telegram ({{ p.age }})</span></p>
  {% endfor %}{% else %}<span class='dim'>Nothing waiting.</span>{% endif %}</div>

  <h2>Trade history</h2><div class='card'>
  {% if trades %}<table><tr><th>When (UTC)</th><th>Side</th><th>Ticker</th><th>Size</th></tr>
    {% for t in trades %}<tr><td class='dim'>{{ t.when }}</td><td>{{ t.side }}</td>
      <td><b>{{ t.ticker }}</b></td><td>{{ t.size }}</td></tr>{% endfor %}
  </table>{% else %}<span class='dim'>No trades executed yet.</span>{% endif %}</div>

  <p class='dim'>Read-only + halt. Charts by TradingView. Data refreshes with
  each watcher/radar run.</p>
  <form method='post' action='/logout'><button>Sign out</button></form>

  <script src='https://s3.tradingview.com/tv.js'></script>
  <script>
    new TradingView.widget({
      "container_id": "tvchart",
      "symbol": "{{ chart }}",
      "interval": "D",
      "timezone": "America/New_York",
      "theme": "dark",
      "style": "1",
      "locale": "en",
      "autosize": true,
      "hide_side_toolbar": true,
      "allow_symbol_change": true,
      "studies": ["MASimple@tv-basicstudies", "RSI@tv-basicstudies"]
    });
  </script>
{% endif %}
</body></html>
"""


def _authed() -> bool:
    return bool(PASSWORD) and session.get("ok") is True


def _age(ts) -> str:
    if not ts:
        return ""
    mins = int((time.time() - ts) / 60)
    if mins < 60:
        return f"updated {mins}m ago"
    return f"updated {mins // 60}h {mins % 60}m ago"


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
    radar = _read_json(RADAR_FILE, {})
    holdings, equity, rh_error = _holdings_safe()

    chart = request.args.get("chart", "")
    if not re.fullmatch(r"[A-Z0-9.\-]{1,12}", chart or ""):
        chart = config.WATCHLIST[0] if config.WATCHLIST else "SPY"

    positions, deployed = [], 0.0
    for tk, h in holdings.items():
        try:
            val = float(h["equity"])
            pct = float(h.get("percent_change") or 0)
            deployed += val
            positions.append({
                "tk": tk,
                "qty": f"{float(h['quantity']):g}",
                "avg": f"{float(h['average_buy_price']):.2f}",
                "val": f"{val:.2f}",
                "pct": f"{pct:+.1f}",
                "pct_f": pct,
            })
        except (KeyError, TypeError, ValueError):
            continue

    day0 = bot_state.get("day_start_equity")
    day_pnl = (equity - day0) if (day0 and equity) else None

    snapshot = watcher_state.get("snapshot", {})
    signals = []
    for tk, verdict in sorted(watcher_state.get("verdicts", {}).items()):
        s = snapshot.get(tk, {})
        signals.append({"tk": tk, "verdict": verdict,
                        "price": f"{s.get('price', 0):.2f}",
                        "chg": float(s.get("chg", 0)),
                        "rsi": s.get("rsi", "-")})
    signals.sort(key=lambda x: (x["verdict"] != "BUY_WATCH",
                                x["verdict"] != "OVERBOUGHT", x["tk"]))

    pending = []
    for p in proposals.load():
        if p["status"] in ("pending", "sent"):
            age_min = int((time.time() - p["created"]) / 60)
            pending.append({**p, "age": f"{age_min}m ago"})

    all_trades = proposals.trades()
    trades = []
    for t in reversed(all_trades[-25:]):
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
        equity=equity, rh_error=rh_error, day_pnl=day_pnl,
        deployed=deployed,
        deployed_pct=min(100, int(deployed / config.MAX_TOTAL_DEPLOYED_USD * 100)),
        caps={"pos": config.MAX_PER_POSITION_USD,
              "total": config.MAX_TOTAL_DEPLOYED_USD,
              "stop": config.DAILY_LOSS_STOP_USD},
        watch=config.WATCHLIST, chart=chart,
        signals=signals, snap_age=_age(watcher_state.get("updated")),
        sectors=radar.get("sectors", []), markets=radar.get("markets", []),
        news=radar.get("news", {}), radar_age=_age(radar.get("updated")),
        positions=positions, pending=pending,
        trades=trades, trades_total=len(all_trades))


if __name__ == "__main__":
    if not PASSWORD:
        raise SystemExit("Set DASHBOARD_PASSWORD in .env first.")
    app.run(host="0.0.0.0", port=8080)
