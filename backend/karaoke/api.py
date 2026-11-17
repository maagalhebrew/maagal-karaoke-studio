"""Local editor API. Served on 127.0.0.1 only by `karaoke serve`.

Paths are read from `paths` at call time so tests can point them at a temp folder.
"""
import json
import re
import subprocess
import threading
from datetime import datetime

import numpy as np
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import importer, learning, library, lineedit, paths, permissions, stages, suggest, translate, wordedit
from .songfile import load, save, validation_errors
from .stages import MIN_WORD_MS, _key

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
AUDIO_KINDS = {"original", "vocals", "instrumental"}
PEAKS_PER_SECOND = 200
PEAKS_SAMPLE_RATE = 8000

_write_lock = threading.Lock()
app = FastAPI(title="Karaoke Studio")

# The server listens on this computer only, but every web page open in the browser is on this computer too.
# Two checks keep other sites out:
# - Host: a request must be addressed to 127.0.0.1 or localhost. A site that points its own domain at 127.0.0.1
#   ("DNS rebinding") sends its domain as the Host, so it can't read the songs or lyrics.
# - Origin: a page on another site can still make the browser send a request here (it just can't read the
#   answer), so anything that changes something must come from the studio's own pages. Browsers add an Origin
#   header to such requests; the CLI and scripts send none and are allowed.
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _hostname(value: str) -> str:
    """'localhost:5180' -> 'localhost'; 'http://127.0.0.1:8321' -> '127.0.0.1'."""
    value = value.split("://", 1)[-1].split("/", 1)[0]
    return value.rsplit(":", 1)[0].lower() if value.count(":") == 1 else value.lower()


@app.middleware("http")
async def only_this_computer(request: Request, call_next):
    if _hostname(request.headers.get("host", "")) not in ALLOWED_HOSTS:
        return PlainTextResponse("Unknown host: open the studio at http://127.0.0.1:8321", status_code=400)
    origin = request.headers.get("origin")
    if request.method not in SAFE_METHODS and origin is not None and _hostname(origin) not in ALLOWED_HOSTS:
        return PlainTextResponse("Changes can only come from the studio's own pages", status_code=403)
    return await call_next(request)


@app.middleware("http")
async def no_stale_pages(request, call_next):
    """index.html and the API must always be fresh; hashed /assets/* files may be cached."""
    response = await call_next(request)
    if not request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def _folder(song_id: str):
    if not SLUG_RE.match(song_id):
        raise HTTPException(400, "invalid song id")
    folder = paths.SONGS / song_id
    if not (folder / "song.json").is_file():
        raise HTTPException(404, f"song '{song_id}' not found")
    return folder


def _read(folder) -> dict:
    return load(folder)


def _words(song: dict):
    for line in song["lines"]:
        yield from line["words"]


def _timing_errors(song: dict) -> list[str]:
    errors, prev_end = [], 0
    duration = song["song"]["durationMs"]
    for w in _words(song):
        if w["startMs"] < prev_end:
            errors.append(f"{w['id']} starts before the previous word ends")
        if w["endMs"] - w["startMs"] < MIN_WORD_MS:
            errors.append(f"{w['id']} is shorter than {MIN_WORD_MS} ms")
        if w["endMs"] > duration:
            errors.append(f"{w['id']} ends after the song")
        prev_end = w["endMs"]
    return errors


def _reference_errors(song: dict) -> list[str]:
    """Sections/clips/drills must point at real lines/words/clips, in order, without overlapping sections."""
    errors = []
    line_idx = {line["id"]: i for i, line in enumerate(song["lines"])}
    word_idx = {w["id"]: i for i, w in enumerate(_words(song))}
    prev_to = -1
    for s in song["sections"]:
        a, b = line_idx.get(s["fromLine"]), line_idx.get(s["toLine"])
        if a is None or b is None or a > b:
            errors.append(f"section {s['id']} has an invalid line range")
        elif a <= prev_to:
            errors.append(f"section {s['id']} overlaps the previous section")
        else:
            prev_to = b
    for kind in ("sections", "clips", "drills"):
        ids = [x["id"] for x in song[kind]]
        if len(ids) != len(set(ids)):
            errors.append(f"duplicate {kind} ids")
    clip_ids = set()
    for c in song["clips"]:
        a, b = word_idx.get(c["fromWord"]), word_idx.get(c["toWord"])
        if a is None or b is None or a > b:
            errors.append(f"clip {c['id']} has an invalid word range")
        clip_ids.add(c["id"])
    for d in song["drills"]:
        for n, step in enumerate(d["steps"], 1):
            if step["type"] == "clip" and step["clip"] not in clip_ids:
                errors.append(f"drill {d['id']} step {n} uses missing clip {step['clip']}")
    return errors


