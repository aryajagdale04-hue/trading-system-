"""Leakage-aware forward-outcome market regime classification."""
import copy
import hashlib
import threading
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score, precision_score, recall_score

from indicators import compute_indicators
from adaptive_strategy import STRATEGY_BY_REGIME, STRATEGY_EXPLANATION

RANDOM_STATE = 42
HORIZON = 20
WALK_FORWARD_TREES = 100
REGIMES = ["Bull Trend", "Bear Trend", "Range / Sideways", "High Volatility"]
FEATURES = ["rsi_14", "macd_hist", "roc_10", "adx_14", "hist_vol_20", "vol_percentile", "bb_width_pct", "volume_vs_avg_pct", "close_vs_sma20_pct", "close_vs_sma50_pct"]
MIN_SAMPLES = 80
_WALK_FORWARD_CACHE = {}
_WALK_FORWARD_LOCKS = {}
_WALK_FORWARD_CACHE_LOCK = threading.Lock()
TARGET_DEFINITION = (
    "Market outcome over the next 20 trading bars: High Volatility when forward realized "
    "volatility exceeds the trailing historical-volatility 80th percentile; otherwise Bull "
    "Trend or Bear Trend when forward return exceeds a volatility-scaled threshold plus "
    "a 0.2% round-trip cost buffer; otherwise Range / Sideways."
)


def _features(df: pd.DataFrame, interval: str = "1d") -> pd.DataFrame:
    ind = compute_indicators(df, interval)
    ind["close_vs_sma20_pct"] = (ind["Close"] / ind["sma_20"] - 1) * 100
    ind["close_vs_sma50_pct"] = (ind["Close"] / ind["sma_50"] - 1) * 100
    return ind[FEATURES].replace([np.inf, -np.inf], np.nan).dropna()


def _dataset(df: pd.DataFrame, interval: str = "1d") -> tuple[pd.DataFrame, list[str]]:
    """Features known at close t and a target derived only for offline scoring from t+1..t+H."""
    if df is None or len(df) < MIN_SAMPLES:
        raise ValueError(f"At least {MIN_SAMPLES} bars are required for forward-outcome ML evaluation.")
    features = _features(df, interval)
    close = df["Close"].astype(float)
    daily_returns = close.pct_change()
    forward_return = close.shift(-HORIZON) / close - 1
    forward_vol = pd.Series(index=close.index, dtype=float)
    # Future window starts after t; trailing percentile is known at t.
    for pos in range(len(close) - HORIZON):
        future = daily_returns.iloc[pos + 1:pos + HORIZON + 1]
        forward_vol.iloc[pos] = future.std(ddof=1) * np.sqrt(252)
    trailing_vol = daily_returns.rolling(20).std(ddof=1) * np.sqrt(252)
    vol_cutoff = trailing_vol.expanding(min_periods=40).quantile(0.80)
    threshold = 0.5 * trailing_vol * np.sqrt(HORIZON / 252)
    target = pd.Series(index=close.index, dtype=object, name="target")
    valid_future = forward_return.notna() & forward_vol.notna() & vol_cutoff.notna() & threshold.notna()
    high_vol = valid_future & (forward_vol > vol_cutoff)
    target.loc[high_vol] = "High Volatility"
    bull = valid_future & ~high_vol & (forward_return > threshold + 0.002)
    bear = valid_future & ~high_vol & (forward_return < -threshold - 0.002)
    sideways = valid_future & ~high_vol & ~bull & ~bear
    target.loc[bull] = "Bull Trend"
    target.loc[bear] = "Bear Trend"
    target.loc[sideways] = "Range / Sideways"
    data = features.join(target.reindex(features.index)).dropna(subset=["target"])
    if len(data) < MIN_SAMPLES:
        raise ValueError("Insufficient valid labeled history after indicator warm-up and 20-bar outcome horizon.")
    present = [r for r in REGIMES if r in set(data.target)]
    if len(present) < 2:
        raise ValueError("At least two forward-outcome regimes must be present; request longer or more varied history.")
    return data, present


def _make_model(kind="forest", max_depth=8, n_estimators=300):
    if kind == "boosting":
        return HistGradientBoostingClassifier(max_iter=120, max_leaf_nodes=15, l2_regularization=1.0, random_state=RANDOM_STATE)
    return RandomForestClassifier(n_estimators=n_estimators, max_depth=max_depth, min_samples_leaf=3,
                                  class_weight="balanced_subsample", random_state=RANDOM_STATE, n_jobs=-1)


