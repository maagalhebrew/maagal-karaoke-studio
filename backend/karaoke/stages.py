"""The pipeline stages (STAGES). Each writes into the song folder and ends with a checkpoint;
a failed checkpoint raises StageError naming the stage.

Privacy (CLAUDE.md rule 5): nothing here may print or return lyric text — only counts and ids.
"""
import gc
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import lyrics as lyrics_mod
from .hebrew import has_hebrew, strip_niqqud
from .models import whisper_for
from .songfile import VERSION, load, save
from .text import LANGUAGES

# Models are cached in M0; staying offline guarantees lyrics never leave the machine.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

AUDIO_TYPES = {".mp3", ".m4a", ".wav", ".mp4", ".webm", ".opus", ".ogg"}  # .mp4: video is dropped, audio kept
SILENT_DB = -60.0  # mean volume below this = no usable audio
TARGET_LUFS = -14.0  # every song is brought to about this loudness with one fixed gain...
PEAK_LIMIT_DB = -1.0  # ...unless that would push its true peak above this; then it ends up a little quieter
MIN_WORD_MS = 40
LONG_GAP_MS = 4000  # a gap this long inside one line usually means lyrics are missing (e.g. an unlisted repeat)
LOW_CONFIDENCE = 0.5
MIN_MEDIAN_CONFIDENCE = 0.3  # below this the whole alignment failed (e.g. latched onto an instrumental intro)
HEARD_GAP_MS = 3000  # free transcription heard no words this long (between heard words) = an instrumental passage
ANCHOR_RUN = 3  # consecutive lyric words matching the transcription before its timing is trusted
LENGTH_TOLERANCE_S = 0.1

STAGES = ["ingest", "separate", "translate", "align", "assemble"]


class StageError(Exception):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


@dataclass
class Song:
    slug: str
    folder: Path
    audio_src: Path
    lyrics_src: Path
    title: str = ""
    language: str = "he"  # "he" or "es"
    english_lines: bool | None = None  # each lyric line followed by its English? None = detect (Hebrew only)
    duration_ms: int = 0
    sections: list = field(default_factory=list)
    lines: list[dict] = field(default_factory=list)  # song.json "lines"
    stage_log: list[dict] = field(default_factory=list)

    @property
    def audio(self) -> Path:
        return self.folder / "audio"

    def words(self):
        for line in self.lines:
            yield from line["words"]


# --- helpers ------------------------------------------------------------------
def _run(cmd: list[str], stage: str, what: str) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        tail = (p.stderr or p.stdout).strip().splitlines()[-1:] or ["no output"]
        raise StageError(stage, f"{what} failed (exit {p.returncode}): {tail[0][:300]}")
    return p


def _normalising_gain_db(path: Path, track: int) -> float:
    """The one gain that brings a track to TARGET_LUFS, held back if its true peak would pass PEAK_LIMIT_DB."""
    p = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", f"0:a:{track}", "-vn",
              "-af", "loudnorm=print_format=json", "-f", "null", "-"], "ingest", "loudness measurement")
    found = re.findall(r"\{[^{}]*\}", p.stderr)
    if not found:
        raise StageError("ingest", "loudness measurement gave no result")
    measured = json.loads(found[-1])
    loudness, peak = float(measured["input_i"]), float(measured["input_tp"])
    gain = min(TARGET_LUFS - loudness, PEAK_LIMIT_DB - peak)
    return gain if math.isfinite(gain) else 0.0


def duration_s(path: Path, stage: str) -> float:
    p = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
             stage, f"reading duration of {path.name}")
    try:
        return float(p.stdout.strip())
    except ValueError:
        raise StageError(stage, f"{path.name} has no readable duration") from None


def _audio_track_volumes(path: Path) -> list[float]:
    """Mean volume (dB) of each audio track. Recordings (e.g. OBS) can carry several, some silent."""
    p = _run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
              "-of", "csv=p=0", str(path)], "ingest", "listing audio tracks")
    count = len(p.stdout.split())
    volumes = []
    for i in range(count):
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", f"0:a:{i}",
                            "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        m = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", r.stderr)
        volumes.append(float(m.group(1)) if m and m.group(1) != "-inf" else float("-inf"))
    return volumes


