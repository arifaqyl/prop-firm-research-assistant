from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import pstdev
from typing import Any

import requests

try:
    import websockets
except ModuleNotFoundError:  # pragma: no cover
    websockets = None


BINANCE_BASE = "https://api.binance.com"
BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"
POLYMARKET_CLOB_BASE = "https://clob.polymarket.com"
POLYMARKET_GAMMA_BASE = "https://gamma-api.polymarket.com"
POLYMARKET_MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


@dataclass(frozen=True)
class BookTop:
    venue: str
    symbol: str
    bid: float | None
    ask: float | None
    bid_size: float | None
    ask_size: float | None
    midpoint: float | None
    spread: float | None
    observed_at: str
    latency_ms: float
    source: str


@dataclass(frozen=True)
class StreamBookEvent:
    venue: str
    symbol: str
    event_type: str
    bid: float | None
    ask: float | None
    spread: float | None
    received_at: str
    source: str
    bid_size: float | None = None
    ask_size: float | None = None
    bid_depth_notional: float | None = None
    ask_depth_notional: float | None = None
    depth_imbalance: float | None = None


@dataclass(frozen=True)
class DepthSnapshot:
    venue: str
    symbol: str
    levels: int
    bid: float | None
    ask: float | None
    midpoint: float | None
    spread: float | None
    spread_bps: float | None
    bid_size: float | None
    ask_size: float | None
    bid_depth_notional: float
    ask_depth_notional: float
    depth_imbalance: float
    observed_at: str
    source: str


def binance_book_top(symbol: str = "BTCUSDT") -> BookTop:
    requested_at = datetime.now(timezone.utc)
    response = requests.get(f"{BINANCE_BASE}/api/v3/ticker/bookTicker", params={"symbol": symbol.upper()}, timeout=8)
    response.raise_for_status()
    observed_at = datetime.now(timezone.utc)
    payload = response.json()
    bid = float(payload["bidPrice"])
    ask = float(payload["askPrice"])
    spread = ask - bid
    return BookTop(
        venue="binance",
        symbol=payload.get("symbol", symbol.upper()),
        bid=bid,
        ask=ask,
        bid_size=float(payload.get("bidQty", 0)),
        ask_size=float(payload.get("askQty", 0)),
        midpoint=(bid + ask) / 2,
        spread=spread,
        observed_at=observed_at.isoformat(),
        latency_ms=(observed_at - requested_at).total_seconds() * 1000,
        source="GET /api/v3/ticker/bookTicker",
    )


def polymarket_book_top(token_id: str | None = None) -> BookTop:
    requested_at = datetime.now(timezone.utc)
    if not token_id:
        return BookTop(
            venue="polymarket",
            symbol="token_id_required",
            bid=None,
            ask=None,
            bid_size=None,
            ask_size=None,
            midpoint=None,
            spread=None,
            observed_at=requested_at.isoformat(),
            latency_ms=0,
            source="CLOB token_id not provided",
        )
    response = requests.get(f"{POLYMARKET_CLOB_BASE}/book", params={"token_id": token_id}, timeout=8)
    response.raise_for_status()
    observed_at = datetime.now(timezone.utc)
    payload = response.json()
    bids = payload.get("bids") or []
    asks = payload.get("asks") or []
    best_bid = _best_level(bids, reverse=True)
    best_ask = _best_level(asks, reverse=False)
    bid = best_bid[0] if best_bid else None
    ask = best_ask[0] if best_ask else None
    return BookTop(
        venue="polymarket",
        symbol=token_id,
        bid=bid,
        ask=ask,
        bid_size=best_bid[1] if best_bid else None,
        ask_size=best_ask[1] if best_ask else None,
        midpoint=(bid + ask) / 2 if bid is not None and ask is not None else None,
        spread=ask - bid if bid is not None and ask is not None else None,
        observed_at=observed_at.isoformat(),
        latency_ms=(observed_at - requested_at).total_seconds() * 1000,
        source="GET https://clob.polymarket.com/book",
    )


