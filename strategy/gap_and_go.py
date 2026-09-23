import pandas as pd
from strategy.base import BaseStrategy, StockPick


class GapAndGo(BaseStrategy):
    """Stock gaps up 2%+ from tight base on high volume = institutional interest."""
    name = "gap_and_go"

    def __init__(self, config: dict):
        self.min_gap_pct = config.get("min_gap_pct", 2.0)
        self.min_vol_ratio = config.get("min_vol_ratio", 1.5)

    def scan(self, df: pd.DataFrame, fundamentals: dict) -> StockPick | None:
        if len(df) < 50:
            return None

        last = df.iloc[-1]
        close = last["close"]

        gap_pct = last.get("gap_pct", 0)
        vol_ratio = last.get("volume_ratio", 1)

        has_gap = gap_pct >= self.min_gap_pct
        has_volume = vol_ratio >= self.min_vol_ratio
        close_above_open = close >= last["open"]

        if not (has_gap and has_volume and close_above_open):
            return None

        was_consolidating = False
        if len(df) >= 10:
            recent_atr = df["atr"].iloc[-10:-1].mean()
            recent_price = df["close"].iloc[-10:-1].mean()
            if recent_price > 0 and recent_atr / recent_price < 0.02:
                was_consolidating = True

        score = 0.0
        reasons = []

        score += 0.3
        reasons.append(f"Gap up {gap_pct:+.1f}% on {vol_ratio:.1f}x volume")

        if close_above_open:
            score += 0.15
            reasons.append("Held gap — close above open (buyers in control)")

        if was_consolidating:
            score += 0.2
            reasons.append("Was in tight consolidation — breakout from base")

        ema_50 = last.get("ema_50", 0)
        if close > ema_50:
            score += 0.15
            reasons.append("Above 50 EMA — uptrend")

        rsi = last.get("rsi", 50)
        if rsi < 75:
            score += 0.1
            reasons.append(f"RSI {rsi:.0f} — not yet overbought")

        adx = last.get("adx", 0)
        if adx > 20:
            score += 0.1
            reasons.append(f"ADX {adx:.0f} — trend backing the gap")

        if score < 0.5:
            return None

        score = min(score, 1.0)
        gap_low = last["open"]
        atr = last.get("atr", close * 0.02)
        stop = round(max(gap_low - atr * 0.3, close - atr * 2), 2)
        risk = close - stop
        if risk <= 0:
            return None
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
