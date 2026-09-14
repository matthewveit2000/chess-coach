"""Tagging *what kind* of mistake was made.

The engine tells you a move lost 0.35 winning chances. It does not tell you
whether you hung a knight, missed a fork, or drifted in a quiet position -- and
that distinction is the whole point of coaching, because each one implies a
different kind of practice.

These tags are deterministic rules over the board and the engine's own lines.
They are not an AI judgement and they are not a full tactics classifier: they
catch the common, checkable patterns and stay quiet otherwise. A position with
no tags is not a position with no lesson; it's one where the pattern didn't
match a rule here.
"""

from __future__ import annotations

import chess

PIECE_VALUE = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}

PIECE_NAME = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}

# Human-readable labels, used in reports and handed to the AI layer so its
# vocabulary matches the data.
LABELS = {
    "missed_mate": "Missed a forced mate",
    "allowed_mate": "Allowed a forced mate",
    "hangs_piece": "Left a piece en prise",
    "missed_free_material": "Missed free material the opponent left hanging",
    "missed_fork": "Missed a fork",
    "missed_forcing_move": "Missed a forcing tactic (check or capture)",
    "back_rank": "Back-rank weakness",
    "quiet_move_missed": "The right move was quiet, not forcing",
    "defensive_resource_missed": "Missed a defensive resource in a worse position",
    "endgame_technique": "Endgame technique",
    "opening_error": "Early-opening error",
    "king_safety": "King safety",
    "material_grab": "Grabbed material and lost the thread",
}


def _is_hanging(board: chess.Board, square: int, owner: chess.Color) -> bool:
    """True when a piece on `square` has no defender of its own colour."""
    return not board.attackers(owner, square)


def _attacked_targets(board: chess.Board, from_square: int, enemy: chess.Color) -> list[int]:
    """Enemy pieces worth 3+ (or the king) attacked by the piece on `from_square`."""
    targets = []
    for sq in board.attacks(from_square):
        piece = board.piece_at(sq)
        if piece and piece.color == enemy and PIECE_VALUE[piece.piece_type] >= 3:
            targets.append(sq)
        elif piece and piece.piece_type == chess.KING and piece.color == enemy:
            targets.append(sq)
    return targets


def _on_back_rank(board: chess.Board, color: chess.Color) -> bool:
    king_sq = board.king(color)
    if king_sq is None:
        return False
    back = 0 if color == chess.WHITE else 7
    return chess.square_rank(king_sq) == back


def tag(
    board: chess.Board,
    played: chess.Move,
    best_uci: str,
    best_pv_uci: list[str],
    reply_pv_uci: list[str],
    mate_before: int | None,
    mate_after: int | None,
    win_loss: float,
    phase: str,
) -> list[str]:
    """Return motif tags for one played move.

    board       - position *before* the played move
    best_pv_uci - engine's line from that position
    reply_pv_uci- engine's line from the position *after* the played move
                  (i.e. what the opponent gets to do)
    """
    tags: list[str] = []
    mover = board.turn
    enemy = not mover

    best_move = chess.Move.from_uci(best_uci) if best_uci else None
    played_is_best = best_move is not None and played == best_move

    # --- Mate-level outcomes -------------------------------------------------
    if mate_before is not None and mate_before > 0 and not played_is_best:
        if mate_after is None or mate_after <= 0:
            tags.append("missed_mate")
    if mate_after is not None and mate_after < 0 and (mate_before is None or mate_before >= 0):
        tags.append("allowed_mate")

    # --- What the opponent gets to do to us next ----------------------------
    after = board.copy(stack=False)
    after.push(played)

    if reply_pv_uci:
        reply = chess.Move.from_uci(reply_pv_uci[0])
        if after.is_legal(reply) and after.is_capture(reply):
            victim = after.piece_at(reply.to_square)
            # after.push(reply) would remove it, so read the value first.
            if victim and PIECE_VALUE[victim.piece_type] >= 3:
                # Is our piece defended once the opponent takes it?
                if _is_hanging(after, reply.to_square, mover):
                    tags.append("hangs_piece")
                    tags.append(f"hangs_{PIECE_NAME[victim.piece_type]}")

        probe = after.copy(stack=False)
        for uci in reply_pv_uci[:6]:
            mv = chess.Move.from_uci(uci)
            if not probe.is_legal(mv):
                break
            probe.push(mv)
            if probe.is_checkmate() and _on_back_rank(probe, mover):
                tags.append("back_rank")
                break

    # --- What we could have done instead ------------------------------------
    if best_move and not played_is_best and win_loss > 0:
        if board.is_capture(best_move):
            victim = board.piece_at(best_move.to_square)
            if victim and PIECE_VALUE[victim.piece_type] >= 3 and _is_hanging(
                board, best_move.to_square, enemy
            ):
                tags.append("missed_free_material")

        # Fork: the best move lands somewhere attacking two valuable targets.
        probe = board.copy(stack=False)
        probe.push(best_move)
        if len(_attacked_targets(probe, best_move.to_square, enemy)) >= 2:
            tags.append("missed_fork")

        is_forcing = board.is_capture(best_move) or board.gives_check(best_move)
        if is_forcing and win_loss >= 0.15:
            tags.append("missed_forcing_move")
        elif not is_forcing and win_loss >= 0.15:
            # The fix was a quiet move. This is a positional lesson, not a
            # tactical one, and it needs different practice.
            tags.append("quiet_move_missed")

        # Did we grab material and lose the thread?
        if board.is_capture(played) and win_loss >= 0.20:
            tags.append("material_grab")

    # --- Situational -------------------------------------------------------
    if win_loss >= 0.15:
        if phase == "endgame":
            tags.append("endgame_technique")
        elif phase == "opening":
            tags.append("opening_error")

    if "allowed_mate" in tags or "back_rank" in tags:
        tags.append("king_safety")

    # Were we already worse and failed to hold?
    # (Caller supplies win_loss from our POV; being worse is handled upstream.)

    # Preserve order, drop duplicates.
    seen, ordered = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered


def label(tag_name: str) -> str:
    if tag_name.startswith("hangs_") and tag_name != "hangs_piece":
        return f"Left a {tag_name.removeprefix('hangs_')} en prise"
    return LABELS.get(tag_name, tag_name.replace("_", " ").capitalize())
