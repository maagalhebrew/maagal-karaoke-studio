"""Run with the application's own interpreter against an explicitly supplied empty test library."""

from pathlib import Path
import os
import socket
import sys
import time
import wave
import zipfile


def run(studio, pictures):
    sys.path.insert(0, str(studio))
    import launch

    assert os.environ.get("KARAOKE_HOME"), "Select an isolated KARAOKE_HOME for this check"
    home = launch.library_path()
    if home.exists() and any(home.iterdir()):
        raise ValueError("This check requires an empty test library.")
    launch.configure()

    def offline(event, args):
        if event in ("socket.connect", "socket.bind") and args[0].family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("Offline check attempted an IP connection")

    sys.addaudithook(offline)
    from PySide6.QtCore import Qt, QEvent, QTimer
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton
    from karaoke import desktop_export, library, paths, song_archive, songfile
    from native import store
    from native.dialogs import AddSong, LineText, Timing
    from native.exercises import Exercises
    from native.theme import apply_theme, AMBER
    from native.window import MainWindow

    app = QApplication(["Karaoke IL"])
    apply_theme(app)
    app.setQuitOnLastWindowClosed(False)

    def until(predicate, seconds=12):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            if predicate():
                return
            time.sleep(0.015)
        raise AssertionError("Timed out waiting for " + repr(predicate))

    def push(view, name):
        btn = next(
            b
            for b in view.findChildren(QPushButton)
            if (b.accessibleName() == name or b.text() == name) and b.isVisible()
        )
        btn.click()

    def shot(window, name):
        if pictures:
            pictures.mkdir(parents=True, exist_ok=True)
            app.processEvents()
            assert window.grab().save(str(pictures / (name + ".png")))

    window = MainWindow()
    window.resize(1360, 850)
    window.show()
    app.processEvents()
    assert [r[2] for r in window.rows] == list(store.entry_order)
    shot(window, "Song library")
    from unittest.mock import patch
    from PySide6.QtGui import QDesktopServices

    with patch.object(QDesktopServices, "openUrl", return_value=True) as external:
        push(window, "Visit MaagalHebrew.com")
        assert external.call_args.args[0].toString() == "https://maagalhebrew.com/"
    window.search.setFocus()
    for ch in "Shalom Aleichem":
        key = Qt.Key.Key_Space if ch == " " else ord(ch.upper())
        for action in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            app.sendEvent(window.search, QKeyEvent(action, key, Qt.KeyboardModifier.NoModifier, ch))
    assert window.search.text() == "Shalom Aleichem", window.search.text()
    assert (
        sum(
            b.isVisible() and b.accessibleName().startswith("Play ")
            for b in window.scroll.findChildren(QPushButton)
        )
        == 1
    )
    window.search.clear()
    for folder, doc, key in window.rows:
        push(window, "Play " + doc["song"]["title"])
        p = window.player
        until(lambda: p.playing() and p.media.position() > 100)
        p.play.click()
        until(lambda: not p.playing())
        window_pos = p.lines[0]["words"][0]["startMs"] + 80
        p.seek_to(window_pos)
        until(lambda: abs(p.media.position() - window_pos) < 100)
        p.display(window_pos)
        assert AMBER in p.lyric.text() and p.pron.text() and p.translation.text()
        assert p.pron.isVisible() and p.translation.isVisible()
        if key == "hatikva":
            sample = p.lines[6]["words"][2]["startMs"] + 100
            p.seek_to(sample)
            p.update_time()
            shot(window, "Karaoke player")
            p.seek_to(window_pos)
        p.text_checks["english"].setChecked(False)
        assert p.translation.isHidden()
        p.text_checks["english"].setChecked(True)
        p.text_checks["nikud"].setChecked(False)
        assert not any("\u0591" <= c <= "\u05c7" for c in p.lyric.accessibleDescription())
        p.text_checks["nikud"].setChecked(True)
        p.tracks["instrumental"].click()
        until(lambda: p.pending is None and abs(p.media.position() - window_pos) < 120)
        assert not p.playing() and p.media.source().fileName() == "instrumental.wav"
        p.speed.setCurrentIndex(p.speed.findData(0.75))
        assert abs(p.media.playbackRate() - 0.75) < 0.01
        p.play.click()
        until(lambda: p.playing() and p.media.position() > window_pos + 120)
        p.repeat.click()
        until(lambda: p.repeat_index == 0)
        p.media.setPosition(p.lines[0]["words"][-1]["endMs"] + 1)
        until(lambda: bool(p.loops))
        p.repeat.click()
        p.speed.setCurrentIndex(p.speed.findData(1.0))
        p.next.click()
        until(lambda: p.line_index == 1)
        if key == "hatikva":
            window.set_favorite(folder.name, True)
            start = doc["lines"][0]["words"][0]["startMs"] / 1000
            captions, _ = desktop_export.create(folder.name, "subtitles", {"from": start, "to": start + 1})
            with zipfile.ZipFile(captions) as file:
                assert doc["song"]["recordingCredit"]["source"] in file.read("Recording credits.txt").decode(
                    "utf8"
                )
        window.show_library()
        app.processEvents()
    assert not (home / "desktop.json").exists()
    assert not {"uvicorn", "fastapi", "webbrowser"}.intersection(sys.modules)
    print(
        "Offline native playback, three guides and backing tracks, Hebrew highlighting, reading aids, speed, repeat, search and settings passed.",
        flush=True,
    )

    window.browse("Favorites")
    assert (
        len([b for b in window.scroll.findChildren(QPushButton) if b.accessibleName().startswith("Play ")])
        == 1
    )
    window.browse("Song library")
    # Use the real manual import and timing dialogs with a short, isolated fixture.
    recording = home / "short test audio.wav"
    import math
    from array import array

    with wave.open(str(recording), "wb") as f:
        f.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        f.writeframes(
            array("h", (int(8800 * math.sin(i * 2 * math.pi * 240 / 8000)) for i in range(16000))).tobytes()
        )
    add = AddSong(window)
    add.mode.setCurrentIndex(add.mode.findData("manual"))
    add.file = recording
    add.title.setText("Practice example")
    add.lyrics.setPlainText("שָׁלוֹם עוֹלָם\nHello world")
    add.english.setChecked(True)
    quiet = home / "silent recording.wav"
    with wave.open(str(quiet), "wb") as f:
        f.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        f.writeframes(bytes(32000))
    add.file = quiet
    add.show()
    add.accept()
    until(lambda: not add.running and "silent" in add.message.text().lower(), 20)
    assert add.isEnabled()
    add.mode.setCurrentIndex(add.mode.findData("manual"))
    add.file = recording
    QTimer.singleShot(10, add.accept)
    QTimer.singleShot(35000, lambda: add.done(QDialog.DialogCode.Rejected) if add.isVisible() else None)
    assert add.exec() == QDialog.DialogCode.Accepted, add.message.text()
    window.open_id(add.result_slug)
    p = window.player
    until(lambda: p.pending is None)
    assert not p.tracks["instrumental"].isEnabled()
    p.media.pause()
    edit = Timing(window, p.folder, p.doc)
    edit.next_review()
    assert edit.table.currentRow() == 0
    edit.table.item(0, 2).setText(".1")
    edit.accept()
    assert edit.result() == QDialog.DialogCode.Accepted, edit.tip.text()
    edit = LineText(window, p.folder, songfile.load(p.folder))
    edit.table.item(0, 1).setText("sha-LOM o-LAM")
    edit.accept()
    doc = songfile.load(p.folder)
    assert doc["lines"][0]["pronunciation"] == "sha-LOM o-LAM"
    assert doc["lines"][0]["words"][0]["startMs"] == 100
    p.doc = doc
    p.lines = doc["lines"]
    clips = Exercises(p)
    clips.clip_name.setText("First phrase")
    clips.add_clip()
    clips.add_step()
    clips.name.setText("One repeat")
    clips.add_drill()
    assert len(songfile.load(p.folder)["drills"]) == 1, clips.notice.text()
    clips.accept()
    bundle = song_archive.backup(p.folder)
    try:
        restored = song_archive.restore(bundle, store.validate)
    finally:
        bundle.unlink()
    assert restored != p.folder.name
    assert songfile.load(paths.SONGS / restored)["lines"] == doc["lines"]
    exported, _ = desktop_export.create(
        restored, "subtitles", {"from": 0, "to": 1, "reason": "Short test excerpt"}
    )
    with zipfile.ZipFile(exported) as f:
        assert any(n.endswith(".srt") for n in f.namelist())
    window.close()
    app.processEvents()
    window = MainWindow()
    window.show()
    app.processEvents()
    assert len(window.rows) == 5
    assert "maagal-hatikva" in library.labels()[1]
    assert library.practice("maagal-hatikva")["lineLoops"]["L1"] >= 1
    window.close()
    print(
        "Manual import, saved timing, pronunciation, clips, drills, backup and restore, subtitle export, history and reopen passed.",
        flush=True,
    )


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None)
