"""
app/routers/scores.py
Endpoints:
  GET /scores/live              → all live matches (SofaScore)
  GET /scores/live?league=slug  → filtered
  GET /scores/upcoming          → all upcoming fixtures (FD.org + TSDB)
  GET /scores/upcoming?league=  → filtered, sorted by kickoff time
  GET /scores/recent            → recent results (last 14 days)

All reads from in-memory cache only. Zero external calls.
"""

from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, timezone
from app.core.cache import get_cache

router = APIRouter(prefix="/scores", tags=["scores"])


def _is_still_upcoming(match: dict) -> bool:
    """Return True if the match kickoff is still in the future (or within 2-min grace)."""
    iso = match.get("kickoff_iso", "")
    if not iso:
        return True  # No time info — keep it
    try:
        # kickoff_iso is stored as IST without tz suffix e.g. "2024-03-16T20:30:00"
        # We need to compare in UTC. kickoff_utc is available for FD matches.
        # For TSDB matches kickoff_iso is also IST. Parse as IST.
        from app.core.config import IST
        dt_naive = datetime.fromisoformat(iso)
        # Assume IST if no tz info
        if dt_naive.tzinfo is None:
            dt = IST.localize(dt_naive)
        else:
            dt = dt_naive
        # 2-minute grace period — keep showing as upcoming right up to kickoff
        now_utc = datetime.now(timezone.utc)
        return dt.astimezone(timezone.utc) > now_utc - __import__('datetime').timedelta(minutes=2)
    except Exception:
        return True


def _all_upcoming() -> list[dict]:
    fd   = get_cache("fd_leagues")  or {}
    tsdb = get_cache("tsdb_leagues") or {}
    out  = []
    for league_data in {**fd, **tsdb}.values():
        out.extend(league_data.get("upcoming", []))
    # Filter out matches that have already kicked off (cache can be up to 30min stale)
    out = [m for m in out if _is_still_upcoming(m)]
    out.sort(key=lambda m: m.get("kickoff_iso", ""))
    return out


def _all_recent() -> list[dict]:
    fd   = get_cache("fd_leagues")  or {}
    tsdb = get_cache("tsdb_leagues") or {}   # FIX: was "indian_leagues"
    out  = []
    for league_data in {**fd, **tsdb}.values():
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
