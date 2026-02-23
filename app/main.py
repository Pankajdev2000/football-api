"""
app/main.py  — Goal2Gol Football API v3
Startup: warms cache, launches adaptive scheduler.
All endpoints are cache-read-only after startup.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.cache import cache_summary
from app.core.http_client import close_all
from app.core.scheduler import run_scheduler
from app.routers import scores, leagues, matches

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🚀 Goal2Gol Football API v3 starting...")
    asyncio.create_task(run_scheduler())
    yield
    log.info("🛑 Shutting down...")
    await close_all()


app = FastAPI(
    title="Goal2Gol Football API",
    description=(
        "Cache-first football backend. "
        "Sources: football-data.org (EU fixtures/standings/scorers) + "
        "SofaScore (live scores/lineups) + "
        "fixturedownload.com (ISL/IFL). "
        "Live refresh: 3 min active / 7 min off-peak (IST)."
    ),
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(scores.router)
app.include_router(leagues.router)
app.include_router(matches.router)


@app.get("/", tags=["meta"])
async def root():
    return {
        "status":  "online",
        "version": "3.0.0",
        "sources": {
            "european_leagues": "football-data.org (fixtures, standings, scorers, squads, H2H)",
            "live_scores":      "SofaScore (live in-progress only)",
            "indian_leagues":   "fixturedownload.com (ISL + IFL)",
        },
        "endpoints": {
            "live":           "/scores/live",
            "upcoming":       "/scores/upcoming",
            "recent":         "/scores/recent",
            "leagues":        "/leagues",
            "league_detail":  "/leagues/{slug}",
            "standings":      "/leagues/{slug}/standings",
            "scorers":        "/leagues/{slug}/stats",
            "h2h":            "/matches/h2h?match_id={fd_match_id}",
            "lineups":        "/matches/{ss_match_id}/lineups",
            "squad":          "/teams/{fd_team_id}/squad",
            "team_form":      "/teams/{team_id}/form?league={slug}",
            "team_next":      "/teams/{team_id}/next",
            "health":         "/health",
            "docs":           "/docs",
        },
        "league_slugs": [
            "premier-league", "la-liga", "bundesliga", "serie-a", "ligue-1",
            "champions-league", "europa-league", "conference-league",
            "fifa-world-cup", "isl", "ifl", "afc",
        ],
    }


@app.get("/health", tags=["meta"])
async def health():
    """Lightweight health check. Ping from UptimeRobot every 5 min."""
    summary = cache_summary()
    return {
        "status":       "healthy" if summary else "warming_up",
        "cache_keys":   summary,
        "live_ready":   "live_scores" in summary,
        "fixtures_ready": "fd_leagues" in summary,
        "indian_ready": "indian_leagues" in summary,
    }
