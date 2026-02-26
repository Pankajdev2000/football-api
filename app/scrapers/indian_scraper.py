"""
app/scrapers/indian_scraper.py
═══════════════════════════════════════════════════════════════════════════════
Replaces fixturedownload.py. Scrapes ISL, IFL and AFC from working sources:

  ISL  →  indiansuperleague.com  (official site, server-rendered HTML)
  IFL  →  en.wikipedia.org       (2025-26 I-League season page)
  AFC  →  en.wikipedia.org       (2024-25 AFC Champions League Elite page)

Why not fixturedownload.com?
  → No 2024-25 / 2025-26 data uploaded for ISL or IFL.

Why not SofaScore for AFC?
  → SofaScore blocks datacenter/server IPs with 403.
═══════════════════════════════════════════════════════════════════════════════
"""

import logging
import re
from datetime import datetime
from typing import Optional

import pytz
from bs4 import BeautifulSoup

from app.core.config import LEAGUES, STREAMING, get_team_logo, IST
from app.core.http_client import plain_client

log = logging.getLogger("indian_scraper")

ISL_FIXTURES_URL = "https://www.indiansuperleague.com/schedule-fixtures"
IFL_WIKI_URL     = "https://en.wikipedia.org/wiki/2025%E2%80%9326_I-League"
AFC_WIKI_URL     = "https://en.wikipedia.org/wiki/2024%E2%80%9325_AFC_Champions_League_Elite"

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.utcnow().replace(tzinfo=pytz.utc)


