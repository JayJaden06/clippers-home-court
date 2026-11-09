from __future__ import annotations

import pandas as pd
import pytest

from clippers_home_court import analysis, halves


def table(team: str, part: str, ftm: int, fta: int) -> str:
    """A box score table with a player row and a totals row, like Basketball Reference's."""
    return (
        f'<table id="box-{team}-{part}-basic"><tbody>'
        f'<tr><td data-stat="ft">99</td><td data-stat="fta">99</td></tr></tbody>'
        f'<tfoot><tr><td data-stat="fg">40</td><td data-stat="ft">{ftm}</td>'
        f'<td data-stat="fta">{fta}</td><td data-stat="ft_pct">.700</td></tr></tfoot></table>'
    )


def page(team: str, h1, h2, ots=(), game=None) -> str:
    total = game or tuple(sum(x) for x in zip(h1, h2, *ots, strict=True))
    parts = [table(team, "game", *total), table(team, "h1", *h1), table(team, "h2", *h2)]
    parts += [table(team, f"ot{i}", *ot) for i, ot in enumerate(ots, 1)]
    return "".join(parts)


def test_parse_halves_sums_overtimes():
    html = page("PHO", (7, 10), (8, 14), ots=[(6, 6), (4, 4)])
    got = halves.parse_halves(html, "PHO")
    assert got == {"game": (25, 34), "h1": (7, 10), "h2": (8, 14), "ot": (10, 10)}


def lac_game(**overrides) -> pd.Series:
    row = {"game_date": pd.Timestamp("2024-10-23"), "season": "2024-25", "opponent": "PHX",
           "ftm": 18, "fta": 22, "opp_ftm": 16, "opp_fta": 20}  # fmt: skip
    row.update(overrides)
    return pd.Series(row)


def test_game_row_uses_bbref_codes_and_checks_totals():
    html = page("LAC", (10, 12), (8, 10)) + page("PHO", (6, 9), (10, 11))
    row = halves.game_row(html, lac_game())
    assert (row["opp_ftm_h1"], row["opp_fta_h1"], row["opp_fta_h2"]) == (6, 9, 11)
    assert (row["lac_ftm_h2"], row["lac_fta_ot"]) == (8, 0)
    assert set(row) == set(halves.COLUMNS)


def test_game_row_rejects_halves_that_dont_match_the_box_score():
    html = page("LAC", (10, 12), (8, 10)) + page("PHO", (6, 9), (9, 11))  # 15/20, not 16/20
    with pytest.raises(ValueError, match="halves add up to 15/20"):
        halves.game_row(html, lac_game())


def test_missing_games_skips_stored_road_and_neutral_games():
    games = pd.DataFrame(
        {
            "team": ["LAC", "LAC", "LAC", "LAC", "PHX"],
            "location": ["home", "home", "away", "neutral", "home"],
            "season": ["2024-25"] * 5,
            "game_date": pd.to_datetime(
                ["2024-10-23", "2024-10-25", "2024-10-27", "2024-12-14", "2024-10-23"]
            ),
        }
    )
    have = pd.DataFrame({"game_date": pd.to_datetime(["2024-10-23"])})
    todo = halves.missing_games(games, have)
    assert list(todo["game_date"].dt.strftime("%m-%d")) == ["10-25"]


def test_ft_by_half_pools_and_measures_swing():
    df = pd.DataFrame(
        {
            "game_date": pd.to_datetime(["2023-11-01", "2024-11-01", "2024-11-03"]),
            "season": ["2023-24", "2024-25", "2024-25"],
            "opponent": ["PHX", "PHX", "DEN"],
            "opp_ftm_h1": [8, 6, 6], "opp_fta_h1": [10, 10, 10],
            "opp_ftm_h2": [8, 9, 7], "opp_fta_h2": [10, 10, 10],
            "opp_ftm_ot": [0, 0, 0], "opp_fta_ot": [0, 0, 0],
            "lac_ftm_h1": [8, 8, 8], "lac_fta_h1": [10, 10, 10],
            "lac_ftm_h2": [8, 8, 8], "lac_fta_h2": [10, 10, 10],
            "lac_ftm_ot": [0, 0, 0], "lac_fta_ot": [0, 0, 0],
        }
    )  # fmt: skip
    out = analysis.ft_by_half(df).set_index("arena")
    dome = out.loc["Intuit Dome"]
    assert dome["games"] == 2
    assert dome["opp_pct_h1"] == pytest.approx(0.6)
    assert dome["opp_pct_h2"] == pytest.approx(0.8)
    assert dome["opp_swing"] == pytest.approx(20.0)
    assert dome["opp_noise"] == pytest.approx(100 * (0.24 / 20 + 0.16 / 20) ** 0.5)
    assert out.loc["Crypto.com Arena", "opp_swing"] == pytest.approx(0.0)


def test_opponent_fts_by_game_compares_with_their_other_games():
    rows = []
    # PHX visits LAC once (5/10), plays one other game (18/20).
    for gid, team, opp, loc, ftm, fta, oftm, ofta in (
        ("g1", "LAC", "PHX", "home", 15, 20, 5, 10),
        ("g1", "PHX", "LAC", "away", 5, 10, 15, 20),
        ("g2", "PHX", "DEN", "home", 18, 20, 10, 10),
        ("g2", "DEN", "PHX", "away", 10, 10, 18, 20),
    ):
        rows.append({"game_id": gid, "season": "2024-25", "game_date": pd.Timestamp("2024-11-01"),
                     "team": team, "opponent": opp, "location": loc, "win": True,
                     "ftm": ftm, "fta": fta, "opp_ftm": oftm, "opp_fta": ofta})  # fmt: skip
    out = analysis.opponent_fts_by_game(pd.DataFrame(rows))
    assert len(out) == 1
    r = out.iloc[0]
    assert r["opponent"] == "PHX"
    assert r["ft_pct"] == pytest.approx(0.5)
    assert r["season_pct"] == pytest.approx(0.9)
    assert r["diff"] == pytest.approx(-40.0)
    assert r["arena"] == "Intuit Dome"
