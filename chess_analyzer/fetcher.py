"""
Fetch game archives from Chess.com and Lichess public APIs.

Caching strategy
----------------
Each API response is written to data/cache/ as a JSON file named by the
MD5 of the request URL.  Completed past months are treated as immutable
and served from cache without a network call.  The current calendar month
is never cached because it is still being written.
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# Placed next to the project root (one level above this package directory).
CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"

# Chess.com asks bots to be polite; 0.5 s between requests is well within limits.
_CHESSCOM_DELAY = 0.5
# Lichess allows a generous rate limit but still deserves courtesy.
_LICHESS_DELAY = 1.0

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "chess-performance-analyzer/1.0 (personal project)"})


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_key(url: str) -> Path:
    """Map a request URL to its cache file path (MD5 of the URL)."""
    digest = hashlib.md5(url.encode()).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def _load_cache(url: str):
    """Return the cached JSON for a URL, or None if it isn't cached."""
    path = _cache_key(url)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _save_cache(url: str, data) -> None:
    """Write a response payload to the cache, creating the dir if needed."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_key(url).write_text(json.dumps(data), encoding="utf-8")


def _is_current_month(year: int, month: int) -> bool:
    """True if (year, month) is the current UTC month (never cache it)."""
    now = datetime.now(timezone.utc)
    return year == now.year and month == now.month


# ---------------------------------------------------------------------------
# Generic request wrapper
# ---------------------------------------------------------------------------

def _get_json(url: str, delay: float = _CHESSCOM_DELAY, cacheable: bool = True) -> dict:
    """GET a URL, returning parsed JSON.  Caches if cacheable=True."""
    if cacheable:
        cached = _load_cache(url)
        if cached is not None:
            logger.debug("Cache hit: %s", url)
            return cached

    logger.debug("Fetching: %s", url)
    time.sleep(delay)
    resp = _SESSION.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if cacheable:
        _save_cache(url, data)

    return data


def _get_ndjson(url: str, params: dict, delay: float = _LICHESS_DELAY) -> list[dict]:
    """GET a Lichess endpoint that streams newline-delimited JSON."""
    logger.debug("Fetching NDJSON: %s", url)
    time.sleep(delay)
    resp = _SESSION.get(
        url,
        params=params,
        headers={"Accept": "application/x-ndjson"},
        stream=True,
        timeout=60,
    )
    resp.raise_for_status()

    records = []
    for line in resp.iter_lines():
        if line:
            records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Chess.com
# ---------------------------------------------------------------------------

def fetch_chesscom_games(username: str) -> list[str]:
    """Return a flat list of raw PGN strings for all rated games on Chess.com.

    Chess.com organises archives by calendar month.  We fetch the archive
    index once (cached), then fetch each monthly bundle (cached for past
    months, live for the current month).
    """
    archive_url = f"https://api.chess.com/pub/player/{username}/games/archives"
    try:
        archive_index = _get_json(archive_url)
    except requests.HTTPError as exc:
        if exc.response.status_code == 404:
            raise ValueError(f"Chess.com user '{username}' not found.") from exc
        raise

    monthly_urls: list[str] = archive_index.get("archives", [])
    if not monthly_urls:
        logger.warning("No Chess.com archives found for %s", username)
        return []

    all_pgns: list[str] = []

    for url in monthly_urls:
        # URL format: .../games/YYYY/MM
        parts = url.rstrip("/").split("/")
        year, month = int(parts[-2]), int(parts[-1])
        cacheable = not _is_current_month(year, month)

        try:
            bundle = _get_json(url, cacheable=cacheable)
        except requests.HTTPError:
            logger.warning("Could not fetch %s — skipping.", url)
            continue

        for game in bundle.get("games", []):
            pgn = game.get("pgn", "").strip()
            if pgn:
                all_pgns.append(pgn)

    logger.info("Chess.com: fetched %d PGNs for %s", len(all_pgns), username)
    return all_pgns


# ---------------------------------------------------------------------------
# Lichess
# ---------------------------------------------------------------------------

def fetch_lichess_games(username: str, max_games: int = 5000) -> list[str]:
    """Return a flat list of raw PGN strings for games from Lichess.

    Lichess streams games as NDJSON.  Each record contains a 'pgn' field
    pre-formatted with headers.  We request rated games only and limit to
    max_games so the first run doesn't take forever.
    """
    url = f"https://lichess.org/api/games/user/{username}"
    params = {
        "rated": "true",
        "pgnInJson": "true",   # embed PGN inside each JSON record
        "opening": "true",     # include opening name in headers
        "max": max_games,
    }

    try:
        records = _get_ndjson(url, params)
    except requests.HTTPError as exc:
        if exc.response.status_code == 404:
            raise ValueError(f"Lichess user '{username}' not found.") from exc
        raise

    pgns = [r["pgn"] for r in records if "pgn" in r]

    # Lichess NDJSON is not cached (streaming response); cache is impractical
    # here without knowing how many records exist.  If offline use matters,
    # save the parsed DataFrame from parser.py instead.
    logger.info("Lichess: fetched %d PGNs for %s", len(pgns), username)
    return pgns
