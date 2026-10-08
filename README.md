# Adaptive and Explainable AI Trading System

Research dashboard for NSE equities. It forecasts the likely price pattern over the next 20 trading days, then chooses a different rule set for a historical pretend-money simulation. It also displays a separate, explainable rule-based signal on the price chart. No broker or real account is connected.

## Architecture

- `backend/nse_client.py`: NSE quote and symbol-list access; Yahoo Finance historical OHLCV provider/fallback.
- `backend/indicators.py`: technical indicators calculated from data available at each date.
- `backend/regime.py`: transparent rule-based regime labels with numeric explanations.
- `backend/ml_regime.py`: Random Forest and HistGradientBoosting comparison, forward-outcome labels, chronological purged evaluation, and walk-forward forecasts.
- `backend/adaptive_strategy.py`: actually applies the method selected by each AI regime forecast.
- `backend/backtest.py`: ML-adaptive, rule-adaptive, Momentum, Mean Reversion, Buy & Hold and optional NIFTY 50 simulations.
- `backend/main.py`: FastAPI endpoints and static frontend serving.
- `frontend/`: HTML, CSS and JavaScript dashboard.

## Setup

Use Python 3.11 or 3.12.

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Open <http://localhost:8000>.

### Optional AI stock chat

Put your key after `GEMINI_API_KEY=` in the included `backend/.env`; `backend/.env.example` lists the available settings. Never put the key in frontend files or commit it. Chat uses Gemini with Google Search grounding; without a key, the rest of the dashboard still works and chat explains the setup issue.

The chat defaults to `gemini-3.5-flash-lite`, limits each answer to 800 output tokens, and times out after 45 seconds. Google Search grounding is disabled by default because it may require paid access; set `GEMINI_ENABLE_GOOGLE_SEARCH=true` only after checking billing and usage terms in AI Studio. You can adjust `GEMINI_MODEL`, `GEMINI_MAX_OUTPUT_TOKENS`, `GEMINI_TIMEOUT_SECONDS`, `CHAT_RATE_LIMIT` and `CHAT_RATE_WINDOW_SECONDS` in `backend/.env`. The default in-memory rate limit is five requests per client IP per 60 seconds; it resets when the app restarts and is intended for local/single-instance use. Before public hosting, add authentication and a shared rate limiter. Google says free-tier prompts may be used to improve its products, so avoid entering private information.

Web search results are treated as untrusted source material, never as instructions. Chat answers are shown as plain text, and clickable sources come only from structured citations returned by the API. The chat explains scenarios and evidence but does not give personalized buy/sell instructions. Stock context is fetched on the server for the selected NSE/BSE symbol and chart interval, with the context retrieval time shown in the chat. The browser does not send its own quote or indicator values.

## What the AI predicts

At the close of a trading day, the model uses indicators known by that close to predict the market's outcome over the next 20 trading days. The outcome is labeled Bull Trend, Bear Trend, Range / Sideways, or High Volatility based on the forward return and realized volatility. Thresholds come from information available at the prediction date, with a small trading-cost buffer. The labels no longer come from the rule detector.

The app compares a Random Forest with HistGradientBoosting and selects the model with the better validation macro-F1. Evaluation uses chronological sections and removes 20 rows at split boundaries so overlapping future outcome windows cannot leak into the next section. Walk-forward training uses only outcome labels that have fully matured before each forecast. The latest 20 days do not yet have complete outcome labels and are excluded from scored metrics.

The AI forecast selects a method that the adaptive historical simulator really uses:

| AI's forecast | Method used in the simulation |
|---|---|
| Rising trend | Momentum: invest only while the short-term trend and momentum agree. |
| Falling trend | Defensive: move the simulated position to cash. |
| Large price swings | Mean reversion: use a small position only after unusually weak prices. |
| Sideways prices | Wait: do not open a new position; keep the previous simulated holding unchanged. |

The app also runs the simpler momentum and mean-reversion methods separately so you can compare them with the AI-selected method. Forecast accuracy and pretend-money results are different measures. The chart's BUY/SELL markers come from the separate rule-based signal system, not the AI forecast. Model scores are rough estimates, not the chance of making money.

## Chart action markers

Chart **BUY** markers require a confirmed rising trend and supporting momentum. **SELL** markers require five confirmed falling-trend bars and a close below a falling 50-bar average. Sideways markets show no chart signals. These chart markers are rule-based guides, not orders.

## Backtest and limits

The backtest compares the AI-selected methods with simpler methods over the same dates, using pretend money. Percentages mean the share of that simulated money invested; they do not refer to a user's real account. Decisions are delayed by one bar. The simulator uses a simplified 0.10% trading cost and omits detailed taxes, liquidity, market impact and broker fees. Forecast accuracy does not guarantee trading gains; past simulations do not predict future performance. Market data may be delayed, incomplete or rate-limited. This is an educational research tool, not investment advice or live order execution.

## API

- `GET /api/symbols?q=reliance`, `/api/quote/{symbol}`, `/api/history/{symbol}?period=1y&interval=1d`
- `GET /api/regime/{symbol}` and `/api/regime-history/{symbol}` — transparent rule baseline.
- `GET /api/ml-regime/{symbol}?period=5y&interval=1d` — latest forward-outcome forecast and the method the simulator selects.
- `GET /api/ml-regime-history/{symbol}?period=5y&interval=1d` — walk-forward forecasts, selected methods, pretend allocation and realized outcomes where available.
- `GET /api/ml-evaluation/{symbol}?period=5y&interval=1d` — purged chronological holdout metrics and model comparison.
- `GET /api/backtest/{symbol}?period=5y` — ML adaptive, rule adaptive, fixed strategies and optional NIFTY 50.
- `GET /api/indicators/{symbol}`, `/api/decision/{symbol}`, `/api/risk/{symbol}`, `/api/regime-performance/{symbol}` — supporting analysis.
- `POST /api/chat` — educational stock/news chat (requires `GEMINI_API_KEY`); body accepts recent `{role, content}` messages plus an optional NSE/BSE symbol and chart interval.
