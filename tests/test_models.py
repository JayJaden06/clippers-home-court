from __future__ import annotations

import pytest
from conftest import line, opponent_line
from pydantic import ValidationError

from clippers_home_court.models import Game, TeamGameLine


def test_valid_line_parses():
    ln = TeamGameLine.model_validate(line())
    assert ln.team == "LAC"
    assert ln.season == "2024-25"
    assert ln.labelled_home
    assert ln.possessions_estimate == pytest.approx(85 + 0.44 * 22 - 10 + 12)


@pytest.mark.parametrize(
    "overrides",
    [
        {"SEASON_ID": "42024"},  # playoffs, not regular season
        {"TEAM_ABBREVIATION": "lac"},
        {"GAME_ID": "22400001"},
        {"WL": None},
        {"PTS": 111},  # doesn't match 2*FGM + FG3M + FTM
        {"FGM": 90, "PTS": 2 * 90 + 12 + 18},  # makes > attempts
        {"FG3A": 90, "FGA": 85},  # 3PA > FGA
        {"MATCHUP": "LAC vs PHX"},
        {"MATCHUP": "BOS vs. PHX"},  # team not in matchup
        {"TOV": -1},
    ],
)
def test_bad_lines_rejected(overrides):
    with pytest.raises(ValidationError):
        TeamGameLine.model_validate(line(**overrides))


def test_plus_minus_is_ignored():
    # Fractional/contradictory PLUS_MINUS values exist upstream; they must not fail a row.
    TeamGameLine.model_validate(line(PLUS_MINUS=7.6))


def lines(*rows):
    return [TeamGameLine.model_validate(r) for r in rows]


def test_game_pairs_home_and_away(game_rows):
    g = Game.from_lines(lines(*game_rows))
    assert (g.home.team, g.away.team) == ("LAC", "PHX")
    assert not g.neutral_site
    rows = g.team_rows()
    assert [r["location"] for r in rows] == ["home", "away"]
    assert rows[0]["opp_pts"] == rows[1]["pts"] == 102


def test_game_rejects_two_winners():
    with pytest.raises(ValidationError, match="exactly one winner"):
        Game.from_lines(lines(line(), opponent_line(WL="W")))


def test_game_rejects_wl_contradicting_score():
    # PHX scores more but is marked the loser.
    phx = opponent_line(FGM=45, PTS=2 * 45 + 10 + 16)
    with pytest.raises(ValidationError, match="disagrees with final score"):
        Game.from_lines(lines(line(), phx))


def test_game_rejects_single_line():
    with pytest.raises(ValueError, match="expected 2 lines"):
        Game.from_lines(lines(line()))


def test_neutral_site_both_away():
    # From 2024-25, Paris/Mexico City/NBA Cup knockout games read 'A @ B' on both rows.
    g = Game.from_lines(lines(line(MATCHUP="LAC @ PHX"), opponent_line(MATCHUP="PHX @ PHX")))
    assert g.neutral_site
    assert g.home.team == "PHX"
    assert {r["location"] for r in g.team_rows()} == {"neutral"}


def test_bubble_games_are_neutral():
    bubble = {"SEASON_ID": "22019", "GAME_ID": "0021901300", "GAME_DATE": "2020-08-01"}
    g = Game.from_lines(lines(line(**bubble), opponent_line(**bubble)))
    assert g.neutral_site


def test_known_neutral_id_is_neutral():
    paris = {"SEASON_ID": "22023", "GAME_ID": "0022300527", "GAME_DATE": "2024-01-11"}
    g = Game.from_lines(lines(line(**paris), opponent_line(**paris)))
    assert g.neutral_site
