"""Telegram notifications. Token + chat id come from the environment."""
from __future__ import annotations

import os

import requests


def send(text: str) -> bool:
    """Send a Telegram message. Falls back to printing if creds are unset."""
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("[notify] TELEGRAM_TOKEN / TELEGRAM_CHAT_ID not set -- printing instead:\n")
        print(text)
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        ok = resp.ok and resp.json().get("ok", False)
        if not ok:
            print(f"[notify] Telegram error: {resp.status_code} {resp.text}")
        return ok
    except Exception as e:
        print(f"[notify] Telegram request failed: {e}")
        return False
