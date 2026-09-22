import re
import logging
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from config.settings import Settings
from data.store import DataStore

logger = logging.getLogger(__name__)

CHANNEL_URL = "https://t.me/s/hashtaghammer"

TV_SYMBOL_PATTERN = re.compile(
    r"tradingview\.com/chart/([A-Z][A-Z0-9&]{1,19})/", re.I
)

TV_NSE_PATTERN = re.compile(
    r"NSE[:\s]([A-Z][A-Z0-9&]{1,19})\b"
)

NSE_SYMBOL_PATTERN = re.compile(
    r"(?:^|[\s#])(?:NSE[:\s])?([A-Z][A-Z0-9&]{1,19})\b", re.MULTILINE
)

NOISE_WORDS = {
    "BUY", "SELL", "LONG", "SHORT", "ENTRY", "TARGET", "TGT", "SL",
    "STOP", "LOSS", "STOPLOSS", "CMP", "ABOVE", "BELOW", "NEAR",
    "THE", "FOR", "AND", "NOT", "WITH", "THIS", "THAT", "FROM",
    "HAS", "HAD", "ARE", "WAS", "WILL", "CAN", "MAY", "ALL",
    "NEW", "HIGH", "LOW", "DAY", "WEEK", "MONTH", "YEAR", "TODAY",
    "NSE", "BSE", "NIFTY", "BANKNIFTY", "SENSEX", "FII", "DII",
    "RSI", "MACD", "EMA", "SMA", "ATR", "ADX", "VWAP", "CPR",
    "RR", "RISK", "REWARD", "PNL", "ROI", "BREAKOUT", "BREAKDOWN",
    "SUPPORT", "RESISTANCE", "BULLISH", "BEARISH", "MOMENTUM",
    "UPDATE", "NOTE", "IMPORTANT", "ALERT", "TRADE", "STOCK",
    "MARKET", "CHART", "ANALYSIS", "PATTERN", "TREND", "VOLUME",
    "OPEN", "CLOSE", "DAILY", "WEEKLY", "MONTHLY", "CHECK",
    "WATCH", "WATCHLIST", "DISCLAIMER", "RESULT", "RESULTS",
    "SWING", "INTRADAY", "POSITIONAL", "INDEX", "SECTOR",
    "GOOD", "GREAT", "NICE", "BEST", "LOOK", "LOOKING",
    "HELLO", "HI", "MORNING", "EVENING", "GUYS", "FRIENDS",
    "FREE", "JOIN", "CHANNEL", "GROUP", "LINK", "CLICK",
    "IMG", "PDF", "VIDEO", "LIVE", "DONE", "BOOKED", "PROFIT",
    "IST", "PM", "AM", "STAY", "TUNED", "SUNDAY", "MONDAY",
    "LETS", "SEE", "HOW", "GOT", "RIGHT", "OPTION",
    "PRO", "PLAN", "SEBI", "PREMIUM", "PAID",
    "NEXT", "TRADING", "MY", "IT", "ITS", "HELD", "UP",
    "COMING", "BACK", "TIME", "JUST", "ABOUT", "BEEN",
    "SOME", "ALSO", "VERY", "MUCH", "MORE", "MOST",
    "THAN", "INTO", "WHAT", "WHEN", "WHERE", "WHICH",
    "THEIR", "THERE", "THESE", "THOSE", "BEEN", "BEING",
    "HAVE", "DOES", "DID", "SHOULD", "WOULD", "COULD",
    "BUT", "ONLY", "AFTER", "BEFORE", "DURING", "STILL",
    "YOUR", "YOU", "OUR", "EVERY", "EACH", "BOTH",
    "REAL", "SHOW", "MAKE", "TAKE", "GIVE", "KEEP",
    "SIMPLE", "GOAL", "GOING", "WAY", "ONE", "TWO",
    "FULL", "HALF", "OUT", "IN", "ON", "OFF",
    "THING", "THINGS", "NEVER", "ALWAYS", "JUST",
    "SHARE", "THINK", "KNOW", "FEEL", "USE", "USED",
    "WORK", "WORKING", "BUILD", "WANT", "NEED",
    "YEARS", "MONTHS", "WEEKS", "DAYS", "HOURS",
    "SINGLE", "BIG", "SMALL", "LONG", "SHORT",
    "FIRST", "LAST", "OLD", "OLDER", "LATEST",
    "PLAN", "PLANNING", "PROCESS", "TOOLS",
    "MINUTE", "SECOND", "PEOPLE", "PERSON",
    "THOUGHT", "NUMB", "AMAZING", "SPECIAL",
    "SHARING", "COMING", "SOON", "STARTED",
    "CURRENTLY", "ACTIVELY", "ALREADY",
    "YOUTUBE", "CANT", "DONT", "WONT", "ISNT",
    "LETS", "THATS", "WHATS", "HERES", "THERES",
    "VERY", "MUCH", "SUCH", "QUITE", "RATHER",
    "VERIFY", "VERIFIED", "VIEWS", "EDITED",
    "PINNED", "PHOTO", "WROTE",
    "REELS", "EDITS", "HERO",
    "PREMIUM", "REGISTRATION", "COMPLETE",
    "DATA", "ACCESS", "USERS", "PLAN",
    "MARKETS", "COMMUNITY", "INFORMATION",
    "CONTENT", "EDUCATION", "EDUCATIONAL",
}

