# Chess Performance Analyzer

A personal analytics tool for competitive chess players. Pulls your game history from Chess.com and/or Lichess, parses it into structured data, and surfaces insights you actually care about: which openings cost you rating, where your performance degrades, and how you compare against different opponent strength brackets.

> Work in progress — built in phases. See below for current status.

## Current status

- [x] Phase 1: Data ingestion (fetcher + parser)
- [ ] Phase 2: Analysis module
- [ ] Phase 3: Streamlit dashboard
- [ ] Phase 4: Tests, docstrings, final README

## Quick start

```bash
git clone https://github.com/YOUR_USERNAME/chess-analyzer
cd chess-analyzer

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### Try the ingestion pipeline

```python
from chess_analyzer.parser import load_games

df = load_games("your_chesscom_username", platform="chesscom")
print(df.head())
print(df.dtypes)
```

### Run the tests

```bash
python -m pytest tests/
```

## Project structure

```
chess_analyzer/
├── chess_analyzer/
│   ├── fetcher.py   # API calls + local cache
│   ├── parser.py    # PGN → DataFrame
│   ├── analysis.py  # (Phase 2)
│   └── dashboard.py # (Phase 3)
├── data/
│   └── cache/       # cached API responses (git-ignored)
├── tests/
│   └── test_parser.py
├── requirements.txt
└── README.md
```

## Design decisions

**Caching:** Raw API responses are cached as JSON files keyed by MD5 of the URL. Past months are treated as immutable; the current month is always re-fetched. This means you can run the tool repeatedly without hammering the API.

**PGN parsing:** Uses `python-chess` rather than a hand-rolled regex parser. PGNs contain comments, annotations, and clock data that a naive split would miscount.

**Ratings:** Chess.com uses `?` for unrated games. These are stored as `None` and excluded from rating-adjusted analysis.

## Limitations

- Chess.com rate limits are not documented publicly. The fetcher sleeps 0.5 s between requests, which has worked reliably in practice.
- Lichess game streaming is not cached (responses are streamed line-by-line). If you have tens of thousands of games, the initial fetch takes a few minutes.
- Opening attribution comes from the PGN `[Opening]` header, which is set by the platform, not computed from the actual moves. Some short games may have generic or incorrect opening names.
