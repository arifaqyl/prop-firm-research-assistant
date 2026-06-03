from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
import json
import os
from math import exp, log, pi, sqrt
import re
import xml.etree.ElementTree as ET
from typing import Any

import requests

from .domain import DirectionCall
from .market_data import MarketSnapshot, build_signal_from_snapshot, fetch_market_snapshot


@dataclass(frozen=True)
class TimeframeSignal:
    timeframe: str
    interval: str
    range: str
    direction: str
    confidence: str
    latest_price: float
    regime: str
    sample_size: int
    source: str


TIMEFRAMES = {
    "1D": ("1d", "1y"),
    "1H": ("1h", "60d"),
    "1M": ("1m", "1d"),
}
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
CATALYST_PROMPT_VERSION = "catalyst-v1"
DEFAULT_CLAUDE_MODEL = "claude-3-5-haiku-latest"
DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"
CATALYST_VERDICTS = {"BULLISH_CATALYST", "BEARISH_CATALYST", "NO_TRADE"}
CATALYST_PROVIDER_NAMES = ("anthropic", "gemini", "openrouter", "ollama")
FREE_NEWS_RSS_URL = "https://news.google.com/rss/search"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
YAHOO_OPTIONS_URL = "https://query2.finance.yahoo.com/v7/finance/options/{symbol}"
FRED_SERIES = {
    "DFII10": "10Y real yield",
    "DGS10": "10Y treasury yield",
    "DFF": "effective fed funds",
    "VIXCLS": "VIX volatility index",
    "DTWEXBGS": "broad dollar index",
}
SECONDS_PER_YEAR = 365 * 24 * 60 * 60


def multi_timeframe_context(symbol: str) -> dict[str, Any]:
    rows: list[TimeframeSignal] = []
    warnings: list[str] = []
    for label, (interval, range_) in TIMEFRAMES.items():
        try:
            snapshot = fetch_market_snapshot(symbol, interval=interval, range_=range_)
            signal = build_signal_from_snapshot(snapshot)
            rows.append(
                TimeframeSignal(
                    timeframe=label,
                    interval=interval,
                    range=range_,
                    direction=signal.direction_call.value,
                    confidence=signal.confidence.value,
                    latest_price=signal.latest_price,
                    regime=signal.regime,
                    sample_size=signal.sample_size,
                    source=snapshot.source,
                )
            )
        except Exception as exc:  # pragma: no cover - provider state varies
            warnings.append(f"{label} fetch failed: {exc}")

    directional = [row.direction for row in rows if row.direction in {DirectionCall.BULLISH.value, DirectionCall.BEARISH.value}]
    aligned_direction = directional[0] if directional and all(item == directional[0] for item in directional) and len(directional) == len(rows) else DirectionCall.NO_EDGE.value
    return {
        "symbol": symbol.strip().upper() or "AAPL",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "timeframes": [row.__dict__ for row in rows],
        "aligned_direction": aligned_direction,
        "micro_trade_allowed": aligned_direction in {DirectionCall.BULLISH.value, DirectionCall.BEARISH.value} and not warnings,
        "warnings": warnings,
        "rule": "1D, 1H, and 1m must all point the same way; otherwise micro-trades are hard-blocked.",
    }


def macro_context() -> dict[str, Any]:
    series: dict[str, Any] = {}
    warnings: list[str] = []
    for series_id, label in FRED_SERIES.items():
        try:
            series[series_id] = _fetch_fred_series(series_id, label)
        except Exception as exc:  # pragma: no cover - public data state varies
            warnings.append(f"{series_id} fetch failed: {exc}")

    signals = _macro_signals(series)
    return {
        "mode": "free_fred_csv",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "series": series,
        "signals": signals,
        "warnings": warnings,
        "rule": "No-key FRED macro context: real yields and dollar strength are headwinds for gold/risk assets; VIX above 25 is risk-off.",
        "sources": [{"name": label, "series_id": series_id, "url": f"{FRED_CSV_URL}?id={series_id}"} for series_id, label in FRED_SERIES.items()],
    }