# --- songs ------------------------------------------------------------------------
@app.get("/api/songs")
def list_songs():
    """The library: counts, artist, workflow status, permission status, favourite, folders (no lyric text)."""
    member, favs = library.labels()
    perms = permissions.all_records()
    exported = {r["song_id"] for r in permissions.export_log()}
    songs = _all_songs()
    practised, learn = _learning(songs)
    out = []
    if paths.SONGS.is_dir():
        for folder in sorted(paths.SONGS.iterdir()):
            if (folder / "song.json").is_file():
                s = songs[folder.name]
                sid = s["song"]["id"]
                words = list(_words(s))
                flagged = sum(1 for w in words if w["flags"])
                out.append({"id": sid, "title": s["song"]["title"], "artist": s["song"]["artist"],
                            "durationMs": s["song"]["durationMs"], "words": len(words), "flaggedWords": flagged,
                            "status": library.status(s, flagged, sid in exported),
                            "permission": perms[sid]["status"] if sid in perms else "Not asked",
                            "favorite": sid in favs, "folders": member.get(sid, []),
                            "practice": practised.get(sid, {"seconds": 0, "practiceSeconds": 0, "lastDay": None, "days": 0}),
                            "learning": {k: v for k, v in learn[folder.name].items() if k != "newWordIds"},
                            "addedAt": datetime.fromtimestamp(folder.stat().st_ctime).strftime("%Y-%m-%d")})
    return out


def _all_songs() -> dict[str, dict]:
    """Every song by folder name (= its id)."""
    if not paths.SONGS.is_dir():
        return {}
    return {f.name: _read(f) for f in sorted(paths.SONGS.iterdir()) if (f / "song.json").is_file()}


def _learning(songs: dict[str, dict]) -> tuple[dict, dict]:
    """(practice summary, learning stats) for the library. Studied = practised or rated."""
    practised = library.practice_summary()
    by_song, rated_on = library.ratings()
    studied = {sid for sid in songs if sid in practised or sid in by_song}
    last = {sid: max(filter(None, [practised.get(sid, {}).get("lastDay"), rated_on.get(sid)]), default=None) for sid in songs}
    return practised, learning.library_stats(songs, studied, by_song, last)


def _song_ids() -> set[str]:
    return {f.name for f in paths.SONGS.iterdir() if (f / "song.json").is_file()} if paths.SONGS.is_dir() else set()


def _library(call):
    try:
        return call()
    except library.LibraryError as e:
        raise HTTPException(422, str(e)) from None


@app.get("/api/folders")
def get_folders():
    return library.folders(_song_ids())


@app.post("/api/folders", status_code=201)
def post_folder(body: dict = Body(...)):
    return _library(lambda: library.create_folder(str(body.get("name", ""))))


@app.patch("/api/folders/{folder_id}")
def patch_folder(folder_id: int, body: dict = Body(...)):
    _library(lambda: library.rename_folder(folder_id, str(body.get("name", ""))))
    return library.folders(_song_ids())


@app.delete("/api/folders/{folder_id}")
def delete_folder(folder_id: int):
    _library(lambda: library.delete_folder(folder_id))
    return library.folders(_song_ids())


@app.post("/api/folders/{folder_id}/songs")
def add_song_to_folder(folder_id: int, body: dict = Body(...)):
    """Drop a song on a folder in the sidebar."""
    song_id = str(body.get("songId", ""))
    _folder(song_id)
    _library(lambda: library.add_to_folder(folder_id, song_id))
    return library.folders(_song_ids())


