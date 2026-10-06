import httpx
import pytest
from rich.console import Console

from intervals_icu_pause_split import Client, cli


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    """Keep the developer's own .env, shell and backups out of every test.

    resolve_api_key() calls load_dotenv(), which would happily pick up the real
    API key sitting next to the project and make the tests depend on the
    machine they run on. Backups go to a temporary state directory, and every
    test gets a fresh console so a --width from one test can't leak into the next.
    """
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **kw: None)
    monkeypatch.delenv("INTERVALS_ICU_API_KEY", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(cli, "console", Console(width=120, highlight=False))


@pytest.fixture
def make_client():
    """Build a Client whose requests are answered by `handler` instead of the network."""

    def factory(handler, api_key="testkey", **kw):
        return Client(api_key, transport=httpx.MockTransport(handler), **kw)

    return factory
