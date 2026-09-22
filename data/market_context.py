import logging
from datetime import datetime, date, time, timedelta

import pandas as pd
import yfinance as yf
import requests

logger = logging.getLogger(__name__)

NIFTY_SYMBOL = "^NSEI"

NSE_HOLIDAYS_2025 = [
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Ramadan)
    date(2025, 4, 10),   # Mahavir Jayanti
    date(2025, 4, 14),   # Dr. Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 6, 7),    # Bakri Id
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 16),   # Parsi New Year
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 1),   # Mahatma Gandhi Jayanti / Dussehra
    date(2025, 10, 2),   # Dussehra
    date(2025, 10, 21),  # Diwali (Laxmi Pujan)
    date(2025, 10, 22),  # Diwali Balipratipada
    date(2025, 11, 5),   # Guru Nanak Jayanti / Prakash Gurpurab
    date(2025, 12, 25),  # Christmas
]

NSE_HOLIDAYS_2026 = [
    date(2026, 1, 26),   # Republic Day
    date(2026, 2, 17),   # Mahashivratri
    date(2026, 3, 4),    # Holi
    date(2026, 3, 20),   # Id-Ul-Fitr
    date(2026, 3, 30),   # Ugadi / Gudi Padwa
    date(2026, 4, 2),    # Mahavir Jayanti / Ram Navami
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 27),   # Bakri Id
    date(2026, 6, 25),   # Muharram
    date(2026, 8, 15),   # Independence Day
    date(2026, 8, 25),   # Milad-un-Nabi
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 19),  # Dussehra
    date(2026, 11, 9),   # Diwali (Laxmi Pujan)
    date(2026, 11, 10),  # Diwali Balipratipada
    date(2026, 11, 24),  # Guru Nanak Jayanti
    date(2026, 12, 25),  # Christmas
]

ALL_NSE_HOLIDAYS = set(NSE_HOLIDAYS_2025 + NSE_HOLIDAYS_2026)

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def is_market_open_today() -> dict:
    now = datetime.now()
    today = now.date()
    weekday = today.weekday()

    if weekday >= 5:
        return {"open": False, "reason": "Weekend"}
    if today in ALL_NSE_HOLIDAYS:
        return {"open": False, "reason": "NSE Holiday"}
    return {"open": True, "reason": "Market day",
            "in_session": MARKET_OPEN <= now.time() <= MARKET_CLOSE}


