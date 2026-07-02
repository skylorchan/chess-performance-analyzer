"""
Core analysis module: answers competitive questions from the parsed game DataFrame.

All functions take a DataFrame produced by parser.pgns_to_dataframe() and return
plain DataFrames or dicts — no plotting, no I/O.  The dashboard (Phase 3) handles
display; keeping analysis separate means you can test every calculation in isolation.

Statistical philosophy
----------------------
Chess game samples are small.  474 games spread across dozens of openings means
most opening buckets have 5-15 games.  We report sample sizes everywhere and mark
results with n < MIN_SAMPLE as unreliable rather than hiding them or drawing false
conclusions.  Where we compute expected performance from Elo, we're explicit about
what the Elo formula assumes (long-run average, not per-game prediction).
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Minimum games in a bucket before we consider the result meaningful.
MIN_SAMPLE = 10

# Elo formula constant.
_ELO_K = 400


# ---------------------------------------------------------------------------
# Shared preprocessing — add derived columns used by multiple analyses
# ---------------------------------------------------------------------------

def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with columns needed by all analysis functions.

    New columns:
      score            float  | 1.0 win, 0.5 draw, 0.0 loss
      rating_diff      int    | my_rating - opp_rating (positive = I'm stronger)
      expected_score   float  | Elo-predicted win probability
      score_vs_expected float | actual score minus expected (our "edge")
      time_category    str    | 'bullet', 'blitz', 'rapid', 'classical', 'other'
      rating_bucket    str    | opponent strength relative to us
    """
    df = df.copy()

    # Score as a number so we can average it (expected value of the result).
    df["score"] = df["result"].map({"win": 1.0, "draw": 0.5, "loss": 0.0})

    # Rating difference from our perspective.  Positive = we are rated higher.
    df["rating_diff"] = df["my_rating"] - df["opp_rating"]

    # Elo expected score: probability of winning from our rating difference.
    # This is the standard FIDE formula.  It tells us what a "typical" player
    # at our rating would score against this opponent — not what we should score
    # in any individual game.
    df["expected_score"] = 1 / (1 + 10 ** (-df["rating_diff"] / _ELO_K))

    # How much we over- or under-performed relative to Elo expectation.
    # Positive = better than expected; negative = worse than expected.
    df["score_vs_expected"] = df["score"] - df["expected_score"]

    # Time category based on base clock seconds (FIDE-style boundaries).
    def _time_cat(secs: int) -> str:
        if secs <= 0:
            return "other"
        if secs < 180:
            return "bullet"
        if secs < 600:
            return "blitz"
        if secs < 1800:
            return "rapid"
        return "classical"

    df["time_category"] = df["base_seconds"].apply(_time_cat)

    # Opponent strength relative to us, in 100-point buckets.
    # Negative diff means opponent is stronger (they have higher rating).
    bins   = [-np.inf, -300, -150, -50, 50, 150, 300, np.inf]
    labels = [
        "much stronger (>300)",
        "stronger (150-300)",
        "slightly stronger (50-150)",
        "even (+/-50)",
        "slightly weaker (50-150)",
        "weaker (150-300)",
        "much weaker (>300)",
    ]
    df["rating_bucket"] = pd.cut(df["rating_diff"], bins=bins, labels=labels)

    return df


# ---------------------------------------------------------------------------
# 1. Opening performance, controlling for opponent strength
# ---------------------------------------------------------------------------

