import logging
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import Settings
from agent.alert_engine import AlertEngine
from agent.improvement_engine import ImprovementEngine
from notifications.telegram_bot import send_daily_alerts, send_close_notification, send_daily_summary
from data.market_context import get_market_regime, get_fii_dii_activity
from agent.paper_trader import PaperTrader
from data.apoorv_tracker import ApoorvTracker
from agent.apoorv_learner import ApoorvLearner
from agent.scanner_learner import ScannerLearner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


settings = Settings()
alert_engine = AlertEngine(settings)
improvement_engine = ImprovementEngine(settings)
paper_trader = PaperTrader(settings)
apoorv_tracker = ApoorvTracker(settings)
apoorv_learner = ApoorvLearner(settings)
scanner_learner = ScannerLearner(settings)


def job_generate_alerts():
    logger.info("=== SCHEDULED: Generate daily alerts ===")
    try:
        regime = get_market_regime()
        flows = get_fii_dii_activity()
        alerts = alert_engine.generate_daily_alerts()

        if alerts:
            logger.info(f"Generated {len(alerts)} alerts")
            send_daily_alerts(alerts, regime, flows)
        else:
            logger.info("No alerts generated today")
    except Exception as e:
        logger.error(f"Alert generation failed: {e}", exc_info=True)


def job_track_positions():
    logger.info("=== SCHEDULED: Track open positions ===")
    try:
        closed = alert_engine.check_and_close_alerts()
        if closed:
            logger.info(f"Closed {len(closed)} positions")
            send_close_notification(closed)
    except Exception as e:
        logger.error(f"Position tracking failed: {e}", exc_info=True)


def job_daily_summary():
    logger.info("=== SCHEDULED: Daily summary ===")
    try:
        perf = alert_engine.get_performance_summary()
        send_daily_summary(perf)
    except Exception as e:
        logger.error(f"Summary failed: {e}", exc_info=True)


def job_track_paper_trades():
    logger.info("=== SCHEDULED: Track paper trades ===")
    try:
        closed = paper_trader.track_positions()
        if closed:
            logger.info(f"Paper trades closed: {len(closed)}")
    except Exception as e:
        logger.error(f"Paper trade tracking failed: {e}", exc_info=True)


def job_scan_apoorv():
    logger.info("=== SCHEDULED: Scan Apoorv's channel ===")
    try:
        new_picks = apoorv_tracker.scan_new_messages()
        if new_picks:
            logger.info(f"Found {len(new_picks)} new Apoorv picks")
            validations = apoorv_learner.cross_validate_new_picks()
            confirmed = [v for v in validations if v.get("agrees")]
            logger.info(f"Cross-validated: {len(confirmed)}/{len(validations)} confirmed")
        apoorv_tracker.update_pick_prices()
    except Exception as e:
        logger.error(f"Apoorv scan failed: {e}", exc_info=True)


def job_scanner_daily_scan():
    logger.info("=== SCHEDULED: Daily full NSE scanner ===")
    try:
        results = scanner_learner.run_full_scan()
        buy_count = sum(1 for r in results if r.get("signal") in ("STRONG_BUY", "BUY"))
        watch_count = sum(1 for r in results if r.get("signal") == "WATCH")
        logger.info(f"Daily scan complete: {len(results)} signals — {buy_count} BUY, {watch_count} WATCH")
    except Exception as e:
        logger.error(f"Daily scanner failed: {e}", exc_info=True)


def job_scanner_track():
    logger.info("=== SCHEDULED: Track scanner picks ===")
    try:
        result = scanner_learner.track_open_picks()
        logger.info(f"Scanner tracking: {result}")
    except Exception as e:
        logger.error(f"Scanner tracking failed: {e}", exc_info=True)


def job_scanner_learn():
    logger.info("=== SCHEDULED: Scanner self-improvement ===")
    try:
        result = scanner_learner.learn_from_results()
        logger.info(f"Scanner learning: {result}")
    except Exception as e:
        logger.error(f"Scanner learning failed: {e}", exc_info=True)


def job_improvement():
    logger.info("=== SCHEDULED: Unified self-improvement cycle (strategies + scanner) ===")
    try:
        result = improvement_engine.run_full_improvement_cycle()
        logger.info(f"Improvement cycle complete: {result}")
    except Exception as e:
        logger.error(f"Improvement cycle failed: {e}", exc_info=True)


def main():
    scheduler = BlockingScheduler(timezone="Asia/Kolkata")

    # 8:30 AM IST — full NSE scanner (takes ~10 min, ready before market opens)
    scheduler.add_job(
        job_scanner_daily_scan,
        CronTrigger(hour=8, minute=30, day_of_week="mon-fri"),
        id="scanner_daily",
        name="Daily full NSE scanner",
    )

    # 9:20 AM IST — generate alerts just after market opens
    scheduler.add_job(
        job_generate_alerts,
        CronTrigger(hour=9, minute=20, day_of_week="mon-fri"),
        id="generate_alerts",
        name="Generate daily alerts",
    )

    # 10:30 AM, 1:30 PM — track mid-day
    scheduler.add_job(
        job_track_positions,
        CronTrigger(hour="10,13", minute=30, day_of_week="mon-fri"),
        id="track_midday",
        name="Track positions mid-day",
    )

    # 3:35 PM IST — track after market close
    scheduler.add_job(
        job_track_positions,
        CronTrigger(hour=15, minute=35, day_of_week="mon-fri"),
        id="track_close",
        name="Track positions at close",
    )

    # 3:40 PM IST — track paper trades after close
    scheduler.add_job(
        job_track_paper_trades,
        CronTrigger(hour=15, minute=40, day_of_week="mon-fri"),
        id="track_paper",
        name="Track paper trades at close",
    )

    # 4:00 PM IST — daily summary
    scheduler.add_job(
        job_daily_summary,
        CronTrigger(hour=16, minute=0, day_of_week="mon-fri"),
        id="daily_summary",
        name="Send daily summary",
    )

    # 9:00 AM IST — scan Apoorv's channel before market opens
    scheduler.add_job(
        job_scan_apoorv,
        CronTrigger(hour=9, minute=0, day_of_week="mon-fri"),
        id="scan_apoorv",
        name="Scan Apoorv's Telegram channel",
    )

    # 3:45 PM IST — track scanner picks after close
    scheduler.add_job(
        job_scanner_track,
        CronTrigger(hour=15, minute=45, day_of_week="mon-fri"),
        id="scanner_track",
        name="Track scanner picks",
    )

    # Saturday 9 AM — scanner self-improvement (learn from results)
    scheduler.add_job(
        job_scanner_learn,
        CronTrigger(hour=9, minute=0, day_of_week="sat"),
        id="scanner_learn",
        name="Scanner self-improvement",
    )

    # Saturday 10 AM — weekly self-improvement
    scheduler.add_job(
        job_improvement,
        CronTrigger(hour=10, minute=0, day_of_week="sat"),
        id="weekly_improvement",
        name="Weekly self-improvement",
    )

    logger.info("Scheduler started — IST timezone")
    logger.info("Schedule:")
    for job in scheduler.get_jobs():
        logger.info(f"  {job.name}: {job.trigger}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
