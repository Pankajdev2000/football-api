"""
app/core/config.py  ── Goal2Gol Football API v3
═══════════════════════════════════════════════════════════════════════════════
SOURCE ASSIGNMENT:

  football-data.org  →  fixtures, standings, scorers, squads, H2H
                         PL, PD, BL1, SA, FL1, CL, EL, WC (free tier)

  SofaScore JSON     →  live scores only (all tracked leagues)
                         live scores use SS_TOURNAMENT_IDS lookup

  TheSportsDB        →  fixtures + standings for leagues NOT on FD.org free:
                         ISL (4346), IFL (4347), AFC (4659),
                         Conference League (4744)
                         Free public API — no key, no IP blocking

═══════════════════════════════════════════════════════════════════════════════
"""

import os
import pytz

IST = pytz.timezone("Asia/Kolkata")

# ── football-data.org ─────────────────────────────────────────────────────────
# SECURITY: Key must be set as an environment variable on Render, NOT hardcoded.
# Dashboard → Environment → Add: FD_TOKEN = your_key
FD_TOKEN   = os.environ.get("FD_TOKEN", "")
if not FD_TOKEN:
    import logging
    logging.getLogger("config").warning(
        "FD_TOKEN env var not set — football-data.org requests will fail with 403"
    )
FD_BASE    = "https://api.football-data.org/v4"
FD_HEADERS = {"X-Auth-Token": FD_TOKEN}

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
FD_SLUG_TO_CODE = {v: k for k, v in FD_LEAGUE_CODES.items()}
FD_DELAY_S = 7.0

# ── SofaScore ─────────────────────────────────────────────────────────────────
SS_BASE = "https://www.sofascore.com/api/v1"
SS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer":         "https://www.sofascore.com/",
    "Origin":          "https://www.sofascore.com",
    "Cache-Control":   "no-cache",
    "Pragma":          "no-cache",
    "Sec-Fetch-Dest":  "empty",
    "Sec-Fetch-Mode":  "cors",
    "Sec-Fetch-Site":  "same-origin",
}

# Used for LIVE score scraping only — maps SS tournament ID → our slug
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
    955:   "isl",    # ISL on SofaScore — live scores only
}

# ── fixturedownload (kept for import compatibility, not actively used) ─────────
FD_DOWNLOAD_BASE = "https://fixturedownload.com/feed/json"

# ── Streaming platforms (India) ───────────────────────────────────────────────
STREAMING: dict[str, dict] = {
    "premier-league":    {"platform": "JioHotstar",  "app": "JioHotstar"},
    "la-liga":           {"platform": "Sony LIV",    "app": "SonyLIV"},
    "bundesliga":        {"platform": "Sony LIV",    "app": "SonyLIV"},
    "serie-a":           {"platform": "Sony LIV",    "app": "SonyLIV"},
    "ligue-1":           {"platform": "Sony LIV",    "app": "SonyLIV"},
    "champions-league":  {"platform": "Sony LIV",    "app": "SonyLIV"},
    "europa-league":     {"platform": "Sony LIV",    "app": "SonyLIV"},
    "conference-league": {"platform": "Sony LIV",    "app": "SonyLIV"},
    "isl":               {"platform": "JioCinema",   "app": "JioCinema"},
    "ifl":               {"platform": "FanCode",     "app": "FanCode"},
    "fifa-world-cup":    {"platform": "JioHotstar",  "app": "JioHotstar"},
    "afc":               {"platform": "Sony LIV",    "app": "SonyLIV"},
}

