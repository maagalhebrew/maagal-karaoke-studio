"""Create a timing draft from local audio, or a fully timed built-in practice song."""
import tempfile
import wave
from pathlib import Path

import numpy as np

from . import lyrics, paths, stages
from .songfile import load, save


def staging_directory():
    # On the library volume so rename is atomic. The library walker only sees complete songs.
    parent = paths.SONGS / ".preparing"
    parent.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=parent)


def make_draft(slug: str, audio: Path, text: str, title: str, artist: str, language: str,
               english_lines: bool | None, on_stage) -> None:
    with staging_directory() as staging:
        root = Path(staging)
        source = root / "pasted-lyrics.txt"
        source.write_text(text, encoding="utf-8")
        song = stages.Song(slug, root / "prepared", audio, source, title or slug, language, english_lines)
        on_stage("ingest", "running")
        stages.ingest(song)
        on_stage("ingest", "done")
        on_stage("assemble", "running")
        words = list(song.words())
        if song.duration_ms < stages.MIN_WORD_MS * len(words):
            raise ValueError("The recording is too short for this many words. Choose a longer recording or fewer lines.")
        for i, word in enumerate(words):
            word["startMs"] = i * song.duration_ms // len(words)
            word["endMs"] = (i + 1) * song.duration_ms // len(words)
            word["flags"] = ["low-confidence"]
        stages.assemble(song, artist=artist, original_only=True)
        song.folder.rename(paths.SONGS / slug)
        on_stage("assemble", "done")


def add_sample() -> str:
    """An original eight-note ear-training exercise. Timings match the generated melody."""
    base = "karaoke-il-first-notes"
    slug = base
    n = 1
    while (paths.SONGS / slug).exists():
        if (paths.SONGS / slug / ".first-notes").is_file() and (paths.SONGS / slug / "song.json").is_file():
            return slug
        n += 1
        slug = f"{base}-{n}"
    with staging_directory() as staging:
        folder = Path(staging) / "prepared"
        song = stages.Song(slug, folder, folder / "audio" / "original.wav", folder / "lyrics.txt", "First notes")
        song.audio.mkdir(parents=True)
        text = "דו רה מי פה\nDo re mi fa\n\nסול מי רה דו\nSol mi re do"
        song.lyrics_src.write_text(text, encoding="utf-8")
        stages.set_lyrics(song, lyrics.parse(text))
        song.duration_ms = 8400
        rate = 22050
        mix = np.zeros(rate * song.duration_ms // 1000, dtype=np.float64)
        starts = (700, 1400, 2100, 2800, 4200, 4900, 5600, 6300)
        for index, (word, start, midi) in enumerate(zip(song.words(), starts, (60, 62, 64, 65, 67, 64, 62, 60))):
            length = 1100 if index in (3, 7) else 620
            word.update(startMs=start, endMs=start + length, confidence=1.0)
            t = np.arange(rate * length // 1000) / rate
            phase = 2 * np.pi * 440 * 2 ** ((midi - 69) / 12) * t
            envelope = np.minimum(1, t / .015) * np.exp(-2.3 * t) * np.minimum(1, (length / 1000 - t) / .09)
            tone = .42 * (np.sin(phase) + .27 * np.sin(phase * 2) + .09 * np.sin(phase * 3)) * envelope
            first = start * rate // 1000
            mix[first:first + len(tone)] = tone
        with wave.open(str(song.audio_src), "wb") as out:
            out.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            out.writeframes((mix * 32767).astype("<i2").tobytes())
        stages.assemble(song, artist="Karaoke IL", original_only=True)
        doc = load(folder)
        doc["clips"] = [{"id": "C1", "name": "First four notes", "fromWord": "L1W1", "toWord": "L1W4",
                         "padBeforeMs": 250, "padAfterMs": 150}]
        doc["drills"] = [{"id": "D1", "name": "Listen and sing back", "steps": [
            {"type": "card", "text": "Listen to the first four notes. Sing them back in the quiet gap.", "durationMs": 2800},
            {"type": "clip", "clip": "C1", "repeats": 2, "speed": 1, "track": "original",
             "yourTurn": True, "tiers": ["lyrics", "en"]}]}]
        save(folder, doc)
        (folder / ".first-notes").touch()
        folder.rename(paths.SONGS / slug)
    return slug
