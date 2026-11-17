"""Other web pages open in the browser can't use the local server: requests must be addressed to 127.0.0.1 or
localhost (no DNS rebinding), and changes must come from the studio's own pages (no cross-site requests)."""
import json

import pytest
from fastapi.testclient import TestClient

from karaoke import api, paths
from test_api import SONG


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SONGS", tmp_path / "songs")
    monkeypatch.setattr(paths, "DB", tmp_path / "data" / "karaoke.db")
    folder = tmp_path / "songs" / "demo"
    folder.mkdir(parents=True)
    (folder / "song.json").write_text(json.dumps(SONG, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(api, "ALLOWED_HOSTS", {"127.0.0.1", "localhost"})  # the real list, without "testserver"
    return TestClient(api.app, base_url="http://127.0.0.1:8321")


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8321", "127.0.0.1.evil.example", "", "0.0.0.0:8321"])
def test_a_request_to_another_host_name_is_refused(client, host):
    r = client.get("/api/songs", headers={"host": host})
    assert r.status_code == 400 and "demo" not in r.text


@pytest.mark.parametrize("host", ["127.0.0.1:8321", "localhost:8321", "localhost:5180", "LOCALHOST"])
def test_this_computer_is_allowed(client, host):
    assert client.get("/api/songs", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("origin", ["https://evil.example", "http://127.0.0.1.evil.example", "null"])
def test_changes_from_another_site_are_refused(client, origin):
    r = client.delete("/api/songs/demo", headers={"origin": origin})
    assert r.status_code == 403
    assert (paths.SONGS / "demo" / "song.json").is_file()  # still there
    assert client.post("/api/import/check", json={"lyrics": "שלום"}, headers={"origin": origin}).status_code == 403


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8321", "http://localhost:5180", None])
def test_changes_from_the_studio_or_without_an_origin_are_allowed(client, origin):
    headers = {"origin": origin} if origin else {}  # no Origin: the CLI or a script, not a web page
    assert client.post("/api/import/check", json={"lyrics": "שלום"}, headers=headers).status_code == 200


def test_reading_from_another_site_is_left_to_the_browser(client):
    # a cross-site GET can't read the answer (no CORS headers are sent), so it isn't blocked here
    r = client.get("/api/songs", headers={"origin": "https://evil.example"})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers
