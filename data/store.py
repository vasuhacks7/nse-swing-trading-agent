import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)


class DataStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._init_db()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                -- Migrate existing alerts tables missing new columns
                CREATE TABLE IF NOT EXISTS _migration_check (v INTEGER);
            """)
            for col, typ, default in [
                ("risk_reward_ratio", "REAL", "0"),
                ("trailing_stop", "REAL", "NULL"),
                ("highest_price", "REAL", "NULL"),
                ("installment", "INTEGER", "1"),
                ("qty_pct", "REAL", "1.0"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE alerts ADD COLUMN {col} {typ} DEFAULT {default}")
                except Exception:
                    pass

            conn.executescript("""
                CREATE TABLE IF NOT EXISTS ohlcv (
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    open REAL, high REAL, low REAL, close REAL, volume REAL,
                    PRIMARY KEY (symbol, date)
                );

                CREATE TABLE IF NOT EXISTS fundamentals (
                    symbol TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT 'BUY',
                    entry_price REAL NOT NULL,
                    target_price REAL,
                    stop_loss REAL,
                    signal_score REAL,
                    reasoning TEXT,
                    technical_summary TEXT,
                    fundamental_summary TEXT,
                    status TEXT DEFAULT 'OPEN',
                    exit_price REAL,
                    exit_date TEXT,
                    pnl_pct REAL,
                    pnl_amount REAL,
                    holding_days INTEGER,
                    exit_reason TEXT,
                    risk_reward_ratio REAL DEFAULT 0,
                    trailing_stop REAL,
                    highest_price REAL,
                    installment INTEGER DEFAULT 1,
                    qty_pct REAL DEFAULT 1.0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS strategy_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT NOT NULL,
                    period_start TEXT,
                    period_end TEXT,
                    total_alerts INTEGER DEFAULT 0,
                    winning_alerts INTEGER DEFAULT 0,
                    losing_alerts INTEGER DEFAULT 0,
                    avg_return_pct REAL DEFAULT 0,
                    win_rate REAL DEFAULT 0,
                    avg_win_pct REAL DEFAULT 0,
                    avg_loss_pct REAL DEFAULT 0,
                    profit_factor REAL DEFAULT 0,
                    current_weight REAL DEFAULT 1.0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS improvement_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    type TEXT NOT NULL,
                    description TEXT,
                    changes TEXT,
                    llm_analysis TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def init_paper_trading(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT DEFAULT 'BUY',
                    entry_price REAL NOT NULL,
                    target_price REAL,
                    stop_loss REAL,
                    qty INTEGER DEFAULT 0,
                    invested REAL DEFAULT 0,
                    risk_reward REAL DEFAULT 0,
                    signal TEXT,
                    confluence_score INTEGER DEFAULT 0,
                    confluence_points TEXT,
                    status TEXT DEFAULT 'OPEN',
                    exit_price REAL,
                    exit_date TEXT,
                    exit_reason TEXT,
                    pnl_pct REAL,
                    pnl_amount REAL,
                    holding_days INTEGER,
                    highest_price REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def open_paper_trade(self, trade: dict) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO paper_trades
                   (date, symbol, action, entry_price, target_price, stop_loss,
                    qty, invested, risk_reward, signal, confluence_score,
                    confluence_points, highest_price, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')""",
                (trade["date"], trade["symbol"], trade.get("action", "BUY"),
                 trade["entry_price"], trade.get("target_price"),
                 trade.get("stop_loss"), trade.get("qty", 0),
                 trade.get("invested", 0), trade.get("risk_reward", 0),
                 trade.get("signal"), trade.get("confluence_score", 0),
                 trade.get("confluence_points", ""), trade["entry_price"]),
            )
            return cursor.lastrowid

    def close_paper_trade(self, trade_id: int, result: dict):
        with self._conn() as conn:
            conn.execute(
                """UPDATE paper_trades SET status='CLOSED', exit_price=?,
                   exit_date=?, exit_reason=?, pnl_pct=?, pnl_amount=?,
                   holding_days=? WHERE id=?""",
                (result["exit_price"], result["exit_date"], result["exit_reason"],
                 result["pnl_pct"], result["pnl_amount"],
                 result.get("holding_days", 0), trade_id),
            )

    def get_paper_position(self, symbol: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM paper_trades WHERE symbol=? AND status='OPEN'",
                (symbol,),
            ).fetchone()
            if row:
                cols = [d[0] for d in conn.execute("SELECT * FROM paper_trades LIMIT 0").description]
                return dict(zip(cols, row))
        return None

    def get_open_paper_trades(self) -> list[dict]:
        with self._conn() as conn:
            cursor = conn.execute("SELECT * FROM paper_trades WHERE status='OPEN' ORDER BY date DESC")
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def get_all_paper_trades(self, limit: int = 200) -> list[dict]:
        with self._conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM paper_trades ORDER BY date DESC LIMIT ?", (limit,))
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def get_closed_paper_trades(self, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM paper_trades WHERE status='CLOSED' ORDER BY exit_date DESC LIMIT ?",
                (limit,))
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def update_paper_highest(self, trade_id: int, highest: float):
        with self._conn() as conn:
            conn.execute("UPDATE paper_trades SET highest_price=? WHERE id=?",
                         (round(highest, 2), trade_id))

    def update_paper_stop(self, trade_id: int, new_stop: float):
        with self._conn() as conn:
            conn.execute("UPDATE paper_trades SET stop_loss=? WHERE id=?",
                         (round(new_stop, 2), trade_id))

    def save_ohlcv(self, df: pd.DataFrame):
        with self._conn() as conn:
            for _, row in df.iterrows():
                conn.execute(
                    """INSERT OR REPLACE INTO ohlcv
                       (symbol, date, open, high, low, close, volume)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (row["symbol"], str(row.name.date()), row["open"],
                     row["high"], row["low"], row["close"], row["volume"]),
                )

    def load_ohlcv(self, symbol: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        query = "SELECT date, open, high, low, close, volume FROM ohlcv WHERE symbol = ?"
        params: list = [symbol]
        if start:
            query += " AND date >= ?"
            params.append(start)
        if end:
            query += " AND date <= ?"
            params.append(end)
        query += " ORDER BY date"
        with self._conn() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            df["symbol"] = symbol
        return df

    def save_fundamentals(self, data: dict):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO fundamentals (symbol, data, updated_at) VALUES (?, ?, ?)",
                (data["symbol"], json.dumps(data), datetime.now().isoformat()),
            )

    def load_fundamentals(self, symbol: str) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT data FROM fundamentals WHERE symbol = ?", (symbol,)
            ).fetchone()
        return json.loads(row[0]) if row else {}

    def save_alert(self, alert: dict) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO alerts
                   (date, symbol, strategy, action, entry_price, target_price,
                    stop_loss, signal_score, reasoning, technical_summary,
                    fundamental_summary, risk_reward_ratio, trailing_stop,
                    highest_price, installment, qty_pct, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')""",
                (alert["date"], alert["symbol"], alert["strategy"],
                 alert.get("action", "BUY"), alert["entry_price"],
                 alert.get("target_price"), alert.get("stop_loss"),
                 alert.get("signal_score"), alert.get("reasoning"),
                 alert.get("technical_summary"), alert.get("fundamental_summary"),
                 alert.get("risk_reward_ratio", 0),
                 alert.get("stop_loss"),
                 alert["entry_price"],
                 alert.get("installment", 1),
                 alert.get("qty_pct", 1.0)),
            )
            return cursor.lastrowid

    def close_alert(self, alert_id: int, exit_price: float, exit_date: str,
                    exit_reason: str):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT entry_price, date FROM alerts WHERE id = ?", (alert_id,)
            ).fetchone()
            if not row:
                return
            entry_price, entry_date = row
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100
            holding_days = (pd.Timestamp(exit_date) - pd.Timestamp(entry_date)).days
            conn.execute(
                """UPDATE alerts SET status='CLOSED', exit_price=?, exit_date=?,
                   pnl_pct=?, pnl_amount=?, holding_days=?, exit_reason=?
                   WHERE id=?""",
                (exit_price, exit_date, round(pnl_pct, 2),
                 round(exit_price - entry_price, 2), holding_days,
                 exit_reason, alert_id),
            )

    def get_open_alerts(self) -> pd.DataFrame:
        with self._conn() as conn:
            return pd.read_sql_query(
                "SELECT * FROM alerts WHERE status='OPEN' ORDER BY date DESC", conn,
            )

    def get_all_alerts(self, limit: int = 200) -> pd.DataFrame:
        with self._conn() as conn:
            return pd.read_sql_query(
                "SELECT * FROM alerts ORDER BY date DESC LIMIT ?", conn, params=[limit],
            )

    def get_closed_alerts(self, strategy: str | None = None, limit: int = 200) -> pd.DataFrame:
        query = "SELECT * FROM alerts WHERE status='CLOSED'"
        params: list = []
        if strategy:
            query += " AND strategy=?"
            params.append(strategy)
        query += " ORDER BY exit_date DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            return pd.read_sql_query(query, conn, params=params)

    def update_trailing_stop(self, alert_id: int, new_stop: float, highest_price: float):
        with self._conn() as conn:
            conn.execute(
                "UPDATE alerts SET trailing_stop=?, highest_price=? WHERE id=?",
                (round(new_stop, 2), round(highest_price, 2), alert_id),
            )

    def get_recent_streak(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT pnl_pct FROM alerts
                   WHERE status='CLOSED' ORDER BY exit_date DESC LIMIT 20"""
            ).fetchall()
        if not rows:
            return {"wins": 0, "losses": 0, "streak_type": "none", "streak_len": 0}
        streak_type = "win" if rows[0][0] > 0 else "loss"
        streak_len = 0
        for row in rows:
            is_win = row[0] > 0
            if (streak_type == "win" and is_win) or (streak_type == "loss" and not is_win):
                streak_len += 1
            else:
                break
        total_wins = sum(1 for r in rows if r[0] > 0)
        total_losses = sum(1 for r in rows if r[0] <= 0)
        return {"wins": total_wins, "losses": total_losses,
                "streak_type": streak_type, "streak_len": streak_len}

    def get_alerts_for_date(self, date: str) -> pd.DataFrame:
        with self._conn() as conn:
            return pd.read_sql_query(
                "SELECT * FROM alerts WHERE date=?", conn, params=[date],
            )

    def save_strategy_score(self, score: dict):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO strategy_scores
                   (strategy, period_start, period_end, total_alerts, winning_alerts,
                    losing_alerts, avg_return_pct, win_rate, avg_win_pct, avg_loss_pct,
                    profit_factor, current_weight)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (score["strategy"], score.get("period_start"), score.get("period_end"),
                 score.get("total_alerts", 0), score.get("winning_alerts", 0),
                 score.get("losing_alerts", 0), score.get("avg_return_pct", 0),
                 score.get("win_rate", 0), score.get("avg_win_pct", 0),
                 score.get("avg_loss_pct", 0), score.get("profit_factor", 0),
                 score.get("current_weight", 1.0)),
            )

    def get_strategy_scores(self) -> pd.DataFrame:
        with self._conn() as conn:
            return pd.read_sql_query(
                """SELECT * FROM strategy_scores
                   ORDER BY updated_at DESC""", conn,
            )

    def get_latest_strategy_weights(self) -> dict[str, float]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT strategy, current_weight FROM strategy_scores
                   WHERE id IN (SELECT MAX(id) FROM strategy_scores GROUP BY strategy)"""
            ).fetchall()
        return {row[0]: row[1] for row in rows} if rows else {}

    def save_improvement_log(self, entry: dict):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO improvement_log (date, type, description, changes, llm_analysis)
                   VALUES (?, ?, ?, ?, ?)""",
                (entry["date"], entry["type"], entry.get("description"),
                 entry.get("changes"), entry.get("llm_analysis")),
            )

    def get_improvement_log(self, limit: int = 50) -> pd.DataFrame:
        with self._conn() as conn:
            return pd.read_sql_query(
                "SELECT * FROM improvement_log ORDER BY created_at DESC LIMIT ?",
                conn, params=[limit],
            )

    # --- Apoorv picks ---

    def init_apoorv_picks(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS apoorv_picks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT UNIQUE,
                    date TEXT NOT NULL,
                    message_text TEXT,
                    symbol TEXT,
                    entry_price REAL,
                    target_price REAL,
                    stop_loss REAL,
                    signal_type TEXT DEFAULT 'BUY',
                    our_confluence_score INTEGER,
                    our_signal TEXT,
                    cross_validated INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'OPEN',
                    current_price REAL,
                    highest_price REAL,
                    exit_price REAL,
                    exit_date TEXT,
                    pnl_pct REAL,
                    exit_reason TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def apoorv_pick_exists(self, message_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM apoorv_picks WHERE message_id=?", (message_id,)
            ).fetchone()
            return row is not None

    def save_apoorv_pick(self, pick: dict) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO apoorv_picks
                   (message_id, date, message_text, symbol, entry_price,
                    target_price, stop_loss, signal_type, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')""",
                (pick["message_id"], pick["date"], pick.get("message_text"),
                 pick["symbol"], pick.get("entry_price"),
                 pick.get("target_price"), pick.get("stop_loss"),
                 pick.get("signal_type", "BUY")),
            )
            return cursor.lastrowid

    def get_apoorv_picks(self, status: str | None = None, limit: int = 100) -> list[dict]:
        query = "SELECT * FROM apoorv_picks"
        params: list = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY date DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            cursor = conn.execute(query, params)
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def get_unvalidated_apoorv_picks(self) -> list[dict]:
        with self._conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM apoorv_picks WHERE cross_validated=0 AND status='OPEN'"
            )
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def update_apoorv_pick_price(self, pick_id: int, current: float, highest: float):
        with self._conn() as conn:
            conn.execute(
                "UPDATE apoorv_picks SET current_price=?, highest_price=? WHERE id=?",
                (round(current, 2), round(highest, 2), pick_id),
            )

    def update_apoorv_cross_validation(self, pick_id: int, score: int,
                                        signal: str, validated: bool,
                                        entry: float | None = None,
                                        target: float | None = None,
                                        stop_loss: float | None = None):
        with self._conn() as conn:
            conn.execute(
                """UPDATE apoorv_picks SET our_confluence_score=?, our_signal=?,
                   cross_validated=?,
                   entry_price=COALESCE(entry_price, ?),
                   target_price=COALESCE(target_price, ?),
                   stop_loss=COALESCE(stop_loss, ?)
                   WHERE id=?""",
                (score, signal, 1 if validated else 0,
                 round(entry, 2) if entry else None,
                 round(target, 2) if target else None,
                 round(stop_loss, 2) if stop_loss else None,
                 pick_id),
            )

    def close_apoorv_pick(self, pick_id: int, exit_price: float,
                           exit_reason: str, pnl_pct: float):
        with self._conn() as conn:
            conn.execute(
                """UPDATE apoorv_picks SET status='CLOSED', exit_price=?,
                   exit_date=?, exit_reason=?, pnl_pct=? WHERE id=?""",
                (round(exit_price, 2), datetime.now().strftime("%Y-%m-%d"),
                 exit_reason, round(pnl_pct, 2), pick_id),
            )

    def get_apoorv_performance_summary(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM apoorv_picks").fetchone()[0]
            open_ct = conn.execute(
                "SELECT COUNT(*) FROM apoorv_picks WHERE status='OPEN'"
            ).fetchone()[0]
            closed = conn.execute(
                "SELECT COUNT(*) FROM apoorv_picks WHERE status='CLOSED'"
            ).fetchone()[0]
            wins = conn.execute(
                "SELECT COUNT(*) FROM apoorv_picks WHERE status='CLOSED' AND pnl_pct > 0"
            ).fetchone()[0]
            losses = conn.execute(
                "SELECT COUNT(*) FROM apoorv_picks WHERE status='CLOSED' AND pnl_pct <= 0"
            ).fetchone()[0]
            avg_ret = conn.execute(
                "SELECT AVG(pnl_pct) FROM apoorv_picks WHERE status='CLOSED'"
            ).fetchone()[0] or 0
            total_ret = conn.execute(
                "SELECT SUM(pnl_pct) FROM apoorv_picks WHERE status='CLOSED'"
            ).fetchone()[0] or 0
            validated = conn.execute(
                "SELECT COUNT(*) FROM apoorv_picks WHERE cross_validated=1"
            ).fetchone()[0]

        return {
            "total": total, "open": open_ct, "closed": closed,
            "wins": wins, "losses": losses,
            "win_rate": round(wins / closed * 100, 1) if closed else 0,
            "avg_return": round(avg_ret, 2),
            "total_return": round(total_ret, 2),
            "cross_validated": validated,
        }
