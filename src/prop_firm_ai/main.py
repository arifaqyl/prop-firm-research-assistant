from __future__ import annotations

import os
from pathlib import Path
import asyncio
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from types import MappingProxyType
import requests


try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ModuleNotFoundError as exc:  # pragma: no cover
    raise RuntimeError("Install project dependencies with `pip install -e .` before running the API.") from exc

from .backtest import run_paper_simulation, run_watchlist_simulation
from .community import Market, SignalMessageType, build_operation_signal, score_signal_quality
from .dashboard import build_dashboard_payload, build_demo_dashboard_payload
from .domain import ExecutionMode, OrderSide, OrderType
from .fundamentals import sec_recent_filings
from .hybrid_gate import evaluate_hybrid_decision
from .macro import macro_context, multi_timeframe_context, options_gex_context, tavily_rag_veto
from .market_data import build_signal_from_snapshot, fallback_signal, fetch_market_snapshot
from .micro import dual_websocket_probe, latency_gap_scan, microstructure_probe, polymarket_market_search
from .open_source import open_source_strategy_catalog
from .statarb import scan_default_pairs, scan_pair
from .system import TradingSystem, demo_signal
from .telegram import format_telegram_digest


def _load_local_env() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value


_load_local_env()
app = FastAPI(title="Prop Firm AI Trading System", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
system = TradingSystem()
APP_DIR = Path(__file__).resolve().parents[2] / "app"
if APP_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(APP_DIR), html=True), name="app")


@app.get("/")
def root() -> RedirectResponse:
    if not APP_DIR.exists():
        raise HTTPException(status_code=404, detail="static app not found")
    return RedirectResponse("/app/")


class PaperOrderPayload(BaseModel):
    symbol: str = Field(default="AAPL")
    side: OrderSide = Field(default=OrderSide.BUY)
    entry_price: float = Field(default=190.0, gt=0)
    stop_price: float = Field(default=184.0, gt=0)
    order_type: OrderType = Field(default=OrderType.LIMIT)
    stale_demo_data: bool = False


class RealtimeSignalPayload(BaseModel):
    symbol: str
    side: OrderSide
    price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    content: str = ""
    market: Market = Field(default=Market.US_STOCK)


@app.get("/api/data-health")
def data_health() -> dict:
    signal = demo_signal()
    return {
        "symbol": signal.symbol,
        "source": signal.data_health.source,
        "age_hours": signal.data_health.age_hours,
        "stale": signal.data_health.is_stale,
        "warnings": signal.data_health.warnings,
        "free_mode": os.getenv("FREE_MODE", "true").lower() in {"1", "true", "yes"},
    }


@app.get("/api/ollama/health")
def ollama_health() -> dict:
    url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
    if not url:
        return {"running": False, "configured": False, "reason": "OLLAMA_BASE_URL is not configured", "url": ""}
    try:
        response = requests.get(url.rstrip("/") + "/", timeout=2)
        if response.status_code == 200:
            model = os.getenv("OLLAMA_CATALYST_MODEL", "qwen2.5:3b")
            tags_resp = requests.get(url.rstrip("/") + "/api/tags", timeout=2)
            models = [m.get("name") for m in tags_resp.json().get("models", [])] if tags_resp.status_code == 200 else []
            model_loaded = model in models or any(m.startswith(model) for m in models)
            return {
                "running": True,
                "model_configured": model,
                "model_available": model_loaded,
                "all_models": models,
                "url": url
            }
    except Exception as exc:
        return {"running": False, "error": str(exc), "url": url}
    return {"running": False, "url": url}



@app.get("/api/market-intel/overview")
def market_intel_overview() -> dict:
    return _serialize({"market_intel": system.market_intel, "warnings": system.market_intel.warnings()})


@app.post("/api/subagents/analyze")
def subagents_analyze(stale_demo_data: bool = False) -> dict:
    return _serialize(system.run_subagent_analysis(demo_signal(stale=stale_demo_data)))


@app.get("/api/dashboard/demo")
def dashboard_demo() -> dict:
    return _serialize(build_demo_dashboard_payload())


