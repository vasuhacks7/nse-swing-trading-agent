import pandas as pd
from strategy.indicators import (
    rsi_signal, macd_signal, moving_average_signal,
    bollinger_signal, volume_signal, stochastic_signal,
)


class SignalGenerator:
    def __init__(self, strategy_params: dict):
        self.params = strategy_params
        self.weights = strategy_params.get("signals", {}).get("weights", {})
        self.buy_threshold = strategy_params.get("signals", {}).get("buy_threshold", 0.3)
        self.sell_threshold = strategy_params.get("signals", {}).get("sell_threshold", -0.3)

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        ind = self.params.get("indicators", {})

        df["sig_rsi"] = rsi_signal(
            df,
            oversold=ind.get("rsi", {}).get("oversold", 30),
            overbought=ind.get("rsi", {}).get("overbought", 70),
        )
        df["sig_macd"] = macd_signal(df)
        df["sig_ma"] = moving_average_signal(df)
        df["sig_bb"] = bollinger_signal(df)
        df["sig_vol"] = volume_signal(
            df,
            surge_multiplier=ind.get("volume", {}).get("surge_multiplier", 1.5),
        )
        df["sig_stoch"] = stochastic_signal(df)

        w = self.weights
        df["composite_signal"] = (
            w.get("rsi", 0.2) * df["sig_rsi"]
            + w.get("macd", 0.2) * df["sig_macd"]
            + w.get("moving_averages", 0.2) * df["sig_ma"]
            + w.get("bollinger", 0.15) * df["sig_bb"]
            + w.get("volume", 0.1) * df["sig_vol"]
            + w.get("stochastic", 0.15) * df["sig_stoch"]
        )

        df["action"] = "hold"
        df.loc[df["composite_signal"] >= self.buy_threshold, "action"] = "buy"
        df.loc[df["composite_signal"] <= self.sell_threshold, "action"] = "sell"

        return df
