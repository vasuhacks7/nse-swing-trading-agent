import logging
import os
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        return False

    try:
        resp = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Telegram message sent")
            return True
        logger.error(f"Telegram API error {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def format_alert(alert: dict) -> str:
    symbol = alert.get("symbol", "?")
    action = alert.get("action", "BUY")
    entry = alert.get("entry_price", 0)
    target = alert.get("target_price", 0)
    stop = alert.get("stop_loss", 0)
    rr = alert.get("risk_reward_ratio", 0)
    strategy = alert.get("strategy", "?")
    score = alert.get("signal_score", alert.get("score", 0))
    qty_pct = alert.get("qty_pct", 1.0)
    reasoning = alert.get("reasoning", "")

    risk_pct = abs(entry - stop) / entry * 100 if entry else 0
    reward_pct = abs(target - entry) / entry * 100 if entry else 0

    return (
        f"<b>{'🟢' if action == 'BUY' else '🔴'} {action} — {symbol}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📍 Entry: <b>₹{entry:.2f}</b>\n"
        f"🎯 Target: <b>₹{target:.2f}</b> (+{reward_pct:.1f}%)\n"
        f"🛑 Stop Loss: <b>₹{stop:.2f}</b> (-{risk_pct:.1f}%)\n"
        f"📊 R:R Ratio: <b>1:{rr:.1f}</b>\n"
        f"⚡ Score: <b>{score:.3f}</b>\n"
        f"💰 Deploy: <b>{qty_pct * 100:.0f}%</b>\n"
        f"🔧 Strategy: {strategy}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"<i>{reasoning[:200]}</i>"
    )


def format_close(alert: dict) -> str:
    symbol = alert.get("symbol", "?")
    entry = alert.get("entry_price", 0)
    exit_price = alert.get("exit_price", 0)
    pnl_pct = alert.get("pnl_pct", 0)
    reason = alert.get("exit_reason", "?")
    days = alert.get("holding_days", "?")

    emoji = "✅" if pnl_pct > 0 else "❌"

    return (
        f"<b>{emoji} CLOSED — {symbol}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📍 Entry: ₹{entry:.2f} → Exit: ₹{exit_price:.2f}\n"
        f"💰 P&L: <b>{pnl_pct:+.2f}%</b>\n"
        f"📅 Held: {days} days\n"
        f"📌 Reason: {reason}"
    )


def send_daily_alerts(alerts: list[dict], regime: dict = None, flows: dict = None):
    if not alerts:
        return

    date_str = datetime.now().strftime("%d %b %Y")
    header = f"<b>📈 NSE Swing Alerts — {date_str}</b>\n\n"

    if regime:
        r = regime.get("regime", "?")
        rsi = regime.get("nifty_rsi", "?")
        header += f"Market: <b>{r}</b> | Nifty RSI: {rsi}\n"
    if flows:
        fii = flows.get("fii_sentiment", "?")
        header += f"FII: <b>{fii}</b>\n"
    header += "\n"

    send_message(header)

    for alert in alerts:
        msg = format_alert(alert)
        send_message(msg)


def send_close_notification(closed_alerts: list[dict]):
    for alert in closed_alerts:
        msg = format_close(alert)
        send_message(msg)


def send_daily_summary(perf: dict):
    total = perf.get("total_trades", 0)
    win_rate = perf.get("win_rate", 0)
    avg_ret = perf.get("avg_return_pct", 0)
    total_pnl = perf.get("total_pnl_pct", 0)
    streak = perf.get("current_streak", "—")

    msg = (
        f"<b>📊 Daily Summary</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Trades: {total} | Win Rate: {win_rate:.1f}%\n"
        f"Avg Return: {avg_ret:+.2f}%\n"
        f"Total P&L: {total_pnl:+.2f}%\n"
        f"Streak: {streak}"
    )
    send_message(msg)
