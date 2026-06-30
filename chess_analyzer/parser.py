"""
Parse raw PGN strings into a clean, structured pandas DataFrame.

One row per game.  Columns:

  date            datetime   | UTC date the game was played
  platform        str        | 'chesscom' or 'lichess'
  game_url        str        | link to the game (from [Site] header)
  color           str        | 'white' or 'black' (our perspective)
  result          str        | 'win', 'loss', or 'draw'
  my_rating       int|None   | our Elo at game start (None if unrated)
  opp_rating      int|None   | opponent Elo at game start
  time_control    str        | raw time-control string, e.g. '600+5'
  base_seconds    int        | base clock in seconds (e.g. 600)
  increment_secs  int        | per-move increment in seconds (0 if none)
  eco             str        | ECO opening code, e.g. 'B20'
  opening         str        | human-readable opening name
  num_moves       int        | number of full moves (half-moves / 2)
  termination     str        | how the game ended ('Normal', 'Time forfeit', …)

Messy-PGN notes (see inline comments for detail):
  - Ratings: Chess.com uses '?' for unrated games → stored as None.
  - Dates: PGN uses YYYY.MM.DD with '??' for unknown parts → best-effort parse.
  - Openings: Chess.com does not include [Opening] in PGN headers, but does
    include [ECOUrl] whose path encodes the name (e.g. "Modern-Defense").  We
    extract it from there.  Lichess includes [Opening] directly if the opening
    flag is set on the API call.  Missing → empty string.
  - Move count: We walk the game tree rather than counting text tokens because
    PGN comments and annotations would throw off a naive split.
  - Some PGNs have no moves at all (abandoned before move 1) → num_moves = 0.
  - python-chess raises ValueError on genuinely corrupt PGNs; we skip those.
"""

import io
import logging
import re
from datetime import datetime

import chess.pgn
import pandas as pd

logger = logging.getLogger(__name__)

# Matches '600', '600+5', '60+0', etc.
_TIME_CTRL_RE = re.compile(r"^(\d+)(?:\+(\d+))?$")


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _parse_rating(raw: str) -> int | None:
    """Convert a PGN Elo string to int, returning None for '?' or missing."""
    if not raw or raw.strip() in ("?", "-", ""):
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _parse_date(raw: str) -> datetime | None:
    """Parse a PGN date string like '2023.11.05' or '2023.??.??' as best we can."""
    if not raw or raw == "????.??.??":
        return None
    parts = raw.split(".")
    # Replace unknown parts with defaults so strptime doesn't choke.
    year = parts[0] if len(parts) > 0 and "?" not in parts[0] else "1900"
    month = parts[1] if len(parts) > 1 and "?" not in parts[1] else "01"
    day = parts[2] if len(parts) > 2 and "?" not in parts[2] else "01"
    try:
        return datetime(int(year), int(month), int(day))
    except ValueError:
        return None


def _parse_time_control(raw: str) -> tuple[int, int]:
    """Return (base_seconds, increment_secs) from a time-control string.

    Handles:
      '600'   → (600, 0)
      '600+5' → (600, 5)
      '-'     → (0, 0)  (untimed/correspondence)
    """
    if not raw or raw in ("-", ""):
        return 0, 0
    m = _TIME_CTRL_RE.match(raw.strip())
    if not m:
        return 0, 0
    base = int(m.group(1))
    inc = int(m.group(2)) if m.group(2) else 0
    return base, inc


def _count_moves(game: chess.pgn.Game) -> int:
    """Walk the mainline and count half-moves, then convert to full moves."""
    board = game.board()
    half_moves = 0
    node = game
    while node.variations:
        node = node.variation(0)
        half_moves += 1
    return half_moves // 2


def _opening_from_eco_url(eco_url: str) -> str:
    """Extract a human-readable opening name from Chess.com's [ECOUrl] header.

    Example URL:
      https://www.chess.com/openings/Modern-Defense...5.e3-c5-6.Be2-cxd4
    We take the path segment after '/openings/', strip the move sequence
    (everything from '...' onward), and replace hyphens with spaces.
    """
    if not eco_url:
        return ""
    try:
        # isolate the segment after '/openings/'
        path = eco_url.split("/openings/", 1)[1]
        # drop the move sequence that follows '...'
        name_part = path.split("...")[0]
        return name_part.replace("-", " ").strip()
    except (IndexError, AttributeError):
        return ""


def _infer_platform(site: str) -> str:
    s = site.lower()
    if "chess.com" in s or s == "chess.com":
        return "chesscom"
    if "lichess" in s:
        return "lichess"
    return "unknown"


