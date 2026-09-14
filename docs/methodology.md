# How a move gets graded

Everything in this document is implemented in `scoring.py` and `analyze.py`. If
a number in a report looks wrong, this is the place to check the reasoning, and
the `move_evals` table is where you can check the arithmetic.

## One engine pass per position, not per move

A naive review evaluates the position before your move, then evaluates it again
after, for every move. That is two engine calls per move.

Instead we evaluate every *position* in the game once:

```
eval(P_i)      what was available to you at move i
-eval(P_i+1)   what you actually got, flipped to your point of view
```

The sign flip is because engine scores are always relative to whoever is on
move. After your move it is your opponent's turn, so their +150 is your -150.

A 60-move game costs ~61 evaluations instead of 120. This is the same approach
Lichess uses server-side.

## Centipawn loss is the wrong metric on its own

Centipawn loss is the gap between the best move and yours, measured in
hundredths of a pawn. It has a serious flaw for coaching:

| Position before | After your move | CPL | Actually matters? |
|---|---|---|---|
| +900 (winning) | +600 (winning) | 300 | No. Still completely winning. |
| +20 (equal) | −280 (losing) | 300 | Yes. You just lost the game. |

Identical CPL, opposite significance. Any metric that treats those the same
will mis-rank your mistakes, and you will end up studying the wrong ones.

## Winning chances instead

Centipawns are converted to a win probability first, using the logistic curve
Lichess fitted to real game outcomes:

```
winning chances = 1 / (1 + exp(-0.00368208 × centipawns))
```

This curve is steep near equality and flat once a position is decided — which
matches how chess actually works. A move is then graded by how much winning
chance it gave away:

| Winning chances lost | Grade |
|---|---|
| ≥ 0.30 | Blunder |
| ≥ 0.20 | Mistake |
| ≥ 0.10 | Inaccuracy |
| ≤ 0.02 | Best |
| otherwise | Good |

All four thresholds live in `config/config.toml` under `[analysis]`. Raise them
if you want only the egregious stuff; lower them if you want detail.

Applying this to the table above: the +900 → +600 move loses 6.4% winning
chances and is graded "good". The +20 → −280 move loses 25.6% and is graded a
mistake. Same 300cp, and the grading separates them the way a coach would.

## Decided positions are excluded from trends

If you are up a queen, or dead lost, your moves stop being instructive. The
engine will happily flag a slow move in a +2000 position as an inaccuracy, and
those entries drown out the ones you would actually learn from.

Any position where winning chances already exceed 90% for either side is marked
`was_decided = 1`. Those rows are stored — nothing is thrown away — but trend
reports filter them out by default. The threshold is `decided_threshold`.

## The opening book is skipped

The first 8 plies (4 moves each side) are not analyzed. The engine has opinions
about move 3 of a mainline that amount to "I prefer a different mainline",
which is not a mistake you made. `skip_opening_plies` controls this.

Genuine opening problems still surface — they just surface as bad positions by
move 10, which is what an opening problem actually looks like.

## Phase detection

Phase is by material, not move number: sum the non-pawn, non-king material on
the board. 14 points or less (roughly a queen and rook each, or less) is an
endgame. Before that, moves 1–12 are opening and the rest is middlegame.

This is a heuristic. A queenless position on move 15 gets called an endgame,
which is usually the right call for coaching purposes.

## Motif tagging, and its limits

`motifs.py` tags *what kind* of error a move was — hung a piece, missed a fork,
allowed mate, the fix was a quiet move. These are deterministic rules over the
board and the engine's own lines: "the opponent's best reply captures an
undefended piece worth 3 or more" is a checkable fact, not a judgement call.

Tagging only runs on moves that actually lost something — at least the
`inaccuracy` threshold. Without that gate the rules fire on sound play too: a
perfectly good recapture can leave a rook on a square with no defender, and the
move gets recorded as "hangs_rook" despite the engine grading it fine. Sound
moves are stored with no tags.

**What this is not:** a complete tactics classifier. It catches common,
checkable patterns. Pins, skewers, zwischenzug, deflection and most positional
themes are not detected. A move with no tags is not a move with no lesson — it
is a move where no rule matched.

This matters when reading trend reports. "Missed fork: 6 times" is a real
count. The absence of "pin" in your results means nothing at all.

## What the engine settings actually change

| Setting | Effect |
|---|---|
| `depth` | Search depth. Cost grows steeply and verdicts stop changing much past 16–18. |
| `multipv` | Lines computed per position. 2 lets a report say "this other move was also fine, yours was not" instead of just naming the single best. |
| `threads` | CPU cores. Defaults to your core count minus one so the machine stays usable. |
| `hash_mb` | Transposition table. 256MB is fine for this workload. |

Measured on a 16-core machine, timing one 40-move game (~72 analyzed positions):

| Settings | Per position | Per game |
|---|---|---|
| depth 14, multipv 2 | 0.73s | ~0.9 min |
| **depth 16, multipv 2** | **2.15s** | **~2.6 min** (default) |
| depth 16, multipv 3 | 2.76s | ~3.3 min |
| depth 18, multipv 3 | 4.34s | ~5.2 min |
| depth 20, multipv 3 | 9.17s | ~11 min |

The jump from 16 to 20 costs roughly 4× the time. For grading club-level
mistakes it changes very few verdicts, because the errors being caught are
worth hundreds of centipawns, not the handful of centipawns that extra depth
resolves. Reach for more depth when you want to settle one specific critical
position, not for a batch review.

## Known limitations

- **Depth changes verdicts.** A move graded a mistake at depth 16 can be fine
  at depth 24. Every stored evaluation records the depth it came from.
- **No opponent modelling.** "Best" means best against perfect play. Against a
  1200, an objectively second-best move that sets a trap may score better.
- **Blitz and bullet look worse than they are.** Compare like with like; that
  is what the `by_time_class` breakdown is for.
- **Sample size.** Opening win rates need games behind them. The
  `min_games_for_opening` floor exists to stop you studying noise.
