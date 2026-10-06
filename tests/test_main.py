"""End-to-end through main(), with the API faked and the write recorded."""

import argparse
import json

import pytest
from helpers import as_json, make_streams

from intervals_icu_pause_split import cli

# Two rides with a 400 s standstill between them: Ride 1 is 0-600, Ride 2 is 1000-1600.
STREAMS = make_streams(("ride", 600), ("stop", 400), ("ride", 600))
RIDES = [
    {"start_index": 0, "end_index": 600, "type": "WORK", "label": "Ride 1"},
    {"start_index": 1000, "end_index": 1600, "type": "WORK", "label": "Ride 2"},
]
ONE_BIG_INTERVAL = [{"id": 7, "start_index": 0, "end_index": 1600, "type": "WORK", "label": None}]


class FakeApi:
    """Answers the three GETs main() makes and records any PUT."""

    def __init__(self, intervals=None, activity_id="i1"):
        self.intervals = {"id": activity_id, "icu_intervals": intervals or []}
        self.puts = []

    def get(self, path, **params):
        if path.endswith("/streams.json"):
            return as_json(STREAMS)
        if path.endswith("/intervals"):
            return self.intervals
        return {"id": "i1", "name": "Saturday [gravel]", "start_date_local": "2026-08-29T06:30:00", "distance": 9600}

    def put(self, path, body, **params):
        self.puts.append((path, body, params))
        return {"icu_intervals": body}


@pytest.fixture
def run(monkeypatch):
    """Run main() with given argv against a FakeApi, return stdout."""

    def go(api, *argv, capsys, tty=False, confirm=None, key="k"):
        monkeypatch.setattr(cli, "Api", lambda key: api)
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
    api = FakeApi(ONE_BIG_INTERVAL)
    out = run(api, "i1", "--dry-run", capsys=capsys)
    assert "Saturday [gravel]" in out
    assert "Ride 2" in out
    assert "2 rides · 20 min · 9.6 km   |   1 pause · 6 min" in out
    assert "nothing written" in out
    assert api.puts == []
    assert backups(tmp_path) == []


def test_yes_writes_only_the_rides_and_backs_up_first(run, capsys, tmp_path):
    api = FakeApi(ONE_BIG_INTERVAL)
    out = run(api, "https://intervals.icu/activities/i1", "--yes", capsys=capsys)
    assert api.puts == [("/activity/i1/intervals", RIDES, {"all": "true"})]
    [backup] = backups(tmp_path)
    assert json.loads(backup.read_text()) == api.intervals
    assert "2 intervals set" in out
    assert "--restore" in out


def test_confirmation_yes_writes(run, capsys):
    api = FakeApi(ONE_BIG_INTERVAL)
    run(api, "i1", capsys=capsys, tty=True, confirm=True)
    assert len(api.puts) == 1


def test_confirmation_no_writes_nothing(run, capsys, tmp_path):
    api = FakeApi(ONE_BIG_INTERVAL)
    out = run(api, "i1", capsys=capsys, tty=True, confirm=False)
    assert "Cancelled" in out
    assert api.puts == []
    assert backups(tmp_path) == []


@pytest.mark.parametrize("error", [KeyboardInterrupt, EOFError])
def test_interrupt_at_the_prompt_writes_nothing(run, capsys, monkeypatch, tmp_path, error):
    def interrupt(*a, **kw):
        raise error

    monkeypatch.setattr(cli.Confirm, "ask", interrupt)
    api = FakeApi(ONE_BIG_INTERVAL)
    with pytest.raises(SystemExit) as exit:
        run(api, "i1", capsys=capsys, tty=True)
    assert exit.value.code == 130
    assert "Interrupted, nothing changed" in capsys.readouterr().out
    assert api.puts == []
    assert backups(tmp_path) == []


