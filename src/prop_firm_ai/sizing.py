from __future__ import annotations

from .domain import AnalyzerSignal, Confidence, RiskConfig, SizingDecision


def calculate_position_size(
    signal: AnalyzerSignal,
    risk_config: RiskConfig,
    entry_price: float,
    stop_price: float,
) -> SizingDecision:
    if entry_price <= 0:
        return SizingDecision(False, signal.symbol, 0, 0, 0, 0, 0, [], "entry price must be positive")

    raw_stop_distance = abs(entry_price - stop_price)
    min_stop_distance = signal.atr * risk_config.min_stop_distance_atr
    stop_distance = max(raw_stop_distance, min_stop_distance)

    if stop_distance <= 0:
        return SizingDecision(False, signal.symbol, 0, 0, 0, 0, 0, [], "stop distance must be positive")

    confidence_multiplier = {
        Confidence.HIGH: 1.0,
        Confidence.MEDIUM: 0.6,
        Confidence.LOW: 0.25,
    }[signal.confidence]

    reductions: list[str] = []
    if signal.spread_bps > 20:
        confidence_multiplier *= 0.5
        reductions.append("reduced for wide spread")
    if signal.earnings_proximity_flag:
        confidence_multiplier *= 0.5
        reductions.append("reduced for earnings proximity")

    risk_dollars = risk_config.equity * risk_config.risk_per_trade_pct * confidence_multiplier
    risk_quantity = int(risk_dollars / stop_distance)

    adv_shares_cap = int(signal.average_daily_volume * risk_config.max_adv_participation_pct)
    quantity = max(0, min(risk_quantity, adv_shares_cap))

    if quantity <= 0:
        return SizingDecision(
            approved=False,
            symbol=signal.symbol,
            quantity=0,
            notional=0,
            risk_dollars=risk_dollars,
            stop_distance=stop_distance,
            confidence_multiplier=confidence_multiplier,
            reductions=reductions,
            rejection_reason="position size rounded to zero",
        )

    return SizingDecision(
        approved=True,
        symbol=signal.symbol,
        quantity=quantity,
        notional=quantity * entry_price,
        risk_dollars=risk_dollars,
        stop_distance=stop_distance,
        confidence_multiplier=confidence_multiplier,
        reductions=reductions,
    )
