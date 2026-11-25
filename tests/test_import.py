"""Import page API: lyrics check and input validation (no network; the download itself was tested by hand)."""
import pytest
from fastapi.testclient import TestClient

from karaoke import api, importer, paths
from test_pipeline import THREE_LINE


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SONGS", tmp_path / "songs")
    monkeypatch.setattr(paths, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(importer, "_job", None)
    return TestClient(api.app)


def test_check_counts_three_line_lyrics(client):
    r = client.post("/api/import/check", json={"lyrics": THREE_LINE}).json()
    assert (r["lines"], r["sections"], r["withEnglish"], r["withPronunciation"], r["problems"]) == (3, 2, 3, 2, [])


def test_check_flags_lyrics_without_hebrew(client):
    assert client.post("/api/import/check", json={"lyrics": "just english"}).json()["problems"] == ["No Hebrew lines found."]


@pytest.mark.parametrize("url", ["", "https://example.com/watch?v=x", "file:///C:/song.mp3", "youtube.com.evil.net/x"])
def test_only_youtube_links_are_accepted(client, url):
    r = client.post("/api/import", json={"url": url, "lyrics": THREE_LINE})
    assert r.status_code == 422 and "YouTube" in r.json()["detail"]
    assert client.get("/api/import").json() is None  # nothing started


def test_lyrics_problems_stop_the_import(client):
    r = client.post("/api/import", json={"url": "https://youtu.be/abc", "lyrics": "no hebrew here"})
    assert r.status_code == 422 and r.json()["detail"] == "No Hebrew lines found."


def test_folder_name_from_title_is_unique(client):
    (paths.SONGS / "my-song").mkdir(parents=True)
    assert importer._unique_slug("My Song") == "my-song-2"
    assert importer._unique_slug("שיר").startswith("song-")  # Hebrew-only title: dated name


def test_folder_name_avoids_windows_reserved_names_and_stays_short(client):
    reserved = importer._unique_slug("CON")
    assert reserved == "song-con"
    assert len(importer._unique_slug("A" * 200)) <= 72


# --- YouTube sign-in cookies (fake file; real ones are the user's) --------------------------------------
FAKE_COOKIES = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tFAKE\tnot-a-real-value\n"


def test_cookies_saved_checked_never_returned_and_removable(client, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "YT_COOKIES", tmp_path / "data" / "youtube-cookies.txt")
    assert client.get("/api/youtube-cookies").json() == {"present": False}
    r = client.put("/api/youtube-cookies", json={"text": FAKE_COOKIES})
    assert r.status_code == 200 and r.json()["present"] is True and "not-a-real-value" not in r.text
    assert paths.YT_COOKIES.read_bytes().count(b"\r\n") == 2  # CRLF, as yt-dlp wants on Windows
    for bad in ("hello", "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tTRUE\t0\tA\tB\n"):
        assert client.put("/api/youtube-cookies", json={"text": bad}).status_code == 422
    assert client.delete("/api/youtube-cookies").json() == {"present": False} and not paths.YT_COOKIES.exists()


def test_download_uses_cookies_and_explains_a_block(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "YT_COOKIES", tmp_path / "youtube-cookies.txt")
    monkeypatch.setattr(paths, "INBOX", tmp_path / "inbox")
    paths.YT_COOKIES.write_text(FAKE_COOKIES)
    seen = {}

    class Done:
        returncode, stdout = 1, ""
        stderr = "ERROR: [youtube] x: Sign in to confirm you’re not a bot. Use --cookies-from-browser"

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return Done()
    monkeypatch.setattr(importer.subprocess, "run", fake_run)
    monkeypatch.setattr(importer, "_job", {"slug": "x", "state": "running", "error": None, "note": None,
                                           "steps": [{"name": n, "state": "waiting", "seconds": None} for n in importer.STEPS]})
    importer._run("x", "https://youtu.be/x", "שלום", "", "", "")
    assert seen["cmd"][seen["cmd"].index("--cookies") + 1] == str(paths.YT_COOKIES)
    assert importer.status()["error"]["message"].startswith("YouTube is blocking downloads")


# --- uploaded audio (a file or a system-sound recording) ------------------------------------------------
def _tone(path, seconds=2):
    import subprocess
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    str(path)], check=True)
    return path.read_bytes()


