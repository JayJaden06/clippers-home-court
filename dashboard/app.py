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
# Streamlit Cloud pulls new commits into the running process: app.py reruns, but modules
# imported on an earlier run stay cached in sys.modules with the old code. Drop them so
# every run imports the package as it is on disk (it's small and quick to import).
for _name in [m for m in sys.modules if m.split(".")[0] == "clippers_home_court"]:
    del sys.modules[_name]

from clippers_home_court import LAC, analysis, halves, storage  # noqa: E402
from clippers_home_court.seasons import (  # noqa: E402
    ANALYSIS_FIRST_SEASON,
    INTUIT_DOME,
    SHARED_ARENA,
    season_label,
)

LIMITED_FAN_SEASONS = ("2019-20", "2020-21")

st.set_page_config(page_title="Clippers Home Court", page_icon="🏀", layout="wide")

# ---- Theme -----------------------------------------------------------------------------------
# Validated categorical slots (light, dark); text always uses the ink tokens, never a series color.
DARK = getattr(getattr(st.context, "theme", None), "type", "light") == "dark"
PALETTE = {
    SHARED_ARENA: "#d95926" if DARK else "#eb6834",
    INTUIT_DOME: "#3987e5" if DARK else "#2a78d6",
    "Home": "#199e70" if DARK else "#1baf7a",
    "Road": "#9085e9" if DARK else "#4a3aa7",
    "ink": "#c3c2b7" if DARK else "#52514e",
}
INK = "#f2f1ea" if DARK else "#1f1e1c"
MUTED = "#a3a29a" if DARK else "#6b6a66"
SURFACE = "#1f1f1d" if DARK else "#f7f6f2"
LINE = "#3a3a37" if DARK else "#e4e2db"
ARENA_SCALE = alt.Scale(
    domain=[SHARED_ARENA, INTUIT_DOME], range=[PALETTE[SHARED_ARENA], PALETTE[INTUIT_DOME]]
)
HALF_SCALE = alt.Scale(domain=["1st half", "2nd half"], range=[PALETTE["Home"], PALETTE["Road"]])
SEASON_AXIS = alt.X("season:O", title=None, axis=alt.Axis(labelAngle=0))

st.markdown(
    f"""
<style>
.block-container {{ padding-top: 2.2rem; max-width: 1200px; }}
.hero-sub {{ color: {MUTED}; font-size: 1.05rem; margin: -0.4rem 0 1.2rem; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
          gap: 14px; margin: 0.4rem 0 1.6rem; }}
.card {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 16px;
         padding: 18px 20px 16px; }}
.card .q {{ color: {MUTED}; font-size: 0.92rem; line-height: 1.3; min-height: 2.4em; }}
.card .v {{ display: flex; align-items: baseline; gap: 10px; margin: 8px 0 4px; }}
.card .verdict {{ font-size: 1.9rem; font-weight: 750; color: {INK}; }}
.card .icon {{ font-size: 1.5rem; }}
.card .num {{ color: {INK}; font-weight: 650; font-size: 1.05rem; }}
.card .sub {{ color: {MUTED}; font-size: 0.86rem; line-height: 1.35; }}
.answer {{ border-left: 4px solid {PALETTE[INTUIT_DOME]}; background: {SURFACE};
           border-radius: 0 12px 12px 0; padding: 12px 18px; margin: 0.6rem 0 1.2rem;
           color: {INK}; font-size: 1.08rem; }}
.answer b {{ font-weight: 700; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
          gap: 12px; margin: 0.2rem 0 1rem; }}
.tile {{ border: 1px solid {LINE}; border-radius: 12px; padding: 12px 14px; }}
.tile .l {{ color: {MUTED}; font-size: 0.82rem; }}
.tile .n {{ color: {INK}; font-size: 1.7rem; font-weight: 700; line-height: 1.25; }}
.tile .s {{ color: {MUTED}; font-size: 0.8rem; }}
.stTabs [data-baseweb="tab"] p {{ font-size: 1.02rem; font-weight: 600; }}
.court svg {{ width: 100%; height: auto; display: block; }}
</style>
""",
    unsafe_allow_html=True,
)


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def answer(text: str) -> None:
    html(f'<div class="answer">{text}</div>')


def tiles(items: list[tuple[str, str, str]]) -> None:
    """A row of small stat tiles: (label, number, footnote)."""
    cells = "".join(
        f'<div class="tile"><div class="l">{label}</div><div class="n">{num}</div>'
        f'<div class="s">{foot}</div></div>'
        for label, num, foot in items
    )
    html(f'<div class="tiles">{cells}</div>')


def chart(c: alt.Chart, height: int) -> None:
    st.altair_chart(
        c.properties(height=height)
        .configure_view(stroke=None)
        .configure_axis(
            gridColor=LINE, domainColor=LINE, tickColor=LINE, labelColor=MUTED,
            titleColor=MUTED, labelFontSize=12, titleFontSize=12, titleFontWeight="normal",
        )
        .configure_legend(labelColor=INK, labelFontSize=13, symbolSize=120),
        width="stretch",
    )  # fmt: skip


