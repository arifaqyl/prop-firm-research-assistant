from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from prop_firm_ai.audit import AuditLog
from prop_firm_ai.backtest import run_paper_simulation, run_watchlist_simulation
from prop_firm_ai.community import (
    MarketIntelSnapshot,
    SignalMessageType,
    SignalStore,
    build_operation_signal,
    build_strategy_signal,
    extract_prediction_from_signal,
    score_signal_quality,
)
from prop_firm_ai.confidence import evaluate_confidence_gate
from prop_firm_ai.dashboard import build_demo_dashboard_payload
from prop_firm_ai.domain import (
    Confidence,
    DataHealth,
    DirectionCall,
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioState,
    RiskConfig,
)
from prop_firm_ai.fundamentals import _extract_recent_filings, _filing_signal, _lookup_company_by_symbol
from prop_firm_ai.hybrid_gate import evaluate_hybrid_decision
from prop_firm_ai.macro import (
    _black_scholes_gamma,
    _macro_signals,
    _option_gex,
    _parse_claude_json,
    _parse_json_text,
    _parse_fred_csv,
    _parse_free_news_rss,
    _summarize_options_gex,
    tavily_rag_veto,
)
from prop_firm_ai.market_data import Candle, MarketSnapshot, build_signal_from_snapshot, fallback_signal, normalize_symbol
from prop_firm_ai.micro import _best_level, latency_gap_scan
from prop_firm_ai.micro import (
    _parse_binance_depth_snapshot,
    _parse_binance_depth_stream_event,
    _parse_binance_stream_event,
    _parse_polymarket_stream_event,
    _extract_polymarket_markets,
    microstructure_analytics,
    probability_to_logit,
    logit_to_probability,
    dual_websocket_probe,
    score_lag_exploit_candidate,
)
from prop_firm_ai.oms import PaperOrderManager
from prop_firm_ai.risk import RiskEngine
from prop_firm_ai.sizing import calculate_position_size
from prop_firm_ai.subagents import PortfolioRating, TraderAction, TradingAgentsTeam
from prop_firm_ai.system import TradingSystem, demo_signal
from prop_firm_ai.telegram import format_telegram_digest
from prop_firm_ai.statarb import scan_pair
from prop_firm_ai.open_source import open_source_strategy_catalog