def polymarket_market_search(query: str = "bitcoin", limit: int = 8) -> dict[str, Any]:
    requested = query.strip() or "bitcoin"
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        response = requests.get(
            f"{POLYMARKET_GAMMA_BASE}/events",
            params={"search": requested, "active": "true", "closed": "false", "limit": min(max(limit, 1), 20)},
            timeout=12,
            headers={"User-Agent": "prop-firm-ai/0.1"},
        )
        response.raise_for_status()
        events = response.json()
        markets = _extract_polymarket_markets(events, max_markets=min(max(limit, 1), 20))
        return {
            "mode": "free_gamma_api",
            "query": requested,
            "checked_at": checked_at,
            "status": "active" if markets else "no_markets",
            "decision": "NO_TRADE",
            "markets": markets,
            "warnings": [
                "Market discovery is public/no-key and does not place orders.",
                "Use the YES token id for CLOB book/stream probes only after checking market rules and jurisdiction.",
            ],
            "source": f"{POLYMARKET_GAMMA_BASE}/events",
        }
    except Exception as exc:  # pragma: no cover - provider state varies
        return {
            "mode": "free_gamma_api",
            "query": requested,
            "checked_at": checked_at,
            "status": "provider_error",
            "decision": "NO_TRADE",
            "markets": [],
            "warnings": [str(exc)],
            "source": f"{POLYMARKET_GAMMA_BASE}/events",
        }


def latency_gap_scan(binance_symbol: str = "BTCUSDT", polymarket_token_id: str | None = None) -> dict[str, Any]:
    binance = _safe_book(lambda: binance_book_top(binance_symbol), "binance", binance_symbol)
    polymarket = _safe_book(lambda: polymarket_book_top(polymarket_token_id), "polymarket", polymarket_token_id or "token_id_required")
    latency_gap = None
    if binance.get("latency_ms") is not None and polymarket.get("latency_ms") is not None:
        latency_gap = round(polymarket["latency_ms"] - binance["latency_ms"], 3)
    executable = bool(polymarket_token_id) and binance.get("error") is None and polymarket.get("error") is None
    return {
        "mode": "monitor_only",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "binance": binance,
        "polymarket": polymarket,
        "latency_gap_ms": latency_gap,
        "status": "ready_for_observation" if executable else "needs_polymarket_token_id",
        "decision": "NO_TRADE",
        "warnings": [
            "This endpoint does not place orders.",
            "Latency gaps are observations, not guaranteed arbitrage.",
            "Polymarket trading requires authentication, geographic compliance, and explicit live-mode controls.",
        ],
        "websocket_plan": {
            "binance_l2": f"{BINANCE_WS_BASE}/{binance_symbol.lower()}@depth5@100ms",
            "polymarket": POLYMARKET_MARKET_WS,
        },
    }


