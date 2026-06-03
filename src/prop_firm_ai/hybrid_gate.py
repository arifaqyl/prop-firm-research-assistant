from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .confidence import evaluate_confidence_gate
from .domain import AnalyzerSignal, DirectionCall, ModelConfig


def evaluate_hybrid_decision(
    signal: AnalyzerSignal,
    dashboard_payload: dict[str, Any],
    catalyst: dict[str, Any],
    timeframes: dict[str, Any],
    stream: dict[str, Any],
    statarb: dict[str, Any],
    model_config: ModelConfig | None = None,
    live_trading_enabled: bool = False,
) -> dict[str, Any]:
    """Fuse the macro brain and micro sniper into one auditable gate.

    This deliberately separates "interesting setup" from "live approved". The
    current system can produce monitor/paper candidates, but live approval stays
    false unless an explicit live config and execution permission exist.
    """
    model_config = model_config or ModelConfig()
    direction = _signal_direction(signal)
    gates = [
        _analyzer_gate(signal, model_config),
        _catalyst_gate(catalyst, direction),
        _timeframe_gate(timeframes, direction),
        _confluence_gate(dashboard_payload),
    ]
    brain_approved = all(gate["approved"] for gate in gates)
    lag_gate = _lag_gate(stream)
    statarb_gate = _statarb_gate(statarb)
    opportunity_gates = [lag_gate, statarb_gate]
    opportunity_found = any(gate["approved"] for gate in opportunity_gates)
    live_approved = bool(live_trading_enabled and brain_approved and opportunity_found and lag_gate.get("execution_allowed"))

    if not brain_approved:
        decision = "NO_TRADE"
    elif opportunity_found:
        decision = "PAPER_CANDIDATE"
    else:
        decision = "OBSERVE_ONLY"

    blockers = [reason for gate in [*gates, *opportunity_gates] if not gate["approved"] for reason in gate.get("blockers", [])]
    if not live_trading_enabled:
        blockers.append("live trading disabled by system config")
    if not live_approved:
        blockers.append("hybrid gate has not approved live execution")

    return {
        "mode": "hybrid_monitor",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "symbol": signal.symbol,
        "direction": direction,
        "decision": decision,
        "brain_approved": brain_approved,
        "opportunity_found": opportunity_found,
        "approved_for_paper": brain_approved and opportunity_found,
        "approved_for_live": live_approved,
        "live_trading_enabled": live_trading_enabled,
        "gates": {
            "analyzer": gates[0],
            "catalyst": gates[1],
            "timeframe": gates[2],
            "confluence": gates[3],
            "lag_sniper": lag_gate,
            "statarb": statarb_gate,
        },
        "blockers": _dedupe(blockers),
        "rule": "Analyzer, catalyst, multi-timeframe, and confluence must all pass before any paper candidate; live remains disabled unless explicit live execution controls are active.",
    }


def _signal_direction(signal: AnalyzerSignal) -> str:
    if signal.direction_call == DirectionCall.BULLISH:
        return "BULLISH"
    if signal.direction_call == DirectionCall.BEARISH:
        return "BEARISH"
    return "NO_EDGE"


def _analyzer_gate(signal: AnalyzerSignal, model_config: ModelConfig) -> dict[str, Any]:
    gate = evaluate_confidence_gate(signal, model_config)
    approved = gate.approved and signal.direction_call in {DirectionCall.BULLISH, DirectionCall.BEARISH}
    return {
        "approved": approved,
        "status": "pass" if approved else "blocked",
        "direction": _signal_direction(signal),
        "confidence": gate.confidence.value,
        "reasons": gate.reasons,
        "warnings": gate.warnings,
        "blockers": [] if approved else gate.reasons or ["analyzer did not produce a tradable edge"],
    }


