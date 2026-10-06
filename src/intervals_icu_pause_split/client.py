"""A small intervals.icu API client with just the calls this package needs."""

from __future__ import annotations

import httpx

from . import __version__
from .detect import Streams
from .errors import AuthError, DataError, IntervalsError, NotFoundError

BASE = "https://intervals.icu/api/v1"
STREAM_TYPES = "time,velocity_smooth,distance,watts"


class Client:
    """intervals.icu API access for one athlete.

    Pass either an API key or an OAuth access token. An API key is sent as
    HTTP Basic with the literal username ``API_KEY`` -- the one detail
    everybody gets wrong first. An access token is what a service acting for
    other athletes gets from intervals.icu's OAuth flow.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        access_token: str | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if bool(api_key) == bool(access_token):
            raise ValueError("pass either api_key or access_token")
        headers = {"User-Agent": f"intervals-icu-pause-split/{__version__}"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        self.http = httpx.Client(
            base_url=BASE,
            auth=("API_KEY", api_key) if api_key else None,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def activity(self, activity_id: str) -> dict:
        return self._send("GET", f"/activity/{activity_id}")

    def streams(self, activity_id: str) -> Streams:
        raw = self._send("GET", f"/activity/{activity_id}/streams.json", params={"types": STREAM_TYPES})
        by_type = {s["type"]: s.get("data") for s in raw or []}
        if not by_type.get("time"):
            raise DataError(f"Activity {activity_id} has no time stream, so there is nothing to split.")
        return Streams(
            time=by_type["time"],
            speed=by_type.get("velocity_smooth"),
            distance=by_type.get("distance"),
            watts=by_type.get("watts"),
        )

    def intervals(self, activity_id: str) -> dict:
        """The activity's intervals as intervals.icu returns them: id, icu_intervals, icu_groups."""
        return self._send("GET", f"/activity/{activity_id}/intervals") or {}

    def replace_intervals(self, activity_id: str, intervals: list[dict]) -> dict:
        """Replace all intervals of the activity; intervals.icu answers with the new set."""
        return self._send("PUT", f"/activity/{activity_id}/intervals", params={"all": "true"}, json=intervals) or {}

    def _send(self, method: str, path: str, **kw):
        try:
            resp = self.http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise IntervalsError(f"Could not reach intervals.icu: {exc}") from exc
        if resp.status_code in (401, 403):
            raise AuthError(f"intervals.icu rejected the credentials (HTTP {resp.status_code}).", resp.status_code)
        if resp.status_code == 404:
            raise NotFoundError(f"Not found: {path}", resp.status_code)
        if resp.is_error:
            raise IntervalsError(f"HTTP {resp.status_code} on {method} {path}: {resp.text[:300]}", resp.status_code)
        return resp.json() if resp.content else None