class PropFirmSystemTests(unittest.TestCase):
    def test_stale_data_forces_no_edge(self) -> None:
        signal = demo_signal(stale=True)

        result = evaluate_confidence_gate(signal, TradingSystem().model_config)

        self.assertFalse(result.approved)
        self.assertEqual(result.direction_call, DirectionCall.NO_EDGE)
        self.assertIn("data freshness gate failed", result.reasons)
        self.assertTrue(any("stale" in warning for warning in result.warnings))

    def test_rag_veto_stays_closed_without_keys(self) -> None:
        result = tavily_rag_veto("BTC ETF approval", use_free_news=False)

        self.assertEqual(result["verdict"], "NO_TRADE")
        self.assertEqual(result["status"], "disabled")
        self.assertFalse(result["llm_used"])
        self.assertIn("prompt_version", result)

    def test_rag_veto_can_explicitly_disable_llm_provider(self) -> None:
        with patch("prop_firm_ai.macro._fetch_free_news_results", return_value=[{"title": "BTC rally", "url": "https://example.com", "content": "ETF inflow"}]):
            result = tavily_rag_veto("BTC ETF approval", use_free_news=True, provider_preference="none")

        self.assertEqual(result["status"], "keyword_only_veto")
        self.assertEqual(result["configured_llm_provider"], "none")
        self.assertFalse(result["llm_used"])
        self.assertEqual(result["active_llm_provider"], None)

    def test_rag_veto_specific_provider_requires_configured_key(self) -> None:
        with patch("prop_firm_ai.macro._fetch_free_news_results", return_value=[{"title": "BTC rally", "url": "https://example.com", "content": "ETF inflow"}]):
            result = tavily_rag_veto("BTC ETF approval", use_free_news=True, provider_preference="gemini")

        self.assertEqual(result["status"], "keyword_only_veto")
        self.assertEqual(result["configured_llm_provider"], "gemini")
        self.assertFalse(result["llm_used"])
        self.assertEqual(result["llm_attempts"], [])

    def test_rag_veto_auto_falls_back_after_provider_failure(self) -> None:
        results = [{"title": "BTC rally", "url": "https://example.com", "content": "ETF inflow"}]
        with (
            patch("prop_firm_ai.macro._fetch_free_news_results", return_value=results),
            patch("prop_firm_ai.macro._classify_catalyst_with_gemini", side_effect=RuntimeError("gemini unavailable")),
            patch(
                "prop_firm_ai.macro._classify_catalyst_with_ollama",
                return_value={
                    "verdict": "BULLISH_CATALYST",
                    "confidence": 0.84,
                    "reason": "Fresh catalyst is clearly supportive.",
                    "evidence": ["ETF inflow"],
                    "risks": ["headline may fade"],
                },
            ),
        ):
            result = tavily_rag_veto(
                "BTC ETF approval",
                use_free_news=True,
                provider_preference="auto",
                gemini_api_key="test-gemini",
                ollama_base_url="http://localhost:11434",
            )

        self.assertEqual(result["status"], "active")
        self.assertEqual(result["active_llm_provider"], "ollama")
        self.assertEqual(result["llm_attempts"][0]["provider"], "gemini")
        self.assertEqual(result["llm_attempts"][0]["status"], "failed")
        self.assertEqual(result["llm_attempts"][1]["provider"], "ollama")
        self.assertEqual(result["llm_attempts"][1]["status"], "ok")

    def test_free_news_rss_parser_normalizes_sources(self) -> None:
        xml = """
        <rss><channel>
          <item><title>BTC rallies</title><link>https://example.com/a</link><description>ETF inflow</description><pubDate>Mon, 01 Jun 2026 00:00:00 GMT</pubDate></item>
        </channel></rss>
        """

        rows = _parse_free_news_rss(xml)

        self.assertEqual(rows[0]["title"], "BTC rallies")
        self.assertEqual(rows[0]["url"], "https://example.com/a")
        self.assertIn("ETF", rows[0]["content"])

    def test_open_source_strategy_catalog_contains_expected_references(self) -> None:
        catalog = open_source_strategy_catalog()
        repo_ids = {item["id"] for item in catalog["repos"]}

        self.assertEqual(catalog["mode"], "research_registry")
        self.assertIn("polybot", repo_ids)
        self.assertIn("tradingview_mcp", repo_ids)
        self.assertIn("sec_edgar_mcp", repo_ids)

    def test_sec_lookup_and_recent_filings_extraction(self) -> None:
        mapping = {
            "0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."},
            "1": {"ticker": "MSFT", "cik_str": 789019, "title": "Microsoft Corp."},
        }
        payload = {
            "cik": "0000320193",
            "filings": {
                "recent": {
                    "form": ["8-K", "10-Q", "4"],
                    "filingDate": ["2026-05-30", "2026-05-02", "2026-04-01"],
                    "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002", "0000320193-26-000003"],
                    "primaryDocument": ["a8k.htm", "a10q.htm", "form4.htm"],
                    "primaryDocDescription": ["Current report", "Quarterly report", "Insider trade"],
                }
            },
        }

        company = _lookup_company_by_symbol(mapping, "AAPL")
        filings = _extract_recent_filings(payload, ["8-K", "10-Q"], 5)

        self.assertEqual(company["name"], "Apple Inc.")
        self.assertEqual(company["cik"], "0000320193")
        self.assertEqual(len(filings), 2)
        self.assertEqual(filings[0]["form"], "8-K")
        self.assertIn("sec.gov/Archives/edgar/data/320193/", filings[0]["filing_url"])
        self.assertEqual(_filing_signal(filings)["event_risk"], "high")

    def test_fred_csv_parser_computes_changes(self) -> None:
        csv_text = "observation_date,DFII10\n2026-05-29,1.90\n2026-06-01,1.75\n"

        parsed = _parse_fred_csv(csv_text, "DFII10", "10Y real yield")

        self.assertEqual(parsed["series_id"], "DFII10")
        self.assertEqual(parsed["latest_value"], 1.75)
        self.assertEqual(parsed["day_change"], -0.15)

    def test_macro_signals_score_gold_and_risk_bias(self) -> None:
        series = {
            "DFII10": {"month_change": -0.2},
            "DTWEXBGS": {"month_change": -1.0},
            "VIXCLS": {"latest_value": 15},
            "DGS10": {"month_change": -0.1},
            "DFF": {"month_change": 0.0},
        }

        signals = _macro_signals(series)

        self.assertEqual(signals["gold_macro_bias"], "bullish")
        self.assertEqual(signals["risk_asset_bias"], "bullish")
        self.assertTrue(signals["reasons"])

    def test_options_gex_math_and_summary(self) -> None:
        option = {"strike": 100, "impliedVolatility": 0.2, "openInterest": 100}
        call_gex = _option_gex(100, option, years_to_expiry=30 / 365, is_put=False)
        put_gex = _option_gex(100, option, years_to_expiry=30 / 365, is_put=True)
        payload = {
            "options": [
                {
                    "expirationDate": int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp()),
                    "calls": [option],
                    "puts": [option],
                }
            ]
        }

        summary = _summarize_options_gex("TEST", 100, [payload])

        self.assertGreater(_black_scholes_gamma(100, 100, 0.2, 30 / 365), 0)
        self.assertGreater(call_gex, 0)
        self.assertLess(put_gex, 0)
        self.assertEqual(summary["gamma_regime"], "neutral_gamma")
        self.assertEqual(summary["expiration_count"], 1)
        self.assertEqual(summary["exposure_basis"], "open_interest")

    def test_claude_json_contract_parser_accepts_strict_json(self) -> None:
        payload = {
            "content": [
                {
                    "type": "text",
                    "text": '{"verdict":"BULLISH_CATALYST","confidence":0.82,"reason":"spot ETF inflow acceleration","evidence":["source A"],"risks":["already priced"]}',
                }
            ]
        }

        parsed = _parse_claude_json(payload)

        self.assertEqual(parsed["verdict"], "BULLISH_CATALYST")
        self.assertEqual(parsed["confidence"], 0.82)

    def test_json_parser_normalizes_percent_confidence_and_missing_lists(self) -> None:
        parsed = _parse_json_text('{"verdict":"BULLISH_CATALYST","confidence":"98%","reason":"fresh upside catalyst"}')

        self.assertEqual(parsed["verdict"], "BULLISH_CATALYST")
        self.assertEqual(parsed["confidence"], 0.98)
        self.assertEqual(parsed["evidence"], [])
        self.assertEqual(parsed["risks"], [])

    def test_weak_calibration_blocks_trade(self) -> None:
        signal = replace(demo_signal(), brier_skill_score=-0.01)

        result = evaluate_confidence_gate(signal, TradingSystem().model_config)

        self.assertFalse(result.approved)
        self.assertEqual(result.direction_call, DirectionCall.NO_EDGE)
        self.assertIn("model calibration does not beat baseline", result.reasons)

    def test_earnings_window_reduces_confidence(self) -> None:
        signal = replace(demo_signal(), earnings_proximity_flag=True)

        result = evaluate_confidence_gate(signal, TradingSystem().model_config)

        self.assertTrue(result.approved)
        self.assertEqual(result.confidence, Confidence.MEDIUM)
        self.assertTrue(any("earnings" in warning for warning in result.warnings))

    def test_position_size_changes_with_confidence_and_spread(self) -> None:
        high = demo_signal()
        medium_wide = replace(high, confidence=Confidence.MEDIUM, spread_bps=25.0)

        high_size = calculate_position_size(high, RiskConfig(), entry_price=190, stop_price=184)
        reduced_size = calculate_position_size(medium_wide, RiskConfig(), entry_price=190, stop_price=184)

        self.assertTrue(high_size.approved)
        self.assertTrue(reduced_size.approved)
        self.assertGreater(high_size.quantity, reduced_size.quantity)
        self.assertIn("reduced for wide spread", reduced_size.reductions)

    def test_drawdown_reduces_size_then_halts(self) -> None:
        risk = RiskEngine(RiskConfig())
        request = OrderRequest("AAPL", OrderSide.BUY, 10, OrderType.LIMIT, limit_price=100)
        reduced_portfolio = PortfolioState(equity=100_000, cash=100_000, daily_pnl=-2_500)
        halted_portfolio = PortfolioState(equity=100_000, cash=100_000, daily_pnl=-5_100)

        reduced = risk.evaluate_order(reduced_portfolio, request, expected_price=100)
        halted = risk.evaluate_order(halted_portfolio, request, expected_price=100)

        self.assertTrue(reduced.approved)
        self.assertEqual(reduced.size_multiplier, 0.5)
        self.assertFalse(halted.approved)
        self.assertIn("daily drawdown halt reached", halted.violations)

    def test_kill_switch_cancels_open_orders_and_blocks_new_orders(self) -> None:
        system = TradingSystem()
        open_request = OrderRequest("AAPL", OrderSide.BUY, 10, OrderType.LIMIT, limit_price=180)
        open_order = system.oms.submit(open_request, system.portfolio, market_price=190, spread_bps=4, available_volume=1_000_000)

        result = system.activate_kill_switch("test")
        blocked = system.risk.evaluate_order(system.portfolio, open_request, expected_price=190)

        self.assertEqual(open_order.status, OrderStatus.CANCELED)
        self.assertEqual(result["canceled_orders"], 1)
        self.assertFalse(blocked.approved)
        self.assertIn("kill switch is active", blocked.violations)

    def test_oms_handles_partial_fill_duplicate_and_live_disabled(self) -> None:
        portfolio = PortfolioState(equity=100_000, cash=100_000)
        oms = PaperOrderManager(RiskConfig())
        request = OrderRequest("AAPL", OrderSide.BUY, 1000, OrderType.LIMIT, limit_price=190, client_order_id="same")

        first = oms.submit(request, portfolio, market_price=190, spread_bps=4, available_volume=1_000)
        duplicate = oms.submit(request, portfolio, market_price=190, spread_bps=4, available_volume=1_000)
        live = oms.submit(
            OrderRequest("AAPL", OrderSide.BUY, 1, OrderType.LIMIT, mode=ExecutionMode.MICRO_LIVE, limit_price=190),
            portfolio,
            market_price=190,
            spread_bps=4,
            available_volume=1_000,
        )

        self.assertEqual(first.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(first.filled_quantity, 10)
        self.assertEqual(duplicate.status, OrderStatus.REJECTED)
        self.assertEqual(live.status, OrderStatus.REJECTED)
        self.assertEqual(live.rejection_reason, "live trading is disabled")

    def test_execution_quality_tracks_slippage_and_missed_quantity(self) -> None:
        portfolio = PortfolioState(equity=100_000, cash=100_000)
        oms = PaperOrderManager(RiskConfig())
        order = oms.submit(
            OrderRequest("AAPL", OrderSide.BUY, 100, OrderType.LIMIT, limit_price=190),
            portfolio,
            market_price=190,
            spread_bps=10,
            available_volume=1_000,
        )

        quality = oms.execution_quality(order.id, spread_bps_at_order=10)

        self.assertIsNotNone(quality)
        self.assertEqual(quality.filled_quantity, 10)
        self.assertEqual(quality.missed_quantity, 90)
        self.assertGreater(quality.realized_slippage_bps, 0)

    def test_audit_chain_is_immutable_and_queryable_by_trade(self) -> None:
        audit = AuditLog()
        audit.append("signal", {"trade_id": "T1", "symbol": "AAPL"})
        audit.append("risk", {"trade_id": "T1", "approved": True})

        self.assertTrue(audit.verify_chain())
        self.assertEqual(len(audit.for_trade("T1")), 2)

    def test_integration_signal_to_paper_order_to_audit(self) -> None:
        system = TradingSystem()

        result = system.analyze_trade(
            demo_signal(),
            side=OrderSide.BUY,
            entry_price=190,
            stop_price=184,
            order_type=OrderType.LIMIT,
        )

        self.assertTrue(result["approved"])
        self.assertEqual(result["stage"], "order")
        self.assertTrue(system.audit.verify_chain())
        self.assertGreaterEqual(len(system.audit.for_trade(result["trade_id"])), 4)

    def test_live_mode_safety_blocks_before_capital(self) -> None:
        system = TradingSystem()

        result = system.analyze_trade(
            demo_signal(),
            side=OrderSide.BUY,
            entry_price=190,
            stop_price=184,
            order_type=OrderType.LIMIT,
            mode=ExecutionMode.MICRO_LIVE,
        )

        self.assertFalse(result["approved"])
        self.assertEqual(result["order"].rejection_reason, "live trading is disabled")

    def test_strategy_signal_contains_evidence_and_scores_quality(self) -> None:
        system = TradingSystem()

        result = system.publish_strategy_from_signal(demo_signal())

        signal = result["signal"]
        quality = result["quality"]
        self.assertEqual(signal.message_type, SignalMessageType.STRATEGY)
        self.assertEqual(signal.symbol, "AAPL")
        self.assertIn("Brier skill score", signal.content)
        self.assertGreaterEqual(quality.verifiability_score, 3.0)
        self.assertGreaterEqual(quality.risk_score, 5.0)
        self.assertEqual(system.heartbeat.poll()["message_count"], 1)

    def test_signal_quality_rewards_specific_verifiable_non_duplicate_content(self) -> None:
        signal = build_operation_signal(
            symbol="AAPL",
            side=OrderSide.BUY,
            price=190,
            quantity=10,
            content="Buy AAPL because chart breakout evidence supports upside. Risk invalid if below 184. Probability 68%.",
        )

        prediction = extract_prediction_from_signal(signal)
        quality = score_signal_quality(signal, duplicate=False)
        duplicate_quality = score_signal_quality(signal, duplicate=True)

        self.assertEqual(prediction.direction, DirectionCall.BULLISH)
        self.assertEqual(prediction.target_probability, 0.68)
        self.assertGreater(quality.overall_score, duplicate_quality.overall_score)

    def test_signal_store_feed_filters_and_duplicate_detection(self) -> None:
        store = SignalStore()
        first = build_operation_signal(
            symbol="AAPL",
            side=OrderSide.BUY,
            price=190,
            quantity=10,
            content="Buy AAPL with evidence and risk plan",
        )
        second = build_operation_signal(
            symbol="MSFT",
            side=OrderSide.SELL,
            price=400,
            quantity=5,
            content="Sell MSFT with evidence and risk plan",
        )

        store.publish(first)
        store.publish(second)

        self.assertTrue(store.is_duplicate("buy   aapl with evidence and risk plan"))
        self.assertEqual(len(store.feed(symbol="AAPL")), 1)
        self.assertEqual(len(store.feed(message_type=SignalMessageType.OPERATION)), 2)

    def test_market_intel_snapshot_warns_when_unavailable_or_stale(self) -> None:
        unavailable = MarketIntelSnapshot(False, None, "unavailable", 0)
        stale = MarketIntelSnapshot(True, datetime.now(timezone.utc) - timedelta(minutes=120), "active", 18)

        self.assertTrue(any("unavailable" in warning for warning in unavailable.warnings()))
        self.assertTrue(any("stale" in warning for warning in stale.warnings(max_age_minutes=90)))

    def test_tradingagents_team_produces_specialist_pipeline(self) -> None:
        team = TradingAgentsTeam()
        market_intel = MarketIntelSnapshot(
            available=True,
            last_updated_at=datetime.now(timezone.utc),
            news_status="active",
            headline_count=20,
            macro_verdict="supportive",
            latest_headline="Large-cap tech momentum remains active",
        )

        run = team.analyze(demo_signal(), market_intel)

        self.assertEqual(len(run.analyst_reports), 4)
        self.assertEqual(run.trader_proposal.action, TraderAction.BUY)
        self.assertIn(run.portfolio_decision.rating, {PortfolioRating.BUY, PortfolioRating.OVERWEIGHT})
        self.assertTrue(run.portfolio_decision.approved_for_execution)
        self.assertIn("outcome resolves", run.memory_reflection)

    def test_tradingagents_team_blocks_stale_data(self) -> None:
        team = TradingAgentsTeam()

        run = team.analyze(demo_signal(stale=True))

        self.assertEqual(run.portfolio_decision.direction_call, DirectionCall.NO_EDGE)
        self.assertFalse(run.portfolio_decision.approved_for_execution)
        self.assertTrue(any("stale" in warning for warning in run.portfolio_decision.warnings))

    def test_extreme_confluence_veto_blocks_when_news_is_not_aligned(self) -> None:
        run = TradingAgentsTeam().analyze(demo_signal(), MarketIntelSnapshot(False, None, "unavailable", 0))

        self.assertFalse(run.portfolio_decision.approved_for_execution)
        self.assertEqual(run.portfolio_decision.direction_call, DirectionCall.NO_EDGE)
        self.assertTrue(any("confluence veto" in warning for warning in run.portfolio_decision.warnings))

    def test_hybrid_gate_skips_downstream_checks_when_analyzer_has_no_edge(self) -> None:
        signal = fallback_signal("BTC-USD", "unit-test no edge")
        payload = {"subagents": {}}
        result = evaluate_hybrid_decision(
            signal,
            payload,
            catalyst={"verdict": "NO_TRADE", "llm_used": True, "news_provider": "tavily"},
            timeframes={"aligned_direction": "no_edge", "micro_trade_allowed": False, "timeframes": []},
            stream={"lag_candidate": {"decision": "OBSERVE_ONLY", "blockers": []}},
            statarb={"pairs": []},
        )

        self.assertEqual(result["gates"]["analyzer"]["status"], "blocked")
        self.assertEqual(result["gates"]["catalyst"]["status"], "skipped")
        self.assertEqual(result["gates"]["timeframe"]["status"], "skipped")
        self.assertEqual(result["gates"]["confluence"]["status"], "skipped")

    def test_system_records_subagent_analysis_in_audit(self) -> None:
        system = TradingSystem()

        result = system.run_subagent_analysis(demo_signal())

        self.assertIn("subagent_run", result)
        self.assertTrue(system.audit.verify_chain())
        self.assertEqual(system.audit.entries[-1].event_type, "subagent_analysis_completed")

    def test_dashboard_payload_contains_visual_sections_and_source_map(self) -> None:
        payload = build_demo_dashboard_payload()

        self.assertEqual(payload["symbol"], "AAPL")
        self.assertIn("trade_call", payload)
        self.assertIn(payload["trade_call"]["action"], {"BUY", "SELL", "NO TRADE"})
        self.assertGreater(len(payload["chart"]["candles"]), 0)
        self.assertIn("features", payload)
        self.assertIn("evidence", payload)
        self.assertGreaterEqual(len(payload["data_sources"]), 3)
        self.assertIn("subagents", payload)
        self.assertIn("paper_order", payload)
        self.assertIn("telegram_preview", payload)
        self.assertFalse(payload["runtime"]["live_market_data"])
        self.assertEqual(payload["runtime"]["payload_mode"], "api_demo")
        self.assertEqual(payload["source_map"]["subagents"], "src/prop_firm_ai/subagents.py")
        self.assertTrue(payload["audit"]["chain_valid"])

    def test_live_market_snapshot_builds_analyzer_signal(self) -> None:
        now = datetime.now(timezone.utc)
        candles = [
            Candle(now - timedelta(minutes=(60 - index) * 5), 100 + index * 0.1, 101 + index * 0.1, 99 + index * 0.1, 100 + index * 0.12, 100_000)
            for index in range(60)
        ]
        snapshot = MarketSnapshot("AAPL", "AAPL", "stock", "test provider", now, candles)

        signal = build_signal_from_snapshot(snapshot)

        self.assertEqual(signal.symbol, "AAPL")
        self.assertEqual(signal.model_version, "heuristic-yahoo-v1")
        self.assertTrue(signal.data_health.source.startswith("test provider"))
        self.assertGreater(signal.latest_price, 100)
        self.assertIn(signal.direction_call, {DirectionCall.BULLISH, DirectionCall.BEARISH, DirectionCall.NO_EDGE})

    def test_provider_error_fallback_is_no_edge_and_partial(self) -> None:
        signal = fallback_signal("BAD", "provider failed")

        self.assertEqual(signal.direction_call, DirectionCall.NO_EDGE)
        self.assertTrue(signal.data_health.is_stale)
        self.assertTrue(signal.data_health.partial)
        self.assertEqual(normalize_symbol("GOLD"), ("GC=F", "gold"))

    def test_scanner_rank_helpers_prioritize_actionable_fresh_calls(self) -> None:
        from prop_firm_ai.main import _attention_tier, _rank_score, _regime_summary

        actionable = {
            "trade_call": {"action": "BUY", "probability": 0.68},
            "probabilities": {"up": 0.68, "down": 0.2, "neutral": 0.12},
            "data_health": {"stale": False},
            "features": {"spread_bps": 4.0, "brier_skill_score": 0.05, "regime": "trending_up"},
        }
        blocked = {
            "trade_call": {"action": "NO TRADE", "probability": 0.34},
            "probabilities": {"up": 0.33, "down": 0.33, "neutral": 0.34},
            "data_health": {"stale": True},
            "features": {"spread_bps": 25.0, "brier_skill_score": -0.01, "regime": "ranging"},
        }

        actionable_score = _rank_score(actionable)
        blocked_score = _rank_score(blocked)

        self.assertGreater(actionable_score, blocked_score)
        self.assertEqual(_attention_tier(actionable, actionable_score), "actionable")
        self.assertEqual(_attention_tier(blocked, blocked_score), "ignore")
        summary = _regime_summary([
            {"features": {"regime": "trending_up"}, "trade_call": {"action": "BUY"}, "data_health": {"stale": False}},
            {"features": {"regime": "ranging"}, "trade_call": {"action": "NO TRADE"}, "data_health": {"stale": True}},
        ])
        self.assertEqual(summary["call_counts"]["BUY"], 1)
        self.assertIn("actionable", summary["headline"])

    def test_paper_simulation_replays_gated_trades_without_lookahead(self) -> None:
        import prop_firm_ai.backtest as backtest

        now = datetime.now(timezone.utc)
        candles = []
        price = 100.0
        for index in range(180):
            price += 0.35
            candles.append(
                Candle(
                    now + timedelta(days=index),
                    open=price - 0.2,
                    high=price + 1.8,
                    low=price - 0.6,
                    close=price,
                    volume=1_000_000,
                )
            )
        snapshot = MarketSnapshot("TEST", "TEST", "stock", "unit-test candles", now, candles)
        original_fetch = backtest.fetch_market_snapshot
        backtest.fetch_market_snapshot = lambda *args, **kwargs: snapshot
        try:
            result = run_paper_simulation("TEST", lookback=60, horizon=5)
            portfolio = run_watchlist_simulation(["TEST"], lookback=60, horizon=5)["portfolio"]
        finally:
            backtest.fetch_market_snapshot = original_fetch

        self.assertEqual(result["symbol"], "TEST")
        self.assertGreater(result["tested_setups"], 0)
        self.assertGreater(result["trades"], 0)
        self.assertIn("win_rate", result)
        self.assertIn("recent_trades", result)
        self.assertEqual(portfolio["trades"], result["trades"])

    def test_micro_scanner_is_monitor_only_without_polymarket_token(self) -> None:
        self.assertEqual(_best_level([{"price": "0.40", "size": "10"}, {"price": "0.42", "size": "5"}], reverse=True), (0.42, 5.0))

        scan = latency_gap_scan(binance_symbol="INVALID", polymarket_token_id=None)

        self.assertEqual(scan["mode"], "monitor_only")
        self.assertEqual(scan["decision"], "NO_TRADE")
        self.assertEqual(scan["status"], "needs_polymarket_token_id")
        self.assertIn("websocket_plan", scan)

    def test_polymarket_market_extractor_returns_yes_and_no_tokens(self) -> None:
        events = [
            {
                "id": "event1",
                "title": "Bitcoin test event",
                "liquidity": 1000,
                "volume24hr": 50,
                "markets": [
                    {
                        "id": "market1",
                        "question": "Bitcoin above test level?",
                        "active": True,
                        "closed": False,
                        "enableOrderBook": True,
                        "outcomes": '["Yes","No"]',
                        "outcomePrices": '["0.42","0.58"]',
                        "clobTokenIds": '["yes-token","no-token"]',
                        "liquidity": "1000",
                    }
                ],
            }
        ]

        rows = _extract_polymarket_markets(events)

        self.assertEqual(rows[0]["yes_token_id"], "yes-token")
        self.assertEqual(rows[0]["no_token_id"], "no-token")
        self.assertEqual(rows[0]["best_yes_price"], 0.42)

    def test_websocket_event_parsers_normalize_binance_and_polymarket(self) -> None:
        binance = _parse_binance_stream_event('{"u":1,"s":"BTCUSDT","b":"100.00","B":"1","a":"100.50","A":"2"}')
        polymarket = _parse_polymarket_stream_event(
            '{"event_type":"best_bid_ask","asset_id":"token","best_bid":"0.40","best_ask":"0.44","spread":"0.04"}'
        )

        self.assertEqual(binance.venue, "binance")
        self.assertEqual(binance.spread, 0.5)
        self.assertEqual(polymarket.venue, "polymarket")
        self.assertAlmostEqual(polymarket.spread, 0.04)

    def test_binance_l2_depth_parser_computes_imbalance(self) -> None:
        raw = '{"lastUpdateId":1,"bids":[["100.00","2"],["99.50","1"]],"asks":[["101.00","3"],["102.00","1"]]}'
        snapshot = _parse_binance_depth_snapshot(raw, symbol="BTCUSDT", levels=2)
        event = _parse_binance_depth_stream_event(raw, symbol="BTCUSDT", levels=2)

        self.assertEqual(snapshot.venue, "binance_l2")
        self.assertEqual(snapshot.bid, 100.0)
        self.assertEqual(snapshot.ask, 101.0)
        self.assertLess(snapshot.depth_imbalance, 0)
        self.assertEqual(event.event_type, "depth2")
        self.assertIsNotNone(event.bid_depth_notional)

    def test_lag_candidate_is_monitor_only_and_blocks_without_polymarket_edge(self) -> None:
        events = [
            {"venue": "binance_l2", "bid": 100.0, "ask": 100.2},
            {"venue": "binance_l2", "bid": 101.2, "ask": 101.4},
        ]
        candidate = score_lag_exploit_candidate(events, {"bid": 0.35, "ask": 0.40})
        missing = score_lag_exploit_candidate(events, {"bid": None, "ask": None})

        self.assertEqual(candidate["mode"], "monitor_only")
        self.assertFalse(candidate["execution_allowed"])
        self.assertEqual(candidate["decision"], "CANDIDATE")
        self.assertGreater(candidate["estimated_yes_edge"], 0.08)
        self.assertEqual(missing["decision"], "OBSERVE_ONLY")
        self.assertTrue(missing["blockers"])

    def test_microstructure_analytics_outputs_logit_ofi_vpin_and_quotes(self) -> None:
        events = [
            {"bid": 100.0, "ask": 100.1, "bid_size": 5, "ask_size": 3, "bid_depth_notional": 500, "ask_depth_notional": 300},
            {"bid": 100.1, "ask": 100.2, "bid_size": 6, "ask_size": 2, "bid_depth_notional": 650, "ask_depth_notional": 220},
            {"bid": 100.1, "ask": 100.2, "bid_size": 7, "ask_size": 2, "bid_depth_notional": 700, "ask_depth_notional": 210},
        ]

        analytics = microstructure_analytics(events)
        probability = logit_to_probability(probability_to_logit(0.62))

        self.assertGreater(analytics["microprice"], analytics["midpoint"])
        self.assertIn("fair_probability", analytics)
        self.assertIn("logit_probability", analytics)
        self.assertGreater(analytics["ofi"], 0)
        self.assertGreater(analytics["vpin_proxy"], 0)
        self.assertIsNotNone(analytics["avellaneda_stoikov"])
        self.assertAlmostEqual(probability, 0.62, places=6)

    def test_hybrid_gate_requires_catalyst_timeframe_confluence_and_keeps_live_disabled(self) -> None:
        signal = demo_signal()
        payload = {
            "subagents": {
                "confluence_approved": True,
                "confluence_matrix": [
                    {"role": "market_analyst", "stance": "bullish", "required": "bullish", "approved": True},
                    {"role": "news_analyst", "stance": "bullish", "required": "bullish", "approved": True},
                    {"role": "fundamentals_analyst", "stance": "bullish", "required": "bullish", "approved": True},
                ],
            }
        }
        catalyst = {"verdict": "BULLISH_CATALYST", "confidence": 0.9, "llm_used": True, "reason": "test catalyst"}
        timeframes = {"aligned_direction": "bullish", "micro_trade_allowed": True, "timeframes": [{}, {}, {}], "warnings": []}
        stream = {"lag_candidate": {"decision": "CANDIDATE", "execution_allowed": False, "estimated_yes_edge": 0.12}}
        statarb = {"pairs": [], "actionable_count": 0}

        decision = evaluate_hybrid_decision(signal, payload, catalyst, timeframes, stream, statarb)

        self.assertEqual(decision["decision"], "PAPER_CANDIDATE")
        self.assertTrue(decision["brain_approved"])
        self.assertTrue(decision["opportunity_found"])
        self.assertTrue(decision["approved_for_paper"])
        self.assertFalse(decision["approved_for_live"])
        self.assertIn("live trading disabled by system config", decision["blockers"])

    def test_hybrid_gate_blocks_keyword_only_catalyst_even_when_other_gates_pass(self) -> None:
        signal = demo_signal()
        payload = {"subagents": {"confluence_approved": True, "confluence_matrix": [{"role": "market_analyst", "stance": "bullish", "required": "bullish", "approved": True}]}}
        catalyst = {"verdict": "BULLISH_CATALYST", "llm_used": False, "reason": "keyword only"}
        timeframes = {"aligned_direction": "bullish", "micro_trade_allowed": True, "timeframes": [{}, {}, {}], "warnings": []}
        stream = {"lag_candidate": {"decision": "CANDIDATE", "execution_allowed": False}}
        statarb = {"pairs": [], "actionable_count": 0}

        decision = evaluate_hybrid_decision(signal, payload, catalyst, timeframes, stream, statarb)

        self.assertEqual(decision["decision"], "NO_TRADE")
        self.assertFalse(decision["brain_approved"])
        self.assertFalse(decision["approved_for_paper"])
        self.assertTrue(any("LLM veto is closed" in blocker for blocker in decision["blockers"]))

    def test_dual_websocket_probe_reports_missing_dependency_safely(self) -> None:
        import asyncio
        import prop_firm_ai.micro as micro

        original = micro.websockets
        micro.websockets = None
        try:
            result = asyncio.run(dual_websocket_probe(sample_seconds=0.01))
        finally:
            micro.websockets = original

        self.assertEqual(result["decision"], "NO_TRADE")
        self.assertEqual(result["status"], "websockets_dependency_missing")

    def test_statarb_pair_scan_flags_z_score_with_mocked_snapshots(self) -> None:
        import prop_firm_ai.statarb as statarb

        now = datetime.now(timezone.utc)
        left = [Candle(now + timedelta(days=i), 100, 101, 99, 100 + i * 0.1 + (20 if i == 59 else 0), 1_000_000) for i in range(60)]
        right = [Candle(now + timedelta(days=i), 100, 101, 99, 100 + i * 0.1, 1_000_000) for i in range(60)]
        snapshots = {
            "AAA": MarketSnapshot("AAA", "AAA", "stock", "test", now, left),
            "BBB": MarketSnapshot("BBB", "BBB", "stock", "test", now, right),
        }
        original_fetch = statarb.fetch_market_snapshot
        statarb.fetch_market_snapshot = lambda symbol, **kwargs: snapshots[symbol]
        try:
            result = scan_pair("AAA", "BBB")
        finally:
            statarb.fetch_market_snapshot = original_fetch

        self.assertEqual(result["decision"], "PAIR_TRADE_WATCH")
        self.assertGreater(result["z_score"], 2)

    def test_telegram_digest_names_subagents_and_decision(self) -> None:
        run = TradingAgentsTeam().analyze(demo_signal())
        message = format_telegram_digest(run)

        self.assertIn("AAPL AI Trading Desk", message)
        self.assertIn("Rating:", message)
        self.assertIn("Subagents:", message)
        self.assertIn("Portfolio manager", message)

    def test_explicit_36_hour_stale_data_path(self) -> None:
        now = datetime.now(timezone.utc)
        signal = replace(
            demo_signal(),
            data_health=DataHealth("AAPL", latest_candle_at=now - timedelta(hours=36), checked_at=now),
        )
        system = TradingSystem()

        result = system.analyze_trade(signal, OrderSide.BUY, entry_price=190, stop_price=184)

        self.assertFalse(result["approved"])
        self.assertEqual(result["stage"], "confidence_gate")
        self.assertEqual(result["gate"].direction_call, DirectionCall.NO_EDGE)


if __name__ == "__main__":
    unittest.main()