def _ist_display(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    return dt.astimezone(IST).strftime("%d %b • %I:%M %p IST")


def _ist_iso(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    return dt.astimezone(IST).strftime("%Y-%m-%dT%H:%M:%S")


def _parse_isl_date(date_str: str, time_str: str = "") -> Optional[datetime]:
    """Parse ISL date like 'Saturday 14 Feb 2026' + optional time '14:00'."""
    try:
        date_str = re.sub(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+", "", date_str.strip())
        if time_str and re.match(r"\d{1,2}:\d{2}", time_str.strip()):
            dt = datetime.strptime(f"{date_str} {time_str.strip()}", "%d %b %Y %H:%M")
        else:
            dt = datetime.strptime(date_str, "%d %b %Y")
        return IST.localize(dt).astimezone(pytz.utc)
    except Exception:
        return None


def _build_match(
    league_slug: str,
    home: str, away: str,
    home_score: Optional[int], away_score: Optional[int],
    dt_utc: Optional[datetime],
    stadium: str = "",
    match_id: str = "",
    status: str = "",
) -> dict:
    cfg = LEAGUES.get(league_slug, {})
    now = _now_utc()

    if not status:
        if home_score is not None and away_score is not None:
            status = "finished"
        elif dt_utc and dt_utc > now:
            status = "scheduled"
        else:
            status = "scheduled"

    return {
        "match_id":        match_id or f"{league_slug}-{home[:3]}-{away[:3]}-{_ist_iso(dt_utc)}",
        "home_team":       home,
        "home_team_short": home,
        "away_team":       away,
        "away_team_short": away,
        "home_logo":       get_team_logo(home),
        "away_logo":       get_team_logo(away),
        "home_team_id":    "",
        "away_team_id":    "",
        "score": {
            "home":    home_score,
            "away":    away_score,
            "home_ht": None,
            "away_ht": None,
        },
        "status":          status,
        "minute":          None,
        "league":          cfg.get("name", league_slug),
        "league_slug":     league_slug,
        "league_logo":     cfg.get("logo_url", ""),
        "league_country":  cfg.get("country", "India"),
        "stadium":         stadium,
        "round":           "",
        "kickoff_iso":     _ist_iso(dt_utc),
        "kickoff_display": _ist_display(dt_utc),
        "kickoff_utc":     dt_utc.strftime("%Y-%m-%d %H:%M:%SZ") if dt_utc else "",
        "streaming":       STREAMING.get(league_slug, {}),
        "source":          "indian_scraper",
    }


def _compute_standings(matches: list[dict], league_slug: str) -> list[dict]:
    """Build standings table from finished matches."""
    table: dict[str, dict] = {}

    def _ensure(team: str):
        if team not in table:
            table[team] = {
                "club": team, "club_short": team,
                "club_logo": get_team_logo(team),
                "played": 0, "won": 0, "drawn": 0, "lost": 0,
                "goals_for": 0, "goals_against": 0,
                "goal_difference": 0, "points": 0, "form": [],
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
        sorted(table.items(),
               key=lambda x: (-x[1]["points"],
                              -(x[1]["goals_for"] - x[1]["goals_against"]),
                              -x[1]["goals_for"])),
        start=1
    ):
        entry["position"]        = pos
        entry["goal_difference"] = entry["goals_for"] - entry["goals_against"]
        entry["form"]            = entry["form"][-5:]
        standings.append(entry)

    return standings


# ── ISL Scraper ───────────────────────────────────────────────────────────────

async def scrape_isl() -> dict:
    """Scrape ISL fixtures and results from indiansuperleague.com (server-rendered HTML)."""
    client = plain_client()
    all_matches = []

    try:
        resp = await client.get(ISL_FIXTURES_URL, headers=SCRAPE_HEADERS)
        if resp.status_code != 200:
            log.warning(f"ISL fixtures HTTP {resp.status_code}")
            return {}

        soup = BeautifulSoup(resp.text, "html.parser")
        current_date = ""

        for element in soup.find_all(["h3", "div"]):
            # Date headers like "Saturday 14 Feb 2026"
            if element.name == "h3" and re.search(r"\d{1,2}\s+\w+\s+\d{4}", element.get_text()):
                current_date = element.get_text(strip=True)
                continue

            # Match cards contain a matchcentre link
            if element.name == "div" and element.find("a", href=re.compile(r"/matchcentre/")):
                try:
                    teams = element.find_all("h3")
                    if len(teams) < 2:
                        continue

                    home_full = teams[0].get_text(strip=True)
                    away_full = teams[1].get_text(strip=True)
                    # Strip short code suffix e.g. "Mohun Bagan Super Giant MBSG"
                    home_name = re.sub(r'\s+[A-Z]{2,5}$', '', home_full).strip()
                    away_name = re.sub(r'\s+[A-Z]{2,5}$', '', away_full).strip()

                    if not home_name or not away_name:
                        continue

                    score_texts = [t.strip() for t in element.stripped_strings]
                    scores = [s for s in score_texts if re.match(r'^\d+$', s)]
                    home_score = int(scores[0]) if len(scores) >= 1 else None
                    away_score = int(scores[1]) if len(scores) >= 2 else None

                    time_match = re.search(r'\b(\d{1,2}:\d{2})\b', element.get_text())
                    time_str   = time_match.group(1) if time_match else ""

                    is_postponed = "Postponed" in element.get_text()

                    link = element.find("a", href=re.compile(r"/matchcentre/"))
                    match_id = ""
                    if link:
                        m = re.search(r'/matchcentre/(\d+)', link["href"])
                        if m:
                            match_id = f"isl-{m.group(1)}"

                    venue_el = element.find_previous("p")
                    venue = venue_el.get_text(strip=True) if venue_el else ""

                    dt_utc = _parse_isl_date(current_date, time_str)
                    status = "postponed" if is_postponed else ""

                    match = _build_match(
                        league_slug="isl",
                        home=home_name, away=away_name,
                        home_score=home_score if not is_postponed else None,
                        away_score=away_score if not is_postponed else None,
                        dt_utc=dt_utc,
                        stadium=venue,
                        match_id=match_id,
                        status=status,
                    )
                    all_matches.append(match)
                except Exception as ex:
                    log.debug(f"ISL match parse error: {ex}")
                    continue

    except Exception as ex:
        log.warning(f"ISL scrape failed: {ex}")
        return {}

    if not all_matches:
        log.warning("ISL: no matches parsed from HTML")
        return {}

    finished = sorted([m for m in all_matches if m["status"] == "finished"],
                      key=lambda m: m["kickoff_utc"], reverse=True)
    upcoming = sorted([m for m in all_matches if m["status"] == "scheduled"],
                      key=lambda m: m["kickoff_utc"])

    log.info(f"ISL: {len(finished)} finished, {len(upcoming)} upcoming")

    return {
        "live":        [],
        "recent":      finished[:20],
        "upcoming":    upcoming[:20],
        "standings":   _compute_standings(all_matches, "isl"),
        "scorers":     [],
        "all_matches": all_matches,
    }


# ── IFL (I-League) Scraper ────────────────────────────────────────────────────

async def scrape_ifl() -> dict:
    """Scrape I-League 2025-26 from Wikipedia (reliable HTML tables)."""
    client = plain_client()
    all_matches = []
    standings   = []

    try:
        resp = await client.get(IFL_WIKI_URL, headers=SCRAPE_HEADERS)
        if resp.status_code != 200:
            log.warning(f"IFL Wikipedia HTTP {resp.status_code}")
            return {}

        soup = BeautifulSoup(resp.text, "html.parser")

        # Parse standings table
        for table in soup.find_all("table", class_="wikitable"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if "pts" in headers or "points" in headers:
                rows = table.find_all("tr")[1:]
                pos  = 1
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) < 8:
                        continue
                    try:
                        texts     = [c.get_text(strip=True) for c in cells]
                        team_name = texts[1] if len(texts) > 1 else ""
                        if not team_name or team_name.isdigit():
                            continue
                        played  = int(re.sub(r'\D', '', texts[2])) if texts[2].strip() else 0
                        won     = int(re.sub(r'\D', '', texts[3])) if texts[3].strip() else 0
                        drawn   = int(re.sub(r'\D', '', texts[4])) if texts[4].strip() else 0
                        lost    = int(re.sub(r'\D', '', texts[5])) if texts[5].strip() else 0
                        gf      = int(re.sub(r'\D', '', texts[6])) if texts[6].strip() else 0
                        ga      = int(re.sub(r'\D', '', texts[7])) if texts[7].strip() else 0
                        pts_idx = next((i for i, h in enumerate(headers) if h in ("pts", "points")), 9)
                        pts     = int(re.sub(r'\D', '', texts[pts_idx])) if len(texts) > pts_idx and texts[pts_idx].strip() else 0
                        standings.append({
                            "position": pos, "club": team_name, "club_short": team_name,
                            "club_logo": get_team_logo(team_name),
                            "played": played, "won": won, "drawn": drawn, "lost": lost,
                            "goals_for": gf, "goals_against": ga,
                            "goal_difference": gf - ga, "points": pts, "form": [],
                        })
                        pos += 1
                    except Exception:
                        continue
                if standings:
                    break

        # Parse match results
        for table in soup.find_all("table", class_=re.compile(r"wikitable")):
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 3:
                    continue
                text       = [c.get_text(strip=True) for c in cells]
                score_cell = next((t for t in text if re.match(r'^\d+\s*[–\-]\s*\d+$', t)), None)
                if not score_cell:
                    continue
                try:
                    parts     = re.split(r'[–\-]', score_cell)
                    hs        = int(parts[0].strip())
                    aws       = int(parts[1].strip())
                    idx       = text.index(score_cell)
                    home_name = text[idx - 1].strip() if idx > 0 else ""
                    away_name = text[idx + 1].strip() if idx + 1 < len(text) else ""
                    if not home_name or not away_name:
                        continue
                    date_text = next((t for t in text if re.search(r'\d{1,2}\s+\w+\s+\d{4}', t)), "")
                    dt_utc = None
                    if date_text:
                        try:
                            dt_utc = datetime.strptime(
                                re.search(r'\d{1,2}\s+\w+\s+\d{4}', date_text).group(), "%d %B %Y"
                            ).replace(tzinfo=pytz.utc)
                        except Exception:
                            pass
                    all_matches.append(_build_match(
                        "ifl", home_name, away_name, hs, aws, dt_utc, status="finished"
                    ))
                except Exception:
                    continue

    except Exception as ex:
        log.warning(f"IFL scrape failed: {ex}")
        return {}

    finished = sorted([m for m in all_matches if m["status"] == "finished"],
                      key=lambda m: m["kickoff_utc"], reverse=True)

    log.info(f"IFL: {len(finished)} finished, {len(standings)} standings rows")

    return {
        "live": [], "recent": finished[:20], "upcoming": [],
        "standings": standings, "scorers": [], "all_matches": all_matches,
    }


# ── AFC Scraper ───────────────────────────────────────────────────────────────

async def scrape_afc() -> dict:
    """Scrape AFC Champions League Elite from Wikipedia."""
    client    = plain_client()
    all_matches = []
    standings   = []

    try:
        resp = await client.get(AFC_WIKI_URL, headers=SCRAPE_HEADERS)
        if resp.status_code != 200:
            log.warning(f"AFC Wikipedia HTTP {resp.status_code}")
            return {}

        soup = BeautifulSoup(resp.text, "html.parser")

        # Parse standings tables (East + West regions)
        for table in soup.find_all("table", class_="wikitable"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if "pts" not in headers and "points" not in headers:
                continue
            rows = table.find_all("tr")[1:]
            pos  = 1
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) < 8:
                    continue
                try:
                    texts     = [c.get_text(strip=True) for c in cells]
                    team_name = texts[1] if len(texts) > 1 else ""
                    if not team_name or team_name.isdigit():
                        continue
                    played  = int(re.sub(r'\D', '', texts[2])) if texts[2].strip() else 0
                    won     = int(re.sub(r'\D', '', texts[3])) if texts[3].strip() else 0
                    drawn   = int(re.sub(r'\D', '', texts[4])) if texts[4].strip() else 0
                    lost    = int(re.sub(r'\D', '', texts[5])) if texts[5].strip() else 0
                    gf      = int(re.sub(r'\D', '', texts[6])) if texts[6].strip() else 0
                    ga      = int(re.sub(r'\D', '', texts[7])) if texts[7].strip() else 0
                    pts_idx = next((i for i, h in enumerate(headers) if h in ("pts", "points")), 9)
                    pts     = int(re.sub(r'\D', '', texts[pts_idx])) if len(texts) > pts_idx and texts[pts_idx].strip() else 0
                    standings.append({
                        "position": pos, "club": team_name, "club_short": team_name,
                        "club_logo": get_team_logo(team_name),
                        "played": played, "won": won, "drawn": drawn, "lost": lost,
                        "goals_for": gf, "goals_against": ga,
                        "goal_difference": gf - ga, "points": pts, "form": [],
                    })
                    pos += 1
                except Exception:
                    continue

        # Parse match results
        for table in soup.find_all("table", class_=re.compile(r"wikitable")):
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 3:
                    continue
                text       = [c.get_text(strip=True) for c in cells]
                score_cell = next((t for t in text if re.match(r'^\d+\s*[–\-]\s*\d+$', t)), None)
                if not score_cell:
                    continue
                try:
                    parts     = re.split(r'[–\-]', score_cell)
                    hs        = int(parts[0].strip())
                    aws       = int(parts[1].strip())
                    idx       = text.index(score_cell)
                    home_name = text[idx - 1].strip() if idx > 0 else ""
                    away_name = text[idx + 1].strip() if idx + 1 < len(text) else ""
                    if not home_name or not away_name:
                        continue
                    date_text = next((t for t in text if re.search(r'\d{1,2}\s+\w+\s+\d{4}', t)), "")
                    dt_utc = None
                    if date_text:
                        try:
                            dt_utc = datetime.strptime(
                                re.search(r'\d{1,2}\s+\w+\s+\d{4}', date_text).group(), "%d %B %Y"
                            ).replace(tzinfo=pytz.utc)
                        except Exception:
                            pass
                    all_matches.append(_build_match(
                        "afc", home_name, away_name, hs, aws, dt_utc, status="finished"
                    ))
                except Exception:
                    continue

    except Exception as ex:
        log.warning(f"AFC scrape failed: {ex}")
        return {}

    finished = sorted([m for m in all_matches if m["status"] == "finished"],
                      key=lambda m: m["kickoff_utc"], reverse=True)

    log.info(f"AFC: {len(finished)} finished, {len(standings)} standings rows")

    return {
        "live": [], "recent": finished[:20], "upcoming": [],
        "standings": standings, "scorers": [], "all_matches": all_matches,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

async def scrape_all_indian_leagues() -> dict:
    """
    Scrape ISL + IFL + AFC. Returns {league_slug: data_dict}.
    Called by scheduler every 60 minutes.
    """
    results = {}

    isl_data = await scrape_isl()
    if isl_data:
        results["isl"] = isl_data

    ifl_data = await scrape_ifl()
    if ifl_data:
        results["ifl"] = ifl_data

    afc_data = await scrape_afc()
    if afc_data:
        results["afc"] = afc_data

    return results
