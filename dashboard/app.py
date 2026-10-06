"""Streamlit dashboard: did Intuit Dome change the Clippers' home-court advantage?

streamlit run dashboard/app.py
DATA_URI=gs://my-bucket GCS_ANON=1 streamlit run dashboard/app.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import altair as alt
import fsspec
import pandas as pd
import streamlit as st

# Import the package from this checkout, not a previously installed copy: Streamlit Cloud
# only reinstalls requirements when requirements.txt changes, so an installed copy can lag.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clippers_home_court import LAC, analysis, storage  # noqa: E402
from clippers_home_court.seasons import (  # noqa: E402
    ANALYSIS_FIRST_SEASON,
    INTUIT_DOME,
    SHARED_ARENA,
    season_label,
)

LIMITED_FAN_SEASONS = ("2019-20", "2020-21")

st.set_page_config(page_title="Clippers Home Court", page_icon="🏀", layout="wide")

# Validated categorical slots (light, dark).
DARK = getattr(getattr(st.context, "theme", None), "type", "light") == "dark"
PALETTE = {
    SHARED_ARENA: "#d95926" if DARK else "#eb6834",
    INTUIT_DOME: "#3987e5" if DARK else "#2a78d6",
    "Home": "#199e70" if DARK else "#1baf7a",
    "Road": "#9085e9" if DARK else "#4a3aa7",
    "ink": "#c3c2b7" if DARK else "#52514e",
}
ARENA_SCALE = alt.Scale(
    domain=[SHARED_ARENA, INTUIT_DOME], range=[PALETTE[SHARED_ARENA], PALETTE[INTUIT_DOME]]
)
SEASON_AXIS = alt.X("season:O", title=None, axis=alt.Axis(labelAngle=0))


@st.cache_data(ttl=3600, show_spinner="Loading games…")
def load() -> tuple[pd.DataFrame, dict]:
    uri = storage.data_uri()
    df = storage.read_all(uri)
    try:
        fs, _ = fsspec.core.url_to_fs(uri, **storage._storage_options(uri))
        with fs.open(f"{uri}/exports/last_run.json") as f:
            report = json.load(f)
    except FileNotFoundError:
        report = {}
    return df, report


@st.cache_data(show_spinner="Crunching…")
def compare(df: pd.DataFrame, exclude: tuple[str, ...]) -> dict:
    return analysis.era_comparison(df, exclude_seasons=exclude, n=4000)


@st.cache_data(show_spinner="Comparing arena moves…")
def arena_moves(games: pd.DataFrame) -> pd.DataFrame:
    return analysis.arena_moves(games)


@st.cache_data
def placebo_changes(games: pd.DataFrame) -> pd.DataFrame:
    return analysis.placebo_changes(games)


@st.cache_data
def visitor_fts(games: pd.DataFrame) -> pd.DataFrame:
    return analysis.visitor_free_throws(games)


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


all_games, report = load()
if all_games.empty:
    st.error("No data found. Run `python -m clippers_home_court.job` first.")
    st.stop()
df = all_games[all_games["season"] >= season_label(ANALYSIS_FIRST_SEASON)]

# The toggle lives in the Details section at the bottom; read its state up here.
exclude = LIMITED_FAN_SEASONS if st.session_state.get("exclude_limited") else ()
result = compare(df, exclude)
eras, change = result["eras"], result["change"]
old, new = eras[SHARED_ARENA], eras[INTUIT_DOME]
data = df[~df["season"].isin(exclude)]
ctx = analysis.league_context(analysis.home_edges(data))

# ---- The answer ------------------------------------------------------------------------------
st.title("Did Intuit Dome give the Clippers a bigger home-court advantage?")
latest_season = df["season"].max()
lac_latest_games = int(((df["season"] == latest_season) & (df["team"] == LAC)).sum())
st.caption(
    f"Data through **{all_games['game_date'].max():%B %d, %Y}**, refreshed every morning."
    + (
        f" {latest_season} is in progress ({lac_latest_games} Clippers games so far)."
        if lac_latest_games < 82
        else ""
    )
)
tab_home, tab_wall, tab_moves = st.tabs(
    ["Home advantage", "The Wall: free throws", "Other new arenas"]
)

with tab_home:
    verdict = "Very likely, yes." if change["p_increase"] >= 0.9 else "Possibly."
    st.markdown(
        f"**{verdict}** At their old shared arena the Clippers got *less* of a home boost "
        f"than the typical NBA team. Since moving to Intuit Dome they get *more*: about "
        f"**{change['delta']:.1f} points per 100 possessions** more than before. "
        f"In {change['p_increase']:.0%} of 4,000 resamples of the games the improvement "
        f"holds up, but that's only {len(new['seasons'])} seasons of games so far."
    )

    c1, c2, c3 = st.columns(3)
    c1.metric(
        f"Crypto.com Arena ({old['seasons'][0]} to {old['seasons'][-1]})", f"{old['excess']:+.1f}"
    )
    c1.caption("Home advantage vs. the average NBA team")
    c2.metric(f"Intuit Dome ({new['seasons'][0]} to {new['seasons'][-1]})", f"{new['excess']:+.1f}")
    c2.caption("Home advantage vs. the average NBA team")
    c3.metric("Change after the move", f"{change['delta']:+.1f}")
    c3.caption("Points per 100 possessions")

    with st.expander('What does "home advantage" mean here?'):
        st.markdown(
            "**Home advantage** = how much better a team does at home than on the road, measured "
            "by point margin per 100 possessions. It's the same players in both, so the difference "
            "comes from the building: the crowd, not traveling, sleeping in your own bed.\n\n"
            "Every team plays better at home. The league average is about +3 to +5 points per "
            "100 possessions. The numbers above show how far the Clippers sit **above or below** "
            "that average."
        )

    # ---- Chart 1: season by season ---------------------------------------------------------------
    st.subheader("Season by season: from 27th in the league to 1st")
    st.caption(
        "Each dot is the Clippers' home advantage that season. The gray line is the league "
        "average. The number is their rank out of 30 teams."
    )
    ctx["rank_label"] = "#" + ctx["rank"].astype(str)
    base = alt.Chart(ctx).encode(x=SEASON_AXIS)
    tooltip = [
        alt.Tooltip("season:N", title="Season"),
        alt.Tooltip("arena:N", title="Home arena"),
        alt.Tooltip("edge:Q", title="Clippers home advantage", format="+.1f"),
        alt.Tooltip("league_mean:Q", title="League average", format="+.1f"),
        alt.Tooltip("rank:Q", title="Rank of 30"),
    ]
    league = base.mark_line(color=PALETTE["ink"], strokeWidth=2, strokeDash=[5, 4]).encode(
        y=alt.Y("league_mean:Q", title="Home advantage (pts per 100 possessions)"), tooltip=tooltip
    )
    dots = base.mark_circle(size=180, opacity=1, stroke="white", strokeWidth=2).encode(
        y="edge:Q",
        color=alt.Color("arena:N", scale=ARENA_SCALE, legend=alt.Legend(title=None, orient="top")),
        tooltip=tooltip,
    )
    ranks = base.mark_text(dx=18, align="left", fontSize=12, color=PALETTE["ink"]).encode(
        y="edge:Q", text="rank_label:N"
    )
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=PALETTE["ink"], opacity=0.4)
    st.altair_chart(
        (zero.encode(y="y:Q") + league + dots + ranks).properties(height=340), width="stretch"
    )

    left, right = st.columns(2)

    # ---- Chart 2: home vs road -------------------------------------------------------------------
    with left:
        st.subheader("Home vs. road")
        st.caption(
            "Point margin per 100 possessions. The gap between the lines is the home advantage. "
            "In 2023-24 they were actually better on the road."
        )
        long = ctx.melt(id_vars=["season"], value_vars=["home_net", "away_net"], value_name="net")
        long["split"] = long["variable"].map({"home_net": "Home", "away_net": "Road"})
        lines = alt.Chart(long).encode(
            x=SEASON_AXIS,
            y=alt.Y("net:Q", title="Point margin per 100 possessions"),
            color=alt.Color(
                "split:N",
                scale=alt.Scale(domain=["Home", "Road"], range=[PALETTE["Home"], PALETTE["Road"]]),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=[
                alt.Tooltip("season:N", title="Season"),
                alt.Tooltip("split:N", title="Where"),
                alt.Tooltip("net:Q", title="Point margin / 100", format="+.1f"),
            ],
        )
        st.altair_chart(
            (lines.mark_line(strokeWidth=2) + lines.mark_circle(size=80, opacity=1)).properties(
                height=300
            ),
            width="stretch",
        )

    # ---- Why: defense ----------------------------------------------------------------------------
    with right:
        st.subheader("Why? Opponents shoot worse there")
        lac = analysis.with_era(data[(data["team"] == LAC) & (data["location"] != "neutral")])
        split = analysis.summarize(lac, ["era", "location"]).set_index(["era", "location"])
        drop = split.xs("away", level="location") - split.xs("home", level="location")
        why = pd.DataFrame(
            {
                "arena": [SHARED_ARENA, INTUIT_DOME],
                "drop": [100 * drop.loc[a, "opp_efg"] for a in (SHARED_ARENA, INTUIT_DOME)],
            }
        )
        bars = (
            alt.Chart(why)
            .mark_bar(size=48, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("arena:N", title=None, sort=[SHARED_ARENA, INTUIT_DOME],
                        axis=alt.Axis(labelAngle=0)),
                y=alt.Y("drop:Q", title="Drop in opponent shooting (pct. points)"),
                color=alt.Color("arena:N", scale=ARENA_SCALE, legend=None),
                tooltip=[
                    alt.Tooltip("arena:N", title="Arena"),
                    alt.Tooltip("drop:Q", title="Opponent shooting drop", format=".1f"),
                ],
            )
        )  # fmt: skip
        labels = bars.mark_text(dy=-10, fontSize=13).encode(
            text=alt.Text("drop:Q", format=".1f"), color=alt.value(PALETTE["ink"])
        )
        st.altair_chart((bars + labels).properties(height=300), width="stretch")
        st.caption(
            "How much worse opponents shoot (effective FG%) against the Clippers at home than "
            f"on the road: {why['drop'].iloc[0]:.1f} points at the old arena, "
            f"{why['drop'].iloc[1]:.1f} at Intuit Dome. Most of the new advantage is defense."
        )

    # ---- Details ---------------------------------------------------------------------------------
    st.divider()
    st.subheader("Details")
    st.toggle(
        "Leave out 2019-20 and 2020-21 (Orlando bubble and empty-arena seasons)",
        key="exclude_limited",
    )

    with st.expander("Method and confidence"):
        lo, hi = change["ci"]
        st.markdown(
            f"- **Data:** every regular-season NBA game since 2018-19 ({len(df) // 2:,} games), "
            "pulled from stats.nba.com and checked with Pydantic before it's stored. Games at "
            "neutral sites (bubble, Paris, Mexico City, NBA Cup in Vegas) are left out.\n"
            "- **Home advantage** = net rating at home − net rating on the road, compared with "
            "the league average for the same season.\n"
            f"- **Confidence:** I resampled the Clippers' games 4,000 times. The change came out "
            f"positive {change['p_increase']:.0%} of the time. The 95% range is {lo:+.1f} to "
            f"{hi:+.1f}, which still touches zero, so the result isn't conclusive yet. "
            "The data refreshes daily, so this firms up as more games are played.\n"
            "- **Not controlled for:** roster changes, rest, schedule."
        )

    with st.expander("Season table"):
        st.dataframe(
            ctx[["season", "arena", "home_net", "away_net", "edge", "league_mean", "rank"]]
            .rename(
                columns={
                    "home_net": "Home margin",
                    "away_net": "Road margin",
                    "edge": "Home advantage",
                    "league_mean": "League avg",
                    "rank": "Rank",
                }
            )
            .style.format(precision=1),
            hide_index=True,
            width="stretch",
        )

    with st.expander("Pipeline status"):
        seasons = report.get("seasons", {})
        rejected = sum(len(s.get("rejected", [])) for s in seasons.values())
        st.write(
            f"Last ingest finished **{report.get('finished_at', 'unknown')}** · "
            f"{len(all_games):,} team-game rows across {all_games['season'].nunique()} seasons · "
            f"{rejected} games rejected by validation"
        )
        st.json(report, expanded=False)

# ---- The Wall: free throws -------------------------------------------------------------------
with tab_wall:
    ft = visitor_fts(all_games)
    lac_ft = ft[ft["arena_team"] == LAC].assign(
        arena=lambda d: d["season"].map(lambda s: INTUIT_DOME if s >= "2024-25" else SHARED_ARENA)
    )
    lac_ft = lac_ft[lac_ft["season"] >= season_label(ANALYSIS_FIRST_SEASON)]

    def pooled(rows: pd.DataFrame) -> float:
        return 100 * (rows["ftm"].sum() - rows["expected"].sum()) / rows["fta"].sum()

    dome = lac_ft[lac_ft["arena"] == INTUIT_DOME]
    league_ft = ft[ft["season"] >= season_label(ANALYSIS_FIRST_SEASON)]
    # Binomial noise in one arena-season's FT% (visitors shoot ~78%), in pct. points.
    noise = 100 * (0.78 * 0.22 / league_ft["fta"].mean()) ** 0.5
    combined = pooled(dome)
    clear = combined <= -2 * noise / len(dome) ** 0.5
    by_season = "; ".join(
        f"{r.season}: **{r.diff:+.1f}** ({ordinal(r.rank)} of 30)" for r in dome.itertuples()
    )
    st.subheader("Does The Wall make opponents miss free throws?")
    st.markdown(
        f"**{'Possibly.' if clear else 'Not in a way that lasts.'}** The Wall is a 51-row "
        "section of Clippers fans behind one basket. Here is how visitors shot free throws at "
        "Intuit Dome compared with their own FT% everywhere else (negative = worse; rank 1 = "
        f"toughest arena that season). {by_season}. All seasons combined: "
        f"**{combined:+.1f}** points" + ("." if clear else ", within what luck alone produces.")
    )
    st.caption(
        "Each gray dot is one NBA arena that season. Its height is how visitors shot free "
        "throws there compared with their own FT% in all their other games. Below zero means "
        "visitors shot worse than usual. The number is the Clippers' arena rank (#1 = hardest "
        "place for visitors)."
    )
    others = (
        alt.Chart(league_ft[league_ft["arena_team"] != LAC])
        .mark_circle(size=45, color=PALETTE["ink"], opacity=0.35)
        .encode(
            x=SEASON_AXIS,
            y=alt.Y("diff:Q", title="Visitors' FT% vs. their usual (pct. points)"),
            tooltip=[
                alt.Tooltip("season:N", title="Season"),
                alt.Tooltip("arena_team:N", title="Home team"),
                alt.Tooltip("diff:Q", title="Visitors vs. usual", format="+.1f"),
            ],
        )
    )
    lac_base = alt.Chart(lac_ft.assign(rank_label="#" + lac_ft["rank"].astype(str))).encode(
        x=SEASON_AXIS, y="diff:Q"
    )
    lac_dots = lac_base.mark_circle(size=180, opacity=1, stroke="white", strokeWidth=2).encode(
        color=alt.Color("arena:N", scale=ARENA_SCALE, legend=alt.Legend(title=None, orient="top")),
        tooltip=[
            alt.Tooltip("season:N", title="Season"),
            alt.Tooltip("arena:N", title="Clippers arena"),
            alt.Tooltip("ft_pct:Q", title="Visitors' FT%", format=".1%"),
            alt.Tooltip("diff:Q", title="Visitors vs. usual", format="+.1f"),
            alt.Tooltip("rank:Q", title="Rank (1 = hardest)"),
            alt.Tooltip("fta:Q", title="Visitor FTA"),
        ],
    )
    lac_ranks = lac_base.mark_text(dx=18, align="left", fontSize=12, color=PALETTE["ink"]).encode(
        text="rank_label:N"
    )
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=PALETTE["ink"], opacity=0.4)
    st.altair_chart(
        (zero.encode(y="y:Q") + others + lac_dots + lac_ranks).properties(height=360),
        width="stretch",
    )
    st.markdown(
        f"**Why it bounces around:** visitors take about {league_ft['fta'].mean():.0f} free "
        f"throws in an arena per season. At that sample size, luck alone moves an arena's "
        f"number by about ±{noise:.1f} points in a typical season, about the size of the "
        "swings in the chart. One season can look like a Wall effect by luck alone, so the "
        "seasons together are what count."
    )
    with st.expander("Why not compare the two baskets directly?"):
        st.markdown(
            "That's the sharper test: free throws at the Wall end vs. the other end. But the "
            "visiting team chooses which basket to attack in each half, so the Wall end "
            "changes from game to game. The public play-by-play data doesn't record which "
            "end a shot was at. Instead this measures the whole arena against every other "
            "arena, which includes the Wall's effect at one end.\n\n"
            "An early-season study ([Above the Break, Dec 2024]"
            "(https://abovethebreak.substack.com/p/ballmers-wall-is-the-intuit-dome)) looked "
            "at the first 12 home games and found a small effect it called largely "
            "indistinguishable from normal home-court variance. Two full seasons point the "
            "same way."
        )

# ---- Other new arenas ------------------------------------------------------------------------
with tab_moves:
    moves = arena_moves(all_games)
    placebo = placebo_changes(all_games)
    st.subheader("Do new arenas usually boost home advantage?")
    others_moved = moves[moves["team"] != LAC] if not moves.empty else moves
    if others_moved.empty or placebo.empty or LAC not in set(moves["team"]):
        st.info("Needs seasons back to 2013-14. Run `clippers-ingest` to backfill them.")
    else:
        lac_move = moves.set_index("team").loc[LAC]
        lo, hi = placebo["delta"].quantile([0.05, 0.95])
        share = (placebo["delta"] >= lac_move["delta"]).mean()
        inside = others_moved["delta"].between(lo, hi).sum()
        verdict = (
            "The Clippers' jump is unusual."
            if share <= 0.1
            else "The Clippers' jump is within the normal range."
        )
        st.markdown(
            f"**{verdict}** {len(others_moved)} other teams moved into newly built arenas in "
            "the same metro area during this period. Their home advantage changed by "
            + ", ".join(f"{r.team} {r.delta:+.1f}" for r in others_moved.itertuples())
            + f". The Clippers' change was **{lac_move['delta']:+.1f}**. "
            f"For teams that didn't move, a change at least that big happened "
            f"**{share:.0%}** of the time."
        )
        st.caption(
            "Each row compares a team's home advantage (vs. the league average) in the 3 "
            "seasons before its move with its first 2 seasons in the new building, skipping "
            "2020-21 (no fans). Lines show the 95% range. The gray band is where 90% of "
            "changes fall for teams that didn't move."
        )
        rows = moves.assign(
            label=moves["team"]
            + " · "
            + moves["new_arena"]
            + " ("
            + moves["first_new_season"]
            + ")",
            who=moves["team"].map(lambda t: "Clippers" if t == LAC else "Other teams"),
        ).sort_values("first_new_season")
        who = alt.Color(
            "who:N",
            scale=alt.Scale(
                domain=["Clippers", "Other teams"], range=[PALETTE[INTUIT_DOME], PALETTE["ink"]]
            ),
            legend=None,
        )
        y = alt.Y("label:N", title=None, sort=list(rows["label"]), axis=alt.Axis(labelLimit=320))
        tooltip = [
            alt.Tooltip("label:N", title="Move"),
            alt.Tooltip("old_arena:N", title="From"),
            alt.Tooltip("before_seasons:N", title="Before"),
            alt.Tooltip("after_seasons:N", title="After"),
            alt.Tooltip("before_excess:Q", title="Before (vs. league)", format="+.1f"),
            alt.Tooltip("after_excess:Q", title="After (vs. league)", format="+.1f"),
            alt.Tooltip("delta:Q", title="Change", format="+.1f"),
            alt.Tooltip("p_increase:Q", title="Resamples with an increase", format=".0%"),
        ]
        band = (
            alt.Chart(pd.DataFrame({"lo": [lo], "hi": [hi]}))
            .mark_rect(color=PALETTE["ink"], opacity=0.15)
            .encode(x="lo:Q", x2="hi:Q")
        )
        zero_x = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=PALETTE["ink"], opacity=0.5)
        base = alt.Chart(rows).encode(y=y, color=who, tooltip=tooltip)
        whiskers = base.mark_rule(strokeWidth=2).encode(
            x=alt.X("ci_low:Q", title="Change in home advantage (pts per 100 possessions)"),
            x2="ci_high:Q",
        )
        points = base.mark_circle(size=160, opacity=1, stroke="white", strokeWidth=2).encode(
            x="delta:Q"
        )
        st.altair_chart(
            (band + zero_x.encode(x="x:Q") + whiskers + points).properties(height=260),
            width="stretch",
        )
        st.markdown(
            f"**How to read it:** the gray band is the range you'd expect from chance. "
            f"{inside} of the {len(others_moved)} other moves land inside it. The Clippers' "
            f"dot is {'outside' if not lo <= lac_move['delta'] <= hi else 'inside'} it."
        )
        with st.expander("Method"):
            st.markdown(
                "- **Comparison:** for each team, home advantage minus the league average in "
                "the 3 seasons before the move, then the same for its first 2 seasons in the "
                "new arena. Subtracting the league average each season makes this a "
                "difference-in-differences against the rest of the league.\n"
                f"- **Chance baseline:** the same calculation for every team at every season "
                f"where nothing happened ({len(placebo):,} team-seasons). It shows how much "
                "home advantage moves between two windows by luck and roster churn alone.\n"
                "- **Why the Clippers' number differs from the first tab:** this tab uses "
                "the same 3-before/2-after window for every team, so the Clippers' before "
                f"window is {lac_move['before_seasons']} rather than 2018-19 onward.\n"
                "- **Left out:** the Nets' 2012 move to Brooklyn (a new city, not just a new "
                "building) and 2020-21 (no fans)."
            )
        st.dataframe(
            rows[
                ["team", "old_arena", "new_arena", "before_seasons", "after_seasons",
                 "before_excess", "after_excess", "delta", "ci_low", "ci_high"]
            ]
            .rename(
                columns={
                    "team": "Team", "old_arena": "From", "new_arena": "To",
                    "before_seasons": "Before", "after_seasons": "After",
                    "before_excess": "Before (vs. league)", "after_excess": "After (vs. league)",
                    "delta": "Change", "ci_low": "95% low", "ci_high": "95% high",
                }
            )
            .style.format(precision=1),
            hide_index=True,
            width="stretch",
        )  # fmt: skip

st.caption(
    "Data: stats.nba.com via nba_api (2018-19 on, with Basketball Reference as a fallback) "
    "and Basketball Reference (2013-14 to 2017-18), refreshed daily by a GitHub Actions job. "
    "Source: github.com/JayJaden06/clippers-home-court"
)
