"""Split / join lines and move edge words: ids renumbered, sections, clips, ratings, loops and dismissed
suggestions follow, and every change undoes cleanly (synthetic song, no real lyrics)."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

from karaoke import api, library, lineedit, paths
from test_api import SONG


def song_of(words_per_line):
    """Lines of w words each, 100 ms apart; two sections (lines 1-2, 3-4) and a clip over line 2."""
    s = copy.deepcopy(SONG)
    t, lines = 0, []
    for n, count in enumerate(words_per_line, 1):
        words = []
        for k in range(1, count + 1):
            words.append({**copy.deepcopy(SONG["lines"][0]["words"][0]), "id": f"L{n}W{k}", "startMs": t, "endMs": t + 80})
            t += 100
        lines.append({"id": f"L{n}", "english": f"line {n}", "words": words})
    s["lines"] = lines
    s["song"]["durationMs"] = t + 1000
    s["sections"] = [{"id": "S1", "kind": "verse", "label": "Verse", "fromLine": "L1", "toLine": "L2"},
                     {"id": "S2", "kind": "chorus", "label": "Chorus", "fromLine": "L3", "toLine": "L4"}]
    s["clips"] = [{"id": "C1", "name": "", "fromWord": "L2W1", "toWord": "L2W3", "padBeforeMs": 0, "padAfterMs": 0}]
    return s


def times(s):
    return [(w["startMs"], w["endMs"]) for line in s["lines"] for w in line["words"]]


def test_split_renumbers_and_keeps_everything_pointing_at_the_same_words():
    s = song_of([3, 3, 2, 2])
    before = times(s)
    r = lineedit.apply(s, "split", word_id="L2W2")
    assert [len(line["words"]) for line in s["lines"]] == [3, 1, 2, 2, 2]
    assert [line["id"] for line in s["lines"]] == ["L1", "L2", "L3", "L4", "L5"]
    assert times(s) == before  # nothing re-timed
    assert r["lineIds"] == ["L2", "L3"] and r["wordId"] == "L3W1" and r["undo"] == {"action": "join", "lineId": "L2"}
    assert (s["lines"][1]["english"], s["lines"][2]["english"]) == ("line 2", "")
    assert [(x["fromLine"], x["toLine"]) for x in s["sections"]] == [("L1", "L3"), ("L4", "L5")]
    assert (s["clips"][0]["fromWord"], s["clips"][0]["toWord"]) == ("L2W1", "L3W2")
    assert r["lineMap"]["L2"] == ["L2", "L3"] and r["lineMap"]["L4"] == ["L5"]


def test_each_change_is_undone_by_its_undo():
    for action, args in (("split", {"word_id": "L2W2"}), ("join", {"line_id": "L1"}),
                         ("move", {"word_id": "L2W3", "to": "next"}), ("move", {"word_id": "L4W1", "to": "prev"})):
        original = song_of([3, 3, 2, 2])
        s = copy.deepcopy(original)
        u = lineedit.apply(s, action, **args)["undo"]
        lineedit.apply(s, u["action"], word_id=u.get("wordId", ""), line_id=u.get("lineId", ""), to=u.get("to", ""))
        for line, orig in zip(s["lines"], original["lines"]):
            line["english"] = orig["english"]  # the English comes back with the undo request (API test)
        assert s == original, action


def test_moving_an_edge_word_to_the_next_line():
    s = song_of([3, 3, 2, 2])
    r = lineedit.apply(s, "move", word_id="L2W3", to="next")
    assert [len(line["words"]) for line in s["lines"]] == [3, 2, 3, 2]
    assert r["wordId"] == "L3W1" and r["lineIds"] == ["L2", "L3"]
    assert s["clips"][0]["toWord"] == "L3W1"  # the clip still ends on the same (moved) word


@pytest.mark.parametrize("action,args,message", [
    ("split", {"word_id": "L2W1"}, "already starts"),
    ("join", {"line_id": "L2"}, "different sections"),
    ("join", {"line_id": "L4"}, "last line"),
    ("move", {"word_id": "L2W2", "to": "next"}, "last word"),
    ("move", {"word_id": "L1W1", "to": "prev"}, "first word"),
    ("move", {"word_id": "L9W1", "to": "prev"}, "no word"),
    ("move", {"word_id": "L2W1", "to": "up"}, "prev or next"),
])
def test_refusals(action, args, message):
    with pytest.raises(lineedit.LineEditError, match=message):
        lineedit.apply(song_of([3, 3, 2, 2]), action, **args)


def test_only_word_cannot_move():
    with pytest.raises(lineedit.LineEditError, match="only word"):
        lineedit.apply(song_of([3, 1, 2]), "move", word_id="L2W1", to="prev")


# --- through the API: saved file, ratings, loops, dismissed suggestions, undo with English -----------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SONGS", tmp_path / "songs")
    monkeypatch.setattr(paths, "DB", tmp_path / "data" / "karaoke.db")
    folder = tmp_path / "songs" / "demo"
    folder.mkdir(parents=True)
    (folder / "song.json").write_text(json.dumps(song_of([3, 3, 2, 2]), ensure_ascii=False), encoding="utf-8")
    (folder / "suggestions-dismissed.json").write_text(json.dumps(["unheard:L3W2::שלום"]), encoding="utf-8")
    return TestClient(api.app)


def test_api_split_moves_ratings_and_loops_and_undo_restores_them(client):
    client.put("/api/songs/demo/ratings/L2", json={"rating": 1})
    client.put("/api/songs/demo/ratings/L3", json={"rating": 2})
    client.post("/api/songs/demo/practice", json={"source": "studio", "seconds": 5, "loops": {"L2": 4, "L3": 1}})

    r = client.post("/api/songs/demo/lines", json={"action": "split", "wordId": "L2W2"}).json()
    assert r["lineIds"] == ["L2", "L3"] and r["undo"] == {"action": "join", "lineId": "L2"}
    learn = client.get("/api/songs/demo/learning").json()
    assert learn["ratings"] == {"L2": 1, "L3": 1, "L4": 2}  # both halves keep the split line's rating
    assert client.get("/api/songs/demo/practice").json()["lineLoops"] == {"L2": 4, "L4": 1}
    dismissed = json.loads((paths.SONGS / "demo" / "suggestions-dismissed.json").read_text(encoding="utf-8"))
    assert dismissed == ["unheard:L4W2::שלום"]

    undo = {**r["undo"], "english": {"L2": "line 2"}}
    back = client.post("/api/songs/demo/lines", json=undo).json()["song"]
    assert back == song_of([3, 3, 2, 2])
    assert client.get("/api/songs/demo/learning").json()["ratings"] == {"L2": 1, "L3": 2}
    assert client.get("/api/songs/demo/practice").json()["lineLoops"] == {"L2": 4, "L3": 1}


def test_api_join_keeps_the_weaker_rating_and_refuses_bad_requests(client):
    client.put("/api/songs/demo/ratings/L1", json={"rating": 2})
    client.put("/api/songs/demo/ratings/L2", json={"rating": 0})
    r = client.post("/api/songs/demo/lines", json={"action": "join", "lineId": "L1"})
    assert r.status_code == 200 and r.json()["song"]["lines"][0]["english"] == "line 1 line 2"
    assert client.get("/api/songs/demo/learning").json()["ratings"] == {"L1": 0}
    assert client.post("/api/songs/demo/lines", json={"action": "join", "lineId": "L1"}).status_code == 422  # verse + chorus
    assert client.post("/api/songs/demo/lines", json={"action": "split", "wordId": "L1W2", "english": "x"}).status_code == 422
    assert client.post("/api/songs/demo/translate-lines", json={"lineIds": ["L99"]}).status_code == 422


# --- delete a line (a stray "chorus" line, say) and its undo ----------------------------------------------
def test_join_and_restore_keep_pronunciation():
    joined = song_of([3, 3, 2, 2])
    joined["lines"][0]["pronunciation"] = "one"
    joined["lines"][1]["pronunciation"] = "two"
    lineedit.apply(joined, "join", line_id="L1")
    assert joined["lines"][0]["pronunciation"] == "one two"

    original = song_of([3, 3, 1, 2])
    original["lines"][2]["pronunciation"] = "kept"
    s = copy.deepcopy(original)
    undo = lineedit.apply(s, "delete", line_id="L3")["undo"]
    lineedit.apply(s, "restore", index=undo["index"], line=undo["line"], sections=undo["sections"])
    assert s == original


def test_delete_line_renumbers_and_restore_puts_it_back_exactly():
    original = song_of([3, 3, 1, 2])
    s = copy.deepcopy(original)
    r = lineedit.apply(s, "delete", line_id="L3")
    assert [len(line["words"]) for line in s["lines"]] == [3, 3, 2]
    assert r["lineMap"]["L3"] == [] and r["lineMap"]["L4"] == ["L3"] and r["removed"] == ["L3W1"]
    assert [(x["fromLine"], x["toLine"]) for x in s["sections"]] == [("L1", "L2"), ("L3", "L3")]  # chorus starts later
    assert r["wordId"] == "L3W1" and r["undo"]["action"] == "restore"
    u = r["undo"]
    back = lineedit.apply(s, "restore", index=u["index"], line=u["line"], sections=u["sections"])
    assert s == original and back["undo"] == {"action": "delete", "lineId": "L3"}


def test_deleting_a_sections_only_line_removes_the_section_and_restore_brings_it_back():
    original = song_of([3, 3, 1, 2])
    original["sections"].insert(1, {"id": "S3", "kind": "custom", "label": "x", "fromLine": "L3", "toLine": "L3"})
    original["sections"][2]["fromLine"] = "L4"
    s = copy.deepcopy(original)
    u = lineedit.apply(s, "delete", line_id="L3")["undo"]
    assert [x["id"] for x in s["sections"]] == ["S1", "S2"] and s["sections"][1]["fromLine"] == "L3"
    lineedit.apply(s, "restore", index=u["index"], line=u["line"], sections=u["sections"])
    assert s == original


def test_deleting_the_last_line_selects_the_new_last_line():
    s = song_of([3, 3, 2, 1])
    r = lineedit.apply(s, "delete", line_id="L4")
    assert r["wordId"] == "L3W1" and s["sections"][1]["toLine"] == "L3"


@pytest.mark.parametrize("words,line_id,message", [
    ([3, 3, 2, 2], "L2", "clip"),        # the clip starts on line 2
    ([3], "L1", "only line"),
    ([3, 3], "L9", "no line"),
])
def test_delete_refusals(words, line_id, message):
    s = song_of(words)
    if len(words) < 2:
        s["clips"] = []
    with pytest.raises(lineedit.LineEditError, match=message):
        lineedit.apply(s, "delete", line_id=line_id)


def test_restore_refuses_junk():
    s = song_of([3, 3, 2, 2])
    for kw in ({"index": 0, "line": None, "sections": []}, {"index": 9, "line": s["lines"][0], "sections": []},
               {"index": 0, "line": copy.deepcopy(s["lines"][0]), "sections": [{"fromLine": "L99", "toLine": "L1"}]}):
        with pytest.raises(lineedit.LineEditError):
            lineedit.apply(copy.deepcopy(s), "restore", **kw)


def test_api_delete_drops_the_lines_rating_and_undo_restores_the_song(client):
    client.put("/api/songs/demo/ratings/L3", json={"rating": 1})
    client.put("/api/songs/demo/ratings/L4", json={"rating": 2})
    r = client.post("/api/songs/demo/lines", json={"action": "delete", "lineId": "L3"})
    assert r.status_code == 200
    assert client.get("/api/songs/demo/learning").json()["ratings"] == {"L3": 2}
    dismissed = json.loads((paths.SONGS / "demo" / "suggestions-dismissed.json").read_text(encoding="utf-8"))
    assert dismissed == []  # it was on a deleted word
    back = client.post("/api/songs/demo/lines", json=r.json()["undo"])
    assert back.status_code == 200 and back.json()["song"] == song_of([3, 3, 2, 2])
    bad = client.post("/api/songs/demo/lines", json={"action": "restore", "index": "0", "line": {}, "sections": []})
    assert bad.status_code == 422
