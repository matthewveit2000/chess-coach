"""Aggregating across games: what am I consistently getting wrong?

A single bad game teaches you little -- everyone hangs a queen occasionally.
The useful signal is what repeats. Everything here is a pandas groupby over the
move_evals table, so the numbers are auditable: any figure in a report can be
traced back to specific plies in specific games.

Two deliberate choices:

1. Positions already decided (you were up a queen, or dead lost) are excluded
   by default. Errors there are real but not instructive, and including them
   makes every stat look worse than your play actually is.

2. Opening stats need a minimum sample. A 100% win rate over two games is not
   a strength, and reporting it as one sends you off studying the wrong thing.
"""

from __future__ import annotations

import json
import sqlite3

import pandas as pd

from .config import Config
from .motifs import label

ERROR_CLASSES = ("inaccuracy", "mistake", "blunder")


def load_moves(
    conn: sqlite3.Connection,
    mine_only: bool = True,
    include_decided: bool = False,
) -> pd.DataFrame:
    """All analyzed moves joined to their game metadata."""
    df = pd.read_sql_query(
        """
        SELECT m.*, g.opening_family, g.opening_name, g.eco, g.time_class,
               g.my_score, g.my_color, g.played_at, g.url, g.my_rating, g.opp_rating
        FROM move_evals m
        JOIN games g ON g.game_id = m.game_id
        """,
        conn,
    )
    if df.empty:
        return df
    if mine_only:
        df = df[df["is_mine"] == 1]
    if not include_decided:
        df = df[df["was_decided"] == 0]
    return df.reset_index(drop=True)


def load_games(conn: sqlite3.Connection, analyzed_only: bool = True) -> pd.DataFrame:
    sql = "SELECT g.* FROM games g"
    if analyzed_only:
        sql += " JOIN analysis_runs r ON r.game_id = g.game_id"
    return pd.read_sql_query(sql, conn)


def _count_class(series: pd.Series, name: str) -> int:
    return int((series == name).sum())


def overview(moves: pd.DataFrame, games: pd.DataFrame) -> dict:
    """Headline numbers. The ones a coach would ask for first."""
    if moves.empty:
        return {}
    n_games = max(1, games.shape[0])
    errors = moves["classification"].isin(ERROR_CLASSES)
    has_score = "my_score" in games and games["my_score"].notna().any()
    return {
        "games_analyzed": int(games.shape[0]),
        "moves_graded": int(moves.shape[0]),
        "avg_centipawn_loss": round(float(moves["cpl"].mean()), 1),
        "median_centipawn_loss": round(float(moves["cpl"].median()), 1),
        "blunders_per_game": round(
            _count_class(moves["classification"], "blunder") / n_games, 2
        ),
        "mistakes_per_game": round(
            _count_class(moves["classification"], "mistake") / n_games, 2
        ),
        "error_rate_pct": round(100 * float(errors.mean()), 1),
        "score_pct": round(100 * float(games["my_score"].mean()), 1) if has_score else None,
        "record": _record(games),
    }


def _record(games: pd.DataFrame) -> str:
    if "my_score" not in games or games.empty:
        return ""
    wins = int((games["my_score"] == 1.0).sum())
    draws = int((games["my_score"] == 0.5).sum())
    losses = int((games["my_score"] == 0.0).sum())
    return f"{wins}W-{losses}L-{draws}D"


def by_phase(moves: pd.DataFrame) -> pd.DataFrame:
    """Where in the game do the errors happen?"""
    if moves.empty:
        return pd.DataFrame()
    grouped = moves.groupby("phase").agg(
        moves=("ply", "count"),
        avg_cpl=("cpl", "mean"),
        blunders=("classification", lambda s: _count_class(s, "blunder")),
        mistakes=("classification", lambda s: _count_class(s, "mistake")),
        inaccuracies=("classification", lambda s: _count_class(s, "inaccuracy")),
    )
    grouped["error_rate_pct"] = (
        100
        * (grouped["blunders"] + grouped["mistakes"] + grouped["inaccuracies"])
        / grouped["moves"]
    ).round(1)
    grouped["avg_cpl"] = grouped["avg_cpl"].round(1)
    order = ["opening", "middlegame", "endgame"]
    return grouped.reindex([p for p in order if p in grouped.index])


