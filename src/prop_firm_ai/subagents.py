from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

import requests

from .community import MarketIntelSnapshot
from .confidence import evaluate_confidence_gate
from .domain import AnalyzerSignal, Confidence, DirectionCall, ModelConfig, RiskConfig


_SEC_FILINGS_CACHE: dict[str, list[dict[str, str]]] = {}


def get_sec_filings(symbol: str) -> list[dict[str, str]]:
    symbol = symbol.upper()
    if symbol in _SEC_FILINGS_CACHE:
        return _SEC_FILINGS_CACHE[symbol]

    cik_mapping = {
        "AAPL": "0000320193",
        "MSFT": "0000789019",
        "NVDA": "0001045810",
        "TSLA": "0001318605",
        "AMD": "0000002488",
        "META": "0001326801",
        "GOOGL": "0001652044",
        "AMZN": "0001018724",
    }
    cik = cik_mapping.get(symbol)
    if not cik:
        return []

    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        headers = {"User-Agent": "PropFirmAI/0.1 admin@propfirmai.com"}
        response = requests.get(url, headers=headers, timeout=3)
        response.raise_for_status()
        data = response.json()
        recent = data.get("filings", {}).get("recent", {})
        filings = []
        for i in range(min(3, len(recent.get("form", [])))):
            form = recent.get("form", [])[i]
            filing_date = recent.get("filingDate", [])[i]
            filings.append({
                "form": form,
                "filing_date": filing_date
            })
        _SEC_FILINGS_CACHE[symbol] = filings
        return filings
    except Exception as exc:
        return [{"error": str(exc)}]



class SubagentRole(StrEnum):
    MARKET_ANALYST = "market_analyst"
    SENTIMENT_ANALYST = "sentiment_analyst"
    NEWS_ANALYST = "news_analyst"
    FUNDAMENTALS_ANALYST = "fundamentals_analyst"
    BULL_RESEARCHER = "bull_researcher"
    BEAR_RESEARCHER = "bear_researcher"
    RESEARCH_MANAGER = "research_manager"
    TRADER = "trader"
    AGGRESSIVE_RISK = "aggressive_risk"
    NEUTRAL_RISK = "neutral_risk"
    CONSERVATIVE_RISK = "conservative_risk"
    PORTFOLIO_MANAGER = "portfolio_manager"


class PortfolioRating(StrEnum):
    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(StrEnum):
    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


@dataclass(frozen=True)
class SubagentReport:
    role: SubagentRole
    stance: DirectionCall
    confidence: Confidence
    score: float
    summary: str
    evidence: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResearchDebate:
    bull_report: SubagentReport
    bear_report: SubagentReport
    manager_report: SubagentReport


@dataclass(frozen=True)
class TraderProposal:
    action: TraderAction
    entry_price: float | None
    stop_loss: float | None
    position_sizing: str
    reasoning: str


@dataclass(frozen=True)
class RiskDebate:
    aggressive_report: SubagentReport
    neutral_report: SubagentReport
    conservative_report: SubagentReport
    manager_report: SubagentReport


@dataclass(frozen=True)
class PortfolioDecision:
    rating: PortfolioRating
    direction_call: DirectionCall
    confidence: Confidence
    approved_for_execution: bool
    executive_summary: str
    thesis: str
    price_target: float | None
    invalidation_level: float | None
    warnings: list[str]


@dataclass(frozen=True)
class SubagentRun:
    symbol: str
    created_at: datetime
    analyst_reports: list[SubagentReport]
    research_debate: ResearchDebate
    trader_proposal: TraderProposal
    risk_debate: RiskDebate
    portfolio_decision: PortfolioDecision
    memory_reflection: str


