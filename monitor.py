"""Pumpfun Scanner — live platform-heat monitor.

Streams the whole Pump.fun platform from PumpPortal, aggregates launch/migration/
volume/buyer activity, renders a live GO / NEUTRAL / WAIT panel, and logs a
snapshot to SQLite every minute so it can learn your best trading windows.

Run:  python monitor.py
"""
from __future__ import annotations

import asyncio
import json
import time

import websockets
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

import config
import heat as heat_mod
import storage
from platform_state import PlatformState

console = Console()
STATE = PlatformState()
CONN = storage.connect()

SIGNAL_STYLE = {"GO": "bold white on green", "NEUTRAL": "black on yellow", "WAIT": "bold white on red"}

_last_snapshot = 0.0
_last_heat = (0, "NEUTRAL", [])


def _fmt(v, suffix="", nd=1):
    return "—" if v is None else f"{v:.{nd}f}{suffix}"


def render() -> Panel:
    snap = STATE.snapshot()
    baseline = storage.recent(CONN, config.BASELINE_HOURS)
    heat, signal, reasons = heat_mod.compute(snap, baseline)
    global _last_heat
    _last_heat = (heat, signal, reasons)

    t = Table.grid(padding=(0, 2))
    t.add_column(justify="right", style="cyan")
    t.add_column()
    t.add_row("Launches", f"{_fmt(snap['launches_5m'])} /min")
    t.add_row("Migrations", f"{_fmt(snap['migrations_1h'])} /hr")
    t.add_row("Migration speed", f"{_fmt(snap['mig_speed_min'], ' min', 0)} (median)")
    t.add_row("Volume (5m)", f"{_fmt(snap['vol_5m'], ' SOL', 0)}")
    t.add_row("Active buyers (5m)", f"{snap['buyers_5m']}")
    t.add_row("Buy/sell", f"{_fmt(snap['buy_sell'], '', 2)}")
    t.add_row("Tracked tokens", f"{len(STATE.created_at)}")

    why = ("  ·  ".join(reasons)) if reasons else "conditions near baseline"
    header = f"[{SIGNAL_STYLE.get(signal, '')}]  {signal}  [/]   heat {heat}/100"
    grid = Table.grid()
    grid.add_row(header)
    grid.add_row("")
    grid.add_row(t)
    grid.add_row("")
    grid.add_row(f"[dim]{why}[/]")
    base_note = "" if len(baseline) >= config.MIN_BASELINE_SNAPSHOTS else \
        f"  [dim](cold start — using reference levels; {len(baseline)}/{config.MIN_BASELINE_SNAPSHOTS} snapshots)[/]"
    grid.add_row(base_note)
    return Panel(grid, title="Pumpfun Platform Heat", border_style="cyan")


def maybe_snapshot() -> None:
    global _last_snapshot
    now = time.time()
    if now - _last_snapshot < config.SNAPSHOT_INTERVAL_S:
        return
    _last_snapshot = now
    snap = STATE.snapshot()
    heat, _sig, _r = _last_heat
    storage.write_snapshot(CONN, snap, heat)
    STATE.prune(config.TOKEN_TTL_MIN)


async def consume() -> None:
    async for ws in websockets.connect(config.PUMPPORTAL_WS_URL, ping_interval=20):
        try:
            await ws.send(json.dumps({"method": "subscribeNewToken"}))
            await ws.send(json.dumps({"method": "subscribeMigration"}))
            with Live(render(), console=console, refresh_per_second=1) as live:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    tx = msg.get("txType")
                    mint = msg.get("mint")
                    if tx == "create" and mint:
                        STATE.on_create(mint)
                        # subscribe to this token's trades for platform-wide volume
                        await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint]}))
                        sol = float(msg.get("solAmount", 0) or 0)
                        if sol:
                            STATE.on_trade(sol, True, msg.get("traderPublicKey", ""))
                    elif tx in ("buy", "sell") and mint:
                        STATE.on_trade(float(msg.get("solAmount", 0) or 0),
                                       tx == "buy", msg.get("traderPublicKey", ""))
                    elif msg.get("txType") == "migrate" or "migration" in str(msg.get("pool", "")).lower():
                        if mint:
                            STATE.on_migration(mint)
                    maybe_snapshot()
                    live.update(render())
        except websockets.ConnectionClosed:
            console.print("[yellow]connection closed, reconnecting…[/]")
            continue


def main() -> None:
    console.print("[bold cyan]Pumpfun Platform Heat[/] — connecting to PumpPortal…")
    console.print(f"[dim]logging snapshots to {config.DB_PATH} every {config.SNAPSHOT_INTERVAL_S}s[/]")
    try:
        asyncio.run(consume())
    except KeyboardInterrupt:
        console.print("\n[dim]stopped.[/]")


if __name__ == "__main__":
    main()
