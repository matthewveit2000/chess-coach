"""Lichess game source.

Free public API, no auth needed to read a user's public games. A personal
access token (LICHESS_TOKEN in .env) only raises the rate limit.
Docs: https://lichess.org/api#tag/Games/operation/apiGamesUser

Included mainly to prove the source layer is genuinely pluggable -- the rest of
the toolkit does not know Chess.com from Lichess.
"""

from __future__ import annotations

import io
import json
import os
from collections.abc import Iterator
from datetime import datetime, timezone

import chess.pgn
import requests

from .base import GameRecord

API = "https://lichess.org/api"

# Lichess "speed" values map onto the same vocabulary Chess.com uses, so trend
# reports can mix sources without special-casing.
SPEED_TO_TIME_CLASS = {
    "ultraBullet": "bullet",
    "bullet": "bullet",
    "blitz": "blitz",
    "rapid": "rapid",
    "classical": "rapid",
    "correspondence": "daily",
}


def _headers() -> dict:
    headers = {"Accept": "application/x-ndjson"}
    token = os.environ.get("LICHESS_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _parse_game(raw: dict) -> GameRecord | None:
    pgn_text = raw.get("pgn")
    if not pgn_text:
        return None
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return None

    players = raw.get("players", {})
    white, black = players.get("white", {}), players.get("black", {})
    created = raw.get("createdAt")
    played_at = (
        datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat(timespec="seconds")
        if created else ""
    )

    winner = raw.get("winner")
    result = {"white": "1-0", "black": "0-1"}.get(winner, "1/2-1/2")

    clock = raw.get("clock", {})
    time_control = (
        f"{clock.get('initial', 0)}+{clock.get('increment', 0)}" if clock else ""
    )

    return GameRecord(
        source="lichess",
        source_game_id=raw.get("id", ""),
        pgn=pgn_text,
        url=f"https://lichess.org/{raw.get('id', '')}",
        played_at=played_at,
        time_class=SPEED_TO_TIME_CLASS.get(raw.get("speed", ""), raw.get("speed", "")),
        time_control=time_control,
        rated=bool(raw.get("rated", True)),
        eco=raw.get("opening", {}).get("eco", ""),
        opening_name=raw.get("opening", {}).get("name", ""),
        white_user=white.get("user", {}).get("name", ""),
        black_user=black.get("user", {}).get("name", ""),
        white_rating=white.get("rating"),
        black_rating=black.get("rating"),
        result=result,
        termination=raw.get("status", ""),
    )


def fetch(
    username: str,
    since: str | None = None,
    limit: int | None = None,
    time_classes: set[str] | None = None,
) -> Iterator[GameRecord]:
    params: dict = {"pgnInJson": "true", "opening": "true", "sort": "dateDesc"}
    if limit:
        params["max"] = limit
    if since:
        dt = datetime.strptime(since, "%Y-%m").replace(tzinfo=timezone.utc)
        params["since"] = int(dt.timestamp() * 1000)

    with requests.get(
        f"{API}/games/user/{username}", params=params,
        headers=_headers(), stream=True, timeout=60,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            raw = json.loads(line)
            if raw.get("variant", "standard") != "standard":
                continue
            record = _parse_game(raw)
            if record is None:
                continue
            if time_classes and record.time_class not in time_classes:
                continue
            yield record
