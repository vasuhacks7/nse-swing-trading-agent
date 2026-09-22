import json
import logging
import random
from typing import Callable

import pandas as pd

from evolution.genome import StrategyGenome
from evolution.fitness import FitnessEvaluator

logger = logging.getLogger(__name__)


class EvolutionaryOptimizer:
    def __init__(self, data: dict[str, pd.DataFrame], backtest_config: dict,
                 evolution_config: dict):
        self.evaluator = FitnessEvaluator(
            data, backtest_config,
            fitness_metric=evolution_config.get("fitness_metric", "sharpe_ratio"),
        )
        self.pop_size = evolution_config.get("population_size", 50)
        self.generations = evolution_config.get("generations", 100)
        self.mutation_rate = evolution_config.get("mutation_rate", 0.1)
        self.crossover_rate = evolution_config.get("crossover_rate", 0.7)
        self.elite_count = evolution_config.get("elite_count", 5)
        self.tournament_size = evolution_config.get("tournament_size", 3)
        self.history: list[dict] = []

    def _tournament_select(self, population: list[StrategyGenome]) -> StrategyGenome:
        candidates = random.sample(population, min(self.tournament_size, len(population)))
        return max(candidates, key=lambda g: g.fitness)

    def _create_next_generation(self, population: list[StrategyGenome]) -> list[StrategyGenome]:
        sorted_pop = sorted(population, key=lambda g: g.fitness, reverse=True)
        next_gen = sorted_pop[:self.elite_count]

        while len(next_gen) < self.pop_size:
            if random.random() < self.crossover_rate:
                parent1 = self._tournament_select(population)
                parent2 = self._tournament_select(population)
                child = parent1.crossover(parent2)
            else:
                child = self._tournament_select(population)

            mutation_strength = max(0.02, 0.15 * (1 - len(self.history) / self.generations))
            child = child.mutate(self.mutation_rate, mutation_strength)
            next_gen.append(child)

        return next_gen

    def optimize(self, callback: Callable[[int, dict], None] | None = None) -> StrategyGenome:
        population = [StrategyGenome.random() for _ in range(self.pop_size)]
        best_overall = None

        for gen in range(self.generations):
            for genome in population:
                genome.fitness = self.evaluator.evaluate(genome)

            sorted_pop = sorted(population, key=lambda g: g.fitness, reverse=True)
            best = sorted_pop[0]
            avg_fitness = sum(g.fitness for g in population) / len(population)

            if best_overall is None or best.fitness > best_overall.fitness:
                best_overall = best

            gen_stats = {
                "generation": gen,
                "best_fitness": best.fitness,
                "avg_fitness": avg_fitness,
                "worst_fitness": sorted_pop[-1].fitness,
                "best_params": json.dumps(best.to_strategy_params()),
            }
            self.history.append(gen_stats)

            logger.info(
                f"Gen {gen}: best={best.fitness:.4f} avg={avg_fitness:.4f}"
            )

            if callback:
                callback(gen, gen_stats)

            population = self._create_next_generation(population)

        return best_overall

    def get_top_n(self, population: list[StrategyGenome], n: int = 5) -> list[StrategyGenome]:
        return sorted(population, key=lambda g: g.fitness, reverse=True)[:n]
