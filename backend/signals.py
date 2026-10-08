"""Stateful, trend-aware chart actions with no entries or exits in sideways markets.

Signals are event labels, not promises: BUY opens exposure and SELL closes it
only after a confirmed broader bearish reversal. Range/sideways bars stay silent.
"""
import pandas as pd

from regime import detect_regimes
from indicators import compute_indicators

BUY_CONFIRM_BARS = 3
EXIT_CONFIRM_BARS = 5
ADX_MIN = 20
FULL_EXPOSURE = 1.0


def _held(regimes: pd.Series, name: str, bars: int) -> pd.Series:
    return (regimes == name).rolling(bars, min_periods=bars).sum() == bars


def compute_signals(df: pd.DataFrame, interval="1d") -> pd.Series:
    """Return BUY / SELL events; emit nothing for Range / Sideways bars."""
    ind = compute_indicators(df, interval)
    regimes = detect_regimes(df, interval=interval)["regime"]
    adx_ok = ind["adx_14"] >= ADX_MIN

    # Buy only when shorter-term momentum and the broader 50-bar trend agree.
    long_trend_up = (ind["Close"] > ind["sma_50"]) & (ind["sma_50"] > ind["sma_50"].shift(5))
    buy_ok = (
        _held(regimes, "Bull Trend", BUY_CONFIRM_BARS)
        & adx_ok
        & long_trend_up
        & (ind["macd_hist"] > 0)
        & (ind["rsi_14"] > 50)
    )

    # An exit needs five confirmed Bear bars, meaningful directional strength,
    # and a close below a falling SMA50. A brief pullback alone cannot exit.
    long_trend_broken = (ind["Close"] < ind["sma_50"]) & (ind["sma_50"] < ind["sma_50"].shift(5))
    exit_ok = _held(regimes, "Bear Trend", EXIT_CONFIRM_BARS) & adx_ok & long_trend_broken
    out = []
    exposure = 0.0
    for regime, can_buy, can_exit in zip(regimes, buy_ok, exit_ok):
        # Range/sideways is deliberately silent; keep the prior position state.
        if regime == "Range / Sideways" or pd.isna(regime):
            out.append(None)
            continue
        if can_exit and exposure > 0:
            out.append("SELL")
            exposure = 0.0
        elif can_buy and exposure < FULL_EXPOSURE:
            out.append("BUY")
            exposure = FULL_EXPOSURE
        else:
            out.append(None)
    return pd.Series(out, index=df.index, dtype=object)
