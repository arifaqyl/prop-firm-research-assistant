from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from .domain import AnalyzerSignal, Confidence, DirectionCall, OrderSide


class SignalMessageType(StrEnum):
    STRATEGY = "strategy"
    OPERATION = "operation"
    DISCUSSION = "discussion"


class Market(StrEnum):
    US_STOCK = "us-stock"
    GOLD = "gold"
    CRYPTO = "crypto"
    FOREX = "forex"


@dataclass(frozen=True)
class PublishedSignal:
    id: str
    message_type: SignalMessageType
    market: Market
    symbol: str | None
    title: str
    content: str
    tags: list[str]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    side: OrderSide | None = None
    price: float | None = None
    quantity: float | None = None
    executed_at: datetime | None = None
    source_analysis_id: str | None = None


@dataclass(frozen=True)
class ExtractedPrediction:
    direction: DirectionCall
    target_price: float | None
    target_probability: float | None
    confidence: float | None
    evidence_keywords: list[str]
    model_version: str = "community-heuristic-v1"


@dataclass(frozen=True)
class SignalQualityScore:
    signal_id: str
    verifiability_score: float
    evidence_score: float
    specificity_score: float
    novelty_score: float
    risk_score: float
    overall_score: float
    model_version: str = "community-heuristic-v1"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketIntelSnapshot:
    available: bool
    last_updated_at: datetime | None
    news_status: str
    headline_count: int
    macro_verdict: str | None = None
    latest_headline: str | None = None
    categories: list[dict[str, Any]] = field(default_factory=list)

    def warnings(self, *, max_age_minutes: int = 90) -> list[str]:
        warnings: list[str] = []
        if not self.available:
            warnings.append("market-intel snapshot unavailable")
        if self.last_updated_at is None:
            warnings.append("market-intel timestamp missing")
        else:
            age_minutes = (datetime.now(timezone.utc) - self.last_updated_at).total_seconds() / 60
            if age_minutes > max_age_minutes:
                warnings.append(f"market-intel snapshot stale: {age_minutes:.0f}m old")
        return warnings


@dataclass(frozen=True)
class HeartbeatMessage:
    id: str
    type: str
    content: str
    data: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class HeartbeatInbox:
    def __init__(self) -> None:
        self._messages: list[HeartbeatMessage] = []
        self._read_ids: set[str] = set()

    def push(self, message_type: str, content: str, data: dict[str, Any] | None = None) -> HeartbeatMessage:
        message = HeartbeatMessage(str(uuid4()), message_type, content, data or {})
        self._messages.append(message)
        return message

    def poll(self, limit: int = 50) -> dict[str, Any]:
        unread = [message for message in self._messages if message.id not in self._read_ids]
        batch = unread[: max(1, min(limit, 50))]
        for message in batch:
            self._read_ids.add(message.id)
        return {
            "messages": batch,
            "message_count": len(batch),
            "remaining_unread_count": max(0, len(unread) - len(batch)),
            "has_more_messages": len(unread) > len(batch),
            "recommended_poll_interval_seconds": 60,
            "server_time": datetime.now(timezone.utc),
        }


class SignalStore:
    def __init__(self) -> None:
        self.signals: dict[str, PublishedSignal] = {}
        self._normalized_content: set[str] = set()

    def publish(self, signal: PublishedSignal) -> PublishedSignal:
        self.signals[signal.id] = signal
        self._normalized_content.add(normalize_content(signal.content))
        return signal

    def is_duplicate(self, content: str) -> bool:
        normalized = normalize_content(content)
        return bool(normalized and normalized in self._normalized_content)

    def feed(self, *, message_type: SignalMessageType | None = None, symbol: str | None = None) -> list[PublishedSignal]:
        values = list(self.signals.values())
        if message_type:
            values = [signal for signal in values if signal.message_type == message_type]
        if symbol:
            values = [signal for signal in values if signal.symbol == symbol.upper()]
        return sorted(values, key=lambda signal: signal.created_at, reverse=True)


def build_strategy_signal(signal: AnalyzerSignal, gate_summary: dict[str, Any]) -> PublishedSignal:
    direction = signal.direction_call.value
    probability = signal.probabilities.get("up" if signal.direction_call == DirectionCall.BULLISH else "down", 0.0)
    title = f"{signal.symbol} {direction} setup, {signal.primary_horizon}"
    content = (
        f"Direction: {direction}. "
        f"Probability: {probability:.0%}. "
        f"Regime: {signal.regime}. "
        f"Brier skill score: {signal.brier_skill_score:.3f}. "
        f"Sample size: {signal.sample_size}. "
        f"Risk: invalid if confidence gates or data freshness fail. "
        f"Evidence: model_version={signal.model_version}, prompt_version={signal.prompt_version}. "
        f"Gate: {gate_summary}."
    )
    return PublishedSignal(
        id=str(uuid4()),
        message_type=SignalMessageType.STRATEGY,
        market=Market.US_STOCK if signal.asset_type == "stock" else Market.GOLD,
        symbol=signal.symbol.upper(),
        title=title,
        content=content,
        tags=[signal.asset_type, signal.regime, signal.primary_horizon, "evidence-backed"],
        source_analysis_id=f"{signal.symbol}:{signal.model_version}:{signal.prompt_version}",
    )


