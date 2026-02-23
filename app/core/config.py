"""
app/core/config.py  ── Goal2Gol Football API v3
═══════════════════════════════════════════════════════════════════════════════
SOURCE ASSIGNMENT (no overlap per data type per league):

  football-data.org  →  standings, fixtures, results, scorers, squads, H2H
                         for: PL, PD, BL1, SA, FL1, CL, EL, WC
                         Team/competition logos from crests.football-data.org

  SofaScore JSON     →  live scores only (FD has no live endpoint)
                         for: all European leagues + AFC

  fixturedownload    →  ISL + IFL: fixtures, results (standings computed here)
                         no overlap with FD.org (Indian leagues not on FD.org)

═══════════════════════════════════════════════════════════════════════════════
"""

import pytz

IST = pytz.timezone("Asia/Kolkata")

# ── football-data.org ─────────────────────────────────────────────────────────
FD_TOKEN   = "059eb2ab33c34001bccb46a3d029cb67"
FD_BASE    = "https://api.football-data.org/v4"
FD_HEADERS = {"X-Auth-Token": FD_TOKEN}

# Free tier codes  →  slug mapping
FD_LEAGUE_CODES: dict[str, str] = {
    "PL":  "premier-league",
    "PD":  "la-liga",
    "BL1": "bundesliga",
    "SA":  "serie-a",
    "FL1": "ligue-1",
    "CL":  "champions-league",
    "EL":  "europa-league",
    "WC":  "fifa-world-cup",
}
# Reverse: slug → code
FD_SLUG_TO_CODE = {v: k for k, v in FD_LEAGUE_CODES.items()}

# Rate limit: 10 req/min free tier → 7 s gap is safe
FD_DELAY_S = 7.0

# ── SofaScore (no auth — public JSON API) ─────────────────────────────────────
SS_BASE = "https://www.sofascore.com/api/v1"
SS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# SofaScore unique-tournament IDs (used only for live score scraping)
SS_TOURNAMENT_IDS: dict[int, str] = {
    17:    "premier-league",
    8:     "la-liga",
    35:    "bundesliga",
    23:    "serie-a",
    34:    "ligue-1",
    7:     "champions-league",
    679:   "europa-league",
    17015: "conference-league",
    16:    "fifa-world-cup",
    329:   "afc",
}

# ── fixturedownload.com ───────────────────────────────────────────────────────
FD_DOWNLOAD_BASE = "https://fixturedownload.com/feed/json"

# ── Streaming platforms in Indian region ──────────────────────────────────────
STREAMING: dict[str, dict] = {
    "premier-league":    {"platform": "Disney+ Hotstar", "app": "Hotstar"},
    "la-liga":           {"platform": "Sony LIV",        "app": "SonyLIV"},
    "bundesliga":        {"platform": "Sony LIV",        "app": "SonyLIV"},
    "serie-a":           {"platform": "Sony LIV",        "app": "SonyLIV"},
    "ligue-1":           {"platform": "Sony LIV",        "app": "SonyLIV"},
    "champions-league":  {"platform": "Sony LIV",        "app": "SonyLIV"},
    "europa-league":     {"platform": "Sony LIV",        "app": "SonyLIV"},
    "conference-league": {"platform": "Sony LIV",        "app": "SonyLIV"},
    "isl":               {"platform": "JioCinema",       "app": "JioCinema"},
    "ifl":               {"platform": "FanCode",         "app": "FanCode"},
    "fifa-world-cup":    {"platform": "Disney+ Hotstar", "app": "Hotstar"},
    "afc":               {"platform": "Sony LIV",        "app": "SonyLIV"},
}

