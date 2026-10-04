"""Ingestion job: the Cloud Run Job entrypoint.

Each run backfills any season missing from storage and re-pulls the current
season, so a daily schedule keeps it fresh and reruns are idempotent.

    python -m clippers_home_court.job                 # backfill + refresh current
    python -m clippers_home_court.job --seasons 2024 2025
    DATA_URI=gs://my-bucket python -m clippers_home_court.job
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime

from . import source, storage
from .seasons import FIRST_SEASON, current_season_start_year, season_label
from .transform import validate

log = logging.getLogger("clippers_home_court")


def run(seasons: list[int], *, uri: str, max_reject_rate: float) -> dict:
    report: dict = {"started_at": datetime.now(UTC).isoformat(), "data_uri": uri, "seasons": {}}
    for year in seasons:
        label = season_label(year)
        raw = source.fetch_season(year)
        if raw.empty:
            log.info("%s: no games yet, skipping", label)
            report["seasons"][label] = {"games": 0}
            continue

        result = validate(raw)
        n_games = raw["GAME_ID"].nunique()
        reject_rate = len(result.rejected) / n_games
        for r in result.rejected:
            log.warning("%s: rejected game %s: %s", label, r.game_id, r.reason)
        report["seasons"][label] = {
            "games": len(result.games),
            "rejected": [vars(r) for r in result.rejected],
            "neutral_site": sum(g.neutral_site for g in result.games),
        }
        if reject_rate > max_reject_rate:
            raise SystemExit(
                f"{label}: {len(result.rejected)}/{n_games} games failed validation "
                f"({reject_rate:.1%} > {max_reject_rate:.1%}); nothing written for this season"
            )
        storage.write_season(uri, label, result.to_frame())
        log.info("%s: wrote %d games (%d rejected)", label, len(result.games), len(result.rejected))

    everything = storage.read_all(uri)
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["total_team_games"] = len(everything)
    storage.write_exports(uri, everything, report)
    return report


def seasons_to_fetch(uri: str, today: date, refresh_all: bool) -> list[int]:
    current = current_season_start_year(today)
    wanted = range(FIRST_SEASON, current + 1)
    if refresh_all:
        return list(wanted)
    have = storage.stored_seasons(uri)
    return [y for y in wanted if season_label(y) not in have or y == current]


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--seasons", type=int, nargs="*", help="season start years, e.g. 2024 2025")
    p.add_argument("--refresh-all", action="store_true", help="re-pull every season")
    p.add_argument(
        "--max-reject-rate",
        type=float,
        default=0.0,
        help="fail the run if more than this fraction of a season's games fail validation",
    )
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stdout
    )

    uri = storage.data_uri()
    seasons = args.seasons or seasons_to_fetch(uri, date.today(), args.refresh_all)
    log.info("data_uri=%s seasons=%s", uri, [season_label(y) for y in seasons])
    report = run(seasons, uri=uri, max_reject_rate=args.max_reject_rate)
    log.info("done: %d team-game rows stored", report["total_team_games"])


if __name__ == "__main__":
    main()
