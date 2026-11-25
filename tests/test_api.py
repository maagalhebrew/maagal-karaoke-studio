"""Editor API tests on a synthetic song in a temp folder (no real lyrics or recordings needed)."""
import copy
import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from karaoke import api, paths


def word(i, start, end, plain="שלום"):
    return {"id": f"L1W{i}", "plain": plain, "startMs": start, "endMs": end, "confidence": 0.9, "flags": []}


SONG = {
    "schema": 2,
    "song": {"id": "demo", "title": "Demo", "artist": "", "language": "he", "permissionId": None,
             "audio": {"original": "audio/original.wav", "vocals": "audio/vocals.wav",
                       "instrumental": "audio/instrumental.wav"}, "durationMs": 2000},
    "lines": [{"id": "L1", "english": "", "words": [word(1, 100, 500), word(2, 600, 1000)]}],
    "sections": [{"id": "S1", "kind": "verse", "label": "Verse 1", "fromLine": "L1", "toLine": "L1"}],
    "clips": [], "drills": [],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SONGS", tmp_path / "songs")
    monkeypatch.setattr(paths, "DB", tmp_path / "data" / "karaoke.db")
    folder = tmp_path / "songs" / "demo"
    (folder / "audio").mkdir(parents=True)
    (folder / "song.json").write_text(json.dumps(SONG, ensure_ascii=False), encoding="utf-8")
    for kind in ("original", "vocals", "instrumental"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                        str(folder / "audio" / f"{kind}.wav")], check=True)
    return TestClient(api.app)


def test_translate_ready_does_not_name_a_model(client, monkeypatch):
    monkeypatch.setattr(api.translate, "translation_ready", lambda: False)
    assert client.get("/api/translate/ready").json() == {"ready": False}
    assert client.get("/api/translate/models").status_code == 404


def test_desktop_song_loads_and_saves(client):
    """A song the desktop app saved (credit, pronunciation, original recording only) opens and saves."""
    song = copy.deepcopy(SONG)
    song["song"]["audio"] = {"original": "audio/original.wav"}
    song["song"]["availableTracks"] = ["original"]
    song["song"]["recordingCredit"] = {
        "title": "Demo", "artist": "A", "source": "https://example.com", "license": "CC0",
        "licenseUrl": "https://example.com/license", "changes": "none"}
    song["lines"][0]["pronunciation"] = "sha-LOM"
    folder = paths.SONGS / "demo"
    (folder / "song.json").write_text(json.dumps(song, ensure_ascii=False), encoding="utf-8")
    (folder / "audio" / "vocals.wav").unlink()
    (folder / "audio" / "instrumental.wav").unlink()

    got = client.get("/api/songs/demo").json()
    assert got["song"]["recordingCredit"] == song["song"]["recordingCredit"]
    assert got["song"]["availableTracks"] == ["original"]
    assert got["song"]["audio"] == {"original": "audio/original.wav"}
    assert got["lines"][0]["pronunciation"] == "sha-LOM"
    assert client.get("/api/songs/demo/peaks?track=vocals").status_code == 404
    assert client.get("/api/songs/demo/peaks?track=original").status_code == 200

    got["lines"][0]["english"] = "hello"
    assert client.put("/api/songs/demo", json=got).status_code == 200
    saved = client.get("/api/songs/demo").json()
    assert saved["lines"][0]["english"] == "hello"
    assert saved["lines"][0]["pronunciation"] == "sha-LOM"
    assert saved["song"]["recordingCredit"] == song["song"]["recordingCredit"]
    assert saved["song"]["availableTracks"] == ["original"]
    assert set(saved["song"]["audio"]) == {"original"}


def test_list_and_get(client):
    [row] = client.get("/api/songs").json()
    assert {k: row[k] for k in ("id", "title", "durationMs", "words", "flaggedWords", "permission", "favorite", "folders")} == {
        "id": "demo", "title": "Demo", "durationMs": 2000, "words": 2, "flaggedWords": 0, "permission": "Not asked",
        "favorite": False, "folders": []}
    assert client.get("/api/songs/demo").json() == SONG


def test_flagged_words_count_as_to_review(client):
    song = copy.deepcopy(SONG)
    song["lines"][0]["words"][1]["flags"] = ["low-confidence", "long-gap"]
    assert client.put("/api/songs/demo", json=song).status_code == 200
    assert client.get("/api/songs").json()[0]["flaggedWords"] == 1


