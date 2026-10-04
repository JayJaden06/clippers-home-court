"""Season labels, arenas, and known neutral-site windows."""

from __future__ import annotations

from datetime import date

FIRST_SEASON = 2018  # 2018-19: six seasons in the shared arena before the move

# The Clippers played at Staples Center (renamed Crypto.com Arena in Dec 2021),
# a building they shared with the Lakers, through 2023-24. Intuit Dome opened for 2024-25.
INTUIT_DOME_FIRST_SEASON = 2024
SHARED_ARENA = "Crypto.com Arena"
INTUIT_DOME = "Intuit Dome"

# 2019-20 restart seeding games in the Orlando bubble. The API still labels
# one side "vs.", but nobody was at home.
BUBBLE_START = date(2020, 7, 30)
BUBBLE_END = date(2020, 10, 11)

# International and in-season-tournament games before 2024-25 that the API
# labels as ordinary home games. From 2024-25 on, both rows read 'A @ B' and
# they are detected automatically.
KNOWN_NEUTRAL_GAME_IDS = frozenset(
    {
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
