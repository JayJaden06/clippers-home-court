"""Raw LeagueGameFinder rows -> validated games -> flat team-game table."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd
from pydantic import ValidationError

from .models import Game, TeamGameLine


@dataclass
class Rejection:
    game_id: str
    reason: str


@dataclass
class ValidationResult:
    games: list[Game] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)

    def to_frame(self) -> pd.DataFrame:
        rows = [r for g in self.games for r in g.team_rows()]
        df = pd.DataFrame(rows)
        if not df.empty:
            df["game_date"] = pd.to_datetime(df["game_date"])
            df = df.sort_values(["game_date", "game_id", "team"]).reset_index(drop=True)
        return df


def validate(raw: pd.DataFrame) -> ValidationResult:
    """Validate every row, pair rows into games, and quarantine anything that
    fails. A bad row takes its whole game with it, so a game is never stored
    with only one side."""
    result = ValidationResult()
    by_game: dict[str, list[TeamGameLine]] = defaultdict(list)
    bad_games: dict[str, str] = {}

    for rec in raw.to_dict(orient="records"):
        gid = str(rec.get("GAME_ID", "?"))
        try:
            by_game[gid].append(TeamGameLine.model_validate(rec))
        except ValidationError as exc:
            bad_games.setdefault(gid, _short(exc))

    for gid, lines in by_game.items():
        if gid in bad_games:
            continue
        try:
            result.games.append(Game.from_lines(lines))
        except (ValidationError, ValueError) as exc:
            bad_games[gid] = _short(exc)

    result.rejected = [Rejection(g, r) for g, r in sorted(bad_games.items())]
    return result


def _short(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        e = exc.errors()[0]
        loc = ".".join(str(p) for p in e["loc"])
        return f"{loc}: {e['msg']}" if loc else e["msg"]
    return str(exc)
