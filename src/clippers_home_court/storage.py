"""Read/write the team-game table to a local directory or a gs:// bucket.

Layout under DATA_URI:
    team_games/season=2024-25.parquet   one file per season, rewritten idempotently
    exports/team_games.csv              everything, flattened, for Tableau
"""

from __future__ import annotations

import json
import os

import fsspec
import pandas as pd

DEFAULT_DATA_URI = "data"


def data_uri() -> str:
    return os.environ.get("DATA_URI", DEFAULT_DATA_URI).rstrip("/")


def _storage_options(uri: str) -> dict:
    # Lets the public dashboard read a public-read bucket without credentials.
    if uri.startswith("gs://") and os.environ.get("GCS_ANON") == "1":
        return {"token": "anon"}
    return {}


def _fs(uri: str):
    fs, _ = fsspec.core.url_to_fs(uri, **_storage_options(uri))
    return fs


def season_path(uri: str, season: str) -> str:
    return f"{uri}/team_games/season={season}.parquet"


def stored_seasons(uri: str) -> set[str]:
    fs = _fs(uri)
    paths = fs.glob(f"{uri}/team_games/season=*.parquet")
    return {p.rsplit("season=", 1)[1].removesuffix(".parquet") for p in paths}


def write_season(uri: str, season: str, df: pd.DataFrame) -> None:
    fs = _fs(uri)
    fs.makedirs(f"{uri}/team_games", exist_ok=True)
    with fs.open(season_path(uri, season), "wb") as f:
        df.to_parquet(f, index=False)


def read_all(uri: str) -> pd.DataFrame:
    fs = _fs(uri)
    frames = []
    for season in sorted(stored_seasons(uri)):
        with fs.open(season_path(uri, season), "rb") as f:
            frames.append(pd.read_parquet(f))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def write_exports(uri: str, df: pd.DataFrame, run_report: dict) -> None:
    fs = _fs(uri)
    fs.makedirs(f"{uri}/exports", exist_ok=True)
    with fs.open(f"{uri}/exports/team_games.csv", "w") as f:
        df.to_csv(f, index=False)
    with fs.open(f"{uri}/exports/last_run.json", "w") as f:
        json.dump(run_report, f, indent=2, default=str)
