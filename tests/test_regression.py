from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from prop_firm_ai.macro import _parse_json_text
from prop_firm_ai.subagents import get_sec_filings, TradingAgentsTeam
from prop_firm_ai.market_data import fetch_stooq_daily_candles
from prop_firm_ai.backtest import run_paper_simulation, SimulatedTrade, _compute_scorecard


class LocalModelRegressionTests(unittest.TestCase):
    def test_parse_json_text_handles_noise(self) -> None:
        raw_conversational = "Sure, here is the JSON:\n```json\n{\"verdict\": \"NO_TRADE\", \"confidence\": 0.95}\n```\nHope that helps!"
        parsed = _parse_json_text(raw_conversational)
        self.assertEqual(parsed["verdict"], "NO_TRADE")
        self.assertEqual(parsed["confidence"], 0.95)

    def test_parse_json_text_handles_raw(self) -> None:
        raw = "{\"verdict\": \"BULLISH_CATALYST\", \"confidence\": 0.8}"
        parsed = _parse_json_text(raw)
        self.assertEqual(parsed["verdict"], "BULLISH_CATALYST")
        self.assertEqual(parsed["confidence"], 0.8)

    @patch("requests.get")
    def test_get_sec_filings_success(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "filings": {
                "recent": {
                    "form": ["10-Q", "8-K"],
                    "filingDate": ["2026-05-01", "2026-04-15"]
                }
            }
        }
        mock_get.return_value = mock_response

        # Clear cache to guarantee fetch
        from prop_firm_ai.subagents import _SEC_FILINGS_CACHE
        _SEC_FILINGS_CACHE.clear()

        filings = get_sec_filings("AAPL")
        self.assertEqual(len(filings), 2)
        self.assertEqual(filings[0]["form"], "10-Q")
        self.assertEqual(filings[0]["filing_date"], "2026-05-01")

    @patch("requests.get")
    def test_fetch_stooq_daily_candles(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Date,Open,High,Low,Close,Volume\n2026-06-01,100,105,95,102,1000\n2026-05-29,98,101,97,99,800\n"
        mock_get.return_value = mock_response

        candles = fetch_stooq_daily_candles("AAPL")
        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[0].close, 102.0)
        self.assertEqual(candles[1].close, 99.0)

    def test_compute_scorecard_empty(self) -> None:
        scorecard = _compute_scorecard([])
        self.assertEqual(scorecard["trades"], 0)
        self.assertEqual(scorecard["win_rate"], 0.0)
        self.assertEqual(scorecard["total_r"], 0.0)
        self.assertEqual(scorecard["average_r"], 0.0)

    def test_compute_scorecard_with_values(self) -> None:
        t1 = SimulatedTrade("AAPL", "2026-06-01", "2026-06-02", "BUY", 100, 103, 98, 105, "target", 1.5, 0.7, "trending_up", "high")
        t2 = SimulatedTrade("AAPL", "2026-06-01", "2026-06-02", "BUY", 100, 98, 98, 105, "stop", -1.0, 0.7, "trending_up", "high")
        scorecard = _compute_scorecard([t1, t2])
        self.assertEqual(scorecard["trades"], 2)
        self.assertEqual(scorecard["win_rate"], 0.5)
        self.assertEqual(scorecard["total_r"], 0.5)
        self.assertEqual(scorecard["average_r"], 0.25)

    def test_calculate_rsi(self) -> None:
        from prop_firm_ai.market_data import _calculate_rsi
        prices = [100.0] * 20
        rsi = _calculate_rsi(prices, 14)
        self.assertEqual(len(rsi), 20)
        self.assertEqual(rsi[-1], 50.0)

        increasing_prices = [100.0 + i for i in range(25)]
        rsi_inc = _calculate_rsi(increasing_prices, 14)
        self.assertGreater(rsi_inc[-1], 50.0)

    def test_calculate_ema_and_macd(self) -> None:
        from prop_firm_ai.market_data import _calculate_ema, _calculate_macd
        prices = [100.0 + i for i in range(40)]
        ema = _calculate_ema(prices, 12)
        self.assertEqual(len(ema), 40)
        self.assertGreater(ema[-1], 100.0)

        macd_line, signal_line, histogram = _calculate_macd(prices)
        self.assertEqual(len(macd_line), 40)
        self.assertEqual(len(signal_line), 40)
        self.assertEqual(len(histogram), 40)

    def test_triple_confirmation_gate(self) -> None:
        from prop_firm_ai.market_data import Candle, MarketSnapshot, build_signal_from_snapshot
        from prop_firm_ai.domain import DirectionCall
        now = datetime.now(timezone.utc)
        
        # 1. Realistic upward trend: RSI is between 50 and 70
        candles_bull = []
        price = 100.0
        for i in range(80):
            if i % 3 == 2:
                price -= 0.25
            else:
                price += 0.25
            candles_bull.append(
                Candle(
                    timestamp=now,
                    open=price - 0.1,
                    high=price + 0.3,
                    low=price - 0.3,
                    close=price,
                    volume=100000.0
                )
            )
        snapshot_bull = MarketSnapshot("AAPL", "AAPL", "stock", "test", now, candles_bull)
        signal_bull = build_signal_from_snapshot(snapshot_bull, bypass_test_check=True)
        self.assertEqual(signal_bull.direction_call, DirectionCall.BULLISH)
        self.assertGreater(signal_bull.rsi, 50.0)
        self.assertLess(signal_bull.rsi, 70.0)

        # 2. Overbought upward trend: RSI is 100.0 (straight line)
        candles_overbought = [
            Candle(
                timestamp=now,
                open=100.0 + i * 0.5,
                high=101.0 + i * 0.5,
                low=99.0 + i * 0.5,
                close=100.0 + (i + 1) * 0.5,
                volume=100000.0
            ) for i in range(80)
        ]
        snapshot_ob = MarketSnapshot("AAPL", "AAPL", "stock", "test", now, candles_overbought)
        signal_ob = build_signal_from_snapshot(snapshot_ob, bypass_test_check=True)
        self.assertEqual(signal_ob.direction_call, DirectionCall.NO_EDGE)
        self.assertEqual(signal_ob.rsi, 100.0)

        # 3. Flat trend (no edge)
        flat_candles = [
            Candle(
                timestamp=now,
                open=100.0,
                high=100.5,
                low=99.5,
                close=100.0,
                volume=100000.0
            ) for i in range(80)
        ]
        flat_snapshot = MarketSnapshot("AAPL", "AAPL", "stock", "test", now, flat_candles)
        flat_signal = build_signal_from_snapshot(flat_snapshot, bypass_test_check=True)
        self.assertEqual(flat_signal.direction_call, DirectionCall.NO_EDGE)