class TradingAgentsTeam:
    """Lightweight local version of the TradingAgents specialist workflow."""

    def __init__(self, model_config: ModelConfig | None = None, risk_config: RiskConfig | None = None) -> None:
        self.model_config = model_config or ModelConfig()
        self.risk_config = risk_config or RiskConfig()

    def analyze(self, signal: AnalyzerSignal, market_intel: MarketIntelSnapshot | None = None) -> SubagentRun:
        market_intel = market_intel or MarketIntelSnapshot(False, None, "unavailable", 0)
        analysts = [
            self._market_analyst(signal),
            self._sentiment_analyst(signal, market_intel),
            self._news_analyst(signal, market_intel),
            self._fundamentals_analyst(signal),
        ]
        research = self._research_debate(signal, analysts)
        trader = self._trader(signal, research.manager_report)
        risk = self._risk_debate(signal, trader, market_intel)
        portfolio = self._portfolio_manager(signal, analysts, research.manager_report, trader, risk.manager_report)
        reflection = self._memory_reflection(signal, portfolio)
        return SubagentRun(
            symbol=signal.symbol,
            created_at=datetime.now(timezone.utc),
            analyst_reports=analysts,
            research_debate=research,
            trader_proposal=trader,
            risk_debate=risk,
            portfolio_decision=portfolio,
            memory_reflection=reflection,
        )

    def _market_analyst(self, signal: AnalyzerSignal) -> SubagentReport:
        evidence = [
            f"regime={signal.regime}",
            f"atr={signal.atr:.2f}",
            f"spread_bps={signal.spread_bps:.1f}",
            f"direction={signal.direction_call.value}",
        ]
        warnings: list[str] = []
        score = 3.0
        stance = signal.direction_call
        if signal.regime == "trending_up" and signal.direction_call == DirectionCall.BULLISH:
            score += 1.2
        elif signal.regime == "trending_down" and signal.direction_call == DirectionCall.BEARISH:
            score += 1.2
        elif signal.regime == "high_volatility":
            score -= 1.0
            warnings.append("high-volatility regime reduces chart reliability")
        if signal.spread_bps > 20:
            score -= 0.8
            warnings.append("spread is wide for clean execution")
        return _report(
            SubagentRole.MARKET_ANALYST,
            stance,
            score,
            "Market analyst weighs technical regime, volatility, and execution cleanliness.",
            evidence,
            warnings,
        )

    def _sentiment_analyst(self, signal: AnalyzerSignal, market_intel: MarketIntelSnapshot) -> SubagentReport:
        evidence = [
            f"news_status={market_intel.news_status}",
            f"headline_count={market_intel.headline_count}",
            f"macro_verdict={market_intel.macro_verdict or 'unknown'}",
        ]
        warnings = market_intel.warnings()
        score = 3.0
        stance = DirectionCall.NEUTRAL
        if market_intel.news_status in {"elevated", "active"} and signal.direction_call in {DirectionCall.BULLISH, DirectionCall.BEARISH}:
            score += 0.5
            stance = signal.direction_call
        if warnings:
            score -= 0.7
        return _report(
            SubagentRole.SENTIMENT_ANALYST,
            stance,
            score,
            "Sentiment analyst uses market-intel freshness and headline activity as alternative context.",
            evidence,
            warnings,
        )

    def _news_analyst(self, signal: AnalyzerSignal, market_intel: MarketIntelSnapshot) -> SubagentReport:
        evidence = [
            f"latest_headline={market_intel.latest_headline or 'none'}",
            f"categories={len(market_intel.categories)}",
        ]
        warnings = []
        score = 3.0
        stance = DirectionCall.NEUTRAL
        if market_intel.headline_count >= 15:
            score += 0.7
            stance = signal.direction_call
        elif market_intel.headline_count == 0:
            score -= 0.6
            warnings.append("no recent headline activity to support the call")
        return _report(
            SubagentRole.NEWS_ANALYST,
            stance,
            score,
            "News analyst checks whether current headline flow supports or weakens the setup.",
            evidence,
            warnings,
        )

    def _fundamentals_analyst(self, signal: AnalyzerSignal) -> SubagentReport:
        evidence = [f"asset_type={signal.asset_type}", f"earnings_proximity={signal.earnings_proximity_flag}"]
        warnings: list[str] = []
        score = 3.0
        stance = DirectionCall.NEUTRAL
        if signal.asset_type == "gold":
            evidence.append("fundamentals deferred to macro/gold-specific features")
            stance = signal.direction_call
        elif signal.earnings_proximity_flag:
            score -= 1.0
            warnings.append("earnings proximity makes fundamentals/event distribution unstable")
        else:
            score += 0.4
            stance = signal.direction_call

        if signal.asset_type == "stock":
            filings = get_sec_filings(signal.symbol)
            for f in filings:
                if "error" in f:
                    evidence.append(f"SEC EDGAR: filing fetch error ({f['error']})")
                else:
                    evidence.append(f"SEC EDGAR: Form {f['form']} filed on {f['filing_date']}")

        return _report(
            SubagentRole.FUNDAMENTALS_ANALYST,
            stance,
            score,
            "Fundamentals analyst checks company/event risk or routes gold to macro-specific context.",
            evidence,
            warnings,
        )

    def _research_debate(self, signal: AnalyzerSignal, analysts: list[SubagentReport]) -> ResearchDebate:
        bullish_score = sum(report.score for report in analysts if report.stance == DirectionCall.BULLISH)
        bearish_score = sum(report.score for report in analysts if report.stance == DirectionCall.BEARISH)
        neutral_penalty = sum(0.25 for report in analysts if report.stance in {DirectionCall.NEUTRAL, DirectionCall.NO_EDGE})
        bull = _report(
            SubagentRole.BULL_RESEARCHER,
            DirectionCall.BULLISH,
            bullish_score - neutral_penalty,
            "Bull researcher argues the strongest upside case from analyst reports.",
            [item for report in analysts for item in report.evidence if report.stance == DirectionCall.BULLISH],
        )
        bear = _report(
            SubagentRole.BEAR_RESEARCHER,
            DirectionCall.BEARISH,
            bearish_score - neutral_penalty,
            "Bear researcher argues the strongest downside/risk case from analyst reports.",
            [item for report in analysts for item in report.evidence if report.stance == DirectionCall.BEARISH],
        )
        if bull.score > bear.score + 1:
            stance = DirectionCall.BULLISH
            summary = "Research manager favors the bull case after debate."
            score = bull.score
        elif bear.score > bull.score + 1:
            stance = DirectionCall.BEARISH
            summary = "Research manager favors the bear case after debate."
            score = bear.score
        else:
            stance = DirectionCall.NO_EDGE
            summary = "Research manager finds the debate too balanced for a strong edge."
            score = max(bull.score, bear.score)
        manager = _report(SubagentRole.RESEARCH_MANAGER, stance, score, summary, [bull.summary, bear.summary])
        return ResearchDebate(bull, bear, manager)

    def _trader(self, signal: AnalyzerSignal, research_manager: SubagentReport) -> TraderProposal:
        if research_manager.stance == DirectionCall.BULLISH:
            action = TraderAction.BUY
            stop = signal.latest_price - max(signal.atr * 2, signal.atr)
            target = signal.latest_price + signal.atr * 3
        elif research_manager.stance == DirectionCall.BEARISH:
            action = TraderAction.SELL
            stop = signal.latest_price + max(signal.atr * 2, signal.atr)
            target = signal.latest_price - signal.atr * 3
        else:
            action = TraderAction.HOLD
            stop = None
            target = None
        sizing = "use risk engine sizing; cap risk per trade before order submission"
        reasoning = f"Trader translates research stance {research_manager.stance.value} into {action.value} with ATR-based risk levels."
        return TraderProposal(action, signal.latest_price if action != TraderAction.HOLD else None, stop, sizing, reasoning + (f" Target: {target:.2f}." if target else ""))

    def _risk_debate(self, signal: AnalyzerSignal, trader: TraderProposal, market_intel: MarketIntelSnapshot) -> RiskDebate:
        aggressive = _report(
            SubagentRole.AGGRESSIVE_RISK,
            signal.direction_call if trader.action != TraderAction.HOLD else DirectionCall.NO_EDGE,
            4.0 if trader.action != TraderAction.HOLD else 2.0,
            "Aggressive risk voice supports taking the trade when the analyzer edge exists.",
            [f"expected_edge={signal.expected_edge:.4f}", f"confidence={signal.confidence.value}"],
        )
        neutral_warnings = market_intel.warnings()
        neutral = _report(
            SubagentRole.NEUTRAL_RISK,
            signal.direction_call if not neutral_warnings else DirectionCall.NEUTRAL,
            3.0 - min(len(neutral_warnings) * 0.5, 1.5),
            "Neutral risk voice balances model edge against context freshness.",
            [f"market_intel_warnings={len(neutral_warnings)}"],
            neutral_warnings,
        )
        conservative_warnings: list[str] = []
        conservative_score = 3.0
        if signal.earnings_proximity_flag:
            conservative_score += 1.0
            conservative_warnings.append("earnings proximity argues for smaller size or no trade")
        if signal.data_health.is_stale:
            conservative_score += 2.0
            conservative_warnings.extend(signal.data_health.warnings)
        conservative = _report(
            SubagentRole.CONSERVATIVE_RISK,
            DirectionCall.NO_EDGE if conservative_warnings else DirectionCall.NEUTRAL,
            conservative_score,
            "Conservative risk voice looks for reasons to block or reduce the trade.",
            [f"spread_bps={signal.spread_bps:.1f}", f"atr={signal.atr:.2f}"],
            conservative_warnings,
        )
        if signal.data_health.is_stale or trader.action == TraderAction.HOLD:
            manager_stance = DirectionCall.NO_EDGE
            manager_summary = "Risk manager blocks execution because core safety gates fail."
        elif conservative_warnings:
            manager_stance = DirectionCall.NEUTRAL
            manager_summary = "Risk manager allows only reduced conviction due to event/data warnings."
        else:
            manager_stance = signal.direction_call
            manager_summary = "Risk manager allows the proposal to proceed to portfolio gate."
        manager = _report(
            SubagentRole.PORTFOLIO_MANAGER,
            manager_stance,
            min(5.0, max(aggressive.score, neutral.score, 5.0 - len(conservative_warnings))),
            manager_summary,
            [aggressive.summary, neutral.summary, conservative.summary],
            conservative_warnings + neutral_warnings,
        )
        return RiskDebate(aggressive, neutral, conservative, manager)

    def _portfolio_manager(
        self,
        signal: AnalyzerSignal,
        analysts: list[SubagentReport],
        research_manager: SubagentReport,
        trader: TraderProposal,
        risk_manager: SubagentReport,
    ) -> PortfolioDecision:
        gate = evaluate_confidence_gate(signal, self.model_config)
        warnings = list(gate.warnings) + list(risk_manager.warnings)
        confluence = self._extreme_confluence(signal, analysts)
        warnings.extend(confluence["warnings"])
        approved = (
            gate.approved
            and confluence["approved"]
            and risk_manager.stance in {DirectionCall.BULLISH, DirectionCall.BEARISH}
            and trader.action != TraderAction.HOLD
        )
        if not approved:
            return PortfolioDecision(
                PortfolioRating.HOLD,
                DirectionCall.NO_EDGE,
                Confidence.LOW,
                False,
                "Portfolio manager refuses execution until research, confidence, confluence, and risk gates align.",
                (
                    f"Research stance={research_manager.stance.value}; risk stance={risk_manager.stance.value}; "
                    f"gate approved={gate.approved}; confluence approved={confluence['approved']}."
                ),
                None,
                None,
                warnings or gate.reasons,
            )
        if signal.direction_call == DirectionCall.BULLISH:
            rating = PortfolioRating.BUY if gate.confidence == Confidence.HIGH else PortfolioRating.OVERWEIGHT
            price_target = signal.latest_price + signal.atr * 3
        else:
            rating = PortfolioRating.SELL if gate.confidence == Confidence.HIGH else PortfolioRating.UNDERWEIGHT
            price_target = signal.latest_price - signal.atr * 3
        return PortfolioDecision(
            rating,
            signal.direction_call,
            gate.confidence,
            True,
            f"Portfolio manager approves {rating.value} with risk-engine sizing and audit logging.",
            f"Decision is backed by research stance={research_manager.stance.value}, trader action={trader.action.value}, and risk stance={risk_manager.stance.value}.",
            price_target,
            trader.stop_loss,
            warnings,
        )

    def _extreme_confluence(self, signal: AnalyzerSignal, analysts: list[SubagentReport]) -> dict[str, Any]:
        required_roles = {
            SubagentRole.MARKET_ANALYST,
            SubagentRole.NEWS_ANALYST,
            SubagentRole.FUNDAMENTALS_ANALYST,
        }
        required = [report for report in analysts if report.role in required_roles]
        missing = required_roles - {report.role for report in required}
        if signal.direction_call not in {DirectionCall.BULLISH, DirectionCall.BEARISH}:
            return {"approved": False, "warnings": ["confluence veto: analyzer has no directional call"], "matrix": []}
        matrix = [
            {
                "role": report.role.value,
                "stance": report.stance.value,
                "required": signal.direction_call.value,
                "approved": report.stance == signal.direction_call,
                "summary": report.summary,
            }
            for report in required
        ]
        warnings = [f"confluence veto: missing {role.value}" for role in missing]
        warnings.extend(
            f"confluence veto: {item['role']} is {item['stance']}, required {item['required']}"
            for item in matrix
            if not item["approved"]
        )
        return {"approved": not warnings, "warnings": warnings, "matrix": matrix}

    def _memory_reflection(self, signal: AnalyzerSignal, decision: PortfolioDecision) -> str:
        return (
            f"Record this {signal.symbol} decision with model={signal.model_version}, prompt={signal.prompt_version}, "
            f"rating={decision.rating.value}, confidence={decision.confidence.value}. "
            "When outcome resolves, compare raw return and alpha to this thesis before reusing the setup."
        )


def _report(
    role: SubagentRole,
    stance: DirectionCall,
    score: float,
    summary: str,
    evidence: list[str],
    warnings: list[str] | None = None,
) -> SubagentReport:
    bounded_score = max(0.0, min(5.0, score))
    if bounded_score >= 4:
        confidence = Confidence.HIGH
    elif bounded_score >= 2.5:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW
    return SubagentReport(role, stance, confidence, round(bounded_score, 4), summary, evidence, warnings or [])
