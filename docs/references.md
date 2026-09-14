# Authoritative references

The coaching layer is expected to tie advice back to named, checkable theory
rather than inventing explanations. This file is the approved source list and
the mapping from the tool's motif tags to the concepts behind them.

Everything here is free and legitimately available. Where a book is listed, it
is one whose copyright has expired and which is hosted by Project Gutenberg or
a similar archive — not a scan of an in-copyright title.

## Primary free sources

| Source | What it covers | Link |
|---|---|---|
| Lichess Practice | Interactive drills: checkmate patterns, pawn endgames, piece endgames, tactical motifs. Built by titled players, free, no account needed. | https://lichess.org/practice |
| Lichess Learn | Fundamentals from piece movement up through basic tactics. | https://lichess.org/learn |
| Lichess Opening Explorer | Real master and amateur game statistics from any position. The reference for "what is actually played here". | https://lichess.org/analysis |
| Lichess Puzzle Themes | The canonical definition of each tactical theme name this tool maps onto. | https://lichess.org/training/themes |
| *Chess Fundamentals*, Capablanca (1921) | Endgame principles, simple positions, general strategy. Public domain. | https://www.gutenberg.org/ebooks/33870 |
| *Common Sense in Chess*, Lasker (1896) | Opening principles, attack and defence. Public domain. | https://www.gutenberg.org/ebooks/25447 |
| Wikibooks: Chess Opening Theory | Move-by-move opening reference, CC-licensed. | https://en.wikibooks.org/wiki/Chess_Opening_Theory |
| Chess Programming Wiki | How engines evaluate. Useful for understanding what the numbers mean, not for strategy. | https://www.chessprogramming.org/ |

## Motif → concept → where to read

When a report says you keep making a particular kind of error, this is the
concept it corresponds to and the reference that explains it.

| Tool motif | Concept | Reference |
|---|---|---|
| `hangs_piece`, `hangs_*` | Undefended pieces; blunder-checking before you move | Lichess Practice → "Piece checkmates"; the standard discipline is to check every enemy capture and check before committing |
| `missed_free_material` | Board vision; scanning for loose pieces (Nunn's "loose pieces drop off") | Lichess Puzzle theme `hangingPiece` |
| `missed_fork` | Double attack — the most common winning tactic below master level | Lichess Practice → "Fork"; puzzle theme `fork` |
| `missed_mate` | Mating patterns; calculation of forcing lines | Lichess Practice → "Checkmate patterns" |
| `allowed_mate`, `king_safety` | King safety, prophylaxis, counting attackers vs defenders | Lasker, *Common Sense in Chess*, lectures on attack |
| `back_rank` | Back-rank weakness; the luft/escape-square habit | Lichess Practice → "Checkmate patterns"; puzzle theme `backRankMate` |
| `missed_forcing_move` | Calculate forcing moves first: checks, captures, threats | Standard calculation method; puzzle themes `capturingDefender`, `discoveredAttack` |
| `quiet_move_missed` | Positional play — improving your worst piece, prophylaxis. The fix was not a tactic. | Nimzowitsch's overprotection and prophylaxis; Lichess puzzle theme `quietMove` |
| `material_grab` | Greed vs development; the cost of time | Lasker, *Common Sense in Chess*, on premature material grabbing |
| `endgame_technique` | Endgame fundamentals: opposition, king activity, rook behind the passer | Capablanca, *Chess Fundamentals*, Part II; Lichess Practice → endgame chapters |
| `opening_error` | Opening principles: centre, development, king safety, don't move a piece twice | Lasker, *Common Sense in Chess*, Lecture 1; Lichess Opening Explorer for the specific position |

## Rules for the coaching layer

These apply to any AI tool reading this repository.

1. **Cite the position, not just the principle.** "You hung a knight" is only
   useful attached to the actual game, move number, and FEN.
2. **Do not invent evaluations.** Every claim about whether a move was good
   comes from `move_evals`. If it is not in the database, do not assert it.
3. **Do not invent opening theory.** If you want to claim a move is the main
   line, check the Lichess Opening Explorer for that exact position. If you
   have not checked, say the theory claim is unverified.
4. **Name the source when citing theory.** "Capablanca's rule about rook
   endgames" is checkable. "Grandmasters generally recommend" is not.
5. **Respect the sample size.** Below `min_games_for_opening` games, an opening
   win rate is noise. Say so rather than building a study plan on it.
6. **Distinguish absence of evidence from evidence of absence.** The motif
   tagger does not detect pins or skewers. Never conclude the player is good at
   something because it does not appear in their error list.
