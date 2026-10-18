# Adaptive and Explainable AI Trading System — Backend

## Overview

FastAPI backend for a research dashboard that forecasts the market pattern over the next 20 trading days and applies a different trading rule set in a pretend-money historical simulation. It does not connect to a broker.

## Main modules

- `nse_client.py`: NSE quotes and symbol lookup; Yahoo Finance historical OHLCV data.
- `indicators.py`: indicator calculations.
- `regime.py`: readable rule-based regime baseline.
- `ml_regime.py`: forward outcome labeling, Random Forest / HistGradientBoosting model selection, purged chronological evaluation, and walk-forward forecasts.
- `adaptive_strategy.py`: maps the AI forecast to and runs the selected historical strategy rules.
- `backtest.py`: lagged long-only comparison of ML adaptive, rule adaptive, Momentum, Mean Reversion and Buy & Hold.
- `main.py`: API routes and static frontend hosting.

## Model and evaluation

For each date, features use information through that day's close. The target describes the next 20 trading bars: high volatility is assigned when forward realized volatility exceeds the trailing historical-volatility 80th percentile; otherwise a sufficiently large volatility-scaled forward move becomes Bull or Bear, and smaller moves become sideways. A 0.2% cost buffer is included for directional labels.

The model comparison selects between Random Forest depths and HistGradientBoosting using validation macro-F1, then reports a later chronological test segment. Twenty rows are purged at split boundaries because neighboring 20-day outcomes overlap. Walk-forward forecasts train only on labels whose full outcome window ended before the forecast date. To keep the five-year interactive simulation responsive, its repeated walk-forward fits use 100 trees; the latest forecast and formal model evaluation continue to use 300 trees. Accuracy/F1 describe forward outcome classification. They are distinct from the backtest's simulated returns. Maximum class probabilities are uncalibrated, and Random Forest feature importance is global, not a per-row explanation.

The rule-based regime detector is preserved as a separate, interpretable chart signal. In the adaptive backtest, Bull uses the momentum rules; Bear moves the pretend position to cash; High Volatility uses mean reversion at no more than 25% of simulated funds; Sideways waits, opens no new position and keeps the prior simulated holding unchanged. The other strategies in the backtest are run separately for comparison. All results use pretend funds, are delayed one bar, and apply simplified turnover costs. They do not model live execution or promise future gains.

## Chart action markers

The chart uses backend-generated rule signals, separate from AI strategy selection. **BUY** requires three Bull Trend bars, ADX at least 20, a close above a rising SMA50, positive MACD histogram and RSI above 50. **SELL** requires five Bear Trend bars, ADX at least 20, and a close below a falling SMA50. Range / Sideways bars intentionally produce no chart signal.

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Open <http://localhost:8000>.

For Gemini chat, add `GEMINI_API_KEY` to `backend/.env`. The default model is `gemini-3.5-flash-lite`, which Google recommends for new projects; model availability still depends on the key's project and quota. Live Google Search grounding is off by default to avoid enabling a potentially billable feature. Set `GEMINI_ENABLE_GOOGLE_SEARCH=true` only after checking your Google AI Studio billing and usage terms. Without live search, the chat must not claim that it verified current news; paste a headline or article for explanation. Google says free-tier prompts may be used to improve its products, so avoid entering private information. The example env file documents output limit, timeout and rate-limit settings.

## API routes

- `/api/regime/{symbol}` and `/api/regime-history/{symbol}` — readable rule baseline and timeline.
- `/api/ml-regime/{symbol}` — latest 20-trading-day outcome forecast and selected simulation method.
- `/api/ml-regime-history/{symbol}` — walk-forward forecasts, methods actually run, simulated allocation and realized outcomes when available.
- `/api/ml-evaluation/{symbol}` — purged chronological forward-outcome test metrics.
- `/api/backtest/{symbol}?period=5y` — ML adaptive, rule adaptive, fixed strategies and optional NIFTY 50 benchmark.
- `/api/indicators/{symbol}`, `/api/decision/{symbol}`, `/api/risk/{symbol}`, `/api/regime-performance/{symbol}` — supporting analysis.

Historical data and live NSE quotes may be delayed, incomplete or rate-limited. This is an educational research dashboard, not investment advice or broker order execution.
