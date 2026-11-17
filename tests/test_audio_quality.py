"""The sound's path in: import keeps a song's dynamics, the quality report is right, link audio isn't converted."""
import subprocess

import numpy as np
import pytest
from fastapi.testclient import TestClient

from karaoke import api, importer, paths, stages
from test_pipeline import FIXTURE


def _audio(path, source, *args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source, *args, str(path)], check=True)
    return path


def _samples(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def _rms_db(x):
    return 20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9)


def test_ingest_keeps_the_gap_between_quiet_and_loud(tmp_path):
    # 10 s quiet, then 10 s 20 dB louder: the old single-pass loudnorm would pull those two together
    src = _audio(tmp_path / "quiet_loud.wav", "sine=frequency=440:duration=20,volume='if(lt(t,10),0.05,0.5)':eval=frame")
    song = stages.Song("t", tmp_path / "song", src, FIXTURE)
    stages.ingest(song)
    before, after = _samples(src), _samples(song.audio / "original.wav")
    a = lambda x: _rms_db(x[8000:72000]) - _rms_db(x[88000:152000])  # quiet minus loud, away from the edges
    assert a(after) == pytest.approx(a(before), abs=0.2)


def test_ingest_gain_respects_the_peak_limit(tmp_path):
    # Tiny full-scale clicks: quiet on average, so reaching the target loudness would push the clicks far over
    src = _audio(tmp_path / "clicks.wav", "aevalsrc='if(lt(mod(t,0.4),0.003),1,0)':d=8:s=44100")
    gain = stages._normalising_gain_db(src, 0)
    assert gain < 0  # brought down to the limit, though the average alone says bring it up
    song = stages.Song("t", tmp_path / "song", src, FIXTURE)
    stages.ingest(song)
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(song.audio / "original.wav"), "-af", "ebur128=peak=true",
                          "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    peak = float(log[log.rfind("Peak:"):].split()[1])
    assert peak <= stages.PEAK_LIMIT_DB + 0.5


def test_quality_report_numbers(tmp_path):
    clean = _audio(tmp_path / "clean.wav", "anoisesrc=d=8:c=pink:a=0.3:r=44100:seed=1", "-ac", "2")
    q = importer.quality(clean)
    assert q["clipped"] == 0 and q["stereo"] is False  # both channels identical: effectively mono
    assert q["topKHz"] > 18 and q["lufs"] < -10 and q["truePeakDb"] < 0

    stereo = tmp_path / "stereo.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=8:c=pink:a=0.3:r=44100:seed=1",
                    "-f", "lavfi", "-i", "anoisesrc=d=8:c=pink:a=0.3:r=44100:seed=2",
                    "-filter_complex", "[0][1]amerge=inputs=2", str(stereo)], check=True)
    assert importer.quality(stereo)["stereo"] is True


def test_quality_report_spots_a_low_quality_stream_and_clipping(tmp_path):
    dull = _audio(tmp_path / "dull.mp3", "anoisesrc=d=8:c=pink:a=0.3:r=44100:seed=1", "-c:a", "libmp3lame", "-b:a", "48k")
    assert importer.quality(dull)["topKHz"] < 15.5  # a low-bitrate stream's cut-off
    hot = _audio(tmp_path / "hot.wav", "sine=frequency=440:duration=4,aformat=channel_layouts=stereo,volume=12")
    assert importer.quality(hot)["clipped"] > 0


def test_youtube_download_keeps_the_stream_unconverted(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "INBOX", tmp_path)
    monkeypatch.setattr(paths, "YT_COOKIES", tmp_path / "none.txt")
    monkeypatch.setattr(importer, "_job", {"steps": [{"name": "download", "state": "waiting"}]})
    seen = {}
    def fake(cmd, **_):
        seen["cmd"] = cmd
        (tmp_path / "s.webm").write_bytes(b"x")
        return subprocess.CompletedProcess(cmd, 0, f"A title\n{tmp_path / 's.webm'}\n", "")
    monkeypatch.setattr(importer.subprocess, "run", fake)
    audio, _ = importer._download("s", "https://youtu.be/abc", {})
    assert audio.suffix == ".webm" and "-x" not in seen["cmd"] and "--audio-format" not in seen["cmd"]
    assert audio.suffix in stages.AUDIO_TYPES  # the pipeline takes it as it is


def test_ingest_takes_a_youtube_style_webm(tmp_path):
    src = _audio(tmp_path / "stream.webm", "sine=frequency=440:duration=4", "-c:a", "libopus", "-b:a", "128k")
    song = stages.Song("t", tmp_path / "song", src, FIXTURE)
    stages.ingest(song)
    assert stages.duration_s(song.audio / "original.wav", "ingest") == pytest.approx(4, abs=0.1)


def test_peaks_follow_the_track(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SONGS", tmp_path / "songs")
    audio = tmp_path / "songs" / "s" / "audio"
    audio.mkdir(parents=True)
    (tmp_path / "songs" / "s" / "song.json").write_text("{}", encoding="utf-8")
    for name in ("vocals", "original"):
        _audio(audio / f"{name}.wav", "sine=frequency=440:duration=1")
    client = TestClient(api.app)
    assert client.get("/api/songs/s/peaks?track=original").status_code == 200
    assert (audio / "original.peaks.json").is_file()
    assert client.get("/api/songs/s/peaks").status_code == 200 and (audio / "vocals.peaks.json").is_file()
    assert client.get("/api/songs/s/peaks?track=nope").status_code == 400
    assert client.get("/api/songs/s/peaks?track=instrumental").status_code == 404
