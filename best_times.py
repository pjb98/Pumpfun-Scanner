"""Analyze recorded snapshots to find the best times to trade.

Groups your logged platform-heat history by hour-of-day (and day-of-week) and
shows where heat / volume / migration flow / froth have historically been
strongest.

Thin hours are handled with empirical-Bayes shrinkage: an hour's heat is pulled
toward the global mean in proportion to how few samples it has, so an hour seen
only a couple of times can't rank as falsely hot. A confidence marker reflects
sample count.

Run:  python best_times.py            # hour-of-day summary
      python best_times.py --dow      # add day-of-week x hour heatmap
"""
from __future__ import annotations

import argparse
import statistics
from collections import defaultdict
from datetime import datetime

from rich.console import Console
from rich.table import Table

import config
import storage

console = Console()
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _heat_style(h: float) -> str:
    if h >= 65:
        return "bold green"
    if h >= 40:
        return "yellow"
    return "dim"


def _confidence(n: int) -> str:
    """Sample-count confidence marker."""
    if n >= config.BEST_TIMES_MIN_SAMPLES * 3:
        return "[green]███[/] high"
    if n >= config.BEST_TIMES_MIN_SAMPLES:
        return "[yellow]██[/dim] med"
    return "[dim]█  low[/]"


def _shrunk(hour_mean: float, n: int, global_mean: float) -> float:
    """Empirical-Bayes: pull hour_mean toward global_mean by k pseudo-samples."""
    k = config.BEST_TIMES_SHRINKAGE
    return (n * hour_mean + k * global_mean) / (n + k)


def _mean(rows, key: str):
    vals = [r[key] for r in rows if r[key] is not None]
    return statistics.mean(vals) if vals else None


def hour_summary(rows) -> None:
    by_hour: dict[int, list] = defaultdict(list)
    for r in rows:
        by_hour[datetime.fromtimestamp(r["ts"]).hour].append(r)

    global_heat = statistics.mean(r["heat"] for r in rows)

    table = Table(title="Best times to trade — by hour of day (local time)")
    for c in ("Hour", "Samples", "Conf", "Heat*", "Raw", "Vol 5m",
              "Migr/hr", "Mig speed", "Buyers", "PF froth", "SOL froth"):
        table.add_column(c)

    ranked = []
    for h in range(24):
        rs = by_hour.get(h, [])
        if not rs:
            continue
        n = len(rs)
        raw = statistics.mean(x["heat"] for x in rs)
        adj = _shrunk(raw, n, global_heat)
        ranked.append((h, adj, n))

        speeds = [x["mig_speed_min"] for x in rs if x["mig_speed_min"] is not None]
        pf = _mean(rs, "pf_froth")
        solf = _mean(rs, "sol_froth")
        table.add_row(
            f"{h:02d}:00",
            str(n),
            _confidence(n),
            f"[{_heat_style(adj)}]{adj:.0f}[/]",
            f"[dim]{raw:.0f}[/]",
            f"{statistics.mean(x['vol_5m'] for x in rs):.0f}",
            f"{statistics.mean(x['migrations_1h'] for x in rs):.1f}",
            f"{statistics.median(speeds):.0f}m" if speeds else "—",
            f"{statistics.mean(x['buyers_5m'] for x in rs):.0f}",
            f"{pf:.0f}" if pf is not None else "—",
            f"{solf:.2f}" if solf is not None else "—",
        )
    console.print(table)
    console.print("[dim]Heat* = confidence-adjusted (shrunk toward global mean); Raw = unadjusted[/]")

    # headline: top hours by *adjusted* heat, among those with enough samples
    solid = [(h, a, n) for (h, a, n) in ranked if n >= config.BEST_TIMES_MIN_SAMPLES]
    pool = solid or ranked
    top = sorted(pool, key=lambda t: t[1], reverse=True)[:3]
    if top:
        best = ", ".join(f"{h:02d}:00 ({a:.0f})" for h, a, _n in top)
        note = "" if solid else " [dim](low confidence — keep collecting)[/]"
        console.print(f"\n[bold green]Hottest hours:[/] {best}{note}")


def dow_heatmap(rows) -> None:
    grid: dict[tuple[int, int], list] = defaultdict(list)
    for r in rows:
        dt = datetime.fromtimestamp(r["ts"])
        grid[(dt.weekday(), dt.hour)].append(r["heat"])
    global_heat = statistics.mean(r["heat"] for r in rows)

    table = Table(title="Confidence-adjusted heat — day-of-week x hour")
    table.add_column("Day")
    for h in range(24):
        table.add_column(f"{h:02d}")
    for d in range(7):
        cells = [DOW[d]]
        for h in range(24):
            vals = grid.get((d, h))
            if vals:
                m = _shrunk(statistics.mean(vals), len(vals), global_heat)
                cells.append(f"[{_heat_style(m)}]{m:.0f}[/]")
            else:
                cells.append("·")
        table.add_row(*cells)
    console.print(table)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dow", action="store_true", help="also show day-of-week x hour heatmap")
    args = ap.parse_args()

    conn = storage.connect()
    rows = storage.all_rows(conn)
    if not rows:
        console.print("[yellow]No snapshots yet. Run monitor.py for a while to collect history.[/]")
        return
    span_h = (rows[-1]["ts"] - rows[0]["ts"]) / 3600
    console.print(f"[dim]{len(rows)} snapshots over {span_h:.1f}h[/]\n")
    hour_summary(rows)
    if args.dow:
        console.print()
        dow_heatmap(rows)


if __name__ == "__main__":
    main()
