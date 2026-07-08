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

import aiohttp
import websockets
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

import config
import heat as heat_mod
import market
import storage
from alerts import GoAlerter
from platform_state import PlatformState

console = Console()
STATE = PlatformState()
CONN = storage.connect()

SIGNAL_STYLE = {"GO": "bold white on green", "NEUTRAL": "black on yellow", "WAIT": "bold white on red"}

_last_snapshot = 0.0


def _fmt(v, suffix="", nd=1):
    return "—" if v is None else f"{v:.{nd}f}{suffix}"


def evaluate(sol: dict) -> tuple[dict, int, str, list[str], int]:
    """Compute current snapshot + heat once, for both display and alerting."""
    snap = STATE.snapshot()
    snap.update(sol)  # sol_price / sol_chg_24h / sol_vol_24h
    baseline = storage.recent(CONN, config.BASELINE_HOURS)
    heat, signal, reasons = heat_mod.compute(snap, baseline)  # fills snap['sol_froth']
    return snap, heat, signal, reasons, len(baseline)


def render(snap: dict, heat: int, signal: str, reasons: list[str], baseline_n: int) -> Panel:
    t = Table.grid(padding=(0, 2))
    t.add_column(justify="right", style="cyan")
    t.add_column()
    t.add_row("Launches", f"{_fmt(snap['launches_5m'])} /min")
    t.add_row("Migrations", f"{_fmt(snap['migrations_1h'])} /hr")
    t.add_row("Migration speed", f"{_fmt(snap['mig_speed_min'], ' min', 0)} (median)")
    t.add_row("Volume (5m)", f"{_fmt(snap['vol_5m'], ' SOL', 0)}")
    t.add_row("Active buyers (5m)", f"{snap['buyers_5m']}")
    t.add_row("Buy/sell", f"{_fmt(snap['buy_sell'], '', 2)}")
    t.add_row("Pump.fun froth", f"{_fmt(snap.get('pf_froth'), '', 1)}")
    sol_p, sol_c = snap.get("sol_price"), snap.get("sol_chg_24h")
    sol_line = "—" if sol_p is None else f"${sol_p:,.2f}  ({sol_c:+.1f}% 24h)"
    t.add_row("SOL price", sol_line)
    t.add_row("SOL froth", _fmt(snap.get("sol_froth"), "", 2))
    t.add_row("Tracked tokens", f"{len(STATE.created_at)}")

    why = ("  ·  ".join(reasons)) if reasons else "conditions near baseline"
    header = f"[{SIGNAL_STYLE.get(signal, '')}]  {signal}  [/]   heat {heat}/100"
    grid = Table.grid()
    grid.add_row(header)
    grid.add_row("")
    grid.add_row(t)
    grid.add_row("")
    grid.add_row(f"[dim]{why}[/]")
    base_note = "" if baseline_n >= config.MIN_BASELINE_SNAPSHOTS else \
        f"  [dim](cold start — using reference levels; {baseline_n}/{config.MIN_BASELINE_SNAPSHOTS} snapshots)[/]"
    grid.add_row(base_note)
    return Panel(grid, title="Pumpfun Platform Heat", border_style="cyan")


def maybe_snapshot(snap: dict, heat: int) -> None:
    global _last_snapshot
    now = time.time()
    if now - _last_snapshot < config.SNAPSHOT_INTERVAL_S:
        return
    _last_snapshot = now
    storage.write_snapshot(CONN, snap, heat)
    STATE.prune(config.TOKEN_TTL_MIN)


def ingest(msg: dict, subscribe_queue: list[str]) -> None:
    """Fold one PumpPortal message into platform state."""
    tx = msg.get("txType")
    mint = msg.get("mint")
    if tx == "create" and mint:
        STATE.on_create(mint)
        subscribe_queue.append(mint)  # queue trade-sub for this token
        sol = float(msg.get("solAmount", 0) or 0)
        if sol:
            STATE.on_trade(sol, True, msg.get("traderPublicKey", ""))
    elif tx in ("buy", "sell") and mint:
        STATE.on_trade(float(msg.get("solAmount", 0) or 0),
                       tx == "buy", msg.get("traderPublicKey", ""))
    elif (tx == "migrate" or msg.get("pool")) and mint:
        STATE.on_migration(mint)


async def consume(session: aiohttp.ClientSession, alerter: GoAlerter) -> None:
    async for ws in websockets.connect(config.PUMPPORTAL_WS_URL, ping_interval=20):
        try:
            await ws.send(json.dumps({"method": "subscribeNewToken"}))
            await ws.send(json.dumps({"method": "subscribeMigration"}))
            snap, heat, signal, reasons, bn = evaluate(await market.fetch_sol(session))
            with Live(render(snap, heat, signal, reasons, bn), console=console, refresh_per_second=1) as live:
                last_ui = 0.0
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    subs: list[str] = []
                    ingest(msg, subs)
                    for mint in subs:
                        await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint]}))

                    now = time.time()
                    if now - last_ui >= 1.0:      # throttle recompute/UI/alert to ~1Hz
                        last_ui = now
                        sol = await market.fetch_sol(session)  # cached, cheap
                        snap, heat, signal, reasons, bn = evaluate(sol)
                        maybe_snapshot(snap, heat)
                        live.update(render(snap, heat, signal, reasons, bn))
                        await alerter.maybe_alert(session, signal, snap, heat, reasons)
        except websockets.ConnectionClosed:
            console.print("[yellow]connection closed, reconnecting…[/]")
            continue


async def run() -> None:
    alerter = GoAlerter()
    async with aiohttp.ClientSession() as session:
        await consume(session, alerter)


def main() -> None:
    console.print("[bold cyan]Pumpfun Platform Heat[/] — connecting to PumpPortal…")
    console.print(f"[dim]logging snapshots to {config.DB_PATH} every {config.SNAPSHOT_INTERVAL_S}s[/]")
    if config.DISCORD_WEBHOOK_URL:
        console.print("[dim]Discord GO-alerts enabled[/]")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        console.print("\n[dim]stopped.[/]")


if __name__ == "__main__":
    main()