def _fit(train: pd.DataFrame, kind="forest", depth=8, n_estimators=300):
    if train.target.nunique() < 2:
        raise ValueError("Training window contains fewer than two forward-outcome regimes; use longer history.")
    return _make_model(kind, depth, n_estimators).fit(train[FEATURES], train.target)


def _metrics(actual, predicted, labels):
    report = classification_report(actual, predicted, labels=labels, output_dict=True, zero_division=0)
    return {
        "accuracy": round(float(accuracy_score(actual, predicted)), 4),
        "precision_macro": round(float(precision_score(actual, predicted, labels=labels, average="macro", zero_division=0)), 4),
        "recall_macro": round(float(recall_score(actual, predicted, labels=labels, average="macro", zero_division=0)), 4),
        "f1_macro": round(float(f1_score(actual, predicted, labels=labels, average="macro", zero_division=0)), 4),
        "per_class": {label: {metric: round(float(report[label][metric]), 4) for metric in ("precision", "recall", "f1-score", "support")} for label in labels},
        "confusion_matrix": {"labels": labels, "matrix": confusion_matrix(actual, predicted, labels=labels).tolist()},
    }


def evaluate_regime_model(df: pd.DataFrame, interval: str = "1d") -> dict:
    """Purged chronological model selection followed by an untouched later test segment."""
    data, labels = _dataset(df, interval)
    n = len(data)
    train_end, val_end = int(n * .60), int(n * .80)
    if train_end <= HORIZON + 20 or val_end - train_end < 10 or n - val_end < 5:
        raise ValueError("Not enough labeled rows for purged chronological train/validation/test splits.")
    train_pool = data.iloc[:train_end - HORIZON]
    candidates = [("forest", 4), ("forest", 8), ("boosting", None)]
    scored = []
    for kind, depth in candidates:
        model = _fit(train_pool, kind, depth)
        scored.append((f1_score(data.target.iloc[train_end:val_end], model.predict(data[FEATURES].iloc[train_end:val_end]), labels=labels, average="macro", zero_division=0), kind, depth))
    score, selected_kind, selected_depth = max(scored, key=lambda x: x[0])
    # Purge the last horizon of validation labels before evaluating the test set.
    model = _fit(data.iloc[:val_end - HORIZON], selected_kind, selected_depth)
    y_test = data.target.iloc[val_end:]
    p_test = model.predict(data[FEATURES].iloc[val_end:])
    return {
        "split": {"method": "chronological with 20-row purge/embargo at boundaries", "train_rows": train_end,
                  "validation_rows": val_end - train_end, "test_rows": n - val_end,
                  "first_date": str(data.index[0]), "train_end": str(data.index[train_end - 1]),
                  "validation_end": str(data.index[val_end - 1]), "test_start": str(data.index[val_end]), "test_end": str(data.index[-1])},
        "target_definition": TARGET_DEFINITION, "target_horizon_rows": HORIZON,
        "metrics": _metrics(y_test, p_test, labels), "validation_macro_f1": round(float(score), 4),
        "selected_model": "HistGradientBoosting" if selected_kind == "boosting" else "Random Forest",
        "selected_max_depth": selected_depth, "features": FEATURES,
        "feature_importance": ([{"feature": f, "importance": round(float(v), 6)} for f, v in sorted(zip(FEATURES, model.feature_importances_), key=lambda x: x[1], reverse=True)] if hasattr(model, "feature_importances_") else []),
    }


