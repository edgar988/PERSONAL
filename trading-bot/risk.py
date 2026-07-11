"""The brakes. Every buy passes through here -- twice (pre-send and at
execution time). Caps live in config.py."""
from __future__ import annotations

import config


def _pos_value(holdings: dict, ticker: str) -> float:
    try:
        return float(holdings.get(ticker, {}).get("equity", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _total_deployed(holdings: dict) -> float:
    total = 0.0
    for h in holdings.values():
        try:
            total += float(h.get("equity", 0) or 0)
        except (TypeError, ValueError):
            pass
    return total


def _theme_deployed(holdings: dict) -> float:
    total = 0.0
    for tk in config.AI_THEME_TICKERS:
        total += _pos_value(holdings, tk)
    return total


def check_buy(ticker: str, dollars: float, holdings: dict, halted: bool):
    """Returns (ok, reason)."""
    if halted:
        return False, "Trading is halted (daily loss stop or /halt). /resume to lift."
    if dollars <= 0:
        return False, "Zero/negative dollar amount."
    if dollars > config.MAX_PER_POSITION_USD:
        return False, (f"${dollars:.0f} exceeds the ${config.MAX_PER_POSITION_USD} "
                       "per-position cap.")
    held = _pos_value(holdings, ticker)
    if held + dollars > config.MAX_PER_POSITION_USD:
        return False, (f"{ticker} already ${held:.0f} held; buying ${dollars:.0f} "
                       f"more would exceed the ${config.MAX_PER_POSITION_USD} "
                       "per-position cap.")
    deployed = _total_deployed(holdings)
    if deployed + dollars > config.MAX_TOTAL_DEPLOYED_USD:
        return False, (f"${deployed:.0f} already deployed; buying ${dollars:.0f} "
                       f"more would exceed the ${config.MAX_TOTAL_DEPLOYED_USD} "
                       "total cap.")
    # Theme concentration: the AI-buildout names as a group can't exceed
    # THEME_MAX_FRACTION of the deployed cap -- one bad AI headline
    # shouldn't be able to hit the whole book.
    if ticker in config.AI_THEME_TICKERS:
        theme_cap = config.THEME_MAX_FRACTION * config.MAX_TOTAL_DEPLOYED_USD
        theme_now = _theme_deployed(holdings)
        if theme_now + dollars > theme_cap:
            return False, (f"AI-theme concentration cap: ${theme_now:.0f} of "
                           f"${theme_cap:.0f} already in AI-buildout names; "
                           f"buying ${dollars:.0f} more {ticker} would exceed it.")
    return True, "ok"
