import base64
import json

import httpx
import pytest

from intervals_icu_pause_split import AuthError, Client, DataError, IntervalsError, NotFoundError, __version__


def test_api_key_is_basic_auth_with_the_literal_username(make_client):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["agent"] = request.headers["user-agent"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    assert make_client(handler, api_key="secret").activity("i1") == {"ok": True}
    assert seen["auth"] == "Basic " + base64.b64encode(b"API_KEY:secret").decode()
    assert seen["agent"] == f"intervals-icu-pause-split/{__version__}"
    assert seen["url"] == "https://intervals.icu/api/v1/activity/i1"


def test_access_token_is_a_bearer_header():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={})

    with Client(access_token="tok", transport=httpx.MockTransport(handler)) as client:
        client.activity("i1")
    assert seen["auth"] == "Bearer tok"


@pytest.mark.parametrize("kw", [{}, {"api_key": "k", "access_token": "t"}])
def test_exactly_one_credential(kw):
    with pytest.raises(ValueError, match="either api_key or access_token"):
        Client(**kw)


def test_replace_intervals_puts_json_with_all(make_client):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"")

    assert make_client(handler).replace_intervals("i1", [{"start_index": 0}]) == {}
    assert seen == {
        "method": "PUT",
        "url": "https://intervals.icu/api/v1/activity/i1/intervals?all=true",
        "body": [{"start_index": 0}],
    }


@pytest.mark.parametrize(
    ("status", "error", "message"),
    [
        (401, AuthError, "rejected the credentials (HTTP 401)"),
        (403, AuthError, "rejected the credentials (HTTP 403)"),
        (404, NotFoundError, "Not found: /activity/i1"),
        (500, IntervalsError, "HTTP 500 on GET /activity/i1: nope"),
    ],
)
def test_errors_raise_instead_of_exiting(make_client, status, error, message):
    client = make_client(lambda request: httpx.Response(status, text="nope"))
    with pytest.raises(error, match=message.replace("(", r"\(").replace(")", r"\)")) as raised:
        client.activity("i1")
    assert raised.value.status_code == status


def test_network_errors_raise(make_client):
    def handler(request):
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(IntervalsError, match="Could not reach intervals.icu"):
        make_client(handler).activity("i1")


def test_streams_are_mapped_by_type(make_client):
    raw = [
        {"type": "time", "data": [0, 1]},
        {"type": "velocity_smooth", "data": [0.0, 2.0]},
        {"type": "distance", "data": [0.0, 2.0]},
    ]
    seen = {}

    def handler(request):
        seen["types"] = request.url.params["types"]
        return httpx.Response(200, json=raw)

    s = make_client(handler).streams("i1")
    assert (s.time, s.speed, s.distance, s.watts) == ([0, 1], [0.0, 2.0], [0.0, 2.0], None)
    assert seen["types"] == "time,velocity_smooth,distance,watts"


def test_activity_without_time_stream_is_refused(make_client):
    client = make_client(lambda request: httpx.Response(200, json=[{"type": "watts", "data": [1, 2]}]))
    with pytest.raises(DataError, match="no time stream"):
        client.streams("i1")
