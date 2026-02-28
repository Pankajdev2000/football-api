"""
app/routers/bracket.py
═══════════════════════════════════════════════════════════════════════════════
GET /leagues/{slug}/bracket

Returns knockout bracket for UCL, UEL, UECL, FA Cup, Copa del Rey, AFC.

Data source: SofaScore /unique-tournament/{id}/season/{season_id}/events/round/{round}
Supported slugs: champions-league, europa-league, conference-league, afc,
                 fa-cup, copa-del-rey

Returns:
{
  "league_slug": "champions-league",
  "league_name": "UEFA Champions League",
  "season":      "2024/25",
  "rounds": [
    {
      "name":    "Round of 16",
      "code":    "r16",
      "matches": [
        {
          "match_id":        "12345",
          "home_team":       "Real Madrid",
          "home_team_short": "Real Madrid",
          "home_logo":       "...",
          "away_team":       "Man City",
          "away_team_short": "Man City",
          "away_logo":       "...",
          "home_score":      null,   ← null = TBD
          "away_score":      null,
          "home_agg":        null,   ← aggregate score (2-leg ties)
          "away_agg":        null,
          "winner":          null,   ← "home" | "away" | null
          "status":          "scheduled",
          "kickoff_display": "18 Mar • 01:30 AM IST",
          "leg":             1       ← 1 or 2
        }
      ]
    },
    { "name": "Quarter-finals", "code": "qf", "matches": [...] },
    { "name": "Semi-finals",    "code": "sf", "matches": [...] },
    { "name": "Final",          "code": "final", "matches": [...] }
  ]
}
═══════════════════════════════════════════════════════════════════════════════
"""

import time
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from app.core.config import LEAGUES
from app.scrapers.sofascore import fetch_bracket

log    = logging.getLogger("bracket_router")
router = APIRouter(tags=["bracket"])

_cache: dict[str, dict] = {}
BRACKET_SLUGS = {
    "champions-league", "europa-league", "conference-league",
    "afc", "fa-cup", "copa-del-rey",
}

def _get(slug: str) -> Optional[dict]:
    e = _cache.get(slug)
    if e and time.time() - e["ts"] < 1800:  # 30 min
        return e["data"]
    return None

def _set(slug: str, data: dict):
    _cache[slug] = {"data": data, "ts": time.time()}


@router.get("/leagues/{slug}/bracket")
async def get_bracket(slug: str):
    """Knockout bracket for cup/UCL competitions."""
    if slug not in BRACKET_SLUGS:
        raise HTTPException(400, detail=f"Bracket not available for '{slug}'. "
                            f"Supported: {sorted(BRACKET_SLUGS)}")

    cfg = LEAGUES.get(slug)
    if not cfg:
        raise HTTPException(404, detail=f"League '{slug}' not found")

    ss_id = cfg.get("ss_id")
    if not ss_id:
        raise HTTPException(503, detail=f"No SofaScore ID configured for '{slug}'")

    cached = _get(slug)
    if cached is not None:
        return cached

    data = await fetch_bracket(slug, ss_id)
    if not data:
        raise HTTPException(503, detail="Bracket data unavailable — try again shortly")

    _set(slug, data)
    return data
