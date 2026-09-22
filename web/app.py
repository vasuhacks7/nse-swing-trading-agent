import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import logging
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config.settings import Settings
from agent.alert_engine import AlertEngine
from agent.improvement_engine import ImprovementEngine
from data.market_context import get_market_regime, get_fii_dii_activity, is_market_open_today
from data.sector_strength import compute_sector_strength
from notifications.telegram_bot import send_daily_alerts, send_close_notification
from data.advanced_analysis import full_analysis
from agent.paper_trader import PaperTrader
from data.apoorv_tracker import ApoorvTracker
from agent.apoorv_learner import ApoorvLearner
from data.nse_universe import fetch_all_nse_symbols, _try_fetch_equity_list, _CACHE_FILE
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Indian Swing Trading Agent", version="2.0")

static_dir = Path(__file__).parent / "static"
templates_dir = Path(__file__).parent / "templates"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))

settings = Settings()
alert_engine = AlertEngine(settings)
improvement_engine = ImprovementEngine(settings)
paper_trader = PaperTrader(settings)
apoorv_tracker = ApoorvTracker(settings)
apoorv_learner = ApoorvLearner(settings)

_symbol_lookup: list[dict] = []


def _load_symbol_lookup() -> list[dict]:
    global _symbol_lookup
    if _symbol_lookup:
        return _symbol_lookup
    try:
        import io, requests, pandas as pd
        NSE_CSV_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
        headers = {"User-Agent": "Mozilla/5.0"}
        if _CACHE_FILE.exists():
            cached_df = pd.read_csv(_CACHE_FILE)
            symbols = cached_df["symbol"].str.replace(".NS", "", regex=False).tolist()
            _symbol_lookup = [{"symbol": s, "name": s} for s in symbols]
            return _symbol_lookup
        resp = requests.get(NSE_CSV_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        name_col = None
        for c in df.columns:
            if "name" in c.lower() or "company" in c.lower():
                name_col = c
                break
        sym_col = None
        for c in df.columns:
            if c.strip().lower() in ("symbol", "ticker"):
                sym_col = c
                break
        if not sym_col:
            sym_col = df.columns[0]
        if name_col:
            _symbol_lookup = [
                {"symbol": row[sym_col].strip(), "name": row[name_col].strip()}
                for _, row in df.iterrows() if pd.notna(row[sym_col])
            ]
        else:
            _symbol_lookup = [
                {"symbol": row[sym_col].strip(), "name": row[sym_col].strip()}
                for _, row in df.iterrows() if pd.notna(row[sym_col])
            ]
    except Exception as e:
        logger.warning(f"Symbol lookup load failed: {e}")
        _symbol_lookup = [{"symbol": s.replace(".NS", ""), "name": s.replace(".NS", "")}
                          for s in (fetch_all_nse_symbols() or [])]
    return _symbol_lookup


def _render(request: Request, template: str, context: dict):
    return templates.TemplateResponse(request, template, context)


def _sanitize(obj):
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj) if not np.isnan(obj) else None
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    market_status = is_market_open_today()
    regime = get_market_regime()
    flows = get_fii_dii_activity()
    perf = alert_engine.get_performance_summary()

    today = datetime.now().strftime("%Y-%m-%d")
    today_alerts = alert_engine.store.get_alerts_for_date(today)
    alerts_list = today_alerts.to_dict("records") if not today_alerts.empty else []

    open_positions = alert_engine.store.get_open_alerts()
    open_list = open_positions.to_dict("records") if not open_positions.empty else []

    return _render(request, "dashboard.html", {
        "now": datetime.now(),
        "market_status": market_status,
        "regime": regime,
        "flows": flows,
        "perf": perf,
        "alerts": alerts_list,
        "open_positions": open_list,
    })


@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    alerts = alert_engine.get_alert_history(200)
    alerts_list = alerts.to_dict("records") if not alerts.empty else []

    closed = [a for a in alerts_list if a.get("status") == "CLOSED"]
    return _render(request, "history.html", {
        "alerts": alerts_list,
        "closed_trades": closed,
    })


@app.get("/scoreboard", response_class=HTMLResponse)
async def scoreboard(request: Request):
    raw_scores = improvement_engine.compute_strategy_scores()
    if isinstance(raw_scores, dict):
        scores = []
        for name, data in raw_scores.items():
            entry = data if isinstance(data, dict) else {"strategy": name}
            entry.setdefault("strategy", name)
            entry.setdefault("total_trades", entry.get("total_alerts", 0))
            entry.setdefault("wins", entry.get("winning_alerts", 0))
            entry.setdefault("losses", entry.get("losing_alerts", 0))
            entry.setdefault("win_rate", 0)
            entry.setdefault("avg_return", entry.get("avg_return_pct", 0))
            entry.setdefault("profit_factor", 0)
            entry.setdefault("weight", entry.get("current_weight", 1.0))
            scores.append(entry)
    else:
        scores = raw_scores
    return _render(request, "scoreboard.html", {
        "scores": scores,
    })


