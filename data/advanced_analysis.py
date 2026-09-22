import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

FIB_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
FIB_EXTENSIONS = [1.272, 1.618, 2.0, 2.618]


def compute_fibonacci_retracement(df: pd.DataFrame, lookback: int = 120) -> dict:
    recent = df.tail(lookback)
    if len(recent) < 20:
        return {}

    swing_high_idx = recent["high"].idxmax()
    swing_low_idx = recent["low"].idxmin()
    swing_high = recent["high"].max()
    swing_low = recent["low"].min()

    is_uptrend = swing_low_idx < swing_high_idx

    levels = {}
    for fib in FIB_LEVELS:
        if is_uptrend:
            price = swing_high - (swing_high - swing_low) * fib
        else:
            price = swing_low + (swing_high - swing_low) * fib
        levels[f"{fib*100:.1f}%"] = round(price, 2)

    current_price = df["close"].iloc[-1]
    nearest_level = None
    min_dist = float("inf")
    for label, price in levels.items():
        dist = abs(current_price - price) / current_price
        if dist < min_dist:
            min_dist = dist
            nearest_level = label

    return {
        "swing_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
        "swing_high_date": str(swing_high_idx.date()) if hasattr(swing_high_idx, "date") else str(swing_high_idx),
        "swing_low_date": str(swing_low_idx.date()) if hasattr(swing_low_idx, "date") else str(swing_low_idx),
        "trend": "UPTREND" if is_uptrend else "DOWNTREND",
        "levels": levels,
        "nearest_level": nearest_level,
        "distance_to_nearest_pct": round(min_dist * 100, 2),
    }


def compute_fibonacci_extensions(df: pd.DataFrame, lookback: int = 200) -> dict:
    recent = df.tail(lookback)
    if len(recent) < 30:
        return {}

    high_idx = recent["high"].idxmax()
    low_idx = recent["low"].idxmin()
    swing_high = recent["high"].max()
    swing_low = recent["low"].min()

    is_uptrend = low_idx < high_idx
    move = swing_high - swing_low

    extensions = {}
    for ext in FIB_EXTENSIONS:
        if is_uptrend:
            price = swing_low + move * ext
        else:
            price = swing_high - move * ext
        extensions[f"{ext*100:.1f}%"] = round(price, 2)

    return {
        "trend": "UPTREND" if is_uptrend else "DOWNTREND",
        "move_size": round(move, 2),
        "move_pct": round(move / swing_low * 100, 2) if swing_low else 0,
        "extensions": extensions,
    }


def detect_supply_demand_zones(df: pd.DataFrame, min_strength: int = 2) -> list[dict]:
    zones = []
    if len(df) < 50:
        return zones

    atr = df["high"].rolling(14).max() - df["low"].rolling(14).min()
    avg_atr = atr.mean() if not atr.empty else 1.0

    for i in range(20, len(df) - 5):
        window = df.iloc[i - 5 : i + 6]
        if len(window) < 11:
            continue

        center = df.iloc[i]

        is_swing_high = center["high"] == window["high"].max()
        is_swing_low = center["low"] == window["low"].min()

        if not (is_swing_high or is_swing_low):
            continue

        body_top = max(center["open"], center["close"])
        body_bottom = min(center["open"], center["close"])
        zone_top = center["high"]
        zone_bottom = center["low"]

        if is_swing_high:
            zone_type = "supply"
            zone_top = center["high"]
            zone_bottom = max(body_bottom, center["high"] - avg_atr * 0.5)
        else:
            zone_type = "demand"
            zone_bottom = center["low"]
            zone_top = min(body_top, center["low"] + avg_atr * 0.5)

        touches = 0
        future = df.iloc[i + 1 :]
        for _, bar in future.iterrows():
            if zone_type == "supply" and bar["high"] >= zone_bottom and bar["high"] <= zone_top * 1.01:
                touches += 1
            elif zone_type == "demand" and bar["low"] <= zone_top and bar["low"] >= zone_bottom * 0.99:
                touches += 1

        if touches >= min_strength:
            broken = False
            if zone_type == "supply" and not future.empty:
                broken = future["close"].max() > zone_top * 1.02
            elif zone_type == "demand" and not future.empty:
                broken = future["close"].min() < zone_bottom * 0.98

            date_val = df.index[i]
            zones.append({
                "type": zone_type,
                "zone_top": round(zone_top, 2),
                "zone_bottom": round(zone_bottom, 2),
                "date": str(date_val.date()) if hasattr(date_val, "date") else str(date_val),
                "touches": touches,
                "broken": broken,
                "strength": "STRONG" if touches >= 3 else "MODERATE",
            })

    zones.sort(key=lambda z: z["touches"], reverse=True)
    return _merge_nearby_zones(zones[:10])


