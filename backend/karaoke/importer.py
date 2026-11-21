"""Import page backend: YouTube link or an uploaded audio file (a file or a system-sound recording) + pasted lyrics
-> inbox files -> `karaoke add` -> permission record.

One import at a time (the GPU holds one model). The pipeline runs as its own process, so all its GPU memory
is freed when it exits and a crash can't take the editor down. Status holds counts and stage names only (rule 5).
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path, PureWindowsPath
from urllib.parse import urlparse

import numpy as np

from . import lyrics as lyrics_mod
from . import desktop_songs, paths, permissions, translate
from .cli import slugify
from .songfile import load, save
from .stages import AUDIO_TYPES, STAGES, StageError, duration_s
from .text import LANGUAGES

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
STEPS = ["download", *STAGES]
# Uploads: the pipeline's own types are kept as they are; these are converted to WAV on arrival (browser
# recordings are WebM/Opus with no duration in the header, which ffprobe can't read).
CONVERT_TYPES = {".webm", ".ogg", ".opus", ".flac", ".aac", ".mov", ".mkv"}
UPLOAD_MAX_BYTES = 500 * 1024 * 1024
UPLOAD_ID = re.compile(r"^upload-[0-9a-f]{32}$")
UPLOAD_KEEP_S = 24 * 3600  # an upload never used for a song is cleared after a day
# Trimming a recording: silence is anything this far below the loudest moment (or below an absolute floor).
ANALYSE_RATE = 8000
FRAME_MS = 50
SILENCE_DB = -55
SILENCE_BELOW_PEAK_DB = 35
MERGE_GAP_MS = 1500  # quieter than this inside a song doesn't split it
MIN_SEGMENT_MS = 500  # shorter bursts (a click, a notification) aren't a stretch of sound
PAD_BEFORE_MS, PAD_AFTER_MS, NEIGHBOUR_GAP_MS = 300, 1000, 200
FADE_S = 0.02
QUALITY_RATE = 44100
CLIP_LEVEL = 0.999
MONO_BELOW_DB = -50  # left minus right this far below left plus right: effectively mono
DOWNLOAD_TIMEOUT_S = 600
STAGE_LINE = re.compile(r"^\[ok\] (\d+)/\d+ (\w+)\s+([\d.]+)s")
FAIL_LINE = re.compile(r"^FAILED at stage \S+ \((\w+)\): (.*)$")

_lock = threading.Lock()
_job: dict | None = None


class ImportError_(ValueError):
    """Bad input for an import (shown to the user as is)."""


COOKIE_HEADERS = ("# HTTP Cookie File", "# Netscape HTTP Cookie File")
BLOCKED = ("confirm you’re not a bot", "confirm you're not a bot", "HTTP Error 429")
BLOCKED_MESSAGE = ("YouTube is blocking downloads from this internet connection for now (too many requests). "
                   "It usually lifts within hours. To download anyway, load sign-in cookies below.")


# --- YouTube sign-in cookies (a cookies.txt the user exports; never printed or returned) ---------------------
def cookies_status() -> dict:
    p = paths.YT_COOKIES
    if not p.exists():
        return {"present": False}
    return {"present": True, "savedAt": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}


def save_cookies(text: str) -> dict:
    """Store an exported cookies.txt (Netscape format, as yt-dlp needs; CRLF line endings on Windows)."""
    text = text.lstrip("﻿")
    if len(text) > 1_000_000:
        raise ImportError_("That file is too big to be a cookies.txt.")
    if not text.startswith(COOKIE_HEADERS):
        raise ImportError_("That isn't a cookies.txt: it must start with '# Netscape HTTP Cookie File' "
                           "(export it with the 'Get cookies.txt LOCALLY' or 'cookies.txt' browser extension).")
    if "youtube.com" not in text:
        raise ImportError_("That cookies.txt has no youtube.com cookies: export it while on youtube.com.")
    paths.YT_COOKIES.parent.mkdir(exist_ok=True)
    # A login: owner-only where the OS supports it (on Windows the user profile's own ACLs already restrict it).
    fd = os.open(paths.YT_COOKIES, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write("\r\n".join(text.splitlines()).encode("utf-8") + b"\r\n")
    os.chmod(paths.YT_COOKIES, 0o600)  # in case it already existed with broader permissions
    return cookies_status()


def remove_cookies() -> dict:
    paths.YT_COOKIES.unlink(missing_ok=True)
    return cookies_status()


# --- uploaded audio (a file, or a recording of the computer's sound made in the browser) -------------------
def new_upload(name: str) -> Path:
    """Where to write an upload named `name` (only its extension is used). Clears day-old unused uploads."""
    ext = Path(name).suffix.lower()
    if ext not in AUDIO_TYPES | CONVERT_TYPES:
        kinds = ", ".join(sorted(t[1:].upper() for t in AUDIO_TYPES | CONVERT_TYPES))
        raise ImportError_(f"That file type can't be used. Audio files work: {kinds}.")
    paths.INBOX.mkdir(parents=True, exist_ok=True)
    for old in paths.INBOX.glob("upload-*.*"):
        if time.time() - old.stat().st_mtime > UPLOAD_KEEP_S:
            old.unlink(missing_ok=True)
    return paths.INBOX / f"upload-{uuid.uuid4().hex}{ext}"


def finish_upload(path: Path) -> dict:
    """Convert a written upload if needed and check it decodes. Returns its id and length."""
    try:
        if path.suffix in CONVERT_TYPES:
            wav = path.with_suffix(".wav")
            p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-c:a", "pcm_s16le", str(wav)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", env=_fresh_env())
            path.unlink(missing_ok=True)
            if p.returncode != 0:
                wav.unlink(missing_ok=True)
                raise ImportError_("That file has no audio that could be read.")
            path = wav
        seconds = duration_s(path, "upload")
        if seconds < 1:
            raise ImportError_("That audio is shorter than a second.")
    except StageError:
        path.unlink(missing_ok=True)
        raise ImportError_("That file has no audio that could be read.") from None
    except ImportError_:
        path.unlink(missing_ok=True)
        raise
    return {"upload": path.stem, "seconds": round(seconds, 1), **analyse(path), "quality": quality(path)}


def quality(path: Path) -> dict:
    """What actually came in, for the report after a recording or upload. Numbers only."""
    env = _fresh_env()
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", env=env).stderr
    summary = log[log.rfind("Summary:"):]
    def number(key: str) -> float | None:
        m = re.search(key + r":\s+(-?[\d.]+)", summary)
        return float(m.group(1)) if m else None
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "2", "-ar", str(QUALITY_RATE), "-f", "f32le", "-"],
                         capture_output=True, check=True, env=env).stdout
    x = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2)
    mid, side = x.mean(axis=1), (x[:, 0] - x[:, 1]) / 2
    side_db = 20 * np.log10((np.sqrt((side ** 2).mean()) + 1e-9) / (np.sqrt((mid ** 2).mean()) + 1e-9))
    return {"lufs": number("I"), "lra": number("LRA"), "truePeakDb": number("Peak"), "clipped": int((np.abs(x) >= CLIP_LEVEL).sum()),
            "stereo": bool(side_db > MONO_BELOW_DB), "topKHz": round(_top_frequency_hz(mid) / 1000, 1)}


def _top_frequency_hz(mono: np.ndarray) -> float:
    """Highest frequency within 70 dB of the loudest band: a lossy stream's cut-off shows up as a cliff."""
    n = 8192
    frames = mono[: len(mono) // n * n].reshape(-1, n)[::4]
    if not len(frames):
        return 0.0
    spectrum = (np.abs(np.fft.rfft(frames * np.hanning(n), axis=1)) ** 2).mean(axis=0)
    db = np.convolve(10 * np.log10(spectrum + 1e-20), np.ones(9) / 9, mode="same")
    return float(np.fft.rfftfreq(n, 1 / QUALITY_RATE)[np.flatnonzero(db > db.max() - 70)[-1]])


def analyse(path: Path) -> dict:
    """Waveform peaks for the trim view, the stretches of sound between silences (a recording can catch the end of
    the song before and the start of the next one), and a suggested range: the longest stretch, padded."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(ANALYSE_RATE),
                          "-f", "s16le", "-"], capture_output=True, check=True, env=_fresh_env()).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    duration_ms = round(len(x) * 1000 / ANALYSE_RATE)
    frame = ANALYSE_RATE * FRAME_MS // 1000
    n = len(x) // frame
    frames = x[: n * frame].reshape(n, frame)
    peaks = np.abs(frames).max(axis=1)
    peaks = peaks / max(float(peaks.max()), 1e-6)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    loud = db > max(SILENCE_DB, float(db.max()) - SILENCE_BELOW_PEAK_DB)

    segments: list[list[int]] = []  # [startMs, endMs] runs of sound, short gaps merged, blips dropped
    for i in np.flatnonzero(loud):
        s, e = int(i) * FRAME_MS, (int(i) + 1) * FRAME_MS
        if segments and s - segments[-1][1] < MERGE_GAP_MS:
            segments[-1][1] = e
        else:
            segments.append([s, e])
    segments = [g for g in segments if g[1] - g[0] >= MIN_SEGMENT_MS]
    if not segments:
        suggest = [0, duration_ms]
    else:
        k = max(range(len(segments)), key=lambda j: segments[j][1] - segments[j][0])
        lo = segments[k - 1][1] + NEIGHBOUR_GAP_MS if k > 0 else 0
        hi = segments[k + 1][0] - NEIGHBOUR_GAP_MS if k + 1 < len(segments) else duration_ms
        suggest = [max(lo, segments[k][0] - PAD_BEFORE_MS), min(hi, segments[k][1] + PAD_AFTER_MS)]
    return {"durationMs": duration_ms, "peaksPerSecond": 1000 // FRAME_MS,
            "peaks": [round(float(p), 3) for p in peaks], "segments": segments, "suggest": suggest}


def trim(upload_id: str, start_ms: int, end_ms: int) -> dict:
    """Cut an upload to [start, end] (short fades so the cut doesn't click). Returns the new upload's id and length."""
    src = _upload_file(upload_id)
    total = duration_s(src, "upload") * 1000
    if not (0 <= start_ms < end_ms <= total + 50) or end_ms - start_ms < 1000:
        raise ImportError_("Keep at least one second of the audio.")
    dur = (end_ms - start_ms) / 1000
    out = paths.INBOX / f"upload-{uuid.uuid4().hex}.wav"
    # -ss before -i: the filters see the cut's own timeline, so the fade-out lands at its end (after -i it fell
    # `start` seconds early and silenced the tail)
    fade = f"afade=t=in:d={FADE_S},afade=t=out:st={max(0.0, dur - FADE_S):.3f}:d={FADE_S}"
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start_ms / 1000:.3f}", "-i", str(src), "-t", f"{dur:.3f}",
                        "-vn", "-af", fade, "-c:a", "pcm_s16le", str(out)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=_fresh_env())
    if p.returncode != 0:
        out.unlink(missing_ok=True)
        raise ImportError_("The audio couldn't be cut.")
    src.unlink(missing_ok=True)
    return {"upload": out.stem, "seconds": round(duration_s(out, "upload"), 1)}


def upload_path(upload_id: str) -> Path:
    """An upload's file, for listening to it on the import page."""
    return _upload_file(upload_id)


def _upload_file(upload_id: str) -> Path:
    found = list(paths.INBOX.glob(f"{upload_id}.*")) if UPLOAD_ID.match(upload_id) else []
    if not found:
        raise ImportError_("That audio upload is gone: choose the file (or record) again.")
    return found[0]


def english_lines_option(value) -> bool | None:
    """The import page's "English under each line" choice: true / false, or absent / "auto" = detect."""
    if value in (None, "", "auto"):
        return None
    if isinstance(value, bool):
        return value
    raise ImportError_("englishLines must be true, false or auto")


def check(text: str, language: str = "he", english_lines: bool | None = None) -> dict:
    """What the pasted lyrics contain (counts only) and what would stop processing."""
    if language not in LANGUAGES:
        raise ImportError_("language must be he (Hebrew) or es (Spanish)")
    sections = lyrics_mod.parse(text, language, english_lines)
    s = lyrics_mod.summary(sections, language)
    problems = []
    if s["lyricLines"] == 0:
        problems.append(f"No {LANGUAGES[language]} lines found.")
    return {**s, "language": language, "problems": problems}


def _fresh_env() -> dict:
    """PATH from the registry: a server started from an old shell may not see ffmpeg/node installed later."""
    env = dict(os.environ)
    if sys.platform == "win32" and not env.get("KARAOKE_DESKTOP"):
        import winreg
        parts = []
        for root, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                          (winreg.HKEY_CURRENT_USER, "Environment")):
            try:
                with winreg.OpenKey(root, key) as k:
                    parts.append(os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]))
            except OSError:
                pass
        env["PATH"] = ";".join(parts + [env.get("PATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _unique_slug(title: str) -> str:
    base = slugify(title) if title and re.search(r"[A-Za-z0-9]", title) else "song-" + datetime.now().strftime("%Y%m%d-%H%M")
    base = base[:72].rstrip("-")
    if PureWindowsPath(base).is_reserved():
        base = "song-" + base
    slug, n = base, 2
    while (paths.SONGS / slug).exists() or any(paths.INBOX.glob(f"{slug}.*")):
        slug, n = f"{base}-{n}", n + 1
    return slug


def status() -> dict | None:
    with _lock:
        return json.loads(json.dumps(_job)) if _job else None


def start(url: str, text: str, title: str = "", artist: str = "", model: str = "", upload: str = "",
          language: str = "he", english_lines: bool | None = None, mode: str = "automatic") -> dict:
    """Start an import from a YouTube `url`, or from an `upload` id (then `url` is ignored)."""
    global _job
    if mode not in ("manual", "automatic"):
        raise ImportError_("Choose manual or automatic timing.")
    audio = _upload_file(upload) if upload else None
    if audio is None:
        if mode == "manual" or os.environ.get("KARAOKE_DESKTOP"):
            raise ImportError_("Choose an audio file first.")
        host = urlparse(url.strip()).hostname or ""
        if host.lower() not in YOUTUBE_HOSTS:
            raise ImportError_("Paste a YouTube link (youtube.com or youtu.be).")
    summary = check(text, language, english_lines)
    if summary["problems"]:
        raise ImportError_(" ".join(summary["problems"]))
    if mode == "automatic" and os.environ.get("KARAOKE_DESKTOP"):
        from . import desktop_models
        if not desktop_models.status(language)["automaticReady"]:
            raise ImportError_("Set up automatic timing for this language, or choose to set the timing yourself.")
    with _lock:
        if _job and _job["state"] == "running":
            raise ImportError_("Another song is still being processed; wait for it to finish.")
        slug = _unique_slug(title)
        steps = ["upload", "ingest", "assemble"] if mode == "manual" else ["upload", *STAGES] if audio else STEPS
        _job = {"slug": slug, "state": "running", "error": None, "note": None, "startedAt": time.time(), "lyrics": summary,
                "steps": [{"name": n, "state": "waiting", "seconds": None} for n in steps]}
    if mode == "manual":
        thread = threading.Thread(target=_run_manual, args=(slug, text, title.strip(), artist.strip(), audio,
                                                            language, english_lines), daemon=True)
    else:
        thread = threading.Thread(target=_run, args=(slug, url.strip(), text, title.strip(), artist.strip(),
                                                     model.strip(), audio, language, english_lines), daemon=True)
    thread.start()
    return status()


def _run_manual(slug: str, text: str, title: str, artist: str, upload: Path, language: str, english_lines: bool | None):
    _set("upload", "done", 0.0)
    try:
        desktop_songs.make_draft(slug, upload, text, title, artist, language, english_lines, _set)
    except (StageError, ValueError) as exc:
        _set(exc.stage if isinstance(exc, StageError) else "assemble", "failed", error=str(exc))
        return
    except (OSError, subprocess.SubprocessError):
        _set("ingest", "failed", error="The recording could not be prepared. Check the file and available disk space, then try again.")
        return
    # The finished song contains its own copy of the recording. A failed import leaves the upload available to retry.
    try:
        upload.unlink(missing_ok=True)
    except OSError:
        pass  # old uploads are also cleaned up by new_upload()
    with _lock:
        _job["state"] = "done"


def _set(name: str, state: str, seconds: float | None = None, error: str | None = None):
    with _lock:
        for s in _job["steps"]:
            if s["name"] == name:
                s["state"], s["seconds"] = state, seconds
        if error:
            _job["state"], _job["error"] = "failed", {"step": name, "message": error}


def _run(slug: str, url: str, text: str, title: str, artist: str, model: str, upload: Path | None = None,
         language: str = "he", english_lines: bool | None = None):
    env = _fresh_env()
    if model:
        env["KARAOKE_TRANSLATE_MODEL"] = model  # read by the translate stage in the pipeline process
    try:
        if upload:
            # 1. the uploaded audio is already in the inbox: give it the song's name
            audio = upload.rename(paths.INBOX / f"{slug}{upload.suffix}")
            yt_title = ""
            _set("upload", "done", 0.0)
        else:
            audio, yt_title = _download(slug, url, env)
            if audio is None:
                return
        _pipeline(slug, audio, text, title or yt_title, artist, env, language, english_lines)
    except subprocess.TimeoutExpired:
        _set("download", "failed", error=f"Download took longer than {DOWNLOAD_TIMEOUT_S // 60} minutes")
    except Exception as e:  # report without leaking text
        msg = str(e)
        with _lock:
            step = next((s["name"] for s in _job["steps"] if s["state"] == "running"), _job["steps"][0]["name"])
        _set(step, "failed", error=f"{type(e).__name__}: {msg[:300]}")


def _download(slug: str, url: str, env: dict) -> tuple[Path | None, str]:
    """yt-dlp into the inbox. Returns (audio path, YouTube title), or (None, "") after marking the step failed."""
    # title printed before download, file path after it is moved into place
    _set("download", "running")
    t0 = time.perf_counter()
    paths.INBOX.mkdir(exist_ok=True)
    cookies = ["--cookies", str(paths.YT_COOKIES)] if paths.YT_COOKIES.exists() else []
    p = subprocess.run(
        # No conversion: YouTube's own stream is kept as it is (WebM/Opus or M4A/AAC), so it isn't compressed twice.
        [sys.executable, "-m", "yt_dlp", "--no-playlist", "--js-runtimes", "node", "-f", "bestaudio/best", *cookies,
         "-o", str(paths.INBOX / f"{slug}.%(ext)s"), "--no-simulate",
         "-O", "before_dl:%(title)s", "-O", "after_move:filepath", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=DOWNLOAD_TIMEOUT_S)
    out = [ln for ln in p.stdout.splitlines() if ln.strip()]
    audio = paths.INBOX / out[-1].strip() if out else None
    if p.returncode != 0 or audio is None or not audio.is_file():
        if any(b in p.stderr for b in BLOCKED):
            _set("download", "failed", error=BLOCKED_MESSAGE + (
                " (Cookies are loaded but YouTube still refused: export fresh ones.)" if cookies else ""))
        else:
            err = next((ln for ln in reversed(p.stderr.splitlines()) if "ERROR" in ln), p.stderr.strip()[-300:] or "no output")
            _set("download", "failed", error=f"Download failed: {err[:300]}")
        return None, ""
    _set("download", "done", round(time.perf_counter() - t0, 1))
    return audio, out[0].strip() if len(out) > 1 else ""


def _pipeline(slug: str, audio: Path, text: str, title: str, artist: str, env: dict, language: str = "he",
              english_lines: bool | None = None):
    # lyrics next to the audio in the inbox, then the pipeline (GPU freed first: the editor's breakdown model
    # may still be loaded, and Demucs needs the memory)
    translate._unload(translate.load_settings())
    lyrics_path = paths.INBOX / f"{slug}.txt"
    lyrics_path.write_text(text, encoding="utf-8")
    eng = {None: "auto", True: "yes", False: "no"}[english_lines]
    python = sys.executable
    if os.environ.get("KARAOKE_DESKTOP"):
        from . import desktop_models
        python = str(desktop_models.python_for(language))
        env.update(desktop_models.worker_env(language))
    proc = subprocess.Popen([python, "-m", "karaoke.cli", "add", str(audio), str(lyrics_path), "--slug", slug,
                             "--language", language, "--english-lines", eng],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                            errors="replace", env=env, cwd=str(paths.ROOT))
    current = STAGES[0]
    _set(current, "running")
    failed = None
    for line in proc.stdout:
        if m := STAGE_LINE.match(line.strip()):
            _set(m.group(2), "done", float(m.group(3)))
            if m.group(2) == "translate" and "skipped=" in line:  # no English made: say why on the page
                with _lock:
                    _job["note"] = "English not added: " + line.split("skipped=", 1)[1].strip()[:300]
            i = int(m.group(1))
            if i < len(STAGES):
                current = STAGES[i]
                _set(current, "running")
        elif m := FAIL_LINE.match(line.strip()):
            failed = (m.group(1), m.group(2))
    proc.wait()
    if failed or proc.returncode != 0:
        step, msg = failed or (current, f"pipeline exited with code {proc.returncode}")
        return _set(step, "failed", error=msg)

    # title / artist, and the permission record (kept if one exists)
    folder = paths.SONGS / slug
    doc = load(folder)
    doc["song"]["title"] = title or slug
    doc["song"]["artist"] = artist
    save(folder, doc)
    if not (permissions.all_records().get(slug)):
        permissions.save(slug, {"status": "Not asked", "artist": artist})
    with _lock:
        _job["state"] = "done"