def options_gex_context(symbol: str = "SPY", max_expirations: int = 2) -> dict[str, Any]:
    requested = symbol.strip().upper() or "SPY"
    warnings: list[str] = []
    try:
        base_payload = _fetch_yahoo_options(requested)
        chain = (base_payload.get("optionChain") or {}).get("result") or []
        if not chain:
            raise ValueError("Yahoo returned no options chain")
        root = chain[0]
        spot = float((root.get("quote") or {}).get("regularMarketPrice") or 0)
        expirations = (root.get("expirationDates") or [])[:max(max_expirations, 1)]
        expiration_payloads = [root]
        for expiration in expirations[1:]:
            try:
                expiration_payloads.append((( _fetch_yahoo_options(requested, expiration).get("optionChain") or {}).get("result") or [{}])[0])
            except Exception as exc:  # pragma: no cover - provider state varies
                warnings.append(f"expiration {expiration} fetch failed: {exc}")
        summary = _summarize_options_gex(requested, spot, expiration_payloads)
    except Exception as exc:  # pragma: no cover - provider state varies
        return {
            "mode": "free_yahoo_options",
            "symbol": requested,
            "status": "provider_error",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "decision": "NO_TRADE",
            "warnings": [str(exc)],
            "rule": "Approximate GEX uses public Yahoo options data and never places orders.",
        }

    return {
        "mode": "free_yahoo_options",
        "symbol": requested,
        "status": "active",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "decision": "NO_TRADE",
        "warnings": warnings,
        "rule": "Approximate GEX: positive net gamma can dampen moves; negative net gamma can amplify moves. Public options data is delayed/incomplete.",
        **summary,
    }


def _fetch_yahoo_options(symbol: str, expiration: int | None = None) -> dict[str, Any]:
    params = {"date": expiration} if expiration else None
    headers = {"User-Agent": "Mozilla/5.0 prop-firm-ai/0.1"}
    response = requests.get(
        YAHOO_OPTIONS_URL.format(symbol=symbol),
        params=params,
        timeout=10,
        headers=headers,
    )
    if response.status_code == 401:
        return _fetch_yahoo_options_with_crumb(symbol, expiration, headers)
    response.raise_for_status()
    return response.json()