@app.put("/api/songs/{song_id}/folders")
def put_song_folders(song_id: str, body: dict = Body(...)):
    _folder(song_id)
    ids = body.get("folders", [])
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        raise HTTPException(422, "folders must be a list of folder ids")
    return {"folders": _library(lambda: library.set_song_folders(song_id, ids))}


@app.get("/api/songs/{song_id}/learning")
def get_learning(song_id: str):
    """One song's line ratings, learning stats and the ids of its words new to you (ids only, no text)."""
    _folder(song_id)
    songs = _all_songs()
    _, learn = _learning(songs)
    by_song, _ = library.ratings()
    return {**learn[song_id], "ratings": by_song.get(song_id, {})}


@app.put("/api/songs/{song_id}/ratings/{line_id}")
def put_rating(song_id: str, line_id: str, body: dict = Body(...)):
    folder = _folder(song_id)
    line_ids = {line["id"] for line in _read(folder)["lines"]}
    _library(lambda: library.set_rating(song_id, line_id, body.get("rating"), line_ids))
    return {"lineId": line_id, "rating": body.get("rating")}


@app.get("/api/songs/{song_id}/practice")
def get_practice(song_id: str):
    _folder(song_id)
    return library.practice(song_id)


@app.post("/api/songs/{song_id}/practice", status_code=204)
def post_practice(song_id: str, body: dict = Body(...)):
    """A batch from the Studio editor or Practice mode (also sent with navigator.sendBeacon when the page closes)."""
    folder = _folder(song_id)
    line_ids = {line["id"] for line in _read(folder)["lines"]}
    _library(lambda: library.record_practice(song_id, body.get("source"), body.get("seconds", 0), body.get("loops", {}), line_ids))


@app.put("/api/songs/{song_id}/favorite")
def put_favorite(song_id: str, body: dict = Body(...)):
    _folder(song_id)
    library.set_favorite(song_id, bool(body.get("favorite")))
    return {"favorite": bool(body.get("favorite"))}


@app.delete("/api/songs/{song_id}")
def delete_song(song_id: str):
    """Recoverable delete: the song's folder moves to songs/_deleted/<id>-<date time>; move it back to restore it.
    The permission record and export log stay (they are history)."""
    folder = _folder(song_id)
    job = importer.status()
    if job and job["state"] == "running" and job["slug"] == song_id:
        raise HTTPException(409, "this song is still being imported")
    trash = paths.SONGS / "_deleted"
    trash.mkdir(exist_ok=True)
    target = trash / f"{song_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    with _write_lock:
        folder.rename(target)
    return {"deleted": song_id, "movedTo": str(target.relative_to(paths.SONGS.parent))}


@app.get("/api/songs/{song_id}")
def get_song(song_id: str):
    return _read(_folder(song_id))


@app.put("/api/songs/{song_id}")
def put_song(song_id: str, song: dict = Body(...)):
    folder = _folder(song_id)
    errors = validation_errors(song)
    if errors:
        raise HTTPException(422, f"schema: {errors[0]}" + (f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""))
    if song["song"]["id"] != song_id:
        raise HTTPException(422, "song.id does not match the URL")
    with _write_lock:
        stored = _read(folder)
        # A word's spelling may change (vowel points, punctuation, letter case) but not its letters: the timing
        # and everything else that points at the word belong to those letters.
        if [(w["id"], _key(w["plain"])) for w in _words(song)] != [(w["id"], _key(w["plain"])) for w in _words(stored)]:
            raise HTTPException(409, "words were added, removed or changed; the editor may only edit timing, spelling marks and English")
        errors = _timing_errors(song)
        if errors:
            raise HTTPException(422, f"timing: {errors[0]}")
        errors = _reference_errors(song)
        if errors:
            raise HTTPException(422, errors[0])
        save(folder, song)
    return {"saved": True}


@app.get("/api/songs/{song_id}/audio/{kind}")
def get_audio(song_id: str, kind: str):
    if kind not in AUDIO_KINDS:
        raise HTTPException(400, "kind must be original, vocals or instrumental")
    path = _folder(song_id) / "audio" / f"{kind}.wav"
    if not path.is_file():
        raise HTTPException(404, f"{kind}.wav missing")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/songs/{song_id}/peaks")
