import logging

logger = logging.getLogger(__name__)

SECTOR_MAP = {
    "Technology": "IT", "Information Technology": "IT",
    "Financial Services": "BFSI", "Banks": "BFSI",
    "Industrials": "Capital Goods",
    "Consumer Cyclical": "Consumer", "Consumer Defensive": "FMCG",
    "Healthcare": "Pharma", "Energy": "Energy",
    "Basic Materials": "Metals & Mining",
    "Utilities": "Power", "Communication Services": "Telecom",
    "Real Estate": "Realty", "Consumer Staples": "FMCG",
}

CORRELATION_GROUPS = [
    {"HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS", "SBIN.NS", "INDUSINDBK.NS"},
    {"TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS", "LTIM.NS"},
    {"TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "VEDL.NS", "SAIL.NS"},
    {"SUNPHARMA.NS", "CIPLA.NS", "DRREDDY.NS", "DIVISLAB.NS", "AUROPHARMA.NS"},
    {"RELIANCE.NS", "ONGC.NS", "BPCL.NS", "IOC.NS"},
    {"BAJFINANCE.NS", "BAJAJFINSV.NS", "SHRIRAMFIN.NS"},
    {"TATAMOTORS.NS", "MARUTI.NS", "M&M.NS", "HEROMOTOCO.NS", "EICHERMOT.NS", "BAJAJ-AUTO.NS"},
    {"ADANIENT.NS", "ADANIPORTS.NS", "ADANIPOWER.NS", "ADANIGREEN.NS"},
    {"POWERGRID.NS", "NTPC.NS", "TATAPOWER.NS", "NHPC.NS"},
]

MAX_SAME_SECTOR = 1
MAX_CORRELATED = 1


def check_portfolio_risk(new_picks: list, open_positions=None,
                         universe_data: dict = None) -> list:
    """Filter picks for sector concentration and stock correlation."""
    if not new_picks:
        return new_picks

    open_positions = open_positions or []
    open_symbols = set()
    open_sectors = {}

    for pos in open_positions:
        sym = pos.get("symbol") if isinstance(pos, dict) else getattr(pos, "symbol", "")
        open_symbols.add(sym)
        if universe_data and sym in universe_data:
            fund = universe_data[sym].get("fundamentals", {})
            raw = fund.get("sector", "")
            sector = SECTOR_MAP.get(raw, raw) or "Unknown"
            open_sectors[sector] = open_sectors.get(sector, 0) + 1

    filtered = []
    day_sectors = dict(open_sectors)
    day_groups_used = set()

    for sym in open_symbols:
        for i, group in enumerate(CORRELATION_GROUPS):
            if sym in group:
                day_groups_used.add(i)

    for pick in new_picks:
        symbol = pick.symbol if hasattr(pick, "symbol") else pick.get("symbol", "")

        if symbol in open_symbols:
            logger.info(f"RISK SKIP {symbol}: already in open positions")
            continue

        sector = "Unknown"
        if universe_data and symbol in universe_data:
            fund = universe_data[symbol].get("fundamentals", {})
            raw = fund.get("sector", "")
            sector = SECTOR_MAP.get(raw, raw) or "Unknown"

        if sector != "Unknown" and day_sectors.get(sector, 0) >= MAX_SAME_SECTOR:
            logger.info(f"RISK SKIP {symbol}: sector {sector} already has {day_sectors[sector]} pick(s)")
            continue

        corr_blocked = False
        for i, group in enumerate(CORRELATION_GROUPS):
            if symbol in group and i in day_groups_used:
                logger.info(f"RISK SKIP {symbol}: correlated stock already picked")
                corr_blocked = True
                break
        if corr_blocked:
            continue

        filtered.append(pick)
        day_sectors[sector] = day_sectors.get(sector, 0) + 1
        for i, group in enumerate(CORRELATION_GROUPS):
            if symbol in group:
                day_groups_used.add(i)

    if len(filtered) < len(new_picks):
        logger.info(f"Portfolio risk: {len(new_picks)} -> {len(filtered)} picks")

    return filtered
