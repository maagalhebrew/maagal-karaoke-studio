"""M1 pipeline tests. The full run needs a Hatikvah recording at inbox/hatikvah.* and is skipped without one."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from karaoke import lyrics, stages
from karaoke.paths import INBOX, SONGS
from karaoke.songfile import validation_errors

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "hatikvah" / "lyrics.txt"
KARAOKE = [sys.executable, "-m", "karaoke.cli"]


def karaoke(*args):
    return subprocess.run([*KARAOKE, *args], capture_output=True, text=True, encoding="utf-8")


@pytest.fixture(scope="module")
def tone(tmp_path_factory):
    path = tmp_path_factory.mktemp("audio") / "tone.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(path)],
                   check=True)
    return path


def _mp4(path, *sources):
    """Video + one audio track per lavfi source, like an OBS recording."""
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=3"]
    for s in sources:
        cmd += ["-f", "lavfi", "-i", s]
    cmd += ["-map", "0:v", *[a for i in range(len(sources)) for a in ("-map", f"{i + 1}:a")],
            "-c:v", "libx264", "-c:a", "aac", "-t", "3", str(path)]
    subprocess.run(cmd, check=True)
    return path


# --- stage 1 -------------------------------------------------------------------
def test_ingest_picks_loudest_audio_track(tmp_path):
    src = _mp4(tmp_path / "obs.mp4", "anullsrc=r=48000:cl=stereo", "sine=frequency=440:duration=3")
    song = stages.Song("t", tmp_path / "song", src, FIXTURE)
    details = stages.ingest(song)
    assert details["audioTrack"] == "2 of 2"
    assert stages._audio_track_volumes(song.audio / "original.wav")[0] > stages.SILENT_DB


def test_silent_audio_stops_at_stage_1(tmp_path):
    src = _mp4(tmp_path / "silent.mp4", "anullsrc=r=48000:cl=stereo")
    p = karaoke("add", str(src), str(FIXTURE), "--slug", "m1-test-silent")
    assert p.returncode == 1 and "FAILED at stage 1 (ingest): audio is silent" in p.stdout
    assert not (SONGS / "m1-test-silent").exists()


def test_empty_lyrics_stops_at_stage_1(tmp_path, tone):
    empty = tmp_path / "lyrics.txt"
    empty.write_text("", encoding="utf-8")
    p = karaoke("add", str(tone), str(empty), "--slug", "m1-test-empty")
    assert p.returncode == 1
    assert "FAILED at stage 1 (ingest): lyrics file has no Hebrew lines" in p.stdout
    assert not (SONGS / "m1-test-empty").exists()


def test_empty_lyrics_json_output(tmp_path, tone):
    empty = tmp_path / "lyrics.txt"
    empty.write_text("\n\n", encoding="utf-8")
    out = json.loads(karaoke("add", str(tone), str(empty), "--slug", "m1-test-empty", "--json").stdout)
    assert (out["ok"], out["error"]["stage"]) == (False, "ingest")


def test_non_utf8_lyrics_stops_at_stage_1(tmp_path, tone):
    bad = tmp_path / "lyrics.txt"
    bad.write_bytes("שלום".encode("cp1255"))
    p = karaoke("add", str(tone), str(bad), "--slug", "m1-test-cp1255")
    assert p.returncode == 1 and "not UTF-8" in p.stdout


def test_lyrics_sections():
    secs = lyrics.parse("[chorus]\nא ב\n\nג\n[פזמון]\nד\n[pre-chorus]\nה\n")
    assert [(s.kind, s.label, len(s.lines)) for s in secs] == [
        ("chorus", "Chorus 1", 1), ("verse", "Verse 1", 1), ("chorus", "Chorus 2", 1), ("custom", "pre-chorus", 1)]


def test_bare_section_words_are_labels_not_sung_lines():
    text = "א ב\nChorus\nג\n\nפזמון x2\nד\n(בית)\nה\nVerse:\nו\n[פזמון ×2]\nז"
    secs = lyrics.parse(text)
    assert [(s.kind, len(s.lines)) for s in secs] == [("verse", 1), ("chorus", 1), ("chorus", 1), ("verse", 1), ("verse", 1), ("chorus", 1)]
    assert [s.label for s in secs] == ["Verse 1", "Chorus 1", "Chorus 2", "Verse 2", "Verse 3", "Chorus 3"]


def test_a_bare_english_label_does_not_switch_on_three_line_mode():
    assert not lyrics.is_three_line(["א ב", "Chorus", "ג ד"])
    assert len(lyrics.parse("א ב\n\nChorus\nג ד")) == 2


# ChatGPT lyrics-skill output: Hebrew / English / pronunciation, blank line between blocks, chat markdown
THREE_LINE = """**[Verse 1]**
שָׁלוֹם עוֹלָם
Hello world
sha-LOM o-LAM

1. אני מחליט עכשיו
I decide now
ani mach-LIT ach-SHAV

