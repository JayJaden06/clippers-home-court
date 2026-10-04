"""Pydantic schema for NBA team box scores.

Two layers:

* ``TeamGameLine`` validates one raw row from stats.nba.com's LeagueGameFinder
  endpoint (one team's box score in one game).
* ``Game`` pairs the two lines for a game and checks that they agree with each
  other: same date, one winner, the winner outscored the loser, and
  there is exactly one home team unless the game was at a neutral site.

Anything that fails validation is rejected before it reaches storage, so the
dashboard never has to second-guess the data.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, computed_field, model_validator

from .seasons import KNOWN_NEUTRAL_GAME_IDS, in_bubble, season_from_id

MATCHUP_RE = re.compile(r"^(?P<team>[A-Z]{3}) (?P<sep>vs\.|@) (?P<opp>[A-Z]{3})$")


class TeamGameLine(BaseModel):
    """One team's box score line, as returned by LeagueGameFinder."""

    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    # SEASON_ID's leading digit is the season type; 2 = regular season.
    season_id: str = Field(alias="SEASON_ID", pattern=r"^2\d{4}$")
    team_id: int = Field(alias="TEAM_ID")
    team: str = Field(alias="TEAM_ABBREVIATION", pattern=r"^[A-Z]{3}$")
    game_id: str = Field(alias="GAME_ID", pattern=r"^\d{10}$")
    game_date: date = Field(alias="GAME_DATE")
    matchup: str = Field(alias="MATCHUP")
    wl: Literal["W", "L"] = Field(alias="WL")
    pts: NonNegativeInt = Field(alias="PTS")
    fgm: NonNegativeInt = Field(alias="FGM")
    fga: NonNegativeInt = Field(alias="FGA")
    fg3m: NonNegativeInt = Field(alias="FG3M")
    fg3a: NonNegativeInt = Field(alias="FG3A")
    ftm: NonNegativeInt = Field(alias="FTM")
    fta: NonNegativeInt = Field(alias="FTA")
    oreb: NonNegativeInt = Field(alias="OREB")
    dreb: NonNegativeInt = Field(alias="DREB")
    tov: NonNegativeInt = Field(alias="TOV")
    # PLUS_MINUS is deliberately not ingested: for older seasons the team-level
    # value is sometimes fractional or contradicts the final score (22 games in
    # 2018-19 alone). Margins are derived from PTS, which is checked below.

    @model_validator(mode="after")
    def _box_score_is_consistent(self) -> TeamGameLine:
        m = MATCHUP_RE.match(self.matchup)
        if not m:
            raise ValueError(f"unrecognised MATCHUP {self.matchup!r}")
        if m["team"] != self.team and m["opp"] != self.team:
            raise ValueError(f"{self.team} does not appear in MATCHUP {self.matchup!r}")
        if self.fgm > self.fga or self.fg3m > self.fg3a or self.ftm > self.fta:
            raise ValueError("makes exceed attempts")
        if self.fg3a > self.fga:
            raise ValueError("3PA exceeds FGA")
        if self.pts != 2 * self.fgm + self.fg3m + self.ftm:
            raise ValueError(
                f"PTS {self.pts} != 2*FGM + FG3M + FTM ({2 * self.fgm + self.fg3m + self.ftm})"
            )
        return self

    @property
    def season(self) -> str:
        return season_from_id(self.season_id)

    @property
    def labelled_home(self) -> bool:
        """True when this row's MATCHUP reads 'TEAM vs. OPP'."""
        return " vs. " in self.matchup

    @property
    def listed_host(self) -> str:
        """The team named second in MATCHUP. For neutral-site games, where both
        rows read 'A @ B', this is the nominal host."""
        return MATCHUP_RE.match(self.matchup)["opp"] if "@" in self.matchup else self.team

    @property
    def possessions_estimate(self) -> float:
        """Standard box-score estimate of possessions used (offensive rebounds
        extend a possession; FTA weighted for and-ones/technicals/3-shot fouls)."""
        return self.fga + 0.44 * self.fta - self.oreb + self.tov


class Game(BaseModel):
    """Both teams' lines for one regular-season game."""

    model_config = ConfigDict(frozen=True)

    home: TeamGameLine
    away: TeamGameLine
    neutral_site: bool

    @model_validator(mode="after")
    def _sides_agree(self) -> Game:
        h, a = self.home, self.away
        if h.game_id != a.game_id:
            raise ValueError(f"mismatched GAME_IDs {h.game_id} / {a.game_id}")
        if h.game_date != a.game_date:
            raise ValueError("lines disagree on game date")
        if h.team == a.team:
            raise ValueError(f"{h.team} listed on both sides")
        if {h.wl, a.wl} != {"W", "L"}:
            raise ValueError("expected exactly one winner")
        if h.pts == a.pts or (h.wl == "W") != (h.pts > a.pts):
            raise ValueError(f"WL disagrees with final score {h.pts}-{a.pts}")
        return self

    @computed_field
    @property
    def game_id(self) -> str:
        return self.home.game_id

    @computed_field
    @property
    def season(self) -> str:
        return self.home.season

    @computed_field
    @property
    def possessions(self) -> float:
        """Average of both teams' estimates; the two should be near-identical."""
        return 0.5 * (self.home.possessions_estimate + self.away.possessions_estimate)

    @classmethod
    def from_lines(cls, lines: list[TeamGameLine]) -> Game:
        if len(lines) != 2:
            raise ValueError(f"expected 2 lines for a game, got {len(lines)}")
        a, b = lines
        homes = [ln for ln in lines if ln.labelled_home]
        if len(homes) == 1:
            home = homes[0]
            neutral = in_bubble(home.game_date) or home.game_id in KNOWN_NEUTRAL_GAME_IDS
        elif not homes and a.listed_host == b.listed_host:
            # Paris / Mexico City / NBA Cup knockout games: both rows read 'X @ Y'.
            home = a if a.team == a.listed_host else b
            neutral = True
        else:
            raise ValueError(f"cannot determine home team from {a.matchup!r} / {b.matchup!r}")
        away = b if home is a else a
        return cls(home=home, away=away, neutral_site=neutral)

    def team_rows(self) -> list[dict]:
        """Two flat rows, one from each team's perspective."""
        rows = []
        for side, us, them in (("home", self.home, self.away), ("away", self.away, self.home)):
            rows.append(
                {
                    "game_id": self.game_id,
                    "season": self.season,
                    "game_date": us.game_date,
                    "team": us.team,
                    "opponent": them.team,
                    "location": "neutral" if self.neutral_site else side,
                    "win": us.wl == "W",
                    "possessions": self.possessions,
                    **{f: getattr(us, f) for f in BOX_FIELDS},
                    **{f"opp_{f}": getattr(them, f) for f in BOX_FIELDS},
                }
            )
        return rows


BOX_FIELDS = ("pts", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "tov")
