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
import re
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
    """
    Map SofaScore status code → normalised status string.
    Full code list (confirmed from SS API):
      0   = Not started
      6   = In progress 1st half
      7   = In progress 2nd half      ← was falling through to "scheduled"
      31  = Half time
      60  = Extra time                ← was falling through to "scheduled"
      61  = Extra time half time      ← was falling through to "scheduled"
      70  = Awaiting penalties        ← was falling through to "scheduled"
      100 = Finished (regular/AET)
      93  = After extra time          ← was falling through to "scheduled"
      94  = After penalties           ← was falling through to "scheduled"
      110 = Postponed
      120 = Cancelled
      999 = Abandoned
    """
    code = event.get("status", {}).get("code", 0)
    # Live / in-progress states
    if code in (6, 7):   return "live"       # 1st half, 2nd half
    if code == 31:       return "halftime"   # Half time
    if code in (60, 61): return "live"       # Extra time, ET halftime
    if code == 70:       return "live"       # Awaiting penalties
    # Finished states
    if code in (100, 93, 94): return "finished"  # FT / AET / Penalties
    # Other terminal states — treat as finished so they don't show as upcoming
    if code in (110, 120, 999): return "finished"
    # 0 = not started → scheduled
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
        "home_logo":       f"https://api.sofascore.com/api/v1/team/{home.get('id','')}/image" if home.get('id') else get_team_logo(home.get("name", "")),
        "away_logo":       f"https://api.sofascore.com/api/v1/team/{away.get('id','')}/image" if away.get('id') else get_team_logo(away.get("name", "")),
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
    from app.core.http_client import rotate_ss_client
    client = ss_client()
    live   = []
    today  = datetime.now(timezone.utc).date()

    for offset in (-1, 0, 1):
        date_str = (today + timedelta(days=offset)).isoformat()
        url = f"{SS_BASE}/sport/football/scheduled-events/{date_str}"
        try:
            resp = await client.get(url)
            if resp.status_code == 403:
                log.warning(f"SS 403 for {date_str} — rotating client and retrying")
                client = rotate_ss_client()
                await asyncio.sleep(1.0)
                resp = await client.get(url)
            if resp.status_code != 200:
                log.warning(f"SS HTTP {resp.status_code} for {date_str}")
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


# ── Match events (on-demand) ──────────────────────────────────────────────────

async def fetch_match_events(ss_match_id: str) -> dict:
    """
    Fetch match incidents: goals, cards, substitutions.
    GET /event/{id}/incidents
    Cached 2 min for live, 60 min for finished (TTL set by router).

    Returns:
    {
        "goals":         [{"minute","team","scorer","assist","type"}],
        "cards":         [{"minute","team","player","type"}],
        "substitutions": [{"minute","team","player_in","player_out"}]
    }
    """
    client = ss_client()
    url = f"{SS_BASE}/event/{ss_match_id}/incidents"
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            log.warning(f"SS incidents HTTP {resp.status_code} for {ss_match_id}")
            return {}
        incidents = resp.json().get("incidents", [])
    except Exception as ex:
        log.warning(f"SS incidents failed for {ss_match_id}: {ex}")
        return {}

    goals, cards, substitutions = [], [], []

    for inc in incidents:
        inc_type   = inc.get("incidentType", "")
        inc_class  = inc.get("incidentClass", "")
        minute     = inc.get("time")
        added      = inc.get("addedTime", 0)
        full_min   = f"{minute}+{added}'" if added else f"{minute}'"
        team       = "home" if inc.get("isHome", True) else "away"

        if inc_type == "goal":
            goals.append({
                "minute": full_min,
                "team":   team,
                "scorer": inc.get("player", {}).get("name", ""),
                "assist": inc.get("assist1", {}).get("name") if inc.get("assist1") else None,
                "type":   "own_goal" if inc_class == "ownGoal" else
                          "penalty"  if inc_class == "penalty"  else "goal",
            })
        elif inc_type == "card":
            cards.append({
                "minute": full_min,
                "team":   team,
                "player": inc.get("player", {}).get("name", ""),
                "type":   "yellow_red" if inc_class == "yellowRed" else
                          "red"        if inc_class == "red"        else "yellow",
            })
        elif inc_type == "substitution":
            substitutions.append({
                "minute":     full_min,
                "team":       team,
                "player_in":  inc.get("playerIn",  {}).get("name", ""),
                "player_out": inc.get("playerOut", {}).get("name", ""),
            })

    return {"goals": goals, "cards": cards, "substitutions": substitutions}


