"""Prepare one recording in a private directory. The UI owns publication and cleanup."""
import json
import re
import sys
import time
from pathlib import Path

from . import lyrics, paths, stages


def subtitle_cues(text):
    """Read SRT and WebVTT cue boundaries, retaining repeated lyric lines."""
    from html import unescape
    stamp = r"(?:\d+:)?[0-5]\d:[0-5]\d[.,]\d{3}"

    def millis(value):
        fields = value.replace(",", ".").split(":")
        return round(sum(float(part) * 60 ** i for i, part in enumerate(reversed(fields))) * 1000)

    cues = []
    for block in re.split(r"\n\s*\n", text.strip().replace("\r", "")):
        rows = block.splitlines()
        for i, row in enumerate(rows):
            if "-->" not in row:
                continue
            match = re.fullmatch(rf"({stamp})\s+-->\s+({stamp})(?:\s+.*)?", row.strip())
            if not match:
                raise ValueError("Check the subtitle timestamps.")
            start, end = map(millis, match.groups())
            line = unescape(re.sub("<[^>]*>", "", " ".join(rows[i + 1:]))).strip()
            if not line or end <= start or (cues and start < cues[-1][1]):
                raise ValueError("Use subtitles with non-overlapping lines and valid times.")
            cues.append((start, end, line))
            break
    return cues


def report(area, message):
    tmp = area / "progress.tmp"
    tmp.write_text(message, encoding="utf8")
    tmp.replace(area / "progress")


def recognized(song):
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"

    def transcribe(device):
        model = stages._load_whisper(device, song.language)
        result = model.transcribe(str(song.audio / "vocals.wav"), language=song.language, word_timestamps=True, verbose=None)
        return [[w for w in segment.words if w.word.strip()] for segment in result.segments]

    try:
        rows = transcribe(device)
    except RuntimeError:
        if device == "cpu":
            raise
        rows = transcribe("cpu")
    rows = [row for row in rows if row]
    if not rows:
        raise ValueError("No sung words were detected. Check the recording and selected language.")
    section = lyrics.Section(label="Verse 1", lines=[[w.word.strip() for w in row] for row in rows], english=[""] * len(rows))
    stages.set_lyrics(song, [section])
    for line, row in zip(song.lines, rows):
        for word, source in zip(line["words"], row):
            confidence = min(1., max(0., float(source.probability or 0)))
            word.update(startMs=round(source.start * 1000), endMs=round(source.end * 1000), confidence=confidence)
            if confidence < stages.LOW_CONFIDENCE:
                word["flags"].append("low-confidence")
    stages._enforce_timing(list(song.words()), song.duration_ms)


def translate_lines(song):
    missing = [line for line in song.lines if not line["english"]]
    if not missing:
        return
    import torch
    from transformers import MarianMTModel, MarianTokenizer
    folder = paths.ROOT / "models" / (song.language + "-en")
    if not folder.is_dir():
        raise ValueError("The offline English model is missing from this installation.")
    tok = MarianTokenizer.from_pretrained(str(folder), local_files_only=True)
    model = MarianMTModel.from_pretrained(str(folder), local_files_only=True).eval()
    with torch.inference_mode():
        for line in missing:
            text = " ".join(w["plain"] for w in line["words"])
            output = model.generate(**tok(text, return_tensors="pt"), max_new_tokens=256)
            line["english"] = tok.decode(output[0], skip_special_tokens=True).strip()
            if not line["english"]:
                raise ValueError("The English model returned an empty line.")


def prepare(area):
    args = json.loads((area / "request.json").read_text("utf8"))
    from . import desktop_models
    if desktop_models.bundled():
        report(area, "Checking the installed models…")
        if desktop_models._model_hub(args["language"]) != paths.ROOT / "models/hub":
            raise ValueError("The installed timing models are incomplete. Reinstall the application and retry.")
    recording = Path(args["audio"])
    report(area, "Preparing audio…")
    start, end = args["start"], args["end"]
    if end and end <= start:
        raise ValueError("The end must be after the start.")
    converted = area / "selection.wav"
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(recording), "-ss", str(start)]
    if end:
        cmd.extend(["-t", str(end-start)])
    stages._run(cmd + ["-vn", "-ac", "2", "-ar", "44100", str(converted)], "ingest", "reading your selection")
    song = stages.Song(args["slug"], area / "song", converted, area / "lyrics.txt", args["title"], args["language"], args["bilingual"])
    stages.ingest_audio(song)
    report(area, "Separating the singer and backing…")
    stages.separate(song)
    text = args["lyrics"].strip()
    report(area, "Finding the sung lines…")
    if "-->" in text:
        offset = round(start * 1000)
        cues = [(max(0, a-offset), min(song.duration_ms, b-offset), line) for a,b,line in subtitle_cues(text)
                if b > offset and a < offset + song.duration_ms]
        if not cues:
            raise ValueError("No subtitle lines fall within this selection.")
        rows = [line.split() for _, _, line in cues]
        stages.set_lyrics(song, [lyrics.Section(label="Verse 1", lines=rows, english=[""] * len(rows))])
        for line, (a,b,_) in zip(song.lines, cues):
            n = len(line["words"])
            if b-a < n:
                raise ValueError("A subtitle line is too short for its words.")
            for i, word in enumerate(line["words"]):
                word.update(startMs=a+(b-a)*i//n, endMs=a+(b-a)*(i+1)//n, flags=["low-confidence"])
    elif text:
        sections = lyrics.parse(text, song.language, song.english_lines)
        if not lyrics.lyric_line_count(sections, song.language):
            raise ValueError("Check the lyrics and selected language.")
        stages.set_lyrics(song, sections)
        for line, pronunciation in zip(song.lines, (p for section in sections for p in section.pronunciation)):
            if pronunciation:
                line["pronunciation"] = pronunciation
        stages.align(song)
    else:
        recognized(song)
    report(area, "Preparing English…")
    if song.language == "he" or (paths.ROOT / "models/es-en").is_dir():
        translate_lines(song)
    else:
        stages.translate_stage(song)
    if song.language == "he":
        from .pronunciation import add_pronunciation
        add_pronunciation(song.lines, paths.ROOT / "models/pronunciation/phonikud-1.0.int8.onnx")
    stages.assemble(song, artist=args["artist"])


if __name__ == "__main__":
    area = Path(sys.argv[1])
    try:
        # The parent establishes process-tree ownership before we may launch a decoder.
        deadline = time.monotonic() + 20
        while not (area / "ready").exists():
            if time.monotonic() > deadline:
                raise ValueError("The recording job did not start. Please try again.")
            time.sleep(0.05)
        prepare(area)
    except Exception as exc:
        report(area, str(exc) if isinstance(exc, (ValueError, stages.StageError)) else "The offline processing tools could not finish this recording.")
        sys.exit(1)
