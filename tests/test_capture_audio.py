"""Driver-independent checks for computer audio capture and transactional WAV output."""

from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

# Also runs directly using Python without a Qt installation or audio device.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from native import capture_audio as capture


class CaptureAudioTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.destination = Path(temporary.name) / "recording.wav"
        self.audible = struct.pack("<hh", -1024, 2048) * capture.MIN_FRAMES

    def assert_no_partial(self):
        self.assertEqual(list(self.destination.parent.glob(".recording-*.part")), [])

    def test_writes_a_complete_stereo_wav_after_stop(self):
        recording = capture.Recording(self.destination)
        self.assertEqual(recording.append(self.audible[:3]), 0)
        self.assertGreater(recording.append(self.audible[3:]), 0)
        self.assertFalse(self.destination.exists())
        self.assertTrue(recording.finish(save=True))
        with wave.open(str(self.destination), "rb") as wav:
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (2, 2, 48_000))
            self.assertEqual(wav.readframes(wav.getnframes()), self.audible)
        self.assert_no_partial()

    def test_silence_and_too_short_do_not_commit(self):
        silence = bytes(capture.MIN_FRAMES * capture.FRAME_BYTES)
        for samples in (silence, self.audible[:4]):
            with self.subTest(length=len(samples)):
                recording = capture.Recording(self.destination)
                recording.append(samples)
                self.assertFalse(recording.ready)
                self.assertFalse(recording.finish(save=True))
                self.assertFalse(self.destination.exists())
                self.assert_no_partial()

    def test_cancel_preserves_any_previous_destination(self):
        self.destination.write_bytes(b"previous file")
        recording = capture.Recording(self.destination)
        recording.append(self.audible)
        self.assertFalse(recording.finish(save=False))
        self.assertEqual(self.destination.read_bytes(), b"previous file")
        self.assert_no_partial()

    def test_failed_commit_cleans_the_partial(self):
        recording = capture.Recording(self.destination)
        recording.append(self.audible)
        with patch.object(capture.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                recording.finish(save=True)
        self.assertFalse(self.destination.exists())
        self.assert_no_partial()

    def test_windows_uses_the_loopback_subprocess(self):
        with patch.object(capture.sys, "platform", "win32"):
            program, args = capture.command()
        self.assertEqual(program, sys.executable)
        self.assertEqual(args[-1], "--wasapi")
        self.assertEqual(Path(args[-2]), Path(capture.__file__))

    def test_old_mac_and_missing_helper_have_actionable_errors(self):
        with patch.object(capture.sys, "platform", "darwin"):
            with patch.object(capture.platform, "mac_ver", return_value=("12.6", (), "")):
                with self.assertRaisesRegex(capture.CaptureError, "macOS 13"):
                    capture.command()
            with patch.object(capture.platform, "mac_ver", return_value=("13.0", (), "")):
                with patch.object(capture.Path, "is_file", return_value=False):
                    with self.assertRaisesRegex(capture.CaptureError, "Reinstall"):
                        capture.command()


if __name__ == "__main__":
    unittest.main()
