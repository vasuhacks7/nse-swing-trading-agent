import pandas as pd
from strategy.base import BaseStrategy, StockPick


class MACDRSIConfluence(BaseStrategy):
    name = "macd_rsi_confluence"

    def __init__(self, config: dict):
        self.rsi_buy_zone = config.get("rsi_buy_zone", [35, 50])

    def scan(self, df: pd.DataFrame, fundamentals: dict) -> StockPick | None:
        if len(df) < 30:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = last["close"]
        rsi = last.get("rsi", 50)

        macd_crossover = (last.get("macd", 0) > last.get("macd_signal", 0) and
                          prev.get("macd", 0) <= prev.get("macd_signal", 0))

        macd_hist_rising = (last.get("macd_hist", 0) > prev.get("macd_hist", 0) and
                            last.get("macd_hist", 0) > 0)

        rsi_in_zone = self.rsi_buy_zone[0] <= rsi <= self.rsi_buy_zone[1]
        rsi_rising = rsi > prev.get("rsi", rsi)

        above_ema_50 = close > last.get("ema_50", 0) if last.get("ema_50") else True

        if not (macd_crossover or macd_hist_rising):
            return None
        if not (rsi_in_zone and rsi_rising):
            return None

        score = 0.0
        reasons = []

        if macd_crossover:
            score += 0.35
            reasons.append("MACD bullish crossover (MACD crossed above signal)")
        elif macd_hist_rising:
            score += 0.2
            reasons.append(f"MACD histogram rising ({last.get('macd_hist', 0):.3f})")

        if rsi_in_zone:
            score += 0.25
            reasons.append(f"RSI in buy zone at {rsi:.1f}")
        if rsi_rising:
            score += 0.1
            reasons.append("RSI momentum rising")
        if above_ema_50:
            score += 0.15
            reasons.append("Price above 50 EMA — uptrend intact")

        vol_ratio = last.get("volume_ratio", 1)
        if vol_ratio > 1.2:
            score += 0.15
            reasons.append(f"Volume confirmation ({vol_ratio:.1f}x avg)")

        score = min(score, 1.0)
        atr = last.get("atr", close * 0.02)
        risk = atr * 1.2
        target = round(close + risk * 2.5, 2)
        stop = round(close - risk, 2)
        rr = (target - close) / (close - stop) if (close - stop) > 0 else 0
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
