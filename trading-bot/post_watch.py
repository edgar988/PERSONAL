#!/usr/bin/env python3
"""
POST WATCH -- send the bot a social post (Instagram link, caption text, or
plain $TICKERs) in Telegram and it:

  1. Tries to read the post (Instagram blocks robots often -- if so it asks
     you to paste the caption).
  2. Extracts and validates the stock tickers mentioned.
  3. Replies with an instant read: price, trend vs the 50-day average, RSI,
     and the same verdict logic the watcher uses.
  4. Tracks each ticker for 7 days from the post, sending daily follow-ups
     showing how the "tip" actually performed. (Great influencer BS-detector.)

Run `python post_watch.py followup` daily via cron for the follow-ups.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

import requests

import data
import notify
from strategy import evaluate

WATCH_FILE = os.path.join(os.path.dirname(__file__), "post_watch.json")
BROWSER_UA = {"User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like "
                             "Mac OS X) AppleWebKit/605.1.15 (KHTML, like "
                             "Gecko) Version/17.0 Mobile/15E148 Safari/604.1")}
WATCH_DAYS = 7
MAX_TICKERS = 6

# words that look like tickers but aren't
_BLACKLIST = {
    "THE", "AND", "FOR", "YOU", "ALL", "NEW", "NOW", "BUY", "SELL", "HOLD",
    "THIS", "WITH", "JUST", "LIKE", "GET", "ONE", "TOP", "CEO", "IPO", "USA",
    "USD", "AI", "DM", "PM", "EPS", "YOY", "ATH", "IMO", "DD", "YOLO", "LFG",
    "WSB", "NOT", "ARE", "CAN", "HAS", "WAS", "OUT", "BIG", "HOT", "SO", "IT",
    "ON", "IN", "AT", "TO", "UP", "GO", "BE", "MY", "WE", "IS", "OF", "OR",
}


def _load() -> list:
    try:
        with open(WATCH_FILE) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(items: list) -> None:
    tmp = WATCH_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(items, fh, indent=2)
    os.replace(tmp, WATCH_FILE)


def fetch_caption(url: str):
    """Try to read a public post's caption via its meta tags. Often blocked."""
    try:
        r = requests.get(url, headers=BROWSER_UA, timeout=20,
                         allow_redirects=True)
        if r.status_code != 200:
            return None
        for prop in ("og:description", "og:title", "description"):
            m = re.search(
                rf'<meta[^>]+(?:property|name)="{prop}"[^>]+content="([^"]+)"',
                r.text) or re.search(
                rf'<meta[^>]+content="([^"]+)"[^>]+(?:property|name)="{prop}"',
                r.text)
            if m:
                cap = html.unescape(m.group(1)).strip()
                if len(cap) > 20 and "log in" not in cap.lower():
                    return cap
        return None
    except Exception as e:
        print(f"[postwatch] fetch failed: {e}")
        return None


def extract_candidates(text: str) -> list:
    """$TAGS first (high confidence), then bare ALL-CAPS words."""
    cands, seen = [], set()
    for m in re.findall(r"\$([A-Za-z]{1,5})\b", text):
        tk = m.upper()
        if tk not in seen and tk not in _BLACKLIST:
            seen.add(tk)
            cands.append(tk)
    for m in re.findall(r"\b[A-Z]{2,5}\b", text):
        if m not in seen and m not in _BLACKLIST:
            seen.add(m)
            cands.append(m)
    return cands[:MAX_TICKERS + 2]


def analyze(ticker: str):
    """Full watcher-style analysis; returns None for invalid tickers."""
    df = data.fetch_history(ticker)
    return evaluate(ticker, df)


