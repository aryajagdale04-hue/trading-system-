"""Regime-to-method switching for the historical adaptive strategy simulation."""
import numpy as np
import pandas as pd


STRATEGY_BY_REGIME = {
    "Bull Trend": "Momentum",
    "Bear Trend": "Cash / defensive",
    "High Volatility": "Mean reversion (25% simulated allocation)",
    "Range / Sideways": "Wait / keep current simulated holding",
}

STRATEGY_EXPLANATION = {
    "Bull Trend": "Uses the momentum rules: simulated funds are invested only while the short-term average is above the long-term average and RSI is above 50.",
    "Bear Trend": "Uses the defensive rule: the simulation moves to cash until the forecast changes.",
    "High Volatility": "Uses the mean-reversion rules only when price is unusually weak, with at most 25% of pretend funds invested.",
    "Range / Sideways": "Waits without opening or changing a simulated position, to avoid choppy sideways signals. If the simulation is already holding, that holding stays unchanged.",
}


def _momentum_targets(ind: pd.DataFrame) -> pd.Series:
    return ((ind["sma_20"] > ind["sma_50"]) & (ind["rsi_14"] > 50)).astype(float)


def _mean_reversion_targets(ind: pd.DataFrame, active: pd.Series) -> pd.Series:
    close = ind["Close"].to_numpy(dtype=float)
    rsi = ind["rsi_14"].to_numpy(dtype=float)
    lower = ind["bb_lower"].to_numpy(dtype=float)
    mean = ind["sma_20"].to_numpy(dtype=float)
    active = active.reindex(ind.index).fillna(False).to_numpy(dtype=bool)
    target = np.zeros(len(ind), dtype=float)
    holding = False
    for i in range(len(ind)):
        if not active[i] or np.isnan(rsi[i]) or np.isnan(lower[i]) or np.isnan(mean[i]):
            holding = False
        elif holding:
            if close[i] >= mean[i]:
                holding = False
        elif rsi[i] < 30 or close[i] < lower[i]:
            holding = True
        target[i] = 1.0 if holding else 0.0
    return pd.Series(target, index=ind.index)


def build_adaptive_strategy(ind: pd.DataFrame, predicted_regimes: pd.Series) -> pd.DataFrame:
    """Select a different rule set by predicted regime; sideways periods hold state and stay quiet."""
    regimes = predicted_regimes.reindex(ind.index)
    momentum = _momentum_targets(ind)
    mean_reversion = _mean_reversion_targets(ind, regimes.eq("High Volatility"))
    positions, methods, actions = [], [], []
    current = 0.0
    for date in ind.index:
        regime = regimes.loc[date]
        if pd.isna(regime):
            positions.append(np.nan)
            methods.append(None)
            actions.append(None)
            continue
        previous = current
        if regime == "Bull Trend":
            current = float(momentum.loc[date])
        elif regime == "Bear Trend":
            current = 0.0
        elif regime == "High Volatility":
            current = 0.25 * float(mean_reversion.loc[date])
        # Sideways: no new trade and no change to the current simulated holding.
        if regime == "Range / Sideways":
            action = "WAIT — RANGE"
        elif current > previous:
            action = "BUY / INCREASE"
        elif current < previous:
            action = "SELL / EXIT"
        else:
            action = "HOLD"
        positions.append(current)
        methods.append(STRATEGY_BY_REGIME.get(regime, "Wait / no new trades"))
        actions.append(action)
    return pd.DataFrame({"position": positions, "selected_strategy": methods, "action": actions}, index=ind.index)
