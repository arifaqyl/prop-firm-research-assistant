from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

from .domain import DirectionCall
from .domain import OrderSide, OrderType
from .system import TradingSystem, demo_signal
from .telegram import format_telegram_digest



def build_demo_dashboard_payload() -> dict[str, Any]:
    """Build a fresh, deterministic payload for the visual dashboard."""
    return build_dashboard_payload(
        demo_signal(),
        runtime={
            "payload_mode": "api_demo",
            "live_market_data": False,
            "refresh_source": "FastAPI demo endpoint",
            "why_not_realtime": (
                "The dashboard is wired to the analyzer/subagent/risk stack, "
                "but this endpoint intentionally uses deterministic demo data."
            ),
        },
    )


def build_dashboard_payload(signal, runtime: dict[str, Any] | None = None, snapshot: Any | None = None) -> dict[str, Any]:
    """Build a UI-ready payload from any analyzer signal."""
    system = TradingSystem()
    subagent_result = system.run_subagent_analysis(signal)["subagent_run"]
    side, stop_price = _execution_plan(signal)
    order_result = system.analyze_trade(
        signal,
        side=side,
        entry_price=max(signal.latest_price, 0.01),
        stop_price=stop_price,
        order_type=OrderType.LIMIT,
    )

    runtime = runtime or {
        "payload_mode": "signal",
        "live_market_data": False,
        "refresh_source": signal.data_health.source,
        "why_not_realtime": "Payload was generated from a provided analyzer signal.",
    }

    return {
        "runtime": {
            **runtime,
            "provider_source": signal.data_health.source,
            "model_version": signal.model_version,
            "prompt_version": signal.prompt_version,
            "free_mode": os.getenv("FREE_MODE", "true").lower() in {"1", "true", "yes"},
        },
        "symbol": signal.symbol,
        "asset_type": signal.asset_type,
        "latest_price": signal.latest_price,
        "primary_horizon": signal.primary_horizon,
        "probabilities": signal.probabilities,
        "trade_call": build_trade_call(signal, subagent_result, order_result),
        "chart": serialize_chart(signal, snapshot),
        "features": serialize_features(signal),
        "evidence": serialize_evidence(signal, subagent_result, order_result),
        "data_sources": serialize_data_sources(signal, runtime, snapshot),
        "data_health": {
            "age_hours": round(signal.data_health.age_hours, 4),
            "stale": signal.data_health.is_stale,
            "warnings": signal.data_health.warnings,
        },
        "subagents": serialize_subagent_run(subagent_result),
        "paper_order": serialize_order_result(order_result),
        "portfolio": {
            "equity": system.portfolio.equity,
            "cash": round(system.portfolio.cash, 2),
            "gross_exposure": round(system.portfolio.gross_exposure, 2),
            "net_exposure": round(system.portfolio.net_exposure, 2),
            "kill_switch_active": system.portfolio.kill_switch_active,
        },
        "audit": {
            "chain_valid": system.audit.verify_chain(),
            "event_count": len(system.audit.entries),
            "events": [
                {
                    "event_type": entry.event_type,
                    "timestamp": entry.timestamp.isoformat(),
                    "hash": entry.hash[:12],
                }
                for entry in system.audit.entries
            ],
        },
        "telegram_preview": format_telegram_digest(subagent_result, order_result),
        "source_map": {
            "subagents": "src/prop_firm_ai/subagents.py",
            "risk": "src/prop_firm_ai/risk.py",
            "oms": "src/prop_firm_ai/oms.py",
            "dashboard_payload": "src/prop_firm_ai/dashboard.py",
            "telegram": "src/prop_firm_ai/telegram.py",
            "market_data": "src/prop_firm_ai/market_data.py",
            "static_app": "app/index.html",
        },
    }


def build_trade_call(signal, subagent_result: Any, order_result: dict[str, Any] | None = None) -> dict[str, Any]:
    decision = subagent_result.portfolio_decision
    trader = subagent_result.trader_proposal
    gate = (order_result or {}).get("gate")
    if not decision.approved_for_execution or signal.direction_call == DirectionCall.NO_EDGE:
        action = "NO TRADE"
    elif signal.direction_call == DirectionCall.BEARISH:
        action = "SELL"
    else:
        action = "BUY"
    probability_key = "down" if action == "SELL" else "up" if action == "BUY" else "neutral"
    return {
        "action": action,
        "direction": decision.direction_call.value,
        "rating": decision.rating.value,
        "confidence": decision.confidence.value,
        "approved_for_execution": decision.approved_for_execution,
        "entry": trader.entry_price,
        "stop": trader.stop_loss,
        "target": decision.price_target,
        "invalidation_level": decision.invalidation_level,
        "probability": signal.probabilities.get(probability_key, 0),
        "reason": decision.executive_summary,
        "gate_reasons": getattr(gate, "reasons", []) if gate else [],
        "warnings": decision.warnings,
    }


