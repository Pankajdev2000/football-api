"""
app/scrapers/sofascore.py
═══════════════════════════════════════════════════════════════════════════════
SofaScore public JSON API — used for LIVE SCORES ONLY.

football-data.org handles fixtures/standings/scorers for European leagues.
SofaScore fills the one gap FD.org cannot: live in-progress match data.

Also provides:
  • Match lineups (on-demand, not cached in main loop)
  • Team form (last 5 in competition, on-demand)
═══════════════════════════════════════════════════════════════════════════════
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytz

from app.core.config import SS_BASE, SS_TOURNAMENT_IDS, LEAGUES, STREAMING, get_team_logo, IST
from app.core.http_client import ss_client

log = logging.getLogger("sofascore")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ist_display(ts: Optional[int]) -> str:
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(IST)
    return dt.strftime("%d %b • %I:%M %p IST")


def _ist_iso(ts: Optional[int]) -> str:
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(IST)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _status(event: dict) -> str:
    code = event.get("status", {}).get("code", 0)
    if code == 6:   return "live"
    if code == 31:  return "halftime"
    if code == 100: return "finished"
    return "scheduled"


def _minute(event: dict) -> Optional[int]:
    return event.get("time", {}).get("played")


def _score(event: dict, side: str) -> Optional[int]:
    key = "homeScore" if side == "home" else "awayScore"
    return event.get(key, {}).get("current")


def _ht_score(event: dict, side: str) -> Optional[int]:
    key = "homeScore" if side == "home" else "awayScore"
    return event.get(key, {}).get("period1")


def _build_match(event: dict, league_slug: str) -> dict:
    home = event.get("homeTeam", {})
    away = event.get("awayTeam", {})
    cfg  = LEAGUES.get(league_slug, {})
    ts   = event.get("startTimestamp")

    return {
        "match_id":        str(event.get("id", "")),
        "home_team":       home.get("name", ""),
        "home_team_short": home.get("shortName", home.get("name", "")),
        "away_team":       away.get("name", ""),
        "away_team_short": away.get("shortName", away.get("name", "")),
        "home_logo":       get_team_logo(home.get("name", "")),
        "away_logo":       get_team_logo(away.get("name", "")),
        "home_team_id":    str(home.get("id", "")),
        "away_team_id":    str(away.get("id", "")),
        "score": {
            "home":    _score(event, "home"),
            "away":    _score(event, "away"),
            "home_ht": _ht_score(event, "home"),
            "away_ht": _ht_score(event, "away"),
        },
        "status":          _status(event),
        "minute":          _minute(event),
        "league":          cfg.get("name", league_slug),
        "league_slug":     league_slug,
        "league_logo":     cfg.get("logo_url", ""),
        "league_country":  cfg.get("country", ""),
        "stadium":         event.get("venue", {}).get("stadium", {}).get("name", ""),
        "round":           event.get("roundInfo", {}).get("name", ""),
        "kickoff_iso":     _ist_iso(ts),
        "kickoff_display": _ist_display(ts),
        "streaming":       STREAMING.get(league_slug, {}),
        "source":          "sofascore",
    }


# ── Live score scraper (called every 3–7 min by scheduler) ───────────────────

async def scrape_live_scores() -> list[dict]:
    """
    Fetch all in-progress matches for tracked tournaments.
    Checks today ±1 day to handle IST/UTC date boundaries.
    Returns only LIVE and HALFTIME matches.
    """
    client = ss_client()
    live   = []
    today  = datetime.now(timezone.utc).date()

    for offset in (-1, 0, 1):
        date_str = (today + timedelta(days=offset)).isoformat()
        url = f"{SS_BASE}/sport/football/scheduled-events/{date_str}"
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                continue
            events = resp.json().get("events", [])
        except Exception as ex:
            log.warning(f"SS fetch failed for {date_str}: {ex}")
            continue

        for event in events:
            tid  = event.get("tournament", {}).get("uniqueTournament", {}).get("id")
            slug = SS_TOURNAMENT_IDS.get(tid)
            if not slug:
                continue
            status = _status(event)
            if status in ("live", "halftime"):
                live.append(_build_match(event, slug))

        await asyncio.sleep(0.3)

    return live


# ── Lineups (on-demand) ───────────────────────────────────────────────────────

async def fetch_lineups(ss_match_id: str) -> dict:
    """
    Fetch lineups for a SofaScore match ID.
    Called on-demand from the matches router, cached there for 10 min.
    """
    client = ss_client()
    url = f"{SS_BASE}/event/{ss_match_id}/lineups"
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            return {}
        data = resp.json()

        def parse_side(side: dict) -> list[dict]:
            return [
                {
                    "name":       p.get("player", {}).get("name", ""),
                    "shirt_no":   p.get("shirtNumber"),
                    "position":   p.get("position", ""),
                    "captain":    p.get("captain", False),
                    "substitute": p.get("substitute", False),
                    "rating":     p.get("statistics", {}).get("rating"),
                }
                for p in side.get("players", [])
            ]

        return {
            "confirmed": data.get("confirmed", False),
            "home":      parse_side(data.get("home", {})),
            "away":      parse_side(data.get("away", {})),
        }
    except Exception as ex:
        log.warning(f"SS lineups failed for {ss_match_id}: {ex}")
        return {}


# ── Team form (on-demand) ─────────────────────────────────────────────────────

async def fetch_team_form(ss_team_id: str, league_slug: str) -> list[dict]:
    """
    Fetch last 5 matches for a team in a competition from SofaScore.
    Used only for Conference League and AFC (not on football-data.org free tier).
    """
    cfg = LEAGUES.get(league_slug, {})
    tid = cfg.get("ss_id")
    if not tid:
        return []

    client = ss_client()
    # Get current season for the tournament
    try:
        seasons_resp = await client.get(f"{SS_BASE}/unique-tournament/{tid}/seasons")
        if seasons_resp.status_code != 200:
            return []
        seasons = seasons_resp.json().get("seasons", [])
        if not seasons:
            return []
        season_id = seasons[0]["id"]
    except Exception:
        return []

    url = f"{SS_BASE}/team/{ss_team_id}/unique-tournament/{tid}/season/{season_id}/matches/last/0"
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            return []
        events = resp.json().get("events", [])[:5]
        return [_build_match(e, league_slug) for e in events]
    except Exception as ex:
        log.warning(f"SS team form failed for {ss_team_id}: {ex}")
        return []
