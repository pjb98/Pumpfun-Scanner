"""In-memory per-token state and the pre-migration score."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

import config


@dataclass
class Trade:
    ts: float
    is_buy: bool
    sol: float
    trader: str


@dataclass
class TokenState:
    mint: str
    symbol: str = "?"
    name: str = "?"
    created_at: float = field(default_factory=time.time)

    sol_in_curve: float = 0.0
    last_bonded_pct: float = 0.0
    bonded_at: dict[int, float] = field(default_factory=dict)  # milestone% -> timestamp

    trades: deque[Trade] = field(default_factory=lambda: deque(maxlen=2000))
    buyers: set[str] = field(default_factory=set)

    dev: str | None = None
    dev_sold: bool = False

    has_socials: bool = False

    # ---- derived metrics -------------------------------------------------

    @property
    def bonded_pct(self) -> float:
        return min(100.0, 100.0 * self.sol_in_curve / config.CURVE_TARGET_SOL)

    @property
    def age_min(self) -> float:
        return (time.time() - self.created_at) / 60.0

    def _window(self, seconds: float) -> list[Trade]:
        cutoff = time.time() - seconds
        return [t for t in self.trades if t.ts >= cutoff]

    def volume_sol(self, seconds: float) -> float:
        return sum(t.sol for t in self._window(seconds))

    def unique_buyers(self, seconds: float) -> int:
        return len({t.trader for t in self._window(seconds) if t.is_buy})

    def buy_sell_ratio(self, seconds: float = 300) -> float:
        w = self._window(seconds)
        buys = sum(t.sol for t in w if t.is_buy)
        sells = sum(t.sol for t in w if not t.is_buy)
        return buys / sells if sells > 0 else (buys if buys else 0.0)

    def bonding_speed(self, seconds: float = 300) -> float:
        """Bonded-% gained over the last `seconds` (proxy via SOL flow)."""
        net_sol = sum((t.sol if t.is_buy else -t.sol) for t in self._window(seconds))
        return 100.0 * net_sol / config.CURVE_TARGET_SOL

    # ---- record a trade --------------------------------------------------

    def apply_trade(self, t: Trade) -> None:
        self.trades.append(t)
        if t.is_buy:
            self.buyers.add(t.trader)
            self.sol_in_curve += t.sol
        else:
            self.sol_in_curve = max(0.0, self.sol_in_curve - t.sol)
            if t.trader == self.dev:
                self.dev_sold = True

        pct = self.bonded_pct
        for milestone in (25, 50, 75, 90):
            if pct >= milestone and milestone not in self.bonded_at:
                self.bonded_at[milestone] = t.ts
        self.last_bonded_pct = pct


def score(tok: TokenState) -> tuple[int, str, list[str]]:
    """Return (score 0-100, label, reasons)."""
    pts = 0.0
    reasons: list[str] = []

    speed = tok.bonding_speed(300)
    if speed > 5:
        pts += 25; reasons.append(f"curve accelerating (+{speed:.0f}%/5m)")
    elif speed > 1:
        pts += 12
    elif speed < 0:
        pts -= 15; reasons.append("curve reversing")

    buyers = tok.unique_buyers(300)
    if buyers >= 75:
        pts += 20; reasons.append(f"{buyers} buyers/5m")
    elif buyers >= 30:
        pts += 10

    ratio = tok.buy_sell_ratio()
    if ratio >= 2.0:
        pts += 15; reasons.append(f"buy/sell {ratio:.1f}")
    elif ratio >= 1.2:
        pts += 7
    elif ratio < 0.8:
        pts -= 10; reasons.append("net selling")

    if tok.volume_sol(300) >= 20:
        pts += 10

    if tok.has_socials:
        pts += 10; reasons.append("has socials")

    if tok.dev and not tok.dev_sold:
        pts += 10; reasons.append("dev holding")
    elif tok.dev_sold:
        pts -= 20; reasons.append("DEV SOLD")

    pts = max(0.0, min(100.0, pts))

    if tok.dev_sold:
        label = "TOXIC"
    elif pts >= config.SCORE_TRADE_THRESHOLD:
        label = "TRADE"
    elif pts >= config.SCORE_WATCH_THRESHOLD:
        label = "WATCH"
    else:
        label = "AVOID"

    return int(round(pts)), label, reasons
