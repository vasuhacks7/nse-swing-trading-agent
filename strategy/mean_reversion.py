import pandas as pd
from strategy.base import BaseStrategy, StockPick


class MeanReversion(BaseStrategy):
    name = "mean_reversion"

    def __init__(self, config: dict):
        self.rsi_oversold = config.get("rsi_oversold", 30)
        self.bb_lower_touch = config.get("bb_lower_touch", True)

    def scan(self, df: pd.DataFrame, fundamentals: dict) -> StockPick | None:
        if len(df) < 50:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = last["close"]
        rsi = last.get("rsi", 50)
        bb_pct = last.get("bb_pct", 0.5)
        bb_lower = last.get("bb_lower", close)

        is_oversold = rsi <= self.rsi_oversold
        near_bb_lower = bb_pct <= 0.05 or close <= bb_lower * 1.01
        rsi_turning_up = rsi > prev.get("rsi", rsi)

        pe = fundamentals.get("pe_ratio")
        roe = fundamentals.get("roe")
        has_good_fundamentals = (pe is not None and pe > 0 and pe < 30 and
                                 roe is not None and roe > 12)

        if not (is_oversold or near_bb_lower):
            return None
        if not rsi_turning_up:
            return None

        score = 0.0
        reasons = []

        if is_oversold:
            score += 0.3
            reasons.append(f"RSI oversold at {rsi:.1f}")
        if near_bb_lower:
            score += 0.25
            reasons.append(f"Price near Bollinger lower band (BB%={bb_pct:.2f})")
        if rsi_turning_up:
            score += 0.15
            reasons.append("RSI turning upward — momentum shift")
        if has_good_fundamentals:
            score += 0.3
            reasons.append(f"Strong fundamentals (P/E={pe:.1f}, ROE={roe:.1f}%)")
        else:
            score += 0.1

        score = min(score, 1.0)
        atr = last.get("atr", close * 0.02)
        risk = atr * 1.5
        bb_mid = last.get("bb_middle", close + atr * 3)
        target = round(max(bb_mid, close + risk * 2), 2)
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
