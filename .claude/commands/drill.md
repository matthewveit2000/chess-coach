---
description: Build a practice set targeting my current weaknesses
---

Build me a training set.

1. `uv run chess-coach trends` to find my top recurring motifs.
2. `uv run chess-coach puzzles generate` — positions from my own games. These
   matter most: I actually reached them and actually got them wrong.
3. `uv run chess-coach puzzles search --from-my-weaknesses --limit 30` for
   volume from the Lichess database. If the database is not downloaded, say so
   and offer `puzzles download-db` rather than downloading ~250MB unasked.
4. Export: `uv run chess-coach puzzles list --limit 30 --export reports/drill.pgn`

Then tell me, briefly:
- Which pattern each group targets and what it is costing me, in winning
  chances, from the actual data.
- What to look for in these positions — the specific search habit that would
  have caught them, not "calculate more carefully".
- The order to work through them.

$ARGUMENTS
