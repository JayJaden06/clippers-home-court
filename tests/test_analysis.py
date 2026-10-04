from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from clippers_home_court import analysis
from clippers_home_court.seasons import (
    current_season_start_year,
    lac_home_arena,
    season_from_id,
    season_label,
)


def test_season_helpers():
    assert season_label(2024) == "2024-25"
    assert season_label(2099) == "2099-00"
    assert season_from_id("22018") == "2018-19"
    assert current_season_start_year(date(2025, 9, 30)) == 2024
    assert current_season_start_year(date(2025, 10, 1)) == 2025
    assert lac_home_arena("2023-24") == "Crypto.com Arena"
    assert lac_home_arena("2024-25") == "Intuit Dome"


def synthetic(seasons: list[str], teams: list[str], home_margin: dict[str, float]) -> pd.DataFrame:
    """Every team plays every other team home and away once per season.
    Each game has 100 possessions; the home team wins by `home_margin[home]`."""
    rows = []
    for season in seasons:
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                m = home_margin.get(h, 0.0)
                gid = f"{season}{h}{a}"
                for team, opp, loc, pts, opp_pts in (
                    (h, a, "home", 100 + m, 100.0),
                    (a, h, "away", 100.0, 100 + m),
                ):
                    rows.append(
                        {
                            "game_id": gid, "season": season, "team": team, "opponent": opp,
                            "location": loc, "win": pts > opp_pts, "possessions": 100.0,
                            "pts": pts, "opp_pts": opp_pts,
                            **{c: 1 for c in analysis.SUM_COLS if c not in
                               {"pts", "opp_pts", "possessions"}},
                        }
                    )  # fmt: skip
    return pd.DataFrame(rows)


def test_home_edges_and_league_context():
    df = synthetic(["2023-24"], ["LAC", "BOS", "DEN"], {"LAC": 6.0})
    edges = analysis.home_edges(df).set_index("team")
    # LAC: +6 per home game, 0 on the road -> edge 6. Others: 0 home, and they lose
    # by 6 at LAC in one of two road games -> away net -3 -> edge +3.
    assert edges.loc["LAC", "edge"] == pytest.approx(6.0)
    assert edges.loc["BOS", "edge"] == pytest.approx(3.0)
    ctx = analysis.league_context(analysis.home_edges(df)).iloc[0]
    assert ctx["rank"] == 1
    assert ctx["league_mean"] == pytest.approx(4.0)
    assert ctx["excess"] == pytest.approx(2.0)


def test_neutral_games_excluded():
    df = synthetic(["2023-24"], ["LAC", "BOS"], {"LAC": 6.0})
    neutral = df.iloc[:2].assign(location="neutral", game_id="x", pts=500.0)
    edges = analysis.home_edges(pd.concat([df, neutral]))
    assert edges.set_index("team").loc["LAC", "edge"] == pytest.approx(6.0)


def test_era_comparison_detects_change():
    teams = ["LAC", "BOS", "DEN", "MIA"]
    old = synthetic(["2022-23", "2023-24"], teams, {"LAC": 0.0})
    new = synthetic(["2024-25"], teams, {"LAC": 10.0})
    out = analysis.era_comparison(pd.concat([old, new]), n=200)
    assert set(out["eras"]) == {"Crypto.com Arena", "Intuit Dome"}
    assert out["change"]["from"] == "Crypto.com Arena"
    assert out["change"]["delta"] > 0
    # No game-to-game noise in synthetic data -> a degenerate, certain interval.
    assert out["change"]["p_increase"] == 1.0


def test_bootstrap_is_seeded():
    df = synthetic(["2023-24"], ["LAC", "BOS"], {"LAC": 4.0})
    lac = df[df["team"] == "LAC"]
    a = analysis.bootstrap_edge(lac, n=50, seed=1)
    b = analysis.bootstrap_edge(lac, n=50, seed=1)
    assert np.array_equal(a, b)


SEASONS = [f"{y}-{(y + 1) % 100:02d}" for y in range(2013, 2026)]


def test_move_windows_skips_no_fan_season():
    pre, post = analysis.move_windows(2019, SEASONS)  # GSW to Chase Center
    assert pre == ["2016-17", "2017-18", "2018-19"]
    assert post == ["2019-20", "2021-22"]  # 2020-21 skipped
    assert analysis.move_windows(2014, SEASONS) is None  # not enough seasons before
    assert analysis.move_windows(2025, SEASONS) is None  # not enough seasons after


def test_placebo_leaves_out_real_moves():
    teams = ["LAC", "BOS", "GSW"]
    df = synthetic(SEASONS, teams, {"LAC": 3.0, "BOS": 3.0, "GSW": 3.0})
    placebo = analysis.placebo_changes(df)
    # Nothing changes in this league, so every placebo change is zero.
    assert np.allclose(placebo["delta"], 0)
    # GSW moved for 2019-20: any window holding seasons from both buildings is left out.
    gsw = set(placebo.loc[placebo["team"] == "GSW", "split_season"])
    assert gsw.isdisjoint({"2018-19", "2019-20", "2021-22", "2022-23"})
    assert "2017-18" in gsw  # 2014-15..2016-17 vs 2017-18..2018-19: all Oracle Arena
    # 2020-21 is skipped, so it is never used as a fake move season.
    assert "2020-21" not in set(placebo["split_season"])
    assert not placebo.duplicated(["team", "split_season"]).any()


def test_arena_moves_measures_change():
    teams = ["LAC", "BOS", "GSW", "MIL"]
    margins = {s: {"GSW": 8.0 if s >= "2019-20" else 2.0} for s in SEASONS}
    df = pd.concat(synthetic([s], teams, margins[s]) for s in SEASONS)
    moves = analysis.arena_moves(df, n=100).set_index("team")
    assert moves.loc["GSW", "delta"] > 0
    assert moves.loc["GSW", "after_seasons"] == "2019-20 to 2021-22"
    # MIL didn't change; it only moves slightly because it plays at GSW.
    assert abs(moves.loc["MIL", "delta"]) < moves.loc["GSW", "delta"] / 4


def test_visitor_free_throws_against_own_baseline():
    def game(gid, home, away, away_ftm):
        base = {"season": "2024-25", "game_id": gid, "possessions": 100.0}
        return [
            {**base, "team": home, "opponent": away, "location": "home", "ftm": 16, "fta": 20},
            {
                **base,
                "team": away,
                "opponent": home,
                "location": "away",
                "ftm": away_ftm,
                "fta": 20,
            },
        ]

    rows = (
        game("1", "LAC", "BOS", 10)  # BOS shoots 50% at LAC...
        + game("2", "MIA", "BOS", 16)  # ...and 80% elsewhere
        + game("3", "BOS", "MIA", 16)
        + game("4", "BOS", "LAC", 16)
    )
    ft = analysis.visitor_free_throws(pd.DataFrame(rows)).set_index("arena_team")
    assert ft.loc["LAC", "diff"] == pytest.approx(-30.0)  # 10 made vs. 16 expected, of 20
    assert ft.loc["LAC", "rank"] == 1
