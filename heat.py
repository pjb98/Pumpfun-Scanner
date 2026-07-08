"""Compute the composite platform-heat score and GO/NEUTRAL/WAIT signal.

Each metric is scored as a ratio against a baseline (the trailing median of your
own recorded history). On a cold start, before enough history exists, it falls
back to the REF_* reference levels in config. Migration *speed* is inverted:
faster migrations => hotter.
"""
from __future__ import annotations

import statistics

import config


def _baseline(rows, key: str, ref: float) -> float:
    vals = [r[key] for r in rows if r[key] is not None]
    if len(vals) >= config.MIN_BASELINE_SNAPSHOTS:
        med = statistics.median(vals)
        return med if med > 0 else ref
    return ref


def _sub(ratio: float) -> float:
    """Map a current/baseline ratio to a 0..1 sub-score (1.0 = 2x baseline)."""
    return max(0.0, min(1.0, ratio / 2.0))


def compute(snap: dict, baseline_rows) -> tuple[int, str, list[str]]:
    """Return (heat 0-100, signal, reasons). `baseline_rows` = recent snapshots."""
    reasons: list[str] = []

    b_launch = _baseline(baseline_rows, "launches_5m", config.REF_LAUNCHES_PER_MIN)
    b_mig = _baseline(baseline_rows, "migrations_1h", config.REF_MIGRATIONS_PER_HOUR)
    b_speed = _baseline(baseline_rows, "mig_speed_min", config.REF_MIG_SPEED_MIN)
    b_vol = _baseline(baseline_rows, "vol_5m", config.REF_VOL_5M_SOL)
    b_buyers = _baseline(baseline_rows, "buyers_5m", config.REF_BUYERS_5M)

    launch_r = snap["launches_5m"] / b_launch if b_launch else 0
    mig_r = snap["migrations_1h"] / b_mig if b_mig else 0
    vol_r = snap["vol_5m"] / b_vol if b_vol else 0
    buyers_r = snap["buyers_5m"] / b_buyers if b_buyers else 0
    # speed inverted: lower minutes-to-migrate is hotter
    speed = snap.get("mig_speed_min")
    speed_r = (b_speed / speed) if (speed and speed > 0) else 1.0

    # weighted composite (migration flow + volume weighted highest)
    weights = {
        "migrations": (mig_r, 0.28),
        "volume": (vol_r, 0.24),
        "speed": (speed_r, 0.20),
        "buyers": (buyers_r, 0.16),
        "launches": (launch_r, 0.12),
    }
    heat = sum(_sub(r) * w for (r, w) in weights.values()) / sum(w for (_r, w) in weights.values())
    heat100 = int(round(heat * 100))

    for name, (r, _w) in weights.items():
        if r >= 1.3:
            reasons.append(f"{name} hot ({r:.1f}x)")
        elif r <= 0.7:
            reasons.append(f"{name} cold ({r:.1f}x)")

    if heat100 >= config.GO_THRESHOLD:
        signal = "GO"
    elif heat100 < config.WAIT_THRESHOLD:
        signal = "WAIT"
    else:
        signal = "NEUTRAL"

    return heat100, signal, reasons