def handle_message(text: str, say) -> None:
    """Entry point called by the approver bot for non-command messages."""
    urls = re.findall(r"https?://\S+", text)
    ig_urls = [u for u in urls if "instagram.com" in u]

    caption = None
    blocked_note = ""
    if ig_urls:
        say("\U0001F50E Reading that post...")
        caption = fetch_caption(ig_urls[0])
        if caption is None:
            blocked_note = ("⚠️ Instagram wouldn't let me read the post "
                            "(they block robots). I used the text of your "
                            "message instead -- paste the caption or type "
                            "the tickers (like $NVDA) if I missed any.\n\n")

    search_text = f"{caption or ''} {text}"
    cands = extract_candidates(search_text)
    if not cands:
        say(blocked_note +
            "I couldn't find any stock tickers. Paste the post's caption "
            "text, or type them like: $NVDA $CLF")
        return

    sigs = []
    for tk in cands:
        s = analyze(tk)
        if s is not None:
            sigs.append(s)
        if len(sigs) >= MAX_TICKERS:
            break
    if not sigs:
        say(blocked_note +
            f"I found possible tickers ({', '.join(cands)}) but none "
            "validated as real stocks. Paste the caption or type them "
            "like $NVDA.")
        return

    lines = [blocked_note + "\U0001F4F1 <b>Post check</b>", ""]
    if caption:
        lines.append(f"<i>“{caption[:180]}”</i>")
        lines.append("")
    for s in sigs:
        trend = "uptrend" if s.price > s.sma_slow else "downtrend"
        icon = {"BUY_WATCH": "\U0001F7E2", "OVERBOUGHT": "\U0001F534",
                "NEUTRAL": "⚪"}[s.verdict]
        lines.append(f"{icon} <b>{s.ticker}</b> ${s.price:.2f} "
                     f"({s.day_change_pct:+.1f}% today) -- {trend}, "
                     f"RSI {s.rsi:.0f}, verdict: {s.verdict}")
    lines.append("")
    lines.append(f"\U0001F440 I'll track these for {WATCH_DAYS} days and "
                 "report how the post's picks actually perform.")
    lines.append("<i>Reminder: social posts often pump at tops. This is "
                 "research, not a buy list.</i>")
    say("\n".join(lines))

    watches = _load()
    watches.append({
        "created": time.time(),
        "source": ig_urls[0] if ig_urls else "text",
        "tickers": {s.ticker: {"start_price": round(s.price, 2)}
                    for s in sigs},
        "last_day_reported": 0,
    })
    _save(watches)


def status_text() -> str:
    watches = [w for w in _load()
               if time.time() - w["created"] < WATCH_DAYS * 86400]
    if not watches:
        return "No active post watches. Send me an Instagram link or $TICKERs."
    lines = ["\U0001F440 <b>Active post watches:</b>"]
    for w in watches:
        day = int((time.time() - w["created"]) / 86400)
        lines.append(f"• day {day}/{WATCH_DAYS}: "
                     + ", ".join(w["tickers"].keys()))
    return "\n".join(lines)


def followup() -> None:
    """Daily cron: report performance-since-post for each active watch."""
    watches = _load()
    if not watches:
        return
    keep, lines = [], []
    for w in watches:
        age_days = int((time.time() - w["created"]) / 86400)
        if age_days > WATCH_DAYS:
            continue  # expired -- drop
        if age_days >= 1 and age_days > w.get("last_day_reported", 0):
            for tk, info in w["tickers"].items():
                s = analyze(tk)
                if s is None:
                    continue
                chg = (s.price / info["start_price"] - 1) * 100
                icon = "\U0001F4C8" if chg >= 0 else "\U0001F4C9"
                lines.append(f"{icon} <b>{tk}</b> {chg:+.1f}% since the post "
                             f"(day {age_days}/{WATCH_DAYS}, "
                             f"now ${s.price:.2f}, RSI {s.rsi:.0f})")
            w["last_day_reported"] = age_days
        keep.append(w)
    _save(keep)
    if lines:
        notify.send("\U0001F440 <b>Post-watch update</b>\n\n" +
                    "\n".join(lines) +
                    "\n\n<i>How the posts' picks are actually doing.</i>")
        print(f"[postwatch] reported {len(lines)} tickers")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "followup":
        followup()
    else:
        print(status_text())
