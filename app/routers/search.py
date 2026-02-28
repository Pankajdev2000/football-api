"""
app/routers/search.py
═══════════════════════════════════════════════════════════════════════════════
GET /search?q={query}

Searches across:
  1. League names / slugs        (instant, from LEAGUES config)
  2. Teams in standings          (instant, from fd_leagues + tsdb_leagues cache)
  3. Players in scorers lists    (instant, from cached scorers)
  4. Matches by team name        (instant, from live + upcoming + recent cache)
  5. SofaScore player search     (live, on-demand, cached 10 min)

Returns:
{
  "query": "...",
  "leagues":  [{slug, name, country, logo_url}],
  "teams":    [{team_id, name, short, logo, league, league_slug}],
  "players":  [{player_id, name, team, nationality, goals, league_slug}],
  "matches":  [{match_id, home_team, away_team, status, kickoff_display, league_slug}]
}
═══════════════════════════════════════════════════════════════════════════════
"""

import time
import logging
from typing import Optional

from fastapi import APIRouter, Query, HTTPException

from app.core.cache import get_cache
from app.core.config import LEAGUES, STREAMING
from app.scrapers.sofascore import search_players

log = logging.getLogger("search_router")
router = APIRouter(tags=["search"])

# Local TTL cache for player search results
_pcache: dict[str, dict] = {}

def _pcache_get(q: str) -> Optional[list]:
    e = _pcache.get(q.lower())
    if e and time.time() - e["ts"] < 600:
        return e["data"]
    return None

def _pcache_set(q: str, data: list):
    _pcache[q.lower()] = {"data": data, "ts": time.time()}


def _matches_query(text: str, q: str) -> bool:
    return q.lower() in (text or "").lower()


