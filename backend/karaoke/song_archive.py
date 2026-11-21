"""Move a prepared song between desktop libraries, including older Studio song folders."""
import json
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from . import paths
from .desktop_songs import staging_directory
from .songfile import load, migrate, save, validation_errors
from .stages import StageError, duration_s

MAX_BYTES = 2 * 1024**3
MAX_MANIFEST = 8 * 1024**2
TRACKS = ("original", "vocals", "instrumental")


def backup(folder: Path) -> Path:
    doc = load(folder)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        output = Path(tmp.name)
    try:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            archive.writestr("song.json", json.dumps(doc, ensure_ascii=False).encode("utf-8"))
            for track in doc["song"].get("availableTracks", TRACKS):
                name = f"audio/{track}.wav"
                archive.write(folder / name, name)
        return output
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def _restore(source: Path, validate, busy_id: str | None) -> str:
    with zipfile.ZipFile(source) as archive, staging_directory() as staging:
        entries = archive.infolist()
        manifests = [i for i in entries if PurePosixPath(i.filename).name == "song.json"
                     and "__MACOSX" not in PurePosixPath(i.filename).parts]
        if len(manifests) != 1 or manifests[0].file_size > MAX_MANIFEST:
            raise ValueError("Choose a ZIP containing one song folder with its song.json and audio files.")
        manifest = manifests[0]
        doc = json.loads(archive.read(manifest).decode("utf-8-sig"))
        if not isinstance(doc, dict):
            raise ValueError("The song information could not be read.")
        migrate(doc)
        if validation_errors(doc) or validate(doc):
            raise ValueError("The saved lyrics, timing or practice settings are incomplete.")
        root = manifest.filename[:-len("song.json")]
        tracks = doc["song"].get("availableTracks", TRACKS)
        folder = Path(staging) / "song"
        (folder / "audio").mkdir(parents=True)
        size = 0
        for track in tracks:
            relative = f"audio/{track}.wav"
            matches = [i for i in entries if i.filename == root + relative]
            if len(matches) != 1:
                raise ValueError(f"The saved song must contain one {track} audio track.")
            info = matches[0]
            size += info.file_size
            if size > MAX_BYTES or info.flag_bits & 1:
                raise ValueError("Use an unencrypted ZIP with up to 2 GB of song audio.")
            # Write to fixed local filenames. ZIP member names and stored song paths never select a destination.
            wav = folder / relative
            with archive.open(info) as src, wav.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            if abs(duration_s(wav, "restore") * 1000 - doc["song"]["durationMs"]) > 150:
                raise ValueError("The recording length differs from the saved timing. Check that the files belong to one song.")
            doc["song"]["audio"][track] = relative
        base = doc["song"]["id"][:72].rstrip("-")
        if PureWindowsPath(base).is_reserved():
            base = "song-" + base
        slug, n = base, 1
        while (paths.SONGS / slug).exists() or slug == busy_id:
            n += 1
            slug = f"{base}-{n}"
        doc["song"].update(id=slug, permissionId=None)
        save(folder, doc)
        folder.rename(paths.SONGS / slug)
        return slug


def restore(source: Path, validate, busy_id: str | None = None) -> str:
    try:
        return _restore(source, validate, busy_id)
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, KeyError, TypeError, IndexError,
            AttributeError, RuntimeError, StageError, NotImplementedError) as exc:
        raise ValueError("This saved song could not be read. Choose a complete Karaoke IL song ZIP.") from exc
