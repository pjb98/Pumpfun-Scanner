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


def sol_market_froth(snap: dict, baseline_rows) -> float | None:
    """SOL market froth in 0..1 from 24h momentum + 24h volume vs baseline.

    Rising price on rising volume = frothy/risk-on. Returns None if SOL data
    is unavailable (caller treats that as neutral).
    """
    chg = snap.get("sol_chg_24h")
    vol = snap.get("sol_vol_24h")
    if chg is None:
        return None
    # momentum: -10% -> 0.0, 0% -> 0.5, +10% -> 1.0
    momentum = max(0.0, min(1.0, 0.5 + chg / 20.0))
    b_vol = _baseline(baseline_rows, "sol_vol_24h", config.REF_SOL_VOL_24H)
    vol_score = _sub(vol / b_vol) if (vol and b_vol) else 0.5
    return round(0.6 * momentum + 0.4 * vol_score, 3)


def compute(snap: dict, baseline_rows) -> tuple[int, str, list[str]]:
    """Return (heat 0-100, signal, reasons). `baseline_rows` = recent snapshots.

    Mutates `snap` to fill in the computed `sol_froth` for persistence.
    """
    reasons: list[str] = []

    b_mig = _baseline(baseline_rows, "migrations_1h", config.REF_MIGRATIONS_PER_HOUR)
    b_speed = _baseline(baseline_rows, "mig_speed_min", config.REF_MIG_SPEED_MIN)
    b_vol = _baseline(baseline_rows, "vol_5m", config.REF_VOL_5M_SOL)
    b_buyers = _baseline(baseline_rows, "buyers_5m", config.REF_BUYERS_5M)
    b_pf = _baseline(baseline_rows, "pf_froth", config.REF_PF_FROTH)

    mig_r = snap["migrations_1h"] / b_mig if b_mig else 0
    vol_r = snap["vol_5m"] / b_vol if b_vol else 0
    buyers_r = snap["buyers_5m"] / b_buyers if b_buyers else 0
    pf_r = snap.get("pf_froth", 0) / b_pf if b_pf else 0
    # speed inverted: lower minutes-to-migrate is hotter
    speed = snap.get("mig_speed_min")
    speed_r = (b_speed / speed) if (speed and speed > 0) else 1.0

    # SOL market froth is already a 0..1 score; None => neutral 0.5 (and excluded from reasons)
    sol_froth = sol_market_froth(snap, baseline_rows)
    snap["sol_froth"] = sol_froth
    sol_sub = 0.5 if sol_froth is None else sol_froth

    # (sub-score 0..1, weight). Migration flow, volume and pump.fun froth lead.
    ratio_parts = {
        "migrations": (mig_r, 0.22),
        "volume": (vol_r, 0.20),
        "pf_froth": (pf_r, 0.18),   # frothy churn — your #1 lead
        "speed": (speed_r, 0.16),
        "buyers": (buyers_r, 0.12),
    }
    heat = sum(_sub(r) * w for (r, w) in ratio_parts.values())
    heat += sol_sub * 0.12          # sol_froth: 0..1 already, weight 0.12
    heat100 = int(round(heat * 100))

    for name, (r, _w) in ratio_parts.items():
        if r >= 1.3:
            reasons.append(f"{name} hot ({r:.1f}x)")
        elif r <= 0.7:
            reasons.append(f"{name} cold ({r:.1f}x)")
    if sol_froth is not None:
        if sol_froth >= 0.65:
            reasons.append(f"SOL risk-on ({snap.get('sol_chg_24h', 0):+.1f}% 24h)")
        elif sol_froth <= 0.35:
            reasons.append(f"SOL risk-off ({snap.get('sol_chg_24h', 0):+.1f}% 24h)")

    if heat100 >= config.GO_THRESHOLD:
        signal = "GO"
    elif heat100 < config.WAIT_THRESHOLD:
        signal = "WAIT"
    else:
        signal = "NEUTRAL"

    return heat100, signal, reasons