# ---- Data ------------------------------------------------------------------------------------
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


@st.cache_data(ttl=3600)
def load_halves() -> pd.DataFrame:
    return halves.read(storage.data_uri())


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def arena_of(season: str) -> str:
    return INTUIT_DOME if season >= "2024-25" else SHARED_ARENA


all_games, report = load()
if all_games.empty:
    st.error("No data found. Run `python -m clippers_home_court.job` first.")
    st.stop()
df = all_games[all_games["season"] >= season_label(ANALYSIS_FIRST_SEASON)]

# The toggle lives in the Details section; read its state up here.
exclude = LIMITED_FAN_SEASONS if st.session_state.get("exclude_limited") else ()
result = compare(df, exclude)
eras, change = result["eras"], result["change"]
old, new = eras[SHARED_ARENA], eras[INTUIT_DOME]
data = df[~df["season"].isin(exclude)]
ctx = analysis.league_context(analysis.home_edges(data))
latest_season = df["season"].max()
lac_latest_games = int(((df["season"] == latest_season) & (df["team"] == LAC)).sum())
in_progress = lac_latest_games < 82

# Free throws: visitors at every arena, every season.
ft = visitor_fts(all_games)
ft = ft[ft["season"] >= season_label(ANALYSIS_FIRST_SEASON)]
lac_ft = ft[ft["arena_team"] == LAC].assign(arena=lambda d: d["season"].map(arena_of))
dome_ft = lac_ft[lac_ft["arena"] == INTUIT_DOME]
noise = 100 * (0.78 * 0.22 / ft["fta"].mean()) ** 0.5  # one arena-season, pct. points
wall_effect = 100 * (dome_ft["ftm"].sum() - dome_ft["expected"].sum()) / dome_ft["fta"].sum()
wall_real = wall_effect <= -2 * noise / len(dome_ft) ** 0.5

# Arena moves.
moves = arena_moves(all_games)
placebo = placebo_changes(all_games)
have_moves = not moves.empty and not placebo.empty and LAC in set(moves["team"])
if have_moves:
    lac_move = moves.set_index("team").loc[LAC]
    others_moved = moves[moves["team"] != LAC]
    share_bigger = float((placebo["delta"] >= lac_move["delta"]).mean())

# ---- Header + the three answers --------------------------------------------------------------
st.title("🏀 Clippers Home Court")
html(
    '<div class="hero-sub">In 2024 the Clippers left the arena they shared with the Lakers for '
    "their own building, Intuit Dome. Did it help? "
    f"Data through <b>{all_games['game_date'].max():%b %d, %Y}</b>, updated every morning.</div>"
)

shared_last = ctx[ctx["arena"] == SHARED_ARENA].iloc[-1]
dome_first = ctx[ctx["arena"] == INTUIT_DOME].iloc[0]
home_yes = change["p_increase"] >= 0.9
cards = [
    (
        "Do the Clippers get a bigger home-court boost at Intuit Dome?",
        "✅",
        "Yes" if home_yes else "Maybe",
        f"{ordinal(int(shared_last['rank']))} → {ordinal(int(dome_first['rank']))} in the NBA",
        f"From {ordinal(int(shared_last['rank']))} of 30 in their last season at the old arena "
        f"to {ordinal(int(dome_first['rank']))} in their first at Intuit Dome.",
    ),
    (
        "Does The Wall make visitors miss free throws?",
        "🤷",
        "Not really" if not wall_real else "A little",
        f"{wall_effect:+.1f} pts of FT%".replace("-", "−"),
        "Visitors shoot about as well at Intuit Dome as they do everywhere else.",
    ),
]
if have_moves:
    cards.append(
        (
            "Do new arenas usually give teams a boost like this?",
            "🏟️",
            "No",
            f"Only {share_bigger:.0%} of teams",
            "see a jump as big as the Clippers' by chance. Other new arenas barely moved.",
        )
    )
html(
    '<div class="cards">'
    + "".join(
        f'<div class="card"><div class="q">{q}</div><div class="v"><span class="icon">{i}'
        f'</span><span class="verdict">{v}</span></div><div class="num">{n}</div>'
        f'<div class="sub">{s}</div></div>'
        for q, i, v, n, s in cards
    )
    + "</div>"
)

tab_home, tab_wall, tab_games, tab_moves = st.tabs(
    ["🏠 Home advantage", "🧱 The Wall", "📅 Every home game", "🏟️ Other new arenas"]
)

