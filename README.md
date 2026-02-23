# ⚽ Goal2Gol Football API v3

## Data Source Map (no overlap per data type)

| Source | What it provides | Leagues |
|--------|-----------------|---------|
| **football-data.org** | Fixtures, results, standings table, top scorers, squads, H2H | PL, La Liga, Bundesliga, Serie A, Ligue 1, UCL, UEL, WC |
| **SofaScore** | Live in-progress scores + lineups | All European + AFC |
| **fixturedownload.com** | ISL + IFL fixtures, results, standings (computed) | ISL, IFL |

Logos for European teams come directly from `crests.football-data.org` — no extra requests.

## Scheduler

| Cycle | Interval | What runs |
|-------|----------|-----------|
| Live | 3 min (17:00–06:00 IST) / 7 min (rest) | SofaScore live scores |
| FD.org | 30 min | Fixtures, standings, scorers for all EU leagues |
| Indian | 60 min | ISL + IFL from fixturedownload.com |

## Deploy to Render

1. Push this folder to GitHub
2. New Web Service → connect repo
3. Build: `pip install -r requirements.txt`
4. Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. UptimeRobot → ping `/health` every 5 minutes (keeps free tier awake)

## Endpoints

```
GET /                              → API info + all endpoint list
GET /health                        → cache freshness per source

GET /scores/live                   → live matches (SofaScore)
GET /scores/live?league=la-liga    → filtered
GET /scores/upcoming               → all upcoming fixtures
GET /scores/recent                 → recent results (last 14 days)

GET /leagues                       → all leagues list
GET /leagues/{slug}                → full page: live+upcoming+recent+standings+scorers
GET /leagues/{slug}/standings      → just the table
GET /leagues/{slug}/stats          → top scorers (goals, assists, penalties)
GET /leagues/{slug}/fixtures       → upcoming fixtures
GET /leagues/{slug}/results        → recent results

GET /matches/h2h?match_id={id}     → H2H via football-data.org (FD match ID)
GET /matches/{id}/lineups          → lineups via SofaScore (SS match ID)
GET /teams/{id}/squad              → squad via football-data.org (FD team ID)
GET /teams/{id}/form?league={slug} → last 5 in competition
GET /teams/{id}/next               → next 5 fixtures
```

## League Slugs

```
premier-league  la-liga   bundesliga  serie-a   ligue-1
champions-league  europa-league  conference-league  fifa-world-cup
isl  ifl  afc
```

## Match Object

```json
{
  "match_id":        "498024",
  "home_team":       "Arsenal FC",
  "home_team_short": "Arsenal",
  "home_logo":       "https://crests.football-data.org/57.png",
  "away_team":       "Chelsea FC",
  "away_logo":       "https://crests.football-data.org/61.png",
  "home_team_id":    "57",
  "away_team_id":    "61",
  "score":           {"home": 2, "away": 1, "home_ht": 1, "away_ht": 0},
  "status":          "finished",
  "minute":          null,
  "league":          "Premier League",
  "league_slug":     "premier-league",
  "league_logo":     "https://crests.football-data.org/PL.png",
  "stadium":         "Emirates Stadium",
  "round":           "Matchday 28",
  "kickoff_iso":     "2024-03-16T21:00:00",
  "kickoff_display": "16 Mar • 09:00 PM IST",
  "streaming":       {"platform": "Disney+ Hotstar", "app": "Hotstar"},
  "source":          "football-data"
}
```

## Standings Row

```json
{
  "position": 1,
  "club": "Arsenal FC",
  "club_logo": "https://crests.football-data.org/57.png",
  "team_id": "57",
  "played": 29, "won": 19, "drawn": 5, "lost": 5,
  "goals_for": 72, "goals_against": 38, "goal_difference": 34,
  "points": 62,
  "form": ["W","W","D","W","L"]
}
```

## Scorer Row

```json
{
  "name": "Erling Haaland",
  "team": "Manchester City FC",
  "team_logo": "https://crests.football-data.org/65.png",
  "goals": 24, "assists": 5, "penalties": 3, "played": 27
}
```

## Android ApiService.java — new endpoints to add

```java
// League full page (standings + scorers + fixtures)
@GET("leagues/{slug}")
Call<LeagueDetailResponse> getLeague(@Path("slug") String slug);

@GET("leagues/{slug}/standings")
Call<StandingsResponse> getStandings(@Path("slug") String slug);

@GET("leagues/{slug}/stats")
Call<ScorersResponse> getScorers(@Path("slug") String slug);

// Match detail
@GET("matches/h2h")
Call<List<Match>> getH2H(@Query("match_id") String matchId);

@GET("matches/{id}/lineups")
Call<LineupsResponse> getLineups(@Path("id") String matchId);

// Team
@GET("teams/{id}/squad")
Call<SquadResponse> getSquad(@Path("id") String teamId);

@GET("teams/{id}/form")
Call<List<Match>> getTeamForm(@Path("id") String teamId, @Query("league") String league);

@GET("teams/{id}/next")
Call<List<Match>> getTeamNext(@Path("id") String teamId);
```

## Note on ID types

- `match_id` in H2H → **football-data.org** integer ID (from fixtures response)
- `match_id` in lineups → **SofaScore** integer ID (from live scores response)
- `team_id` in squad/form/next → **football-data.org** integer ID (from fixtures/standings)

Both IDs are included in every match object in their respective source responses.