PRICE_PATTERNS = {
    "entry": [
        re.compile(r"(?:entry|buy\s*(?:above|near|@)?|cmp|enter)\s*[:\-=]?\s*[₹]?\s*([\d,.]+)", re.I),
        re.compile(r"(?:above|around|near)\s+[₹]?\s*([\d,.]+)", re.I),
    ],
    "target": [
        re.compile(r"(?:target|tgt|t1|tp)\s*[:\-=]?\s*[₹]?\s*([\d,.]+)", re.I),
        re.compile(r"(?:target|tgt)\s*\d?\s*[:\-=]?\s*[₹]?\s*([\d,.]+)", re.I),
    ],
    "stop_loss": [
        re.compile(r"(?:stop\s*loss|stoploss|sl)\s*[:\-=]?\s*[₹]?\s*([\d,.]+)", re.I),
    ],
}


def _parse_price(text: str) -> float | None:
    cleaned = text.replace(",", "").strip()
    try:
        val = float(cleaned)
        return val if val > 0 else None
    except ValueError:
        return None


def _extract_symbol_from_tv(text: str) -> str | None:
    match = TV_SYMBOL_PATTERN.search(text)
    if match:
        return match.group(1).upper()
    match = TV_NSE_PATTERN.search(text)
    if match:
        return match.group(1).upper()
    return None


def _extract_symbol(text: str) -> str | None:
    matches = NSE_SYMBOL_PATTERN.findall(text)
    for m in matches:
        if m not in NOISE_WORDS and len(m) >= 2 and not m.isdigit():
            return m
    return None


def _extract_prices(text: str) -> dict:
    result = {}
    for key, patterns in PRICE_PATTERNS.items():
        for pat in patterns:
            match = pat.search(text)
            if match:
                val = _parse_price(match.group(1))
                if val:
                    result[key] = val
                    break
    return result


