import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import yfinance as yf

from config.settings import Settings
from data.preprocessor import Preprocessor
from data.portfolio_risk import check_portfolio_risk
from strategy.manager import StrategyManager

logger = logging.getLogger(__name__)

BATCH_SIZE = 50


@dataclass
class BacktestTrade:
    symbol: str
    strategy: str
    entry_date: str
    entry_price: float
    target_price: float
    stop_loss: float
    score: float
    risk_reward: float
    exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl_pct: float = 0.0
    highest_price: float = 0.0
    trailing_stop: float = 0.0
    holding_days: int = 0
    partial_booked: bool = False
    partial_exit_price: float = 0.0


@dataclass
class BacktestResult:
    start_date: str
    end_date: str
    universe_size: int
    initial_capital: float
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    strategy_metrics: dict = field(default_factory=dict)
    monthly_returns: list[dict] = field(default_factory=list)


class Backtester:
    def __init__(self, settings: Settings, start_date: str = None, end_date: str = None,
                 universe_size: int = 200, initial_capital: float = 1000000):
        self.settings = settings
        self.end_date = end_date or datetime.now().strftime("%Y-%m-%d")
        self.start_date = start_date or (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        self.universe_size = universe_size
        self.initial_capital = initial_capital

        self.strategy_mgr = StrategyManager(settings.strategies)
        self.max_positions = settings.alerts.get("max_daily_alerts", 2)
        self.min_score = settings.alerts.get("min_signal_score", 0.65)
        self.min_rr = settings.alerts.get("min_risk_reward", 2.0)
        self.max_hold = settings.alerts.get("holding_period_days", 10)
        self.no_trade_threshold = settings.alerts.get("no_trade_threshold", 0.70)

        tsl = settings.risk.get("trailing_stop", {})
        self.tsl_enabled = tsl.get("enabled", True)
        self.tsl_activate_rr = tsl.get("activate_after_rr", 1.0)
        self.tsl_trail_pct = tsl.get("trail_pct", 0.03)

    def run(self, on_progress=None) -> BacktestResult:
        logger.info(f"Backtest: {self.start_date} to {self.end_date}, {self.universe_size} stocks")

        symbols = self._get_universe()
        if on_progress:
            on_progress("downloading", 0, len(symbols))

        all_data = self._download_data(symbols, on_progress)
        logger.info(f"Downloaded data for {len(all_data)} stocks")

        trading_days = self._get_trading_days(all_data)
        logger.info(f"Simulating {len(trading_days)} trading days")

        open_positions: list[BacktestTrade] = []
        closed_trades: list[BacktestTrade] = []
        capital = self.initial_capital
        equity_curve = []

        for day_idx, day in enumerate(trading_days):
            day_str = day.strftime("%Y-%m-%d")

            closed_today = self._manage_positions(open_positions, all_data, day, day_str)
            for trade in closed_today:
                trade_capital = self.initial_capital / self.max_positions
                capital += trade_capital * (trade.pnl_pct / 100)
                closed_trades.append(trade)
                open_positions.remove(trade)

            if len(open_positions) < self.max_positions:
                new_picks = self._generate_picks(all_data, day, open_positions)
                for pick in new_picks[:self.max_positions - len(open_positions)]:
                    trade = BacktestTrade(
                        symbol=pick.symbol,
                        strategy=pick.strategy,
                        entry_date=day_str,
                        entry_price=pick.entry_price,
                        target_price=pick.target_price,
                        stop_loss=pick.stop_loss,
                        score=pick.score,
                        risk_reward=pick.risk_reward_ratio,
                        highest_price=pick.entry_price,
                        trailing_stop=pick.stop_loss,
                    )
                    open_positions.append(trade)

            open_value = sum(
                self._get_price(all_data, t.symbol, day) / t.entry_price
                * (self.initial_capital / self.max_positions)
                for t in open_positions
                if self._get_price(all_data, t.symbol, day)
            )
            cash = capital - len(open_positions) * (self.initial_capital / self.max_positions)
            equity_curve.append({
                "date": day_str,
                "equity": round(cash + open_value, 2),
                "open_positions": len(open_positions),
                "total_trades": len(closed_trades),
            })

            if on_progress and (day_idx + 1) % 10 == 0:
                on_progress("simulating", day_idx + 1, len(trading_days))

        for trade in list(open_positions):
            last_day = trading_days[-1]
            price = self._get_price(all_data, trade.symbol, last_day)
            if price:
                trade.exit_date = last_day.strftime("%Y-%m-%d")
                trade.exit_price = price
                trade.exit_reason = "BACKTEST_END"
                trade.pnl_pct = round((price - trade.entry_price) / trade.entry_price * 100, 2)
                trade.holding_days = (last_day - pd.Timestamp(trade.entry_date)).days
            closed_trades.append(trade)
        open_positions.clear()

        result = BacktestResult(
            start_date=self.start_date,
            end_date=self.end_date,
            universe_size=len(all_data),
            initial_capital=self.initial_capital,
            trades=closed_trades,
            equity_curve=equity_curve,
        )
        result.metrics = self._compute_metrics(closed_trades, equity_curve)
        result.strategy_metrics = self._compute_strategy_metrics(closed_trades)
        result.monthly_returns = self._compute_monthly_returns(closed_trades)

        logger.info(f"Backtest done: {len(closed_trades)} trades, "
                     f"win rate={result.metrics.get('win_rate', 0):.1f}%, "
                     f"total return={result.metrics.get('total_return_pct', 0):.2f}%")
        return result

    def _get_universe(self) -> list[str]:
        try:
            from data.nse_universe import fetch_all_nse_symbols
            symbols = fetch_all_nse_symbols()
        except Exception:
            symbols = [f"{s}.NS" for s in [
                "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR",
                "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "ITC", "AXISBANK",
                "BAJFINANCE", "MARUTI", "HCLTECH", "SUNPHARMA", "TITAN",
                "TATAMOTORS", "WIPRO", "NTPC", "POWERGRID", "ULTRACEMCO",
                "NESTLEIND", "TECHM", "JSWSTEEL", "TATASTEEL", "ADANIENT",
                "BAJAJFINSV", "ONGC", "COALINDIA", "GRASIM", "DIVISLAB",
                "CIPLA", "DRREDDY", "EICHERMOT", "HEROMOTOCO", "APOLLOHOSP",
                "BPCL", "BRITANNIA", "INDUSINDBK", "HINDALCO", "M&M",
            ]]
        return symbols[:self.universe_size]

    def _download_data(self, symbols: list[str], on_progress=None) -> dict[str, pd.DataFrame]:
        download_start = (pd.Timestamp(self.start_date) - timedelta(days=300)).strftime("%Y-%m-%d")
        all_data = {}

        for i in range(0, len(symbols), BATCH_SIZE):
            batch = symbols[i:i + BATCH_SIZE]
            tickers_str = " ".join(batch)

            try:
                data = yf.download(tickers_str, start=download_start, end=self.end_date,
                                   progress=False, threads=True, group_by="ticker")
            except Exception as e:
                logger.debug(f"Batch download failed: {e}")
                if on_progress:
                    on_progress("downloading", min(i + BATCH_SIZE, len(symbols)), len(symbols))
                continue

            for sym in batch:
                try:
                    if len(batch) == 1:
                        df = data.copy()
                    else:
                        if sym not in data.columns.get_level_values(0):
                            continue
                        df = data[sym].copy()

                    df = df.dropna(subset=["Close"])
                    if len(df) < 60:
                        continue

                    df.index = pd.to_datetime(df.index).tz_localize(None)
                    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                            "Close": "close", "Volume": "volume"})
                    df = df[["open", "high", "low", "close", "volume"]]
                    df["symbol"] = sym

                    try:
                        df = Preprocessor.add_indicators(df)
                        all_data[sym] = df
                    except Exception:
                        pass
                except Exception:
                    continue

            if on_progress:
                on_progress("downloading", min(i + BATCH_SIZE, len(symbols)), len(symbols))

        return all_data

    def _get_trading_days(self, all_data: dict) -> list[pd.Timestamp]:
        if not all_data:
            return []
        sample_df = next(iter(all_data.values()))
        start_ts = pd.Timestamp(self.start_date)
        end_ts = pd.Timestamp(self.end_date)
        mask = (sample_df.index >= start_ts) & (sample_df.index <= end_ts)
        return sorted(sample_df.index[mask].tolist())

    def _manage_positions(self, open_positions: list[BacktestTrade], all_data: dict,
                          day: pd.Timestamp, day_str: str) -> list[BacktestTrade]:
        closed = []
        for trade in list(open_positions):
            df = all_data.get(trade.symbol)
            if df is None or day not in df.index:
                continue

            row = df.loc[day]
            current_price = row["close"]
            day_high = row["high"]
            day_low = row["low"]
            holding_days = (day - pd.Timestamp(trade.entry_date)).days

            if day_high > trade.highest_price:
                trade.highest_price = day_high

            if self.tsl_enabled:
                risk = trade.entry_price - trade.stop_loss
                if risk > 0:
                    profit = trade.highest_price - trade.entry_price
                    r_multiple = profit / risk
                    if r_multiple >= self.tsl_activate_rr:
                        new_tsl = trade.highest_price * (1 - self.tsl_trail_pct)
                        if new_tsl > trade.trailing_stop:
                            trade.trailing_stop = round(new_tsl, 2)

                        if not trade.partial_booked:
                            trade.partial_booked = True
                            trade.partial_exit_price = current_price

            active_stop = max(trade.trailing_stop, trade.stop_loss)

            exit_reason = None
            exit_price = current_price

            if day_high >= trade.target_price:
                exit_reason = "TARGET_HIT"
                exit_price = trade.target_price
            elif day_low <= active_stop:
                if trade.trailing_stop > trade.stop_loss:
                    exit_reason = "TRAILING_STOP_HIT"
                    exit_price = active_stop
                else:
                    exit_reason = "STOP_LOSS_HIT"
                    exit_price = trade.stop_loss
            elif holding_days >= self.max_hold:
                exit_reason = "MAX_HOLD"
                exit_price = current_price

            if exit_reason:
                trade.exit_date = day_str
                trade.exit_price = round(exit_price, 2)
                trade.exit_reason = exit_reason
                trade.holding_days = holding_days

                if trade.partial_booked and trade.partial_exit_price:
                    partial_pnl = (trade.partial_exit_price - trade.entry_price) / trade.entry_price * 100
                    final_pnl = (exit_price - trade.entry_price) / trade.entry_price * 100
                    trade.pnl_pct = round(0.5 * partial_pnl + 0.5 * final_pnl, 2)
                else:
                    trade.pnl_pct = round((exit_price - trade.entry_price) / trade.entry_price * 100, 2)

                closed.append(trade)

        return closed

    def _generate_picks(self, all_data: dict, day: pd.Timestamp,
                        open_positions: list[BacktestTrade]) -> list:
        open_symbols = {t.symbol for t in open_positions}
        universe_data = {}

        for sym, df in all_data.items():
            if sym in open_symbols:
                continue
            mask = df.index <= day
            df_slice = df[mask]
            if len(df_slice) < 60:
                continue
            universe_data[sym] = {"ohlcv": df_slice, "fundamentals": {}}

        if not universe_data:
            return []

        picks = self.strategy_mgr.get_top_picks(universe_data, self.max_positions * 3, self.min_score)
        picks = [p for p in picks if p.risk_reward_ratio >= self.min_rr]

        if picks and picks[0].score < self.no_trade_threshold:
            return []

        picks = check_portfolio_risk(picks, open_positions, universe_data)
        return picks[:self.max_positions]

    def _get_price(self, all_data: dict, symbol: str, day: pd.Timestamp) -> float | None:
        df = all_data.get(symbol)
        if df is None:
            return None
        mask = df.index <= day
        subset = df[mask]
        if subset.empty:
            return None
        return float(subset["close"].iloc[-1])

    def _compute_metrics(self, trades: list[BacktestTrade], equity_curve: list[dict]) -> dict:
        if not trades:
            return {"total_trades": 0}

        real_trades = [t for t in trades if t.exit_reason != "BACKTEST_END"]
        all_pnl = [t.pnl_pct for t in real_trades]
        if not all_pnl:
            return {"total_trades": 0}

        wins = [p for p in all_pnl if p > 0]
        losses = [p for p in all_pnl if p <= 0]

        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

        equities = [e["equity"] for e in equity_curve]
        if equities:
            peak = equities[0]
            max_dd = 0
            for eq in equities:
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak * 100
                if dd > max_dd:
                    max_dd = dd
        else:
            max_dd = 0

        daily_returns = []
        for i in range(1, len(equities)):
            if equities[i - 1] > 0:
                daily_returns.append((equities[i] - equities[i - 1]) / equities[i - 1])
        if daily_returns:
            mean_ret = np.mean(daily_returns)
            std_ret = np.std(daily_returns)
            sharpe = (mean_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0
        else:
            sharpe = 0

        final_equity = equities[-1] if equities else self.initial_capital
        total_return = (final_equity - self.initial_capital) / self.initial_capital * 100

        avg_hold = np.mean([t.holding_days for t in real_trades]) if real_trades else 0

        return {
            "total_trades": len(real_trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(len(wins) / len(real_trades) * 100, 1) if real_trades else 0,
            "avg_return_pct": round(np.mean(all_pnl), 2),
            "avg_win_pct": round(np.mean(wins), 2) if wins else 0,
            "avg_loss_pct": round(np.mean(losses), 2) if losses else 0,
            "best_trade_pct": round(max(all_pnl), 2),
            "worst_trade_pct": round(min(all_pnl), 2),
            "total_return_pct": round(total_return, 2),
            "final_equity": round(final_equity, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 99.9,
            "avg_holding_days": round(avg_hold, 1),
            "gross_profit_pct": round(gross_profit, 2),
            "gross_loss_pct": round(gross_loss, 2),
        }

    def _compute_strategy_metrics(self, trades: list[BacktestTrade]) -> dict:
        by_strategy = {}
        real_trades = [t for t in trades if t.exit_reason != "BACKTEST_END"]

        for trade in real_trades:
            s = trade.strategy
            if s not in by_strategy:
                by_strategy[s] = []
            by_strategy[s].append(trade)

        result = {}
        for strategy, strades in by_strategy.items():
            pnls = [t.pnl_pct for t in strades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            gp = sum(wins) if wins else 0
            gl = abs(sum(losses)) if losses else 0

            result[strategy] = {
                "total_trades": len(strades),
                "win_rate": round(len(wins) / len(strades) * 100, 1) if strades else 0,
                "avg_return_pct": round(np.mean(pnls), 2),
                "avg_win_pct": round(np.mean(wins), 2) if wins else 0,
                "avg_loss_pct": round(np.mean(losses), 2) if losses else 0,
                "best_trade_pct": round(max(pnls), 2),
                "worst_trade_pct": round(min(pnls), 2),
                "total_pnl_pct": round(sum(pnls), 2),
                "profit_factor": round(gp / gl, 2) if gl > 0 else 99.9,
                "avg_holding_days": round(np.mean([t.holding_days for t in strades]), 1),
            }

        return result

    def _compute_monthly_returns(self, trades: list[BacktestTrade]) -> list[dict]:
        monthly = {}
        for t in trades:
            if not t.exit_date or t.exit_reason == "BACKTEST_END":
                continue
            month = t.exit_date[:7]
            if month not in monthly:
                monthly[month] = {"month": month, "trades": 0, "wins": 0, "total_pnl": 0.0}
            monthly[month]["trades"] += 1
            monthly[month]["total_pnl"] += t.pnl_pct
            if t.pnl_pct > 0:
                monthly[month]["wins"] += 1

        result = []
        for month in sorted(monthly.keys()):
            m = monthly[month]
            m["win_rate"] = round(m["wins"] / m["trades"] * 100, 1) if m["trades"] > 0 else 0
            m["total_pnl"] = round(m["total_pnl"], 2)
            result.append(m)
        return result
