from datetime import datetime

import pytest
from helpers import make_streams
from rich.console import Console

from intervals_icu_pause_split import cli
from intervals_icu_pause_split.cli import Segment

SATURDAY_MORNING = datetime(2026, 8, 29, 6, 30)
STOP_SPEED = 3 / 3.6


def text_of(renderable) -> str:
    console = Console(width=120, record=True)
    console.print(renderable)
    return console.export_text()


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(45, "45 s"), (300, "5 min"), (3599, "59 min"), (3 * 3600 + 50 * 60, "3:50 h"), (25 * 3600, "25:00 h")],
)
def test_fmt_duration(seconds, expected):
    assert cli.fmt_duration(seconds) == expected


def test_fmt_clock():
    assert cli.fmt_clock(SATURDAY_MORNING, with_day=False) == "06:30"
    assert cli.fmt_clock(SATURDAY_MORNING, with_day=True) == "Sat 06:30"


def band(s, segments, width=60) -> tuple[str, list[str | None]]:
    """The characters and per-column styles inside the frame of the first band."""
    line = cli.render_timeline(s, [("New", segments)], SATURDAY_MORNING, width)[1]
    styles: list[str | None] = [None] * len(line.plain)
    for span in line.spans:
        for i in range(span.start, span.end):
            styles[i] = str(span.style)
    start, end = line.plain.index("│") + 1, line.plain.rindex("│")
    return line.plain[start:end], styles[start:end]


def test_short_pause_is_a_thin_mark_not_a_block():
    s = make_streams(("ride", 6 * 3600), ("stop", 360), ("ride", 6 * 3600))
    segments = cli.build_segments(s, cli.find_pauses(s, STOP_SPEED, 300, 60), "Leg")
    chars, _ = band(s, segments)
    # 6 minutes of 12 hours is well under one column: visible, but not inflated to a full one.
    assert chars.count(cli.SHORT_PAUSE_CHAR) == 1
    assert cli.PAUSE_CHAR not in chars


def test_pause_widths_stay_proportional():
    # One hour of pause in 21 hours on 48 columns is 2.3 columns, so two.
    s = make_streams(("ride", 10 * 3600), ("stop", 3600), ("ride", 10 * 3600))
    segments = cli.build_segments(s, cli.find_pauses(s, STOP_SPEED, 300, 60), "Leg")
    chars, _ = band(s, segments)
    assert len(chars) == 48
    assert chars.count(cli.PAUSE_CHAR) == 2


def test_rides_are_solid_and_alternate_colour():
    s = make_streams(("ride", 7200))
    chars, styles = band(s, [Segment("WORK", 0, 3600), Segment("WORK", 3600, 7200)])
    assert set(chars) == {cli.LEG_CHAR}
    assert set(styles) == set(cli.LEG_STYLES)


def test_tiny_ride_still_gets_a_column():
    s = make_streams(("ride", 7200))
    segments = [Segment("WORK", 0, 3590), Segment("WORK", 3590, 3600), Segment("WORK", 3600, 7200)]
    _, styles = band(s, segments)
    # Three legs alternate green, cyan, green: the cyan one only exists if the tiny one got a column.
    assert styles.count(cli.LEG_STYLES[1]) == 1


def test_tiny_warmup_is_not_swallowed_by_the_ride_after_it():
    s = make_streams(("ride", 7200))
    _, styles = band(s, [Segment("WORK", 0, 60, "Warmup"), Segment("WORK", 60, 7200)])
    assert styles[:2] == [cli.LEG_STYLES[0], cli.LEG_STYLES[1]]


def test_short_pause_wins_over_a_tiny_ride_in_the_same_column():
    s = make_streams(("ride", 7200))
    segments = [
        Segment("WORK", 0, 3590),
        Segment("RECOVERY", 3590, 3595),
        Segment("WORK", 3595, 3600),
        Segment("WORK", 3600, 7200),
    ]
    chars, _ = band(s, segments)
    assert chars.count(cli.SHORT_PAUSE_CHAR) == 1


def test_legend_states_the_column_width():
    s = make_streams(("ride", 4 * 3600))
    legend = cli.render_timeline(s, [], SATURDAY_MORNING, 60)[-1].plain
    assert "one column ≈ 5 min" in legend


def test_axis_marks_midnight_with_the_weekday():
    s = make_streams(("ride", 4 * 3600))
    lines = [x.plain for x in cli.render_timeline(s, [], datetime(2026, 8, 29, 22, 15), 80)]
    assert "23:00" in lines[-2]
    assert "Sun" in lines[-2]


def test_gap_leaves_the_speed_line_blank():
    s = make_streams(("ride", 3600), ("gap", 6 * 3600), ("ride", 3600))
    speed = cli.render_timeline(s, [], SATURDAY_MORNING, 60)[0].plain
    assert "    " in speed.split("│")[1]


def test_table_shows_ride_stats_and_blanks_for_pauses():
    s = make_streams(("ride", 600), ("stop", 400), ("ride", 600))
    segments = cli.build_segments(s, cli.find_pauses(s, STOP_SPEED, 300, 60), "Leg")
    out = text_of(cli.render_table(s, segments, SATURDAY_MORNING, STOP_SPEED, "New"))
    assert "Leg 1" in out
    assert "28.8" in out  # 8 m/s
    assert "150" in out
    assert "4.8 km" in out
    pause_row = next(x for x in out.splitlines() if "RECOVERY" in x)
    assert "06:40" in pause_row
    assert "—" in pause_row


def test_short_table_keeps_the_first_and_last_few():
    s = make_streams(("ride", 2000))
    segments = [Segment("WORK", i * 100, (i + 1) * 100, f"Leg {i + 1}") for i in range(20)]
    out = text_of(cli.render_table(s, segments, SATURDAY_MORNING, STOP_SPEED, "Now", short=True))
    assert "20 intervals, 11 not shown" in out
    shown = [f"Leg {i}" for i in (1, 6, 18, 20)]
    assert all(x in out for x in shown)
    assert "Leg 7 " not in out and "Leg 17" not in out
    assert "…" in out


def test_short_table_shows_everything_when_it_would_hide_one_row():
    s = make_streams(("ride", 1000))
    segments = [Segment("WORK", i * 100, (i + 1) * 100, f"Leg {i + 1}") for i in range(10)]
    out = text_of(cli.render_table(s, segments, SATURDAY_MORNING, STOP_SPEED, "Now", short=True))
    assert "Leg 7" in out
    assert "not shown" not in out


def test_table_shows_the_weekday_only_for_multi_day_activities():
    s = make_streams(("ride", 600))
    segments = [Segment("WORK", 0, 600, "Leg 1")]
    assert "Sat" not in text_of(cli.render_table(s, segments, SATURDAY_MORNING, STOP_SPEED, "New"))
    late = datetime(2026, 8, 29, 23, 55)
    assert "Sat 23:55" in text_of(cli.render_table(s, segments, late, STOP_SPEED, "New"))


def test_summary_counts_rides_and_pauses():
    s = make_streams(("ride", 600), ("stop", 400), ("ride", 600))
    segments = cli.build_segments(s, cli.find_pauses(s, STOP_SPEED, 300, 60), "Leg")
    assert cli.render_summary(s, segments) == "  2 legs · 20 min · 9.6 km   |   1 pause · 6 min"
