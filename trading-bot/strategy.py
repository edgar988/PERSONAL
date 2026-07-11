"""
Transparent swing-trading signal logic. Nothing here is a black box:

  * Trend filter  -- is price above its 50-day average? (only buy uptrends)
  * Entry trigger -- 20-day avg crossing above 50-day (fresh momentum), OR
                     RSI climbing back out of oversold (a bounce)
  * Caution       -- RSI above 70 (stretched / take-profit zone)
  * ATR           -- average daily range %, used for position sizing
  * Volume ratio  -- today's volume vs 20-day average (institutional radar)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

import config


@dataclass
class Signal:
    ticker: str
    price: float
    prev_close: float
    sma_fast: float
    sma_slow: float
    rsi: float
    verdict: str        # "BUY_WATCH" | "OVERBOUGHT" | "NEUTRAL"
    reasons: list = field(default_factory=list)
    atr_pct: float = 0.0    # avg daily true range as % of price
    vol_ratio: float = 0.0  # today's volume / 20-day avg volume

    @property
    def day_change_pct(self) -> float:
        if self.prev_close <= 0:
            return 0.0
        return (self.price - self.prev_close) / self.prev_close * 100.0


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, 1e-9)
    return 100.0 - 100.0 / (1.0 + rs)


def _atr_pct(df, price: float) -> float:
    """Average True Range over ATR_PERIOD days, as % of current price."""
    try:
        high, low, close = df["High"], df["Low"], df["Close"]
        prev_close = close.shift(1)
        tr = pd.concat([high - low,
                        (high - prev_close).abs(),
                        (low - prev_close).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(config.ATR_PERIOD).mean().iloc[-1])
        return (atr / price * 100.0) if price > 0 else 0.0
    except (KeyError, TypeError, ValueError, IndexError):
        return 0.0


def _vol_ratio(df) -> float:
    """Today's volume vs its trailing 20-day average."""
    try:
        vol = df["Volume"].dropna()
        if len(vol) < 22:
            return 0.0
        avg = float(vol.iloc[-21:-1].mean())
        return float(vol.iloc[-1]) / avg if avg > 0 else 0.0
    except (KeyError, TypeError, ValueError):
        return 0.0


def evaluate(ticker: str, df):
    if df is None or len(df) < config.SLOW_SMA + 5:
        return None
    close = df["Close"]
    sma_fast = close.rolling(config.FAST_SMA).mean()
    sma_slow = close.rolling(config.SLOW_SMA).mean()
    rsi = _rsi(close, config.RSI_PERIOD)

    price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])
    f = float(sma_fast.iloc[-1])
    s = float(sma_slow.iloc[-1])
    r = float(rsi.iloc[-1])

    reasons = []

    trend_up = price > s
    reasons.append(
        f"Price ${price:.2f} is {'above' if trend_up else 'below'} "
        f"the {config.SLOW_SMA}-day avg ${s:.2f} "
        f"({'uptrend' if trend_up else 'downtrend'})"
    )

    fresh_cross = False
    for i in range(1, config.CROSS_RECENT_DAYS + 1):
        if (
            float(sma_fast.iloc[-i]) > float(sma_slow.iloc[-i])
            and float(sma_fast.iloc[-i - 1]) <= float(sma_slow.iloc[-i - 1])
        ):
            fresh_cross = True
            break
    if fresh_cross:
        reasons.append(
            f"{config.FAST_SMA}-day avg just crossed ABOVE the "
            f"{config.SLOW_SMA}-day avg (fresh momentum)"
        )

    rsi_recovering = (
        r > config.RSI_OVERSOLD and float(rsi.iloc[-2]) <= config.RSI_OVERSOLD
    )
    if rsi_recovering:
        reasons.append(
            f"RSI just recovered above {config.RSI_OVERSOLD} "
            f"(bounce off oversold), now {r:.0f}"
        )

    reasons.append(f"RSI is {r:.0f}")

    if r >= config.RSI_OVERBOUGHT:
        verdict = "OVERBOUGHT"
        reasons.append(
            f"RSI >= {config.RSI_OVERBOUGHT}: stretched -- take-profit / don't chase"
        )
    elif trend_up and (fresh_cross or rsi_recovering):
        verdict = "BUY_WATCH"
    else:
        verdict = "NEUTRAL"

    return Signal(ticker, price, prev_close, f, s, r, verdict, reasons,
                  atr_pct=_atr_pct(df, price), vol_ratio=_vol_ratio(df))
