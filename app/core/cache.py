"""
app/core/cache.py
═══════════════════════════════════════════════════════════════════════════
Atomic in-memory cache.
  • Only scrapers call set_cache()
  • Only routers call get_cache()
  • Writes are protected by a threading lock → atomic replace, never partial
  • Failed scrapes never call set_cache() → stale data stays valid
═══════════════════════════════════════════════════════════════════════════
"""

import time
import threading
from typing import Any, Optional

_store: dict[str, dict] = {}
_lock  = threading.Lock()


def set_cache(key: str, data: Any) -> None:
    """Atomically store a cache entry. Called by scrapers only."""
    with _lock:
        _store[key] = {"data": data, "ts": time.time()}


def get_cache(key: str) -> Optional[Any]:
    """Read cache entry. Returns None if key was never set."""
    with _lock:
        e = _store.get(key)
        return e["data"] if e else None


def get_cache_age(key: str) -> Optional[float]:
    """Seconds since last successful write, or None."""
    with _lock:
        e = _store.get(key)
        return round(time.time() - e["ts"], 1) if e else None


def cache_summary() -> dict:
    """Metadata only — safe to expose in /health."""
    with _lock:
        return {k: {"age_s": round(time.time() - v["ts"], 1)} for k, v in _store.items()}
