from helpers import make_streams

from intervals_icu_pause_split import cli
from intervals_icu_pause_split.cli import Segment, Streams

STOP_SPEED = 3 / 3.6


def pauses(s, min_pause=300, merge=60, stop_speed=STOP_SPEED):
    return cli.find_pauses(s, stop_speed, min_pause, merge)


def test_auto_pause_gap_is_a_pause():
    s = make_streams(("ride", 600), ("gap", 600), ("ride", 600))
    # The sample before the jump owns the missing time.
    assert pauses(s) == [(599, 600)]


def test_standstill_while_recording_is_a_pause():
    s = make_streams(("ride", 600), ("stop", 400), ("ride", 600))
    assert pauses(s) == [(600, 1000)]


def test_short_stop_is_not_a_pause():
    s = make_streams(("ride", 600), ("stop", 120), ("ride", 600))
    assert pauses(s) == []
    assert pauses(s, min_pause=60) == [(600, 720)]


def test_stops_close_together_merge_into_one_pause():
    s = make_streams(("ride", 600), ("stop", 200), ("ride", 30), ("stop", 200), ("ride", 600))
    assert pauses(s) == [(600, 1030)]


def test_stops_far_apart_are_judged_on_their_own():
    s = make_streams(("ride", 600), ("stop", 200), ("ride", 120), ("stop", 200), ("ride", 600))
    assert pauses(s) == []
    assert pauses(s, merge=180) == [(600, 1120)]


def test_riding_between_merged_stops_does_not_count_as_standstill():
    # Four 70 s stops with 30 s of rolling between them: 280 s standing in a 370 s span.
    stop_and_go = [("stop", 70), ("ride", 30)] * 3 + [("stop", 70)]
    s = make_streams(("ride", 600), *stop_and_go, ("ride", 600))
    assert pauses(s) == []
    assert pauses(s, min_pause=280) == [(600, 970)]


def test_stop_speed_decides_what_counts_as_standing():
    s = make_streams(("ride", 1600))
    s.speed[600:1000] = [1.0] * 400  # 3.6 km/h, pushing the bike
    assert pauses(s) == []
    assert pauses(s, stop_speed=5 / 3.6) == [(600, 1000)]


def test_without_speed_only_recording_gaps_count():
    s = make_streams(("ride", 600), ("stop", 400), ("gap", 600), ("ride", 600))
    s.speed = None
    assert pauses(s) == [(999, 1000)]


def test_missing_speed_samples_are_not_standstill():
    s = make_streams(("ride", 1600))
    s.speed[600:1000] = [None] * 400
    assert pauses(s) == []


def test_pauses_at_the_start_and_the_end():
    s = make_streams(("stop", 400), ("ride", 600), ("stop", 400))
    segments = cli.build_segments(s, pauses(s), "Ride")
    assert [(x.type, x.start, x.end, x.label) for x in segments] == [
        ("RECOVERY", 0, 400, ""),
        ("WORK", 400, 1000, "Ride 1"),
        ("RECOVERY", 1000, 1400, ""),
    ]


def test_segments_cover_the_activity_without_overlap():
    s = make_streams(("ride", 600), ("gap", 600), ("ride", 300), ("stop", 400), ("ride", 600))
    segments = cli.build_segments(s, pauses(s), "Fahrt")
    assert segments[0].start == 0
    assert segments[-1].end == len(s)
    assert all(a.end == b.start for a, b in zip(segments, segments[1:]))
    assert [x.label for x in segments if not x.is_pause] == ["Fahrt 1", "Fahrt 2", "Fahrt 3"]


def test_edges_split_off_warmup_and_cooldown():
    s = make_streams(("ride", 1800), ("stop", 400), ("ride", 1800))
    segments = cli.build_segments(s, pauses(s), "Ride", warmup=600, cooldown=300)
    assert [(x.type, x.start, x.end, x.label) for x in segments] == [
        ("WORK", 0, 600, "Warmup"),
        ("WORK", 600, 1800, "Ride 1"),
        ("RECOVERY", 1800, 2200, ""),
        ("WORK", 2200, 3700, "Ride 2"),
        ("WORK", 3700, 4000, "Cooldown"),
    ]


def test_edges_count_elapsed_time_across_an_auto_pause_gap():
    # A short traffic-light gap inside the warmup still counts towards its 10 minutes.
    s = make_streams(("ride", 300), ("gap", 120), ("ride", 1800))
    [warmup, ride] = cli.build_segments(s, pauses(s), "Ride", warmup=600)
    assert (warmup.label, warmup.start, warmup.end) == ("Warmup", 0, 480)
    assert (ride.label, ride.start) == ("Ride 1", 480)


def test_edges_on_a_single_ride():
    s = make_streams(("ride", 3600))
    segments = cli.build_segments(s, [], "Ride", warmup=600, cooldown=600)
    assert [(x.start, x.end, x.label) for x in segments] == [
        (0, 600, "Warmup"),
        (600, 3000, "Ride 1"),
        (3000, 3600, "Cooldown"),
    ]


def test_ride_shorter_than_the_edge_becomes_the_edge_as_a_whole():
    s = make_streams(("ride", 300), ("stop", 400), ("ride", 1800), ("stop", 400), ("ride", 200))
    segments = cli.build_segments(s, pauses(s), "Ride", warmup=600, cooldown=600)
    assert [x.label for x in segments] == ["Warmup", "", "Ride 1", "", "Cooldown"]


def test_one_short_ride_is_the_cooldown_and_gets_no_warmup():
    s = make_streams(("ride", 300))
    segments = cli.build_segments(s, [], "Ride", warmup=600, cooldown=600)
    assert [(x.start, x.end, x.label) for x in segments] == [(0, 300, "Cooldown")]


def test_edges_without_any_riding_change_nothing():
    s = make_streams(("stop", 600))
    assert cli.split_edges(s, [Segment("RECOVERY", 0, 600)], 300, 300) == [Segment("RECOVERY", 0, 600)]


def test_no_pauses_means_one_ride():
    s = make_streams(("ride", 600))
    assert [(x.type, x.start, x.end) for x in cli.build_segments(s, [], "Ride")] == [("WORK", 0, 600)]


def test_payload_sends_only_the_rides():
    segments = [Segment("WORK", 0, 10, "Ride 1"), Segment("RECOVERY", 10, 20), Segment("WORK", 20, 30)]
    assert cli.payload(segments) == [
        {"start_index": 0, "end_index": 10, "type": "WORK", "label": "Ride 1"},
        {"start_index": 20, "end_index": 30, "type": "WORK", "label": None},
    ]


def test_segments_from_intervals_fills_in_missing_type_and_label():
    segments = cli.segments_from_intervals(
        [
            {"start_index": 0, "end_index": 5, "type": None, "label": None},
            {"start_index": 5, "end_index": 9, "type": "RECOVERY"},
        ]
    )
    assert segments == [Segment("WORK", 0, 5, ""), Segment("RECOVERY", 5, 9, "")]


def test_distance_at_skips_missing_values():
    s = Streams(time=[0, 1, 2, 3], speed=None, distance=[None, 5.0, None, None], watts=None)
    assert s.distance_at(0) == 0.0
    assert s.distance_at(3) == 5.0
    assert s.distance_at(10) == 5.0
    s.distance = None
    assert s.distance_at(2) == 0.0
