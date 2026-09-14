# CLAUDE.md

**The agent contract for this repository is [`AGENTS.md`](AGENTS.md). Read it
before doing anything here.**

It is kept in `AGENTS.md` rather than inline so that Claude Code, Antigravity,
Cursor and Codex all follow identical rules instead of drifting apart. This
file only holds the Claude Code specifics.

## The short version

Stockfish decides whether a move is good. You explain what it decided. You
never evaluate a position from your own chess judgement — see AGENTS.md for
why, and for what you may and may not assert.

## Claude Code specifics

### Slash commands

- `/coach` — full loop: fetch anything new, analyze it, read the brief, and
  deliver a coaching session
- `/review-last` — deep review of the most recent game
- `/drill` — build a practice set from current weaknesses

They live in `.claude/commands/`.

### Long-running analysis

`chess-coach analyze` is CPU-bound: roughly 2.5 minutes per 80-ply game at the
default depth 16, so a 20-game batch is most of an hour. Run it with
`run_in_background: true`, tell Matthew roughly how long it will take, and do
not sit blocking on it.

It uses every core but one, and competing CPU work slows it disproportionately
-- a three-game batch that should have taken eight minutes took 29 when other
commands ran alongside it. While a batch is running, keep other work light.

Note that results are written to the database only when a game finishes
analyzing, so an empty `move_evals` table mid-run is expected, not a failure.
To check real progress, look for the `stockfish.exe` process.

### Reading results

Prefer `reports/brief.json` over the markdown — it carries the full structure
including FENs and engine lines. For anything the CLI does not expose, query
`data/games.db` directly with pandas. The schema in `src/chess_coach/db.py` is
meant to be queried.

### Environment

- `uv` for everything: `uv sync` to install, `uv run chess-coach ...` to run.
- Windows. Use PowerShell or Bash-tool syntax appropriately; the engine binary
  is `data/engine/stockfish.exe`.
- `data/` and `reports/` are gitignored and must stay that way. Matthew's game
  history is not repository content.
