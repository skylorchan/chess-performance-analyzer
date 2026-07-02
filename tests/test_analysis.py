"""Tests for chess_analyzer.analysis — uses a synthetic DataFrame, no network."""

import pandas as pd
import pytest
from datetime import datetime
from chess_analyzer.analysis import (
    add_derived_columns,
    opening_performance,
    performance_by_color,
    performance_by_time_control,
    performance_by_move_count,
    rating_trajectory,
    summary_stats,
    MIN_SAMPLE,
)


def make_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal DataFrame in the shape parser.py produces."""
    defaults = {
        "date": datetime(2024, 1, 1),
        "platform": "chesscom",
        "game_url": "",
        "color": "white",
        "result": "win",
        "my_rating": 1500,
        "opp_rating": 1500,
        "time_control": "600",
        "base_seconds": 600,
        "increment_secs": 0,
        "eco": "A00",
        "opening": "Test Opening",
        "num_moves": 30,
        "termination": "Normal",
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


# ---------------------------------------------------------------------------
# add_derived_columns
# ---------------------------------------------------------------------------

class TestAddDerivedColumns:
    def test_score_mapping(self):
        df = make_df([
            {"result": "win"},
            {"result": "draw"},
            {"result": "loss"},
        ])
        out = add_derived_columns(df)
        assert list(out["score"]) == [1.0, 0.5, 0.0]

    def test_rating_diff(self):
        df = make_df([{"my_rating": 1600, "opp_rating": 1400}])
        out = add_derived_columns(df)
        assert out["rating_diff"].iloc[0] == 200

    def test_expected_score_even(self):
        # Same rating → expected score = 0.5
        df = make_df([{"my_rating": 1500, "opp_rating": 1500}])
        out = add_derived_columns(df)
        assert abs(out["expected_score"].iloc[0] - 0.5) < 1e-9

    def test_expected_score_higher_rated(self):
        # Higher-rated player should have expected score > 0.5
        df = make_df([{"my_rating": 1700, "opp_rating": 1500}])
        out = add_derived_columns(df)
        assert out["expected_score"].iloc[0] > 0.5

    def test_time_categories(self):
        df = make_df([
            {"base_seconds": 60},    # bullet
            {"base_seconds": 300},   # blitz
            {"base_seconds": 600},   # rapid
            {"base_seconds": 3600},  # classical
        ])
        out = add_derived_columns(df)
        assert list(out["time_category"]) == ["bullet", "blitz", "rapid", "classical"]


# ---------------------------------------------------------------------------
# opening_performance
# ---------------------------------------------------------------------------

class TestOpeningPerformance:
    def _make_opening_df(self):
        # 15 games of Opening A: all wins vs equal opponents → positive edge
        # 15 games of Opening B: all losses vs equal opponents → negative edge
        rows = (
            [{"opening": "Opening A", "eco": "A00", "result": "win",
              "my_rating": 1500, "opp_rating": 1500}] * 15
            + [{"opening": "Opening B", "eco": "B00", "result": "loss",
                "my_rating": 1500, "opp_rating": 1500}] * 15
        )
        return make_df(rows)

    def test_score_edge_direction(self):
        df = self._make_opening_df()
        result = opening_performance(df, min_games=5)
        a = result[result["opening"] == "Opening A"]["score_edge"].iloc[0]
        b = result[result["opening"] == "Opening B"]["score_edge"].iloc[0]
        assert a > 0
        assert b < 0

    def test_sort_order_worst_first(self):
        df = self._make_opening_df()
        result = opening_performance(df, min_games=5)
        edges = result["score_edge"].tolist()
        assert edges == sorted(edges)

    def test_reliable_flag(self):
        df = self._make_opening_df()
        result = opening_performance(df, min_games=15)
        assert result["reliable"].all()
        result2 = opening_performance(df, min_games=20)
        assert not result2["reliable"].any()

    def test_win_loss_rates_sum_to_one(self):
        df = self._make_opening_df()
        result = opening_performance(df, min_games=5)
        totals = result["win_rate"] + result["draw_rate"] + result["loss_rate"]
        assert (totals.round(10) == 1.0).all()


# ---------------------------------------------------------------------------
# performance_by_color
# ---------------------------------------------------------------------------

class TestPerformanceByColor:
    def test_columns_present(self):
        df = make_df([{"color": "white"}, {"color": "black"}])
        result = performance_by_color(df)
        for col in ["color", "n_games", "win_rate", "score_edge"]:
            assert col in result.columns

    def test_both_colors_present(self):
        df = make_df([{"color": "white"}, {"color": "black"}])
        result = performance_by_color(df)
        assert set(result["color"]) == {"white", "black"}


# ---------------------------------------------------------------------------
# performance_by_time_control
# ---------------------------------------------------------------------------

class TestPerformanceByTimeControl:
    def test_blitz_and_rapid(self):
        df = make_df([
            {"base_seconds": 300},  # blitz
            {"base_seconds": 600},  # rapid
        ])
        result = performance_by_time_control(df)
        cats = set(result["time_category"])
        assert "blitz" in cats
        assert "rapid" in cats


# ---------------------------------------------------------------------------
# rating_trajectory
# ---------------------------------------------------------------------------

class TestRatingTrajectory:
    def test_rolling_avg_monotone_increase(self):
        # All ratings increasing → rolling avg should also increase
        rows = [{"my_rating": 1400 + i * 10, "date": datetime(2024, 1, i + 1)}
                for i in range(20)]
        df = make_df(rows)
        result = rating_trajectory(df, rolling_window=5)
        avg = result["rolling_avg"].tolist()
        assert avg[-1] > avg[0]

    def test_output_columns(self):
        df = make_df([{"my_rating": 1500}])
        result = rating_trajectory(df)
        for col in ["date", "my_rating", "rolling_avg", "time_category"]:
            assert col in result.columns


# ---------------------------------------------------------------------------
# summary_stats
# ---------------------------------------------------------------------------

class TestSummaryStats:
    def test_counts(self):
        df = make_df([
            {"result": "win"},
            {"result": "win"},
            {"result": "loss"},
            {"result": "draw"},
        ])
        s = summary_stats(df)
        assert s["total_games"] == 4
        assert s["wins"] == 2
        assert s["losses"] == 1
        assert s["draws"] == 1
        assert abs(s["win_rate"] - 0.5) < 1e-9
