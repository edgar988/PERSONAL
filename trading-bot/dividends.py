#!/usr/bin/env python3
"""
Dividend tracker -- the income-stream module.

  python dividends.py          refresh dividends.json quietly (daily cron)
  python dividends.py notify   refresh + send the Telegram income summary
                               (weekly cron, Monday mornings)

Tracks yields / payout dates for the dividend sleeve and projects annual
dividend income from the shares you ACTUALLY hold. Read-only, never trades.
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

import yfinance as yf

import config
import notify

DIV_FILE = os.path.join(os.path.dirname(__file__), "dividends.json")


def dividend_info(ticker: str):
    try:
        i = yf.Ticker(ticker).info or {}
    except Exception as e:
        print(f"[div] {ticker}: {e}")
        return None
    rate = i.get("dividendRate") or i.get("trailingAnnualDividendRate") or 0
    yld = i.get("dividendYield") or i.get("trailingAnnualDividendYield") or 0
    if yld and yld < 1:            # yfinance sometimes returns 0.04, sometimes 4.0
        yld *= 100
    ex = i.get("exDividendDate")
    ex_date = None
    if isinstance(ex, (int, float)) and ex > 0:
        try:
            ex_date = datetime.fromtimestamp(ex, tz=timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            ex_date = None
    price = i.get("regularMarketPrice") or i.get("previousClose") or 0
    if not rate and not yld:
        return None
    return {"ticker": ticker,
            "price": round(float(price), 2) if price else None,
            "rate": round(float(rate), 2) if rate else 0,     # $/share/year
            "yield": round(float(yld), 2) if yld else 0,      # %/year
            "ex_date": ex_date}


def _holdings_safe() -> dict:
    try:
        import broker
        broker.ensure_login()
        return broker.holdings()
    except Exception as e:
        print(f"[div] holdings unavailable: {e}")
        return {}


def main(do_notify: bool) -> None:
    holdings = _holdings_safe()
    tickers = list(dict.fromkeys(config.DIVIDEND_TICKERS + list(holdings.keys())))

    rows, income_rows, total_income = [], [], 0.0
    for tk in tickers:
        d = dividend_info(tk)
        if not d:
            continue
        held_qty = 0.0
        if tk in holdings:
            try:
                held_qty = float(holdings[tk]["quantity"])
            except (KeyError, TypeError, ValueError):
                held_qty = 0.0
        d["held_qty"] = held_qty
        d["annual_income"] = round(held_qty * d["rate"], 2)
        total_income += d["annual_income"]
        rows.append(d)
        if d["annual_income"] > 0:
            income_rows.append(d)

    payload = {"updated": time.time(), "rows": rows,
               "total_annual_income": round(total_income, 2)}
    tmp = DIV_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, DIV_FILE)
    print(f"[div] {len(rows)} tickers, projected income ${total_income:.2f}/yr")

    if not do_notify:
        return

    lines = ["<b>\U0001F4B0 Dividend report</b>", ""]
    if income_rows:
        lines.append(f"<b>Projected income from your holdings: "
                     f"${total_income:.2f}/yr</b> "
                     f"(~${total_income / 12:.2f}/mo)")
        for d in income_rows:
            lines.append(f"• {d['ticker']}: {d['held_qty']:g} sh x "
                         f"${d['rate']:.2f} = ${d['annual_income']:.2f}/yr")
        lines.append("")
    else:
        lines.append("<i>No dividend-paying holdings yet -- the sleeve below "
                     "is what the bot watches for entries.</i>")
        lines.append("")
    lines.append("<b>Income sleeve yields:</b>")
    for d in rows:
        if d["ticker"] in config.DIVIDEND_TICKERS:
            ex = f", ex-div {d['ex_date']}" if d["ex_date"] else ""
            lines.append(f"• {d['ticker']}: {d['yield']:.1f}%/yr{ex}")
    lines.append("")
    lines.append("<i>Dividends compound slowly and reliably -- deposits "
                 "grow this number faster than anything else.</i>")
    notify.send("\n".join(lines))


if __name__ == "__main__":
    main(do_notify=len(sys.argv) > 1 and sys.argv[1] == "notify")