def _merge_nearby_zones(zones: list[dict], threshold_pct: float = 0.02) -> list[dict]:
    if not zones:
        return zones
    merged = [zones[0]]
    for z in zones[1:]:
        overlap = False
        for m in merged:
            if z["type"] != m["type"]:
                continue
            mid_z = (z["zone_top"] + z["zone_bottom"]) / 2
            mid_m = (m["zone_top"] + m["zone_bottom"]) / 2
            if abs(mid_z - mid_m) / mid_m < threshold_pct:
                m["zone_top"] = max(m["zone_top"], z["zone_top"])
                m["zone_bottom"] = min(m["zone_bottom"], z["zone_bottom"])
                m["touches"] += z["touches"]
                m["strength"] = "STRONG" if m["touches"] >= 3 else "MODERATE"
                overlap = True
                break
        if not overlap:
            merged.append(z)
    return merged


def detect_trendlines(df: pd.DataFrame, lookback: int = 120) -> list[dict]:
    recent = df.tail(lookback).copy()
    if len(recent) < 30:
        return []

    trendlines = []

    swing_lows = []
    for i in range(5, len(recent) - 5):
        if recent["low"].iloc[i] == recent["low"].iloc[i - 5 : i + 6].min():
            swing_lows.append((i, recent["low"].iloc[i], recent.index[i]))

    swing_highs = []
    for i in range(5, len(recent) - 5):
        if recent["high"].iloc[i] == recent["high"].iloc[i - 5 : i + 6].max():
            swing_highs.append((i, recent["high"].iloc[i], recent.index[i]))

    for a_idx in range(len(swing_lows)):
        for b_idx in range(a_idx + 1, len(swing_lows)):
            i1, p1, d1 = swing_lows[a_idx]
            i2, p2, d2 = swing_lows[b_idx]
            if i2 - i1 < 10:
                continue
            slope = (p2 - p1) / (i2 - i1)
            if slope <= 0:
                continue

            touches = 0
            for i in range(len(recent)):
                expected = p1 + slope * (i - i1)
                actual_low = recent["low"].iloc[i]
                tolerance = actual_low * 0.015
                if abs(actual_low - expected) < tolerance:
                    touches += 1

            if touches >= 3:
                last_idx = len(recent) - 1
                current_tl_price = p1 + slope * (last_idx - i1)
                current_price = recent["close"].iloc[-1]
                dist_pct = (current_price - current_tl_price) / current_price * 100

                d1_str = str(d1.date()) if hasattr(d1, "date") else str(d1)
                d2_str = str(d2.date()) if hasattr(d2, "date") else str(d2)
                trendlines.append({
                    "type": "ascending_support",
                    "start_date": d1_str,
                    "start_price": round(p1, 2),
                    "end_date": d2_str,
                    "end_price": round(p2, 2),
                    "slope_per_day": round(slope, 4),
                    "current_tl_price": round(current_tl_price, 2),
                    "touches": touches,
                    "distance_pct": round(dist_pct, 2),
                    "near_trendline": abs(dist_pct) < 3,
                })

    for a_idx in range(len(swing_highs)):
        for b_idx in range(a_idx + 1, len(swing_highs)):
            i1, p1, d1 = swing_highs[a_idx]
            i2, p2, d2 = swing_highs[b_idx]
            if i2 - i1 < 10:
                continue
            slope = (p2 - p1) / (i2 - i1)
            if slope >= 0:
                continue

            touches = 0
            for i in range(len(recent)):
                expected = p1 + slope * (i - i1)
                actual_high = recent["high"].iloc[i]
                tolerance = actual_high * 0.015
                if abs(actual_high - expected) < tolerance:
                    touches += 1

            if touches >= 3:
                last_idx = len(recent) - 1
                current_tl_price = p1 + slope * (last_idx - i1)
                current_price = recent["close"].iloc[-1]
                dist_pct = (current_tl_price - current_price) / current_price * 100

                d1_str = str(d1.date()) if hasattr(d1, "date") else str(d1)
                d2_str = str(d2.date()) if hasattr(d2, "date") else str(d2)
                trendlines.append({
                    "type": "descending_resistance",
                    "start_date": d1_str,
                    "start_price": round(p1, 2),
                    "end_date": d2_str,
                    "end_price": round(p2, 2),
                    "slope_per_day": round(slope, 4),
                    "current_tl_price": round(current_tl_price, 2),
                    "touches": touches,
                    "distance_pct": round(dist_pct, 2),
                    "near_trendline": abs(dist_pct) < 3,
                })

    trendlines.sort(key=lambda t: t["touches"], reverse=True)
    return trendlines[:5]


# ═══════════ NEW: Candlestick Patterns ═══════════