@app.get("/api/analyze/{symbol}")
def analyze_symbol(symbol: str) -> dict:
    live = _live_signal(symbol)
    signal = live["signal"]
    return {
        "symbol": signal.symbol,
        "runtime": live["runtime"],
        "signal": {
            "symbol": signal.symbol,
            "asset_type": signal.asset_type,
            "direction_call": signal.direction_call.value,
            "confidence": signal.confidence.value,
            "primary_horizon": signal.primary_horizon,
            "probabilities": signal.probabilities,
            "sample_size": signal.sample_size,
            "brier_skill_score": signal.brier_skill_score,
            "regime": signal.regime,
            "latest_price": signal.latest_price,
            "atr": signal.atr,
            "average_daily_volume": signal.average_daily_volume,
            "spread_bps": signal.spread_bps,
            "expected_edge": signal.expected_edge,
            "model_version": signal.model_version,
            "prompt_version": signal.prompt_version,
            "earnings_proximity_flag": signal.earnings_proximity_flag,
            "data_health": {
                "source": signal.data_health.source,
                "age_hours": round(signal.data_health.age_hours, 4),
                "stale": signal.data_health.is_stale,
                "warnings": signal.data_health.warnings,
                "checked_at": signal.data_health.checked_at.isoformat(),
                "latest_candle_at": signal.data_health.latest_candle_at.isoformat(),
            },
            "rsi": signal.rsi,
            "macd": signal.macd,
            "adx": signal.adx,
            "bollinger": signal.bollinger,
        },
    }


@app.get("/api/dashboard/live")
def dashboard_live(symbol: str = "AAPL") -> dict:
    live = _live_signal(symbol)
    return _serialize(build_dashboard_payload(live["signal"], runtime=live["runtime"], snapshot=live.get("snapshot")))


@app.get("/api/scan")
def scan(symbols: str = "AAPL,NVDA,BTC-USD,ETH-USD") -> dict:
    requested = [item.strip().upper() for item in symbols.split(",") if item.strip()][:8]
    cards = []
    for symbol in requested:
        live = _live_signal(symbol)
        payload = build_dashboard_payload(live["signal"], runtime=live["runtime"], snapshot=live.get("snapshot"))
        rank_score = _rank_score(payload)
        cards.append(
            {
                "symbol": payload["symbol"],
                "asset_type": payload["asset_type"],
                "latest_price": payload["latest_price"],
                "trade_call": payload["trade_call"],
                "rank_score": rank_score,
                "attention_tier": _attention_tier(payload, rank_score),
                "probabilities": payload["probabilities"],
                "data_health": payload["data_health"],
                "features": payload["features"],
                "runtime": payload["runtime"],
            }
        )
    cards.sort(key=lambda item: item["rank_score"], reverse=True)
    return _serialize({"symbols": requested, "cards": cards, "regime_summary": _regime_summary(cards)})


@app.get("/api/paper/simulate")
def paper_simulate(
    symbols: str = "AAPL,NVDA,BTC-USD,ETH-USD",
    range_: str = "5y",
    horizon: int = 15,
    lookback: int = 80,
    max_trades: int = 5000,
    direction: str | None = None,
    regime: str | None = None,
    exclude_crypto: bool = False,
) -> dict:
    requested = [item.strip().upper() for item in symbols.split(",") if item.strip()][:8]
    return _serialize(
        run_watchlist_simulation(
            requested,
            range_=range_,
            horizon=horizon,
            lookback=lookback,
            max_trades=min(max(max_trades, 50), 20000),
            direction_filter=direction,
            regime_filter=regime,
            exclude_crypto=exclude_crypto,
        )
    )


@app.get("/api/paper/simulate/{symbol}")
def paper_simulate_symbol(
    symbol: str,
    range_: str = "5y",
    horizon: int = 15,
    lookback: int = 80,
    max_trades: int = 5000,
    direction: str | None = None,
    regime: str | None = None,
    exclude_crypto: bool = False,
) -> dict:
    return _serialize(
        run_paper_simulation(
            symbol,
            range_=range_,
            horizon=horizon,
            lookback=lookback,
            max_trades=min(max(max_trades, 50), 20000),
            direction_filter=direction,
            regime_filter=regime,
            exclude_crypto=exclude_crypto,
        )
    )



@app.get("/api/macro/timeframes")
def macro_timeframes(symbol: str = "BTC-USD") -> dict:
    return _serialize(multi_timeframe_context(symbol))


@app.get("/api/macro/context")
def macro_context_endpoint() -> dict:
    return _serialize(macro_context())


@app.get("/api/macro/options-gex")
def macro_options_gex(symbol: str = "SPY", max_expirations: int = 2) -> dict:
    return _serialize(options_gex_context(symbol, max_expirations=min(max(max_expirations, 1), 6)))