# ── Match stats (on-demand) ───────────────────────────────────────────────────

async def fetch_match_stats(ss_match_id: str) -> dict:
    """
    Fetch match statistics: possession, shots, corners, fouls etc.
    GET /event/{id}/statistics
    Cached by the matches router (10 min live, 60 min finished).

    Returns:
    {
      "home": {"possession": 55, "shots": 12, "shots_on_target": 5,
               "corners": 6, "fouls": 11, "yellow_cards": 2, "red_cards": 0,
               "offsides": 2, "passes": 432, "pass_accuracy": 87,
               "tackles": 18, "saves": 4},
      "away": {...}
    }
    """
    client = ss_client()
    url = f"{SS_BASE}/event/{ss_match_id}/statistics"
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            log.warning(f"SS stats HTTP {resp.status_code} for {ss_match_id}")
            return {}
        data = resp.json()
    except Exception as ex:
        log.warning(f"SS stats failed for {ss_match_id}: {ex}")
        return {}

    home_stats: dict = {}
    away_stats: dict = {}

    # SofaScore returns a list of stat groups, each with "statisticsItems"
    # Key map: SS key → our key
    key_map = {
        "Ball possession":    "possession",
        "Total shots":        "shots",
        "Shots on target":    "shots_on_target",
        "Shots off target":   "shots_off_target",
        "Blocked shots":      "blocked_shots",
        "Corner kicks":       "corners",
        "Fouls":              "fouls",
        "Yellow cards":       "yellow_cards",
        "Red cards":          "red_cards",
        "Offsides":           "offsides",
        "Passes":             "passes",
        "Accurate passes":    "accurate_passes",
        "Pass accuracy":      "pass_accuracy",
        "Tackles":            "tackles",
        "Goalkeeper saves":   "saves",
        "Free kicks":         "free_kicks",
        "Big chances":        "big_chances",
        "Big chances missed": "big_chances_missed",
    }

    for group in data.get("statistics", []):
        for item in group.get("statisticsItems", []):
            name = item.get("name", "")
            key  = key_map.get(name)
            if not key:
                continue
            # Values come as strings like "55%" or "12" or "432 (87%)"
            def _parse(val):
                if val is None:
                    return None
                s = str(val).replace("%", "").strip()
                # Take the first number before any space/paren
                m = re.match(r"[\d.]+", s)
                if m:
                    n = m.group()
                    try:
                        return int(float(n))
                    except Exception:
                        return None
                return None

            home_stats[key] = _parse(item.get("home"))
            away_stats[key] = _parse(item.get("away"))

    return {"home": home_stats, "away": away_stats}


# ── Player profile (on-demand) ────────────────────────────────────────────────