@router.get("/search")
async def search(
    q: str = Query(..., min_length=2, description="Search query — team, player, or league name"),
):
    if not q or len(q.strip()) < 2:
        raise HTTPException(400, detail="Query must be at least 2 characters")

    q = q.strip()

    # ── 1. League search ──────────────────────────────────────────────────────
    leagues_result = []
    for slug, cfg in LEAGUES.items():
        if _matches_query(cfg["name"], q) or _matches_query(slug, q) or \
           _matches_query(cfg.get("short", ""), q) or _matches_query(cfg.get("country", ""), q):
            leagues_result.append({
                "slug":      slug,
                "name":      cfg["name"],
                "short":     cfg.get("short", ""),
                "country":   cfg.get("country", ""),
                "logo_url":  cfg.get("logo_url", ""),
                "streaming": STREAMING.get(slug, {}),
            })

    # ── 2. Team search (from standings cache) ─────────────────────────────────
    teams_result = []
    seen_teams: set[str] = set()

    for cache_key in ("fd_leagues", "tsdb_leagues"):
        cache_data = get_cache(cache_key) or {}
        for league_slug, league_data in cache_data.items():
            for row in league_data.get("standings", []):
                name = row.get("club", "")
                short = row.get("club_short", "")
                team_id = row.get("team_id", "")
                if _matches_query(name, q) or _matches_query(short, q):
                    key = name.lower()
                    if key not in seen_teams:
                        seen_teams.add(key)
                        teams_result.append({
                            "team_id":     team_id,
                            "name":        name,
                            "short":       short,
                            "logo":        row.get("club_logo", ""),
                            "league":      LEAGUES.get(league_slug, {}).get("name", league_slug),
                            "league_slug": league_slug,
                            "position":    row.get("position"),
                            "points":      row.get("points"),
                        })

    # Also check team names in match data
    for cache_key in ("fd_leagues", "tsdb_leagues"):
        cache_data = get_cache(cache_key) or {}
        for league_slug, league_data in cache_data.items():
            for match in league_data.get("upcoming", []) + league_data.get("recent", []):
                for side in ("home", "away"):
                    name = match.get(f"{side}_team", "")
                    short = match.get(f"{side}_team_short", "")
                    team_id = match.get(f"{side}_team_id", "")
                    if _matches_query(name, q) or _matches_query(short, q):
                        key = name.lower()
                        if key not in seen_teams:
                            seen_teams.add(key)
                            teams_result.append({
                                "team_id":     team_id,
                                "name":        name,
                                "short":       short,
                                "logo":        match.get(f"{side}_logo", ""),
                                "league":      LEAGUES.get(league_slug, {}).get("name", league_slug),
                                "league_slug": league_slug,
                                "position":    None,
                                "points":      None,
                            })

    # ── 3. Player search (from scorers cache) ─────────────────────────────────
    players_result = []
    seen_players: set[str] = set()

    for cache_key in ("fd_leagues", "tsdb_leagues"):
        cache_data = get_cache(cache_key) or {}
        for league_slug, league_data in cache_data.items():
            for scorer in league_data.get("scorers", []):
                name = scorer.get("name", "")
                if _matches_query(name, q):
                    key = f"{name}_{league_slug}"
                    if key not in seen_players:
                        seen_players.add(key)
                        players_result.append({
                            "player_id":   scorer.get("player_id", ""),
                            "name":        name,
                            "team":        scorer.get("team", ""),
                            "team_logo":   scorer.get("team_logo", ""),
                            "nationality": scorer.get("nationality", ""),
                            "goals":       scorer.get("goals", 0),
                            "assists":     scorer.get("assists", 0),
                            "league_slug": league_slug,
                            "league":      LEAGUES.get(league_slug, {}).get("name", league_slug),
                            "source":      "scorers_cache",
                        })

    # SofaScore player search (live — fills gap for players not in scorers list)
    if len(players_result) < 3 and len(q) >= 3:
        cached_players = _pcache_get(q)
        if cached_players is not None:
            players_result.extend(cached_players)
        else:
            try:
                ss_players = await search_players(q)
                _pcache_set(q, ss_players)
                for p in ss_players:
                    key = f"{p.get('name','')}_{p.get('player_id','')}"
                    if key not in seen_players:
                        seen_players.add(key)
                        players_result.append(p)
            except Exception as ex:
                log.warning(f"SofaScore player search failed: {ex}")

    # ── 4. Match search ───────────────────────────────────────────────────────
    matches_result = []
    seen_matches: set[str] = set()

    all_matches: list[dict] = list(get_cache("live_scores") or [])
    for cache_key in ("fd_leagues", "tsdb_leagues"):
        cache_data = get_cache(cache_key) or {}
        for league_data in cache_data.values():
            all_matches.extend(league_data.get("upcoming", []))
            all_matches.extend(league_data.get("recent", []))

    for m in all_matches:
        home = m.get("home_team", "")
        away = m.get("away_team", "")
        mid  = m.get("match_id", "")
        if (_matches_query(home, q) or _matches_query(away, q)) and mid not in seen_matches:
            seen_matches.add(mid)
            matches_result.append({
                "match_id":        mid,
                "home_team":       home,
                "home_team_short": m.get("home_team_short", ""),
                "away_team":       away,
                "away_team_short": m.get("away_team_short", ""),
                "home_logo":       m.get("home_logo", ""),
                "away_logo":       m.get("away_logo", ""),
                "status":          m.get("status", ""),
                "score":           m.get("score"),
                "kickoff_display": m.get("kickoff_display", ""),
                "kickoff_iso":     m.get("kickoff_iso", ""),
                "league":          m.get("league", ""),
                "league_slug":     m.get("league_slug", ""),
            })

    # Sort matches: live first, then by kickoff
    def _sort_key(m):
        s = m.get("status", "")
        if s in ("live", "halftime"):
            return "0"
        return m.get("kickoff_iso", "9")

    matches_result.sort(key=_sort_key)

    return {
        "query":   q,
        "leagues": leagues_result[:5],
        "teams":   teams_result[:10],
        "players": players_result[:10],
        "matches": matches_result[:15],
        "total":   len(leagues_result) + len(teams_result) + len(players_result) + len(matches_result),
    }
