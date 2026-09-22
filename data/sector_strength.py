import logging

import pandas as pd

logger = logging.getLogger(__name__)

SECTOR_MAP = {
    "Technology": "IT",
    "Information Technology": "IT",
    "Financial Services": "BFSI",
    "Banks": "BFSI",
    "Industrials": "Capital Goods",
    "Consumer Cyclical": "Consumer",
    "Consumer Defensive": "FMCG",
    "Healthcare": "Pharma",
    "Energy": "Energy",
    "Basic Materials": "Metals & Mining",
    "Utilities": "Power",
    "Communication Services": "Telecom",
    "Real Estate": "Realty",
    "Consumer Staples": "FMCG",
}


def compute_sector_strength(universe_data: dict) -> dict:
    sector_stocks = {}

    for symbol, data in universe_data.items():
        fund = data.get("fundamentals", {})
        ohlcv = data.get("ohlcv")
        if ohlcv is None or ohlcv.empty or len(ohlcv) < 20:
            continue

        raw_sector = fund.get("sector", "")
        sector = SECTOR_MAP.get(raw_sector, raw_sector) or "Unknown"

        last = ohlcv.iloc[-1]
        close = last.get("close", 0)
        ema_21 = last.get("ema_21", 0)
        ema_50 = last.get("ema_50", 0)
        rsi = last.get("rsi", 50)

        strength_score = 0
        if close and ema_21 and close > ema_21:
            strength_score += 1
        if close and ema_50 and close > ema_50:
            strength_score += 1
        if 45 < rsi < 70:
            strength_score += 1

        if sector not in sector_stocks:
            sector_stocks[sector] = []
        sector_stocks[sector].append({
            "symbol": symbol,
            "strength": strength_score,
            "rsi": rsi,
        })

    sector_scores = {}
    for sector, stocks in sector_stocks.items():
        if len(stocks) < 3:
            continue
        avg_strength = sum(s["strength"] for s in stocks) / len(stocks)
        avg_rsi = sum(s["rsi"] for s in stocks) / len(stocks)
        pct_above_ema = sum(1 for s in stocks if s["strength"] >= 2) / len(stocks)

        sector_scores[sector] = {
            "stock_count": len(stocks),
            "avg_strength": round(avg_strength, 2),
            "avg_rsi": round(avg_rsi, 1),
            "pct_bullish": round(pct_above_ema * 100, 1),
            "rank_score": round(avg_strength * 0.6 + pct_above_ema * 0.4, 3),
        }

    ranked = sorted(sector_scores.items(), key=lambda x: x[1]["rank_score"], reverse=True)
    for i, (sector, data) in enumerate(ranked):
        data["rank"] = i + 1
        if data["rank_score"] > 2.0:
            data["momentum"] = "STRONG"
        elif data["rank_score"] > 1.2:
            data["momentum"] = "MODERATE"
        else:
            data["momentum"] = "WEAK"

    return dict(ranked)


def get_sector_bonus(symbol: str, fundamentals: dict, sector_scores: dict) -> float:
    raw_sector = fundamentals.get("sector", "")
    sector = SECTOR_MAP.get(raw_sector, raw_sector) or "Unknown"

    if sector not in sector_scores:
        return 0.0

    data = sector_scores[sector]
    momentum = data.get("momentum", "MODERATE")

    if momentum == "STRONG":
        return 0.05
    elif momentum == "WEAK":
        return -0.05
    return 0.0
