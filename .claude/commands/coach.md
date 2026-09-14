---
description: Full coaching loop - fetch new games, analyze them, and deliver a session
---

Run a complete coaching session. Follow `AGENTS.md` throughout — especially the
rule that Stockfish judges positions and you explain, never the reverse.

1. `uv run chess-coach status` to see what exists.
2. If there are unfetched games, `uv run chess-coach fetch --limit 30`.
3. If there are unanalyzed games, `uv run chess-coach analyze --limit 15` in the
   background. Tell me it is running; do not block on it.
4. `uv run chess-coach brief`, then read `reports/brief.json`.
5. Deliver the session:
   - Open with the single most costly recurring pattern, with its count.
   - Prove it with two or three specific positions: move number, what I played,
     what the engine wanted, and the analysis-board link.
   - Tie it to named theory using the mapping in `docs/references.md`.
   - Say what is working, not only what is broken.
   - End with a concrete drill set, generated not described.

Be honest about sample size. If something happened twice, it happened twice —
that is not yet a pattern.

$ARGUMENTS
