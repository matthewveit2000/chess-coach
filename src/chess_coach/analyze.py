"""Game analysis: walk a game, evaluate every position, grade every move.

The efficient trick here is that one engine pass per *position* gives you both
numbers you need for every *move*:

    eval(P_i)     = the best you could have done at move i
    -eval(P_i+1)  = what you actually got, from your point of view

So a 60-move game costs ~61 evaluations, not 122. This is the same approach
Lichess's server-side analysis uses.
"""

from __future__ import annotations

import io
import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone

import chess
import chess.pgn

from . import motifs, scoring
from .config import Config
from .engine import EngineSession

ProgressFn = Callable[[int, int], None]


def _terminal_eval(board: chess.Board) -> tuple[int | None, int | None]:
    """Evaluation of a finished position, from the POV of the player who just moved.

    Deliberately not expressed as "the side to move is mated, then flip": a mate
    score of 0 flips to 0, which reads as a loss rather than a win and would
    grade every checkmate as a catastrophic blunder.
    """
    if board.is_checkmate():
        return None, 1          # we just delivered mate
    return 0, None              # stalemate or draw by rule


def analyze_game(
    conn: sqlite3.Connection,
    game_row: sqlite3.Row,
    engine: EngineSession,
    cfg: Config,
    progress: ProgressFn | None = None,
) -> int:
    """Analyze one game and write its move_evals rows. Returns moves graded."""
    game = chess.pgn.read_game(io.StringIO(game_row["pgn"]))
    if game is None:
        return 0

    moves = list(game.mainline_moves())
    if not moves:
        return 0

    my_color = chess.WHITE if game_row["my_color"] == "white" else chess.BLACK
    acfg = cfg.analysis
    start_ply = min(acfg.skip_opening_plies, len(moves))

    # Replay to the first ply we care about.
    board = game.board()
    for move in moves[:start_ply]:
        board.push(move)

    # Evaluate positions start_ply .. len(moves) inclusive.
    positions: list[chess.Board] = [board.copy(stack=False)]
    probe = board.copy(stack=False)
    for move in moves[start_ply:]:
        probe.push(move)
        positions.append(probe.copy(stack=False))

    evals: list[list] = []
    total = len(positions)
    for idx, pos in enumerate(positions):
        evals.append(engine.analyse(pos) if not pos.is_game_over() else [])
        if progress:
            progress(idx + 1, total)

    rows = []
    board = positions[0].copy(stack=False)
    for offset, move in enumerate(moves[start_ply:]):
        ply = start_ply + offset
        before_lines = evals[offset]
        after_lines = evals[offset + 1]
        after_board = positions[offset + 1]

        if not before_lines:
            board.push(move)
            continue

        best = before_lines[0]
        cp_before, mate_before = best.cp, best.mate

        if after_lines:
            opp_best = after_lines[0]
            cp_after, mate_after = scoring.flip(opp_best.cp, opp_best.mate)
            reply_pv = opp_best.pv_uci
        else:
            # Game ended on this move: already from the mover's point of view.
            cp_after, mate_after = _terminal_eval(after_board)
            reply_pv = []

        win_before = scoring.win_prob(cp_before, mate_before)
        win_after = scoring.win_prob(cp_after, mate_after)
        win_loss = max(0.0, win_before - win_after)

        phase = scoring.phase_of(board)
        classification = scoring.classify(
            win_loss, acfg.inaccuracy, acfg.mistake, acfg.blunder
        )
        decided = scoring.is_decided(win_before, acfg.decided_threshold)

        # Only tag moves that actually cost something. Otherwise the rules fire
        # on sound play -- a good move can still let the opponent recapture on a
        # square with no defender -- and "hangs_rook" ends up recorded against a
        # move the engine graded as fine.
        tags = (
            motifs.tag(
                board=board,
                played=move,
                best_uci=best.move_uci,
                best_pv_uci=best.pv_uci,
                reply_pv_uci=reply_pv,
                mate_before=mate_before,
                mate_after=mate_after,
                win_loss=win_loss,
                phase=phase,
            )
            if win_loss >= acfg.inaccuracy
            else []
        )

        alt_lines = [
            {"san": ln.move_san, "cp": ln.cp, "mate": ln.mate, "pv": " ".join(ln.pv_san)}
            for ln in before_lines[1:]
        ]

        rows.append({
            "game_id": game_row["game_id"],
            "ply": ply,
            "move_number": board.fullmove_number,
            "color": "white" if board.turn == chess.WHITE else "black",
            "is_mine": int(board.turn == my_color),
            "phase": phase,
            "fen_before": board.fen(),
            "san": board.san(move),
            "uci": move.uci(),
            "cp_before": cp_before,
            "mate_before": mate_before,
            "cp_after": cp_after,
            "mate_after": mate_after,
            "win_before": round(win_before, 4),
            "win_after": round(win_after, 4),
            "win_loss": round(win_loss, 4),
            "cpl": scoring.centipawn_loss(cp_before, mate_before, cp_after, mate_after),
            "best_san": best.move_san,
            "best_uci": best.move_uci,
            "best_pv": " ".join(best.pv_san),
            "alt_lines": json.dumps(alt_lines),
            "classification": classification,
            "was_decided": int(decided),
            "motifs": json.dumps(tags),
        })
        board.push(move)

    _write(conn, game_row["game_id"], rows, engine, cfg)
    return len(rows)


def _write(conn, game_id: str, rows: list[dict], engine: EngineSession, cfg: Config) -> None:
    cols = list(rows[0].keys()) if rows else []
    with conn:
        conn.execute("DELETE FROM move_evals WHERE game_id = ?", (game_id,))
        conn.execute("DELETE FROM analysis_runs WHERE game_id = ?", (game_id,))
        if rows:
            placeholders = ",".join("?" * len(cols))
            conn.executemany(
                f"INSERT INTO move_evals ({','.join(cols)}) VALUES ({placeholders})",
                [tuple(r[c] for c in cols) for r in rows],
            )
        conn.execute(
            "INSERT INTO analysis_runs (game_id, engine, depth, multipv, created_at) "
            "VALUES (?,?,?,?,?)",
            (game_id, engine.name, cfg.engine.depth, cfg.engine.multipv,
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