def build_operation_signal(
    *,
    symbol: str,
    side: OrderSide,
    price: float,
    quantity: float,
    content: str,
    market: Market = Market.US_STOCK,
) -> PublishedSignal:
    return PublishedSignal(
        id=str(uuid4()),
        message_type=SignalMessageType.OPERATION,
        market=market,
        symbol=symbol.upper(),
        title=f"{symbol.upper()} {side.value}",
        content=content,
        tags=["operation", "paper-execution"],
        side=side,
        price=price,
        quantity=quantity,
        executed_at=datetime.now(timezone.utc),
    )


def extract_prediction_from_signal(signal: PublishedSignal) -> ExtractedPrediction:
    content = " ".join([signal.title, signal.content, signal.symbol or "", " ".join(signal.tags)])
    lower = content.lower()
    if any(word in lower for word in ("buy", "long", "bull", "bullish", "upside", "breakout")):
        direction = DirectionCall.BULLISH
    elif any(word in lower for word in ("sell", "short", "bear", "bearish", "downside", "breakdown")):
        direction = DirectionCall.BEARISH
    elif any(word in lower for word in ("hold", "neutral", "range", "sideways")):
        direction = DirectionCall.NEUTRAL
    else:
        direction = DirectionCall.NO_EDGE

    price_match = re.search(r"(?:target|tp|price)\D{0,12}([0-9]+(?:\.[0-9]+)?)", content, flags=re.IGNORECASE)
    probability_match = re.search(r"([0-9]{1,3})(?:\s?%|\s?percent)", content, flags=re.IGNORECASE)
    confidence_match = re.search(r"(?:confidence|conf)\D{0,12}([0-9]+(?:\.[0-9]+)?)", content, flags=re.IGNORECASE)

    probability = None
    if probability_match:
        probability = min(float(probability_match.group(1)) / 100.0, 1.0)
    confidence = None
    if confidence_match:
        raw = float(confidence_match.group(1))
        confidence = min(raw / 100.0 if raw > 1 else raw, 1.0)

    keywords = [word for word in ("because", "risk", "evidence", "data", "chart", "catalyst", "regime") if word in lower]
    return ExtractedPrediction(
        direction=direction,
        target_price=float(price_match.group(1)) if price_match else None,
        target_probability=probability,
        confidence=confidence,
        evidence_keywords=keywords,
    )


def score_signal_quality(signal: PublishedSignal, *, duplicate: bool = False) -> SignalQualityScore:
    prediction = extract_prediction_from_signal(signal)
    content = normalize_content(signal.content)
    verifiability = 1.0
    if prediction.direction != DirectionCall.NO_EDGE:
        verifiability += 1.2
    if signal.symbol:
        verifiability += 0.8
    if prediction.target_price is not None or prediction.target_probability is not None:
        verifiability += 1.2

    evidence = min(5.0, len(content) / 160.0 + len(prediction.evidence_keywords) * 0.7)
    specificity = 1.0 + (1.0 if signal.symbol else 0.0) + (1.0 if signal.tags else 0.0) + min(len(content) / 320.0, 2.0)
    novelty = 2.0 if duplicate else 5.0
    risk_score = 5.0 if any(word in content for word in ("risk", "invalid", "stop", "drawdown")) else 1.0
    overall = (verifiability * 0.25) + (evidence * 0.25) + (specificity * 0.2) + (novelty * 0.15) + (risk_score * 0.15)

    return SignalQualityScore(
        signal_id=signal.id,
        verifiability_score=clamp_score(verifiability),
        evidence_score=clamp_score(evidence),
        specificity_score=clamp_score(specificity),
        novelty_score=clamp_score(novelty),
        risk_score=clamp_score(risk_score),
        overall_score=clamp_score(overall),
        metadata={
            "prediction_direction": prediction.direction.value,
            "target_probability": prediction.target_probability,
            "evidence_keywords": prediction.evidence_keywords,
            "duplicate": duplicate,
        },
    )


def normalize_content(content: str) -> str:
    return " ".join((content or "").lower().split())


def clamp_score(value: float) -> float:
    return round(max(0.0, min(5.0, value)), 4)