def detect_candlestick_patterns(df: pd.DataFrame) -> list[dict]:
    if len(df) < 5:
        return []

    patterns = []

    for i in range(-3, 0):
        idx = len(df) + i
        if idx < 2:
            continue
        c = df.iloc[idx]
        prev = df.iloc[idx - 1]

        body = abs(c["close"] - c["open"])
        full_range = c["high"] - c["low"]
        if full_range == 0:
            continue
        body_pct = body / full_range

        upper_wick = c["high"] - max(c["open"], c["close"])
        lower_wick = min(c["open"], c["close"]) - c["low"]

        date_str = str(df.index[idx].date()) if hasattr(df.index[idx], "date") else str(df.index[idx])
        days_ago = abs(i)

        if lower_wick >= body * 2 and upper_wick < body * 0.5 and c["close"] > c["open"]:
            patterns.append({
                "pattern": "Hammer",
                "type": "bullish",
                "date": date_str,
                "price": round(c["close"], 2),
                "days_ago": days_ago,
                "strength": "STRONG" if lower_wick >= body * 3 else "MODERATE",
            })

        if upper_wick >= body * 2 and lower_wick < body * 0.5 and c["close"] < c["open"]:
            patterns.append({
                "pattern": "Shooting Star",
                "type": "bearish",
                "date": date_str,
                "price": round(c["close"], 2),
                "days_ago": days_ago,
                "strength": "STRONG" if upper_wick >= body * 3 else "MODERATE",
            })

        if (prev["close"] < prev["open"]
                and c["close"] > c["open"]
                and c["open"] <= prev["close"]
                and c["close"] >= prev["open"]):
            patterns.append({
                "pattern": "Bullish Engulfing",
                "type": "bullish",
                "date": date_str,
                "price": round(c["close"], 2),
                "days_ago": days_ago,
                "strength": "STRONG",
            })

        if (prev["close"] > prev["open"]
                and c["close"] < c["open"]
                and c["open"] >= prev["close"]
                and c["close"] <= prev["open"]):
            patterns.append({
                "pattern": "Bearish Engulfing",
                "type": "bearish",
                "date": date_str,
                "price": round(c["close"], 2),
                "days_ago": days_ago,
                "strength": "STRONG",
            })

        if body_pct < 0.1:
            patterns.append({
                "pattern": "Doji",
                "type": "neutral",
                "date": date_str,
                "price": round(c["close"], 2),
                "days_ago": days_ago,
                "strength": "MODERATE",
            })

        if idx >= 2:
            pp = df.iloc[idx - 2]
            prev_body = abs(prev["close"] - prev["open"])
            prev_range = prev["high"] - prev["low"]
            prev_body_pct = prev_body / prev_range if prev_range > 0 else 1

            if (pp["close"] < pp["open"]
                    and prev_body_pct < 0.3
                    and c["close"] > c["open"]
                    and c["close"] > (pp["open"] + pp["close"]) / 2):
                patterns.append({
                    "pattern": "Morning Star",
                    "type": "bullish",
                    "date": date_str,
                    "price": round(c["close"], 2),
                    "days_ago": days_ago,
                    "strength": "STRONG",
                })

            if (pp["close"] > pp["open"]
                    and prev_body_pct < 0.3
                    and c["close"] < c["open"]
                    and c["close"] < (pp["open"] + pp["close"]) / 2):
                patterns.append({
                    "pattern": "Evening Star",
                    "type": "bearish",
                    "date": date_str,
                    "price": round(c["close"], 2),
                    "days_ago": days_ago,
                    "strength": "STRONG",
                })

    return patterns


# ═══════════ NEW: Multi-Timeframe Analysis ═══════════

def multi_timeframe_analysis(df: pd.DataFrame) -> dict:
    if len(df) < 60:
        return {"weekly_trend": "UNKNOWN", "alignment": "UNKNOWN"}

    weekly = df.resample("W").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()

    if len(weekly) < 10:
        return {"weekly_trend": "UNKNOWN", "alignment": "UNKNOWN"}

    w_ema8 = weekly["close"].ewm(span=8).mean()
    w_ema21 = weekly["close"].ewm(span=21).mean()
    w_ema50 = weekly["close"].ewm(span=50).mean() if len(weekly) >= 50 else w_ema21

    w_close = weekly["close"].iloc[-1]
    w_e8 = w_ema8.iloc[-1]
    w_e21 = w_ema21.iloc[-1]

    if w_close > w_e8 > w_e21:
        weekly_trend = "BULLISH"
    elif w_close < w_e8 < w_e21:
        weekly_trend = "BEARISH"
    else:
        weekly_trend = "SIDEWAYS"

    w_rsi = _compute_rsi(weekly["close"], 14)

    d_close = df["close"].iloc[-1]
    d_ema9 = df["close"].ewm(span=9).mean().iloc[-1]
    d_ema21 = df["close"].ewm(span=21).mean().iloc[-1]

    if d_close > d_ema9 > d_ema21:
        daily_trend = "BULLISH"
    elif d_close < d_ema9 < d_ema21:
        daily_trend = "BEARISH"
    else:
        daily_trend = "SIDEWAYS"

    if weekly_trend == daily_trend:
        alignment = "ALIGNED"
    elif weekly_trend == "SIDEWAYS" or daily_trend == "SIDEWAYS":
        alignment = "PARTIAL"
    else:
        alignment = "DIVERGENT"

    weekly_higher_lows = False
    if len(weekly) >= 4:
        recent_lows = weekly["low"].tail(4).values
        weekly_higher_lows = all(recent_lows[j] >= recent_lows[j - 1] * 0.98 for j in range(1, len(recent_lows)))

    return {
        "weekly_trend": weekly_trend,
        "daily_trend": daily_trend,
        "alignment": alignment,
        "weekly_ema8": round(w_e8, 2),
        "weekly_ema21": round(w_e21, 2),
        "weekly_rsi": round(w_rsi, 1) if w_rsi else None,
        "weekly_higher_lows": weekly_higher_lows,
        "daily_ema9": round(d_ema9, 2),
        "daily_ema21": round(d_ema21, 2),
    }


