import logging
from datetime import datetime, timedelta

import yfinance as yf

logger = logging.getLogger(__name__)


def has_upcoming_earnings(symbol: str, days_ahead: int = 5) -> dict:
    try:
        ticker = yf.Ticker(symbol)
        cal = ticker.calendar
        if cal is None or (hasattr(cal, 'empty') and cal.empty):
            return {"has_earnings": False, "source": "no_data"}

        earnings_date = None
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed:
                earnings_date = ed[0] if isinstance(ed, list) else ed
        elif hasattr(cal, 'columns'):
            if "Earnings Date" in cal.columns:
                earnings_date = cal["Earnings Date"].iloc[0]
            elif len(cal) > 0:
                for col in cal.columns:
                    if "earning" in col.lower() or "result" in col.lower():
                        earnings_date = cal[col].iloc[0]
                        break

        if earnings_date is None:
            return {"has_earnings": False, "source": "no_date_found"}

        if hasattr(earnings_date, 'date'):
            earnings_date = earnings_date.date()
        elif isinstance(earnings_date, str):
            earnings_date = datetime.strptime(earnings_date[:10], "%Y-%m-%d").date()

        today = datetime.now().date()
        days_until = (earnings_date - today).days

        if 0 <= days_until <= days_ahead:
            return {
                "has_earnings": True,
                "earnings_date": str(earnings_date),
                "days_until": days_until,
                "warning": f"Results in {days_until} days — avoid new entry",
            }

        return {
            "has_earnings": False,
            "next_earnings": str(earnings_date),
            "days_until": days_until,
        }
    except Exception as e:
        logger.debug(f"Earnings check failed for {symbol}: {e}")
        return {"has_earnings": False, "source": "error"}


def filter_earnings_stocks(symbols: list[str], days_ahead: int = 5) -> tuple[list[str], list[dict]]:
    safe = []
    earnings_upcoming = []

    for symbol in symbols:
        result = has_upcoming_earnings(symbol, days_ahead)
        if result["has_earnings"]:
            earnings_upcoming.append({
                "symbol": symbol,
                **result,
            })
            logger.info(f"SKIP {symbol}: earnings on {result['earnings_date']} "
                        f"({result['days_until']}d away)")
        else:
            safe.append(symbol)

    return safe, earnings_upcoming
