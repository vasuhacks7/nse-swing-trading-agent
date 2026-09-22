import numpy as np
import pandas as pd


def total_return(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    return (equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1


def annualized_return(equity_curve: pd.Series, trading_days: int = 252) -> float:
    if len(equity_curve) < 2:
        return 0.0
    total = total_return(equity_curve)
    n_days = len(equity_curve)
    return (1 + total) ** (trading_days / n_days) - 1


def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.04, trading_days: int = 252) -> float:
    if returns.empty or returns.std() == 0:
        return 0.0
    daily_rf = (1 + risk_free_rate) ** (1 / trading_days) - 1
    excess = returns - daily_rf
    return np.sqrt(trading_days) * excess.mean() / excess.std()


def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.04, trading_days: int = 252) -> float:
    if returns.empty:
        return 0.0
    daily_rf = (1 + risk_free_rate) ** (1 / trading_days) - 1
    excess = returns - daily_rf
    downside = returns[returns < 0]
    if downside.empty or downside.std() == 0:
        return float("inf") if excess.mean() > 0 else 0.0
    return np.sqrt(trading_days) * excess.mean() / downside.std()


def max_drawdown(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    peak = equity_curve.cummax()
    drawdown = (equity_curve - peak) / peak
    return abs(drawdown.min())


def win_rate(trades: list[dict]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    return wins / len(trades)


def profit_factor(trades: list[dict]) -> float:
    gross_profit = sum(t["pnl"] for t in trades if t.get("pnl", 0) > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t.get("pnl", 0) < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def avg_trade_duration(trades: list[dict]) -> float:
    durations = []
    for t in trades:
        if t.get("entry_date") and t.get("exit_date"):
            entry = pd.Timestamp(t["entry_date"])
            exit_ = pd.Timestamp(t["exit_date"])
            durations.append((exit_ - entry).days)
    return np.mean(durations) if durations else 0.0


def calculate_all_metrics(equity_curve: pd.Series, trades: list[dict]) -> dict:
    returns = equity_curve.pct_change().dropna()
    return {
        "total_return": total_return(equity_curve),
        "annualized_return": annualized_return(equity_curve),
        "sharpe_ratio": sharpe_ratio(returns),
        "sortino_ratio": sortino_ratio(returns),
        "max_drawdown": max_drawdown(equity_curve),
        "win_rate": win_rate(trades),
        "profit_factor": profit_factor(trades),
        "avg_trade_duration": avg_trade_duration(trades),
        "total_trades": len(trades),
        "avg_pnl": np.mean([t.get("pnl", 0) for t in trades]) if trades else 0,
    }
