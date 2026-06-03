from __future__ import annotations

from typing import Any


def format_telegram_digest(subagent_run: Any, order_result: dict[str, Any] | None = None) -> str:
    decision = subagent_run.portfolio_decision
    trader = subagent_run.trader_proposal
    risk = subagent_run.risk_debate.manager_report
    order = (order_result or {}).get("order")
    sizing = (order_result or {}).get("sizing")

    lines = [
        f"{subagent_run.symbol} AI Trading Desk",
        f"Rating: {decision.rating.value} | Direction: {decision.direction_call.value} | Confidence: {decision.confidence.value}",
        f"Execution approved: {'yes' if decision.approved_for_execution else 'no'}",
        "",
        f"Trader: {trader.action.value} @ {trader.entry_price if trader.entry_price is not None else 'n/a'}",
        f"Stop: {trader.stop_loss if trader.stop_loss is not None else 'n/a'} | Target: {decision.price_target if decision.price_target is not None else 'n/a'}",
        f"Risk voice: {risk.stance.value} ({risk.confidence.value})",
    ]

    if sizing is not None:
        lines.extend([
            "",
            f"Size: {getattr(sizing, 'quantity', 'n/a')} shares",
            f"Risk dollars: {getattr(sizing, 'risk_dollars', 'n/a')}",
        ])

    if order is not None:
        lines.extend([
            f"Paper order: {getattr(getattr(order, 'status', None), 'value', 'unknown')}",
            f"Filled: {getattr(order, 'filled_quantity', 0)} @ {getattr(order, 'average_fill_price', None)}",
        ])

    if decision.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"- {warning}" for warning in decision.warnings[:5]])

    lines.extend([
        "",
        "Subagents:",
        "- Market, sentiment, news, fundamentals analysts",
        "- Bull/bear researchers",
        "- Trader",
        "- Aggressive/neutral/conservative risk",
        "- Portfolio manager",
    ])
    return "\n".join(lines)