def get_peaks(song_id: str, track: str = "vocals"):
    """Waveform peaks of a track (max |amplitude| per 5 ms), cached next to the audio."""
    if track not in AUDIO_KINDS:
        raise HTTPException(400, "track must be original, vocals or instrumental")
    folder = _folder(song_id)
    wav = folder / "audio" / f"{track}.wav"
    if not wav.is_file():
        raise HTTPException(404, f"{track}.wav missing")
    cache = folder / "audio" / f"{track}.peaks.json"
    if cache.is_file() and cache.stat().st_mtime >= wav.stat().st_mtime:
        return json.loads(cache.read_text(encoding="utf-8"))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-ac", "1", "-ar", str(PEAKS_SAMPLE_RATE),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    samples = np.abs(np.frombuffer(raw, dtype=np.int16).astype(np.float32)) / 32768
    bucket = PEAKS_SAMPLE_RATE // PEAKS_PER_SECOND
    n = len(samples) // bucket
    peaks = samples[: n * bucket].reshape(n, bucket).max(axis=1)
    peaks = peaks / max(float(peaks.max()), 1e-6)
    data = {"peaksPerSecond": PEAKS_PER_SECOND, "duration": len(samples) / PEAKS_SAMPLE_RATE,
            "peaks": [round(float(p), 3) for p in peaks]}
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data


# --- permissions tracker + export log ----------------------------------------------
def _permission_view(song_id: str, record: dict) -> dict:
    song = _read(paths.SONGS / song_id)["song"]
    return {**record, "title": song["title"], "draft": permissions.draft(record, song["title"], song["language"])}


@app.get("/api/permissions")
def list_permissions():
    """One row per song (unsaved songs show as 'Not asked'), each with its filled-in request draft."""
    permissions.due()  # refresh 'Follow-up due' first
    records = permissions.all_records()
    return [_permission_view(s["id"], records.get(s["id"]) or permissions.get(s["id"])) for s in list_songs()]


@app.get("/api/permissions/due")
def due_permissions():
    """Launch reminder: requests whose follow-up date has come."""
    return [_permission_view(r["song_id"], r) for r in permissions.due() if (paths.SONGS / r["song_id"] / "song.json").is_file()]


@app.put("/api/permissions/{song_id}")
def put_permission(song_id: str, changes: dict = Body(...)):
    _folder(song_id)
    try:
        return _permission_view(song_id, permissions.save(song_id, changes))
    except permissions.RecordError as e:
        raise HTTPException(422, str(e)) from None


@app.get("/api/export-log")
def get_export_log(song: str | None = None):
    return permissions.export_log(song)


# --- split / join lines, move a word between lines ------------------------------------------
@app.post("/api/songs/{song_id}/lines")
def edit_lines(song_id: str, body: dict = Body(...)):
    """{"action": "split", "wordId"} · {"action": "join", "lineId"} · {"action": "move", "wordId", "to": "prev"|"next"}
    · {"action": "delete", "lineId"} · {"action": "restore", "index", "line", "sections"} (a delete's undo),
    optionally with "english": {lineId: text} applied to the resulting lines (an undo restores the old English).
    Saves the song, then moves ratings, loop counts and dismissed suggestions to the new ids.
    Returns the song, the changed lines, a word to select and the request that undoes this one."""
    folder = _folder(song_id)
    with _write_lock:
        song = _read(folder)
        try:
            index = body.get("index", -1)
            if not isinstance(index, int) or isinstance(index, bool):
                raise lineedit.LineEditError("index must be a whole number")
            r = lineedit.apply(song, str(body.get("action", "")), word_id=str(body.get("wordId", "")),
                               line_id=str(body.get("lineId", "")), to=str(body.get("to", "")),
                               index=index, line=body.get("line"), sections=body.get("sections"))
        except lineedit.LineEditError as e:
            raise HTTPException(422, str(e)) from None
        english = body.get("english") or {}
        if not isinstance(english, dict) or not all(isinstance(v, str) for v in english.values()):
            raise HTTPException(422, "english must map line ids to text")
        for line in song["lines"]:
            if line["id"] in english and line["id"] in r["lineIds"]:
                line["english"] = english[line["id"]]
        errors = validation_errors(song) or _timing_errors(song)
        if errors:
            raise HTTPException(422, f"edit would break the song: {errors[0]}")
        save(folder, song)
        library.remap_lines(song_id, r["lineMap"])
        suggest.remap_dismissed(folder, r["wordMap"], r["removed"])
    return {"song": song, "lineIds": r["lineIds"], "wordId": r["wordId"], "undo": r["undo"]}


