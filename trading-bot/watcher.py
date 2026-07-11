#!/usr/bin/env python3
"""
Stage 1 -- THE WATCHER.

Two modes, both cron-friendly and both place ZERO trades:

  python watcher.py           Full digest -- every ticker, sent every time.
                              Run once daily after market close.

  python watcher.py scan      Quiet intraday scan -- run every 30 min during
                              market hours. Sends a message ONLY when:
                                * a ticker newly turns BUY_WATCH, or
                                * a ticker moves +/-BIG_MOVE_PCT% on the day
                                  (one alert per ticker per day).
                              Otherwise: total silence.

  python watcher.py test      Telegram self-test.
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
            raw = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"verdicts": {}, "move_alerts": {}}
    if "verdicts" not in raw:  # migrate old flat format
        return {"verdicts": raw, "move_alerts": {}}
    raw.setdefault("move_alerts", {})
    return raw


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as fh:
        json.dump(state, fh, indent=2)


def _icon(verdict: str) -> str:
    return {"BUY_WATCH": "\U0001F7E2", "OVERBOUGHT": "\U0001F534",
            "NEUTRAL": "⚪"}.get(verdict, "⚪")


def _collect_signals():
    signals = []
    for ticker in config.WATCHLIST:
        df = data.fetch_history(ticker)
        sig = evaluate(ticker, df)
        if sig is not None:
            signals.append(sig)
    return signals


def _fresh_buys(signals, state):
    return [s for s in signals
            if s.verdict == "BUY_WATCH"
            and state["verdicts"].get(s.ticker) != "BUY_WATCH"]


def _send_buy_detail(s) -> None:
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


def _update_state(state, signals) -> None:
    state["verdicts"] = {s.ticker: s.verdict for s in signals}
    _save_state(state)


def digest() -> None:
    """Full board, sent unconditionally. Run once daily after the close."""
    state = _load_state()
    signals = _collect_signals()
    if not signals:
        notify.send("⚠️ Watcher ran but could not fetch any market "
                    "data. Check the VPS internet / yfinance.")
        return

    fresh = _fresh_buys(signals, state)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    buys = [s for s in signals if s.verdict == "BUY_WATCH"]
    over = [s for s in signals if s.verdict == "OVERBOUGHT"]

    lines = [f"<b>\U0001F4CA Watcher digest -- {now}</b>",
             "<i>Stage 1: signals only, no trades placed.</i>", ""]
    if fresh:
        lines.append("<b>\U0001F195 NEW buy-watch signals:</b>")
        for s in fresh:
            lines.append(f"\U0001F7E2 <b>{s.ticker}</b> ${s.price:.2f} -- {s.reasons[0]}")
        lines.append("")
    lines.append(f"<b>\U0001F7E2 Buy-watch ({len(buys)}):</b> "
                 + (", ".join(s.ticker for s in buys) or "none"))
    lines.append(f"<b>\U0001F534 Overbought ({len(over)}):</b> "
                 + (", ".join(s.ticker for s in over) or "none"))
    lines.append("")
    lines.append("<b>Full board:</b>")
    for s in sorted(signals, key=lambda x: x.verdict):
        arrow = "↑" if s.day_change_pct >= 0 else "↓"
        lines.append(f"{_icon(s.verdict)} {s.ticker} ${s.price:.2f} "
                     f"{arrow}{abs(s.day_change_pct):.1f}% (RSI {s.rsi:.0f})")
    notify.send("\n".join(lines))

    for s in fresh:
        _send_buy_detail(s)

    _update_state(state, signals)
    print(f"[watcher] digest: {len(signals)} tickers, {len(fresh)} fresh buys.")


def scan() -> None:
    """Quiet intraday scan. Only speaks when something changed."""
    state = _load_state()
    signals = _collect_signals()
    if not signals:
        print("[watcher] scan: no data fetched (market data hiccup?)")
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fresh = _fresh_buys(signals, state)

    # Big intraday movers -- one alert per ticker per day
    movers = [s for s in signals
              if abs(s.day_change_pct) >= config.BIG_MOVE_PCT
              and state["move_alerts"].get(s.ticker) != today]

    for s in fresh:
        _send_buy_detail(s)

    if movers:
        lines = ["<b>⚡ Big intraday moves:</b>"]
        for s in movers:
            arrow = "\U0001F4C8 up" if s.day_change_pct > 0 else "\U0001F4C9 down"
            lines.append(f"<b>{s.ticker}</b> {arrow} "
                         f"{abs(s.day_change_pct):.1f}% today, ${s.price:.2f} "
                         f"(RSI {s.rsi:.0f})")
            state["move_alerts"][s.ticker] = today
        lines.append("")
        lines.append("<i>Heads-up only -- no trades placed.</i>")
        notify.send("\n".join(lines))

    _update_state(state, signals)
    print(f"[watcher] scan: {len(signals)} tickers, {len(fresh)} fresh buys, "
          f"{len(movers)} big movers. "
          + ("(quiet -- nothing new)" if not fresh and not movers else ""))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "digest"
    if mode == "test":
        notify.send("✅ Telegram test from the trading bot Watcher. "
                    "Notifications are working.")
    elif mode == "scan":
        scan()
    else:
        digest()