async def fetch_player_profile(player_id: str) -> dict:
    """
    Fetch full player profile from SofaScore.
    Endpoints:
      GET /player/{id}                        → basic info
      GET /player/{id}/statistics/seasons     → season stats list
      GET /player/{id}/recent-matches/0       → last 5 matches

    Returns standardised PlayerDetailResponse-compatible dict.
    """
    client = ss_client()

    # ── Basic info ────────────────────────────────────────────────────────────
    try:
        resp = await client.get(f"{SS_BASE}/player/{player_id}")
        if resp.status_code != 200:
            return {}
        p = resp.json().get("player", {})
    except Exception as ex:
        log.warning(f"SS player basic info failed for {player_id}: {ex}")
        return {}

    team     = p.get("team", {})
    country  = p.get("country", {})
    position_map = {
        "G": "Goalkeeper", "D": "Defender",
        "M": "Midfielder", "F": "Forward", "A": "Forward",
    }
    pos_raw  = p.get("position", "") or ""
    position = position_map.get(pos_raw.upper()[:1], pos_raw)

    photo = f"https://api.sofascore.com/api/v1/player/{player_id}/image"
    team_logo = ""
    if team.get("id"):
        team_logo = f"https://api.sofascore.com/api/v1/team/{team['id']}/image"

    result = {
        "player_id":    str(player_id),
        "name":         p.get("name", ""),
        "first_name":   p.get("firstName", p.get("name", "").split()[0] if p.get("name") else ""),
        "nationality":  country.get("name", ""),
        "position":     position,
        "date_of_birth": datetime.fromtimestamp(p["dateOfBirthTimestamp"]).strftime("%Y-%m-%d")
                         if p.get("dateOfBirthTimestamp") else "",
        "shirt_no":     p.get("jerseyNumber"),
        "team":         team.get("name", ""),
        "team_id":      str(team.get("id", "")),
        "team_logo":    team_logo,
        "photo":        photo,
        "height_cm":    p.get("height"),
        "preferred_foot": p.get("preferredFoot", ""),
        "market_value": None,  # SS doesn't expose this
        "source":       "sofascore",
    }

    await asyncio.sleep(0.3)

    # ── Season stats ──────────────────────────────────────────────────────────
    try:
        resp2 = await client.get(f"{SS_BASE}/player/{player_id}/statistics/seasons")
        if resp2.status_code == 200:
            seasons_data = resp2.json()
            # seasons is a list; take the first one that has football stats
            for season_entry in (seasons_data.get("uniqueTournamentSeasons") or []):
                for s_item in (season_entry.get("seasons") or [])[:1]:
                    sid  = s_item.get("id")
                    tid  = season_entry.get("uniqueTournament", {}).get("id")
                    if not sid or not tid:
                        continue
                    stat_resp = await client.get(
                        f"{SS_BASE}/player/{player_id}/unique-tournament/{tid}/season/{sid}/statistics/overall"
                    )
                    await asyncio.sleep(0.3)
                    if stat_resp.status_code == 200:
                        stats = stat_resp.json().get("statistics", {})
                        result["season_stats"] = {
                            "goals":       stats.get("goals", 0) or 0,
                            "assists":     stats.get("assists", 0) or 0,
                            "appearances": stats.get("appearances", 0) or 0,
                            "minutes":     stats.get("minutesPlayed", 0) or 0,
                            "yellow_cards":stats.get("yellowCards", 0) or 0,
                            "red_cards":   stats.get("redCards", 0) or 0,
                            "rating":      stats.get("rating"),
                            "penalties":   stats.get("penaltyGoals", 0) or 0,
                        }
                        break
                if result.get("season_stats"):
                    break
    except Exception as ex:
        log.warning(f"SS player stats failed for {player_id}: {ex}")

    if not result.get("season_stats"):
        result["season_stats"] = {
            "goals": 0, "assists": 0, "appearances": 0, "minutes": 0,
            "yellow_cards": 0, "red_cards": 0, "rating": None, "penalties": 0,
        }

    await asyncio.sleep(0.3)

    # ── Recent matches ────────────────────────────────────────────────────────
    recent_matches = []
    try:
        resp3 = await client.get(f"{SS_BASE}/player/{player_id}/matches/last/0")
        if resp3.status_code == 200:
            events = resp3.json().get("events", [])[:5]
            for ev in events:
                home_t = ev.get("homeTeam", {})
                away_t = ev.get("awayTeam", {})
                ts     = ev.get("startTimestamp")
                tid_ev = ev.get("tournament", {}).get("uniqueTournament", {}).get("id")
                slug   = SS_TOURNAMENT_IDS.get(tid_ev, "")
                recent_matches.append({
                    "match_id":        str(ev.get("id", "")),
                    "home_team":       home_t.get("name", ""),
                    "home_team_short": home_t.get("shortName", ""),
                    "away_team":       away_t.get("name", ""),
                    "away_team_short": away_t.get("shortName", ""),
                    "home_logo":       f"https://api.sofascore.com/api/v1/team/{home_t.get('id','')}/image" if home_t.get('id') else "",
                    "away_logo":       f"https://api.sofascore.com/api/v1/team/{away_t.get('id','')}/image" if away_t.get('id') else "",
                    "status":          _status(ev),
                    "score": {
                        "home": _score(ev, "home"),
                        "away": _score(ev, "away"),
                    },
                    "kickoff_display": _ist_display(ts),
                    "kickoff_iso":     _ist_iso(ts),
                    "league_slug":     slug,
                    "league":          LEAGUES.get(slug, {}).get("name", ""),
                    "player_rating":   None,  # Would need per-player stats per match
                    "player_goals":    None,
                    "player_assists":  None,
                })
    except Exception as ex:
        log.warning(f"SS player recent matches failed for {player_id}: {ex}")

    result["recent_matches"] = recent_matches
    return result