def _catalyst_gate(catalyst: dict[str, Any], direction: str) -> dict[str, Any]:
    if direction not in {"BULLISH", "BEARISH"}:
        return {
            "approved": False,
            "status": "skipped",
            "verdict": catalyst.get("verdict", "NO_TRADE"),
            "required": None,
            "confidence": catalyst.get("confidence"),
            "news_provider": catalyst.get("news_provider"),
            "llm_used": bool(catalyst.get("llm_used")),
            "reason": "Analyzer has no directional edge, so catalyst confirmation is skipped.",
            "blockers": [],
        }
    verdict = catalyst.get("verdict", "NO_TRADE")
    required = "BULLISH_CATALYST" if direction == "BULLISH" else "BEARISH_CATALYST" if direction == "BEARISH" else "NO_TRADE"
    approved = direction in {"BULLISH", "BEARISH"} and verdict == required and bool(catalyst.get("llm_used"))
    blockers = []
    if verdict != required:
        blockers.append(f"catalyst verdict {verdict} does not match required {required}")
    if not catalyst.get("llm_used"):
        blockers.append("catalyst classifier is keyword/free-news only; LLM veto is closed")
    return {
        "approved": approved,
        "status": "pass" if approved else "blocked",
        "verdict": verdict,
        "required": required,
        "confidence": catalyst.get("confidence"),
        "news_provider": catalyst.get("news_provider"),
        "llm_used": bool(catalyst.get("llm_used")),
        "reason": catalyst.get("reason"),
        "blockers": blockers,
    }


def _timeframe_gate(timeframes: dict[str, Any], direction: str) -> dict[str, Any]:
    if direction not in {"BULLISH", "BEARISH"}:
        return {
            "approved": False,
            "status": "skipped",
            "aligned_direction": timeframes.get("aligned_direction"),
            "required": None,
            "timeframe_count": len(timeframes.get("timeframes", [])),
            "warnings": timeframes.get("warnings", []),
            "blockers": [],
        }
    required = direction.lower()
    approved = bool(timeframes.get("micro_trade_allowed")) and timeframes.get("aligned_direction") == required
    blockers = []
    if not timeframes.get("micro_trade_allowed"):
        blockers.append("multi-timeframe gate does not allow micro trades")
    if timeframes.get("aligned_direction") != required:
        blockers.append(f"timeframes aligned {timeframes.get('aligned_direction')} but analyzer requires {required}")
    return {
        "approved": approved,
        "status": "pass" if approved else "blocked",
        "aligned_direction": timeframes.get("aligned_direction"),
        "required": required,
        "timeframe_count": len(timeframes.get("timeframes", [])),
        "warnings": timeframes.get("warnings", []),
        "blockers": blockers,
    }


def _confluence_gate(payload: dict[str, Any]) -> dict[str, Any]:
    subagents = payload.get("subagents", {})
    target = (subagents.get("portfolio_decision") or {}).get("direction_call")
    if target not in {"bullish", "bearish"}:
        matrix = subagents.get("confluence_matrix", [])
        target = next((item.get("required") for item in matrix if item.get("required") in {"bullish", "bearish"}), target)
    if target not in {"bullish", "bearish"}:
        return {
            "approved": False,
            "status": "skipped",
            "matrix": [],
            "blockers": [],
        }
    matrix = subagents.get("confluence_matrix", [])
    approved = bool(subagents.get("confluence_approved"))
    blockers = [
        f"{item.get('role')} stance {item.get('stance')} != required {item.get('required')}"
        for item in matrix
        if not item.get("approved")
    ]
    if not matrix:
        blockers.append("confluence matrix unavailable")
    return {
        "approved": approved,
        "status": "pass" if approved else "blocked",
        "matrix": matrix,
        "blockers": blockers,
    }


def _lag_gate(stream: dict[str, Any]) -> dict[str, Any]:
    candidate = stream.get("lag_candidate", {})
    approved = candidate.get("decision") == "CANDIDATE"
    return {
        "approved": approved,
        "status": "candidate" if approved else "observe",
        "decision": candidate.get("decision", "OBSERVE_ONLY"),
        "execution_allowed": bool(candidate.get("execution_allowed")),
        "true_probability_estimate": candidate.get("true_probability_estimate"),
        "estimated_yes_edge": candidate.get("estimated_yes_edge"),
        "binance_impulse_bps": candidate.get("binance_impulse_bps"),
        "blockers": candidate.get("blockers", []) if not approved else [],
    }


def _statarb_gate(statarb: dict[str, Any]) -> dict[str, Any]:
    pairs = statarb.get("pairs", [])
    actionable = [pair for pair in pairs if pair.get("decision") != "NO_TRADE"]
    approved = bool(actionable)
    return {
        "approved": approved,
        "status": "candidate" if approved else "observe",
        "actionable_count": len(actionable),
        "candidates": actionable,
        "blockers": [] if approved else ["no stat-arb pair spread outside threshold"],
    }


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
