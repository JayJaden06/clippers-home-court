"""Fetch raw team game logs from stats.nba.com via nba_api."""

from __future__ import annotations

import logging
import os
import time

import pandas as pd
from nba_api.stats.endpoints import leaguegamefinder

from . import bbref
from .seasons import NBA_API_FIRST_SEASON, season_label

log = logging.getLogger(__name__)


def fetch_season(start_year: int) -> pd.DataFrame:
    """Every team's box score line for one regular season (two rows per game).
    ``df.attrs["source"]`` records where the rows came from.

    Seasons before NBA_API_FIRST_SEASON come from Basketball Reference. Later seasons
    come from stats.nba.com, which blocks many datacenter IP ranges (including GitHub
    Actions runners); if it fails, Basketball Reference is used instead unless
    BBREF_FALLBACK=0. Set NBA_API_PROXY to route stats.nba.com through a proxy.
    """
    if start_year < NBA_API_FIRST_SEASON:
        df = bbref.fetch_season(start_year)
    else:
        try:
            df = fetch_nba_api(start_year, retries=int(os.environ.get("NBA_API_RETRIES", 4)))
            df.attrs["source"] = "stats.nba.com"
            return df
        except Exception as exc:
            if os.environ.get("BBREF_FALLBACK", "1") == "0":
                raise
            log.warning("stats.nba.com failed (%s); using Basketball Reference", exc)
            df = bbref.fetch_season(start_year)
    df.attrs["source"] = "basketball-reference.com"
    return df


def fetch_nba_api(start_year: int, *, retries: int = 4, timeout: int = 60) -> pd.DataFrame:
    """One regular season from stats.nba.com's LeagueGameFinder endpoint."""
    proxy = os.environ.get("NBA_API_PROXY") or None
    season = season_label(start_year)
    for attempt in range(1, retries + 1):
        try:
            frames = leaguegamefinder.LeagueGameFinder(
                player_or_team_abbreviation="T",
                season_nullable=season,
                season_type_nullable="Regular Season",
                league_id_nullable="00",
                proxy=proxy,
                timeout=timeout,
            ).get_data_frames()
            df = frames[0]
            log.info("fetched %s: %d rows", season, len(df))
            return df
        except Exception as exc:  # nba_api surfaces requests/JSON errors as-is
            if attempt == retries:
                raise
            wait = 5 * 2 ** (attempt - 1)
            log.warning("fetch %s failed (%s); retry %d in %ds", season, exc, attempt, wait)
            time.sleep(wait)
    raise AssertionError("unreachable")
