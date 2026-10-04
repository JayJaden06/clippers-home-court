from __future__ import annotations

import pytest


def line(**overrides) -> dict:
    """A raw LeagueGameFinder row that passes validation (LAC 110, home)."""
    row = {
        "SEASON_ID": "22024",
        "TEAM_ID": 1610612746,
        "TEAM_ABBREVIATION": "LAC",
        "GAME_ID": "0022400001",
        "GAME_DATE": "2024-10-23",
        "MATCHUP": "LAC vs. PHX",
        "WL": "W",
        # 2*40 + 12 + 18 = 110
        "PTS": 110,
        "FGM": 40,
        "FGA": 85,
        "FG3M": 12,
        "FG3A": 33,
        "FTM": 18,
        "FTA": 22,
        "OREB": 10,
        "DREB": 34,
        "TOV": 12,
        "PLUS_MINUS": 8.0,
    }
    row.update(overrides)
    return row


def opponent_line(**overrides) -> dict:
    """PHX's side of the same game (102, away)."""
    base = {
        "TEAM_ID": 1610612756,
        "TEAM_ABBREVIATION": "PHX",
        "MATCHUP": "PHX @ LAC",
        "WL": "L",
        # 2*38 + 10 + 16 = 102
        "PTS": 102,
        "FGM": 38,
        "FGA": 88,
        "FG3M": 10,
        "FG3A": 35,
        "FTM": 16,
        "FTA": 20,
        "OREB": 11,
        "DREB": 32,
        "TOV": 14,
    }
    base.update(overrides)
    return line(**base)


@pytest.fixture
def game_rows() -> list[dict]:
    return [line(), opponent_line()]