def _free_gpu():
    import torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _flag(word: dict, flag: str):
    if flag not in word["flags"]:
        word["flags"].append(flag)


# --- 1. ingest ------------------------------------------------------------------
def ingest(song: Song) -> dict:
    try:
        text = song.lyrics_src.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise StageError("ingest", "lyrics file is not UTF-8 text; re-save it as UTF-8 and retry") from None
    sections = lyrics_mod.parse(text, song.language, song.english_lines)
    lyric_lines = lyrics_mod.lyric_line_count(sections, song.language)
    if lyric_lines == 0:
        lang = LANGUAGES[song.language]
        raise StageError("ingest", f"lyrics file has no {lang} lines (it is empty or contains no {lang})")
    if song.audio_src.suffix.lower() not in AUDIO_TYPES:
        raise StageError("ingest", f"audio must be MP3, M4A, MP4, WAV, WebM, Opus or OGG, got '{song.audio_src.suffix}'")
    if duration_s(song.audio_src, "ingest") <= 0:
        raise StageError("ingest", "audio file decodes to zero length")
    volumes = _audio_track_volumes(song.audio_src)
    if not volumes:
        raise StageError("ingest", "file has no audio track")
    track = max(range(len(volumes)), key=lambda i: volumes[i])
    if volumes[track] < SILENT_DB:
        raise StageError("ingest", f"audio is silent (loudest of {len(volumes)} track(s) is {volumes[track]:.0f} dB)")

    song.audio.mkdir(parents=True, exist_ok=True)
    original = song.audio / "original.wav"
    # One fixed gain for the whole song: unlike single-pass loudnorm, it can't ride the volume and flatten the song.
    gain = _normalising_gain_db(song.audio_src, track)
    _run(["ffmpeg", "-v", "error", "-y", "-i", str(song.audio_src), "-map", f"0:a:{track}", "-vn",
          "-af", f"volume={gain:.2f}dB", "-ar", "44100", "-ac", "2", str(original)],
         "ingest", "audio conversion")
    shutil.copyfile(song.lyrics_src, song.folder / "lyrics.txt")

    seconds = duration_s(original, "ingest")
    if seconds <= 0:
        raise StageError("ingest", "converted audio has no duration")
    song.duration_ms = round(seconds * 1000)
    song.sections = sections

    n = 0
    for section in sections:
        for tokens, english in zip(section.lines, section.english):
            n += 1
            song.lines.append({"id": f"L{n}", "english": english, "words": [
                {"id": f"L{n}W{k}", "plain": t, "startMs": 0, "endMs": 0, "confidence": 0.0, "flags": []}
                for k, t in enumerate(tokens, 1)]})  # as written: vowel points, if given, are kept
    return {"durationMs": song.duration_ms, "audioTrack": f"{track + 1} of {len(volumes)}", "sections": len(sections), "lines": n,
            "lyricLines": lyric_lines, "language": song.language, "words": sum(1 for _ in song.words()),
            "linesWithEnglish": sum(bool(line["english"]) for line in song.lines)}


