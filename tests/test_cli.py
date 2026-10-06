"""End-to-end through main(), against a fake intervals.icu that records every write."""

import argparse
import json

import httpx
import pytest
from helpers import FakeIntervals, make_streams

from intervals_icu_pause_split import Client, cli

# Two legs with a 400 s standstill between them: Leg 1 is 0-600, Leg 2 is 1000-1600.
STREAMS = make_streams(("ride", 600), ("stop", 400), ("ride", 600))
LEGS = [
    {"start_index": 0, "end_index": 600, "type": "WORK", "label": "Leg 1"},
    {"start_index": 1000, "end_index": 1600, "type": "WORK", "label": "Leg 2"},
]
ONE_BIG_INTERVAL = [{"id": 7, "start_index": 0, "end_index": 1600, "type": "WORK", "label": None}]


def fake(intervals=None, **kw) -> FakeIntervals:
    kw.setdefault("streams", STREAMS)
    return FakeIntervals(intervals=intervals, **kw)


@pytest.fixture
def run(monkeypatch):
    """Run main() with given argv against a FakeIntervals, return stdout."""

    def go(site, *argv, capsys, tty=False, confirm=None, key="k"):
        monkeypatch.setattr(cli, "Client", site.client if isinstance(site, FakeIntervals) else site)
        monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: tty, raising=False)
        if confirm is not None:
            monkeypatch.setattr(cli.Confirm, "ask", lambda *a, **kw: confirm)
        key_args = ["--api-key", key] if key else []
        monkeypatch.setattr(cli.sys, "argv", ["intervals-icu-pause-split", *key_args, *argv])
        cli.main()
        return capsys.readouterr().out

    return go


def backups(tmp_path):
    return sorted((tmp_path / "state" / "intervals-icu-pause-split" / "backups").glob("*.json"))


def test_dry_run_previews_but_never_writes(run, capsys, tmp_path):
    site = fake(ONE_BIG_INTERVAL)
    out = run(site, "i1", "--dry-run", capsys=capsys)
    assert "Saturday [gravel]" in out
    assert "Leg 2" in out
    assert "2 legs · 20 min · 9.6 km   |   1 pause · 6 min" in out
    assert "nothing written" in out
    assert site.puts == []
    assert backups(tmp_path) == []


def test_yes_writes_only_the_legs_and_backs_up_first(run, capsys, tmp_path):
    site = fake(ONE_BIG_INTERVAL)
    out = run(site, "https://intervals.icu/activities/i1", "--yes", capsys=capsys)
    assert site.puts == [("/activity/i1/intervals", LEGS, {"all": "true"})]
    [backup] = backups(tmp_path)
    assert json.loads(backup.read_text()) == site.intervals
    assert "2 intervals set" in out
    assert "--restore" in out


def test_confirmation_yes_writes(run, capsys):
    site = fake(ONE_BIG_INTERVAL)
    run(site, "i1", capsys=capsys, tty=True, confirm=True)
    assert len(site.puts) == 1


def test_confirmation_no_writes_nothing(run, capsys, tmp_path):
    site = fake(ONE_BIG_INTERVAL)
    out = run(site, "i1", capsys=capsys, tty=True, confirm=False)
    assert "Cancelled" in out
    assert site.puts == []
    assert backups(tmp_path) == []


@pytest.mark.parametrize("error", [KeyboardInterrupt, EOFError])
def test_interrupt_at_the_prompt_writes_nothing(run, capsys, monkeypatch, tmp_path, error):
    def interrupt(*a, **kw):
        raise error

    monkeypatch.setattr(cli.Confirm, "ask", interrupt)
    site = fake(ONE_BIG_INTERVAL)
    with pytest.raises(SystemExit) as exit:
        run(site, "i1", capsys=capsys, tty=True)
    assert exit.value.code == 130
    assert "Interrupted, nothing changed" in capsys.readouterr().out
    assert site.puts == []
    assert backups(tmp_path) == []


