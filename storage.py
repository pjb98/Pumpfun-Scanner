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
    heat          INTEGER
);
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    p = Path(path or config.DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def write_snapshot(conn: sqlite3.Connection, snap: dict, heat: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO snapshots "
        "(ts, launches_5m, migrations_1h, mig_speed_min, vol_5m, buyers_5m, buy_sell, heat) "
        "VALUES (:ts, :launches_5m, :migrations_1h, :mig_speed_min, :vol_5m, :buyers_5m, :buy_sell, :heat)",
        {**snap, "heat": heat},
    )
    conn.commit()


def recent(conn: sqlite3.Connection, hours: float) -> list[sqlite3.Row]:
    cutoff = time.time() - hours * 3600
    return conn.execute(
        "SELECT * FROM snapshots WHERE ts >= ? ORDER BY ts", (cutoff,)
    ).fetchall()


def all_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM snapshots ORDER BY ts").fetchall()
