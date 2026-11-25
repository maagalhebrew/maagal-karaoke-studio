"""Translate stage: Ollama replies are faked, so no model or GPU is needed."""
import json

import pytest

from karaoke import paths, stages, translate


def reply(english):
    return {"message": {"content": json.dumps({translate.KEY: english})}}


@pytest.fixture
def calls(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA", tmp_path)  # default settings
    sent = []

    def fake(url, body, timeout):
        sent.append(body)
        return fake.replies.pop(0) if "messages" in body else {}  # no messages = the unload request
    fake.replies = []
    monkeypatch.setattr(translate, "_post", fake)
    return fake, sent


def song_with(lines):
    s = stages.Song(slug="t", folder=paths.SONGS, audio_src=paths.SONGS, lyrics_src=paths.SONGS)
    s.lines = [{"id": f"L{i}", "english": en, "words": [{"plain": w} for w in he.split()]}
               for i, (he, en) in enumerate(lines, 1)]
    return s


def test_one_request_per_line_repeats_once_then_unload(calls):
    fake, sent = calls
    fake.replies = [reply("Hello world"), reply('"Peace"')]
    assert translate.translate_lines(["שלום עולם", "שלום", "שלום עולם"]) == ["Hello world", "Peace", "Hello world"]
    chats = [b for b in sent if "messages" in b]
    assert len(chats) == 2 and all(b["think"] is False for b in chats)
    # one line per request, with its neighbours as context
    assert chats[1]["messages"][1]["content"].endswith("Hebrew line: שלום\nEnglish translation:")
    assert "שלום עולם\nשלום" in chats[1]["messages"][1]["content"]
    assert sent[-1] == {"model": translate.DEFAULTS["model"], "keep_alive": 0}  # frees the GPU for alignment (rule 4)


def test_context_is_only_the_neighbouring_lines(calls):
    fake, sent = calls
    lines = [f"שורה{c}" for c in "אבגדהוזח"]
    fake.replies = [reply("x")] * len(lines)
    translate.translate_lines(lines)
    middle = [b for b in sent if "messages" in b][4]["messages"][1]["content"]
    assert "שורהג\nשורהד\nשורהה\nשורהו" in middle and "שורהב" not in middle and "שורהז" not in middle


def test_hebrew_copied_back_is_never_saved_as_english(calls):
    fake, _ = calls
    fake.replies = [reply("למה אני לא בבית"), reply("why am i not home")]
    assert translate.translate_lines(["למה אני לא בבית"]) == ["why am i not home"]
    fake.replies = [reply("שלום"), reply("שלום עולם"), reply("morning")]
    assert translate.translate_lines(["שלום", "בוקר"]) == ["", "morning"]  # Hebrew twice -> left empty


def test_answer_that_swallowed_other_lines_is_retried_then_left_empty(calls):
    fake, _ = calls
    run_on = "and then all the next lines of the song merged into this one subtitle line again and again"
    fake.replies = [reply(run_on), reply(run_on), reply("Good")]
    assert translate.translate_lines(["שלום לך", "בוקר טוב"]) == ["", "Good"]


def test_nothing_usable_is_reported_and_model_still_unloaded(calls):
    fake, sent = calls
    fake.replies = [{"message": {"content": "not json"}}] * 2
    with pytest.raises(translate.TranslateError, match="usable form"):
        translate.translate_lines(["שלום"])
    assert sent[-1]["keep_alive"] == 0


def test_plausible_length():
    assert translate.plausible("שלום עולם", "Hello world")
    assert not translate.plausible("שלום", "word " * 8)
    assert not translate.plausible("שלום", "")
    assert not translate.plausible("שלום עולם", "שלום עולם")  # copied back


def test_stage_fills_only_lines_without_english(calls):
    fake, sent = calls
    fake.replies = [reply("Hi")]
    s = song_with([("שלום", ""), ("עולם", "World (from ChatGPT)")])
    assert stages.translate_stage(s) == {"model": translate.DEFAULTS["model"], "translated": 1, "alreadyHadEnglish": 1}
    assert [line["english"] for line in s.lines] == ["Hi", "World (from ChatGPT)"]
    assert sent[0]["messages"][1]["content"].endswith("Hebrew line: שלום\nEnglish translation:")


def test_stage_never_fails_the_song(calls, monkeypatch):
    def down(*_):
        raise translate.TranslateError("Ollama is not reachable")
    monkeypatch.setattr(translate, "_post", down)
    s = song_with([("שלום", "")])
    assert stages.translate_stage(s) == {"translated": 0, "skipped": "Ollama is not reachable"}
    assert s.lines[0]["english"] == ""


def test_can_be_turned_off(calls, tmp_path):
    (tmp_path / "translate.json").write_text('{"enabled": false}', encoding="utf-8")
    assert stages.translate_stage(song_with([("שלום", "")]))["skipped"] == "English translation is turned off."


def test_ready_is_whether_the_configured_model_is_installed(monkeypatch):
    monkeypatch.setattr(translate, "installed_models", lambda settings=None: ["gemma4:12b"])
    assert translate.translation_ready() is True
    monkeypatch.setattr(translate, "installed_models", lambda settings=None: ["something-else:1b"])
    assert translate.translation_ready() is False
    monkeypatch.setattr(translate, "installed_models", lambda settings=None: [])
    assert translate.translation_ready() is False
