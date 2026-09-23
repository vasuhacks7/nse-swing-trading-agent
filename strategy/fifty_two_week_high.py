import pandas as pd
from strategy.base import BaseStrategy, StockPick


class FiftyTwoWeekHigh(BaseStrategy):
    """Stocks near 52-week high that pull back to EMA support = continuation buy."""
    name = "52_week_high"

    def __init__(self, config: dict):
        self.max_pct_from_high = config.get("max_pct_from_high", -10)
        self.min_pct_from_high = config.get("min_pct_from_high", -2)

    def scan(self, df: pd.DataFrame, fundamentals: dict) -> StockPick | None:
        if len(df) < 252:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = last["close"]

        pct_from_high = last.get("pct_from_high_52w", -100)
        if not (self.max_pct_from_high <= pct_from_high <= self.min_pct_from_high):
            return None

        ema_21 = last.get("ema_21", 0)
        ema_50 = last.get("ema_50", 0)
        near_ema_support = close <= ema_21 * 1.02 and close >= ema_50 * 0.98
        bouncing = close > prev["close"]

        if not (near_ema_support and bouncing):
            return None

        score = 0.0
        reasons = []

        score += 0.3
        reasons.append(f"Near 52-week high ({pct_from_high:+.1f}% from peak)")

        if near_ema_support:
            score += 0.25
            reasons.append("Pullback to EMA support zone")
        if bouncing:
            score += 0.15
            reasons.append("Price bouncing — higher close than previous")

        rsi = last.get("rsi", 50)
        if 40 < rsi < 65:
            score += 0.15
            reasons.append(f"RSI healthy at {rsi:.0f}")

        vol_dry = last.get("vol_dry_up", False)
        if vol_dry:
            score += 0.1
            reasons.append("Volume dried up on pullback — sellers exhausted")

        adx = last.get("adx", 0)
        if adx > 20:
            score += 0.1
            reasons.append(f"ADX {adx:.0f} — trend has strength")

        if score < 0.5:
            return None

        score = min(score, 1.0)
        atr = last.get("atr", close * 0.02)
        stop = round(ema_50 - atr * 0.5, 2)
        risk = close - stop
        if risk <= 0:
            return None
        high_52w = last.get("high_52w", close * 1.1)
        target = round(max(high_52w, close + risk * 2.5), 2)
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
