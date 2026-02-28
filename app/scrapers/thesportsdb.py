"""
app/scrapers/thesportsdb.py
═══════════════════════════════════════════════════════════════════════════════
TheSportsDB free public API (api key = 3, no registration required).

Used for leagues NOT covered by football-data.org free tier:
  • ISL  (Indian Super League)       league ID 4346
  • IFL  (I-League)                  league ID 4347
  • AFC  (AFC Champions League)      league ID 4659
  • UECL (UEFA Conference League)    league ID 4744

Endpoints used:
  /api/v1/json/3/eventsnext.php?id={lid}          → next 25 upcoming events
  /api/v1/json/3/eventslast.php?id={lid}          → last 15 finished events
  /api/v1/json/3/lookuptable.php?l={lid}&s={ssn}  → standings table

Returns same match dict shape as every other scraper so the router
can serve it transparently.
═══════════════════════════════════════════════════════════════════════════════
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import pytz

from app.core.config import LEAGUES, STREAMING, get_team_logo, IST
from app.core.http_client import plain_client
from app.scrapers.sofascore import fetch_ss_scorers

log = logging.getLogger("thesportsdb")

TSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"

# league slug → TheSportsDB league ID + current season string
# league slug → TheSportsDB league ID + current season string
# NOTE: europa-league is intentionally NOT here — it's handled by football-data.org
# (data_source = "football-data" in config.py). It was previously listed here
# causing confusion even though the guard in scrape_all_tsdb_leagues() prevented
# double-scraping. Removed to keep this table unambiguous.
TSDB_LEAGUES: dict[str, dict] = {
    "isl":               {"id": 4346, "season": "2024-2025"},
    "ifl":               {"id": 4347, "season": "2024-2025"},
    "afc":               {"id": 4659, "season": "2024-2025"},
    "conference-league": {"id": 4744, "season": "2024-2025"},
}

# TheSportsDB status strings
_FINISHED = {"Match Finished", "FT", "AET", "PEN"}
_LIVE     = {"Live", "HT", "Half Time", "ET", "Penalties"}


def _parse_dt(date_str: str, time_str: str) -> Optional[datetime]:
    """Parse TheSportsDB date + time (UTC) to timezone-aware UTC datetime."""
    if not date_str:
        return None
    try:
        t = (time_str or "00:00:00").strip()
        if len(t) == 5:          # "19:30"
            t += ":00"
        raw = f"{date_str.strip()} {t}"
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _ist_display(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    return dt.astimezone(IST).strftime("%d %b • %I:%M %p IST")


def _ist_iso(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    return dt.astimezone(IST).strftime("%Y-%m-%dT%H:%M:%S")


def _match_status(tsdb_status: Optional[str], dt: Optional[datetime]) -> str:
    s = (tsdb_status or "").strip()
    if s in _FINISHED:
        return "finished"
    if s in _LIVE:
        return "live"
    # "Not Started" or empty — infer from time
    if dt:
        now = datetime.now(timezone.utc)
        if dt > now:
            return "scheduled"
    return "scheduled"


def _build_match(event: dict, league_slug: str) -> dict:
    cfg  = LEAGUES.get(league_slug, {})
    home = event.get("strHomeTeam", "")
    away = event.get("strAwayTeam", "")
    dt   = _parse_dt(event.get("dateEvent", ""), event.get("strTime", ""))

    raw_hs  = event.get("intHomeScore")
    raw_aws = event.get("intAwayScore")
    hs  = int(raw_hs)  if raw_hs  not in (None, "", "null") else None
    aws = int(raw_aws) if raw_aws not in (None, "", "null") else None

    status = _match_status(event.get("strStatus"), dt)

    return {
        "match_id":        str(event.get("idEvent", "")),
        "home_team":       home,
        "home_team_short": home,
        "away_team":       away,
        "away_team_short": away,
        "home_logo":       get_team_logo(home),
        "away_logo":       get_team_logo(away),
        "home_team_id":    str(event.get("idHomeTeam", "")),
        "away_team_id":    str(event.get("idAwayTeam", "")),
        "score": {
            "home":    hs,
            "away":    aws,
            "home_ht": None,
            "away_ht": None,
        },
        "status":          status,
        "minute":          None,
        "league":          cfg.get("name", league_slug),
        "league_slug":     league_slug,
        "league_logo":     cfg.get("logo_url", ""),
        "league_country":  cfg.get("country", ""),
        "stadium":         event.get("strVenue", ""),
        "round":           f"Round {event.get('intRound', '')}".strip(),
        "kickoff_iso":     _ist_iso(dt),
        "kickoff_display": _ist_display(dt),
        # Normalise kickoff_utc to ISO format so it sorts correctly alongside FD matches
        # FD uses "2024-03-16T15:00:00Z", TSDB was using "2024-03-16 19:30:00" (mixed format)
        "kickoff_utc":     dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else "",
        "streaming":       STREAMING.get(league_slug, {}),
        "source":          "thesportsdb",
    }


async def _get(path: str) -> Optional[dict]:
    client = plain_client()
    url = f"{TSDB_BASE}{path}"
    try:
        resp = await client.get(url, timeout=20)
        if resp.status_code != 200:
            log.warning(f"TSDB HTTP {resp.status_code} for {path}")
            return None
        return resp.json()
    except Exception as ex:
        log.warning(f"TSDB request failed ({path}): {ex}")
        return None


async def scrape_tsdb_league(league_slug: str) -> dict:
    """
    Fetch upcoming + recent fixtures and standings for one league.
    Returns the standard {live, upcoming, recent, standings, scorers} dict.
    """
    cfg = TSDB_LEAGUES.get(league_slug)
    if not cfg:
        log.warning(f"No TSDB config for {league_slug}")
        return {}

    lid    = cfg["id"]
    season = cfg["season"]

    # 1. Next events (upcoming fixtures)
    upcoming = []
    data = await _get(f"/eventsnext.php?id={lid}")
    await asyncio.sleep(0.3)
    if data:
        events = data.get("events") or []
        for e in events:
            m = _build_match(e, league_slug)
            if m["status"] == "scheduled":
                upcoming.append(m)

    # 2. Last events (recent results)
    recent = []
    data = await _get(f"/eventslast.php?id={lid}")
    await asyncio.sleep(0.3)
    if data:
        events = data.get("results") or data.get("events") or []
        for e in events:
            m = _build_match(e, league_slug)
            if m["status"] == "finished":
                recent.append(m)

    # Sort: upcoming ascending, recent descending
    upcoming.sort(key=lambda m: m["kickoff_utc"])
    recent.sort(key=lambda m: m["kickoff_utc"], reverse=True)

    # 3. Standings table
    standings = []
    data = await _get(f"/lookuptable.php?l={lid}&s={season}")
    await asyncio.sleep(0.3)
    if data:
        table = data.get("table") or []
        for row in table:
            team_name = row.get("strTeam", "")
            form_raw  = row.get("strForm") or ""
            form_list = list(form_raw.replace(",", "").upper())[-5:]

            try:
                gf  = int(row.get("intGoalsFor",     0) or 0)
                ga  = int(row.get("intGoalsAgainst", 0) or 0)
                standings.append({
                    "position":        int(row.get("intRank", 0) or 0),
                    "club":            team_name,
                    "club_short":      team_name,
                    "club_logo":       get_team_logo(team_name),
                    "played":          int(row.get("intPlayed", 0) or 0),
                    "won":             int(row.get("intWin",    0) or 0),
                    "drawn":           int(row.get("intDraw",   0) or 0),
                    "lost":            int(row.get("intLoss",   0) or 0),
                    "goals_for":       gf,
                    "goals_against":   ga,
                    "goal_difference": int(row.get("intGoalDifference", gf - ga) or gf - ga),
                    "points":          int(row.get("intPoints", 0) or 0),
                    "form":            form_list,
                })
            except (ValueError, TypeError):
                continue

    log.info(f"TSDB {league_slug}: {len(upcoming)} upcoming, {len(recent)} recent, {len(standings)} standings rows")

    # Fetch scorers from SofaScore for leagues that have an ss_id
    scorers = []
    cfg_league = LEAGUES.get(league_slug, {})
    ss_id = cfg_league.get("ss_id")
    if ss_id:
        try:
            scorers = await fetch_ss_scorers(league_slug, ss_id)
            log.info(f"TSDB {league_slug}: {len(scorers)} scorers from SofaScore")
        except Exception as ex:
            log.warning(f"SS scorers fetch failed for {league_slug}: {ex}")

    return {
        "live":      [],
        "upcoming":  upcoming[:25],
        "recent":    recent[:20],
        "standings": standings,
        "scorers":   scorers,
    }


async def scrape_all_tsdb_leagues() -> dict:
    """
    Scrape all leagues assigned data_source == 'thesportsdb'.
    Called by scheduler every 60 minutes.
    """
    results = {}
    for slug in TSDB_LEAGUES:
        cfg_league = LEAGUES.get(slug, {})
        if cfg_league.get("data_source") == "thesportsdb":
            data = await scrape_tsdb_league(slug)
            if data:
                results[slug] = data
            await asyncio.sleep(0.5)
    return results
