"""The library API a service builds on: plan(), to_dict(), apply(), plan_restore()."""

import json

import pytest
from helpers import FakeIntervals, make_streams

from intervals_icu_pause_split import DataError, Edge, Options, apply, plan, plan_restore

STREAMS = make_streams(("ride", 600), ("stop", 400), ("ride", 600))
ONE_BIG_INTERVAL = [{"id": 7, "start_index": 0, "end_index": 1600, "type": "WORK", "label": None}]


def test_plan_finds_the_legs_without_writing():
    site = FakeIntervals(STREAMS, ONE_BIG_INTERVAL)
    p = plan(site.client(), "https://intervals.icu/activities/i1")
    assert p.activity_id == "i1"
    assert [(x.type, x.start, x.end, x.label) for x in p.new] == [
        ("WORK", 0, 600, "Leg 1"),
        ("RECOVERY", 600, 1000, ""),
        ("WORK", 1000, 1600, "Leg 2"),
    ]
    assert [(x.start, x.end) for x in p.current] == [(0, 1600)]
    assert p.has_changes
    assert p.previous == site.intervals
    assert site.puts == []


def test_options_are_applied():
    site = FakeIntervals(STREAMS)
    p = plan(site.client(), "i1", Options(min_pause=600, label="Etappe"))
    assert [x.label for x in p.new] == ["Etappe 1"]


def test_options_parse_takes_command_line_strings():
    o = Options.parse(min_pause="10m", merge="90s", stop_speed="1.5", edges="3km,10m", label="Fahrt")
    assert o == Options(
        min_pause=600,
        merge=90,
        stop_speed=1.5,
        warmup=Edge(3000, by_distance=True),
        cooldown=Edge(600),
        label="Fahrt",
    )
    assert Options.parse() == Options()
    assert Options.parse(stop_speed="").stop_speed is None
    with pytest.raises(ValueError, match="invalid edges"):
        Options.parse(edges="1m,2m,3m")


def test_stop_speed_comes_from_the_sport_unless_given():
    assert plan(FakeIntervals(STREAMS, sport="Hike").client(), "i1").stop_speed == 1.0
    assert plan(FakeIntervals(STREAMS, sport="Ride").client(), "i1").stop_speed == 3.0
    assert plan(FakeIntervals(STREAMS, sport="Hike").client(), "i1", Options(stop_speed=2)).stop_speed == 2


def test_distance_edges_need_a_distance_stream():
    streams = make_streams(("ride", 600))
    streams.distance = None
    site = FakeIntervals(streams)
    with pytest.raises(DataError, match="no distance stream"):
        plan(site.client(), "i1", Options.parse(edges="1km"))


def test_to_dict_is_json_ready_and_complete():
    p = plan(FakeIntervals(STREAMS, ONE_BIG_INTERVAL).client(), "i1", Options.parse(edges="2m"))
    data = json.loads(json.dumps(p.to_dict(speed_points=16)))

    assert data["activity"] == {
        "id": "i1",
        "name": "Saturday [gravel]",
        "type": "GravelRide",
        "start": "2026-08-29T06:30:00",
        "distance_m": 9600,
        "elapsed_s": 1600,
    }
    assert data["options"]["warmup"] == {"amount": 120.0, "by_distance": False}
    assert data["stop_speed_kmh"] == 3.0
    assert data["has_changes"] is True
    assert len(data["current"]) == 1
    assert [x["label"] for x in data["new"]] == ["Warmup", "Leg 1", None, "Leg 2", "Cooldown"]

    warmup, leg, pause = data["new"][:3]
    assert warmup == {
        "type": "WORK",
        "label": "Warmup",
        "start_index": 0,
        "end_index": 120,
        "start_s": 0,
        "end_s": 120,
        "start": "2026-08-29T06:30:00",
        "elapsed_s": 120,
        "moving_s": 120,
        "distance_m": 960.0,
        "avg_kmh": 28.8,
        "avg_watts": 150,
    }
    assert leg["start"] == "2026-08-29T06:32:00"
    assert pause["type"] == "RECOVERY"
    assert pause["avg_kmh"] is None and pause["avg_watts"] is None
    assert pause["elapsed_s"] == 400

    assert data["summary"] == {
        "legs": 4,
        "legs_elapsed": 1200,
        "legs_distance": 9592.0,
        "pauses": 1,
        "pauses_elapsed": 400,
    }
    assert data["speed"]["slice_s"] == 100
    assert len(data["speed"]["kmh"]) == 16
    assert data["speed"]["kmh"][0] == 28.8
    assert data["speed"]["kmh"][7] == 0.0


def test_apply_writes_the_legs_and_returns_what_was_there():
    site = FakeIntervals(STREAMS, ONE_BIG_INTERVAL)
    client = site.client()
    p = plan(client, "i1")
    result = apply(client, p)
    assert site.puts == [
        (
            "/activity/i1/intervals",
            [
                {"start_index": 0, "end_index": 600, "type": "WORK", "label": "Leg 1"},
                {"start_index": 1000, "end_index": 1600, "type": "WORK", "label": "Leg 2"},
            ],
            {"all": "true"},
        )
    ]
    assert result.previous == {"id": "i1", "icu_intervals": ONE_BIG_INTERVAL}
    assert len(result.intervals) == 2


def test_restore_round_trips_through_result_previous():
    site = FakeIntervals(STREAMS, ONE_BIG_INTERVAL)
    client = site.client()
    result = apply(client, plan(client, "i1"))
    site.intervals = {"id": "i1", "icu_intervals": result.intervals}

    undo = plan_restore(client, "i1", result.previous)
    assert undo.options is None
    assert [(x.start, x.end) for x in undo.new] == [(0, 1600)]
    apply(client, undo)
    assert site.puts[-1][1] == [{"start_index": 0, "end_index": 1600, "type": "WORK", "label": None}]


def test_restore_refuses_a_backup_of_another_activity():
    site = FakeIntervals(STREAMS)
    with pytest.raises(DataError, match="belongs to i2, not i1"):
        plan_restore(site.client(), "i1", {"id": "i2", "icu_intervals": []})
