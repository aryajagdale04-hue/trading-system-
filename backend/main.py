from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator
from typing import Literal
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd
import numpy as np

# Load the backend-local key before any request reads its configuration.
load_dotenv(Path(__file__).with_name(".env"), override=False)

from nse_client import nse_client
from regime import detect_regimes, current_regime_summary
from backtest import run_backtest
from indicators import current_indicator_summary, compute_indicators
from adaptive_strategy import build_adaptive_strategy
from decision import build_decision
from signals import compute_signals
from risk import build_risk_plan
from regime_performance import regime_performance
from ml_regime import evaluate_regime_model, predict_regime, walk_forward_regime_predictions
import chat_service


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: Literal["user", "assistant"]
    content: StrictStr = Field(min_length=1, max_length=chat_service.MAX_MESSAGE_CHARS)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    messages: list[ChatMessage] = Field(min_length=1, max_length=chat_service.MAX_INCOMING_MESSAGES)
    symbol: StrictStr | None = Field(default=None, max_length=24)
    interval: Literal["1m", "2m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"] | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_and_validate_symbol(cls, value):
        if value is None:
            return None
        normalized = value.strip().upper()
        if not chat_service.SYMBOL_PATTERN.fullmatch(normalized):
            raise ValueError("Stock symbol is not valid.")
        return normalized

    @model_validator(mode="after")
    def validate_conversation(self):
        if self.messages[-1].role != "user":
            raise ValueError("The latest chat message must be from you.")
        if sum(len(message.content) for message in self.messages) > chat_service.MAX_TOTAL_CHARS:
            raise ValueError(f"Chat history must be no longer than {chat_service.MAX_TOTAL_CHARS} characters.")
        if self.interval is not None and self.symbol is None:
            raise ValueError("Choose a stock before sending a chart timeframe.")
        return self


def _clean_records(df: pd.DataFrame) -> list:
    """Convert a DataFrame to JSON-safe records: NaN/inf (from rolling-window
    warm-up periods) become None instead of crashing json.dumps."""
    return df.replace({np.nan: None, np.inf: None, -np.inf: None}).to_dict(orient="records")

def _analysis_period(period: str, interval: str) -> str:
    """Daily bars need >= 2y so SMA200 / 52-week fields are filled. Other
    timeframes use exactly the period the chart asked for (yfinance limits
    intraday history, so asking for more would just fail)."""
    if interval == "1d" and period not in ("2y", "5y", "10y", "max"):
        return "2y"
    return period


app = FastAPI(title="NSE/BSE Regime Detection Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/indices")
def get_indices():
    """Top ticker strip: NIFTY 50 / SENSEX / BANK NIFTY."""
    return {"indices": nse_client.get_index_quotes()}


@app.post("/api/chat")
def post_chat(payload: ChatRequest, request: Request):
    try:
        return chat_service.answer_chat(
            payload.model_dump(), request.client.host if request.client else "unknown"
        )
    except chat_service.ChatServiceError as exc:
        raise HTTPException(exc.status_code, detail=exc.detail, headers=exc.headers)


@app.get("/api/symbols")
def list_symbols(q: str = Query("", description="Optional search filter")):
    symbols = nse_client.get_all_symbols()
    if q:
        q_lower = q.lower()
        symbols = [
            s for s in symbols
            if q_lower in s["symbol"].lower() or q_lower in s["name"].lower()
        ][:50]
    else:
        symbols = symbols[:50]
    return {"count": len(symbols), "results": symbols}


@app.get("/api/quote/{symbol}")
def get_quote(symbol: str):
    data = nse_client.get_quote(symbol)
    if data.get("error"):
        raise HTTPException(status_code=502, detail=data["error"])
    return data


