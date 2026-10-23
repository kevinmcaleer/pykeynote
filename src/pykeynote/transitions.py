"""Slide transition effects that Keynote's scripting dictionary exposes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Enumerator names from Keynote's AppleScript dictionary. AppleScript can't
# turn a string into an enumerator, so the effect name is written into the
# script source. Only names on this list are accepted.
EFFECTS = frozenset(
    {
        "no transition effect",
        "magic move",
        "shimmer",
        "sparkle",
        "swing",
        "object cube",
        "object flip",
        "object pop",
        "object push",
        "object revolve",
        "object zoom",
        "perspective",
        "clothesline",
        "confetti",
        "dissolve",
        "drop",
        "droplet",
        "fade through color",
        "grid",
        "iris",
        "move in",
        "push",
        "reveal",
        "switch",
        "wipe",
        "blinds",
        "color planes",
        "cube",
        "doorway",
        "fall",
        "flip",
        "flop",
        "mosaic",
        "page flip",
        "pivot",
        "reflection",
        "revolving door",
        "scale",
        "swap",
        "swoosh",
        "twirl",
        "twist",
    }
)


def normalize_effect(name: str) -> str:
    """Turn ``"magicMove"``, ``"magic_move"`` or ``"Magic Move"`` into ``"magic move"``."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    spaced = re.sub(r"[_\-\s]+", " ", spaced).strip().lower()
    if spaced in ("none", ""):
        spaced = "no transition effect"
    if spaced not in EFFECTS:
        raise ValueError(f"Unknown transition effect {name!r}. Choose one of: {', '.join(sorted(EFFECTS))}")
    return spaced


@dataclass(frozen=True)
class Transition:
    """A slide's transition. ``duration`` and ``delay`` are in seconds."""

    effect: str
    duration: Optional[float] = None
    delay: Optional[float] = None
    automatic: Optional[bool] = None
