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


def test_short_pause_stays_visible_on_a_long_timeline():
    s = make_streams(("ride", 6 * 3600), ("stop", 360), ("ride", 6 * 3600))
    segments = cli.build_segments(s, cli.find_pauses(s, STOP_SPEED, 300, 60), "Ride")
    lines = [x.plain for x in cli.render_timeline(s, [("New", segments)], SATURDAY_MORNING, 60)]
    band = next(x for x in lines if x.startswith("New"))
    # 6 minutes of 12 hours is well under one column, but it still gets one
    # (two when it straddles a column boundary).
    assert 1 <= band.count(cli.PAUSE_CHAR) <= 2


def test_adjacent_rides_are_told_apart():
    s = make_streams(("ride", 7200))
    segments = [Segment("WORK", 0, 3600), Segment("WORK", 3600, 7200)]
    band = cli.render_timeline(s, [("Now", segments)], SATURDAY_MORNING, 60)[1].plain
    assert cli.RIDE_CHARS[0] in band and cli.RIDE_CHARS[1] in band


def test_tiny_ride_still_gets_a_column():
    s = make_streams(("ride", 7200))
    segments = [Segment("WORK", 0, 3590), Segment("WORK", 3590, 3600), Segment("WORK", 3600, 7200)]
    band = cli.render_timeline(s, [("Now", segments)], SATURDAY_MORNING, 60)[1].plain
    assert cli.RIDE_CHARS[1] in band


def test_tiny_warmup_is_not_swallowed_by_the_ride_after_it():
    s = make_streams(("ride", 7200))
    segments = [Segment("WORK", 0, 60, "Warmup"), Segment("WORK", 60, 7200)]
    band = cli.render_timeline(s, [("New", segments)], SATURDAY_MORNING, 60)[1].plain
    assert band.split("│")[1].startswith(cli.RIDE_CHARS[0] + cli.RIDE_CHARS[1])


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
    segments = cli.build_segments(s, cli.find_pauses(s, STOP_SPEED, 300, 60), "Ride")
    out = text_of(cli.render_table(s, segments, SATURDAY_MORNING, STOP_SPEED, "New"))
    assert "Ride 1" in out
    assert "28.8" in out  # 8 m/s
    assert "150" in out
    assert "4.8 km" in out
    pause_row = next(x for x in out.splitlines() if "RECOVERY" in x)
    assert "06:40" in pause_row
    assert "—" in pause_row


def test_table_shows_the_weekday_only_for_multi_day_activities():
    s = make_streams(("ride", 600))
    segments = [Segment("WORK", 0, 600, "Ride 1")]
    assert "Sat" not in text_of(cli.render_table(s, segments, SATURDAY_MORNING, STOP_SPEED, "New"))
    late = datetime(2026, 8, 29, 23, 55)
    assert "Sat 23:55" in text_of(cli.render_table(s, segments, late, STOP_SPEED, "New"))


def test_summary_counts_rides_and_pauses():
    s = make_streams(("ride", 600), ("stop", 400), ("ride", 600))
    segments = cli.build_segments(s, cli.find_pauses(s, STOP_SPEED, 300, 60), "Ride")
    assert cli.render_summary(s, segments) == "  2 rides · 20 min · 9.6 km   |   1 pause · 6 min"
