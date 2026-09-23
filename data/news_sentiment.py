import logging
import re

import requests

logger = logging.getLogger(__name__)

NEGATIVE_KEYWORDS = [
    "fraud", "scam", "sebi penalty", "sebi ban", "tax raid", "ed raid",
    "cbi raid", "downgrade", "debt default", "bankruptcy", "insolvency",
    "nclt", "profit warning", "guidance cut", "layoff", "retrench",
    "promoter pledge", "promoter sell", "rating downgrade", "credit negative",
    "loss widens", "revenue miss", "earnings miss", "fir filed", "arrest",
    "investigation probe", "margin call", "stock crash", "share plunge",
]

POSITIVE_KEYWORDS = [
    "upgrade", "outperform", "buy rating", "target raised",
    "order win", "contract win", "deal win",
    "profit jump", "revenue beat", "earnings beat",
    "promoter buy", "buyback", "rating upgrade", "credit positive",
]


def check_news_sentiment(symbol: str) -> dict:
    """Check recent news headlines for a stock via Google News RSS."""
    clean = symbol.replace(".NS", "").replace(".BO", "")

    result = {
        "sentiment": "NEUTRAL",
        "negative_headlines": [],
        "positive_headlines": [],
        "should_skip": False,
        "risk_level": "LOW",
    }

    try:
        url = (f"https://news.google.com/rss/search?"
               f"q={clean}+NSE+stock&hl=en-IN&gl=IN&ceid=IN:en")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return result

        titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", resp.text)
        if not titles:
            titles = re.findall(r"<title>(.*?)</title>", resp.text)

        headlines = titles[1:11]
        neg_count = 0
        pos_count = 0

        for headline in headlines:
            hl = headline.lower()
            for kw in NEGATIVE_KEYWORDS:
                if kw in hl:
                    result["negative_headlines"].append(headline[:100])
                    neg_count += 1
                    break
            for kw in POSITIVE_KEYWORDS:
                if kw in hl:
                    result["positive_headlines"].append(headline[:100])
                    pos_count += 1
                    break

        if neg_count >= 3:
            result["sentiment"] = "VERY_NEGATIVE"
            result["should_skip"] = True
            result["risk_level"] = "HIGH"
        elif neg_count >= 2:
            result["sentiment"] = "NEGATIVE"
            result["should_skip"] = True
            result["risk_level"] = "MEDIUM"
        elif neg_count == 1 and pos_count == 0:
            result["sentiment"] = "SLIGHTLY_NEGATIVE"
            result["risk_level"] = "MEDIUM"
        elif pos_count >= 2:
            result["sentiment"] = "POSITIVE"
        elif pos_count >= 1:
            result["sentiment"] = "SLIGHTLY_POSITIVE"

        logger.debug(f"News {clean}: {result['sentiment']} (neg={neg_count} pos={pos_count})")
    except Exception as e:
        logger.debug(f"News check failed for {symbol}: {e}")

    return result
