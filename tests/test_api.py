import base64
import json

import httpx
import pytest

from intervals_icu_pause_split import __version__, cli


def test_requests_carry_auth_user_agent_and_params(make_api):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["agent"] = request.headers["user-agent"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    assert make_api(handler, key="secret").get("/activity/i1/streams.json", types="time") == {"ok": True}
    assert seen["auth"] == "Basic " + base64.b64encode(b"API_KEY:secret").decode()
    assert seen["agent"] == f"intervals-icu-pause-split/{__version__}"
    assert seen["url"] == "https://intervals.icu/api/v1/activity/i1/streams.json?types=time"


def test_put_sends_json_and_query(make_api):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"")

    assert make_api(handler).put("/activity/i1/intervals", [{"start_index": 0}], all="true") is None
    assert seen == {
        "method": "PUT",
        "url": "https://intervals.icu/api/v1/activity/i1/intervals?all=true",
        "body": [{"start_index": 0}],
    }


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "rejected the credentials"), (403, "rejected the credentials"), (404, "Not found"), (500, "HTTP 500")],
)
def test_errors_end_with_a_message(make_api, capsys, status, message):
    api = make_api(lambda request: httpx.Response(status, text="nope"))
    with pytest.raises(SystemExit):
        api.get("/activity/i1")
    assert message in capsys.readouterr().out


def test_network_errors_end_with_a_message(make_api, capsys):
    def handler(request):
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(SystemExit):
        make_api(handler).get("/activity/i1")
    assert "Could not reach intervals.icu" in capsys.readouterr().out


def test_activity_without_time_stream_is_refused(make_api, capsys):
    api = make_api(lambda request: httpx.Response(200, json=[{"type": "watts", "data": [1, 2]}]))
    with pytest.raises(SystemExit):
        cli.fetch_streams(api, "i1")
    assert "no time stream" in capsys.readouterr().out


def test_fetch_streams_maps_stream_types(make_api):
    raw = [
        {"type": "time", "data": [0, 1]},
        {"type": "velocity_smooth", "data": [0.0, 2.0]},
        {"type": "distance", "data": [0.0, 2.0]},
    ]
    s = cli.fetch_streams(make_api(lambda request: httpx.Response(200, json=raw)), "i1")
    assert (s.time, s.speed, s.distance, s.watts) == ([0, 1], [0.0, 2.0], [0.0, 2.0], None)