def _fetch_yahoo_options_with_crumb(symbol: str, expiration: int | None, headers: dict[str, str]) -> dict[str, Any]:
    session = requests.Session()
    session.headers.update(headers)
    session.get("https://fc.yahoo.com", timeout=10)
    crumb_response = session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10)
    crumb_response.raise_for_status()
    params = {"crumb": crumb_response.text.strip()}
    if expiration:
        params["date"] = expiration
    response = session.get(YAHOO_OPTIONS_URL.format(symbol=symbol), params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def _summarize_options_gex(symbol: str, spot: float, expiration_payloads: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    total_call_gex = 0.0
    total_put_gex = 0.0
    expiration_count = 0
    open_interest_contracts = 0
    volume_proxy_contracts = 0
    for payload in expiration_payloads:
        options = payload.get("options") or []
        if not options:
            continue
        expiration_count += 1
        expiration = options[0].get("expirationDate")
        days_to_expiry = max(((float(expiration or 0) - datetime.now(timezone.utc).timestamp()) / 86400), 1.0)
        years = days_to_expiry / 365
        contracts = [*(options[0].get("calls") or []), *(options[0].get("puts") or [])]
        open_interest_contracts += sum(1 for item in contracts if _safe_float(item.get("openInterest"), 0.0) > 0)
        volume_proxy_contracts += sum(1 for item in contracts if _safe_float(item.get("openInterest"), 0.0) <= 0 and _safe_float(item.get("volume"), 0.0) > 0)
        call_gex = sum(_option_gex(spot, item, years, is_put=False) for item in options[0].get("calls") or [])
        put_gex = sum(_option_gex(spot, item, years, is_put=True) for item in options[0].get("puts") or [])
        total_call_gex += call_gex
        total_put_gex += put_gex
        rows.append(
            {
                "expiration": expiration,
                "days_to_expiry": round(days_to_expiry, 2),
                "call_gex": round(call_gex, 2),
                "put_gex": round(put_gex, 2),
                "net_gex": round(call_gex + put_gex, 2),
            }
        )
    net_gex = total_call_gex + total_put_gex
    return {
        "spot": spot,
        "expiration_count": expiration_count,
        "call_gex": round(total_call_gex, 2),
        "put_gex": round(total_put_gex, 2),
        "net_gex": round(net_gex, 2),
        "gamma_regime": "positive_gamma_dampening" if net_gex > 0 else "negative_gamma_amplifying" if net_gex < 0 else "neutral_gamma",
        "exposure_basis": "open_interest" if open_interest_contracts else "volume_proxy",
        "open_interest_contracts": open_interest_contracts,
        "volume_proxy_contracts": volume_proxy_contracts,
        "expirations": rows,
        "source": YAHOO_OPTIONS_URL.format(symbol=symbol),
    }


def _option_gex(spot: float, option: dict[str, Any], years_to_expiry: float, is_put: bool) -> float:
    strike = _safe_float(option.get("strike"), 0.0)
    iv = max(_safe_float(option.get("impliedVolatility"), 0.0), 0.0001)
    quantity = max(_safe_float(option.get("openInterest"), 0.0), 0.0)
    if quantity <= 0:
        quantity = max(_safe_float(option.get("volume"), 0.0), 0.0)
    if spot <= 0 or strike <= 0 or quantity <= 0:
        return 0.0
    gamma = _black_scholes_gamma(spot, strike, iv, years_to_expiry)
    notional_gamma = gamma * quantity * 100 * spot * spot * 0.01
    return -notional_gamma if is_put else notional_gamma


def _black_scholes_gamma(spot: float, strike: float, volatility: float, years_to_expiry: float, risk_free_rate: float = 0.045) -> float:
    t = max(years_to_expiry, 1 / 365)
    sigma = max(volatility, 0.0001)
    d1 = (log(spot / strike) + (risk_free_rate + 0.5 * sigma * sigma) * t) / (sigma * sqrt(t))
    pdf = exp(-0.5 * d1 * d1) / sqrt(2 * pi)
    return pdf / (spot * sigma * sqrt(t))


def _fetch_fred_series(series_id: str, label: str) -> dict[str, Any]:
    response = requests.get(FRED_CSV_URL, params={"id": series_id}, timeout=10, headers={"User-Agent": "prop-firm-ai/0.1"})
    response.raise_for_status()
    return _parse_fred_csv(response.text, series_id, label)


def _parse_fred_csv(text: str, series_id: str, label: str) -> dict[str, Any]:
    rows = []
    for row in csv.DictReader(StringIO(text)):
        raw_value = row.get(series_id)
        if raw_value in {None, "", "."}:
            continue
        try:
            rows.append({"date": row.get("observation_date"), "value": float(raw_value)})
        except ValueError:
            continue
    if not rows:
        raise ValueError(f"no usable values for {series_id}")
    latest = rows[-1]
    previous = rows[-2] if len(rows) > 1 else rows[-1]
    month_ago = rows[-22] if len(rows) >= 22 else rows[0]
    return {
        "series_id": series_id,
        "label": label,
        "latest_date": latest["date"],
        "latest_value": latest["value"],
        "previous_value": previous["value"],
        "day_change": round(latest["value"] - previous["value"], 4),
        "month_change": round(latest["value"] - month_ago["value"], 4),
        "observations": len(rows),
        "source": f"{FRED_CSV_URL}?id={series_id}",
    }


def _macro_signals(series: dict[str, Any]) -> dict[str, Any]:
    real_yield = series.get("DFII10", {})
    dollar = series.get("DTWEXBGS", {})
    vix = series.get("VIXCLS", {})
    nominal_yield = series.get("DGS10", {})
    fed_funds = series.get("DFF", {})

    gold_score = 0
    risk_score = 0
    reasons = []
    if real_yield.get("month_change", 0) < 0:
        gold_score += 1
        reasons.append("falling real yields support gold")
    elif real_yield.get("month_change", 0) > 0:
        gold_score -= 1
        reasons.append("rising real yields pressure gold")
    if dollar.get("month_change", 0) < 0:
        gold_score += 1
        risk_score += 1
        reasons.append("weaker dollar supports gold and risk assets")
    elif dollar.get("month_change", 0) > 0:
        gold_score -= 1
        risk_score -= 1
        reasons.append("stronger dollar is a headwind")
    if vix.get("latest_value", 0) >= 25:
        risk_score -= 2
        reasons.append("VIX above 25 signals risk-off volatility")
    elif 0 < vix.get("latest_value", 0) < 18:
        risk_score += 1
        reasons.append("low VIX supports risk-on conditions")
    if nominal_yield.get("month_change", 0) > 0 or fed_funds.get("month_change", 0) > 0:
        risk_score -= 1
        reasons.append("rising rates tighten financial conditions")

    return {
        "gold_macro_bias": _bias_from_score(gold_score),
        "risk_asset_bias": _bias_from_score(risk_score),
        "gold_score": gold_score,
        "risk_score": risk_score,
        "reasons": reasons,
    }


def _bias_from_score(score: int) -> str:
    if score >= 2:
        return "bullish"
    if score <= -2:
        return "bearish"
    return "neutral"


def tavily_rag_veto(
    query: str,
    api_key: str | None = None,
    anthropic_api_key: str | None = None,
    model: str = DEFAULT_CLAUDE_MODEL,
    openrouter_api_key: str | None = None,
    openrouter_model: str = "meta-llama/llama-3.1-8b-instruct",
    gemini_api_key: str | None = None,
    gemini_model: str = "gemini-2.5-flash",
    ollama_base_url: str | None = None,
    ollama_model: str = DEFAULT_OLLAMA_MODEL,
    use_free_news: bool = True,
    provider_preference: str = "auto",
) -> dict[str, Any]:
    """Fetch recent context and classify whether a catalyst is strong enough.

    Missing data or LLM failures keep the veto closed. That is deliberate: this
    function is an execution gate, not a content generator.
    """
    if not api_key and not use_free_news:
        return {
            "status": "disabled",
            "verdict": "NO_TRADE",
            "reason": "Tavily API key is not configured; catalyst veto stays closed.",
            "sources": [],
            "prompt_version": CATALYST_PROMPT_VERSION,
            "model": model,
            "llm_used": False,
            "news_provider": "none",
        }
    try:
        if api_key:
            results = _fetch_tavily_results(query, api_key)
            news_provider = "tavily"
        else:
            results = _fetch_free_news_results(query)
            news_provider = "free_google_news_rss"
    except Exception as exc:  # pragma: no cover - provider state varies
        return _closed_veto(
            "provider_error",
            f"News fetch failed; catalyst veto stays closed: {exc}",
            model=model,
            sources=[],
            llm_used=False,
            news_provider="tavily" if api_key else "free_google_news_rss",
        )

    sources = [{"title": item.get("title"), "url": item.get("url")} for item in results]
    keyword = _keyword_catalyst_classification(results)
    if not results:
        return _closed_veto(
            "no_sources",
            "No news sources returned; catalyst veto stays closed.",
            model=model,
            sources=[],
            llm_used=False,
            keyword=keyword,
            news_provider=news_provider,
        )

    configured_provider = _normalize_provider_preference(provider_preference)
    provider_plan = _catalyst_provider_plan(
        configured_provider=configured_provider,
        anthropic_api_key=anthropic_api_key,
        gemini_api_key=gemini_api_key,
        openrouter_api_key=openrouter_api_key,
        ollama_base_url=ollama_base_url,
    )

    if not provider_plan:
        return {
            "status": "keyword_only_veto",
            "verdict": "NO_TRADE",
            "reason": _keyword_only_reason(configured_provider),
            "keyword_verdict": keyword["verdict"],
            "keyword_reason": keyword["reason"],
            "sources": sources,
            "prompt_version": CATALYST_PROMPT_VERSION,
            "model": model,
            "llm_used": False,
            "configured_llm_provider": configured_provider,
            "active_llm_provider": None,
            "llm_attempts": [],
            "news_provider": news_provider,
        }

    attempts: list[dict[str, Any]] = []
    llm = None
    llm_provider = None
    active_model = model
    last_error = "no provider attempt was made"
    for provider_name in provider_plan:
        try:
            if provider_name == "anthropic":
                llm = _classify_catalyst_with_claude(query=query, results=results, api_key=anthropic_api_key or "", model=model)
                active_model = model
            elif provider_name == "gemini":
                llm = _classify_catalyst_with_gemini(query=query, results=results, api_key=gemini_api_key or "", model=gemini_model)
                active_model = gemini_model
            elif provider_name == "openrouter":
                llm = _classify_catalyst_with_openrouter(query=query, results=results, api_key=openrouter_api_key or "", model=openrouter_model)
                active_model = openrouter_model
            else:
                llm = _classify_catalyst_with_ollama(query=query, results=results, base_url=ollama_base_url or "", model=ollama_model)
                active_model = ollama_model
            attempts.append({"provider": provider_name, "status": "ok", "model": active_model})
            llm_provider = provider_name
            break
        except Exception as exc:  # pragma: no cover - provider state varies
            last_error = str(exc)
            attempts.append({"provider": provider_name, "status": "failed", "error": str(exc)})

    if llm is None or llm_provider is None:
        return {
            "status": "llm_unavailable_keyword_only_veto",
            "verdict": "NO_TRADE",
            "reason": f"All configured catalyst classifiers failed; veto stays closed. Last error: {last_error}",
            "keyword_verdict": keyword["verdict"],
            "keyword_reason": keyword["reason"],
            "sources": sources,
            "prompt_version": CATALYST_PROMPT_VERSION,
            "model": model,
            "llm_used": False,
            "configured_llm_provider": configured_provider,
            "active_llm_provider": None,
            "llm_attempts": attempts,
            "news_provider": news_provider,
        }

    verdict = llm.get("verdict")
    if verdict not in CATALYST_VERDICTS:
        return _closed_veto(
            "invalid_llm_contract",
            "The catalyst LLM returned an invalid verdict; veto stays closed.",
            model=model,
            sources=sources,
            llm_used=False,
            keyword=keyword,
            news_provider=news_provider,
            configured_provider=configured_provider,
            active_provider=llm_provider,
            attempts=attempts,
        )

    confidence = _parse_confidence_value(llm.get("confidence"), 0.0)
    if verdict != "NO_TRADE" and confidence < 0.72:
        return {
            "status": "low_confidence_veto",
            "verdict": "NO_TRADE",
            "raw_verdict": verdict,
            "confidence": confidence,
            "reason": f"The catalyst LLM found {verdict} but confidence {confidence:.2f} is below the 0.72 catalyst gate.",
            "keyword_verdict": keyword["verdict"],
            "keyword_reason": keyword["reason"],
            "evidence": llm.get("evidence", []),
            "risks": llm.get("risks", []),
            "sources": sources,
            "prompt_version": CATALYST_PROMPT_VERSION,
            "model": active_model,
            "llm_used": True,
            "llm_provider": llm_provider,
            "configured_llm_provider": configured_provider,
            "active_llm_provider": llm_provider,
            "llm_attempts": attempts,
            "news_provider": news_provider,
        }

    return {
        "status": "active",
        "verdict": verdict,
        "confidence": confidence,
        "reason": llm.get("reason", "The catalyst classifier returned a valid contract."),
        "keyword_verdict": keyword["verdict"],
        "keyword_reason": keyword["reason"],
        "evidence": llm.get("evidence", []),
        "risks": llm.get("risks", []),
        "sources": sources,
        "prompt_version": CATALYST_PROMPT_VERSION,
        "model": active_model,
        "llm_used": True,
        "llm_provider": llm_provider,
        "configured_llm_provider": configured_provider,
        "active_llm_provider": llm_provider,
        "llm_attempts": attempts,
        "news_provider": news_provider,
    }


def _normalize_provider_preference(provider_preference: str | None) -> str:
    value = (provider_preference or "auto").strip().lower()
    if value in {"", "default"}:
        return "auto"
    if value in {"off", "disabled", "keyword_only"}:
        return "none"
    if value in {"auto", "none", *CATALYST_PROVIDER_NAMES}:
        return value
    return "auto"


def _catalyst_provider_plan(
    configured_provider: str,
    anthropic_api_key: str | None,
    gemini_api_key: str | None,
    openrouter_api_key: str | None,
    ollama_base_url: str | None,
) -> list[str]:
    available = {
        "anthropic": bool(anthropic_api_key),
        "gemini": bool(gemini_api_key),
        "openrouter": bool(openrouter_api_key),
        "ollama": bool(ollama_base_url),
    }
    if configured_provider == "none":
        return []
    if configured_provider in CATALYST_PROVIDER_NAMES:
        return [configured_provider] if available.get(configured_provider) else []
    return [name for name in CATALYST_PROVIDER_NAMES if available.get(name)]


def _keyword_only_reason(configured_provider: str) -> str:
    if configured_provider == "none":
        return "Catalyst LLM provider is explicitly disabled; news context was fetched but the veto stays closed."
    if configured_provider in CATALYST_PROVIDER_NAMES:
        return f"Catalyst LLM provider '{configured_provider}' is selected but not configured; news context was fetched but the veto stays closed."
    return "No Claude, local Ollama, OpenRouter, or Gemini classifier is configured; news context was fetched but catalyst veto stays closed."


def _fetch_tavily_results(query: str, api_key: str) -> list[dict[str, Any]]:
    response = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "search_depth": "advanced",
            "topic": "news",
            "max_results": 8,
            "include_answer": False,
            "include_raw_content": False,
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json().get("results", [])


def _fetch_free_news_results(query: str) -> list[dict[str, Any]]:
    response = requests.get(
        FREE_NEWS_RSS_URL,
        params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
        timeout=10,
        headers={"User-Agent": "prop-firm-ai/0.1"},
    )
    response.raise_for_status()
    return _parse_free_news_rss(response.text)


def _parse_free_news_rss(xml_text: str, limit: int = 8) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    items = []
    for item in root.findall(".//item")[:limit]:
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        description = item.findtext("description") or ""
        published = item.findtext("pubDate") or None
        items.append({"title": title, "url": link, "content": description, "published_date": published})
    return items


def _keyword_catalyst_classification(results: list[dict[str, Any]]) -> dict[str, Any]:
    text = " ".join((item.get("title", "") + " " + item.get("content", "")).lower() for item in results)
    bullish_words = {"surge", "beat", "approval", "breakthrough", "rally", "inflow", "upgrade"}
    bearish_words = {"miss", "lawsuit", "hack", "ban", "selloff", "outflow", "downgrade"}
    bullish = sum(1 for word in bullish_words if word in text)
    bearish = sum(1 for word in bearish_words if word in text)
    if bullish > bearish + 1:
        verdict = "BULLISH_CATALYST"
    elif bearish > bullish + 1:
        verdict = "BEARISH_CATALYST"
    else:
        verdict = "NO_TRADE"
    return {
        "verdict": verdict,
        "reason": f"Keyword catalyst score bullish={bullish}, bearish={bearish}. LLM classification is still deferred.",
        "bullish_score": bullish,
        "bearish_score": bearish,
    }


def _classify_catalyst_with_claude(query: str, results: list[dict[str, Any]], api_key: str, model: str) -> dict[str, Any]:
    context = _catalyst_context(results)
    response = requests.post(
        ANTHROPIC_MESSAGES_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 700,
            "temperature": 0,
            "system": (
                "You are a catalyst veto classifier for a trading risk system. "
                "Return only strict JSON. Do not recommend trades. "
                "If evidence is stale, mixed, weak, unsourced, or not market-moving, return NO_TRADE."
            ),
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Classify the market catalyst for this query.\n"
                        f"Query: {query}\n"
                        f"Prompt version: {CATALYST_PROMPT_VERSION}\n"
                        "Allowed verdicts: BULLISH_CATALYST, BEARISH_CATALYST, NO_TRADE.\n"
                        "Required JSON schema: {"
                        '"verdict": string, "confidence": number between 0 and 1, '
                        '"reason": string, "evidence": string[], "risks": string[]'
                        "}.\n"
                        "Use only the supplied sources:\n"
                        f"{json.dumps(context, ensure_ascii=True)}"
                    ),
                }
            ],
        },
        timeout=20,
    )
    response.raise_for_status()
    return _parse_claude_json(response.json())


