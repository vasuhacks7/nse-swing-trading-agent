import pandas as pd
from strategy.base import BaseStrategy, StockPick


class VWAPBounce(BaseStrategy):
    """Stock pulls back to VWAP with volume dry-up, then bounces = institutional accumulation."""
    name = "vwap_bounce"

    def __init__(self, config: dict):
        pass

    def scan(self, df: pd.DataFrame, fundamentals: dict) -> StockPick | None:
        if len(df) < 50:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = last["close"]
        vwap = last.get("vwap", 0)

        if not vwap or vwap <= 0:
            return None

        pct_from_vwap = (close - vwap) / vwap * 100

        near_vwap = -2.0 <= pct_from_vwap <= 1.0
        bouncing = close > prev["close"] and last["low"] < prev["low"]

        if not (near_vwap and bouncing):
            return None

        ema_50 = last.get("ema_50", 0)
        in_uptrend = close > ema_50 and last.get("ema_21", 0) > ema_50
        if not in_uptrend:
            return None

        score = 0.0
        reasons = []

        score += 0.25
        reasons.append(f"Bounced near VWAP ({pct_from_vwap:+.1f}% from VWAP)")

        if bouncing:
            score += 0.2
            reasons.append("Reversal candle — lower low but higher close")

        if in_uptrend:
            score += 0.2
            reasons.append("Uptrend — above 50 EMA, EMAs aligned")

        rsi = last.get("rsi", 50)
        if 35 < rsi < 55:
            score += 0.15
            reasons.append(f"RSI {rsi:.0f} — oversold enough for bounce")

        vol_ratio = last.get("volume_ratio", 1)
        vol_dry = last.get("vol_dry_up", False)
        if vol_dry or vol_ratio < 0.8:
            score += 0.1
            reasons.append("Volume dried up on pullback — sellers done")
        elif vol_ratio > 1.3:
            score += 0.1
            reasons.append(f"Volume pickup on bounce ({vol_ratio:.1f}x)")

        if score < 0.5:
            return None

        score = min(score, 1.0)
        atr = last.get("atr", close * 0.02)
        recent_low = df["low"].tail(5).min()
        stop = round(min(recent_low - atr * 0.3, close - atr * 1.5), 2)
        risk = close - stop
        if risk <= 0:
            return None
        target = round(close + risk * 2.5, 2)
        reasons.append(f"R:R = 1:{(target - close) / risk:.1f}")

        return StockPick(
            symbol=last.get("symbol", ""),
            strategy=self.name,
            score=score,
            action="BUY",
            entry_price=close,
            target_price=target,
            stop_loss=stop,
            reasoning=" | ".join(reasons),
            technical_summary=self._technical_summary(df),
            fundamental_summary=self._fundamental_summary(fundamentals),
        )
