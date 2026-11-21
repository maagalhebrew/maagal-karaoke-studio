"""Exercise prepare staging, subtitle timing and the native import entry points."""

import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from unittest import TestCase, main, skipUnless
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "desktop")]

from karaoke import importer, paths, prepare, songfile, stages


try:
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QFileDialog
except ModuleNotFoundError:
    QApplication = None
else:
    from native import dialogs


SRT = """1
00:00:00,250 --> 00:00:01,250
<i>Otra vez</i>

2
00:00:01,900 --> 00:00:02,750
Otra vez
"""

FAKE_WORKER = """
import json, shutil, subprocess, sys, time
from pathlib import Path
from karaoke import stages
from karaoke.lyrics import Section

area, behavior = Path(sys.argv[1]), sys.argv[2]
while not (area / "ready").exists():
    time.sleep(.01)
request = json.loads((area / "request.json").read_text("utf8"))
if behavior == "cancel":
    descendant = ("import os, sys, time; from pathlib import Path; "
                  "Path(sys.argv[1]).write_text(str(os.getpid()), 'ascii'); time.sleep(30)")
    subprocess.Popen([sys.executable, "-B", "-c", descendant, str(area / "descendant")],
                     creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    (area / "progress").write_text("Working in staging...", "utf8")
    time.sleep(30)
if behavior == "fail":
    (area / "progress").write_text("Fixture model failed. Retry.", "utf8")
    sys.exit(1)
song = stages.Song(request["slug"], area / "song", Path(request["audio"]), area / "lyrics.txt",
                   request["title"], request["language"])
song.audio.mkdir(parents=True)
shutil.copyfile(song.audio_src, song.audio / "original.wav")
song.duration_ms = 4000
stages.set_lyrics(song, [Section(label="Verse 1", lines=[["Otra", "vez"]], english=["Again"])])
for word, start, end in zip(song.words(), [0, 500], [500, 1000]):
    word.update(startMs=start, endMs=end)
stages.assemble(song, original_only=True)
"""


def write_recording(path):
    rate = 22050
    second = b"".join(struct.pack("<h", round(5000 * math.sin(2 * math.pi * 440 * n / rate))) for n in range(rate))
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        wav.writeframes(second * 4)


class PrepareDesktopBackendTest(TestCase):
    def test_subtitle_parser_preserves_repetitions_and_rejects_overlapping_cues(self):
        self.assertEqual(prepare.subtitle_cues(SRT), [(250, 1250, "Otra vez"), (1900, 2750, "Otra vez")])
        with self.assertRaisesRegex(ValueError, "non-overlapping"):
            prepare.subtitle_cues(SRT.replace("00:00:01,900", "00:00:01,000"))
        with self.assertRaisesRegex(ValueError, "timestamps"):
            prepare.subtitle_cues(SRT.replace("00:00:00,250", "00:00:zero"))
        with self.assertRaisesRegex(ValueError, "timestamps"):
            prepare.subtitle_cues(SRT.replace("00:00:00,250", "00:00:99,250"))

    @skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and FFprobe are required")
    def test_trimmed_subtitle_boundaries_use_actual_audio_duration(self):
        def copy_stems(song):
            for track in ("vocals", "instrumental"):
                shutil.copyfile(song.audio / "original.wav", song.audio / f"{track}.wav")

        def english(song):
            for line in song.lines:
                line["english"] = "Again"

        with tempfile.TemporaryDirectory() as directory:
            area = Path(directory)
            source = area / "recording.wav"
            write_recording(source)
            request = dict(audio=str(source), start=.5, end=2.5, slug="repeated-lines", title="Repeated lines",
                           language="es", bilingual=False, lyrics=SRT, artist="")
            (area / "request.json").write_text(json.dumps(request), "utf8")
            # Real media conversion and schema assembly. Only model stages are stubbed.
            with patch.object(stages, "separate", copy_stems), patch.object(stages, "translate_stage", english):
                with patch.object(prepare, "translate_lines", english):
                    prepare.prepare(area)
            doc = songfile.load(area / "song")
            self.assertEqual(doc["song"]["durationMs"], 2000)
            self.assertEqual(doc["song"]["language"], "es")
            self.assertEqual([line["english"] for line in doc["lines"]], ["Again", "Again"])
            self.assertEqual([[(w["plain"], w["startMs"], w["endMs"]) for w in line["words"]]
                              for line in doc["lines"]],
                             [[("Otra", 0, 375), ("vez", 375, 750)], [("Otra", 1400, 1700), ("vez", 1700, 2000)]])
            self.assertTrue(all("low-confidence" in w["flags"] for line in doc["lines"] for w in line["words"]))


