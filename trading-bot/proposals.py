"""
Pending-trade proposal queue.

Producer: the Watcher (enqueues a buy proposal when a fresh signal fires).
Consumer: the approver bot (sends it to Telegram with buttons, executes on
approval). Also holds the executed-trade log.
"""
from __future__ import annotations

import json
import os
import time
import uuid

_DIR = os.path.dirname(__file__)
QUEUE_FILE = os.path.join(_DIR, "proposals.json")
TRADES_FILE = os.path.join(_DIR, "trades.json")


def _read(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _write(path, items):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(items, fh, indent=2)
    os.replace(tmp, path)


def load():
    return _read(QUEUE_FILE)


def save(items):
    _write(QUEUE_FILE, items)


def enqueue_buy(ticker, ref_price, dollars, reasons):
    """Queue a buy proposal. Skips if one is already open for this ticker."""
    items = load()
    for p in items:
        if (p["ticker"] == ticker and p["side"] == "buy"
                and p["status"] in ("pending", "sent")):
            return None
    p = {
        "id": uuid.uuid4().hex[:10],
        "side": "buy",
        "ticker": ticker,
        "dollars": round(float(dollars), 2),
        "ref_price": round(float(ref_price), 2),
        "reasons": list(reasons),
        "status": "pending",   # pending -> sent -> approved/denied/expired/executed/failed
        "created": time.time(),
        "tg_message_id": None,
        "result": None,
    }
    items.append(p)
    save(items)
    return p


def enqueue_sell(ticker, quantity, reasons):
    items = load()
    for p in items:
        if (p["ticker"] == ticker and p["side"] == "sell"
                and p["status"] in ("pending", "sent")):
            return None
    p = {
        "id": uuid.uuid4().hex[:10],
        "side": "sell",
        "ticker": ticker,
        "quantity": float(quantity),
        "reasons": list(reasons),
        "status": "pending",
        "created": time.time(),
        "tg_message_id": None,
        "result": None,
    }
    items.append(p)
    save(items)
    return p


def update(pid, **fields):
    items = load()
    for p in items:
        if p["id"] == pid:
            p.update(fields)
            save(items)
            return p
    return None


def log_trade(entry):
    items = _read(TRADES_FILE)
    items.append(entry)
    _write(TRADES_FILE, items)


def trades():
    return _read(TRADES_FILE)
