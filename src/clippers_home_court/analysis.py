"""Home/away split metrics on the team-game table.

The core number is a team's **home edge**: net rating at home minus net rating
on the road, in points per 100 possessions. Because the same roster plays both
halves of the schedule, team quality largely cancels out, leaving the venue
effect (crowd, travel, familiarity, officiating). Every season is compared with
the league-wide average edge for that season, which absorbs league trends
such as the 2020-21 seasons played with few or no fans.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import LAC
from .seasons import (
    ARENA_MOVES,
    INTUIT_DOME,
    NO_FAN_SEASONS,
    SHARED_ARENA,
    lac_home_arena,
    season_label,
    season_start_year,
)

SUM_COLS = [
    "pts", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "tov",
    "opp_pts", "opp_fgm", "opp_fga", "opp_fg3m", "opp_fg3a", "opp_ftm", "opp_fta",
    "opp_oreb", "opp_dreb", "opp_tov", "possessions",
]  # fmt: skip


def rates(sums: pd.DataFrame) -> pd.DataFrame:
    """Turn summed box-score columns into per-possession and shooting rates."""
    s = sums
    out = pd.DataFrame(index=s.index)
    out["games"] = s["games"]
    out["wins"] = s["wins"]
    out["win_pct"] = s["wins"] / s["games"]
    out["ortg"] = 100 * s["pts"] / s["possessions"]
    out["drtg"] = 100 * s["opp_pts"] / s["possessions"]
    out["net"] = out["ortg"] - out["drtg"]
    out["efg"] = (s["fgm"] + 0.5 * s["fg3m"]) / s["fga"]
    out["opp_efg"] = (s["opp_fgm"] + 0.5 * s["opp_fg3m"]) / s["opp_fga"]
    out["tov_pct"] = s["tov"] / s["possessions"]
    out["opp_tov_pct"] = s["opp_tov"] / s["possessions"]
    out["orb_pct"] = s["oreb"] / (s["oreb"] + s["opp_dreb"])
    out["drb_pct"] = s["dreb"] / (s["dreb"] + s["opp_oreb"])
    out["ft_rate"] = s["ftm"] / s["fga"]
    out["opp_ft_rate"] = s["opp_ftm"] / s["opp_fga"]
    out["fg3_pct"] = s["fg3m"] / s["fg3a"]
    out["opp_fg3_pct"] = s["opp_fg3m"] / s["opp_fg3a"]
    return out


def summarize(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    g = df.groupby(by, observed=True)
    sums = g[SUM_COLS].sum()
    sums["games"] = g.size()
    sums["wins"] = g["win"].sum()
    return rates(sums).reset_index()


def with_era(df: pd.DataFrame) -> pd.DataFrame:
    """Tag every row with the arena the Clippers called home that season."""
    arenas = {s: lac_home_arena(s) for s in df["season"].unique()}
    return df.assign(era=df["season"].map(arenas))


def home_edges(df: pd.DataFrame) -> pd.DataFrame:
    """Home edge for every team-season (neutral-site games excluded)."""
    split = summarize(df[df["location"] != "neutral"], ["season", "team", "location"])
    wide = split.pivot(index=["season", "team"], columns="location", values="net")
    wide["edge"] = wide["home"] - wide["away"]
    return wide.rename(columns={"home": "home_net", "away": "away_net"}).reset_index()


def league_context(edges: pd.DataFrame, team: str = LAC) -> pd.DataFrame:
    """Per season: league distribution of home edges and where `team` ranks."""
    g = edges.groupby("season")["edge"]
    ctx = pd.DataFrame(
        {
            "league_mean": g.mean(),
            "league_p25": g.quantile(0.25),
            "league_p75": g.quantile(0.75),
            "league_min": g.min(),
            "league_max": g.max(),
        }
    )
    ranked = edges.assign(rank=edges.groupby("season")["edge"].rank(ascending=False))
    mine = ranked[ranked["team"] == team].set_index("season")
    ctx["edge"] = mine["edge"]
    ctx["home_net"] = mine["home_net"]
    ctx["away_net"] = mine["away_net"]
    ctx["rank"] = mine["rank"].astype(int)
    ctx["excess"] = ctx["edge"] - ctx["league_mean"]
    ctx["arena"] = [lac_home_arena(s) for s in ctx.index]
    return ctx.reset_index()


def _net(rows: np.ndarray) -> float:
    """Net rating from an array of [pts, opp_pts, possessions] rows."""
    pts, opp, poss = rows.sum(axis=0)
    return 100 * (pts - opp) / poss


def bootstrap_edge(
    team_games: pd.DataFrame, *, n: int = 4000, seed: int = 0, stratify: str | None = "season"
) -> np.ndarray:
    """Bootstrap distribution of home net minus away net, resampling games
    with replacement within home/away (and within season, when pooling)."""
    rng = np.random.default_rng(seed)
    cols = ["pts", "opp_pts", "possessions"]
    groups = [team_games] if stratify is None else [g for _, g in team_games.groupby(stratify)]
    home = [g.loc[g["location"] == "home", cols].to_numpy(float) for g in groups]
    away = [g.loc[g["location"] == "away", cols].to_numpy(float) for g in groups]

    def resample(parts: list[np.ndarray]) -> np.ndarray:
        # (n, games, 3) -> per-draw totals (n, 3)
        totals = np.zeros((n, 3))
        for arr in parts:
            idx = rng.integers(0, len(arr), size=(n, len(arr)))
            totals += arr[idx].sum(axis=1)
        return totals

    h, a = resample(home), resample(away)
    return 100 * ((h[:, 0] - h[:, 1]) / h[:, 2] - (a[:, 0] - a[:, 1]) / a[:, 2])


def _window_summary(team_games: pd.DataFrame, league_mean: pd.Series, n: int, seed: int):
    """Pooled home edge for one team over a set of seasons, its excess over the
    league average for those seasons, and bootstrap draws of that excess."""
    seasons = sorted(team_games["season"].unique())
    rows = team_games[["location", "pts", "opp_pts", "possessions"]].to_numpy()
    home = rows[rows[:, 0] == "home"][:, 1:].astype(float)
    away = rows[rows[:, 0] == "away"][:, 1:].astype(float)
    edge = _net(home) - _net(away)
    league = league_mean[seasons].mean()
    dist = bootstrap_edge(team_games, n=n, seed=seed) - league
    summary = {
        "seasons": seasons,
        "home_games": len(home),
        "edge": edge,
        "league_edge": league,
        "excess": edge - league,
        "ci": tuple(np.percentile(dist, [2.5, 97.5])),
    }
    return summary, dist


def compare_windows(
    df: pd.DataFrame, team: str, windows: dict[str, list[str]], *, n: int = 4000, seed: int = 0
) -> dict:
    """Excess home edge for `team` in each window of seasons, and the change from
    the first window to the last.

    Excess = team's pooled home edge minus the average league home edge over the
    same seasons, so league-wide swings cancel out: in effect a difference-in-
    differences against the rest of the league. The interval reflects game-to-game
    noise in the team's results; league means over ~1,200 games a season are
    treated as fixed.
    """
    df = df[df["location"] != "neutral"]
    league_mean = home_edges(df).groupby("season")["edge"].mean()
    mine = df[df["team"] == team]

    out: dict = {"eras": {}}
    draws = {}
    for label, seasons in windows.items():
        games = mine[mine["season"].isin(seasons)]
        out["eras"][label], draws[label] = _window_summary(games, league_mean, n, seed)
    if len(draws) >= 2:
        first, last = list(windows)[0], list(windows)[-1]
        diff = draws[last] - draws[first]
        out["change"] = {
            "from": first,
            "to": last,
            "delta": out["eras"][last]["excess"] - out["eras"][first]["excess"],
            "ci": tuple(np.percentile(diff, [2.5, 97.5])),
            "p_increase": float((diff > 0).mean()),
            "draws": diff,
        }
    return out


def era_comparison(
    df: pd.DataFrame, *, team: str = LAC, exclude_seasons: tuple[str, ...] = (), n: int = 4000
) -> dict:
    """The Clippers' shared-arena seasons vs. their Intuit Dome seasons."""
    seasons = sorted(set(df["season"]) - set(exclude_seasons))
    windows: dict[str, list[str]] = {SHARED_ARENA: [], INTUIT_DOME: []}
    for season in seasons:
        windows[lac_home_arena(season)].append(season)
    return compare_windows(df[df["season"].isin(seasons)], team, windows, n=n)


