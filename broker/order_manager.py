import logging
from datetime import datetime

from broker.alpaca_client import AlpacaBroker
from data.store import DataStore

logger = logging.getLogger(__name__)


class OrderManager:
    def __init__(self, broker: AlpacaBroker, store: DataStore):
        self.broker = broker
        self.store = store
        self.pending_entries: dict[str, dict] = {}

    def execute_buy(self, symbol: str, signal_score: float,
                    position_size_dollars: float, current_price: float) -> dict | None:
        qty = int(position_size_dollars / current_price)
        if qty <= 0:
            logger.warning(f"Position size too small for {symbol}")
            return None

        try:
            order = self.broker.submit_market_order(symbol, qty, "buy")
            self.pending_entries[symbol] = {
                "symbol": symbol,
                "side": "long",
                "entry_date": datetime.now().strftime("%Y-%m-%d"),
                "entry_price": current_price,
                "shares": qty,
                "signal_score": signal_score,
            }
            logger.info(f"BUY {qty} shares of {symbol} @ ~${current_price:.2f}")
            return order
        except Exception as e:
            logger.error(f"Failed to execute buy for {symbol}: {e}")
            return None

    def execute_sell(self, symbol: str, current_price: float,
                     reason: str = "signal") -> dict | None:
        try:
            result = self.broker.close_position(symbol)
            entry = self.pending_entries.pop(symbol, {})
            trade_record = {
                "symbol": symbol,
                "side": "long",
                "entry_date": entry.get("entry_date", ""),
                "exit_date": datetime.now().strftime("%Y-%m-%d"),
                "entry_price": entry.get("entry_price", 0),
                "exit_price": current_price,
                "shares": entry.get("shares", 0),
                "pnl": (current_price - entry.get("entry_price", current_price)) * entry.get("shares", 0),
                "pnl_pct": (current_price / entry.get("entry_price", current_price) - 1)
                    if entry.get("entry_price") else 0,
                "signal_score": entry.get("signal_score", 0),
                "notes": f"Exit reason: {reason}",
            }
            self.store.save_trade(trade_record)
            logger.info(f"SELL {symbol} @ ~${current_price:.2f} | P&L: ${trade_record['pnl']:.2f}")
            return result
        except Exception as e:
            logger.error(f"Failed to execute sell for {symbol}: {e}")
            return None

    def sync_positions(self):
        positions = self.broker.get_positions()
        for pos in positions:
            sym = pos["symbol"]
            if sym not in self.pending_entries:
                self.pending_entries[sym] = {
                    "symbol": sym,
                    "side": pos["side"],
                    "entry_date": "",
                    "entry_price": pos["avg_entry"],
                    "shares": pos["qty"],
                    "signal_score": 0,
                }
        return positions
