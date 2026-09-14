"""Practice material, from two free sources.

1. Your own games. Every position where the engine says a clearly better move
   existed becomes a puzzle. These are the most valuable puzzles you will ever
   get, because they are positions you actually reached and actually got wrong.

2. The Lichess puzzle database (CC0, https://database.lichess.org/#puzzles).
   ~5 million puzzles, each tagged with themes and rated. Filtering it by the
   motifs you keep missing gives you volume on exactly your weak spots.

Source 1 is always available. Source 2 needs a one-time ~250MB download, so it
is opt-in. There is also a no-download option that pulls single puzzles from
the Lichess API by theme.

A note on the Lichess puzzle format, which trips people up: the stored FEN is
the position *before* the opponent's losing move. The first move in the Moves
column is that opponent move; the solution starts from the second. We normalize
that on import so every puzzle here means the same thing: "you are to move, find
the best move".
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.pgn
import requests

from .config import DATA_DIR

PUZZLE_DB_URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
PUZZLE_DB_PATH = DATA_DIR / "lichess_db_puzzle.csv.zst"
LICHESS_PUZZLE_API = "https://lichess.org/api/puzzle/next"

# Our motif tags -> Lichess puzzle themes. Approximate by nature: our tags are
# rules over engine output, theirs are crowd-curated. Good enough to point you
# at the right drill, not a formal equivalence.
MOTIF_TO_LICHESS_THEMES = {
    "missed_fork": ["fork"],
    "hangs_piece": ["hangingPiece"],
    "hangs_knight": ["hangingPiece"],
    "hangs_bishop": ["hangingPiece"],
    "hangs_rook": ["hangingPiece"],
    "hangs_queen": ["hangingPiece"],
    "missed_free_material": ["hangingPiece"],
    "missed_mate": ["mateIn2", "mateIn3"],
    "allowed_mate": ["defensiveMove"],
    "back_rank": ["backRankMate"],
    "missed_forcing_move": ["capturingDefender", "discoveredAttack"],
    "quiet_move_missed": ["quietMove"],
    "endgame_technique": ["endgame"],
    "king_safety": ["exposedKing"],
    "material_grab": ["trappedPiece"],
}


@dataclass
class Puzzle:
    puzzle_id: str
    source: str
    fen: str
    solution_uci: str
    solution_san: str = ""
    played_san: str = ""
    themes: list[str] | None = None
    win_swing: float | None = None
    rating: int | None = None
    game_id: str | None = None
    ply: int | None = None

    def lichess_url(self) -> str:
        """Open this position on the free Lichess analysis board.

        Lichess accepts the FEN with spaces as underscores. Percent-encoding
        works too but produces a link that wraps badly in a terminal.
        """
        return "https://lichess.org/analysis/" + self.fen.replace(" ", "_")


def themes_for_motifs(motifs: list[str]) -> list[str]:
    out: list[str] = []
    for motif in motifs:
        for theme in MOTIF_TO_LICHESS_THEMES.get(motif, []):
            if theme not in out:
                out.append(theme)
    return out


# --------------------------------------------------------------------------
# Source 1: your own games
# --------------------------------------------------------------------------

def generate_from_games(
    conn: sqlite3.Connection,
    min_win_loss: float = 0.15,
    include_decided: bool = False,
    limit: int | None = None,
) -> int:
    """Turn your own critical mistakes into puzzles. Returns the number stored.

    Only positions where the engine found a clearly better move qualify --
    if your move was near-best, there is nothing to practice.
    """
    sql = """
        SELECT m.*, g.url AS game_url
        FROM move_evals m
        JOIN games g ON g.game_id = m.game_id
        WHERE m.is_mine = 1
          AND m.win_loss >= ?
          AND m.best_uci != ''
          AND m.best_uci != m.uci
    """
    params: list = [min_win_loss]
    if not include_decided:
        sql += " AND m.was_decided = 0"
    sql += " ORDER BY m.win_loss DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"

    rows = conn.execute(sql, params).fetchall()
    puzzles = [
        Puzzle(
            puzzle_id=f"own:{r['game_id']}:{r['ply']}",
            source="own_game",
            fen=r["fen_before"],
            solution_uci=r["best_uci"],
            solution_san=r["best_pv"] or r["best_san"],
            played_san=r["san"],
            themes=json.loads(r["motifs"] or "[]"),
            win_swing=r["win_loss"],
            game_id=r["game_id"],
            ply=r["ply"],
        )
        for r in rows
    ]
    store(conn, puzzles)
    return len(puzzles)


# --------------------------------------------------------------------------
# Source 2: the Lichess puzzle database
# --------------------------------------------------------------------------

def download_puzzle_db(dest: Path = PUZZLE_DB_PATH, log=print) -> Path:
    """Fetch the compressed Lichess puzzle database (~250MB). One-time."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"Downloading {PUZZLE_DB_URL}")
    log("This is roughly 250MB compressed and is only needed once.")
    with requests.get(PUZZLE_DB_URL, stream=True, timeout=1800) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    log(f"  {done / 1_048_576:6.0f} / {total / 1_048_576:.0f} MB", end="\r")
    log(f"\nSaved to {dest}")
    return dest


