from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class StockPick:
    symbol: str
    strategy: str
    score: float
    action: str
    entry_price: float
    target_price: float
    stop_loss: float
    reasoning: str
    technical_summary: str
    fundamental_summary: str
    risk_reward_ratio: float = 0.0

    def __post_init__(self):
        if self.risk_reward_ratio == 0.0 and self.stop_loss and self.entry_price:
            risk = abs(self.entry_price - self.stop_loss)
            reward = abs(self.target_price - self.entry_price)
            self.risk_reward_ratio = round(reward / risk, 2) if risk > 0 else 0.0


class BaseStrategy(ABC):
    name: str = "base"

    @abstractmethod
    def scan(self, df: pd.DataFrame, fundamentals: dict) -> StockPick | None:
        pass

    def _technical_summary(self, df: pd.DataFrame) -> str:
        last = df.iloc[-1]
        parts = []
        if "rsi" in df.columns:
            parts.append(f"RSI={last['rsi']:.1f}")
        if "macd_hist" in df.columns:
            parts.append(f"MACD_hist={last['macd_hist']:.2f}")
        if "adx" in df.columns:
            parts.append(f"ADX={last['adx']:.1f}")
        if "volume_ratio" in df.columns:
            parts.append(f"Vol_ratio={last['volume_ratio']:.2f}")
        if "bb_pct" in df.columns:
            parts.append(f"BB%={last['bb_pct']:.2f}")
        if "atr" in df.columns:
            parts.append(f"ATR={last['atr']:.2f}")
        return " | ".join(parts)

    def _fundamental_summary(self, fund: dict) -> str:
        parts = []
        if fund.get("pe_ratio"):
            parts.append(f"P/E={fund['pe_ratio']:.1f}")
        if fund.get("roe"):
            parts.append(f"ROE={fund['roe']:.1f}%")
        if fund.get("debt_to_equity") is not None:
            parts.append(f"D/E={fund['debt_to_equity']:.2f}")
        if fund.get("revenue_growth"):
            parts.append(f"Rev_growth={fund['revenue_growth']:.1f}%")
        if fund.get("profit_margin"):
            parts.append(f"Margin={fund['profit_margin']:.1f}%")
        return " | ".join(parts) if parts else "No fundamental data"
