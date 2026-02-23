"""
app/scrapers/football_data.py
═══════════════════════════════════════════════════════════════════════════════
Scrapes football-data.org v4 API (authenticated, free tier).

Provides for European leagues (PL, PD, BL1, SA, FL1, CL, EL, WC):
  • Fixtures and results (scheduled + finished matches)
  • Official standings table (total / home / away)
  • Top scorers + assists
  • Squad / team list

Rate limit: 10 req/min → we wait FD_DELAY_S between requests.
The scheduler never calls this during high-frequency live cycles —
it runs on its own 30-minute cadence.

This scraper NEVER provides live scores (football-data.org has no live API).
Live scores come from SofaScore only.
═══════════════════════════════════════════════════════════════════════════════
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import pytz

from app.core.config import (
    FD_BASE, FD_DELAY_S, FD_SLUG_TO_CODE, FD_LEAGUE_CODES,
    STREAMING, LEAGUES, get_team_logo, IST,
)
from app.core.http_client import fd_client

log = logging.getLogger("fd_scraper")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_to_ist_display(utc_str: str) -> str:
    """'2024-03-16T15:00:00Z' → '16 Mar • 08:30 PM IST'"""
    if not utc_str:
        return ""
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        ist = dt.astimezone(IST)
        return ist.strftime("%d %b • %I:%M %p IST")
    except Exception:
        return utc_str


def _utc_to_ist_iso(utc_str: str) -> str:
    """'2024-03-16T15:00:00Z' → '2024-03-16T20:30:00' (IST, no tz suffix)"""
    if not utc_str:
        return ""
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone(IST).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return utc_str


def _match_status(status: str) -> str:
    """Normalise football-data status to our internal status string."""
    s = status.upper()
    if s in ("IN_PLAY", "PAUSED"):   return "live"
    if s == "HALF_TIME":             return "halftime"
    if s in ("FINISHED", "AWARDED"): return "finished"
    if s in ("TIMED", "SCHEDULED"):  return "scheduled"
    return s.lower()


def _build_match(m: dict, league_slug: str) -> dict:
    home = m.get("homeTeam", {})
    away = m.get("awayTeam", {})
    score = m.get("score", {})
    ft    = score.get("fullTime", {})
    ht    = score.get("halfTime", {})
    status = _match_status(m.get("status", ""))
    utc_date = m.get("utcDate", "")

    cfg = LEAGUES.get(league_slug, {})
    streaming = STREAMING.get(league_slug, {})

    return {
        "match_id":        str(m.get("id", "")),
        "home_team":       home.get("name", ""),
        "home_team_short": home.get("shortName", ""),
        "home_team_tla":   home.get("tla", ""),
        "away_team":       away.get("name", ""),
        "away_team_short": away.get("shortName", ""),
        "away_team_tla":   away.get("tla", ""),
        # football-data.org always provides crests for European teams
        "home_logo":       get_team_logo(home.get("name",""), home.get("crest","")),
        "away_logo":       get_team_logo(away.get("name",""), away.get("crest","")),
        "home_team_id":    str(home.get("id", "")),
        "away_team_id":    str(away.get("id", "")),
        "score": {
            "home":    ft.get("home"),
            "away":    ft.get("away"),
            "home_ht": ht.get("home"),
            "away_ht": ht.get("away"),
        },
        "status":          status,
        "minute":          None,  # FD.org has no live data
        "league":          cfg.get("name", league_slug),
        "league_slug":     league_slug,
        "league_logo":     cfg.get("logo_url", ""),
        "league_country":  cfg.get("country", ""),
        "stadium":         m.get("venue", ""),
        "round":           m.get("matchday") and f"Matchday {m['matchday']}" or m.get("stage",""),
        "referee":         m.get("referees", [{}])[0].get("name","") if m.get("referees") else "",
        "kickoff_iso":     _utc_to_ist_iso(utc_date),
        "kickoff_display": _utc_to_ist_display(utc_date),
        "kickoff_utc":     utc_date,
        "streaming":       streaming,
        "source":          "football-data",
    }


async def _get(path: str) -> Optional[dict]:
    """Rate-limited GET from football-data.org. Returns parsed JSON or None."""
    client = fd_client()
    url = f"{FD_BASE}{path}"
    try:
        resp = await client.get(url)
        if resp.status_code == 429:
            log.warning(f"FD rate limit hit for {path} — waiting 60s")
            await asyncio.sleep(60)
            resp = await client.get(url)
        if resp.status_code != 200:
            log.warning(f"FD HTTP {resp.status_code} for {path}")
            return None
        return resp.json()
    except Exception as ex:
        log.warning(f"FD request failed ({path}): {ex}")
        return None


# ── Per-league scrapers ───────────────────────────────────────────────────────

async def scrape_league_matches(league_slug: str) -> dict:
    """
    Fetch all matches for a league (current season).
    Returns {"upcoming": [...], "recent": [...]}
    upcoming = SCHEDULED
    recent   = FINISHED from last 14 days
    """
    code = FD_SLUG_TO_CODE.get(league_slug)
    if not code:
        return {"upcoming": [], "recent": []}

    data = await _get(f"/competitions/{code}/matches")
    await asyncio.sleep(FD_DELAY_S)

    if not data:
        return {"upcoming": [], "recent": []}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=14)

    upcoming, recent = [], []
    for m in data.get("matches", []):
        match = _build_match(m, league_slug)
        if match["status"] == "scheduled":
            upcoming.append(match)
        elif match["status"] == "finished":
            utc_str = m.get("utcDate", "")
            try:
                dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                if dt >= cutoff:
                    recent.append(match)
            except Exception:
                recent.append(match)

    # Sort upcoming ascending, recent descending
    upcoming.sort(key=lambda x: x["kickoff_utc"])
    recent.sort(key=lambda x: x["kickoff_utc"], reverse=True)

    return {"upcoming": upcoming[:30], "recent": recent[:20]}


async def scrape_standings(league_slug: str) -> list[dict]:
    """
    Fetch official standings for a league.
    Returns the TOTAL standing table sorted by position.
    """
    code = FD_SLUG_TO_CODE.get(league_slug)
    if not code:
        return []

    data = await _get(f"/competitions/{code}/standings")
    await asyncio.sleep(FD_DELAY_S)

    if not data:
        return []

    # Extract TOTAL standing (not HOME or AWAY)
    for standing in data.get("standings", []):
        if standing.get("type") == "TOTAL":
            table = []
            for row in standing.get("table", []):
                team = row.get("team", {})
                form_raw = row.get("form") or ""
                # form from FD is "W,D,L,W,W" → take last 5
                form_list = [f.strip() for f in form_raw.split(",") if f.strip()][-5:]
                table.append({
                    "position":        row.get("position", 0),
                    "club":            team.get("name", ""),
                    "club_short":      team.get("shortName", ""),
                    "club_tla":        team.get("tla", ""),
                    "club_logo":       get_team_logo(team.get("name",""), team.get("crest","")),
                    "team_id":         str(team.get("id", "")),
                    "played":          row.get("playedGames", 0),
                    "won":             row.get("won", 0),
                    "drawn":           row.get("draw", 0),
                    "lost":            row.get("lost", 0),
                    "goals_for":       row.get("goalsFor", 0),
                    "goals_against":   row.get("goalsAgainst", 0),
                    "goal_difference": row.get("goalDifference", 0),
                    "points":          row.get("points", 0),
                    "form":            form_list,  # list of "W"/"D"/"L", last 5
                })
            return table

    return []


async def scrape_scorers(league_slug: str, limit: int = 10) -> list[dict]:
    """
    Fetch top scorers for a league (goals + assists + penalties).
    """
    code = FD_SLUG_TO_CODE.get(league_slug)
    if not code:
        return []

    data = await _get(f"/competitions/{code}/scorers?limit={limit}")
    await asyncio.sleep(FD_DELAY_S)

    if not data:
        return []

    result = []
    for entry in data.get("scorers", []):
        player = entry.get("player", {})
        team   = entry.get("team", {})
        result.append({
            "player_id":   str(player.get("id", "")),
            "name":        player.get("name", ""),
            "first_name":  player.get("firstName", ""),
            "nationality": player.get("nationality", ""),
            "position":    player.get("position", ""),
            "dob":         player.get("dateOfBirth", ""),
            "team":        team.get("name", ""),
            "team_short":  team.get("shortName", ""),
            "team_logo":   get_team_logo(team.get("name",""), team.get("crest","")),
            "goals":       entry.get("goals", 0),
            "assists":     entry.get("assists", 0) or 0,
            "penalties":   entry.get("penalties", 0) or 0,
            "played":      entry.get("playedMatches", 0) or 0,
        })

    return result


async def scrape_squad(team_id: str) -> dict:
    """
    Fetch squad (players + coach) for a team from football-data.org.
    Called on-demand — cached separately per team.
    """
    data = await _get(f"/teams/{team_id}")
    await asyncio.sleep(FD_DELAY_S)

    if not data:
        return {}

    squad = []
    for p in data.get("squad", []):
        squad.append({
            "id":          str(p.get("id", "")),
            "name":        p.get("name", ""),
            "position":    p.get("position", ""),
            "dob":         p.get("dateOfBirth", ""),
            "nationality": p.get("nationality", ""),
            "shirt_no":    p.get("shirtNumber"),
        })

    coach = data.get("coach", {})
    return {
        "team_id":     str(data.get("id", "")),
        "name":        data.get("name", ""),
        "short_name":  data.get("shortName", ""),
        "logo":        get_team_logo(data.get("name",""), data.get("crest","")),
        "venue":       data.get("venue", ""),
        "founded":     data.get("founded"),
        "colors":      data.get("clubColors", ""),
        "website":     data.get("website", ""),
        "coach":       coach.get("name", ""),
        "coach_nationality": coach.get("nationality",""),
        "squad":       squad,
    }


async def scrape_team_matches(team_id: str) -> list[dict]:
    """
    Fetch last 5 + next 5 matches for a team across all subscribed competitions.
    Used for team form and upcoming fixtures widgets.
    """
    now     = datetime.now(timezone.utc)
    d_from  = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    d_to    = (now + timedelta(days=90)).strftime("%Y-%m-%d")

    data = await _get(f"/teams/{team_id}/matches?dateFrom={d_from}&dateTo={d_to}&limit=50")
    await asyncio.sleep(FD_DELAY_S)

    if not data:
        return []

    result = []
    for m in data.get("matches", []):
        comp = m.get("competition", {})
        comp_code = comp.get("code", "")
        slug = FD_LEAGUE_CODES.get(comp_code, comp_code.lower())
        result.append(_build_match(m, slug))

    return result


async def scrape_h2h(match_id: str) -> list[dict]:
    """
    Fetch last 5 head-to-head matches using football-data.org H2H endpoint.
    Endpoint: /matches/{id}/head2head
    """
    data = await _get(f"/matches/{match_id}/head2head?limit=5")
    await asyncio.sleep(FD_DELAY_S)

    if not data:
        return []

    result = []
    for m in data.get("matches", [])[:5]:
        comp = m.get("competition", {})
        slug = FD_LEAGUE_CODES.get(comp.get("code",""), "unknown")
        result.append(_build_match(m, slug))

    return result


# ── Full all-leagues batch scrape ─────────────────────────────────────────────

async def scrape_all_fd_leagues() -> dict:
    """
    Scrape fixtures + standings + scorers for all football-data.org leagues.
    Respects rate limit with FD_DELAY_S between each request.
    Returns: {league_slug: {upcoming, recent, standings, scorers}}
    """
    result = {}
    fd_slugs = [
        slug for slug, cfg in LEAGUES.items()
        if cfg.get("data_source") == "football-data"
    ]

    for slug in fd_slugs:
        log.info(f"FD scraping: {slug}")
        try:
            matches   = await scrape_league_matches(slug)
            standings = await scrape_standings(slug)
            scorers   = await scrape_scorers(slug)
            result[slug] = {
                "upcoming":  matches["upcoming"],
                "recent":    matches["recent"],
                "standings": standings,
                "scorers":   scorers,
            }
        except Exception as ex:
            log.error(f"FD scrape failed for {slug}: {ex}")

    return result