def _compute_rsi(series: pd.Series, period: int = 14) -> float | None:
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return None if np.isnan(val) else val


# ═══════════ NEW: Relative Strength vs Nifty ═══════════

def compute_relative_strength(df: pd.DataFrame) -> dict:
    try:
        import yfinance as yf
        nifty = yf.Ticker("^NSEI").history(period="1y", interval="1d")
        if nifty.empty:
            return {"rs_rating": "N/A"}

        nifty.index = pd.to_datetime(nifty.index).tz_localize(None)
        nifty = nifty.rename(columns={"Close": "close"})

        common = df.index.intersection(nifty.index)
        if len(common) < 30:
            return {"rs_rating": "N/A"}

        stock_close = df.loc[common, "close"]
        nifty_close = nifty.loc[common, "close"]

        rs_line = stock_close / nifty_close
        rs_ema20 = rs_line.ewm(span=20).mean()

        rs_current = rs_line.iloc[-1]
        rs_ema = rs_ema20.iloc[-1]

        if rs_current > rs_ema:
            rs_trend = "OUTPERFORMING"
        else:
            rs_trend = "UNDERPERFORMING"

        stock_1m = (stock_close.iloc[-1] / stock_close.iloc[-22] - 1) * 100 if len(stock_close) >= 22 else 0
        nifty_1m = (nifty_close.iloc[-1] / nifty_close.iloc[-22] - 1) * 100 if len(nifty_close) >= 22 else 0

        stock_3m = (stock_close.iloc[-1] / stock_close.iloc[-66] - 1) * 100 if len(stock_close) >= 66 else 0
        nifty_3m = (nifty_close.iloc[-1] / nifty_close.iloc[-66] - 1) * 100 if len(nifty_close) >= 66 else 0

        rs_pct_rank = rs_line.rank(pct=True).iloc[-1] * 100

        return {
            "rs_trend": rs_trend,
            "rs_percentile": round(rs_pct_rank, 0),
            "stock_1m_return": round(stock_1m, 2),
            "nifty_1m_return": round(nifty_1m, 2),
            "stock_3m_return": round(stock_3m, 2),
            "nifty_3m_return": round(nifty_3m, 2),
            "alpha_1m": round(stock_1m - nifty_1m, 2),
            "alpha_3m": round(stock_3m - nifty_3m, 2),
        }
    except Exception as e:
        logger.warning(f"RS calculation failed: {e}")
        return {"rs_trend": "N/A"}


# ═══════════ NEW: Chart Patterns ═══════════

def detect_chart_patterns(df: pd.DataFrame, lookback: int = 60) -> list[dict]:
    recent = df.tail(lookback)
    if len(recent) < 30:
        return []

    patterns = []

    _detect_flag(recent, patterns)
    _detect_triangle(recent, patterns)
    _detect_double_bottom_top(recent, patterns)

    return patterns


def _detect_flag(df: pd.DataFrame, patterns: list):
    n = len(df)
    if n < 25:
        return

    impulse = df.iloc[:int(n * 0.4)]
    consolidation = df.iloc[int(n * 0.4):]

    impulse_return = (impulse["close"].iloc[-1] - impulse["close"].iloc[0]) / impulse["close"].iloc[0]
    consol_range = (consolidation["high"].max() - consolidation["low"].min()) / consolidation["close"].mean()

    if abs(impulse_return) > 0.05 and consol_range < 0.06:
        flag_type = "Bull Flag" if impulse_return > 0 else "Bear Flag"
        patterns.append({
            "pattern": flag_type,
            "type": "bullish" if impulse_return > 0 else "bearish",
            "strength": "STRONG" if abs(impulse_return) > 0.10 else "MODERATE",
            "impulse_pct": round(impulse_return * 100, 1),
            "consolidation_pct": round(consol_range * 100, 1),
        })


