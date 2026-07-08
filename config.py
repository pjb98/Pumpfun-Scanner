"""Configuration loaded from environment / .env."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ModuleNotFoundError:  # runs fine without python-dotenv installed
    pass


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


PUMPPORTAL_WS_URL = os.getenv("PUMPPORTAL_WS_URL", "wss://pumpportal.fun/api/data")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# --- persistence ---
DB_PATH = os.getenv("DB_PATH", str(Path(__file__).parent / "data" / "platform_heat.sqlite"))
SNAPSHOT_INTERVAL_S = _int("SNAPSHOT_INTERVAL_S", 60)      # how often to log a snapshot

# --- live signal thresholds ---
GO_THRESHOLD = _int("GO_THRESHOLD", 65)       # composite heat >= this => GO
WAIT_THRESHOLD = _int("WAIT_THRESHOLD", 40)   # composite heat <  this => WAIT
GO_ALERT_COOLDOWN_MIN = _float("GO_ALERT_COOLDOWN_MIN", 30.0)  # min gap between GO alerts

# Trailing baseline: current conditions are judged against the median of the last
# BASELINE_HOURS of snapshots. Below MIN_BASELINE_SNAPSHOTS we cold-start on the
# REF_* reference levels instead.
BASELINE_HOURS = _float("BASELINE_HOURS", 6.0)
MIN_BASELINE_SNAPSHOTS = _int("MIN_BASELINE_SNAPSHOTS", 30)

# Cold-start reference levels (rough Pump.fun norms — CALIBRATE from your own data).
REF_LAUNCHES_PER_MIN = _float("REF_LAUNCHES_PER_MIN", 8.0)
REF_MIGRATIONS_PER_HOUR = _float("REF_MIGRATIONS_PER_HOUR", 12.0)
REF_MIG_SPEED_MIN = _float("REF_MIG_SPEED_MIN", 30.0)   # median minutes to migrate (lower=hotter)
REF_VOL_5M_SOL = _float("REF_VOL_5M_SOL", 300.0)
REF_BUYERS_5M = _float("REF_BUYERS_5M", 400.0)

# Pump.fun bonding curve: ~85 SOL in the curve == migration.
CURVE_TARGET_SOL = 85.0

# Prune a token's trade subscription this long after launch (keeps the sub set small).
TOKEN_TTL_MIN = _int("TOKEN_TTL_MIN", 90)
