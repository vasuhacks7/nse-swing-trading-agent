import pandas as pd
from strategy.base import BaseStrategy, StockPick


class MomentumBreakout(BaseStrategy):
    name = "momentum_breakout"

    def __init__(self, config: dict):
        self.lookback = config.get("lookback_days", 20)
        self.volume_surge = config.get("volume_surge", 1.5)
        self.breakout_pct = config.get("breakout_pct", 0.02)

    def scan(self, df: pd.DataFrame, fundamentals: dict) -> StockPick | None:
        if len(df) < self.lookback + 5:
            return None

        last = df.iloc[-1]
        prev_high = df["high"].iloc[-(self.lookback + 1):-1].max()
        close = last["close"]
        vol_ratio = last.get("volume_ratio", 1)

        is_breakout = close > prev_high * (1 + self.breakout_pct)
        has_volume = vol_ratio >= self.volume_surge
        rsi_ok = 50 < last.get("rsi", 50) < 75
        adx_strong = last.get("adx", 0) > 20

        if not (is_breakout and has_volume):
            return None

        score = 0.0
        if is_breakout:
            score += 0.3
        if has_volume:
            score += 0.2 + min(0.1, (vol_ratio - self.volume_surge) * 0.1)
        if rsi_ok:
            score += 0.2
        if adx_strong:
            score += 0.2

        score = min(score, 1.0)
        atr = last.get("atr", close * 0.02)
        risk = atr * 1.5
        target = round(close + risk * 3, 2)
        stop = round(close - risk, 2)

        reasons = []
        reasons.append(f"Price broke {self.lookback}-day high of {prev_high:.2f}")
        reasons.append(f"Volume {vol_ratio:.1f}x above average")
        if rsi_ok:
            reasons.append(f"RSI at {last.get('rsi', 0):.1f} — strong but not overbought")
        if adx_strong:
            reasons.append(f"ADX at {last.get('adx', 0):.1f} — strong trend")
        reasons.append(f"R:R = 1:{(target - close) / (close - stop):.1f}")

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
