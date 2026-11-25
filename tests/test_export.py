"""Export tests that need no render: subtitles, lesson length, and the guard rules."""
import json

import pytest

from karaoke import export, paths, subtitles


def w(i, start, end, plain="שָׁלוֹם"):  # written with vowel points, as some lyrics are
    return {"id": i, "plain": plain, "startMs": start, "endMs": end, "confidence": 1.0, "flags": []}


SONG = {
    "schema": 2,
    "song": {"id": "demo", "title": "Demo", "artist": "", "language": "he", "permissionId": None, "durationMs": 10_000,
             "audio": {"original": "audio/original.wav", "vocals": "audio/vocals.wav", "instrumental": "audio/instrumental.wav"}},
    "lines": [
        {"id": "L1", "english": "hello hello", "words": [w("L1W1", 1000, 1600), w("L1W2", 1700, 2300)]},
        {"id": "L2", "english": "", "words": [w("L2W1", 2500, 3500)]},
    ],
    "sections": [],
    "clips": [{"id": "C1", "name": "c", "fromWord": "L1W1", "toWord": "L1W2", "padBeforeMs": 300, "padAfterMs": 300}],
    "drills": [{"id": "D1", "name": "d", "steps": [
        {"type": "card", "text": "card", "durationMs": 4000},
        {"type": "clip", "clip": "C1", "repeats": 2, "speed": 0.75, "track": "original", "yourTurn": True, "tiers": ["lyrics"]},
        {"type": "clip", "clip": "C1", "repeats": 1, "speed": 1, "track": "instrumental", "yourTurn": False, "tiers": ["lyrics"]},
    ]}],
}
STYLE = {"heSizePx": 80, "enScale": 0.6, "textColor": "#ffffff", "highlightColor": "#facc15",
         "boxOpacity": 0.5, "verticalPosition": 0.85, "showNiqqud": True}


def test_cue_windows_lead_tail_and_no_overlap():
    # L1: 1000-300 .. min(2300+500, next 2500-300=2200); L2: 2200 .. 3500+500
    assert [(l["id"], a, b) for l, a, b in subtitles.cues(SONG, 0, 10_000)] == [("L1", 700, 2200), ("L2", 2200, 4000)]


def test_cues_relative_to_range():
    assert [(l["id"], a, b) for l, a, b in subtitles.cues(SONG, 2000, 3000)] == [("L1", 0, 200), ("L2", 200, 1000)]


def test_srt_tiers():
    lyrics = subtitles.srt(SONG, "lyrics", 0, 10_000)
    assert lyrics.startswith("1\n00:00:00,700 --> 00:00:02,200\n‏שָׁלוֹם שָׁלוֹם‏\n")
    assert subtitles.srt(SONG, "lyrics", 0, 10_000, show_niqqud=False).splitlines()[2] == "‏שלום שלום‏"
    assert export.TIERS == ("lyrics", "en")
    en = subtitles.srt(SONG, "en", 0, 10_000)
    assert en.count(" --> ") == 1 and "hello hello" in en  # empty English lines are skipped


def test_ass_has_two_styles_and_word_karaoke_on_the_lyrics():
    text = subtitles.ass(SONG, STYLE, 0, 10_000)
    assert [ln.split(",")[0] for ln in text.splitlines() if ln.startswith("Style:")] == ["Style: Lyrics", "Style: En"]
    assert sum(ln.startswith("Dialogue:") for ln in text.splitlines()) == 3  # 2 lyric lines + 1 English
    lyrics = next(ln for ln in text.splitlines() if ",Lyrics," in ln and ln.startswith("Dialogue"))
    # starts 300 ms before the first word: a 30 cs wait, then each word fills over its own 60 cs
    assert lyrics.endswith("{\\k30}{\\kf60}שָׁלוֹם {\\k10}{\\kf60}שָׁלוֹם‏")


def test_ass_escapes_braces_and_backslashes():
    song = json.loads(json.dumps(SONG))
    song["lines"][0]["words"][0] = w("L1W1", 1000, 1600, "a{b}\\c")
    song["lines"][0]["english"] = "hello {there}"
    text = subtitles.ass(song, STYLE, 0, 10_000)
    assert subtitles.ass_text("a{b}\\c") in text
    assert subtitles.ass_text("hello {there}") in text
    assert "{\\kf60}a{b}" not in text


def test_left_to_right_lyrics_get_no_direction_marks():
    spanish = {**SONG, "song": {**SONG["song"], "language": "es"},
               "lines": [{"id": "L1", "english": "", "words": [w("L1W1", 1000, 1600, "Hola")]}]}
    assert subtitles.srt(spanish, "lyrics", 0, 10_000).splitlines()[2] == "Hola"
    assert subtitles.ass(spanish, STYLE, 0, 10_000).rstrip().endswith("{\\k30}{\\kf60}Hola")


def test_lesson_duration_matches_layout():
    # clip C1 = (1000-300) .. (2300+300) = 700..2600 = 1900 ms. Card 4000 + 2 x (clip at 75% + gap) + 1 x 1900
    played = round(1900 / 0.75)
    assert export.lesson_duration_ms(SONG, SONG["drills"][0]) == 4000 + 2 * 2 * played + 1900


@pytest.fixture
def song_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SONGS", tmp_path / "songs")
    monkeypatch.setattr(paths, "INBOX", tmp_path / "inbox")
    (tmp_path / "songs" / "demo").mkdir(parents=True)
    (tmp_path / "inbox").mkdir()
    return tmp_path


def test_lesson_needs_a_card(song_dir):
    song = json.loads(json.dumps(SONG))
    song["drills"][0]["steps"] = song["drills"][0]["steps"][1:]
    (song_dir / "songs" / "demo" / "song.json").write_text(json.dumps(song), encoding="utf-8")
    with pytest.raises(export.ExportError, match="at least one teaching card"):
        export.export_lesson("demo", "D1")


def test_background_never_from_the_song(song_dir):
    for folder in ("inbox", "songs/demo"):
        f = song_dir / folder / "frame.png"
        f.write_bytes(b"x")
        with pytest.raises(export.ExportError, match="not a file from inbox"):
            export.parse_background(str(f))
    own = song_dir / "my-background.png"
    own.write_bytes(b"x")
    assert export.parse_background(str(own))["kind"] == "image"
    assert export.parse_background("#112233") == {"kind": "color", "color": "#112233"}


def test_range_must_be_inside_song():
    with pytest.raises(export.ExportError):
        export._range(SONG, 5, 11)
    assert export._range(SONG, 1.5, 3) == (1500, 3000)