def test_interrupt_while_fetching_writes_nothing(run, capsys):
    site = fake(ONE_BIG_INTERVAL)
    site.interrupt = "GET"
    with pytest.raises(SystemExit) as exit:
        run(site, "i1", "--yes", capsys=capsys)
    assert exit.value.code == 130
    assert "Interrupted, nothing changed" in capsys.readouterr().out


def test_interrupt_while_writing_points_at_the_backup(run, capsys, tmp_path):
    site = fake(ONE_BIG_INTERVAL)
    site.interrupt = "PUT"
    with pytest.raises(SystemExit) as exit:
        run(site, "i1", "--yes", capsys=capsys)
    out = capsys.readouterr().out
    assert exit.value.code == 130
    assert "may or may not have changed" in out
    assert "nothing changed" not in out
    [backup] = backups(tmp_path)
    assert str(backup) in out.replace("\n", "")


def test_without_a_terminal_it_needs_yes(run, capsys):
    site = fake(ONE_BIG_INTERVAL)
    out = run(site, "i1", capsys=capsys)
    assert "pass --yes" in out
    assert site.puts == []


def test_nothing_to_do_when_the_intervals_already_match(run, capsys):
    current = [*LEGS[:1], {"start_index": 600, "end_index": 1000, "type": "RECOVERY", "label": None}, *LEGS[1:]]
    site = fake(current)
    out = run(site, "i1", "--yes", capsys=capsys)
    assert "already has these intervals" in out
    assert site.puts == []


def test_label_and_thresholds_are_passed_through(run, capsys):
    site = fake()
    out = run(site, "i1", "--yes", "--label", "Fahrt", "--min-pause", "10m", "--width", "70", capsys=capsys)
    # A 400 s stop is below 10 minutes, so the whole activity is one leg.
    written = [{"start_index": 0, "end_index": 1600, "type": "WORK", "label": "Fahrt 1"}]
    assert site.puts == [("/activity/i1/intervals", written, {"all": "true"})]
    assert "no intervals" in out


def test_edges_write_warmup_and_cooldown(run, capsys):
    site = fake()
    out = run(site, "i1", "--yes", "--edges", "2m,3m", capsys=capsys)
    assert [(x["start_index"], x["end_index"], x["label"]) for x in site.puts[0][1]] == [
        (0, 120, "Warmup"),
        (120, 600, "Leg 1"),
        (1000, 1420, "Leg 2"),
        (1420, 1600, "Cooldown"),
    ]
    assert "Warmup: first 2 min · Cooldown: last 3 min" in out


def test_edges_in_km(run, capsys):
    site = fake()
    out = run(site, "i1", "--yes", "--edges", "1km", capsys=capsys)
    # 8 m/s: the first kilometre ends at sample 125, the last one starts at 1474.
    assert [(x["start_index"], x["end_index"], x["label"]) for x in site.puts[0][1]] == [
        (0, 125, "Warmup"),
        (125, 600, "Leg 1"),
        (1000, 1474, "Leg 2"),
        (1474, 1600, "Cooldown"),
    ]
    assert "Warmup: first 1 km · Cooldown: last 1 km" in out


def test_edges_in_km_need_a_distance_stream(run, capsys):
    streams = make_streams(("ride", 600), ("stop", 400), ("ride", 600))
    streams.distance = None
    with pytest.raises(SystemExit):
        run(fake(streams=streams), "i1", "--edges", "1km", capsys=capsys)
    assert "no distance stream" in capsys.readouterr().out


def test_edges_take_at_most_two_lengths(run, capsys):
    with pytest.raises(SystemExit):
        run(fake(), "i1", "--edges", "1m,2m,3m", capsys=capsys)
    assert "give one length for both ends or two" in capsys.readouterr().err


def test_bad_duration_is_explained(run, capsys):
    with pytest.raises(SystemExit):
        run(fake(), "i1", "--min-pause", "five", capsys=capsys)
    assert "invalid duration 'five'" in capsys.readouterr().err