def _normalize_lichess_puzzle(row: dict) -> Puzzle | None:
    """Apply the opponent's setup move so the FEN is the position you solve."""
    board = chess.Board(row["FEN"])
    moves = row["Moves"].split()
    if not moves:
        return None
    try:
        board.push_uci(moves[0])
    except ValueError:
        return None

    solution = moves[1:]
    if not solution:
        return None

    san_line, probe = [], board.copy(stack=False)
    for uci in solution:
        try:
            move = chess.Move.from_uci(uci)
            san_line.append(probe.san(move))
            probe.push(move)
        except (ValueError, AssertionError):
            break

    return Puzzle(
        puzzle_id=f"lichess:{row['PuzzleId']}",
        source="lichess_db",
        fen=board.fen(),
        solution_uci=" ".join(solution),
        solution_san=" ".join(san_line),
        themes=row.get("Themes", "").split(),
        rating=int(row["Rating"]) if row.get("Rating", "").isdigit() else None,
    )


def search_puzzle_db(
    themes: list[str],
    rating_range: tuple[int, int] = (0, 4000),
    limit: int = 20,
    db_path: Path = PUZZLE_DB_PATH,
    match_all: bool = False,
) -> list[Puzzle]:
    """Stream the compressed database and pull matching puzzles.

    Decompresses on the fly so the ~900MB uncompressed CSV never hits disk.
    """
    try:
        import zstandard
    except ImportError as exc:
        raise RuntimeError(
            "Reading the puzzle database needs the zstandard package:\n"
            "  uv sync --extra puzzles"
        ) from exc

    if not db_path.exists():
        raise FileNotFoundError(
            f"No puzzle database at {db_path}.\n"
            "Run:  uv run chess-coach puzzles download-db"
        )

    wanted = set(themes)
    lo, hi = rating_range
    found: list[Puzzle] = []

    dctx = zstandard.ZstdDecompressor()
    with open(db_path, "rb") as raw, dctx.stream_reader(raw) as stream:
        text = io.TextIOWrapper(stream, encoding="utf-8", newline="")
        for row in csv.DictReader(text):
            rating = row.get("Rating", "")
            if not rating.isdigit() or not (lo <= int(rating) <= hi):
                continue
            row_themes = set(row.get("Themes", "").split())
            hit = row_themes >= wanted if match_all else bool(row_themes & wanted)
            if not hit:
                continue
            puzzle = _normalize_lichess_puzzle(row)
            if puzzle:
                found.append(puzzle)
            if len(found) >= limit:
                break
    return found