# ---- Home advantage --------------------------------------------------------------------------
with tab_home:
    answer(
        f"<b>{'Yes.' if home_yes else 'Possibly.'}</b> At the shared arena the Clippers' home "
        "boost was average at best. At Intuit Dome it's one of the best in the league."
    )
    st.subheader("Where the Clippers' home court ranks in the NBA each season")
    st.caption("1 = the biggest home-court boost in the league. Hover a dot for details.")
    ranks = ctx.assign(
        label=lambda d: (
            "#"
            + d["rank"].astype(str)
            + d["season"].map(lambda s: " so far" if (s == latest_season and in_progress) else "")
        ),
        note=lambda d: d["season"].map(
            lambda s: "in progress" if (s == latest_season and in_progress) else "full season"
        ),
    )
    hover = alt.selection_point(on="pointerover", fields=["season"], empty=False, nearest=True)
    rbase = alt.Chart(ranks).encode(x=SEASON_AXIS)
    dome_band = (
        alt.Chart(ranks[ranks["arena"] == INTUIT_DOME])
        .mark_rect(color=PALETTE[INTUIT_DOME], opacity=0.07)
        .encode(x=SEASON_AXIS)
    )
    band_label = (
        alt.Chart(ranks[ranks["arena"] == INTUIT_DOME].head(1))
        .mark_text(align="left", dx=-30, dy=4, fontSize=12, fontWeight="bold",
                   color=PALETTE[INTUIT_DOME])
        .encode(x=SEASON_AXIS, y=alt.value(348), text=alt.value("Intuit Dome →"))
    )  # fmt: skip
    rline = rbase.mark_line(color=PALETTE["ink"], strokeWidth=2, opacity=0.5).encode(
        y=alt.Y("rank:Q", title="Rank (of 30)", scale=alt.Scale(domain=[30, 1], nice=False),
                axis=alt.Axis(values=[1, 5, 10, 15, 20, 25, 30]))
    )  # fmt: skip
    rdots = (
        rbase.mark_circle(opacity=1, stroke=SURFACE, strokeWidth=2)
        .encode(
            y="rank:Q",
            size=alt.condition(hover, alt.value(420), alt.value(230)),
            color=alt.Color(
                "arena:N", scale=ARENA_SCALE, legend=alt.Legend(title=None, orient="top")
            ),
            tooltip=[
                alt.Tooltip("season:N", title="Season"),
                alt.Tooltip("arena:N", title="Home arena"),
                alt.Tooltip("rank:Q", title="Rank of 30"),
                alt.Tooltip("edge:Q", title="Home boost (pts/100 poss.)", format="+.1f"),
                alt.Tooltip("league_mean:Q", title="League average boost", format="+.1f"),
                alt.Tooltip("note:N", title="Season"),
            ],
        )
        .add_params(hover)
    )
    rlabels = rbase.mark_text(dy=-20, fontSize=13, fontWeight="bold", color=INK).encode(
        y="rank:Q", text="label:N"
    )
    chart(dome_band + band_label + rline + rdots + rlabels, 360)

    left, right = st.columns(2, gap="large")
    lac = analysis.with_era(data[(data["team"] == LAC) & (data["location"] != "neutral")])
    with left:
        st.subheader("Win % at home vs. on the road")
        st.caption("The gap between the lines is the home-court boost.")
        wins = analysis.summarize(lac, ["season", "location"])
        wins = wins[wins.groupby("season")["games"].transform("sum") >= 20]  # skip tiny samples
        wins["split"] = wins["location"].map({"home": "Home", "away": "Road"})
        sel = alt.selection_point(fields=["split"], bind="legend")
        wl = alt.Chart(wins).encode(
            x=SEASON_AXIS,
            y=alt.Y("win_pct:Q", title="Win %", axis=alt.Axis(format="%"),
                    scale=alt.Scale(domain=[0, 0.85])),
            color=alt.Color("split:N", scale=alt.Scale(domain=["Home", "Road"],
                            range=[PALETTE["Home"], PALETTE["Road"]]),
                            legend=alt.Legend(title=None, orient="top")),
            opacity=alt.condition(sel, alt.value(1), alt.value(0.15)),
            tooltip=[
                alt.Tooltip("season:N", title="Season"),
                alt.Tooltip("split:N", title="Where"),
                alt.Tooltip("win_pct:Q", title="Win %", format=".0%"),
                alt.Tooltip("wins:Q", title="Wins"),
                alt.Tooltip("games:Q", title="Games"),
            ],
        )  # fmt: skip
        chart(wl.mark_line(strokeWidth=2) + wl.mark_circle(size=90).add_params(sel), 300)
        st.caption("Click a legend item to highlight it.")

    with right:
        st.subheader("Why? Opponents shoot worse there")
        split = analysis.summarize(lac, ["era", "location"]).set_index(["era", "location"])
        drop = split.xs("away", level="location") - split.xs("home", level="location")
        why = pd.DataFrame(
            {
                "arena": [SHARED_ARENA, INTUIT_DOME],
                "drop": [100 * drop.loc[a, "opp_efg"] for a in (SHARED_ARENA, INTUIT_DOME)],
            }
        )
        st.caption("How much worse opponents shoot against the Clippers at home than on the road.")
        bars = (
            alt.Chart(why)
            .mark_bar(size=70, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("arena:N", title=None, sort=[SHARED_ARENA, INTUIT_DOME],
                        axis=alt.Axis(labelAngle=0, labelFontSize=13, labelColor=INK)),
                y=alt.Y("drop:Q", title="Drop in opponents' shooting (eFG%, pct. points)"),
                color=alt.Color("arena:N", scale=ARENA_SCALE, legend=None),
                tooltip=[
                    alt.Tooltip("arena:N", title="Arena"),
                    alt.Tooltip("drop:Q", title="Opponent shooting drop", format=".1f"),
                ],
            )
        )  # fmt: skip
        blabels = bars.mark_text(dy=-12, fontSize=18, fontWeight="bold").encode(
            text=alt.Text("drop:Q", format=".1f"), color=alt.value(INK)
        )
        chart(bars + blabels, 300)
        st.caption("Most of the new advantage is defense.")

    with st.expander("📐 How this is measured, and how sure it is"):
        lo, hi = change["ci"]
        tiles(
            [
                (f"Old arena ({old['seasons'][0]} to {old['seasons'][-1]})",
                 f"{old['excess']:+.1f}", "home boost vs. league average"),
                (f"Intuit Dome ({new['seasons'][0]} to {new['seasons'][-1]})",
                 f"{new['excess']:+.1f}", "home boost vs. league average"),
                ("Change after the move", f"{change['delta']:+.1f}", "points per 100 possessions"),
                ("Resamples showing a gain", f"{change['p_increase']:.0%}",
                 f"95% range {lo:+.1f} to {hi:+.1f}"),
            ]
        )  # fmt: skip
        st.markdown(
            "- **Home boost** = point margin per 100 possessions at home minus on the road. "
            "Same players both ways, so the gap comes from the building: crowd, travel, sleep.\n"
            "- Each season is compared with that season's league average boost.\n"
            f"- **Confidence:** 4,000 resamples of the games; {change['p_increase']:.0%} show an "
            "increase. The range still touches zero, so it isn't conclusive yet.\n"
            "- **Not controlled for:** roster changes, rest, schedule.\n"
            f"- **Data:** every regular-season game since 2018-19 ({len(df) // 2:,} games), "
            "validated before it's stored. Neutral-site games are left out."
        )
        st.toggle(
            "Leave out 2019-20 and 2020-21 (Orlando bubble and empty-arena seasons)",
            key="exclude_limited",
        )
        st.dataframe(
            ctx[["season", "arena", "home_net", "away_net", "edge", "league_mean", "rank"]]
            .rename(columns={"home_net": "Home margin", "away_net": "Road margin",
                             "edge": "Home boost", "league_mean": "League avg", "rank": "Rank"})
            .style.format(precision=1),
            hide_index=True,
            width="stretch",
        )  # fmt: skip

