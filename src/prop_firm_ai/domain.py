from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


class DirectionCall(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    NO_EDGE = "no_edge"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    BRACKET = "bracket"


class ExecutionMode(StrEnum):
    PAPER = "paper"
    MICRO_LIVE = "micro_live"
    FULL_LIVE = "full_live"


class OrderStatus(StrEnum):
    NEW = "new"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELED = "canceled"
    EXPIRED = "expired"


@dataclass(frozen=True)
class DataHealth:
    symbol: str
    latest_candle_at: datetime
    max_age_hours: float = 30.0
    source: str = "unknown"
    partial: bool = False
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def age_hours(self) -> float:
        return (self.checked_at - self.latest_candle_at).total_seconds() / 3600

    @property
    def is_stale(self) -> bool:
        import os
        if os.getenv("BYPASS_FRESHNESS_GATE", "").lower() in {"1", "true", "yes"}:
            return False
        return self.partial or self.age_hours > self.max_age_hours

    @property
    def warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.partial:
            warnings.append("data source returned a partial response")
        import os
        bypass_freshness = os.getenv("BYPASS_FRESHNESS_GATE", "").lower() in {"1", "true", "yes"}
        if self.age_hours > self.max_age_hours:
            if bypass_freshness:
                warnings.append(f"latest candle is stale: {self.age_hours:.1f}h old (bypassed by config)")
            else:
                warnings.append(f"latest candle is stale: {self.age_hours:.1f}h old")
        return warnings


@dataclass(frozen=True)
class AnalyzerSignal:
    symbol: str
    asset_type: str
    direction_call: DirectionCall
    confidence: Confidence
    primary_horizon: str
    probabilities: dict[str, float]
    sample_size: int
    brier_skill_score: float
    regime: str
    data_health: DataHealth
    latest_price: float
    atr: float
    average_daily_volume: float
    spread_bps: float
    expected_edge: float
    model_version: str
    prompt_version: str = "v1"
    earnings_proximity_flag: bool = False
    source_ids_used: list[str] = field(default_factory=list)
    rsi: float | None = None
    macd: dict[str, float] | None = None
    adx: float | None = None
    bollinger: dict[str, float] | None = None



@dataclass(frozen=True)
class ConfidenceGateResult:
    approved: bool
    direction_call: DirectionCall
    confidence: Confidence
    reasons: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class ModelConfig:
    high_probability_threshold: float = 0.65
    medium_probability_threshold: float = 0.57
    high_min_sample_size: int = 100
    medium_min_sample_size: int = 50
    min_brier_skill_score: float = 0.0
    stale_data_max_age_hours: float = 30.0
    max_spread_bps_for_market_order: float = 15.0
    min_adv_dollars: float = 5_000_000


@dataclass(frozen=True)
class RiskConfig:
    equity: float = 100_000.0
    risk_per_trade_pct: float = 0.005
    daily_reduce_size_drawdown_pct: float = 0.02
    daily_halt_drawdown_pct: float = 0.05
    weekly_halt_drawdown_pct: float = 0.08
    max_gross_exposure_pct: float = 1.5
    max_net_exposure_pct: float = 1.0
    max_symbol_exposure_pct: float = 0.20
    max_sector_exposure_pct: float = 0.25
    max_adv_participation_pct: float = 0.01
    max_market_order_spread_bps: float = 15.0
    min_stop_distance_atr: float = 0.5
    live_trading_enabled: bool = False


@dataclass
class Position:
    symbol: str
    quantity: float
    average_price: float
    sector: str = "unknown"

    @property
    def market_value(self) -> float:
        return self.quantity * self.average_price


@dataclass
class PortfolioState:
    equity: float
    cash: float
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    kill_switch_active: bool = False

    @property
    def gross_exposure(self) -> float:
        return sum(abs(position.market_value) for position in self.positions.values())

    @property
    def net_exposure(self) -> float:
        return sum(position.market_value for position in self.positions.values())


@dataclass(frozen=True)
class SizingDecision:
    approved: bool
    symbol: str
    quantity: int
    notional: float
    risk_dollars: float
    stop_distance: float
    confidence_multiplier: float
    reductions: list[str]
    rejection_reason: str | None = None


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    size_multiplier: float
    reasons: list[str]
    violations: list[str]


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType
    mode: ExecutionMode = ExecutionMode.PAPER
    limit_price: float | None = None
    stop_price: float | None = None
    client_order_id: str = field(default_factory=lambda: str(uuid4()))
    strategy_id: str = "default"


@dataclass
class Order:
    id: str
    request: OrderRequest
    status: OrderStatus
    created_at: datetime
    updated_at: datetime
    filled_quantity: int = 0
    average_fill_price: float | None = None
    rejection_reason: str | None = None


@dataclass(frozen=True)
class Fill:
    id: str
    order_id: str
    symbol: str
    quantity: int
    expected_price: float
    fill_price: float
    filled_at: datetime

    @property
    def slippage_bps(self) -> float:
        if self.expected_price <= 0:
            return 0.0
        return ((self.fill_price - self.expected_price) / self.expected_price) * 10_000


@dataclass(frozen=True)
class ExecutionQuality:
    order_id: str
    symbol: str
    expected_price: float
    average_fill_price: float | None
    requested_quantity: int
    filled_quantity: int
    spread_bps_at_order: float
    realized_slippage_bps: float | None
    missed_quantity: int


@dataclass(frozen=True)
class AuditEntry:
    id: str
    timestamp: datetime
    event_type: str
    payload: dict[str, Any]
    previous_hash: str
    hash: str
