"""Render the desktop downloads with the audio/video tools included in the app."""
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path

from . import export, subtitles


def _ffmpeg(work: Path, args: list[str]):
    p = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args],
                       cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if p.returncode:
        raise export.ExportError("The video could not be created. Check free space, then try a shorter excerpt.")


def _event(start, end, style, text):
    return f"Dialogue: 0,{subtitles._ass_time(start)},{subtitles._ass_time(end)},{style},,0,0,0,,{text}"


def _recording_credit(song):
    credit = song["song"].get("recordingCredit")
    if not credit:
        return ""
    return "\n".join(credit[key] for key in ("title", "artist", "source", "license", "licenseUrl", "changes"))


def _media_credit(song):
    credit = _recording_credit(song)
    return ["-metadata", "comment=" + credit] if credit else []


def _clip_lines(song, clip):
    lines = []
    active = False
    for line in song["lines"]:
        picked = []
        for word in line["words"]:
            if word["id"] == clip["fromWord"]:
                active = True
            if active:
                picked.append(word)
            if word["id"] == clip["toWord"]:
                active = False
        if picked:
            lines.append({**line, "words": picked})
    return lines


def _lesson(work, folder, song, drill, style, output):
    parts, events, silence = [], [], {}
    head = subtitles.ass({**song, "lines": []}, style, 0, 1)
    clock = 0

    def quiet(ms):
        if ms not in silence:
            name = f"silence-{ms}.wav"
            _ffmpeg(work, ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(ms / 1000), name])
            silence[ms] = name
        return silence[ms]

    for i, step in enumerate(drill["steps"]):
        if step["type"] == "card":
            length = step["durationMs"]
            parts.append(quiet(length))
            events.append(_event(clock, clock + length, "En", r"{\an5\pos(960,540)\fs68}" + subtitles.ass_text(step["text"])))
            clock += length
            continue
        clip = next(c for c in song["clips"] if c["id"] == step["clip"])
        start, end = export._clip_range(song, clip)
        speed = step["speed"]
        length = round((end - start) / speed)
        name = f"clip-{i}.wav"
        track = folder / "audio" / (step["track"] + ".wav")
        if not track.is_file():
            raise export.ExportError("A recording used by this drill is missing. Choose another track in the drill.")
        _ffmpeg(work, ["-ss", str(start / 1000), "-t", str((end - start) / 1000), "-i", str(track), "-vn",
                       "-af", f"atempo={speed},apad,atrim=duration={length / 1000}", "-ac", "2", "-ar", "44100", name])
        lines = _clip_lines(song, clip)
        shown = {**song, "lines": lines}
        for _ in range(step["repeats"]):
            parts.append(name)
            for line, a, b in subtitles.cues(shown, start, end):
                at, until = clock + round(a / speed), clock + round(b / speed)
                if "lyrics" in step["tiers"]:
                    timed = {**line, "words": [{**w, "startMs": clock + round((w["startMs"] - start) / speed),
                                                 "endMs": clock + round((w["endMs"] - start) / speed)} for w in line["words"]]}
                    events.append(_event(at, until, "Lyrics", subtitles._karaoke(song, timed, at, style["showNiqqud"])))
                if "en" in step["tiers"] and line["english"]:
                    events.append(_event(at, until, "En", subtitles.ass_text(line["english"])))
            clock += length
            if step["yourTurn"]:
                parts.append(quiet(length))
                held = [subtitles.tier_text(song, line, tier, style["showNiqqud"])
                        for line in lines for tier in step["tiers"]]
                prompt = "\n".join(["Your turn", *filter(None, held)])
                events.append(_event(clock, clock + length, "En", r"{\an5\pos(960,540)}" + subtitles.ass_text(prompt)))
                clock += length
    (work / "captions.ass").write_text(head + "\n".join(events) + "\n", encoding="utf-8-sig")
    (work / "parts.txt").write_text("".join(f"file '{name}'\n" for name in parts), encoding="ascii")
    _ffmpeg(work, ["-f", "lavfi", "-i", "color=c=0x101d2a:s=1920x1080:r=30", "-f", "concat", "-safe", "1",
                   "-i", "parts.txt", "-vf", "ass=captions.ass", "-t", str(clock / 1000), "-c:v", "libx264",
                   "-preset", "veryfast", "-threads", "4", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
                   *_media_credit(song), str(output)])


def create(slug: str, kind: str, body: dict) -> tuple[Path, str]:
    folder, song = export.load_song(slug)
    style = export.load_preset("default")
    if kind == "lesson":
        drill = next((d for d in song["drills"] if d["id"] == body.get("drill")), None)
        if drill is None or not any(s["type"] == "card" for s in drill["steps"]):
            raise export.ExportError("Choose a drill that includes a teaching card.")
        spans, runtime = export.lesson_plays(song, drill), export.lesson_duration_ms(song, drill)
    elif kind in ("overlay", "subtitles"):
        try:
            a, b = export._range(song, body.get("from"), body.get("to"))
        except (TypeError, ValueError, OverflowError):
            raise export.ExportError("Enter a start and end time in seconds within the song.") from None
        spans, runtime = [(a, b, b - a)], None
    else:
        raise export.ExportError("Choose a lesson video, caption overlay or subtitles.")
    guard = export._check_guard(slug, song, spans, runtime, str(body.get("reason") or ""))
    suffix = {"lesson": ".mp4", "overlay": ".mov", "subtitles": ".zip"}[kind]
    exports = folder / "exports"
    exports.mkdir(exist_ok=True)
    output = exports / f"{kind}-{uuid.uuid4().hex}{suffix}"
    filename = f"{slug}-{kind}{suffix}"
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            work = Path(tmpdir)
            if kind == "lesson":
                _lesson(work, folder, song, drill, style, output)
            else:
                ass = subtitles.ass(song, style, a, b)
                if kind == "subtitles":
                    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
                        z.writestr(f"{slug}.ass", ass.encode("utf-8-sig"))
                        credit = _recording_credit(song)
                        if credit:
                            z.writestr("Recording credits.txt", credit.encode("utf-8"))
                        for tier in export.TIERS:
                            srt = subtitles.srt(song, tier, a, b, style["showNiqqud"])
                            if srt:
                                z.writestr(f"{slug}.{tier}.srt", srt.encode("utf-8-sig"))
                else:
                    (work / "captions.ass").write_text(ass, encoding="utf-8-sig")
                    _ffmpeg(work, ["-f", "lavfi", "-i", "color=c=black@0:s=1920x1080:r=30,format=rgba",
                                   "-vf", "ass=captions.ass:alpha=1", "-t", str((b - a) / 1000), "-an",
                                   "-c:v", "prores_ks", "-profile:v", "4", "-threads", "4", "-pix_fmt", "yuva444p10le",
                                   *_media_credit(song), str(output)])
        export._log(slug, "subs" if kind == "subtitles" else kind, output, guard)
        return output, filename
    except BaseException:
        output.unlink(missing_ok=True)
        raise
