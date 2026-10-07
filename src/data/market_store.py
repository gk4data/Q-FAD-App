"""Local, transactional candle cache and persistent backtest history."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import os
import sqlite3

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def strategy_fingerprint():
    digest = hashlib.sha256()
    paths = [ROOT / "src/backtest/backtest_engine.py", ROOT / "src/data/data_fetcher.py"]
    for folder in ("indicators", "signals"):
        paths.extend(sorted((ROOT / "src" / folder).glob("*.py")))
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None if math.isnan(value) else str(value)
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    return value


class MarketStore:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("QFAD_DATABASE_PATH") or ROOT / "data/market_data.sqlite3")

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS candle_days (
                instrument TEXT, expiry TEXT, interval TEXT, day TEXT,
                source TEXT NOT NULL, fetched_at TEXT NOT NULL,
                PRIMARY KEY (instrument, expiry, interval, day)
            );
            CREATE TABLE IF NOT EXISTS candles (
                instrument TEXT, expiry TEXT, interval TEXT, day TEXT,
                timestamp TEXT, open REAL, high REAL, low REAL, close REAL,
                volume REAL, oi REAL,
                PRIMARY KEY (instrument, expiry, interval, day, timestamp)
            );
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL, kind TEXT NOT NULL, label TEXT NOT NULL,
                strategy TEXT NOT NULL, context TEXT NOT NULL,
                summary TEXT NOT NULL, results TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contracts (
                underlying TEXT, day TEXT, strike INTEGER, side TEXT, exchange TEXT,
                instrument TEXT NOT NULL, expiry TEXT NOT NULL, source TEXT NOT NULL,
                PRIMARY KEY (underlying, day, strike, side, exchange)
            );
        """)
        return conn

    def load_contract(self, underlying, day, strike, side, exchange):
        with closing(self.connect()) as conn:
            return conn.execute("SELECT instrument,expiry,source FROM contracts WHERE underlying=? AND day=? AND strike=? AND side=? AND exchange=?", (underlying, day, strike, side, exchange)).fetchone()

    def save_contract(self, underlying, day, strike, side, exchange, instrument, expiry, source):
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO contracts VALUES (?,?,?,?,?,?,?,?)", (underlying, day, strike, side, exchange, instrument, expiry, source))

    def load_day(self, instrument, expiry, interval, day):
        key = (instrument, expiry or "", interval, day)
        with closing(self.connect()) as conn:
            if not conn.execute("SELECT 1 FROM candle_days WHERE instrument=? AND expiry=? AND interval=? AND day=?", key).fetchone():
                return None
            df = pd.read_sql_query(
                'SELECT timestamp AS Date, open AS Open, high AS High, low AS Low, close AS Close, volume AS Volume, oi AS OI FROM candles WHERE instrument=? AND expiry=? AND interval=? AND day=? ORDER BY timestamp',
                conn, params=key)
        df["Date"] = pd.to_datetime(df["Date"])
        if df["Date"].dt.tz is not None:
            df["Date"] = df["Date"].dt.tz_convert("Asia/Kolkata")
        if df["OI"].isna().all():
            df = df.drop(columns="OI")
        return df

    def save_day(self, instrument, expiry, interval, day, df, source):
        # Empty responses/failures are never treated as successfully cached days.
        if df.empty:
            return
        key = (instrument, expiry or "", interval, day)
        rows = []
        for row in df.to_dict("records"):
            ts = pd.Timestamp(row["Date"])
            if ts.tzinfo is not None:
                ts = ts.tz_convert("Asia/Kolkata")
            if ts.strftime("%Y-%m-%d") != day:
                continue
            values = [None if pd.isna(row.get(c)) else float(row[c]) for c in ("Open", "High", "Low", "Close", "Volume", "OI")]
            rows.append((*key, ts.isoformat(), *values))
        if not rows:
            return
        with closing(self.connect()) as conn, conn:
            conn.execute("DELETE FROM candles WHERE instrument=? AND expiry=? AND interval=? AND day=?", key)
            conn.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
            conn.execute("INSERT OR REPLACE INTO candle_days VALUES (?,?,?,?,?,?)", (*key, source, datetime.now(timezone.utc).isoformat()))

    def save_run(self, kind, label, context, summary, results, strategy=None):
        with closing(self.connect()) as conn, conn:
            cur = conn.execute("INSERT INTO backtest_runs (created_at,kind,label,strategy,context,summary,results) VALUES (?,?,?,?,?,?,?)", (
                datetime.now(timezone.utc).isoformat(), kind, label.strip() or "Baseline",
                strategy or strategy_fingerprint(), json.dumps(_clean(context), allow_nan=False),
                json.dumps(_clean(summary), allow_nan=False), json.dumps(_clean(results), allow_nan=False)))
            return cur.lastrowid

    def list_runs(self):
        with closing(self.connect()) as conn:
            rows = conn.execute("SELECT id,created_at,kind,label,strategy,context,summary FROM backtest_runs ORDER BY id DESC").fetchall()
        records = []
        for run_id, created, kind, label, strategy, context, summary in rows:
            record = {"Run ID": run_id, "Saved At (IST)": pd.Timestamp(created).tz_convert("Asia/Kolkata").strftime("%Y-%m-%d %H:%M:%S"), "Type": kind, "Label": label, "Strategy": strategy}
            record.update(json.loads(context))
            metrics = json.loads(summary)
            aliases = {"Return [%]": "Return (%)", "Win Rate [%]": "Win Rate (%)", "# Trades": "Trades", "Max Drawdown [%]": "Max Drawdown (%)", "Buy & Hold Return [%]": "Buy & Hold Return (%)"}
            record.update({aliases.get(k, k): v for k, v in metrics.items()})
            records.append(record)
        return pd.DataFrame(records)

    def load_results(self, run_id):
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT results FROM backtest_runs WHERE id=?", (int(run_id),)).fetchone()
        return pd.DataFrame(json.loads(row[0])) if row else pd.DataFrame()