def _detect_triangle(df: pd.DataFrame, patterns: list):
    n = len(df)
    if n < 20:
        return

    thirds = n // 3
    if thirds < 3:
        return
    h1 = df["high"].iloc[:thirds].max()
    h2 = df["high"].iloc[thirds:2*thirds].max()
    h3 = df["high"].iloc[2*thirds:].max()
    l1 = df["low"].iloc[:thirds].min()
    l2 = df["low"].iloc[thirds:2*thirds].min()
    l3 = df["low"].iloc[2*thirds:].min()

    highs_converging = h1 > h2 > h3
    lows_converging = l1 < l2 < l3

    if highs_converging and lows_converging:
        patterns.append({
            "pattern": "Symmetrical Triangle",
            "type": "neutral",
            "strength": "MODERATE",
        })
    elif not highs_converging and lows_converging:
        patterns.append({
            "pattern": "Ascending Triangle",
            "type": "bullish",
            "strength": "STRONG",
        })
    elif highs_converging and not lows_converging:
        patterns.append({
            "pattern": "Descending Triangle",
            "type": "bearish",
            "strength": "STRONG",
        })


def _detect_double_bottom_top(df: pd.DataFrame, patterns: list):
    n = len(df)
    if n < 30:
        return

    swing_lows = []
    swing_highs = []
    for i in range(5, n - 5):
        if df["low"].iloc[i] == df["low"].iloc[i-5:i+6].min():
            swing_lows.append((i, df["low"].iloc[i]))
        if df["high"].iloc[i] == df["high"].iloc[i-5:i+6].max():
            swing_highs.append((i, df["high"].iloc[i]))

    for a in range(len(swing_lows)):
        for b in range(a + 1, len(swing_lows)):
            i1, p1 = swing_lows[a]
            i2, p2 = swing_lows[b]
            if i2 - i1 < 10:
                continue
            diff_pct = abs(p1 - p2) / ((p1 + p2) / 2) * 100
            if diff_pct < 2.0:
                patterns.append({
                    "pattern": "Double Bottom",
                    "type": "bullish",
                    "strength": "STRONG",
                    "level": round((p1 + p2) / 2, 2),
                })
                return

    for a in range(len(swing_highs)):
        for b in range(a + 1, len(swing_highs)):
            i1, p1 = swing_highs[a]
            i2, p2 = swing_highs[b]
            if i2 - i1 < 10:
                continue
            diff_pct = abs(p1 - p2) / ((p1 + p2) / 2) * 100
            if diff_pct < 2.0:
                patterns.append({
                    "pattern": "Double Top",
                    "type": "bearish",
                    "strength": "STRONG",
                    "level": round((p1 + p2) / 2, 2),
                })
                return


# ═══════════ NEW: CPR (Central Pivot Range) ═══════════

def compute_cpr(df: pd.DataFrame) -> dict:
    if len(df) < 2:
        return {}

    prev = df.iloc[-2]
    h, l, c = prev["high"], prev["low"], prev["close"]

    pivot = (h + l + c) / 3
    bc = (h + l) / 2
    tc = 2 * pivot - bc

    r1 = 2 * pivot - l
    r2 = pivot + (h - l)
    r3 = r1 + (h - l)
    s1 = 2 * pivot - h
    s2 = pivot - (h - l)
    s3 = s1 - (h - l)

    cpr_width = abs(tc - bc) / pivot * 100

    current = df["close"].iloc[-1]
    if current > tc:
        position = "ABOVE_CPR"
    elif current < bc:
        position = "BELOW_CPR"
    else:
        position = "INSIDE_CPR"

    return {
        "pivot": round(pivot, 2),
        "tc": round(tc, 2),
        "bc": round(bc, 2),
        "r1": round(r1, 2),
        "r2": round(r2, 2),
        "r3": round(r3, 2),
        "s1": round(s1, 2),
        "s2": round(s2, 2),
        "s3": round(s3, 2),
        "cpr_width_pct": round(cpr_width, 2),
        "narrow_cpr": cpr_width < 0.5,
        "position": position,
    }


# ═══════════ NEW: VWAP Analysis ═══════════

def analyze_vwap(df: pd.DataFrame) -> dict:
    if "vwap" not in df.columns or len(df) < 5:
        return {}

    current = df["close"].iloc[-1]
    vwap_val = df["vwap"].iloc[-1]

    if np.isnan(vwap_val):
        return {}

    dist_pct = (current - vwap_val) / vwap_val * 100

    if current > vwap_val:
        position = "ABOVE_VWAP"
    else:
        position = "BELOW_VWAP"

    vwap_slope = (df["vwap"].iloc[-1] - df["vwap"].iloc[-5]) / df["vwap"].iloc[-5] * 100 if len(df) >= 5 else 0

    return {
        "vwap": round(vwap_val, 2),
        "distance_pct": round(dist_pct, 2),
        "position": position,
        "vwap_slope_pct": round(vwap_slope, 3),
        "near_vwap": abs(dist_pct) < 1.5,
    }