@app.post("/api/songs/{song_id}/translate-lines")
def translate_some_lines(song_id: str, body: dict = Body(...)):
    """English for the given lines, with their neighbours as context. Nothing is saved: the editor applies it
    (so typing in the meantime is never overwritten). 503 when the local model can't be used."""
    song = _read(_folder(song_id))
    lines = song["lines"]
    wanted = [str(x) for x in body.get("lineIds", [])][:4]
    index = {line["id"]: i for i, line in enumerate(lines)}
    if not wanted or any(w not in index for w in wanted):
        raise HTTPException(422, "lineIds must name lines of this song (at most 4)")
    hebrew = [" ".join(w["plain"] for w in line["words"]) for line in lines]
    try:
        done = translate.translate_in_song(hebrew, [index[w] for w in wanted], language=song["song"]["language"])
    except translate.TranslateError as e:
        raise HTTPException(503, str(e)) from None
    return {"english": {lines[i]["id"]: text for i, text in done.items()}}


# --- add / remove a lyric word ---------------------------------------------------------
@app.post("/api/songs/{song_id}/words")
def edit_words(song_id: str, body: dict = Body(...)):
    """{"action": "insert", "wordId", "side": "before"|"after", "text"} or {"action": "delete", "wordId"}.
    The only way the word list changes after import (PUT refuses it, so a stale tab can't undo it).
    Returns the saved song and the word to select."""
    folder = _folder(song_id)
    with _write_lock:
        song = _read(folder)
        try:
            if body.get("action") == "insert":
                word = wordedit.insert_word(song, str(body.get("wordId", "")), str(body.get("side", "")),
                                            str(body.get("text", "")), body.get("startMs"), body.get("endMs"))
            elif body.get("action") == "delete":
                word = wordedit.delete_word(song, str(body.get("wordId", "")))
            else:
                raise wordedit.WordEditError("action must be insert or delete")
        except wordedit.WordEditError as e:
            raise HTTPException(422, str(e)) from None
        errors = validation_errors(song) or _timing_errors(song)
        if errors:
            raise HTTPException(422, f"edit would break the song: {errors[0]}")
        save(folder, song)
    return {"song": song, "wordId": word}


# --- missing / extra word suggestions (lyrics vs what Whisper heard) ------------------------
@app.get("/api/songs/{song_id}/suggestions")
def get_suggestions(song_id: str):
    folder = _folder(song_id)
    heard = suggest.load_heard(folder)
    if heard is None:
        return {"available": False, "suggestions": []}
    return {"available": True, "suggestions": suggest.suggestions(_read(folder), heard, suggest.load_dismissed(folder))}


@app.post("/api/songs/{song_id}/suggestions/scan")
def scan_suggestions(song_id: str):
    """Transcribe the vocals now (songs added before transcripts were kept). About a minute on the GPU."""
    folder = _folder(song_id)
    with _breakdown_lock:  # one model at a time (rule 4); the breakdown model is unloaded first
        translate._unload(translate.load_settings())
        stages.transcribe_song(folder)
    return get_suggestions(song_id)


@app.post("/api/songs/{song_id}/suggestions/dismiss")
def dismiss_suggestion(song_id: str, body: dict = Body(...)):
    suggest.dismiss(_folder(song_id), str(body.get("key", "")))
    return get_suggestions(song_id)


# --- word-by-word breakdown (local model) ---------------------------------------------
_breakdown_lock = threading.Lock()  # one model request at a time


