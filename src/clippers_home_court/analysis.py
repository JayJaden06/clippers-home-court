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
from .seasons import SHARED_ARENA, lac_home_arena

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


def era_comparison(
    df: pd.DataFrame, *, team: str = LAC, exclude_seasons: tuple[str, ...] = (), n: int = 4000
) -> dict:
    """Pooled excess home edge in each arena era, and the change between them.

    Excess = team's pooled home edge minus the average league home edge over
    the same seasons. The interval reflects game-to-game noise in the team's
    results; league means over ~1,200 games a season are treated as fixed.
    """
    df = with_era(df[~df["season"].isin(exclude_seasons) & (df["location"] != "neutral")])
    ctx = league_context(home_edges(df), team).set_index("season")
    mine = df[df["team"] == team]

    out: dict = {"eras": {}}
    draws = {}
    for era, games in mine.groupby("era"):
        seasons = sorted(games["season"].unique())
        rows = games[["location", "pts", "opp_pts", "possessions"]].to_numpy()
        home = rows[rows[:, 0] == "home"][:, 1:].astype(float)
        away = rows[rows[:, 0] == "away"][:, 1:].astype(float)
        edge = _net(home) - _net(away)
        league = ctx.loc[seasons, "league_mean"].mean()
        dist = bootstrap_edge(games, n=n) - league
        draws[era] = dist
        out["eras"][era] = {
            "seasons": seasons,
            "home_games": len(home),
            "edge": edge,
            "league_edge": league,
            "excess": edge - league,
            "ci": tuple(np.percentile(dist, [2.5, 97.5])),
        }
    if len(draws) == 2:
        (old, d_old), (new, d_new) = sorted(draws.items(), key=lambda kv: kv[0] != SHARED_ARENA)
        diff = d_new - d_old
        out["change"] = {
            "from": old,
            "to": new,
            "delta": out["eras"][new]["excess"] - out["eras"][old]["excess"],
            "ci": tuple(np.percentile(diff, [2.5, 97.5])),
            "p_increase": float((diff > 0).mean()),
            "draws": diff,
        }
    return out
