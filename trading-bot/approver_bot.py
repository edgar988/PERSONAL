#!/usr/bin/env python3
"""
APPROVE-FIRST EXECUTOR (long-running service).

* Proposal queue -> Telegram with ✅/❌ buttons. NOTHING executes without a tap.
* Risk caps re-checked at execution time (per-position, total, theme).
* Daily loss stop: equity down $DAILY_LOSS_STOP_USD from the day's start ->
  buys halt until tomorrow (or /resume).
* TRAILING STOP: any position down STOP_LOSS_PCT from its PEAK price ->
  sell proposal. Protects gains, not just principal.
* TAKE PROFIT: position up TAKE_PROFIT_PCT from avg cost -> proposal to
  sell half (lock gains, let the rest ride).
* Plain messages (no /) = post-watch: send IG links, captions, or $TICKERs.
* Commands: /status /positions /halt /resume /sell TICKER /watching /help
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

import requests

import broker
import config
import post_watch
import proposals
import risk

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = str(os.environ.get("TELEGRAM_CHAT_ID", ""))
API = f"https://api.telegram.org/bot{TOKEN}"
_DIR = os.path.dirname(__file__)
STATE_FILE = os.path.join(_DIR, "bot_state.json")
HALT_REQUEST_FILE = os.path.join(_DIR, "halt_request.txt")  # dashboard -> bot
PROPOSAL_TTL = 4 * 3600
PERIODIC_EVERY = 600


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as fh:
            st = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        st = {}
    st.setdefault("offset", 0)
    st.setdefault("halted", False)
    st.setdefault("halt_reason", "")
    st.setdefault("day", None)
    st.setdefault("day_start_equity", None)
    st.setdefault("stoploss_proposed", {})
    st.setdefault("tp_proposed", {})
    st.setdefault("peaks", {})   # ticker -> high-water price since entry
    return st


def _save_state(st: dict) -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(st, fh, indent=2)
    os.replace(tmp, STATE_FILE)


def tg(method: str, **params):
    try:
        r = requests.post(f"{API}/{method}", json=params, timeout=40)
        return r.json()
    except Exception as e:
        print(f"[tg] {method} failed: {e}")
        return {"ok": False}


def say(text: str):
    return tg("sendMessage", chat_id=CHAT_ID, text=text, parse_mode="HTML")


def _edit(message_id, text):
    tg("editMessageText", chat_id=CHAT_ID, message_id=message_id,
       text=text, parse_mode="HTML")


def send_proposal(p: dict) -> None:
    if p["side"] == "buy":
        head = (f"\U0001F7E2 <b>BUY proposal</b> -- {p['ticker']}\n"
                f"Amount: <b>${p['dollars']:.2f}</b> "
                f"(ref price ${p['ref_price']:.2f})")
    else:
        head = (f"\U0001F534 <b>SELL proposal</b> -- {p['ticker']}\n"
                f"Quantity: <b>{p['quantity']:g}</b> shares")
    why = "\n".join(f"• {r}" for r in p["reasons"])
    text = (f"{head}\n\n<b>Why:</b>\n{why}\n\n"
            "<i>No order is placed unless you tap Approve. "
            "Expires in 4 hours.</i>")
    kb = {"inline_keyboard": [[
        {"text": "✅ Approve", "callback_data": f"approve:{p['id']}"},
        {"text": "❌ Deny", "callback_data": f"deny:{p['id']}"},
    ]]}
    resp = tg("sendMessage", chat_id=CHAT_ID, text=text,
              parse_mode="HTML", reply_markup=kb)
    if resp.get("ok"):
        proposals.update(p["id"], status="sent",
                         tg_message_id=resp["result"]["message_id"])
    else:
        print(f"[bot] failed to send proposal {p['id']}")


def execute(p: dict):
    """Place the order. Returns (ok, detail)."""
    try:
        if p["side"] == "buy":
            res = broker.buy_dollars(p["ticker"], p["dollars"])
        else:
            res = broker.sell_quantity(p["ticker"], p["quantity"])
    except Exception as e:
        return False, str(e)
    if isinstance(res, dict) and res.get("id"):
        return True, res["id"]
    detail = json.dumps(res)[:300] if res else "empty response from Robinhood"
    return False, detail


def on_callback(cb: dict, st: dict) -> None:
    if str(cb.get("from", {}).get("id")) != CHAT_ID:
        tg("answerCallbackQuery", callback_query_id=cb["id"], text="Not authorized.")
        return
    try:
        action, pid = cb["data"].split(":", 1)
    except (KeyError, ValueError):
        return
    p = next((x for x in proposals.load() if x["id"] == pid), None)
    mid = cb.get("message", {}).get("message_id")
    if p is None or p["status"] != "sent":
        tg("answerCallbackQuery", callback_query_id=cb["id"],
           text="Already handled or expired.")
        return

    if action == "deny":
        proposals.update(pid, status="denied")
        if mid:
            _edit(mid, f"❌ <b>Denied</b> -- {p['side']} {p['ticker']} not placed.")
        tg("answerCallbackQuery", callback_query_id=cb["id"], text="Denied.")
        return

    tg("answerCallbackQuery", callback_query_id=cb["id"], text="Placing order...")
    try:
        live_holdings = broker.holdings()
    except Exception as e:
        proposals.update(pid, status="failed", result=str(e))
        if mid:
            _edit(mid, f"⚠️ Could not reach Robinhood: {e}")
        return
    if p["side"] == "buy":
        ok, reason = risk.check_buy(p["ticker"], p["dollars"],
                                    live_holdings, st["halted"])
        if not ok:
            proposals.update(pid, status="denied", result=reason)
            if mid:
                _edit(mid, f"\U0001F6AB <b>Blocked by risk check:</b> {reason}")
            return

    ok, detail = execute(p)
    if ok:
        proposals.update(pid, status="executed", result=detail)
        proposals.log_trade({
            "ts": time.time(),
            "side": p["side"],
            "ticker": p["ticker"],
            "dollars": p.get("dollars"),
            "quantity": p.get("quantity"),
            "order_id": detail,
        })
        what = (f"${p['dollars']:.2f} of {p['ticker']}" if p["side"] == "buy"
                else f"{p['quantity']:g} shares of {p['ticker']}")
        if mid:
            _edit(mid, f"✅ <b>Order placed:</b> {p['side']} {what}\n"
                       f"Order id: <code>{detail}</code>")
    else:
        proposals.update(pid, status="failed", result=detail)
        if mid:
            _edit(mid, f"⚠️ <b>Order FAILED:</b> {detail}")


def on_message(msg: dict, st: dict) -> None:
    if str(msg.get("from", {}).get("id")) != CHAT_ID:
        return
    text = (msg.get("text") or "").strip()
    if not text:
        return

    # Plain message (no /command) -> post-watch: IG links, captions, $tickers
    if not text.startswith("/"):
        if re.search(r"https?://", text) or re.search(r"\$?[A-Za-z]{1,5}", text):
            try:
                post_watch.handle_message(text, say)
            except Exception as e:
                traceback.print_exc()
                say(f"⚠️ Post-watch hit an error: {e}")
        return

    cmd, *args = text.split()
    cmd = cmd.lower()

    if cmd == "/status":
        try:
            eq = broker.equity()
            bp = broker.buying_power()
            day0 = st.get("day_start_equity") or eq
            pnl = eq - day0
            say(f"\U0001F4CB <b>Status</b>\n"
                f"Equity: ${eq:,.2f} ({'+' if pnl >= 0 else ''}{pnl:,.2f} today)\n"
                f"Buying power: ${bp:,.2f}\n"
                f"Halted: {'YES -- ' + st['halt_reason'] if st['halted'] else 'no'}\n"
                f"Caps: ${config.MAX_PER_POSITION_USD}/position (ATR-scaled), "
                f"${config.MAX_TOTAL_DEPLOYED_USD} total, "
                f"{int(config.THEME_MAX_FRACTION*100)}% AI-theme cap, "
                f"${config.DAILY_LOSS_STOP_USD} daily stop, "
                f"{int(config.STOP_LOSS_PCT*100)}% trailing stop, "
                f"+{int(config.TAKE_PROFIT_PCT*100)}% take-profit")
        except Exception as e:
            say(f"⚠️ Robinhood unreachable: {e}")

    elif cmd == "/positions":
        try:
            hs = broker.holdings()
        except Exception as e:
            say(f"⚠️ Robinhood unreachable: {e}")
            return
        if not hs:
            say("No open positions.")
            return
        lines = ["\U0001F4BC <b>Positions</b>"]
        for tk, h in hs.items():
            try:
                peak = st["peaks"].get(tk)
                peak_note = f" (peak ${float(peak):.2f})" if peak else ""
                lines.append(
                    f"{tk}: {float(h['quantity']):g} sh @ "
                    f"${float(h['average_buy_price']):.2f} avg -> "
                    f"${float(h['equity']):.2f} ({h['percent_change']}%)"
                    f"{peak_note}")
            except (KeyError, TypeError, ValueError):
                lines.append(f"{tk}: (parse error)")
        say("\n".join(lines))

    elif cmd == "/halt":
        st["halted"] = True
        st["halt_reason"] = "manual /halt"
        say("\U0001F6D1 Halted. No new buys until /resume. (Sells still allowed.)")

    elif cmd == "/resume":
        st["halted"] = False
        st["halt_reason"] = ""
        say("▶️ Resumed. Buys allowed again, caps still enforced.")

    elif cmd == "/watching":
        say(post_watch.status_text())

    elif cmd == "/sell" and args:
        tk = args[0].upper()
        try:
            hs = broker.holdings()
        except Exception as e:
            say(f"⚠️ Robinhood unreachable: {e}")
            return
        if tk not in hs:
            say(f"You don't hold {tk}.")
            return
        qty = float(hs[tk]["quantity"])
        p = proposals.enqueue_sell(tk, qty, [f"Manual /sell request for all {qty:g} shares"])
        say(f"Sell proposal queued for {tk} -- approval buttons incoming."
            if p else f"A {tk} sell proposal is already open.")

    else:
        say("Commands:\n/status -- equity, P&L, halt state\n"
            "/positions -- open positions (with peak prices)\n"
            "/sell TICKER -- propose selling a position\n"
            "/watching -- active post watches\n"
            "/halt /resume -- stop/allow new buys\n\n"
            "Or just send an Instagram link, a post caption, or $TICKERs "
            "and I'll analyze + track the stocks mentioned.")


def periodic(st: dict) -> None:
    """Daily-stop bookkeeping + trailing-stop / take-profit watchdog (~10 min)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    eq = broker.equity()

    if st["day"] != today:
        st["day"] = today
        st["day_start_equity"] = eq
        st["stoploss_proposed"] = {}
        st["tp_proposed"] = {}
        if st["halted"] and st["halt_reason"] == "daily loss stop":
            st["halted"] = False
            st["halt_reason"] = ""
            say("▶️ New trading day -- daily loss halt lifted.")

    day0 = st.get("day_start_equity")
    if (day0 and not st["halted"]
            and eq <= day0 - config.DAILY_LOSS_STOP_USD):
        st["halted"] = True
        st["halt_reason"] = "daily loss stop"
        say(f"\U0001F6D1 <b>Daily loss stop hit</b> -- down "
            f"${day0 - eq:,.2f} today. New buys halted until tomorrow "
            "(or /resume to override).")

    holdings = broker.holdings()
    for tk, h in holdings.items():
        try:
            avg = float(h["average_buy_price"])
            price = float(h["price"])
            qty = float(h["quantity"])
        except (KeyError, TypeError, ValueError):
            continue
        if avg <= 0 or qty <= 0 or price <= 0:
            continue

        # High-water mark: starts at avg cost, ratchets up with price.
        peak = max(float(st["peaks"].get(tk, avg)), price)
        st["peaks"][tk] = peak
        gain = (price / avg - 1) * 100
        drop = (1 - price / peak) * 100

        # TRAILING STOP -- 8% below the peak (protects gains AND principal;
        # when the position never rose, peak ~ avg and it acts as the old
        # fixed stop-loss).
        if (price <= peak * (1 - config.STOP_LOSS_PCT)
                and st["stoploss_proposed"].get(tk) != today):
            kind = "TRAILING STOP" if peak > avg * 1.01 else "STOP-LOSS"
            proposals.enqueue_sell(tk, qty, [
                f"{kind}: {tk} is down {drop:.1f}% from its ${peak:.2f} "
                f"high-water mark (now ${price:.2f}, {gain:+.1f}% vs your "
                f"${avg:.2f} avg cost).",
                f"Rule: propose exit {int(config.STOP_LOSS_PCT * 100)}% below "
                "the peak.",
            ])
            st["stoploss_proposed"][tk] = today

        # TAKE PROFIT -- up 15%+ from avg cost: sell half, let the rest ride.
        elif (gain >= config.TAKE_PROFIT_PCT * 100
                and st["tp_proposed"].get(tk) != today):
            half = round(qty / 2, 4)
            if half <= 0:
                half = qty
            proposals.enqueue_sell(tk, half, [
                f"TAKE PROFIT: {tk} is up {gain:.1f}% from your ${avg:.2f} "
                f"avg cost (now ${price:.2f}).",
                f"Proposal: sell half ({half:g} sh) to lock in gains and let "
                "the rest ride. Deny to keep holding everything.",
            ])
            st["tp_proposed"][tk] = today

    # forget peaks for positions no longer held
    st["peaks"] = {k: v for k, v in st["peaks"].items() if k in holdings}


