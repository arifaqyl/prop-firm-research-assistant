from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Any

from .market_data import fetch_market_snapshot


@dataclass(frozen=True)
class PairSpreadResult:
    pair: str
    left_symbol: str
    right_symbol: str
    z_score: float
    spread: float
    mean_spread: float
    std_spread: float
    signal: str
    decision: str
    checked_at: str
    observations: int
    warning: str | None = None


def scan_pair(left: str = "GLD", right: str = "GOLD", interval: str = "1d", range_: str = "1y") -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        left_snapshot = fetch_market_snapshot(left, interval=interval, range_=range_)
        right_snapshot = fetch_market_snapshot(right, interval=interval, range_=range_)
        left_closes = [candle.close for candle in left_snapshot.candles]
        right_closes = [candle.close for candle in right_snapshot.candles]
        length = min(len(left_closes), len(right_closes))
        if length < 30:
            raise ValueError("not enough paired observations")
        left_norm = _normalize(left_closes[-length:])
        right_norm = _normalize(right_closes[-length:])
        spreads = [left_value - right_value for left_value, right_value in zip(left_norm, right_norm)]
        current = spreads[-1]
        avg = mean(spreads)
        std = pstdev(spreads) or 1e-9
        z_score = (current - avg) / std
        if z_score > 2:
            signal = f"SHORT {left.upper()} / LONG {right.upper()}"
            decision = "PAIR_TRADE_WATCH"
        elif z_score < -2:
            signal = f"LONG {left.upper()} / SHORT {right.upper()}"
            decision = "PAIR_TRADE_WATCH"
        else:
            signal = "spread inside normal band"
            decision = "NO_TRADE"
        result = PairSpreadResult(
            pair=f"{left.upper()}:{right.upper()}",
            left_symbol=left.upper(),
            right_symbol=right.upper(),
            z_score=round(z_score, 4),
            spread=round(current, 6),
            mean_spread=round(avg, 6),
            std_spread=round(std, 6),
            signal=signal,
            decision=decision,
            checked_at=checked_at,
            observations=length,
        )
        return result.__dict__
    except Exception as exc:  # pragma: no cover - provider state varies
        return PairSpreadResult(
            pair=f"{left.upper()}:{right.upper()}",
            left_symbol=left.upper(),
            right_symbol=right.upper(),
            z_score=0,
            spread=0,
            mean_spread=0,
            std_spread=0,
            signal="unavailable",
            decision="NO_TRADE",
            checked_at=checked_at,
            observations=0,
            warning=str(exc),
        ).__dict__


def scan_default_pairs() -> dict[str, Any]:
    pairs = [("GLD", "GOLD"), ("BTC-USD", "ETH-USD")]
    results = [scan_pair(left, right) for left, right in pairs]
    return {
        "mode": "monitor_only",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "pairs": results,
        "actionable_count": sum(1 for item in results if item.get("decision") != "NO_TRADE"),
        "rule": "Flag pair-trade watch when normalized spread exceeds +/-2 standard deviations.",
    }


def _normalize(values: list[float]) -> list[float]:
    first = values[0] or 1
    return [value / first for value in values]