# ---- The Wall --------------------------------------------------------------------------------
COURT_SVG = """
<div class="court"><svg viewBox="0 0 1000 430" role="img"
 aria-label="Diagram of Intuit Dome: a basketball court with The Wall, a 51-row section of
 fans, rising behind the left basket.">
  <defs><linearGradient id="wall" x1="0" x2="1">
    <stop offset="0" stop-color="{blue}" stop-opacity="0.95"/>
    <stop offset="1" stop-color="{blue}" stop-opacity="0.55"/></linearGradient></defs>
  {rows}
  <text x="105" y="34" text-anchor="middle" font-size="34" font-weight="800"
   fill="{ink}" letter-spacing="2">THE WALL</text>
  <text x="105" y="400" text-anchor="middle" font-size="27" fill="{muted}">51 rows of fans</text>
  <rect x="200" y="60" width="760" height="300" rx="6" fill="{floor}" stroke="{courtline}"
   stroke-width="3"/>
  <line x1="580" y1="60" x2="580" y2="360" stroke="{courtline}" stroke-width="3"/>
  <circle cx="580" cy="210" r="45" fill="none" stroke="{courtline}" stroke-width="3"/>
  <rect x="200" y="155" width="150" height="110" fill="{paint}" stroke="{courtline}"
   stroke-width="3"/>
  <circle cx="350" cy="210" r="45" fill="none" stroke="{courtline}" stroke-width="3"/>
  <rect x="810" y="155" width="150" height="110" fill="{paint2}" stroke="{courtline}"
   stroke-width="3"/>
  <circle cx="810" cy="210" r="45" fill="none" stroke="{courtline}" stroke-width="3"/>
  <path d="M200 90 L250 90 A140 140 0 0 1 250 330 L200 330" fill="none" stroke="{courtline}"
   stroke-width="3"/>
  <path d="M960 90 L910 90 A140 140 0 0 0 910 330 L960 330" fill="none" stroke="{courtline}"
   stroke-width="3"/>
  <circle cx="222" cy="210" r="9" fill="none" stroke="{hoop}" stroke-width="4"/>
  <circle cx="938" cy="210" r="9" fill="none" stroke="{hoop}" stroke-width="4"/>
  <circle cx="350" cy="210" r="7" fill="{ink}"/>
  <text x="390" y="392" text-anchor="middle" font-size="27" fill="{ink}" font-weight="700">
  Free throw toward The Wall</text>
  <text x="390" y="420" text-anchor="middle" font-size="22" fill="{muted}">
  visitors get this end for one half</text>
  <text x="780" y="392" text-anchor="middle" font-size="27" fill="{ink}" font-weight="700">
  Normal end</text>
  <text x="780" y="420" text-anchor="middle" font-size="22" fill="{muted}">
  the other half</text>
</svg></div>
"""


