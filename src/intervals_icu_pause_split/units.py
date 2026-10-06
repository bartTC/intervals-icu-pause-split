"""Durations, distances and activity ids as people type them, and back."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .detect import Streams


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d} h"
    if seconds >= 60:
        return f"{seconds // 60} min"
    return f"{seconds} s"


def parse_duration(text: str) -> float:
    """'90s', '5m', '1.5h' -> seconds; a bare number means minutes."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(s|m|min|h)?\s*", text)
    if not m:
        raise ValueError(f"invalid duration {text!r}, use e.g. 90s, 5m or 1h")
    return float(m[1]) * {"s": 1, "m": 60, "min": 60, "h": 3600}[m[2] or "m"]


@dataclass(frozen=True)
class Edge:
    """How much of the start or end to split off: seconds, or metres when by_distance."""

    amount: float
    by_distance: bool = False

    def __str__(self) -> str:
        return f"{self.amount / 1000:g} km" if self.by_distance else fmt_duration(self.amount)

    def position(self, s: Streams, i: int) -> float:
        """Where sample i lies on this edge's scale: elapsed time or distance."""
        return s.distance_at(i) if self.by_distance else s.t(i)


def parse_edge(text: str) -> Edge:
    """'3km' is a distance, anything else a duration. Metres are left out: '5m' already means minutes."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*km\s*", text)
    if m:
        return Edge(float(m[1]) * 1000, by_distance=True)
    try:
        return Edge(parse_duration(text))
    except ValueError:
        raise ValueError(f"invalid edge {text!r}, use a duration (10m) or a distance (3km)") from None


def parse_edges(text: str) -> tuple[Edge, Edge]:
    """'5km' for both ends, '3km,10m' for warmup and cooldown separately.

    One comma-separated value rather than nargs, which would swallow the
    activity URL in `--edges 5km https://...`.
    """
    parts = text.split(",")
    if len(parts) > 2:
        raise ValueError(f"invalid edges {text!r}, give one length for both ends or two: 3km,10m")
    edges = [parse_edge(x) for x in parts]
    return edges[0], edges[-1]


def parse_activity_id(text: str) -> str:
    """Accept the bare id or the activity's intervals.icu URL."""
    m = re.search(r"/activities/([^/?#]+)", text)
    return m[1] if m else text.strip()