def by_opening(moves: pd.DataFrame, games: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Per-opening results and accuracy, split by colour.

    Colour matters: playing the Caro-Kann as Black and facing it as White are
    different study problems that happen to share a name.
    """
    if games.empty:
        return pd.DataFrame()

    gstats = games.groupby(["opening_family", "my_color"]).agg(
        games=("game_id", "count"),
        score_pct=("my_score", lambda s: 100 * s.mean()),
    )

    if not moves.empty:
        mstats = moves.groupby(["opening_family", "my_color"]).agg(
            avg_cpl=("cpl", "mean"),
            blunders=("classification", lambda s: _count_class(s, "blunder")),
        )
        gstats = gstats.join(mstats, how="left")
    else:
        gstats["avg_cpl"] = pd.NA
        gstats["blunders"] = pd.NA

    gstats = gstats[gstats["games"] >= cfg.trends.min_games_for_opening]
    if gstats.empty:
        return gstats

    gstats["blunders_per_game"] = (gstats["blunders"] / gstats["games"]).round(2)
    gstats["score_pct"] = gstats["score_pct"].round(1)
    gstats["avg_cpl"] = gstats["avg_cpl"].round(1)
    return gstats.sort_values("score_pct", ascending=False)


def motif_frequency(moves: pd.DataFrame, min_win_loss: float = 0.10) -> pd.DataFrame:
    """Which kinds of mistake repeat, and what they cost."""
    if moves.empty:
        return pd.DataFrame()

    errors = moves[moves["win_loss"] >= min_win_loss]
    records = []
    for _, row in errors.iterrows():
        for tag in json.loads(row["motifs"] or "[]"):
            records.append(
                {
                    "motif": tag,
                    "win_loss": row["win_loss"],
                    "game_id": row["game_id"],
                    "phase": row["phase"],
                }
            )
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    grouped = df.groupby("motif").agg(
        occurrences=("motif", "count"),
        games_affected=("game_id", "nunique"),
        avg_win_loss=("win_loss", "mean"),
        total_win_loss=("win_loss", "sum"),
    )
    grouped["avg_win_loss"] = grouped["avg_win_loss"].round(3)
    grouped["total_win_loss"] = grouped["total_win_loss"].round(2)
    grouped["label"] = [label(i) for i in grouped.index]
    # Rank by total damage rather than raw count: one recurring queen blunder
    # costs more than ten small inaccuracies of the same type.
    return grouped.sort_values("total_win_loss", ascending=False)


def worst_moments(moves: pd.DataFrame, limit: int = 15) -> pd.DataFrame:
    """The single costliest decisions across every analyzed game."""
    if moves.empty:
        return pd.DataFrame()
    cols = [
        "game_id", "url", "played_at", "move_number", "color", "san", "best_san",
        "best_pv", "win_before", "win_after", "win_loss", "cpl", "classification",
        "phase", "motifs", "fen_before", "opening_family",
    ]
    available = [c for c in cols if c in moves.columns]
    return moves.sort_values("win_loss", ascending=False).head(limit)[available]


def by_time_class(moves: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Does accuracy fall apart at faster time controls?"""
    if games.empty:
        return pd.DataFrame()
    gstats = games.groupby("time_class").agg(
        games=("game_id", "count"),
        score_pct=("my_score", lambda s: 100 * s.mean()),
    )
    if not moves.empty:
        mstats = moves.groupby("time_class").agg(
            avg_cpl=("cpl", "mean"),
            blunders=("classification", lambda s: _count_class(s, "blunder")),
        )
        gstats = gstats.join(mstats, how="left")
        gstats["blunders_per_game"] = (gstats["blunders"] / gstats["games"]).round(2)
        gstats["avg_cpl"] = gstats["avg_cpl"].round(1)
    gstats["score_pct"] = gstats["score_pct"].round(1)
    return gstats.sort_values("games", ascending=False)
