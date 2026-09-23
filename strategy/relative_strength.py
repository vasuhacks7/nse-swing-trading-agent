import pandas as pd
from strategy.base import BaseStrategy, StockPick


class RelativeStrength(BaseStrategy):
    """Top 3-month/6-month performers pulling back to support = leader continuation."""
    name = "relative_strength"

    def __init__(self, config: dict):
        self.min_return_3m = config.get("min_return_3m", 15)
        self.min_return_6m = config.get("min_return_6m", 25)

    def scan(self, df: pd.DataFrame, fundamentals: dict) -> StockPick | None:
        if len(df) < 130:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = last["close"]

        ret_3m = last.get("return_3m", 0)
        ret_6m = last.get("return_6m", 0)

        is_strong_performer = ret_3m >= self.min_return_3m or ret_6m >= self.min_return_6m
        if not is_strong_performer:
            return None

        ema_21 = last.get("ema_21", 0)
        ema_50 = last.get("ema_50", 0)
        pullback_to_support = close <= ema_21 * 1.01 and close >= ema_50 * 0.97
        bouncing = close > prev["close"]

        if not pullback_to_support:
            return None

        score = 0.0
        reasons = []

        if ret_3m >= self.min_return_3m:
            score += 0.25
            reasons.append(f"Strong 3M return: {ret_3m:+.1f}%")
        if ret_6m >= self.min_return_6m:
            score += 0.2
            reasons.append(f"Strong 6M return: {ret_6m:+.1f}%")

        if pullback_to_support:
            score += 0.25
            reasons.append("Pulled back to EMA support — buy the dip in a leader")

        if bouncing:
            score += 0.1
            reasons.append("Bounce confirmed — close > previous close")

        rsi = last.get("rsi", 50)
        if 35 < rsi < 55:
            score += 0.15
            reasons.append(f"RSI cooled to {rsi:.0f} — reset after run")

        vol_ratio = last.get("volume_ratio", 1)
        if vol_ratio < 0.8:
            score += 0.05
            reasons.append("Light volume on pullback — no panic selling")

        if score < 0.5:
            return None

        score = min(score, 1.0)
        atr = last.get("atr", close * 0.02)
        stop = round(ema_50 - atr * 0.5, 2)
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