def parse_message(message_text: str) -> dict | None:
    if not message_text or len(message_text) < 15:
        return None

    text_upper = message_text.upper()

    tv_symbol = _extract_symbol_from_tv(message_text)
    if tv_symbol:
        is_analysis = any(kw in text_upper for kw in [
            "CONFLUENCE", "TRENDLINE", "DIVERGENCE", "STRUCTURE",
            "SWING TRADE", "PRICE ACTION", "PLANNING", "BREAK",
            "CHART", "ANALYSIS", "PATTERN", "SUPPORT", "RESISTANCE",
        ])
        return {
            "symbol": tv_symbol,
            "signal_type": "ANALYSIS",
            "entry_price": None,
            "target_price": None,
            "stop_loss": None,
            "raw_text": message_text.strip(),
            "source": "tradingview",
            "is_educational": is_analysis,
        }

    is_trade = any(kw in text_upper for kw in [
        "BUY", "ENTRY", "TARGET", "TGT", "SL", "STOP LOSS",
        "CMP", "BREAKOUT", "LONG",
    ])
    if is_trade:
        symbol = _extract_symbol(text_upper)
        if symbol:
            prices = _extract_prices(message_text)
            if prices.get("entry") or prices.get("target"):
                signal_type = "BUY"
                if any(kw in text_upper for kw in ["SELL", "SHORT"]):
                    signal_type = "SELL"
                return {
                    "symbol": symbol,
                    "signal_type": signal_type,
                    "entry_price": prices.get("entry"),
                    "target_price": prices.get("target"),
                    "stop_loss": prices.get("stop_loss"),
                    "raw_text": message_text.strip(),
                    "source": "direct",
                    "is_educational": False,
                }

    nse_explicit = re.search(r"NSE[:\s]+([A-Z][A-Z0-9]{2,19})\b", text_upper)
    hashtag_sym = re.search(r"#([A-Z][A-Z0-9]{2,19})\b", text_upper)
    mention_symbol = None
    if nse_explicit and nse_explicit.group(1) not in NOISE_WORDS:
        mention_symbol = nse_explicit.group(1)
    elif hashtag_sym and hashtag_sym.group(1) not in NOISE_WORDS:
        mention_symbol = hashtag_sym.group(1)

    if mention_symbol:
        return {
            "symbol": mention_symbol,
            "signal_type": "MENTION",
            "entry_price": None,
            "target_price": None,
            "stop_loss": None,
            "raw_text": message_text.strip(),
            "source": "mention",
            "is_educational": False,
        }

    return None


