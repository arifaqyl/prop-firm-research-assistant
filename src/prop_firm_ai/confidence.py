from __future__ import annotations

from .domain import (
    AnalyzerSignal,
    Confidence,
    ConfidenceGateResult,
    DirectionCall,
    ModelConfig,
)


def evaluate_confidence_gate(signal: AnalyzerSignal, config: ModelConfig) -> ConfidenceGateResult:
    reasons: list[str] = []
    warnings = list(signal.data_health.warnings)

    if signal.data_health.is_stale:
        return ConfidenceGateResult(
            approved=False,
            direction_call=DirectionCall.NO_EDGE,
            confidence=Confidence.LOW,
            reasons=["data freshness gate failed"],
            warnings=warnings,
        )

    if signal.direction_call not in {DirectionCall.BULLISH, DirectionCall.BEARISH}:
        return ConfidenceGateResult(
            approved=False,
            direction_call=DirectionCall.NO_EDGE,
            confidence=Confidence.LOW,
            reasons=["analyzer did not produce a directional edge"],
            warnings=warnings,
        )

    directional_probability = signal.probabilities.get(
        "up" if signal.direction_call == DirectionCall.BULLISH else "down",
        0.0,
    )

    if signal.brier_skill_score <= config.min_brier_skill_score:
        return ConfidenceGateResult(
            approved=False,
            direction_call=DirectionCall.NO_EDGE,
            confidence=Confidence.LOW,
            reasons=["model calibration does not beat baseline"],
            warnings=warnings,
        )

    confidence = Confidence.LOW
    if (
        directional_probability >= config.high_probability_threshold
        and signal.sample_size >= config.high_min_sample_size
    ):
        confidence = Confidence.HIGH
        reasons.append("high-confidence probability and sample-size gates passed")
    elif (
        directional_probability >= config.medium_probability_threshold
        and signal.sample_size >= config.medium_min_sample_size
    ):
        confidence = Confidence.MEDIUM
        reasons.append("medium-confidence probability and sample-size gates passed")
    else:
        return ConfidenceGateResult(
            approved=False,
            direction_call=DirectionCall.NO_EDGE,
            confidence=Confidence.LOW,
            reasons=["probability or historical sample size is too weak"],
            warnings=warnings,
        )

    if signal.earnings_proximity_flag:
        warnings.append("earnings event imminent; historical setup comparison is less reliable")
        confidence = Confidence.MEDIUM if confidence == Confidence.HIGH else Confidence.LOW
        reasons.append("confidence reduced for earnings proximity")

    return ConfidenceGateResult(
        approved=True,
        direction_call=signal.direction_call,
        confidence=confidence,
        reasons=reasons,
        warnings=warnings,
    )