def _result_from_perspective(pgn_result: str, color: str) -> str:
    """Map '1-0'/'0-1'/'1/2-1/2' to win/loss/draw from our perspective."""
    if pgn_result == "1/2-1/2":
        return "draw"
    if (pgn_result == "1-0" and color == "white") or (pgn_result == "0-1" and color == "black"):
        return "win"
    if pgn_result in ("1-0", "0-1"):
        return "loss"
    return "unknown"


# ---------------------------------------------------------------------------
# Single-game parser
# ---------------------------------------------------------------------------

def _parse_single_pgn(pgn_text: str, my_username: str) -> dict | None:
    """Parse one PGN string and return a dict of fields, or None on failure."""
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
    except Exception:
        return None

    if game is None:
        return None

    headers = game.headers

    white = headers.get("White", "")
    black = headers.get("Black", "")

    # Determine our color.  Chess.com lowercases usernames in some headers;
    # do a case-insensitive comparison to be safe.
    if my_username.lower() == white.lower():
        color = "white"
        my_rating = _parse_rating(headers.get("WhiteElo", ""))
        opp_rating = _parse_rating(headers.get("BlackElo", ""))
    elif my_username.lower() == black.lower():
        color = "black"
        my_rating = _parse_rating(headers.get("BlackElo", ""))
        opp_rating = _parse_rating(headers.get("WhiteElo", ""))
    else:
        # Username not found in this game — skip rather than guess.
        logger.debug("Username '%s' not in game (%s vs %s); skipping.", my_username, white, black)
        return None

    pgn_result = headers.get("Result", "*")
    result = _result_from_perspective(pgn_result, color)

    time_control_raw = headers.get("TimeControl", "")
    base_secs, inc_secs = _parse_time_control(time_control_raw)

    return {
        "date": _parse_date(headers.get("Date", "")),
        "platform": _infer_platform(headers.get("Site", "")),
        # Chess.com sets [Site] to "Chess.com" (not a URL); the actual link is in [Link].
        "game_url": headers.get("Link", "") or headers.get("Site", ""),
        "color": color,
        "result": result,
        "my_rating": my_rating,
        "opp_rating": opp_rating,
        "time_control": time_control_raw,
        "base_seconds": base_secs,
        "increment_secs": inc_secs,
        "eco": headers.get("ECO", ""),
        # Chess.com omits [Opening] but includes [ECOUrl]; Lichess includes [Opening] directly.
        "opening": headers.get("Opening", "") or _opening_from_eco_url(headers.get("ECOUrl", "")),
        "num_moves": _count_moves(game),
        "termination": headers.get("Termination", ""),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def pgns_to_dataframe(pgn_list: list[str], my_username: str) -> pd.DataFrame:
    """Parse a list of raw PGN strings into a clean DataFrame.

    Skips games that cannot be parsed or where my_username is not a player.
    Logs a warning if more than 5 % of games are skipped (a sign of a username
    mismatch or systematic PGN corruption).
    """
    rows = []
    skipped = 0

    for pgn_text in pgn_list:
        row = _parse_single_pgn(pgn_text, my_username)
        if row is None:
            skipped += 1
        else:
            rows.append(row)

    total = len(pgn_list)
    if total > 0 and skipped / total > 0.05:
        logger.warning(
            "%d / %d PGNs skipped (%.0f%%).  Check that the username matches "
            "what appears inside the PGN headers.",
            skipped, total, 100 * skipped / total,
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    logger.info("Parsed %d games (%d skipped).", len(df), skipped)
    return df


# ---------------------------------------------------------------------------
# Convenience loader: fetch + parse in one call
# ---------------------------------------------------------------------------

def load_games(
    username: str,
    platform: str = "chesscom",
    lichess_max: int = 5000,
) -> pd.DataFrame:
    """High-level helper: fetch from API, parse, return DataFrame.

    Args:
        username:    Your exact Chess.com or Lichess username.
        platform:    'chesscom', 'lichess', or 'both'.
        lichess_max: Cap on Lichess games fetched (streaming; can be slow).
    """
    from chess_analyzer.fetcher import fetch_chesscom_games, fetch_lichess_games

    all_pgns: list[str] = []

    if platform in ("chesscom", "both"):
        all_pgns.extend(fetch_chesscom_games(username))

    if platform in ("lichess", "both"):
        all_pgns.extend(fetch_lichess_games(username, max_games=lichess_max))

    return pgns_to_dataframe(all_pgns, username)
