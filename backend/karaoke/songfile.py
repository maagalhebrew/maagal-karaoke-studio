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
    # Write the new file first. The previous song.json stays in place until the new text is on disk,
    # then a copy is kept in backups. A failed write does not move the live file out of the way.
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
