import io
import json
import subprocess
import zipfile

import numpy as np

from karaoke import paths, permissions
from test_desktop import studio


def test_downloads_follow_sharing_settings(studio):
    slug = studio.post("/api/desktop/sample").json()["id"]
    permissions.save(slug, {"status": "Not asked"})
    endpoint = f"/api/desktop/export/{slug}/subtitles"
    review = studio.post(endpoint, json={})
    assert review.status_code == 409 and review.json()["detail"]["warnings"]
    result = studio.post(endpoint, json={"reason": "This is my practice exercise."})
    assert result.status_code == 200
    resp = studio.get(result.json()["download"])
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        assert {p.split(".")[-2] for p in z.namelist() if p.endswith(".srt")} == {"lyrics", "en"}
        assert any(p.endswith(".ass") for p in z.namelist())
    assert permissions.export_log(slug)[0]["override_reason"] == "This is my practice exercise."


def test_desktop_renders_real_lesson_and_alpha(studio):
    slug = studio.post("/api/desktop/sample").json()["id"]
    song = studio.get(f"/api/songs/{slug}").json()
    song["drills"][0]["steps"][1].update(speed=.75, repeats=1)
    assert studio.put(f"/api/songs/{slug}", json=song).status_code == 200
    for kind, options in [("lesson", {"drill": "D1"}), ("overlay", {"from": .7, "to": 1.2})]:
        response = studio.post(f"/api/desktop/export/{slug}/{kind}", json=options)
        assert response.status_code == 200, response.text
        path = paths.SONGS / slug / "exports" / response.json()["download"].split("/")[-1]
        metadata = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration:stream=codec_name,pix_fmt,width,height", "-of", "json", str(path)]))
        video = metadata["streams"][0]
        assert (video["width"], video["height"]) == (1920, 1080)
        if kind == "lesson":
            assert [s["codec_name"] for s in metadata["streams"]] == ["h264", "aac"]
            # First four notes play at 75% speed and retain their pitch. The answer gap is silent.
            def samples(t):
                return np.frombuffer(subprocess.check_output(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path),
                                     "-t", "0.22", "-vn", "-ar", "16000", "-ac", "1", "-f", "f32le", "-"]), "<f4")
            tone = samples(3.25)
            fundamental = np.argmax(np.abs(np.fft.rfft(tone * np.hanning(tone.size)))) * 16000 / tone.size
            assert abs(fundamental - 261.63) < 8
            assert np.max(np.abs(samples(9))) < .005
        else:
            assert video["codec_name"] == "prores" and video["pix_fmt"].startswith("yuva")
            alpha = np.frombuffer(subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-vframes", "1",
                                  "-vf", "alphaextract", "-pix_fmt", "gray", "-f", "rawvideo", "-"]), "u1")
            assert alpha.min() < 10 and alpha.max() > 240