def wall_rows() -> str:
    out = []
    for i in range(12):  # stylised: 12 bands stand in for 51 rows
        y = 52 + i * 26
        heads = "".join(
            f'<circle cx="{40 + j * 22 + (i % 2) * 11}" cy="{y + 9}" r="7" '
            f'fill="url(#wall)" opacity="{0.55 + 0.04 * (11 - i):.2f}"/>'
            for j in range(7)
        )
        out.append(heads)
    return "".join(out)


with tab_wall:
    answer(
        f"<b>{'Not really.' if not wall_real else 'Maybe a little.'}</b> The Wall is 51 rows "
        "of Clippers fans behind one basket. Visitors shoot free throws there "
        + (
            "about as well as they do everywhere else."
            if not wall_real
            else "a bit worse than usual."
        )
    )
    court, stats = st.columns([3, 2], gap="large")
    with court:
        html(
            COURT_SVG.format(
                rows=wall_rows(), blue=PALETTE[INTUIT_DOME], ink=INK, muted=MUTED, line=LINE,
                courtline="#7a6a52" if DARK else "#c4ab83",
                floor="#2b2620" if DARK else "#f3e6d0", paint="#2a3a55" if DARK else "#dbe7f7",
                paint2="#2b2620" if DARK else "#efe0c5", hoop=PALETTE[SHARED_ARENA],
            )
        )  # fmt: skip
    with stats:
        dome_pct = dome_ft["ftm"].sum() / dome_ft["fta"].sum()
        usual_pct = dome_ft["expected"].sum() / dome_ft["fta"].sum()
        tiles(
            [
                ("Visitors' FT% at Intuit Dome", f"{dome_pct:.1%}",
                 f"{int(dome_ft['fta'].sum()):,} free throws"),
                ("Their usual FT% elsewhere", f"{usual_pct:.1%}", "same players, other arenas"),
            ]
        )  # fmt: skip
        tiles(
            [
                ("Difference", f"{wall_effect:+.1f} pts".replace("-", "−"),
                 f"luck alone moves this ±{2 * noise / len(dome_ft) ** 0.5:.1f}"),
            ]
        )  # fmt: skip

    st.subheader("How hard is each arena for visiting free-throw shooters?")
    st.caption(
        "Visitors' FT% in each arena compared with their own FT% everywhere else. "
        "Bars to the left = visitors miss more there. Pick a season with the slider."
    )
    seasons_all = sorted(ft["season"].unique())
    season_pick = st.select_slider(
        "Season", options=seasons_all, value=seasons_all[-2] if in_progress else seasons_all[-1]
    )
    one = ft[ft["season"] == season_pick].assign(
        who=lambda d: d["arena_team"].map(
            lambda t: ("Clippers · " + arena_of(season_pick)) if t == LAC else "Other arenas"
        )
    )
    lac_row = one[one["arena_team"] == LAC].iloc[0]
    who_scale = alt.Scale(
        domain=["Clippers · " + arena_of(season_pick), "Other arenas"],
        range=[PALETTE[arena_of(season_pick)], "#5c5b56" if DARK else "#c9c7bf"],
    )
    abars = (
        alt.Chart(one)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            y=alt.Y("arena_team:N", title=None, sort="x",
                    axis=alt.Axis(labelColor=MUTED, labelFontSize=11, labelOverlap=False)),
            x=alt.X("diff:Q", title="Visitors' FT% vs. their usual (pct. points)"),
            color=alt.Color("who:N", scale=who_scale, legend=alt.Legend(title=None, orient="top")),
            tooltip=[
                alt.Tooltip("arena_team:N", title="Home team"),
                alt.Tooltip("ft_pct:Q", title="Visitors' FT% there", format=".1%"),
                alt.Tooltip("diff:Q", title="vs. their usual", format="+.1f"),
                alt.Tooltip("rank:Q", title="Rank (1 = toughest)"),
                alt.Tooltip("fta:Q", title="Visitor free throws"),
            ],
        )
    )  # fmt: skip
    zero_x = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=MUTED).encode(x="x:Q")
    chart(abars + zero_x, 640)
    st.caption(
        f"In {season_pick} the Clippers' arena ranked **{ordinal(int(lac_row['rank']))} of 30** "
        f"({lac_row['diff']:+.1f}). One season bounces around by about ±{noise:.1f} from luck "
        "alone, so the seasons together are what count."
    )

    # ---- 1st half vs 2nd half
    half_rows = load_halves()
    st.subheader("1st half vs. 2nd half")
    if half_rows.empty:
        st.info("No half-by-half data yet. Run `clippers-halves` to fetch it.")
    else:
        st.caption(
            "Teams switch baskets at halftime, so visitors face The Wall for only one half. "
            "If The Wall works, one half should be clearly lower at Intuit Dome."
        )
        by_season = analysis.ft_by_half(half_rows, by="season")
        by_season["arena"] = by_season["season"].map(arena_of)
        hl = pd.concat(
            [
                by_season.assign(half=half, pct=by_season[f"opp_pct_{p}"],
                                 fta=by_season[f"opp_fta_{p}"])
                for p, half in (("h1", "1st half"), ("h2", "2nd half"))
            ]
        )  # fmt: skip
        hl["season_lbl"] = hl["season"] + "  ·  " + hl["arena"].str.replace(" Arena", "")
        order = list(by_season["season"] + "  ·  " + by_season["arena"].str.replace(" Arena", ""))
        hy = alt.Y("season_lbl:N", title=None, sort=order,
                   axis=alt.Axis(labelColor=INK, labelFontSize=12, labelLimit=260))  # fmt: skip
        dome_rows = (
            alt.Chart(by_season[by_season["arena"] == INTUIT_DOME].assign(
                season_lbl=lambda d: d["season"] + "  ·  Intuit Dome"))
            .mark_rect(color=PALETTE[INTUIT_DOME], opacity=0.08)
            .encode(y=hy)
        )  # fmt: skip
        stems = (
            alt.Chart(by_season.assign(season_lbl=order))
            .mark_rule(color=MUTED, strokeWidth=2)
            .encode(
                y=hy,
                x=alt.X("opp_pct_h1:Q", scale=alt.Scale(domain=[0.64, 0.86])),
                x2="opp_pct_h2:Q",
            )
        )
        hdots = (
            alt.Chart(hl)
            .mark_circle(size=170, opacity=1, stroke=SURFACE, strokeWidth=2)
            .encode(
                y=hy,
                x=alt.X("pct:Q", title="Visitors' FT%", axis=alt.Axis(format="%"),
                        scale=alt.Scale(domain=[0.64, 0.86])),
                color=alt.Color("half:N", scale=HALF_SCALE,
                                legend=alt.Legend(title=None, orient="top")),
                tooltip=[
                    alt.Tooltip("season:N", title="Season"),
                    alt.Tooltip("arena:N", title="Arena"),
                    alt.Tooltip("half:N", title="Half"),
                    alt.Tooltip("pct:Q", title="Visitors' FT%", format=".1%"),
                    alt.Tooltip("fta:Q", title="Free throws"),
                    alt.Tooltip("games:Q", title="Games"),
                ],
            )
        )  # fmt: skip
        chart(dome_rows + stems + hdots, 380)
        dome_s = by_season[by_season["arena"] == INTUIT_DOME]
        full = dome_s[dome_s["games"] >= 30]
        swings = ", ".join(
            f"{r.season}: {'2nd' if r.opp_swing < 0 else '1st'} half lower by "
            f"{abs(r.opp_swing):.1f}"
            for r in full.itertuples()
        )
        st.caption(
            f"At Intuit Dome: {swings}. The seasons point opposite ways, so overall the halves "
            "even out. That could be luck, or visitors facing The Wall in a different half each "
            "season; box scores don't record which end a team shot at."
        )

    with st.expander("📐 How this is measured"):
        st.markdown(
            "- Each visiting team's FT% in an arena is compared with **its own** FT% in all its "
            "other games that season, so good and bad shooting teams cancel out.\n"
            f"- Visitors take about {ft['fta'].mean():.0f} free throws per arena per season; at "
            f"that sample size luck alone moves one season by about ±{noise:.1f} points.\n"
            "- Half-by-half numbers come from Basketball Reference box scores for every "
            "Clippers home game since 2018-19, each checked against the full-game totals.\n"
            "- An early-season study ([Above the Break, Dec 2024]"
            "(https://abovethebreak.substack.com/p/ballmers-wall-is-the-intuit-dome)) found a "
            "small effect it called largely indistinguishable from normal home-court variance."
        )

