import pandas as pd
from strategy.base import BaseStrategy, StockPick


class FundamentalValue(BaseStrategy):
    name = "fundamental_value"

    def __init__(self, config: dict):
        self.max_pe = config.get("max_pe", 25)
        self.min_roe = config.get("min_roe", 15)
        self.max_debt_equity = config.get("max_debt_equity", 1.0)
        self.min_revenue_growth = config.get("min_revenue_growth", 10)

    def scan(self, df: pd.DataFrame, fundamentals: dict) -> StockPick | None:
        if len(df) < 50 or not fundamentals:
            return None

        last = df.iloc[-1]
        close = last["close"]

        pe = fundamentals.get("pe_ratio")
        roe = fundamentals.get("roe")
        de = fundamentals.get("debt_to_equity")
        rev_growth = fundamentals.get("revenue_growth")
        margin = fundamentals.get("profit_margin")
        pb = fundamentals.get("pb_ratio")

        score = 0.0
        reasons = []

        if pe is not None and 0 < pe <= self.max_pe:
            score += 0.2
            reasons.append(f"Attractive P/E of {pe:.1f} (below {self.max_pe})")
        elif pe is None or pe <= 0 or pe > self.max_pe * 1.5:
            return None

        if roe is not None and roe >= self.min_roe:
            score += 0.2
            reasons.append(f"Strong ROE of {roe:.1f}%")
        elif roe is None or roe < self.min_roe * 0.7:
            return None

        if de is not None and de <= self.max_debt_equity:
            score += 0.15
            reasons.append(f"Low debt (D/E={de:.2f})")

        if rev_growth is not None and rev_growth >= self.min_revenue_growth:
            score += 0.15
            reasons.append(f"Revenue growing {rev_growth:.1f}%")

        if margin is not None and margin > 10:
            score += 0.1
            reasons.append(f"Healthy margin of {margin:.1f}%")

        rsi = last.get("rsi", 50)
        above_sma_50 = close > last.get("sma_50", 0) if last.get("sma_50") else False
        rsi_not_overbought = rsi < 65

        if above_sma_50 and rsi_not_overbought:
            score += 0.2
            reasons.append(f"Technically sound: above 50 SMA, RSI={rsi:.1f}")
        elif rsi >= 70:
            score -= 0.1
            reasons.append(f"Warning: RSI overbought at {rsi:.1f}")

        if score < 0.4:
            return None

        score = min(score, 1.0)
        atr = last.get("atr", close * 0.02)
        risk = max(atr * 1.5, close * 0.05)
        target = round(close + risk * 2, 2)
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