@app.get("/analysis", response_class=HTMLResponse)
async def analysis(request: Request, symbol: str = "", interval: str = "D"):
    interval = interval.upper() if interval else "D"
    if interval not in ("D", "W", "M"):
        interval = "D"

    if not symbol:
        return _render(request, "analysis.html", {
            "symbol": None, "analysis": None, "interval": interval,
            "chart_data": [], "error": None,
        })

    symbol_clean = symbol.strip().upper().replace(".NS", "")
    try:
        result = paper_trader.analyze_and_trade(symbol_clean)
        chart_data = result.pop("ohlcv_json", []) or []
        return _render(request, "analysis.html", {
            "symbol": symbol_clean,
            "analysis": result,
            "interval": interval,
            "chart_data": chart_data,
            "error": None,
        })
    except Exception as e:
        logger.error(f"Analysis failed for {symbol_clean}: {e}", exc_info=True)
        return _render(request, "analysis.html", {
            "symbol": symbol_clean,
            "analysis": None,
            "interval": interval,
            "chart_data": [],
            "error": f"Could not analyze {symbol_clean}: {str(e)}",
        })


@app.get("/paper-trading", response_class=HTMLResponse)
async def paper_trading_page(request: Request):
    portfolio = paper_trader.get_portfolio()
    closed = paper_trader.store.get_closed_paper_trades(100)
    return _render(request, "paper_trading.html", {
        "portfolio": portfolio,
        "closed_trades": closed,
    })


@app.get("/api/analyze/{symbol}")
async def api_analyze(symbol: str):
    symbol_clean = symbol.strip().upper().replace(".NS", "")
    try:
        result = paper_trader.analyze_and_trade(symbol_clean)
        result.pop("ohlcv_json", None)
        return _sanitize(result)
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/paper-portfolio")
async def api_paper_portfolio():
    return paper_trader.get_portfolio()


@app.get("/api/paper-track")
async def api_paper_track():
    closed = paper_trader.track_positions()
    return {"closed": closed}


@app.get("/premium-picks", response_class=HTMLResponse)
async def premium_picks_page(request: Request):
    picks = apoorv_tracker.store.get_apoorv_picks(limit=50)
    open_picks = [p for p in picks if p.get("status") == "OPEN"]
    closed_picks = [p for p in picks if p.get("status") == "CLOSED"]
    perf = apoorv_tracker.get_performance()
    suggestions = apoorv_learner.get_suggestions()
    patterns = apoorv_learner.analyze_patterns()

    return _render(request, "apoorv.html", {
        "picks": picks,
        "open_picks": open_picks,
        "closed_picks": closed_picks,
        "performance": perf,
        "suggestions": suggestions,
        "patterns": patterns,
    })


@app.get("/apoorv", response_class=HTMLResponse)
async def apoorv_redirect():
    return RedirectResponse(url="/premium-picks", status_code=301)


@app.get("/api/apoorv/scan")
async def api_apoorv_scan():
    new_picks = apoorv_tracker.scan_new_messages()
    validations = apoorv_learner.cross_validate_new_picks()
    return _sanitize({
        "new_picks": len(new_picks),
        "picks": new_picks,
        "validations": validations,
    })


@app.get("/api/apoorv/picks")
async def api_apoorv_picks(status: str | None = None):
    picks = apoorv_tracker.store.get_apoorv_picks(status=status)
    return _sanitize({"picks": picks})


@app.get("/api/apoorv/track")
async def api_apoorv_track():
    apoorv_tracker.update_pick_prices()
    return {"status": "ok"}


@app.get("/api/apoorv/suggestions")
async def api_apoorv_suggestions():
    suggestions = apoorv_learner.get_suggestions()
    return _sanitize({"suggestions": suggestions})


@app.get("/api/apoorv/learn")
async def api_apoorv_learn():
    report = apoorv_learner.generate_learning_report()
    return _sanitize(report)


@app.get("/generate", response_class=HTMLResponse)
async def generate_and_redirect():
    regime = get_market_regime()
    flows = get_fii_dii_activity()
    alerts = alert_engine.generate_daily_alerts()
    if alerts:
        send_daily_alerts(alerts, regime, flows)
    return RedirectResponse(url="/", status_code=303)


# --- JSON API endpoints ---

@app.get("/api/alerts")
async def api_alerts():
    today = datetime.now().strftime("%Y-%m-%d")
    alerts = alert_engine.store.get_alerts_for_date(today)
    return {"date": today, "alerts": alerts.to_dict("records") if not alerts.empty else []}


@app.get("/api/generate")
async def api_generate():
    regime = get_market_regime()
    flows = get_fii_dii_activity()
    alerts = alert_engine.generate_daily_alerts()
    if alerts:
        send_daily_alerts(alerts, regime, flows)
    return {"generated": len(alerts), "alerts": alerts}


