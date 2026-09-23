import logging
from datetime import datetime, timedelta
from collections import defaultdict

import pandas as pd

from config.settings import Settings
from data.store import DataStore
from data.fetcher import DataFetcher
from data.preprocessor import Preprocessor
from strategy.manager import StrategyManager
from reflection.llm_advisor import LLMAdvisor

logger = logging.getLogger(__name__)

MAX_HOLD_DAYS = 20


class ScannerLearner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = DataStore(settings.db_path)
        self.fetcher = DataFetcher(settings)
        self.store.init_scanner()
        weights = self.store.get_latest_strategy_weights()
        self.strategy_mgr = StrategyManager(settings.strategies, weights or None)
        llm_model = settings.reflection.get("model", "claude-haiku-4-5")
        self.llm = LLMAdvisor(model=llm_model)

    def run_full_scan(self, on_progress=None) -> list[dict]:
        import yfinance as yf
        from data.advanced_analysis import full_analysis
        from data.nse_universe import fetch_all_nse_symbols

        symbols = fetch_all_nse_symbols()
        total = len(symbols)
        logger.info(f"Scanner: starting unified scan of {total} stocks (confluence + 5 strategies)")

        batch_size = 50
        results = []

        for i in range(0, total, batch_size):
            batch = symbols[i:i + batch_size]
            tickers_str = " ".join(batch)

            try:
                data = yf.download(tickers_str, period="1y", progress=False, threads=True, group_by="ticker")
            except Exception as e:
                logger.debug(f"Scanner batch download failed: {e}")
                if on_progress:
                    on_progress(min(i + batch_size, total), total, results)
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

                    # --- Confluence analysis ---
                    analysis = full_analysis(df)

                    # --- Run 5 strategies ---
                    strategy_hits = []
                    try:
                        df_ind = Preprocessor.add_indicators(df.copy())
                        fund = {}
                        try:
                            fund = self.fetcher.fetch_fundamentals(sym)
                        except Exception:
                            pass
                        picks = self.strategy_mgr.scan_stock(df_ind, fund)
                        for p in picks:
                            strategy_hits.append({
                                "name": p.strategy,
                                "score": round(p.score, 3),
                                "entry": p.entry_price,
                                "target": p.target_price,
                                "stop_loss": p.stop_loss,
                                "rr": p.risk_reward_ratio,
                                "reasoning": p.reasoning,
                            })
                    except Exception:
                        pass

                    # Skip if no confluence signal AND no strategy hit
                    if analysis["signal"] in ("NO_SIGNAL",) and not strategy_hits:
                        continue

                    mtf = analysis.get("multi_timeframe", {})
                    rs = analysis.get("relative_strength", {})
                    factors = ", ".join(analysis.get("confluence_points", [])[:3])

                    # Boost signal if strategies agree with confluence
                    signal = analysis["signal"]
                    if strategy_hits and signal == "NO_SIGNAL":
                        signal = "WATCH"
                    if strategy_hits and signal in ("WATCH", "BUY"):
                        if len(strategy_hits) >= 2:
                            signal = "STRONG_BUY"
                        elif signal == "WATCH":
                            signal = "BUY"

                    # Use best entry/target/SL from strategy if confluence didn't provide one
                    entry = analysis.get("entry")
                    target = analysis.get("target")
                    stop_loss = analysis.get("stop_loss")
                    if strategy_hits and (not entry or not target):
                        best = max(strategy_hits, key=lambda s: s["score"])
                        entry = entry or best["entry"]
                        target = target or best["target"]
                        stop_loss = stop_loss or best["stop_loss"]

                    strat_names = [s["name"].replace("_", " ").title() for s in strategy_hits]

                    results.append({
                        "symbol": sym,
                        "signal": signal,
                        "confluence_score": analysis["confluence_score"],
                        "max_confluence": analysis["max_confluence"],
                        "current_price": analysis.get("current_price"),
                        "entry": entry,
                        "target": target,
                        "stop_loss": stop_loss,
                        "weekly_trend": mtf.get("weekly_trend", "—"),
                        "rs_trend": rs.get("rs_trend", "—"),
                        "factors": factors,
                        "strategies": strat_names,
                        "strategy_count": len(strategy_hits),
                        "strategy_details": strategy_hits,
                    })
                except Exception:
                    continue

            if on_progress:
                on_progress(min(i + batch_size, total), total, results)

        results.sort(key=lambda r: (
            0 if r["signal"] == "STRONG_BUY" else 1 if r["signal"] == "BUY" else 2,
            -r["confluence_score"],
            -r.get("strategy_count", 0),
        ))

        # --- LLM validation on top BUY picks ---
        if self.llm.client:
            buy_picks = [r for r in results if r["signal"] in ("STRONG_BUY", "BUY")][:10]
            if buy_picks:
                logger.info(f"Scanner: running LLM validation on top {len(buy_picks)} BUY picks...")
                for r in buy_picks:
                    strat_text = "\n".join(
                        f"- {s['name']}: score={s['score']}, R:R=1:{s['rr']:.1f}, {s['reasoning']}"
                        for s in r.get("strategy_details", [])
                    ) or "None"

                    pick_data = {
                        "symbol": r["symbol"],
                        "current_price": r.get("current_price", 0),
                        "entry": r.get("entry", 0),
                        "target": r.get("target", 0),
                        "stop_loss": r.get("stop_loss", 0),
                        "signal": r["signal"],
                        "confluence_score": r.get("confluence_score", 0),
                        "max_confluence": r.get("max_confluence", 12),
                        "factors": r.get("factors", ""),
                        "weekly_trend": r.get("weekly_trend", ""),
                        "rs_trend": r.get("rs_trend", ""),
                        "strategy_signals": strat_text,
                        "fundamentals": "Not available",
                        "market_regime": "N/A",
                        "fii_sentiment": "N/A",
                        "sector": "",
                        "sector_strength": "N/A",
                    }

                    try:
                        result = self.llm.validate_pick(pick_data)
                        r["llm_verdict"] = result.get("verdict", "BUY")
                        r["llm_confidence"] = result.get("confidence", 0.5)
                        r["llm_reasoning"] = result.get("reasoning", "")
                        r["llm_risk_flags"] = result.get("risk_flags", [])

                        if r["llm_verdict"] == "SKIP":
                            r["signal"] = "WATCH"
                            logger.info(f"Scanner LLM downgraded {r['symbol']} to WATCH: {r['llm_reasoning'][:80]}")
                        elif r["llm_verdict"] == "STRONG_BUY" and r["signal"] == "BUY":
                            r["signal"] = "STRONG_BUY"
                            logger.info(f"Scanner LLM upgraded {r['symbol']} to STRONG_BUY")
                        else:
                            logger.info(f"Scanner LLM {r['llm_verdict']} {r['symbol']} (conf={r['llm_confidence']:.0%})")
                    except Exception as e:
                        logger.error(f"Scanner LLM validation failed for {r['symbol']}: {e}")

                results.sort(key=lambda r: (
                    0 if r["signal"] == "STRONG_BUY" else 1 if r["signal"] == "BUY" else 2 if r["signal"] == "WATCH" else 3,
                    -r["confluence_score"],
                    -r.get("strategy_count", 0),
                ))

        self.save_scan_results(results)
        buy_count = sum(1 for r in results if r["signal"] in ("STRONG_BUY", "BUY"))
        strat_count = sum(1 for r in results if r.get("strategy_count", 0) > 0)
        logger.info(f"Scanner: done. {len(results)} signals ({buy_count} BUY, {strat_count} with strategy hits) from {total} stocks.")
        return results

    def save_scan_results(self, results: list[dict]):
        today = datetime.now().strftime("%Y-%m-%d")
        saved = 0
        for r in results:
            if r.get("signal") not in ("STRONG_BUY", "BUY"):
                continue
            if not r.get("entry"):
                continue
            # Combine confluence factors + strategy names for tracking
            factors_parts = [r.get("factors", "")]
            for s in r.get("strategies", []):
                factors_parts.append(f"strategy:{s}")
            all_factors = ", ".join(f for f in factors_parts if f)

            self.store.save_scanner_pick({
                "scan_date": today,
                "symbol": r["symbol"],
                "signal": r["signal"],
                "confluence_score": r.get("confluence_score", 0),
                "entry_price": r["entry"],
                "target_price": r.get("target"),
                "stop_loss": r.get("stop_loss"),
                "confluence_factors": all_factors,
                "weekly_trend": r.get("weekly_trend", ""),
                "rs_trend": r.get("rs_trend", ""),
                "llm_verdict": r.get("llm_verdict", ""),
                "llm_reasoning": r.get("llm_reasoning", ""),
                "llm_confidence": r.get("llm_confidence", 0),
            })
            saved += 1
        logger.info(f"Scanner learner: saved {saved} BUY picks from scan")
        return saved

    def track_open_picks(self) -> dict:
        picks = self.store.get_open_scanner_picks()
        if not picks:
            return {"tracked": 0, "closed": 0}

        closed = 0
        today = datetime.now()

        for pick in picks:
            symbol = pick["symbol"]
            entry = pick["entry_price"]
            target = pick.get("target_price")
            stop_loss = pick.get("stop_loss")
            scan_date = datetime.strptime(pick["scan_date"], "%Y-%m-%d")
            days = (today - scan_date).days

            try:
                df = self.fetcher.fetch_ohlcv(symbol, period="1mo")
                if df.empty:
                    continue
                current = float(df["close"].iloc[-1])
                high_since = float(df["high"].max())
                low_since = float(df["low"].min())
            except Exception:
                continue

            max_price = max(pick.get("max_price") or entry, high_since)
            min_price = min(pick.get("min_price") or entry, low_since)
            self.store.update_scanner_pick_prices(pick["id"], max_price, min_price, days)

            outcome = None
            exit_price = current

            if target and current >= target:
                outcome = "TARGET_HIT"
                exit_price = target
            elif stop_loss and current <= stop_loss:
                outcome = "STOP_LOSS_HIT"
                exit_price = stop_loss
            elif days >= MAX_HOLD_DAYS:
                outcome = "EXPIRED"
                exit_price = current

            if outcome:
                pnl_pct = ((exit_price - entry) / entry) * 100
                self.store.close_scanner_pick(pick["id"], {
                    "outcome": outcome,
                    "exit_price": round(exit_price, 2),
                    "exit_date": today.strftime("%Y-%m-%d"),
                    "pnl_pct": round(pnl_pct, 2),
                    "max_price": round(max_price, 2),
                    "min_price": round(min_price, 2),
                    "days_tracked": days,
                })
                closed += 1
                logger.info(f"Scanner pick {symbol}: {outcome} pnl={pnl_pct:.1f}% days={days}")

        return {"tracked": len(picks), "closed": closed}

    def learn_from_results(self) -> dict:
        closed = self.store.get_closed_scanner_picks(500)
        if len(closed) < 10:
            logger.info(f"Scanner learner: only {len(closed)} closed picks, need 10+ to learn")
            return {"status": "insufficient_data", "closed_picks": len(closed)}

        factor_stats = defaultdict(lambda: {"returns": [], "wins": 0, "losses": 0, "total": 0})

        for pick in closed:
            factors_str = pick.get("confluence_factors", "") or ""
            factors = [f.strip() for f in factors_str.split(",") if f.strip()]
            pnl = pick.get("pnl_pct", 0) or 0
            is_win = pnl > 0

            for factor in factors:
                factor_key = self._normalize_factor(factor)
                factor_stats[factor_key]["returns"].append(pnl)
                factor_stats[factor_key]["total"] += 1
                if is_win:
                    factor_stats[factor_key]["wins"] += 1
                else:
                    factor_stats[factor_key]["losses"] += 1

            for attr, value in [("weekly_trend", pick.get("weekly_trend")),
                                ("rs_trend", pick.get("rs_trend"))]:
                if value and value != "—":
                    key = f"{attr}={value}"
                    factor_stats[key]["returns"].append(pnl)
                    factor_stats[key]["total"] += 1
                    if is_win:
                        factor_stats[key]["wins"] += 1
                    else:
                        factor_stats[key]["losses"] += 1

        results = {}
        for factor, stats in factor_stats.items():
            if stats["total"] < 3:
                continue
            avg_return = sum(stats["returns"]) / len(stats["returns"])
            win_rate = stats["wins"] / stats["total"] if stats["total"] > 0 else 0

            if win_rate >= 0.6:
                weight = min(2.0, 1.0 + (win_rate - 0.5))
            elif win_rate <= 0.35:
                weight = max(0.3, 1.0 - (0.5 - win_rate))
            else:
                weight = 1.0

            self.store.save_scanner_factor_score(factor, {
                "total": stats["total"],
                "wins": stats["wins"],
                "losses": stats["losses"],
                "avg_return": round(avg_return, 2),
                "win_rate": round(win_rate, 3),
                "weight": round(weight, 2),
            })
            results[factor] = {"win_rate": round(win_rate, 3), "avg_return": round(avg_return, 2), "weight": round(weight, 2)}

        total_closed = len(closed)
        total_wins = sum(1 for p in closed if (p.get("pnl_pct") or 0) > 0)
        overall_win_rate = total_wins / total_closed if total_closed > 0 else 0
        avg_pnl = sum(p.get("pnl_pct", 0) or 0 for p in closed) / total_closed

        if overall_win_rate > 0.55:
            new_min = max(1, int(self.store.get_scanner_config("min_confluence", "2")) - 1)
        elif overall_win_rate < 0.40:
            new_min = min(5, int(self.store.get_scanner_config("min_confluence", "2")) + 1)
        else:
            new_min = int(self.store.get_scanner_config("min_confluence", "2"))

        self.store.set_scanner_config("min_confluence", str(new_min))
        self.store.set_scanner_config("last_learn_date", datetime.now().strftime("%Y-%m-%d"))

        summary = {
            "status": "learned",
            "total_closed": total_closed,
            "overall_win_rate": round(overall_win_rate, 3),
            "avg_pnl": round(avg_pnl, 2),
            "min_confluence": new_min,
            "factor_count": len(results),
            "top_factors": sorted(results.items(), key=lambda x: x[1]["win_rate"], reverse=True)[:5],
            "worst_factors": sorted(results.items(), key=lambda x: x[1]["win_rate"])[:3],
        }
        logger.info(f"Scanner learner: win_rate={overall_win_rate:.1%} avg_pnl={avg_pnl:.1f}% "
                     f"min_confluence={new_min} factors={len(results)}")
        return summary

    def get_latest_scan_results(self) -> list[dict]:
        self.store.init_scanner()
        with self.store._conn() as conn:
            cursor = conn.execute(
                """SELECT symbol, signal, confluence_score, entry_price as entry,
                          target_price as target, stop_loss, confluence_factors as factors,
                          weekly_trend, rs_trend, scan_date,
                          llm_verdict, llm_reasoning, llm_confidence
                   FROM scanner_picks
                   WHERE scan_date = (SELECT MAX(scan_date) FROM scanner_picks)
                   ORDER BY confluence_score DESC"""
            )
            cols = [d[0] for d in cursor.description]
            rows = [dict(zip(cols, row)) for row in cursor.fetchall()]

        results = []
        for r in rows:
            results.append({
                "symbol": r["symbol"],
                "signal": r["signal"],
                "confluence_score": r.get("confluence_score", 0),
                "max_confluence": 12,
                "current_price": r.get("entry"),
                "entry": r.get("entry"),
                "target": r.get("target"),
                "stop_loss": r.get("stop_loss"),
                "weekly_trend": r.get("weekly_trend", "—"),
                "rs_trend": r.get("rs_trend", "—"),
                "factors": r.get("factors", ""),
                "scan_date": r.get("scan_date"),
                "llm_verdict": r.get("llm_verdict", ""),
                "llm_reasoning": r.get("llm_reasoning", ""),
                "llm_confidence": r.get("llm_confidence", 0),
            })
        return results

    def get_performance_summary(self) -> dict:
        closed = self.store.get_closed_scanner_picks(500)
        factor_scores = self.store.get_scanner_factor_scores()
        min_confluence = int(self.store.get_scanner_config("min_confluence", "2"))

        if not closed:
            return {"total_picks": 0, "min_confluence": min_confluence, "factor_scores": factor_scores}

        total = len(closed)
        wins = sum(1 for p in closed if (p.get("pnl_pct") or 0) > 0)
        losses = total - wins
        avg_pnl = sum(p.get("pnl_pct", 0) or 0 for p in closed) / total
        avg_win = sum(p["pnl_pct"] for p in closed if (p.get("pnl_pct") or 0) > 0) / wins if wins else 0
        avg_loss = sum(p["pnl_pct"] for p in closed if (p.get("pnl_pct") or 0) <= 0) / losses if losses else 0

        by_signal = defaultdict(lambda: {"total": 0, "wins": 0, "avg_pnl": 0, "returns": []})
        for p in closed:
            sig = p.get("signal", "UNKNOWN")
            by_signal[sig]["total"] += 1
            by_signal[sig]["returns"].append(p.get("pnl_pct", 0) or 0)
            if (p.get("pnl_pct") or 0) > 0:
                by_signal[sig]["wins"] += 1

        signal_stats = {}
        for sig, s in by_signal.items():
            signal_stats[sig] = {
                "total": s["total"],
                "win_rate": round(s["wins"] / s["total"], 3) if s["total"] > 0 else 0,
                "avg_pnl": round(sum(s["returns"]) / len(s["returns"]), 2),
            }

        return {
            "total_picks": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total, 3),
            "avg_pnl": round(avg_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "min_confluence": min_confluence,
            "signal_stats": signal_stats,
            "factor_scores": factor_scores[:10],
        }

    @staticmethod
    def _normalize_factor(factor: str) -> str:
        factor = factor.strip().lower()
        if factor.startswith("strategy:"):
            name = factor.replace("strategy:", "").strip().replace(" ", "_")
            return f"strategy_{name}"
        if "fib" in factor:
            return "near_fibonacci_level"
        if "demand" in factor:
            return "at_demand_zone"
        if "supply" in factor:
            return "at_supply_zone"
        if "support" in factor and "trendline" in factor:
            return "near_support_trendline"
        if "resistance" in factor and "trendline" in factor:
            return "near_resistance_trendline"
        if "ema" in factor and "200" in factor:
            return "near_200_ema"
        if "rsi" in factor and "oversold" in factor:
            return "rsi_oversold"
        if "rsi" in factor and "overbought" in factor:
            return "rsi_overbought"
        if "bullish" in factor and "candle" in factor:
            return "bullish_candle_pattern"
        if "bearish" in factor and "candle" in factor:
            return "bearish_candle_pattern"
        if "aligned" in factor:
            return "weekly_daily_aligned"
        if "outperform" in factor:
            return "outperforming_nifty"
        if "vwap" in factor:
            return "near_vwap"
        return factor[:50]
