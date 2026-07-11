"""Market-data fetch. Uses yfinance (free, no API key)."""
from __future__ import annotations

import pandas as pd
import yfinance as yf

import config


def fetch_history(ticker: str):
    """Return a daily OHLCV DataFrame for `ticker`, or None on failure."""
    try:
        df = yf.download(
            ticker,
            period=f"{config.LOOKBACK_DAYS + 40}d",
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
        if df is None or df.empty:
            return None
        # yfinance sometimes returns multi-index columns for a single ticker
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df.dropna()
    except Exception as e:  # one bad ticker shouldn't stop the whole run
        print(f"[data] failed to fetch {ticker}: {e}")
        return None