@app.get("/api/news/veto")
def news_veto(query: str = "Bitcoin market catalyst") -> dict:
    return _serialize(_catalyst_veto(query))


@app.get("/api/open-source/strategies")
def open_source_strategies() -> dict:
    return _serialize(open_source_strategy_catalog())


@app.get("/api/fundamentals/sec-filings")
def fundamentals_sec_filings(symbol: str = "AAPL", forms: str = "8-K,10-Q,10-K,6-K,20-F", limit: int = 8) -> dict:
    requested_forms = [item.strip() for item in forms.split(",") if item.strip()]
    return _serialize(sec_recent_filings(symbol=symbol, forms=requested_forms, limit=limit))


@app.get("/api/hybrid/gate")
def hybrid_gate(
    symbol: str = "BTC-USD",
    binance_symbol: str = "BTCUSDT",
    polymarket_token_id: str | None = None,
    sample_seconds: float = 1.0,
    max_events: int = 3,
) -> dict:
    live = _live_signal(symbol)
    payload = build_dashboard_payload(live["signal"], runtime=live["runtime"], snapshot=live.get("snapshot"))
    catalyst = _catalyst_veto(_catalyst_query_for_signal(live["signal"].symbol, live["signal"].asset_type))
    timeframes = multi_timeframe_context(symbol)
    stream = asyncio.run(
        dual_websocket_probe(
            binance_symbol=binance_symbol,
            polymarket_token_id=polymarket_token_id,
            sample_seconds=min(max(sample_seconds, 0.25), 4.0),
            max_events=min(max(max_events, 1), 10),
        )
    )
    statarb = scan_default_pairs()
    return _serialize(
        evaluate_hybrid_decision(
            live["signal"],
            payload,
            catalyst,
            timeframes,
            stream,
            statarb,
            live_trading_enabled=os.getenv("LIVE_TRADING_ENABLED", "").lower() in {"1", "true", "yes"},
        )
    )


@app.get("/api/arbitrage/scan")
def arbitrage_scan(binance_symbol: str = "BTCUSDT", polymarket_token_id: str | None = None) -> dict:
    return _serialize(
        {
            "latency": latency_gap_scan(binance_symbol=binance_symbol, polymarket_token_id=polymarket_token_id),
            "statarb": scan_default_pairs(),
        }
    )


@app.get("/api/arbitrage/polymarket-markets")
def arbitrage_polymarket_markets(query: str = "bitcoin", limit: int = 8) -> dict:
    return _serialize(polymarket_market_search(query=query, limit=min(max(limit, 1), 20)))


@app.get("/api/arbitrage/microstructure")
def arbitrage_microstructure(
    binance_symbol: str = "BTCUSDT",
    sample_seconds: float = 2.0,
    max_events: int = 10,
    inventory_units: float = 0.0,
) -> dict:
    return _serialize(
        asyncio.run(
            microstructure_probe(
                binance_symbol=binance_symbol,
                sample_seconds=min(max(sample_seconds, 0.25), 6.0),
                max_events=min(max(max_events, 2), 30),
                inventory_units=inventory_units,
            )
        )
    )


@app.get("/api/arbitrage/stream-snapshot")
def arbitrage_stream_snapshot(
    binance_symbol: str = "BTCUSDT",
    polymarket_token_id: str | None = None,
    sample_seconds: float = 2.0,
    max_events: int = 5,
) -> dict:
    return _serialize(
        asyncio.run(
            dual_websocket_probe(
                binance_symbol=binance_symbol,
                polymarket_token_id=polymarket_token_id,
                sample_seconds=min(max(sample_seconds, 0.25), 6.0),
                max_events=min(max(max_events, 1), 20),
            )
        )
    )


@app.get("/api/statarb/scan")
def statarb_scan(left: str = "GLD", right: str = "GOLD") -> dict:
    return _serialize(scan_pair(left, right))


@app.get("/api/telegram/preview")
def telegram_preview(symbol: str = "AAPL", stale_demo_data: bool = False) -> dict:
    signal = demo_signal(stale=True) if stale_demo_data else _live_signal(symbol)["signal"]
    run = system.subagents.analyze(signal, system.market_intel)
    side = OrderSide.SELL if signal.direction_call.value == "bearish" else OrderSide.BUY
    stop = signal.latest_price + signal.atr * 2 if side == OrderSide.SELL else signal.latest_price - signal.atr * 2
    order_result = system.analyze_trade(signal, side, entry_price=max(signal.latest_price, 0.01), stop_price=max(stop, 0.01))
    return {"message": format_telegram_digest(run, order_result)}


