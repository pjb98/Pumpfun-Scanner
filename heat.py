"""Compute the composite platform-heat score and GO/NEUTRAL/WAIT signal.

Each metric is scored as a ratio against a baseline (the trailing median of your
own recorded history). On a cold start, before enough history exists, it falls
back to the REF_* reference levels in config. Migration *speed* is inverted:
faster migrations => hotter.
"""
from __future__ import annotations

import bisect
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


def signal_from_heat(heat100: int, go_cut: float | None = None,
                     wait_cut: float | None = None) -> str:
    """Map a 0-100 heat score to GO / NEUTRAL / WAIT.

    Uses the given GO/WAIT cutoffs when provided (adaptive banding), otherwise
    the fixed config thresholds.
    """
    go = config.GO_THRESHOLD if go_cut is None else go_cut
    wait = config.WAIT_THRESHOLD if wait_cut is None else wait_cut
    if heat100 >= go:
        return "GO"
    if heat100 < wait:
        return "WAIT"
    return "NEUTRAL"


def _pctl_value(sorted_heats: list[int], pct: float) -> float:
    """Linear-interpolated value at percentile `pct` (0-100) of a sorted list."""
    if not sorted_heats:
        return 0.0
    if len(sorted_heats) == 1:
        return float(sorted_heats[0])
    k = (len(sorted_heats) - 1) * pct / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_heats) - 1)
    return sorted_heats[lo] + (sorted_heats[hi] - sorted_heats[lo]) * (k - lo)


def percentile_rank(heat100: int, sorted_heats: list[int]) -> float | None:
    """Percentile (0-100) of `heat100` within the sorted heat history.

    `sorted_heats` MUST be pre-sorted ascending. Returns None until there is
    enough history (MIN_PERCENTILE_SAMPLES) to be meaningful. Uses the midpoint
    of the strictly-below and at-or-below ranks so ties land at their centre.
    """
    n = len(sorted_heats)
    if n < config.MIN_PERCENTILE_SAMPLES:
        return None
    lo = bisect.bisect_left(sorted_heats, heat100)
    hi = bisect.bisect_right(sorted_heats, heat100)
    return round(100.0 * (lo + hi) / 2 / n, 1)


def adaptive_bands(sorted_heats: list[int]) -> dict:
    """GO/WAIT cutoffs for the live signal, from the heat-history distribution.

    `sorted_heats` MUST be pre-sorted ascending. Below MIN_PERCENTILE_SAMPLES it
    falls back to the fixed config thresholds (adaptive=False). Once adaptive, the
    GO cutoff is floored at GO_ABS_FLOOR so a barely-warmer-than-dead market can't
    trip GO. Returns {go_cut, wait_cut, adaptive, n}.
    """
    n = len(sorted_heats)
    if n < config.MIN_PERCENTILE_SAMPLES:
        return {"go_cut": config.GO_THRESHOLD, "wait_cut": config.WAIT_THRESHOLD,
                "adaptive": False, "n": n}
    go = max(int(round(_pctl_value(sorted_heats, config.GO_PERCENTILE))), config.GO_ABS_FLOOR)
    wait = int(round(_pctl_value(sorted_heats, config.WAIT_PERCENTILE)))
    wait = min(wait, go)  # keep WAIT <= GO even if the floor lifts GO above it
    return {"go_cut": go, "wait_cut": wait, "adaptive": True, "n": n}


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


# Metric weights (sum with SOL_WEIGHT == 1.0). Migration flow, volume and
# pump.fun froth lead. Kept module-level so compute() and components() agree.
RATIO_WEIGHTS = {
    "migrations": 0.22,
    "volume": 0.20,
    "pf_froth": 0.18,   # frothy churn — your #1 lead
    "speed": 0.16,
    "buyers": 0.12,
}
SOL_WEIGHT = 0.12


