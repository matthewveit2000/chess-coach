"""Game sources. Add a new site by writing a module with a `fetch()` function
that yields GameRecord objects, then registering it in SOURCES below."""

from __future__ import annotations

from . import chesscom, lichess

SOURCES = {
    "chesscom": chesscom,
    "lichess": lichess,
}
