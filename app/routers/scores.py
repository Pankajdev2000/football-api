"""
app/routers/scores.py
Endpoints:
  GET /scores/live              → all live matches (SofaScore)
  GET /scores/live?league=slug  → filtered
  GET /scores/upcoming          → all upcoming fixtures (FD.org + Indian)
  GET /scores/upcoming?league=  → filtered, sorted by kickoff time
  GET /scores/recent            → recent results (last 14 days)

All reads from in-memory cache only. Zero external calls.
"""

from fastapi import APIRouter, Query
from typing import Optional
from app.core.cache import get_cache

router = APIRouter(prefix="/scores", tags=["scores"])


def _all_upcoming() -> list[dict]:
    fd   = get_cache("fd_leagues") or {}
    ind  = get_cache("indian_leagues") or {}
    out  = []
    for league_data in {**fd, **ind}.values():
        out.extend(league_data.get("upcoming", []))
    out.sort(key=lambda m: m.get("kickoff_iso", ""))
    return out


def _all_recent() -> list[dict]:
    fd  = get_cache("fd_leagues") or {}
    ind = get_cache("indian_leagues") or {}
    out = []
    for league_data in {**fd, **ind}.values():
        out.extend(league_data.get("recent", []))
    out.sort(key=lambda m: m.get("kickoff_iso", ""), reverse=True)
    return out


@router.get("/live")
async def get_live(league: Optional[str] = Query(None)):
    matches = get_cache("live_scores") or []
    if league:
        matches = [m for m in matches if m.get("league_slug") == league]
    return matches


@router.get("/upcoming")
async def get_upcoming(
    league: Optional[str] = Query(None),
    limit:  int           = Query(50, ge=1, le=200),
):
    matches = _all_upcoming()
    if league:
        matches = [m for m in matches if m.get("league_slug") == league]
    return matches[:limit]


@router.get("/recent")
async def get_recent(
    league: Optional[str] = Query(None),
    limit:  int           = Query(40, ge=1, le=200),
):
    matches = _all_recent()
    if league:
        matches = [m for m in matches if m.get("league_slug") == league]
    return matches[:limit]
