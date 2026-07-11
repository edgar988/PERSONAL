#!/usr/bin/env python3
"""
THE WATCHER.

  python watcher.py           Full digest -- every ticker, sent every time.
  python watcher.py scan      Quiet intraday scan (every 30 min via cron).
                              Speaks only on: fresh BUY_WATCH, +/-3% day
                              moves, or unusual volume (>= 2.5x average).
  python watcher.py test      Telegram self-test.

Stage 2 integration: every fresh BUY_WATCH lands in the proposal queue,
sized by volatility (ATR): calm names get up to $500, wild ones get less,
so every position carries roughly equal risk. Nothing is placed without
a ✅ tap in Telegram.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

import config
import data
import notify
import proposals
from strategy import evaluate

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as fh:
            raw = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        raw = {}
    if "verdicts" not in raw:  # migrate old flat format
        raw = {"verdicts": raw} if raw else {"verdicts": {}}
    raw.setdefault("move_alerts", {})
    raw.setdefault("vol_alerts", {})
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


def _position_dollars(s) -> int:
    """Volatility-scaled position size: equal risk, not equal dollars."""
    if s.atr_pct <= 0:
        return int(config.MAX_PER_POSITION_USD)
    scale = min(1.0, config.ATR_BASELINE_PCT / s.atr_pct)
    dollars = int(round(config.MAX_PER_POSITION_USD * scale / 10) * 10)
    return max(config.MIN_POSITION_USD,
               min(dollars, config.MAX_PER_POSITION_USD))


def _queue_for_approval(s) -> None:
    """Stage 2 hand-off: put the signal in the proposal queue."""
    try:
        dollars = _position_dollars(s)
        reasons = list(s.reasons)
        if dollars < config.MAX_PER_POSITION_USD:
            reasons.append(
                f"Position sized ${dollars} (not ${config.MAX_PER_POSITION_USD}) "
                f"because {s.ticker} moves ~{s.atr_pct:.1f}%/day vs the "
                f"{config.ATR_BASELINE_PCT:.0f}% baseline -- equal risk sizing.")
        proposals.enqueue_buy(s.ticker, s.price, dollars, reasons)
    except Exception as e:  # queueing must never break the watcher
        print(f"[watcher] could not enqueue {s.ticker}: {e}")


def _send_buy_detail(s) -> None:
    detail = [f"\U0001F7E2 <b>{s.ticker}</b> -- buy-watch triggered",
              f"Price: ${s.price:.2f}",
              f"{config.FAST_SMA}d avg: ${s.sma_fast:.2f} | "
              f"{config.SLOW_SMA}d avg: ${s.sma_slow:.2f} | RSI: {s.rsi:.0f} | "
              f"ATR {s.atr_pct:.1f}%/day",
              "", "<b>Why:</b>"]
    detail += [f"* {r}" for r in s.reasons]
    detail.append("")
    detail.append("<i>If the approver is running, a ✅/❌ proposal follows. "
                  "No order is placed without your tap.</i>")
    notify.send("\n".join(detail))


def _update_state(state, signals) -> None:
    state["verdicts"] = {s.ticker: s.verdict for s in signals}
    state["snapshot"] = {
        s.ticker: {"price": round(s.price, 2),
                   "rsi": round(s.rsi),
                   "chg": round(s.day_change_pct, 2),
                   "atr": round(s.atr_pct, 2),
                   "vol": round(s.vol_ratio, 2)}
        for s in signals
    }
    state["updated"] = time.time()
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
             "<i>Signals below; orders only happen via ✅ approval.</i>", ""]
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
        vol_note = f" ⚡{s.vol_ratio:.1f}x vol" if s.vol_ratio >= config.VOLUME_SPIKE_MULT else ""
        lines.append(f"{_icon(s.verdict)} {s.ticker} ${s.price:.2f} "
                     f"{arrow}{abs(s.day_change_pct):.1f}% (RSI {s.rsi:.0f})"
                     f"{vol_note}")
    notify.send("\n".join(lines))

    for s in fresh:
        _send_buy_detail(s)
        _queue_for_approval(s)

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

    movers = [s for s in signals
              if abs(s.day_change_pct) >= config.BIG_MOVE_PCT
              and state["move_alerts"].get(s.ticker) != today]

    # Unusual volume: someone big is active (free order-flow proxy).
    vol_spikes = [s for s in signals
                  if s.vol_ratio >= config.VOLUME_SPIKE_MULT
                  and state["vol_alerts"].get(s.ticker) != today]

    for s in fresh:
        _send_buy_detail(s)
        _queue_for_approval(s)

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

    if vol_spikes:
        lines = ["<b>\U0001F50A Unusual volume (institutional radar):</b>"]
        for s in vol_spikes:
            lines.append(f"<b>{s.ticker}</b> trading at {s.vol_ratio:.1f}x its "
                         f"normal volume ({s.day_change_pct:+.1f}% today, "
                         f"${s.price:.2f})")
            state["vol_alerts"][s.ticker] = today
        lines.append("")
        lines.append("<i>Big volume = big players active. Check the chart and "
                     "news before reacting -- this is awareness, not a signal.</i>")
        notify.send("\n".join(lines))

    _update_state(state, signals)
    print(f"[watcher] scan: {len(signals)} tickers, {len(fresh)} fresh buys, "
          f"{len(movers)} movers, {len(vol_spikes)} volume spikes.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "digest"
    if mode == "test":
        notify.send("✅ Telegram test from the trading bot Watcher. "
                    "Notifications are working.")
    elif mode == "scan":
        scan()
    else:
        digest()
