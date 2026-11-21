import json
import os
import signal
import subprocess
import tempfile
import copy
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from karaoke import desktop_models, desktop_songs, importer, paths, songfile
from . import store
from .theme import AMBER, button, label


class Job(QThread):
    result = Signal(object)
    failure = Signal(str)

    def __init__(self, fn, parent):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            value = self.fn()
        except Exception as exc:
            self.failure.emit(str(exc) or "The operation could not finish.")
        else:
            self.result.emit(value)


def busy(parent, title, fn):
    dialog = QDialog(parent)
    dialog.setWindowTitle("Maagal Karaoke Studio")
    layout = QVBoxLayout(dialog)
    layout.addWidget(label(title, 19, "head"))
    progress = QProgressBar()
    progress.setRange(0, 0)
    layout.addWidget(progress)
    dialog.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
    dialog.reject = lambda: None
    outcome = []
    job = Job(fn, dialog)
    job.result.connect(lambda val: outcome.append((True, val)))
    job.failure.connect(lambda why: outcome.append((False, why)))
    job.finished.connect(dialog.accept)
    QTimer.singleShot(0, job.start)
    dialog.exec()
    job.wait()
    if not outcome or not outcome[0][0]:
        raise ValueError(outcome[0][1] if outcome else "The operation ended early.")
    return outcome[0][1]


def controls(dialog, layout, save="Save"):
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    box.button(QDialogButtonBox.StandardButton.Save).setText(save)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    layout.addWidget(box)
    return box