@app.post("/api/songs/{song_id}/breakdown")
def line_breakdown(song_id: str, body: dict = Body(...)):
    """Word-by-word breakdown of one line, cached in the song folder (breakdowns.json, keyed by the line's text)."""
    folder = _folder(song_id)
    song = _read(folder)
    if song["song"]["language"] != "he":
        raise HTTPException(422, "the word-by-word breakdown is for Hebrew songs for now")
    lines = song["lines"]
    i = next((k for k, line in enumerate(lines) if line["id"] == body.get("lineId")), None)
    if i is None:
        raise HTTPException(404, "no such line")
    words = [w["plain"] for w in lines[i]["words"]]
    key = " ".join(words)
    cache_path = folder / "breakdowns.json"
    with _breakdown_lock:
        cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
        if key in cache and not body.get("refresh"):
            return cache[key]
        nearby = "\n".join(" ".join(w["plain"] for w in line["words"]) for line in lines[max(0, i - 2):i + 2])
        try:
            result = translate.breakdown_line(words, nearby)
        except translate.TranslateError as e:
            raise HTTPException(503, str(e)) from None
        cache[key] = result
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        return result


# --- import page --------------------------------------------------------------------
@app.post("/api/import/check")
def import_check(body: dict = Body(...)):
    """Counts for pasted lyrics (nothing is saved)."""
    try:
        return importer.check(str(body.get("lyrics", "")), str(body.get("language", "he")),
                              importer.english_lines_option(body.get("englishLines")))
    except importer.ImportError_ as e:
        raise HTTPException(422, str(e)) from None


@app.post("/api/import/audio")
async def import_audio(request: Request, name: str = ""):
    """An audio file (or a browser recording) as the raw request body; `name` gives its type. Returns an upload id."""
    try:
        path = importer.new_upload(name)
    except importer.ImportError_ as e:
        raise HTTPException(422, str(e)) from None
    size = 0
    try:
        with path.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > importer.UPLOAD_MAX_BYTES:
                    raise HTTPException(413, f"That file is bigger than {importer.UPLOAD_MAX_BYTES // 2**20} MB.")
                f.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    try:
        return await run_in_threadpool(importer.finish_upload, path)
    except importer.ImportError_ as e:
        raise HTTPException(422, str(e)) from None


@app.get("/api/import/audio/{upload_id}")
def import_audio_file(upload_id: str):
    """Listen to an upload (the trim step and the 'audio ready' player)."""
    try:
        return FileResponse(importer.upload_path(upload_id))
    except importer.ImportError_ as e:
        raise HTTPException(404, str(e)) from None


@app.post("/api/import/audio/{upload_id}/trim")
def import_audio_trim(upload_id: str, body: dict = Body(...)):
    try:
        return importer.trim(upload_id, int(body.get("startMs", 0)), int(body.get("endMs", 0)))
    except importer.ImportError_ as e:
        raise HTTPException(422, str(e)) from None


@app.post("/api/import", status_code=202)
def import_start(body: dict = Body(...)):
    try:
        return importer.start(str(body.get("url", "")), str(body.get("lyrics", "")),
                              str(body.get("title", "")), str(body.get("artist", "")), str(body.get("model", "")),
                              str(body.get("upload", "")), str(body.get("language", "he")),
                              importer.english_lines_option(body.get("englishLines")))
    except importer.ImportError_ as e:
        raise HTTPException(422, str(e)) from None


@app.get("/api/youtube-cookies")
def youtube_cookies():
    """Whether sign-in cookies are loaded (never their content)."""
    return importer.cookies_status()


@app.put("/api/youtube-cookies")
def put_youtube_cookies(body: dict = Body(...)):
    try:
        return importer.save_cookies(str(body.get("text", "")))
    except importer.ImportError_ as e:
        raise HTTPException(422, str(e)) from None


@app.delete("/api/youtube-cookies")
def delete_youtube_cookies():
    return importer.remove_cookies()


@app.get("/api/translate/models")
def translate_models():
    """Ollama models for the import page's picker; the default from data/translate.json comes first."""
    s = translate.load_settings()
    models = translate.installed_models(s)
    return {"default": s["model"], "enabled": s["enabled"], "ollamaRunning": bool(models),
            "models": [s["model"]] + [m for m in models if m != s["model"]]}


@app.get("/api/import")
def import_status():
    """The running (or last) import; null when there hasn't been one since the server started."""
    return importer.status()


# --- the built editor (frontend/dist), mounted last so /api wins ------------------
if paths.FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=paths.FRONTEND_DIST, html=True), name="editor")
