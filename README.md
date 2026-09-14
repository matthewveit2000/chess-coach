# Chess Coach

An engine-backed chess coach. It pulls your real games, has Stockfish analyze
them, finds the mistakes you keep making, and turns those into practice.

## The design idea

The tool is split into two layers, and the split is deliberate:

| Layer | Does | Never does |
|---|---|---|
| **Python** (this package) | Fetches games, runs Stockfish, computes centipawn loss, classifies moves, tags motifs, aggregates trends | Decides whether a move is good |
| **AI** (Claude Code, Antigravity, any agent) | Reads the structured output, explains *why*, ties it to named theory, builds a study plan | Evaluates positions itself |

Stockfish decides what's good. The model only explains it. That means the
coaching advice is grounded in real evaluations rather than an LLM's vibes
about a position — and if you disagree with a claim, you can trace it back to
an engine number in the database.

## Everything it uses is free

| Need | Service | Cost | Auth |
|---|---|---|---|
| Your games | [Chess.com Published-Data API](https://www.chess.com/news/view/published-data-api) | Free | None |
| Your games | [Lichess API](https://lichess.org/api) | Free | Optional token |
| Move evaluation | [Stockfish](https://stockfishchess.org/) (GPL-3.0) | Free | Local binary |
| Puzzles | [Lichess puzzle database](https://database.lichess.org/#puzzles) (CC0) | Free | None |
| Opening reference | [Lichess Opening Explorer](https://lichess.org/analysis) | Free | None |

No API keys required to get started. No paid tiers anywhere.

## Setup

```bash
uv sync
uv run chess-coach setup-engine
cp config/config.example.toml config/config.toml
```

Then put your username in `config/config.toml`:

```toml
[player]
chesscom = "your_username_here"
```

## Use

```bash
# 1. Pull your games (nothing is analyzed yet, this is just download + store)
uv run chess-coach fetch --since 2026-01 --limit 50

# 2. Have Stockfish grade every move. This is the slow step:
#    ~2.5 min per 80-ply game at the default depth 16.
uv run chess-coach analyze --limit 20

# 3. Look at one game in detail
uv run chess-coach review --last
uv run chess-coach review --game-id chesscom:12345678

# 4. Find the patterns across all analyzed games
uv run chess-coach trends

# 5. Turn your own recurring mistakes into puzzles
uv run chess-coach puzzles generate
uv run chess-coach puzzles list --theme missed_fork

# 6. Write the full coaching brief for an AI to interpret
uv run chess-coach brief
```

Step 6 is the one that matters most. `brief` writes
`reports/coaching_brief.md` plus a machine-readable `reports/brief.json`. Point
any AI agent at the repo and ask it to coach you — the agent instructions in
[`CLAUDE.md`](CLAUDE.md) tell it how to read those files, what it may assert,
and what it must not.

## Where things live

```
src/chess_coach/
  sources/       Game providers. Add a site = add one fetch() function.
  engine.py      Stockfish wrapper. All move judgement comes from here.
  scoring.py     Centipawns -> winning chances -> move grades.
  motifs.py      Rule-based tagging of *what kind* of mistake was made.
  analyze.py     Walk a game, evaluate every position, grade every move.
  trends.py      Aggregate across games: openings, phases, recurring motifs.
  puzzles.py     Your own blunders as puzzles + Lichess puzzle DB lookup.
  report.py      Render the coaching brief.
data/            SQLite database, engine binary, puzzle DB. Gitignored.
reports/         Generated output. Gitignored.
docs/            Methodology, theory references, agent contract.
```

Your game data and analysis never leave this machine. `data/` and `reports/`
are gitignored, so committing the repo does not publish your games.

## Documentation

- [`docs/methodology.md`](docs/methodology.md) — how a move gets graded, and why
  centipawn loss alone is the wrong metric
- [`docs/references.md`](docs/references.md) — the authoritative sources the
  coaching layer is expected to cite
- [`AGENTS.md`](AGENTS.md) — the contract every AI tool follows in this repo

## License

MIT for this code. Stockfish is GPL-3.0 and is downloaded, not bundled.