# ── League registry ───────────────────────────────────────────────────────────
LEAGUES: dict[str, dict] = {
    "premier-league": {
        "name": "Premier League", "short": "EPL", "country": "England",
        "data_source": "football-data",   # fixtures / standings / scorers
        "live_source": "sofascore",
        "fd_code": "PL",
        "ss_id": 17,
        "logo_url": "https://crests.football-data.org/PL.png",
    },
    "la-liga": {
        "name": "La Liga", "short": "LaLiga", "country": "Spain",
        "data_source": "football-data",
        "live_source": "sofascore",
        "fd_code": "PD",
        "ss_id": 8,
        "logo_url": "https://crests.football-data.org/PD.png",
    },
    "bundesliga": {
        "name": "Bundesliga", "short": "Bundes", "country": "Germany",
        "data_source": "football-data",
        "live_source": "sofascore",
        "fd_code": "BL1",
        "ss_id": 35,
        "logo_url": "https://crests.football-data.org/BL1.png",
    },
    "serie-a": {
        "name": "Serie A", "short": "SerieA", "country": "Italy",
        "data_source": "football-data",
        "live_source": "sofascore",
        "fd_code": "SA",
        "ss_id": 23,
        "logo_url": "https://crests.football-data.org/SA.png",
    },
    "ligue-1": {
        "name": "Ligue 1", "short": "Ligue1", "country": "France",
        "data_source": "football-data",
        "live_source": "sofascore",
        "fd_code": "FL1",
        "ss_id": 34,
        "logo_url": "https://crests.football-data.org/FL1.png",
    },
    "champions-league": {
        "name": "UEFA Champions League", "short": "UCL", "country": "Europe",
        "data_source": "football-data",
        "live_source": "sofascore",
        "fd_code": "CL",
        "ss_id": 7,
        "logo_url": "https://crests.football-data.org/CL.png",
    },
    "europa-league": {
        "name": "UEFA Europa League", "short": "UEL", "country": "Europe",
        "data_source": "football-data",
        "live_source": "sofascore",
        "fd_code": "EL",
        "ss_id": 679,
        "logo_url": "https://crests.football-data.org/EL.png",
    },
    "fifa-world-cup": {
        "name": "FIFA World Cup 2026", "short": "WC26", "country": "World",
        "data_source": "football-data",
        "live_source": "sofascore",
        "fd_code": "WC",
        "ss_id": 16,
        "logo_url": "https://crests.football-data.org/WC.png",
    },
    "conference-league": {
        "name": "UEFA Conference League", "short": "UECL", "country": "Europe",
        "data_source": "sofascore",        # not on FD free tier
        "live_source": "sofascore",
        "ss_id": 17015,
        "logo_url": "https://upload.wikimedia.org/wikipedia/en/f/f3/UEFA_Europa_Conference_League_logo.svg",
    },
    "isl": {
        "name": "Indian Super League", "short": "ISL", "country": "India",
        "data_source": "fixturedownload",
        "live_source": "none",
        "fd_download_id": "isl-2024",
        "logo_url": "https://upload.wikimedia.org/wikipedia/en/0/04/Indian_Super_League_logo.svg",
    },
    "ifl": {
        "name": "Indian Football League", "short": "IFL", "country": "India",
        "data_source": "fixturedownload",
        "live_source": "none",
        "fd_download_id": "i-league-2024",
        "logo_url": "https://upload.wikimedia.org/wikipedia/en/3/35/I-League_logo.png",
    },
    "afc": {
        "name": "AFC Champions League Elite", "short": "ACLE", "country": "Asia",
        "data_source": "sofascore",
        "live_source": "sofascore",
        "ss_id": 329,
        "logo_url": "https://upload.wikimedia.org/wikipedia/en/b/b5/AFC_Champions_League_logo.svg",
    },
}

# ── Fallback team logos (used when API response has no crest) ─────────────────
# Keys are lowercase partial names. get_team_logo() does a fuzzy match.
FALLBACK_LOGOS: dict[str, str] = {
    # ISL
    "mumbai city":     "https://upload.wikimedia.org/wikipedia/en/2/2e/Mumbai_City_FC_Logo.svg",
    "bengaluru":       "https://upload.wikimedia.org/wikipedia/en/b/b1/Bengaluru_FC_Logo.svg",
    "mohun bagan":     "https://upload.wikimedia.org/wikipedia/en/5/58/ATK_Mohun_Bagan_FC_Logo.svg",
    "kerala blasters": "https://upload.wikimedia.org/wikipedia/en/d/d9/Kerala_Blasters_FC_logo.svg",
    "fc goa":          "https://upload.wikimedia.org/wikipedia/en/a/a5/FC_Goa_Logo.svg",
    "hyderabad":       "https://upload.wikimedia.org/wikipedia/en/0/0d/Hyderabad_FC_Logo.svg",
    "chennaiyin":      "https://upload.wikimedia.org/wikipedia/en/2/2d/Chennaiyin_FC_Logo.svg",
    "east bengal":     "https://upload.wikimedia.org/wikipedia/en/8/8e/East_Bengal_FC_logo.svg",
    "odisha":          "https://upload.wikimedia.org/wikipedia/en/0/01/Odisha_FC_Logo.svg",
    "jamshedpur":      "https://upload.wikimedia.org/wikipedia/en/2/2a/Jamshedpur_FC_Logo.svg",
    "northeast united":"https://upload.wikimedia.org/wikipedia/en/8/86/NorthEast_United_FC_Logo.svg",
    "ne united":       "https://upload.wikimedia.org/wikipedia/en/8/86/NorthEast_United_FC_Logo.svg",
    "punjab":          "https://upload.wikimedia.org/wikipedia/en/f/f5/Punjab_FC_Logo.svg",
    # IFL
    "mohammedan":      "https://upload.wikimedia.org/wikipedia/en/6/6f/Mohammedan_SC_logo.svg",
    "real kashmir":    "https://upload.wikimedia.org/wikipedia/en/5/5e/Real_Kashmir_FC.svg",
    "shillong lajong": "https://upload.wikimedia.org/wikipedia/en/9/9e/Shillong_Lajong_FC_Logo.svg",
    "gokulam":         "https://upload.wikimedia.org/wikipedia/en/8/84/Gokulam_Kerala_FC_logo.svg",
    "sreenidi":        "https://upload.wikimedia.org/wikipedia/en/0/03/Sreenidi_Deccan_FC.png",
    "churchill":       "https://upload.wikimedia.org/wikipedia/en/6/69/Churchill_Brothers_FC_logo.png",
    "minerva":         "https://upload.wikimedia.org/wikipedia/en/1/11/Minerva_Punjab_FC_Logo.png",
}


def get_team_logo(name: str, api_crest: str = "") -> str:
    """
    Returns team logo URL.
    Priority: API-provided crest → fallback table fuzzy match → empty string.
    football-data.org always provides crests for European teams, so the
    fallback table is mainly for ISL/IFL teams.
    """
    if api_crest:
        return api_crest
    if not name:
        return ""
    lower = name.lower()
    for key, url in FALLBACK_LOGOS.items():
        if key in lower or lower in key:
            return url
    return ""
