"""song.json: reading (older versions are upgraded on the way in), schema validation, and saving with numbered backups."""
import json
import shutil
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA = json.loads((Path(__file__).parent / "song.schema.json").read_text(encoding="utf-8"))
VERSION = SCHEMA["properties"]["schema"]["const"]
_validator = Draft202012Validator(SCHEMA)
# Flags of the removed niqqud and transliteration stages (schema 1).
OLD_FLAGS = {"stress-guess", "no-niqqud", "niqqud-mismatch", "non-hebrew"}


def migrate(song: dict) -> bool:
    """Bring a song up to the current schema in place. Returns True when it changed.
    1 -> 2 (17 Nov 2026): two caption lines. Words lose `pointed` and `syllables` (the niqqud and transliteration
    stages are gone), their flags lose those stages' flags, drill tiers become lyrics/en, and the song gets a
    language (every schema-1 song is Hebrew)."""
    if song.get("schema") != 1:
        return False
    song["schema"] = 2
    song["song"].setdefault("language", "he")
    for line in song["lines"]:
        for w in line["words"]:
            w.pop("pointed", None)
            w.pop("syllables", None)
            w["flags"] = [f for f in w["flags"] if f not in OLD_FLAGS]
    for drill in song["drills"]:
        for step in drill["steps"]:
            if step.get("type") == "clip":
                step["tiers"] = [{"he": "lyrics"}.get(t, t) for t in step["tiers"] if t != "translit"]
    return True


def migrate_folder(folder: Path) -> dict | None:
    """Upgrade a song folder's song.json on disk (`karaoke migrate`); the old file goes to backups\\.
    Returns counts (never lyric text), or None when it is already current."""
    song = json.loads((folder / "song.json").read_text(encoding="utf-8"))
    if song.get("schema") == VERSION:
        return None
    words = [w for line in song["lines"] for w in line["words"]]
    flags = sum(f in OLD_FLAGS for w in words for f in w["flags"])
    steps = sum(1 for d in song["drills"] for s in d["steps"] if s.get("type") == "clip")
    if not migrate(song):
        raise ValueError(f"schema {song.get('schema')} can't be upgraded")
    save(folder, song)
    return {"from": 1, "to": VERSION, "words": len(words), "flagsRemoved": flags, "drillStepsUpdated": steps}


def load(folder: Path) -> dict:
    """A song folder's song.json, upgraded to the current schema if it is older (saved as such on its next save)."""
    song = json.loads((folder / "song.json").read_text(encoding="utf-8"))
    migrate(song)
    return song


def validation_errors(song: dict) -> list[str]:
    """Schema errors as 'path: message' strings. Messages name fields and ids, never lyric text."""
    out = []
    for e in sorted(_validator.iter_errors(song), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(p) for p in e.absolute_path) or "(root)"
        out.append(f"{path}: {e.validator} check failed")
    return out


def save(folder: Path, song: dict) -> Path:
    """Validate, back up the previous song.json as backups/song.<n>.json, then write atomically."""
    errors = validation_errors(song)
    if errors:
        raise ValueError(f"song.json failed schema validation ({len(errors)} errors), first: {errors[0]}")
    path = folder / "song.json"
    with tempfile.NamedTemporaryFile(dir=folder, suffix=".tmp", delete=False) as tmp:
        pending = Path(tmp.name)
    try:
        pending.write_text(json.dumps(song, ensure_ascii=False, indent=2), encoding="utf-8")
        if path.exists():
            backups = folder / "backups"
            backups.mkdir(exist_ok=True)
            n = 1 + max((int(p.stem.split(".")[1]) for p in backups.glob("song.*.json")
                         if p.stem.split(".")[1].isdigit()), default=0)
            shutil.copyfile(path, backups / f"song.{n}.json")
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)
    return path


def timing_errors(song: dict) -> list[str]:
    from .stages import MIN_WORD_MS as min_word_ms
    errors, prev_end = [], 0
    duration = song["song"]["durationMs"]
    for w in (w for line in song["lines"] for w in line["words"]):
        if w["startMs"] < prev_end:
            errors.append(f"{w['id']} starts before the previous word ends")
        if w["endMs"] - w["startMs"] < min_word_ms:
            errors.append(f"{w['id']} is shorter than {min_word_ms} ms")
        if w["endMs"] > duration:
            errors.append(f"{w['id']} ends after the song")
        prev_end = w["endMs"]
    return errors


def reference_errors(song: dict) -> list[str]:
    """Sections/clips/drills must point at real lines/words/clips, in order, without overlapping sections."""
    errors = []
    line_idx = {line["id"]: i for i, line in enumerate(song["lines"])}
    word_idx = {w["id"]: i for i, w in enumerate(w for line in song["lines"] for w in line["words"])}
    if len(line_idx) != len(song["lines"]) or len(word_idx) != sum(len(line["words"]) for line in song["lines"]):
        errors.append("Lines and words must have unique identifiers.")
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
            if step["type"] == "clip" and step["track"] not in song["song"]["audio"]:
                errors.append(f"drill {d['id']} step {n} needs an unavailable audio track")
    return errors
