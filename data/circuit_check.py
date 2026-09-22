import logging

import pandas as pd

logger = logging.getLogger(__name__)

CIRCUIT_BANDS = {
    "2": 0.02,
    "5": 0.05,
    "10": 0.10,
    "20": 0.20,
}


def check_circuit_status(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 2:
        return {"at_circuit": False}

    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = last["close"]
    high = last["high"]
    low = last["low"]
    prev_close = prev["close"]
    volume = last.get("volume", 0)
    avg_vol = df["volume"].iloc[-20:].mean() if len(df) >= 20 else df["volume"].mean()

    if prev_close == 0:
        return {"at_circuit": False}

    daily_change_pct = ((close - prev_close) / prev_close) * 100

    at_upper = (
        abs(close - high) / close < 0.001 and
        abs(daily_change_pct) > 1.8 and
        daily_change_pct > 0
    )

    at_lower = (
        abs(close - low) / close < 0.001 and
        abs(daily_change_pct) > 1.8 and
        daily_change_pct < 0
    )

    near_upper = (
        not at_upper and
        daily_change_pct > 4.5 and
        close >= high * 0.995
    )

    near_lower = (
        not at_lower and
        daily_change_pct < -4.5 and
        close <= low * 1.005
    )

    vol_thin = volume < avg_vol * 0.3 if avg_vol > 0 else False

    if at_upper and vol_thin:
        return {
            "at_circuit": True,
            "type": "UPPER_CIRCUIT",
            "change_pct": round(daily_change_pct, 2),
            "warning": "Stock at upper circuit — cannot buy, no sellers",
        }
    elif at_upper:
        return {
            "at_circuit": True,
            "type": "LIKELY_UPPER_CIRCUIT",
            "change_pct": round(daily_change_pct, 2),
            "warning": "Stock likely at upper circuit",
        }
    elif at_lower:
        return {
            "at_circuit": True,
            "type": "LOWER_CIRCUIT",
            "change_pct": round(daily_change_pct, 2),
            "warning": "Stock at lower circuit — cannot sell",
        }
    elif near_upper:
        return {
            "at_circuit": False,
            "near_circuit": True,
            "type": "NEAR_UPPER",
            "change_pct": round(daily_change_pct, 2),
            "warning": "Stock near upper circuit — risky entry",
        }
    elif near_lower:
        return {
            "at_circuit": False,
            "near_circuit": True,
            "type": "NEAR_LOWER",
            "change_pct": round(daily_change_pct, 2),
            "warning": "Stock near lower circuit — may get stuck",
        }

    return {
        "at_circuit": False,
        "near_circuit": False,
        "change_pct": round(daily_change_pct, 2),
    }