def move_windows(
    move_year: int,
    seasons: list[str],
    *,
    before: int = 3,
    after: int = 2,
    skip: tuple[str, ...] = NO_FAN_SEASONS,
) -> tuple[list[str], list[str]] | None:
    """The `before` seasons just before a move and the first `after` seasons in the
    new building, skipping no-fan seasons. None if the data doesn't cover both."""
    usable = sorted(s for s in seasons if s not in skip)
    pre = [s for s in usable if season_start_year(s) < move_year][-before:]
    post = [s for s in usable if season_start_year(s) >= move_year][:after]
    if len(pre) < before or len(post) < after:
        return None
    return pre, post


def arena_moves(df: pd.DataFrame, *, n: int = 4000, **window_kw) -> pd.DataFrame:
    """Change in excess home edge for every team that opened a new arena."""
    seasons = sorted(df["season"].unique())
    rows = []
    for team, (year, old, new) in ARENA_MOVES.items():
        win = move_windows(year, seasons, **window_kw)
        if win is None:
            continue
        res = compare_windows(df, team, {old: win[0], new: win[1]}, n=n)
        ch, b, a = res["change"], res["eras"][old], res["eras"][new]
        rows.append(
            {
                "team": team, "old_arena": old, "new_arena": new,
                "first_new_season": season_label(year),
                "before_seasons": f"{win[0][0]} to {win[0][-1]}",
                "after_seasons": f"{win[1][0]} to {win[1][-1]}",
                "before_excess": b["excess"], "after_excess": a["excess"],
                "delta": ch["delta"], "ci_low": ch["ci"][0], "ci_high": ch["ci"][1],
                "p_increase": ch["p_increase"],
            }
        )  # fmt: skip
    return pd.DataFrame(rows)


