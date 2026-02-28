"""
app/routers/players.py
═══════════════════════════════════════════════════════════════════════════════
GET /players/{player_id}

Fetches full player profile from SofaScore (primary) or football-data.org.

Returns:
{
  "player_id", "name", "first_name", "nationality", "position",
  "date_of_birth", "shirt_no", "team", "team_id", "team_logo",
  "photo",       ← SofaScore player image URL
  "height_cm",   ← from SofaScore
  "preferred_foot",
  "market_value",

  "season_stats": {
    "goals", "assists", "appearances", "minutes",
    "yellow_cards", "red_cards", "rating", "penalties"
  },

  "recent_matches": [
    {match_id, home_team, away_team, score, status, kickoff_display,
     league_slug, player_rating, player_goals, player_assists}
  ]
}
═══════════════════════════════════════════════════════════════════════════════
"""

import time
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from app.scrapers.sofascore import fetch_player_profile
from app.scrapers.football_data import fetch_player_fd

log    = logging.getLogger("players_router")
router = APIRouter(tags=["players"])

_cache: dict[str, dict] = {}

def _get(pid: str) -> Optional[dict]:
    e = _cache.get(pid)
    if e and time.time() - e["ts"] < 1800:   # 30 min TTL
        return e["data"]
    return None

def _set(pid: str, data: dict):
    _cache[pid] = {"data": data, "ts": time.time()}


@router.get("/players/{player_id}")
async def get_player(player_id: str):
    """
    Full player profile.
    player_id can be a SofaScore numeric ID (preferred) or FD.org numeric ID.
    The app navigates here from:
      - Timeline player name tap  (SofaScore match → SS player ID)
      - Top scorers row tap       (FD.org scorer → FD player ID)
    We try SofaScore first, fall back to FD.org.
    """
    cached = _get(player_id)
    if cached is not None:
        return cached

    # Try SofaScore first (has photo, rating, recent matches)
    data = await fetch_player_profile(player_id)

    # Fall back to football-data.org (for FD player IDs from scorers list)
    if not data:
        data = await fetch_player_fd(player_id)

    if not data:
        raise HTTPException(404, detail=f"Player '{player_id}' not found")

    _set(player_id, data)
    return data
