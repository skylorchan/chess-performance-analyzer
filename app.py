"""
Streamlit dashboard — Chess Performance Analyzer.

Run with:
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pandas.io.formats.style import Styler

from chess_analyzer.parser import load_games
from chess_analyzer.analysis import (
    summary_stats,
    opening_performance,
    performance_by_color,
    performance_by_time_control,
    performance_by_move_count,
    performance_by_rating_bucket,
    rating_trajectory,
    MIN_SAMPLE,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Chess Performance Analyzer",
    page_icon="♟",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar — inputs
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("♟ Chess Analyzer")
    username = st.text_input("Chess.com username", value="", placeholder="e.g. hikaru")
    platform = st.selectbox("Platform", ["chesscom", "lichess", "both"])
    min_games = st.slider(
        "Min games to show an opening",
        min_value=3, max_value=30, value=MIN_SAMPLE,
        help="Openings with fewer games than this are hidden from the opening table.",
    )
    run = st.button("Analyze", type="primary", width="stretch")
    st.divider()
    st.caption(
        "Data is cached locally after the first fetch. "
        "Current month is always re-fetched."
    )

# ---------------------------------------------------------------------------
# Load data (cached so re-renders don't re-fetch)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Fetching games...")
def get_data(username: str, platform: str) -> pd.DataFrame:
    return load_games(username, platform=platform)


if not run and "df" not in st.session_state:
    st.info("Enter your username in the sidebar and click **Analyze**.")
    st.stop()

if run:
    if not username.strip():
        st.warning("Please enter a username first.")
        st.stop()
    try:
        st.session_state["df"] = get_data(username.strip(), platform)
        st.session_state["username"] = username.strip()
    except ValueError as e:
        st.error(str(e))
        st.stop()

df: pd.DataFrame = st.session_state["df"]
username: str = st.session_state.get("username", username)

if df.empty:
    st.warning("No games found for this username.")
    st.stop()

# ---------------------------------------------------------------------------
# Helper: color unreliable rows in tables
# ---------------------------------------------------------------------------

def style_reliable(df_in: pd.DataFrame) -> Styler:
    """Gray out rows where reliable == False."""
    def _row_style(row):
        if "reliable" in row.index and not row["reliable"]:
            return ["color: #888"] * len(row)
        return [""] * len(row)
    return df_in.style.apply(_row_style, axis=1)


def fmt_pct(v):
    return f"{v:.1%}"

def fmt_f2(v):
    return f"{v:+.3f}"


# ---------------------------------------------------------------------------
# Summary header
# ---------------------------------------------------------------------------

stats = summary_stats(df)

st.title(f"Performance report: {username}")
st.caption(stats["note"])

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total games", stats["total_games"])
c2.metric("Win rate", fmt_pct(stats["win_rate"]))
c3.metric("Peak rating", stats["peak_rating"])
c4.metric("Current rating", stats["current_rating"])
c5.metric("Avg game length", f"{stats['avg_game_length']} moves")

st.divider()

# ---------------------------------------------------------------------------
# Tab layout
# ---------------------------------------------------------------------------

tab_rating, tab_openings, tab_length, tab_breakdown = st.tabs([
    "Rating trajectory",
    "Openings",
    "Game length",
    "Color & time control",
])

# ── Tab 1: Rating trajectory ────────────────────────────────────────────────

with tab_rating:
    st.subheader("Rating over time")
    st.caption(
        "Each dot is one game. The line is a 20-game rolling average — "
        "it smooths out individual swings to show the real trend."
    )

    traj = rating_trajectory(df, rolling_window=20)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=traj["date"], y=traj["my_rating"],
        mode="markers",
        marker=dict(size=4, opacity=0.35, color="#93c5fd"),
        name="Individual game",
        hovertemplate="%{x|%b %d, %Y}<br>Rating: %{y}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=traj["date"], y=traj["rolling_avg"],
        mode="lines",
        line=dict(width=2.5, color="#2563eb"),
        name="20-game average",
        hovertemplate="%{x|%b %d, %Y}<br>Avg: %{y:.0f}<extra></extra>",
    ))
    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Rating",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=10, b=0),
        height=380,
    )
    st.plotly_chart(fig, width="stretch")

# ── Tab 2: Openings ─────────────────────────────────────────────────────────

with tab_openings:
    st.subheader("Opening performance (Elo-adjusted)")
    st.caption(
        "**Score edge** = your actual score minus what your Elo predicts you should score. "
        "A negative edge means you're losing more than your rating difference explains — "
        "it controls for the fact that some openings put you against harder opponents."
    )

    op = opening_performance(df, min_games=min_games)

    col_left, col_right = st.columns([3, 2])

    with col_left:
        # Bar chart: top 15 openings by game count, colored by score edge
        top_op = op[op["reliable"]].copy()
        if top_op.empty:
            st.info(f"No openings with {min_games}+ games. Lower the slider.")
        else:
            top_op = top_op.nlargest(15, "n_games").sort_values("score_edge")
            top_op["label"] = top_op["opening"].str[:40]

            fig2 = px.bar(
                top_op,
                x="score_edge",
                y="label",
                orientation="h",
                color="score_edge",
                color_continuous_scale=["#ef4444", "#f9fafb", "#22c55e"],
                color_continuous_midpoint=0,
                labels={"score_edge": "Score edge", "label": "Opening"},
                hover_data={"n_games": True, "win_rate": ":.1%", "score_edge": ":.3f"},
            )
            fig2.update_layout(
                margin=dict(l=0, r=0, t=10, b=0),
                height=420,
                coloraxis_showscale=False,
                yaxis_title="",
            )
            fig2.add_vline(x=0, line_width=1, line_color="#374151")
            st.plotly_chart(fig2, width="stretch")

    with col_right:
        st.markdown("**Full table** (grayed = < min games)")
        display_op = op[["opening", "eco", "n_games", "win_rate", "avg_expected", "score_edge", "reliable"]].copy()
        display_op["win_rate"] = display_op["win_rate"].map(fmt_pct)
        display_op["avg_expected"] = display_op["avg_expected"].map(fmt_pct)
        display_op["score_edge"] = display_op["score_edge"].map(fmt_f2)
        st.dataframe(
            style_reliable(display_op),
            width="stretch",
            height=420,
            hide_index=True,
        )

# ── Tab 3: Game length ───────────────────────────────────────────────────────

with tab_length:
    st.subheader("Performance by game length")
    st.caption(
        "Does your win rate change as games get longer? "
        "Score edge controls for opponent strength within each bucket."
    )

    ml = performance_by_move_count(df)

    fig3 = go.Figure()
    fig3.add_trace(go.Bar(
        x=ml["move_bucket"], y=ml["win_rate"],
        name="Win rate", marker_color="#22c55e", opacity=0.85,
        hovertemplate="%{x}<br>Win rate: %{y:.1%}<extra></extra>",
    ))
    fig3.add_trace(go.Bar(
        x=ml["move_bucket"], y=ml["draw_rate"],
        name="Draw rate", marker_color="#94a3b8", opacity=0.85,
        hovertemplate="%{x}<br>Draw rate: %{y:.1%}<extra></extra>",
    ))
    fig3.add_trace(go.Bar(
        x=ml["move_bucket"], y=ml["loss_rate"],
        name="Loss rate", marker_color="#ef4444", opacity=0.85,
        hovertemplate="%{x}<br>Loss rate: %{y:.1%}<extra></extra>",
    ))
    fig3.update_layout(
        barmode="stack",
        xaxis_title="Game length (full moves)",
        yaxis_title="Proportion of games",
        yaxis_tickformat=".0%",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=10, b=0),
        height=360,
    )
    st.plotly_chart(fig3, width="stretch")

    # Score edge line overlaid
    fig4 = px.line(
        ml, x="move_bucket", y="score_edge",
        markers=True,
        labels={"move_bucket": "Game length", "score_edge": "Score edge"},
        title="Score edge by game length (+ = outperforming Elo prediction)",
    )
    fig4.add_hline(y=0, line_width=1, line_dash="dash", line_color="#374151")
    fig4.update_traces(line_color="#2563eb", marker_size=8)
    fig4.update_layout(margin=dict(l=0, r=0, t=40, b=0), height=280)
    st.plotly_chart(fig4, width="stretch")

    st.caption(
        "Grayed buckets have fewer than "
        f"{MIN_SAMPLE} games and should be treated with caution."
    )
    st.dataframe(
        style_reliable(ml[["move_bucket", "n_games", "win_rate", "draw_rate", "loss_rate", "score_edge", "reliable"]]),
        width="stretch",
        hide_index=True,
    )

# ── Tab 4: Color & time control ──────────────────────────────────────────────

with tab_breakdown:
    st.subheader("Breakdown by color, time control, and opponent strength")

    left, right = st.columns(2)

    with left:
        st.markdown("**By color**")
        color_df = performance_by_color(df)
        fig5 = px.bar(
            color_df.melt(id_vars="color", value_vars=["win_rate", "draw_rate", "loss_rate"],
                          var_name="result", value_name="rate"),
            x="color", y="rate", color="result",
            color_discrete_map={
                "win_rate": "#22c55e",
                "draw_rate": "#94a3b8",
                "loss_rate": "#ef4444",
            },
            barmode="stack",
            labels={"rate": "Proportion", "color": "Color played", "result": ""},
        )
        fig5.update_layout(
            yaxis_tickformat=".0%",
            margin=dict(l=0, r=0, t=10, b=0),
            height=300,
            showlegend=True,
        )
        st.plotly_chart(fig5, width="stretch")

        color_display = color_df[["color", "n_games", "win_rate", "score_edge"]].copy()
        color_display["win_rate"] = color_display["win_rate"].map(fmt_pct)
        color_display["score_edge"] = color_display["score_edge"].map(fmt_f2)
        st.dataframe(color_display, width="stretch", hide_index=True)

    with right:
        st.markdown("**By time control**")
        tc_df = performance_by_time_control(df)
        fig6 = px.bar(
            tc_df.melt(id_vars="time_category",
                       value_vars=["win_rate", "draw_rate", "loss_rate"],
                       var_name="result", value_name="rate"),
            x="time_category", y="rate", color="result",
            color_discrete_map={
                "win_rate": "#22c55e",
                "draw_rate": "#94a3b8",
                "loss_rate": "#ef4444",
            },
            barmode="stack",
            labels={"rate": "Proportion", "time_category": "Time control", "result": ""},
        )
        fig6.update_layout(
            yaxis_tickformat=".0%",
            margin=dict(l=0, r=0, t=10, b=0),
            height=300,
        )
        st.plotly_chart(fig6, width="stretch")

        tc_display = tc_df[["time_category", "n_games", "win_rate", "score_edge", "reliable"]].copy()
        tc_display["win_rate"] = tc_display["win_rate"].map(fmt_pct)
        tc_display["score_edge"] = tc_display["score_edge"].map(fmt_f2)
        st.dataframe(style_reliable(tc_display), width="stretch", hide_index=True)

    st.divider()
    st.markdown("**By opponent strength (relative to your rating)**")
    st.caption(
        "Score edge here is the most direct measure: are you beating "
        "the people you're supposed to beat, and holding your own against stronger players?"
    )

    rb_df = performance_by_rating_bucket(df)
    fig7 = go.Figure()
    fig7.add_trace(go.Bar(
        x=rb_df["rating_bucket"], y=rb_df["win_rate"],
        name="Win", marker_color="#22c55e", opacity=0.85,
    ))
    fig7.add_trace(go.Bar(
        x=rb_df["rating_bucket"], y=rb_df["draw_rate"],
        name="Draw", marker_color="#94a3b8", opacity=0.85,
    ))
    fig7.add_trace(go.Bar(
        x=rb_df["rating_bucket"], y=rb_df["loss_rate"],
        name="Loss", marker_color="#ef4444", opacity=0.85,
    ))
    fig7.update_layout(
        barmode="stack",
        xaxis_title="Opponent strength vs. your rating",
        yaxis_title="Proportion",
        yaxis_tickformat=".0%",
        margin=dict(l=0, r=0, t=10, b=0),
        height=320,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig7, width="stretch")

    rb_display = rb_df[["rating_bucket", "n_games", "win_rate", "avg_expected", "score_edge", "reliable"]].copy()
    rb_display["win_rate"] = rb_display["win_rate"].map(fmt_pct)
    rb_display["avg_expected"] = rb_display["avg_expected"].map(fmt_pct)
    rb_display["score_edge"] = rb_display["score_edge"].map(fmt_f2)
    st.dataframe(style_reliable(rb_display), width="stretch", hide_index=True)
