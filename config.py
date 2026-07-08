"""Configuration loaded from environment / .env."""
import os
from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


PUMPPORTAL_WS_URL = os.getenv("PUMPPORTAL_WS_URL", "wss://pumpportal.fun/api/data")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

MIN_BONDED_PCT = _int("MIN_BONDED_PCT", 35)
MAX_BONDED_PCT = _int("MAX_BONDED_PCT", 90)
SCORE_TRADE_THRESHOLD = _int("SCORE_TRADE_THRESHOLD", 75)
SCORE_WATCH_THRESHOLD = _int("SCORE_WATCH_THRESHOLD", 55)

# Pump.fun bonding curve constant: ~85 SOL in the curve == 100% bonded (migration).
CURVE_TARGET_SOL = 85.0
