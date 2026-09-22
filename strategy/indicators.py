import pandas as pd
import numpy as np


def rsi_signal(df: pd.DataFrame, oversold: float = 30, overbought: float = 70) -> pd.Series:
    rsi = df["rsi"]
    signal = pd.Series(0.0, index=df.index)

    signal[rsi <= oversold] = 1.0
    signal[rsi >= overbought] = -1.0

    mid = (oversold + overbought) / 2
    mask_mid = (rsi > oversold) & (rsi < overbought)
    signal[mask_mid] = (mid - rsi[mask_mid]) / (mid - oversold)

    return signal.clip(-1, 1)


def macd_signal(df: pd.DataFrame) -> pd.Series:
    hist = df["macd_hist"]
    signal = pd.Series(0.0, index=df.index)

    hist_std = hist.rolling(20).std().replace(0, np.nan)
    signal = (hist / hist_std).clip(-1, 1)

    crossover_up = (df["macd"] > df["macd_signal"]) & (df["macd"].shift(1) <= df["macd_signal"].shift(1))
    crossover_down = (df["macd"] < df["macd_signal"]) & (df["macd"].shift(1) >= df["macd_signal"].shift(1))
    signal[crossover_up] = signal[crossover_up].clip(lower=0.5)
    signal[crossover_down] = signal[crossover_down].clip(upper=-0.5)

    return signal.fillna(0)


def moving_average_signal(df: pd.DataFrame) -> pd.Series:
    signal = pd.Series(0.0, index=df.index)

    above_short = (df["close"] > df["sma_short"]).astype(float) * 0.33
    above_medium = (df["close"] > df["sma_medium"]).astype(float) * 0.33
    above_long = (df["close"] > df["sma_long"]).astype(float) * 0.34

    signal = above_short + above_medium + above_long

    golden = (df["sma_short"] > df["sma_long"]) & (df["sma_short"].shift(1) <= df["sma_long"].shift(1))
    death = (df["sma_short"] < df["sma_long"]) & (df["sma_short"].shift(1) >= df["sma_long"].shift(1))
    signal[golden] = 1.0
    signal[death] = -1.0

    signal = signal * 2 - 1
    return signal.clip(-1, 1)


def bollinger_signal(df: pd.DataFrame) -> pd.Series:
    bb_pct = df["bb_pct"]
    signal = 1 - 2 * bb_pct
    return signal.clip(-1, 1).fillna(0)


def volume_signal(df: pd.DataFrame, surge_multiplier: float = 1.5) -> pd.Series:
    vol_ratio = df["volume_ratio"]
    price_change = df["close"].pct_change()

    signal = pd.Series(0.0, index=df.index)

    surge = vol_ratio > surge_multiplier
    signal[surge & (price_change > 0)] = vol_ratio[surge & (price_change > 0)].clip(upper=2) / 2
    signal[surge & (price_change < 0)] = -vol_ratio[surge & (price_change < 0)].clip(upper=2) / 2

    return signal.clip(-1, 1).fillna(0)


def stochastic_signal(df: pd.DataFrame) -> pd.Series:
    k = df["stoch_k"]
    d = df["stoch_d"]

    signal = pd.Series(0.0, index=df.index)

    signal[k <= 20] = 1.0
    signal[k >= 80] = -1.0

    mid_range = (k > 20) & (k < 80)
    signal[mid_range] = (50 - k[mid_range]) / 50

    crossover_up = (k > d) & (k.shift(1) <= d.shift(1)) & (k < 50)
    crossover_down = (k < d) & (k.shift(1) >= d.shift(1)) & (k > 50)
    signal[crossover_up] = signal[crossover_up].clip(lower=0.5)
    signal[crossover_down] = signal[crossover_down].clip(upper=-0.5)

    return signal.clip(-1, 1).fillna(0)
