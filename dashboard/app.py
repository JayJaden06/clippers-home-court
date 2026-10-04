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

# Validated categorical slots (light, dark); see the README's design notes.
DARK = getattr(getattr(st.context, "theme", None), "type", "light") == "dark"
PALETTE = {
    SHARED_ARENA: "#d95926" if DARK else "#eb6834",
    INTUIT_DOME: "#3987e5" if DARK else "#2a78d6",
    "Home": "#199e70" if DARK else "#1baf7a",
    "Road": "#9085e9" if DARK else "#4a3aa7",
    "league": "#5f5e5a" if DARK else "#c3c2b7",
    "ink": "#c3c2b7" if DARK else "#52514e",
}
ARENA_SCALE = alt.Scale(
    domain=[SHARED_ARENA, INTUIT_DOME], range=[PALETTE[SHARED_ARENA], PALETTE[INTUIT_DOME]]
)


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


@st.cache_data(show_spinner="Bootstrapping…")
def compare(df: pd.DataFrame, exclude: tuple[str, ...]) -> dict:
    return analysis.era_comparison(df, exclude_seasons=exclude, n=4000)


df, report = load()
if df.empty:
    st.error("No data found. Run `python -m clippers_home_court.job` first.")
    st.stop()

# ---- Header & controls -----------------------------------------------------------------------
st.title("Did Intuit Dome change the Clippers' home-court advantage?")
st.caption(
    "Home edge = net rating at home − net rating on the road (points per 100 possessions). "
    "The roster is the same in both, so what's left is the building: crowd, travel, "
    "familiarity. Each season is compared with the league-average edge that year."
)
exclude_limited = st.toggle(
    "Exclude 2019-20 and 2020-21 (Orlando bubble and limited-fan seasons)", value=False
)
exclude = LIMITED_FAN_SEASONS if exclude_limited else ()

result = compare(df, exclude)
eras, change = result["eras"], result["change"]

# ---- Headline numbers ------------------------------------------------------------------------
c1, c2, c3 = st.columns(3)
for col, era in ((c1, SHARED_ARENA), (c2, INTUIT_DOME)):
    e = eras[era]
    col.metric(
        f"{era} · {e['seasons'][0]} to {e['seasons'][-1]}",
        f"{e['excess']:+.1f}",
        help=f"Clippers' home edge {e['edge']:+.1f} vs. league {e['league_edge']:+.1f}, "
        f"pooled over {e['home_games']} home games. 95% CI {e['ci'][0]:+.1f} to {e['ci'][1]:+.1f}.",
    )
    col.caption(f"Edge vs. league average, pts/100. 95% CI {e['ci'][0]:+.1f} to {e['ci'][1]:+.1f}")
c3.metric("Change after the move", f"{change['delta']:+.1f}")
c3.caption(
    f"95% CI {change['ci'][0]:+.1f} to {change['ci'][1]:+.1f} · "
    f"{change['p_increase']:.0%} of bootstrap draws show an increase"
)

# ---- Season-by-season ------------------------------------------------------------------------
data = df[~df["season"].isin(exclude)]
ctx = analysis.league_context(analysis.home_edges(data))
ctx["Clippers home edge"] = ctx["edge"]

st.subheader("Clippers' home edge by season, against the league")
st.caption("Gray bar: middle half of the league (25th to 75th percentile). Tick: league average.")
base = alt.Chart(ctx).encode(x=alt.X("season:O", title=None, axis=alt.Axis(labelAngle=0)))
tooltip = [
    alt.Tooltip("season:N", title="Season"),
    alt.Tooltip("arena:N", title="Home arena"),
    alt.Tooltip("edge:Q", title="LAC home edge", format="+.1f"),
    alt.Tooltip("home_net:Q", title="LAC home net rtg", format="+.1f"),
    alt.Tooltip("away_net:Q", title="LAC road net rtg", format="+.1f"),
    alt.Tooltip("league_mean:Q", title="League avg edge", format="+.1f"),
    alt.Tooltip("rank:Q", title="Rank of 30"),
]
iqr = base.mark_bar(size=22, cornerRadius=4, color=PALETTE["league"], opacity=0.6).encode(
    y=alt.Y("league_p25:Q", title="Home edge (pts/100)"), y2="league_p75:Q", tooltip=tooltip
)
mean = base.mark_tick(thickness=2, size=22, color=PALETTE["ink"]).encode(
    y="league_mean:Q", tooltip=tooltip
)
dots = base.mark_circle(size=140, opacity=1, stroke="white", strokeWidth=2).encode(
    y="edge:Q",
    color=alt.Color("arena:N", scale=ARENA_SCALE, legend=alt.Legend(title=None, orient="top")),
    tooltip=tooltip,
)
rank_labels = base.mark_text(dx=17, align="left", fontSize=11, color=PALETTE["ink"]).encode(
    y="edge:Q", text=alt.Text("rank:Q", format="d")
)
zero = (
    alt.Chart(pd.DataFrame({"y": [0]}))
    .mark_rule(color=PALETTE["ink"], strokeWidth=1)
    .encode(y="y:Q")
)
st.altair_chart((zero + iqr + mean + dots + rank_labels).properties(height=360), width="stretch")
st.caption("Number beside each dot: Clippers' rank among 30 teams in home edge that season.")

