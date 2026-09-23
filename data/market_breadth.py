import logging

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

NIFTY_50 = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS", "LT.NS",
    "ITC.NS", "AXISBANK.NS", "BAJFINANCE.NS", "MARUTI.NS", "HCLTECH.NS",
    "SUNPHARMA.NS", "TITAN.NS", "TATAMOTORS.NS", "WIPRO.NS", "NTPC.NS",
    "POWERGRID.NS", "ULTRACEMCO.NS", "NESTLEIND.NS", "TECHM.NS", "JSWSTEEL.NS",
    "TATASTEEL.NS", "ADANIENT.NS", "BAJAJFINSV.NS", "ONGC.NS", "COALINDIA.NS",
    "GRASIM.NS", "DIVISLAB.NS", "CIPLA.NS", "DRREDDY.NS", "EICHERMOT.NS",
    "HEROMOTOCO.NS", "APOLLOHOSP.NS", "BPCL.NS", "BRITANNIA.NS", "INDUSINDBK.NS",
    "HINDALCO.NS", "M&M.NS", "ASIANPAINT.NS", "BAJAJ-AUTO.NS", "SBILIFE.NS",
    "HDFCLIFE.NS", "TATACONSUM.NS", "SHRIRAMFIN.NS", "ADANIPORTS.NS", "LTIM.NS",
]


def get_market_breadth() -> dict:
    """Compute market breadth from Nifty 50 components."""
    result = {
        "above_200ema_pct": 0,
        "above_50ema_pct": 0,
        "advancing": 0,
        "declining": 0,
        "ad_ratio": 1.0,
        "new_20d_highs": 0,
        "new_20d_lows": 0,
        "breadth_signal": "NEUTRAL",
        "score_adjustment": 0.0,
    }

    try:
        tickers_str = " ".join(NIFTY_50)
        data = yf.download(tickers_str, period="1y", progress=False,
                           threads=True, group_by="ticker")

        if data.empty:
            logger.warning("Market breadth: no data")
            return result

        above_200 = 0
        above_50 = 0
        advancing = 0
        declining = 0
        new_highs = 0
        new_lows = 0
        counted = 0

        for sym in NIFTY_50:
            try:
                if sym not in data.columns.get_level_values(0):
                    continue
                df = data[sym].dropna(subset=["Close"])
                if len(df) < 200:
                    continue

                counted += 1
                close = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2])
                ema_200 = float(df["Close"].ewm(span=200).mean().iloc[-1])
                ema_50 = float(df["Close"].ewm(span=50).mean().iloc[-1])
                high_20 = float(df["High"].tail(20).max())
                low_20 = float(df["Low"].tail(20).min())

                if close > ema_200:
                    above_200 += 1
                if close > ema_50:
                    above_50 += 1
                if close > prev:
                    advancing += 1
                else:
                    declining += 1
                if close >= high_20 * 0.99:
                    new_highs += 1
                if close <= low_20 * 1.01:
                    new_lows += 1
            except Exception:
                continue

        if counted > 0:
            result["above_200ema_pct"] = round(above_200 / counted * 100, 1)
            result["above_50ema_pct"] = round(above_50 / counted * 100, 1)
            result["advancing"] = advancing
            result["declining"] = declining
            result["ad_ratio"] = round(advancing / max(declining, 1), 2)
            result["new_20d_highs"] = new_highs
            result["new_20d_lows"] = new_lows
            result["stocks_counted"] = counted

            pct_200 = result["above_200ema_pct"]
            ad = result["ad_ratio"]

            if pct_200 > 70 and ad > 1.5:
                result["breadth_signal"] = "STRONG_BULLISH"
                result["score_adjustment"] = -0.03
            elif pct_200 > 55 and ad > 1.0:
                result["breadth_signal"] = "BULLISH"
                result["score_adjustment"] = -0.02
            elif pct_200 < 30 or ad < 0.5:
                result["breadth_signal"] = "BEARISH"
                result["score_adjustment"] = 0.05
            elif pct_200 < 40 or ad < 0.7:
                result["breadth_signal"] = "WEAK"
                result["score_adjustment"] = 0.03

        logger.info(f"Market breadth: {result['above_200ema_pct']}% >200EMA, "
                     f"A/D={result['ad_ratio']}, {result['breadth_signal']}")
    except Exception as e:
        logger.warning(f"Market breadth failed: {e}")

    return result
