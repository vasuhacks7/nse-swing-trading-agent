import logging

import yfinance as yf

logger = logging.getLogger(__name__)

GLOBAL_SYMBOLS = {
    "sp500_futures": "ES=F",
    "dxy": "DX-Y.NYB",
    "crude_oil": "CL=F",
    "india_vix": "^INDIAVIX",
}


def get_global_context() -> dict:
    """Check global macro indicators before market open."""
    result = {
        "overall_sentiment": "NEUTRAL",
        "score_adjustment": 0.0,
        "details": {},
        "bullish_signals": 0,
        "bearish_signals": 0,
    }

    bearish = 0
    bullish = 0

    try:
        sp = yf.Ticker(GLOBAL_SYMBOLS["sp500_futures"])
        df = sp.history(period="5d")
        if len(df) >= 2:
            change = (df["Close"].iloc[-1] / df["Close"].iloc[-2] - 1) * 100
            result["details"]["sp500_futures"] = {
                "last": round(float(df["Close"].iloc[-1]), 2),
                "change_pct": round(change, 2),
            }
            if change < -1.0:
                bearish += 2
            elif change < -0.5:
                bearish += 1
            elif change > 0.5:
                bullish += 1
    except Exception as e:
        logger.debug(f"S&P futures fetch failed: {e}")

    try:
        dxy = yf.Ticker(GLOBAL_SYMBOLS["dxy"])
        df = dxy.history(period="5d")
        if len(df) >= 2:
            change = (df["Close"].iloc[-1] / df["Close"].iloc[-2] - 1) * 100
            result["details"]["dxy"] = {
                "last": round(float(df["Close"].iloc[-1]), 2),
                "change_pct": round(change, 2),
            }
            if change > 0.5:
                bearish += 1
            elif change < -0.5:
                bullish += 1
    except Exception as e:
        logger.debug(f"DXY fetch failed: {e}")

    try:
        oil = yf.Ticker(GLOBAL_SYMBOLS["crude_oil"])
        df = oil.history(period="5d")
        if len(df) >= 2:
            change = (df["Close"].iloc[-1] / df["Close"].iloc[-2] - 1) * 100
            result["details"]["crude_oil"] = {
                "last": round(float(df["Close"].iloc[-1]), 2),
                "change_pct": round(change, 2),
            }
            if change > 2.0:
                bearish += 1
            elif change < -2.0:
                bullish += 1
    except Exception as e:
        logger.debug(f"Crude oil fetch failed: {e}")

    try:
        vix = yf.Ticker(GLOBAL_SYMBOLS["india_vix"])
        df = vix.history(period="5d")
        if not df.empty:
            level = float(df["Close"].iloc[-1])
            result["details"]["india_vix"] = {"last": round(level, 2)}
            if level > 20:
                bearish += 1
            elif level < 13:
                bullish += 1
    except Exception as e:
        logger.debug(f"India VIX fetch failed: {e}")

    if bearish >= 3:
        result["overall_sentiment"] = "BEARISH"
        result["score_adjustment"] = 0.05
    elif bearish >= 2:
        result["overall_sentiment"] = "CAUTIOUS"
        result["score_adjustment"] = 0.03
    elif bullish >= 3:
        result["overall_sentiment"] = "BULLISH"
        result["score_adjustment"] = -0.02

    result["bullish_signals"] = bullish
    result["bearish_signals"] = bearish

    logger.info(f"Global context: {result['overall_sentiment']} "
                f"(bull={bullish}, bear={bearish}, adj={result['score_adjustment']:+.2f})")
    return result
