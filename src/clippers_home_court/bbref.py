"""Team game logs from Basketball Reference, for seasons before stats.nba.com coverage
is used (see ``source.fetch_season``).

Rows are converted to the same columns LeagueGameFinder returns, so they go through
exactly the same Pydantic validation. Two differences from the NBA feed:

* GAME_ID is synthetic but stable: ``90`` + YYMMDD + the last two digits of the home
  team's NBA team id (a team plays at most one home game a day).
* International games are listed under a nominal home team, like the NBA feed, so they
  are flagged by ID in ``seasons.KNOWN_NEUTRAL_GAME_IDS``. Any row Basketball Reference
  marks "N" gets the 'A @ HOST' form that ``Game.from_lines`` treats as neutral.
"""

from __future__ import annotations

import logging
import re
import time

import pandas as pd
import requests
from nba_api.stats.static import teams as nba_teams

log = logging.getLogger(__name__)

URL = "https://www.basketball-reference.com/teams/{team}/{end_year}/gamelog/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
}
REQUEST_GAP_S = 3.5  # Basketball Reference allows ~20 requests a minute

TEAM_IDS = {t["abbreviation"]: t["id"] for t in nba_teams.get_teams()}
TO_NBA = {"BRK": "BKN", "CHO": "CHA", "PHO": "PHX"}

ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r'data-stat="([^"]+)"[^>]*>(.*?)</t[dh]>', re.S)
BOX_RE = re.compile(r'href="/boxscores/\d{9}([A-Z]{3})\.html"')
TAG_RE = re.compile(r"<[^>]+>")


def bbref_code(nba_abbr: str, start_year: int) -> str:
    """NBA abbreviation -> the code Basketball Reference uses in team URLs."""
    if nba_abbr == "CHA":
        return "CHA" if start_year <= 2013 else "CHO"  # Bobcats until 2013-14
    return {"BKN": "BRK", "PHX": "PHO"}.get(nba_abbr, nba_abbr)


def to_nba(code: str) -> str:
    return TO_NBA.get(code, code)


def parse_game_log(html: str, team: str, start_year: int) -> pd.DataFrame:
    """Regular-season rows of one team's game log page, as LeagueGameFinder columns."""
    start = html.find('id="team_game_log_reg"')
    if start < 0:
        raise ValueError(f"{team} {start_year}: regular-season game log table not found")
    end = html.find("</table>", start)
    rows = []
    for raw in ROW_RE.findall(html[start:end]):
        if "<td" not in raw or 'data-stat="date"' not in raw:
            continue  # header rows repeat every 20 games
        c = {k: TAG_RE.sub("", v).strip() for k, v in CELL_RE.findall(raw)}
        if not c.get("date"):
            continue  # season totals row
        box = BOX_RE.search(raw)
        if not box:
            raise ValueError(f"{team} {c.get('date')}: no box score link")
        host, opp = to_nba(box[1]), to_nba(c["opp_name_abbr"])
        if c["game_location"] == "N":
            matchup = f"{team} @ {host}"
        elif c["game_location"] == "@":
            matchup = f"{team} @ {opp}"
        else:
            matchup = f"{team} vs. {opp}"
        game_date = pd.Timestamp(c["date"])
        rows.append(
            {
                "SEASON_ID": f"2{start_year}",
                "TEAM_ID": TEAM_IDS[team],
                "TEAM_ABBREVIATION": team,
                "GAME_ID": f"90{game_date:%y%m%d}{TEAM_IDS[host] % 100:02d}",
                "GAME_DATE": game_date.strftime("%Y-%m-%d"),
                "MATCHUP": matchup,
                "WL": c["team_game_result"],
                "PTS": c["team_game_score"],
                "FGM": c["fg"],
                "FGA": c["fga"],
                "FG3M": c["fg3"],
                "FG3A": c["fg3a"],
                "FTM": c["ft"],
                "FTA": c["fta"],
                "OREB": c["orb"],
                "DREB": c["drb"],
                "TOV": c["tov"],
            }
        )
    return pd.DataFrame(rows)


def fetch_season(start_year: int, *, retries: int = 3) -> pd.DataFrame:
    """Every team's game log for one regular season (two rows per game)."""
    frames = []
    session = requests.Session()
    for team in sorted(TEAM_IDS):
        url = URL.format(team=bbref_code(team, start_year), end_year=start_year + 1)
        for attempt in range(1, retries + 1):
            resp = session.get(url, headers=HEADERS, timeout=30)
            time.sleep(REQUEST_GAP_S)
            if resp.status_code == 200:
                break
            if attempt == retries:
                resp.raise_for_status()
            log.warning("%s: HTTP %s, retry %d", url, resp.status_code, attempt)
            time.sleep(30 * attempt)
        frames.append(parse_game_log(resp.text, team, start_year))
    df = pd.concat(frames, ignore_index=True)
    log.info("fetched %d-%02d from Basketball Reference: %d rows", start_year,
             (start_year + 1) % 100, len(df))  # fmt: skip
    return df
