"""Exercise first-run, local file import, persistence and portable song copies."""
import io
import json
import time
import wave
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient

from karaoke import api, importer, paths


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SONGS", tmp_path / "songs")
    monkeypatch.setattr(paths, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(paths, "DB", tmp_path / "data" / "karaoke.db")
    monkeypatch.setattr(importer, "_job", None)
    return TestClient(api.app)


def recording(seconds=2):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
        t = np.arange(seconds * 22050) / 22050
        out.writeframes((12000 * np.sin(2 * np.pi * 440 * t)).astype("<i2").tobytes())
    return buffer.getvalue()


def wait_for_import(studio):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        job = studio.get("/api/import").json()
        if job["state"] != "running":
            return job
        time.sleep(.05)
    pytest.fail("The local import did not finish")


@pytest.mark.parametrize("language,lyrics", [("he", "דו רה\nמי פה"), ("es", "Una voz\nOtra vez")])
def test_local_file_to_editable_practice_song(studio, language, lyrics):
    up = studio.post("/api/import/audio?name=My%20recording.wav", content=recording())
    assert up.status_code == 200
    response = studio.post("/api/import", json={"upload": up.json()["upload"], "mode": "manual", "title": "Practice",
                           "artist": "A singer", "lyrics": lyrics, "language": language})
    assert response.status_code == 202
    job = wait_for_import(studio)
    assert job["state"] == "done", job["error"]
    assert [s["state"] for s in job["steps"]] == ["done", "done", "done"]
    song = studio.get("/api/songs/practice").json()
    assert song["song"]["availableTracks"] == ["original"]
    assert song["song"]["artist"] == "A singer" and song["song"]["language"] == language
    assert song["lines"][0]["words"][0]["flags"] == ["low-confidence"]
    assert studio.get("/api/songs/practice/audio/original").content.startswith(b"RIFF")
    assert studio.get("/api/songs/practice/audio/vocals").status_code == 404
    assert studio.get("/api/songs/practice/peaks?track=original").json()["peaks"]
    song["lines"][0]["english"] = "My edited line"
    assert studio.put("/api/songs/practice", json=song).status_code == 200
    assert TestClient(api.app).get("/api/songs/practice").json() == song
    assert len(studio.get("/api/songs").json()) == 1


def test_import_failure_keeps_recording_and_library_consistent(studio):
    up = studio.post("/api/import/audio?name=short.wav", content=recording(1)).json()["upload"]
    studio.post("/api/import", json={"upload": up, "mode": "manual", "lyrics": "רה " * 40})
    assert wait_for_import(studio)["state"] == "failed"
    assert studio.get(f"/api/import/audio/{up}").status_code == 200
    assert studio.get("/api/songs").json() == []


def test_sample_round_trip(studio):
    slug = studio.post("/api/desktop/sample").json()["id"]
    assert studio.post("/api/desktop/sample").json()["id"] == slug
    song = studio.get(f"/api/songs/{slug}").json()
    assert song["drills"][0]["steps"][1]["yourTurn"]
    assert not any(w["flags"] for line in song["lines"] for w in line["words"])
    audio = studio.get(f"/api/songs/{slug}/audio/original").content
    copied = studio.get(f"/api/desktop/backup/{slug}")
    assert copied.status_code == 200 and "attachment" in copied.headers["content-disposition"]
    restored = studio.post("/api/desktop/restore", content=copied.content)
    assert restored.status_code == 201
    new_id = restored.json()["id"]
    assert new_id != slug
    assert studio.get(f"/api/songs/{new_id}/audio/original").content == audio
    assert studio.get(f"/api/songs/{new_id}").json()["drills"] == song["drills"]
    assert len(studio.get("/api/songs").json()) == 2


def test_legacy_zipped_folder_and_incomplete_bundle(studio):
    from test_api import SONG
    doc = json.loads(json.dumps(SONG))
    doc["schema"] = 1
    del doc["song"]["language"]
    for word in doc["lines"][0]["words"]:
        word.update(pointed=word["plain"], syllables=[])
    data = recording()
    def bundle(tracks):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("old song/song.json", json.dumps(doc))
            for track in tracks:
                archive.writestr(f"old song/audio/{track}.wav", data)
        return buf.getvalue()
    assert studio.post("/api/desktop/restore", content=bundle(["original"])).status_code == 422
    assert studio.get("/api/songs").json() == []
    assert studio.post("/api/desktop/restore", content=bundle(["original", "vocals", "instrumental"])).status_code == 201
    saved = studio.get("/api/songs/demo").json()
    assert saved["schema"] == 2 and saved["song"]["language"] == "he"
    assert studio.get("/api/songs/demo/audio/instrumental").content == data