def test_edges_before_the_activity_url_leave_the_url_alone(run, capsys):
    site = fake()
    run(site, "--yes", "--edges", "1km", "https://intervals.icu/activities/i1", capsys=capsys)
    assert site.puts[0][0] == "/activity/i1/intervals"


def slow_climb():
    """400 s at 2 km/h between two faster stretches: a steep climb on foot, a stop on a bike."""
    s = make_streams(("ride", 1600))
    s.speed[600:1000] = [2 / 3.6] * 400
    return s


def test_stop_speed_defaults_to_standing_still_on_a_bike(run, capsys):
    site = fake(streams=slow_climb())
    out = run(site, "i1", "--yes", capsys=capsys)
    assert len(site.puts[0][1]) == 2
    assert "below 3 km/h" in out
    assert "GravelRide ·" in out


def test_stop_speed_defaults_to_walking_pace_on_foot(run, capsys):
    site = fake(streams=slow_climb(), sport="Hike")
    out = run(site, "i1", "--yes", capsys=capsys)
    assert len(site.puts[0][1]) == 1
    assert "below 1 km/h" in out
    assert "Hike ·" in out


def test_stop_speed_flag_overrides_the_sport_default(run, capsys):
    site = fake(streams=slow_climb(), sport="Hike")
    run(site, "i1", "--yes", "--stop-speed", "3", capsys=capsys)
    assert len(site.puts[0][1]) == 2


def test_restore_puts_back_the_intervals_from_a_backup(run, capsys, tmp_path):
    path = tmp_path / "backup.json"
    path.write_text(json.dumps({"id": "i1", "icu_intervals": ONE_BIG_INTERVAL}))
    site = fake(LEGS)
    out = run(site, "i1", "--restore", str(path), "--yes", capsys=capsys)
    written = [{"start_index": 0, "end_index": 1600, "type": "WORK", "label": None}]
    assert site.puts == [("/activity/i1/intervals", written, {"all": "true"})]
    assert "Restoring the intervals from" in out


def test_restore_refuses_a_backup_of_another_activity(run, capsys, tmp_path):
    path = tmp_path / "backup.json"
    path.write_text(json.dumps({"id": "i2", "icu_intervals": ONE_BIG_INTERVAL}))
    with pytest.raises(SystemExit):
        run(fake(), "i1", "--restore", str(path), capsys=capsys)
    assert "belongs to i2" in capsys.readouterr().out


def test_restore_reports_an_unreadable_backup(run, capsys, tmp_path):
    with pytest.raises(SystemExit):
        run(fake(), "i1", "--restore", str(tmp_path / "missing.json"), capsys=capsys)
    assert "Cannot read backup" in capsys.readouterr().out


def test_unknown_activity_is_explained(run, capsys):
    with pytest.raises(SystemExit) as exit:
        run(fake(), "i2", capsys=capsys)
    out = capsys.readouterr().out
    assert exit.value.code == 1
    assert "Not found: /activity/i2" in out
    assert "Check the activity id" in out


def test_rejected_key_is_explained(run, capsys):
    def client(api_key):
        return Client(api_key, transport=httpx.MockTransport(lambda request: httpx.Response(401)))

    with pytest.raises(SystemExit):
        run(client, "i1", capsys=capsys)
    out = capsys.readouterr().out
    assert "rejected the credentials" in out
    assert "Check the API key" in out


def test_missing_api_key_is_explained(run, capsys):
    with pytest.raises(SystemExit):
        run(fake(), "i1", capsys=capsys, key=None)
    assert "No API key" in capsys.readouterr().out


def test_api_key_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("INTERVALS_ICU_API_KEY", "from-env")
    assert cli.resolve_api_key(argparse.Namespace(api_key=None)) == "from-env"
    assert cli.resolve_api_key(argparse.Namespace(api_key="flag")) == "flag"