def test_bad_ids(client):
    assert client.get("/api/songs/..%5Csecret").status_code in (400, 404)
    assert client.get("/api/songs/nope").status_code == 404
    assert client.get("/api/songs/demo/audio/secret").status_code == 400


def test_save_persists_and_backs_up(client, tmp_path):
    edited = copy.deepcopy(SONG)
    w = edited["lines"][0]["words"][0]
    w["endMs"], w["flags"] = 550, ["low-confidence"]
    w["plain"] = "שָׁלוֹם!"  # spelling marks may change: vowel points, punctuation
    assert client.put("/api/songs/demo", json=edited).status_code == 200
    assert client.get("/api/songs/demo").json() == edited  # survives a reload
    backup = json.loads((tmp_path / "songs" / "demo" / "backups" / "song.1.json").read_text(encoding="utf-8"))
    assert backup == SONG


@pytest.mark.parametrize("mutate,status", [
    (lambda s: s["lines"][0]["words"][0].update(endMs=700), 422),           # overlaps next word
    (lambda s: s["lines"][0]["words"][0].update(endMs=120), 422),           # shorter than 40 ms
    (lambda s: s["lines"][0]["words"][1].update(endMs=2500), 422),          # past the song end
    (lambda s: s["lines"][0]["words"][0].update(plain="שלוה"), 409),       # lyrics changed
    (lambda s: s["lines"][0]["words"][0].update(plain="שָׁלוֹמִי"), 409),   # letters differ, even with vowels
    (lambda s: s["lines"][0]["words"][0].update(pointed="שָׁלוֹם"), 422),  # the old schema-1 field is gone
])
def test_save_rejects_invalid(client, mutate, status):
    bad = copy.deepcopy(SONG)
    mutate(bad)
    assert client.put("/api/songs/demo", json=bad).status_code == status
    assert client.get("/api/songs/demo").json() == SONG  # nothing written


CLIP = {"id": "C1", "name": "two words", "fromWord": "L1W1", "toWord": "L1W2", "padBeforeMs": 300, "padAfterMs": 300}
DRILL = {"id": "D1", "name": "drill", "steps": [
    {"type": "clip", "clip": "C1", "repeats": 3, "speed": 0.75, "track": "original", "yourTurn": True,
     "tiers": ["lyrics", "en"]},
    {"type": "card", "text": "Shalom means hello", "durationMs": 4000},
]}


def test_save_sections_clips_drills(client):
    edited = copy.deepcopy(SONG)
    edited["sections"] = [{"id": "S1", "kind": "chorus", "label": "Chorus 1", "fromLine": "L1", "toLine": "L1"}]
    edited["clips"], edited["drills"] = [CLIP], [DRILL]
    assert client.put("/api/songs/demo", json=edited).status_code == 200
    assert client.get("/api/songs/demo").json() == edited


@pytest.mark.parametrize("mutate,message", [
    (lambda s: s["clips"][0].update(fromWord="L1W2", toWord="L1W1"), "invalid word range"),
    (lambda s: s["clips"][0].update(toWord="L9W9"), "invalid word range"),
    (lambda s: s["drills"][0]["steps"][0].update(clip="C7"), "missing clip C7"),
    (lambda s: s["sections"].append(dict(s["sections"][0], id="S2")), "overlaps"),
    (lambda s: s["clips"].append(dict(s["clips"][0])), "duplicate clips ids"),
    (lambda s: s["drills"][0]["steps"][0].update(speed=0.4), "schema"),
    (lambda s: s["drills"][0]["steps"][0].update(repeats=11), "schema"),
])
def test_save_rejects_bad_references(client, mutate, message):
    bad = copy.deepcopy(SONG)
    bad["clips"], bad["drills"] = [dict(CLIP)], copy.deepcopy([DRILL])
    mutate(bad)
    r = client.put("/api/songs/demo", json=bad)
    assert r.status_code == 422 and message in r.json()["detail"]


