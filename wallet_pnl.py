"""Track your own wallet's realized/unrealized P&L (SolanaTracker), for the dashboard.

This is the "self-improving toward what's *profitable*" complement to the heat
signal: instead of only asking "is the platform statistically hot", it surfaces
whether the trades actually made money.

Owned by the dashboard (stdlib only — urllib, no aiohttp) so the live heat
monitor / alert path is never touched. It caches to a JSON file and only calls
the quota-limited SolanaTracker endpoint when that cache is older than
WALLET_PNL_TTL_S, so a browser refreshing every 15s still makes ~48 calls/day.
Every failure mode degrades to the last good cache (marked stale) or an inert
"disabled/error" state — it can never raise into the dashboard.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import config

_LOCK = threading.Lock()


def _cache_path() -> Path:
    return Path(config.DB_PATH).parent / "wallet_pnl.json"


def _load_cache() -> dict:
    try:
        return json.loads(_cache_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_cache(data: dict) -> None:
    p = _cache_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(p)  # atomic swap so a reader never sees a half-written file


def _fetch_raw() -> dict:
    """GET /pnl/{wallet} from SolanaTracker. Raises on network/HTTP/JSON error."""
    url = f"{config.SOLANATRACKER_BASE}/pnl/{config.WALLET_ADDRESS}"
    req = urllib.request.Request(url, headers={"x-api-key": config.SOLANATRACKER_API_KEY})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode())


def _summarize(raw: dict) -> dict:
    """Reduce the full SolanaTracker payload to the compact shape the dashboard needs."""
    s = raw.get("summary") or {}
    tokens = raw.get("tokens") or {}

    # Rank open positions and closed trades by dollar P&L for the movers lists.
    movers = []
    for mint, t in tokens.items():
        movers.append({
            "mint": mint,
            "total": t.get("total"),
            "realized": t.get("realized"),
            "unrealized": t.get("unrealized"),
            "holding": bool(t.get("holding")),
            "invested": t.get("total_invested"),
        })
    ranked = [m for m in movers if m["total"] is not None]
    ranked.sort(key=lambda m: m["total"], reverse=True)
    n = config.WALLET_PNL_TOP_N
    winners = [m for m in ranked if (m["total"] or 0) > 0][:n]
    losers = [m for m in ranked if (m["total"] or 0) < 0][-n:][::-1]

    return {
        "realized": s.get("realized"),
        "unrealized": s.get("unrealized"),
        "total": s.get("total"),
        "total_invested": s.get("totalInvested"),
        "wins": s.get("totalWins"),
        "losses": s.get("totalLosses"),
        "win_pct": s.get("winPercentage"),
        "tokens": len(tokens),
        "winners": winners,
        "losers": losers,
    }


def _refresh(cache: dict) -> dict:
    """Fetch fresh P&L, append a trend point, persist, and return the new cache."""
    summary = _summarize(_fetch_raw())
    now = time.time()

    history = cache.get("history") or []
    history.append({
        "t": now,
        "total": summary["total"],
        "realized": summary["realized"],
        "unrealized": summary["unrealized"],
    })
    history = history[-config.WALLET_PNL_HISTORY_MAX:]

    data = {
        "wallet": config.WALLET_ADDRESS,
        "fetched": now,
        "summary": summary,
        "history": history,
    }
    _save_cache(data)
    return data


def state() -> dict:
    """Dashboard entry point. Returns a P&L payload that is always safe to render.

    status is one of:
      disabled  — no wallet / key configured
      ok        — fresh data (age <= TTL)
      stale     — cache present but older than TTL (a refresh failed)
      error     — no cache and the first fetch failed
    """
    if not (config.WALLET_ADDRESS and config.SOLANATRACKER_API_KEY):
        return {"status": "disabled"}

    with _LOCK:  # serialise so concurrent requests don't stampede the API
        cache = _load_cache()
        fresh = cache and (time.time() - cache.get("fetched", 0) < config.WALLET_PNL_TTL_S)
        # Wallet changed since the cache was written? Treat it as empty.
        if cache and cache.get("wallet") != config.WALLET_ADDRESS:
            cache, fresh = {}, False

        if fresh:
            return {"status": "ok", **cache}
        try:
            data = _refresh(cache)
            return {"status": "ok", **data}
        except (urllib.error.URLError, ValueError, OSError, TimeoutError) as e:
            if cache:
                return {"status": "stale", "error": str(e), **cache}
            return {"status": "error", "error": str(e)}
