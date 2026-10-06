"""Split an intervals.icu activity into riding and pause intervals.

A pause is a stretch where you stood still (slower than --stop-speed) or the
device stopped recording, which is what auto-pause leaves behind: a jump in the
time stream. Stops with less than --merge of riding in between count as one
pause, and only pauses with at least --min-pause of standstill are kept.

Only the riding blocks are written, as WORK intervals. intervals.icu fills the
gaps between them with RECOVERY intervals on its own; it does not accept
RECOVERY intervals (or labels on them) through the API.

Nothing is written without confirmation, and the intervals that get replaced
are backed up first.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

from . import __version__

PROG = "intervals-icu-pause-split"
BASE = "https://intervals.icu/api/v1"

# Consecutive samples further apart than this mean the device was paused.
RECORDING_GAP_S = 10

WARMUP_LABEL = "Warmup"
COOLDOWN_LABEL = "Cooldown"

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SPARK = "▁▂▃▄▅▆▇█"
# Alternated so that adjacent riding intervals stay distinguishable.
RIDE_CHARS = ("█", "▓")
RIDE_STYLES = ("green", "cyan")
PAUSE_CHAR = "░"
PAUSE_STYLE = "yellow"

console = Console(highlight=False)

# Panels auf eine lesbare Breite begrenzen, statt sie das Terminal ausfuellen zu
# lassen. Schmale Terminals gewinnen weiterhin.
PANEL_WIDTH = 78


def panel(body: str, title: str, border_style: str) -> Panel:
    return Panel(body, title=title, border_style=border_style, width=min(PANEL_WIDTH, console.width))


def fail(message: str) -> None:
    console.print(panel(message, "Error", "red"))
    raise SystemExit(1)


class Api:
    """Thin intervals.icu client.

    Authentication is HTTP Basic with the literal username ``API_KEY`` and the
    key as the password -- the one detail everybody gets wrong first.
    """

    def __init__(self, key: str, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(
            base_url=BASE,
            auth=("API_KEY", key),
            timeout=60.0,
            headers={"User-Agent": f"{PROG}/{__version__}"},
            transport=transport,
        )

    def get(self, path: str, **params):
        return self._send("GET", path, params=params)

    def put(self, path: str, body, **params):
        return self._send("PUT", path, params=params, json=body)

    def _send(self, method: str, path: str, **kw):
        try:
            resp = self.client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            fail(f"Could not reach intervals.icu: {exc}")
        if resp.status_code in (401, 403):
            fail(
                "intervals.icu rejected the credentials.\n"
                "Check the API key at https://intervals.icu/settings (bottom of the page)."
            )
        if resp.status_code == 404:
            fail(f"Not found: {path}\nCheck the activity id, and that your API key can see it.")
        if resp.is_error:
            fail(f"HTTP {resp.status_code} on {method} {path}\n{resp.text[:300]}")
        return resp.json() if resp.content else None


# --- Detection ----------------------------------------------------------------


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


def fetch_streams(api: Api, activity_id: str) -> Streams:
    raw = api.get(f"/activity/{activity_id}/streams.json", types="time,velocity_smooth,distance,watts")
    by_type = {s["type"]: s.get("data") for s in raw or []}
    if not by_type.get("time"):
        fail(f"Activity {activity_id} has no time stream, so there is nothing to split.")
    return Streams(
        time=by_type["time"],
        speed=by_type.get("velocity_smooth"),
        distance=by_type.get("distance"),
        watts=by_type.get("watts"),
    )


def is_stopped(s: Streams, i: int, stop_speed: float) -> bool:
    if s.t(i + 1) - s.time[i] > RECORDING_GAP_S:
        return True
    v = s.speed[i] if s.speed else None
    return v is not None and v < stop_speed


def find_pauses(s: Streams, stop_speed: float, min_pause: float, merge: float) -> list[tuple[int, int]]:
    """Return (start, end) sample ranges of pauses with at least min_pause seconds standstill."""
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
    s: Streams, pauses: list[tuple[int, int]], ride_label: str, warmup: float = 0, cooldown: float = 0
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
        seg.label = f"{ride_label} {no}"
    return segments


def split_edges(s: Streams, segments: list[Segment], warmup: float, cooldown: float) -> list[Segment]:
    """Cut the first `warmup` and last `cooldown` seconds of riding into intervals of their own.

    Meant for riding out of and back into town, so the stop-and-go doesn't
    dilute the first and last block. A ride too short to split becomes the
    warmup or cooldown as a whole.
    """
    rides = [i for i, x in enumerate(segments) if not x.is_pause]
    if not rides:
        return segments
    out = list(segments)

    # The cooldown goes first: splitting the last ride never shifts the index of the first.
    if cooldown:
        seg = out[rides[-1]]
        cut = bisect.bisect_left(s.time, s.t(seg.end) - cooldown, seg.start, seg.end)
        if cut <= seg.start:
            seg.label = COOLDOWN_LABEL
        else:
            out[rides[-1] : rides[-1] + 1] = [
                Segment("WORK", seg.start, cut),
                Segment("WORK", cut, seg.end, COOLDOWN_LABEL),
            ]

    seg = out[rides[0]]
    if warmup and not seg.label:
        cut = bisect.bisect_left(s.time, s.time[seg.start] + warmup, seg.start, seg.end)
        if cut >= seg.end:
            seg.label = WARMUP_LABEL
        else:
            out[rides[0] : rides[0] + 1] = [
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


# --- Rendering ----------------------------------------------------------------


@dataclass
class Stats:
    elapsed: float
    moving: float
    distance: float  # m
    watts: float | None


def segment_stats(s: Streams, seg: Segment, stop_speed: float) -> Stats:
    watts = [w for w in (s.watts or [])[seg.start : seg.end] if w is not None]
    return Stats(
        elapsed=s.t(seg.end) - s.t(seg.start),
        moving=sum(s.t(i + 1) - s.time[i] for i in range(seg.start, seg.end) if not is_stopped(s, i, stop_speed)),
        distance=s.distance_at(seg.end) - s.distance_at(seg.start),
        watts=sum(watts) / len(watts) if watts else None,
    )


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d} h"
    if seconds >= 60:
        return f"{seconds // 60} min"
    return f"{seconds} s"


def fmt_clock(dt: datetime, with_day: bool) -> str:
    return f"{WEEKDAYS[dt.weekday()]} {dt:%H:%M}" if with_day else f"{dt:%H:%M}"


def render_table(s: Streams, segments: list[Segment], start_dt: datetime, stop_speed: float, title: str) -> Table:
    multi_day = (start_dt + timedelta(seconds=s.t(len(s)))).date() != start_dt.date()
    table = Table(title=title, title_justify="left", header_style="bold", box=None, pad_edge=False)
    for name in ("#", "Type", "Label", "Start", "Duration", "Distance", "km/h", "W"):
        table.add_column(name, justify="left" if name in ("Type", "Label") else "right")

    for no, seg in enumerate(segments, 1):
        st = segment_stats(s, seg, stop_speed)
        riding = not seg.is_pause
        table.add_row(
            str(no),
            seg.type,
            Text(seg.label or "—"),
            fmt_clock(start_dt + timedelta(seconds=s.t(seg.start)), multi_day),
            fmt_duration(st.elapsed),
            f"{st.distance / 1000:.1f} km",
            f"{st.distance / st.moving * 3.6:.1f}" if riding and st.moving else "—",
            f"{st.watts:.0f}" if riding and st.watts is not None else "—",
            style=PAUSE_STYLE if seg.is_pause else None,
        )
    return table


def render_timeline(s: Streams, rows: list[tuple[str, list[Segment]]], start_dt: datetime, width: int) -> list[Text]:
    """Draw speed and interval bands on a shared wall-clock axis."""
    label_w = 9
    cols = max(20, width - label_w - 3)
    t0 = s.time[0]
    total = s.t(len(s)) - t0

    def col(t: float) -> float:
        return (t - t0) / total * cols

    def line(name: str, body: Text, left: str = "│", right: str = "│") -> Text:
        return Text(f"{name:<{label_w}} {left}") + body + Text(right)

    # Speed sparkline: average speed per column, blank where nothing was recorded.
    sums, counts = [0.0] * cols, [0] * cols
    for i, t in enumerate(s.time):
        v = s.speed[i] if s.speed else None
        if v is not None:
            c = min(cols - 1, int(col(t)))
            sums[c] += v
            counts[c] += 1
    avgs = [sums[c] / counts[c] if counts[c] else None for c in range(cols)]
    vmax = max((a for a in avgs if a is not None), default=0) or 1
    spark = "".join(" " if a is None else SPARK[min(7, int(a / vmax * 8))] for a in avgs)
    lines = [line("Speed", Text(spark, style="blue"))]

    for name, segments in rows:
        band: list[tuple[str, str | None]] = [(" ", None)] * cols
        # Rides cover the columns whose midpoint they contain. One too short for
        # that (a 10 min warmup on a two-day trip) gets a single column, painted
        # last so its neighbour can't swallow it ...
        tiny: list[tuple[int, int]] = []
        for ordinal, seg in enumerate(x for x in segments if not x.is_pause):
            lo, hi = col(s.t(seg.start)), col(s.t(seg.end))
            covered = [c for c in range(cols) if lo <= c + 0.5 < hi]
            if not covered:
                tiny.append((ordinal, min(cols - 1, int(lo))))
            for c in covered:
                band[c] = (RIDE_CHARS[ordinal % 2], RIDE_STYLES[ordinal % 2])
        for ordinal, c in tiny:
            band[c] = (RIDE_CHARS[ordinal % 2], RIDE_STYLES[ordinal % 2])
        # ... and pauses are painted on top with at least one column, so short ones stay visible.
        for seg in (x for x in segments if x.is_pause):
            lo = min(cols - 1, int(col(s.t(seg.start))))
            hi = max(lo + 1, math.ceil(col(s.t(seg.end))))
            for c in range(lo, min(hi, cols)):
                band[c] = (PAUSE_CHAR, PAUSE_STYLE)
        body = Text()
        for char, style in band:
            body.append(char, style=style)
        lines.append(line(name, body))

    # Clock axis with ticks on full hours; midnight is labelled with the weekday.
    hours = total / 3600
    step = next((h for h in (1, 2, 3, 4, 6, 12, 24) if hours / h <= cols / 7), 48)
    axis, labels = ["─"] * cols, [" "] * (cols + 6)
    tick = start_dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while tick.hour % step:
        tick += timedelta(hours=1)
    end_dt = start_dt + timedelta(seconds=total)
    free_from = 0
    while tick < end_dt:
        c = int(col(t0 + (tick - start_dt).total_seconds()))
        if c < cols:
            axis[c] = "┴"
            text = WEEKDAYS[tick.weekday()] if tick.hour == 0 else f"{tick:%H}:00"
            if c >= free_from:
                labels[c : c + len(text)] = text
                free_from = c + len(text) + 1
        tick += timedelta(hours=step)
    lines.append(line("", Text("".join(axis)), "└", "┘"))
    lines.append(Text(" " * (label_w + 2) + "".join(labels).rstrip()))

    legend = Text(" " * (label_w + 2))
    legend.append(RIDE_CHARS[0], RIDE_STYLES[0]).append(RIDE_CHARS[1], RIDE_STYLES[1]).append(" ride   ")
    legend.append(PAUSE_CHAR, PAUSE_STYLE).append(" pause   ")
    legend.append(f"{SPARK[0]}…{SPARK[-1]}", "blue").append(f" speed up to {vmax * 3.6:.0f} km/h")
    lines.append(legend)
    return lines


def render_summary(s: Streams, segments: list[Segment]) -> str:
    rides = [x for x in segments if not x.is_pause]
    pauses = [x for x in segments if x.is_pause]
    ride_s = sum(s.t(x.end) - s.t(x.start) for x in rides)
    ride_km = sum(s.distance_at(x.end) - s.distance_at(x.start) for x in rides) / 1000
    pause_s = sum(s.t(x.end) - s.t(x.start) for x in pauses)
    return (
        f"  {len(rides)} {'ride' if len(rides) == 1 else 'rides'} · {fmt_duration(ride_s)} · {ride_km:.1f} km"
        f"   |   {len(pauses)} {'pause' if len(pauses) == 1 else 'pauses'} · {fmt_duration(pause_s)}"
    )


# --- Backups ------------------------------------------------------------------


def backup_dir() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(state) / PROG / "backups"


def save_backup(activity_id: str, current: dict) -> Path:
    folder = backup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{activity_id}-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(current, indent=2))
    return path


def load_backup(path: Path, activity_id: str) -> list[Segment]:
    try:
        backup = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        fail(f"Cannot read backup {path}: {exc}")
    if backup.get("id") not in (None, activity_id):
        fail(f"Backup {path} belongs to {backup['id']}, not {activity_id}.")
    return segments_from_intervals(backup.get("icu_intervals") or [])


# --- CLI ----------------------------------------------------------------------


def parse_duration(text: str) -> float:
    """'90s', '5m', '1.5h' -> seconds; a bare number means minutes."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(s|m|min|h)?\s*", text)
    if not m:
        raise argparse.ArgumentTypeError(f"invalid duration {text!r}, use e.g. 90s, 5m or 1h")
    return float(m[1]) * {"s": 1, "m": 60, "min": 60, "h": 3600}[m[2] or "m"]


