import logging

import pandas as pd

from backtesting.engine import BacktestEngine, BacktestResult
from evolution.genome import StrategyGenome

logger = logging.getLogger(__name__)


class FitnessEvaluator:
    def __init__(self, data: dict[str, pd.DataFrame], backtest_config: dict,
                 fitness_metric: str = "sharpe_ratio"):
        self.data = data
        self.engine = BacktestEngine(
            initial_capital=backtest_config.get("initial_capital", 100000),
            commission_pct=backtest_config.get("commission_pct", 0.001),
            slippage_pct=backtest_config.get("slippage_pct", 0.001),
        )
        self.fitness_metric = fitness_metric

    def evaluate(self, genome: StrategyGenome) -> float:
        strategy_params = genome.to_strategy_params()
        risk_params = genome.to_risk_params()
        fitness_scores = []

        for symbol, df in self.data.items():
            try:
                result = self.engine.run(df, strategy_params, risk_params)
                score = self._extract_fitness(result)
                fitness_scores.append(score)
            except Exception as e:
                logger.debug(f"Backtest failed for {symbol}: {e}")
                fitness_scores.append(-10.0)

        if not fitness_scores:
            return -10.0

        avg = sum(fitness_scores) / len(fitness_scores)
        worst = min(fitness_scores)
        return 0.7 * avg + 0.3 * worst

    def _extract_fitness(self, result: BacktestResult) -> float:
        m = result.metrics
        if self.fitness_metric == "sharpe_ratio":
            return m.get("sharpe_ratio", 0)
        elif self.fitness_metric == "sortino_ratio":
            return m.get("sortino_ratio", 0)
        elif self.fitness_metric == "total_return":
            return m.get("total_return", 0)
        elif self.fitness_metric == "combined":
            sharpe = m.get("sharpe_ratio", 0)
            dd = m.get("max_drawdown", 1)
            wr = m.get("win_rate", 0)
            dd_penalty = max(0, dd - 0.15) * 5
            return sharpe + wr - dd_penalty
        return m.get("sharpe_ratio", 0)