def placebo_changes(
    df: pd.DataFrame, *, before: int = 3, after: int = 2, skip: tuple[str, ...] = NO_FAN_SEASONS
) -> pd.DataFrame:
    """The same before/after change for every team at every possible 'fake move'
    season where nothing happened: how much a team's home edge moves between two
    windows by chance alone. Windows that span a real arena move are left out."""
    df = df[df["location"] != "neutral"]
    league_mean = home_edges(df).groupby("season")["edge"].mean()
    sums = df.groupby(["team", "season", "location"])[["pts", "opp_pts", "possessions"]].sum()
    seasons = sorted(df["season"].unique())

    def excess(team: str, window: list[str]) -> float:
        w = sums.loc[team].loc[window].groupby("location").sum()
        net = 100 * (w["pts"] - w["opp_pts"]) / w["possessions"]
        return net["home"] - net["away"] - league_mean[window].mean()

    rows = []
    for split in range(season_start_year(seasons[0]) + 1, season_start_year(seasons[-1]) + 1):
        win = move_windows(split, seasons, before=before, after=after, skip=skip)
        # A skipped season can't be a move season; its windows would repeat the next one's.
        if win is None or season_label(split) in skip:
            continue
        span = range(season_start_year(win[0][0]) + 1, season_start_year(win[1][-1]) + 1)
        for team in sums.index.get_level_values("team").unique():
            if team in ARENA_MOVES and ARENA_MOVES[team][0] in span:
                continue
            rows.append(
                {
                    "team": team,
                    "split_season": season_label(split),
                    "delta": excess(team, win[1]) - excess(team, win[0]),
                }
            )
    return pd.DataFrame(rows)


def visitor_free_throws(df: pd.DataFrame) -> pd.DataFrame:
    """How visitors shoot free throws in each arena, against their own FT% in
    their other games that season. `diff` is in percentage points; negative means
    visitors shot worse there than usual. `rank` 1 = toughest arena that season."""
    df = df[df["location"] != "neutral"]
    totals = df.groupby(["season", "team"])[["ftm", "fta"]].sum()
    visits = df[df["location"] == "away"].join(totals, on=["season", "team"], rsuffix="_season")
    # The visitor's FT% in all its other games, so a game isn't part of its own baseline.
    rest_pct = (visits["ftm_season"] - visits["ftm"]) / (visits["fta_season"] - visits["fta"])
    visits = visits.assign(expected=rest_pct * visits["fta"])
    out = (
        visits.groupby(["season", "opponent"])[["ftm", "fta", "expected"]]
        .sum()
        .rename_axis(["season", "arena_team"])
        .reset_index()
    )
    out["ft_pct"] = out["ftm"] / out["fta"]
    out["diff"] = 100 * (out["ftm"] - out["expected"]) / out["fta"]
    out["rank"] = out.groupby("season")["diff"].rank(method="min").astype(int)
    return out
