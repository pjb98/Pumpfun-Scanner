"""Analyze recorded snapshots to find the best times to trade.

Groups your logged platform-heat history by hour-of-day (and day-of-week) and
shows where volume / migration flow / heat have historically been strongest.

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

import storage

console = Console()
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _heat_style(h: float) -> str:
    if h >= 65:
        return "bold green"
    if h >= 40:
        return "yellow"
    return "dim"


def hour_summary(rows) -> None:
    by_hour: dict[int, list] = defaultdict(list)
    for r in rows:
        by_hour[datetime.fromtimestamp(r["ts"]).hour].append(r)

    table = Table(title="Best times to trade — by hour of day (local time)")
    for c in ("Hour", "Samples", "Avg heat", "Avg vol 5m", "Migr/hr", "Mig speed", "Buyers 5m"):
        table.add_column(c)

    for h in range(24):
        rs = by_hour.get(h, [])
        if not rs:
            continue
        avg_heat = statistics.mean(x["heat"] for x in rs)
        speeds = [x["mig_speed_min"] for x in rs if x["mig_speed_min"] is not None]
        table.add_row(
            f"{h:02d}:00",
            str(len(rs)),
            f"[{_heat_style(avg_heat)}]{avg_heat:.0f}[/]",
            f"{statistics.mean(x['vol_5m'] for x in rs):.0f}",
            f"{statistics.mean(x['migrations_1h'] for x in rs):.1f}",
            f"{statistics.median(speeds):.0f}m" if speeds else "—",
            f"{statistics.mean(x['buyers_5m'] for x in rs):.0f}",
        )
    console.print(table)

    # headline: top 3 hours by average heat
    ranked = sorted(
        ((h, statistics.mean(x["heat"] for x in rs)) for h, rs in by_hour.items() if rs),
        key=lambda t: t[1], reverse=True,
    )
    if ranked:
        best = ", ".join(f"{h:02d}:00 ({v:.0f})" for h, v in ranked[:3])
        console.print(f"\n[bold green]Hottest hours:[/] {best}")


def dow_heatmap(rows) -> None:
    grid: dict[tuple[int, int], list] = defaultdict(list)
    for r in rows:
        dt = datetime.fromtimestamp(r["ts"])
        grid[(dt.weekday(), dt.hour)].append(r["heat"])

    table = Table(title="Avg heat — day-of-week x hour")
    table.add_column("Day")
    for h in range(24):
        table.add_column(f"{h:02d}")
    for d in range(7):
        cells = [DOW[d]]
        for h in range(24):
            vals = grid.get((d, h))
            if vals:
                m = statistics.mean(vals)
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
