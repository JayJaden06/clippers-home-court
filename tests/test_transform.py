from __future__ import annotations

import pandas as pd
from conftest import line, opponent_line

from clippers_home_court.transform import validate


def test_validate_good_game(game_rows):
    result = validate(pd.DataFrame(game_rows))
    assert len(result.games) == 1
    assert result.rejected == []
    df = result.to_frame()
    assert len(df) == 2
    assert set(df["team"]) == {"LAC", "PHX"}


def test_bad_row_quarantines_whole_game(game_rows):
    other = [
        line(GAME_ID="0022400002", PTS=999),  # fails the points identity
        opponent_line(GAME_ID="0022400002"),
    ]
    result = validate(pd.DataFrame(game_rows + other))
    assert [g.game_id for g in result.games] == ["0022400001"]
    assert [r.game_id for r in result.rejected] == ["0022400002"]
    assert "PTS" in result.rejected[0].reason
    # The surviving side of the bad game never reaches the table.
    assert set(result.to_frame()["game_id"]) == {"0022400001"}


def test_orphan_line_rejected():
    result = validate(pd.DataFrame([line()]))
    assert result.games == []
    assert "expected 2 lines" in result.rejected[0].reason