@app.post("/api/paper/orders")
def create_paper_order(payload: PaperOrderPayload) -> dict:
    signal = demo_signal(stale=payload.stale_demo_data)
    result = system.analyze_trade(
        signal,
        side=payload.side,
        entry_price=payload.entry_price,
        stop_price=payload.stop_price,
        order_type=payload.order_type,
        mode=ExecutionMode.PAPER,
    )
    return _serialize(result)


@app.post("/api/signals/strategy")
def publish_strategy_signal(stale_demo_data: bool = False) -> dict:
    result = system.publish_strategy_from_signal(demo_signal(stale=stale_demo_data))
    return _serialize(result)


@app.post("/api/signals/realtime")
def publish_realtime_signal(payload: RealtimeSignalPayload) -> dict:
    signal = build_operation_signal(
        symbol=payload.symbol,
        side=payload.side,
        price=payload.price,
        quantity=payload.quantity,
        content=payload.content,
        market=payload.market,
    )
    duplicate = system.signals.is_duplicate(signal.content)
    published = system.signals.publish(signal)
    quality = score_signal_quality(published, duplicate=duplicate)
    system.heartbeat.push(
        "operation_published",
        f"Operation published for {published.symbol}",
        {"signal_id": published.id, "quality_score": quality.overall_score},
    )
    return _serialize({"signal": published, "quality": quality})


@app.get("/api/signals/feed")
def signal_feed(message_type: SignalMessageType | None = None, symbol: str | None = None) -> dict:
    return _serialize({"signals": system.signals.feed(message_type=message_type, symbol=symbol)})


@app.get("/api/signals/{signal_id}/quality")
def signal_quality(signal_id: str) -> dict:
    signal = system.signals.signals.get(signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="signal not found")
    return _serialize({"quality": score_signal_quality(signal)})


@app.post("/api/heartbeat")
def heartbeat(limit: int = 50) -> dict:
    return _serialize(system.heartbeat.poll(limit=limit))


@app.post("/api/live/orders")
def create_live_order(_: PaperOrderPayload) -> dict:
    raise HTTPException(status_code=403, detail="live trading is disabled by default")


@app.post("/api/orders/{order_id}/cancel")
def cancel_order(order_id: str) -> dict:
    order = system.oms.cancel(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="order not found")
    return _serialize({"order": order})


@app.get("/api/orders")
def orders() -> dict:
    return _serialize({"orders": list(system.oms.orders.values())})


@app.get("/api/fills")
def fills() -> dict:
    return _serialize({"fills": system.oms.fills})


@app.get("/api/positions")
def positions() -> dict:
    return _serialize({"positions": system.portfolio.positions})


@app.get("/api/portfolio")
def portfolio() -> dict:
    return _serialize({"portfolio": system.portfolio})


@app.get("/api/risk")
def risk() -> dict:
    return _serialize({"risk_config": system.risk_config, "kill_switch_active": system.portfolio.kill_switch_active})


@app.patch("/api/risk/config")
def patch_risk_config() -> dict:
    return {"detail": "risk config patching is intentionally deferred until authenticated config storage exists"}


@app.post("/api/kill-switch/activate")
def activate_kill_switch(reason: str = "manual") -> dict:
    return system.activate_kill_switch(reason)


@app.post("/api/kill-switch/deactivate")
def deactivate_kill_switch(reason: str = "manual") -> dict:
    return system.deactivate_kill_switch(reason)


@app.get("/api/execution-quality")
def execution_quality() -> dict:
    values = [system.oms.execution_quality(order_id, 0.0) for order_id in system.oms.orders]
    return _serialize({"execution_quality": [value for value in values if value]})


@app.get("/api/audit/{trade_id}")
def audit(trade_id: str) -> dict:
    return _serialize({"entries": system.audit.for_trade(trade_id), "chain_valid": system.audit.verify_chain()})