def test_recording_upload_is_converted_and_can_start_an_import(client, tmp_path, monkeypatch):
    body = _tone(tmp_path / "rec.webm")  # what Chrome's recorder makes
    r = client.post("/api/import/audio?name=recording.webm", content=body)
    assert r.status_code == 200, r.text
    up = r.json()
    assert up["upload"].startswith("upload-") and 1.5 < up["seconds"] < 2.5
    assert [p.suffix for p in paths.INBOX.iterdir()] == [".wav"]  # converted; the WebM is gone

    seen = {}
    monkeypatch.setattr(importer.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: seen.update(args=args)})())
    job = client.post("/api/import", json={"upload": up["upload"], "lyrics": THREE_LINE, "title": "Rec"}).json()
    assert [s["name"] for s in job["steps"]][:2] == ["upload", "ingest"]
    audio, language, english_lines = seen["args"][6:]
    assert (audio.suffix, language, english_lines) == (".wav", "he", None)


def test_upload_rejects_wrong_types_junk_and_unknown_ids(client):
    r = client.post("/api/import/audio?name=notes.txt", content=b"hello")
    assert r.status_code == 422 and "MP3" in r.json()["detail"]
    r = client.post("/api/import/audio?name=song.mp3", content=b"not audio at all")
    assert r.status_code == 422 and "no audio" in r.json()["detail"]
    assert not list(paths.INBOX.iterdir())  # junk removed
    for bad in ("upload-" + "0" * 32, "../../etc/passwd", "upload-x"):
        r = client.post("/api/import", json={"upload": bad, "lyrics": THREE_LINE})
        assert r.status_code == 422 and "gone" in r.json()["detail"]


def _layout(path, parts):
    """A WAV of (seconds, loud?) parts: sine where loud, near-silence (a faint hiss) elsewhere."""
    import wave
    import numpy as np
    rate = 44100
    chunks = []
    for secs, loud in parts:
        t = np.arange(int(secs * rate)) / rate
        chunks.append(0.5 * np.sin(2 * np.pi * 440 * t) if loud else 0.0005 * np.random.default_rng(0).standard_normal(len(t)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes((np.concatenate(chunks) * 32767).astype("<i2").tobytes())
    return path.read_bytes()


def test_upload_finds_the_song_between_other_sounds_and_trims_to_it(client, tmp_path):
    body = _layout(tmp_path / "rec.wav", [(1, False), (3, True), (2, False), (8, True), (2, False), (2, True), (1, False)])
    up = client.post("/api/import/audio?name=rec.wav", content=body).json()
    assert [[round(s / 1000), round(e / 1000)] for s, e in up["segments"]] == [[1, 4], [6, 14], [16, 18]]
    s, e = up["suggest"]
    assert 5500 <= s <= 6000 and 14000 <= e <= 15800  # the 8-second song, padded, clear of its neighbours
    assert up["peaksPerSecond"] == 20 and len(up["peaks"]) == 19 * 20

    assert client.get(f"/api/import/audio/{up['upload']}").status_code == 200
    cut = client.post(f"/api/import/audio/{up['upload']}/trim", json={"startMs": s, "endMs": e}).json()
    assert abs(cut["seconds"] - (e - s) / 1000) < 0.1
    assert [p.stem for p in paths.INBOX.iterdir()] == [cut["upload"]]  # the untrimmed file is gone
    assert client.post(f"/api/import/audio/{cut['upload']}/trim", json={"startMs": 0, "endMs": 500}).status_code == 422
    assert client.get("/api/import/audio/upload-x").status_code == 404


def test_trim_keeps_the_sound_up_to_its_end(client, tmp_path):
    """The fade-out sits at the end of the cut, not `start` seconds before it (it once silenced the song's last 20 s)."""
    import wave
    import numpy as np
    body = _layout(tmp_path / "tone.wav", [(10, True)])
    up = client.post("/api/import/audio?name=tone.wav", content=body).json()
    cut = client.post(f"/api/import/audio/{up['upload']}/trim", json={"startMs": 4000, "endMs": 9000}).json()
    with wave.open(str(paths.INBOX / f"{cut['upload']}.wav")) as w:
        rate, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, ch)[:, 0] / 32767
    tail = x[-int(0.5 * rate):-int(0.05 * rate)]  # the half second before the 20 ms fade-out
    assert np.sqrt(np.mean(tail ** 2)) > 0.2