# ── League registry ───────────────────────────────────────────────────────────
LEAGUES: dict[str, dict] = {
    # ── football-data.org leagues ─────────────────────────────────────────────
    "premier-league": {
        "name": "Premier League", "short": "EPL", "country": "England",
        "data_source": "football-data",
        "live_source": "sofascore",
        "fd_code": "PL", "ss_id": 17,
        "logo_url": "https://crests.football-data.org/PL.png",
    },
    "la-liga": {
        "name": "La Liga", "short": "LaLiga", "country": "Spain",
        "data_source": "football-data",
        "live_source": "sofascore",
        "fd_code": "PD", "ss_id": 8,
        "logo_url": "https://crests.football-data.org/PD.png",
    },
    "bundesliga": {
        "name": "Bundesliga", "short": "Bundes", "country": "Germany",
        "data_source": "football-data",
        "live_source": "sofascore",
        "fd_code": "BL1", "ss_id": 35,
        "logo_url": "https://crests.football-data.org/BL1.png",
    },
    "serie-a": {
        "name": "Serie A", "short": "SerieA", "country": "Italy",
        "data_source": "football-data",
        "live_source": "sofascore",
        "fd_code": "SA", "ss_id": 23,
        "logo_url": "https://crests.football-data.org/SA.png",
    },
    "ligue-1": {
        "name": "Ligue 1", "short": "Ligue1", "country": "France",
        "data_source": "football-data",
        "live_source": "sofascore",
        "fd_code": "FL1", "ss_id": 34,
        "logo_url": "https://crests.football-data.org/FL1.png",
    },
    "champions-league": {
        "name": "UEFA Champions League", "short": "UCL", "country": "Europe",
        "data_source": "football-data",
        "live_source": "sofascore",
        "fd_code": "CL", "ss_id": 7,
        "logo_url": "https://crests.football-data.org/CL.png",
    },
    "europa-league": {
        "name": "UEFA Europa League", "short": "UEL", "country": "Europe",
        "data_source": "football-data",
        "live_source": "sofascore",
        "fd_code": "EL", "ss_id": 679,
        "logo_url": "https://crests.football-data.org/EL.png",
    },
    "fifa-world-cup": {
        "name": "FIFA World Cup 2026", "short": "WC26", "country": "World",
        "data_source": "football-data",
        "live_source": "sofascore",
        "fd_code": "WC", "ss_id": 16,
        "logo_url": "https://crests.football-data.org/WC.png",
    },
    # ── TheSportsDB leagues (fixtures + standings) ────────────────────────────
    "conference-league": {
        "name": "UEFA Conference League", "short": "UECL", "country": "Europe",
        "data_source": "thesportsdb",   # TSDB id 4744
        "live_source": "sofascore",
        "ss_id": 17015,
        "logo_url": "https://upload.wikimedia.org/wikipedia/en/f/f3/UEFA_Europa_Conference_League_logo.svg",
    },
    "isl": {
        "name": "Indian Super League", "short": "ISL", "country": "India",
        "data_source": "thesportsdb",   # TSDB id 4346
        "live_source": "sofascore",
        "ss_id": 955,
        "logo_url": "https://upload.wikimedia.org/wikipedia/en/0/04/Indian_Super_League_logo.svg",
    },
    "ifl": {
        "name": "I-League", "short": "IFL", "country": "India",
        "data_source": "thesportsdb",   # TSDB id 4347
        "live_source": "none",
        "logo_url": "https://upload.wikimedia.org/wikipedia/en/3/35/I-League_logo.png",
    },
    "afc": {
        "name": "AFC Champions League Elite", "short": "ACLE", "country": "Asia",
        "data_source": "thesportsdb",   # TSDB id 4659
        "live_source": "sofascore",
        "ss_id": 329,
        "logo_url": "https://upload.wikimedia.org/wikipedia/en/b/b5/AFC_Champions_League_logo.svg",
    },
}

# ── Fallback team logos ───────────────────────────────────────────────────────
FALLBACK_LOGOS: dict[str, str] = {
    # ISL
    "mumbai city":         "https://upload.wikimedia.org/wikipedia/en/2/2e/Mumbai_City_FC_Logo.svg",
    "bengaluru":           "https://upload.wikimedia.org/wikipedia/en/b/b1/Bengaluru_FC_Logo.svg",
    "mohun bagan":         "https://upload.wikimedia.org/wikipedia/en/5/58/ATK_Mohun_Bagan_FC_Logo.svg",
    "kerala blasters":     "https://upload.wikimedia.org/wikipedia/en/d/d9/Kerala_Blasters_FC_logo.svg",
    "fc goa":              "https://upload.wikimedia.org/wikipedia/en/a/a5/FC_Goa_Logo.svg",
    "hyderabad":           "https://upload.wikimedia.org/wikipedia/en/0/0d/Hyderabad_FC_Logo.svg",
    "chennaiyin":          "https://upload.wikimedia.org/wikipedia/en/2/2d/Chennaiyin_FC_Logo.svg",
    "east bengal":         "https://upload.wikimedia.org/wikipedia/en/8/8e/East_Bengal_FC_logo.svg",
    "odisha":              "https://upload.wikimedia.org/wikipedia/en/0/01/Odisha_FC_Logo.svg",
    "jamshedpur":          "https://upload.wikimedia.org/wikipedia/en/2/2a/Jamshedpur_FC_Logo.svg",
    "northeast united":    "https://upload.wikimedia.org/wikipedia/en/8/86/NorthEast_United_FC_Logo.svg",
    "ne united":           "https://upload.wikimedia.org/wikipedia/en/8/86/NorthEast_United_FC_Logo.svg",
    "punjab":              "https://upload.wikimedia.org/wikipedia/en/f/f5/Punjab_FC_Logo.svg",
    "inter kashi":         "https://upload.wikimedia.org/wikipedia/en/0/04/Indian_Super_League_logo.svg",
    "sporting club delhi": "https://upload.wikimedia.org/wikipedia/en/0/04/Indian_Super_League_logo.svg",
    # IFL
    "mohammedan":          "https://upload.wikimedia.org/wikipedia/en/6/6f/Mohammedan_SC_logo.svg",
    "real kashmir":        "https://upload.wikimedia.org/wikipedia/en/5/5e/Real_Kashmir_FC.svg",
    "shillong lajong":     "https://upload.wikimedia.org/wikipedia/en/9/9e/Shillong_Lajong_FC_Logo.svg",
    "gokulam":             "https://upload.wikimedia.org/wikipedia/en/8/84/Gokulam_Kerala_FC_logo.svg",
    "sreenidi":            "https://upload.wikimedia.org/wikipedia/en/0/03/Sreenidi_Deccan_FC.png",
    "churchill":           "https://upload.wikimedia.org/wikipedia/en/6/69/Churchill_Brothers_FC_logo.png",
    "minerva":             "https://upload.wikimedia.org/wikipedia/en/1/11/Minerva_Punjab_FC_Logo.png",
}


def get_team_logo(name: str, api_crest: str = "") -> str:
    if api_crest:
        return api_crest
    if not name:
        return ""
    lower = name.lower()
    for key, url in FALLBACK_LOGOS.items():
        if key in lower or lower in key:
            return url
    return ""
