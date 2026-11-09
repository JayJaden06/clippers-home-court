"""Free throws by half in Clippers home games, from Basketball Reference box scores.

The team game table only has full-game totals. To see whether visitors shoot free throws
worse in one half (when they attack the end with The Wall behind it) than the other, this
pulls each Clippers home game's box score page, which has separate 1st-half, 2nd-half and
overtime tables, and stores one row per game:

    data/ft_halves.parquet

Rows are keyed by game date (the Clippers play at most one home game a day), because
GAME_ID depends on which source the daily job used. Every game is checked against the
validated full-game box score: 1st half + 2nd half + OT must equal the game total for both
teams, or the game is skipped and retried on the next run.

    clippers-halves              # fetch any Clippers home games not stored yet
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time

import pandas as pd
import requests

from . import LAC, storage
from .bbref import HEADERS, REQUEST_GAP_S, bbref_code
from .seasons import ANALYSIS_FIRST_SEASON, season_label, season_start_year

log = logging.getLogger(__name__)

URL = "https://www.basketball-reference.com/boxscores/{date:%Y%m%d}0{home}.html"
FT_RE = re.compile(r'data-stat="(fta?)"[^>]*>(\d*)<')
PARTS = ("h1", "h2", "ot")
COLUMNS = [
    "game_date", "season", "opponent",
    *(f"{side}_{stat}_{part}" for side in ("opp", "lac") for part in PARTS
      for stat in ("ftm", "fta")),
]  # fmt: skip


def halves_path(uri: str) -> str:
    return f"{uri}/ft_halves.parquet"


def read(uri: str) -> pd.DataFrame:
    fs = storage._fs(uri)
    if not fs.exists(halves_path(uri)):
        return pd.DataFrame(columns=COLUMNS)
    with fs.open(halves_path(uri), "rb") as f:
        return pd.read_parquet(f)


def write(uri: str, df: pd.DataFrame) -> None:
    fs = storage._fs(uri)
    with fs.open(halves_path(uri), "wb") as f:
        df.sort_values("game_date").to_parquet(f, index=False)


def _table_ft(html: str, table_id: str) -> tuple[int, int] | None:
    """(FTM, FTA) from the totals row of one box score table, or None if it's absent."""
    start = html.find(f'id="{table_id}"')
    if start < 0:
        return None
    end = html.find("</table>", start)
    foot = html[html.find("<tfoot", start, end) : end]
    stats = dict(FT_RE.findall(foot))
    if not stats.get("ft") or not stats.get("fta"):
        raise ValueError(f"{table_id}: no FT totals")
    return int(stats["ft"]), int(stats["fta"])


def parse_halves(html: str, team_code: str) -> dict[str, tuple[int, int]]:
    """One team's (FTM, FTA) for h1, h2, ot (all overtimes summed) and the full game."""
    out = {}
    for part in ("game", "h1", "h2"):
        ft = _table_ft(html, f"box-{team_code}-{part}-basic")
        if ft is None:
            raise ValueError(f"box-{team_code}-{part}-basic not found")
        out[part] = ft
    ot = [0, 0]
    n = 1
    while (ft := _table_ft(html, f"box-{team_code}-ot{n}-basic")) is not None:
        ot[0] += ft[0]
        ot[1] += ft[1]
        n += 1
    out["ot"] = (ot[0], ot[1])
    return out


def game_row(html: str, game: pd.Series) -> dict:
    """The stored row for one Clippers home game. `game` is the Clippers' row from the
    team game table; the page must agree with its validated full-game FT totals."""
    start_year = season_start_year(game["season"])
    row: dict = {
        "game_date": pd.Timestamp(game["game_date"]),
        "season": game["season"],
        "opponent": game["opponent"],
    }
    for side, team, prefix in (("lac", LAC, ""), ("opp", game["opponent"], "opp_")):
        parts = parse_halves(html, bbref_code(team, start_year))
        h1, h2, ot = parts["h1"], parts["h2"], parts["ot"]
        total = (h1[0] + h2[0] + ot[0], h1[1] + h2[1] + ot[1])
        expected = (int(game[f"{prefix}ftm"]), int(game[f"{prefix}fta"]))
        if total != expected or parts["game"] != expected:
            raise ValueError(
                f"{team}: halves add up to {total[0]}/{total[1]} FT, page says "
                f"{parts['game'][0]}/{parts['game'][1]}, box score says "
                f"{expected[0]}/{expected[1]}"
            )
        for part, (m, a) in (("h1", h1), ("h2", h2), ("ot", ot)):
            row[f"{side}_ftm_{part}"] = m
            row[f"{side}_fta_{part}"] = a
    return row


def missing_games(games: pd.DataFrame, have: pd.DataFrame) -> pd.DataFrame:
    """Clippers home games (not neutral site) from ANALYSIS_FIRST_SEASON on that aren't
    stored yet."""
    home = games[
        (games["team"] == LAC)
        & (games["location"] == "home")
        & (games["season"] >= season_label(ANALYSIS_FIRST_SEASON))
    ]
    stored = set(pd.to_datetime(have["game_date"]))
    return home[~pd.to_datetime(home["game_date"]).isin(stored)].sort_values("game_date")


def update(uri: str, *, limit: int | None = None, retries: int = 3) -> dict:
    """Fetch and store every missing Clippers home game. Returns a small report."""
    games = storage.read_all(uri)
    have = read(uri)
    todo = missing_games(games, have)
    if limit is not None:
        todo = todo.head(limit)
    log.info("%d Clippers home games to fetch", len(todo))

    session = requests.Session()
    rows, rejected = [], []
    for _, game in todo.iterrows():
        url = URL.format(date=pd.Timestamp(game["game_date"]), home=LAC)
        for attempt in range(1, retries + 1):
            resp = session.get(url, headers=HEADERS, timeout=30)
            time.sleep(REQUEST_GAP_S)
            if resp.status_code in (200, 404):
                break
            log.warning("%s: HTTP %s, retry %d", url, resp.status_code, attempt)
            time.sleep(30 * attempt)
        try:
            resp.raise_for_status()
            rows.append(game_row(resp.text, game))
        except Exception as exc:  # retried on the next run
            log.warning("%s: skipped (%s)", url, exc)
            rejected.append({"game_date": str(game["game_date"].date()), "reason": str(exc)})

    if rows:
        new = pd.DataFrame(rows, columns=COLUMNS)
        write(uri, pd.concat([have, new], ignore_index=True) if len(have) else new)
    log.info("stored %d games, skipped %d", len(rows), len(rejected))
    return {"fetched": len(rows), "rejected": rejected, "total": len(have) + len(rows)}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--limit", type=int, help="fetch at most this many games")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stdout
    )
    report = update(storage.data_uri(), limit=args.limit)
    if report["rejected"] and not report["fetched"]:
        raise SystemExit(f"every game failed: {report['rejected'][:3]}")


if __name__ == "__main__":
    main()
