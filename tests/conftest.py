"""Shared test setup."""
import pytest

from karaoke import api


@pytest.fixture(autouse=True)
def test_client_host(monkeypatch):
    """FastAPI's TestClient addresses the app as "testserver"; the real server only answers to 127.0.0.1 and
    localhost (api.only_this_computer). Allow the test name in tests only."""
    monkeypatch.setattr(api, "ALLOWED_HOSTS", api.ALLOWED_HOSTS | {"testserver"})
