"""
app/routers/matches.py
═══════════════════════════════════════════════════════════════════════════════
On-demand endpoints:

  GET /matches/h2h?match_id={fd_id}    → H2H via football-data.org
  GET /matches/{id}/events             → goals/cards/subs via SofaScore
  GET /matches/{id}/lineups            → lineups via SofaScore
  GET /teams/{id}/squad                → squad via football-data.org
  GET /teams/{id}/form?league=slug     → last 5 in competition
  GET /teams/{id}/next                 → next N fixtures
═══════════════════════════════════════════════════════════════════════════════
"""

import time
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.cache import get_cache
from app.scrapers.football_data import scrape_h2h, scrape_squad, scrape_team_matches
from app.scrapers.sofascore import fetch_lineups, fetch_team_form, fetch_match_events
from app.core.config import LEAGUES

log    = logging.getLogger("matches_router")
router = APIRouter(tags=["matches & teams"])

_cache: dict[str, dict] = {}

def _get(key: str, ttl: int):
    e = _cache.get(key)
    if e and time.time() - e["ts"] < ttl:
        return e["data"]
    return None

def _set(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}


@router.get("/matches/h2h")
async def get_h2h(match_id: str = Query(..., description="football-data.org match ID")):
    """Last 5 H2H matches. Cached 60 min."""
    key = f"h2h:{match_id}"
    cached = _get(key, 3600)
    if cached is not None:
        return cached
    matches = await scrape_h2h(match_id)
    _set(key, matches)
    return matches


@router.get("/matches/{match_id}/events")
async def get_match_events(match_id: str):
    """
    Goals, cards, substitutions from SofaScore.
    match_id = SofaScore event ID (from /scores/live).
    TTL: 2 min if live, 60 min if finished.
    """
    key      = f"events:{match_id}"
    is_live  = any(m.get("match_id") == match_id for m in (get_cache("live_scores") or []))
    ttl      = 120 if is_live else 3600
    cached   = _get(key, ttl)
    if cached is not None:
        return cached
    data = await fetch_match_events(match_id)
    if not data:
        raise HTTPException(404, detail="Events not available for this match")
    _set(key, data)
    return data


@router.get("/matches/{match_id}/lineups")
async def get_lineups(match_id: str):
    """Match lineups from SofaScore. Cached 10 min."""
    key    = f"lineups:{match_id}"
    cached = _get(key, 600)
    if cached is not None:
        return cached
    data = await fetch_lineups(match_id)
    if not data:
        raise HTTPException(404, detail="Lineups not available yet for this match")
    _set(key, data)
    return data


@router.get("/teams/{team_id}/squad")
async def get_squad(team_id: str):
    """Full squad from football-data.org. Cached 24 h."""
    key    = f"squad:{team_id}"
    cached = _get(key, 86400)
    if cached is not None:
        return cached
    data = await scrape_squad(team_id)
    if not data:
        raise HTTPException(404, detail="Squad not found")
    _set(key, data)
    return data


@router.get("/teams/{team_id}/form")
async def get_team_form(
    team_id: str,
    league:  str           = Query(..., description="League slug e.g. premier-league"),
    source:  Optional[str] = Query(None),
):
    """Last 5 matches for a team. Cached 10 min."""
    key    = f"form:{team_id}:{league}"
    cached = _get(key, 600)
    if cached is not None:
        return cached

    cfg      = LEAGUES.get(league, {})
    data_src = source or cfg.get("data_source", "football-data")

    if data_src == "football-data":
        all_matches = await scrape_team_matches(team_id)
        form = [m for m in all_matches if m.get("league_slug") == league and m["status"] == "finished"]
        form = sorted(form, key=lambda m: m["kickoff_iso"], reverse=True)[:5]
    else:
        # SofaScore team form (works for any league with ss_id)
        form = await fetch_team_form(team_id, league)

    _set(key, form)
    return form


@router.get("/teams/{team_id}/next")
async def get_team_next(
    team_id: str,
    league:  Optional[str] = Query(None),
    limit:   int           = Query(5, ge=1, le=10),
):
    """Next N upcoming fixtures for a team. Cached 30 min."""
    key    = f"next:{team_id}:{league}"
    cached = _get(key, 1800)
    if cached is not None:
        return cached

    if team_id.isdigit():
        # football-data.org team
        all_matches = await scrape_team_matches(team_id)
        upcoming = [
            m for m in all_matches
            if m["status"] == "scheduled" and (not league or m.get("league_slug") == league)
        ]
        upcoming.sort(key=lambda m: m["kickoff_iso"])
        result = upcoming[:limit]
    else:
        # Indian / TSDB team — search by name in tsdb_leagues cache
        tsdb = get_cache("tsdb_leagues") or {}
        upcoming = []
        for slug, data in tsdb.items():
            for m in data.get("upcoming", []):
                if team_id.lower() in m.get("home_team", "").lower() or \
                   team_id.lower() in m.get("away_team", "").lower():
                    upcoming.append(m)
        upcoming.sort(key=lambda m: m["kickoff_iso"])
        result = upcoming[:limit]

    _set(key, result)
    return result
