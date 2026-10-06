import pytest

from intervals_icu_pause_split.units import Edge, parse_activity_id, parse_duration, parse_edge, parse_edges


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("5", 300), ("5m", 300), ("5min", 300), ("90s", 90), ("1.5h", 5400), (" 2 m ", 120)],
)
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds


def test_parse_duration_rejects_nonsense():
    with pytest.raises(ValueError, match="invalid duration 'five'"):
        parse_duration("five")


@pytest.mark.parametrize(
    ("text", "edge"),
    [
        ("3km", Edge(3000, by_distance=True)),
        ("2.5 km", Edge(2500, by_distance=True)),
        ("10m", Edge(600)),
        ("10", Edge(600)),
        ("90s", Edge(90)),
    ],
)
def test_parse_edge(text, edge):
    assert parse_edge(text) == edge


def test_parse_edge_rejects_other_units():
    with pytest.raises(ValueError, match="duration .* or a distance"):
        parse_edge("3mi")


def test_parse_edges():
    assert parse_edges("5km") == (Edge(5000, by_distance=True), Edge(5000, by_distance=True))
    assert parse_edges("3km,10m") == (Edge(3000, by_distance=True), Edge(600))
    with pytest.raises(ValueError, match="one length for both ends or two"):
        parse_edges("1m,2m,3m")


@pytest.mark.parametrize(
    "text",
    [
        "i87942121",
        "https://intervals.icu/activities/i87942121",
        "https://intervals.icu/activities/i87942121/",
        "https://intervals.icu/activities/i87942121?w=2025-05-12",
    ],
)
def test_parse_activity_id(text):
    assert parse_activity_id(text) == "i87942121"