# ── Player search (on-demand) ─────────────────────────────────────────────────

async def search_players(query: str) -> list[dict]:
    """
    Search for players by name via SofaScore.
    GET /search/all?q={query}

    Returns list of player result dicts compatible with /search endpoint.
    """
    client = ss_client()
    url = f"{SS_BASE}/search/all?q={query}&page=0"
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception as ex:
        log.warning(f"SS search failed for '{query}': {ex}")
        return []

    results = []
    # SS returns "results": [{"type": "player", "entity": {...}}]
    for item in data.get("results", []):
        if item.get("type") != "player":
            continue
        p = item.get("entity", {})
        if not p:
            continue
        pid  = p.get("id", "")
        team = p.get("team", {})
        pos_map = {"G": "Goalkeeper", "D": "Defender", "M": "Midfielder", "F": "Forward"}
        pos_raw = (p.get("position") or "")
        results.append({
            "player_id":   str(pid),
            "name":        p.get("name", ""),
            "team":        team.get("name", ""),
            "team_logo":   f"https://api.sofascore.com/api/v1/team/{team.get('id','')}/image" if team.get("id") else "",
            "nationality": p.get("country", {}).get("name", ""),
            "photo":       f"https://api.sofascore.com/api/v1/player/{pid}/image",
            "goals":       0,
            "assists":     0,
            "league_slug": "",
            "league":      "",
            "source":      "sofascore_search",
        })
        if len(results) >= 5:
            break

    return results


# ── Bracket (on-demand) ───────────────────────────────────────────────────────

