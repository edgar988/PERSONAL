#!/usr/bin/env python3
"""
Social buzz monitor -- Reddit + StockTwits, run 2x daily by cron.

Counts watchlist-ticker mentions across r/wallstreetbets, r/stocks and
r/investing, flags mention SPIKES vs the recent average, and pulls
StockTwits sentiment. Saves buzz.json for the dashboard and sends a
Telegram digest.

IMPORTANT: buzz is AWARENESS, not a buy signal. By the time a ticker
trends on social media, the easy move usually already happened.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import Counter

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

import requests

import config
import notify

_DIR = os.path.dirname(__file__)
BUZZ_FILE = os.path.join(_DIR, "buzz.json")
BUZZ_STATE = os.path.join(_DIR, "buzz_state.json")
UA = {"User-Agent": "personal-trading-research-bot/1.0"}
HISTORY_KEEP = 10  # runs of history for the spike baseline


def reddit_titles(sub: str, limit: int = 60) -> list:
    try:
        r = requests.get(
            f"https://www.reddit.com/r/{sub}/hot.json?limit={limit}",
            headers=UA, timeout=25)
        posts = r.json()["data"]["children"]
        return [(p["data"].get("title", "") + " " +
                 (p["data"].get("selftext", "") or "")[:500])
                for p in posts]
    except Exception as e:
        print(f"[buzz] reddit r/{sub}: {e}")
        return []


def stocktwits(ticker: str):
    try:
        r = requests.get(
            f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json",
            headers=UA, timeout=25)
        msgs = r.json().get("messages", [])
    except Exception as e:
        print(f"[buzz] stocktwits {ticker}: {e}")
        return None
    bull = bear = 0
    for m in msgs:
        s = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
        if s == "Bullish":
            bull += 1
        elif s == "Bearish":
            bear += 1
    return {"messages": len(msgs), "bull": bull, "bear": bear}


def main() -> None:
    # ---- Reddit sweep ----
    texts = []
    for sub in config.BUZZ_SUBREDDITS:
        texts += reddit_titles(sub)
        time.sleep(1)

    mentions = Counter()
    cashtags = Counter()
    watch = set(config.WATCHLIST)
    for t in texts:
        for tk in watch:
            if re.search(rf"(?<![A-Za-z$]){re.escape(tk)}(?![A-Za-z])", t):
                mentions[tk] += 1
        for m in re.findall(r"\$([A-Za-z]{1,5})\b", t):
            cashtags[m.upper()] += 1

    # ---- spike detection vs recent history ----
    try:
        with open(BUZZ_STATE) as fh:
            hist = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        hist = {}
    spikes = []
    for tk in watch:
        n = mentions.get(tk, 0)
        past = hist.get(tk, [])
        avg = (sum(past) / len(past)) if past else 0
        if (n >= config.BUZZ_SPIKE_MIN
                and past and n >= avg * config.BUZZ_SPIKE_MULT):
            spikes.append((tk, n, avg))
        hist[tk] = (past + [n])[-HISTORY_KEEP:]
    with open(BUZZ_STATE + ".tmp", "w") as fh:
        json.dump(hist, fh)
    os.replace(BUZZ_STATE + ".tmp", BUZZ_STATE)

    # ---- StockTwits sentiment for talked-about watchlist names ----
    st_rows = {}
    for tk, _n in mentions.most_common(8):
        st = stocktwits(tk)
        if st:
            st_rows[tk] = st
        time.sleep(1)

    trending_new = [(tk, n) for tk, n in cashtags.most_common(15)
                    if tk not in watch and n >= 5][:5]

    payload = {
        "updated": time.time(),
        "mentions": dict(mentions.most_common()),
        "stocktwits": st_rows,
        "spikes": [{"ticker": tk, "count": n, "avg": round(a, 1)}
                   for tk, n, a in spikes],
        "trending_other": trending_new,
    }
    with open(BUZZ_FILE + ".tmp", "w") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(BUZZ_FILE + ".tmp", BUZZ_FILE)

    # ---- Telegram digest ----
    lines = ["<b>\U0001F4AC Social buzz</b> "
             "<i>(awareness only -- never a buy signal)</i>", ""]
    if spikes:
        lines.append("<b>⚠️ Mention spikes on your watchlist:</b>")
        for tk, n, avg in spikes:
            lines.append(f"• <b>{tk}</b>: {n} mentions "
                         f"(recent avg {avg:.0f}) -- check the chart + news "
                         "before reacting")
        lines.append("")
    top = mentions.most_common(5)
    if top:
        lines.append("<b>Watchlist chatter (Reddit):</b>")
        for tk, n in top:
            st = st_rows.get(tk)
            senti = ""
            if st and (st["bull"] + st["bear"]) >= 5:
                pct = st["bull"] / (st["bull"] + st["bear"]) * 100
                senti = f" | StockTwits {pct:.0f}% bullish"
            lines.append(f"• {tk}: {n} mentions{senti}")
    else:
        lines.append("<i>Quiet day -- no meaningful watchlist chatter.</i>")
    if trending_new:
        lines.append("")
        lines.append("<b>Trending elsewhere (not on watchlist):</b> "
                     + ", ".join(f"${tk} ({n})" for tk, n in trending_new))
    notify.send("\n".join(lines))
    print(f"[buzz] {sum(mentions.values())} watchlist mentions, "
          f"{len(spikes)} spikes, {len(trending_new)} outside trends")


if __name__ == "__main__":
    main()
