"""System loopback subprocess and atomic PCM WAV writing for native import."""

import math
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
import wave
from array import array

RATE = 48_000
CHANNELS = 2
FRAME_BYTES = CHANNELS * 2
MIN_FRAMES = RATE // 4
# A standard WAV uses 32-bit chunk sizes.
MAX_BYTES = (2**32 - 45) // FRAME_BYTES * FRAME_BYTES
SILENCE_PEAK = 10 ** (-60 / 20)


class CaptureError(RuntimeError):
    pass


class Recording:
    def __init__(self, destination: Path):
        self.destination = destination
        self.frames = 0
        self.audible = False
        self.pending = b""
        self._temporary = tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=".recording-", suffix=".part", delete=False,
        )
        self._path = Path(self._temporary.name)
        self._wav = wave.open(self._temporary, "wb")
        self._wav.setparams((CHANNELS, 2, RATE, 0, "NONE", "not compressed"))

    @property
    def ready(self):
        return self.audible and self.frames >= MIN_FRAMES

    def append(self, data):
        data = self.pending + data
        complete = len(data) // FRAME_BYTES * FRAME_BYTES
        self.pending = data[complete:]
        if not complete:
            return 0
        samples = array("h")
        samples.frombytes(data[:complete])
        if sys.byteorder != "little":
            samples.byteswap()
        peak = max(abs(min(samples)), abs(max(samples))) / 32768
        frames = self.frames + complete // FRAME_BYTES
        if frames * FRAME_BYTES > MAX_BYTES:
            raise CaptureError("This recording reached the size limit for a WAV file.")
        self._wav.writeframesraw(data[:complete])
        self.frames = frames
        self.audible |= peak >= SILENCE_PEAK
        # A logarithmic meter makes quieter playback visible without changing the recording.
        return round(max(0, 100 + 100 * math.log10(max(peak, SILENCE_PEAK)) / 3))

    def finish(self, save):
        try:
            try:
                self._wav.close()
            finally:
                self._temporary.close()
            if save and self.ready:
                os.replace(self._path, self.destination)
                return True
            return False
        finally:
            self._path.unlink(missing_ok=True)


def command():
    if sys.platform == "win32":
        return sys.executable, ["-B", str(Path(__file__).resolve()), "--wasapi"]
    if sys.platform == "darwin":
        version = platform.mac_ver()[0]
        if not version or int(version.split(".", 1)[0]) < 13:
            raise CaptureError("Recording computer audio requires macOS 13 or later. You can choose an audio file.")
        helper = Path(__file__).resolve().with_name("SystemAudioCapture")
        if not helper.is_file():
            raise CaptureError("The macOS audio recorder is missing. Reinstall the desktop app or choose an audio file.")
        return str(helper), []
    raise CaptureError("Recording computer audio is available on Windows and macOS. You can choose an audio file.")


def _message(kind, text):
    text = " ".join(text.split())
    sys.stderr.buffer.write(f"{kind}\t{text}\n".encode("utf-8"))
    sys.stderr.buffer.flush()


def _wasapi():
    # A separate process keeps COM on its initialization thread and can be
    # stopped even when a disconnected output device blocks the WASAPI call.
    try:
        import numpy as np
        import soundcard
    except ImportError as exc:
        raise CaptureError("The Windows audio recorder is missing. Reinstall the desktop app or choose an audio file.") from exc
    try:
        speaker = soundcard.default_speaker()
        if speaker is None:
            raise CaptureError("Windows has no default playback device.")
        loopback = next(candidate for candidate in soundcard.all_microphones(include_loopback=True)
                        if candidate.isloopback and candidate.id == speaker.id)
        channel_map = [0, 1] if loopback.channels >= CHANNELS else [0]
        with loopback.recorder(samplerate=RATE, channels=channel_map) as recorder:
            _message("DEVICE", speaker.name)
            next_device_check = time.monotonic() + 1
            while True:
                if time.monotonic() >= next_device_check:
                    current = soundcard.default_speaker()
                    if not current or current.id != speaker.id:
                        raise CaptureError("Your playback device changed. Start a new recording on the current speakers or headphones.")
                    next_device_check = time.monotonic() + 1
                samples = recorder.record(numframes=RATE // 20)
                if samples.ndim == 1:
                    samples = samples.reshape(-1, 1)
                if samples.shape[1] == 1:
                    samples = np.repeat(samples, CHANNELS, axis=1)
                pcm = (np.clip(np.nan_to_num(samples), -1, 1) * 32767).astype("<i2")
                sys.stdout.buffer.write(pcm.tobytes())
                sys.stdout.buffer.flush()
    except CaptureError:
        raise
    except (RuntimeError, OSError, StopIteration) as exc:
        raise CaptureError("Windows could not record from the default playback device. "
                           "Check Sound settings, reconnect your speakers or headphones, then try again.") from exc


if __name__ == "__main__":
    if sys.argv[1:] != ["--wasapi"] or sys.platform != "win32":
        sys.exit(2)
    try:
        _wasapi()
    except CaptureError as exc:
        _message("ERROR", str(exc))
        sys.exit(1)
