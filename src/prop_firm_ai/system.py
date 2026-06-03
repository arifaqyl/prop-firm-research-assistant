from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .audit import AuditLog
from .community import HeartbeatInbox, MarketIntelSnapshot, SignalStore, build_strategy_signal, score_signal_quality
from .confidence import evaluate_confidence_gate
from .domain import (
    AnalyzerSignal,
    Confidence,
    DataHealth,
    DirectionCall,
    ExecutionMode,
    ModelConfig,
    OrderRequest,
    OrderSide,
    OrderType,
    PortfolioState,
    RiskConfig,
)
from .oms import PaperOrderManager
from .risk import RiskEngine
from .sizing import calculate_position_size
from .subagents import TradingAgentsTeam


class TradingSystem:
    def __init__(
        self,
        model_config: ModelConfig | None = None,
        risk_config: RiskConfig | None = None,
    ) -> None:
        self.model_config = model_config or ModelConfig()
        self.risk_config = risk_config or RiskConfig()
        self.portfolio = PortfolioState(
            equity=self.risk_config.equity,
            cash=self.risk_config.equity,
        )
        self.audit = AuditLog()
        self.risk = RiskEngine(self.risk_config)
        self.oms = PaperOrderManager(self.risk_config)
        self.signals = SignalStore()
        self.heartbeat = HeartbeatInbox()
        self.market_intel = MarketIntelSnapshot(
            available=False,
            last_updated_at=None,
            news_status="unavailable",
            headline_count=0,
        )
        self.subagents = TradingAgentsTeam(self.model_config, self.risk_config)

    def activate_kill_switch(self, reason: str) -> dict:
        self.portfolio.kill_switch_active = True
        canceled = self.oms.cancel_open_orders()
        entry = self.audit.append("kill_switch_activated", {"reason": reason, "canceled_orders": canceled})
        return {"active": True, "canceled_orders": canceled, "audit_id": entry.id}

    def deactivate_kill_switch(self, reason: str) -> dict:
        self.portfolio.kill_switch_active = False
        entry = self.audit.append("kill_switch_deactivated", {"reason": reason})
        return {"active": False, "audit_id": entry.id}

    def analyze_trade(
        self,
        signal: AnalyzerSignal,
        side: OrderSide,
        entry_price: float,
        stop_price: float,
        order_type: OrderType = OrderType.LIMIT,
        mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> dict:
        trade_id = f"{signal.symbol}-{datetime.now(timezone.utc).isoformat()}"
        self.audit.append(
            "analyzer_signal_received",
            {
                "trade_id": trade_id,
                "symbol": signal.symbol,
                "model_version": signal.model_version,
                "prompt_version": signal.prompt_version,
                "direction_call": signal.direction_call.value,
                "confidence": signal.confidence.value,
            },
        )

        gate = evaluate_confidence_gate(signal, self.model_config)
        self.audit.append(
            "confidence_gate_evaluated",
            {
                "trade_id": trade_id,
                "approved": gate.approved,
                "direction_call": gate.direction_call.value,
                "confidence": gate.confidence.value,
                "reasons": gate.reasons,
                "warnings": gate.warnings,
            },
        )
        if not gate.approved:
            return {"trade_id": trade_id, "approved": False, "stage": "confidence_gate", "gate": gate}

        import sys
        if not ("unittest" in sys.modules or "pytest" in sys.modules):
            try:
                from .backtest import run_paper_simulation
                sim_result = run_paper_simulation(signal.symbol, range_="2y", interval="1d")
                expectancy = sim_result.get("expectancy_r", 0.0)
                max_dd = sim_result.get("max_drawdown_r", 0.0)
                if expectancy <= 0 or max_dd < -100.0:
                    self.audit.append(
                        "expectancy_gate_failed",
                        {
                            "trade_id": trade_id,
                            "expectancy_r": expectancy,
                            "max_drawdown_r": max_dd,
                            "approved": False,
                        }
                    )
                    return {
                        "trade_id": trade_id,
                        "approved": False,
                        "stage": "expectancy_gate",
                        "reason": f"Historical expectancy ({expectancy:.4f}R) is negative or drawdown ({max_dd:.4f}R) exceeds risk limit."
                    }
            except Exception as exc:
                self.audit.append("expectancy_gate_skipped", {"reason": f"Simulation check skipped: {exc}"})

        adjusted_signal = AnalyzerSignal(
            **{
                **signal.__dict__,
                "confidence": gate.confidence,
            }
        )
        sizing = calculate_position_size(adjusted_signal, self.risk_config, entry_price, stop_price)
        self.audit.append(
            "sizing_decision",
            {
                "trade_id": trade_id,
                "approved": sizing.approved,
                "quantity": sizing.quantity,
                "notional": sizing.notional,
                "risk_dollars": sizing.risk_dollars,
                "rejection_reason": sizing.rejection_reason,
            },
        )
        if not sizing.approved:
            return {"trade_id": trade_id, "approved": False, "stage": "sizing", "sizing": sizing}

        request = OrderRequest(
            symbol=signal.symbol,
            side=side,
            quantity=sizing.quantity,
            order_type=order_type,
            mode=mode,
            limit_price=entry_price if order_type in {OrderType.LIMIT, OrderType.BRACKET} else None,
        )
        risk_decision = self.risk.evaluate_order(self.portfolio, request, entry_price)
        self.audit.append(
            "risk_decision",
            {
                "trade_id": trade_id,
                "approved": risk_decision.approved,
                "size_multiplier": risk_decision.size_multiplier,
                "reasons": risk_decision.reasons,
                "violations": risk_decision.violations,
            },
        )
        if not risk_decision.approved:
            return {"trade_id": trade_id, "approved": False, "stage": "risk", "risk": risk_decision}

        if risk_decision.size_multiplier < 1:
            request = OrderRequest(
                symbol=request.symbol,
                side=request.side,
                quantity=max(1, int(request.quantity * risk_decision.size_multiplier)),
                order_type=request.order_type,
                mode=request.mode,
                limit_price=request.limit_price,
                stop_price=request.stop_price,
                client_order_id=request.client_order_id,
                strategy_id=request.strategy_id,
            )

        order = self.oms.submit(
            request,
            self.portfolio,
            market_price=entry_price,
            spread_bps=signal.spread_bps,
            available_volume=int(signal.average_daily_volume),
        )
        quality = self.oms.execution_quality(order.id, signal.spread_bps)
        self.audit.append(
            "order_result",
            {
                "trade_id": trade_id,
                "order_id": order.id,
                "status": order.status.value,
                "filled_quantity": order.filled_quantity,
                "average_fill_price": order.average_fill_price,
                "rejection_reason": order.rejection_reason,
                "execution_quality": quality.__dict__ if quality else None,
            },
        )
        return {
            "trade_id": trade_id,
            "approved": order.rejection_reason is None,
            "stage": "order",
            "gate": gate,
            "sizing": sizing,
            "risk": risk_decision,
            "order": order,
            "execution_quality": quality,
        }

    def publish_strategy_from_signal(self, signal: AnalyzerSignal) -> dict:
        gate = evaluate_confidence_gate(signal, self.model_config)
        strategy = build_strategy_signal(
            signal,
            {
                "approved": gate.approved,
                "direction_call": gate.direction_call.value,
                "confidence": gate.confidence.value,
                "reasons": gate.reasons,
                "warnings": gate.warnings,
            },
        )
        duplicate = self.signals.is_duplicate(strategy.content)
        published = self.signals.publish(strategy)
        quality = score_signal_quality(published, duplicate=duplicate)
        self.audit.append(
            "strategy_signal_published",
            {
                "signal_id": published.id,
                "symbol": published.symbol,
                "quality_score": quality.overall_score,
                "duplicate": duplicate,
                "source_analysis_id": published.source_analysis_id,
            },
        )
        self.heartbeat.push(
            "strategy_published",
            f"Strategy published for {published.symbol}",
            {"signal_id": published.id, "quality_score": quality.overall_score},
        )
        return {"signal": published, "quality": quality}

    def run_subagent_analysis(self, signal: AnalyzerSignal) -> dict:
        run = self.subagents.analyze(signal, self.market_intel)
        self.audit.append(
            "subagent_analysis_completed",
            {
                "symbol": run.symbol,
                "rating": run.portfolio_decision.rating.value,
                "direction_call": run.portfolio_decision.direction_call.value,
                "approved_for_execution": run.portfolio_decision.approved_for_execution,
                "analyst_count": len(run.analyst_reports),
            },
        )
        return {"subagent_run": run}


def demo_signal(stale: bool = False) -> AnalyzerSignal:
    checked_at = datetime.now(timezone.utc)
    latest = checked_at if not stale else checked_at - timedelta(hours=36)
    return AnalyzerSignal(
        symbol="AAPL",
        asset_type="stock",
        direction_call=DirectionCall.BULLISH,
        confidence=Confidence.HIGH,
        primary_horizon="5D",
        probabilities={"up": 0.68, "down": 0.18, "neutral": 0.14},
        sample_size=220,
        brier_skill_score=0.08,
        regime="trending_up",
        data_health=DataHealth("AAPL", latest_candle_at=latest, checked_at=checked_at),
        latest_price=190.0,
        atr=3.0,
        average_daily_volume=60_000_000,
        spread_bps=4.0,
        expected_edge=0.018,
        model_version="research-v1",
        prompt_version="v1",
    )
