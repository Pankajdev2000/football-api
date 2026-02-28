"""
app/main.py  — Goal2Gol Football API v4
Startup: warms cache, launches adaptive scheduler.
All endpoints are cache-read-only after startup (except on-demand endpoints).
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.cache import cache_summary, get_cache
from app.core.http_client import close_all
from app.core.scheduler import run_scheduler
from app.routers import scores, leagues, matches
from app.routers.search import router as search_router
from app.routers.players import router as players_router
from app.routers.bracket import router as bracket_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🚀 Goal2Gol Football API v4 starting...")
    asyncio.create_task(run_scheduler())
    yield
    log.info("🛑 Shutting down...")
    await close_all()


app = FastAPI(
    title="Goal2Gol Football API",
    description=(
        "Cache-first football backend for Goal2Gol Android app. "
        "Sources: football-data.org (EU fixtures/standings/scorers) + "
        "SofaScore (live scores/lineups/stats/players/brackets) + "
        "TheSportsDB (ISL/IFL/AFC/Conference League). "
        "Live refresh: 3 min active / 7 min off-peak (IST)."
    ),
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(scores.router)
app.include_router(leagues.router)
app.include_router(matches.router)
app.include_router(search_router)
app.include_router(players_router)
app.include_router(bracket_router)


@app.get("/", tags=["meta"])
async def root():
    return {
        "status":  "online",
        "version": "4.0.0",
        "sources": {
            "european_leagues": "football-data.org (fixtures, standings, scorers, squads, H2H)",
            "live_scores":      "SofaScore (live scores, events, lineups, stats, players, brackets)",
            "indian_leagues":   "TheSportsDB (ISL + IFL + AFC + Conference League)",
        },
        "endpoints": {
            "live":           "/scores/live",
            "upcoming":       "/scores/upcoming",
            "recent":         "/scores/recent",
            "leagues":        "/leagues",
            "league_detail":  "/leagues/{slug}",
            "standings":      "/leagues/{slug}/standings",
            "scorers":        "/leagues/{slug}/stats",
            "fixtures":       "/leagues/{slug}/fixtures",
            "results":        "/leagues/{slug}/results",
            "bracket":        "/leagues/{slug}/bracket",
            "h2h":            "/matches/h2h?match_id={fd_match_id}",
            "events":         "/matches/{ss_match_id}/events",
            "lineups":        "/matches/{ss_match_id}/lineups",
            "stats":          "/matches/{ss_match_id}/stats",
            "squad":          "/teams/{fd_team_id}/squad",
            "team_form":      "/teams/{team_id}/form?league={slug}",
            "team_next":      "/teams/{team_id}/next",
            "player_profile": "/players/{player_id}",
            "search":         "/search?q={query}",
            "health":         "/health",
            "docs":           "/docs",
        },
        "league_slugs": [
            "premier-league", "la-liga", "bundesliga", "serie-a", "ligue-1",
            "champions-league", "europa-league", "conference-league",
            "fifa-world-cup", "isl", "ifl", "afc",
        ],
        "bracket_slugs": [
            "champions-league", "europa-league", "conference-league", "afc",
        ],
    }


@app.get("/health", tags=["meta"])
async def health():
    """Lightweight health check. Ping from UptimeRobot every 5 min."""
    summary = cache_summary()

    # Build per-source detail for easier debugging
    live_matches   = get_cache("live_scores") or []
    fd_data        = get_cache("fd_leagues")  or {}
    tsdb_data      = get_cache("tsdb_leagues") or {}

    fd_upcoming_count  = sum(len(v.get("upcoming", [])) for v in fd_data.values())
    tsdb_upcoming_count = sum(len(v.get("upcoming", [])) for v in tsdb_data.values())

    return {
        "status":     "healthy" if summary else "warming_up",
        "cache_keys": summary,
        "sources": {
            "live_scores": {
                "ready":        "live_scores" in summary,
                "age_s":        summary.get("live_scores", {}).get("age_s"),
                "match_count":  len(live_matches),
            },
            "football_data": {
                "ready":        "fd_leagues" in summary,
                "age_s":        summary.get("fd_leagues", {}).get("age_s"),
                "leagues_cached": list(fd_data.keys()),
                "upcoming_count": fd_upcoming_count,
            },
            "thesportsdb": {
                "ready":        "tsdb_leagues" in summary,
                "age_s":        summary.get("tsdb_leagues", {}).get("age_s"),
                "leagues_cached": list(tsdb_data.keys()),
                "upcoming_count": tsdb_upcoming_count,
            },
        },
        "live_ready":     "live_scores" in summary,
        "fixtures_ready": "fd_leagues" in summary,
        "indian_ready":   "tsdb_leagues" in summary,
    }
