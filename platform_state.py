"""Platform-wide rolling aggregation of Pump.fun activity.

This tracks the whole platform, not individual tokens: launch rate, migration
rate, how fast tokens are migrating, aggregate volume, active buyers and
buy/sell pressure over rolling time windows.
"""
from __future__ import annotations

import statistics
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class PlatformState:
    # event logs: each entry is a timestamp (seconds)
    creates: deque[float] = field(default_factory=lambda: deque(maxlen=20000))
    migrations: deque[float] = field(default_factory=lambda: deque(maxlen=5000))
    # migration speed samples: (ts_migrated, minutes_to_migrate)
    mig_speed: deque[tuple[float, float]] = field(default_factory=lambda: deque(maxlen=2000))
    # trades: (ts, sol, is_buy, trader)
    trades: deque[tuple[float, float, bool, str]] = field(default_factory=lambda: deque(maxlen=100000))

    # mint -> creation timestamp (to compute time-to-migrate); pruned by TTL
    created_at: dict[str, float] = field(default_factory=dict)

    # ---- ingest ----------------------------------------------------------

    def on_create(self, mint: str, ts: float | None = None) -> None:
        ts = ts or time.time()
        self.creates.append(ts)
        self.created_at[mint] = ts

    def on_migration(self, mint: str, ts: float | None = None) -> None:
        ts = ts or time.time()
        self.migrations.append(ts)
        launched = self.created_at.get(mint)
        if launched is not None and ts > launched:
            self.mig_speed.append((ts, (ts - launched) / 60.0))

    def on_trade(self, sol: float, is_buy: bool, trader: str, ts: float | None = None) -> None:
        self.trades.append((ts or time.time(), sol, is_buy, trader))

    # ---- rolling metrics -------------------------------------------------

    @staticmethod
    def _since(dq, seconds: float):
        cutoff = time.time() - seconds
        return [x for x in dq if (x[0] if isinstance(x, tuple) else x) >= cutoff]

    def launches_per_min(self, window_s: float = 300) -> float:
        n = len(self._since(self.creates, window_s))
        return n / (window_s / 60.0)

    def migrations_per_hour(self, window_s: float = 3600) -> float:
        n = len(self._since(self.migrations, window_s))
        return n / (window_s / 3600.0)

    def median_migration_speed_min(self, window_s: float = 3600) -> float | None:
        samples = [m for (t, m) in self.mig_speed if t >= time.time() - window_s]
        return statistics.median(samples) if samples else None

    def volume_sol(self, window_s: float = 300) -> float:
        return sum(sol for (t, sol, _b, _w) in self._since(self.trades, window_s))

    def unique_buyers(self, window_s: float = 300) -> int:
        return len({w for (t, _s, is_buy, w) in self._since(self.trades, window_s) if is_buy})

    def buy_sell_ratio(self, window_s: float = 300) -> float:
        w = self._since(self.trades, window_s)
        buys = sum(s for (_t, s, is_buy, _w) in w if is_buy)
        sells = sum(s for (_t, s, is_buy, _w) in w if not is_buy)
        return buys / sells if sells > 0 else (buys if buys else 0.0)

    def snapshot(self) -> dict:
        """Current metrics as a flat dict for storage / display."""
        return {
            "ts": time.time(),
            "launches_5m": round(self.launches_per_min(300), 2),
            "migrations_1h": round(self.migrations_per_hour(3600), 2),
            "mig_speed_min": self.median_migration_speed_min(3600),
            "vol_5m": round(self.volume_sol(300), 2),
            "buyers_5m": self.unique_buyers(300),
            "buy_sell": round(self.buy_sell_ratio(300), 2),
        }

    def prune(self, ttl_min: float) -> list[str]:
        """Drop created_at entries older than ttl; return the pruned mints."""
        cutoff = time.time() - ttl_min * 60
        stale = [m for m, t in self.created_at.items() if t < cutoff]
        for m in stale:
            del self.created_at[m]
        return stale