def _live_signal(symbol: str) -> dict:
    try:
        snapshot = fetch_market_snapshot(symbol)
        signal = build_signal_from_snapshot(snapshot)
        return {
            "signal": signal,
            "snapshot": snapshot,
            "runtime": {
                "payload_mode": "live_yahoo",
                "live_market_data": True,
                "refresh_source": snapshot.source,
                "why_not_realtime": (
                    "Live candles are coming from Yahoo Finance's chart endpoint. "
                    "They can be exchange-delayed and are not broker-grade execution data."
                ),
            },
        }
    except Exception as exc:  # pragma: no cover - provider failures depend on network/exchange state
        signal = fallback_signal(symbol, str(exc))
        return {
            "signal": signal,
            "runtime": {
                "payload_mode": "live_provider_error_fallback",
                "live_market_data": False,
                "refresh_source": "provider failed; generated safety no_edge payload",
                "why_not_realtime": f"Market data provider failed, so the analyzer returned no_edge instead of guessing: {exc}",
            },
        }


def _catalyst_veto(query: str) -> dict:
    return tavily_rag_veto(
        query,
        api_key=os.getenv("TAVILY_API_KEY"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY"),
        model=os.getenv("CLAUDE_CATALYST_MODEL", "claude-3-5-haiku-latest"),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
        openrouter_model=os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct"),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL"),
        ollama_model=os.getenv("OLLAMA_CATALYST_MODEL", "qwen2.5:3b"),
        use_free_news=os.getenv("DISABLE_FREE_NEWS", "").lower() not in {"1", "true", "yes"},
        provider_preference=os.getenv("CATALYST_LLM_PROVIDER", "auto"),
    )


def _catalyst_query_for_signal(symbol: str, asset_type: str) -> str:
    normalized = (symbol or "").strip().upper()
    if asset_type == "crypto":
        base = normalized.replace("-USD", "")
        return f"{base} crypto market news catalyst ETF flows regulation exchange inflows"
    if asset_type == "forex":
        pair = normalized.replace("=X", "")
        return f"{pair} forex central bank inflation rates macro catalyst"
    if asset_type == "gold":
        return "gold real yields dollar fed inflation macro catalyst"
    return f"{normalized} earnings guidance outlook analyst rating stock catalyst"


def _rank_score(payload: dict) -> float:
    call = payload["trade_call"]
    features = payload["features"]
    probabilities = payload["probabilities"]
    if call["action"] == "NO TRADE":
        directional_probability = max(probabilities.get("up", 0), probabilities.get("down", 0))
        gate_penalty = 0.18
    else:
        directional_probability = call.get("probability", 0)
        gate_penalty = 0
    uncertainty = probabilities.get("neutral", 0)
    stale_penalty = 0.25 if payload["data_health"]["stale"] else 0
    spread_penalty = min((features.get("spread_bps") or 0) / 200, 0.12)
    calibration_bonus = max(features.get("brier_skill_score") or 0, -0.1)
    return round(directional_probability - uncertainty - stale_penalty - spread_penalty - gate_penalty + calibration_bonus, 4)


def _attention_tier(payload: dict, rank_score: float) -> str:
    action = payload["trade_call"]["action"]
    if action in {"BUY", "SELL"} and rank_score >= 0.38 and not payload["data_health"]["stale"]:
        return "actionable"
    if rank_score >= 0.18:
        return "watch"
    return "ignore"


def _regime_summary(cards: list[dict]) -> dict:
    regimes: dict[str, int] = {}
    calls: dict[str, int] = {}
    stale = 0
    for card in cards:
        regime = card["features"].get("regime", "unknown")
        call = card["trade_call"].get("action", "NO TRADE")
        regimes[regime] = regimes.get(regime, 0) + 1
        calls[call] = calls.get(call, 0) + 1
        stale += 1 if card["data_health"].get("stale") else 0
    dominant_regime = max(regimes, key=regimes.get) if regimes else "unknown"
    actionable = calls.get("BUY", 0) + calls.get("SELL", 0)
    return {
        "dominant_regime": dominant_regime,
        "regime_counts": regimes,
        "call_counts": calls,
        "fresh_symbols": len(cards) - stale,
        "stale_symbols": stale,
        "headline": (
            f"{dominant_regime.replace('_', ' ')} across {regimes.get(dominant_regime, 0)}/{len(cards)} watched symbols; "
            f"{actionable} actionable, {calls.get('NO TRADE', 0)} no-trade."
        ),
    }


def _serialize(value):
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, MappingProxyType):
        return {key: _serialize(item) for key, item in dict(value).items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "__dict__"):
        return _serialize(value.__dict__)
    if hasattr(value, "value"):
        return value.value
    return value