# ═══════════ NEW: Gap Analysis ═══════════

def detect_gaps(df: pd.DataFrame, lookback: int = 10) -> list[dict]:
    gaps = []
    recent = df.tail(lookback + 1)

    for i in range(1, len(recent)):
        prev_close = recent["close"].iloc[i - 1]
        curr_open = recent["open"].iloc[i]
        curr_low = recent["low"].iloc[i]
        curr_high = recent["high"].iloc[i]

        gap_pct = (curr_open - prev_close) / prev_close * 100

        if abs(gap_pct) < 1.0:
            continue

        prev_high = recent["high"].iloc[i - 1]

        if curr_open > prev_high:
            gap_type = "GAP_UP"
            filled = curr_low <= prev_high
        elif curr_open < recent["low"].iloc[i - 1]:
            gap_type = "GAP_DOWN"
            filled = curr_high >= recent["low"].iloc[i - 1]
        else:
            continue

        date_val = recent.index[i]
        gaps.append({
            "type": gap_type,
            "date": str(date_val.date()) if hasattr(date_val, "date") else str(date_val),
            "gap_pct": round(gap_pct, 2),
            "open_price": round(curr_open, 2),
            "prev_close": round(prev_close, 2),
            "filled": filled,
            "strength": "STRONG" if abs(gap_pct) > 3 else "MODERATE",
        })

    return gaps


# ═══════════ Enhanced Confluence Detection ═══════════

def detect_confluence(df: pd.DataFrame, fundamentals: dict = None) -> dict:
    current_price = df["close"].iloc[-1]

    fib = compute_fibonacci_retracement(df)
    fib_ext = compute_fibonacci_extensions(df)
    zones = detect_supply_demand_zones(df)
    trendlines = detect_trendlines(df)
    candle_patterns = detect_candlestick_patterns(df)
    mtf = multi_timeframe_analysis(df)
    rs = compute_relative_strength(df)
    chart_patterns = detect_chart_patterns(df)
    cpr = compute_cpr(df)
    vwap_data = analyze_vwap(df)
    gaps = detect_gaps(df)

    confluence_points = []
    confluence_score = 0
    max_score = 12

    if fib and fib.get("distance_to_nearest_pct", 100) < 2.0:
        confluence_score += 1
        confluence_points.append(f"Near Fib {fib['nearest_level']} level")

    active_demand = [z for z in zones if z["type"] == "demand" and not z["broken"]
                     and z["zone_bottom"] <= current_price <= z["zone_top"] * 1.03]
    active_supply = [z for z in zones if z["type"] == "supply" and not z["broken"]
                     and z["zone_bottom"] * 0.97 <= current_price <= z["zone_top"]]

    if active_demand:
        confluence_score += 1
        best = max(active_demand, key=lambda z: z["touches"])
        confluence_points.append(f"At demand zone ({best['zone_bottom']}-{best['zone_top']}, {best['touches']} touches)")

    if active_supply:
        confluence_score += 1
        best = max(active_supply, key=lambda z: z["touches"])
        confluence_points.append(f"At supply zone ({best['zone_bottom']}-{best['zone_top']}, {best['touches']} touches)")

    near_support = [t for t in trendlines if t["type"] == "ascending_support" and t["near_trendline"]]
    near_resistance = [t for t in trendlines if t["type"] == "descending_resistance" and t["near_trendline"]]

    if near_support:
        confluence_score += 1
        confluence_points.append(f"Near ascending support trendline ({near_support[0]['touches']} touches)")

    if near_resistance:
        confluence_score += 1
        confluence_points.append(f"Near descending resistance trendline ({near_resistance[0]['touches']} touches)")

    if "ema_200" in df.columns:
        ema200 = df["ema_200"].iloc[-1]
        if not np.isnan(ema200):
            dist_ema200 = abs(current_price - ema200) / current_price * 100
            if dist_ema200 < 2:
                confluence_score += 1
                confluence_points.append(f"Near 200 EMA (₹{ema200:.2f})")

    if "rsi" in df.columns:
        rsi = df["rsi"].iloc[-1]
        if not np.isnan(rsi):
            if rsi < 35:
                confluence_score += 1
                confluence_points.append(f"RSI oversold ({rsi:.1f})")
            elif rsi > 70:
                confluence_score += 1
                confluence_points.append(f"RSI overbought ({rsi:.1f})")

    bullish_candles = [p for p in candle_patterns if p["type"] == "bullish" and p["days_ago"] <= 2]
    bearish_candles = [p for p in candle_patterns if p["type"] == "bearish" and p["days_ago"] <= 2]

    if bullish_candles:
        confluence_score += 1
        names = ", ".join(p["pattern"] for p in bullish_candles[:2])
        confluence_points.append(f"Bullish candle: {names}")

    if bearish_candles:
        confluence_score += 1
        names = ", ".join(p["pattern"] for p in bearish_candles[:2])
        confluence_points.append(f"Bearish candle: {names}")

    if mtf.get("alignment") == "ALIGNED" and mtf.get("weekly_trend") in ("BULLISH", "BEARISH"):
        confluence_score += 1
        confluence_points.append(f"Weekly + Daily aligned {mtf['weekly_trend']}")

    if rs.get("rs_trend") == "OUTPERFORMING":
        confluence_score += 1
        confluence_points.append(f"Outperforming Nifty (RS percentile: {rs.get('rs_percentile', '?')}%)")

    if vwap_data.get("near_vwap"):
        confluence_score += 1
        confluence_points.append(f"Near VWAP (₹{vwap_data['vwap']})")

    signal = "NO_SIGNAL"
    if confluence_score >= 5 and active_demand and (bullish_candles or near_support):
        signal = "STRONG_BUY"
    elif confluence_score >= 3 and (active_demand or near_support or bullish_candles):
        signal = "BUY"
    elif confluence_score >= 5 and active_supply and (bearish_candles or near_resistance):
        signal = "STRONG_SELL"
    elif confluence_score >= 3 and (active_supply or near_resistance or bearish_candles):
        signal = "SELL"
    elif confluence_score >= 2:
        signal = "WATCH"

    entry = None
    target = None
    stop_loss = None

    if signal in ("STRONG_BUY", "BUY"):
        entry = current_price
        if active_demand:
            stop_loss = active_demand[0]["zone_bottom"] * 0.98
        elif near_support:
            stop_loss = near_support[0]["current_tl_price"] * 0.97
        elif cpr and cpr.get("s1"):
            stop_loss = cpr["s1"] * 0.99
        else:
            stop_loss = current_price * 0.95

        if fib_ext and fib_ext.get("extensions"):
            ext_prices = sorted(fib_ext["extensions"].values())
            above = [p for p in ext_prices if p > current_price]
            target = above[0] if above else current_price * 1.10
        elif active_supply:
            target = active_supply[0]["zone_bottom"]
        elif cpr and cpr.get("r2"):
            target = cpr["r2"]
        else:
            target = current_price * 1.10

        risk = entry - stop_loss
        if risk > 0:
            rr = (target - entry) / risk
            if rr < 2.0:
                target = entry + risk * 2.0

    return {
        "current_price": round(current_price, 2),
        "fibonacci": fib,
        "fibonacci_extensions": fib_ext,
        "supply_demand_zones": zones,
        "trendlines": trendlines,
        "candlestick_patterns": candle_patterns,
        "multi_timeframe": mtf,
        "relative_strength": rs,
        "chart_patterns": chart_patterns,
        "cpr": cpr,
        "vwap": vwap_data,
        "gaps": gaps,
        "confluence_score": confluence_score,
        "max_confluence": max_score,
        "confluence_points": confluence_points,
        "signal": signal,
        "entry": round(entry, 2) if entry else None,
        "target": round(target, 2) if target else None,
        "stop_loss": round(stop_loss, 2) if stop_loss else None,
    }