def _classify_catalyst_with_ollama(query: str, results: list[dict[str, Any]], base_url: str, model: str) -> dict[str, Any]:
    compact_results = [
        {
            "title": (item.get("title") or "")[:140],
            "url": item.get("url"),
            "published_date": item.get("published_date"),
        }
        for item in results[:2]
    ]
    response = requests.post(
        f"{base_url.rstrip('/')}/api/chat",
        json={
            "model": model,
            "stream": False,
            "format": "json",
            "messages": [
                {
                    "role": "system",
                    "content": "Return JSON only.",
                },
                {
                    "role": "user",
                    "content": (
                        "Return minified JSON only with keys verdict, confidence, reason. "
                        "Allowed verdicts: BULLISH_CATALYST, BEARISH_CATALYST, NO_TRADE. "
                        "Use only these article titles and urls. "
                        "If evidence is mixed, weak, stale, or not clearly market-moving, verdict must be NO_TRADE. "
                        f"Query={query}. "
                        f"PromptVersion={CATALYST_PROMPT_VERSION}. "
                        f"Sources={json.dumps(compact_results, ensure_ascii=True)}"
                    ),
                },
            ],
            "options": {
                "temperature": 0,
                "num_ctx": 512,
                "num_predict": 80,
            },
        },
        timeout=120,
    )
    response.raise_for_status()
    content = response.json().get("message", {}).get("content", "")
    return _parse_json_text(content)


