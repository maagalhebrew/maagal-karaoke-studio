import json
import re
import shutil
from pathlib import Path

from karaoke import paths, songfile
from karaoke.desktop_songs import staging_directory

catalog = Path(__file__).resolve().parents[1] / "catalog"
entry_order = ("hatikva", "lecha-dodi", "shalom-aleichem")
entries = {
    "hatikva": ("Hatikva", "הַתִּקְוָה", "Israeli national anthem", "flag.webp", 0.29),
    "lecha-dodi": ("Lecha Dodi", "לְכָה דוֹדִי", "A song to welcome Shabbat", "time.webp", 0.49),
    "shalom-aleichem": (
        "Shalom Aleichem",
        "שָׁלוֹם עֲלֵיכֶם",
        "A Friday-night greeting of peace",
        "rose.webp",
        0.42,
    ),
}


def list_songs():
    result = []
    for folder in paths.SONGS.iterdir():
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9-]*", folder.name)
            or folder.is_symlink()
            or not (folder / "song.json").is_file()
        ):
            continue
        try:
            data = songfile.load(folder)
            if songfile.validation_errors(data) or data["song"]["id"] != folder.name:
                continue
            tag = (
                (folder / ".maagal-song").read_text("ascii").strip()
                if (folder / ".maagal-song").is_file()
                else ""
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        result.append((folder, data, tag if tag in entries else ""))
    return sorted(
        result,
        key=lambda row: (
            entry_order.index(row[2]) if row[2] in entries else 10,
            row[1]["song"]["title"].casefold(),
        ),
    )


def seed():
    existing = {row[2] for row in list_songs() if row[2]}
    for key in entry_order:
        source = catalog / key
        if key in existing or not (source / "song.json").is_file():
            continue
        base = f"maagal-{key}"
        slug, serial = base, 1
        while (paths.SONGS / slug).exists():
            serial += 1
            slug = f"{base}-{serial}"
        with staging_directory() as area:
            dest = Path(area) / "song"
            shutil.copytree(source, dest)
            doc = songfile.load(dest)
            doc["song"]["id"] = slug
            errors = validate(doc)
            if errors:
                raise ValueError("Could not read included song: " + errors[0])
            (dest / "song.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            (dest / ".maagal-song").write_text(key, encoding="ascii")
            dest.rename(paths.SONGS / slug)


def validate(doc):
    return songfile.validation_errors(doc) or songfile.timing_errors(doc) or songfile.reference_errors(doc)


def save(folder, doc):
    problems = validate(doc)
    if problems:
        raise ValueError(problems[0])
    songfile.save(folder, doc)


def track_path(folder, doc, track):
    if track not in ("original", "vocals", "instrumental") or track not in doc["song"]["audio"]:
        raise ValueError("This recording does not include that track.")
    # Legacy manifests may contain absolute paths. Media belongs to the selected song.
    audio = (folder / "audio" / (track + ".wav")).resolve()
    if not audio.is_relative_to(folder.resolve()) or not audio.is_file():
        raise ValueError("The audio file is missing. Import a saved copy of this song.")
    return audio


def stamp(ms):
    seconds = max(0, int(ms) // 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"
