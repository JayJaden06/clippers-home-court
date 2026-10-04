"""Streamlit dashboard: did Intuit Dome change the Clippers' home-court advantage?

streamlit run dashboard/app.py
DATA_URI=gs://my-bucket GCS_ANON=1 streamlit run dashboard/app.py
"""

from __future__ import annotations

import json

import altair as alt
import fsspec
import pandas as pd
import streamlit as st

from clippers_home_court import LAC, analysis, storage
from clippers_home_court.seasons import INTUIT_DOME, SHARED_ARENA

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


df, report = load()
if df.empty:
    st.error("No data found. Run `python -m clippers_home_court.job` first.")
    st.stop()

# The toggle lives in the Details section at the bottom; read its state up here.
exclude = LIMITED_FAN_SEASONS if st.session_state.get("exclude_limited") else ()
result = compare(df, exclude)
eras, change = result["eras"], result["change"]
old, new = eras[SHARED_ARENA], eras[INTUIT_DOME]
data = df[~df["season"].isin(exclude)]
ctx = analysis.league_context(analysis.home_edges(data))

# ---- The answer ------------------------------------------------------------------------------
st.title("Did Intuit Dome give the Clippers a bigger home-court advantage?")
verdict = "Very likely, yes." if change["p_increase"] >= 0.9 else "Possibly."
st.markdown(
    f"**{verdict}** At their old shared arena the Clippers got *less* of a home boost "
    f"than the typical NBA team. Since moving to Intuit Dome they get *more*: about "
    f"**{change['delta']:.1f} points per 100 possessions** more than before. "
    f"In {change['p_increase']:.0%} of 4,000 simulations the improvement holds up, "
    f"but it's only two seasons so far."
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
    "Each dot is the Clippers' home advantage that season. The gray line is the league average. "
    "The number is their rank out of 30 teams."
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
        "It should firm up as the 2026-27 season adds games.\n"
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
        f"{len(df):,} team-game rows across {df['season'].nunique()} seasons · "
        f"{rejected} games rejected by validation"
    )
    st.json(report, expanded=False)

st.caption("Data: stats.nba.com via nba_api. Source: github.com/JayJaden06/clippers-home-court")