@skipUnless(QApplication, "PySide6 is required for desktop flow checks")
class PrepareDesktopQtTest(TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.source = self.folder / "Recording.wav"
        self.dropped = self.folder / "Dropped.wav"
        write_recording(self.source)
        write_recording(self.dropped)
        for name, value in (("SONGS", self.folder / "songs"), ("INBOX", self.folder / "inbox"),
                            ("DB", self.folder / "data" / "karaoke.db")):
            self.enterContext(patch.object(paths, name, value))
        self.enterContext(patch.object(importer, "_job", None))
        self.enterContext(patch.object(dialogs.desktop_models, "status", return_value={
            "message": "Fixture timing tools ready", "automaticReady": True, "canInstall": False,
        }))
        self.dialog = dialogs.AddSong(None)
        self.addCleanup(self.release_dialog)

    def release_dialog(self):
        if self.dialog.process is not None:
            self.dialog.reject()
        self.dialog.preview.stop()
        self.dialog.preview.setSource(QUrl())
        self.application.processEvents()
        self.dialog.captures.cleanup()

    def wait_for(self, condition, seconds=15):
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(.025)
        self.assertTrue(condition(), self.dialog.message.text())

    def fake_worker(self, *behaviors):
        original_popen = subprocess.Popen
        scenarios = iter(behaviors)
        requests = []
        def spawn(args, **options):
            if args[1:3] != ["-m", "karaoke.prepare"]:
                return original_popen(args, **options)
            staging = Path(args[-1])
            requests.append((staging, json.loads((staging / "request.json").read_text("utf8"))))
            return original_popen([sys.executable, "-B", "-c", FAKE_WORKER, str(staging), next(scenarios)], **options)
        env = os.pathsep.join(filter(None, (str(ROOT / "backend"), os.environ.get("PYTHONPATH"))))
        self.enterContext(patch.object(dialogs.desktop_models, "python_for", return_value=sys.executable))
        self.enterContext(patch.object(dialogs.desktop_models, "worker_env", return_value={"PYTHONPATH": env}))
        self.enterContext(patch.object(dialogs.subprocess, "Popen", side_effect=spawn))
        return requests

    def test_file_chooser_prepares_then_publishes_a_valid_fresh_song(self):
        requests = self.fake_worker("success")
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(self.source), "")):
            self.dialog.pick.click()
        self.assertEqual(self.dialog.file, self.source)
        self.assertEqual(self.dialog.title.text(), "Recording")
        self.dialog.start.setValue(.5)
        self.dialog.end.setValue(1.75)
        self.dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click()
        self.assertTrue(self.dialog.running)
        self.assertFalse(self.dialog.pick.isEnabled())
        self.assertFalse((paths.SONGS / "recording").exists())
        self.wait_for(lambda: self.dialog.result() == QDialog.DialogCode.Accepted)
        staging, request = requests[0]
        self.assertEqual(Path(request["audio"]), self.source)
        self.assertEqual((request["start"], request["end"], request["lyrics"]), (.5, 1.75, ""))
        self.assertFalse(staging.exists())
        self.assertEqual(songfile.load(paths.SONGS / "recording")["song"]["title"], "Recording")

    def test_drop_cancel_stops_process_and_cleans_staging(self):
        requests = self.fake_worker("cancel")
        self.dialog.start.setValue(3)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.dropped))])
        event = QDropEvent(QPointF(), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier)
        self.dialog.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(self.dialog.file, self.dropped)
        self.assertEqual(self.dialog.start.value(), 0)
        self.dialog.accept()
        process = self.dialog.process
        staging, _ = requests[0]
        child_pid_file = staging / "descendant"
        self.wait_for(lambda: child_pid_file.exists() and child_pid_file.stat().st_size > 0)
        if os.name == "nt":
            import _winapi
            child_handle = _winapi.OpenProcess(_winapi.SYNCHRONIZE, False, int(child_pid_file.read_text("ascii")))
            self.addCleanup(_winapi.CloseHandle, child_handle)
        self.dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
        self.assertIsNotNone(process.poll())
        if os.name == "nt":
            self.assertEqual(_winapi.WaitForSingleObject(child_handle, 5000), _winapi.WAIT_OBJECT_0)
        self.assertFalse(self.dialog.running)
        self.assertFalse(staging.exists())
        self.assertEqual(list(paths.SONGS.glob("dropped*")), [])
        self.assertTrue(self.dropped.is_file())

    def test_failed_worker_retains_inputs_and_retry_uses_a_fresh_stage(self):
        requests = self.fake_worker("fail", "success")
        self.dialog.select_file(self.source)
        self.dialog.lyrics.setPlainText("Otra vez")
        self.dialog.lang.setCurrentIndex(self.dialog.lang.findData("es"))
        self.dialog.accept()
        self.wait_for(lambda: not self.dialog.running)
        failed_stage, failed_request = requests[0]
        self.assertFalse(failed_stage.exists())
        self.assertIn("Fixture model failed", self.dialog.message.text())
        self.assertEqual(self.dialog.file, self.source)
        self.assertEqual(self.dialog.lyrics.toPlainText(), "Otra vez")
        self.assertTrue(self.dialog.pick.isEnabled())
        self.dialog.accept()
        self.wait_for(lambda: self.dialog.result() == QDialog.DialogCode.Accepted)
        retry_stage, retry_request = requests[1]
        self.assertNotEqual(failed_stage, retry_stage)
        self.assertEqual(failed_request, retry_request)
        self.assertFalse(retry_stage.exists())
        self.assertEqual(songfile.load(paths.SONGS / self.dialog.result_slug)["song"]["language"], "es")

    @skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and FFprobe are required")
    def test_existing_spanish_manual_import_keeps_original_track_and_lyrics(self):
        self.dialog.select_file(self.source)
        self.dialog.lang.setCurrentIndex(self.dialog.lang.findData("es"))
        self.dialog.mode.setCurrentIndex(self.dialog.mode.findData("manual"))
        self.dialog.lyrics.setPlainText("Otra vez\nUna voz")
        self.dialog.accept()
        self.wait_for(lambda: self.dialog.result() == QDialog.DialogCode.Accepted)
        doc = songfile.load(paths.SONGS / self.dialog.result_slug)
        self.assertEqual(doc["song"]["language"], "es")
        self.assertEqual(doc["song"]["availableTracks"], ["original"])
        self.assertEqual([[w["plain"] for w in line["words"]] for line in doc["lines"]],
                         [["Otra", "vez"], ["Una", "voz"]])


if __name__ == "__main__":
    main()
