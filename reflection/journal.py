import json
from datetime import datetime

import pandas as pd

from data.store import DataStore


class TradeJournal:
    def __init__(self, store: DataStore):
        self.store = store

    def log_trade(self, trade: dict):
        self.store.save_trade(trade)

    def get_recent_trades(self, limit: int = 50) -> list[dict]:
        df = self.store.load_trades(limit)
        if df.empty:
            return []
        return df.to_dict("records")

    def get_period_summary(self, start: str, end: str) -> dict:
        trades = self.get_recent_trades(200)
        period_trades = [
            t for t in trades
            if t.get("entry_date") and start <= t["entry_date"] <= end
        ]

        if not period_trades:
            return {"period": f"{start} to {end}", "total_trades": 0}

        pnls = [t.get("pnl", 0) for t in period_trades]
        winners = [p for p in pnls if p > 0]
        losers = [p for p in pnls if p < 0]

        return {
            "period": f"{start} to {end}",
            "total_trades": len(period_trades),
            "winning_trades": len(winners),
            "losing_trades": len(losers),
            "total_pnl": sum(pnls),
            "avg_win": sum(winners) / len(winners) if winners else 0,
            "avg_loss": sum(losers) / len(losers) if losers else 0,
            "win_rate": len(winners) / len(period_trades) if period_trades else 0,
            "best_trade": max(pnls),
            "worst_trade": min(pnls),
            "trades": period_trades,
        }

    def format_for_llm(self, trades: list[dict], metrics: dict | None = None) -> str:
        lines = ["## Recent Trade History\n"]
        for t in trades[:50]:
            pnl = t.get("pnl", 0)
            pnl_pct = t.get("pnl_pct", 0)
            lines.append(
                f"- {t.get('symbol','?')} | {t.get('side','?')} | "
                f"Entry: {t.get('entry_date','?')} @ ${t.get('entry_price',0):.2f} | "
                f"Exit: {t.get('exit_date','?')} @ ${t.get('exit_price',0):.2f} | "
                f"P&L: ${pnl:.2f} ({pnl_pct:.2%}) | "
                f"Signal: {t.get('signal_score',0):.3f}"
            )

        if metrics:
            lines.append("\n## Performance Metrics\n")
            for k, v in metrics.items():
                if isinstance(v, float):
                    lines.append(f"- {k}: {v:.4f}")
                else:
                    lines.append(f"- {k}: {v}")

        return "\n".join(lines)