@app.get("/api/history/{symbol}")
def get_history(symbol: str, period: str = "1y", interval: str = "1d"):
    df = nse_client.get_history(symbol, period=period, interval=interval)
    if df.empty:
        raise HTTPException(status_code=404, detail="No historical data found for symbol")
    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else df.columns[0]
    df[date_col] = df[date_col].astype(str)
    return _clean_records(
        df[[date_col, "Open", "High", "Low", "Close", "Volume"]].rename(columns={date_col: "date"})
    )


@app.get("/api/regime/{symbol}")
def get_regime(symbol: str, period: str = "1y", interval: str = "1d"):
    df = nse_client.get_history(symbol, period=period, interval=interval)
    if df.empty:
        raise HTTPException(status_code=404, detail="No historical data found for symbol")
    try:
        summary = current_regime_summary(df, interval)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    summary["symbol"] = symbol.upper()
    return summary


@app.get("/api/ml-regime/{symbol}")
def get_ml_regime(symbol: str, period: str = "5y", interval: str = "1d"):
    """Latest Random Forest prediction and the strategy target it selects."""
    df = nse_client.get_history(symbol, period=period, interval=interval)
    if df.empty:
        raise HTTPException(status_code=404, detail="No historical data found for symbol")
    try:
        result = predict_regime(df, interval)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    result["symbol"] = symbol.upper()
    return result


@app.get("/api/ml-regime-history/{symbol}")
def get_ml_regime_history(symbol: str, period: str = "5y", interval: str = "1d"):
    """Causal walk-forward ML regimes, exposed separately from rule history."""
    df = nse_client.get_history(symbol, period=period, interval=interval)
    if df.empty:
        raise HTTPException(status_code=404, detail="No historical data found for symbol")
    try:
        predictions, evaluation = walk_forward_regime_predictions(df, interval)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    indicators = compute_indicators(df, interval)
    predicted_regimes = pd.Series(index=indicators.index, dtype=object)
    predicted_regimes.loc[predictions.index] = predictions["predicted_regime"].astype(str)
    switched = build_adaptive_strategy(indicators, predicted_regimes).loc[predictions.index]
    history = pd.DataFrame({
        "date": [str(value) for value in predictions.index],
        "predicted_regime": predictions["predicted_regime"].astype(str).values,
        "realized_outcome_regime": predictions["realized_outcome_regime"].values,
        "selected_strategy": switched["selected_strategy"].values,
        "simulated_allocation_pct": (switched["position"] * 100).round().values,
        "simulated_action": switched["action"].values,
        "trained_through": predictions["trained_through"].values,
    })
    return {
        "symbol": symbol.upper(),
        "history": _clean_records(history),
        "evaluation": evaluation,
    }


@app.get("/api/ml-evaluation/{symbol}")
def get_ml_evaluation(symbol: str, period: str = "5y", interval: str = "1d"):
    """Chronological holdout metrics and feature importance for this symbol."""
    df = nse_client.get_history(symbol, period=period, interval=interval)
    if df.empty:
        raise HTTPException(status_code=404, detail="No historical data found for symbol")
    try:
        result = evaluate_regime_model(df, interval)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    result["symbol"] = symbol.upper()
    return result


@app.get("/api/regime-history/{symbol}")
def get_regime_history(symbol: str, period: str = "1y", interval: str = "1d"):
    """Full regime timeline, used to shade the chart by regime."""
    df = nse_client.get_history(symbol, period=period, interval=interval)
    if df.empty:
        raise HTTPException(status_code=404, detail="No historical data found for symbol")
    analyzed = detect_regimes(df, interval=interval)
    # Stateful BUY/REDUCE/EXIT events; sideways regimes deliberately emit none.
    analyzed["signal"] = compute_signals(df, interval)
    analyzed = analyzed.reset_index()
    date_col = "Date" if "Date" in analyzed.columns else analyzed.columns[0]
    analyzed[date_col] = analyzed[date_col].astype(str)
    cols = [date_col, "Open", "High", "Low", "Close", "regime", "strategy", "selected_strategy", "exposure_pct", "trade_action", "reason", "slope_pct", "volatility", "signal"]
    return _clean_records(analyzed[cols].rename(columns={date_col: "date"}))


