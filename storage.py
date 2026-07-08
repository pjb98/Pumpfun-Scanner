"""SQLite persistence for platform-heat snapshots (stdlib only)."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    ts            REAL PRIMARY KEY,
    launches_5m   REAL,
    migrations_1h REAL,
    mig_speed_min REAL,
    vol_5m        REAL,
    buyers_5m     INTEGER,
    buy_sell      REAL,
    pf_froth      REAL,
    sol_price     REAL,
    sol_chg_24h   REAL,
    sol_vol_24h   REAL,
    sol_froth     REAL,
    heat          INTEGER
);
"""

# columns added after v1 — brought in for pre-existing DBs
_MIGRATION_COLS = {
    "pf_froth": "REAL",
    "sol_price": "REAL",
    "sol_chg_24h": "REAL",
    "sol_vol_24h": "REAL",
    "sol_froth": "REAL",
}

_INSERT_COLS = ("ts", "launches_5m", "migrations_1h", "mig_speed_min", "vol_5m",
                "buyers_5m", "buy_sell", "pf_froth", "sol_price", "sol_chg_24h",
                "sol_vol_24h", "sol_froth", "heat")


def _ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(snapshots)")}
    for col, typ in _MIGRATION_COLS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE snapshots ADD COLUMN {col} {typ}")
    conn.commit()


def connect(path: str | None = None) -> sqlite3.Connection:
    p = Path(path or config.DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    _ensure_columns(conn)
    return conn


def write_snapshot(conn: sqlite3.Connection, snap: dict, heat: int) -> None:
    row = {c: snap.get(c) for c in _INSERT_COLS}
    row["heat"] = heat
    placeholders = ", ".join(f":{c}" for c in _INSERT_COLS)
    conn.execute(
        f"INSERT OR REPLACE INTO snapshots ({', '.join(_INSERT_COLS)}) VALUES ({placeholders})",
        row,
    )
    conn.commit()


def recent(conn: sqlite3.Connection, hours: float) -> list[sqlite3.Row]:
    cutoff = time.time() - hours * 3600
    return conn.execute(
        "SELECT * FROM snapshots WHERE ts >= ? ORDER BY ts", (cutoff,)
    ).fetchall()


def all_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM snapshots ORDER BY ts").fetchall()
