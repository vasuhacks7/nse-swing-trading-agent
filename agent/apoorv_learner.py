import logging
from datetime import datetime

from config.settings import Settings
from data.store import DataStore
from data.fetcher import DataFetcher
from data.advanced_analysis import full_analysis

logger = logging.getLogger(__name__)


class ApoorvLearner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = DataStore(settings.db_path)
        self.store.init_apoorv_picks()
        self.fetcher = DataFetcher(settings)

    def cross_validate_pick(self, pick: dict) -> dict:
        symbol = pick["symbol"]
        nse_sym = f"{symbol}.NS"

        try:
            df = self.fetcher.fetch_ohlcv(nse_sym, period="2y")
            fundamentals = {}
            try:
                fundamentals = self.fetcher.fetch_fundamentals(nse_sym)
            except Exception:
                pass

            analysis = full_analysis(df, fundamentals)

            our_signal = analysis.get("signal", "NEUTRAL")
            our_score = analysis.get("confluence_score", 0)
            our_entry = analysis.get("entry")
            our_target = analysis.get("target")
            our_sl = analysis.get("stop_loss")

            pick_type = pick.get("signal_type", "ANALYSIS")
            if pick_type == "BUY":
                agrees = our_signal in ("STRONG_BUY", "BUY")
            else:
                agrees = our_signal in ("STRONG_BUY", "BUY", "WATCH")

            current_price = float(df["close"].iloc[-1]) if not df.empty else None

            self.store.update_apoorv_cross_validation(
                pick["id"], our_score, our_signal, agrees,
                entry=our_entry, target=our_target, stop_loss=our_sl,
            )
            if current_price:
                self.store.update_apoorv_pick_price(
                    pick["id"], current_price,
                    max(current_price, pick.get("highest_price") or 0),
                )

            return {
                "symbol": symbol,
                "apoorv_signal": pick.get("signal_type", "BUY"),
                "our_signal": our_signal,
                "our_confluence": our_score,
                "agrees": agrees,
                "our_entry": our_entry,
                "our_target": our_target,
                "our_sl": our_sl,
                "confluence_points": analysis.get("confluence_points", []),
                "analysis": analysis,
            }

        except Exception as e:
            logger.error(f"Cross-validation failed for {symbol}: {e}")
            return {
                "symbol": symbol,
                "error": str(e),
                "agrees": False,
            }

    def cross_validate_new_picks(self) -> list[dict]:
        unvalidated = self.store.get_unvalidated_apoorv_picks()
        results = []

        for pick in unvalidated:
            result = self.cross_validate_pick(pick)
            results.append(result)
            if result.get("agrees"):
                logger.info(
                    f"Apoorv pick {pick['symbol']} CONFIRMED by our analysis "
                    f"(confluence: {result.get('our_confluence', 0)}/12)"
                )

        return results

    def get_suggestions(self) -> list[dict]:
        open_picks = self.store.get_apoorv_picks(status="OPEN")
        suggestions = []

        for pick in open_picks:
            if pick.get("cross_validated") and pick.get("our_confluence_score", 0) >= 3:
                suggestions.append({
                    "symbol": pick["symbol"],
                    "apoorv_entry": pick.get("entry_price"),
                    "apoorv_target": pick.get("target_price"),
                    "apoorv_sl": pick.get("stop_loss"),
                    "our_confluence": pick.get("our_confluence_score", 0),
                    "our_signal": pick.get("our_signal", ""),
                    "date": pick.get("date"),
                    "confidence": "HIGH" if pick.get("our_confluence_score", 0) >= 5 else "MEDIUM",
                })

        suggestions.sort(key=lambda x: x.get("our_confluence", 0), reverse=True)
        return suggestions

    def analyze_patterns(self) -> dict:
        closed = self.store.get_apoorv_picks(status="CLOSED")
        if not closed:
            return {"message": "No closed picks to analyze yet"}

        wins = [p for p in closed if (p.get("pnl_pct") or 0) > 0]
        losses = [p for p in closed if (p.get("pnl_pct") or 0) <= 0]

        validated_wins = [w for w in wins if w.get("cross_validated")]
        validated_losses = [l for l in losses if l.get("cross_validated")]
        unvalidated_wins = [w for w in wins if not w.get("cross_validated")]
        unvalidated_losses = [l for l in losses if not l.get("cross_validated")]

        avg_win = sum(w.get("pnl_pct", 0) for w in wins) / len(wins) if wins else 0
        avg_loss = sum(l.get("pnl_pct", 0) for l in losses) / len(losses) if losses else 0

        v_win_rate = (
            round(len(validated_wins) / (len(validated_wins) + len(validated_losses)) * 100, 1)
            if (validated_wins or validated_losses) else 0
        )
        u_win_rate = (
            round(len(unvalidated_wins) / (len(unvalidated_wins) + len(unvalidated_losses)) * 100, 1)
            if (unvalidated_wins or unvalidated_losses) else 0
        )

        insights = []
        if v_win_rate > u_win_rate + 5:
            insights.append(
                f"Cross-validated picks win {v_win_rate:.0f}% vs {u_win_rate:.0f}% — "
                f"our confirmation adds value"
            )
        elif u_win_rate > v_win_rate + 5:
            insights.append(
                f"Unvalidated picks win {u_win_rate:.0f}% vs {v_win_rate:.0f}% — "
                f"Apoorv catches setups we miss"
            )

        if avg_win > abs(avg_loss) * 1.5:
            insights.append(
                f"Winners avg +{avg_win:.1f}% vs losers avg {avg_loss:.1f}% — "
                f"good risk:reward discipline"
            )

        confluence_scores = [p.get("our_confluence_score", 0) for p in wins if p.get("our_confluence_score")]
        avg_win_confluence = sum(confluence_scores) / len(confluence_scores) if confluence_scores else 0

        loss_scores = [p.get("our_confluence_score", 0) for p in losses if p.get("our_confluence_score")]
        avg_loss_confluence = sum(loss_scores) / len(loss_scores) if loss_scores else 0

        if avg_win_confluence > avg_loss_confluence + 1:
            insights.append(
                f"Winners have higher confluence ({avg_win_confluence:.1f}) "
                f"vs losers ({avg_loss_confluence:.1f})"
            )

        return {
            "total_analyzed": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "validated_win_rate": v_win_rate,
            "unvalidated_win_rate": u_win_rate,
            "avg_win_confluence": round(avg_win_confluence, 1),
            "avg_loss_confluence": round(avg_loss_confluence, 1),
            "insights": insights,
        }

    def generate_learning_report(self) -> dict:
        perf = self.store.get_apoorv_performance_summary()
        patterns = self.analyze_patterns()
        suggestions = self.get_suggestions()

        return {
            "performance": perf,
            "patterns": patterns,
            "current_suggestions": suggestions,
            "generated_at": datetime.now().isoformat(),
        }
