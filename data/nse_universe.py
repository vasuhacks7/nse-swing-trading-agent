import logging
import io
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parent.parent / "db"
_CACHE_FILE = _CACHE_DIR / "nse_symbols.csv"
_CACHE_MAX_AGE_DAYS = 7

NSE_CSV_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

NIFTY_500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
NIFTY_TOTAL_MARKET_URL = "https://archives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv"


def fetch_all_nse_symbols() -> list[str]:
    cached = _load_cache()
    if cached is not None:
        return cached

    symbols = []

    symbols = _try_fetch_equity_list()
    if symbols:
        _save_cache(symbols)
        return symbols

    symbols = _try_fetch_nifty_total_market()
    if symbols:
        _save_cache(symbols)
        return symbols

    symbols = _try_fetch_nifty_500()
    if symbols:
        _save_cache(symbols)
        return symbols

    logger.warning("All NSE fetches failed, falling back to hardcoded Nifty 500 symbols")
    symbols = _get_hardcoded_broad_list()
    _save_cache(symbols)
    return symbols


def _try_fetch_equity_list() -> list[str]:
    try:
        logger.info("Fetching full NSE equity list...")
        resp = requests.get(NSE_CSV_URL, headers=NSE_HEADERS, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        col = _find_symbol_column(df)
        if col is None:
            return []
        symbols = df[col].dropna().str.strip().tolist()
        symbols = [s for s in symbols if s and not s.startswith(" ")]
        yf_symbols = [f"{s}.NS" for s in symbols]
        logger.info(f"Fetched {len(yf_symbols)} NSE symbols from equity list")
        return yf_symbols
    except Exception as e:
        logger.warning(f"Failed to fetch NSE equity list: {e}")
        return []


def _try_fetch_nifty_total_market() -> list[str]:
    try:
        logger.info("Fetching Nifty Total Market index...")
        resp = requests.get(NIFTY_TOTAL_MARKET_URL, headers=NSE_HEADERS, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        col = _find_symbol_column(df)
        if col is None:
            return []
        symbols = df[col].dropna().str.strip().tolist()
        yf_symbols = [f"{s}.NS" for s in symbols if s]
        logger.info(f"Fetched {len(yf_symbols)} symbols from Nifty Total Market")
        return yf_symbols
    except Exception as e:
        logger.warning(f"Failed to fetch Nifty Total Market: {e}")
        return []


def _try_fetch_nifty_500() -> list[str]:
    try:
        logger.info("Fetching Nifty 500 index...")
        resp = requests.get(NIFTY_500_URL, headers=NSE_HEADERS, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        col = _find_symbol_column(df)
        if col is None:
            return []
        symbols = df[col].dropna().str.strip().tolist()
        yf_symbols = [f"{s}.NS" for s in symbols if s]
        logger.info(f"Fetched {len(yf_symbols)} symbols from Nifty 500")
        return yf_symbols
    except Exception as e:
        logger.warning(f"Failed to fetch Nifty 500: {e}")
        return []


def _find_symbol_column(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        lower = col.strip().lower()
        if lower in ("symbol", "ticker", "scrip code", "nse symbol"):
            return col
    for col in df.columns:
        if "symbol" in col.lower():
            return col
    return df.columns[0] if len(df.columns) > 0 else None


def _load_cache() -> list[str] | None:
    if not _CACHE_FILE.exists():
        return None
    age = datetime.now() - datetime.fromtimestamp(_CACHE_FILE.stat().st_mtime)
    if age > timedelta(days=_CACHE_MAX_AGE_DAYS):
        return None
    try:
        df = pd.read_csv(_CACHE_FILE)
        symbols = df["symbol"].tolist()
        logger.info(f"Loaded {len(symbols)} symbols from cache")
        return symbols
    except Exception:
        return None


def _save_cache(symbols: list[str]):
    _CACHE_DIR.mkdir(exist_ok=True)
    pd.DataFrame({"symbol": symbols}).to_csv(_CACHE_FILE, index=False)
    logger.info(f"Cached {len(symbols)} symbols to {_CACHE_FILE}")


def prefilter_symbols(symbols: list[str], min_price: float = 50,
                      max_price: float = 50000, min_avg_volume: int = 100000) -> list[str]:
    import yfinance as yf

    logger.info(f"Pre-filtering {len(symbols)} symbols (price {min_price}-{max_price}, min vol {min_avg_volume})...")

    batch_size = 50
    filtered = []

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        tickers_str = " ".join(batch)
        try:
            data = yf.download(tickers_str, period="5d", progress=False, threads=True)
            if data.empty:
                continue

            if len(batch) == 1:
                close = data["Close"].iloc[-1] if not data["Close"].empty else 0
                vol = data["Volume"].mean() if not data["Volume"].empty else 0
                if min_price <= close <= max_price and vol >= min_avg_volume:
                    filtered.append(batch[0])
            else:
                for sym in batch:
                    try:
                        if sym in data["Close"].columns:
                            close = data["Close"][sym].iloc[-1]
                            vol = data["Volume"][sym].mean()
                            if pd.notna(close) and pd.notna(vol):
                                if min_price <= close <= max_price and vol >= min_avg_volume:
                                    filtered.append(sym)
                    except (KeyError, IndexError):
                        continue
        except Exception as e:
            logger.debug(f"Batch filter failed: {e}")

    logger.info(f"Pre-filter: {len(symbols)} → {len(filtered)} tradeable stocks")
    return filtered


def _get_hardcoded_broad_list() -> list[str]:
    """Broad list of ~200 liquid NSE stocks as fallback."""
    return [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
        "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
        "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS",
        "SUNPHARMA.NS", "ULTRACEMCO.NS", "NESTLEIND.NS", "WIPRO.NS", "HCLTECH.NS",
        "BAJFINANCE.NS", "BAJAJFINSV.NS", "TATAMOTORS.NS", "POWERGRID.NS", "NTPC.NS",
        "ONGC.NS", "ADANIENT.NS", "ADANIPORTS.NS", "JSWSTEEL.NS", "TATASTEEL.NS",
        "TECHM.NS", "INDUSINDBK.NS", "CIPLA.NS", "DRREDDY.NS", "DIVISLAB.NS",
        "EICHERMOT.NS", "HEROMOTOCO.NS", "BAJAJ-AUTO.NS", "BPCL.NS", "COALINDIA.NS",
        "GRASIM.NS", "BRITANNIA.NS", "APOLLOHOSP.NS", "TATACONSUM.NS", "M&M.NS",
        "HINDALCO.NS", "SBILIFE.NS", "HDFCLIFE.NS", "DABUR.NS", "PIDILITIND.NS",
        "VEDL.NS", "AMBUJACEM.NS", "GODREJCP.NS", "HAVELLS.NS", "SIEMENS.NS",
        "DLF.NS", "BANKBARODA.NS", "PNB.NS", "CANBK.NS", "IDFCFIRSTB.NS",
        "TRENT.NS", "ZOMATO.NS", "PAYTM.NS", "NYKAA.NS", "POLICYBZR.NS",
        "DMART.NS", "PIIND.NS", "CHOLAFIN.NS", "MUTHOOTFIN.NS", "SHRIRAMFIN.NS",
        "BERGEPAINT.NS", "COLPAL.NS", "MARICO.NS", "TATAPOWER.NS", "ADANIGREEN.NS",
        "TORNTPHARM.NS", "AUROPHARMA.NS", "BIOCON.NS", "LUPIN.NS", "ALKEM.NS",
        "LAURUSLABS.NS", "PERSISTENT.NS", "COFORGE.NS", "LTIM.NS", "MPHASIS.NS",
        "CROMPTON.NS", "VOLTAS.NS", "BLUESTARLT.NS", "WHIRLPOOL.NS", "BATAINDIA.NS",
        "PAGEIND.NS", "RELAXO.NS", "TVSMOTOR.NS", "ASHOKLEY.NS", "ESCORTS.NS",
        "MRF.NS", "CUMMINSIND.NS", "ABB.NS", "BHEL.NS", "HAL.NS",
        "BEL.NS", "IRCTC.NS", "INDIANB.NS", "FEDERALBNK.NS", "RBLBANK.NS",
        "AUBANK.NS", "BANDHANBNK.NS", "MANAPPURAM.NS", "MFSL.NS", "ICICIGI.NS",
        "SBICARD.NS", "ICICIPRULI.NS", "HDFCAMC.NS", "NAM-INDIA.NS", "MCX.NS",
        "IEX.NS", "CDSL.NS", "BSE.NS", "CAMS.NS", "KPITTECH.NS",
        "TATAELXSI.NS", "HAPPSTMNDS.NS", "LTTS.NS", "SONACOMS.NS", "AFFLE.NS",
        "DEEPAKNTR.NS", "ATUL.NS", "NAVINFLUOR.NS", "SRF.NS", "FLUOROCHEM.NS",
        "ASTRAL.NS", "SUPREMEIND.NS", "POLYCAB.NS", "KEI.NS", "FINOLEX.NS",
        "CONCOR.NS", "DELHIVERY.NS", "ZYDUSLIFE.NS", "GLAND.NS", "IPCALAB.NS",
        "METROPOLIS.NS", "LALPATHLAB.NS", "MAXHEALTH.NS", "FORTIS.NS", "SYNGENE.NS",
        "UPL.NS", "COROMANDEL.NS", "TATACOMM.NS", "INDUSTOWER.NS", "IDEA.NS",
        "SAIL.NS", "NMDC.NS", "NATIONALUM.NS", "HINDCOPPER.NS", "JINDALSTEL.NS",
        "RECLTD.NS", "PFC.NS", "NHPC.NS", "SJVN.NS", "IRFC.NS",
        "GAIL.NS", "IGL.NS", "MGL.NS", "PETRONET.NS", "HPCL.NS",
        "IOC.NS", "OBEROIRLTY.NS", "GODREJPROP.NS", "PRESTIGE.NS", "BRIGADE.NS",
        "PHOENIXLTD.NS", "DIXON.NS", "KAYNES.NS", "CLEAN.NS", "JSWENERGY.NS",
        "NAUKRI.NS", "INDIGO.NS", "JUBLFOOD.NS", "DEVYANI.NS", "SAPPHIRE.NS",
        "SUNTV.NS", "PVR.NS", "PVRINOX.NS", "ZEEL.NS", "MANYAVAR.NS",
        "STARHEALTH.NS", "NIACL.NS", "GICRE.NS", "LICI.NS", "CENTRALBK.NS",
        "MAHABANK.NS", "IOB.NS", "UCOBANK.NS", "BALKRISIND.NS", "APOLLOTYRE.NS",
        "EXIDEIND.NS", "AMARARAJA.NS", "MOTHERSON.NS", "BOSCHLTD.NS", "SUNDRMFAST.NS",
    ]