def check_halt_request(st: dict) -> None:
    """Dashboard writes halt_request.txt; we apply and delete it."""
    try:
        with open(HALT_REQUEST_FILE) as fh:
            req = fh.read().strip().lower()
        os.remove(HALT_REQUEST_FILE)
    except FileNotFoundError:
        return
    except OSError:
        return
    if req == "halt" and not st["halted"]:
        st["halted"] = True
        st["halt_reason"] = "dashboard halt"
        say("\U0001F6D1 Halted from the dashboard. /resume or dashboard to lift.")
    elif req == "resume" and st["halted"]:
        st["halted"] = False
        st["halt_reason"] = ""
        say("▶️ Resumed from the dashboard.")


def main() -> None:
    if not TOKEN or not CHAT_ID:
        sys.exit("Set TELEGRAM_TOKEN / TELEGRAM_CHAT_ID in .env")
    try:
        broker.ensure_login()
    except Exception as e:
        say(f"⚠️ Approver bot can't start: {e}")
        sys.exit(str(e))

    st = _load_state()
    say("\U0001F916 <b>Approver online (Risk v2).</b>\n"
        "ATR position sizing · trailing stops · take-profit proposals · "
        "theme concentration cap.\n"
        "✅/❌ proposals, /help for commands.")
    last_periodic = 0.0

    while True:
        try:
            check_halt_request(st)

            for p in proposals.load():
                if p["status"] == "pending":
                    if p["side"] == "buy":
                        try:
                            hs = broker.holdings()
                        except Exception:
                            hs = {}
                        ok, reason = risk.check_buy(p["ticker"], p["dollars"],
                                                    hs, st["halted"])
                        if not ok:
                            proposals.update(p["id"], status="denied", result=reason)
                            say(f"\U0001F6AB Skipped {p['ticker']} buy: {reason}")
                            continue
                    send_proposal(p)
                elif (p["status"] == "sent"
                      and time.time() - p["created"] > PROPOSAL_TTL):
                    proposals.update(p["id"], status="expired")
                    if p.get("tg_message_id"):
                        _edit(p["tg_message_id"],
                              f"⌛ Expired -- {p['ticker']} {p['side']} "
                              "proposal timed out (4h).")

            if time.time() - last_periodic > PERIODIC_EVERY:
                periodic(st)
                last_periodic = time.time()
                _save_state(st)

            upd = tg("getUpdates", offset=st["offset"] + 1, timeout=25)
            for u in upd.get("result", []):
                st["offset"] = u["update_id"]
                if "callback_query" in u:
                    on_callback(u["callback_query"], st)
                elif "message" in u:
                    on_message(u["message"], st)
            _save_state(st)
        except KeyboardInterrupt:
            raise
        except Exception:
            traceback.print_exc()
            time.sleep(10)


if __name__ == "__main__":
    main()
