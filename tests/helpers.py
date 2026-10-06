"""Builders for 1 Hz streams made of rides, standstills and auto-pause gaps."""

from intervals_icu_pause_split.cli import Streams

RIDE_SPEED = 8.0  # m/s, 28.8 km/h
RIDE_WATTS = 150


def make_streams(*parts: tuple[str, int]) -> Streams:
    """Build streams from ("ride", secs), ("stop", secs) and ("gap", secs) parts.

    "stop" keeps recording at zero speed; "gap" is what auto-pause leaves
    behind: no samples at all, just a jump in the time stream.
    """
    time, speed, distance, watts = [], [], [], []
    t, d = 0, 0.0
    for kind, secs in parts:
        if kind == "gap":
            t += secs
            continue
        v = RIDE_SPEED if kind == "ride" else 0.0
        for _ in range(secs):
            time.append(t)
            speed.append(v)
            distance.append(d)
            watts.append(RIDE_WATTS if v else 0)
            t += 1
            d += v
    return Streams(time, speed, distance, watts)


def as_json(s: Streams) -> list[dict]:
    """The shape GET /activity/{id}/streams.json answers with."""
    return [
        {"type": "time", "data": s.time},
        {"type": "velocity_smooth", "data": s.speed},
        {"type": "distance", "data": s.distance},
        {"type": "watts", "data": s.watts},
    ]