def parse_activity_id(text: str) -> str:
    """Accept the bare id or the activity's intervals.icu URL."""
    m = re.search(r"/activities/([^/?#]+)", text)
    return m[1] if m else text.strip()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=PROG, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("activity", help="Activity id (i181405932) or its URL (https://intervals.icu/activities/i181405932)")
    p.add_argument("--api-key", help="intervals.icu API key (env: INTERVALS_ICU_API_KEY)")
    p.add_argument(
        "--min-pause", type=parse_duration, default=parse_duration("5m"), metavar="DURATION",
        help="Minimum standstill for a pause, e.g. 90s, 5m, 1h; a bare number is minutes (default: 5m)",
    )
    p.add_argument(
        "--merge", type=parse_duration, default=parse_duration("60s"), metavar="DURATION",
        help="Stops with less riding than this in between count as one pause (default: 60s)",
    )
    p.add_argument(
        "--stop-speed", type=float, default=3.0, metavar="KMH",
        help="Below this speed you count as standing still, in km/h (default: 3)",
    )
    p.add_argument(
        "--edges", type=parse_duration, nargs="+", metavar="DURATION",
        help="Split the first and last DURATION of riding into Warmup and Cooldown intervals, e.g. for riding "
        "out of and back into town. Two values set them separately: --edges 10m 15m",
    )
    p.add_argument("--label", default="Ride", help="Label prefix for the riding intervals (default: Ride)")
    p.add_argument("--width", type=int, help="Width of the timeline (default: terminal width)")
    p.add_argument("--restore", type=Path, metavar="BACKUP", help="Put back the intervals from a backup file")
    p.add_argument("--dry-run", action="store_true", help="Show the preview, never write")
    p.add_argument("--yes", action="store_true", help="Write without asking")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def resolve_api_key(args: argparse.Namespace) -> str:
    load_dotenv()
    key = args.api_key or os.environ.get("INTERVALS_ICU_API_KEY")
    if not key:
        fail(
            "No API key.\n\n"
            "Pass --api-key, set INTERVALS_ICU_API_KEY, or put it in a .env file.\n"
            "You find the key at the bottom of https://intervals.icu/settings"
        )
    return key


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.edges and len(args.edges) > 2:
        parser.error("--edges takes one duration for both ends, or two for start and end")
    warmup, cooldown = (args.edges[0], args.edges[-1]) if args.edges else (0, 0)
    if args.width:
        console.width = args.width
    api = Api(resolve_api_key(args))
    activity_id = parse_activity_id(args.activity)

    activity = api.get(f"/activity/{activity_id}")
    streams = fetch_streams(api, activity_id)
    current = api.get(f"/activity/{activity_id}/intervals") or {}
    current_segments = segments_from_intervals(current.get("icu_intervals") or [])
    stop_speed = args.stop_speed / 3.6

    if args.restore:
        new_segments = load_backup(args.restore, activity_id)
        rule = f"Restoring the intervals from {escape(str(args.restore))}"
    else:
        pauses = find_pauses(streams, stop_speed, args.min_pause, args.merge)
        new_segments = build_segments(streams, pauses, args.label, warmup, cooldown)
        rule = (
            f"Pause: at least {fmt_duration(args.min_pause)} below {args.stop_speed:g} km/h or not recording; "
            f"stops less than {fmt_duration(args.merge)} apart are merged"
        )
        if warmup or cooldown:
            rule += f"\n  Warmup: first {fmt_duration(warmup)} of riding · Cooldown: last {fmt_duration(cooldown)}"

    start_dt = datetime.fromisoformat(activity["start_date_local"])
    elapsed = streams.t(len(streams)) - streams.time[0]
    header = (
        f"[bold]{escape(activity.get('name') or activity_id)}[/]\n"
        f"{fmt_clock(start_dt, True)}, {start_dt:%Y-%m-%d} · {(activity.get('distance') or 0) / 1000:.1f} km"
        f" · {fmt_duration(elapsed)} elapsed"
    )
    console.print()
    console.print(Panel.fit(header, title=f"intervals.icu · {activity_id}", border_style="cyan"))
    console.print(f"  [dim]{rule}[/]\n")

    for line in render_timeline(streams, [("Now", current_segments), ("New", new_segments)], start_dt, console.width):
        console.print(line, no_wrap=True)
    console.print()
    if current_segments:
        console.print(render_table(streams, current_segments, start_dt, stop_speed, "Now"))
    else:
        console.print("[bold]Now[/]  [dim]no intervals[/]")
    console.print()
    console.print(render_table(streams, new_segments, start_dt, stop_speed, "New"))
    console.print(render_summary(streams, new_segments))
    console.print()

    if payload(new_segments) == payload(current_segments):
        console.print("  The activity already has these intervals, nothing to do.\n")
        return
    if args.dry_run:
        console.print("  [dim]--dry-run, nothing written.[/]\n")
        return
    if not args.yes:
        if not sys.stdin.isatty():
            console.print("  [yellow]Not a terminal; pass --yes to write unattended.[/]\n")
            return
        question = f"  Replace the {len(current_segments)} intervals with these {len(new_segments)}?"
        if not Confirm.ask(question, default=False):
            console.print("\n  Cancelled, nothing changed.\n")
            return

    backup = save_backup(activity_id, current)
    result = api.put(f"/activity/{activity_id}/intervals", payload(new_segments), all="true") or {}
    written = len(result.get("icu_intervals") or [])
    console.print(f"\n  [green]✓[/] {written} intervals set → https://intervals.icu/activities/{activity_id}")
    console.print(f"  [dim]Undo with: {PROG} {activity_id} --restore {escape(str(backup))}[/]\n")


if __name__ == "__main__":
    main()