def _execution_plan(signal) -> tuple[OrderSide, float]:
    if signal.direction_call.value == "bearish":
        return OrderSide.SELL, signal.latest_price + max(signal.atr * 2, signal.latest_price * 0.01, 0.01)
    return OrderSide.BUY, max(signal.latest_price - max(signal.atr * 2, signal.latest_price * 0.01, 0.01), 0.01)


def serialize_chart(signal, snapshot: Any | None = None) -> dict[str, Any]:
    candles = getattr(snapshot, "candles", None) or _demo_candles(signal)
    limited = candles[-90:]
    return {
        "type": "ohlcv",
        "interval": "5m" if snapshot else "demo",
        "range": "1d" if snapshot else "demo",
        "provider_symbol": getattr(snapshot, "provider_symbol", signal.symbol),
        "latest_candle_at": limited[-1].timestamp.isoformat() if limited else signal.data_health.latest_candle_at.isoformat(),
        "candles": [
            {
                "time": candle.timestamp.isoformat(),
                "open": round(candle.open, 6),
                "high": round(candle.high, 6),
                "low": round(candle.low, 6),
                "close": round(candle.close, 6),
                "volume": round(candle.volume, 2),
            }
            for candle in limited
        ],
    }


def serialize_features(signal) -> dict[str, Any]:
    return {
        "regime": signal.regime,
        "sample_size": signal.sample_size,
        "brier_skill_score": signal.brier_skill_score,
        "atr": round(signal.atr, 6),
        "spread_bps": signal.spread_bps,
        "average_daily_volume": round(signal.average_daily_volume, 2),
        "expected_edge": signal.expected_edge,
        "model_version": signal.model_version,
        "prompt_version": signal.prompt_version,
        "earnings_proximity_flag": signal.earnings_proximity_flag,
        "rsi": signal.rsi,
        "macd": signal.macd,
        "adx": signal.adx,
        "bollinger": signal.bollinger,
    }


def serialize_evidence(signal, subagent_result: Any, order_result: dict[str, Any] | None = None) -> dict[str, Any]:
    reports = [
        *subagent_result.analyst_reports,
        subagent_result.research_debate.bull_report,
        subagent_result.research_debate.bear_report,
        subagent_result.research_debate.manager_report,
        subagent_result.risk_debate.aggressive_report,
        subagent_result.risk_debate.neutral_report,
        subagent_result.risk_debate.conservative_report,
        subagent_result.risk_debate.manager_report,
    ]
    bullish: list[str] = []
    bearish: list[str] = []
    conflicting: list[str] = []
    warnings: list[str] = []
    for report in reports:
        line = f"{report.role.value}: {report.summary}"
        if report.stance == DirectionCall.BULLISH:
            bullish.append(line)
        elif report.stance == DirectionCall.BEARISH:
            bearish.append(line)
        else:
            conflicting.append(line)
        warnings.extend(report.warnings)
    gate = (order_result or {}).get("gate")
    if gate:
        conflicting.extend(getattr(gate, "reasons", []))
        warnings.extend(getattr(gate, "warnings", []))
    return {
        "bullish": bullish[:8],
        "bearish": bearish[:8],
        "conflicting": conflicting[:8],
        "warnings": list(dict.fromkeys(warnings))[:8],
        "raw_inputs": [
            f"probabilities={signal.probabilities}",
            f"regime={signal.regime}",
            f"ATR={signal.atr:.4f}",
            f"spread_bps={signal.spread_bps:.2f}",
            f"sample_size={signal.sample_size}",
            f"brier_skill_score={signal.brier_skill_score:.4f}",
        ],
    }


def serialize_data_sources(signal, runtime: dict[str, Any] | None = None, snapshot: Any | None = None) -> list[dict[str, Any]]:
    return [
        {
            "name": "Market candles",
            "status": "live" if runtime and runtime.get("live_market_data") else "demo_or_fallback",
            "source": signal.data_health.source,
            "provider_symbol": getattr(snapshot, "provider_symbol", signal.symbol),
            "rows": len(getattr(snapshot, "candles", []) or []),
            "latest_candle_at": signal.data_health.latest_candle_at.isoformat(),
            "fields": ["open", "high", "low", "close", "volume"],
        },
        {
            "name": "Analyzer features",
            "status": "computed",
            "source": "local deterministic feature engine",
            "provider_symbol": signal.symbol,
            "rows": signal.sample_size,
            "latest_candle_at": signal.data_health.checked_at.isoformat(),
            "fields": ["regime", "ATR", "spread_bps", "expected_edge", "probabilities"],
        },
        {
            "name": "Subagent evidence",
            "status": "computed",
            "source": "local TradingAgents-inspired pipeline",
            "provider_symbol": signal.symbol,
            "rows": 12,
            "latest_candle_at": signal.data_health.checked_at.isoformat(),
            "fields": ["market", "sentiment", "news", "fundamentals", "risk", "portfolio"],
        },
    ]


