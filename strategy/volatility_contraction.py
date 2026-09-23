import pandas as pd
from strategy.base import BaseStrategy, StockPick


class VolatilityContraction(BaseStrategy):
    """NR7/NR4 + tight Bollinger squeeze near support = coiled spring breakout."""
    name = "volatility_contraction"

    def __init__(self, config: dict):
        self.bb_width_pctile_max = config.get("bb_width_pctile_max", 0.15)

    def scan(self, df: pd.DataFrame, fundamentals: dict) -> StockPick | None:
        if len(df) < 60:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = last["close"]

        nr7 = bool(last.get("nr7", False))
        nr4 = bool(last.get("nr4", False))
        bb_squeeze = (last.get("bb_width_pctile", 1) <= self.bb_width_pctile_max)
        tight = bool(last.get("tight_range", False))

        if not (nr7 or bb_squeeze):
            return None

        in_uptrend = close > last.get("ema_50", 0) and last.get("ema_21", 0) > last.get("ema_50", 0)
        if not in_uptrend:
            return None

        score = 0.0
        reasons = []

        if nr7:
            score += 0.25
            reasons.append("NR7 — narrowest range in 7 days (coiled spring)")
        if nr4:
            score += 0.1
            reasons.append("NR4 — extreme contraction")
        if bb_squeeze:
            score += 0.25
            reasons.append(f"Bollinger squeeze (width at {last.get('bb_width_pctile', 0):.0%} percentile)")
        if tight:
            score += 0.1
            reasons.append("Tight ATR/price ratio — consolidation")

        if in_uptrend:
            score += 0.2
            reasons.append("Uptrend intact (above 50 EMA, EMAs aligned)")

        rsi = last.get("rsi", 50)
        if 40 < rsi < 60:
            score += 0.1
            reasons.append(f"RSI neutral at {rsi:.0f} — not extended")

        if score < 0.45:
            return None

        score = min(score, 1.0)
        atr = last.get("atr", close * 0.02)
        daily_range = last["high"] - last["low"]
        stop = round(close - max(daily_range * 1.5, atr), 2)
        risk = close - stop
        target = round(close + risk * 3, 2)
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
