from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from .confidence import evaluate_confidence_gate
from .domain import DirectionCall, ModelConfig
from .market_data import Candle, MarketSnapshot, build_signal_from_snapshot, fetch_market_snapshot


@dataclass(frozen=True)
class SimulatedTrade:
    symbol: str
    entered_at: str
    exited_at: str
    direction: str
    entry: float
    exit: float
    stop: float
    target: float
    outcome: str
    r_multiple: float
    probability: float
    regime: str
    confidence: str


def run_paper_simulation(
    symbol: str,
    range_: str = "5y",
    interval: str = "1d",
    lookback: int = 80,
    horizon: int = 15,
    max_trades: int = 5000,
    model_config: ModelConfig | None = None,
    direction_filter: str | None = None,
    regime_filter: str | None = None,
    exclude_crypto: bool = False,
) -> dict[str, Any]:
    """Replay historical candles forward and resolve gated paper trades.

    This is not a trained backtest yet. It replays the current heuristic analyzer
    without lookahead so the user can see whether the existing rules have any
    basic historical behavior worth improving.
    """
    model_config = model_config or ModelConfig()
    snapshot = fetch_market_snapshot(symbol, interval=interval, range_=range_)
    
    if exclude_crypto and snapshot.asset_type == "crypto":
        return {
            "symbol": snapshot.requested_symbol,
            "provider_symbol": snapshot.provider_symbol,
            "source": snapshot.source,
            "range": range_,
            "interval": interval,
            "lookback_bars": lookback,
            "horizon_bars": horizon,
            "candles": len(snapshot.candles),
            "tested_setups": 0,
            "approved_setups": 0,
            "blocked_or_no_edge": 0,
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "average_r": 0.0,
            "expectancy_r": 0.0,
            "total_r": 0.0,
            "profit_factor": None,
            "max_drawdown_r": 0.0,
            "by_direction": {},
            "by_regime": {},
            "scorecards": {},
            "walk_forward": {},
            "equity_curve": [],
            "drawdown_curve": [],
            "recent_trades": [],
            "summary": f"{snapshot.requested_symbol}: excluded (crypto symbol excluded by filter).",
            "_trades_objects": [],
        }

    candles = snapshot.candles
    trades: list[SimulatedTrade] = []
    gate_counts = {"tested_setups": 0, "no_edge_or_blocked": 0, "approved": 0}
    start = max(lookback, 30)
    end = max(start, len(candles) - horizon - 1)

    for index in range(start, end):
        gate_counts["tested_setups"] += 1
        history = candles[index - lookback : index + 1]
        signal_snapshot = MarketSnapshot(
            requested_symbol=snapshot.requested_symbol,
            provider_symbol=snapshot.provider_symbol,
            asset_type=snapshot.asset_type,
            source=f"{snapshot.source} replay cutoff {history[-1].timestamp.date().isoformat()}",
            fetched_at=history[-1].timestamp,
            candles=history,
        )
        signal = build_signal_from_snapshot(signal_snapshot)

        # Apply regime filter
        if regime_filter and signal.regime != regime_filter:
            gate_counts["no_edge_or_blocked"] += 1
            continue

        # Apply direction filter
        if direction_filter:
            expected_direction = DirectionCall.BEARISH if direction_filter.upper() == "SELL" else DirectionCall.BULLISH
            if signal.direction_call != expected_direction:
                gate_counts["no_edge_or_blocked"] += 1
                continue

        gate = evaluate_confidence_gate(signal, model_config)
        if not gate.approved or signal.direction_call not in {DirectionCall.BULLISH, DirectionCall.BEARISH}:
            gate_counts["no_edge_or_blocked"] += 1
            continue

        gate_counts["approved"] += 1
        future = candles[index + 1 : index + horizon + 1]
        trades.append(_resolve_trade(signal, history[-1], future))
        if len(trades) >= max_trades:
            break

    summary_dict = _summarize(snapshot, trades, gate_counts, range_, interval, lookback, horizon)
    summary_dict["_trades_objects"] = trades
    return summary_dict


