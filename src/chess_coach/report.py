"""Rendering analysis into something a coach -- human or AI -- can work from.

Two outputs, same data:

  reports/coaching_brief.md   readable by you
  reports/brief.json          readable by an agent

The markdown is deliberately dense with raw numbers and links rather than
prose. Prose is the AI layer's job; this file's job is to give it facts it
cannot get wrong, each traceable to a specific move in a specific game.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import trends
from .config import REPORTS_DIR, Config
from .motifs import label

CLASS_SYMBOL = {
    "blunder": "??",
    "mistake": "?",
    "inaccuracy": "?!",
    "good": "",
    "best": "!",
}


def lichess_analysis_url(fen: str) -> str:
    """Free Lichess analysis board for a position. Spaces become underscores."""
    return "https://lichess.org/analysis/" + fen.replace(" ", "_")


def _df_to_md(df: pd.DataFrame, index_names: list[str] | None = None) -> str:
    """Render a DataFrame as a markdown table without adding a dependency."""
    if df is None or df.empty:
        return "_No data yet._\n"
    out = df.reset_index()
    if index_names:
        out.columns = index_names + list(out.columns[len(index_names):])
    header = "| " + " | ".join(str(c) for c in out.columns) + " |"
    divider = "|" + "|".join("---" for _ in out.columns) + "|"
    rows = [
        "| " + " | ".join("" if pd.isna(v) else str(v) for v in rec) + " |"
        for rec in out.itertuples(index=False, name=None)
    ]
    return "\n".join([header, divider, *rows]) + "\n"


def build_brief(conn: sqlite3.Connection, cfg: Config) -> dict:
    """Assemble every trend figure into one structure."""
    moves = trends.load_moves(conn)
    games = trends.load_games(conn)

    overview = trends.overview(moves, games)
    phase = trends.by_phase(moves)
    opening = trends.by_opening(moves, games, cfg)
    motifs_df = trends.motif_frequency(moves)
    worst = trends.worst_moments(moves, limit=15)
    timing = trends.by_time_class(moves, games)

    strong, weak = pd.DataFrame(), pd.DataFrame()
    if not opening.empty:
        strong = opening[opening["score_pct"] >= 55]
        weak = opening[opening["score_pct"] < 45]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine_settings": {
            "depth": cfg.engine.depth,
            "multipv": cfg.engine.multipv,
        },
        "thresholds": {
            "inaccuracy": cfg.analysis.inaccuracy,
            "mistake": cfg.analysis.mistake,
            "blunder": cfg.analysis.blunder,
            "decided": cfg.analysis.decided_threshold,
            "units": "winning chances lost (0-1)",
        },
        "overview": overview,
        "by_phase": phase.reset_index().to_dict(orient="records") if not phase.empty else [],
        "by_time_class": (
            timing.reset_index().to_dict(orient="records") if not timing.empty else []
        ),
        "openings_working": (
            strong.reset_index().to_dict(orient="records") if not strong.empty else []
        ),
        "openings_to_practice": (
            weak.reset_index().to_dict(orient="records") if not weak.empty else []
        ),
        "recurring_motifs": (
            motifs_df.reset_index().to_dict(orient="records") if not motifs_df.empty else []
        ),
        "worst_moments": _worst_records(worst),
        "_dataframes": {
            "phase": phase, "opening": opening, "motifs": motifs_df,
            "worst": worst, "timing": timing,
        },
    }


def _worst_records(worst: pd.DataFrame) -> list[dict]:
    if worst.empty:
        return []
    records = []
    for _, row in worst.iterrows():
        records.append({
            "game_id": row.get("game_id"),
            "game_url": row.get("url"),
            "played_at": row.get("played_at"),
            "opening": row.get("opening_family"),
            "move_number": int(row.get("move_number", 0)),
            "color": row.get("color"),
            "phase": row.get("phase"),
            "you_played": row.get("san"),
            "engine_best": row.get("best_san"),
            "engine_line": row.get("best_pv"),
            "classification": row.get("classification"),
            "win_before": row.get("win_before"),
            "win_after": row.get("win_after"),
            "win_loss": row.get("win_loss"),
            "centipawn_loss": int(row.get("cpl", 0)),
            "motifs": json.loads(row.get("motifs") or "[]"),
            "fen": row.get("fen_before"),
            "analysis_board": lichess_analysis_url(row.get("fen_before", "")),
        })
    return records


def render_markdown(brief: dict, cfg: Config) -> str:
    ov = brief["overview"]
    dfs = brief["_dataframes"]
    lines: list[str] = []
    add = lines.append

    add("# Coaching brief\n")
    add(f"_Generated {brief['generated_at']} · Stockfish depth "
        f"{brief['engine_settings']['depth']}_\n")

    if not ov:
        add("No analyzed games yet. Run `chess-coach fetch` then `chess-coach analyze`.\n")
        return "\n".join(lines)

    add("## Overview\n")
    add(f"- **Games analyzed:** {ov['games_analyzed']} ({ov['record']})")
    if ov.get("score_pct") is not None:
        add(f"- **Score:** {ov['score_pct']}%")
    add(f"- **Average centipawn loss:** {ov['avg_centipawn_loss']} "
        f"(median {ov['median_centipawn_loss']})")
    add(f"- **Blunders per game:** {ov['blunders_per_game']}")
    add(f"- **Mistakes per game:** {ov['mistakes_per_game']}")
    add(f"- **Error rate:** {ov['error_rate_pct']}% of your moves\n")
    add("> Positions that were already decided are excluded from these numbers. "
        "See docs/methodology.md.\n")

    add("## Where the errors happen\n")
    add(_df_to_md(dfs["phase"], ["phase"]))

    if not dfs["timing"].empty:
        add("## By time control\n")
        add(_df_to_md(dfs["timing"], ["time_class"]))

    add("## Openings\n")
    if brief["openings_working"]:
        add("### Working well\n")
        add(_df_to_md(
            pd.DataFrame(brief["openings_working"]).set_index(["opening_family", "my_color"]),
            ["opening", "color"],
        ))
    if brief["openings_to_practice"]:
        add("### Needs practice\n")
        add(_df_to_md(
            pd.DataFrame(brief["openings_to_practice"]).set_index(["opening_family", "my_color"]),
            ["opening", "color"],
        ))
    if not brief["openings_working"] and not brief["openings_to_practice"]:
        add(f"_Not enough games per opening yet "
            f"(need {cfg.trends.min_games_for_opening}). Fetch and analyze more._\n")

    add("## Recurring mistakes\n")
    if brief["recurring_motifs"]:
        add("Ranked by total winning chances lost, not raw count.\n")
        motif_df = dfs["motifs"][
            ["label", "occurrences", "games_affected", "avg_win_loss", "total_win_loss"]
        ]
        add(_df_to_md(motif_df, ["motif"]))
    else:
        add("_No recurring patterns detected yet._\n")

    add("## Your costliest moments\n")
    for i, m in enumerate(brief["worst_moments"], 1):
        symbol = CLASS_SYMBOL.get(m["classification"], "")
        tags = ", ".join(label(t) for t in m["motifs"]) or "-"
        add(f"**{i}. Move {m['move_number']} ({m['color']}) — "
            f"{m['you_played']}{symbol}**  ")
        add(f"Engine wanted **{m['engine_best']}** · line: `{m['engine_line']}`  ")
        add(f"Winning chances {m['win_before']:.0%} → {m['win_after']:.0%} "
            f"(lost {m['win_loss']:.0%}, {m['centipawn_loss']}cp)  ")
        add(f"Pattern: {tags} · Phase: {m['phase']} · Opening: {m['opening']}  ")
        add(f"[Analysis board]({m['analysis_board']})"
            + (f" · [Game]({m['game_url']})" if m.get("game_url") else ""))
        add("")

    return "\n".join(lines)


def write_brief(conn: sqlite3.Connection, cfg: Config) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    brief = build_brief(conn, cfg)
    markdown = render_markdown(brief, cfg)

    md_path = REPORTS_DIR / "coaching_brief.md"
    json_path = REPORTS_DIR / "brief.json"

    md_path.write_text(markdown, encoding="utf-8")
    serializable = {k: v for k, v in brief.items() if k != "_dataframes"}
    json_path.write_text(json.dumps(serializable, indent=2, default=str), encoding="utf-8")
    return md_path, json_path


# --------------------------------------------------------------------------
# Single-game review
# --------------------------------------------------------------------------

def render_game_review(conn: sqlite3.Connection, game_id: str) -> str:
    game = conn.execute("SELECT * FROM games WHERE game_id = ?", (game_id,)).fetchone()
    if game is None:
        return f"No game {game_id} in the database."

    rows = conn.execute(
        "SELECT * FROM move_evals WHERE game_id = ? ORDER BY ply", (game_id,)
    ).fetchall()
    if not rows:
        return f"Game {game_id} has not been analyzed yet. Run: chess-coach analyze"

    mine = [r for r in rows if r["is_mine"]]
    errors = [r for r in mine if r["classification"] in trends.ERROR_CLASSES]
    critical = sorted(mine, key=lambda r: r["win_loss"], reverse=True)[:6]

    result_word = {1.0: "Win", 0.5: "Draw", 0.0: "Loss"}.get(game["my_score"], "?")
    lines = [
        f"# {game['white_user']} vs {game['black_user']}\n",
        f"_{game['played_at']} · {game['time_class']} · {game['opening_name'] or 'Unknown opening'}"
        f" ({game['eco']}) · You were {game['my_color']} · **{result_word}**_\n",
    ]
    if game["url"]:
        lines.append(f"[View game]({game['url']})\n")

    avg_cpl = sum(r["cpl"] for r in mine) / len(mine) if mine else 0
    counts = {c: sum(1 for r in mine if r["classification"] == c)
              for c in ("blunder", "mistake", "inaccuracy")}
    lines.append("## Your accuracy\n")
    lines.append(f"- Average centipawn loss: **{avg_cpl:.0f}**")
    lines.append(f"- Blunders: {counts['blunder']} · Mistakes: {counts['mistake']} "
                 f"· Inaccuracies: {counts['inaccuracy']}")
    lines.append(f"- Moves graded: {len(mine)} (opening book skipped)\n")

    lines.append("## Critical positions\n")
    if not errors:
        lines.append("_No significant errors found. Clean game._\n")
    for r in critical:
        if r["win_loss"] < 0.05:
            continue
        tags = ", ".join(label(t) for t in json.loads(r["motifs"] or "[]")) or "-"
        symbol = CLASS_SYMBOL.get(r["classification"], "")
        lines.append(f"### Move {r['move_number']}: you played {r['san']}{symbol}\n")
        lines.append(f"- Engine's choice: **{r['best_san']}** — `{r['best_pv']}`")
        lines.append(f"- Winning chances: {r['win_before']:.0%} → {r['win_after']:.0%} "
                     f"(lost {r['win_loss']:.0%}, {r['cpl']}cp)")
        lines.append(f"- Pattern: {tags}")
        lines.append(f"- Phase: {r['phase']}")

        alts = json.loads(r["alt_lines"] or "[]")
        if alts:
            alt_text = " · ".join(
                f"{a['san']} ({a['cp']}cp)" if a.get("cp") is not None
                else f"{a['san']} (mate {a.get('mate')})"
                for a in alts[:2]
            )
            lines.append(f"- Other engine candidates: {alt_text}")
        lines.append(f"- [Analysis board]({lichess_analysis_url(r['fen_before'])})\n")

    return "\n".join(lines)
