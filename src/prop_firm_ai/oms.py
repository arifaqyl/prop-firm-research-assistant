from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .domain import (
    ExecutionMode,
    ExecutionQuality,
    Fill,
    Order,
    OrderRequest,
    OrderStatus,
    OrderType,
    PortfolioState,
    Position,
    RiskConfig,
)


class PaperOrderManager:
    def __init__(self, risk_config: RiskConfig):
        self.risk_config = risk_config
        self.orders: dict[str, Order] = {}
        self.client_order_ids: set[str] = set()
        self.fills: list[Fill] = []
        self.events: list[dict] = []

    def submit(
        self,
        request: OrderRequest,
        portfolio: PortfolioState,
        market_price: float,
        spread_bps: float,
        available_volume: int,
    ) -> Order:
        now = datetime.now(timezone.utc)
        order = Order(str(uuid4()), request, OrderStatus.NEW, now, now)

        if request.client_order_id in self.client_order_ids:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "duplicate client_order_id"
            self._record(order, "rejected")
            return order

        if request.mode != ExecutionMode.PAPER and not self.risk_config.live_trading_enabled:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "live trading is disabled"
            self._record(order, "rejected")
            return order

        self.client_order_ids.add(request.client_order_id)
        order.status = OrderStatus.ACCEPTED
        self.orders[order.id] = order
        self._record(order, "accepted")

        fillable = self._is_fillable(request, market_price, spread_bps)
        if not fillable:
            return order

        max_fill = max(0, int(available_volume * self.risk_config.max_adv_participation_pct))
        fill_quantity = min(request.quantity, max_fill)
        if fill_quantity <= 0:
            return order

        expected_price = request.limit_price or market_price
        fill_price = self._fill_price(request, market_price, spread_bps)
        fill = Fill(str(uuid4()), order.id, request.symbol, fill_quantity, expected_price, fill_price, now)
        self.fills.append(fill)

        order.filled_quantity = fill_quantity
        order.average_fill_price = fill_price
        order.status = OrderStatus.FILLED if fill_quantity == request.quantity else OrderStatus.PARTIALLY_FILLED
        order.updated_at = now
        self._apply_fill_to_portfolio(portfolio, request.symbol, fill_quantity, fill_price, request.side.value)
        self._record(order, "filled" if order.status == OrderStatus.FILLED else "partially_filled")
        return order

    def cancel(self, order_id: str) -> Order | None:
        order = self.orders.get(order_id)
        if not order:
            return None
        if order.status in {OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELED}:
            return order
        order.status = OrderStatus.CANCELED
        order.updated_at = datetime.now(timezone.utc)
        self._record(order, "canceled")
        return order

    def cancel_open_orders(self) -> int:
        canceled = 0
        for order in list(self.orders.values()):
            if order.status in {OrderStatus.NEW, OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED}:
                self.cancel(order.id)
                canceled += 1
        return canceled

    def execution_quality(self, order_id: str, spread_bps_at_order: float) -> ExecutionQuality | None:
        order = self.orders.get(order_id)
        if not order:
            return None
        order_fills = [fill for fill in self.fills if fill.order_id == order_id]
        if not order_fills:
            return ExecutionQuality(
                order_id=order_id,
                symbol=order.request.symbol,
                expected_price=order.request.limit_price or 0.0,
                average_fill_price=None,
                requested_quantity=order.request.quantity,
                filled_quantity=0,
                spread_bps_at_order=spread_bps_at_order,
                realized_slippage_bps=None,
                missed_quantity=order.request.quantity,
            )
        total_quantity = sum(fill.quantity for fill in order_fills)
        average_fill = sum(fill.fill_price * fill.quantity for fill in order_fills) / total_quantity
        expected = order_fills[0].expected_price
        slippage = ((average_fill - expected) / expected) * 10_000 if expected else None
        return ExecutionQuality(
            order_id=order_id,
            symbol=order.request.symbol,
            expected_price=expected,
            average_fill_price=average_fill,
            requested_quantity=order.request.quantity,
            filled_quantity=total_quantity,
            spread_bps_at_order=spread_bps_at_order,
            realized_slippage_bps=slippage,
            missed_quantity=order.request.quantity - total_quantity,
        )

    def _is_fillable(self, request: OrderRequest, market_price: float, spread_bps: float) -> bool:
        if request.order_type == OrderType.MARKET:
            return spread_bps <= self.risk_config.max_market_order_spread_bps
        if request.order_type in {OrderType.LIMIT, OrderType.BRACKET}:
            if request.limit_price is None:
                return False
            if request.side.value == "buy":
                return request.limit_price >= market_price
            return request.limit_price <= market_price
        return False

    def _fill_price(self, request: OrderRequest, market_price: float, spread_bps: float) -> float:
        half_spread = market_price * (spread_bps / 10_000) / 2
        if request.side.value == "buy":
            return market_price + half_spread
        return market_price - half_spread

    def _apply_fill_to_portfolio(
        self,
        portfolio: PortfolioState,
        symbol: str,
        quantity: int,
        price: float,
        side: str,
    ) -> None:
        signed_quantity = quantity if side == "buy" else -quantity
        existing = portfolio.positions.get(symbol)
        if not existing:
            portfolio.positions[symbol] = Position(symbol, signed_quantity, price)
            portfolio.cash -= signed_quantity * price
            return
        new_quantity = existing.quantity + signed_quantity
        if new_quantity == 0:
            portfolio.cash -= signed_quantity * price
            del portfolio.positions[symbol]
            return
        existing.average_price = ((existing.quantity * existing.average_price) + (signed_quantity * price)) / new_quantity
        existing.quantity = new_quantity
        portfolio.cash -= signed_quantity * price

    def _record(self, order: Order, event_type: str) -> None:
        self.events.append(
            {
                "order_id": order.id,
                "client_order_id": order.request.client_order_id,
                "event_type": event_type,
                "status": order.status.value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": order.rejection_reason,
            }
        )