class AddSong(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Add a song")
        self.setMinimumWidth(520)
        self.file = None
        self.result_slug = None
        self.running = False
        self.process = None
        self.process_group = None
        self.area = None
        self.captures = tempfile.TemporaryDirectory(prefix="maagal-capture-")
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.addWidget(label("Add a song", 28, "head", weight=800))
        layout.addWidget(label("Choose or drop a recording, or record what is playing on your computer.", 16, muted=True))
        self.pick = button("Choose audio file…", self.choose)
        layout.addWidget(self.pick)
        layout.addWidget(button("Record computer audio...", self.record))
        layout.addWidget(button("Open lyrics or subtitles...", self.open_lyrics))
        self.preview = QMediaPlayer(self)
        self.preview_audio = QAudioOutput(self)
        self.preview.setAudioOutput(self.preview_audio)
        self.listen = button("Preview selection", self.preview_selection)
        self.listen.setEnabled(False)
        self.preview.playbackStateChanged.connect(
            lambda _: self.listen.setText(
                "Pause preview" if self.preview.isPlaying() else "Preview selection"
            )
        )
        self.preview.positionChanged.connect(self.preview_position)
        layout.addWidget(self.listen)
        form = QFormLayout()
        self.title = QLineEdit()
        self.artist = QLineEdit()
        self.lang = QComboBox()
        self.lang.addItem("Hebrew", "he")
        self.lang.addItem("Spanish", "es")
        form.addRow("Song title", self.title)
        form.addRow("Artist (optional)", self.artist)
        form.addRow("Language", self.lang)
        layout.addLayout(form)
        self.lyrics = QPlainTextEdit()
        self.lyrics.setAccessibleName("Song lyrics")
        self.lyrics.setPlaceholderText("Optional lyrics or subtitles. Leave empty to recognize the singing.")
        self.lyrics.setMinimumHeight(98)
        layout.addWidget(self.lyrics)
        self.english = QCheckBox("Each lyric line is followed by its English translation")
        layout.addWidget(self.english)
        ranges = QHBoxLayout()
        self.start = QDoubleSpinBox()
        self.end = QDoubleSpinBox()
        for spin in (self.start, self.end):
            spin.setRange(0, 86400)
            spin.setDecimals(2)
            spin.setSuffix(" s")
        self.end.setSpecialValueText("End of file")
        for title, w in (("Start", self.start), ("End", self.end)):
            ranges.addWidget(label(title, 14))
            ranges.addWidget(w)
        layout.addLayout(ranges)
        self.mode = QComboBox()
        self.mode.addItem("Match the words automatically", "automatic")
        self.mode.addItem("Edit timing manually", "manual")
        layout.addWidget(self.mode)
        self.setup = button("Download automatic timing tools", self.install)
        layout.addWidget(self.setup)
        self.message = label("", 14, muted=True)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.buttons = controls(self, layout, "Prepare song")
        self.poll = QTimer(self)
        self.poll.setInterval(600)
        self.poll.timeout.connect(self.refresh)
        self.mode.currentIndexChanged.connect(self.refresh)
        self.lang.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def choose(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a recording",
            "",
            "Audio and video (*.wav *.mp3 *.m4a *.flac *.ogg *.aac *.mp4 *.mov *.webm *.mkv *.aiff);;All files (*)",
        )
        if filename:
            self.select_file(Path(filename))

    def select_file(self, file):
        self.file = file
        self.pick.setText(file.name)
        self.preview.setSource(QUrl.fromLocalFile(str(file)))
        self.listen.setEnabled(True)
        self.start.setValue(0)
        self.end.setValue(0)
        if not self.title.text():
            self.title.setText(file.stem)

    def dragEnterEvent(self, event):
        if not self.running and len(event.mimeData().urls()) == 1 and event.mimeData().urls()[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not self.running:
            urls = event.mimeData().urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                self.select_file(Path(urls[0].toLocalFile()))
                event.acceptProposedAction()

    def record(self):
        from .capture import capture_recording
        from uuid import uuid4
        path = Path(self.captures.name) / (uuid4().hex + ".wav")
        if capture_recording(self, path):
            if not self.title.text():
                self.title.setText("Computer recording")
            self.select_file(path)

    def open_lyrics(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open lyrics or subtitles", "", "Lyrics and subtitles (*.txt *.srt *.vtt)")
        if filename:
            try:
                self.lyrics.setPlainText(Path(filename).read_text("utf-8-sig"))
            except (UnicodeError, OSError):
                self.message.setText("Choose a readable UTF-8 lyrics or subtitle file.")

    def preview_selection(self):
        if self.preview.isPlaying():
            self.preview.pause()
        else:
            self.preview.setPosition(round(self.start.value() * 1000))
            self.preview.play()

    def preview_position(self, position):
        if self.preview.isPlaying() and self.end.value() and position >= self.end.value() * 1000:
            self.preview.pause()

    def done(self, result):
        self.preview.stop()
        self.preview.setSource(QUrl())
        self.captures.cleanup()
        super().done(result)

    def install(self):
        desktop_models.start(self.lang.currentData())
        self.poll.start()
        self.refresh()

    def refresh(self):
        if self.process is not None:
            area = Path(self.area.name)
            code = self.process.poll()
            try:
                progress = (area / "progress").read_text("utf8")
            except FileNotFoundError:
                progress = "Preparing your recording..."
            self.message.setText(progress)
            if code is None:
                return
            if self.process_group:
                self.process_group.close()
                self.process_group = None
            self.process = None
            self.poll.stop()
            try:
                if code == 0:
                    folder = area / "song"
                    doc = songfile.load(folder)
                    problems = store.validate(doc)
                    if problems:
                        raise ValueError(problems[0])
                    for track in doc["song"]["audio"]:
                        store.track_path(folder, doc, track)
                    slug = doc["song"]["id"]
                    folder.rename(paths.SONGS / slug)
                    self.result_slug = slug
                elif progress == "Preparing your recording...":
                    self.message.setText("The processing tools could not start. Check the installation and retry.")
            except (OSError, ValueError) as exc:
                self.message.setText(str(exc))
            finally:
                self.area.cleanup()
                self.area = None
                self.running = False
                self.set_inputs_enabled(True)
            if self.result_slug:
                super().accept()
            return
        if self.running:
            state = importer.status()
            if state and state["state"] == "done":
                self.result_slug = state["slug"]
                self.poll.stop()
                self.running = False
                super().accept()
            elif state and state["state"] == "failed":
                self.running = False
                self.setEnabled(True)
                self.poll.stop()
                reason = (state.get("error") or {}).get("message")
                self.message.setText(
                    reason or "This recording could not be prepared. Choose another file or try again."
                )
            elif state:
                step = next((s["name"] for s in state["steps"] if s["state"] == "running"), "audio")
                names = {
                    "ingest": "Preparing audio",
                    "align": "Matching words",
                    "separate": "Separating voice and backing",
                    "assemble": "Saving your song",
                    "translate": "Preparing translations",
                }
                self.message.setText(names.get(step, "Preparing your song…"))
            return
        auto = self.mode.currentData() == "automatic"
        self.setup.setVisible(auto)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(True)
        if auto and desktop_models.bundled():
            self.setup.hide()
            self.message.setText("Your recording will be prepared on this computer.")
        elif auto:
            state = desktop_models.status(self.lang.currentData())
            self.message.setText(state.get("error") or state["message"])
            self.setup.setVisible(not state["automaticReady"])
            self.setup.setEnabled(state["canInstall"])
            self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(state["automaticReady"])
        else:
            self.message.setText("You’ll mark the words during playback after adding the recording.")

    def accept(self):
        if self.mode.currentData() == "automatic":
            if self.running:
                return
            if not self.file or not self.file.is_file():
                self.message.setText("Choose or record audio first.")
                return
            try:
                self.start_preparation()
            except (OSError, ValueError, RuntimeError) as exc:
                if self.area:
                    self.area.cleanup()
                    self.area = None
                self.message.setText(str(exc))
            return
        if (
            not self.file
            or not self.file.is_file()
            or not self.title.text().strip()
            or not self.lyrics.toPlainText().strip()
        ):
            self.message.setText("Choose a recording, enter its title, and add the lyrics.")
            return
        try:
            text = self.lyrics.toPlainText()
            lang = self.lang.currentData()
            bilingual = self.english.isChecked()
            problems = importer.check(text, lang, bilingual)["problems"]
            if problems:
                raise ValueError(" ".join(problems))
            source = self.file
            start, end = self.start.value(), self.end.value()
            self.preview.stop()

            def prepare():
                tmp = importer.new_upload(source.name)
                try:
                    shutil.copyfile(source, tmp)
                    data = importer.finish_upload(tmp)
                    if start or end:
                        stop = end or data["seconds"]
                        return importer.trim(data["upload"], round(start * 1000), round(stop * 1000))[
                            "upload"
                        ]
                    return data["upload"]
                except BaseException:
                    tmp.unlink(missing_ok=True)
                    raise

            upload = busy(self, "Preparing your recording…", prepare)
            importer.start(
                "",
                text,
                self.title.text(),
                self.artist.text(),
                upload=upload,
                language=lang,
                english_lines=bilingual,
                mode=self.mode.currentData(),
            )
            self.running = True
            self.setEnabled(False)
            self.poll.start()
        except Exception as exc:
            self.message.setText(str(exc))

    def set_inputs_enabled(self, enabled):
        for i in range(self.layout().count()):
            item = self.layout().itemAt(i)
            if item.widget() and item.widget() not in (self.buttons, self.message):
                item.widget().setEnabled(enabled)
        for w in (self.title, self.artist, self.lang, self.start, self.end):
            w.setEnabled(enabled)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(enabled)

    def start_preparation(self):
        lang = self.lang.currentData()
        env = os.environ.copy()
        if desktop_models.bundled():
            worker = desktop_models._base()
            env.update(desktop_models.offline_env(paths.ROOT / "models/hub"))
        else:
            worker = desktop_models.python_for(lang)
            env.update(desktop_models.worker_env(lang))
        self.preview.stop()
        title = self.title.text().strip() or self.file.stem
        request = dict(audio=str(self.file.resolve()), slug=importer._unique_slug(title), title=title,
                       artist=self.artist.text().strip(), language=lang, lyrics=self.lyrics.toPlainText(),
                       bilingual=self.english.isChecked(), start=self.start.value(), end=self.end.value())
        self.area = desktop_songs.staging_directory()
        area = Path(self.area.name)
        (area / "request.json").write_text(json.dumps(request), "utf8")
        self.process = subprocess.Popen([str(worker), "-m", "karaoke.prepare", str(area)], env=env,
                                        start_new_session=os.name != "nt",
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            if os.name == "nt":
                from .process_group import ProcessGroup
                self.process_group = ProcessGroup(self.process)
            (area / "ready").touch()
        except OSError:
            self.process.kill()
            self.process.wait()
            self.process = None
            if self.process_group:
                self.process_group.close()
                self.process_group = None
            raise
        self.running = True
        self.set_inputs_enabled(False)
        self.poll.start()

    def reject(self):
        if self.process is not None:
            if self.process.poll() is None:
                if os.name == "nt":
                    if self.process_group:
                        self.process_group.close()
                        self.process_group = None
                    else:
                        self.process.kill()
                else:
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.message.setText("Still stopping the recording tools. Try cancelling again.")
                    return
            self.process = None
            self.poll.stop()
            self.area.cleanup()
            self.area = None
            self.running = False
        if not self.running:
            super().reject()


class Timing(QDialog):
    def __init__(self, parent, folder, doc):
        super().__init__(parent)
        self.setWindowTitle("Lyrics and timing")
        self.resize(835, 580)
        self.folder = folder
        self.doc = copy.deepcopy(doc)
        self.words = [w for ln in self.doc["lines"] for w in ln["words"]]
        self.original = [(w["startMs"], w["endMs"]) for w in self.words]
        self.review_rows = [i for i, word in enumerate(self.words) if "low-confidence" in word["flags"]]
        self.taps = []
        self.audio = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.setSource(QUrl.fromLocalFile(str(store.track_path(folder, doc, "original"))))
        layout = QVBoxLayout(self)
        layout.addWidget(label("Lyrics and timing", 26, "head", weight=800))
        layout.addWidget(
            label(
                "Press Play, then tap Mark word as each word begins. Mark the end after the last word.",
                15,
                muted=True,
            )
        )
        self.table = QTableWidget(len(self.words), 4)
        self.table.setHorizontalHeaderLabels(["Line", "Word", "Starts (seconds)", "Ends (seconds)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for i, w in enumerate(self.words):
            line_id = w["id"].split("W")[0]
            item = QTableWidgetItem(line_id)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 0, item)
            for j, t in enumerate([w["plain"], f"{w['startMs'] / 1000:.3f}", f"{w['endMs'] / 1000:.3f}"], 1):
                self.table.setItem(i, j, QTableWidgetItem(t))
            if "low-confidence" in w["flags"]:
                word_item = self.table.item(i, 1)
                word_item.setForeground(QColor(AMBER))
                word_item.setToolTip("Check this word’s timing against the recording.")
                word_item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, "Timing needs review")
        layout.addWidget(self.table)
        bar = QHBoxLayout()
        self.play = button("Play", self.toggle)
        self.player.playbackStateChanged.connect(
            lambda _: self.play.setText("Pause" if self.player.isPlaying() else "Play")
        )
        self.mark = button("Mark word", self.tap)
        self.undo = button("Undo last tap", self.undo_tap)
        for b in (self.play, self.mark, self.undo):
            bar.addWidget(b)
        bar.addWidget(button("From selected word", self.from_selected))
        if self.review_rows:
            bar.addWidget(button("Next word to check", self.next_review))
        layout.addLayout(bar)
        self.tip = label(
            "Choose Next word to check to review estimated timings." if self.review_rows else "",
            15,
            muted=True,
        )
        layout.addWidget(self.tip)
        controls(self, layout, "Save timing")

    def next_review(self):
        row = next((i for i in self.review_rows if i > self.table.currentRow()), self.review_rows[0])
        self.table.selectRow(row)
        self.table.scrollToItem(self.table.item(row, 1))

    def toggle(self):
        if self.player.isPlaying():
            self.player.pause()
        else:
            self.player.play()

    def from_selected(self):
        index = max(0, self.table.currentRow())
        try:
            pos = round(float(self.table.item(index, 2).text()) * 1000)
        except ValueError:
            return
        self.player.setPosition(pos)
        self.player.play()

    def tap(self):
        n = len(self.taps)
        if n > len(self.words):
            return
        at = self.player.position()
        if n and at - self.taps[-1] < 40:
            self.tip.setText("Each word needs at least a short moment of sound.")
            return
        self.taps.append(at)
        if n == len(self.words):
            self.player.pause()
        self.update_taps()

    def undo_tap(self):
        if self.taps:
            pos = self.taps.pop()
            self.player.setPosition(max(0, pos - 500))
            self.update_taps()

    def update_taps(self):
        for i, (a, b) in enumerate(self.original):
            if i < len(self.taps):
                a = self.taps[i]
            if i + 1 < len(self.taps):
                b = self.taps[i + 1]
            self.table.item(i, 2).setText(f"{a / 1000:.3f}")
            self.table.item(i, 3).setText(f"{b / 1000:.3f}")
        n = len(self.taps)
        self.table.selectRow(min(n, len(self.words) - 1))
        self.mark.setEnabled(n <= len(self.words))
        self.mark.setText("Mark the end" if n == len(self.words) else "Mark word")
        self.tip.setText(
            "Timing complete. Choose Save timing."
            if n > len(self.words)
            else f"Next word: {self.words[min(n, len(self.words) - 1)]['plain']}"
        )

    def accept(self):
        try:
            if self.taps and len(self.taps) <= len(self.words):
                raise ValueError("Finish marking the words and their end before saving.")
            for i, w in enumerate(self.words):
                a, b = (round(float(self.table.item(i, j).text()) * 1000) for j in (2, 3))
                if self.taps or (a, b) != self.original[i]:
                    w["flags"] = [f for f in w["flags"] if f not in ("low-confidence", "timing-adjusted")]
                w.update(plain=self.table.item(i, 1).text().strip(), startMs=a, endMs=b)
            store.save(self.folder, self.doc)
        except (ValueError, OverflowError) as exc:
            self.tip.setText(str(exc))
            return
        super().accept()

    def done(self, result):
        self.player.stop()
        self.player.setSource(QUrl())
        super().done(result)


class LineText(QDialog):
    def __init__(self, parent, folder, doc):
        super().__init__(parent)
        self.setWindowTitle("Pronunciation and English")
        self.resize(810, 450)
        self.folder = folder
        self.doc = copy.deepcopy(doc)
        box = QVBoxLayout(self)
        self.table = QTableWidget(len(doc["lines"]), 3)
        self.table.setHorizontalHeaderLabels(["Lyric", "Pronunciation", "English"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for i, ln in enumerate(doc["lines"]):
            words = QTableWidgetItem(" ".join(w["plain"] for w in ln["words"]))
            words.setFlags(words.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 0, words)
            for j, text in enumerate((ln.get("pronunciation", ""), ln["english"]), 1):
                self.table.setItem(i, j, QTableWidgetItem(text))
        box.addWidget(self.table)
        controls(self, box)

    def accept(self):
        for i, ln in enumerate(self.doc["lines"]):
            ln["english"] = self.table.item(i, 2).text().strip()
            val = self.table.item(i, 1).text().strip()
            if val:
                ln["pronunciation"] = val
            else:
                ln.pop("pronunciation", None)
        try:
            store.save(self.folder, self.doc)
        except ValueError as exc:
            QMessageBox.warning(self, "Save lyrics", str(exc))
            return
        super().accept()