def _extract_polymarket_markets(events: list[dict[str, Any]], max_markets: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        for market in event.get("markets") or []:
            if not market.get("enableOrderBook"):
                continue
            if not market.get("active", True) or market.get("closed", False):
                continue
            outcomes = _json_list(market.get("outcomes"))
            token_ids = _json_list(market.get("clobTokenIds"))
            prices = _json_list(market.get("outcomePrices"))
            yes_index = _find_outcome_index(outcomes, "Yes")
            no_index = _find_outcome_index(outcomes, "No")
            yes_token = token_ids[yes_index] if yes_index is not None and yes_index < len(token_ids) else token_ids[0] if token_ids else None
            no_token = token_ids[no_index] if no_index is not None and no_index < len(token_ids) else token_ids[1] if len(token_ids) > 1 else None
            rows.append(
                {
                    "event_id": event.get("id"),
                    "event_title": event.get("title") or event.get("ticker"),
                    "market_id": market.get("id"),
                    "question": market.get("question"),
                    "slug": market.get("slug"),
                    "end_date": market.get("endDate") or market.get("endDateIso"),
                    "liquidity": _optional_float(market.get("liquidityNum") or market.get("liquidity") or event.get("liquidity")),
                    "volume_24h": _optional_float(market.get("volume24hr") or market.get("volume24hrClob") or event.get("volume24hr")),
                    "outcomes": outcomes,
                    "outcome_prices": prices,
                    "yes_token_id": yes_token,
                    "no_token_id": no_token,
                    "best_yes_price": _optional_float(prices[yes_index]) if yes_index is not None and yes_index < len(prices) else None,
                    "best_no_price": _optional_float(prices[no_index]) if no_index is not None and no_index < len(prices) else None,
                    "restricted": bool(market.get("restricted") or event.get("restricted")),
                    "source": POLYMARKET_GAMMA_BASE,
                }
            )
    rows.sort(key=lambda item: (item.get("liquidity") or 0, item.get("volume_24h") or 0), reverse=True)
    return rows[:max_markets]


def _json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _find_outcome_index(outcomes: list[Any], name: str) -> int | None:
    target = name.lower()
    for index, outcome in enumerate(outcomes):
        if str(outcome).lower() == target:
            return index
    return None


async def dual_websocket_probe(
    binance_symbol: str = "BTCUSDT",
    polymarket_token_id: str | None = None,
    sample_seconds: float = 2.0,
    max_events: int = 5,
) -> dict[str, Any]:
    if websockets is None:
        return {
            "mode": "monitor_only",
            "status": "websockets_dependency_missing",
            "decision": "NO_TRADE",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "streams": [],
            "events": [],
            "warnings": ["Install the websockets dependency to enable live stream probes."],
        }

    tasks = [collect_binance_l2_stream(binance_symbol, levels=5, sample_seconds=sample_seconds, max_events=max_events)]
    if polymarket_token_id:
        tasks.append(collect_polymarket_market_stream(polymarket_token_id, sample_seconds, max_events))
    else:
        tasks.append(_skipped_polymarket_stream())
    streams = await asyncio.gather(*tasks)
    events = [event for stream in streams for event in stream.get("events", [])]
    polymarket = _safe_book(lambda: polymarket_book_top(polymarket_token_id), "polymarket", polymarket_token_id or "token_id_required")
    lag_candidate = score_lag_exploit_candidate(events, polymarket)
    return {
        "mode": "monitor_only",
        "status": "streaming_observed" if any(stream.get("events") for stream in streams) else "no_stream_events",
        "decision": "NO_TRADE",
        "lag_candidate": lag_candidate,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "streams": streams,
        "events": events[: max_events * 2],
        "warnings": [
            "This websocket probe never places orders.",
            "Use it to verify feed health before any future paper execution.",
            "Polymarket streaming requires valid asset token IDs.",
        ],
    }


async def collect_binance_bookticker_stream(symbol: str, sample_seconds: float = 2.0, max_events: int = 5) -> dict[str, Any]:
    url = f"{BINANCE_WS_BASE}/{symbol.lower()}@bookTicker"
    return await _collect_stream("binance", symbol.upper(), url, None, _parse_binance_stream_event, sample_seconds, max_events)


async def collect_binance_l2_stream(symbol: str, levels: int = 5, sample_seconds: float = 2.0, max_events: int = 5) -> dict[str, Any]:
    safe_levels = 20 if levels >= 20 else 5
    url = f"{BINANCE_WS_BASE}/{symbol.lower()}@depth{safe_levels}@100ms"
    parser = lambda raw: _parse_binance_depth_stream_event(raw, symbol.upper(), safe_levels)
    return await _collect_stream("binance_l2", symbol.upper(), url, None, parser, sample_seconds, max_events)


async def collect_polymarket_market_stream(token_id: str, sample_seconds: float = 2.0, max_events: int = 5) -> dict[str, Any]:
    subscribe = {"assets_ids": [token_id], "type": "market", "custom_feature_enabled": True}
    return await _collect_stream("polymarket", token_id, POLYMARKET_MARKET_WS, subscribe, _parse_polymarket_stream_event, sample_seconds, max_events)


def score_lag_exploit_candidate(
    events: list[dict[str, Any]],
    polymarket: dict[str, Any],
    min_impulse_bps: float = 8.0,
    min_edge: float = 0.08,
) -> dict[str, Any]:
    binance_events = [event for event in events if event.get("venue") in {"binance", "binance_l2"} and event.get("bid") and event.get("ask")]
    blockers: list[str] = []
    if len(binance_events) < 2:
        blockers.append("need at least two Binance L2 events to estimate a price impulse")
    poly_ask = polymarket.get("ask")
    poly_bid = polymarket.get("bid")
    if poly_ask is None:
        blockers.append("Polymarket YES ask unavailable; provide a valid asset token id")

    first_mid = _midpoint(binance_events[0]) if binance_events else None
    last_mid = _midpoint(binance_events[-1]) if binance_events else None
    impulse_bps = None
    if first_mid and last_mid:
        impulse_bps = ((last_mid - first_mid) / first_mid) * 10_000
    if impulse_bps is None or abs(impulse_bps) < min_impulse_bps:
        blockers.append(f"Binance impulse below {min_impulse_bps:g} bps threshold")

    true_probability = _probability_from_impulse(impulse_bps or 0)
    yes_edge = round(true_probability - float(poly_ask), 4) if poly_ask is not None else None
    no_edge = round((1 - true_probability) - float(poly_bid), 4) if poly_bid is not None else None
    if yes_edge is None or yes_edge < min_edge:
        blockers.append(f"estimated YES edge below {min_edge:.0%} threshold")

    observable = not blockers
    return {
        "mode": "monitor_only",
        "decision": "CANDIDATE" if observable else "OBSERVE_ONLY",
        "execution_allowed": False,
        "true_probability_estimate": round(true_probability, 4),
        "binance_impulse_bps": round(impulse_bps, 4) if impulse_bps is not None else None,
        "polymarket_yes_ask": poly_ask,
        "polymarket_yes_bid": poly_bid,
        "estimated_yes_edge": yes_edge,
        "estimated_no_edge": no_edge,
        "thresholds": {"min_impulse_bps": min_impulse_bps, "min_edge": min_edge},
        "blockers": blockers,
        "warnings": [
            "Candidate means observable mispricing only; this system does not submit CLOB orders.",
            "True probability is a rough microstructure estimate, not a calibrated prediction.",
        ],
    }


async def microstructure_probe(
    binance_symbol: str = "BTCUSDT",
    sample_seconds: float = 2.0,
    max_events: int = 10,
    inventory_units: float = 0.0,
) -> dict[str, Any]:
    stream = await collect_binance_l2_stream(binance_symbol, levels=5, sample_seconds=sample_seconds, max_events=max_events)
    analytics = microstructure_analytics(stream.get("events", []), inventory_units=inventory_units)
    return {
        "mode": "monitor_only",
        "status": "active" if stream.get("events") else "no_l2_events",
        "decision": "NO_TRADE",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "symbol": binance_symbol.upper(),
        "stream": stream,
        "analytics": analytics,
        "warnings": [
            "Microstructure analytics are observation-only.",
            "OFI, microprice, VPIN proxy, and Avellaneda-Stoikov quote are not live order instructions.",
        ],
    }


def microstructure_analytics(events: list[dict[str, Any]], inventory_units: float = 0.0) -> dict[str, Any]:
    usable = [event for event in events if event.get("bid") is not None and event.get("ask") is not None]
    if not usable:
        return {
            "microprice": None,
            "midpoint": None,
            "ofi": 0.0,
            "vpin_proxy": 0.0,
            "toxicity": "unknown",
            "logit_probability": 0.0,
            "fair_probability": 0.5,
            "avellaneda_stoikov": None,
            "blockers": ["no usable L2 events"],
        }

    latest = usable[-1]
    microprice = _microprice(latest)
    midpoint = _midpoint(latest)
    ofi = _order_flow_imbalance(usable)
    vpin_proxy = _vpin_proxy(usable)
    midpoints = [_midpoint(event) for event in usable if _midpoint(event) is not None]
    returns = [
        (new - old) / old
        for old, new in zip(midpoints[:-1], midpoints[1:])
        if old
    ]
    volatility = pstdev(returns) if len(returns) > 1 else 0.0001
    fair_probability = _microstructure_probability(microprice, midpoint, ofi, vpin_proxy)
    quote = _avellaneda_stoikov_quote(midpoint or 0, volatility, inventory_units, vpin_proxy)
    return {
        "microprice": round(microprice, 8) if microprice is not None else None,
        "midpoint": round(midpoint, 8) if midpoint is not None else None,
        "microprice_edge_bps": round(((microprice - midpoint) / midpoint) * 10_000, 4) if microprice and midpoint else None,
        "ofi": round(ofi, 6),
        "vpin_proxy": round(vpin_proxy, 6),
        "toxicity": "high" if vpin_proxy >= 0.65 else "medium" if vpin_proxy >= 0.35 else "low",
        "logit_probability": round(probability_to_logit(fair_probability), 6),
        "fair_probability": round(fair_probability, 6),
        "avellaneda_stoikov": quote,
        "blockers": ["toxicity high: widen or withdraw maker quotes"] if vpin_proxy >= 0.65 else [],
    }


def probability_to_logit(probability: float) -> float:
    bounded = max(0.0001, min(0.9999, probability))
    return math.log(bounded / (1 - bounded))


def logit_to_probability(logit: float) -> float:
    return 1 / (1 + math.exp(-logit))


def _safe_book(fetcher, venue: str, symbol: str) -> dict[str, Any]:
    try:
        return fetcher().__dict__
    except Exception as exc:  # pragma: no cover - public API state varies
        now = datetime.now(timezone.utc).isoformat()
        return {
            "venue": venue,
            "symbol": symbol,
            "bid": None,
            "ask": None,
            "midpoint": None,
            "spread": None,
            "observed_at": now,
            "latency_ms": None,
            "source": "provider_error",
            "error": str(exc),
        }


def _microprice(event: dict[str, Any]) -> float | None:
    bid = event.get("bid")
    ask = event.get("ask")
    bid_size = event.get("bid_size")
    ask_size = event.get("ask_size")
    if bid is None or ask is None or bid_size is None or ask_size is None:
        return _midpoint(event)
    total = float(bid_size) + float(ask_size)
    if total <= 0:
        return _midpoint(event)
    return (float(ask) * float(bid_size) + float(bid) * float(ask_size)) / total


def _order_flow_imbalance(events: list[dict[str, Any]]) -> float:
    if len(events) < 2:
        return 0.0
    total = 0.0
    for previous, current in zip(events[:-1], events[1:]):
        prev_bid = float(previous.get("bid") or 0)
        curr_bid = float(current.get("bid") or 0)
        prev_ask = float(previous.get("ask") or 0)
        curr_ask = float(current.get("ask") or 0)
        prev_bid_size = float(previous.get("bid_size") or 0)
        curr_bid_size = float(current.get("bid_size") or 0)
        prev_ask_size = float(previous.get("ask_size") or 0)
        curr_ask_size = float(current.get("ask_size") or 0)
        bid_contribution = curr_bid_size if curr_bid > prev_bid else curr_bid_size - prev_bid_size if curr_bid == prev_bid else -prev_bid_size
        ask_contribution = -curr_ask_size if curr_ask < prev_ask else prev_ask_size - curr_ask_size if curr_ask == prev_ask else prev_ask_size
        total += bid_contribution + ask_contribution
    depth = sum(float(event.get("bid_size") or 0) + float(event.get("ask_size") or 0) for event in events) or 1
    return total / depth


def _vpin_proxy(events: list[dict[str, Any]]) -> float:
    imbalances = []
    for event in events:
        bid_depth = float(event.get("bid_depth_notional") or 0)
        ask_depth = float(event.get("ask_depth_notional") or 0)
        total = bid_depth + ask_depth
        if total > 0:
            imbalances.append(abs(bid_depth - ask_depth) / total)
    return sum(imbalances) / len(imbalances) if imbalances else 0.0


def _microstructure_probability(microprice: float | None, midpoint: float | None, ofi: float, vpin_proxy: float) -> float:
    if not microprice or not midpoint:
        return 0.5
    edge_bps = ((microprice - midpoint) / midpoint) * 10_000
    logit = (edge_bps * 0.18) + (ofi * 1.2) - (vpin_proxy * 0.35)
    return logit_to_probability(max(-4.0, min(4.0, logit)))


def _avellaneda_stoikov_quote(
    midpoint: float,
    volatility: float,
    inventory_units: float,
    vpin_proxy: float,
    risk_aversion: float = 0.12,
    horizon_seconds: float = 1.0,
    k: float = 1.5,
) -> dict[str, Any] | None:
    if midpoint <= 0:
        return None
    horizon_years = horizon_seconds / (365 * 24 * 60 * 60)
    sigma2_t = (volatility * midpoint) ** 2 * horizon_years
    reservation = midpoint - inventory_units * risk_aversion * sigma2_t
    half_spread = (risk_aversion * sigma2_t / 2) + (math.log(1 + risk_aversion / k) / risk_aversion)
    toxicity_multiplier = 1 + max(0.0, min(1.0, vpin_proxy))
    adjusted_half_spread = half_spread * toxicity_multiplier
    return {
        "reservation_price": round(reservation, 8),
        "bid_quote": round(reservation - adjusted_half_spread, 8),
        "ask_quote": round(reservation + adjusted_half_spread, 8),
        "half_spread": round(adjusted_half_spread, 8),
        "toxicity_multiplier": round(toxicity_multiplier, 6),
        "inventory_units": inventory_units,
        "rule": "Monitor-only Avellaneda-Stoikov quote; do not place orders from this output.",
    }


def _best_level(levels: list[dict[str, Any]], reverse: bool) -> tuple[float, float] | None:
    parsed = []
    for level in levels:
        price = level.get("price")
        size = level.get("size")
        if price is None or size is None:
            continue
        parsed.append((float(price), float(size)))
    if not parsed:
        return None
    return sorted(parsed, key=lambda item: item[0], reverse=reverse)[0]


def _parse_levels(levels: list[Any], reverse: bool) -> list[tuple[float, float]]:
    parsed = []
    for level in levels:
        if isinstance(level, dict):
            price = level.get("price")
            size = level.get("size")
        else:
            price = level[0] if len(level) > 0 else None
            size = level[1] if len(level) > 1 else None
        if price is None or size is None:
            continue
        parsed.append((float(price), float(size)))
    return sorted(parsed, key=lambda item: item[0], reverse=reverse)


def _depth_snapshot_from_levels(
    venue: str,
    symbol: str,
    bids: list[Any],
    asks: list[Any],
    levels: int,
    source: str,
) -> DepthSnapshot:
    bid_levels = _parse_levels(bids, reverse=True)[:levels]
    ask_levels = _parse_levels(asks, reverse=False)[:levels]
    best_bid = bid_levels[0] if bid_levels else None
    best_ask = ask_levels[0] if ask_levels else None
    bid = best_bid[0] if best_bid else None
    ask = best_ask[0] if best_ask else None
    midpoint = (bid + ask) / 2 if bid is not None and ask is not None else None
    spread = ask - bid if bid is not None and ask is not None else None
    bid_depth = sum(price * size for price, size in bid_levels)
    ask_depth = sum(price * size for price, size in ask_levels)
    depth_total = bid_depth + ask_depth
    imbalance = (bid_depth - ask_depth) / depth_total if depth_total else 0.0
    return DepthSnapshot(
        venue=venue,
        symbol=symbol,
        levels=levels,
        bid=bid,
        ask=ask,
        midpoint=midpoint,
        spread=spread,
        spread_bps=(spread / midpoint) * 10_000 if spread is not None and midpoint else None,
        bid_size=best_bid[1] if best_bid else None,
        ask_size=best_ask[1] if best_ask else None,
        bid_depth_notional=bid_depth,
        ask_depth_notional=ask_depth,
        depth_imbalance=imbalance,
        observed_at=datetime.now(timezone.utc).isoformat(),
        source=source,
    )


async def _skipped_polymarket_stream() -> dict[str, Any]:
    return {
        "venue": "polymarket",
        "symbol": "token_id_required",
        "status": "skipped",
        "source": POLYMARKET_MARKET_WS,
        "events": [],
        "error": "Provide polymarket_token_id to subscribe to the CLOB market channel.",
    }


async def _collect_stream(
    venue: str,
    symbol: str,
    url: str,
    subscribe_payload: dict[str, Any] | None,
    parser,
    sample_seconds: float,
    max_events: int,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    started = datetime.now(timezone.utc)
    try:
        async with websockets.connect(url, open_timeout=6, ping_interval=None) as socket:
            if subscribe_payload is not None:
                await socket.send(json.dumps(subscribe_payload))
            deadline = asyncio.get_running_loop().time() + max(sample_seconds, 0.25)
            while len(events) < max_events:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=remaining)
                except TimeoutError:
                    break
                parsed = parser(raw)
                if parsed:
                    events.append(parsed.__dict__)
        status = "connected" if events else "connected_no_events"
        error = None
    except Exception as exc:  # pragma: no cover - public stream state varies
        status = "error"
        error = str(exc)
    finished = datetime.now(timezone.utc)
    return {
        "venue": venue,
        "symbol": symbol,
        "status": status,
        "source": url,
        "duration_ms": round((finished - started).total_seconds() * 1000, 3),
        "events": events,
        "error": error,
    }


def _parse_binance_stream_event(raw: str | bytes) -> StreamBookEvent | None:
    payload = json.loads(raw)
    bid = float(payload["b"])
    ask = float(payload["a"])
    return StreamBookEvent(
        venue="binance",
        symbol=payload.get("s", "unknown"),
        event_type="bookTicker",
        bid=bid,
        ask=ask,
        spread=ask - bid,
        received_at=datetime.now(timezone.utc).isoformat(),
        source="@bookTicker websocket",
        bid_size=_optional_float(payload.get("B")),
        ask_size=_optional_float(payload.get("A")),
    )


def _parse_binance_depth_snapshot(raw: str | bytes, symbol: str = "unknown", levels: int = 5) -> DepthSnapshot:
    payload = json.loads(raw)
    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]
    return _depth_snapshot_from_levels(
        venue="binance_l2",
        symbol=payload.get("s") or symbol,
        bids=payload.get("bids") or payload.get("b") or [],
        asks=payload.get("asks") or payload.get("a") or [],
        levels=levels,
        source=f"@depth{levels}@100ms websocket",
    )


