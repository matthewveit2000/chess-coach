"""Shared shape for every game source.

A source is any module exposing:

    fetch(username: str, since: str | None, limit: int | None) -> Iterator[GameRecord]

Adding a new site (OTB PGN dumps, Chess24, a local folder) means writing that
one function. Nothing downstream knows or cares where a game came from.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timezone

import chess.pgn

from ..openings import family


@dataclass
class GameRecord:
    source: str
    source_game_id: str
    pgn: str
    url: str = ""
    played_at: str = ""
    time_class: str = ""
    time_control: str = ""
    rated: bool = True
    eco: str = ""
    opening_name: str = ""
    white_user: str = ""
    black_user: str = ""
    white_rating: int | None = None
    black_rating: int | None = None
    result: str = ""
    termination: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def game_id(self) -> str:
        return f"{self.source}:{self.source_game_id}"

    def perspective(self, username: str) -> dict:
        """Work out which side is 'you' and how the game went for you."""
        user = username.lower()
        if self.white_user.lower() == user:
            my_color, my_rating, opp_rating = "white", self.white_rating, self.black_rating
        elif self.black_user.lower() == user:
            my_color, my_rating, opp_rating = "black", self.black_rating, self.white_rating
        else:
            # Username not in this game -- default to white so nothing crashes,
            # and let the caller notice via my_color.
            my_color, my_rating, opp_rating = "white", self.white_rating, self.black_rating

        score_map = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}
        white_score = score_map.get(self.result)
        if white_score is None:
            my_score = None
        else:
            my_score = white_score if my_color == "white" else 1.0 - white_score

        return {"my_color": my_color, "my_rating": my_rating,
                "opp_rating": opp_rating, "my_score": my_score}

    def to_row(self, username: str) -> dict:
        game = chess.pgn.read_game(io.StringIO(self.pgn))
        ply_count = len(list(game.mainline_moves())) if game else 0
        return {
            "game_id": self.game_id,
            "source": self.source,
            "source_game_id": self.source_game_id,
            "url": self.url,
            "played_at": self.played_at,
            "time_class": self.time_class,
            "time_control": self.time_control,
            "rated": int(self.rated),
            "eco": self.eco,
            "opening_name": self.opening_name,
            "opening_family": family(self.opening_name),
            "white_user": self.white_user,
            "black_user": self.black_user,
            "white_rating": self.white_rating,
            "black_rating": self.black_rating,
            "result": self.result,
            "termination": self.termination,
            "ply_count": ply_count,
            "pgn": self.pgn,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **self.perspective(username),
        }
