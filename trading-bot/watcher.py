#!/usr/bin/env python3
"""
Stage 1 -- THE WATCHER.

Runs once per invocation (cron-friendly): pulls prices for every ticker in
the watchlist, evaluates the swing-trading rules, and sends you a Telegram
digest. It PLACES NO TRADES. Nothing here can touch your Robinhood account.

Run it:        python watcher.py
Self-test:     python watcher.py test     (just sends a Telegram test message)
Schedule it (Linux/VPS): see README.md -> cron
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

# Load .env (TELEGRAM_TOKEN, TELEGRAM_CHAT_ID) if python-dotenv is installed.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

import config
import data
import notify
from strategy import evaluate

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as fh:
        json.dump(state, fh, indent=2)


def _icon(verdict: str) -> str:
    return {"BUY_WATCH": "\U0001F7E2", "OVERBOUGHT": "\U0001F534",
            "NEUTRAL": "⚪"}.get(verdict, "⚪")


def main() -> None:
    state = _load_state()
    signals = []

    for ticker in config.WATCHLIST:
        df = data.fetch_history(ticker)
        sig = evaluate(ticker, df)
        if sig is not None:
            signals.append(sig)

    if not signals:
        notify.send("⚠️ Watcher ran but could not fetch any market "
                    "data. Check the VPS internet / yfinance.")
        return

    # Fresh BUY_WATCH = one that wasn't BUY_WATCH last run
    fresh_buys = [
        s for s in signals
        if s.verdict == "BUY_WATCH" and state.get(s.ticker) != "BUY_WATCH"
    ]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    buys = [s for s in signals if s.verdict == "BUY_WATCH"]
    over = [s for s in signals if s.verdict == "OVERBOUGHT"]

    lines = [f"<b>\U0001F4CA Watcher digest -- {now}</b>",
             "<i>Stage 1: signals only, no trades placed.</i>", ""]

    if fresh_buys:
        lines.append("<b>\U0001F195 NEW buy-watch signals:</b>")
        for s in fresh_buys:
            lines.append(f"\U0001F7E2 <b>{s.ticker}</b> ${s.price:.2f} -- {s.reasons[0]}")
        lines.append("")

    lines.append(f"<b>\U0001F7E2 Buy-watch ({len(buys)}):</b> "
                 + (", ".join(s.ticker for s in buys) or "none"))
    lines.append(f"<b>\U0001F534 Overbought ({len(over)}):</b> "
                 + (", ".join(s.ticker for s in over) or "none"))
    lines.append("")
    lines.append("<b>Full board:</b>")
    for s in sorted(signals, key=lambda x: x.verdict):
        lines.append(f"{_icon(s.verdict)} {s.ticker} ${s.price:.2f} "
                     f"(RSI {s.rsi:.0f})")

    notify.send("\n".join(lines))

    # Detailed reasoning for each fresh buy, as its own message
    for s in fresh_buys:
        detail = [f"\U0001F7E2 <b>{s.ticker}</b> -- buy-watch triggered",
                  f"Price: ${s.price:.2f}",
                  f"{config.FAST_SMA}d avg: ${s.sma_fast:.2f} | "
                  f"{config.SLOW_SMA}d avg: ${s.sma_slow:.2f} | RSI: {s.rsi:.0f}",
                  "", "<b>Why:</b>"]
        detail += [f"* {r}" for r in s.reasons]
        detail.append("")
        detail.append("<i>Watcher only -- no order placed. This is a heads-up "
                      "to research the name.</i>")
        notify.send("\n".join(detail))

    _save_state({s.ticker: s.verdict for s in signals})
    print(f"[watcher] evaluated {len(signals)} tickers, "
          f"{len(fresh_buys)} fresh buy-watch signals.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        notify.send("✅ Telegram test from the trading bot Watcher. "
                    "Notifications are working.")
    else:
        main()
