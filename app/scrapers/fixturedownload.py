"""
app/scrapers/fixturedownload.py
═══════════════════════════════════════════════════════════════════════════════
Scrapes fixturedownload.com JSON feeds for Indian leagues only:
  • ISL  (Indian Super League)
  • IFL  (Indian Football League — formerly I-League, rebranded)

Feed format:  https://fixturedownload.com/feed/json/{id}
Each row:
{
  "MatchNumber": 1,
  "RoundNumber": 1,
  "DateUtc": "2024-09-13 14:00:00Z",
  "Location": "Salt Lake Stadium, Kolkata",
  "HomeTeam": "ATK Mohun Bagan",
  "AwayTeam": "Mumbai City FC",
  "Group": null,
  "HomeTeamScore": 1,
  "AwayTeamScore": 2
}

Standings are computed locally from match results — no extra requests needed.
No overlap with football-data.org (Indian leagues are not on FD.org free tier).
═══════════════════════════════════════════════════════════════════════════════
"""

import logging
from datetime import datetime
from typing import Optional

import pytz

from app.core.config import LEAGUES, STREAMING, get_team_logo, IST, FD_DOWNLOAD_BASE
from app.core.http_client import plain_client

log = logging.getLogger("fixturedownload")


def _parse_utc(raw: str) -> Optional[datetime]:
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=pytz.utc)
    except Exception:
        return None


def _ist_display(dt_utc: Optional[datetime]) -> str:
    if not dt_utc:
        return ""
    return dt_utc.astimezone(IST).strftime("%d %b • %I:%M %p IST")


def _ist_iso(dt_utc: Optional[datetime]) -> str:
    if not dt_utc:
        return ""
    return dt_utc.astimezone(IST).strftime("%Y-%m-%dT%H:%M:%S")


def _build_match(row: dict, league_slug: str) -> dict:
    cfg       = LEAGUES.get(league_slug, {})
    streaming = STREAMING.get(league_slug, {})
    home_name = row.get("HomeTeam", "")
    away_name = row.get("AwayTeam", "")
    dt_utc    = _parse_utc(row.get("DateUtc", ""))
    hs        = row.get("HomeTeamScore")
    aws       = row.get("AwayTeamScore")

    now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)

    if hs is not None and aws is not None:
        status = "finished"
    elif dt_utc and dt_utc > now_utc:
        status = "scheduled"
    else:
        status = "scheduled"

    return {
        "match_id":        f"fd-{league_slug}-{row.get('MatchNumber', 0)}",
        "home_team":       home_name,
        "home_team_short": home_name,
        "away_team":       away_name,
        "away_team_short": away_name,
        "home_logo":       get_team_logo(home_name),
        "away_logo":       get_team_logo(away_name),
        "home_team_id":    "",
        "away_team_id":    "",
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
        "league_country":  "India",
        "stadium":         row.get("Location", ""),
        "round":           f"Round {row.get('RoundNumber', '')}",
        "kickoff_iso":     _ist_iso(dt_utc),
        "kickoff_display": _ist_display(dt_utc),
        "kickoff_utc":     row.get("DateUtc", ""),
        "streaming":       streaming,
        "source":          "fixturedownload",
    }


def _compute_standings(matches: list[dict]) -> list[dict]:
    """Build a league table from finished matches."""
    table: dict[str, dict] = {}

    def _ensure(team: str):
        if team not in table:
            table[team] = {
                "club": team,
                "club_short": team,
                "club_logo": get_team_logo(team),
                "played": 0, "won": 0, "drawn": 0, "lost": 0,
                "goals_for": 0, "goals_against": 0,
                "goal_difference": 0, "points": 0,
                "form": [],
            }

    for m in matches:
        if m["status"] != "finished":
            continue
        hs, aws = m["score"]["home"], m["score"]["away"]
        if hs is None or aws is None:
            continue
        ht, at = m["home_team"], m["away_team"]
        _ensure(ht); _ensure(at)

        table[ht]["played"] += 1; table[at]["played"] += 1
        table[ht]["goals_for"] += hs; table[ht]["goals_against"] += aws
        table[at]["goals_for"] += aws; table[at]["goals_against"] += hs

        if hs > aws:
            table[ht]["won"] += 1; table[ht]["points"] += 3; table[at]["lost"] += 1
            table[ht]["form"].append("W"); table[at]["form"].append("L")
        elif aws > hs:
            table[at]["won"] += 1; table[at]["points"] += 3; table[ht]["lost"] += 1
            table[at]["form"].append("W"); table[ht]["form"].append("L")
        else:
            table[ht]["drawn"] += 1; table[ht]["points"] += 1
            table[at]["drawn"] += 1; table[at]["points"] += 1
            table[ht]["form"].append("D"); table[at]["form"].append("D")

    standings = []
    for pos, (_, entry) in enumerate(
        sorted(
            table.items(),
            key=lambda x: (-x[1]["points"], -(x[1]["goals_for"] - x[1]["goals_against"]), -x[1]["goals_for"])
        ), start=1
    ):
        entry["position"]        = pos
        entry["goal_difference"] = entry["goals_for"] - entry["goals_against"]
        entry["form"]            = entry["form"][-5:]  # last 5 results as list
        standings.append(entry)

    return standings


async def scrape_fd_league(league_slug: str) -> dict:
    """Fetch and parse one Indian league from fixturedownload.com."""
    cfg   = LEAGUES.get(league_slug, {})
    fd_id = cfg.get("fd_download_id")
    if not fd_id:
        log.warning(f"No fd_download_id for {league_slug}")
        return {}

    client = plain_client()
    url    = f"{FD_DOWNLOAD_BASE}/{fd_id}"
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            log.warning(f"fixturedownload HTTP {resp.status_code} for {league_slug}")
            return {}
        rows = resp.json()
    except Exception as ex:
        log.warning(f"fixturedownload failed for {league_slug}: {ex}")
        return {}

    if not isinstance(rows, list):
        return {}

    all_matches = [_build_match(r, league_slug) for r in rows]
    finished    = [m for m in all_matches if m["status"] == "finished"]
    upcoming    = [m for m in all_matches if m["status"] == "scheduled"]

    # Sort
    finished.sort(key=lambda m: m["kickoff_utc"], reverse=True)
    upcoming.sort(key=lambda m: m["kickoff_utc"])

    return {
        "live":         [],               # No live data from fixturedownload
        "recent":       finished[:20],
        "upcoming":     upcoming[:20],
        "standings":    _compute_standings(all_matches),
        "scorers":      [],               # No player data in fixturedownload
        "all_matches":  all_matches,
    }


async def scrape_all_indian_leagues() -> dict:
    """Scrape ISL + IFL. Returns {league_slug: data}."""
    results = {}
    for slug, cfg in LEAGUES.items():
        if cfg.get("data_source") == "fixturedownload":
            data = await scrape_fd_league(slug)
            if data:
                results[slug] = data
    return results
