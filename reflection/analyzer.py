import json
import logging

logger = logging.getLogger(__name__)


class TradeAnalyzer:
    @staticmethod
    def analyze_patterns(trades: list[dict]) -> dict:
        if not trades:
            return {"patterns": [], "issues": []}

        winners = [t for t in trades if t.get("pnl", 0) > 0]
        losers = [t for t in trades if t.get("pnl", 0) < 0]

        patterns = []
        issues = []

        if winners:
            avg_win_signal = sum(t.get("signal_score", 0) for t in winners) / len(winners)
            patterns.append(f"Average winning signal score: {avg_win_signal:.3f}")

        if losers:
            avg_lose_signal = sum(t.get("signal_score", 0) for t in losers) / len(losers)
            issues.append(f"Average losing signal score: {avg_lose_signal:.3f}")

        by_symbol: dict[str, list] = {}
        for t in trades:
            sym = t.get("symbol", "?")
            by_symbol.setdefault(sym, []).append(t)

        for sym, sym_trades in by_symbol.items():
            sym_pnl = sum(t.get("pnl", 0) for t in sym_trades)
            if sym_pnl < 0 and len(sym_trades) >= 3:
                issues.append(f"{sym} consistently losing (${sym_pnl:.2f} over {len(sym_trades)} trades)")
            elif sym_pnl > 0 and len(sym_trades) >= 3:
                patterns.append(f"{sym} consistently profitable (${sym_pnl:.2f} over {len(sym_trades)} trades)")

        if len(trades) >= 10:
            recent = trades[:len(trades) // 2]
            older = trades[len(trades) // 2:]
            recent_wr = sum(1 for t in recent if t.get("pnl", 0) > 0) / len(recent)
            older_wr = sum(1 for t in older if t.get("pnl", 0) > 0) / len(older)
            if recent_wr < older_wr - 0.1:
                issues.append(f"Win rate declining: {older_wr:.1%} → {recent_wr:.1%}")
            elif recent_wr > older_wr + 0.1:
                patterns.append(f"Win rate improving: {older_wr:.1%} → {recent_wr:.1%}")

        return {"patterns": patterns, "issues": issues}

    @staticmethod
    def suggest_adjustments(analysis: dict, current_params: dict) -> list[dict]:
        suggestions = []

        for issue in analysis.get("issues", []):
            if "consistently losing" in issue:
                suggestions.append({
                    "type": "symbol_filter",
                    "detail": issue,
                    "action": "Consider removing underperforming symbol from watchlist",
                })
            if "Win rate declining" in issue:
                suggestions.append({
                    "type": "threshold_adjust",
                    "detail": issue,
                    "action": "Consider raising buy_threshold for higher-conviction entries",
                })

        return suggestions