async def fetch_bracket(league_slug: str, ss_tournament_id: int) -> dict:
    """
    Fetch knockout bracket rounds from SofaScore.

    SofaScore exposes cup brackets via:
      GET /unique-tournament/{id}/seasons  → get current season_id
      GET /unique-tournament/{id}/season/{season_id}/rounds
        → returns list of rounds with round codes
      For each knockout round:
      GET /unique-tournament/{id}/season/{season_id}/events/round/{round_id}
        → matches in that round

    Returns standardised bracket response for BracketActivity.
    """
    client = ss_client()
    cfg    = LEAGUES.get(league_slug, {})

    # ── Get current season ────────────────────────────────────────────────────
    try:
        resp = await client.get(f"{SS_BASE}/unique-tournament/{ss_tournament_id}/seasons")
        if resp.status_code != 200:
            log.warning(f"SS bracket seasons failed: {resp.status_code}")
            return {}
        seasons = resp.json().get("seasons", [])
        if not seasons:
            return {}
        season_id   = seasons[0]["id"]
        season_name = seasons[0].get("name", "")
    except Exception as ex:
        log.warning(f"SS seasons failed for {league_slug}: {ex}")
        return {}

    await asyncio.sleep(0.3)

    # ── Get rounds ────────────────────────────────────────────────────────────
    try:
        resp2 = await client.get(
            f"{SS_BASE}/unique-tournament/{ss_tournament_id}/season/{season_id}/rounds"
        )
        if resp2.status_code != 200:
            log.warning(f"SS bracket rounds failed: {resp2.status_code}")
            return {}
        all_rounds = resp2.json().get("rounds", [])
    except Exception as ex:
        log.warning(f"SS rounds failed for {league_slug}: {ex}")
        return {}

    # Filter to knockout rounds only (SofaScore labels them by prefix/name)
    KNOCKOUT_KEYWORDS = {
        "round of 16", "last 16", "round of 32", "r16",
        "quarter", "qf", "semi", "sf", "final",
    }

    def _is_knockout(r: dict) -> bool:
        name = (r.get("name") or r.get("description") or "").lower()
        return any(kw in name for kw in KNOCKOUT_KEYWORDS)

    knockout_rounds = [r for r in all_rounds if _is_knockout(r)]

    # If no explicit knockout rounds found, take the last 4 rounds (typical bracket depth)
    if not knockout_rounds and all_rounds:
        knockout_rounds = all_rounds[-4:]

    # Round name normalisation
    def _round_name(r: dict) -> tuple[str, str]:
        name = (r.get("name") or r.get("description") or "Round").strip()
        nl   = name.lower()
        if "final" in nl and "semi" not in nl and "quarter" not in nl:
            return "Final", "final"
        if "semi" in nl:
            return "Semi-finals", "sf"
        if "quarter" in nl:
            return "Quarter-finals", "qf"
        if "16" in nl or "r16" in nl or "last 16" in nl:
            return "Round of 16", "r16"
        if "32" in nl or "last 32" in nl:
            return "Round of 32", "r32"
        return name, name.lower().replace(" ", "_")

    # ── Fetch matches for each knockout round ─────────────────────────────────
    bracket_rounds = []

    for r in knockout_rounds:
        round_id = r.get("round") or r.get("id")
        if round_id is None:
            continue
        rname, rcode = _round_name(r)

        try:
            resp3 = await client.get(
                f"{SS_BASE}/unique-tournament/{ss_tournament_id}/season/{season_id}"
                f"/events/round/{round_id}"
            )
            await asyncio.sleep(0.25)
            if resp3.status_code != 200:
                continue
            events = resp3.json().get("events", [])
        except Exception as ex:
            log.warning(f"SS bracket round {round_id} failed: {ex}")
            continue

        matches = []
        for ev in events:
            home_t = ev.get("homeTeam", {})
            away_t = ev.get("awayTeam", {})
            ts     = ev.get("startTimestamp")
            status = _status(ev)

            home_id = home_t.get("id", "")
            away_id = away_t.get("id", "")

            hs = _score(ev, "home")
            aws = _score(ev, "away")

            # Determine winner
            winner = None
            if status == "finished":
                if hs is not None and aws is not None:
                    if hs > aws:
                        winner = "home"
                    elif aws > hs:
                        winner = "away"

            # Aggregate scores (SS provides for 2-leg ties)
            agg_home = ev.get("homeScore", {}).get("aggregated")
            agg_away = ev.get("awayScore", {}).get("aggregated")
            if agg_home is not None and agg_away is not None and winner is None:
                if agg_home > agg_away:
                    winner = "home"
                elif agg_away > agg_home:
                    winner = "away"

            matches.append({
                "match_id":        str(ev.get("id", "")),
                "home_team":       home_t.get("name", "TBD"),
                "home_team_short": home_t.get("shortName", home_t.get("name", "TBD")),
                "home_logo":       f"https://api.sofascore.com/api/v1/team/{home_id}/image" if home_id else "",
                "away_team":       away_t.get("name", "TBD"),
                "away_team_short": away_t.get("shortName", away_t.get("name", "TBD")),
                "away_logo":       f"https://api.sofascore.com/api/v1/team/{away_id}/image" if away_id else "",
                "home_score":      hs,
                "away_score":      aws,
                "home_agg":        agg_home,
                "away_agg":        agg_away,
                "winner":          winner,
                "status":          status,
                "kickoff_display": _ist_display(ts),
                "kickoff_iso":     _ist_iso(ts),
                "leg":             ev.get("roundInfo", {}).get("cupRoundType"),
            })

        if matches:
            bracket_rounds.append({
                "name":    rname,
                "code":    rcode,
                "matches": matches,
            })

    # Sort rounds by typical bracket order
    ORDER = {"r32": 0, "r16": 1, "qf": 2, "sf": 3, "final": 4}
    bracket_rounds.sort(key=lambda r: ORDER.get(r["code"], 99))

    return {
        "league_slug": league_slug,
        "league_name": cfg.get("name", league_slug),
        "logo_url":    cfg.get("logo_url", ""),
        "season":      season_name,
        "rounds":      bracket_rounds,
    }


