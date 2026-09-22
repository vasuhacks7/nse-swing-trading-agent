import json
import logging
from datetime import datetime, timedelta

import pandas as pd

from config.settings import Settings
from data.store import DataStore
from reflection.llm_advisor import LLMAdvisor
from agent.scanner_learner import ScannerLearner

logger = logging.getLogger(__name__)


class ImprovementEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = DataStore(settings.db_path)
        self.llm_advisor = LLMAdvisor(
            model=settings.reflection.get("model", "claude-sonnet-5"),
        )
        self.scanner_learner = ScannerLearner(settings)

    def compute_strategy_scores(self) -> dict[str, dict]:
        strategies = self.settings.get_enabled_strategies()
        scores = {}

        for strategy_name in strategies:
            closed = self.store.get_closed_alerts(strategy=strategy_name, limit=500)
            if closed.empty:
                scores[strategy_name] = {
                    "strategy": strategy_name,
                    "total_alerts": 0,
                    "win_rate": 0,
                    "current_weight": self.settings.strategies.get(strategy_name, {}).get("weight", 1.0),
                }
                continue

            wins = closed[closed["pnl_pct"] > 0]
            losses = closed[closed["pnl_pct"] <= 0]
            win_rate = len(wins) / len(closed) if len(closed) > 0 else 0
            avg_win = wins["pnl_pct"].mean() if len(wins) > 0 else 0
            avg_loss = abs(losses["pnl_pct"].mean()) if len(losses) > 0 else 0
            profit_factor = (avg_win * len(wins)) / (avg_loss * len(losses)) if avg_loss * len(losses) > 0 else float("inf")

            score = {
                "strategy": strategy_name,
                "period_start": closed["date"].min(),
                "period_end": closed["date"].max(),
                "total_alerts": len(closed),
                "winning_alerts": len(wins),
                "losing_alerts": len(losses),
                "avg_return_pct": round(closed["pnl_pct"].mean(), 2),
                "win_rate": round(win_rate, 3),
                "avg_win_pct": round(avg_win, 2),
                "avg_loss_pct": round(-abs(avg_loss), 2),
                "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 99.0,
            }
            scores[strategy_name] = score

        return scores

    def update_strategy_weights(self) -> dict[str, float]:
        scores = self.compute_strategy_scores()
        improve_cfg = self.settings.improvement
        promote_threshold = improve_cfg.get("promote_threshold_winrate", 0.55)
        demote_threshold = improve_cfg.get("demote_threshold_winrate", 0.35)
        min_weight = improve_cfg.get("strategy_weight_min", 0.2)
        max_weight = improve_cfg.get("strategy_weight_max", 3.0)
        min_trades = improve_cfg.get("min_trades_for_review", 5)

        current_weights = self.store.get_latest_strategy_weights()
        new_weights = {}
        changes = []

        for name, score in scores.items():
            old_weight = current_weights.get(name, 1.0)

            if score["total_alerts"] < min_trades:
                new_weights[name] = old_weight
                continue

            win_rate = score["win_rate"]
            avg_return = score.get("avg_return_pct", 0)

            if win_rate >= promote_threshold and avg_return > 0:
                new_weight = min(old_weight * 1.2, max_weight)
                changes.append(f"PROMOTED {name}: win_rate={win_rate:.1%}, weight {old_weight:.2f}→{new_weight:.2f}")
            elif win_rate <= demote_threshold or avg_return < -2:
                new_weight = max(old_weight * 0.7, min_weight)
                changes.append(f"DEMOTED {name}: win_rate={win_rate:.1%}, weight {old_weight:.2f}→{new_weight:.2f}")
            else:
                new_weight = old_weight
                changes.append(f"KEPT {name}: win_rate={win_rate:.1%}, weight {old_weight:.2f}")

            new_weights[name] = round(new_weight, 2)

            score["current_weight"] = new_weight
            self.store.save_strategy_score(score)

        for name, weight in new_weights.items():
            self.settings.update_strategy_weight(name, weight)

        if changes:
            self.store.save_improvement_log({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "type": "weight_update",
                "description": "Strategy weights updated based on performance",
                "changes": json.dumps(changes),
            })
            for change in changes:
                logger.info(change)

        return new_weights

    def run_llm_reflection(self) -> dict:
        if not self.llm_advisor.client:
            logger.warning("LLM advisor not configured (set AWS_REGION or ANTHROPIC_API_KEY)")
            return {}

        closed = self.store.get_closed_alerts(limit=50)
        if closed.empty:
            logger.info("No closed trades to reflect on")
            return {}

        scores = self.compute_strategy_scores()
        scanner_perf = self.scanner_learner.get_performance_summary()
        performance = self._format_performance(closed, scores, scanner_perf)

        logger.info("Requesting LLM analysis of trading performance...")
        analysis = self.llm_advisor.analyze_performance(performance, scores)

        if "error" not in analysis:
            self.store.save_improvement_log({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "type": "llm_reflection",
                "description": "AI analysis of strategy performance",
                "llm_analysis": json.dumps(analysis),
                "changes": json.dumps(analysis.get("parameter_adjustments", [])),
            })

            if analysis.get("weight_suggestions"):
                for suggestion in analysis["weight_suggestions"]:
                    name = suggestion.get("strategy")
                    new_weight = suggestion.get("suggested_weight")
                    if name and new_weight:
                        confidence = analysis.get("confidence", 0.5)
                        current = self.settings.strategies.get(name, {}).get("weight", 1.0)
                        blended = current + (new_weight - current) * min(confidence, 0.3)
                        self.settings.update_strategy_weight(name, round(blended, 2))
                        logger.info(f"LLM suggested {name} weight: {current:.2f}→{blended:.2f}")

        return analysis

    def run_full_improvement_cycle(self) -> dict:
        logger.info("=== SELF-IMPROVEMENT CYCLE ===")

        logger.info("Step 1: Computing strategy scoreboards...")
        scores = self.compute_strategy_scores()

        logger.info("Step 2: Updating strategy weights based on performance...")
        new_weights = self.update_strategy_weights()

        logger.info("Step 3: Scanner self-learning (factor weights + min confluence)...")
        scanner_result = self.scanner_learner.learn_from_results()

        logger.info("Step 4: Running LLM reflection (strategies + scanner combined)...")
        reflection = self.run_llm_reflection()

        save_path = str(self.settings.log_dir / f"config_{datetime.now():%Y%m%d_%H%M%S}.yaml")
        self.settings.save(save_path)
        logger.info(f"Saved updated config to {save_path}")

        return {
            "strategy_scores": scores,
            "new_weights": new_weights,
            "scanner_learning": scanner_result,
            "reflection": reflection,
        }

    def _format_performance(self, closed: pd.DataFrame, scores: dict, scanner_perf: dict = None) -> str:
        lines = ["## Closed Trade History (most recent first)\n"]
        for _, t in closed.head(30).iterrows():
            lines.append(
                f"- {t.get('symbol','?')} | {t.get('strategy','?')} | "
                f"Entry: {t.get('date','?')} @ ₹{t.get('entry_price',0):.2f} | "
                f"Exit: {t.get('exit_date','?')} @ ₹{t.get('exit_price',0):.2f} | "
                f"P&L: {t.get('pnl_pct',0):+.2f}% | {t.get('exit_reason','?')} | "
                f"Hold: {t.get('holding_days',0)}d"
            )

        lines.append("\n## Strategy Scoreboard\n")
        for name, s in scores.items():
            lines.append(
                f"- {name}: {s.get('total_alerts',0)} trades | "
                f"Win rate: {s.get('win_rate',0):.1%} | "
                f"Avg return: {s.get('avg_return_pct',0):+.2f}% | "
                f"Weight: {s.get('current_weight',1.0):.2f}"
            )

        if scanner_perf and scanner_perf.get("total_picks"):
            lines.append("\n## Scanner Confluence Performance\n")
            lines.append(
                f"- Total scanner picks: {scanner_perf['total_picks']} | "
                f"Win rate: {scanner_perf.get('win_rate', 0):.1%} | "
                f"Avg return: {scanner_perf.get('avg_pnl', 0):+.1f}% | "
                f"Min confluence: {scanner_perf.get('min_confluence', 2)}/12"
            )
            for f in scanner_perf.get("factor_scores", []):
                lines.append(
                    f"  - {f['factor']}: {f['total_picks']} picks | "
                    f"Win rate: {f['win_rate']:.1%} | "
                    f"Avg return: {f.get('avg_return_pct', 0):+.1f}% | "
                    f"Weight: {f['weight']:.2f}x"
                )

        return "\n".join(lines)
