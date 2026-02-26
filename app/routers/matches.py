"""
app/routers/matches.py
═══════════════════════════════════════════════════════════════════════════════
On-demand endpoints (with local TTL cache to prevent hammering):

  GET /matches/h2h?match_id={fd_match_id}     → H2H from football-data.org
  GET /matches/{match_id}/lineups             → lineups from SofaScore
  GET /matches/{match_id}/events              → goals/cards/subs from SofaScore
  GET /teams/{team_id}/squad                  → squad from football-data.org
  GET /teams/{team_id}/form?league=slug       → last 5 in competition
  GET /teams/{team_id}/next                   → next N fixtures

H2H uses football-data.org match IDs (from FD fixtures cache).
Lineups + Events use SofaScore match IDs (from live scores cache).

All on-demand results are cached locally for their TTL to avoid re-fetching
on every screen open.
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

# ── Local TTL cache for on-demand results ─────────────────────────────────────
_cache: dict[str, dict] = {}

def _get(key: str, ttl: int):
    e = _cache.get(key)
    if e and time.time() - e["ts"] < ttl:
        return e["data"]
    return None

def _set(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}


# ── H2H ───────────────────────────────────────────────────────────────────────

@router.get("/matches/h2h")
async def get_h2h(match_id: str = Query(..., description="football-data.org match ID")):
    """
    Last 5 head-to-head matches via football-data.org.
    Cached 60 minutes (H2H rarely changes).
    """
    key = f"h2h:{match_id}"
    cached = _get(key, 3600)
    if cached is not None:
        return cached

    matches = await scrape_h2h(match_id)
    _set(key, matches)
    return matches


# ── Match events ──────────────────────────────────────────────────────────────

@router.get("/matches/{match_id}/events")
async def get_match_events(match_id: str):
    """
    Match events from SofaScore: goals, cards, substitutions.
    Pass the SofaScore match_id (from /scores/live response).

    Cache TTL:
      - Live match  → 2 minutes  (events change every few minutes)
      - Finished    → 60 minutes (static once the match ends)

    Response:
    {
        "goals":         [{"minute","team","scorer","assist","type"}],
        "cards":         [{"minute","team","player","type"}],
        "substitutions": [{"minute","team","player_in","player_out"}]
    }
    """
    key = f"events:{match_id}"

    # Use shorter TTL if match is currently live
    live_matches = get_cache("live_scores") or []
    is_live = any(m.get("match_id") == match_id for m in live_matches)
    ttl = 120 if is_live else 3600

    cached = _get(key, ttl)
    if cached is not None:
        return cached

    data = await fetch_match_events(match_id)
    if not data:
        raise HTTPException(404, detail="Events not available for this match")

    _set(key, data)
    return data


# ── Lineups ───────────────────────────────────────────────────────────────────

@router.get("/matches/{match_id}/lineups")
async def get_lineups(match_id: str):
    """
    Match lineups from SofaScore.
    Pass the SofaScore match_id (from /scores/live response).
    Cached 10 minutes.
    """
    key = f"lineups:{match_id}"
    cached = _get(key, 600)
    if cached is not None:
        return cached

    data = await fetch_lineups(match_id)
    if not data:
        raise HTTPException(404, detail="Lineups not available yet for this match")

    _set(key, data)
    return data


# ── Squad ──────────────────────────────────────────────────────────────────────

@router.get("/teams/{team_id}/squad")
async def get_squad(team_id: str):
    """
    Full squad from football-data.org.
    team_id = football-data.org team ID (from fixtures/standings responses).
    Cached 24 hours (squads change slowly).
    """
    key = f"squad:{team_id}"
    cached = _get(key, 86400)
    if cached is not None:
        return cached

    data = await scrape_squad(team_id)
    if not data:
        raise HTTPException(404, detail="Squad not found")

    _set(key, data)
    return data


# ── Team form ─────────────────────────────────────────────────────────────────

@router.get("/teams/{team_id}/form")
async def get_team_form(
    team_id: str,
    league:  str           = Query(..., description="League slug e.g. premier-league"),
    source:  Optional[str] = Query(None, description="'fd' or 'ss' — auto-detected if omitted"),
):
    """
    Last 5 matches for a team in a competition.
    For football-data.org leagues: uses FD team matches endpoint.
    For SofaScore-only leagues (conference-league): uses SofaScore.
    Cached 10 minutes.
    """
    key = f"form:{team_id}:{league}"
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
        form = await fetch_team_form(team_id, league)

    _set(key, form)
    return form


# ── Team next fixtures ────────────────────────────────────────────────────────

@router.get("/teams/{team_id}/next")
async def get_team_next(
    team_id: str,
    league:  Optional[str] = Query(None),
    limit:   int           = Query(5, ge=1, le=10),
):
    """
    Next N upcoming fixtures for a team.
    For FD.org teams (numeric IDs): fetches from FD team matches endpoint.
    For Indian teams (name-based): searches the indian_leagues cache.
    Cached 30 minutes.
    """
    key = f"next:{team_id}:{league}"
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
        # Indian team — search by name in the indian_leagues cache
        ind = get_cache("indian_leagues") or {}
        upcoming = []
        for slug, data in ind.items():
            for m in data.get("upcoming", []):
                if team_id.lower() in m.get("home_team", "").lower() or \
                   team_id.lower() in m.get("away_team", "").lower():
                    upcoming.append(m)
        upcoming.sort(key=lambda m: m["kickoff_iso"])
        result = upcoming[:limit]

    _set(key, result)
    return result
