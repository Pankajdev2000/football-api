"""
app/core/scheduler.py
═══════════════════════════════════════════════════════════════════════════════
Adaptive background scheduler:

  • Live cycle  (3–7 min IST-aware):  SofaScore live scores
  • FD.org cycle  (30 min):           EU league fixtures/standings/scorers
  • TSDB cycle    (60 min):           ISL/IFL/AFC/Conference League via TheSportsDB

TheSportsDB is a free public API — no key, no IP blocking.
Replaces both fixturedownload.com (dead) and SofaScore (blocks servers).
═══════════════════════════════════════════════════════════════════════════════
"""

import asyncio
import logging
import time
from datetime import datetime

from app.core.cache import set_cache, get_cache
from app.core.config import IST
from app.scrapers.sofascore import scrape_live_scores
from app.scrapers.football_data import scrape_all_fd_leagues
from app.scrapers.thesportsdb import scrape_all_tsdb_leagues
from app.scrapers.worldfootball import scrape_isl_standings

log = logging.getLogger("scheduler")

ACTIVE_INTERVAL_S  = 3 * 60
OFFPEAK_INTERVAL_S = 7 * 60
FD_INTERVAL_S      = 30 * 60
TSDB_INTERVAL_S    = 60 * 60

_scrape_lock    = asyncio.Lock()
_running        = False
_last_fd_scrape = 0.0
_last_tsdb      = 0.0


def _is_active() -> bool:
    hour = datetime.now(IST).hour
    return hour >= 17 or hour < 6


def _live_interval() -> int:
    return ACTIVE_INTERVAL_S if _is_active() else OFFPEAK_INTERVAL_S


async def _job_live() -> None:
    """SofaScore live scores — runs every cycle."""
    try:
        matches = await scrape_live_scores()
        set_cache("live_scores", matches)
        log.info(f"Live: {len(matches)} live matches cached")
    except Exception as ex:
        log.error(f"Live scrape error: {ex}")


async def _job_fd_leagues() -> None:
    """football-data.org — runs every 30 min."""
    global _last_fd_scrape
    if time.time() - _last_fd_scrape < FD_INTERVAL_S:
        return
    log.info("Starting football-data.org scrape...")
    try:
        data = await scrape_all_fd_leagues()
        if data:
            set_cache("fd_leagues", data)
            _last_fd_scrape = time.time()
            log.info(f"FD.org: cached {list(data.keys())}")
    except Exception as ex:
        log.error(f"FD.org scrape error: {ex}")


async def _job_tsdb_leagues() -> None:
    """TheSportsDB + WorldFootball fallback for ISL."""
    global _last_tsdb
    if time.time() - _last_tsdb < TSDB_INTERVAL_S:
        return

    log.info("Starting TheSportsDB scrape (ISL/IFL/AFC/UECL)...")

    try:
        data = await scrape_all_tsdb_leagues()

        if data:
            # 🔥 ISL fallback
            isl_block = data.get("isl")

            if isl_block:
                if not isl_block.get("standings"):
                    log.info("ISL standings empty → using WorldFootball fallback")
                    wf_table = await scrape_isl_standings()
                    if wf_table:
                        isl_block["standings"] = wf_table

            set_cache("tsdb_leagues", data)
            _last_tsdb = time.time()
            log.info(f"TheSportsDB: cached {list(data.keys())}")

    except Exception as ex:
        log.error(f"TheSportsDB scrape error: {ex}")


async def _run_cycle() -> None:
    if _scrape_lock.locked():
        log.warning("Previous scrape still running — skipping cycle")
        return
    async with _scrape_lock:
        t0 = time.time()
        await _job_live()
        await _job_fd_leagues()
        await _job_tsdb_leagues()
        log.info(f"Cycle complete in {time.time() - t0:.1f}s")


async def run_scheduler() -> None:
    global _running
    if _running:
        log.warning("Scheduler already running — ignoring duplicate start")
        return
    _running = True
    log.info("Scheduler started")
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
