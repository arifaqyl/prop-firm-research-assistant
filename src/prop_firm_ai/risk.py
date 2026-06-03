from __future__ import annotations

from .domain import OrderRequest, OrderSide, PortfolioState, RiskConfig, RiskDecision


class RiskEngine:
    def __init__(self, config: RiskConfig):
        self.config = config

    def evaluate_order(
        self,
        portfolio: PortfolioState,
        request: OrderRequest,
        expected_price: float,
    ) -> RiskDecision:
        violations: list[str] = []
        reasons: list[str] = []

        if portfolio.kill_switch_active:
            violations.append("kill switch is active")

        daily_drawdown = -portfolio.daily_pnl / portfolio.equity if portfolio.equity else 0
        weekly_drawdown = -portfolio.weekly_pnl / portfolio.equity if portfolio.equity else 0

        size_multiplier = 1.0
        if daily_drawdown >= self.config.daily_halt_drawdown_pct:
            violations.append("daily drawdown halt reached")
        elif daily_drawdown >= self.config.daily_reduce_size_drawdown_pct:
            size_multiplier = 0.5
            reasons.append("daily drawdown reduction active")

        if weekly_drawdown >= self.config.weekly_halt_drawdown_pct:
            violations.append("weekly drawdown halt reached")

        order_notional = request.quantity * expected_price
        signed_notional = order_notional if request.side == OrderSide.BUY else -order_notional
        gross_after = portfolio.gross_exposure + abs(order_notional)
        net_after = portfolio.net_exposure + signed_notional
        symbol_after = abs(portfolio.positions.get(request.symbol, None).market_value if request.symbol in portfolio.positions else 0) + abs(order_notional)

        if gross_after > portfolio.equity * self.config.max_gross_exposure_pct:
            violations.append("gross exposure limit exceeded")
        if abs(net_after) > portfolio.equity * self.config.max_net_exposure_pct:
            violations.append("net exposure limit exceeded")
        if symbol_after > portfolio.equity * self.config.max_symbol_exposure_pct:
            violations.append("single-symbol exposure limit exceeded")

        if violations:
            return RiskDecision(False, 0.0, reasons, violations)

        reasons.append("portfolio risk checks passed")
        return RiskDecision(True, size_multiplier, reasons, violations)
