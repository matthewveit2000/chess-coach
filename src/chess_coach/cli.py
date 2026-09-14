"""Command line interface.

Every command is a thin wrapper: parse arguments, call into a module, print.
The real work lives in the modules so that an agent, a notebook, or a future
web UI can call the same functions without going through argv.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from . import analyze as analyze_mod
from . import db, puzzles as puzzles_mod, report, trends
from .config import EXAMPLE_CONFIG_PATH, CONFIG_PATH, REPORTS_DIR, ensure_dirs, load_config
from .engine import EngineNotFound, open_engine
from .sources import SOURCES

app = typer.Typer(
    add_completion=False,
    help="Engine-backed chess coaching. Fetch games, analyze them, find your patterns.",
    no_args_is_help=True,
)
puzzles_app = typer.Typer(help="Practice material from your games and Lichess.",
                          no_args_is_help=True)
app.add_typer(puzzles_app, name="puzzles")

# Reports contain arrows, middle dots and chess figurines, and `review` prints
# markdown straight to the terminal. On Windows a console running the legacy
# cp1252 codepage cannot encode those and raises UnicodeEncodeError mid-command
# -- so force UTF-8 rather than restricting what the reports may contain.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

console = Console()


def _require_username(cfg, source: str, override: str | None) -> str:
    user = override or cfg.username_for(source)
    if not user:
        console.print(
            f"[red]No {source} username set.[/red]\n"
            f"Either pass --user, or copy {EXAMPLE_CONFIG_PATH.name} to "
            f"{CONFIG_PATH.name} and fill in [player].{source}."
        )
        raise typer.Exit(1)
    return user


# --------------------------------------------------------------------------

@app.command("setup-engine")
def setup_engine_cmd():
    """Download Stockfish into data/engine/ and verify it runs."""
    from .setup_engine import install

    try:
        path = install(log=lambda *a, **k: console.print(*a, **k))
    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Engine ready:[/green] {path}")
    console.print("Set [cyan]engine.path[/cyan] in config/config.toml if you move it.")


@app.command()
def fetch(
    source: str = typer.Option("chesscom", help="chesscom | lichess"),
    user: str = typer.Option(None, help="Override the username from config."),
    since: str = typer.Option(None, help="Only games from this month onward, YYYY-MM."),
    limit: int = typer.Option(50, help="Stop after this many games."),
    time_class: str = typer.Option(
        None, help="Comma-separated: bullet,blitz,rapid,daily. Default: all."
    ),
):
    """Download games and store them. Nothing is analyzed at this stage."""
    ensure_dirs()
    cfg = load_config()
    if source not in SOURCES:
        console.print(f"[red]Unknown source '{source}'. Known: {', '.join(SOURCES)}[/red]")
        raise typer.Exit(1)

    username = _require_username(cfg, source, user)
    classes = {c.strip() for c in time_class.split(",")} if time_class else None

    conn = db.connect()
    added = skipped = 0
    console.print(f"Fetching up to {limit} games for [cyan]{username}[/cyan] from {source} ...")

    try:
        for record in SOURCES[source].fetch(username, since=since, limit=limit,
                                            time_classes=classes):
            row = record.to_row(username)
            cols = ",".join(row)
            placeholders = ",".join("?" * len(row))
            cur = conn.execute(
                f"INSERT OR IGNORE INTO games ({cols}) VALUES ({placeholders})",
                tuple(row.values()),
            )
            if cur.rowcount:
                added += 1
            else:
                skipped += 1
        conn.commit()
    except Exception as exc:
        console.print(f"[red]Fetch failed: {exc}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]{added} new games[/green], {skipped} already stored. "
                  f"Total in database: {db.game_count(conn)}")
    if added:
        console.print("Next: [cyan]chess-coach analyze[/cyan]")


@app.command()
def analyze(
    limit: int = typer.Option(10, help="How many unanalyzed games to process."),
    game_id: str = typer.Option(None, help="Analyze one specific game."),
    redo: bool = typer.Option(False, "--redo", help="Re-analyze games already done."),
):
    """Run Stockfish over stored games and grade every move. The slow step."""
    ensure_dirs()
    cfg = load_config()
    conn = db.connect()

    if game_id:
        rows = conn.execute("SELECT * FROM games WHERE game_id = ?", (game_id,)).fetchall()
        if not rows:
            console.print(f"[red]No game {game_id}[/red]")
            raise typer.Exit(1)
    elif redo:
        rows = conn.execute(
            "SELECT * FROM games ORDER BY played_at DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = db.unanalyzed_games(conn, limit)

    if not rows:
        console.print("Nothing to analyze. Fetch some games, or pass --redo.")
        raise typer.Exit(0)

    console.print(f"Analyzing {len(rows)} games at depth {cfg.engine.depth}, "
                  f"{cfg.engine.multipv} lines per position.")
    console.print("[dim]CPU-bound, and it wants every core. Roughly 2.5 min per "
                  "80-ply game at depth 16 on 16 cores.[/dim]\n")

    try:
        with open_engine(cfg.engine) as engine:
            console.print(f"Engine: [cyan]{engine.name}[/cyan]\n")
            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(), TextColumn("{task.completed}/{task.total}"),
                TimeRemainingColumn(), console=console,
            ) as progress:
                overall = progress.add_task("Games", total=len(rows))
                for row in rows:
                    opponent = (row["black_user"] if row["my_color"] == "white"
                                else row["white_user"])
                    task = progress.add_task(f"  vs {opponent}", total=1)

                    def on_position(done: int, total: int, _t=task):
                        progress.update(_t, completed=done, total=total)

                    graded = analyze_mod.analyze_game(conn, row, engine, cfg,
                                                      progress=on_position)
                    progress.remove_task(task)
                    progress.advance(overall)
                    console.print(f"  {row['game_id']}: {graded} moves graded")
    except EngineNotFound as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    console.print("\n[green]Done.[/green] Next: [cyan]chess-coach trends[/cyan] "
                  "or [cyan]chess-coach brief[/cyan]")


@app.command()
def review(
    game_id: str = typer.Option(None, help="Which game to review."),
    last: bool = typer.Option(False, "--last", help="Review the most recent analyzed game."),
    save: bool = typer.Option(False, "--save", help="Also write it to reports/."),
):
    """Show the critical positions from a single game."""
    cfg = load_config()
    conn = db.connect()

    if last or not game_id:
        row = conn.execute(
            """
            SELECT g.game_id FROM games g
            JOIN analysis_runs r ON r.game_id = g.game_id
            ORDER BY g.played_at DESC LIMIT 1
            """
        ).fetchone()
        if row is None:
            console.print("No analyzed games yet. Run [cyan]chess-coach analyze[/cyan].")
            raise typer.Exit(1)
        game_id = row["game_id"]

    markdown = report.render_game_review(conn, game_id)
    console.print(markdown)

    if save:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / f"review_{game_id.replace(':', '_')}.md"
        path.write_text(markdown, encoding="utf-8")
        console.print(f"\n[green]Saved:[/green] {path}")


@app.command("trends")
def trends_cmd():
    """Aggregate patterns across every analyzed game."""
    cfg = load_config()
    conn = db.connect()
    moves = trends.load_moves(conn)
    games = trends.load_games(conn)

    if moves.empty:
        console.print("No analyzed games yet. Run [cyan]chess-coach analyze[/cyan].")
        raise typer.Exit(0)

    ov = trends.overview(moves, games)
    console.print(f"\n[bold]{ov['games_analyzed']} games[/bold] ({ov['record']}) · "
                  f"avg CPL [bold]{ov['avg_centipawn_loss']}[/bold] · "
                  f"{ov['blunders_per_game']} blunders/game · "
                  f"error rate {ov['error_rate_pct']}%\n")

    _print_df(trends.by_phase(moves), "Errors by phase")
    _print_df(trends.by_time_class(moves, games), "By time control")
    _print_df(trends.by_opening(moves, games, cfg), "Openings")

    motifs_df = trends.motif_frequency(moves)
    if not motifs_df.empty:
        table = Table(title="Recurring mistakes (ranked by total damage)",
                      title_style="bold")
        for col in ("Pattern", "Times", "Games", "Avg cost", "Total cost"):
            table.add_column(col)
        for _, r in motifs_df.head(12).iterrows():
            table.add_row(r["label"], str(r["occurrences"]), str(r["games_affected"]),
                          f"{r['avg_win_loss']:.0%}", f"{r['total_win_loss']:.2f}")
        console.print(table)

    console.print("\nFull detail: [cyan]chess-coach brief[/cyan]")


def _print_df(df, title: str) -> None:
    if df is None or df.empty:
        return
    out = df.reset_index()
    table = Table(title=title, title_style="bold")
    for col in out.columns:
        table.add_column(str(col))
    for rec in out.itertuples(index=False, name=None):
        table.add_row(*["" if v is None else str(v) for v in rec])
    console.print(table)


@app.command()
def brief():
    """Write the full coaching brief for an AI agent to interpret."""
    cfg = load_config()
    conn = db.connect()
    md_path, json_path = report.write_brief(conn, cfg)
    console.print(f"[green]Wrote:[/green]\n  {md_path}\n  {json_path}")
    console.print("\nNow ask your AI tool to read those and coach you. "
                  "See [cyan]CLAUDE.md[/cyan] for the contract it should follow.")


@app.command()
def status():
    """What is in the database right now."""
    cfg = load_config()
    conn = db.connect()
    total = db.game_count(conn)
    analyzed = len(db.analyzed_game_ids(conn))
    n_puzzles = conn.execute("SELECT COUNT(*) FROM puzzles").fetchone()[0]

    engine_path = cfg.engine.resolved_path()
    console.print(f"Config:   {'found' if CONFIG_PATH.exists() else 'MISSING (using defaults)'}")
    console.print(f"Player:   chess.com={cfg.chesscom_user or '-'} "
                  f"lichess={cfg.lichess_user or '-'}")
    console.print(f"Engine:   {engine_path} "
                  f"{'[green]OK[/green]' if engine_path.exists() else '[red]MISSING[/red]'}")
    console.print(f"Games:    {total} stored, {analyzed} analyzed")
    console.print(f"Puzzles:  {n_puzzles}")


# --------------------------------------------------------------------------
# Puzzles
# --------------------------------------------------------------------------

@puzzles_app.command("generate")
def puzzles_generate(
    min_swing: float = typer.Option(0.15, help="Minimum winning chances lost to qualify."),
    limit: int = typer.Option(None, help="Cap how many to generate."),
):
    """Turn your own critical mistakes into puzzles."""
    conn = db.connect()
    count = puzzles_mod.generate_from_games(conn, min_win_loss=min_swing, limit=limit)
    console.print(f"[green]{count} puzzles[/green] generated from your own games.")
    if count:
        console.print("List them: [cyan]chess-coach puzzles list[/cyan]")


@puzzles_app.command("list")
def puzzles_list(
    theme: str = typer.Option(None, help="Filter by motif or Lichess theme."),
    source: str = typer.Option(None, help="own_game | lichess_db"),
    limit: int = typer.Option(10),
    export: Path = typer.Option(None, help="Also write them to a PGN file."),
):
    """Show stored puzzles."""
    conn = db.connect()
    found = puzzles_mod.load(conn, theme=theme or "", source=source or "", limit=limit)
    if not found:
        console.print("No puzzles stored. Try [cyan]chess-coach puzzles generate[/cyan].")
        raise typer.Exit(0)

    for i, p in enumerate(found, 1):
        console.print(f"\n[bold]{i}. {p.puzzle_id}[/bold]")
        console.print(f"   FEN: {p.fen}")
        if p.played_san:
            console.print(f"   You played: [red]{p.played_san}[/red] → "
                          f"best was [green]{p.solution_san or p.solution_uci}[/green]")
        else:
            console.print(f"   Solution: [green]{p.solution_san or p.solution_uci}[/green]")
        console.print(f"   Themes: {', '.join(p.themes or []) or '-'}"
                      + (f" · Rating {p.rating}" if p.rating else "")
                      + (f" · Cost {p.win_swing:.0%}" if p.win_swing else ""))
        console.print(f"   [link={p.lichess_url()}]Open on Lichess[/link]: {p.lichess_url()}")

    if export:
        path = puzzles_mod.export_pgn(found, export)
        console.print(f"\n[green]Exported:[/green] {path}")


@puzzles_app.command("download-db")
def puzzles_download_db():
    """Download the free Lichess puzzle database (~250MB, one time)."""
    typer.confirm(
        "This downloads roughly 250MB from database.lichess.org. Continue?", abort=True
    )
    path = puzzles_mod.download_puzzle_db(log=lambda *a, **k: console.print(*a, **k))
    console.print(f"[green]Ready:[/green] {path}")


@puzzles_app.command("search")
def puzzles_search(
    theme: str = typer.Option(None, help="Lichess theme, e.g. fork, hangingPiece."),
    from_my_weaknesses: bool = typer.Option(
        False, "--from-my-weaknesses",
        help="Pick themes automatically from your own recurring mistakes.",
    ),
    min_rating: int = typer.Option(0),
    max_rating: int = typer.Option(4000),
    limit: int = typer.Option(20),
):
    """Pull matching puzzles out of the Lichess database."""
    conn = db.connect()
    themes: list[str] = []

    if from_my_weaknesses:
        moves = trends.load_moves(conn)
        motifs_df = trends.motif_frequency(moves)
        if motifs_df.empty:
            console.print("No recurring mistakes found yet. Analyze more games first.")
            raise typer.Exit(0)
        top = list(motifs_df.head(4).index)
        themes = puzzles_mod.themes_for_motifs(top)
        console.print(f"Your top patterns: {', '.join(top)}")
        console.print(f"Mapped to Lichess themes: {', '.join(themes) or 'none'}\n")
    elif theme:
        themes = [theme]
    else:
        console.print("[red]Pass --theme or --from-my-weaknesses.[/red]")
        raise typer.Exit(1)

    if not themes:
        console.print("No Lichess themes map to those patterns.")
        raise typer.Exit(0)

    try:
        found = puzzles_mod.search_puzzle_db(
            themes, rating_range=(min_rating, max_rating), limit=limit
        )
    except (FileNotFoundError, RuntimeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    puzzles_mod.store(conn, found)
    console.print(f"[green]{len(found)} puzzles[/green] stored. "
                  f"View: [cyan]chess-coach puzzles list --source lichess_db[/cyan]")


@puzzles_app.command("online")
def puzzles_online(
    theme: str = typer.Option("", help="Lichess theme angle, e.g. fork."),
    difficulty: str = typer.Option("", help="easiest | easier | normal | harder | hardest"),
):
    """Grab one puzzle from the Lichess API. No download needed."""
    conn = db.connect()
    try:
        puzzle = puzzles_mod.fetch_next_online(theme=theme, difficulty=difficulty)
    except Exception as exc:
        console.print(f"[red]Lichess API error: {exc}[/red]")
        raise typer.Exit(1)
    if puzzle is None:
        console.print("No puzzle returned.")
        raise typer.Exit(0)

    puzzles_mod.store(conn, [puzzle])
    console.print(f"[bold]{puzzle.puzzle_id}[/bold] (rating {puzzle.rating})")
    console.print(f"FEN: {puzzle.fen}")
    console.print(f"Themes: {', '.join(puzzle.themes or [])}")
    console.print(f"Solve it: {puzzle.lichess_url()}")
    console.print(f"[dim]Solution: {puzzle.solution_san or puzzle.solution_uci}[/dim]")


if __name__ == "__main__":
    app()