def _classify_catalyst_with_openrouter(query: str, results: list[dict[str, Any]], api_key: str, model: str) -> dict[str, Any]:
    context = _catalyst_context(results)
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model or "meta-llama/llama-3.1-8b-instruct",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a catalyst veto classifier for a trading risk system. "
                        "Return only strict JSON. If evidence is weak, mixed, stale, or not market-moving, return NO_TRADE."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Classify the market catalyst for this query.\n"
                        f"Query: {query}\n"
                        f"Prompt version: {CATALYST_PROMPT_VERSION}\n"
                        "Allowed verdicts: BULLISH_CATALYST, BEARISH_CATALYST, NO_TRADE.\n"
                        "Required JSON schema: {"
                        '"verdict": string, "confidence": number between 0 and 1, '
                        '"reason": string, "evidence": string[], "risks": string[]'
                        "}.\n"
                        "Use only the supplied sources:\n"
                        f"{json.dumps(context, ensure_ascii=True)}"
                    ),
                }
            ],
            "temperature": 0,
        },
        timeout=30,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _parse_json_text(content)


def _classify_catalyst_with_gemini(query: str, results: list[dict[str, Any]], api_key: str, model: str) -> dict[str, Any]:
    context = _catalyst_context(results)
    system_instruction = (
        "You are a catalyst veto classifier for a trading risk system. "
        "Return only strict JSON. If evidence is weak, mixed, stale, or not market-moving, return NO_TRADE."
    )
    prompt = (
        "Classify the market catalyst for this query.\n"
        f"Query: {query}\n"
        f"Prompt version: {CATALYST_PROMPT_VERSION}\n"
        "Allowed verdicts: BULLISH_CATALYST, BEARISH_CATALYST, NO_TRADE.\n"
        "Required JSON schema: {\n"
        '  "verdict": string,\n'
        '  "confidence": number between 0 and 1,\n'
        '  "reason": string,\n'
        '  "evidence": string[],\n'
        '  "risks": string[]\n'
        "}.\n"
        "Use only the supplied sources:\n"
        f"{json.dumps(context, ensure_ascii=True)}"
    )
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model or 'gemini-2.5-flash'}:generateContent?key={api_key}"
    response = requests.post(
        url,
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0
            }
        },
        timeout=30
    )
    response.raise_for_status()
    payload = response.json()
    text = payload["candidates"][0]["content"]["parts"][0]["text"].strip()
    return _parse_json_text(text)


