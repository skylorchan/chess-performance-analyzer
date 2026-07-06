"""Tests for chess_analyzer.fetcher — cache logic only, no live network calls.

The network functions (fetch_chesscom_games / fetch_lichess_games) are thin
wrappers over requests and are exercised end-to-end by manual runs.  Here we
test the pure logic that's worth locking down: cache keys, cache round-trips,
and the current-month rule that decides whether a response is cacheable.
"""

import json
from datetime import datetime

import pytest

from chess_analyzer import fetcher


class TestCacheKey:
    def test_deterministic(self):
        # Same URL always maps to the same cache file.
        k1 = fetcher._cache_key("https://api.chess.com/pub/player/x/games/2024/01")
        k2 = fetcher._cache_key("https://api.chess.com/pub/player/x/games/2024/01")
        assert k1 == k2

    def test_distinct_urls_distinct_keys(self):
        k1 = fetcher._cache_key("https://api.chess.com/a")
        k2 = fetcher._cache_key("https://api.chess.com/b")
        assert k1 != k2


class TestCacheRoundTrip:
    def test_save_then_load(self, tmp_path, monkeypatch):
        # Point the cache at a temp dir so we don't touch the real one.
        monkeypatch.setattr(fetcher, "CACHE_DIR", tmp_path)

        url = "https://api.chess.com/pub/player/test/games/2024/01"
        payload = {"games": [{"pgn": "sample"}]}

        assert fetcher._load_cache(url) is None  # nothing cached yet
        fetcher._save_cache(url, payload)
        assert fetcher._load_cache(url) == payload

    def test_miss_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fetcher, "CACHE_DIR", tmp_path)
        assert fetcher._load_cache("https://api.chess.com/never/cached") is None


class TestIsCurrentMonth:
    def test_current_month_true(self):
        now = datetime.utcnow()
        assert fetcher._is_current_month(now.year, now.month) is True

    def test_past_month_false(self):
        assert fetcher._is_current_month(2000, 1) is False