def _walk_forward_uncached(df: pd.DataFrame, interval: str = "1d", initial_train_fraction: float = .60, refit_every: int = 21):
    """Train on matured outcome labels only, and predict forward-outcome regime at each block origin."""
    if not 0 < initial_train_fraction < 1:
        raise ValueError("initial_train_fraction must be greater than 0 and less than 1.")
    if isinstance(refit_every, bool) or not isinstance(refit_every, int) or refit_every < 1:
        raise ValueError("refit_every must be a positive integer.")
    data, labels = _dataset(df, interval)
    feature_rows = _features(df, interval)
    n = len(data)
    first = int(n * initial_train_fraction)
    blocks = []
    for start in range(first, len(feature_rows), refit_every):
        # A label at t is usable only after its entire future horizon has elapsed.
        # Use the feature row HORIZON observations before the origin as cutoff,
        # so every training label's outcome window has fully elapsed.
        cutoff = feature_rows.index[start - HORIZON]
        eligible = data.loc[data.index <= cutoff]
        if eligible.target.nunique() < 2:
            continue
        end = min(start + refit_every, len(feature_rows))
        block = feature_rows.iloc[start:end]
        # Walk-forward backtests refit many times. A 100-tree forest retains
        # the same features, labels and chronology while cutting fit work to
        # roughly one third of the full 300-tree model used for the latest
        # forecast and formal evaluation.
        model = _fit(eligible, n_estimators=WALK_FORWARD_TREES)
        predicted = model.predict(block[FEATURES])
        probs = model.predict_proba(block[FEATURES])
        # Realized future outcome is included only for later offline evaluation, never training at prediction time.
        actual = data.target.reindex(block.index)
        result = pd.DataFrame({"predicted_regime": predicted, "realized_outcome_regime": actual,
                               "top_class_probability": probs.max(axis=1), "trained_through": str(eligible.index[-1])}, index=block.index)
        blocks.append(result)
    if not blocks:
        raise ValueError("Not enough matured multi-regime labels to produce walk-forward predictions.")
    predictions = pd.concat(blocks).sort_index()
    scored = predictions.dropna(subset=["realized_outcome_regime"])
    metadata = {"method": "expanding walk-forward; 20-row outcome purge; refit by prediction block",
                "initial_train_fraction": initial_train_fraction, "refit_every_rows": refit_every,
                "target_horizon_rows": HORIZON, "target_definition": TARGET_DEFINITION,
                "first_training_end": str(predictions.trained_through.iloc[0]),
                "first_prediction_date": str(predictions.index[0]), "last_prediction_date": str(predictions.index[-1]),
                "prediction_rows": len(predictions), "metrics": _metrics(scored.realized_outcome_regime, scored.predicted_regime, labels) if len(scored) else None}
    return predictions, metadata


def _walk_forward_key(df: pd.DataFrame, interval: str, initial_train_fraction: float, refit_every: int):
    digest = hashlib.blake2b(pd.util.hash_pandas_object(df, index=True).values.tobytes(), digest_size=20).hexdigest()
    return (digest, interval, initial_train_fraction, refit_every)


def walk_forward_regime_predictions(df: pd.DataFrame, interval: str = "1d", initial_train_fraction: float = .60, refit_every: int = 21):
    """Share the expensive walk-forward fit across dashboard panels for identical price data."""
    key = _walk_forward_key(df, interval, initial_train_fraction, refit_every)
    with _WALK_FORWARD_CACHE_LOCK:
        cached = _WALK_FORWARD_CACHE.get(key)
        if cached is not None:
            return cached[0].copy(deep=True), copy.deepcopy(cached[1])
        lock = _WALK_FORWARD_LOCKS.setdefault(key, threading.Lock())

    with lock:
        with _WALK_FORWARD_CACHE_LOCK:
            cached = _WALK_FORWARD_CACHE.get(key)
            if cached is not None:
                return cached[0].copy(deep=True), copy.deepcopy(cached[1])
        result = _walk_forward_uncached(df, interval, initial_train_fraction, refit_every)
        predictions, metadata = result
        with _WALK_FORWARD_CACHE_LOCK:
            _WALK_FORWARD_CACHE[key] = (predictions.copy(deep=True), copy.deepcopy(metadata))
            while len(_WALK_FORWARD_CACHE) > 16:
                _WALK_FORWARD_CACHE.pop(next(iter(_WALK_FORWARD_CACHE)))
        return predictions, metadata


def predict_regime(df: pd.DataFrame, interval: str = "1d") -> dict:
    """Predict the next 20-bar outcome using only labels whose full horizon has elapsed."""
    data, _ = _dataset(df, interval)
    features = _features(df, interval)
    row = features.iloc[[-1]]
    # Need HORIZON complete observations after the end of each training label.
    # _dataset omits rows whose forward outcomes have not fully matured.
    train = data
    model = _fit(train)
    pred = str(model.predict(row)[0])
    probs = model.predict_proba(row)[0]
    probability_by_class = dict(zip(model.classes_, probs))
    probabilities = {label: round(float(probability_by_class.get(label, 0)), 4) for label in REGIMES}
    important = sorted(zip(FEATURES, model.feature_importances_), key=lambda item: item[1], reverse=True)[:5]
    return {"predicted_regime": pred, "confidence": round(float(max(probs)), 4), "class_probabilities": probabilities,
            "important_features": [{"feature": f, "importance": round(float(v), 6)} for f, v in important],
            "rule_based_regime": None, "agreement": None, "comparison": "Forward-outcome prediction",
            "selected_strategy": STRATEGY_BY_REGIME[pred],
            "strategy_explanation": STRATEGY_EXPLANATION[pred],
            "strategy_use": "This method is applied in the historical paper-trading comparison only. The app does not place orders or connect to a broker.",
            "as_of": str(features.index[-1]), "trained_through": str(train.index[-1]),
            "target_definition": TARGET_DEFINITION, "target_horizon_rows": HORIZON}
