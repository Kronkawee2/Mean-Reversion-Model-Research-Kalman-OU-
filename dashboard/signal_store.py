"""
Signal persistence layer — read/write signal history to MySQL signals.trade_signals.
"""

import os
import uuid
import pymysql
import pymysql.cursors
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DB = dict(
    host     = os.getenv("DB_HOST", "localhost"),
    port     = int(os.getenv("DB_PORT", 3306)),
    user     = os.getenv("DB_USER", "gold_user"),
    password = os.getenv("DB_PASSWORD", "1234"),
    charset  = "utf8mb4",
    database = "signals",
    cursorclass = pymysql.cursors.DictCursor,
)


def _conn():
    return pymysql.connect(**DB)


# ── Read ──────────────────────────────────────────────────────────────────────

def load_signals(symbol: str = None, status: str = None, limit: int = 500) -> list:
    """Load signals from MySQL. Optionally filter by symbol and/or status."""
    where = []
    params = []
    if symbol:
        where.append("symbol = %s"); params.append(symbol)
    if status:
        where.append("status = %s"); params.append(status)

    clause = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT signal_uuid, symbol, tf_exec AS timeframe, formed_at,
               direction, entry, stop_loss, take_profit, atr_14,
               confluence_score AS score, confluence_max,
               conditions, htf_bias, confidence, status,
               pnl_pts, bars_held, closed_at
        FROM trade_signals
        {clause}
        ORDER BY formed_at DESC
        LIMIT %s
    """
    params.append(limit)
    try:
        c = _conn(); cur = c.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close(); c.close()
        result = []
        for r in rows:
            r = dict(r)
            # Convert conditions pipe-string → list
            r["conditions"] = r["conditions"].split("|") if r["conditions"] else []
            r["formed_at"]  = str(r["formed_at"])[:16]
            r["closed_at"]  = str(r["closed_at"])[:16] if r["closed_at"] else None
            r["entry"]      = float(r["entry"])
            r["stop_loss"]  = float(r["stop_loss"])
            r["take_profit"]= float(r["take_profit"])
            r["pnl_pts"]    = float(r["pnl_pts"]) if r["pnl_pts"] is not None else None
            r["confidence"] = float(r["confidence"])
            # Backwards compat
            r["id"]         = r["signal_uuid"]
            # Unix timestamp for chart markers
            try:
                import pandas as pd
                r["time"] = int(pd.to_datetime(r["formed_at"]).timestamp())
            except Exception:
                r["time"] = 0
            result.append(r)
        return result
    except Exception as e:
        print(f"[signal_store] load_signals error: {e}")
        return []


# ── Write ─────────────────────────────────────────────────────────────────────

def append_new_signals(new_sigs: list) -> int:
    """Insert new signals. Skip duplicates (by symbol, tf_exec, formed_at, direction)."""
    if not new_sigs:
        return 0

    sql = """
        INSERT IGNORE INTO trade_signals
            (signal_uuid, symbol, tf_exec, formed_at, direction,
             entry, stop_loss, take_profit, atr_14,
             confluence_score, confluence_max, conditions,
             confidence, status)
        VALUES
            (%s, %s, %s, %s, %s,
             %s, %s, %s, %s,
             %s, %s, %s,
             %s, 'PENDING')
    """
    rows = []
    for s in new_sigs:
        conds = s.get("conditions", [])
        cond_str = "|".join(conds) if isinstance(conds, list) else str(conds)
        rows.append((
            s.get("id", str(uuid.uuid4())[:8]),
            s["symbol"],
            s.get("timeframe", s.get("tf_exec", "5m")),
            s["formed_at"],
            s["direction"],
            s["entry"],
            s["stop_loss"],
            s["take_profit"],
            s.get("atr_14", 0),
            s.get("score", s.get("confluence_score", 0)),
            s.get("confluence_max", 7),
            cond_str,
            s.get("confidence", 0),
        ))

    try:
        c = _conn(); cur = c.cursor()
        cur.executemany(sql, rows)
        added = cur.rowcount
        c.commit(); cur.close(); c.close()
        return added
    except Exception as e:
        print(f"[signal_store] append error: {e}")
        return 0


# ── Auto-Evaluate ─────────────────────────────────────────────────────────────

def evaluate_pending_from_db() -> int:
    """
    Load PENDING signals and check against price data in MySQL.
    Updates status/pnl_pts/closed_at in trade_signals.
    Returns count of signals updated.
    """
    import pandas as pd

    try:
        c = _conn(); cur = c.cursor()
        cur.execute("""
            SELECT signal_uuid, symbol, tf_exec, formed_at, direction,
                   entry, stop_loss, take_profit
            FROM trade_signals WHERE status = 'PENDING'
        """)
        pending = cur.fetchall()
        cur.close(); c.close()
    except Exception as e:
        print(f"[signal_store] evaluate fetch error: {e}")
        return 0

    if not pending:
        return 0

    # Map tf_exec → MySQL table name
    tf_table = {"5m": "m5", "15m": "m15", "1h": "h1", "4h": "h4", "1d": "d1"}
    # Map symbol → MySQL database
    sym_db   = {"XAUUSD": "gold", "EURUSD": "eurusd"}

    updated = 0
    for sig in pending:
        db_name = sym_db.get(sig["symbol"])
        table   = tf_table.get(sig["tf_exec"])
        if not db_name or not table:
            continue

        try:
            pc = pymysql.connect(
                host=os.getenv("DB_HOST","localhost"),
                port=int(os.getenv("DB_PORT",3306)),
                user=os.getenv("DB_USER","gold_user"),
                password=os.getenv("DB_PASSWORD","1234"),
                database=db_name,
                cursorclass=pymysql.cursors.DictCursor,
            )
            pcur = pc.cursor()
            pcur.execute(
                "SELECT price_datetime, high_price, low_price "
                f"FROM `{table}` WHERE price_datetime > %s "
                "ORDER BY price_datetime LIMIT 500",
                (sig["formed_at"],)
            )
            future_rows = pcur.fetchall()
            pcur.close(); pc.close()
        except Exception:
            continue

        direction = sig["direction"]
        entry     = float(sig["entry"])
        tp        = float(sig["take_profit"])
        sl        = float(sig["stop_loss"])
        result_status = None
        result_pnl    = None
        result_closed = None

        for row in future_rows:
            h = float(row["high_price"])
            l = float(row["low_price"])
            if direction == "bullish":
                if h >= tp:
                    result_status = "WIN";  result_pnl = round(tp - entry, 5)
                    result_closed = str(row["price_datetime"])[:16]; break
                if l <= sl:
                    result_status = "LOSS"; result_pnl = round(sl - entry, 5)
                    result_closed = str(row["price_datetime"])[:16]; break
            else:
                if l <= tp:
                    result_status = "WIN";  result_pnl = round(entry - tp, 5)
                    result_closed = str(row["price_datetime"])[:16]; break
                if h >= sl:
                    result_status = "LOSS"; result_pnl = round(entry - sl, 5)
                    result_closed = str(row["price_datetime"])[:16]; break

        if result_status:
            try:
                uc = _conn(); ucur = uc.cursor()
                ucur.execute(
                    "UPDATE trade_signals SET status=%s, pnl_pts=%s, closed_at=%s WHERE signal_uuid=%s",
                    (result_status, result_pnl, result_closed, sig["signal_uuid"])
                )
                uc.commit(); ucur.close(); uc.close()
                updated += 1
            except Exception as e:
                print(f"[signal_store] update error: {e}")

    return updated
