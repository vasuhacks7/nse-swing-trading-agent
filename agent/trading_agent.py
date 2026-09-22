import logging
from datetime import datetime

from config.settings import Settings
from agent.alert_engine import AlertEngine
from agent.improvement_engine import ImprovementEngine

logger = logging.getLogger(__name__)


class TradingAgent:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.alert_engine = AlertEngine(settings)
        self.improvement_engine = ImprovementEngine(settings)

    def daily_run(self) -> dict:
        logger.info(f"=== DAILY RUN: {datetime.now():%Y-%m-%d %H:%M} ===")

        logger.info("Step 1: Checking open alerts for exits...")
        closed = self.alert_engine.check_and_close_alerts()

        logger.info("Step 2: Generating today's alerts...")
        alerts = self.alert_engine.generate_daily_alerts()

        logger.info("Step 3: Performance summary...")
        performance = self.alert_engine.get_performance_summary()

        should_improve = self._should_run_improvement()
        improvement = None
        if should_improve:
            logger.info("Step 4: Running self-improvement cycle...")
            improvement = self.improvement_engine.run_full_improvement_cycle()

        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "alerts": alerts,
            "closed_today": closed,
            "performance": performance,
            "improvement": improvement,
        }

    def _should_run_improvement(self) -> bool:
        interval = self.settings.improvement.get("review_interval_days", 7)
        log = self.improvement_engine.store.get_improvement_log(1)
        if log.empty:
            return True
        last_date = log.iloc[0].get("date", "")
        if not last_date:
            return True
        days_since = (datetime.now() - datetime.strptime(last_date, "%Y-%m-%d")).days
        return days_since >= interval