def test_audio_supports_seeking(client):
    r = client.get("/api/songs/demo/audio/vocals", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100


def test_peaks(client):
    p = client.get("/api/songs/demo/peaks").json()
    assert p["peaksPerSecond"] == 200 and abs(p["duration"] - 2) < 0.01
    assert len(p["peaks"]) == 400 and max(p["peaks"]) == 1.0


def test_breakdown_is_cached_per_line(client, monkeypatch):
    from karaoke import translate
    calls = []

    def fake(words, nearby="", settings=None, unload=False):
        calls.append(words)
        return {"words": [{"word": w, "parts": [{"hebrew": w, "english": "peace"}], "english": "peace", "note": ""} for w in words],
                "literal": "peace peace", "model": "fake"}
    monkeypatch.setattr(translate, "breakdown_line", fake)
    first = client.post("/api/songs/demo/breakdown", json={"lineId": "L1"}).json()
    again = client.post("/api/songs/demo/breakdown", json={"lineId": "L1"}).json()
    assert first == again and first["literal"] == "peace peace" and len(calls) == 1  # second answer from the cache
    client.post("/api/songs/demo/breakdown", json={"lineId": "L1", "refresh": True})
    assert len(calls) == 2  # "Redo" asks the model again
    assert client.post("/api/songs/demo/breakdown", json={"lineId": "L9"}).status_code == 404


# --- add / remove a word ---------------------------------------------------------------
def test_insert_word_splits_a_tight_neighbour_and_renumbers(client):
    r = client.post("/api/songs/demo/words", json={"action": "insert", "wordId": "L1W1", "side": "after", "text": "עולם"})
    assert r.status_code == 200 and r.json()["wordId"] == "L1W2"
    words = client.get("/api/songs/demo").json()["lines"][0]["words"]
    assert [(w["id"], w["plain"], w["startMs"], w["endMs"]) for w in words] == [
        ("L1W1", "שלום", 100, 300), ("L1W2", "עולם", 300, 500), ("L1W3", "שלום", 600, 1000)]
    assert words[1]["flags"] == ["timing-adjusted"]


def test_insert_word_uses_a_gap(client):
    r = client.post("/api/songs/demo/words", json={"action": "insert", "wordId": "L1W2", "side": "after", "text": "עוֹלָם"})
    new = client.get("/api/songs/demo").json()["lines"][0]["words"][2]
    assert (new["id"], new["startMs"], new["endMs"], new["plain"]) == ("L1W3", 1000, 2000, "עוֹלָם")  # as typed


def test_delete_word_moves_clips_and_refuses_unsafe_deletes(client):
    song = client.get("/api/songs/demo").json()
    song["clips"] = [{"id": "C1", "name": "both", "fromWord": "L1W1", "toWord": "L1W2", "padBeforeMs": 0, "padAfterMs": 0},
                     {"id": "C2", "name": "second", "fromWord": "L1W2", "toWord": "L1W2", "padBeforeMs": 0, "padAfterMs": 0}]
    assert client.put("/api/songs/demo", json=song).status_code == 200
    r = client.post("/api/songs/demo/words", json={"action": "delete", "wordId": "L1W2"})
    assert r.status_code == 422 and "C2" in r.json()["detail"]  # a clip of just that word
    r = client.post("/api/songs/demo/words", json={"action": "delete", "wordId": "L1W1"})
    assert r.status_code == 200 and r.json()["wordId"] == "L1W1"
    after = client.get("/api/songs/demo").json()
    assert [w["startMs"] for w in after["lines"][0]["words"]] == [600]  # the old second word, renumbered
    assert [(c["fromWord"], c["toWord"]) for c in after["clips"]] == [("L1W1", "L1W1"), ("L1W1", "L1W1")]
    r = client.post("/api/songs/demo/words", json={"action": "delete", "wordId": "L1W1"})
    assert r.status_code == 422 and "only word" in r.json()["detail"]


def test_insert_needs_exactly_one_word(client):
    for text in ("", "שתי מילים"):
        assert client.post("/api/songs/demo/words", json={"action": "insert", "wordId": "L1W1", "side": "after",
                                                          "text": text}).status_code == 422


def test_insert_at_heard_time_trims_the_stretched_neighbour(client):
    # Whisper heard a word at 400-560 ms, where the forced alignment had stretched L1W1 (100-500) over it
    r = client.post("/api/songs/demo/words", json={"action": "insert", "wordId": "L1W1", "side": "after",
                                                   "text": "עולם", "startMs": 400, "endMs": 560})
    assert r.status_code == 200
    words = client.get("/api/songs/demo").json()["lines"][0]["words"]
    assert [(w["startMs"], w["endMs"]) for w in words] == [(100, 400), (400, 560), (600, 1000)]
    assert "timing-adjusted" not in words[1]["flags"]  # heard timing, not a guess


def test_suggestions_endpoint(client):
    assert client.get("/api/songs/demo/suggestions").json() == {"available": False, "suggestions": []}
    folder = paths.SONGS / "demo"
    (folder / "heard.json").write_text(json.dumps([["שלום", 100, 500, "שלום"], ["עולם", 520, 580, "עולם"],
                                                   ["שלום", 600, 1000, "שלום"]], ensure_ascii=False), encoding="utf-8")
    [s] = client.get("/api/songs/demo/suggestions").json()["suggestions"]
    assert (s["type"], s["text"], s["wordId"]) == ("missing", "עולם", "L1W1")
    assert client.post("/api/songs/demo/suggestions/dismiss", json={"key": s["key"]}).json()["suggestions"] == []


def test_delete_song_is_recoverable(client):
    r = client.delete("/api/songs/demo")
    assert r.status_code == 200 and r.json()["movedTo"].replace("\\", "/").startswith("songs/_deleted/demo-")
    assert client.get("/api/songs").json() == []  # gone from the list (the trash folder isn't a song)
    assert client.get("/api/songs/demo").status_code == 404
    [moved] = (paths.SONGS / "_deleted").iterdir()
    assert (moved / "song.json").is_file()  # everything kept: move it back to restore
    assert client.delete("/api/songs/demo").status_code == 404


# --- library: folders, favourites, status -----------------------------------------------
def test_folders_hold_songs_without_moving_them(client):
    a = client.post("/api/folders", json={"name": "  Ziv   songs "}).json()
    b = client.post("/api/folders", json={"name": "Hard"}).json()
    assert a["name"] == "Ziv songs"  # spaces tidied
    assert client.post("/api/folders", json={"name": "ziv songs"}).status_code == 422  # names are unique, any case
    assert client.post("/api/folders", json={"name": "  "}).status_code == 422

    assert client.put("/api/songs/demo/folders", json={"folders": [b["id"], a["id"]]}).json() == {"folders": sorted([a["id"], b["id"]])}
    assert client.get("/api/songs").json()[0]["folders"] == sorted([a["id"], b["id"]])
    assert {f["name"]: f["count"] for f in client.get("/api/folders").json()} == {"Hard": 1, "Ziv songs": 1}
    assert (paths.SONGS / "demo" / "song.json").is_file()  # the song stays where it was

    assert client.put("/api/songs/demo/folders", json={"folders": [999]}).status_code == 422
    assert client.put("/api/songs/nope/folders", json={"folders": []}).status_code == 404
    assert client.patch(f"/api/folders/{a['id']}", json={"name": "Hard"}).status_code == 422  # taken
    assert client.patch(f"/api/folders/{a['id']}", json={"name": "Ziv"}).status_code == 200

    # deleting a folder keeps the song (and its other folder); dropping a song on a folder adds it once
    assert [f["name"] for f in client.delete(f"/api/folders/{b['id']}").json()] == ["Ziv"]
    assert client.get("/api/songs").json()[0]["folders"] == [a["id"]]
    client.put("/api/songs/demo/folders", json={"folders": []})
    for _ in range(2):
        assert client.post(f"/api/folders/{a['id']}/songs", json={"songId": "demo"}).json()[0]["count"] == 1
    assert client.post(f"/api/folders/{b['id']}/songs", json={"songId": "demo"}).status_code == 422


def test_favorite_and_status(client):
    assert client.put("/api/songs/demo/favorite", json={"favorite": True}).status_code == 200
    row = client.get("/api/songs").json()[0]
    assert row["favorite"] is True
    assert row["status"]["stage"] == "add-english" and (row["status"]["englishLines"], row["status"]["lines"]) == (0, 1)
    song = copy.deepcopy(SONG)
    song["lines"][0]["english"] = "peace"
    client.put("/api/songs/demo", json=song)
    assert client.get("/api/songs").json()[0]["status"]["stage"] == "make-drills"
    client.put("/api/songs/demo/favorite", json={"favorite": False})
    assert client.get("/api/songs").json()[0]["favorite"] is False


def test_practice_log_adds_time_and_line_loops(client):
    assert client.get("/api/songs").json()[0]["practice"] == {"seconds": 0, "practiceSeconds": 0, "lastDay": None, "days": 0}
    assert client.post("/api/songs/demo/practice", json={"source": "studio", "seconds": 30, "loops": {"L1": 2}}).status_code == 204
    assert client.post("/api/songs/demo/practice", json={"source": "practice", "seconds": 12, "loops": {"L1": 1, "L99": 4}}).status_code == 204
    p = client.get("/api/songs/demo/practice").json()
    assert p["seconds"] == 42 and p["lineLoops"] == {"L1": 3}  # a line the song doesn't have is ignored
    assert len(p["days"]) == 1
    summary = client.get("/api/songs").json()[0]["practice"]
    assert (summary["seconds"], summary["practiceSeconds"], summary["days"]) == (42, 12, 1) and summary["lastDay"]

    for bad in ({"source": "radio", "seconds": 5}, {"source": "studio", "seconds": -1}, {"source": "studio", "seconds": 5000},
                {"source": "studio", "seconds": 1.5}, {"source": "studio", "seconds": 5, "loops": {"x; DROP": 1}},
                {"source": "studio", "seconds": 5, "loops": {"L1": 0}}):
        assert client.post("/api/songs/demo/practice", json=bad).status_code == 422, bad
    assert client.post("/api/songs/nope/practice", json={"source": "studio", "seconds": 5}).status_code == 404
    assert client.get("/api/songs/demo/practice").json()["seconds"] == 42  # nothing bad was added


def test_line_ratings_drive_mastery_and_review(client):
    assert client.put("/api/songs/demo/ratings/L1", json={"rating": 1}).status_code == 200
    got = client.get("/api/songs/demo/learning").json()
    assert got["ratings"] == {"L1": 1} and got["mastery"] == 0.5 and got["dueDay"]  # rated today = studied
    assert set(got["newWordIds"]) == {"L1W1", "L1W2"}  # ids only
    row = client.get("/api/songs").json()[0]["learning"]
    assert row["shaky"] == 1 and "newWordIds" not in row
    for bad in ({"rating": 3}, {"rating": "2"}, {"rating": True}, {"rating": 1.0}):
        assert client.put("/api/songs/demo/ratings/L1", json=bad).status_code == 422, bad
    assert client.put("/api/songs/demo/ratings/L9", json={"rating": 2}).status_code == 422
    assert client.put("/api/songs/demo/ratings/L1", json={"rating": None}).status_code == 200
    assert client.get("/api/songs/demo/learning").json()["ratings"] == {}


def test_a_schema_1_song_is_upgraded_when_read_and_saved_as_schema_2(client, tmp_path):
    old = copy.deepcopy(SONG)
    old["schema"] = 1
    del old["song"]["language"]
    for w in old["lines"][0]["words"]:
        w.update(pointed="שָׁלוֹם", syllables=[{"t": "sha", "stress": False}, {"t": "lom", "stress": True}],
                 flags=["stress-guess", "no-niqqud", "low-confidence"])
    old["clips"], old["drills"] = [CLIP], [{**DRILL, "steps": [{**DRILL["steps"][0], "tiers": ["he", "translit", "en"]}]}]
    path = tmp_path / "songs" / "demo" / "song.json"
    path.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    got = client.get("/api/songs/demo").json()
    assert got["schema"] == 2 and got["song"]["language"] == "he"
    assert [set(w) for w in got["lines"][0]["words"]] == [{"id", "plain", "startMs", "endMs", "confidence", "flags"}] * 2
    assert [w["flags"] for w in got["lines"][0]["words"]] == [["low-confidence"]] * 2
    assert got["drills"][0]["steps"][0]["tiers"] == ["lyrics", "en"]
    assert client.put("/api/songs/demo", json=got).status_code == 200  # the editor saves it back as schema 2
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == 2


def test_migrate_command_upgrades_songs_on_disk_and_keeps_the_old_file(client, tmp_path, monkeypatch):
    from karaoke import cli
    monkeypatch.setattr(cli, "SONGS", paths.SONGS)
    old = copy.deepcopy(SONG)
    old["schema"] = 1
    del old["song"]["language"]
    for w in old["lines"][0]["words"]:
        w.update(pointed="שָׁלוֹם", syllables=[{"t": "sha", "stress": False}, {"t": "lom", "stress": True}], flags=["stress-guess"])
    folder = tmp_path / "songs" / "demo"
    (folder / "song.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["migrate"]) == 0
    assert json.loads((folder / "song.json").read_text(encoding="utf-8")) == SONG
    assert json.loads((folder / "backups" / "song.1.json").read_text(encoding="utf-8")) == old
    assert cli.main(["migrate"]) == 0  # second run: already current, nothing written
    assert not (folder / "backups" / "song.2.json").exists()
