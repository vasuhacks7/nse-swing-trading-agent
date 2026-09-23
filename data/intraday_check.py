import logging

import yfinance as yf

logger = logging.getLogger(__name__)


def check_intraday_entry(symbol: str, entry_price: float) -> dict:
    """Check 15-min intraday data for optimal entry timing.

    Returns a dict with:
    - favorable: bool (True if intraday supports entry)
    - adjusted_entry: float (refined entry if near support)
    - reason: str
    """
    result = {
        "favorable": True,
        "adjusted_entry": entry_price,
        "reason": "No intraday data — use daily entry",
        "intraday_rsi": None,
        "distance_from_vwap_pct": None,
    }

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1d", interval="15m")

        if df.empty or len(df) < 5:
            return result

        close = float(df["Close"].iloc[-1])
        high = float(df["High"].max())
        low = float(df["Low"].min())
        vwap = float((df["Close"] * df["Volume"]).sum() / df["Volume"].sum()) if df["Volume"].sum() > 0 else close

        delta = df["Close"].diff()
        gain = delta.clip(lower=0).rolling(14, min_periods=5).mean()
        loss = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()
        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))
        intraday_rsi = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50

        dist_from_vwap = ((close - vwap) / vwap) * 100

        result["intraday_rsi"] = round(intraday_rsi, 1)
        result["distance_from_vwap_pct"] = round(dist_from_vwap, 2)

        if intraday_rsi > 75 and dist_from_vwap > 1.0:
            result["favorable"] = False
            result["reason"] = f"Overbought intraday (RSI={intraday_rsi:.0f}, {dist_from_vwap:+.1f}% from VWAP)"
            return result

        if close <= vwap and intraday_rsi < 45:
            result["adjusted_entry"] = round(min(close, entry_price), 2)
            result["reason"] = f"Pullback to VWAP — good entry (RSI={intraday_rsi:.0f})"
            result["favorable"] = True
            return result

        intraday_range = high - low
        if intraday_range > 0:
            position_in_range = (close - low) / intraday_range
            if position_in_range > 0.85:
                result["favorable"] = False
                result["reason"] = f"Near intraday high ({position_in_range:.0%} of range)"
                return result

        result["reason"] = f"Intraday neutral (RSI={intraday_rsi:.0f}, VWAP dist={dist_from_vwap:+.1f}%)"
        result["favorable"] = True

    except Exception as e:
        logger.debug(f"Intraday check failed for {symbol}: {e}")

    return result
