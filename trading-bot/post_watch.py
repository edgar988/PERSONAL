#!/usr/bin/env python3
"""
POST WATCH v2 -- send the bot a social post (Instagram link, caption text, or
plain $TICKERs) in Telegram and it:

  1. Tries to read the post (Instagram blocks robots often -- if so it asks
     you to paste the caption).
  2. AI CONTEXT READ (if ANTHROPIC_API_KEY is set): Claude reads the whole
     post -- identifying companies even when no ticker is named ("the company
     making cooling systems for Nvidia's data centers" -> VRT), judging the
     post's stance per stock, and flagging hype/pressure tactics.
  3. Falls back to plain ticker-pattern matching when no AI key is set or
     the API call fails.
  4. Validates every candidate against real market data, replies with an
     instant read (price, trend, RSI, verdict), and tracks each ticker for
     7 days with daily follow-ups. (Great influencer BS-detector.)

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

# words that look like tickers but aren't (regex-fallback path)
_BLACKLIST = {
    "THE", "AND", "FOR", "YOU", "ALL", "NEW", "BUY", "SELL", "HOLD",
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


def ai_read_post(text: str):
    """Claude reads the post in context. Returns a parsed PostRead or None.

    Identifies stocks the post is ABOUT -- explicit tickers AND companies
    implied by description -- plus per-stock stance and hype red flags.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        from pydantic import BaseModel
    except ImportError:
        print("[postwatch] anthropic/pydantic not installed -- regex fallback")
        return None

    class StockRead(BaseModel):
        ticker: str      # primary US ticker, e.g. VRT
        company: str     # company name
        why: str         # one sentence: how the post points at this stock
        stance: str      # "bullish" | "bearish" | "neutral"

    class PostRead(BaseModel):
        stocks: list[StockRead]
        summary: str         # one-sentence plain-language summary of the post
        hype_level: str      # "low" | "medium" | "high"
        red_flags: list[str]  # pressure tactics, guarantees, urgency, etc.

    try:
        client = anthropic.Anthropic()
        resp = client.messages.parse(
            model="claude-opus-4-8",
            max_tokens=2000,
            system=(
                "You analyze social-media posts about investing for a retail "
                "investor who wants the truth, not hype. Identify every "
                "publicly traded US stock the post is actually about: tickers "
                "named explicitly AND companies only implied by description "
                "(e.g. 'the company making cooling systems for Nvidia data "
                "centers' implies Vertiv, ticker VRT). Use each company's "
                "primary US ticker. Judge the post's stance per stock. Rate "
                "hype_level high when you see pressure tactics, urgency, "
                "guaranteed-return language, or signs of undisclosed "
                "promotion, and list those as red_flags. If the post is not "
                "about specific stocks, return an empty stocks list."
            ),
            messages=[{"role": "user", "content": f"Post:\n{text[:4000]}"}],
            output_format=PostRead,
        )
        return resp.parsed_output
    except Exception as e:
        print(f"[postwatch] AI read failed: {e}")
        return None


def extract_candidates(text: str) -> list:
    """Regex fallback: $TAGS first (high confidence), then ALL-CAPS words."""
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
                            "message instead -- paste the caption text for "
                            "a full context read.\n\n")

    search_text = f"{caption or ''}\n{text}".strip()

    # -- AI context read (preferred) --
    ai = ai_read_post(search_text)
    ai_info = {}          # ticker -> StockRead
    cands = []
    if ai is not None:
        for s in ai.stocks:
            tk = s.ticker.upper().strip()
            if tk and tk not in ai_info:
                ai_info[tk] = s
                cands.append(tk)

    # -- regex fallback / supplement --
    for tk in extract_candidates(search_text):
        if tk not in cands:
            cands.append(tk)

    if not cands:
        if ai is not None and ai.summary:
            say(blocked_note +
                f"\U0001F4F1 <b>Post check</b>\n\n<i>{ai.summary}</i>\n\n"
                "I couldn't tie this post to any specific stock. If you "
                "think it points at one, tell me the name or ticker.")
        else:
            say(blocked_note +
                "I couldn't find any stock tickers. Paste the post's caption "
                "text, or type them like: $NVDA $CLF")
        return

    # -- validate against real market data --
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

    # -- compose the reply --
    lines = [blocked_note + "\U0001F4F1 <b>Post check</b>", ""]
    if ai is not None:
        lines.append(f"<i>{ai.summary}</i>")
        hype_icon = {"low": "\U0001F7E2", "medium": "\U0001F7E1",
                     "high": "\U0001F534"}.get(ai.hype_level, "⚪")
        lines.append(f"Hype level: {hype_icon} <b>{ai.hype_level}</b>")
        if ai.red_flags:
            lines.append("⚠️ <b>Red flags:</b> " + "; ".join(ai.red_flags[:4]))
        lines.append("")
    elif caption:
        lines.append(f"<i>“{caption[:180]}”</i>")
        lines.append("")

    for s in sigs:
        trend = "uptrend" if s.price > s.sma_slow else "downtrend"
        icon = {"BUY_WATCH": "\U0001F7E2", "OVERBOUGHT": "\U0001F534",
                "NEUTRAL": "⚪"}[s.verdict]
        line = (f"{icon} <b>{s.ticker}</b> ${s.price:.2f} "
                f"({s.day_change_pct:+.1f}% today) -- {trend}, "
                f"RSI {s.rsi:.0f}, verdict: {s.verdict}")
        lines.append(line)
        info = ai_info.get(s.ticker)
        if info is not None:
            stance_icon = {"bullish": "\U0001F4C8", "bearish": "\U0001F4C9",
                           "neutral": "➖"}.get(info.stance, "➖")
            lines.append(f"   {stance_icon} Post is <b>{info.stance}</b>: "
                         f"{info.why}")
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
