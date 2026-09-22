import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from config.settings import Settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 50


class DataFetcher:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._fundamentals_cache: dict[str, dict] = {}
        self._fundamentals_cache_date: str = ""

    def fetch_ohlcv(self, symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        if df.empty:
            raise ValueError(f"No data for {symbol}")
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df = df.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })
        df = df[["open", "high", "low", "close", "volume"]]
        df["symbol"] = symbol
        return df

    def fetch_fundamentals(self, symbol: str) -> dict:
        if symbol in self._fundamentals_cache and self._fundamentals_cache_date == datetime.now().strftime("%Y-%m-%d"):
            return self._fundamentals_cache[symbol]

        ticker = yf.Ticker(symbol)
        info = ticker.info
        result = {
            "symbol": symbol,
            "company_name": info.get("longName", ""),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "market_cap": info.get("marketCap", 0),
            "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
            "forward_pe": info.get("forwardPE"),
            "pb_ratio": info.get("priceToBook"),
            "peg_ratio": info.get("pegRatio"),
            "roe": _pct(info.get("returnOnEquity")),
            "roa": _pct(info.get("returnOnAssets")),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "revenue_growth": _pct(info.get("revenueGrowth")),
            "earnings_growth": _pct(info.get("earningsGrowth")),
            "profit_margin": _pct(info.get("profitMargins")),
            "operating_margin": _pct(info.get("operatingMargins")),
            "dividend_yield": _pct(info.get("dividendYield")),
            "eps": info.get("trailingEps"),
            "book_value": info.get("bookValue"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "avg_volume": info.get("averageVolume"),
            "beta": info.get("beta"),
        }
        self._fundamentals_cache[symbol] = result
        self._fundamentals_cache_date = datetime.now().strftime("%Y-%m-%d")
        return result

    def fetch_stock(self, symbol: str, period: str = "1y") -> dict:
        ohlcv = self.fetch_ohlcv(symbol, period)
        try:
            fundamentals = self.fetch_fundamentals(symbol)
        except Exception as e:
            logger.warning(f"Could not fetch fundamentals for {symbol}: {e}")
            fundamentals = {"symbol": symbol}
        return {"ohlcv": ohlcv, "fundamentals": fundamentals}

    def get_universe_symbols(self) -> list[str]:
        from data.nse_universe import fetch_all_nse_symbols, prefilter_symbols

        mode = self.settings.market.get("universe_mode", "dynamic")
        if mode != "dynamic":
            return self.settings.market.get("universe", [])

        all_symbols = fetch_all_nse_symbols()
        pf = self.settings.market.get("prefilter", {})
        return prefilter_symbols(
            all_symbols,
            min_price=pf.get("min_price", 50),
            max_price=pf.get("max_price", 50000),
            min_avg_volume=pf.get("min_avg_volume", 100000),
        )

    def fetch_universe_batch(self, symbols: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
        results = {}
        total = len(symbols)

        for batch_start in range(0, total, BATCH_SIZE):
            batch = symbols[batch_start:batch_start + BATCH_SIZE]
            tickers_str = " ".join(batch)
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
            logger.info(f"Batch {batch_num}/{total_batches}: downloading {len(batch)} stocks...")

            try:
                data = yf.download(
                    tickers_str,
                    period=period,
                    interval="1d",
                    group_by="ticker",
                    threads=True,
                    progress=False,
                )

                if len(batch) == 1:
                    sym = batch[0]
                    df = data.copy()
                    df = _clean_ohlcv(df, sym)
                    if df is not None and len(df) >= 30:
                        results[sym] = df
                else:
                    for sym in batch:
                        try:
                            if sym in data.columns.get_level_values(0):
                                df = data[sym].copy()
                            else:
                                continue
                            df = _clean_ohlcv(df, sym)
                            if df is not None and len(df) >= 30:
                                results[sym] = df
                        except Exception:
                            pass

            except Exception as e:
                logger.error(f"Batch download failed: {e}")
                for sym in batch:
                    try:
                        df = self.fetch_ohlcv(sym, period)
                        if len(df) >= 30:
                            results[sym] = df
                    except Exception:
                        pass

        logger.info(f"Downloaded {len(results)}/{total} stocks successfully")
        return results

    def fetch_universe(self, period: str = "1y") -> dict[str, dict]:
        universe = self.get_universe_symbols()
        logger.info(f"Scanning {len(universe)} stocks...")
        results = {}
        for symbol in universe:
            try:
                results[symbol] = self.fetch_stock(symbol, period)
                logger.info(f"Fetched {symbol}: {len(results[symbol]['ohlcv'])} bars")
            except Exception as e:
                logger.error(f"Failed {symbol}: {e}")
        return results


def _clean_ohlcv(df: pd.DataFrame, symbol: str) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    df = df.copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    col_map = {}
    for c in df.columns:
        cl = c.lower() if isinstance(c, str) else str(c).lower()
        if "open" in cl:
            col_map[c] = "open"
        elif "high" in cl:
            col_map[c] = "high"
        elif "low" in cl:
            col_map[c] = "low"
        elif "close" in cl and "adj" not in cl:
            col_map[c] = "close"
        elif "volume" in cl:
            col_map[c] = "volume"
    df = df.rename(columns=col_map)
    needed = ["open", "high", "low", "close", "volume"]
    if not all(c in df.columns for c in needed):
        return None
    df = df[needed]
    df = df.dropna(subset=["close"])
    if df.empty:
        return None
    df["symbol"] = symbol
    return df


def _pct(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return round(val * 100, 2) if abs(val) < 1 else round(val, 2)
    return None
