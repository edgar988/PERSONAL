"""
Thin wrapper around robin_stocks -- ALL Robinhood access goes through here.

A one-time interactive login (python rh_login.py) stores a session pickle
under ~/.tokens/. After that, headless services reuse it.
"""
from __future__ import annotations

import os

import robin_stocks.robinhood as rh

_PICKLE_DIR = os.path.expanduser("~/.tokens")


def has_stored_session() -> bool:
    if not os.path.isdir(_PICKLE_DIR):
        return False
    return any(f.endswith(".pickle") for f in os.listdir(_PICKLE_DIR))


def ensure_login() -> None:
    """Reuse the stored session. Raises RuntimeError with a clear message
    if no session exists (never blocks waiting for terminal input)."""
    if not has_stored_session():
        raise RuntimeError(
            "No Robinhood session found. SSH to the server and run: "
            "python rh_login.py (one-time interactive login)."
        )
    rh.login(store_session=True)


def latest_price(ticker: str):
    vals = rh.stocks.get_latest_price(ticker)
    try:
        return float(vals[0]) if vals and vals[0] else None
    except (TypeError, ValueError):
        return None


def holdings() -> dict:
    """{ticker: {price, quantity, average_buy_price, equity, ...}} (strings)."""
    return rh.account.build_holdings() or {}


def equity() -> float:
    v = rh.profiles.load_portfolio_profile(info="equity")
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def buying_power() -> float:
    v = rh.profiles.load_account_profile(info="buying_power")
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def buy_dollars(ticker: str, dollars: float):
    """Market buy by dollar amount (fractional shares). Returns order dict."""
    return rh.orders.order_buy_fractional_by_price(ticker, float(dollars))


def sell_quantity(ticker: str, quantity: float):
    """Market sell of a share quantity (supports fractional)."""
    return rh.orders.order_sell_fractional_by_quantity(ticker, float(quantity))