@app.get("/api/track")
async def api_track():
    closed = alert_engine.check_and_close_alerts()
    if closed:
        send_close_notification(closed)
    return {"closed": closed}


@app.get("/api/market")
async def api_market():
    return {
        "market_open": is_market_open_today(),
        "regime": get_market_regime(),
        "fii_dii": get_fii_dii_activity(),
    }


@app.get("/api/performance")
async def api_performance():
    return alert_engine.get_performance_summary()


@app.get("/api/scoreboard")
async def api_scoreboard():
    return improvement_engine.compute_strategy_scores()


@app.get("/api/open-positions")
async def api_open_positions():
    open_alerts = alert_engine.store.get_open_alerts()
    return {"positions": open_alerts.to_dict("records") if not open_alerts.empty else []}


@app.get("/api/search-symbols")
async def api_search_symbols(q: str = ""):
    q = q.strip().upper()
    if len(q) < 1:
        return []
    lookup = _load_symbol_lookup()
    results = []
    for item in lookup:
        if q in item["symbol"].upper() or q in item["name"].upper():
            results.append(item)
            if len(results) >= 15:
                break
    return results


@app.get("/scanner", response_class=HTMLResponse)
async def scanner_page(request: Request):
    return _render(request, "scanner.html", {})


import threading

_scan_state = {"running": False, "progress": 0, "total": 0, "results": [], "done": False}


def _run_full_scan():
    import yfinance as yf
    from data.advanced_analysis import full_analysis
    from data.preprocessor import Preprocessor

    _scan_state["running"] = True
    _scan_state["done"] = False
    _scan_state["results"] = []
    _scan_state["progress"] = 0

    symbols = fetch_all_nse_symbols()
    _scan_state["total"] = len(symbols)
    logger.info(f"Scanner: starting full scan of {len(symbols)} stocks")

    batch_size = 50
    results = []

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        tickers_str = " ".join(batch)

        try:
            data = yf.download(tickers_str, period="1y", progress=False, threads=True, group_by="ticker")
        except Exception as e:
            logger.debug(f"Scanner batch download failed: {e}")
            _scan_state["progress"] = min(i + batch_size, len(symbols))
            continue

        for sym in batch:
            try:
                if len(batch) == 1:
                    df = data.copy()
                else:
                    if sym not in data.columns.get_level_values(0):
                        continue
                    df = data[sym].copy()

                df = df.dropna(subset=["Close"])
                if len(df) < 60:
                    continue

                df.index = pd.to_datetime(df.index).tz_localize(None)
                df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
                df = df[["open", "high", "low", "close", "volume"]]
                df["symbol"] = sym

                analysis = full_analysis(df)

                if analysis["signal"] in ("NO_SIGNAL",):
                    continue

                mtf = analysis.get("multi_timeframe", {})
                rs = analysis.get("relative_strength", {})
                factors = ", ".join(analysis.get("confluence_points", [])[:3])

                results.append({
                    "symbol": sym,
                    "signal": analysis["signal"],
                    "confluence_score": analysis["confluence_score"],
                    "max_confluence": analysis["max_confluence"],
                    "current_price": analysis.get("current_price"),
                    "entry": analysis.get("entry"),
                    "target": analysis.get("target"),
                    "stop_loss": analysis.get("stop_loss"),
                    "weekly_trend": mtf.get("weekly_trend", "—"),
                    "rs_trend": rs.get("rs_trend", "—"),
                    "factors": factors,
                })
            except Exception:
                continue

        _scan_state["progress"] = min(i + batch_size, len(symbols))
        _scan_state["results"] = sorted(results, key=lambda r: (
            0 if r["signal"] == "STRONG_BUY" else 1 if r["signal"] == "BUY" else 2,
            -r["confluence_score"]
        ))

    _scan_state["results"] = sorted(results, key=lambda r: (
        0 if r["signal"] == "STRONG_BUY" else 1 if r["signal"] == "BUY" else 2,
        -r["confluence_score"]
    ))
    _scan_state["running"] = False
    _scan_state["done"] = True
    logger.info(f"Scanner: done. {len(results)} signals found from {len(symbols)} stocks.")


@app.get("/api/scanner")
async def api_scanner():
    if not _scan_state["running"] and not _scan_state["done"]:
        thread = threading.Thread(target=_run_full_scan, daemon=True)
        thread.start()
        return {"status": "started", "results": [], "scanned": 0, "total": 0}

    return _sanitize({
        "status": "done" if _scan_state["done"] else "scanning",
        "results": _scan_state["results"],
        "scanned": _scan_state["progress"],
        "total": _scan_state["total"],
    })


@app.get("/api/scanner/reset")
async def api_scanner_reset():
    _scan_state["running"] = False
    _scan_state["done"] = False
    _scan_state["results"] = []
    _scan_state["progress"] = 0
    _scan_state["total"] = 0
    return {"status": "reset"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