[Chorus]
שלום
Hi
"""


def test_three_line_format():
    secs = lyrics.parse(THREE_LINE)
    assert [(s.kind, s.label, len(s.lines)) for s in secs] == [("verse", "Verse 1", 2), ("chorus", "Chorus 1", 1)]
    assert secs[0].english == ["Hello world", "I decide now"] and secs[1].english == ["Hi"]
    assert secs[0].pronunciation == ["sha-LOM o-LAM", "ani mach-LIT ach-SHAV"] and secs[1].pronunciation == [""]
    assert secs[0].lines[1] == ["אני", "מחליט", "עכשיו"]  # numbering stripped
    assert lyrics.summary(secs)["withPronunciation"] == 2


def test_hebrew_only_lyrics_unchanged_by_three_line_support():
    assert not lyrics.is_three_line(["א ב", "", "ג", "ד"])


# --- schema -----------------------------------------------------------------------
GOOD = {
    "schema": 2,
    "song": {"id": "t", "title": "", "artist": "", "language": "he", "permissionId": None,
             "audio": {"original": "a", "vocals": "v", "instrumental": "i"}, "durationMs": 1000},
    "lines": [{"id": "L1", "english": "", "words": [
        {"id": "L1W1", "plain": "x", "startMs": 0, "endMs": 100, "confidence": 0.9, "flags": []}]}],
    "sections": [{"id": "S1", "kind": "verse", "label": "Verse 1", "fromLine": "L1", "toLine": "L1"}],
    "clips": [], "drills": [],
}


def test_schema_accepts_valid_song():
    assert validation_errors(GOOD) == []


@pytest.mark.parametrize("mutate", [
    lambda s: s["lines"][0]["words"][0].update(pointed="x"),       # schema-1 fields are gone
    lambda s: s["lines"][0]["words"][0].update(syllables=[]),
    lambda s: s["song"].update(language="fr"),                    # Hebrew or Spanish only
    lambda s: s.update(schema=1),
])
def test_schema_rejects_old_or_unknown_fields(mutate):
    bad = copy.deepcopy(GOOD)
    mutate(bad)
    assert validation_errors(bad)


def test_schema_rejects_float_ms():
    bad = copy.deepcopy(GOOD)
    bad["lines"][0]["words"][0]["startMs"] = 1.5
    assert validation_errors(bad)


CREDIT = {"title": "Demo", "artist": "A", "source": "https://example.com", "license": "CC0",
          "licenseUrl": "https://example.com/license", "changes": "none"}


def test_schema_accepts_a_desktop_song_with_only_the_original_recording():
    song = copy.deepcopy(GOOD)
    song["song"]["audio"] = {"original": "audio/original.wav"}
    song["song"]["availableTracks"] = ["original"]
    song["song"]["recordingCredit"] = CREDIT
    song["lines"][0]["pronunciation"] = "sha-LOM"
    assert validation_errors(song) == []


def test_schema_requires_stems_unless_the_song_says_only_the_original_is_available():
    bare = copy.deepcopy(GOOD)
    bare["song"]["audio"] = {"original": "audio/original.wav"}
    assert validation_errors(bare)
    extra = copy.deepcopy(bare)
    extra["song"]["availableTracks"] = ["original"]
    extra["song"]["audio"]["vocals"] = "audio/vocals.wav"
    assert validation_errors(extra)
    wrong = copy.deepcopy(bare)
    wrong["song"]["availableTracks"] = ["original", "vocals"]
    assert validation_errors(wrong)


# --- full run (needs the user's recording) ------------------------------------------
RECORDING = (Path(os.environ["KARAOKE_TEST_RECORDING"]) if os.environ.get("KARAOKE_TEST_RECORDING") else
             next(iter(sorted(p for p in INBOX.glob("hatikva*.*") if p.suffix.lower() in stages.AUDIO_TYPES)), None))


TEST_SLUG = "m1-test-hatikvah"  # never the user's own "hatikvah" song, which they edit in the editor


@pytest.fixture
def test_song_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("KARAOKE_HOME", str(tmp_path))
    return tmp_path / "songs" / TEST_SLUG


@pytest.mark.skipif(RECORDING is None, reason="put a Hatikvah recording at inbox/hatikva(h).mp3|m4a|mp4|wav")
def test_full_pipeline_on_hatikvah(test_song_folder):
    p = karaoke("add", str(RECORDING), str(FIXTURE), "--slug", TEST_SLUG, "--json")
    out = json.loads(p.stdout)
    assert out["ok"], out["error"]
    assert [s["stage"] for s in out["stages"]] == stages.STAGES
    details = {s["stage"]: s["details"] for s in out["stages"]}
    assert details["align"]["medianConfidence"] >= 0.5
    # local model wrote English for every line (skipped only if Ollama isn't running on this machine)
    skipped = details["translate"].get("skipped", "")
    assert details["translate"].get("translated") == 10 or "English translation isn't available" in skipped

    folder = test_song_folder
    song = json.loads((folder / "song.json").read_text(encoding="utf-8"))
    assert validation_errors(song) == []
    words = [w for line in song["lines"] for w in line["words"]]
    assert len(words) == 35
    assert all(w["endMs"] - w["startMs"] >= stages.MIN_WORD_MS for w in words)
    assert all(set(w) == {"id", "plain", "startMs", "endMs", "confidence", "flags"} for w in words)
    assert not any("long-gap" in w["flags"] for w in words)  # every sung line is in the lyrics
    for name in ("original.wav", "vocals.wav", "instrumental.wav"):
        assert (folder / "audio" / name).exists()
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    assert report["counts"]["words"] == 35