def _demo_candles(signal) -> list[Any]:
    class DemoCandle:
        def __init__(self, index: int) -> None:
            self.timestamp = signal.data_health.checked_at - timedelta(minutes=(59 - index) * 5)
            drift = (index - 30) * signal.atr * 0.025
            wave = ((index % 9) - 4) * signal.atr * 0.035
            self.close = max(signal.latest_price + drift + wave, 0.01)
            self.open = max(self.close - signal.atr * 0.08, 0.01)
            self.high = max(self.open, self.close) + signal.atr * 0.12
            self.low = max(min(self.open, self.close) - signal.atr * 0.12, 0.01)
            self.volume = signal.average_daily_volume / 78

    return [DemoCandle(index) for index in range(60)]


def serialize_subagent_run(run: Any) -> dict[str, Any]:
    target = run.research_debate.manager_report.stance.value
    required_roles = {"market_analyst", "news_analyst", "fundamentals_analyst"}
    confluence_matrix = [
        {
            "role": report.role.value,
            "stance": report.stance.value,
            "required": target,
            "approved": bool(target in {"bullish", "bearish"} and report.stance.value == target),
            "summary": report.summary,
        }
        for report in run.analyst_reports
        if report.role.value in required_roles
    ]
    return {
        "symbol": run.symbol,
        "created_at": run.created_at.isoformat(),
        "analyst_reports": [serialize_report(report) for report in run.analyst_reports],
        "confluence_matrix": confluence_matrix,
        "confluence_approved": bool(confluence_matrix) and all(item["approved"] for item in confluence_matrix),
        "research_debate": {
            "bull": serialize_report(run.research_debate.bull_report),
            "bear": serialize_report(run.research_debate.bear_report),
            "manager": serialize_report(run.research_debate.manager_report),
        },
        "trader_proposal": {
            "action": run.trader_proposal.action.value,
            "entry_price": run.trader_proposal.entry_price,
            "stop_loss": run.trader_proposal.stop_loss,
            "position_sizing": run.trader_proposal.position_sizing,
            "reasoning": run.trader_proposal.reasoning,
        },
        "risk_debate": {
            "aggressive": serialize_report(run.risk_debate.aggressive_report),
            "neutral": serialize_report(run.risk_debate.neutral_report),
            "conservative": serialize_report(run.risk_debate.conservative_report),
            "manager": serialize_report(run.risk_debate.manager_report),
        },
        "portfolio_decision": {
            "rating": run.portfolio_decision.rating.value,
            "direction_call": run.portfolio_decision.direction_call.value,
            "confidence": run.portfolio_decision.confidence.value,
            "approved_for_execution": run.portfolio_decision.approved_for_execution,
            "executive_summary": run.portfolio_decision.executive_summary,
            "thesis": run.portfolio_decision.thesis,
            "price_target": run.portfolio_decision.price_target,
            "invalidation_level": run.portfolio_decision.invalidation_level,
            "warnings": run.portfolio_decision.warnings,
        },
        "memory_reflection": run.memory_reflection,
    }


def serialize_report(report: Any) -> dict[str, Any]:
    return {
        "role": report.role.value,
        "stance": report.stance.value,
        "confidence": report.confidence.value,
        "score": report.score,
        "summary": report.summary,
        "evidence": report.evidence,
        "warnings": report.warnings,
    }


def serialize_order_result(result: dict[str, Any]) -> dict[str, Any]:
    order = result.get("order")
    quality = result.get("execution_quality")
    sizing = result.get("sizing")
    risk = result.get("risk")
    gate = result.get("gate")
    return {
        "approved": result.get("approved"),
        "stage": result.get("stage"),
        "trade_id": result.get("trade_id"),
        "gate": {
            "approved": getattr(gate, "approved", None),
            "direction_call": getattr(getattr(gate, "direction_call", None), "value", None),
            "confidence": getattr(getattr(gate, "confidence", None), "value", None),
            "reasons": getattr(gate, "reasons", []),
            "warnings": getattr(gate, "warnings", []),
        },
        "sizing": {
            "approved": getattr(sizing, "approved", None),
            "quantity": getattr(sizing, "quantity", None),
            "notional": round(getattr(sizing, "notional", 0) or 0, 2),
            "risk_dollars": round(getattr(sizing, "risk_dollars", 0) or 0, 2),
            "reductions": getattr(sizing, "reductions", []),
        },
        "risk": {
            "approved": getattr(risk, "approved", None),
            "size_multiplier": getattr(risk, "size_multiplier", None),
            "reasons": getattr(risk, "reasons", []),
            "violations": getattr(risk, "violations", []),
        },
        "order": {
            "id": getattr(order, "id", None),
            "status": getattr(getattr(order, "status", None), "value", None),
            "filled_quantity": getattr(order, "filled_quantity", None),
            "average_fill_price": getattr(order, "average_fill_price", None),
            "rejection_reason": getattr(order, "rejection_reason", None),
        },
        "execution_quality": {
            "realized_slippage_bps": round(getattr(quality, "realized_slippage_bps", 0) or 0, 4),
            "missed_quantity": getattr(quality, "missed_quantity", None),
            "filled_quantity": getattr(quality, "filled_quantity", None),
        },
    }
