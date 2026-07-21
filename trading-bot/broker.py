"""
Thin wrapper around robin_stocks -- ALL Robinhood access goes through here.

A one-time interactive login (python rh_login.py) stores a session pickle
under ~/.tokens/. After that, headless services reuse it. When the session
expires, ensure_login() sends ONE Telegram alert (flag-file deduped) with
the fix steps instead of spamming on every systemd restart.
"""
from __future__ import annotations

import os

import robin_stocks.robinhood as rh

_PICKLE_DIR = os.path.expanduser("~/.tokens")
_FAIL_FLAG = os.path.join(os.path.dirname(__file__), "login_failed.flag")

_RELOGIN_HELP = (
    "Robinhood session expired -- one-time re-login needed.\n\n"
    "On your PC:\n"
    "1. ssh root@YOUR-SERVER-IP\n"
    "2. cd ~/personal/trading-bot\n"
    "3. systemctl stop tradingbot-approver\n"
    "4. ~/.tradingbot-venv/bin/python rh_login.py  (phone handy for approval)\n"
    "5. systemctl start tradingbot-approver\n\n"
    "I'll stay quiet and come back online automatically after that."
)


def _alert_once(text: str) -> None:
    """Send a Telegram alert only once per failure streak (flag-file gate)."""
    if os.path.exists(_FAIL_FLAG):
        return
    try:
        with open(_FAIL_FLAG, "w") as fh:
            fh.write(text[:500])
    except OSError:
        pass
    try:
        import notify
        notify.send("⚠️ " + text)
    except Exception:
        pass


def _clear_flag() -> None:
    try:
        os.remove(_FAIL_FLAG)
    except OSError:
        pass


def has_stored_session() -> bool:
    if not os.path.isdir(_PICKLE_DIR):
        return False
    return any(f.endswith(".pickle") for f in os.listdir(_PICKLE_DIR))


def ensure_login() -> None:
    """Reuse the stored session. Raises RuntimeError with a clear message if
    the session is missing or expired -- never blocks waiting for input.
    Alerts Telegram once per failure streak, not per restart."""
    if not has_stored_session():
        msg = ("No Robinhood session found. SSH to the server and run: "
               "~/.tradingbot-venv/bin/python rh_login.py")
        _alert_once(msg)
        raise RuntimeError(msg)
    try:
        rh.login(store_session=True)
    except EOFError:
        # robin_stocks tried to prompt for credentials -- the stored session
        # is expired/invalid and there's no terminal to type into.
        _alert_once(_RELOGIN_HELP)
        raise RuntimeError("Robinhood session expired -- run rh_login.py "
                           "(see the Telegram alert for steps).")
    except Exception as e:
        _alert_once(f"Robinhood login failed: {e}\n\n{_RELOGIN_HELP}")
        raise RuntimeError(f"Robinhood login failed: {e}")
    _clear_flag()


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
