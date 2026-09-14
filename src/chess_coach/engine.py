"""Stockfish wrapper.

Every judgement about whether a move is good comes from here. Nothing else in
this project -- and nothing in the AI layer on top of it -- second-guesses the
engine's numbers.

python-chess speaks UCI, the protocol Stockfish (and every other serious
engine) uses, so swapping Stockfish for Leela or Dragon is a path change.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.engine

from .config import EngineConfig
from .scoring import score_to_parts


class EngineNotFound(RuntimeError):
    pass


@dataclass
class Line:
    """One engine candidate line for a position, from the mover's point of view."""
    rank: int           # 1 = best
    cp: int | None
    mate: int | None
    pv_uci: list[str]
    pv_san: list[str]

    @property
    def move_uci(self) -> str:
        return self.pv_uci[0] if self.pv_uci else ""

    @property
    def move_san(self) -> str:
        return self.pv_san[0] if self.pv_san else ""


@contextmanager
def open_engine(cfg: EngineConfig):
    """Start Stockfish, hand back a configured session, always shut it down."""
    path: Path = cfg.resolved_path()
    if not path.exists():
        raise EngineNotFound(
            f"No engine at {path}\n"
            "Run:  uv run chess-coach setup-engine\n"
            "or set engine.path in config/config.toml to your own Stockfish binary."
        )

    engine = chess.engine.SimpleEngine.popen_uci(str(path))
    try:
        options = {}
        if "Threads" in engine.options:
            options["Threads"] = cfg.resolved_threads()
        if "Hash" in engine.options:
            options["Hash"] = cfg.hash_mb
        if options:
            engine.configure(options)
        yield EngineSession(engine, cfg)
    finally:
        engine.quit()


class EngineSession:
    def __init__(self, engine: chess.engine.SimpleEngine, cfg: EngineConfig):
        self._engine = engine
        self._cfg = cfg
        self.name = engine.id.get("name", "unknown engine")

    def analyse(self, board: chess.Board, multipv: int | None = None) -> list[Line]:
        """Evaluate a position. Returns candidate lines, best first.

        Scores are relative to the side to move: positive is good for whoever
        is on move, regardless of colour.
        """
        if board.is_game_over():
            return []

        k = multipv if multipv is not None else self._cfg.multipv
        infos = self._engine.analyse(
            board, chess.engine.Limit(depth=self._cfg.depth), multipv=k
        )
        if isinstance(infos, dict):  # python-chess returns a bare dict when multipv=1
            infos = [infos]

        lines: list[Line] = []
        for i, info in enumerate(infos):
            score = info.get("score")
            if score is None:
                continue
            cp, mate = score_to_parts(score)
            pv = info.get("pv", []) or []
            lines.append(
                Line(
                    rank=info.get("multipv", i + 1),
                    cp=cp,
                    mate=mate,
                    pv_uci=[m.uci() for m in pv],
                    pv_san=_san_line(board, pv),
                )
            )
        lines.sort(key=lambda ln: ln.rank)
        return lines


def _san_line(board: chess.Board, moves: list[chess.Move], max_plies: int = 8) -> list[str]:
    """Render a principal variation in readable notation (Nf3, Qxd5+ ...)."""
    out: list[str] = []
    tmp = board.copy(stack=False)
    for move in moves[:max_plies]:
        if not tmp.is_legal(move):
            break
        out.append(tmp.san(move))
        tmp.push(move)
    return out
