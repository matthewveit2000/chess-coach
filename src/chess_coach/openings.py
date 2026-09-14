"""Opening name normalization.

Both Chess.com and Lichess hand us an opening name with the game, so we never
need a local ECO database or a third-party lookup. What they *don't* give us is
a stable grouping: "Sicilian Defense: Najdorf Variation" and
"Sicilian-Defense-Closed" are the same repertoire decision from your point of
view, but sort as different strings.

`family()` collapses a full opening name down to the part you actually study.
"""

from __future__ import annotations

import re

# Words that end the "family" part of an opening name. Everything after the
# first one of these is variation detail.
_FAMILY_ANCHORS = (
    "defense",
    "defence",
    "opening",
    "game",
    "gambit",
    "attack",
    "system",
    "variation",
    "counter",
)

_ACCEPTED_DECLINED = re.compile(r"\b(accepted|declined)\b", re.I)


def name_from_eco_url(url: str) -> str:
    """Turn a Chess.com ECOUrl into a readable opening name.

    "https://www.chess.com/openings/Scandinavian-Defense-Mieses-Kotroc-Variation"
    -> "Scandinavian Defense Mieses Kotroc Variation"
    """
    if not url:
        return ""
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").replace("_", " ").strip()


def family(opening_name: str) -> str:
    """Collapse a full opening name to its family.

    "Sicilian Defense: Najdorf Variation"        -> "Sicilian Defense"
    "Queens Gambit Accepted Old Variation"       -> "Queens Gambit Accepted"
    "Scandinavian Defense Mieses Kotroc Variation" -> "Scandinavian Defense"
    """
    if not opening_name:
        return "Unknown"

    # Lichess uses "Family: Variation" -- that colon is the cleanest signal.
    head = opening_name.split(":", 1)[0].strip()

    words = head.split()
    for i, word in enumerate(words):
        if word.lower().strip(",") in _FAMILY_ANCHORS:
            # Keep a trailing Accepted/Declined: it is a different opening to play.
            if i + 1 < len(words) and _ACCEPTED_DECLINED.fullmatch(words[i + 1]):
                return " ".join(words[: i + 2])
            return " ".join(words[: i + 1])

    # No anchor word found (e.g. "Bishops Opening" variants, or odd names).
    # Fall back to the first three words, which is almost always the family.
    return " ".join(words[:3]) if words else "Unknown"
