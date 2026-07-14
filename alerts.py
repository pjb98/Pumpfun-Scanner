"""Discord alerting on platform-signal transitions.

Fires on two edges:
  • rising  — into GO           (conditions turned good: consider trading)
  • falling — out of GO         (GO -> NEUTRAL/WAIT: conditions cooling, ease off)

Only the *edges* alert (not every tick while a state holds), each direction has
its own cooldown so an entry alert never suppresses a later exit alert, and any
webhook error is swallowed so alerting can't crash the monitor.
"""
from __future__ import annotations

import time

import config


class GoAlerter:
    def __init__(self, webhook_url: str = "", cooldown_min: float | None = None):
        self.webhook_url = webhook_url or config.DISCORD_WEBHOOK_URL
        self.cooldown_s = (cooldown_min if cooldown_min is not None
                           else config.GO_ALERT_COOLDOWN_MIN) * 60
        self.prev_signal: str | None = None
        self.last_fired: dict[str, float] = {"GO": 0.0, "COOL": 0.0}

    def _cooled(self, kind: str) -> bool:
        return (time.time() - self.last_fired[kind]) >= self.cooldown_s

    def _fields(self, snap: dict) -> list[dict]:
        speed = snap.get("mig_speed_min")
        sol_p, sol_c = snap.get("sol_price"), snap.get("sol_chg_24h")
        sol = "—" if sol_p is None else f"${sol_p:,.2f} ({sol_c:+.1f}%)"
        return [
            {"name": "Heat", "value": f"**{snap.get('_heat', '?')}/100**", "inline": True},
            {"name": "Migrations", "value": f"{snap['migrations_1h']:.0f}/hr", "inline": True},
            {"name": "Mig speed", "value": (f"{speed:.0f} min" if speed else "—"), "inline": True},
            {"name": "Volume 5m", "value": f"{snap['vol_5m']:.0f} SOL", "inline": True},
            {"name": "PF froth", "value": f"{snap.get('pf_froth', 0):.0f}", "inline": True},
            {"name": "SOL", "value": sol, "inline": True},
        ]

    def _payload(self, title: str, color: int, desc: str, snap: dict, heat: int) -> dict:
        snap = {**snap, "_heat": heat}
        return {"embeds": [{
            "title": title, "description": desc, "color": color,
            "fields": self._fields(snap), "footer": {"text": "Pumpfun Scanner"},
        }]}

    async def _post(self, session, payload: dict) -> bool:
        try:
            async with session.post(self.webhook_url, json=payload) as resp:
                return resp.status < 300
        except Exception:
            return False

    async def maybe_alert(self, session, signal: str, snap: dict, heat: int, reasons: list[str]) -> str | None:
        """Send a Discord alert on a GO entry/exit edge. Returns 'GO', 'COOL', or None."""
        fired: str | None = None
        why = "  ·  ".join(reasons) if reasons else "conditions near baseline"
        if self.webhook_url:
            rising = signal == "GO" and self.prev_signal != "GO"
            falling = self.prev_signal == "GO" and signal != "GO"
            if rising and self._cooled("GO"):
                if await self._post(session, self._payload(
                        "🟢 Pump.fun heat: GO", 0x2ECC71, why, snap, heat)):
                    self.last_fired["GO"] = time.time(); fired = "GO"
            elif falling and self._cooled("COOL"):
                if await self._post(session, self._payload(
                        f"🔴 Pump.fun heat cooling (GO → {signal})", 0xE74C3C, why, snap, heat)):
                    self.last_fired["COOL"] = time.time(); fired = "COOL"
        self.prev_signal = signal
        return fired
