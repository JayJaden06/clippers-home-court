"""Season labels, arenas, and known neutral-site windows."""

from __future__ import annotations

from datetime import date

FIRST_SEASON = 2013  # 2013-14: three seasons before the earliest arena move compared (SAC, 2016)
ANALYSIS_FIRST_SEASON = 2018  # the Clippers era comparison: six shared-arena seasons
NBA_API_FIRST_SEASON = 2018  # earlier seasons come from Basketball Reference (see bbref.py)

# The Clippers played at Staples Center (renamed Crypto.com Arena in Dec 2021),
# a building they shared with the Lakers, through 2023-24. Intuit Dome opened for 2024-25.
INTUIT_DOME_FIRST_SEASON = 2024
SHARED_ARENA = "Crypto.com Arena"
INTUIT_DOME = "Intuit Dome"

# Teams that moved into a newly built arena in the same metro area during the data window:
# team -> (first season in the new building, old arena, new arena). Every one is a new
# building, not a renamed one; renames (Staples Center -> Crypto.com Arena, Philips Arena ->
# State Farm Arena, ...) are deliberately not moves. This is every NBA arena opened since
# 2013; the Nets' 2012 move to Brooklyn (a relocation) predates the data anyway.
ARENA_MOVES = {
    "SAC": (2016, "Sleep Train Arena", "Golden 1 Center"),
    "DET": (2017, "The Palace of Auburn Hills", "Little Caesars Arena"),
    "MIL": (2018, "BMO Harris Bradley Center", "Fiserv Forum"),
    "GSW": (2019, "Oracle Arena", "Chase Center"),
    "LAC": (INTUIT_DOME_FIRST_SEASON, SHARED_ARENA, INTUIT_DOME),
}

# Seasons left out of before/after windows: 2020-21 was played with few or no fans.
NO_FAN_SEASONS = ("2020-21",)

# 2019-20 restart seeding games in the Orlando bubble. The API still labels
# one side "vs.", but nobody was at home.
BUBBLE_START = date(2020, 7, 30)
BUBBLE_END = date(2020, 10, 11)

# International and in-season-tournament games before 2024-25 that the source labels as
# ordinary home games. From 2024-25 on, both rows read 'A @ B' and they are detected
# automatically. IDs starting "90" are the synthetic Basketball Reference IDs (bbref.py).
# The Dec 2013 SAS-MIN game in Mexico City was postponed (generator fire) and replayed
# in Minneapolis, so it is a real home game. From 2024-25 on, both rows read 'A @ B' and
# they are detected automatically.
KNOWN_NEUTRAL_GAME_IDS = frozenset(
    {
        "9014011637",  # 2014-01-16 ATL-BKN, London
        "9014111250",  # 2014-11-12 HOU-MIN, Mexico City
        "9015011549",  # 2015-01-15 MIL-NYK, London
        "9015120358",  # 2015-12-03 BOS-SAC, Mexico City
        "9016011453",  # 2016-01-14 TOR-ORL, London
        "9017011243",  # 2017-01-12 IND-DEN, London
        "9017011256",  # 2017-01-12 DAL-PHX, Mexico City
        "9017011456",  # 2017-01-14 SAS-PHX, Mexico City
        "9017120751",  # 2017-12-07 OKC-BKN, Mexico City
        "9017120951",  # 2017-12-09 MIA-BKN, Mexico City
        "9018011155",  # 2018-01-11 BOS-PHI, London
        "0021800418",  # 2018-12-13 CHI-ORL, Mexico City
        "0021800429",  # 2018-12-15 UTA-ORL, Mexico City
        "0021800665",  # 2019-01-17 NYK-WAS, London
        "0021900380",  # 2019-12-14 SAS-PHX, Mexico City
        "0021900669",  # 2020-01-24 MIL-CHA, Paris
        "0022200439",  # 2022-12-17 MIA-SAS, Mexico City
        "0022200678",  # 2023-01-19 CHI-DET, Paris
        "0022300172",  # 2023-11-09 ATL-ORL, Mexico City
        "0022300527",  # 2024-01-11 BKN-CLE, Paris
        "0022301229",  # 2023-12-07 IND-MIL, In-Season Tournament semi, Las Vegas
        "0022301230",  # 2023-12-07 NOP-LAL, In-Season Tournament semi, Las Vegas
    }
)


def season_label(start_year: int) -> str:
    """2024 -> '2024-25'."""
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def season_start_year(label: str) -> int:
    """'2024-25' -> 2024."""
    return int(label[:4])


def season_from_id(season_id: str) -> str:
    """NBA SEASON_ID '22024' (2 = regular season) -> '2024-25'."""
    return season_label(int(season_id[1:]))


def current_season_start_year(today: date) -> int:
    """The season that is in progress (or most recently finished) on `today`.

    Regular seasons tip off in October, so anything before October belongs to
    the season that started the previous calendar year.
    """
    return today.year if today.month >= 10 else today.year - 1


def lac_home_arena(season: str) -> str:
    if season_start_year(season) >= INTUIT_DOME_FIRST_SEASON:
        return INTUIT_DOME
    return SHARED_ARENA


def in_bubble(d: date) -> bool:
    return BUBBLE_START <= d <= BUBBLE_END
