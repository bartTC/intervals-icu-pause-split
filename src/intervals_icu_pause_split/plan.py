"""Work out a split for an activity, describe it as plain data, and write it.

This is the part to build on from other code, e.g. a web service:

    with Client(access_token=token) as client:
        p = plan(client, "https://intervals.icu/activities/i87942121", Options.parse(edges="5km"))
        p.to_dict()            # JSON-ready, for drawing your own preview
        result = apply(client, p)
        result.previous        # the intervals before, to undo with plan_restore()
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from .client import Client
from .detect import (
    Segment,
    Stats,
    Streams,
    Summary,
    build_segments,
    default_stop_speed,
    find_pauses,
    payload,
    segment_stats,
    segments_from_intervals,
    speed_profile,
    summarize,
)
from .errors import DataError
from .units import Edge, parse_activity_id, parse_duration, parse_edges


@dataclass(frozen=True)
class Options:
    """How pauses are found and how the moving legs are labelled.

    Durations are in seconds, the stop speed in km/h; `stop_speed=None` picks
    one for the sport. `Options.parse` takes the strings the command line
    takes ("5m", "3km,10m"), for forms and query strings.
    """

    min_pause: float = 300
    merge: float = 60
    stop_speed: float | None = None
    warmup: Edge | None = None
    cooldown: Edge | None = None
    label: str = "Leg"

    @classmethod
    def parse(
        cls,
        *,
        min_pause: str = "5m",
        merge: str = "60s",
        stop_speed: str | float | None = None,
        edges: str | None = None,
        label: str = "Leg",
    ) -> Options:
        """Raises ValueError with a readable message for anything it can't parse."""
        warmup, cooldown = parse_edges(edges) if edges else (None, None)
        return cls(
            min_pause=parse_duration(min_pause),
            merge=parse_duration(merge),
            stop_speed=float(stop_speed) if stop_speed not in (None, "") else None,
            warmup=warmup,
            cooldown=cooldown,
            label=label,
        )


@dataclass
class Plan:
    """A proposed split: what the activity has now, and what it would get."""

    activity_id: str
    activity: dict  # the activity as intervals.icu returns it
    streams: Streams
    stop_speed: float  # km/h, as used for this plan
    current: list[Segment]
    new: list[Segment]
    previous: dict  # GET /intervals as it was; keep it to undo
    options: Options | None = None  # None when restoring a backup

    @property
    def sport(self) -> str:
        return self.activity.get("type") or "activity"

    @property
    def start(self) -> datetime:
        """Local start time of the activity."""
        return datetime.fromisoformat(self.activity["start_date_local"])

    @property
    def has_changes(self) -> bool:
        return payload(self.new) != payload(self.current)

    def stats(self, seg: Segment) -> Stats:
        return segment_stats(self.streams, seg, self.stop_speed / 3.6)

    def summary(self) -> Summary:
        return summarize(self.streams, self.new)

    def to_dict(self, speed_points: int = 200) -> dict:
        """Everything a preview needs, as JSON-ready values.

        Times are seconds from the activity start plus local ISO timestamps,
        distances metres. `speed` is the average speed in km/h over
        `speed_points` equal slices of the elapsed time, null where the device
        was not recording.
        """
        s = self.streams
        summary = self.summary()
        return {
            "activity": {
                "id": self.activity_id,
                "name": self.activity.get("name"),
                "type": self.activity.get("type"),
                "start": self.start.isoformat(),
                "distance_m": self.activity.get("distance"),
                "elapsed_s": s.elapsed,
            },
            "options": asdict(self.options) if self.options else None,
            "stop_speed_kmh": self.stop_speed,
            "has_changes": self.has_changes,
            "current": [self._segment_dict(x) for x in self.current],
            "new": [self._segment_dict(x) for x in self.new],
            "summary": {**asdict(summary), "legs_distance": round(summary.legs_distance, 1)},
            "speed": {
                "slice_s": s.elapsed / speed_points,
                "kmh": [None if v is None else round(v * 3.6, 1) for v in speed_profile(s, speed_points)],
            },
        }

    def _segment_dict(self, seg: Segment) -> dict:
        st = self.stats(seg)
        start_s = self.streams.t(seg.start) - self.streams.time[0]
        moving = not seg.is_pause
        return {
            "type": seg.type,
            "label": seg.label or None,
            "start_index": seg.start,
            "end_index": seg.end,
            "start_s": start_s,
            "end_s": start_s + st.elapsed,
            "start": (self.start + timedelta(seconds=start_s)).isoformat(),
            "elapsed_s": st.elapsed,
            "moving_s": st.moving,
            "distance_m": round(st.distance, 1),
            "avg_kmh": round(st.speed, 1) if moving and st.speed is not None else None,
            "avg_watts": round(st.watts) if moving and st.watts is not None else None,
        }


@dataclass
class Result:
    """What apply() wrote, and what was there before."""

    intervals: list[dict]  # as intervals.icu stored them, RECOVERY gaps included
    previous: dict  # GET /intervals before the write


def _fetch(client: Client, activity_id: str) -> tuple[dict, Streams, dict]:
    return client.activity(activity_id), client.streams(activity_id), client.intervals(activity_id)


def plan(client: Client, activity: str, options: Options | None = None) -> Plan:
    """Fetch the activity (an id or its URL) and work out the split, without writing anything."""
    options = options or Options()
    activity_id = parse_activity_id(activity)
    data, streams, previous = _fetch(client, activity_id)
    if any(e and e.by_distance for e in (options.warmup, options.cooldown)) and not streams.distance:
        raise DataError(
            f"Activity {activity_id} has no distance stream, so warmup and cooldown have to be a duration (10m), "
            "not a distance."
        )
    stop_speed = options.stop_speed if options.stop_speed is not None else default_stop_speed(data.get("type"))
    pauses = find_pauses(streams, stop_speed / 3.6, options.min_pause, options.merge)
    return Plan(
        activity_id=activity_id,
        activity=data,
        streams=streams,
        stop_speed=stop_speed,
        current=segments_from_intervals(previous.get("icu_intervals") or []),
        new=build_segments(streams, pauses, options.label, options.warmup, options.cooldown),
        previous=previous,
        options=options,
    )


def plan_restore(client: Client, activity: str, backup: dict, stop_speed: float | None = None) -> Plan:
    """Plan putting back intervals saved from `Plan.previous` or `Result.previous`."""
    activity_id = parse_activity_id(activity)
    if backup.get("id") not in (None, activity_id):
        raise DataError(f"The backup belongs to {backup['id']}, not {activity_id}.")
    data, streams, previous = _fetch(client, activity_id)
    return Plan(
        activity_id=activity_id,
        activity=data,
        streams=streams,
        stop_speed=stop_speed if stop_speed is not None else default_stop_speed(data.get("type")),
        current=segments_from_intervals(previous.get("icu_intervals") or []),
        new=segments_from_intervals(backup.get("icu_intervals") or []),
        previous=previous,
    )


def apply(client: Client, p: Plan) -> Result:
    """Write the plan's moving legs; intervals.icu derives the pauses from the gaps between them."""
    response = client.replace_intervals(p.activity_id, payload(p.new))
    return Result(intervals=response.get("icu_intervals") or [], previous=p.previous)
