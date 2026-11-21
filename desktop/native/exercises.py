import copy
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from karaoke import export
from . import store
from .theme import button, label


def next_id(items, prefix):
    return prefix + str(1 + max((int(x["id"][1:]) for x in items), default=0))


class Exercises(QDialog):
    def __init__(self, player):
        super().__init__(player)
        self.setWindowTitle("Clips and drills")
        self.resize(650, 545)
        self.player = player
        self.doc = copy.deepcopy(player.doc)
        layout = QVBoxLayout(self)
        layout.addWidget(label("Clips and drills", 25, "head", weight=800))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        clip_tab = QWidget()
        c = QVBoxLayout(clip_tab)
        self.clips = QListWidget()
        c.addWidget(self.clips)
        c.addWidget(label("Save part of the song to sing again.", 15, muted=True))
        form = QFormLayout()
        self.clip_name = QLineEdit()
        self.first, self.last = QComboBox(), QComboBox()
        for ln in self.doc["lines"]:
            for w in ln["words"]:
                for combo in (self.first, self.last):
                    combo.addItem(f"{store.stamp(w['startMs'])}   {w['plain']}", w["id"])
        self.first.currentIndexChanged.connect(
            lambda i: self.last.setCurrentIndex(max(i, self.last.currentIndex()))
        )
        self.first.setCurrentIndex(sum(len(l["words"]) for l in self.doc["lines"][: player.line_index]))
        self.last.setCurrentIndex(
            self.first.currentIndex() + len(self.doc["lines"][player.line_index]["words"]) - 1
        )
        form.addRow("Clip name", self.clip_name)
        form.addRow("First word", self.first)
        form.addRow("Last word", self.last)
        c.addLayout(form)
        bar = QHBoxLayout()
        bar.addWidget(button("Save clip", self.add_clip))
        bar.addWidget(button("Play selected clip", self.play_clip))
        c.addLayout(bar)
        self.tabs.addTab(clip_tab, "Clips")
        drill_tab = QWidget()
        d = QVBoxLayout(drill_tab)
        self.drills = QListWidget()
        d.addWidget(self.drills)
        d.addWidget(button("Play selected drill", self.play_drill))
        self.name = QLineEdit()
        self.name.setPlaceholderText("New drill name")
        d.addWidget(self.name)
        row = QHBoxLayout()
        self.clip = QComboBox()
        self.reps = QSpinBox()
        self.reps.setRange(1, 10)
        self.reps.setPrefix("Repeats  ")
        self.speed = QComboBox()
        for val in (0.5, 0.75, 1.0):
            self.speed.addItem(f"{val:g}×", val)
        self.speed.setCurrentIndex(2)
        self.track = QComboBox()
        for key, title in [("original", "Original"), ("instrumental", "Backing"), ("vocals", "Voice")]:
            if key in self.doc["song"]["audio"]:
                self.track.addItem(title, key)
        for w in (self.clip, self.reps, self.speed, self.track):
            row.addWidget(w)
        d.addLayout(row)
        self.gap = QCheckBox("Leave a silent turn for me to sing")
        d.addWidget(self.gap)
        self.steps = []
        self.step_list = QListWidget()
        d.addWidget(self.step_list)
        actions = QHBoxLayout()
        for title, fn in [
            ("Add clip step", self.add_step),
            ("Add teaching card", self.card),
            ("Undo last step", self.undo),
        ]:
            actions.addWidget(button(title, fn))
        d.addLayout(actions)
        d.addWidget(button("Save new drill", self.add_drill))
        self.tabs.addTab(drill_tab, "Drills")
        self.notice = label("", 14, muted=True)
        layout.addWidget(self.notice)
        layout.addWidget(button("Done", self.accept))
        self.reload()

    def reload(self):
        self.clips.clear()
        self.drills.clear()
        self.clip.clear()
        for c in self.doc["clips"]:
            self.clips.addItem(c["name"])
            self.clip.addItem(c["name"], c["id"])
        for d in self.doc["drills"]:
            self.drills.addItem(d["name"])
        self.clips.setCurrentRow(0)
        self.drills.setCurrentRow(0)

    def persist(self, candidate):
        try:
            store.save(self.player.folder, candidate)
        except ValueError as exc:
            self.notice.setText(str(exc))
            return False
        self.doc = candidate
        self.player.doc = candidate
        self.reload()
        return True

    def add_clip(self):
        name = self.clip_name.text().strip()
        if not name or self.last.currentIndex() < self.first.currentIndex():
            self.notice.setText("Name your clip and choose the words in singing order.")
            return
        cand = copy.deepcopy(self.doc)
        cand["clips"].append(
            dict(
                id=next_id(cand["clips"], "C"),
                name=name,
                fromWord=self.first.currentData(),
                toWord=self.last.currentData(),
                padBeforeMs=0,
                padAfterMs=0,
            )
        )
        if self.persist(cand):
            self.clips.setCurrentRow(len(cand["clips"]) - 1)
            self.notice.setText("Clip saved.")

    def add_step(self):
        if self.clip.currentIndex() < 0:
            return
        self.steps.append(
            dict(
                type="clip",
                clip=self.clip.currentData(),
                repeats=self.reps.value(),
                speed=self.speed.currentData(),
                track=self.track.currentData(),
                yourTurn=self.gap.isChecked(),
                tiers=["lyrics", "en"],
            )
        )
        self.step_list.addItem(f"{self.clip.currentText()}  ·  {self.reps.value()} repeats")

    def card(self):
        text, ok = QInputDialog.getMultiLineText(self, "Teaching card", "What should the singer read?")
        if not ok or not text.strip():
            return
        seconds, ok = QInputDialog.getInt(self, "Teaching card", "Seconds on screen", 4, 1, 120)
        if ok:
            self.steps.append(dict(type="card", text=text.strip(), durationMs=seconds * 1000))
            self.step_list.addItem(text.strip())

    def undo(self):
        if self.steps:
            self.steps.pop()
            self.step_list.takeItem(self.step_list.count() - 1)

    def add_drill(self):
        if not self.name.text().strip() or not self.steps:
            self.notice.setText("Name the drill and add at least one step.")
            return
        cand = copy.deepcopy(self.doc)
        cand["drills"].append(
            dict(id=next_id(cand["drills"], "D"), name=self.name.text().strip(), steps=list(self.steps))
        )
        if self.persist(cand):
            self.steps = []
            self.step_list.clear()
            self.drills.setCurrentRow(len(cand["drills"]) - 1)
            self.notice.setText("Drill saved.")

    def play_clip(self):
        i = self.clips.currentRow()
        if i < 0:
            return
        c = self.doc["clips"][i]
        a, b = export._clip_range(self.doc, c)
        self.accept()
        self.player.practice(
            [
                dict(
                    type="audio",
                    track=self.player.track,
                    start=a,
                    end=b,
                    speed=self.player.speed.currentData(),
                )
            ],
            c["name"],
        )

    def play_drill(self):
        i = self.drills.currentRow()
        if i >= 0:
            self.accept()
            self.player.play_drill(self.doc["drills"][i])
