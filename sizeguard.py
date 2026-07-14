"""Disk-footprint watch for the scanner.

A minute-cadence SQLite of small rows grows only a few KB/day, so this project
should stay tiny — but after a 70GB scare on the VPS it's worth watching. This
module reports the project's own footprint plus overall disk headroom, and flags
when either crosses a configurable threshold. It's imported by both the dashboard
(size panel + banner) and the monitor (a throttled warning line in the journal).

Everything here is read-only and stdlib.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import config

PROJECT_DIR = Path(__file__).resolve().parent

# dir_size walks the whole tree (venv has thousands of files); cache briefly so
# frequent dashboard refreshes don't re-stat everything each time.
_CACHE: dict[str, tuple[float, int]] = {}
_CACHE_TTL_S = 30.0


def dir_size(path: str | Path) -> int:
    """Total bytes under `path` (following the tree, ignoring unreadable files)."""
    path = Path(path)
    key = str(path)
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _CACHE_TTL_S:
        return hit[1]
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            continue
    _CACHE[key] = (now, total)
    return total


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def stats() -> dict:
    """Footprint + disk-headroom snapshot, with human strings and any warnings."""
    db = Path(config.DB_PATH)
    db_bytes = db.stat().st_size if db.exists() else 0
    data_bytes = dir_size(db.parent) if db.parent.exists() else 0
    project_bytes = dir_size(PROJECT_DIR)
    du = shutil.disk_usage(PROJECT_DIR)

    warn_project = project_bytes > config.SIZE_WARN_PROJECT_MB * 1024**2
    warn_disk = du.free < config.SIZE_WARN_DISK_FREE_GB * 1024**3
    warnings: list[str] = []
    if warn_project:
        warnings.append(
            f"project is {_human(project_bytes)} "
            f"(> {config.SIZE_WARN_PROJECT_MB:.0f} MB threshold)")
    if warn_disk:
        warnings.append(
            f"only {_human(du.free)} free on disk "
            f"(< {config.SIZE_WARN_DISK_FREE_GB:.0f} GB threshold)")

    return {
        "db_bytes": db_bytes,
        "data_bytes": data_bytes,
        "project_bytes": project_bytes,
        "disk_free_bytes": du.free,
        "disk_total_bytes": du.total,
        "disk_used_pct": round(100 * (du.total - du.free) / du.total, 1),
        "db_human": _human(db_bytes),
        "data_human": _human(data_bytes),
        "project_human": _human(project_bytes),
        "disk_free_human": _human(du.free),
        "disk_total_human": _human(du.total),
        "warnings": warnings,
    }
