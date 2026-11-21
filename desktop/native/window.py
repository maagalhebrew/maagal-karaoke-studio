import os
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from karaoke import desktop_export, desktop_models, export, library, paths, song_archive, songfile
from . import store
from .dialogs import AddSong, LineText, Timing, busy
from .exercises import Exercises
from .player import Player
from .theme import button, label, picture, rule
from .icons import icon


def save_copy(source, destination):
    destination = Path(destination)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
        temporary = Path(output.name)
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Maagal Karaoke Studio")
        self.setAcceptDrops(True)
        self.setMinimumSize(780, 545)
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1360, screen.width() - 30), min(850, screen.height() - 55))
        self.settings = QSettings(str(paths.DATA / "native.ini"), QSettings.Format.IniFormat)
        self.player = None
        self.section = "Song library"
        store.seed()
        self.setup_shortcuts()
        self.show_library()

    def setup_shortcuts(self):
        self.playback_shortcuts = []
        for key, fn in (
            ("Space", lambda p: p.toggle()),
            ("Left", lambda p: p.skip(-1)),
            ("Right", lambda p: p.skip(1)),
            ("L", lambda p: p.repeat.click()),
            (
                "V",
                lambda p: (
                    p.switch_track("instrumental" if p.track == "original" else "original")
                    if "instrumental" in p.doc["song"]["audio"]
                    else None
                ),
            ),
            ("[", lambda p: p.speed.setCurrentIndex(max(0, p.speed.currentIndex() - 1))),
            ("]", lambda p: p.speed.setCurrentIndex(min(p.speed.count() - 1, p.speed.currentIndex() + 1))),
            ("Esc", lambda p: self.show_library()),
        ):
            action = QShortcut(QKeySequence(key), self)
            action.activated.connect(
                lambda cb=fn: (
                    cb(self.player) if self.player and not QApplication.activeModalWidget() else None
                )
            )
            self.playback_shortcuts.append(action)
        find = QShortcut(QKeySequence.StandardKey.Find, self)
        find.activated.connect(lambda: self.search.setFocus() if not self.player else None)

    def safe(self, fn):
        try:
            return fn()
        except (ValueError, OSError, RuntimeError, export.ExportError) as exc:
            QMessageBox.warning(self, "Maagal Karaoke Studio", str(exc))
            return None

    def show_library(self):
        for shortcut in self.playback_shortcuts:
            shortcut.setEnabled(False)
        if self.player:
            self.player.close_player()
            self.player = None
        page = QWidget()
        page.setObjectName("page")
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        rail = QFrame()
        self.library_page = page
        self.rail = rail
        rail.setObjectName("rail")
        rail.setFixedWidth(194 if self.width() < 1060 else 219)
        side = QVBoxLayout(rail)
        side.setContentsMargins(17, 26, 17, 15)
        side.setSpacing(8)
        side.addWidget(picture("medallion.png", 122, 122), alignment=Qt.AlignmentFlag.AlignCenter)
        side.addSpacing(5)
        for value, size, kind, muted in (
            ("Maagal Karaoke Studio", 22, "head", False),
            ("by Maagal Hebrew", 15, "body", True),
        ):
            mark = label(value, size, kind, muted, 800 if kind == "head" else 600)
            mark.setWordWrap(kind == "head")
            mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
            side.addWidget(mark)
        side.addSpacing(19)
        side.addWidget(rule())
        side.addSpacing(13)
        self.nav = QButtonGroup(page)
        for title, symbol in (("Song library", "library"), ("Favorites", "heart"), ("My songs", "folder")):
            b = button(title, lambda t=title: self.browse(t), "nav", title, symbol)
            b.setCheckable(True)
            b.setChecked(self.section == title)
            self.nav.addButton(b)
            side.addWidget(b)
        side.addStretch()
        side.addWidget(rule())
        link = button(
            "MaagalHebrew.com",
            lambda: QDesktopServices.openUrl(QUrl("https://maagalhebrew.com/")),
            "quiet",
            "Visit MaagalHebrew.com",
        )
        link.setStyleSheet("font-size:14px;padding:4px")
        side.addWidget(link)
        outer.addWidget(rail)
        main = QVBoxLayout()
        self.main_layout = main
        margin = 26 if self.width() < 1050 else 49
        main.setContentsMargins(margin, 32 if self.width() < 1080 else 44, margin, 24)
        main.setSpacing(15 if self.width() < 1080 else 19)
        head = QHBoxLayout()
        self.heading = label(self.section, 43, "head", weight=800)
        head.addWidget(self.heading, 1)
        head.addWidget(button("Add a song", self.add_song, icon_name="add"))
        main.addLayout(head)
        main.addWidget(label("Pick a song and follow the words as you sing.", 18, muted=True))
        main.addSpacing(10)
        main.addWidget(rule())
        bar = QHBoxLayout()
        self.sub = label("", 25, "head", weight=750)
        bar.addWidget(self.sub, 1)
        self.search = QLineEdit()
        self.search.setAccessibleName("Find a song")
        self.search.setPlaceholderText("Find a song")
        self.search.addAction(icon("search", "#B1BDC7"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(245)
        self.search.setMinimumHeight(39)
        self.search.textChanged.connect(self.fill)
        bar.addWidget(self.search)
        main.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        main.addWidget(self.scroll, 1)
        foot = QHBoxLayout()
        note = label("Included songs have a guide vocal and a backing track.", 15, muted=True)
        note.setWordWrap(True)
        foot.addWidget(note, 1)
        foot.addWidget(button("Import a saved song…", self.restore_song, "quiet"))
        main.addLayout(foot)
        outer.addLayout(main, 1)
        self.setCentralWidget(page)
        self.rows = store.list_songs()
        self.narrow = self.width() < 1080
        self.fill()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "library_page", None) is not self.centralWidget() or not hasattr(self, "narrow"):
            return
        narrow = event.size().width() < 1080
        if narrow != self.narrow:
            self.narrow = narrow
            self.rail.setFixedWidth(194 if narrow else 225)
            margin = 26 if narrow else 52
            self.main_layout.setContentsMargins(margin, 32 if narrow else 44, margin, 24)
            self.main_layout.setSpacing(15 if narrow else 19)
            self.fill()

    def browse(self, title):
        self.section = title
        self.heading.setText(title)
        self.search.clear()
        self.fill()

    def fill(self):
        _, favorites = library.labels()
        query = self.search.text().casefold().strip()
        listing = QWidget()
        box = QVBoxLayout(listing)
        box.setContentsMargins(0, 0, 4, 2)
        box.setSpacing(7)
        self.sub.setText(
            {
                "Song library": "Included songs"
                if not query and not any(not r[2] for r in self.rows)
                else "Songs",
                "My songs": "Your recordings",
                "Favorites": "Saved favorites",
            }[self.section]
        )
        chosen = []
        for row in self.rows:
            folder, doc, key = row
            title, artist = doc["song"]["title"], doc["song"]["artist"]
            meta = store.entries.get(key)
            haystack = " ".join([title, artist, meta[1] if meta else ""])
            from karaoke.hebrew import strip_niqqud

            if query and strip_niqqud(query) not in strip_niqqud(haystack.casefold()):
                continue
            if self.section == "My songs" and key:
                continue
            if self.section == "Favorites" and folder.name not in favorites:
                continue
            chosen.append(row)
        if chosen:
            group = QFrame()
            group.setObjectName("rows")
            rows = QVBoxLayout(group)
            rows.setContentsMargins(14, 4, 14, 4)
            rows.setSpacing(0)
            for i, row in enumerate(chosen):
                if i:
                    rows.addWidget(rule())
                folder, doc, key = row
                content = QWidget()
                content.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                content.customContextMenuRequested.connect(
                    lambda pos, w=content, r=row: self.row_menu(r, w.mapToGlobal(pos))
                )
                lay = QHBoxLayout(content)
                row_space = 11 if self.width() < 1080 else 15
                lay.setContentsMargins(4, row_space, 4, row_space)
                lay.setSpacing(19)
                meta = store.entries.get(key)
                if meta:
                    cover = picture(
                        meta[3],
                        94 if self.width() < 1080 else 128,
                        79 if self.width() < 1080 else 106,
                        True,
                        meta[4],
                    )
                    lay.addWidget(cover)
                titles = QVBoxLayout()
                titles.setSpacing(2)
                title = label(doc["song"]["title"], 25, "head", weight=800)
                title.setWordWrap(True)
                titles.addWidget(title)
                desc = label(meta[2] if meta else doc["song"]["artist"], 15, muted=True)
                desc.setWordWrap(True)
                titles.addWidget(desc)
                lay.addLayout(titles, 1)
                if meta:
                    ht = label(meta[1], 27, "he")
                    ht.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
                    lay.addWidget(ht)
                    lay.addSpacing(10)
                play = button(
                    "Play",
                    lambda r=row: self.open_song(r),
                    "primary" if i == 0 else None,
                    "Play " + doc["song"]["title"],
                    "play",
                )
                play.setMinimumWidth(100)
                lay.addWidget(play)
                rows.addWidget(content)
            box.addWidget(group)
        else:
            text = (
                "No matching songs."
                if query
                else "Choose Add a song to bring in your recording."
                if self.section == "My songs"
                else "Open a song and choose Song tools → Add to favorites."
                if self.section == "Favorites"
                else "Choose Add a song to get started."
            )
            box.addWidget(label(text, 17, muted=True))
        box.addStretch()
        self.scroll.setWidget(listing)

    def row_menu(self, row, position):
        menu = QMenu(self)
        menu.addAction("Play", lambda: self.open_song(row))
        fav = row[0].name in library.labels()[1]
        menu.addAction(
            "Remove from favorites" if fav else "Add to favorites",
            lambda: self.set_favorite(row[0].name, not fav),
        )
        menu.exec(position)

    def open_song(self, row):
        def open_it():
            store.track_path(row[0], row[1], "original")
            if self.player:
                self.player.close_player()
            self.player = Player(self, row)
            self.setCentralWidget(self.player)
            for shortcut in self.playback_shortcuts:
                shortcut.setEnabled(True)

        self.safe(open_it)

    def open_id(self, slug):
        row = next((r for r in store.list_songs() if r[0].name == slug), None)
        if row:
            self.open_song(row)

    def set_favorite(self, slug, fav):
        library.set_favorite(slug, fav)
        if self.player:
            self.player.tool.setMenu(self.tools_menu(self.player))
        else:
            self.fill()

    def tools_menu(self, p):
        menu = QMenu(self)
        fav = p.folder.name in library.labels()[1]
        menu.addAction(
            "Remove from favorites" if fav else "Add to favorites",
            lambda: self.set_favorite(p.folder.name, not fav),
        )
        menu.addAction("Lyrics and timing…", lambda: self.edit(p, Timing))
        menu.addAction("Pronunciation and English…", lambda: self.edit(p, LineText))
        menu.addAction("Clips and drills…", lambda: self.exercises(p))
        rates = menu.addMenu("Rate this line")
        for val, title in [(0, "Learning"), (1, "Getting there"), (2, "I know it"), (None, "Clear rating")]:
            rates.addAction(
                title,
                lambda checked=False, v=val: self.safe(
                    lambda: library.set_rating(
                        p.folder.name, p.lines[p.line_index]["id"], v, {l["id"] for l in p.lines}
                    )
                ),
            )
        menu.addAction("Practice history", lambda: self.history(p))
        menu.addSeparator()
        menu.addAction("Save a copy…", lambda: self.backup(p))
        share = menu.addMenu("Export")
        for kind, title in [
            ("subtitles", "Subtitle files…"),
            ("overlay", "Transparent caption video…"),
            ("lesson", "Lesson video…"),
        ]:
            share.addAction(title, lambda checked=False, k=kind: self.export_file(p, k))
        menu.addAction("Recording credits", lambda: self.credits(p))
        return menu

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()
            self.add_song(Path(urls[0].toLocalFile()))

    def add_song(self, file=None):
        dialog = AddSong(self)
        if isinstance(file, Path):
            dialog.select_file(file)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_slug:
            self.open_id(dialog.result_slug)
            if dialog.mode.currentData() == "manual" and self.player:
                self.edit(self.player, Timing)

    def edit(self, p, dialog_type):
        p.cancel_sequence()
        p.media.pause()
        dlg = dialog_type(self, p.folder, p.doc)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            p.doc = songfile.load(p.folder)
            p.lines = p.doc["lines"]
            p.starts = [ln["words"][0]["startMs"] for ln in p.lines]
            p.last_draw = None
            p.display(p.media.position())

    def exercises(self, p):
        p.cancel_sequence()
        p.media.pause()
        Exercises(p).exec()

    def history(self, p):
        p.flush()
        stats = library.practice(p.folder.name)
        seconds = stats["seconds"]
        QMessageBox.information(
            self,
            "Practice history",
            f"{p.doc['song']['title']}\n\nTime singing: {store.stamp(seconds * 1000)}\nDays practiced: {len(stats['days'])}\nLine repeats: {sum(stats['lineLoops'].values())}",
        )

    def credits(self, p):
        credit = p.doc["song"].get("recordingCredit")
        if not credit:
            QMessageBox.information(
                self,
                "Recording credits",
                p.doc["song"].get("artist") or "This recording was added to your library.",
            )
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("Recording credits")
        msg.setTextFormat(Qt.TextFormat.PlainText)
        msg.setText(
            "\n\n".join(
                [
                    credit["title"],
                    credit["artist"],
                    credit["license"],
                    credit["changes"],
                    credit["source"],
                    credit["licenseUrl"],
                ]
            )
        )
        msg.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByKeyboard | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        msg.exec()

    def backup(self, p):
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save an editable copy", p.folder.name + ".zip", "Karaoke IL song (*.zip)"
        )
        if not dest:
            return

        def copy():
            tmp = song_archive.backup(p.folder)
            try:
                save_copy(tmp, dest)
            finally:
                tmp.unlink(missing_ok=True)

        self.safe(lambda: busy(self, "Saving your song…", copy))

    def restore_song(self):
        source, _ = QFileDialog.getOpenFileName(self, "Import a saved song", "", "Karaoke IL songs (*.zip)")
        if source:
            slug = self.safe(
                lambda: busy(
                    self,
                    "Importing your saved song…",
                    lambda: song_archive.restore(Path(source), store.validate),
                )
            )
            if slug:
                self.open_id(slug)

    def export_file(self, p, kind):
        body = {}
        if kind == "lesson":
            drills = [d for d in p.doc["drills"] if any(s["type"] == "card" for s in d["steps"])]
            if not drills:
                QMessageBox.information(
                    self,
                    "Lesson video",
                    "Add a teaching card to a drill in Song tools → Clips and drills first.",
                )
                return
            names = [d["id"] + "  " + d["name"] for d in drills]
            selected, ok = QInputDialog.getItem(self, "Lesson video", "Choose a drill", names, 0, False)
            if not ok:
                return
            body["drill"] = drills[names.index(selected)]["id"]
        else:
            choices = ["Whole song", "Current line"] + [c["name"] for c in p.doc["clips"]]
            choice, ok = QInputDialog.getItem(self, "Export", "Choose the part to export", choices, 0, False)
            if not ok:
                return
            i = choices.index(choice)
            if i == 1:
                words = p.lines[p.line_index]["words"]
                a, b = words[0]["startMs"], words[-1]["endMs"]
            elif i >= 2:
                a, b = export._clip_range(p.doc, p.doc["clips"][i - 2])
            else:
                a, b = 0, p.duration
            body.update({"from": a / 1000, "to": b / 1000})
        ext = {"lesson": "mp4", "overlay": "mov", "subtitles": "zip"}[kind]
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save export", p.folder.name + "-" + kind + "." + ext, "Export (*." + ext + ")"
        )
        if not dest:
            return

        def write():
            result, _ = desktop_export.create(p.folder.name, kind, body)
            save_copy(result, dest)
            return True

        try:
            write_guard = export._check_guard
            spans = (
                export.lesson_plays(p.doc, next(d for d in p.doc["drills"] if d["id"] == body["drill"]))
                if kind == "lesson"
                else [(a, b, b - a)]
            )
            runtime = (
                export.lesson_duration_ms(p.doc, next(d for d in p.doc["drills"] if d["id"] == body["drill"]))
                if kind == "lesson"
                else None
            )
            write_guard(p.folder.name, p.doc, spans, runtime, None)
        except export.GuardError as exc:
            why, ok = QInputDialog.getMultiLineText(
                self,
                "Review export",
                "\n".join(exc.warnings) + "\n\nEnter your reason to continue this export.",
            )
            if not ok or not why.strip():
                return
            body["reason"] = why.strip()
        self.safe(lambda: busy(self, "Creating your export…", write))

    def closeEvent(self, event):
        if desktop_models.is_installing():
            QMessageBox.information(
                self,
                "Maagal Karaoke Studio",
                "The optional audio tools are still downloading. Close the app when setup finishes.",
            )
            event.ignore()
            return
        if self.player:
            self.player.close_player()
        event.accept()