def _ratios(snap: dict, baseline_rows) -> tuple[dict[str, float], float | None]:
    """Compute each metric's current/baseline ratio and the SOL froth score.

    Returns ({metric: raw_ratio}, sol_froth). Mutates `snap` to fill in the
    computed `sol_froth` for persistence. Shared by compute() and components()
    so the scoring math lives in exactly one place.
    """
    b_mig = _baseline(baseline_rows, "migrations_1h", config.REF_MIGRATIONS_PER_HOUR)
    b_speed = _baseline(baseline_rows, "mig_speed_min", config.REF_MIG_SPEED_MIN)
    b_vol = _baseline(baseline_rows, "vol_5m", config.REF_VOL_5M_SOL)
    b_buyers = _baseline(baseline_rows, "buyers_5m", config.REF_BUYERS_5M)
    b_pf = _baseline(baseline_rows, "pf_froth", config.REF_PF_FROTH)

    # speed inverted: lower minutes-to-migrate is hotter
    speed = snap.get("mig_speed_min")
    ratios = {
        "migrations": snap["migrations_1h"] / b_mig if b_mig else 0,
        "volume": snap["vol_5m"] / b_vol if b_vol else 0,
        "pf_froth": snap.get("pf_froth", 0) / b_pf if b_pf else 0,
        "speed": (b_speed / speed) if (speed and speed > 0) else 1.0,
        "buyers": snap["buyers_5m"] / b_buyers if b_buyers else 0,
    }

    # SOL market froth is already a 0..1 score; None => neutral (excluded from reasons)
    sol_froth = sol_market_froth(snap, baseline_rows)
    snap["sol_froth"] = sol_froth
    return ratios, sol_froth


def compute(snap: dict, baseline_rows,
            sorted_heats: list[int] | None = None) -> tuple[int, str, list[str]]:
    """Return (heat 0-100, signal, reasons). `baseline_rows` = recent snapshots.

    If `sorted_heats` (the ascending heat history) is given, the GO/WAIT signal
    uses adaptive percentile bands off that distribution; otherwise it uses the
    fixed config thresholds. Mutates `snap` to fill in `sol_froth` for persistence.
    """
    reasons: list[str] = []
    ratios, sol_froth = _ratios(snap, baseline_rows)
    sol_sub = 0.5 if sol_froth is None else sol_froth

    heat = sum(_sub(ratios[name]) * w for name, w in RATIO_WEIGHTS.items())
    heat += sol_sub * SOL_WEIGHT    # sol_froth: 0..1 already
    heat100 = int(round(heat * 100))

    if sorted_heats is None:
        signal = signal_from_heat(heat100)
    else:
        b = adaptive_bands(sorted_heats)
        signal = signal_from_heat(heat100, b["go_cut"], b["wait_cut"])

    for name in RATIO_WEIGHTS:
        r = ratios[name]
        if r >= 1.3:
            reasons.append(f"{name} hot ({r:.1f}x)")
        elif r <= 0.7:
            reasons.append(f"{name} cold ({r:.1f}x)")
    if sol_froth is not None:
        if sol_froth >= 0.65:
            reasons.append(f"SOL risk-on ({snap.get('sol_chg_24h', 0):+.1f}% 24h)")
        elif sol_froth <= 0.35:
            reasons.append(f"SOL risk-off ({snap.get('sol_chg_24h', 0):+.1f}% 24h)")

    return heat100, signal, reasons


def components(snap: dict, baseline_rows) -> list[dict]:
    """Per-metric breakdown of the current heat score, for the dashboard.

    Returns one dict per component (metrics + SOL froth), ordered by weight:
      name   — metric label
      ratio  — current/baseline ratio (None for sol_froth, which is a 0..1 score)
      sub    — 0..1 sub-score (how "full" this component is)
      weight — its share of the 0..1 heat total
      points — its actual contribution to the 0..100 heat (sub * weight * 100)
    The points sum to the same heat compute() reports.
    """
    ratios, sol_froth = _ratios(snap, baseline_rows)
    out: list[dict] = []
    for name, w in RATIO_WEIGHTS.items():
        sub = _sub(ratios[name])
        out.append({
            "name": name,
            "ratio": round(ratios[name], 2),
            "sub": round(sub, 3),
            "weight": w,
            "points": round(sub * w * 100, 1),
        })
    sol_sub = 0.5 if sol_froth is None else sol_froth
    out.append({
        "name": "sol_froth",
        "ratio": None,
        "sub": round(sol_sub, 3),
        "weight": SOL_WEIGHT,
        "points": round(sol_sub * SOL_WEIGHT * 100, 1),
    })
    return out