def run_watchlist_simulation(symbols: list[str], **kwargs: Any) -> dict[str, Any]:
    results = []
    all_trades: list[SimulatedTrade] = []

    for symbol in symbols:
        try:
            res = run_paper_simulation(symbol, **kwargs)
            trades_objs = res.pop("_trades_objects", [])
            all_trades.extend(trades_objs)
            results.append(res)
        except Exception as exc:  # pragma: no cover - provider failures vary
            results.append(
                {
                    "symbol": symbol,
                    "error": str(exc),
                    "trades": 0,
                    "win_rate": 0,
                    "expectancy_r": 0,
                    "total_r": 0,
                    "summary": f"{symbol}: simulation failed: {exc}",
                }
            )

    # Sort all trades chronologically by entered_at
    all_trades.sort(key=lambda t: t.entered_at)

    # Compute scorecards for different slices
    scorecards = {
        "all": _compute_scorecard(all_trades),
        "long_only": _compute_scorecard([t for t in all_trades if t.direction == "BUY"]),
        "short_only": _compute_scorecard([t for t in all_trades if t.direction == "SELL"]),
        "trending_up_only": _compute_scorecard([t for t in all_trades if t.regime == "trending_up"]),
        "high_volatility_only": _compute_scorecard([t for t in all_trades if t.regime == "high_volatility"]),
    }

    # Compute walk-forward splits on all portfolio trades
    n = len(all_trades)
    train_end = int(n * 0.5)
    val_end = int(n * 0.75)

    walk_forward = {
        "train": _compute_scorecard(all_trades[:train_end]),
        "validation": _compute_scorecard(all_trades[train_end:val_end]),
        "out_of_sample": _compute_scorecard(all_trades[val_end:]),
    }

    # Compute cumulative equity and drawdown curve
    equity_curve = []
    drawdown_curve = []
    current_equity = 0.0
    peak = 0.0
    for t in all_trades:
        current_equity += t.r_multiple
        peak = max(peak, current_equity)
        dd = current_equity - peak
        equity_curve.append(round(current_equity, 4))
        drawdown_curve.append(round(dd, 4))

    ranked = sorted(results, key=lambda item: (item.get("expectancy_r", -999), item.get("win_rate", 0)), reverse=True)
    total_trades = len(all_trades)
    total_wins = sum(1 for t in all_trades if t.r_multiple > 0)
    total_r = sum(t.r_multiple for t in all_trades)

    return {
        "symbols": symbols,
        "results": ranked,
        "portfolio": {
            "trades": total_trades,
            "wins": total_wins,
            "losses": total_trades - total_wins,
            "win_rate": round(total_wins / total_trades, 4) if total_trades else 0,
            "total_r": round(total_r, 4),
            "average_r": round(total_r / total_trades, 4) if total_trades else 0,
            "best_symbol": ranked[0]["symbol"] if ranked and "symbol" in ranked[0] else None,
            "worst_symbol": ranked[-1]["symbol"] if ranked and "symbol" in ranked[-1] else None,
            "scorecards": scorecards,
            "walk_forward": walk_forward,
            "equity_curve": equity_curve,
            "drawdown_curve": drawdown_curve,
        },
        "warnings": [
            "Simulation uses the current heuristic analyzer, not a trained model.",
            "Yahoo Finance candles can be adjusted/delayed and are not broker-grade fills.",
            "Same-candle stop/target conflicts are resolved as stop-first.",
        ],
    }


def _resolve_trade(signal, entry_candle: Candle, future: list[Candle]) -> SimulatedTrade:
    direction = signal.direction_call
    entry = entry_candle.close
    stop_distance = max(signal.atr * 2, entry * 0.01, 0.01)
    target_distance = signal.atr * (4 if signal.model_version.startswith("daily-trend-v2") else 3)
    if direction == DirectionCall.BEARISH:
        stop = entry + stop_distance
        target = max(entry - target_distance, 0.01)
        probability = signal.probabilities.get("down", 0)
    else:
        stop = max(entry - stop_distance, 0.01)
        target = entry + target_distance
        probability = signal.probabilities.get("up", 0)

    exit_price = future[-1].close
    exit_time = future[-1].timestamp
    outcome = "expiry_loss"
    for candle in future:
        if direction == DirectionCall.BEARISH:
            stopped = candle.high >= stop
            targeted = candle.low <= target
        else:
            stopped = candle.low <= stop
            targeted = candle.high >= target
        if stopped:
            exit_price = stop
            exit_time = candle.timestamp
            outcome = "stop"
            break
        if targeted:
            exit_price = target
            exit_time = candle.timestamp
            outcome = "target"
            break

    raw_r = ((entry - exit_price) if direction == DirectionCall.BEARISH else (exit_price - entry)) / stop_distance
    if outcome.startswith("expiry") and raw_r > 0:
        outcome = "expiry_win"
    slippage_cost_r = (entry * (signal.spread_bps / 10_000) * 2) / stop_distance
    r_multiple = raw_r - slippage_cost_r
    return SimulatedTrade(
        symbol=signal.symbol,
        entered_at=entry_candle.timestamp.isoformat(),
        exited_at=exit_time.isoformat(),
        direction="SELL" if direction == DirectionCall.BEARISH else "BUY",
        entry=round(entry, 6),
        exit=round(exit_price, 6),
        stop=round(stop, 6),
        target=round(target, 6),
        outcome=outcome,
        r_multiple=round(r_multiple, 4),
        probability=probability,
        regime=signal.regime,
        confidence=signal.confidence.value,
    )


