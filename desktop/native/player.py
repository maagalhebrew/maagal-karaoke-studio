import bisect
from html import escape
import time

from PySide6.QtCore import Qt, QTimer, QUrl, QSignalBlocker
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from karaoke import export, library, subtitles
from . import store
from .theme import AMBER, NAVY, button, label, picture, rule
from .icons import icon


class Player(QWidget):
    def __init__(self, window, row):
        super().__init__()
        self.setObjectName("page")
        self.window = window
        self.folder, self.doc, self.key = row
        self.lines = self.doc["lines"]
        self.starts = [line["words"][0]["startMs"] for line in self.lines]
        self.duration = self.doc["song"]["durationMs"]
        self.track = None
        self.pending = None
        self.line_index = 0
        self.repeat_index = None
        self.last_draw = None
        self.sequence = []
        self.segment = None
        self.hold_left = 0
        self.hold_running = False
        self.clock = time.monotonic()
        self.listened = 0.0
        self.loops = {}
        self.settings = window.settings
        self.media = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.media.setAudioOutput(self.audio)
        self.build()
        self.media.mediaStatusChanged.connect(self.loaded)
        self.media.playbackStateChanged.connect(self.state_changed)
        self.media.errorOccurred.connect(self.failed)
        self.tick = QTimer(self)
        self.tick.setInterval(42)
        self.tick.timeout.connect(self.update_time)
        self.tick.start()
        self.set_track("original", 0, True)
        self.display(0)

    def build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(44, 14, 44, 20)
        root.setSpacing(13)
        nav = QHBoxLayout()
        nav.addWidget(button("Song library", self.window.show_library, "quiet", icon_name="back"))
        nav.addStretch()
        self.tool = button("Song tools")
        self.tool.setMenu(self.window.tools_menu(self))
        nav.addWidget(self.tool)
        text = button("Text options")
        menu = QMenu(text)
        self.text_checks = {}
        for key, title in (
            ("nikud", "Hebrew vowel points"),
            ("pron", "Pronunciation"),
            ("english", "English translation"),
        ):
            item = menu.addAction(title)
            item.setCheckable(True)
            item.setChecked(self.settings.value(key, True, type=bool))
            item.toggled.connect(lambda val, k=key: self.option(k, val))
            self.text_checks[key] = item
        text.setMenu(menu)
        nav.addWidget(text)
        root.addLayout(nav)
        root.addWidget(rule())
        info = QHBoxLayout()
        if self.key:
            data = store.entries[self.key]
            info.addWidget(picture(data[3], 72, 66, True, data[4]))
        name = QVBoxLayout()
        name.setSpacing(0)
        name.addWidget(label(self.doc["song"]["title"], 31, "head", weight=800))
        name.addWidget(
            label(store.entries[self.key][2] if self.key else self.doc["song"]["artist"], 16, muted=True)
        )
        info.addLayout(name, 1)
        self.group = QButtonGroup(self)
        self.tracks = {}
        for track, title in (
            ("original", "Guide vocal" if self.key else "Original"),
            ("instrumental", "Backing only"),
        ):
            b = button(title, lambda t=track: self.switch_track(t))
            b.setCheckable(True)
            b.setMinimumWidth(129)
            b.setEnabled(track in self.doc["song"]["audio"])
            if not b.isEnabled():
                b.setToolTip("This song has one recorded track.")
            self.group.addButton(b)
            info.addWidget(b)
            self.tracks[track] = b
        root.addLayout(info)
        stage = QFrame()
        stage.setObjectName("stage")
        lay = QVBoxLayout(stage)
        lay.setContentsMargins(27, 14, 27, 10)
        lay.setSpacing(7)
        lay.addStretch(2)
        self.lyric = QLabel()
        self.lyric.setTextFormat(Qt.TextFormat.RichText)
        self.lyric.setWordWrap(True)
        self.lyric.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lyric.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lyric.setAccessibleName("Current lyric")
        lay.addWidget(self.lyric)
        self.pron = label("", 24, weight=650)
        self.translation = label("", 19, muted=True)
        for l in (self.pron, self.translation):
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setWordWrap(True)
            lay.addWidget(l)
        lay.addStretch(2)
        lay.addWidget(rule())
        n = QHBoxLayout()
        n.addWidget(label("Next line", 14, muted=True))
        self.upcoming = label("", 23, "he", True)
        self.upcoming.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.upcoming.setWordWrap(True)
        n.addWidget(self.upcoming, 1)
        n.addSpacing(67)
        lay.addLayout(n)
        root.addWidget(stage, 1)
        times = QHBoxLayout()
        self.pos = label("0:00", 15)
        times.addWidget(self.pos)
        times.addStretch()
        self.notice = label("", 15, muted=True)
        times.addWidget(self.notice)
        self.first_lyric = button(
            "Skip to singing",
            lambda: self.seek_to(self.starts[0]),
            "quiet",
            "Skip the instrumental introduction",
        )
        self.first_lyric.setMinimumHeight(28)
        times.addWidget(self.first_lyric)
        times.addStretch()
        times.addWidget(label(store.stamp(self.duration), 15, muted=True))
        root.addLayout(times)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, self.duration)
        self.seek.setSingleStep(1000)
        self.seek.setPageStep(5000)
        self.seek.setAccessibleName("Song position")
        self.seek.setTracking(False)
        self.seek.valueChanged.connect(self.seek_to)
        root.addWidget(self.seek)
        controls = QHBoxLayout()
        self.repeat = button("Repeat line", self.toggle_repeat, icon_name="repeat")
        self.repeat.setCheckable(True)
        controls.addWidget(self.repeat)
        self.speed = QComboBox()
        self.speed.setAccessibleName("Playback speed")
        for value in (0.5, 0.65, 0.75, 0.85, 1.0, 1.15, 1.25):
            self.speed.addItem(f"Speed  {value:g}×", value)
        self.speed.setCurrentIndex(max(0, self.speed.findData(self.settings.value("speed", 1.0, type=float))))
        self.speed.currentIndexChanged.connect(self.speed_changed)
        self.media.setPlaybackRate(self.speed.currentData())
        controls.addWidget(self.speed)
        controls.addStretch(1)
        self.prev = button("", lambda: self.skip(-1), "step", "Previous line", "previous")
        self.play = button("", self.toggle, "transport", "Pause", "pause")
        self.play.setFixedSize(54, 54)
        self.next = button("", lambda: self.skip(1), "step", "Next line", "next")
        for step in (self.prev, self.next):
            step.setFixedSize(43, 43)
        for key, btn, title in (
            ("prev", self.prev, "Previous line"),
            ("play", self.play, "Pause"),
            ("next", self.next, "Next line"),
        ):
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)
            tag = label(title, 13, muted=True)
            tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if key == "play":
                self.play_label = tag
            col.addWidget(tag)
            controls.addLayout(col)
        controls.addStretch(1)
        controls.addWidget(label("Volume", 14, muted=True))
        volume = QSlider(Qt.Orientation.Horizontal)
        volume.setAccessibleName("Volume")
        volume.setRange(0, 100)
        volume.setMaximumWidth(100)
        volume.setValue(self.settings.value("volume", 78, type=int))
        self.audio.setVolume(volume.value() / 100)
        volume.valueChanged.connect(
            lambda v: (self.audio.setVolume(v / 100), self.settings.setValue("volume", v))
        )
        controls.addWidget(volume)
        root.addLayout(controls)

    def option(self, key, value):
        self.settings.setValue(key, value)
        self.last_draw = None
        self.display(self.media.position())

    def speed_changed(self):
        self.media.setPlaybackRate(self.speed.currentData())
        self.settings.setValue("speed", self.speed.currentData())

    def set_track(self, track, at, playing):
        source = QUrl.fromLocalFile(str(store.track_path(self.folder, self.doc, track)))
        self.track = track
        for name, b in self.tracks.items():
            b.setChecked(name == track)
            b.setIcon(icon("check" if name == track else "music"))
        if self.media.source() == source and self.pending is None:
            self.media.setPosition(at)
            self.media.play() if playing else self.media.pause()
            return
        self.pending = (source, at, playing)
        self.media.setSource(source)

    def loaded(self, status):
        if self.pending and status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            source, at, playing = self.pending
            if self.media.source() != source:
                return
            self.pending = None
            self.media.setPosition(at)
            if playing:
                self.media.play()
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.segment and self.segment["type"] == "audio":
                ended = self.segment
                QTimer.singleShot(0, lambda: self.advance() if self.segment is ended else None)
            elif self.repeat_index is not None:
                QTimer.singleShot(0, self.replay_line)

    def failed(self, err, message):
        self.pending = None
        self.segment = None
        self.sequence = []
        self.notice.setText(
            "The recording could not play. Open Song tools to check the song or restore a saved copy."
        )
        self.notice.setToolTip(message)

    def playing(self):
        return self.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def state_changed(self, *_):
        playing = self.playing() or bool(
            self.segment and self.segment["type"] != "audio" and self.hold_running
        )
        self.play.setIcon(icon("pause" if playing else "play", NAVY))
        title = "Pause" if playing else "Play"
        self.play.setAccessibleName(title)
        self.play_label.setText(title)
        self.play.setToolTip(title + " (Space)")

    def display(self, at):
        self.first_lyric.setVisible(self.starts[0] - at > 3500 and not self.segment)
        i = max(0, bisect.bisect_right(self.starts, at) - 1)
        self.line_index = i
        line = self.lines[i]
        active = next((j for j, w in enumerate(line["words"]) if w["startMs"] <= at < w["endMs"]), -1)
        uncertain = any("low-confidence" in word["flags"] or "timing-adjusted" in word["flags"] for word in line["words"])
        if uncertain:
            active = -2 if line["words"][0]["startMs"] <= at < line["words"][-1]["endMs"] else -1
        pixel = max(30, min(72, round(self.width() / 18)))
        key = (i, active, pixel)
        if key == self.last_draw:
            return
        self.last_draw = key
        marked = self.text_checks["nikud"].isChecked()
        parts = []
        for j, w in enumerate(line["words"]):
            text = escape(subtitles.word_text(w, marked))
            parts.append(
                f'<span style="color:{AMBER};text-decoration:underline">{text}</span>'
                if j == active or active == -2
                else text
            )
        rtl = self.doc["song"]["language"] == "he"
        body = " ".join(parts)
        self.lyric.setText(
            f'<p align="center" dir="{"rtl" if rtl else "ltr"}" style="margin:3px;font-family:{"Rubik" if rtl else "Nunito"};font-size:{pixel}px;font-weight:500">{body}</p>'
        )
        self.lyric.setAccessibleDescription(" ".join(subtitles.word_text(w, marked) for w in line["words"]))
        self.pron.setText(line.get("pronunciation", ""))
        self.pron.setVisible(bool(self.pron.text()) and self.text_checks["pron"].isChecked())
        self.translation.setText(line["english"])
        tiers = self.segment.get("tiers", ["lyrics", "en"]) if self.segment else ["lyrics", "en"]
        self.lyric.setVisible("lyrics" in tiers)
        self.translation.setVisible(
            bool(line["english"]) and self.text_checks["english"].isChecked() and "en" in tiers
        )
        upcoming = self.lines[i + 1]["words"] if i + 1 < len(self.lines) else []
        self.upcoming.setText(" ".join(subtitles.word_text(w, marked) for w in upcoming))

    def update_time(self):
        now = time.monotonic()
        elapsed = now - self.clock
        self.clock = now
        if self.playing():
            self.listened += min(1, elapsed)
        if self.segment and self.segment["type"] != "audio":
            if self.hold_running:
                self.hold_left -= elapsed * 1000
                if self.hold_left <= 0:
                    self.advance()
            return
        at = self.media.position()
        if self.segment and self.pending is None and self.playing() and at >= self.segment["end"]:
            self.advance()
            return
        if (
            self.repeat_index is not None
            and self.playing()
            and at >= self.lines[self.repeat_index]["words"][-1]["endMs"]
        ):
            self.replay_line()
            return
        if not self.seek.isSliderDown():
            with QSignalBlocker(self.seek):
                self.seek.setValue(at)
        self.pos.setText(store.stamp(at))
        self.display(at)
        if self.listened >= 30:
            self.flush()

    def toggle(self):
        if self.segment and self.segment["type"] != "audio":
            self.hold_running = not self.hold_running
            self.state_changed()
        elif self.pending:
            url, at, was = self.pending
            self.pending = (url, at, not was)
        elif self.playing():
            self.media.pause()
        else:
            if self.media.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
                self.media.setPosition(0)
            self.media.play()

    def cancel_sequence(self):
        if self.segment or self.sequence:
            self.segment = None
            self.sequence = []
            self.hold_running = False
            self.notice.clear()
            self.media.setPlaybackRate(self.speed.currentData())
            self.lyric.show()
            self.last_draw = None

    def seek_to(self, at):
        self.cancel_sequence()
        self.repeat_index = None
        self.repeat.setChecked(False)
        if self.pending:
            source, unused, play = self.pending
            self.pending = (source, at, play)
        else:
            self.media.setPosition(at)
        self.display(at)

    def skip(self, offset):
        i = max(0, min(len(self.lines) - 1, self.line_index + offset))
        self.seek_to(self.starts[i])

    def toggle_repeat(self):
        self.cancel_sequence()
        self.repeat_index = self.line_index if self.repeat.isChecked() else None
        if self.repeat_index is not None:
            self.media.setPosition(self.starts[self.repeat_index])
            self.media.play()

    def replay_line(self):
        if self.repeat_index is None:
            return
        lid = self.lines[self.repeat_index]["id"]
        self.loops[lid] = self.loops.get(lid, 0) + 1
        self.media.setPosition(self.starts[self.repeat_index])
        self.media.play()

    def switch_track(self, track):
        at = self.pending[1] if self.pending else self.media.position()
        play = self.pending[2] if self.pending else self.playing()
        self.cancel_sequence()
        self.set_track(track, at, play)

    def practice(self, steps, title):
        self.repeat_index = None
        self.repeat.setChecked(False)
        self.sequence = list(steps)
        self.notice.setText(title)
        self.advance()

    def advance(self):
        self.media.pause()
        if not self.sequence:
            self.cancel_sequence()
            self.notice.setText("Practice complete")
            self.state_changed()
            return
        self.segment = self.sequence.pop(0)
        step = self.segment
        self.last_draw = None
        if step["type"] == "audio":
            self.media.setPlaybackRate(step["speed"])
            self.set_track(step["track"], step["start"], True)
            self.display(step["start"])
        else:
            self.hold_left = step["ms"]
            self.hold_running = True
            self.clock = time.monotonic()
            if step["type"] == "card":
                self.lyric.show()
                self.lyric.setText(
                    '<p align="center" style="font-size:32px">' + escape(step["text"]) + "</p>"
                )
                self.pron.hide()
                self.translation.hide()
            self.notice.setText(step.get("text", "Your turn"))
            self.state_changed()

    def play_drill(self, drill):
        by_id = {x["id"]: x for x in self.doc["clips"]}
        steps = []
        for s in drill["steps"]:
            if s["type"] == "card":
                steps.append(dict(type="card", text=s["text"], ms=s["durationMs"]))
                continue
            a, b = export._clip_range(self.doc, by_id[s["clip"]])
            for _ in range(s["repeats"]):
                steps.append(
                    dict(type="audio", start=a, end=b, speed=s["speed"], track=s["track"], tiers=s["tiers"])
                )
                if s["yourTurn"]:
                    steps.append(dict(type="gap", ms=(b - a) / s["speed"]))
        if steps:
            self.practice(steps, drill["name"])

    def flush(self):
        seconds = int(self.listened)
        if seconds or self.loops:
            library.record_practice(
                self.folder.name, "practice", seconds, self.loops, {l["id"] for l in self.lines}
            )
            self.listened -= seconds
            self.loops = {}

    def close_player(self):
        self.tick.stop()
        self.cancel_sequence()
        self.pending = None
        self.media.stop()
        self.media.setSource(QUrl())
        self.flush()
