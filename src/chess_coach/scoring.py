"""Turning engine numbers into coaching numbers.

Raw centipawns are a bad unit for judging mistakes. Going from +900 to +600 is
a 300cp "loss" that changes nothing -- you were winning, you are still winning.
Going from +20 to -280 is the same 300cp and it lost you the game.

The fix is to convert centipawns to *winning chances* first, then measure the
drop. This is the model Lichess uses for its own move classification:

    winning chances = 1 / (1 + exp(-0.00368208 * centipawns))

It is a logistic curve fitted to real game outcomes, so a 300cp swing near
equality is worth far more than the same swing in a decided position.

All values here are from the point of view of the side to move.
"""

from __future__ import annotations

import math

import chess
import chess.engine

# Fitted constant from Lichess's accuracy model.
_K = 0.00368208

# Centipawn value we treat a forced mate as, for CPL bookkeeping only.
MATE_CP = 10_000

# Centipawn loss above this is clamped -- beyond ~1000 the number stops meaning
# anything and would otherwise dominate any average.
MAX_CPL = 1000


def win_prob(cp: int | None, mate: int | None) -> float:
    """Winning chances in 0.0-1.0 for the side to move."""
    if mate is not None:
        return 1.0 if mate > 0 else 0.0
    if cp is None:
        return 0.5
    return 1.0 / (1.0 + math.exp(-_K * cp))


def score_to_parts(score: chess.engine.PovScore, white_pov: bool = False) -> tuple[int | None, int | None]:
    """Split a python-chess score into (centipawns, mate_in). Exactly one is set."""
    pov = score.white() if white_pov else score.relative
    if pov.is_mate():
        return None, pov.mate()
    return pov.score(), None


def flip(cp: int | None, mate: int | None) -> tuple[int | None, int | None]:
    """Flip an evaluation to the other side's point of view."""
    return (None if cp is None else -cp, None if mate is None else -mate)


def centipawn_loss(
    cp_before: int | None, mate_before: int | None,
    cp_after: int | None, mate_after: int | None,
) -> int:
    """Centipawn loss of the played move, clamped and mate-aware."""
    before = MATE_CP if mate_before and mate_before > 0 else (
        -MATE_CP if mate_before else (cp_before or 0)
    )
    after = MATE_CP if mate_after and mate_after > 0 else (
        -MATE_CP if mate_after else (cp_after or 0)
    )
    return max(0, min(MAX_CPL, before - after))


def classify(win_loss: float, inaccuracy: float, mistake: float, blunder: float) -> str:
    """Grade a move by how much winning chance it gave away."""
    if win_loss >= blunder:
        return "blunder"
    if win_loss >= mistake:
        return "mistake"
    if win_loss >= inaccuracy:
        return "inaccuracy"
    if win_loss <= 0.02:
        return "best"
    return "good"


def is_decided(win_before: float, threshold: float) -> bool:
    """True when the game was already effectively over before this move."""
    return win_before >= threshold or win_before <= (1.0 - threshold)


def phase_of(board: chess.Board) -> str:
    """Opening / middlegame / endgame by material and development.

    Uses the common heuristic: count non-pawn, non-king material. Under 14
    points of it (roughly a queen and a rook each, or less) is an endgame.
    """
    values = {chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
    total = sum(
        val * len(board.pieces(piece, color))
        for piece, val in values.items()
        for color in (chess.WHITE, chess.BLACK)
    )
    if total <= 14:
        return "endgame"
    if board.fullmove_number <= 12:
        return "opening"
    return "middlegame"

