"""Pumpfun Scanner — live pre-migration token scanner.

Connects to the PumpPortal free WebSocket feed, tracks each token's bonding
curve / volume / buyers / dev behavior in memory, scores them, and renders a
live TRADE/WATCH/AVOID/TOXIC table.

Run:  python scanner.py
"""
from __future__ import annotations

import asyncio
import json
import time

import websockets
from rich.console import Console
from rich.live import Live
from rich.table import Table

import config
from token_state import TokenState, Trade, score

console = Console()
TOKENS: dict[str, TokenState] = {}

LABEL_STYLE = {
    "TRADE": "bold green",
    "WATCH": "yellow",
    "AVOID": "dim",
    "TOXIC": "bold red",
}


def _has_socials(payload: dict) -> bool:
    return any(payload.get(k) for k in ("twitter", "telegram", "website"))


def handle_new_token(msg: dict) -> None:
    mint = msg.get("mint")
    if not mint:
        return
    tok = TOKENS.setdefault(mint, TokenState(mint=mint))
    tok.symbol = msg.get("symbol", tok.symbol)
    tok.name = msg.get("name", tok.name)
    tok.dev = msg.get("traderPublicKey", tok.dev)
    tok.has_socials = _has_socials(msg)
    # Initial dev buy, if present in the create event.
    sol = float(msg.get("solAmount", 0) or 0)
    if sol:
        tok.apply_trade(Trade(ts=time.time(), is_buy=True, sol=sol, trader=tok.dev or ""))


def handle_trade(msg: dict) -> None:
    mint = msg.get("mint")
    if not mint or mint not in TOKENS:
        return
    tok = TOKENS[mint]
    sol = float(msg.get("solAmount", 0) or 0)
    is_buy = msg.get("txType") == "buy"
    trader = msg.get("traderPublicKey", "")
    tok.apply_trade(Trade(ts=time.time(), is_buy=is_buy, sol=sol, trader=trader))


def render_table() -> Table:
    table = Table(title="Pumpfun Scanner — pre-migration", expand=True)
    for col in ("Token", "Age", "Bonded", "5m Vol", "Buyers", "B/S", "Dev", "Social", "Score", "Label"):
        table.add_column(col)

    rows = []
    for tok in TOKENS.values():
        if not (config.MIN_BONDED_PCT <= tok.bonded_pct <= config.MAX_BONDED_PCT):
            continue
        pts, label, _ = score(tok)
        rows.append((pts, tok, label))

    rows.sort(key=lambda r: r[0], reverse=True)
    for pts, tok, label in rows[:25]:
        table.add_row(
            tok.symbol,
            f"{tok.age_min:.0f}m",
            f"{tok.bonded_pct:.0f}%",
            f"{tok.volume_sol(300):.0f}",
            str(tok.unique_buyers(300)),
            f"{tok.buy_sell_ratio():.1f}",
            "sold" if tok.dev_sold else "hold",
            "yes" if tok.has_socials else "—",
            str(pts),
            f"[{LABEL_STYLE.get(label, '')}]{label}[/]",
        )
    return table


async def consume() -> None:
    async for ws in websockets.connect(config.PUMPPORTAL_WS_URL, ping_interval=20):
        try:
            await ws.send(json.dumps({"method": "subscribeNewToken"}))
            await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": []}))
            with Live(render_table(), console=console, refresh_per_second=2) as live:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    tx = msg.get("txType")
                    if tx == "create":
                        handle_new_token(msg)
                    elif tx in ("buy", "sell"):
                        handle_trade(msg)
                    live.update(render_table())
        except websockets.ConnectionClosed:
            console.print("[yellow]connection closed, reconnecting…[/]")
            continue


def main() -> None:
    console.print("[bold cyan]Pumpfun Scanner[/] starting — connecting to PumpPortal…")
    try:
        asyncio.run(consume())
    except KeyboardInterrupt:
        console.print("\n[dim]stopped.[/]")


if __name__ == "__main__":
    main()
