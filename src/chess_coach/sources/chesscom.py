"""Chess.com game source.

Uses the Published-Data API: free, read-only, no account or API key needed.
Docs: https://www.chess.com/news/view/published-data-api

Games are organized into monthly archives. We list the archives, then pull the
months we care about newest-first.

One gotcha worth knowing: Chess.com blocks requests that use a default HTTP
client User-Agent. A descriptive UA string is required, not optional.
"""

from __future__ import annotations

import io
import time
from collections.abc import Iterator
from datetime import datetime, timezone

import chess.pgn
import requests

from ..openings import name_from_eco_url
from .base import GameRecord

API = "https://api.chess.com/pub"
HEADERS = {
    "User-Agent": "chess-coach/0.1 (personal game-review tool; "
                  "https://github.com/matthewveit2000/chess-coach)",
    "Accept": "application/json",
}
# Chess.com asks for serial, unhurried requests against the public API.
POLITE_DELAY_SEC = 0.4


class ChessComError(RuntimeError):
    pass


def _get(url: str) -> dict:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    if resp.status_code == 404:
        raise ChessComError(f"Not found: {url} (is the username spelled right?)")
    if resp.status_code == 429:
        raise ChessComError("Chess.com rate-limited the request. Wait a minute and retry.")
    resp.raise_for_status()
    return resp.json()


def list_archives(username: str) -> list[str]:
    """Monthly archive URLs, oldest first."""
    data = _get(f"{API}/player/{username.lower()}/games/archives")
    return data.get("archives", [])


def _archive_month(url: str) -> str:
    """'.../games/2024/07' -> '2024-07'"""
    parts = url.rstrip("/").split("/")
    return f"{parts[-2]}-{parts[-1]}"


def _parse_game(raw: dict) -> GameRecord | None:
    pgn_text = raw.get("pgn")
    if not pgn_text:
        return None  # e.g. an in-progress daily game

    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return None
    h = game.headers

    end_time = raw.get("end_time")
    played_at = (
        datetime.fromtimestamp(end_time, tz=timezone.utc).isoformat(timespec="seconds")
        if end_time else ""
    )

    # Prefer the human-readable opening name from ECOUrl; fall back to the
    # Opening header if a game somehow lacks one.
    eco_url = h.get("ECOUrl", "")
    opening = name_from_eco_url(eco_url) or h.get("Opening", "")

    url = raw.get("url", "")
    return GameRecord(
        source="chesscom",
        source_game_id=url.rstrip("/").rsplit("/", 1)[-1] or raw.get("uuid", ""),
        pgn=pgn_text,
        url=url,
        played_at=played_at,
        time_class=raw.get("time_class", ""),
        time_control=raw.get("time_control", ""),
        rated=bool(raw.get("rated", True)),
        eco=h.get("ECO", ""),
        opening_name=opening,
        white_user=raw.get("white", {}).get("username", ""),
        black_user=raw.get("black", {}).get("username", ""),
        white_rating=raw.get("white", {}).get("rating"),
        black_rating=raw.get("black", {}).get("rating"),
        result=h.get("Result", ""),
        termination=h.get("Termination", ""),
        extra={"rules": raw.get("rules", "chess")},
    )


def fetch(
    username: str,
    since: str | None = None,
    limit: int | None = None,
    time_classes: set[str] | None = None,
) -> Iterator[GameRecord]:
    """Yield games newest-first.

    since: "YYYY-MM" -- skip archives older than this month.
    limit: stop after this many games.
    time_classes: e.g. {"rapid", "blitz"}; None means all.
    """
    archives = list_archives(username)
    if since:
        archives = [a for a in archives if _archive_month(a) >= since]

    yielded = 0
    for archive_url in reversed(archives):  # newest month first
        games = _get(archive_url).get("games", [])
        for raw in sorted(games, key=lambda g: g.get("end_time", 0), reverse=True):
            # Skip variants -- Chess960, bughouse etc. would poison the stats.
            if raw.get("rules", "chess") != "chess":
                continue
            if time_classes and raw.get("time_class") not in time_classes:
                continue
            record = _parse_game(raw)
            if record is None:
                continue
            yield record
            yielded += 1
            if limit and yielded >= limit:
                return
        time.sleep(POLITE_DELAY_SEC)
