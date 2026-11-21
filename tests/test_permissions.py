"""M5: permissions tracker, excerpt guard, export log, follow-up reminders."""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from karaoke import export, guard, paths, permissions
from test_export import SONG

RULES = {"maxContinuousSeconds": 30, "maxShareOfSong": 0.25, "maxShareOfVideo": 0.5}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A 200 s song in a temp songs/ folder and a temp database."""
    monkeypatch.setattr(paths, "SONGS", tmp_path / "songs")
    monkeypatch.setattr(paths, "DB", tmp_path / "data" / "karaoke.db")
    song = json.loads(json.dumps(SONG))
    song["song"]["durationMs"] = 200_000
    (tmp_path / "songs" / "demo").mkdir(parents=True)
    (tmp_path / "songs" / "demo" / "song.json").write_text(json.dumps(song), encoding="utf-8")
    return tmp_path


# --- guard rules ------------------------------------------------------------------
def test_covered_counts_each_moment_once():
    assert guard.covered_ms([(0, 10), (5, 15), (5, 15), (20, 25)]) == 20


def test_rules():
    assert guard.check([(0, 30_000, 30_000)], 200_000, None, RULES) == []  # exactly 30 s is allowed
    assert guard.check([(0, 45_000, 45_000)], 200_000, None, RULES) == ["continuous song audio of 45.0 s (limit 30 s)"]
    # three different 20 s clips: none too long, but 60 s of a 200 s song = 30%
    assert guard.check([(0, 20_000, 20_000), (50_000, 70_000, 20_000), (100_000, 120_000, 20_000)], 200_000, None, RULES) \
        == ["uses 30% of the song (limit 25%)"]
    # one 10 s clip repeated: 5% of the song, but 40 s of a 60 s video is song audio
    assert guard.check([(0, 10_000, 10_000)] * 4, 200_000, 60_000, RULES) == ["song audio is 67% of the video (limit 50%)"]


def test_rules_are_configurable(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    (tmp_path / "guard.json").write_text('{"maxContinuousSeconds": 60}', encoding="utf-8")
    assert guard.load_rules() == {**RULES, "maxContinuousSeconds": 60.0}


def test_lesson_plays_follow_repeats_and_speed():
    played = round(1900 / 0.75)
    assert export.lesson_plays(SONG, SONG["drills"][0]) == [(700, 2600, played), (700, 2600, played), (700, 2600, 1900)]


# --- acceptance: 45 s continuous excerpt from an ungranted song --------------------
def test_45s_excerpt_of_ungranted_song_is_stopped(env):
    with pytest.raises(export.GuardError, match="continuous song audio of 45.0 s") as e:
        export.export_subs("demo", 0, 45)
    assert e.value.status == "Not asked"
    assert not (env / "songs" / "demo" / "exports").exists()  # stopped before writing anything
    assert permissions.export_log() == []


def test_override_is_logged(env):
    result = export.export_subs("demo", 0, 45, override="teaching excerpt, trimmed in Resolve")
    assert result["guard"]["override"] == "teaching excerpt, trimmed in Resolve"
    [row] = permissions.export_log("demo")
    assert (row["kind"], row["ranges"], row["permission_status"], row["override_reason"]) == \
        ("subs", [[0, 45_000]], "Not asked", "teaching excerpt, trimmed in Resolve")
    assert row["warnings"] == ["continuous song audio of 45.0 s (limit 30 s)"]


def test_blank_override_is_not_an_override(env):
    with pytest.raises(export.GuardError):
        export.export_subs("demo", 0, 45, override="   ")


def test_granted_song_exports_without_override(env):
    permissions.save("demo", {"status": "Granted", "scope": "short excerpts with credit"})
    result = export.export_subs("demo", 0, 45)
    assert result["guard"] == {"permission": "Granted", "warnings": ["continuous song audio of 45.0 s (limit 30 s)"],
                               "override": None, "logId": 1}


def test_small_excerpt_needs_no_override_and_is_logged(env):
    export.export_subs("demo", 10, 20)
    [row] = permissions.export_log()
    assert row["override_reason"] is None and row["warnings"] == [] and row["ranges"] == [[10_000, 20_000]]


def test_lesson_without_card_is_blocked_even_with_override(env):
    song = json.loads((env / "songs" / "demo" / "song.json").read_text(encoding="utf-8"))
    song["drills"][0]["steps"] = song["drills"][0]["steps"][1:]
    (env / "songs" / "demo" / "song.json").write_text(json.dumps(song), encoding="utf-8")
    with pytest.raises(export.ExportError, match="teaching card"):
        export.export_lesson("demo", "D1", override="please")


# --- tracker ----------------------------------------------------------------------
def test_asking_sets_follow_up_ten_days_later(env):
    rec = permissions.save("demo", {"status": "Asked", "artist": "Someone"}, today=date(2026, 10, 1))
    assert (rec["asked_on"], rec["follow_up_on"]) == ("2026-10-01", "2026-10-11")


def test_bad_values_are_refused(env):
    for changes in ({"status": "Maybe"}, {"asked_on": "1 Oct"}, {"song": "x"}):
        with pytest.raises(permissions.RecordError):
            permissions.save("demo", changes)


def test_due_on_launch(env):
    permissions.save("demo", {"status": "Asked", "asked_on": "2026-10-01"})
    assert permissions.due(today=date(2026, 10, 10)) == []
    [row] = permissions.due(today=date(2026, 10, 12))
    assert (row["song_id"], row["status"], row["follow_up_on"]) == ("demo", "Follow-up due", "2026-10-11")
    permissions.save("demo", {"status": "Granted"})
    assert permissions.due(today=date(2026, 10, 12)) == []


def test_serve_prints_due_on_launch(env, capsys):
    from karaoke.cli import print_due
    permissions.save("demo", {"status": "Asked", "asked_on": "2020-01-01", "artist": "Someone"})
    print_due()
    assert capsys.readouterr().out.splitlines() == [
        "Follow-up due on 1 permission request(s):", "  demo: asked 2020-01-01, follow up 2020-01-11 (Someone)"]


def test_draft_fills_the_template():
    text = permissions.draft({"contact_name": "", "artist": "דנה"}, "השיר שלי")
    assert text.startswith("שלום דנה,") and "״השיר שלי״" in text and text.endswith("תודה רבה!")


# --- API --------------------------------------------------------------------------
def test_api(env):
    from karaoke.api import app
    client = TestClient(app)
    [row] = client.get("/api/permissions").json()
    assert (row["song_id"], row["status"], row["title"]) == ("demo", "Not asked", "Demo")
    saved = client.put("/api/permissions/demo", json={"status": "Asked", "asked_on": "2020-01-01", "contact_name": "דנה"}).json()
    assert saved["follow_up_on"] == "2020-01-11" and saved["draft"].startswith("שלום דנה,")
    assert [r["song_id"] for r in client.get("/api/permissions/due").json()] == ["demo"]
    assert client.put("/api/permissions/demo", json={"status": "Maybe"}).status_code == 422
    assert client.put("/api/permissions/nope", json={}).status_code == 404
    export.export_subs("demo", 0, 10)
    assert [r["kind"] for r in client.get("/api/export-log?song=demo").json()] == ["subs"]
