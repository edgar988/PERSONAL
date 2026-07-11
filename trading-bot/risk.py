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
    return True, "ok"
