"""Check a Windows desktop upgrade from the installed runtime to this source tree.

Run from the source tree with any Python 3.11+ interpreter:
    python desktop/verify_upgrade.py --installed "C:/path/to/Karaoke IL"

The old installed Python runs both revisions with their respective source paths.
The checker creates and removes isolated libraries and settings under .build.
The default-location case redirects LOCALAPPDATA within the current OS account.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import traceback


ROOT = Path(__file__).resolve().parents[1]
TRACKS = ("original", "vocals", "instrumental")
BASELINE_TITLE = "Karaoke IL"
CANDIDATE_TITLE = "Maagal Karaoke Studio"


def sha256(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def baseline_identity(installed):
    launcher = installed / "Karaoke IL.exe"
    studio = installed / "Studio"
    version = subprocess.check_output([str(studio / "python" / "python.exe"), "--version"], text=True).strip()
    command = (
        "$item = Get-Item -LiteralPath $env:KARAOKE_BASELINE_EXE; "
        "$status = 'Unavailable'; $signer = $null; "
        "try { $auth = Get-AuthenticodeSignature -LiteralPath $item.FullName -ErrorAction Stop; "
        "$status = $auth.Status.ToString(); $signer = $auth.SignerCertificate.Subject } catch {} "
        "[pscustomobject]@{ProductName=$item.VersionInfo.ProductName; "
        "ProductVersion=$item.VersionInfo.ProductVersion; FileVersion=$item.VersionInfo.FileVersion; "
        "Authenticode=$status; Signer=$signer} | ConvertTo-Json -Compress"
    )
    metadata = subprocess.check_output(
        [shutil.which("pwsh.exe") or "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        env={**os.environ, "KARAOKE_BASELINE_EXE": str(launcher)},
        text=True,
    )
    image = launcher.read_bytes()
    pe = struct.unpack_from("<I", image, 0x3c)[0]
    assert image[pe:pe + 4] == b"PE\0\0"
    optional = pe + 24
    magic = struct.unpack_from("<H", image, optional)[0]
    # PE data directory index four holds the embedded certificate table.
    certificate = optional + {0x10b: 96, 0x20b: 112}[magic] + 4 * 8
    _, certificate_size = struct.unpack_from("<II", image, certificate)
    print(json.dumps({
        "baseline": {**json.loads(metadata), "python": version, "launcherSha256": sha256(launcher),
                     "launchPySha256": sha256(studio / "launch.py"),
                     "embeddedAuthenticodeCertificate": bool(certificate_size)},
    }), flush=True)


def decode_tracks(folder, doc, store):
    summary = {}
    for track in TRACKS:
        path = store.track_path(folder, doc, track)
        assert path.name == f"{track}.wav", path
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(path),
                        "-map", "0:a:0", "-f", "null", "-"],
                       check=True, capture_output=True, timeout=30)
        summary[track] = sha256(path)
    assert len(set(summary.values())) == len(TRACKS), "Three distinct audio tracks are expected"
    return summary


def check_child(studio, home, mode, expected_path, archive):
    sys.path.insert(0, str(studio))
    import launch
    from PySide6 import QtWidgets, __version__ as qt_version
    from PySide6.QtCore import QSettings, QTimer

    if launch.library_path() != home or not home.resolve().is_relative_to(ROOT / ".build" / "desktop"):
        raise RuntimeError(f"Library selected outside declared workspace scratch home: {launch.library_path()}")
    settings = home.parent / "qt-settings"
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(settings))
        QSettings.setPath(QSettings.Format.NativeFormat, scope, str(settings))

    if mode == "restore":
        launch.configure()
        from karaoke import paths, song_archive, songfile
        from native import store
        assert not any(paths.SONGS.iterdir()), "Restore library must be empty before unpacking"
        expected = json.loads(expected_path.read_text("utf8"))
        slug = song_archive.restore(archive, store.validate)
        assert slug == expected["slug"]
        folder = paths.SONGS / slug
        assert [item.name for item in paths.SONGS.iterdir() if (item / "song.json").is_file()] == [slug]
        assert not any((paths.SONGS / ".preparing").iterdir()), "Restore left staging content"
        doc = songfile.load(folder)
        assert {key: doc[key] for key in expected["content"]} == expected["content"]
        assert {key: doc["song"][key] for key in expected["song"]} == expected["song"]
        assert decode_tracks(folder, doc, store) == expected["tracks"]
        print(json.dumps({"mode": mode, "song": slug, "restoreStartedEmpty": True,
                          "wordTimingPreserved": True, "decodedTracks": list(TRACKS)}), flush=True)
        return

    class VerifyApplication(QtWidgets.QApplication):
        def exec(self):
            result = []

            def inspect_first_window():
                try:
                    result.append(check_window(self, mode, expected_path, archive, qt_version))
                except Exception:
                    traceback.print_exc()
                finally:
                    for window in self.topLevelWidgets():
                        window.close()
                    self.exit(0 if result else 1)

            QTimer.singleShot(0, inspect_first_window)
            return super().exec()

    QtWidgets.QApplication = VerifyApplication
    sys.exit(launch.main())


def check_window(application, mode, expected_path, archive, qt_version):
    from karaoke import library, song_archive
    from native import store
    from native.window import MainWindow

    windows = [window for window in application.topLevelWidgets() if window.isVisible()]
    assert len(windows) == 1 and isinstance(windows[0], MainWindow), windows
    window = windows[0]
    title = BASELINE_TITLE if mode == "seed" else CANDIDATE_TITLE
    assert window.windowTitle() == title, window.windowTitle()
    folder, doc, _ = next(row for row in window.rows if row[2] == "hatikva")
    first_line = doc["lines"][0]
    first_word = first_line["words"][0]
    if mode == "seed":
        assert first_word["endMs"] - first_word["startMs"] > 7
        first_word["startMs"] += 7
        if not doc["clips"] and not doc["drills"]:
            doc["clips"] = [{"id": "C1", "name": "Upgrade clip", "fromWord": first_word["id"],
                             "toWord": first_line["words"][-1]["id"], "padBeforeMs": 0, "padAfterMs": 0}]
            doc["drills"] = [{"id": "D1", "name": "Upgrade drill", "steps": [
                {"type": "clip", "clip": "C1", "repeats": 2, "speed": 1, "track": "original",
                 "yourTurn": True, "tiers": ["lyrics", "en"]},
            ]}]
        store.save(folder, doc)
        library.set_favorite(folder.name, True)
        library.record_practice(folder.name, "practice", 13, {first_line["id"]: 2}, {first_line["id"]})
        tracks = {track: sha256(store.track_path(folder, doc, track)) for track in TRACKS}
        expected_path.write_text(json.dumps({
            "slug": folder.name, "tracks": tracks, "history": library.practice(folder.name),
            "song": {key: doc["song"][key] for key in ("id", "title", "artist", "language", "durationMs", "audio")},
            "content": {key: doc[key] for key in ("lines", "sections", "clips", "drills")},
        }, ensure_ascii=False), encoding="utf8")
        if archive:
            shutil.move(song_archive.backup(folder), archive)
    else:
        expected = json.loads(expected_path.read_text("utf8"))
        assert folder.name == expected["slug"]
        assert {key: doc[key] for key in expected["content"]} == expected["content"]
        assert {key: doc["song"][key] for key in expected["song"]} == expected["song"]
        assert decode_tracks(folder, doc, store) == expected["tracks"]
        assert folder.name in library.labels()[1]
        assert library.practice(folder.name) == expected["history"]
    print(json.dumps({
        "mode": mode, "firstQtWindowTitle": title, "qt": qt_version, "song": folder.name,
        "savedWordStartMs": first_word["startMs"], "favorite": folder.name in library.labels()[1],
        "practice": library.practice(folder.name), "decodedTracks": list(TRACKS) if mode == "upgrade" else [],
    }), flush=True)
    return True


def verify(installed):
    studio = installed / "Studio"
    interpreter = studio / "python" / "python.exe"
    assert sys.platform == "win32", "The installed-runtime upgrade check runs on Windows"
    assert interpreter.is_file() and (studio / "launch.py").is_file(), f"Missing installed runtime under {studio}"
    baseline_identity(installed)
    scratch = ROOT / ".build" / "desktop"
    if not scratch.resolve().is_relative_to(ROOT):
        raise RuntimeError("The workspace scratch directory resolves outside the repository.")
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch, prefix="upgrade-") as directory:
        scratch = Path(directory).resolve()
        archive = scratch / "old-song.zip"
        old_env = {key: value for key, value in os.environ.items() if not key.startswith("KARAOKE_")}
        old_env.update(
            PYTHONPATH=str(studio / "packages"), QT_QPA_PLATFORM="offscreen", PYTHONNOUSERSITE="1",
            PATH=str(studio / "tools") + os.pathsep + old_env["PATH"],
            TMP=str(scratch), TEMP=str(scratch), TMPDIR=str(scratch),
        )

        def run(revision, home, mode, expected, archive_arg, env):
            subprocess.run([str(interpreter), "-B", str(Path(__file__).resolve()), "--child", str(revision),
                            str(home), mode, str(expected), str(archive_arg) if archive_arg else ""],
                           check=True, cwd=scratch, env=env, timeout=100)

        for location in ("explicit-KARAOKE_HOME", "simulated-default-LOCALAPPDATA"):
            with tempfile.TemporaryDirectory(dir=scratch, prefix="location-") as case:
                case = Path(case)
                env = {**old_env, "LOCALAPPDATA": str(case / "local")}
                explicit = location == "explicit-KARAOKE_HOME"
                home = case / "library" if explicit else case / "local" / "Karaoke IL"
                if explicit:
                    env["KARAOKE_HOME"] = str(home)
                expected = case / "expected.json"
                print(json.dumps({"checking": location}), flush=True)
                run(studio, home, "seed", expected, archive if explicit else None, env)
                run(ROOT / "desktop", home, "upgrade", expected, None, env)
                if explicit:
                    shutil.copyfile(expected, scratch / "archive-expected.json")

        home = scratch / "empty-restore"
        run(ROOT / "desktop", home, "restore", scratch / "archive-expected.json", archive,
            {**old_env, "KARAOKE_HOME": str(home), "LOCALAPPDATA": str(scratch / "restore-local")})


if __name__ == "__main__":
    if sys.argv[1:2] == ["--child"]:
        _, _, studio, home, mode, expected, archive = sys.argv
        check_child(Path(studio), Path(home), mode, Path(expected), Path(archive) if archive else None)
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--installed", required=True, type=Path, help="Existing Karaoke IL installation folder")
        verify(parser.parse_args().installed.resolve())