left, right = st.columns(2)

with left:
    st.subheader("Net rating at home and on the road")
    long = ctx.melt(
        id_vars=["season", "arena"], value_vars=["home_net", "away_net"], value_name="net"
    )
    long["split"] = long["variable"].map({"home_net": "Home", "away_net": "Road"})
    color = alt.Color(
        "split:N",
        scale=alt.Scale(domain=["Home", "Road"], range=[PALETTE["Home"], PALETTE["Road"]]),
        legend=alt.Legend(title=None, orient="top"),
    )
    lines = alt.Chart(long).encode(
        x=alt.X("season:O", title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("net:Q", title="Net rating (pts/100)"),
        color=color,
        tooltip=[
            alt.Tooltip("season:N", title="Season"),
            alt.Tooltip("split:N", title="Split"),
            alt.Tooltip("net:Q", title="Net rating", format="+.1f"),
        ],
    )
    st.altair_chart(
        (lines.mark_line(strokeWidth=2) + lines.mark_circle(size=80, opacity=1)).properties(
            height=300
        ),
        width="stretch",
    )
    st.caption(
        "The gap between the lines is the home edge. 2023-24 is the only season "
        "the Clippers were better on the road than at home."
    )

with right:
    st.subheader("How sure can we be?")
    hist = pd.DataFrame({"delta": change["draws"]})
    bars = (
        alt.Chart(hist)
        .mark_bar(color=PALETTE[INTUIT_DOME], cornerRadiusTopLeft=2, cornerRadiusTopRight=2)
        .encode(
            x=alt.X("delta:Q", bin=alt.Bin(step=0.75), title="Change in edge vs. league (pts/100)"),
            y=alt.Y("count():Q", title="Bootstrap draws"),
            tooltip=[alt.Tooltip("delta:Q", bin=alt.Bin(step=0.75), title="Change"), "count():Q"],
        )
    )
    zero_v = (
        alt.Chart(pd.DataFrame({"x": [0]}))
        .mark_rule(color=PALETTE["ink"], strokeDash=[4, 3])
        .encode(x="x:Q")
    )
    st.altair_chart((bars + zero_v).properties(height=300), width="stretch")
    st.caption(
        f"Resampling the Clippers' games 4,000 times: {change['p_increase']:.0%} of draws "
        "land right of zero. Two seasons is a small sample, so the interval is wide."
    )

# ---- Where the edge comes from ---------------------------------------------------------------
st.subheader("Where the edge comes from: the four factors")
lac = analysis.with_era(data[(data["team"] == LAC) & (data["location"] != "neutral")])
ff = analysis.summarize(lac, ["era", "location"]).set_index(["era", "location"])
cols = {
    "ortg": "Off. rating",
    "drtg": "Def. rating",
    "efg": "eFG%",
    "opp_efg": "Opp eFG%",
    "tov_pct": "TOV%",
    "opp_tov_pct": "Opp TOV%",
    "orb_pct": "ORB%",
    "drb_pct": "DRB%",
    "ft_rate": "FT rate",
    "opp_ft_rate": "Opp FT rate",
}
pct = [c for c in cols if c not in ("ortg", "drtg")]
edge = (ff.xs("home", level="location") - ff.xs("away", level="location"))[list(cols)]
edge = edge.reindex([SHARED_ARENA, INTUIT_DOME])
shown = edge.copy()
shown[pct] = shown[pct] * 100
st.dataframe(
    shown.rename(columns=cols).style.format("{:+.1f}"),
    width="stretch",
)
st.caption(
    "Home minus road, per era. Ratings in pts/100; the rest in percentage points. "
    "For defense and opponent columns, negative is good for the Clippers."
)

# ---- Data & pipeline -------------------------------------------------------------------------
with st.expander("Season table"):
    st.dataframe(
        ctx[["season", "arena", "edge", "home_net", "away_net", "league_mean", "excess", "rank"]]
        .rename(
            columns={
                "edge": "LAC edge",
                "home_net": "Home net",
                "away_net": "Road net",
                "league_mean": "League avg edge",
                "excess": "Edge vs. league",
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
        f"{rejected} games rejected by validation · "
        f"{int((df['location'] == 'neutral').sum() / 2)} neutral-site games excluded"
    )
    st.json(report, expanded=False)

st.caption(
    "Data: stats.nba.com via nba_api, regular season only, validated with Pydantic and "
    "refreshed daily by a Cloud Run job. Source: github.com/JayJaden06/clippers-home-court"
)
