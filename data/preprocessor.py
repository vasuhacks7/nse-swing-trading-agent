import pandas as pd
import numpy as np
import ta


MIN_BARS = 30


class Preprocessor:
    @staticmethod
    def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < MIN_BARS:
            raise ValueError(f"Need at least {MIN_BARS} bars, got {len(df)}")

        df = df.copy()

        df["rsi"] = ta.momentum.rsi(df["close"], window=14)

        macd = ta.trend.MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
        df["macd"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_hist"] = macd.macd_diff()

        for period in [9, 21, 50, 200]:
            df[f"ema_{period}"] = ta.trend.ema_indicator(df["close"], window=period)
            df[f"sma_{period}"] = ta.trend.sma_indicator(df["close"], window=period)

        bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2.0)
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_middle"] = bb.bollinger_mavg()
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_pct"] = bb.bollinger_pband()

        df["atr"] = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=14)

        stoch = ta.momentum.StochasticOscillator(df["high"], df["low"], df["close"], window=14, smooth_window=3)
        df["stoch_k"] = stoch.stoch()
        df["stoch_d"] = stoch.stoch_signal()

        adx = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14)
        df["adx"] = adx.adx()
        df["di_plus"] = adx.adx_pos()
        df["di_minus"] = adx.adx_neg()

        df["volume_sma_20"] = df["volume"].rolling(window=20).mean()
        df["volume_ratio"] = df["volume"] / df["volume_sma_20"]

        df["daily_return"] = df["close"].pct_change()
        df["high_20"] = df["high"].rolling(window=20).max()
        df["low_20"] = df["low"].rolling(window=20).min()

        df["pct_from_52w_high"] = (df["close"] / df["high"].rolling(252).max() - 1) * 100
        df["pct_from_52w_low"] = (df["close"] / df["low"].rolling(252).min() - 1) * 100

        typical = (df["high"] + df["low"] + df["close"]) / 3
        cum_tp_vol = (typical * df["volume"]).cumsum()
        cum_vol = df["volume"].cumsum()
        df["vwap"] = cum_tp_vol / cum_vol

        df["gap_pct"] = (df["open"] - df["close"].shift(1)) / df["close"].shift(1) * 100

        bb_width = (df["bb_upper"] - df["bb_lower"])
        bb_mid = df["bb_middle"]
        df["bb_width"] = bb_width / bb_mid.where(bb_mid > 0, 1)
        df["bb_width_pctile"] = df["bb_width"].rolling(120, min_periods=30).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
        )

        daily_range = df["high"] - df["low"]
        df["nr7"] = daily_range == daily_range.rolling(7).min()
        df["nr4"] = daily_range == daily_range.rolling(4).min()

        df["inside_bar"] = (df["high"] < df["high"].shift(1)) & (df["low"] > df["low"].shift(1))

        df["tight_range"] = df["atr"] / df["close"].where(df["close"] > 0, 1) < 0.015

        df["return_1m"] = df["close"].pct_change(20) * 100
        df["return_3m"] = df["close"].pct_change(63) * 100
        df["return_6m"] = df["close"].pct_change(126) * 100

        df["high_52w"] = df["high"].rolling(252, min_periods=60).max()
        df["pct_from_high_52w"] = (df["close"] / df["high_52w"] - 1) * 100

        df["vol_contraction"] = df["volume_ratio"] < 0.7
        df["vol_expansion"] = df["volume_ratio"] > 1.5
        df["vol_dry_up"] = df["volume_ratio"].rolling(5).mean() < 0.6

        return df
