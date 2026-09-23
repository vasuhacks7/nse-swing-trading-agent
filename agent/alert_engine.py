import logging
from datetime import datetime, timedelta

import pandas as pd

from config.settings import Settings
from data.fetcher import DataFetcher
from data.store import DataStore
from data.preprocessor import Preprocessor
from data.market_context import is_market_open_today, get_market_regime, get_fii_dii_activity
from data.earnings_calendar import has_upcoming_earnings
from data.circuit_check import check_circuit_status
from data.sector_strength import compute_sector_strength, get_sector_bonus
from data.global_context import get_global_context
from data.market_breadth import get_market_breadth
from data.news_sentiment import check_news_sentiment
from data.portfolio_risk import check_portfolio_risk
from data.intraday_check import check_intraday_entry
from strategy.manager import StrategyManager
from reflection.llm_advisor import LLMAdvisor

logger = logging.getLogger(__name__)


class AlertEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.fetcher = DataFetcher(settings)
        self.store = DataStore(settings.db_path)

        weights = self.store.get_latest_strategy_weights()
        self.strategy_mgr = StrategyManager(settings.strategies, weights or None)

        llm_model = settings.reflection.get("model", "claude-haiku-4-5")
        self.llm = LLMAdvisor(model=llm_model)

    def generate_daily_alerts(self) -> list[dict]:
        today = datetime.now().strftime("%Y-%m-%d")

        existing = self.store.get_alerts_for_date(today)
        if not existing.empty:
            logger.info(f"Alerts already generated for {today}, returning existing")
            return existing.to_dict("records")

        # --- CHECK 1: Is market open? ---
        market_status = is_market_open_today()
        if not market_status["open"]:
            logger.info(f"Market closed today: {market_status['reason']}. No alerts.")
            return []
        logger.info(f"Market status: {market_status['reason']}")

        # --- CHECK 2: Market regime ---
        regime = get_market_regime()
        regime_type = regime.get("regime", "UNKNOWN")
        logger.info(f"Market regime: {regime_type} | Nifty RSI: {regime.get('nifty_rsi', '?')} | "
                     f"5d return: {regime.get('return_5d', '?')}% | "
                     f"Volatility: {regime.get('volatility', '?')}%")

        min_score = self.settings.alerts.get("min_signal_score", 0.65)
        no_trade_threshold = self.settings.alerts.get("no_trade_threshold", 0.70)

        if regime_type == "BEARISH":
            min_score += 0.10
            no_trade_threshold += 0.10
            logger.info(f"BEARISH regime: raised quality bar (min_score={min_score:.2f}, "
                        f"no_trade={no_trade_threshold:.2f})")
        elif regime.get("volatility_regime") == "HIGH_VOLATILITY":
            min_score += 0.05
            logger.info(f"High volatility: raised min_score to {min_score:.2f}")

        # --- CHECK 3: FII/DII activity ---
        flows = get_fii_dii_activity()
        fii_sentiment = flows.get("fii_sentiment", "UNKNOWN")
        logger.info(f"Institutional flows: FII={fii_sentiment} | "
                     f"FII net: {flows.get('fii_net_cr', '?')} Cr | "
                     f"DII net: {flows.get('dii_net_cr', '?')} Cr")

        if fii_sentiment == "HEAVY_SELLING":
            min_score += 0.05
            logger.info(f"FII heavy selling: raised min_score to {min_score:.2f}")

        # --- CHECK 3b: Global context (US futures, DXY, crude) ---
        global_ctx = get_global_context()
        global_sentiment = global_ctx.get("overall_sentiment", "NEUTRAL")
        global_adj = global_ctx.get("score_adjustment", 0)
        if global_adj != 0:
            min_score += global_adj
            no_trade_threshold += global_adj
            logger.info(f"Global context: {global_sentiment} — "
                        f"adj min_score to {min_score:.2f}")
        for name, detail in global_ctx.get("details", {}).items():
            logger.info(f"  {name}: {detail}")

        # --- CHECK 3c: Market breadth ---
        breadth = get_market_breadth()
        breadth_signal = breadth.get("breadth_signal", "NEUTRAL")
        breadth_adj = breadth.get("score_adjustment", 0)
        if breadth_adj != 0:
            min_score += breadth_adj
            no_trade_threshold += breadth_adj
            logger.info(f"Breadth: {breadth_signal} — "
                        f"adj min_score to {min_score:.2f}")
        logger.info(f"Breadth: {breadth.get('above_200ema_pct', 0)}% >200EMA, "
                     f"A/D={breadth.get('ad_ratio', '?')}, "
                     f"Highs={breadth.get('new_20d_highs', 0)} / "
                     f"Lows={breadth.get('new_20d_lows', 0)}")

        # --- FETCH & PREPARE DATA ---
        logger.info("Fetching universe data...")
        universe_data = self._fetch_and_prepare()

        # --- CHECK 6: Sector strength ---
        sector_scores = compute_sector_strength(universe_data)
        strong_sectors = [s for s, d in sector_scores.items() if d.get("momentum") == "STRONG"]
        weak_sectors = [s for s, d in sector_scores.items() if d.get("momentum") == "WEAK"]
        if strong_sectors:
            logger.info(f"Strong sectors: {', '.join(strong_sectors)}")
        if weak_sectors:
            logger.info(f"Weak sectors: {', '.join(weak_sectors)}")

        # --- SCAN STRATEGIES ---
        logger.info("Scanning all strategies across universe...")
        max_alerts = self.settings.alerts.get("max_daily_alerts", 2)
        min_rr = self.settings.alerts.get("min_risk_reward", 2.0)

        picks = self.strategy_mgr.get_top_picks(universe_data, max_alerts * 3, min_score)

        # Apply sector bonus/penalty to scores
        for pick in picks:
            fund = universe_data.get(pick.symbol, {}).get("fundamentals", {})
            bonus = get_sector_bonus(pick.symbol, fund, sector_scores)
            if bonus != 0:
                pick.score = max(0, min(1.0, pick.score + bonus))

        picks.sort(key=lambda p: p.score, reverse=True)

        # --- FILTER: R:R ratio ---
        picks = [p for p in picks if p.risk_reward_ratio >= min_rr]

        # --- CHECK 4: Circuit limits ---
        filtered_picks = []
        for pick in picks:
            ohlcv = universe_data.get(pick.symbol, {}).get("ohlcv")
            if ohlcv is not None:
                circuit = check_circuit_status(ohlcv)
                if circuit.get("at_circuit"):
                    logger.info(f"SKIP {pick.symbol}: {circuit['warning']}")
                    continue
                if circuit.get("near_circuit") and circuit.get("type") == "NEAR_UPPER":
                    logger.info(f"SKIP {pick.symbol}: {circuit['warning']}")
                    continue
            filtered_picks.append(pick)
        picks = filtered_picks

        # --- CHECK 5: Earnings calendar ---
        final_picks = []
        for pick in picks:
            earnings = has_upcoming_earnings(pick.symbol, days_ahead=5)
            if earnings["has_earnings"]:
                logger.info(f"SKIP {pick.symbol}: {earnings['warning']}")
                continue
            final_picks.append(pick)
        picks = final_picks

        # --- CHECK 7: News sentiment filter ---
        news_filtered = []
        for pick in picks:
            news = check_news_sentiment(pick.symbol)
            if news["should_skip"]:
                logger.info(f"SKIP {pick.symbol}: news sentiment {news['sentiment']} — "
                            f"{news['negative_headlines'][:2]}")
                continue
            pick._news_sentiment = news["sentiment"]
            news_filtered.append(pick)
        picks = news_filtered

        # --- CHECK 8: Portfolio risk (sector concentration + correlation) ---
        open_alerts = self.store.get_open_alerts()
        open_list = open_alerts.to_dict("records") if not open_alerts.empty else []
        picks = check_portfolio_risk(picks, open_list, universe_data)

        # --- NO-TRADE QUALITY GATE ---
        if picks and picks[0].score < no_trade_threshold:
            logger.info(f"Best pick score {picks[0].score:.3f} below no-trade threshold "
                        f"{no_trade_threshold:.2f}. Skipping today — no quality setups.")
            return []

        picks = picks[:max_alerts]

        # --- LLM VALIDATION ---
        if picks and self.llm.client:
            logger.info(f"Running LLM validation on {len(picks)} candidate(s)...")
            validated = []
            for pick in picks:
                ud = universe_data.get(pick.symbol, {})
                ohlcv = ud.get("ohlcv")
                fund = ud.get("fundamentals", {})

                indicators = {}
                if ohlcv is not None and not ohlcv.empty:
                    last = ohlcv.iloc[-1]
                    indicators = {
                        "rsi": round(last.get("rsi", 0), 1),
                        "macd_hist": round(last.get("macd_hist", 0), 3),
                        "adx": round(last.get("adx", 0), 1),
                        "bb_pct": round(last.get("bb_pct", 0), 2),
                        "volume_ratio": round(last.get("volume", 0) / ohlcv["volume"].tail(20).mean(), 1) if ohlcv["volume"].tail(20).mean() > 0 else 1.0,
                        "ema_20": round(last.get("ema_20", 0), 2),
                        "ema_50": round(last.get("ema_50", 0), 2),
                        "ema_200": round(last.get("ema_200", 0), 2),
                    }

                pick_data = {
                    "symbol": pick.symbol,
                    "current_price": pick.entry_price,
                    "entry": pick.entry_price,
                    "target": pick.target_price,
                    "stop_loss": pick.stop_loss,
                    "signal": pick.action,
                    **indicators,
                    "confluence_score": "N/A",
                    "max_confluence": 12,
                    "factors": pick.technical_summary or "",
                    "weekly_trend": "N/A",
                    "rs_trend": "N/A",
                    "strategy_signals": f"{pick.strategy}: score={pick.score:.3f}, R:R=1:{pick.risk_reward_ratio:.1f}\n{pick.reasoning}",
                    "fundamentals": pick.fundamental_summary or f"P/E={fund.get('pe_ratio', '?')}, ROE={fund.get('roe', '?')}, D/E={fund.get('debt_to_equity', '?')}",
                    "market_regime": regime_type,
                    "fii_sentiment": fii_sentiment,
                    "sector": fund.get("sector", ""),
                    "sector_strength": "Strong" if fund.get("sector", "") in strong_sectors else "Weak" if fund.get("sector", "") in weak_sectors else "Neutral",
                }

                result = self.llm.validate_pick(pick_data)
                verdict = result.get("verdict", "BUY")
                confidence = result.get("confidence", 0.5)
                reasoning = result.get("reasoning", "")

                if verdict == "SKIP":
                    logger.info(f"LLM SKIP {pick.symbol}: {reasoning}")
                    continue

                pick._llm_verdict = verdict
                pick._llm_confidence = confidence
                pick._llm_reasoning = reasoning
                pick._llm_risk_flags = result.get("risk_flags", [])

                if verdict == "STRONG_BUY" and confidence >= 0.7:
                    pick.score = min(1.0, pick.score + 0.05)

                validated.append(pick)
                logger.info(f"LLM {verdict} {pick.symbol} (confidence={confidence:.0%}): {reasoning[:100]}")

            picks = validated
            if not picks:
                logger.info("All candidates rejected by LLM. No alerts today.")
                return []

        # --- CHECK 9: Intraday entry refinement (15-min data) ---
        intraday_filtered = []
        for pick in picks:
            intra = check_intraday_entry(pick.symbol, pick.entry_price)
            if not intra["favorable"]:
                logger.info(f"SKIP {pick.symbol}: intraday unfavorable — {intra['reason']}")
                continue
            if intra["adjusted_entry"] != pick.entry_price:
                logger.info(f"ENTRY ADJ {pick.symbol}: {pick.entry_price:.2f} -> "
                            f"{intra['adjusted_entry']:.2f} ({intra['reason']})")
                pick.entry_price = intra["adjusted_entry"]
            intraday_filtered.append(pick)
        picks = intraday_filtered

        # --- POSITION SIZING ---
        streak = self.store.get_recent_streak()
        qty_pct = self._compute_position_size(streak)

        if regime_type == "BEARISH":
            qty_pct = min(qty_pct, 0.75)
            logger.info(f"Bearish regime: capped position size at {qty_pct * 100:.0f}%")

        ps_cfg = self.settings.risk.get("position_sizing", {})
        installments = ps_cfg.get("installments", 2)
        first_deploy = ps_cfg.get("first_deploy_pct", 0.50)

        # --- GENERATE ALERTS ---
        alerts = []
        for pick in picks:
            fund = universe_data.get(pick.symbol, {}).get("fundamentals", {})
            raw_sector = fund.get("sector", "")

            llm_reasoning = getattr(pick, "_llm_reasoning", "")
            llm_verdict = getattr(pick, "_llm_verdict", "")
            llm_flags = getattr(pick, "_llm_risk_flags", [])
            full_reasoning = pick.reasoning
            if llm_reasoning:
                full_reasoning += f"\n\nLLM ({llm_verdict}): {llm_reasoning}"
                if llm_flags:
                    full_reasoning += f"\nRisk flags: {', '.join(llm_flags)}"

            alert = {
                "date": today,
                "symbol": pick.symbol,
                "strategy": pick.strategy,
                "action": pick.action,
                "entry_price": pick.entry_price,
                "target_price": pick.target_price,
                "stop_loss": pick.stop_loss,
                "signal_score": round(pick.score, 3),
                "reasoning": full_reasoning,
                "technical_summary": pick.technical_summary,
                "fundamental_summary": pick.fundamental_summary,
                "risk_reward_ratio": pick.risk_reward_ratio,
                "installment": 1,
                "qty_pct": round(qty_pct * first_deploy, 2) if installments > 1 else qty_pct,
            }
            alert_id = self.store.save_alert(alert)
            alert["id"] = alert_id
            alert["market_regime"] = regime_type
            alert["fii_sentiment"] = fii_sentiment
            alert["sector"] = raw_sector
            alerts.append(alert)

            rr_str = f"1:{pick.risk_reward_ratio:.1f}"
            deploy_str = f"{alert['qty_pct'] * 100:.0f}%"
            logger.info(
                f"ALERT: {pick.action} {pick.symbol} @ Rs.{pick.entry_price:.2f} "
                f"[{pick.strategy}] score={pick.score:.3f} R:R={rr_str} "
                f"deploy={deploy_str} regime={regime_type}"
            )

        if not alerts:
            logger.info("No stocks met all criteria today. No alerts generated.")
        else:
            if streak["streak_type"] == "loss" and streak["streak_len"] >= 2:
                logger.info(f"NOTE: On a {streak['streak_len']}-trade losing streak. "
                            f"Position size reduced to {qty_pct * 100:.0f}%.")
            elif streak["streak_type"] == "win" and streak["streak_len"] >= 5:
                logger.info(f"NOTE: On a {streak['streak_len']}-trade winning streak. "
                            f"Position size scaled up to {qty_pct * 100:.0f}%.")

        return alerts

    def get_market_snapshot(self) -> dict:
        regime = get_market_regime()
        flows = get_fii_dii_activity()
        market_status = is_market_open_today()
        global_ctx = get_global_context()
        breadth = get_market_breadth()
        return {
            "market_open": market_status,
            "regime": regime,
            "fii_dii": flows,
            "global_context": global_ctx,
            "breadth": breadth,
        }

    def check_and_close_alerts(self):
        open_alerts = self.store.get_open_alerts()
        if open_alerts.empty:
            return []

        closed = []
        today = datetime.now().strftime("%Y-%m-%d")
        tsl_cfg = self.settings.risk.get("trailing_stop", {})
        tsl_enabled = tsl_cfg.get("enabled", True)
        tsl_activate_rr = tsl_cfg.get("activate_after_rr", 1.0)
        tsl_trail_pct = tsl_cfg.get("trail_pct", 0.03)

        for _, alert in open_alerts.iterrows():
            symbol = alert["symbol"]
            try:
                df = self.fetcher.fetch_ohlcv(symbol, period="5d")
                current_price = df["close"].iloc[-1]
                day_high = df["high"].iloc[-1]
            except Exception as e:
                logger.error(f"Could not fetch price for {symbol}: {e}")
                continue

            entry_price = alert["entry_price"]
            target = alert["target_price"]
            original_stop = alert["stop_loss"]
            trailing_stop = alert.get("trailing_stop") or original_stop
            highest_price = alert.get("highest_price") or entry_price
            alert_date = pd.Timestamp(alert["date"])
            holding_days = (pd.Timestamp(today) - alert_date).days
            max_hold = self.settings.alerts.get("holding_period_days", 10)

            if day_high > highest_price:
                highest_price = day_high

            partial_booked = bool(alert.get("partial_booked"))

            if tsl_enabled and original_stop and entry_price:
                risk_per_share = entry_price - original_stop
                if risk_per_share > 0:
                    profit = highest_price - entry_price
                    r_multiple = profit / risk_per_share
                    if r_multiple >= tsl_activate_rr:
                        new_tsl = highest_price * (1 - tsl_trail_pct)
                        if new_tsl > trailing_stop:
                            trailing_stop = round(new_tsl, 2)
                            logger.info(
                                f"TRAIL: {symbol} highest={highest_price:.2f} "
                                f"trailing SL raised to Rs.{trailing_stop:.2f} "
                                f"({r_multiple:.1f}R profit)"
                            )

                        if not partial_booked and r_multiple >= tsl_activate_rr:
                            self.store.mark_partial_booked(alert["id"], current_price)
                            partial_booked = True
                            partial_pnl = ((current_price - entry_price) / entry_price) * 100
                            logger.info(
                                f"PARTIAL BOOK: {symbol} booked 50% @ Rs.{current_price:.2f} "
                                f"({partial_pnl:+.2f}%, {r_multiple:.1f}R). Trailing rest."
                            )

            self.store.update_trailing_stop(alert["id"], trailing_stop, highest_price)
            active_stop = max(trailing_stop, original_stop) if trailing_stop else original_stop

            exit_reason = None
            if target and current_price >= target:
                exit_reason = "TARGET_HIT"
            elif active_stop and current_price <= active_stop:
                if trailing_stop and trailing_stop > original_stop:
                    exit_reason = "TRAILING_STOP_HIT"
                else:
                    exit_reason = "STOP_LOSS_HIT"
            elif holding_days >= max_hold:
                exit_reason = "MAX_HOLDING_PERIOD"

            if exit_reason:
                self.store.close_alert(alert["id"], current_price, today, exit_reason)
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
                logger.info(f"CLOSED: {symbol} @ Rs.{current_price:.2f} | "
                            f"P&L: {pnl_pct:+.2f}% | Reason: {exit_reason} | "
                            f"Held: {holding_days}d")
                closed.append({
                    "symbol": symbol, "exit_price": current_price,
                    "pnl_pct": pnl_pct, "exit_reason": exit_reason,
                    "holding_days": holding_days,
                })

        return closed

    def get_alert_history(self, limit: int = 100) -> pd.DataFrame:
        return self.store.get_all_alerts(limit)

    def get_performance_summary(self) -> dict:
        closed = self.store.get_closed_alerts(limit=500)
        if closed.empty:
            return {"total_trades": 0}

        wins = closed[closed["pnl_pct"] > 0]
        losses = closed[closed["pnl_pct"] <= 0]
        streak = self.store.get_recent_streak()

        return {
            "total_trades": len(closed),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(len(wins) / len(closed) * 100, 1),
            "avg_return_pct": round(closed["pnl_pct"].mean(), 2),
            "avg_win_pct": round(wins["pnl_pct"].mean(), 2) if len(wins) > 0 else 0,
            "avg_loss_pct": round(losses["pnl_pct"].mean(), 2) if len(losses) > 0 else 0,
            "best_trade": round(closed["pnl_pct"].max(), 2),
            "worst_trade": round(closed["pnl_pct"].min(), 2),
            "total_pnl_pct": round(closed["pnl_pct"].sum(), 2),
            "avg_holding_days": round(closed["holding_days"].mean(), 1) if "holding_days" in closed else 0,
            "current_streak": f"{streak['streak_len']} {streak['streak_type']}s" if streak["streak_len"] > 0 else "—",
        }

    def _compute_position_size(self, streak: dict) -> float:
        ps_cfg = self.settings.risk.get("position_sizing", {})
        scale_up_after = ps_cfg.get("scale_up_after_wins", 5)
        scale_down_after = ps_cfg.get("scale_down_after_losses", 2)
        scale_factor = ps_cfg.get("scale_factor", 1.5)

        if streak["streak_type"] == "win" and streak["streak_len"] >= scale_up_after:
            return min(scale_factor, 2.0)
        elif streak["streak_type"] == "loss" and streak["streak_len"] >= scale_down_after:
            return round(1.0 / scale_factor, 2)
        return 1.0

    def _fetch_and_prepare(self) -> dict:
        universe = self.fetcher.get_universe_symbols()
        period = self.settings.market.get("default_period", "1y")
        logger.info(f"Scanning {len(universe)} NSE stocks across all strategies...")
        results = {}

        for i, symbol in enumerate(universe):
            try:
                stock = self.fetcher.fetch_stock(symbol, period)
                ohlcv = Preprocessor.add_indicators(stock["ohlcv"])
                self.store.save_ohlcv(stock["ohlcv"])
                if stock.get("fundamentals"):
                    self.store.save_fundamentals(stock["fundamentals"])
                results[symbol] = {"ohlcv": ohlcv, "fundamentals": stock["fundamentals"]}
                if (i + 1) % 50 == 0:
                    logger.info(f"Progress: {i + 1}/{len(universe)} stocks processed")
            except Exception as e:
                logger.error(f"Failed to prepare {symbol}: {e}")

        logger.info(f"Prepared {len(results)}/{len(universe)} stocks for strategy scanning")
        return results
