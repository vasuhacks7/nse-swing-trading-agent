import pandas as pd
from strategy.base import BaseStrategy, StockPick


class BollingerSqueeze(BaseStrategy):
    """Bollinger Width at historic low then starts expanding + positive momentum = squeeze fire."""
    name = "bollinger_squeeze"

    def __init__(self, config: dict):
        self.squeeze_pctile = config.get("squeeze_pctile", 0.10)

    def scan(self, df: pd.DataFrame, fundamentals: dict) -> StockPick | None:
        if len(df) < 120:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = last["close"]

        bb_width = last.get("bb_width", 0)
        bb_width_prev = prev.get("bb_width", 0)
        bb_pctile = last.get("bb_width_pctile", 1)
        bb_pctile_prev = prev.get("bb_width_pctile", 1)

        was_squeezed = bb_pctile_prev <= self.squeeze_pctile
        expanding = bb_width > bb_width_prev

        if not (was_squeezed and expanding):
            return None

        macd_hist = last.get("macd_hist", 0)
        bullish_momentum = macd_hist > 0 or close > last.get("ema_21", 0)
        if not bullish_momentum:
            return None

        score = 0.0
        reasons = []

        score += 0.3
        reasons.append(f"Squeeze fired — BB width expanding from {bb_pctile_prev:.0%} percentile")

        if macd_hist > 0:
            score += 0.2
            reasons.append(f"MACD histogram positive ({macd_hist:.2f}) — bullish momentum")

        ema_50 = last.get("ema_50", 0)
        if close > ema_50 and last.get("ema_21", 0) > ema_50:
            score += 0.2
            reasons.append("Uptrend — EMAs aligned, squeeze expanding upward")

        vol_ratio = last.get("volume_ratio", 1)
        if vol_ratio > 1.2:
            score += 0.15
            reasons.append(f"Volume expanding ({vol_ratio:.1f}x) — confirming breakout")

        rsi = last.get("rsi", 50)
        if 45 < rsi < 70:
            score += 0.1
            reasons.append(f"RSI {rsi:.0f} — momentum with room to run")

        adx = last.get("adx", 0)
        if adx > 15:
            score += 0.05
            reasons.append(f"ADX {adx:.0f} — trend developing")

        if score < 0.5:
            return None

        score = min(score, 1.0)
        atr = last.get("atr", close * 0.02)
        bb_lower = last.get("bb_lower", close - atr * 2)
        stop = round(max(bb_lower - atr * 0.3, close - atr * 2), 2)
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