def _build_swing_verdict(analysis: dict, df: pd.DataFrame) -> dict:
    signal = analysis["signal"]
    score = analysis["confluence_score"]
    max_score = analysis["max_confluence"]
    entry = analysis.get("entry")
    target = analysis.get("target")
    stop_loss = analysis.get("stop_loss")
    cmp = analysis.get("current_price", 0)
    mtf = analysis.get("multi_timeframe", {})
    rs = analysis.get("relative_strength", {})
    candles = analysis.get("candlestick_patterns", [])
    chart_pats = analysis.get("chart_patterns", [])

    rsi = float(df["rsi"].iloc[-1]) if "rsi" in df.columns and not np.isnan(df["rsi"].iloc[-1]) else None
    adx = float(df["adx"].iloc[-1]) if "adx" in df.columns and not np.isnan(df["adx"].iloc[-1]) else None

    verdict = {"action": "IGNORE", "color": "#6b7280", "icon": "—"}
    reasons = []
    risks = []
    plan = []

    if signal in ("STRONG_BUY", "BUY") and entry and target and stop_loss:
        risk_pct = round((entry - stop_loss) / entry * 100, 1)
        reward_pct = round((target - entry) / entry * 100, 1)
        rr = round(reward_pct / risk_pct, 1) if risk_pct > 0 else 0

        if signal == "STRONG_BUY":
            verdict = {"action": "BUY", "color": "#22c55e", "icon": "BUY"}
        else:
            verdict = {"action": "BUY", "color": "#3b82f6", "icon": "BUY"}

        reasons.append(f"{score}/{max_score} confluence factors aligned")
        if mtf.get("alignment") == "ALIGNED" and mtf.get("weekly_trend") == "BULLISH":
            reasons.append("Weekly and daily trends both bullish")
        if rs.get("rs_trend") == "OUTPERFORMING":
            reasons.append(f"Outperforming Nifty 50 (top {100 - rs.get('rs_percentile', 50):.0f}%)")
        bullish_candles = [p for p in candles if p["type"] == "bullish" and p["days_ago"] <= 2]
        if bullish_candles:
            reasons.append(f"Bullish candle pattern: {bullish_candles[0]['pattern']}")
        bullish_chart = [p for p in chart_pats if p.get("type") == "bullish"]
        if bullish_chart:
            reasons.append(f"Chart pattern: {bullish_chart[0]['pattern']}")

        plan.append(f"Entry: ₹{entry:.2f} (current price)")
        plan.append(f"Stop Loss: ₹{stop_loss:.2f} (risk: {risk_pct}%)")
        plan.append(f"Target: ₹{target:.2f} (reward: {reward_pct}%)")
        plan.append(f"Risk:Reward = 1:{rr}")
        plan.append("Deploy 50% now, add 50% on confirmation")
        plan.append("Hold period: 1-4 weeks")

        if rsi and rsi > 75:
            risks.append(f"RSI is overbought ({rsi:.0f}) — momentum may fade")
        if rsi and rsi > 85:
            risks.append("Extremely overbought — high chance of pullback")
        if mtf.get("weekly_rsi") and float(mtf["weekly_rsi"]) > 80:
            risks.append(f"Weekly RSI overbought ({mtf['weekly_rsi']}) — late stage rally")
        if rs.get("stock_1m_return") and float(rs["stock_1m_return"]) > 30:
            risks.append(f"Already up {rs['stock_1m_return']:.0f}% in 1 month — chasing risk")

        verdict["risk_pct"] = risk_pct
        verdict["reward_pct"] = reward_pct
        verdict["rr"] = rr

    elif signal == "WATCH":
        verdict = {"action": "WATCH", "color": "#eab308", "icon": "WATCH"}
        reasons.append(f"{score}/{max_score} confluence — needs more alignment")
        if mtf.get("weekly_trend") == "BULLISH":
            reasons.append("Weekly trend is bullish — structure is favorable")
        if rs.get("rs_trend") == "OUTPERFORMING":
            reasons.append("Stock is outperforming the market")

        plan.append("Add to watchlist — don't buy yet")
        plan.append("Wait for: pullback to support/demand zone, or breakout with volume")
        if analysis.get("supply_demand_zones"):
            demand = [z for z in analysis["supply_demand_zones"] if z["type"] == "demand" and not z.get("broken")]
            if demand:
                plan.append(f"Key demand zone: ₹{demand[0]['zone_bottom']}-₹{demand[0]['zone_top']}")

        if rsi and rsi > 70:
            risks.append(f"RSI overbought ({rsi:.0f}) — wait for cooling")

    elif signal in ("SELL", "STRONG_SELL"):
        verdict = {"action": "AVOID", "color": "#ef4444", "icon": "AVOID"}
        reasons.append("Bearish confluence detected — selling pressure")
        if mtf.get("weekly_trend") == "BEARISH":
            reasons.append("Weekly trend is bearish")
        if rs.get("rs_trend") == "UNDERPERFORMING":
            reasons.append("Underperforming the broader market")
        plan.append("Do not buy — bearish setup")
        plan.append("If holding, consider trailing stop or exit on bounce")

    else:
        verdict = {"action": "NO SETUP", "color": "#6b7280", "icon": "SKIP"}
        reasons.append(f"Only {score}/{max_score} confluence — no clear edge")
        if mtf.get("weekly_trend") == "SIDEWAYS":
            reasons.append("Sideways trend — no directional bias")
        plan.append("Skip this stock for now")
        plan.append("Re-check if price reaches a key support/demand zone")

    if not risks:
        risks.append("Always use a stop loss — never risk more than 2-3% of capital per trade")

    verdict["reasons"] = reasons
    verdict["risks"] = risks
    verdict["plan"] = plan
    return verdict


def full_analysis(df: pd.DataFrame, fundamentals: dict = None) -> dict:
    from data.preprocessor import Preprocessor
    df = df.dropna(subset=["close"])
    df_ind = Preprocessor.add_indicators(df)

    analysis = detect_confluence(df_ind, fundamentals)
    analysis["swing_verdict"] = _build_swing_verdict(analysis, df_ind)
    analysis["ohlcv_json"] = _df_to_chart_json(df)

    return analysis


def _df_to_chart_json(df: pd.DataFrame) -> list[dict]:
    rows = []
    for idx, row in df.tail(250).iterrows():
        ts = idx
        if hasattr(ts, "timestamp"):
            ts_val = int(ts.timestamp())
        else:
            ts_val = str(ts)
        rows.append({
            "time": ts_val,
            "open": round(row["open"], 2),
            "high": round(row["high"], 2),
            "low": round(row["low"], 2),
            "close": round(row["close"], 2),
            "volume": int(row.get("volume", 0)),
        })
    return rows
