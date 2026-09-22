import pandas as pd
from strategy.base import BaseStrategy, StockPick


class TrendFollowing(BaseStrategy):
    name = "trend_following"

    def __init__(self, config: dict):
        self.ema_short = config.get("ema_short", 9)
        self.ema_long = config.get("ema_long", 21)
        self.adx_min = config.get("adx_min", 25)

    def scan(self, df: pd.DataFrame, fundamentals: dict) -> StockPick | None:
        if len(df) < 50:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = last["close"]

        ema_s = last.get(f"ema_{self.ema_short}", last.get("ema_9", 0))
        ema_l = last.get(f"ema_{self.ema_long}", last.get("ema_21", 0))
        ema_50 = last.get("ema_50", 0)

        if not ema_s or not ema_l:
            return None

        in_uptrend = ema_s > ema_l and close > ema_50
        adx_strong = last.get("adx", 0) >= self.adx_min
        di_bullish = last.get("di_plus", 0) > last.get("di_minus", 0)

        pullback_to_ema = (
            close <= ema_s * 1.01 and
            close >= ema_l * 0.99 and
            prev["close"] < last["close"]
        )

        if not in_uptrend:
            return None
        if not adx_strong:
            return None

        score = 0.0
        reasons = []

        if in_uptrend:
            score += 0.25
            reasons.append(f"Uptrend: EMA{self.ema_short} > EMA{self.ema_long} > EMA50")

        if adx_strong:
            score += 0.2
            reasons.append(f"Strong trend (ADX={last.get('adx', 0):.1f})")

        if di_bullish:
            score += 0.15
            reasons.append("DI+ > DI- — bullish directional")

        if pullback_to_ema:
            score += 0.25
            reasons.append("Pullback entry near short-term EMA support")
        else:
            score += 0.1

        rsi = last.get("rsi", 50)
        if 40 < rsi < 65:
            score += 0.15
            reasons.append(f"RSI healthy at {rsi:.1f}")

        if score < 0.4:
            return None

        score = min(score, 1.0)
        atr = last.get("atr", close * 0.02)
        stop = round(max(ema_l - atr * 0.5, close - atr * 2), 2)
        risk = close - stop
        target = round(close + risk * 3, 2)
        rr = (target - close) / risk if risk > 0 else 0
        reasons.append(f"R:R = 1:{rr:.1f}")

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
