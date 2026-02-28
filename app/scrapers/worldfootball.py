import httpx
from bs4 import BeautifulSoup
from app.core.config import get_team_logo

BASE = "https://www.worldfootball.net"


async def _fetch(url: str) -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return r.text


async def _scrape_table(path: str, season: str = "2025-2026") -> list[dict]:
    url = f"{BASE}/table/{path}-{season}/"
    html = await _fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table", {"class": "standard_tabelle"})
    if not table:
        return []

    rows = table.find_all("tr")[1:]
    standings = []

    for row in rows:
        cols = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cols) < 8:
            continue

        team = cols[1]

        standings.append({
            "position": int(cols[0]),
            "team": team,
            "logo_url": get_team_logo(team),
            "played": int(cols[2]),
            "won": int(cols[3]),
            "draw": int(cols[4]),
            "lost": int(cols[5]),
            "goals": cols[6],
            "points": int(cols[7]),
        })

    return standings


async def scrape_isl():
    return await _scrape_table("ind-super-league")


async def scrape_ifl():
    return await _scrape_table("i-league")


async def scrape_afc():
    return await _scrape_table("afc-champions-league")
    
    # Backward-compatible alias for scheduler
async def scrape_isl_standings():
    return await scrape_isl()