# --- 2. separate ----------------------------------------------------------------
def separate(song: Song) -> dict:
    original = song.audio / "original.wav"
    tmp = song.folder / "_demucs"
    shutil.rmtree(tmp, ignore_errors=True)
    # Demucs runs in its own process: when it exits, all its VRAM is released (rule 4).
    # --shifts 0: no random time shift, so the same song always gives the same stems. With the default random
    # shift, separation (and so alignment) varied run to run: median word confidence 0.74 / 0.49 / 0.74 on Hatikvah.
    base = [sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs", "--shifts", "0", "-o", str(tmp)]
    device = "cuda"
    try:
        _run(base + ["-d", "cuda", str(original)], "separate", "Demucs (GPU)")
    except StageError:
        device = "cpu"  # rule 4 fallback
        _run(base + ["-d", "cpu", str(original)], "separate", "Demucs (CPU fallback)")
    out = tmp / "htdemucs" / original.stem
    for src, dst in (("vocals.wav", "vocals.wav"), ("no_vocals.wav", "instrumental.wav")):
        if not (out / src).exists():
            raise StageError("separate", f"Demucs did not produce {src}")
        (out / src).replace(song.audio / dst)
    shutil.rmtree(tmp, ignore_errors=True)

    want = song.duration_ms / 1000
    lengths = {}
    for name in ("vocals.wav", "instrumental.wav"):
        got = duration_s(song.audio / name, "separate")
        if abs(got - want) > LENGTH_TOLERANCE_S:
            raise StageError("separate", f"{name} is {got:.2f}s, original is {want:.2f}s (> {LENGTH_TOLERANCE_S}s apart)")
        lengths[name] = round(got, 3)
    return {"device": device, "vocalsS": lengths["vocals.wav"], "instrumentalS": lengths["instrumental.wav"]}


# --- 3. translate ---------------------------------------------------------------
def translate_stage(song: Song) -> dict:
    """English for lines that have none, from a local model (Ollama). A convenience, not a checkpoint:
    if the model is off or unreachable the song still completes with the English left empty."""
    from . import translate
    todo = [line for line in song.lines if not line["english"].strip()]
    settings = translate.load_settings()
    if not todo:
        return {"translated": 0, "alreadyHadEnglish": len(song.lines)}
    if not settings["enabled"]:
        return {"translated": 0, "skipped": "turned off in data/translate.json"}
    try:
        english = translate.translate_lines([" ".join(w["plain"] for w in line["words"]) for line in todo], settings,
                                            song.language)
    except translate.TranslateError as e:
        return {"translated": 0, "skipped": str(e)}
    for line, en in zip(todo, english):
        line["english"] = en
    details = {"model": settings["model"], "translated": sum(1 for en in english if en),
               "alreadyHadEnglish": len(song.lines) - len(todo)}
    if missing := sum(1 for en in english if not en):
        details["skipped"] = f"{missing} line(s) left without English (the model's answer didn't match)"
    return details


def translate_song(folder: Path, model: str | None = None, redo: bool = False) -> dict:
    """Fill in missing English for an existing song (`karaoke translate`), or redo every line (`--all`);
    previous song.json is backed up."""
    doc = load(folder)
    if redo:
        for line in doc["lines"]:
            line["english"] = ""
    if model:
        os.environ["KARAOKE_TRANSLATE_MODEL"] = model
    song = Song(slug=folder.name, folder=folder, audio_src=folder, lyrics_src=folder, lines=doc["lines"],
                language=doc["song"]["language"])
    details = translate_stage(song)
    if details.get("translated"):
        save(folder, doc)
    return details


# --- 4. align -------------------------------------------------------------------
def _key(text: str) -> str:
    return "".join(ch for ch in strip_niqqud(text) if ch.isalnum()).lower()


def _load_whisper(device: str, language: str):
    import torch  # noqa: F401  (loads torch's CUDA 12 DLLs that CTranslate2 reuses)
    import stable_whisper
    return stable_whisper.load_faster_whisper(whisper_for(language), device=device,
                                              compute_type="float16" if device == "cuda" else "int8")


def _heard_words(model, vocals: Path, language: str) -> list[tuple[str, int, int, str]]:
    """Free transcription (no lyrics given): where Whisper hears words, as (key, startMs, endMs, text).
    Its words may be wrong; its timing is good."""
    result = model.transcribe(str(vocals), language=language, verbose=None, word_timestamps=True)
    return [(k, round(w.start * 1000), round(w.end * 1000), w.word.strip())
            for s in result.segments for w in s.words if (k := _key(w.word))]


def save_heard(folder: Path, heard: list) -> None:
    """Keep the transcription for the editor's missing/extra word suggestions (stays in the song folder)."""
    (folder / "heard.json").write_text(json.dumps([list(h) for h in heard], ensure_ascii=False), encoding="utf-8")


def _whisper_align(vocals: Path, text: str, device: str, language: str):
    """Forced alignment of the lyrics, plus the free transcription to check it against (one model load)."""
    model = _load_whisper(device, language)
    try:
        # verbose=None: stable-ts would otherwise print the lyrics it aligns (rule 5).
        result = model.align(str(vocals), text, language=language, original_split=True, verbose=None)
        if result is None:
            raise StageError("align", "stable-ts could not align the lyrics to the vocals")
        model.refine(str(vocals), result, verbose=None)
        return ([(w.word, w.start, w.end, w.probability) for w in result.all_words()],
                _heard_words(model, vocals, language))
    finally:
        del model
        _free_gpu()


def correct_from_transcript(words: list[dict], heard: list[tuple[str, int, int]]) -> int:
    """Forced alignment must place every lyric word, so across an instrumental passage it can pull lines into it.
    Move a word that sits where Whisper heard nothing for HEARD_GAP_MS+ to where it was heard, if it belongs to a
    run of ANCHOR_RUN+ lyric words matching the transcription; then re-space the words those moves overlap.
    Returns the number of words changed (flagged timing-adjusted)."""
    import difflib
    gaps = [(a[2], b[1]) for a, b in zip(heard, heard[1:]) if b[1] - a[2] >= HEARD_GAP_MS]
    in_gap = lambda ms: any(a < ms < b for a, b in gaps)  # noqa: E731
    mid = lambda start, end: (start + end) // 2  # noqa: E731
    matcher = difflib.SequenceMatcher(a=[_key(w["plain"]) for w in words], b=[h[0] for h in heard], autojunk=False)
    moved = set()
    for a, b, n in matcher.get_matching_blocks():
        if n < ANCHOR_RUN:
            continue
        for i in range(n):
            w, (start, end) = words[a + i], heard[b + i][1:3]
            if in_gap(mid(w["startMs"], w["endMs"])) and not in_gap(mid(start, end)):
                w["startMs"], w["endMs"] = start, end
                moved.add(a + i)
    if not moved:
        return 0

    def spread(run: list[int], left: int, right: int):
        step = max(MIN_WORD_MS, (right - left) // len(run))
        for k, i in enumerate(run):
            words[i]["startMs"], words[i]["endMs"] = left + k * step, left + (k + 1) * step

    # Words between moved ones keep their times unless they now overlap a moved word.
    changed = set(moved)
    order = sorted(moved)
    for prev, nxt in zip([None] + order, order + [None]):
        run = list(range(0 if prev is None else prev + 1, len(words) if nxt is None else nxt))
        if not run:
            continue
        lo = 0 if prev is None else words[prev]["endMs"]
        hi = None if nxt is None else words[nxt]["startMs"]
        early = [i for i in run if words[i]["startMs"] < lo]
        late = [i for i in run if hi is not None and words[i]["endMs"] > hi and i not in early]
        ok = [i for i in run if i not in early and i not in late]
        if early:
            right = words[ok[0]]["startMs"] if ok else hi if hi is not None else lo + 300 * len(early)
            spread(early, lo, right)
        if late:
            spread(late, words[ok[-1]]["endMs"] if ok else words[early[-1]]["endMs"] if early else lo, hi)
        changed.update(early, late)
    for i in changed:
        _flag(words[i], "timing-adjusted")
    return len(changed)


def _map_times(words: list[dict], aligned: list[tuple]) -> None:
    """Give each lyric word the span of the aligned fragments covering its characters."""
    stream = [(ch, i) for i, a in enumerate(aligned) for ch in _key(a[0])]
    expected = "".join(_key(w["plain"]) for w in words)
    if "".join(ch for ch, _ in stream) != expected:
        raise StageError("align", f"aligned text does not match the lyrics ({len(stream)} vs {len(expected)} characters)")
    pos = 0
    for w in words:
        n = len(_key(w["plain"]))
        idx = sorted({i for _, i in stream[pos:pos + n]})
        pos += n
        w["startMs"] = round(min(aligned[i][1] for i in idx) * 1000)
        w["endMs"] = round(max(aligned[i][2] for i in idx) * 1000)
        w["confidence"] = round(min((aligned[i][3] or 0.0) for i in idx), 3)


def _enforce_timing(words: list[dict], duration_ms: int) -> int:
    """Make times monotonic with every word >= 40 ms. Returns the number of words adjusted."""
    times = []
    prev_end = 0
    for w in words:  # forward: no overlaps, minimum length
        start = max(w["startMs"], prev_end)
        end = max(w["endMs"], start + MIN_WORD_MS)
        times.append([start, end])
        prev_end = end
    limit = duration_ms
    for t in reversed(times):  # backward: pull words that ran past the end back inside the song
        t[1] = min(t[1], limit)
        t[0] = min(t[0], t[1] - MIN_WORD_MS)
        limit = t[0]
    adjusted = 0
    for w, (start, end) in zip(words, times):
        if (start, end) != (w["startMs"], w["endMs"]):
            adjusted += 1
            _flag(w, "timing-adjusted")
        w["startMs"], w["endMs"] = start, end
    return adjusted


def align(song: Song) -> dict:
    import torch
    words = list(song.words())
    text = "\n".join(" ".join(w["plain"] for w in line["words"]) for line in song.lines)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        aligned, heard = _whisper_align(song.audio / "vocals.wav", text, device, song.language)
    except (torch.OutOfMemoryError, RuntimeError) as e:
        if device == "cpu" or "out of memory" not in str(e).lower():
            raise
        device = "cpu"  # rule 4 fallback
        aligned, heard = _whisper_align(song.audio / "vocals.wav", text, device, song.language)
    _map_times(words, aligned)
    median = sorted(w["confidence"] for w in words)[len(words) // 2]
    if median < MIN_MEDIAN_CONFIDENCE:
        raise StageError("align", f"alignment failed: median word confidence {median:.2f} (< {MIN_MEDIAN_CONFIDENCE}). "
                                  "Check that the lyrics match what is sung and that vocals.wav contains the singing")
    save_heard(song.folder, heard)
    moved = correct_from_transcript(words, heard)
    adjusted = _enforce_timing(words, song.duration_ms)
    low = 0
    for w in words:
        if w["confidence"] < LOW_CONFIDENCE:
            _flag(w, "low-confidence")
            low += 1
    gaps = 0
    for line in song.lines:
        for a, b in zip(line["words"], line["words"][1:]):
            if b["startMs"] - a["endMs"] > LONG_GAP_MS:
                _flag(b, "long-gap")
                gaps += 1

    # Checkpoint
    prev_end = 0
    for w in words:
        if not (prev_end <= w["startMs"] < w["endMs"] <= song.duration_ms) or w["endMs"] - w["startMs"] < MIN_WORD_MS:
            raise StageError("align", f"word {w['id']} has invalid timing after adjustment")
        prev_end = w["endMs"]
    return {"device": device, "words": len(words), "medianConfidence": round(median, 2), "lowConfidence": low,
            "timingAdjusted": adjusted, "movedOutOfGaps": moved, "longGaps": gaps}


def transcribe_song(folder: Path) -> tuple[list, str]:
    """Free transcription of a song's vocals, saved as heard.json. One model load, freed after (rule 4)."""
    import torch
    language = load(folder)["song"]["language"]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = _load_whisper(device, language)
    try:
        heard = _heard_words(model, folder / "audio" / "vocals.wav", language)
    finally:
        del model
        _free_gpu()
    save_heard(folder, heard)
    return heard, device


def retime(folder: Path) -> dict:
    """Re-check an existing song's timing against a fresh transcription (`karaoke retime`).
    Only words sitting in an instrumental gap move, so hand-made timing edits elsewhere are kept."""
    doc = load(folder)
    words = [w for line in doc["lines"] for w in line["words"]]
    heard, device = transcribe_song(folder)
    before = {w["id"]: (w["startMs"], w["endMs"]) for w in words}
    moved = correct_from_transcript(words, heard)
    if moved:
        _enforce_timing(words, doc["song"]["durationMs"])
        save(folder, doc)  # previous song.json goes to backups\
    lines_moved = sum(1 for line in doc["lines"]
                      if any((w["startMs"], w["endMs"]) != before[w["id"]] for w in line["words"]))
    return {"device": device, "wordsHeard": len(heard), "wordsMoved": moved, "linesChanged": lines_moved}


# --- 5. assemble ------------------------------------------------------------------
REVIEW_GROUPS = {
    "timing": {"low-confidence", "timing-adjusted", "long-gap"},
}


def assemble(song: Song) -> dict:
    sections, n, line_no = [], 0, 0
    for s in song.sections:
        first = line_no + 1
        line_no += len(s.lines)
        n += 1
        sections.append({"id": f"S{n}", "kind": s.kind, "label": s.label,
                         "fromLine": f"L{first}", "toLine": f"L{line_no}"})
    doc = {
        "schema": VERSION,
        "song": {"id": song.slug, "title": song.title, "artist": "", "language": song.language, "permissionId": None,
                 "audio": {"original": "audio/original.wav", "vocals": "audio/vocals.wav",
                           "instrumental": "audio/instrumental.wav"},
                 "durationMs": song.duration_ms},
        "lines": song.lines, "sections": sections, "clips": [], "drills": [],
    }
    try:
        save(song.folder, doc)
    except ValueError as e:
        raise StageError("assemble", str(e)) from None

    flags = [{"word": w["id"], "type": f} for w in song.words() for f in w["flags"]]
    by_type = Counter(f["type"] for f in flags)
    review = {g: len({f["word"] for f in flags if f["type"] in types}) for g, types in REVIEW_GROUPS.items()}
    report = {
        "schema": VERSION, "song": song.slug,
        "stages": song.stage_log,
        "counts": {"lines": len(song.lines), "sections": len(sections),
                   "words": sum(1 for _ in song.words()),
                   "flaggedWords": len({f["word"] for f in flags}), "flagsByType": dict(by_type),
                   "wordsToReview": review},
        "flags": flags,
    }
    (song.folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"songJson": "song.json", "flaggedWords": report["counts"]["flaggedWords"], "wordsToReview": review}


RUNNERS = {"ingest": ingest, "separate": separate, "translate": translate_stage, "align": align, "assemble": assemble}


def leaks_lyrics(message: str, song: Song) -> bool:
    """True when a message may quote the lyrics (rule 5): it has Hebrew letters, or one of the song's words
    of 4+ letters (short words like "de" or "la" appear in ordinary error text)."""
    if has_hebrew(message):
        return True
    words = set(re.findall(r"\w{4,}", message.lower()))
    return any(_key(w["plain"]) in words for w in song.words() if len(_key(w["plain"])) >= 4)


def run(song: Song, on_stage=None) -> None:
    """Run all stages in order. on_stage(index, name, ok, seconds, details_or_error) is called after each."""
    for i, name in enumerate(STAGES, 1):
        t0 = time.perf_counter()
        try:
            details = RUNNERS[name](song)
        except StageError as e:
            secs = round(time.perf_counter() - t0, 1)
            song.stage_log.append({"stage": name, "ok": False, "seconds": secs})
            if on_stage:
                on_stage(i, name, False, secs, str(e))
            raise
        except Exception as e:  # unexpected: report without leaking lyric text
            msg = str(e)
            msg = "(message hidden: it may contain lyric text)" if leaks_lyrics(msg, song) else msg[:300]
            secs = round(time.perf_counter() - t0, 1)
            song.stage_log.append({"stage": name, "ok": False, "seconds": secs})
            if on_stage:
                on_stage(i, name, False, secs, f"{type(e).__name__}: {msg}")
            raise StageError(name, f"{type(e).__name__}: {msg}") from e
        secs = round(time.perf_counter() - t0, 1)
        song.stage_log.append({"stage": name, "ok": True, "seconds": secs})
        if on_stage:
            on_stage(i, name, True, secs, details)