class ApoorvTracker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = DataStore(settings.db_path)
        self.store.init_apoorv_picks()

    def fetch_channel_messages(self, before_id: int | None = None) -> list[dict]:
        url = CHANNEL_URL
        if before_id:
            url = f"{CHANNEL_URL}?before={before_id}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to fetch channel: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        messages = []

        for widget in soup.select(".tgme_widget_message"):
            msg_id = widget.get("data-post", "")
            post_num = msg_id.split("/")[-1] if "/" in msg_id else msg_id

            text_el = widget.select_one(".tgme_widget_message_text")
            text = text_el.get_text(separator="\n").strip() if text_el else ""

            links = text_el.find_all("a") if text_el else []
            link_urls = [a.get("href", "") for a in links]
            for href in link_urls:
                if "tradingview.com" in href and href not in text:
                    text += f"\n{href}"

            time_el = widget.select_one("time")
            date_str = ""
            if time_el and time_el.get("datetime"):
                try:
                    dt = datetime.fromisoformat(time_el["datetime"].replace("Z", "+00:00"))
                    date_str = dt.strftime("%Y-%m-%d")
                except Exception:
                    date_str = datetime.now().strftime("%Y-%m-%d")

            if text:
                messages.append({
                    "message_id": post_num,
                    "date": date_str,
                    "text": text,
                })

        return messages

    def scan_new_messages(self) -> list[dict]:
        messages = self.fetch_channel_messages()
        if not messages:
            logger.info("No messages fetched from Apoorv's channel")
            return []

        new_picks = []
        seen_symbols = set()
        for msg in messages:
            if self.store.apoorv_pick_exists(msg["message_id"]):
                continue

            if "pinned" in msg["text"].lower()[:50]:
                continue

            parsed = parse_message(msg["text"])
            if not parsed:
                continue

            if parsed["symbol"] in seen_symbols:
                continue
            seen_symbols.add(parsed["symbol"])

            pick = {
                "message_id": msg["message_id"],
                "date": msg["date"],
                "message_text": msg["text"][:1000],
                "symbol": parsed["symbol"],
                "entry_price": parsed.get("entry_price"),
                "target_price": parsed.get("target_price"),
                "stop_loss": parsed.get("stop_loss"),
                "signal_type": parsed.get("signal_type", "ANALYSIS"),
            }

            pick_id = self.store.save_apoorv_pick(pick)
            pick["id"] = pick_id
            new_picks.append(pick)
            logger.info(
                f"New Apoorv {parsed['signal_type']}: {parsed['symbol']} "
                f"(msg {msg['message_id']}, source: {parsed.get('source', '?')})"
            )

        logger.info(f"Scanned channel: {len(new_picks)} new picks from {len(messages)} messages")
        return new_picks

    def update_pick_prices(self):
        from data.fetcher import DataFetcher
        fetcher = DataFetcher(self.settings)
        open_picks = self.store.get_apoorv_picks(status="OPEN")

        for pick in open_picks:
            symbol = pick["symbol"]
            nse_sym = f"{symbol}.NS"
            try:
                df = fetcher.fetch_ohlcv(nse_sym, period="5d")
                if df.empty:
                    continue
                current = float(df["close"].iloc[-1])
                day_high = float(df["high"].iloc[-1])
            except Exception as e:
                logger.error(f"Could not fetch {symbol}: {e}")
                continue

            entry = pick.get("entry_price")
            target = pick.get("target_price")
            stop_loss = pick.get("stop_loss")
            highest = max(pick.get("highest_price") or 0, day_high)

            self.store.update_apoorv_pick_price(pick["id"], current, highest)

            if not entry:
                continue

            exit_reason = None
            exit_price = None

            if target and current >= target:
                exit_reason = "TARGET_HIT"
                exit_price = target
            elif stop_loss and current <= stop_loss:
                exit_reason = "STOP_LOSS_HIT"
                exit_price = stop_loss
            else:
                pick_date = datetime.strptime(pick["date"], "%Y-%m-%d")
                if (datetime.now() - pick_date).days > 30:
                    exit_reason = "EXPIRED"
                    exit_price = current

            if exit_reason and entry:
                pnl_pct = round((exit_price - entry) / entry * 100, 2)
                self.store.close_apoorv_pick(pick["id"], exit_price, exit_reason, pnl_pct)
                logger.info(f"Closed Apoorv pick {symbol}: {exit_reason} ({pnl_pct:+.2f}%)")

    def get_performance(self) -> dict:
        closed = self.store.get_apoorv_picks(status="CLOSED")
        if not closed:
            open_picks = self.store.get_apoorv_picks(status="OPEN")
            return {
                "total_picks": len(open_picks), "closed": 0,
                "open": len(open_picks),
                "wins": 0, "losses": 0, "win_rate": 0,
                "avg_return": 0, "total_return": 0,
                "best_pick": None, "worst_pick": None,
                "cross_validated_pct": 0,
            }

        open_picks = self.store.get_apoorv_picks(status="OPEN")
        wins = [p for p in closed if (p.get("pnl_pct") or 0) > 0]
        losses = [p for p in closed if (p.get("pnl_pct") or 0) <= 0]
        returns = [p.get("pnl_pct", 0) for p in closed]
        validated = [p for p in closed if p.get("cross_validated")]

        best = max(closed, key=lambda x: x.get("pnl_pct") or 0, default=None)
        worst = min(closed, key=lambda x: x.get("pnl_pct") or 0, default=None)

        return {
            "total_picks": len(closed) + len(open_picks),
            "closed": len(closed),
            "open": len(open_picks),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
            "avg_return": round(sum(returns) / len(returns), 2) if returns else 0,
            "total_return": round(sum(returns), 2),
            "best_pick": best,
            "worst_pick": worst,
            "cross_validated_pct": round(len(validated) / len(closed) * 100, 1) if closed else 0,
        }
