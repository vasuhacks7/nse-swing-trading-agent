import pandas as pd
from strategy.base import BaseStrategy, StockPick


class InsideBarBreakout(BaseStrategy):
    """Inside bar near support in uptrend = tight-stop breakout entry."""
    name = "inside_bar_breakout"

    def __init__(self, config: dict):
        pass

    def scan(self, df: pd.DataFrame, fundamentals: dict) -> StockPick | None:
        if len(df) < 50:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = last["close"]

        is_inside = bool(last.get("inside_bar", False))
        if not is_inside:
            return None

        in_uptrend = close > last.get("ema_50", 0) and last.get("ema_21", 0) > last.get("ema_50", 0)
        if not in_uptrend:
            return None

        score = 0.0
        reasons = []

        score += 0.3
        reasons.append(f"Inside bar: range [{last['low']:.2f}-{last['high']:.2f}] "
                       f"within [{prev['low']:.2f}-{prev['high']:.2f}]")

        if in_uptrend:
            score += 0.2
            reasons.append("Uptrend intact — EMAs aligned")

        ema_21 = last.get("ema_21", 0)
        near_ema = close >= ema_21 * 0.98 and close <= ema_21 * 1.02
        if near_ema:
            score += 0.15
            reasons.append("Consolidating near 21 EMA")

        rsi = last.get("rsi", 50)
        if 40 < rsi < 60:
            score += 0.1
            reasons.append(f"RSI neutral at {rsi:.0f} — coiled for move")

        adx = last.get("adx", 0)
        if adx > 20:
            score += 0.1
            reasons.append(f"ADX {adx:.0f} — underlying trend strength")

        vol_ratio = last.get("volume_ratio", 1)
        if vol_ratio < 1.0:
            score += 0.1
            reasons.append("Low volume — contraction before expansion")

        if score < 0.5:
            return None

        score = min(score, 1.0)
        mother_bar_range = prev["high"] - prev["low"]
        stop = round(prev["low"] - mother_bar_range * 0.1, 2)
        risk = close - stop
        if risk <= 0:
            return None
        target = round(prev["high"] + mother_bar_range * 1.5, 2)
        rr = (target - close) / risk
        if rr < 2.0:
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