def opening_performance(df: pd.DataFrame, min_games: int = MIN_SAMPLE) -> pd.DataFrame:
    """Return opening statistics adjusted for opponent strength.

    Naive win-rate-per-opening is misleading: if you only play the Sicilian
    against 200-point-higher opponents, it will look terrible even if you're
    playing it well.  We control for this by comparing your actual score to
    your Elo-expected score in each opening.  A negative score_vs_expected
    means you're losing more than the rating difference predicts.

    Columns returned:
      opening          str   | opening name
      eco              str   | ECO code
      n_games          int   | sample size
      win_rate         float | raw win percentage (0–1)
      draw_rate        float | raw draw percentage
      loss_rate        float | raw loss percentage
      avg_score        float | average actual score (win=1, draw=0.5, loss=0)
      avg_expected     float | average Elo-expected score
      score_edge       float | avg_score - avg_expected (the key number)
      avg_opp_rating   float | average opponent rating (context)
      avg_rating_diff  float | average rating difference (context)
      reliable         bool  | True if n_games >= min_games

    Sort order: score_edge ascending (worst openings first).
    """
    df = add_derived_columns(df)
    df = df.dropna(subset=["my_rating", "opp_rating"])

    grp = df.groupby(["opening", "eco"], observed=True)

    result = grp.agg(
        n_games=("score", "count"),
        avg_score=("score", "mean"),
        avg_expected=("expected_score", "mean"),
        avg_opp_rating=("opp_rating", "mean"),
        avg_rating_diff=("rating_diff", "mean"),
    ).reset_index()

    result["score_edge"] = result["avg_score"] - result["avg_expected"]

    # Compute win/draw/loss rates separately (agg doesn't do conditional counts).
    for res, col in [("win", "win_rate"), ("draw", "draw_rate"), ("loss", "loss_rate")]:
        counts = df[df["result"] == res].groupby(["opening", "eco"], observed=True).size()
        result = result.join(counts.rename(col), on=["opening", "eco"])
        result[col] = result[col].fillna(0) / result["n_games"]

    result["reliable"] = result["n_games"] >= min_games
    result = result.sort_values("score_edge").reset_index(drop=True)

    return result


# ---------------------------------------------------------------------------
# 2. Performance by game length (move count)
# ---------------------------------------------------------------------------

def performance_by_move_count(df: pd.DataFrame) -> pd.DataFrame:
    """Win rate and score edge by number of moves, split into buckets.

    Answers: do I collapse in long games?  Do I win quick but lose long?

    Buckets are chosen to have roughly even game counts rather than even
    move-count widths — a 10-move bucket and a 80-move bucket would have
    very different sample sizes otherwise.

    Columns returned:
      move_bucket      str   | e.g. '1–20 moves'
      n_games          int   |
      win_rate         float |
      draw_rate        float |
      loss_rate        float |
      avg_score        float |
      avg_expected     float |
      score_edge       float |
      reliable         bool  |
    """
    df = add_derived_columns(df)
    df = df.dropna(subset=["my_rating", "opp_rating"])
    df = df[df["num_moves"] > 0]

    bins   = [0, 15, 25, 35, 50, 70, np.inf]
    labels = ["0-15 moves", "16-25", "26-35", "36-50", "51-70", "71+"]
    df = df.copy()
    df["move_bucket"] = pd.cut(df["num_moves"], bins=bins, labels=labels)

    grp = df.groupby("move_bucket", observed=True)
    result = grp.agg(
        n_games=("score", "count"),
        avg_score=("score", "mean"),
        avg_expected=("expected_score", "mean"),
    ).reset_index()

    result["score_edge"] = result["avg_score"] - result["avg_expected"]

    for res, col in [("win", "win_rate"), ("draw", "draw_rate"), ("loss", "loss_rate")]:
        counts = df[df["result"] == res].groupby("move_bucket", observed=True).size()
        result = result.join(counts.rename(col), on="move_bucket")
        result[col] = result[col].fillna(0) / result["n_games"]

    result["reliable"] = result["n_games"] >= MIN_SAMPLE
    return result


# ---------------------------------------------------------------------------
# 3. Win/draw/loss breakdown by color, time control, and rating bucket
# ---------------------------------------------------------------------------

def performance_by_color(df: pd.DataFrame) -> pd.DataFrame:
    """Win/draw/loss rates split by color.

    Most players have a meaningful white vs. black split — white has the
    first-move advantage.  Small datasets can make this noisy; check n_games.
    """
    df = add_derived_columns(df)
    df = df.dropna(subset=["my_rating", "opp_rating"])

    grp = df.groupby("color", observed=True)
    result = grp.agg(
        n_games=("score", "count"),
        avg_score=("score", "mean"),
        avg_expected=("expected_score", "mean"),
    ).reset_index()
    result["score_edge"] = result["avg_score"] - result["avg_expected"]

    for res, col in [("win", "win_rate"), ("draw", "draw_rate"), ("loss", "loss_rate")]:
        counts = df[df["result"] == res].groupby("color", observed=True).size()
        result = result.join(counts.rename(col), on="color")
        result[col] = result[col].fillna(0) / result["n_games"]

    return result