def _summarize(
    snapshot: MarketSnapshot,
    trades: list[SimulatedTrade],
    gate_counts: dict[str, int],
    range_: str,
    interval: str,
    lookback: int,
    horizon: int,
) -> dict[str, Any]:
    wins = [trade for trade in trades if trade.r_multiple > 0]
    losses = [trade for trade in trades if trade.r_multiple <= 0]
    r_values = [trade.r_multiple for trade in trades]
    total_r = sum(r_values)
    gross_win_r = sum(value for value in r_values if value > 0)
    gross_loss_r = abs(sum(value for value in r_values if value <= 0))
    by_direction = _group_stats(trades, "direction")
    by_regime = _group_stats(trades, "regime")

    # Compute scorecards
    scorecards = {
        "all": _compute_scorecard(trades),
        "long_only": _compute_scorecard([t for t in trades if t.direction == "BUY"]),
        "short_only": _compute_scorecard([t for t in trades if t.direction == "SELL"]),
        "trending_up_only": _compute_scorecard([t for t in trades if t.regime == "trending_up"]),
        "high_volatility_only": _compute_scorecard([t for t in trades if t.regime == "high_volatility"]),
    }

    # Compute walk-forward splits
    n = len(trades)
    train_end = int(n * 0.5)
    val_end = int(n * 0.75)
    walk_forward = {
        "train": _compute_scorecard(trades[:train_end]),
        "validation": _compute_scorecard(trades[train_end:val_end]),
        "out_of_sample": _compute_scorecard(trades[val_end:]),
    }

    # Compute equity curve
    equity_curve = []
    drawdown_curve = []
    current_equity = 0.0
    peak = 0.0
    for t in trades:
        current_equity += t.r_multiple
        peak = max(peak, current_equity)
        dd = current_equity - peak
        equity_curve.append(round(current_equity, 4))
        drawdown_curve.append(round(dd, 4))

    return {
        "symbol": snapshot.requested_symbol,
        "provider_symbol": snapshot.provider_symbol,
        "source": snapshot.source,
        "range": range_,
        "interval": interval,
        "lookback_bars": lookback,
        "horizon_bars": horizon,
        "candles": len(snapshot.candles),
        "tested_setups": gate_counts["tested_setups"],
        "approved_setups": gate_counts["approved"],
        "blocked_or_no_edge": gate_counts["no_edge_or_blocked"],
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades), 4) if trades else 0,
        "average_r": round(mean(r_values), 4) if r_values else 0,
        "expectancy_r": round(mean(r_values), 4) if r_values else 0,
        "total_r": round(total_r, 4),
        "profit_factor": round(gross_win_r / gross_loss_r, 4) if gross_loss_r else None,
        "max_drawdown_r": round(_max_drawdown(r_values), 4),
        "by_direction": by_direction,
        "by_regime": by_regime,
        "scorecards": scorecards,
        "walk_forward": walk_forward,
        "equity_curve": equity_curve,
        "drawdown_curve": drawdown_curve,
        "recent_trades": [trade.__dict__ for trade in trades[-12:]][::-1],
        "summary": _summary_line(snapshot.requested_symbol, trades, wins, total_r),
    }


def _summary_line(symbol: str, trades: list[SimulatedTrade], wins: list[SimulatedTrade], total_r: float) -> str:
    if not trades:
        return f"{symbol}: no gated paper trades triggered in the replay window."
    win_rate = len(wins) / len(trades)
    verdict = "positive" if total_r > 0 else "negative"
    return f"{symbol}: {len(trades)} trades, {win_rate:.1%} win rate, {total_r:.2f}R total, {verdict} expectancy."


def _group_stats(trades: list[SimulatedTrade], field: str) -> dict[str, dict[str, float]]:
    groups: dict[str, list[SimulatedTrade]] = {}
    for trade in trades:
        key = getattr(trade, field)
        groups.setdefault(key, []).append(trade)
    return {
        key: {
            "trades": len(values),
            "win_rate": round(sum(1 for trade in values if trade.r_multiple > 0) / len(values), 4),
            "average_r": round(mean(trade.r_multiple for trade in values), 4),
            "total_r": round(sum(trade.r_multiple for trade in values), 4),
        }
        for key, values in groups.items()
    }


def _max_drawdown(r_values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in r_values:
        equity += value
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return max_dd


def _compute_scorecard(trades: list[SimulatedTrade]) -> dict[str, Any]:
    wins = [trade for trade in trades if trade.r_multiple > 0]
    losses = [trade for trade in trades if trade.r_multiple <= 0]
    r_values = [trade.r_multiple for trade in trades]
    total_r = sum(r_values)
    win_rate = len(wins) / len(trades) if trades else 0.0
    average_r = mean(r_values) if r_values else 0.0
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 4),
        "total_r": round(total_r, 4),
        "average_r": round(average_r, 4),
        "max_drawdown_r": round(_max_drawdown(r_values), 4),
    }
