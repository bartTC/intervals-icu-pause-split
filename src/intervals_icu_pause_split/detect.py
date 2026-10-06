"""Find the pauses in an activity's streams and turn them into intervals.

Everything here is plain computation on lists: no network, no output.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from .units import Edge

# Consecutive samples further apart than this mean the device was paused.
RECORDING_GAP_S = 10

# km/h below which you count as standing still. On foot a steep climb easily
# drops below 3 km/h, while GPS drift at a real stop stays under 1 km/h.
STOP_SPEED = 3.0
STOP_SPEED_ON_FOOT = 1.0
FOOT_TYPES = {"Hike", "Walk", "Run", "TrailRun", "VirtualRun", "Snowshoe"}

WARMUP_LABEL = "Warmup"
COOLDOWN_LABEL = "Cooldown"


@dataclass
class Streams:
    time: list[int]
    speed: list[float | None] | None  # m/s
    distance: list[float | None] | None  # cumulative m
    watts: list[float | None] | None

    def __len__(self) -> int:
        return len(self.time)

    def t(self, i: int) -> int:
        """Start time of sample i; sample i "owns" the time until sample i+1."""
        return self.time[i] if i < len(self.time) else self.time[-1] + 1

    @property
    def elapsed(self) -> int:
        return self.t(len(self)) - self.time[0]

    def distance_at(self, i: int) -> float:
        if not self.distance:
            return 0.0
        i = min(i, len(self.distance) - 1)
        while i >= 0 and self.distance[i] is None:
            i -= 1
        return self.distance[i] if i >= 0 else 0.0


@dataclass
class Segment:
    type: str  # intervals.icu interval type: WORK or RECOVERY
    start: int  # first sample index
    end: int  # one past the last sample, same as intervals.icu's end_index
    label: str = ""

    @property
    def is_pause(self) -> bool:
        return self.type == "RECOVERY"


def default_stop_speed(sport: str | None) -> float:
    """The stop speed in km/h for an intervals.icu activity type."""
    return STOP_SPEED_ON_FOOT if sport in FOOT_TYPES else STOP_SPEED


def is_stopped(s: Streams, i: int, stop_speed: float) -> bool:
    if s.t(i + 1) - s.time[i] > RECORDING_GAP_S:
        return True
    v = s.speed[i] if s.speed else None
    return v is not None and v < stop_speed


def find_pauses(s: Streams, stop_speed: float, min_pause: float, merge: float) -> list[tuple[int, int]]:
    """Return (start, end) sample ranges of pauses with at least min_pause seconds standstill.

    `stop_speed` is in m/s, `min_pause` and `merge` in seconds.
    """
    runs: list[list] = []  # [start, end, seconds stopped]
    i, n = 0, len(s)
    while i < n:
        if not is_stopped(s, i, stop_speed):
            i += 1
            continue
        j = i
        while j < n and is_stopped(s, j, stop_speed):
            j += 1
        runs.append([i, j, s.t(j) - s.time[i]])
        i = j

    # Pushing the bike from the café back to the road shouldn't split one pause in two.
    merged: list[list] = []
    for run in runs:
        if merged and s.time[run[0]] - s.t(merged[-1][1]) < merge:
            merged[-1][1] = run[1]
            merged[-1][2] += run[2]
        else:
            merged.append(run)

    return [(a, b) for a, b, stopped in merged if stopped >= min_pause]


def build_segments(
    s: Streams,
    pauses: list[tuple[int, int]],
    leg_label: str,
    warmup: Edge | None = None,
    cooldown: Edge | None = None,
) -> list[Segment]:
    segments: list[Segment] = []
    pos = 0
    for a, b in pauses:
        if a > pos:
            segments.append(Segment("WORK", pos, a))
        segments.append(Segment("RECOVERY", a, b))
        pos = b
    if pos < len(s):
        segments.append(Segment("WORK", pos, len(s)))

    segments = split_edges(s, segments, warmup, cooldown)
    for no, seg in enumerate((x for x in segments if not x.is_pause and not x.label), 1):
        seg.label = f"{leg_label} {no}"
    return segments


def first_reaching(s: Streams, edge: Edge, target: float, lo: int, hi: int) -> int:
    """First sample in [lo, hi) whose time or distance is at least target; hi if there is none."""
    return bisect.bisect_left(range(hi), target, lo, hi, key=lambda i: edge.position(s, i))


def split_edges(s: Streams, segments: list[Segment], warmup: Edge | None, cooldown: Edge | None) -> list[Segment]:
    """Cut the first `warmup` and last `cooldown` of moving into intervals of their own.

    Meant for getting out of and back into town, so the stop-and-go doesn't
    dilute the first and last leg. A leg too short to split becomes the
    warmup or cooldown as a whole.
    """
    legs = [i for i, x in enumerate(segments) if not x.is_pause]
    if not legs:
        return segments
    out = list(segments)

    # The cooldown goes first: splitting the last leg never shifts the index of the first.
    if cooldown and cooldown.amount:
        seg = out[legs[-1]]
        cut = first_reaching(s, cooldown, cooldown.position(s, seg.end) - cooldown.amount, seg.start, seg.end)
        if cut <= seg.start:
            seg.label = COOLDOWN_LABEL
        else:
            out[legs[-1] : legs[-1] + 1] = [
                Segment("WORK", seg.start, cut),
                Segment("WORK", cut, seg.end, COOLDOWN_LABEL),
            ]

    seg = out[legs[0]]
    if warmup and warmup.amount and not seg.label:
        cut = first_reaching(s, warmup, warmup.position(s, seg.start) + warmup.amount, seg.start, seg.end)
        if cut >= seg.end:
            seg.label = WARMUP_LABEL
        else:
            out[legs[0] : legs[0] + 1] = [
                Segment("WORK", seg.start, cut, WARMUP_LABEL),
                Segment("WORK", cut, seg.end),
            ]
    return out


def segments_from_intervals(intervals: list[dict]) -> list[Segment]:
    return [
        Segment(iv.get("type") or "WORK", iv["start_index"], iv["end_index"], iv.get("label") or "")
        for iv in intervals
    ]


def payload(segments: list[Segment]) -> list[dict]:
    """The WORK intervals to send; intervals.icu derives the RECOVERY ones from the gaps."""
    return [
        {"start_index": x.start, "end_index": x.end, "type": "WORK", "label": x.label or None}
        for x in segments
        if not x.is_pause
    ]


@dataclass
class Stats:
    elapsed: float  # s
    moving: float  # s
    distance: float  # m
    watts: float | None

    @property
    def speed(self) -> float | None:
        """Average moving speed in km/h."""
        return self.distance / self.moving * 3.6 if self.moving else None


def segment_stats(s: Streams, seg: Segment, stop_speed: float) -> Stats:
    watts = [w for w in (s.watts or [])[seg.start : seg.end] if w is not None]
    return Stats(
        elapsed=s.t(seg.end) - s.t(seg.start),
        moving=sum(s.t(i + 1) - s.time[i] for i in range(seg.start, seg.end) if not is_stopped(s, i, stop_speed)),
        distance=s.distance_at(seg.end) - s.distance_at(seg.start),
        watts=sum(watts) / len(watts) if watts else None,
    )


@dataclass
class Summary:
    legs: int
    legs_elapsed: float  # s
    legs_distance: float  # m
    pauses: int
    pauses_elapsed: float  # s


def summarize(s: Streams, segments: list[Segment]) -> Summary:
    legs = [x for x in segments if not x.is_pause]
    pauses = [x for x in segments if x.is_pause]
    return Summary(
        legs=len(legs),
        legs_elapsed=sum(s.t(x.end) - s.t(x.start) for x in legs),
        legs_distance=sum(s.distance_at(x.end) - s.distance_at(x.start) for x in legs),
        pauses=len(pauses),
        pauses_elapsed=sum(s.t(x.end) - s.t(x.start) for x in pauses),
    )


def speed_profile(s: Streams, buckets: int) -> list[float | None]:
    """Average speed in m/s per equal slice of elapsed time; None where nothing was recorded."""
    t0, total = s.time[0], s.elapsed
    sums, counts = [0.0] * buckets, [0] * buckets
    for i, t in enumerate(s.time):
        v = s.speed[i] if s.speed else None
        if v is not None:
            b = min(buckets - 1, int((t - t0) / total * buckets))
            sums[b] += v
            counts[b] += 1
    return [sums[b] / counts[b] if counts[b] else None for b in range(buckets)]
