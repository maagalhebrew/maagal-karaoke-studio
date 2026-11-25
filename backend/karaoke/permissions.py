"""Permissions tracker and export log, in SQLite (data/karaoke.db).

One permission record per song. The export log keeps every export with the song ranges it used, the permission
status at that moment and any guard override. Nothing here stores or prints lyric text.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from . import paths

STATUSES = ("Not asked", "Asked", "Follow-up due", "Granted", "Declined", "No answer")
FOLLOW_UP_DAYS = 10
FIELDS = ("artist", "contact_name", "contact_channel", "contact_handle", "asked_on", "follow_up_on", "status", "scope",
          "reply_path")
WAITING = ("Asked", "Follow-up due")  # statuses that are waiting on a reply

# The permission request, one per song language. {name}: the contact (or artist); {song}: the song title.
DRAFT = ("שלום {name}, אשמח לקבל אישור להשתמש בקטעים קצרים מהשיר ״{song}״ בשיעור ללימוד השפה. "
         "בשיעור יופיעו קרדיט מלא וקישור לשיר המקורי. תודה רבה!")


DRAFT_ES = ("Hola {name}: me gustaría pedirte permiso para usar fragmentos cortos de «{song}» "
            "en una lección de idiomas. Incluiré los créditos y un enlace a la canción original. ¡Muchas gracias!")


def draft(record: dict, song_title: str, language: str = "he") -> str:
    if language == "es":
        return DRAFT_ES.format(name=record["contact_name"] or record["artist"] or "[nombre]", song=song_title or "[canción]")
    return DRAFT.format(name=record["contact_name"] or record["artist"] or "[שם]", song=song_title or "[שם השיר]")

SCHEMA = """
CREATE TABLE IF NOT EXISTS permissions (
  song_id TEXT PRIMARY KEY,
  artist TEXT NOT NULL DEFAULT '',
  contact_name TEXT NOT NULL DEFAULT '',
  contact_channel TEXT NOT NULL DEFAULT '',
  contact_handle TEXT NOT NULL DEFAULT '',
  asked_on TEXT,
  follow_up_on TEXT,
  status TEXT NOT NULL DEFAULT 'Not asked',
  scope TEXT NOT NULL DEFAULT '',
  reply_path TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS export_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  song_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  output TEXT NOT NULL,
  ranges TEXT NOT NULL,             -- JSON [[fromMs, toMs], ...]: every play of song audio, in order
  permission_status TEXT NOT NULL,
  warnings TEXT NOT NULL,           -- JSON list of guard warnings
  override_reason TEXT              -- set when the user exported despite warnings
);
"""


class RecordError(ValueError):
    pass


@contextmanager
def connect():
    """One short-lived connection per call: commit on success, always close (the editor and CLI share the file)."""
    paths.DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(paths.DB)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _iso(value) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise RecordError(f"dates must look like 2026-10-28, got '{value}'") from None


def _default(song_id: str) -> dict:
    return {"song_id": song_id, **{f: "" for f in FIELDS}, "asked_on": None, "follow_up_on": None,
            "status": "Not asked", "updated_at": None}


def get(song_id: str) -> dict:
    """The song's record, or an unsaved 'Not asked' one."""
    with connect() as con:
        row = con.execute("SELECT * FROM permissions WHERE song_id = ?", (song_id,)).fetchone()
    return dict(row) if row else _default(song_id)


def all_records() -> dict[str, dict]:
    with connect() as con:
        return {r["song_id"]: dict(r) for r in con.execute("SELECT * FROM permissions")}


def save(song_id: str, changes: dict, today: date | None = None) -> dict:
    """Create or update a record. Asking sets the ask date (today if missing) and a follow-up 10 days later."""
    unknown = set(changes) - set(FIELDS)
    if unknown:
        raise RecordError(f"unknown field(s): {', '.join(sorted(unknown))}")
    today = today or date.today()
    rec = {**get(song_id), **{k: ("" if v is None and k not in ("asked_on", "follow_up_on") else v) for k, v in changes.items()}}
    if rec["status"] not in STATUSES:
        raise RecordError(f"status must be one of: {', '.join(STATUSES)}")
    rec["asked_on"], rec["follow_up_on"] = _iso(rec["asked_on"]), _iso(rec["follow_up_on"])
    if rec["status"] in WAITING and not rec["asked_on"]:
        rec["asked_on"] = today.isoformat()
    if rec["asked_on"] and not rec["follow_up_on"]:
        rec["follow_up_on"] = (date.fromisoformat(rec["asked_on"]) + timedelta(days=FOLLOW_UP_DAYS)).isoformat()
    rec["updated_at"] = datetime.now().isoformat(timespec="seconds")
    cols = ("song_id", *FIELDS, "updated_at")
    with connect() as con:
        con.execute(f"INSERT OR REPLACE INTO permissions ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    [rec[c] for c in cols])
    return rec


def due(today: date | None = None) -> list[dict]:
    """Requests still waiting on a reply whose follow-up date has come. Marks them 'Follow-up due'."""
    today = (today or date.today()).isoformat()
    with connect() as con:
        con.execute("UPDATE permissions SET status = 'Follow-up due' WHERE status = 'Asked' AND follow_up_on <= ?", (today,))
        rows = con.execute("SELECT * FROM permissions WHERE status IN (?, ?) AND follow_up_on <= ? ORDER BY follow_up_on",
                           (*WAITING, today)).fetchall()
    return [dict(r) for r in rows]


def log_export(song_id: str, kind: str, output: str, ranges: list[tuple[int, int]], status: str,
               warnings: list[str], override_reason: str | None) -> int:
    with connect() as con:
        cur = con.execute(
            "INSERT INTO export_log (at, song_id, kind, output, ranges, permission_status, warnings, override_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), song_id, kind, output, json.dumps([list(r) for r in ranges]),
             status, json.dumps(warnings), override_reason))
        return cur.lastrowid


def export_log(song_id: str | None = None) -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT * FROM export_log" + (" WHERE song_id = ?" if song_id else "") + " ORDER BY id DESC",
                           (song_id,) if song_id else ()).fetchall()
    return [{**dict(r), "ranges": json.loads(r["ranges"]), "warnings": json.loads(r["warnings"])} for r in rows]
