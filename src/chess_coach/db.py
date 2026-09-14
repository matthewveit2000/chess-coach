"""SQLite storage.

One file at data/games.db holds everything: raw games, engine evaluations, and
generated puzzles. SQLite because it needs no server, the whole database is a
single file you can copy or delete, and pandas reads from it directly.

Schema notes:
  games        - one row per game, source-agnostic. PGN kept verbatim so any
                 future analysis can be re-derived without re-downloading.
  move_evals   - one row per ply, the output of an engine pass over a game.
  puzzles      - positions worth re-practicing, generated from move_evals.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id         TEXT PRIMARY KEY,   -- "{source}:{source_game_id}"
    source          TEXT NOT NULL,
    source_game_id  TEXT NOT NULL,
    url             TEXT,
    played_at       TEXT,               -- ISO-8601 UTC
    time_class      TEXT,               -- bullet | blitz | rapid | daily
    time_control    TEXT,
    rated           INTEGER,
    eco             TEXT,
    opening_name    TEXT,
    opening_family  TEXT,               -- normalized grouping, e.g. "Sicilian Defense"
    white_user      TEXT,
    black_user      TEXT,
    white_rating    INTEGER,
    black_rating    INTEGER,
    result          TEXT,               -- "1-0" | "0-1" | "1/2-1/2"
    termination     TEXT,
    my_color        TEXT,               -- white | black
    my_rating       INTEGER,
    opp_rating      INTEGER,
    my_score        REAL,               -- 1.0 win, 0.5 draw, 0.0 loss
    ply_count       INTEGER,
    pgn             TEXT NOT NULL,
    fetched_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_games_played  ON games(played_at);
CREATE INDEX IF NOT EXISTS idx_games_opening ON games(opening_family);

CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    engine      TEXT NOT NULL,
    depth       INTEGER NOT NULL,
    multipv     INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE(game_id)                     -- one current analysis per game
);

CREATE TABLE IF NOT EXISTS move_evals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    ply             INTEGER NOT NULL,   -- 0-based index of the move in the game
    move_number     INTEGER NOT NULL,   -- 1-based chess move number
    color           TEXT NOT NULL,      -- white | black
    is_mine         INTEGER NOT NULL,
    phase           TEXT NOT NULL,      -- opening | middlegame | endgame
    fen_before      TEXT NOT NULL,
    san             TEXT NOT NULL,      -- the move actually played
    uci             TEXT NOT NULL,
    cp_before       INTEGER,            -- eval of fen_before, mover's POV, centipawns
    mate_before     INTEGER,
    cp_after        INTEGER,            -- eval after the played move, same POV
    mate_after      INTEGER,
    win_before      REAL,               -- winning chances 0-1, mover's POV
    win_after       REAL,
    win_loss        REAL,               -- win_before - win_after, >= 0
    cpl             INTEGER,            -- centipawn loss, clamped
    best_san        TEXT,
    best_uci        TEXT,
    best_pv         TEXT,               -- space-separated SAN of the engine's line
    alt_lines       TEXT,               -- JSON: other multipv lines
    classification  TEXT,               -- best | good | inaccuracy | mistake | blunder
    was_decided     INTEGER NOT NULL,   -- position already won/lost before the move
    motifs          TEXT,               -- JSON list of tactical/positional tags
    UNIQUE(game_id, ply)
);

CREATE INDEX IF NOT EXISTS idx_evals_game  ON move_evals(game_id);
CREATE INDEX IF NOT EXISTS idx_evals_class ON move_evals(classification, is_mine);

CREATE TABLE IF NOT EXISTS puzzles (
    puzzle_id    TEXT PRIMARY KEY,
    source       TEXT NOT NULL,         -- "own_game" | "lichess_db"
    game_id      TEXT,                  -- set when derived from your own game
    ply          INTEGER,
    fen          TEXT NOT NULL,         -- position to solve, side to move = you
    solution_uci TEXT NOT NULL,         -- space-separated engine principal variation
    solution_san TEXT,
    played_san   TEXT,                  -- what you actually played, if from a game
    themes       TEXT,                  -- JSON list
    win_swing    REAL,                  -- winning chances at stake
    rating       INTEGER,               -- Lichess puzzles only
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_puzzles_source ON puzzles(source);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def game_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]


def analyzed_game_ids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT game_id FROM analysis_runs").fetchall()
    return {r[0] for r in rows}


def unanalyzed_games(conn: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    sql = """
        SELECT g.* FROM games g
        LEFT JOIN analysis_runs r ON r.game_id = g.game_id
        WHERE r.run_id IS NULL
        ORDER BY g.played_at DESC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql).fetchall()
