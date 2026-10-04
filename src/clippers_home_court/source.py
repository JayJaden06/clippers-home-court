"""Fetch raw team game logs from stats.nba.com via nba_api."""

from __future__ import annotations

import logging
import os
import time

import pandas as pd
from nba_api.stats.endpoints import leaguegamefinder

from .seasons import season_label

log = logging.getLogger(__name__)


def fetch_season(start_year: int, *, retries: int = 4, timeout: int = 60) -> pd.DataFrame:
    """Every team's box score line for one regular season (two rows per game).

    stats.nba.com is slow and drops requests from some datacenter IP ranges;
    set NBA_API_PROXY to route through a proxy if requests time out.
    """
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
