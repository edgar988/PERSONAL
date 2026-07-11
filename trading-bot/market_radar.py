#!/usr/bin/env python3
"""
MARKET RADAR -- broad-market research sweep, run 3x each trading day by cron.

Scans all 11 S&P sectors, major indexes, gold, bonds, and crypto plus the
watchlist. Ranks movers, pulls news headlines for the biggest watchlist
movers, sends a Telegram digest, and saves radar.json for the dashboard.
Read-only: never trades.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

import pandas as pd
import yfinance as yf

import config
import notify

RADAR_FILE = os.path.join(os.path.dirname(__file__), "radar.json")

SECTORS = {
    "XLK": "Tech", "XLE": "Energy", "XLF": "Financials", "XLI": "Industrials",
    "XLV": "Healthcare", "XLP": "Staples", "XLY": "Discretionary",
    "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real Estate",
    "XLC": "Comms",
}
MARKETS = {
    "SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Small caps",
    "GLD": "Gold", "TLT": "20y bonds", "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
}


def snapshot(ticker: str):
    """Last price, 1-day % and 5-day % for a ticker, or None."""
    try:
        df = yf.download(ticker, period="30d", interval="1d",
                         auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"].dropna()
        if len(close) < 6:
            return None
        last, prev, wk = (float(close.iloc[-1]), float(close.iloc[-2]),
                          float(close.iloc[-6]))
        return {"ticker": ticker,
                "price": round(last, 2),
                "d1": round((last / prev - 1) * 100, 2),
                "d5": round((last / wk - 1) * 100, 2)}
    except Exception as e:
        print(f"[radar] {ticker}: {e}")
        return None


def headlines(ticker: str, n: int = 2) -> list:
    try:
        news = yf.Ticker(ticker).news or []
    except Exception:
        return []
    out = []
    for item in news[:n]:
        title = None
        if isinstance(item, dict):
            title = (item.get("content") or {}).get("title") if \
                isinstance(item.get("content"), dict) else item.get("title")
        if title:
            out.append(str(title))
    return out


def fmt(row, label=None) -> str:
    arrow = "\U0001F4C8" if row["d1"] >= 0 else "\U0001F4C9"
    name = label or row["ticker"]
    return (f"{arrow} <b>{name}</b> {row['d1']:+.1f}% today "
            f"({row['d5']:+.1f}% 5d)")


def main() -> None:
    # -- broad market sweep --
    sector_rows, market_rows = [], []
    for tk, label in SECTORS.items():
        r = snapshot(tk)
        if r:
            r["label"] = label
            sector_rows.append(r)
    for tk, label in MARKETS.items():
        r = snapshot(tk)
        if r:
            r["label"] = label
            market_rows.append(r)

    # -- watchlist movers + their headlines --
    watch_rows = []
    for tk in config.WATCHLIST:
        r = snapshot(tk)
        if r:
            watch_rows.append(r)
    watch_rows.sort(key=lambda r: abs(r["d1"]), reverse=True)
    news = {}
    for r in watch_rows[:3]:
        if abs(r["d1"]) >= 1.0:
            hs = headlines(r["ticker"])
            if hs:
                news[r["ticker"]] = hs

    payload = {
        "updated": time.time(),
        "sectors": sorted(sector_rows, key=lambda r: r["d1"], reverse=True),
        "markets": market_rows,
        "watchlist": watch_rows,
        "news": news,
    }
    tmp = RADAR_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, RADAR_FILE)

    # -- Telegram digest --
    if not sector_rows:
        notify.send("⚠️ Market radar ran but fetched no data.")
        return
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    up = [r for r in payload["sectors"][:3] if r["d1"] > 0]
    down = [r for r in reversed(payload["sectors"]) if r["d1"] < 0][:3]
    lines = [f"<b>\U0001F4E1 Market radar -- {now}</b>", ""]
    if up:
        lines.append("<b>Leading sectors:</b>")
        lines += [fmt(r, r['label']) for r in up]
    if down:
        lines.append("")
        lines.append("<b>Lagging sectors:</b>")
        lines += [fmt(r, r['label']) for r in down]
    lines.append("")
    lines.append("<b>Other markets:</b>")
    lines += [fmt(r, r['label']) for r in market_rows]
    big = [r for r in watch_rows if abs(r["d1"]) >= 1.5][:4]
    if big:
        lines.append("")
        lines.append("<b>Watchlist movers:</b>")
        for r in big:
            lines.append(fmt(r))
            for h in news.get(r["ticker"], []):
                lines.append(f"   \U0001F4F0 {h}")
    lines.append("")
    lines.append("<i>Research only -- no trades placed.</i>")
    notify.send("\n".join(lines))
    print(f"[radar] {len(sector_rows)} sectors, {len(watch_rows)} watchlist, "
          f"{len(news)} with headlines.")


if __name__ == "__main__":
    main()
