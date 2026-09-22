import logging
from datetime import datetime

from config.settings import Settings
from data.fetcher import DataFetcher
from data.store import DataStore
from data.advanced_analysis import full_analysis

logger = logging.getLogger(__name__)

STARTING_CAPITAL = 1_000_000


class PaperTrader:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.fetcher = DataFetcher(settings)
        self.store = DataStore(settings.db_path)
        self.store.init_paper_trading()

    def analyze_and_trade(self, symbol: str) -> dict:
        nse_symbol = symbol if symbol.endswith(".NS") else f"{symbol}.NS"

        df = self.fetcher.fetch_ohlcv(nse_symbol, period="2y")
        fundamentals = {}
        try:
            fundamentals = self.fetcher.fetch_fundamentals(nse_symbol)
        except Exception:
            pass

        analysis = full_analysis(df, fundamentals)

        if analysis["signal"] in ("STRONG_BUY", "BUY") and analysis["entry"]:
            portfolio = self.get_portfolio()
            cash = portfolio["cash"]
            position_size = cash * 0.10

            entry = analysis["entry"]
            stop_loss = analysis["stop_loss"]
            target = analysis["target"]
            qty = int(position_size / entry)

            if qty < 1:
                analysis["trade_action"] = "SKIP_NO_CAPITAL"
                return analysis

            risk = entry - stop_loss
            reward = target - entry
            rr = round(reward / risk, 2) if risk > 0 else 0

            existing = self.store.get_paper_position(nse_symbol)
            if existing:
                analysis["trade_action"] = "ALREADY_HOLDING"
                return analysis

            trade_id = self.store.open_paper_trade({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "symbol": nse_symbol,
                "action": "BUY",
                "entry_price": entry,
                "target_price": target,
                "stop_loss": stop_loss,
                "qty": qty,
                "invested": round(qty * entry, 2),
                "risk_reward": rr,
                "signal": analysis["signal"],
                "confluence_score": analysis["confluence_score"],
                "confluence_points": ", ".join(analysis["confluence_points"]),
            })

            analysis["trade_action"] = "BOUGHT"
            analysis["trade_id"] = trade_id
            analysis["qty"] = qty
            analysis["invested"] = round(qty * entry, 2)

        else:
            analysis["trade_action"] = "NO_SIGNAL"

        return analysis

    def track_positions(self) -> list[dict]:
        positions = self.store.get_open_paper_trades()
        closed = []

        for pos in positions:
            symbol = pos["symbol"]
            try:
                df = self.fetcher.fetch_ohlcv(symbol, period="5d")
                current = df["close"].iloc[-1]
                day_high = df["high"].iloc[-1]
            except Exception as e:
                logger.error(f"Could not fetch {symbol}: {e}")
                continue

            entry = pos["entry_price"]
            target = pos["target_price"]
            stop_loss = pos["stop_loss"]
            highest = max(pos.get("highest_price") or entry, day_high)

            self.store.update_paper_highest(pos["id"], highest)

            risk = entry - stop_loss
            if risk > 0 and (highest - entry) >= risk:
                trailing_stop = highest * 0.97
                if trailing_stop > stop_loss:
                    stop_loss = trailing_stop
                    self.store.update_paper_stop(pos["id"], stop_loss)

            exit_reason = None
            exit_price = None

            if current >= target:
                exit_reason = "TARGET_HIT"
                exit_price = target
            elif current <= stop_loss:
                exit_reason = "STOP_LOSS_HIT"
                exit_price = stop_loss
            else:
                entry_date = datetime.strptime(pos["date"], "%Y-%m-%d")
                holding_days = (datetime.now() - entry_date).days
                if holding_days > 20:
                    exit_reason = "MAX_HOLD"
                    exit_price = current

            if exit_reason:
                pnl_pct = round((exit_price - entry) / entry * 100, 2)
                pnl_amount = round((exit_price - entry) * pos["qty"], 2)
                holding_days = (datetime.now() - datetime.strptime(pos["date"], "%Y-%m-%d")).days

                self.store.close_paper_trade(pos["id"], {
                    "exit_price": exit_price,
                    "exit_date": datetime.now().strftime("%Y-%m-%d"),
                    "exit_reason": exit_reason,
                    "pnl_pct": pnl_pct,
                    "pnl_amount": pnl_amount,
                    "holding_days": holding_days,
                })
                closed.append({**pos, "exit_reason": exit_reason, "exit_price": exit_price,
                               "pnl_pct": pnl_pct, "pnl_amount": pnl_amount})

        return closed

    def get_portfolio(self) -> dict:
        trades = self.store.get_all_paper_trades()
        cash = STARTING_CAPITAL
        positions = []
        total_pnl = 0
        wins = 0
        losses = 0

        for t in trades:
            if t["status"] == "CLOSED":
                cash -= t["invested"]
                cash += t["invested"] + t.get("pnl_amount", 0)
                total_pnl += t.get("pnl_amount", 0)
                if t.get("pnl_pct", 0) > 0:
                    wins += 1
                else:
                    losses += 1
            elif t["status"] == "OPEN":
                cash -= t["invested"]
                positions.append(t)

        invested_value = sum(p["invested"] for p in positions)
        total_trades = wins + losses

        return {
            "starting_capital": STARTING_CAPITAL,
            "cash": round(cash, 2),
            "invested_value": round(invested_value, 2),
            "total_value": round(cash + invested_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl / STARTING_CAPITAL * 100, 2),
            "open_positions": positions,
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total_trades * 100, 1) if total_trades else 0,
        }
