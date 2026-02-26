"""
app/routers/leagues.py
═══════════════════════════════════════════════════════════════════════════════
Endpoints:
  GET /leagues                  → list all leagues
  GET /leagues/{slug}           → full page: live + upcoming + recent + standings + scorers
  GET /leagues/{slug}/standings → standings table only
  GET /leagues/{slug}/stats     → top scorers only
  GET /leagues/{slug}/fixtures  → upcoming only
  GET /leagues/{slug}/results   → recent only

Cache routing:
  data_source == "football-data"  →  "fd_leagues"   cache
  data_source == "thesportsdb"    →  "tsdb_leagues"  cache
  Live matches always from "live_scores" cache (SofaScore)
═══════════════════════════════════════════════════════════════════════════════
"""

from fastapi import APIRouter, HTTPException
from app.core.cache import get_cache
from app.core.config import LEAGUES, STREAMING

router = APIRouter(prefix="/leagues", tags=["leagues"])


def _fd_data() -> dict:
    return get_cache("fd_leagues") or {}


def _tsdb_data() -> dict:
    return get_cache("tsdb_leagues") or {}


def _live_for(slug: str) -> list[dict]:
    return [m for m in (get_cache("live_scores") or []) if m.get("league_slug") == slug]


def _league_cache(slug: str) -> dict:
    """Route to correct cache based on data_source."""
    cfg = LEAGUES.get(slug, {})
    src = cfg.get("data_source", "")
    if src == "thesportsdb":
        return _tsdb_data().get(slug, {})
    # Default: football-data.org
    return _fd_data().get(slug, {})


def _dedup(matches: list[dict]) -> list[dict]:
    seen, out = set(), []
    for m in matches:
        key = (m.get("kickoff_iso", ""), m.get("home_team", ""), m.get("away_team", ""))
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


@router.get("")
async def list_leagues():
    return [
        {
            "slug":      slug,
            "name":      cfg["name"],
            "short":     cfg["short"],
            "country":   cfg["country"],
            "logo_url":  cfg.get("logo_url", ""),
            "streaming": STREAMING.get(slug, {}),
        }
        for slug, cfg in LEAGUES.items()
    ]


@router.get("/{slug}")
async def get_league(slug: str):
    if slug not in LEAGUES:
        raise HTTPException(404, detail=f"League '{slug}' not found")
    cfg   = LEAGUES[slug]
    block = _league_cache(slug)
    return {
        "slug":      slug,
        "name":      cfg["name"],
        "short":     cfg["short"],
        "country":   cfg["country"],
        "logo_url":  cfg.get("logo_url", ""),
        "streaming": STREAMING.get(slug, {}),
        "live":      _live_for(slug),
        "upcoming":  _dedup(block.get("upcoming", []))[:20],
        "recent":    _dedup(block.get("recent",   []))[:20],
        "standings": block.get("standings", []),
        "scorers":   block.get("scorers",   []),
    }


@router.get("/{slug}/standings")
async def get_standings(slug: str):
    if slug not in LEAGUES:
        raise HTTPException(404, detail=f"League '{slug}' not found")
    return {"league": slug, "standings": _league_cache(slug).get("standings", [])}


@router.get("/{slug}/stats")
async def get_stats(slug: str):
    if slug not in LEAGUES:
        raise HTTPException(404, detail=f"League '{slug}' not found")
    return {"league": slug, "scorers": _league_cache(slug).get("scorers", [])}


@router.get("/{slug}/fixtures")
async def get_fixtures(slug: str, limit: int = 20):
    if slug not in LEAGUES:
        raise HTTPException(404, detail=f"League '{slug}' not found")
    block    = _league_cache(slug)
    upcoming = _dedup(block.get("upcoming", []))
    return {"live": _live_for(slug), "upcoming": upcoming[:limit]}


@router.get("/{slug}/results")
async def get_results(slug: str, limit: int = 20):
    if slug not in LEAGUES:
        raise HTTPException(404, detail=f"League '{slug}' not found")
    return {"recent": _dedup(_league_cache(slug).get("recent", []))[:limit]}