# ── Top scorers for TSDB leagues (SS-sourced) ─────────────────────────────────

async def fetch_ss_scorers(league_slug: str, ss_tournament_id: int, limit: int = 20) -> list[dict]:
    """
    Fetch top scorers from SofaScore for a given tournament.
    Used for leagues not covered by football-data.org scorers
    (ISL, IFL, AFC, Conference League).

    GET /unique-tournament/{id}/season/{season_id}/top-players/scoring
    """
    client = ss_client()

    # Get current season id
    try:
        resp = await client.get(f"{SS_BASE}/unique-tournament/{ss_tournament_id}/seasons")
        if resp.status_code != 200:
            return []
        seasons = resp.json().get("seasons", [])
        if not seasons:
            return []
        season_id = seasons[0]["id"]
    except Exception as ex:
        log.warning(f"SS scorers seasons failed for {league_slug}: {ex}")
        return []

    await asyncio.sleep(0.3)

    url = (f"{SS_BASE}/unique-tournament/{ss_tournament_id}"
           f"/season/{season_id}/top-players/scoring")
    try:
        resp2 = await client.get(url)
        if resp2.status_code != 200:
            log.warning(f"SS scorers HTTP {resp2.status_code} for {league_slug}")
            return []
        top_players = resp2.json().get("topPlayers", [])
    except Exception as ex:
        log.warning(f"SS scorers failed for {league_slug}: {ex}")
        return []

    results = []
    for entry in top_players[:limit]:
        p     = entry.get("player", {})
        team  = entry.get("team", {})
        stats = entry.get("statistics", {})
        pid   = p.get("id", "")
        results.append({
            "player_id":   str(pid),
            "name":        p.get("name", ""),
            "first_name":  p.get("firstName", ""),
            "nationality": p.get("country", {}).get("name", ""),
            "position":    p.get("position", ""),
            "dob":         "",
            "team":        team.get("name", ""),
            "team_short":  team.get("shortName", team.get("name", "")),
            "team_logo":   f"https://api.sofascore.com/api/v1/team/{team.get('id','')}/image" if team.get("id") else "",
            "goals":       stats.get("goals", 0) or 0,
            "assists":     stats.get("goalAssists", 0) or 0,
            "penalties":   stats.get("penaltyGoals", 0) or 0,
            "played":      stats.get("appearances", 0) or 0,
            "photo":       f"https://api.sofascore.com/api/v1/player/{pid}/image",
        })

    return results
