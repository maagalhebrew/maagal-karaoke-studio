"""Record the computer's playback and hand the WAV to the existing import flow."""

from pathlib import Path
import time

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QProgressBar, QVBoxLayout

from .capture_audio import CaptureError, RATE, Recording, command
from .theme import button, label


class CaptureDialog(QDialog):
    def __init__(self, parent, destination):
        super().__init__(parent)
        self.destination = destination
        self.recording = None
        self.stop_choice = None
        self.failure = ""
        self.device = ""
        self.diagnostics = b""
        self.last_sound = 0.0

        self.setWindowTitle("Record computer audio")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.addWidget(label("Record computer audio", 24, "head", weight=800))
        instructions = label("Play the audio on this computer while recording. "
                             "Other playing apps may be included.", 15, muted=True)
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self.status = label("Ready to record.", 15)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.clock = label("0:00", 15)
        layout.addWidget(self.clock)
        self.meter = QProgressBar()
        self.meter.setAccessibleName("Playback audio level")
        self.meter.setTextVisible(False)
        self.meter.setRange(0, 100)
        self.meter.setValue(0)
        layout.addWidget(self.meter)

        controls = QHBoxLayout()
        self.start = button("Start recording", self._begin)
        self.stop = button("Stop and use recording", lambda: self._stop(True))
        self.stop.setEnabled(False)
        self.cancel = button("Cancel", self.reject)
        controls.addWidget(self.start)
        controls.addWidget(self.stop)
        controls.addStretch()
        controls.addWidget(self.cancel)
        layout.addLayout(controls)

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read_audio)
        self.process.readyReadStandardError.connect(self._read_diagnostics)
        self.process.errorOccurred.connect(self._process_error)
        self.process.finished.connect(self._finished)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._refresh)

    def _begin(self):
        try:
            executable, args = command()
            self.recording = Recording(self.destination)
        except (CaptureError, OSError) as exc:
            self.status.setText(str(exc))
            return

        self.stop_choice = None
        self.failure = ""
        self.device = ""
        self.diagnostics = b""
        self.last_sound = 0.0
        self.clock.setText("0:00")
        self.start.setEnabled(False)
        self.status.setText("Opening system audio. Check for a permission prompt.")
        self.timer.start()
        self.process.start(executable, args)

    def _read_audio(self):
        chunk = bytes(self.process.readAllStandardOutput())
        if self.recording is None or self.stop_choice is False or self.failure or not chunk:
            return
        try:
            level = self.recording.append(chunk)
        except (CaptureError, OSError) as exc:
            self.failure = str(exc)
            self.process.kill()
            return
        self.meter.setValue(level)
        if level:
            self.last_sound = time.monotonic()
        self._refresh()

    def _read_diagnostics(self):
        self.diagnostics += bytes(self.process.readAllStandardError())
        while b"\n" in self.diagnostics:
            line, self.diagnostics = self.diagnostics.split(b"\n", 1)
            kind, _, message = line.decode("utf-8", errors="replace").partition("\t")
            if kind == "DEVICE":
                self.device = message
            elif kind == "ERROR":
                self.failure = message
        self._refresh()

    def _refresh(self):
        if self.recording is None or self.stop_choice is not None or self.failure:
            return
        seconds = self.recording.frames // RATE
        self.clock.setText(f"{seconds // 60}:{seconds % 60:02d}")
        self.stop.setEnabled(self.recording.ready)
        if self.device:
            if time.monotonic() - self.last_sound >= 2:
                self.meter.setValue(0)
                self.status.setText(f"{self.device}. No audio detected. Check that playback is active on this output.")
            else:
                self.status.setText(f"Recording from {self.device}.")

    def _stop(self, save):
        if self.stop_choice is not None:
            return
        if self.recording is None:
            if not save:
                super().reject()
            return
        if save and not self.recording.ready:
            return
        self.stop_choice = save
        self.stop.setEnabled(False)
        self.cancel.setEnabled(False)
        self.status.setText("Finishing recording…" if save else "Discarding recording…")
        self.process.kill()

    def reject(self):
        self._stop(False)

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.failure = "The system audio recorder could not start. Reinstall the desktop app or choose an audio file."
            self._finished()

    def _finished(self, *_):
        self.timer.stop()
        if self.recording is None:
            return
        self._read_audio()
        self._read_diagnostics()
        save = self.stop_choice is True and not self.failure
        recording, self.recording = self.recording, None
        try:
            saved = recording.finish(save)
        except OSError:
            self.failure = "The recording could not be saved. Check the available storage and try again."
            saved = False
        if self.stop_choice is False:
            super().reject()
        elif saved:
            super().accept()
        else:
            self.stop_choice = None
            self.meter.setValue(0)
            self.stop.setEnabled(False)
            self.start.setEnabled(True)
            self.cancel.setEnabled(True)
            self.status.setText(self.failure or "System audio stopped. Check your playback device and try again.")

    def cleanup(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1500)
        if self.recording is not None:
            self.recording.finish(False)


def capture_recording(parent, destination: Path) -> bool:
    """Return true after Stop finalizes a usable WAV, or false when cancelled."""
    dialog = CaptureDialog(parent, destination)
    try:
        return dialog.exec() == QDialog.DialogCode.Accepted
    finally:
        dialog.cleanup()
