import numpy as np
import pandas as pd

from nse_client import NSEClient
import ml_regime


def test_history_download_is_reused_and_callers_receive_independent_frames(monkeypatch):
    client = NSEClient()
    calls = []

    class FakeTicker:
        def __init__(self, symbol):
            calls.append(symbol)

        def history(self, **kwargs):
            return pd.DataFrame({"Close": [100.0, 101.0]}, index=pd.date_range("2025-01-01", periods=2))

    monkeypatch.setattr("nse_client.yf.Ticker", FakeTicker)
    first = client.get_history("RELIANCE", period="5y", interval="1d")
    first.iloc[0, 0] = -1
    second = client.get_history("RELIANCE", period="5y", interval="1d")

    assert calls == ["RELIANCE.NS"]
    assert second.iloc[0, 0] == 100.0


def test_walk_forward_fit_is_reused_for_identical_market_data(monkeypatch):
    ml_regime._WALK_FORWARD_CACHE.clear()
    ml_regime._WALK_FORWARD_LOCKS.clear()
    calls = []

    def fake_compute(df, interval, initial_train_fraction, refit_every):
        calls.append((interval, refit_every))
        return pd.DataFrame({"predicted_regime": ["Bull Trend"]}), {"prediction_rows": 1}

    monkeypatch.setattr(ml_regime, "_walk_forward_uncached", fake_compute)
    prices = pd.DataFrame({"Close": np.arange(100, dtype=float)})
    first, _ = ml_regime.walk_forward_regime_predictions(prices)
    first.iloc[0, 0] = "changed"
    second, _ = ml_regime.walk_forward_regime_predictions(prices)

    assert calls == [("1d", 21)]
    assert second.iloc[0, 0] == "Bull Trend"
