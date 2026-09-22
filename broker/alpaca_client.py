import logging
from datetime import datetime

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, QueryOrderStatus

logger = logging.getLogger(__name__)


class AlpacaBroker:
    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        self.client = TradingClient(api_key, secret_key, paper=paper)
        self.paper = paper

    def get_account(self) -> dict:
        account = self.client.get_account()
        return {
            "equity": float(account.equity),
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "portfolio_value": float(account.portfolio_value),
            "status": account.status.value if account.status else "unknown",
        }

    def get_positions(self) -> list[dict]:
        positions = self.client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": p.side.value if p.side else "long",
                "avg_entry": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pnl": float(p.unrealized_pl),
                "unrealized_pnl_pct": float(p.unrealized_plpc),
            }
            for p in positions
        ]

    def submit_market_order(self, symbol: str, qty: float, side: str,
                            time_in_force: str = "day") -> dict:
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        tif = TimeInForce.DAY if time_in_force == "day" else TimeInForce.GTC

        request = MarketOrderRequest(
            symbol=symbol, qty=qty, side=order_side, time_in_force=tif,
        )
        order = self.client.submit_order(request)
        logger.info(f"Submitted {side} market order for {qty} {symbol}: {order.id}")
        return {
            "id": str(order.id),
            "symbol": order.symbol,
            "qty": str(order.qty),
            "side": order.side.value,
            "status": order.status.value,
            "submitted_at": str(order.submitted_at),
        }

    def submit_limit_order(self, symbol: str, qty: float, side: str,
                           limit_price: float, time_in_force: str = "day") -> dict:
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        tif = TimeInForce.DAY if time_in_force == "day" else TimeInForce.GTC

        request = LimitOrderRequest(
            symbol=symbol, qty=qty, side=order_side,
            time_in_force=tif, limit_price=limit_price,
        )
        order = self.client.submit_order(request)
        logger.info(f"Submitted {side} limit order for {qty} {symbol} @ ${limit_price}: {order.id}")
        return {
            "id": str(order.id),
            "symbol": order.symbol,
            "qty": str(order.qty),
            "side": order.side.value,
            "limit_price": str(order.limit_price),
            "status": order.status.value,
        }

    def get_orders(self, status: str = "open") -> list[dict]:
        query_status = QueryOrderStatus.OPEN if status == "open" else QueryOrderStatus.ALL
        request = GetOrdersRequest(status=query_status)
        orders = self.client.get_orders(request)
        return [
            {
                "id": str(o.id),
                "symbol": o.symbol,
                "qty": str(o.qty),
                "side": o.side.value,
                "status": o.status.value,
                "type": o.type.value if o.type else "unknown",
                "submitted_at": str(o.submitted_at),
            }
            for o in orders
        ]

    def cancel_order(self, order_id: str):
        self.client.cancel_order_by_id(order_id)
        logger.info(f"Cancelled order {order_id}")

    def close_position(self, symbol: str) -> dict:
        order = self.client.close_position(symbol)
        logger.info(f"Closed position for {symbol}")
        return {"symbol": symbol, "status": "closed", "order_id": str(order.id)}

    def close_all_positions(self):
        self.client.close_all_positions(cancel_orders=True)
        logger.info("Closed all positions")
