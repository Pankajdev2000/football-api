"""
app/core/scheduler.py
═══════════════════════════════════════════════════════════════════════════════
Adaptive background scheduler with strict guarantees:

  1. ONE scheduler instance ever (guarded by _running flag)
  2. ONE scrape at a time (asyncio.Lock — overlapping scrapes impossible)
  3. Slow scrape → skip next cycle, never queue
  4. Failed scrape → keep last valid cache, never overwrite with partial data
  5. IST-aware interval:
       17:00–06:00 IST (active football hours) → 3 minutes
       06:00–17:00 IST (off-peak)              → 7 minutes
  6. football-data.org (rate-limited) → separate 30-minute cycle
  7. Indian leagues (HTML scrapers)   → separate 60-minute cycle
  8. Conference League (SofaScore)    → separate 30-minute cycle

Timing design:
  • Live cycle (every 3–7 min):   SofaScore live scores only
  • FD.org cycle (every 30 min):  fixtures, standings, scorers for EU leagues
  • Indian cycle (every 60 min):  ISL + IFL + AFC from HTML scrapers
  • SS cycle (every 30 min):      Conference League fixtures/standings
═══════════════════════════════════════════════════════════════════════════════
"""

import asyncio
import logging
import time
from datetime import datetime

from app.core.cache import set_cache, get_cache
from app.core.config import IST
from app.scrapers.sofascore import scrape_live_scores, scrape_all_ss_leagues
from app.scrapers.football_data import scrape_all_fd_leagues
from app.scrapers.indian_scraper import scrape_all_indian_leagues

log = logging.getLogger("scheduler")

# ── Intervals ─────────────────────────────────────────────────────────────────
ACTIVE_INTERVAL_S     = 3 * 60      # 3 min  — live football hours
OFFPEAK_INTERVAL_S    = 7 * 60      # 7 min  — quiet hours
FD_INTERVAL_S         = 30 * 60     # 30 min — football-data.org (rate limited)
INDIAN_INTERVAL_S     = 60 * 60     # 60 min — Indian leagues (HTML scraping)
SS_LEAGUES_INTERVAL_S = 30 * 60     # 30 min — Conference League (SofaScore)
MAX_CYCLE_S           = 120         # if scrape exceeds this → skip next live cycle

# ── State ─────────────────────────────────────────────────────────────────────
_scrape_lock     = asyncio.Lock()
_running         = False
_last_fd_scrape  = 0.0
_last_indian     = 0.0
_last_ss_leagues = 0.0


def _is_active() -> bool:
    hour = datetime.now(IST).hour
    return hour >= 17 or hour < 6


def _live_interval() -> int:
    return ACTIVE_INTERVAL_S if _is_active() else OFFPEAK_INTERVAL_S


# ── Individual scrape jobs ─────────────────────────────────────────────────────

async def _job_live() -> None:
    """SofaScore live scores — runs every cycle."""
    try:
        matches = await scrape_live_scores()
        # Always write (even empty list is valid — it means nothing is live)
        set_cache("live_scores", matches)
        log.info(f"Live: {len(matches)} live matches cached")
    except Exception as ex:
        log.error(f"Live scrape error: {ex}")
        # Cache not written → previous valid data stays


async def _job_fd_leagues() -> None:
    """football-data.org — runs every 30 min (rate limit aware)."""
    global _last_fd_scrape
    if time.time() - _last_fd_scrape < FD_INTERVAL_S:
        return

    log.info("Starting football-data.org scrape...")
    try:
        data = await scrape_all_fd_leagues()
        if data:  # never overwrite with empty
            set_cache("fd_leagues", data)
            _last_fd_scrape = time.time()
            log.info(f"FD.org: cached {list(data.keys())}")
    except Exception as ex:
        log.error(f"FD.org scrape error: {ex}")


async def _job_indian_leagues() -> None:
    """ISL + IFL + AFC from HTML scrapers — runs every 60 min."""
    global _last_indian
    if time.time() - _last_indian < INDIAN_INTERVAL_S:
        return

    log.info("Starting Indian leagues scrape (ISL/IFL/AFC)...")
    try:
        data = await scrape_all_indian_leagues()
        if data:
            set_cache("indian_leagues", data)
            _last_indian = time.time()
            log.info(f"Indian leagues: cached {list(data.keys())}")
    except Exception as ex:
        log.error(f"Indian leagues scrape error: {ex}")


async def _job_ss_leagues() -> None:
    """Conference League fixtures/standings from SofaScore — runs every 30 min."""
    global _last_ss_leagues
    if time.time() - _last_ss_leagues < SS_LEAGUES_INTERVAL_S:
        return

    log.info("Starting SofaScore leagues scrape (Conference League)...")
    try:
        data = await scrape_all_ss_leagues()
        if data:
            set_cache("sofascore_leagues", data)
            _last_ss_leagues = time.time()
            log.info(f"SofaScore leagues: cached {list(data.keys())}")
    except Exception as ex:
        log.error(f"SofaScore leagues scrape error: {ex}")


# ── Main cycle ────────────────────────────────────────────────────────────────

async def _run_cycle() -> None:
    if _scrape_lock.locked():
        log.warning("Previous scrape still running — skipping cycle")
        return

    async with _scrape_lock:
        t0 = time.time()
        await _job_live()
        await _job_fd_leagues()
        await _job_indian_leagues()
        await _job_ss_leagues()
        elapsed = time.time() - t0
        log.info(f"Cycle complete in {elapsed:.1f}s")


# ── Scheduler entry point ──────────────────────────────────────────────────────

async def run_scheduler() -> None:
    """
    Called once at startup. Runs indefinitely.
    Never starts a second instance — guarded by _running flag.
    """
    global _running
    if _running:
        log.warning("Scheduler already running — ignoring duplicate start")
        return
    _running = True
    log.info("Scheduler started")

    # Run immediately on startup so cache is warm before first request
    try:
        await _run_cycle()
    except Exception as ex:
        log.error(f"Startup scrape error: {ex}")

    while True:
        interval = _live_interval()
        log.debug(f"Next cycle in {interval}s ({'active' if _is_active() else 'off-peak'})")
        await asyncio.sleep(interval)
        try:
            await _run_cycle()
        except Exception as ex:
            log.error(f"Cycle error (continuing): {ex}")
