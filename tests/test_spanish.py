"""M8: Spanish songs. Parsing, word forms, translation checks, the import page API and the privacy guard.
Every Spanish line here is made up for the tests (no song lyrics); no model or GPU is needed."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from karaoke import api, learning, lyrics, models, paths, permissions, stages, text, translate
from test_api import SONG as HE_SONG

ROOT = Path(__file__).resolve().parents[1]

# Made-up lines, with credits-style noise, labels and an English line after each lyric line.
LYRICS_ONLY = "Verso 1\nEl sol de la mañana\nCamino por la playa\n\nCoro x2\nCanto contigo\n"
WITH_ENGLISH = "[Verso]\nEl sol de la mañana\nThe morning sun\nCamino por la playa\nI walk along the beach\n\n" \
               "Coro\nCanto contigo\nI sing with you\n"


# --- parsing ------------------------------------------------------------------------
def test_spanish_lyrics_only_with_bare_spanish_section_words():
    secs = lyrics.parse(LYRICS_ONLY, "es")
    assert [(s.kind, s.label, len(s.lines)) for s in secs] == [("verse", "Verse 1", 2), ("chorus", "Chorus 1", 1)]
    assert secs[0].lines[1] == ["Camino", "por", "la", "playa"] and secs[0].english == ["", ""]


def test_spanish_with_english_lines_alternate_and_restart_after_a_blank_line():
    secs = lyrics.parse(WITH_ENGLISH, "es", english_lines=True)
    assert [len(s.lines) for s in secs] == [2, 1]
    assert secs[0].english == ["The morning sun", "I walk along the beach"] and secs[1].english == ["I sing with you"]
    assert lyrics.summary(secs, "es")["lyricLines"] == 3


def test_spanish_english_lines_are_not_guessed():
    # same alphabet as English: without being told, every line is a lyric line
    assert sum(len(s.lines) for s in lyrics.parse(WITH_ENGLISH, "es")) == 6


def test_hebrew_can_be_told_there_are_no_english_lines():
    mixed = "שלום עולם\nOh yeah\nבוקר טוב\n"  # a sung English phrase inside Hebrew lyrics
    assert sum(len(s.lines) for s in lyrics.parse(mixed)) == 2  # detected: "Oh yeah" read as English
    assert sum(len(s.lines) for s in lyrics.parse(mixed, "he", english_lines=False)) == 3


# --- text helpers, word forms -----------------------------------------------------------
def test_spanish_letters_keep_accents_and_drop_punctuation_and_case():
    assert text.letters("¡Está,", "es") == "está" and text.letters("esta", "es") == "esta"
    assert text.letters("שָׁלוֹם,", "he") == "שלום"
    assert text.has_lyrics_text("El sol", "es") and not text.has_lyrics_text("שלום", "es")
    assert not text.has_lyrics_text("1, 2, 3", "es")
    with pytest.raises(ValueError):
        text.check_language("fr")


def test_learning_forms_for_a_spanish_song():
    song = {"song": {"language": "es"}, "lines": [{"words": [{"id": "L1W1", "plain": "¡Hola!"}, {"id": "L1W2", "plain": "..."}]}]}
    assert learning.forms(song) == {"L1W1": "hola"}


def test_the_timing_model_depends_on_the_language():
    assert models.whisper_for("he") == "ivrit-ai/whisper-large-v3-turbo-ct2"
    assert models.whisper_for("es") == "mobiuslabsgmbh/faster-whisper-large-v3-turbo"


# --- translation ---------------------------------------------------------------------------
def test_the_hebrew_prompt_is_unchanged_and_the_spanish_one_names_spanish():
    assert translate.prompt_for("he") == translate.PROMPT
    es = translate.prompt_for("es")
    assert "Spanish song lyrics" in es and "Hebrew" not in es and "Buenos Aires" in es


def test_spanish_copied_back_is_rejected_but_a_real_translation_passes():
    assert translate.plausible("Camino por la playa", "I walk along the beach", "es")
    assert not translate.plausible("Camino por la playa", "Camino por la playa", "es")
    assert not translate.plausible("Camino por la playa", "camino por la playa!", "es")
    assert translate.plausible("No sé", "I don't know", "es")


def test_translate_lines_sends_the_spanish_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    sent = []

    def fake(url, body, timeout):
        sent.append(body)
        return {"message": {"content": json.dumps({translate.KEY: "The morning sun"})}} if "messages" in body else {}
    monkeypatch.setattr(translate, "_post", fake)
    assert translate.translate_lines(["El sol de la mañana"], language="es") == ["The morning sun"]
    system, user = sent[0]["messages"]
    assert "Spanish song lyrics" in system["content"] and user["content"].startswith("Nearby lines (Spanish")


# --- privacy guard ------------------------------------------------------------------------------
def test_an_error_quoting_spanish_lyrics_is_hidden():
    song = stages.Song("t", Path("."), Path("a.wav"), Path("l.txt"), language="es")
    song.lines = [{"id": "L1", "english": "", "words": [{"plain": w} for w in "Camino por la playa".split()]}]
    assert stages.leaks_lyrics("could not align 'Camino por la playa'", song)
    assert not stages.leaks_lyrics("CUDA out of memory (tried to allocate 2 GiB)", song)
    assert stages.leaks_lyrics("שגיאה", song)  # Hebrew text is always hidden


# --- command line: a Spanish lyrics file with no Spanish in it stops at stage 1 --------------------
def test_spanish_song_without_spanish_lines_stops_at_ingest(tmp_path):
    tone = tmp_path / "tone.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(tone)], check=True)
    hebrew = tmp_path / "lyrics.txt"
    hebrew.write_text("שלום עולם\n", encoding="utf-8")
    p = subprocess.run([sys.executable, "-m", "karaoke.cli", "add", str(tone), str(hebrew), "--slug", "m8-test-empty",
                        "--language", "es", "--json"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    out = json.loads(p.stdout)
    assert p.returncode == 1 and out["error"]["stage"] == "ingest" and "no Spanish lines" in out["error"]["message"]


# --- import page API, breakdown, permission draft --------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SONGS", tmp_path / "songs")
    monkeypatch.setattr(paths, "DB", tmp_path / "data" / "karaoke.db")
    folder = tmp_path / "songs" / "demo"
    folder.mkdir(parents=True)
    es = json.loads(json.dumps(HE_SONG))
    es["song"]["language"] = "es"
    es["lines"][0]["words"][0]["plain"], es["lines"][0]["words"][1]["plain"] = "Hola", "mundo"
    (folder / "song.json").write_text(json.dumps(es, ensure_ascii=False), encoding="utf-8")
    return TestClient(api.app)


def test_import_check_counts_spanish_lines_and_honours_the_english_choice(client):
    r = client.post("/api/import/check", json={"lyrics": WITH_ENGLISH, "language": "es", "englishLines": True}).json()
    assert (r["lines"], r["withEnglish"], r["lyricLines"], r["language"], r["problems"]) == (3, 3, 3, "es", [])
    r = client.post("/api/import/check", json={"lyrics": WITH_ENGLISH, "language": "es", "englishLines": False}).json()
    assert (r["lines"], r["withEnglish"]) == (6, 0)
    r = client.post("/api/import/check", json={"lyrics": "שלום", "language": "es"}).json()
    assert r["problems"] == ["No Spanish lines found."]
    assert client.post("/api/import/check", json={"lyrics": "x", "language": "fr"}).status_code == 422
    assert client.post("/api/import/check", json={"lyrics": "x", "englishLines": "maybe"}).status_code == 422


def test_breakdown_is_hebrew_only_for_now(client):
    r = client.post("/api/songs/demo/breakdown", json={"lineId": "L1"})
    assert r.status_code == 422 and "Hebrew" in r.json()["detail"]


def test_spanish_songs_get_the_spanish_permission_draft(client):
    text_ = permissions.draft({"contact_name": "", "artist": "Ana"}, "Mi canción", "es")
    assert text_.startswith("Hola Ana:") and "Mi canción" in text_
    permissions.save("demo", {"status": "Not asked", "artist": "Ana"})
    row = next(r for r in client.get("/api/permissions").json() if r["song_id"] == "demo")
    assert row["draft"].startswith("Hola Ana:")


def _fake_model(monkeypatch, tmp_path, answers):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    answers = list(answers)

    def fake(url, body, timeout):
        return {"message": {"content": json.dumps({translate.KEY: answers.pop(0)})}} if "messages" in body else {}
    monkeypatch.setattr(translate, "_post", fake)


def test_a_spanish_line_the_model_keeps_the_same_twice_is_kept(monkeypatch, tmp_path):
    # names, sounds or an English phrase in the song: the same words are its English
    _fake_model(monkeypatch, tmp_path, ["Oh oh oh", "Oh, oh, oh"])
    assert translate.translate_lines(["Oh oh oh"], language="es") == ["Oh, oh, oh"]


def test_a_spanish_echo_that_the_retry_translates_uses_the_translation(monkeypatch, tmp_path):
    _fake_model(monkeypatch, tmp_path, ["Camino por la playa", "I walk along the beach"])
    assert translate.translate_lines(["Camino por la playa"], language="es") == ["I walk along the beach"]


def test_hebrew_copied_back_twice_is_still_left_empty(monkeypatch, tmp_path):
    _fake_model(monkeypatch, tmp_path, ["שלום", "שלום", "Good morning"])
    assert translate.translate_lines(["שלום", "בוקר טוב"]) == ["", "Good morning"]
