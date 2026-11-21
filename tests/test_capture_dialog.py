"""Exercise the native capture dialog asynchronously with a PCM-producing subprocess."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
try:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog
except ModuleNotFoundError:
    QApplication = None
else:
    from native import capture


PCM_HELPER = """
import struct
import sys
import time
print("DEVICE\\tSynthetic output", file=sys.stderr, flush=True)
sys.stdout.buffer.write(struct.pack("<hh", 1400, 1400) * 12000)
sys.stdout.buffer.flush()
time.sleep(15)
"""


@unittest.skipUnless(QApplication, "PySide6 is required for capture dialog tests")
class CaptureDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.destination = Path(temporary.name) / "test.wav"
        self.dialog = capture.CaptureDialog(None, self.destination)
        self.addCleanup(self.dialog.cleanup)

    def run_with_helper(self, helper, when, click):
        timer = QTimer(self.dialog)
        done = False

        def act_when_ready():
            nonlocal done
            if when():
                done = True
                timer.stop()
                click()
        timer.timeout.connect(act_when_ready)
        timeout = QTimer(self.dialog)
        timeout.setSingleShot(True)
        timeout.timeout.connect(self.dialog.reject)
        with patch.object(capture, "command", return_value=(sys.executable, ["-B", "-c", helper])):
            QTimer.singleShot(0, self.dialog.start.click)
            timer.start(20)
            timeout.start(8000)
            result = self.dialog.exec()
            timer.stop()
            timeout.stop()
        self.assertTrue(done, self.dialog.status.text())
        self.assertEqual(list(self.destination.parent.glob(".recording-*.part")), [])
        return result

    def test_stop_keeps_audible_audio(self):
        result = self.run_with_helper(PCM_HELPER, self.dialog.stop.isEnabled, self.dialog.stop.click)
        self.assertEqual(result, QDialog.DialogCode.Accepted)
        with wave.open(str(self.destination), "rb") as wav:
            self.assertEqual(wav.getnframes(), 12000)

    def test_cancel_after_meter_activity_discards_audio(self):
        result = self.run_with_helper(PCM_HELPER, self.dialog.stop.isEnabled, self.dialog.cancel.click)
        self.assertEqual(result, QDialog.DialogCode.Rejected)
        self.assertFalse(self.destination.exists())

    def test_surfaces_permission_error_and_allows_cancel(self):
        helper = "import sys; print('ERROR\\tAllow audio in Privacy settings.', file=sys.stderr); sys.exit(1)"
        result = self.run_with_helper(
            helper, lambda: "Privacy settings" in self.dialog.status.text(), self.dialog.cancel.click,
        )
        self.assertEqual(result, QDialog.DialogCode.Rejected)
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
