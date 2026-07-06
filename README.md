# Chess Performance Analyzer

A personal analytics tool for competitive chess players. It pulls your game history from Chess.com (and optionally Lichess), parses it into a clean dataset, and surfaces insights that actually matter to a player trying to improve: which openings are quietly costing you rating, whether you fall apart in short or long games, and how you really perform against stronger versus weaker opponents.

The guiding principle throughout is **honest statistics**. Chess game samples are small, and raw win rates are misleading without accounting for opponent strength. Every metric here is reported with its sample size, and results computed from too few games are flagged rather than hidden.

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)

## What it does

- **Rating trajectory** — your rating over time with a rolling average to reveal the real trend under the noise.
- **Opening analysis, Elo-adjusted** — instead of raw win rate per opening (which unfairly punishes openings you happen to play against stronger players), it compares your actual score to what your rating *predicts* you should score. A negative "score edge" means you're genuinely underperforming in that opening.
- **Game-length performance** — do you win quick and lose long, or grind out wins in the endgame? Bucketed by move count and controlled for opponent strength.
- **Breakdowns** — win/draw/loss by color, by time control (bullet/blitz/rapid/classical), and by opponent strength relative to you.

## Quick start

```bash
git clone https://github.com/skylorchan/chess-performance-analyzer
cd chess-performance-analyzer

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### Run the dashboard

```bash
streamlit run app.py
```

Then enter your Chess.com username in the sidebar and click **Analyze**. The first run fetches your archives from the API (a few seconds for a few hundred games); subsequent runs are instant because responses are cached locally.

### Use the pipeline directly in Python

```python
from chess_analyzer.parser import load_games
from chess_analyzer.analysis import opening_performance, summary_stats

df = load_games("your_username", platform="chesscom")
print(summary_stats(df))
print(opening_performance(df).head(10))   # worst openings first
```

## Project structure

```
chess_analyzer/
├── app.py                   # Streamlit dashboard (Phase 3)
├── chess_analyzer/
│   ├── fetcher.py           # API calls + local response cache (Phase 1)
│   ├── parser.py            # PGN → clean DataFrame           (Phase 1)
│   └── analysis.py          # all statistics                  (Phase 2)
├── tests/
│   ├── test_parser.py       # parsing + field extraction
│   ├── test_analysis.py     # every analysis calculation
│   └── test_fetcher.py      # cache logic
├── data/cache/              # cached API responses (git-ignored)
├── requirements.txt
└── README.md
```

The split between `fetcher` (network), `parser` (pure transformation), and `analysis` (pure statistics) is deliberate: the parser and analysis modules touch no network, so they're fully unit-testable without mocking HTTP. Run `python -m pytest tests/` to see 42 tests pass in about six seconds.

## Design decisions

These are the choices I'd want to be able to defend in an interview.

**Score edge instead of raw win rate.** Raw win rate per opening is the number everyone shows, and it's misleading. If you only play the Sicilian against opponents rated 150 points above you, it'll look terrible even if you're playing it well. So the core metric is `score_edge = your_actual_score − your_Elo_expected_score`, where expected score comes from the standard FIDE formula `1 / (1 + 10^(−ratingDiff/400))`. Zero means you performed exactly as your rating predicts; negative means you lost more than the rating gap explains. This is the honest way to attribute results to an opening rather than to the strength of who you faced.

**What the Elo expectation does and doesn't mean.** The formula gives a *long-run average* win probability, not a per-game prediction. Averaged over dozens of games in a bucket it's a fair benchmark; for a single game it says little. The code and docstrings are explicit about this so the number isn't over-read.

**A minimum-sample threshold, surfaced rather than hidden.** With a few hundred games spread across dozens of openings, most openings have only a handful of games. Rather than silently dropping thin buckets (hiding information) or presenting them at face value (implying false confidence), results below `MIN_SAMPLE = 10` games are marked with a `reliable` flag and grayed out in the dashboard. You can still see them; you're just warned.

**`python-chess` for PGN parsing, not regex.** PGNs contain comments, clock annotations (`{[%clk 0:09:45]}`), and move-number formatting that a naive string split miscounts. `python-chess` builds the real game tree, so move counts and results are correct.

**Caching by URL hash, with a current-month rule.** Chess.com organizes archives by calendar month, and a completed month never changes. Each API response is cached to disk keyed by the MD5 of its URL; past months are served from cache forever, while the current (still-being-played) month is always re-fetched. This keeps the tool fast and polite to the API without ever serving stale complete data.

**Openings recovered from `[ECOUrl]`.** Chess.com doesn't include the standard `[Opening]` PGN header, but it does include an `[ECOUrl]` whose path encodes the name (`.../openings/Modern-Defense...`). The parser extracts the name from there, so every game gets a readable opening even though the conventional header is missing.

## Limitations (read these)

I'd rather state these plainly than have someone assume the tool claims more than it does.

- **The opening name comes from the platform's classifier, not the moves.** It reflects however Chess.com labeled the position, which can be generic or off for unusual move orders. It's good enough for aggregate trends, not for fine opening-theory work.
- **No engine analysis.** This tool measures *results*, not move quality. It can tell you that you underperform in short games; it can't tell you *why* (a blunder-rate analysis would need Stockfish evaluation of every position, which is out of scope here).
- **Elo expected score assumes both ratings are accurate and comparable.** Provisional ratings, rating deflation across time-control pools, and sandbagging opponents all violate this to some degree.
- **Small samples are still small even when flagged.** The `reliable` flag at n≥10 is a pragmatic line, not a significance test. Ten games is enough to notice a trend worth watching, not enough to prove one.
- **Lichess game streaming is not cached.** Lichess returns games as a stream, so unlike Chess.com those responses aren't written to disk; a large Lichess history re-fetches each run.
- **Rate limits are handled by politeness, not backoff.** The fetcher sleeps between requests (0.5s Chess.com, 1s Lichess), which has been reliable in practice, but there's no exponential-backoff retry on a 429. For personal-scale use this is fine.

## Testing

```bash
python -m pytest tests/ -v
```

42 tests cover PGN field extraction (ratings, dates, time controls, result-from-perspective, opening-name recovery), every analysis calculation (score mapping, Elo expectation, sort order, sample-size flagging, rate sums), and the fetcher's cache round-trip and current-month logic. All run offline — no network required.

## Tech stack

Python 3.11+ · `requests` · `pandas` · `python-chess` · `streamlit` · `plotly`

Dependencies were kept deliberately minimal and standard.