def test_interrupt_while_fetching_writes_nothing(run, capsys, monkeypatch):
    api = FakeApi(ONE_BIG_INTERVAL)

    def interrupt(*a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(api, "get", interrupt)
    with pytest.raises(SystemExit) as exit:
        run(api, "i1", "--yes", capsys=capsys)
    assert exit.value.code == 130
    assert "Interrupted, nothing changed" in capsys.readouterr().out


def test_interrupt_while_writing_points_at_the_backup(run, capsys, monkeypatch, tmp_path):
    api = FakeApi(ONE_BIG_INTERVAL)

    def interrupt(*a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(api, "put", interrupt)
    with pytest.raises(SystemExit) as exit:
        run(api, "i1", "--yes", capsys=capsys)
    out = capsys.readouterr().out
    assert exit.value.code == 130
    assert "may or may not have changed" in out
    assert "nothing changed" not in out
    [backup] = backups(tmp_path)
    assert str(backup) in out.replace("\n", "")


def test_without_a_terminal_it_needs_yes(run, capsys):
    api = FakeApi(ONE_BIG_INTERVAL)
    out = run(api, "i1", capsys=capsys)
    assert "pass --yes" in out
    assert api.puts == []


def test_nothing_to_do_when_the_intervals_already_match(run, capsys):
    current = [*RIDES[:1], {"start_index": 600, "end_index": 1000, "type": "RECOVERY", "label": None}, *RIDES[1:]]
    api = FakeApi(current)
    out = run(api, "i1", "--yes", capsys=capsys)
    assert "already has these intervals" in out
    assert api.puts == []


def test_label_and_thresholds_are_passed_through(run, capsys):
    api = FakeApi()
    out = run(api, "i1", "--yes", "--label", "Fahrt", "--min-pause", "10m", "--width", "70", capsys=capsys)
    # A 400 s stop is below 10 minutes, so the whole activity is one ride.
    assert api.puts == [
        ("/activity/i1/intervals", [{"start_index": 0, "end_index": 1600, "type": "WORK", "label": "Fahrt 1"}], {"all": "true"})
    ]
    assert "no intervals" in out


def test_edges_write_warmup_and_cooldown(run, capsys):
    api = FakeApi()
    out = run(api, "i1", "--yes", "--edges", "2m", "3m", capsys=capsys)
    assert [(x["start_index"], x["end_index"], x["label"]) for x in api.puts[0][1]] == [
        (0, 120, "Warmup"),
        (120, 600, "Ride 1"),
        (1000, 1420, "Ride 2"),
        (1420, 1600, "Cooldown"),
    ]
    assert "Warmup: first 2 min of riding · Cooldown: last 3 min" in out


def test_edges_in_km(run, capsys):
    api = FakeApi()
    out = run(api, "i1", "--yes", "--edges", "1km", capsys=capsys)
    # 8 m/s: the first kilometre ends at sample 125, the last one starts at 1474.
    assert [(x["start_index"], x["end_index"], x["label"]) for x in api.puts[0][1]] == [
        (0, 125, "Warmup"),
        (125, 600, "Ride 1"),
        (1000, 1474, "Ride 2"),
        (1474, 1600, "Cooldown"),
    ]
    assert "Warmup: first 1 km of riding · Cooldown: last 1 km" in out


def test_edges_in_km_need_a_distance_stream(run, capsys, monkeypatch):
    monkeypatch.setattr(STREAMS, "distance", None)
    with pytest.raises(SystemExit):
        run(FakeApi(), "i1", "--edges", "1km", capsys=capsys)
    assert "no distance stream" in capsys.readouterr().out


def test_edges_take_at_most_two_lengths(run, capsys):
    with pytest.raises(SystemExit):
        run(FakeApi(), "i1", "--edges", "1m", "2m", "3m", capsys=capsys)
    assert "--edges takes one length" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("text", "edge"),
    [
        ("3km", cli.Edge(3000, by_distance=True)),
        ("2.5 km", cli.Edge(2500, by_distance=True)),
        ("10m", cli.Edge(600)),
        ("10", cli.Edge(600)),
        ("90s", cli.Edge(90)),
    ],
)
def test_parse_edge(text, edge):
    assert cli.parse_edge(text) == edge


def test_parse_edge_rejects_other_units():
    with pytest.raises(argparse.ArgumentTypeError, match="duration .* or a distance"):
        cli.parse_edge("3mi")


def test_restore_puts_back_the_rides_from_a_backup(run, capsys, tmp_path):
    path = tmp_path / "backup.json"
    path.write_text(json.dumps({"id": "i1", "icu_intervals": ONE_BIG_INTERVAL}))
    api = FakeApi(RIDES)
    run(api, "i1", "--restore", str(path), "--yes", capsys=capsys)
    assert api.puts == [
        ("/activity/i1/intervals", [{"start_index": 0, "end_index": 1600, "type": "WORK", "label": None}], {"all": "true"})
    ]


def test_restore_refuses_a_backup_of_another_activity(run, capsys, tmp_path):
    path = tmp_path / "backup.json"
    path.write_text(json.dumps({"id": "i2", "icu_intervals": ONE_BIG_INTERVAL}))
    with pytest.raises(SystemExit):
        run(FakeApi(), "i1", "--restore", str(path), capsys=capsys)
    assert "belongs to i2" in capsys.readouterr().out


def test_restore_reports_an_unreadable_backup(run, capsys, tmp_path):
    with pytest.raises(SystemExit):
        run(FakeApi(), "i1", "--restore", str(tmp_path / "missing.json"), capsys=capsys)
    assert "Cannot read backup" in capsys.readouterr().out


def test_missing_api_key_is_explained(run, capsys):
    with pytest.raises(SystemExit):
        run(FakeApi(), "i1", capsys=capsys, key=None)
    assert "No API key" in capsys.readouterr().out


def test_api_key_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("INTERVALS_ICU_API_KEY", "from-env")
    assert cli.resolve_api_key(argparse.Namespace(api_key=None)) == "from-env"
    assert cli.resolve_api_key(argparse.Namespace(api_key="flag")) == "flag"


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("5", 300), ("5m", 300), ("5min", 300), ("90s", 90), ("1.5h", 5400), (" 2 m ", 120)],
)
def test_parse_duration(text, seconds):
    assert cli.parse_duration(text) == seconds


def test_parse_duration_rejects_nonsense():
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_duration("five")


@pytest.mark.parametrize(
    "text",
    [
        "i181405932",
        "https://intervals.icu/activities/i181405932",
        "https://intervals.icu/activities/i181405932/",
        "https://intervals.icu/activities/i181405932?w=2026-08-24",
    ],
)
def test_parse_activity_id(text):
    assert cli.parse_activity_id(text) == "i181405932"
