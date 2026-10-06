"""Builders for 1 Hz streams, and a fake intervals.icu behind httpx's MockTransport."""

import json

import httpx

from intervals_icu_pause_split import Client
from intervals_icu_pause_split.detect import Streams

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


class FakeIntervals:
    """Answers the calls the package makes for one activity and records every write.

    Set `interrupt` to "GET" or "PUT" to raise KeyboardInterrupt on that call,
    as if Ctrl-C hit while the request was in flight.
    """

    def __init__(self, streams, intervals=None, activity_id="i1", sport="GravelRide"):
        self.activity_id = activity_id
        self.streams = streams
        self.intervals = {"id": activity_id, "icu_intervals": intervals or []}
        self.sport = sport
        self.puts: list[tuple[str, list, dict]] = []
        self.interrupt: str | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == self.interrupt:
            raise KeyboardInterrupt
        path = request.url.path.removeprefix("/api/v1")
        base = f"/activity/{self.activity_id}"
        if request.method == "PUT" and path == f"{base}/intervals":
            body = json.loads(request.content)
            self.puts.append((path, body, dict(request.url.params)))
            return httpx.Response(200, json={"id": self.activity_id, "icu_intervals": body})
        if path == f"{base}/streams.json":
            return httpx.Response(200, json=as_json(self.streams))
        if path == f"{base}/intervals":
            return httpx.Response(200, json=self.intervals)
        if path == base:
            return httpx.Response(
                200,
                json={
                    "id": self.activity_id,
                    "type": self.sport,
                    "name": "Saturday [gravel]",
                    "start_date_local": "2026-08-29T06:30:00",
                    "distance": 9600,
                },
            )
        return httpx.Response(404, text="no such thing")

    def client(self, api_key="k", **kw) -> Client:
        return Client(api_key, transport=httpx.MockTransport(self.handler), **kw)