# ---- Every home game -------------------------------------------------------------------------
with tab_games:
    by_game = analysis.opponent_fts_by_game(df)
    half_rows = load_halves()
    if not half_rows.empty:
        h = half_rows.assign(game_date=pd.to_datetime(half_rows["game_date"]))
        by_game = by_game.merge(
            h[["game_date", "opp_ftm_h1", "opp_fta_h1", "opp_ftm_h2", "opp_fta_h2"]],
            on="game_date",
            how="left",
        )
    else:
        by_game = by_game.assign(opp_ftm_h1=pd.NA, opp_fta_h1=pd.NA, opp_ftm_h2=pd.NA,
                                 opp_fta_h2=pd.NA)  # fmt: skip

    c1, c2 = st.columns([1, 2])
    seasons_desc = sorted(by_game["season"].unique(), reverse=True)
    pick = c1.selectbox("Season", seasons_desc, index=0, key="ft_game_season")
    games_s = by_game[by_game["season"] == pick].copy()
    teams = sorted(games_s["opponent"].unique())
    chosen = c2.multiselect("Opponents (leave empty for all)", teams, key="ft_game_teams")
    if chosen:
        games_s = games_s[games_s["opponent"].isin(chosen)]
    if games_s.empty:
        st.info("No games match.")
    else:
        games_s["label"] = games_s["game_date"].dt.strftime("%b %d") + " " + games_s["opponent"]
        games_s["result"] = games_s["win"].map({True: "W", False: "L"})
        games_s["outcome"] = games_s["diff"].map(
            lambda d: "Missed more than usual" if d < 0 else "Shot as well or better"
        )
        worse = int((games_s["diff"] < 0).sum())
        n_wins = int((games_s["result"] == "W").sum())
        made = games_s["opp_ftm"].sum() / games_s["opp_fta"].sum()
        usual = (games_s["season_pct"] * games_s["opp_fta"]).sum() / games_s["opp_fta"].sum()
        tiles(
            [
                ("Home games", f"{len(games_s)}",
                 f"{n_wins} win{'' if n_wins == 1 else 's'} at {games_s['arena'].iloc[0]}"),
                ("Visitors missed more than usual", f"{worse} of {len(games_s)}", "games"),
                ("Visitors' FT% here", f"{made:.1%}", f"vs. {usual:.1%} usual"),
            ]
        )  # fmt: skip
        st.caption(
            "Each dot is the visitors' FT% that night. The gray tick is their usual FT% (all "
            "their other games that season). Hover for details."
        )
        gx = alt.X("label:N", title=None, sort=list(games_s["label"]),
                   axis=alt.Axis(labelAngle=-60, labelColor=MUTED))  # fmt: skip
        gtip = [
            alt.Tooltip("label:N", title="Game"),
            alt.Tooltip("result:N", title="Clippers"),
            alt.Tooltip("opp_ftm:Q", title="Visitors made"),
            alt.Tooltip("opp_fta:Q", title="Visitors attempted"),
            alt.Tooltip("ft_pct:Q", title="Visitors' FT% that night", format=".1%"),
            alt.Tooltip("season_pct:Q", title="Their usual FT%", format=".1%"),
            alt.Tooltip("diff:Q", title="vs. usual (pct. points)", format="+.1f"),
        ]
        outcome_scale = alt.Scale(
            domain=["Missed more than usual", "Shot as well or better"],
            range=[PALETTE[INTUIT_DOME], PALETTE[SHARED_ARENA]],
        )
        gb = alt.Chart(games_s).encode(x=gx, tooltip=gtip)
        gstems = gb.mark_rule(color=MUTED, opacity=0.6, strokeWidth=2).encode(
            y=alt.Y("season_pct:Q", title="Visitors' FT%", axis=alt.Axis(format="%"),
                    scale=alt.Scale(zero=False)),
            y2="ft_pct:Q",
        )  # fmt: skip
        gticks = gb.mark_tick(color=MUTED, thickness=3, size=16).encode(y="season_pct:Q")
        gdots = gb.mark_circle(size=130, opacity=1, stroke=SURFACE, strokeWidth=2).encode(
            y="ft_pct:Q",
            color=alt.Color("outcome:N", scale=outcome_scale,
                            legend=alt.Legend(title=None, orient="top")),
        )  # fmt: skip
        chart(gstems + gticks + gdots, 340)

        def ft_cell(m, a) -> str:
            if pd.isna(a):
                return "–"
            return f"{int(m)}/{int(a)}  ({m / a:.0%})" if a else "0/0"

        table = pd.DataFrame(
            {
                "Date": games_s["game_date"].dt.date,
                "Opponent": games_s["opponent"],
                "Clippers": games_s["result"],
                "Visitors' FT%": 100 * games_s["ft_pct"],
                "Their usual": 100 * games_s["season_pct"],
                "vs. usual": games_s["diff"],
                "Made / attempted": [ft_cell(m, a) for m, a in
                                     zip(games_s["opp_ftm"], games_s["opp_fta"], strict=True)],
                "1st half": [ft_cell(m, a) for m, a in
                             zip(games_s["opp_ftm_h1"], games_s["opp_fta_h1"], strict=True)],
                "2nd half": [ft_cell(m, a) for m, a in
                             zip(games_s["opp_ftm_h2"], games_s["opp_fta_h2"], strict=True)],
            }
        ).iloc[::-1]  # fmt: skip
        st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            column_config={
                "Visitors' FT%": st.column_config.ProgressColumn(
                    format="%.1f%%", min_value=0.0, max_value=100.0
                ),
                "Their usual": st.column_config.NumberColumn(format="%.1f%%"),
                "vs. usual": st.column_config.NumberColumn(
                    format="%+.1f", help="Percentage points; negative = visitors missed more"
                ),
            },
        )

