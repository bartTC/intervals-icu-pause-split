"""The terminal preview: a timeline drawn to scale, and tables of the intervals."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .detect import Segment, Streams, segment_stats, speed_profile, summarize
from .plan import Plan
from .units import fmt_duration

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SPARK = "▁▂▃▄▅▆▇█"
# Legs are always solid; the colour alternates so adjacent legs stay apart.
# A shaded block for every other leg reads as a pause in many fonts.
LEG_CHAR = "█"
LEG_STYLES = ("green", "cyan")
PAUSE_CHAR = "░"
SHORT_PAUSE_CHAR = "╎"  # a pause shorter than one column
PAUSE_STYLE = "yellow"

# The current intervals can be dozens of auto-detected few-second efforts; the
# timeline shows them all, the table only the first and last few.
SHORT_HEAD = 6
SHORT_TAIL = 3


def fmt_clock(dt: datetime, with_day: bool) -> str:
    return f"{WEEKDAYS[dt.weekday()]} {dt:%H:%M}" if with_day else f"{dt:%H:%M}"


def render_header(p: Plan) -> Panel:
    body = (
        f"[bold]{escape(p.activity.get('name') or p.activity_id)}[/]\n"
        f"{escape(p.sport)} · {fmt_clock(p.start, True)}, {p.start:%Y-%m-%d}"
        f" · {(p.activity.get('distance') or 0) / 1000:.1f} km"
        f" · {fmt_duration(p.streams.elapsed)} elapsed"
    )
    return Panel.fit(body, title=f"intervals.icu · {p.activity_id}", border_style="cyan")


def render_rule(p: Plan, restore: Path | None = None) -> str:
    """One or two lines saying how the new intervals came about."""
    if restore or not p.options:
        return f"Restoring the intervals from {escape(str(restore or 'a backup'))}"
    o = p.options
    rule = (
        f"Pause: at least {fmt_duration(o.min_pause)} below {p.stop_speed:g} km/h or not recording; "
        f"stops less than {fmt_duration(o.merge)} apart are merged"
    )
    if o.warmup or o.cooldown:
        rule += f"\n  Warmup: first {o.warmup or '—'} · Cooldown: last {o.cooldown or '—'}"
    return rule


def render_table(
    s: Streams, segments: list[Segment], start_dt: datetime, stop_speed: float, title: str, short: bool = False
) -> Table:
    """List the intervals; `short` keeps only the first and last few of a long list."""
    numbered = list(enumerate(segments, 1))
    hidden = len(numbered) - SHORT_HEAD - SHORT_TAIL
    if short and hidden > 1:
        numbered = [*numbered[:SHORT_HEAD], None, *numbered[-SHORT_TAIL:]]
        title += f"  [dim]{len(segments)} intervals, {hidden} not shown[/]"

    multi_day = (start_dt + timedelta(seconds=s.elapsed)).date() != start_dt.date()
    table = Table(title=title, title_justify="left", header_style="bold", box=None, pad_edge=False)
    for name in ("#", "Type", "Label", "Start", "Duration", "Distance", "km/h", "W"):
        table.add_column(name, justify="left" if name in ("Type", "Label") else "right")

    for row in numbered:
        if row is None:
            table.add_row(*["…"] * 8, style="dim")
            continue
        no, seg = row
        st = segment_stats(s, seg, stop_speed)
        moving = not seg.is_pause
        table.add_row(
            str(no),
            seg.type,
            Text(seg.label or "—"),
            fmt_clock(start_dt + timedelta(seconds=s.t(seg.start) - s.time[0]), multi_day),
            fmt_duration(st.elapsed),
            f"{st.distance / 1000:.1f} km",
            f"{st.speed:.1f}" if moving and st.speed is not None else "—",
            f"{st.watts:.0f}" if moving and st.watts is not None else "—",
            style=PAUSE_STYLE if seg.is_pause else None,
        )
    return table


def render_timeline(s: Streams, rows: list[tuple[str, list[Segment]]], start_dt: datetime, width: int) -> list[Text]:
    """Draw speed and interval bands on a shared wall-clock axis."""
    label_w = 9
    cols = max(20, width - label_w - 3)
    t0 = s.time[0]
    total = s.elapsed

    def col(t: float) -> float:
        return (t - t0) / total * cols

    def line(name: str, body: Text, left: str = "│", right: str = "│") -> Text:
        return Text(f"{name:<{label_w}} {left}") + body + Text(right)

    # Speed sparkline: average speed per column, blank where nothing was recorded.
    avgs = speed_profile(s, cols)
    vmax = max((a for a in avgs if a is not None), default=0) or 1
    spark = "".join(" " if a is None else SPARK[min(7, int(a / vmax * 8))] for a in avgs)
    lines = [line("Speed", Text(spark, style="blue"))]

    for name, segments in rows:
        band: list[tuple[str, str | None]] = [(" ", None)] * cols
        looks: list[tuple[Segment, str, str]] = []
        legs = 0
        for seg in segments:
            if seg.is_pause:
                looks.append((seg, PAUSE_CHAR, PAUSE_STYLE))
            else:
                looks.append((seg, LEG_CHAR, LEG_STYLES[legs % 2]))
                legs += 1

        # Every interval covers the columns whose midpoint it contains, which
        # keeps the widths proportional to the time ...
        tiny: list[tuple[Segment, str, str, int]] = []
        for seg, char, style in looks:
            lo, hi = col(s.t(seg.start)), col(s.t(seg.end))
            covered = [c for c in range(cols) if lo <= c + 0.5 < hi]
            if not covered:
                tiny.append((seg, char, style, min(cols - 1, int(lo))))
            for c in covered:
                band[c] = (char, style)
        # ... and one too short for that still shows up: a leg (a 5 km warmup on a
        # two-day trip) as a block, a pause as a thin mark. Painted last, pauses on
        # top, so the neighbour can't swallow them.
        for seg, char, style, c in sorted(tiny, key=lambda x: x[0].is_pause):
            band[c] = (SHORT_PAUSE_CHAR if seg.is_pause else char, style)
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
    legend.append(LEG_CHAR, LEG_STYLES[0]).append(LEG_CHAR, LEG_STYLES[1]).append(" moving   ")
    legend.append(PAUSE_CHAR, PAUSE_STYLE).append(" pause   ")
    legend.append(SHORT_PAUSE_CHAR, PAUSE_STYLE).append(" shorter pause   ")
    legend.append(f"{SPARK[0]}…{SPARK[-1]}", "blue").append(f" speed up to {vmax * 3.6:.0f} km/h")
    legend.append(f"   · one column ≈ {fmt_duration(total / cols)}", "dim")
    lines.append(legend)
    return lines


def render_summary(s: Streams, segments: list[Segment]) -> str:
    x = summarize(s, segments)
    return (
        f"  {x.legs} {'leg' if x.legs == 1 else 'legs'} · {fmt_duration(x.legs_elapsed)}"
        f" · {x.legs_distance / 1000:.1f} km"
        f"   |   {x.pauses} {'pause' if x.pauses == 1 else 'pauses'} · {fmt_duration(x.pauses_elapsed)}"
    )