def get_market_regime() -> dict:
    try:
        nifty = yf.Ticker(NIFTY_SYMBOL)
        df = nifty.history(period="6mo", interval="1d")
        if df.empty or len(df) < 50:
            return {"regime": "UNKNOWN", "details": "Insufficient Nifty data"}

        df["ema_21"] = df["Close"].ewm(span=21).mean()
        df["ema_50"] = df["Close"].ewm(span=50).mean()
        df["ema_200"] = df["Close"].ewm(span=200).mean()
        df["sma_20"] = df["Close"].rolling(20).mean()

        delta = df["Close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        df["rsi"] = 100 - (100 / (1 + rs))

        df["returns_5d"] = df["Close"].pct_change(5) * 100
        df["returns_20d"] = df["Close"].pct_change(20) * 100
        df["volatility"] = df["Close"].pct_change().rolling(20).std() * 100

        last = df.iloc[-1]
        close = last["Close"]
        ema_21 = last["ema_21"]
        ema_50 = last["ema_50"]
        ema_200 = last["ema_200"]
        rsi = last["rsi"]
        ret_5d = last["returns_5d"]
        ret_20d = last["returns_20d"]
        vol = last["volatility"]

        bullish_signals = 0
        bearish_signals = 0

        if close > ema_21:
            bullish_signals += 1
        else:
            bearish_signals += 1
        if close > ema_50:
            bullish_signals += 1
        else:
            bearish_signals += 1
        if close > ema_200:
            bullish_signals += 1
        else:
            bearish_signals += 1
        if ema_21 > ema_50:
            bullish_signals += 1
        else:
            bearish_signals += 1
        if rsi > 50:
            bullish_signals += 1
        else:
            bearish_signals += 1

        if bullish_signals >= 4:
            regime = "BULLISH"
        elif bearish_signals >= 4:
            regime = "BEARISH"
        else:
            regime = "SIDEWAYS"

        if vol > 2.0:
            regime_note = "HIGH_VOLATILITY"
        elif vol < 0.8:
            regime_note = "LOW_VOLATILITY"
        else:
            regime_note = "NORMAL_VOLATILITY"

        return {
            "regime": regime,
            "nifty_close": round(close, 2),
            "nifty_rsi": round(rsi, 1),
            "above_ema21": close > ema_21,
            "above_ema50": close > ema_50,
            "above_ema200": close > ema_200,
            "return_5d": round(ret_5d, 2),
            "return_20d": round(ret_20d, 2),
            "volatility": round(vol, 2),
            "volatility_regime": regime_note,
            "bullish_signals": bullish_signals,
            "bearish_signals": bearish_signals,
        }
    except Exception as e:
        logger.warning(f"Failed to get market regime: {e}")
        return {"regime": "UNKNOWN", "details": str(e)}


def get_fii_dii_activity() -> dict:
    result = _try_nse_fii_dii()
    if result:
        return result
    return _estimate_from_nifty_flows()


def _try_nse_fii_dii() -> dict | None:
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        })
        session.get("https://www.nseindia.com", timeout=10)

        resp = session.get(
            "https://www.nseindia.com/api/fiidiiTradeReact",
            timeout=10,
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        fii_buy = 0
        fii_sell = 0
        dii_buy = 0
        dii_sell = 0

        for item in data:
            cat = item.get("category", "").upper()
            if "FII" in cat or "FPI" in cat:
                fii_buy += float(item.get("buyValue", 0))
                fii_sell += float(item.get("sellValue", 0))
            elif "DII" in cat:
                dii_buy += float(item.get("buyValue", 0))
                dii_sell += float(item.get("sellValue", 0))

        fii_net = fii_buy - fii_sell
        dii_net = dii_buy - dii_sell

        if fii_net > 1000:
            fii_sentiment = "STRONG_BUYING"
        elif fii_net > 0:
            fii_sentiment = "MILD_BUYING"
        elif fii_net > -1000:
            fii_sentiment = "MILD_SELLING"
        else:
            fii_sentiment = "HEAVY_SELLING"

        return {
            "source": "NSE",
            "fii_net_cr": round(fii_net, 2),
            "dii_net_cr": round(dii_net, 2),
            "fii_sentiment": fii_sentiment,
            "combined_net_cr": round(fii_net + dii_net, 2),
        }
    except Exception as e:
        logger.debug(f"NSE FII/DII API failed: {e}")
        return None


def _estimate_from_nifty_flows() -> dict:
    try:
        nifty = yf.Ticker(NIFTY_SYMBOL)
        df = nifty.history(period="10d")
        if len(df) < 5:
            return {"source": "estimate", "fii_sentiment": "UNKNOWN"}

        recent_return = (df["Close"].iloc[-1] / df["Close"].iloc[-5] - 1) * 100
        avg_vol = df["Volume"].mean()
        last_vol = df["Volume"].iloc[-1]
        vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1

        if recent_return > 2 and vol_ratio > 1.2:
            sentiment = "STRONG_BUYING"
        elif recent_return > 0:
            sentiment = "MILD_BUYING"
        elif recent_return > -2:
            sentiment = "MILD_SELLING"
        else:
            sentiment = "HEAVY_SELLING"

        return {
            "source": "estimate",
            "nifty_5d_return": round(recent_return, 2),
            "volume_ratio": round(vol_ratio, 2),
            "fii_sentiment": sentiment,
        }
    except Exception as e:
        logger.warning(f"Flow estimation failed: {e}")
        return {"source": "error", "fii_sentiment": "UNKNOWN"}
