"""Discord alerting — fires when the platform signal flips into GO."""
from __future__ import annotations

import time

import config


class GoAlerter:
    """Fires a Discord webhook on a NEUTRAL/WAIT -> GO transition, with a cooldown.

    Only alerts on the *rising edge* into GO (not every tick while GO), and never
    more than once per GO_ALERT_COOLDOWN_MIN to avoid flapping near the threshold.
    """

    def __init__(self, webhook_url: str = "", cooldown_min: float | None = None):
        self.webhook_url = webhook_url or config.DISCORD_WEBHOOK_URL
        self.cooldown_s = (cooldown_min if cooldown_min is not None
                           else config.GO_ALERT_COOLDOWN_MIN) * 60
        self.prev_signal: str | None = None
        self.last_fired: float = 0.0

    def _should_fire(self, signal: str) -> bool:
        rising_edge = signal == "GO" and self.prev_signal != "GO"
        cooled = (time.time() - self.last_fired) >= self.cooldown_s
        return bool(self.webhook_url) and rising_edge and cooled

    def _payload(self, snap: dict, heat: int, reasons: list[str]) -> dict:
        speed = snap.get("mig_speed_min")
        fields = [
            {"name": "Heat", "value": f"**{heat}/100**", "inline": True},
            {"name": "Migrations", "value": f"{snap['migrations_1h']:.0f}/hr", "inline": True},
            {"name": "Mig speed", "value": (f"{speed:.0f} min" if speed else "—"), "inline": True},
            {"name": "Volume 5m", "value": f"{snap['vol_5m']:.0f} SOL", "inline": True},
            {"name": "Buyers 5m", "value": f"{snap['buyers_5m']}", "inline": True},
            {"name": "Launches", "value": f"{snap['launches_5m']:.0f}/min", "inline": True},
        ]
        desc = "  ·  ".join(reasons) if reasons else "conditions above baseline"
        return {
            "embeds": [{
                "title": "🟢 Pump.fun heat: GO",
                "description": desc,
                "color": 0x2ECC71,
                "fields": fields,
                "footer": {"text": "Pumpfun Scanner"},
            }]
        }

    async def maybe_alert(self, session, signal: str, snap: dict, heat: int, reasons: list[str]) -> bool:
        """Send a Discord alert if we just entered GO. Returns True if sent."""
        fired = False
        if self._should_fire(signal):
            try:
                async with session.post(self.webhook_url, json=self._payload(snap, heat, reasons)) as resp:
                    fired = resp.status < 300
            except Exception:
                fired = False  # never let alerting crash the monitor
            if fired:
                self.last_fired = time.time()
        self.prev_signal = signal
        return fired
