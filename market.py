"""SOL market data from CoinGecko's public API (no key required).

Fetches SOL spot price, 24h % change and 24h volume (USD), cached so we don't
hammer the endpoint. Never raises — on failure it returns the last good value
(or Nones), so the monitor keeps running.

CoinGecko is used instead of Binance because Binance geo-blocks many cloud/IP
regions (HTTP 451). Override SOL_PRICE_URL to swap providers, but note the
parser below expects the CoinGecko `simple/price` response shape.
"""
from __future__ import annotations

import time

import aiohttp

import config

_cache: dict = {"ts": 0.0, "data": None}
_EMPTY = {"sol_price": None, "sol_chg_24h": None, "sol_vol_24h": None}


async def fetch_sol(session: aiohttp.ClientSession) -> dict:
    now = time.time()
    if _cache["data"] and now - _cache["ts"] < config.SOL_FETCH_INTERVAL_S:
        return _cache["data"]
    try:
        async with session.get(
            config.SOL_PRICE_URL, timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            sol = (await r.json())["solana"]
        data = {
            "sol_price": float(sol["usd"]),
            "sol_chg_24h": float(sol["usd_24h_change"]),
            "sol_vol_24h": float(sol["usd_24h_vol"]),
        }
        _cache.update(ts=now, data=data)
    except Exception:
        pass  # keep last good value
    return _cache["data"] or dict(_EMPTY)