# ---- Other new arenas ------------------------------------------------------------------------
with tab_moves:
    if not have_moves:
        st.info("Needs seasons back to 2013-14. Run `clippers-ingest` to backfill them.")
    else:
        lo, hi = placebo["delta"].quantile([0.05, 0.95])
        answer(
            "<b>No, a jump like this is rare.</b> Four other teams opened new arenas since 2016. "
            f"None gained more than {others_moved['delta'].max():+.1f}. "
            f"The Clippers gained <b>{lac_move['delta']:+.1f}</b>."
        )
        tiles(
            [
                ("Clippers' change", f"{lac_move['delta']:+.1f}", "pts per 100 possessions"),
                ("Average for other new arenas", f"{others_moved['delta'].mean():+.1f}",
                 f"{len(others_moved)} teams"),
                ("Chance of a jump this big", f"{share_bigger:.0%}",
                 f"from {len(placebo):,} seasons with no move"),
            ]
        )  # fmt: skip
        rows = moves.assign(
            label=moves["team"] + " → " + moves["new_arena"] + " (" + moves["first_new_season"]
            + ")",
            who=moves["team"].map(lambda t: "Clippers" if t == LAC else "Other teams"),
        ).sort_values("delta")  # fmt: skip
        st.subheader("Change in home-court boost after moving into a new arena")
        st.caption(
            "3 seasons before the move vs. the first 2 in the new building. The gray band is "
            "where 90% of changes land for teams that didn't move. Hover for details."
        )
        who = alt.Color(
            "who:N",
            scale=alt.Scale(domain=["Clippers", "Other teams"],
                            range=[PALETTE[INTUIT_DOME], "#6b6a66" if not DARK else "#8a8983"]),
            legend=None,
        )  # fmt: skip
        y = alt.Y("label:N", title=None, sort=list(rows["label"]),
                  axis=alt.Axis(labelLimit=340, labelColor=INK, labelFontSize=13))  # fmt: skip
        tooltip = [
            alt.Tooltip("label:N", title="Move"),
            alt.Tooltip("old_arena:N", title="From"),
            alt.Tooltip("before_seasons:N", title="Before"),
            alt.Tooltip("after_seasons:N", title="After"),
            alt.Tooltip("delta:Q", title="Change", format="+.1f"),
            alt.Tooltip("ci_low:Q", title="95% low", format="+.1f"),
            alt.Tooltip("ci_high:Q", title="95% high", format="+.1f"),
        ]
        band = (
            alt.Chart(pd.DataFrame({"lo": [lo], "hi": [hi]}))
            .mark_rect(color=MUTED, opacity=0.15)
            .encode(x="lo:Q", x2="hi:Q")
        )
        mbars = (
            alt.Chart(rows)
            .mark_bar(height=26, cornerRadiusEnd=4)
            .encode(y=y, x=alt.X("delta:Q", title="Change (pts per 100 possessions)",
                          axis=alt.Axis(tickCount=8)),
                    color=who, tooltip=tooltip)
        )  # fmt: skip
        label_enc = {"text": alt.Text("delta:Q", format="+.1f"), "color": alt.value(INK)}
        pos_labels = (
            mbars.transform_filter("datum.delta >= 0")
            .mark_text(align="left", dx=6, fontSize=13, fontWeight="bold")
            .encode(**label_enc)
        )
        neg_labels = (
            mbars.transform_filter("datum.delta < 0")
            .mark_text(align="right", dx=-6, fontSize=13, fontWeight="bold")
            .encode(**label_enc)
        )
        band_note = (
            alt.Chart(pd.DataFrame({"x": [(lo + hi) / 2]}))
            .mark_text(dy=-6, fontSize=11, color=MUTED)
            .encode(
                x="x:Q", y=alt.value(0), text=alt.value("normal range for teams that didn't move")
            )
        )
        chart(band + band_note + mbars + pos_labels + neg_labels + zero_x, 300)
        with st.expander("📐 How this is measured"):
            st.markdown(
                "- For each team: home boost minus the league average, 3 seasons before the "
                "move vs. the first 2 seasons after, skipping 2020-21 (no fans).\n"
                f"- **Chance baseline:** the same calculation for every team at every season "
                f"where nothing happened ({len(placebo):,} comparisons).\n"
                "- This uses the same window for every team, so the Clippers' number differs "
                "slightly from the Home advantage tab.\n"
                "- Only new buildings count, not renamed ones."
            )
            st.dataframe(
                rows[["team", "old_arena", "new_arena", "before_seasons", "after_seasons",
                      "before_excess", "after_excess", "delta", "ci_low", "ci_high"]]
                .rename(columns={
                    "team": "Team", "old_arena": "From", "new_arena": "To",
                    "before_seasons": "Before", "after_seasons": "After",
                    "before_excess": "Before (vs. league)", "after_excess": "After (vs. league)",
                    "delta": "Change", "ci_low": "95% low", "ci_high": "95% high",
                })
                .style.format(precision=1),
                hide_index=True,
                width="stretch",
            )  # fmt: skip

# ---- Footer ----------------------------------------------------------------------------------
st.divider()
with st.expander("⚙️ Data pipeline status"):
    seasons = report.get("seasons", {})
    rejected = sum(len(s.get("rejected", [])) for s in seasons.values())
    st.write(
        f"Last ingest finished **{report.get('finished_at', 'unknown')}** · "
        f"{len(all_games):,} team-game rows across {all_games['season'].nunique()} seasons · "
        f"{rejected} games rejected by validation"
    )
    st.json(report, expanded=False)
st.caption(
    "Data: stats.nba.com via nba_api and Basketball Reference, refreshed daily. "
    "Not affiliated with the NBA or the LA Clippers. "
    "Source: github.com/JayJaden06/clippers-home-court"
)