def _parse_binance_depth_stream_event(raw: str | bytes, symbol: str = "unknown", levels: int = 5) -> StreamBookEvent | None:
    snapshot = _parse_binance_depth_snapshot(raw, symbol=symbol, levels=levels)
    return StreamBookEvent(
        venue="binance_l2",
        symbol=snapshot.symbol,
        event_type=f"depth{snapshot.levels}",
        bid=snapshot.bid,
        ask=snapshot.ask,
        spread=snapshot.spread,
        received_at=snapshot.observed_at,
        source=snapshot.source,
        bid_size=snapshot.bid_size,
        ask_size=snapshot.ask_size,
        bid_depth_notional=round(snapshot.bid_depth_notional, 6),
        ask_depth_notional=round(snapshot.ask_depth_notional, 6),
        depth_imbalance=round(snapshot.depth_imbalance, 6),
    )


def _parse_polymarket_stream_event(raw: str | bytes) -> StreamBookEvent | None:
    if raw in {"PING", "PONG", b"PING", b"PONG"}:
        return None
    payload = json.loads(raw)
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    event_type = payload.get("event_type", "unknown")
    bid = ask = None
    if event_type == "book":
        best_bid = _best_level(payload.get("bids") or [], reverse=True)
        best_ask = _best_level(payload.get("asks") or [], reverse=False)
        bid = best_bid[0] if best_bid else None
        ask = best_ask[0] if best_ask else None
    elif event_type == "best_bid_ask":
        bid = _optional_float(payload.get("best_bid"))
        ask = _optional_float(payload.get("best_ask"))
    elif event_type == "price_change":
        changes = payload.get("price_changes") or []
        if changes:
            bid = _optional_float(changes[0].get("best_bid"))
            ask = _optional_float(changes[0].get("best_ask"))
    return StreamBookEvent(
        venue="polymarket",
        symbol=payload.get("asset_id") or payload.get("market") or "unknown",
        event_type=event_type,
        bid=bid,
        ask=ask,
        spread=ask - bid if bid is not None and ask is not None else None,
        received_at=datetime.now(timezone.utc).isoformat(),
        source="market websocket",
    )


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


def _midpoint(event: dict[str, Any]) -> float | None:
    bid = event.get("bid")
    ask = event.get("ask")
    if bid is None or ask is None:
        return None
    return (float(bid) + float(ask)) / 2


def _probability_from_impulse(impulse_bps: float) -> float:
    # Rough monitor-only mapping: a 40 bps impulse moves fair probability by about 10 points.
    return max(0.05, min(0.95, 0.5 + impulse_bps / 400))
