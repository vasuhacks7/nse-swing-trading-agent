import logging
from dataclasses import dataclass, field

import pandas as pd
import numpy as np

from strategy.base import Strategy
from backtesting.metrics import calculate_all_metrics

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    side: str
    entry_date: str
    entry_price: float
    shares: float
    stop_loss: float
    take_profit: float
    signal_score: float


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[dict]
    metrics: dict
    signals_df: pd.DataFrame


class BacktestEngine:
    def __init__(self, initial_capital: float = 100000, commission_pct: float = 0.001,
                 slippage_pct: float = 0.001):
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct

    def run(self, df: pd.DataFrame, strategy_params: dict,
            risk_params: dict | None = None) -> BacktestResult:
        strategy = Strategy(strategy_params)
        signals_df = strategy.analyze(df)

        risk = risk_params or {}
        max_pos_pct = risk.get("max_position_pct", 0.10)
        stop_loss_atr_mult = risk.get("stop_loss_atr_multiplier", 2.0)
        take_profit_atr_mult = risk.get("take_profit_atr_multiplier", 3.0)
        max_open = risk.get("max_open_positions", 5)

        cash = self.initial_capital
        positions: list[Position] = []
        trades: list[dict] = []
        equity_history = []

        for i in range(len(signals_df)):
            row = signals_df.iloc[i]
            date = str(signals_df.index[i].date())
            price = row["close"]
            atr = row.get("atr", price * 0.02)

            if pd.isna(atr) or atr <= 0:
                atr = price * 0.02

            closed = []
            for pos in positions:
                if price <= pos.stop_loss or price >= pos.take_profit:
                    exit_price = price * (1 - self.slippage_pct)
                    commission = exit_price * pos.shares * self.commission_pct
                    pnl = (exit_price - pos.entry_price) * pos.shares - commission
                    cash += exit_price * pos.shares - commission
                    trades.append({
                        "symbol": pos.symbol, "side": "long",
                        "entry_date": pos.entry_date, "exit_date": date,
                        "entry_price": pos.entry_price, "exit_price": exit_price,
                        "shares": pos.shares, "pnl": pnl,
                        "pnl_pct": pnl / (pos.entry_price * pos.shares),
                        "signal_score": pos.signal_score,
                    })
                    closed.append(pos)

            if row.get("action") == "sell":
                for pos in positions:
                    if pos not in closed:
                        exit_price = price * (1 - self.slippage_pct)
                        commission = exit_price * pos.shares * self.commission_pct
                        pnl = (exit_price - pos.entry_price) * pos.shares - commission
                        cash += exit_price * pos.shares - commission
                        trades.append({
                            "symbol": pos.symbol, "side": "long",
                            "entry_date": pos.entry_date, "exit_date": date,
                            "entry_price": pos.entry_price, "exit_price": exit_price,
                            "shares": pos.shares, "pnl": pnl,
                            "pnl_pct": pnl / (pos.entry_price * pos.shares),
                            "signal_score": pos.signal_score,
                        })
                        closed.append(pos)

            positions = [p for p in positions if p not in closed]

            if row.get("action") == "buy" and len(positions) < max_open:
                portfolio_value = cash + sum(p.shares * price for p in positions)
                position_size = portfolio_value * max_pos_pct
                entry_price = price * (1 + self.slippage_pct)
                shares = position_size / entry_price
                commission = entry_price * shares * self.commission_pct

                if cash >= position_size + commission:
                    cash -= entry_price * shares + commission
                    positions.append(Position(
                        symbol=row.get("symbol", "UNKNOWN"),
                        side="long",
                        entry_date=date,
                        entry_price=entry_price,
                        shares=shares,
                        stop_loss=entry_price - atr * stop_loss_atr_mult,
                        take_profit=entry_price + atr * take_profit_atr_mult,
                        signal_score=row.get("composite_signal", 0),
                    ))

            portfolio_value = cash + sum(p.shares * price for p in positions)
            equity_history.append({"date": signals_df.index[i], "equity": portfolio_value})

        equity_df = pd.DataFrame(equity_history).set_index("date")
        equity_curve = equity_df["equity"]
        metrics = calculate_all_metrics(equity_curve, trades)

        return BacktestResult(
            equity_curve=equity_curve,
            trades=trades,
            metrics=metrics,
            signals_df=signals_df,
        )