def _catalyst_context(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "title": item.get("title"),
            "url": item.get("url"),
            "content": (item.get("content") or "")[:900],
            "published_date": item.get("published_date"),
        }
        for item in results[:8]
    ]


def _parse_claude_json(payload: dict[str, Any]) -> dict[str, Any]:
    blocks = payload.get("content") or []
    text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text").strip()
    return _parse_json_text(text)


def _parse_json_text(text: str) -> dict[str, Any]:
    text = text.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end+1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        repaired = _repair_llm_json(text)
        if repaired is None:
            raise
        parsed = repaired
    if not isinstance(parsed, dict):
        raise ValueError("response JSON was not an object")
    parsed.setdefault("evidence", [])
    parsed.setdefault("risks", [])
    parsed["confidence"] = _parse_confidence_value(parsed.get("confidence"), 0.0)
    return parsed


def _repair_llm_json(text: str) -> dict[str, Any] | None:
    verdict_match = re.search(r'"verdict"\s*:\s*"([^"]+)"', text)
    confidence_match = re.search(r'"confidence"\s*:\s*"?(?P<value>[0-9]+(?:\.[0-9]+)?%?)"?', text)
    reason_match = re.search(r'"reason"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
    if not verdict_match:
        return None

    def _extract_list(key: str) -> list[str]:
        block = re.search(rf'"{key}"\s*:\s*\[(.*?)\]', text, re.DOTALL)
        if not block:
            return []
        return [bytes(item, "utf-8").decode("unicode_escape") for item in re.findall(r'"((?:[^"\\]|\\.)*)"', block.group(1))]

    reason = bytes((reason_match.group(1) if reason_match else ""), "utf-8").decode("unicode_escape")
    return {
        "verdict": verdict_match.group(1),
        "confidence": _parse_confidence_value(confidence_match.group("value"), 0.0) if confidence_match else 0.0,
        "reason": reason,
        "evidence": _extract_list("evidence"),
        "risks": _extract_list("risks"),
    }


def _closed_veto(
    status: str,
    reason: str,
    model: str,
    sources: list[dict[str, Any]],
    llm_used: bool,
    keyword: dict[str, Any] | None = None,
    news_provider: str = "unknown",
    configured_provider: str = "auto",
    active_provider: str | None = None,
    attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    keyword = keyword or {"verdict": "NO_TRADE", "reason": "keyword fallback unavailable"}
    return {
        "status": status,
        "verdict": "NO_TRADE",
        "reason": reason,
        "keyword_verdict": keyword["verdict"],
        "keyword_reason": keyword["reason"],
        "sources": sources,
        "prompt_version": CATALYST_PROMPT_VERSION,
        "model": model,
        "llm_used": llm_used,
        "configured_llm_provider": configured_provider,
        "active_llm_provider": active_provider,
        "llm_attempts": attempts or [],
        "news_provider": news_provider,
    }


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_confidence_value(value: Any, default: float) -> float:
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("%"):
            try:
                return float(text[:-1]) / 100
            except ValueError:
                return default
    return _safe_float(value, default)
