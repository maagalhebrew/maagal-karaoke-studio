"""The song library: folders (a song can be in several), favourites, each song's workflow status, and the
practice log (seconds played per song per day, and how many times each line was looped).

Folders and favourites are labels in SQLite (data/karaoke.db); song folders on disk never move, so ids, the
permission records and the export log stay valid. Memberships of a deleted song are kept: restoring its folder
from songs/_deleted brings them back. Status is derived from the song itself every time, never stored.
"""
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime

from . import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS folder_songs (
  folder_id INTEGER NOT NULL,
  song_id TEXT NOT NULL,
  PRIMARY KEY (folder_id, song_id)
);
CREATE TABLE IF NOT EXISTS song_meta (
  song_id TEXT PRIMARY KEY,
  favorite INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS practice_time (
  song_id TEXT NOT NULL,
  day TEXT NOT NULL,                -- local date, 2026-11-01
  source TEXT NOT NULL,             -- studio | practice
  seconds INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (song_id, day, source)
);
CREATE TABLE IF NOT EXISTS line_ratings (
  song_id TEXT NOT NULL,
  line_id TEXT NOT NULL,
  rating INTEGER NOT NULL,          -- 0 don't know, 1 shaky, 2 know it
  rated_on TEXT NOT NULL,           -- local date
  PRIMARY KEY (song_id, line_id)
);
CREATE TABLE IF NOT EXISTS line_loops (
  song_id TEXT NOT NULL,
  line_id TEXT NOT NULL,
  passes INTEGER NOT NULL DEFAULT 0, -- completed passes of a line loop
  last_at TEXT NOT NULL,
  PRIMARY KEY (song_id, line_id)
);
"""
NAME_MAX = 60
SOURCES = ("studio", "practice")
MAX_BATCH_S = 900  # one report covers at most this much playing (the page reports every 30 s)
MAX_BATCH_LOOPS = 500
LINE_ID = re.compile(r"^L\d+$")

# Workflow stages in order; a song's stage is the first one it hasn't finished.
STAGES = ("add-english", "make-drills", "export", "exported")


class LibraryError(ValueError):
    """Bad input (shown to the user as is)."""


@contextmanager
def connect():
    """Short-lived connection, as in permissions.py (the editor and CLI share the file)."""
    paths.DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(paths.DB)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _name(name: str) -> str:
    name = " ".join(str(name).split())
    if not name:
        raise LibraryError("A folder needs a name.")
    if len(name) > NAME_MAX:
        raise LibraryError(f"Keep folder names under {NAME_MAX} characters.")
    return name


# --- folders ------------------------------------------------------------------------
def folders(song_ids: set[str]) -> list[dict]:
    """Every folder with how many of the existing songs are in it, by name."""
    with connect() as con:
        rows = con.execute("SELECT id, name FROM folders ORDER BY name COLLATE NOCASE").fetchall()
        members = con.execute("SELECT folder_id, song_id FROM folder_songs").fetchall()
    count = {r["id"]: 0 for r in rows}
    for m in members:
        if m["song_id"] in song_ids and m["folder_id"] in count:
            count[m["folder_id"]] += 1
    return [{"id": r["id"], "name": r["name"], "count": count[r["id"]]} for r in rows]


def create_folder(name: str) -> dict:
    name = _name(name)
    try:
        with connect() as con:
            cur = con.execute("INSERT INTO folders (name, created_at) VALUES (?, ?)",
                              (name, datetime.now().isoformat(timespec="seconds")))
            return {"id": cur.lastrowid, "name": name, "count": 0}
    except sqlite3.IntegrityError:
        raise LibraryError(f'There is already a folder called "{name}".') from None


def rename_folder(folder_id: int, name: str) -> None:
    name = _name(name)
    try:
        with connect() as con:
            if con.execute("UPDATE folders SET name = ? WHERE id = ?", (name, folder_id)).rowcount == 0:
                raise LibraryError("That folder no longer exists.")
    except sqlite3.IntegrityError:
        raise LibraryError(f'There is already a folder called "{name}".') from None


def delete_folder(folder_id: int) -> None:
    """The folder goes; its songs stay in the library (and in their other folders)."""
    with connect() as con:
        con.execute("DELETE FROM folder_songs WHERE folder_id = ?", (folder_id,))
        if con.execute("DELETE FROM folders WHERE id = ?", (folder_id,)).rowcount == 0:
            raise LibraryError("That folder no longer exists.")


def set_song_folders(song_id: str, folder_ids: list[int]) -> list[int]:
    """Put a song in exactly these folders."""
    wanted = sorted({int(f) for f in folder_ids})
    with connect() as con:
        known = {r["id"] for r in con.execute("SELECT id FROM folders")}
        if missing := [f for f in wanted if f not in known]:
            raise LibraryError(f"Unknown folder id(s): {missing}")
        con.execute("DELETE FROM folder_songs WHERE song_id = ?", (song_id,))
        con.executemany("INSERT INTO folder_songs (folder_id, song_id) VALUES (?, ?)", [(f, song_id) for f in wanted])
    return wanted


def add_to_folder(folder_id: int, song_id: str) -> None:
    with connect() as con:
        if not con.execute("SELECT 1 FROM folders WHERE id = ?", (folder_id,)).fetchone():
            raise LibraryError("That folder no longer exists.")
        con.execute("INSERT OR IGNORE INTO folder_songs (folder_id, song_id) VALUES (?, ?)", (folder_id, song_id))


# --- per-song labels ----------------------------------------------------------------
def set_favorite(song_id: str, favorite: bool) -> None:
    with connect() as con:
        con.execute("INSERT INTO song_meta (song_id, favorite) VALUES (?, ?) "
                    "ON CONFLICT(song_id) DO UPDATE SET favorite = excluded.favorite", (song_id, int(bool(favorite))))


def labels() -> tuple[dict[str, list[int]], set[str]]:
    """(song id -> its folder ids, favourite song ids)."""
    with connect() as con:
        member: dict[str, list[int]] = {}
        for r in con.execute("SELECT song_id, folder_id FROM folder_songs ORDER BY folder_id"):
            member.setdefault(r["song_id"], []).append(r["folder_id"])
        favs = {r["song_id"] for r in con.execute("SELECT song_id FROM song_meta WHERE favorite = 1")}
    return member, favs


# --- derived status -------------------------------------------------------------------
def status(song: dict, flagged_words: int, exported: bool) -> dict:
    """Where the song stands in the workflow (counts only)."""
    lines = song["lines"]
    english = sum(1 for line in lines if line["english"].strip())
    drills = sum(1 for d in song["drills"] if d["steps"])
    if english < len(lines):
        stage = "add-english"
    elif not drills:
        stage = "make-drills"
    elif not exported:
        stage = "export"
    else:
        stage = "exported"
    return {"stage": stage, "englishLines": english, "lines": len(lines), "drills": drills,
            "sections": len(song["sections"]), "exported": exported}


# --- practice log -----------------------------------------------------------------------
def record_practice(song_id: str, source: str, seconds: int, loops: dict, line_ids: set[str],
                    today: date | None = None) -> None:
    """Add a batch from the page: seconds of playing, and loop passes per line (only the song's own lines)."""
    if source not in SOURCES:
        raise LibraryError(f"source must be one of: {', '.join(SOURCES)}")
    if not isinstance(seconds, int) or not 0 <= seconds <= MAX_BATCH_S:
        raise LibraryError(f"seconds must be a whole number from 0 to {MAX_BATCH_S}")
    if not isinstance(loops, dict) or not all(
            isinstance(k, str) and LINE_ID.match(k) and isinstance(v, int) and 0 < v <= MAX_BATCH_LOOPS for k, v in loops.items()):
        raise LibraryError("loops must map line ids to pass counts")
    day = (today or date.today()).isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as con:
        if seconds:
            con.execute("INSERT INTO practice_time (song_id, day, source, seconds) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(song_id, day, source) DO UPDATE SET seconds = seconds + excluded.seconds",
                        (song_id, day, source, seconds))
        con.executemany("INSERT INTO line_loops (song_id, line_id, passes, last_at) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(song_id, line_id) DO UPDATE SET passes = passes + excluded.passes, last_at = excluded.last_at",
                        [(song_id, k, v, now) for k, v in loops.items() if k in line_ids])


def practice_summary() -> dict[str, dict]:
    """Per song: total seconds, seconds in Practice mode, the last day played and on how many days."""
    with connect() as con:
        rows = con.execute("SELECT song_id, SUM(seconds) AS total, SUM(CASE WHEN source = 'practice' THEN seconds ELSE 0 END) AS practice, "
                           "MAX(day) AS last_day, COUNT(DISTINCT day) AS days FROM practice_time WHERE seconds > 0 GROUP BY song_id").fetchall()
    return {r["song_id"]: {"seconds": r["total"], "practiceSeconds": r["practice"], "lastDay": r["last_day"], "days": r["days"]}
            for r in rows}


def practice(song_id: str) -> dict:
    """One song's log: time per day, and loop passes per line."""
    with connect() as con:
        days = con.execute("SELECT day, SUM(seconds) AS seconds FROM practice_time WHERE song_id = ? GROUP BY day ORDER BY day",
                           (song_id,)).fetchall()
        loops = con.execute("SELECT line_id, passes FROM line_loops WHERE song_id = ?", (song_id,)).fetchall()
    return {"seconds": sum(d["seconds"] for d in days), "days": [dict(d) for d in days],
            "lineLoops": {r["line_id"]: r["passes"] for r in loops}}


# --- line ratings (self-assessment) --------------------------------------------------------
def set_rating(song_id: str, line_id: str, rating: int | None, line_ids: set[str], today: date | None = None) -> None:
    """Rate a line 0 (don't know), 1 (shaky) or 2 (know it); None clears the rating."""
    if line_id not in line_ids:
        raise LibraryError(f"line {line_id} is not in this song")
    with connect() as con:
        if rating is None:
            con.execute("DELETE FROM line_ratings WHERE song_id = ? AND line_id = ?", (song_id, line_id))
            return
        if not isinstance(rating, int) or isinstance(rating, bool) or rating not in (0, 1, 2):
            raise LibraryError("rating must be 0 (don't know), 1 (shaky), 2 (know it) or null")
        con.execute("INSERT INTO line_ratings (song_id, line_id, rating, rated_on) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(song_id, line_id) DO UPDATE SET rating = excluded.rating, rated_on = excluded.rated_on",
                    (song_id, line_id, rating, (today or date.today()).isoformat()))


def ratings() -> tuple[dict[str, dict[str, int]], dict[str, str]]:
    """(song id -> line id -> rating, song id -> last day a line was rated)."""
    by_song: dict[str, dict[str, int]] = {}
    last: dict[str, str] = {}
    with connect() as con:
        for r in con.execute("SELECT song_id, line_id, rating, rated_on FROM line_ratings"):
            by_song.setdefault(r["song_id"], {})[r["line_id"]] = r["rating"]
            last[r["song_id"]] = max(last.get(r["song_id"], ""), r["rated_on"])
    return by_song, last


def remap_lines(song_id: str, line_map: dict[str, list[str]]) -> None:
    """Follow a split / join / delete / renumbering (lineedit). A split line's rating goes to both halves and its loop count
    to the first; joined lines keep the weaker rating and the sum of their loop counts."""
    with connect() as con:
        ratings = {r["line_id"]: (r["rating"], r["rated_on"]) for r in
                   con.execute("SELECT line_id, rating, rated_on FROM line_ratings WHERE song_id = ?", (song_id,))}
        loops = {r["line_id"]: (r["passes"], r["last_at"]) for r in
                 con.execute("SELECT line_id, passes, last_at FROM line_loops WHERE song_id = ?", (song_id,))}
        new_ratings: dict[str, tuple[int, str]] = {}
        new_loops: dict[str, tuple[int, str]] = {}
        for old, news in line_map.items():
            if not news:
                continue  # a deleted line: its rating and loop count go with it
            if old in ratings:
                for new in news:
                    have = new_ratings.get(new)
                    new_ratings[new] = ratings[old] if have is None else (min(have[0], ratings[old][0]), max(have[1], ratings[old][1]))
            if old in loops:
                have = new_loops.get(news[0])
                new_loops[news[0]] = loops[old] if have is None else (have[0] + loops[old][0], max(have[1], loops[old][1]))
        con.execute("DELETE FROM line_ratings WHERE song_id = ?", (song_id,))
        con.execute("DELETE FROM line_loops WHERE song_id = ?", (song_id,))
        con.executemany("INSERT INTO line_ratings (song_id, line_id, rating, rated_on) VALUES (?, ?, ?, ?)",
                        [(song_id, k, r, d) for k, (r, d) in new_ratings.items()])
        con.executemany("INSERT INTO line_loops (song_id, line_id, passes, last_at) VALUES (?, ?, ?, ?)",
                        [(song_id, k, n, d) for k, (n, d) in new_loops.items()])
