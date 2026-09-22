import copy
import random
from dataclasses import dataclass


@dataclass
class Gene:
    name: str
    value: float
    min_val: float
    max_val: float
    is_int: bool = False

    def mutate(self, mutation_strength: float = 0.1) -> "Gene":
        range_size = self.max_val - self.min_val
        noise = random.gauss(0, mutation_strength * range_size)
        new_val = max(self.min_val, min(self.max_val, self.value + noise))
        if self.is_int:
            new_val = round(new_val)
        return Gene(self.name, new_val, self.min_val, self.max_val, self.is_int)

    def randomize(self) -> "Gene":
        val = random.uniform(self.min_val, self.max_val)
        if self.is_int:
            val = round(val)
        return Gene(self.name, val, self.min_val, self.max_val, self.is_int)


class StrategyGenome:
    GENE_DEFINITIONS = [
        Gene("rsi_period", 14, 5, 30, is_int=True),
        Gene("rsi_oversold", 30, 15, 40),
        Gene("rsi_overbought", 70, 60, 85),
        Gene("macd_fast", 12, 5, 20, is_int=True),
        Gene("macd_slow", 26, 15, 40, is_int=True),
        Gene("macd_signal", 9, 5, 15, is_int=True),
        Gene("ma_short", 10, 5, 20, is_int=True),
        Gene("ma_medium", 20, 15, 40, is_int=True),
        Gene("ma_long", 50, 30, 100, is_int=True),
        Gene("bb_period", 20, 10, 30, is_int=True),
        Gene("bb_std_dev", 2.0, 1.0, 3.5),
        Gene("atr_period", 14, 7, 25, is_int=True),
        Gene("stoch_k", 14, 5, 25, is_int=True),
        Gene("stoch_d", 3, 2, 7, is_int=True),
        Gene("vol_avg_period", 20, 10, 40, is_int=True),
        Gene("vol_surge_mult", 1.5, 1.0, 3.0),
        Gene("w_rsi", 0.20, 0.0, 0.5),
        Gene("w_macd", 0.20, 0.0, 0.5),
        Gene("w_ma", 0.20, 0.0, 0.5),
        Gene("w_bb", 0.15, 0.0, 0.5),
        Gene("w_vol", 0.10, 0.0, 0.5),
        Gene("w_stoch", 0.15, 0.0, 0.5),
        Gene("buy_threshold", 0.3, 0.1, 0.6),
        Gene("sell_threshold", -0.3, -0.6, -0.1),
        Gene("stop_loss_atr", 2.0, 1.0, 4.0),
        Gene("take_profit_atr", 3.0, 1.5, 6.0),
        Gene("max_position_pct", 0.10, 0.03, 0.20),
    ]

    def __init__(self, genes: list[Gene] | None = None):
        if genes:
            self.genes = {g.name: g for g in genes}
        else:
            self.genes = {g.name: copy.deepcopy(g) for g in self.GENE_DEFINITIONS}
        self.fitness: float = 0.0

    @classmethod
    def random(cls) -> "StrategyGenome":
        genes = [g.randomize() for g in cls.GENE_DEFINITIONS]
        return cls(genes)

    def to_strategy_params(self) -> dict:
        g = {name: gene.value for name, gene in self.genes.items()}

        total_w = g["w_rsi"] + g["w_macd"] + g["w_ma"] + g["w_bb"] + g["w_vol"] + g["w_stoch"]
        if total_w > 0:
            g["w_rsi"] /= total_w
            g["w_macd"] /= total_w
            g["w_ma"] /= total_w
            g["w_bb"] /= total_w
            g["w_vol"] /= total_w
            g["w_stoch"] /= total_w

        return {
            "indicators": {
                "rsi": {"period": int(g["rsi_period"]), "oversold": g["rsi_oversold"], "overbought": g["rsi_overbought"]},
                "macd": {"fast": int(g["macd_fast"]), "slow": int(g["macd_slow"]), "signal": int(g["macd_signal"])},
                "moving_averages": {"short": int(g["ma_short"]), "medium": int(g["ma_medium"]), "long": int(g["ma_long"])},
                "bollinger": {"period": int(g["bb_period"]), "std_dev": g["bb_std_dev"]},
                "atr": {"period": int(g["atr_period"])},
                "stochastic": {"k_period": int(g["stoch_k"]), "d_period": int(g["stoch_d"])},
                "volume": {"avg_period": int(g["vol_avg_period"]), "surge_multiplier": g["vol_surge_mult"]},
            },
            "signals": {
                "weights": {
                    "rsi": g["w_rsi"], "macd": g["w_macd"],
                    "moving_averages": g["w_ma"], "bollinger": g["w_bb"],
                    "volume": g["w_vol"], "stochastic": g["w_stoch"],
                },
                "buy_threshold": g["buy_threshold"],
                "sell_threshold": g["sell_threshold"],
            },
        }

    def to_risk_params(self) -> dict:
        g = {name: gene.value for name, gene in self.genes.items()}
        return {
            "stop_loss_atr_multiplier": g["stop_loss_atr"],
            "take_profit_atr_multiplier": g["take_profit_atr"],
            "max_position_pct": g["max_position_pct"],
        }

    def crossover(self, other: "StrategyGenome") -> "StrategyGenome":
        child_genes = []
        for name, gene in self.genes.items():
            if random.random() < 0.5:
                child_genes.append(copy.deepcopy(gene))
            else:
                child_genes.append(copy.deepcopy(other.genes[name]))
        return StrategyGenome(child_genes)

    def mutate(self, mutation_rate: float = 0.1, mutation_strength: float = 0.1) -> "StrategyGenome":
        new_genes = []
        for gene in self.genes.values():
            if random.random() < mutation_rate:
                new_genes.append(gene.mutate(mutation_strength))
            else:
                new_genes.append(copy.deepcopy(gene))
        return StrategyGenome(new_genes)
