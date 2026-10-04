from __future__ import annotations

import pandas as pd

from clippers_home_court import bbref
from clippers_home_court.transform import validate


def row(date, loc, opp, host, result, pts, opp_pts, fg, fg3, ft):
    """One Basketball Reference game-log row. Box score: fg FGM / 85 FGA, fg3 / 30,
    ft / 25, 10 ORB, 30 DRB, 12 TOV."""
    stats = {
        "date": date, "game_location": loc, "opp_name_abbr": f'<a href="/teams/{opp}/x">{opp}</a>',
        "team_game_result": result, "team_game_score": pts, "opp_team_game_score": opp_pts,
        "fg": fg, "fga": 85, "fg3": fg3, "fg3a": 30, "ft": ft, "fta": 25,
        "orb": 10, "drb": 30, "tov": 12,
    }  # fmt: skip
    cells = "".join(f'<td data-stat="{k}">{v}</td>' for k, v in stats.items())
    link = f'<a href="/boxscores/{date.replace("-", "")}0{host}.html">box</a>'
    return f"<tr><th data-stat='ranker'>1</th>{cells}<td>{link}</td></tr>"


def page(team_rows: str) -> str:
    totals = '<tr><td data-stat="date"></td><td data-stat="fg">3000</td></tr>'
    return f'<table id="team_game_log_reg"><tbody>{team_rows}{totals}</tbody></table>'


def test_home_away_and_neutral_rows_validate_as_games():
    # 2*40+10+15 = 105; 2*35+8+20 = 98
    phx = page(
        row("2016-11-01", "", "BRK", "PHO", "W", 105, 98, 40, 10, 15)
        + row("2017-01-14", "N", "SAS", "PHO", "W", 105, 98, 40, 10, 15)
    )
    bkn = page(row("2016-11-01", "@", "PHO", "PHO", "L", 98, 105, 35, 8, 20))
    sas = page(row("2017-01-14", "N", "PHO", "PHO", "L", 98, 105, 35, 8, 20))
    raw = pd.concat(
        [
            bbref.parse_game_log(phx, "PHX", 2016),
            bbref.parse_game_log(bkn, "BKN", 2016),
            bbref.parse_game_log(sas, "SAS", 2016),
        ]
    )
    assert list(raw["MATCHUP"]) == ["PHX vs. BKN", "PHX @ PHX", "BKN @ PHX", "SAS @ PHX"]
    result = validate(raw)
    assert result.rejected == []
    games = {g.home.game_date.isoformat(): g for g in result.games}
    assert not games["2016-11-01"].neutral_site
    assert games["2017-01-14"].neutral_site  # rows marked "N" by Basketball Reference
    assert games["2017-01-14"].home.team == "PHX"


def test_bbref_codes_round_trip():
    assert bbref.bbref_code("CHA", 2013) == "CHA"  # Bobcats
    assert bbref.bbref_code("CHA", 2014) == "CHO"
    assert bbref.bbref_code("BKN", 2016) == "BRK"
    assert bbref.to_nba("PHO") == "PHX"
