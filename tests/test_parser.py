"""Tests for chess_analyzer.parser — no network calls required."""

import pytest
import pandas as pd
from chess_analyzer.parser import (
    _parse_rating,
    _parse_date,
    _parse_time_control,
    _result_from_perspective,
    _opening_from_eco_url,
    pgns_to_dataframe,
)
from datetime import datetime

# ---------------------------------------------------------------------------
# Unit tests for individual helpers
# ---------------------------------------------------------------------------

class TestParseRating:
    def test_normal_rating(self):
        assert _parse_rating("1500") == 1500

    def test_question_mark(self):
        assert _parse_rating("?") is None

    def test_empty_string(self):
        assert _parse_rating("") is None

    def test_dash(self):
        assert _parse_rating("-") is None


class TestParseDate:
    def test_full_date(self):
        assert _parse_date("2023.11.05") == datetime(2023, 11, 5)

    def test_unknown_day(self):
        result = _parse_date("2023.11.??")
        assert result == datetime(2023, 11, 1)

    def test_fully_unknown(self):
        assert _parse_date("????.??.??") is None


class TestParseTimeControl:
    def test_base_only(self):
        assert _parse_time_control("600") == (600, 0)

    def test_base_plus_increment(self):
        assert _parse_time_control("600+5") == (600, 5)

    def test_untimed(self):
        assert _parse_time_control("-") == (0, 0)

    def test_bullet(self):
        assert _parse_time_control("60+0") == (60, 0)


class TestResultFromPerspective:
    def test_white_wins_as_white(self):
        assert _result_from_perspective("1-0", "white") == "win"

    def test_white_wins_as_black(self):
        assert _result_from_perspective("1-0", "black") == "loss"

    def test_draw(self):
        assert _result_from_perspective("1/2-1/2", "white") == "draw"
        assert _result_from_perspective("1/2-1/2", "black") == "draw"


# ---------------------------------------------------------------------------
# Integration test: parse a minimal PGN string
# ---------------------------------------------------------------------------

SAMPLE_PGN = """\
[Event "Live Chess"]
[Site "https://www.chess.com/game/live/12345"]
[Date "2024.01.15"]
[White "testplayer"]
[Black "opponent123"]
[Result "1-0"]
[WhiteElo "1450"]
[BlackElo "1480"]
[TimeControl "600"]
[ECO "B20"]
[Opening "Sicilian Defense"]
[Termination "testplayer won on time"]

1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 *
"""


class TestOpeningFromEcoUrl:
    def test_typical_url(self):
        url = "https://www.chess.com/openings/Modern-Defense...5.e3-c5-6.Be2-cxd4-7.exd4"
        assert _opening_from_eco_url(url) == "Modern Defense"

    def test_multi_word(self):
        url = "https://www.chess.com/openings/Queens-Pawn-Opening-Chigorin-Variation...2.Nc3"
        assert _opening_from_eco_url(url) == "Queens Pawn Opening Chigorin Variation"

    def test_empty_string(self):
        assert _opening_from_eco_url("") == ""

    def test_no_moves_suffix(self):
        url = "https://www.chess.com/openings/Sicilian-Defense"
        assert _opening_from_eco_url(url) == "Sicilian Defense"


class TestPgnsToDataframe:
    def test_basic_parse(self):
        df = pgns_to_dataframe([SAMPLE_PGN], "testplayer")
        assert len(df) == 1
        row = df.iloc[0]
        assert row["color"] == "white"
        assert row["result"] == "win"
        assert row["my_rating"] == 1450
        assert row["opp_rating"] == 1480
        assert row["eco"] == "B20"
        assert row["opening"] == "Sicilian Defense"
        assert row["base_seconds"] == 600
        assert row["increment_secs"] == 0

    def test_wrong_username_skipped(self):
        df = pgns_to_dataframe([SAMPLE_PGN], "notaplayer")
        assert len(df) == 0

    def test_returns_dataframe(self):
        df = pgns_to_dataframe([SAMPLE_PGN], "testplayer")
        assert isinstance(df, pd.DataFrame)
        assert "date" in df.columns