def performance_by_time_control(df: pd.DataFrame) -> pd.DataFrame:
    """Win/draw/loss rates split by time category (bullet / blitz / rapid)."""
    df = add_derived_columns(df)
    df = df.dropna(subset=["my_rating", "opp_rating"])

    grp = df.groupby("time_category", observed=True)
    result = grp.agg(
        n_games=("score", "count"),
        avg_score=("score", "mean"),
        avg_expected=("expected_score", "mean"),
    ).reset_index()
    result["score_edge"] = result["avg_score"] - result["avg_expected"]

    for res, col in [("win", "win_rate"), ("draw", "draw_rate"), ("loss", "loss_rate")]:
        counts = df[df["result"] == res].groupby("time_category", observed=True).size()
        result = result.join(counts.rename(col), on="time_category")
        result[col] = result[col].fillna(0) / result["n_games"]

    result["reliable"] = result["n_games"] >= MIN_SAMPLE
    return result.sort_values("n_games", ascending=False).reset_index(drop=True)


def performance_by_rating_bucket(df: pd.DataFrame) -> pd.DataFrame:
    """Win/draw/loss rates by opponent strength relative to us.

    This answers: do I beat the people I'm supposed to beat?  Do I punch
    above my weight against stronger players?
    """
    df = add_derived_columns(df)
    df = df.dropna(subset=["my_rating", "opp_rating"])

    grp = df.groupby("rating_bucket", observed=True)
    result = grp.agg(
        n_games=("score", "count"),
        avg_score=("score", "mean"),
        avg_expected=("expected_score", "mean"),
    ).reset_index()
    result["score_edge"] = result["avg_score"] - result["avg_expected"]

    for res, col in [("win", "win_rate"), ("draw", "draw_rate"), ("loss", "loss_rate")]:
        counts = df[df["result"] == res].groupby("rating_bucket", observed=True).size()
        result = result.join(counts.rename(col), on="rating_bucket")
        result[col] = result[col].fillna(0) / result["n_games"]

    result["reliable"] = result["n_games"] >= MIN_SAMPLE
    return result


# ---------------------------------------------------------------------------
# 4. Rating trajectory over time
# ---------------------------------------------------------------------------

def rating_trajectory(df: pd.DataFrame, rolling_window: int = 20) -> pd.DataFrame:
    """Return rating over time with a rolling average to smooth noise.

    Chess ratings are noisy game-to-game.  A 20-game rolling mean reveals
    the actual trend without being swamped by variance.

    Columns returned:
      date             datetime |
      my_rating        int      | raw rating at that game
      rolling_avg      float    | rolling mean over last `rolling_window` games
      time_category    str      | for optional color-coding by time control
    """
    df = add_derived_columns(df)
    df = df.dropna(subset=["my_rating"]).sort_values("date").reset_index(drop=True)

    result = df[["date", "my_rating", "time_category"]].copy()
    result["rolling_avg"] = result["my_rating"].rolling(window=rolling_window, min_periods=1).mean()

    return result


# ---------------------------------------------------------------------------
# 5. Summary stats — single dict for the dashboard header
# ---------------------------------------------------------------------------

def summary_stats(df: pd.DataFrame) -> dict:
    """Return a dict of top-level numbers for the dashboard summary card."""
    df = add_derived_columns(df)
    rated = df.dropna(subset=["my_rating", "opp_rating"])

    total = len(df)
    wins  = (df["result"] == "win").sum()
    draws = (df["result"] == "draw").sum()
    losses= (df["result"] == "loss").sum()

    return {
        "total_games":   int(total),
        "wins":          int(wins),
        "draws":         int(draws),
        "losses":        int(losses),
        "win_rate":      round(wins / total, 3) if total else 0,
        "peak_rating":   int(rated["my_rating"].max()) if len(rated) else None,
        "current_rating":int(rated.sort_values("date")["my_rating"].iloc[-1]) if len(rated) else None,
        "date_range":    (df["date"].min(), df["date"].max()),
        "avg_game_length": round(df["num_moves"].mean(), 1),
        "note": (
            f"Based on {total} rated games.  "
            f"Results with fewer than {MIN_SAMPLE} games are flagged as unreliable."
        ),
    }