@app.get("/api/indicators/{symbol}")
def get_indicators(symbol: str, period: str = "1y", interval: str = "1d"):
    """
    Latest-row technical indicator snapshot (trend / momentum / volatility /
    market structure), grouped for the Indicators panel. Uses a longer
    lookback than the requested period internally when needed so that
    slow-moving indicators (SMA200, 52-week high/low) aren't all-None just
    because the chart's own period is shorter than a year.
    """
    fetch_period = _analysis_period(period, interval)
    df = nse_client.get_history(symbol, period=fetch_period, interval=interval)
    if df.empty:
        raise HTTPException(status_code=404, detail="No historical data found for symbol")
    try:
        summary = current_indicator_summary(df, interval)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    summary["symbol"] = symbol.upper()
    return summary


@app.get("/api/decision/{symbol}")
def get_decision(symbol: str, period: str = "1y", interval: str = "1d"):
    """
    The AI Decision card's data: a BUY/HOLD/REDUCE/EXIT call, a component-based
    confidence score, recommended exposure, risk level, and the plain-language
    reasons behind it. See decision.py for the full methodology.
    """
    fetch_period = _analysis_period(period, interval)
    df = nse_client.get_history(symbol, period=fetch_period, interval=interval)
    if df.empty:
        raise HTTPException(status_code=404, detail="No historical data found for symbol")
    try:
        result = build_decision(df, interval)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    result["symbol"] = symbol.upper()
    return result


@app.get("/api/risk/{symbol}")
def get_risk(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    portfolio_value: float = 100000.0,
    risk_pct: float = 1.0,
    atr_multiplier: float = 2.0,
    reward_multiple: float = 2.0,
):
    """
    Risk Management card: ATR-based stop-loss/take-profit and a fixed-
    fractional position size for a hypothetical new long entry, capped by
    the AI Decision's regime-based exposure limit. See risk.py.
    """
    fetch_period = _analysis_period(period, interval)
    df = nse_client.get_history(symbol, period=fetch_period, interval=interval)
    if df.empty:
        raise HTTPException(status_code=404, detail="No historical data found for symbol")
    try:
        result = build_risk_plan(df, interval, portfolio_value, risk_pct, atr_multiplier, reward_multiple)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    result["symbol"] = symbol.upper()
    return result


@app.get("/api/regime-performance/{symbol}")
def get_regime_performance(symbol: str, period: str = "5y"):
    """
    Performance-by-regime breakdown (always daily bars, like the backtest,
    since this needs years of history to say anything meaningful about any
    one regime). See regime_performance.py.
    """
    df = nse_client.get_history(symbol, period=period, interval="1d")
    if df.empty:
        raise HTTPException(status_code=404, detail="No historical data found for symbol")
    try:
        result = regime_performance(df, interval="1d")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    result["symbol"] = symbol.upper()
    return result


# Serve the frontend
app.mount("/static", StaticFiles(directory="../frontend"), name="static")


@app.get("/api/backtest/{symbol}")
def get_backtest(symbol: str, period: str = "1y"):
    """
    Simulates the ML adaptive strategy, rule-adaptive baseline, fixed strategies
    and optional NIFTY benchmark over aligned dates. ML walk-forward predictions
    use earlier observations and positions are lagged one bar. See backtest.py.
    """
    df = nse_client.get_history(symbol, period=period, interval="1d")
    if df.empty:
        raise HTTPException(status_code=404, detail="No historical data found for symbol")
    try:
        benchmark = nse_client.get_history("^NSEI", period=period, interval="1d")
        result = run_backtest(df, benchmark_df=benchmark)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    result["symbol"] = symbol.upper()
    if result.get("benchmark") is None:
        result["benchmark_note"] = "NIFTY 50 benchmark data was unavailable for this period."
    return result


@app.get("/")
def root():
    return FileResponse("../frontend/index.html")