def fetch_next_online(theme: str = "", difficulty: str = "") -> Puzzle | None:
    """Pull a single puzzle from the Lichess API. No download required."""
    params = {}
    if theme:
        params["angle"] = theme
    if difficulty:
        params["difficulty"] = difficulty
    resp = requests.get(
        LICHESS_PUZZLE_API, params=params, timeout=30,
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    data = resp.json()

    puzzle_data = data.get("puzzle", {})
    pgn_text = data.get("game", {}).get("pgn", "")
    if not pgn_text or not puzzle_data:
        return None

    # The API gives the game PGN plus the ply the puzzle starts at.
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return None
    board = game.board()
    for move in list(game.mainline_moves())[: puzzle_data.get("initialPly", 0) + 1]:
        board.push(move)

    solution = puzzle_data.get("solution", [])
    san_line, probe = [], board.copy(stack=False)
    for uci in solution:
        try:
            move = chess.Move.from_uci(uci)
            san_line.append(probe.san(move))
            probe.push(move)
        except (ValueError, AssertionError):
            break

    return Puzzle(
        puzzle_id=f"lichess:{puzzle_data.get('id', '')}",
        source="lichess_db",
        fen=board.fen(),
        solution_uci=" ".join(solution),
        solution_san=" ".join(san_line),
        themes=puzzle_data.get("themes", []),
        rating=puzzle_data.get("rating"),
    )


# --------------------------------------------------------------------------
# Storage and export
# --------------------------------------------------------------------------

def store(conn: sqlite3.Connection, puzzles: list[Puzzle]) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO puzzles
            (puzzle_id, source, game_id, ply, fen, solution_uci, solution_san,
             played_san, themes, win_swing, rating, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    p.puzzle_id, p.source, p.game_id, p.ply, p.fen, p.solution_uci,
                    p.solution_san, p.played_san, json.dumps(p.themes or []),
                    p.win_swing, p.rating, now,
                )
                for p in puzzles
            ],
        )


def load(
    conn: sqlite3.Connection,
    theme: str = "",
    source: str = "",
    limit: int = 20,
) -> list[Puzzle]:
    sql = "SELECT * FROM puzzles WHERE 1=1"
    params: list = []
    if theme:
        sql += " AND themes LIKE ?"
        params.append(f"%{theme}%")
    if source:
        sql += " AND source = ?"
        params.append(source)
    sql += " ORDER BY COALESCE(win_swing, 0) DESC, rating DESC LIMIT ?"
    params.append(limit)

    return [
        Puzzle(
            puzzle_id=r["puzzle_id"], source=r["source"], fen=r["fen"],
            solution_uci=r["solution_uci"], solution_san=r["solution_san"] or "",
            played_san=r["played_san"] or "", themes=json.loads(r["themes"] or "[]"),
            win_swing=r["win_swing"], rating=r["rating"],
            game_id=r["game_id"], ply=r["ply"],
        )
        for r in conn.execute(sql, params).fetchall()
    ]


def export_pgn(puzzles: list[Puzzle], path: Path) -> Path:
    """Write puzzles as a PGN any chess GUI can open as a study set."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for p in puzzles:
            board = chess.Board(p.fen)
            game = chess.pgn.Game()
            game.setup(board)
            game.headers["Event"] = "Chess Coach practice"
            game.headers["Site"] = p.lichess_url()
            # Most GUIs show these two headers as the "players", so use them to
            # say who is to move and what the position is about.
            game.headers["White"] = "White to play" if board.turn else "Black to play"
            game.headers["Black"] = ", ".join(p.themes or []) or "-"
            game.headers["Result"] = "*"
            if p.played_san:
                game.headers["Annotator"] = f"You played {p.played_san}"

            node = game
            probe = board.copy(stack=False)
            for uci in p.solution_uci.split():
                try:
                    move = chess.Move.from_uci(uci)
                    if not probe.is_legal(move):
                        break
                    node = node.add_variation(move)
                    probe.push(move)
                except ValueError:
                    break
            fh.write(str(game) + "\n\n")
    return path
