"""Check distributable archives and optionally run the native interface from a packaged runtime."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import posixpath
import re
import stat
import struct
import subprocess
import sys
import tempfile
import wave
import zipfile

from build import CACHE, DESKTOP, MAC_CAPTURE, MAC_CAPTURE_MINIMUM, RELEASE, TARGETS
from qt_bundle import mac_headers
from fetch_reading_models import MODELS


def check_mac(package, target, names):
    prefix = "Karaoke IL.app/Contents/"
    base = prefix + "Resources/Studio/"
    plist = plistlib.loads(package.read(prefix + "Info.plist"))
    assert plist["CFBundleIdentifier"] == "app.karaokeil.studio"
    assert plist["CFBundleName"] == "Karaoke IL"
    assert plist["CFBundleDisplayName"] == "Maagal Karaoke Studio"
    assert plist["CFBundleExecutable"] == "KaraokeIL"
    launcher = prefix + "MacOS/" + plist["CFBundleExecutable"]
    assert (
        plist["CFBundlePackageType"] == "APPL" and prefix + "Resources/" + plist["CFBundleIconFile"] in names
    )
    required = {launcher, base + "python/bin/python3.11", base + "tools/ffmpeg", base + "tools/ffprobe"}
    cpu = {"mac-intel": 0x1000007, "mac-arm64": 0x100000C}[target]
    capture = base + "native/" + MAC_CAPTURE
    required.add(capture)
    capture_major, capture_minor = map(int, MAC_CAPTURE_MINIMUM.split("."))
    capture_version = capture_major << 16 | capture_minor << 8
    matches_count = highest = 0
    for info in package.infolist():
        name = info.filename
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            link = package.read(info).decode()
            assert not link.startswith("/"), (name, link)
            dest = posixpath.normpath(posixpath.join(posixpath.dirname(name), link))
            assert dest.startswith(prefix) and (
                dest in names or any(n.startswith(dest + "/") for n in names)
            ), (name, link)
            continue
        known = (
            name in required
            or name.endswith((".so", ".dylib"))
            or re.search(r"\.framework/Versions/[^/]+/[^/]+$", name)
        )
        if not known:
            continue
        if name in required:
            assert mode & 0o111, name
        matches = [(v, deps) for arch, v, deps in mac_headers(package.read(info)) if arch == cpu]
        assert matches, f"Target architecture missing in {name}"
        matches_count += 1
        for version, deps in matches:
            if name == capture:
                assert version == capture_version, (name, version)
                assert any("/ScreenCaptureKit.framework/" in dep for dep in deps), name
            else:
                highest = max(highest, version)
            for dep in deps:
                if dep.startswith(("/System/Library/", "/usr/lib/")) or (
                    name == capture and dep.startswith("@rpath/libswift") and "/" not in dep[7:]
                ):
                    continue
                if dep.startswith("@loader_path/"):
                    resolved = posixpath.normpath(
                        posixpath.join(posixpath.dirname(name), dep.split("/", 1)[1])
                    )
                    assert resolved in names, (name, dep)
                elif dep.startswith("@rpath/"):
                    assert any(n.endswith("/" + dep.split("/", 1)[1]) for n in names), (name, dep)
                elif dep.startswith("@executable_path/"):
                    rel = dep.split("/", 1)[1]
                    assert any(
                        posixpath.normpath(posixpath.join(posixpath.dirname(p), rel)) in names
                        for p in required
                    ), (name, dep)
                else:
                    raise AssertionError((name, dep))
    assert required <= names and matches_count > 45
    major, minor = map(int, plist["LSMinimumSystemVersion"].split(".")[:2])
    assert highest <= (major << 16 | minor << 8), (
        f"A library requires macOS {highest >> 16}.{(highest >> 8) & 255}"
    )
    print(
        f"{target}: checked {matches_count} Mach-O files, dependent libraries, launch permissions and macOS {major}.{minor} deployment target.",
        flush=True,
    )


def check_catalog(package, base):
    credits = package.read(base + "catalog/CREDITS.txt").decode("utf8")
    for key in ("hatikva", "lecha-dodi", "shalom-aleichem"):
        folder = base + "catalog/" + key + "/"
        doc = json.loads(package.read(folder + "song.json"))
        assert doc["song"]["id"] == "maagal-" + key and doc["song"]["recordingCredit"]["source"] in credits
        assert all(line["english"] and line["pronunciation"] for line in doc["lines"])
        previous = 0
        for line in doc["lines"]:
            for word in line["words"]:
                assert previous <= word["startMs"] < word["endMs"] <= doc["song"]["durationMs"], (
                    key,
                    word["id"],
                )
                previous = word["endMs"]
        fingerprints = set()
        for part in ("original", "instrumental", "vocals"):
            data = package.read(folder + doc["song"]["audio"][part])
            with wave.open(io.BytesIO(data), "rb") as wav:
                assert wav.getnchannels() == 2 and wav.getsampwidth() == 2
                assert abs(wav.getnframes() * 1000 / wav.getframerate() - doc["song"]["durationMs"]) < 2
            fingerprints.add(hashlib.sha256(data).digest())
        assert len(fingerprints) == 3


def audit(target, bundle=None):
    bundle = bundle or RELEASE / TARGETS[target]
    sums = dict(line.split("  ")[::-1] for line in (bundle.parent / "SHA256SUMS.txt").read_text().splitlines())
    with bundle.open("rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == sums[bundle.name]
    with zipfile.ZipFile(bundle) as package:
        names = set(package.namelist())
        assert len(names) == len(package.infolist()) and package.testzip() is None
        assert not any(PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts for n in names)
        base = "Karaoke IL/Studio/" if target == "win64" else "Karaoke IL.app/Contents/Resources/Studio/"
        for relative in (
            "launch.py",
            "native/window.py",
            "native/player.py",
            "native/capture.py",
            "native/capture_audio.py",
            "brand/medallion.png",
            "data/presets.json",
            "backend/karaoke/song.schema.json",
            "notices/COPYING.LGPLv3",
            "THIRD-PARTY-NOTICES.txt",
        ):
            assert base + relative in names, relative
        assert not any(
            n.startswith(
                tuple(
                    base + folder + "/"
                    for folder in ("frontend", "songs", "inbox", "packages/uvicorn", "packages/fastapi")
                )
            )
            or "qtwebengine" in n.lower()
            for n in names
        )
        assert {n for n in names if n.startswith(base + "data/")} == {
            base + "data/presets.json",
            base + "data/guard.json",
        }
        check_catalog(package, base)
        for key, _, _, assets in MODELS:
            for asset in assets.split():
                package.getinfo(base + f"models/{key}/{asset}")
        package.getinfo(base + "models/Reading model credits.txt")
        if target.startswith("mac"):
            check_mac(package, target, names)
        else:
            for relative in ("transformers/__init__.py", "phonikud_onnx/__init__.py", "sentencepiece/__init__.py"):
                assert base + "processing-packages/" + relative in names, relative
            for relative in ("soundcard/mediafoundation.py", "cffi/__init__.py", "pycparser/__init__.py"):
                assert base + "packages/" + relative in names, relative
            files = [
                base + "packages/_cffi_backend.cp311-win_amd64.pyd",
                "Karaoke IL/Karaoke IL.exe",
                base + "python/python.exe",
                base + "tools/ffmpeg.exe",
                base + "tools/ffprobe.exe",
                base + "packages/PySide6/QtWidgets.pyd",
                base + "packages/PySide6/QtMultimedia.pyd",
                base + "packages/PySide6/plugins/platforms/qwindows.dll",
            ]
            for name in files:
                binary = package.read(name)
                offset = struct.unpack_from("<I", binary, 0x3C)[0]
                assert binary[:2] == b"MZ" and binary[offset : offset + 6] == b"PE\0\0d\x86", name
    print(
        f"{bundle.name}: checksum, CRCs, application resources, three credited songs, track durations and timed words passed.",
        flush=True,
    )


def native_smoke(pictures=None):
    CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=CACHE.parent, prefix="qa-") as temp:
        root = Path(temp)
        if sys.platform == "darwin":
            target = "mac-arm64" if platform.machine() == "arm64" else "mac-intel"
            subprocess.run(
                ["/usr/bin/ditto", "-x", "-k", str(RELEASE / TARGETS[target]), str(root)], check=True
            )
            studio = root / "Karaoke IL.app/Contents/Resources/Studio"
            python = studio / "python/bin/python3.11"
            search = "/usr/bin:/bin"
        elif os.name == "nt":
            with zipfile.ZipFile(RELEASE / TARGETS["win64"]) as z:
                z.extractall(root)
            studio = root / "Karaoke IL/Studio"
            python = studio / "python/python.exe"
            search = str(Path(os.environ["SystemRoot"]) / "System32")
        else:
            raise ValueError("A Windows or Mac host is required for native playback.")
        env = dict(os.environ, KARAOKE_HOME=str(root / "New library"), PATH=search, PYTHONNOUSERSITE="1")
        args = [str(python), "-I", "-B", str(DESKTOP / "smoke.py"), str(studio)]
        if pictures:
            args.append(str(pictures.resolve()))
        subprocess.run(args, cwd=root, env=env, check=True, timeout=180)


def private_smoke(bundle, recording=False):
    from private_qa import FILES, REVISIONS

    with tempfile.TemporaryDirectory(prefix="qa-") as temp:
        with zipfile.ZipFile(bundle) as package:
            package.getinfo("PRIVATE-QA.txt")
            prefix = "Karaoke IL/Studio/"
            for repo, assets in FILES.items():
                base = prefix + "models/hub/models--" + repo.replace("/", "--") + "/"
                assert package.read(base + "refs/main").decode("ascii") == REVISIONS[repo], repo
                for asset, expected in assets.items():
                    name = base + "snapshots/" + REVISIONS[repo] + "/" + asset
                    assert package.getinfo(name).file_size == expected[0], name
                    with package.open(name) as stream:
                        assert hashlib.file_digest(stream, "sha256").hexdigest() == expected[1], name
            package.extractall(temp)
        studio = Path(temp) / "Karaoke IL/Studio"
        env = check_private_runtime(studio)
        if recording:
            check_recording(studio, Path(temp), env)


def check_private_runtime(studio):
    check = """
import importlib
import sys

sys.path[:0] = [sys.argv[1], sys.argv[2]]
for name in ("torch", "torchaudio", "demucs.hf", "faster_whisper", "stable_whisper",
             "soundcard", "onnxruntime", "phonikud_onnx", "transformers"):
    print("Importing", name, flush=True)
    importlib.import_module(name)
from transformers import MarianMTModel, MarianTokenizer
print("Packaged processing imports passed.", flush=True)
"""
    env = dict(
        os.environ,
        HF_HUB_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        TRANSFORMERS_OFFLINE="1",
        OMP_NUM_THREADS="4",
        MKL_NUM_THREADS="4",
        PATH=str(Path(os.environ["SystemRoot"]) / "System32"),
    )
    subprocess.run(
        [str(studio / "python/python.exe"), "-I", "-B", "-c", check,
         str(studio / "processing-packages"), str(studio / "packages")],
        env=env, cwd=studio, timeout=720, check=True,
    )
    return env


def check_recording(studio, root, env):
    area = root / "Recording"
    area.mkdir()
    request = {
        "language": "he", "title": "Packaged recording check", "slug": "packaged-recording-check",
        "artist": "", "start": 23, "end": 45, "bilingual": False, "lyrics": "",
        "audio": str(studio / "catalog/hatikva/audio/original.wav"),
    }
    (area / "request.json").write_text(json.dumps(request), encoding="utf-8")
    (area / "ready").touch()
    hub = str(studio / "models/hub")
    worker = dict(
        env,
        HF_HUB_CACHE=hub,
        HUGGINGFACE_HUB_CACHE=hub,
        OMP_NUM_THREADS="4",
        MKL_NUM_THREADS="4",
        KARAOKE_RESOURCES=str(studio),
        KARAOKE_HOME=str(root / "Library"),
        PYTHONPATH=os.pathsep.join(str(studio / f) for f in ("backend", "processing-packages")),
        PATH=str(studio / "tools") + os.pathsep + env["PATH"],
    )
    result = subprocess.run(
        [str(studio / "python/python.exe"), "-B", "-m", "karaoke.prepare", str(area)],
        env=worker, cwd=studio, timeout=1200,
    )
    if result.returncode:
        raise RuntimeError((area / "progress").read_text(encoding="utf-8"))
    folder = area / "song"
    doc = json.loads((folder / "song.json").read_text(encoding="utf-8"))
    assert doc["lines"] and all(line["english"] and line["pronunciation"] for line in doc["lines"])
    for name in ("original", "instrumental", "vocals"):
        with wave.open(str(folder / doc["song"]["audio"][name]), "rb") as track:
            assert track.getnframes() and abs(track.getnframes() / track.getframerate() - 22) < 0.1
    print(f"Packaged recording-only worker verified three 22-second tracks and English and pronunciation for {len(doc['lines'])} lines.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="*")
    parser.add_argument("--native-smoke", action="store_true")
    parser.add_argument("--private-qa", action="store_true")
    parser.add_argument("--recording", action="store_true", help="Run the packaged recording-only check with --private-qa.")
    parser.add_argument("--pictures", type=Path)
    args = parser.parse_args()
    if args.recording and not args.private_qa:
        parser.error("--recording requires --private-qa")
    if args.private_qa:
        if args.targets or args.native_smoke or os.name != "nt":
            parser.error("Run private QA verification on Windows without target or smoke flags.")
        from private_qa import PRIVATE_ARCHIVE
        private = RELEASE / "private-qa" / PRIVATE_ARCHIVE
        audit("win64", private)
        private_smoke(private, args.recording)
    else:
        for target in args.targets or TARGETS:
            audit(target)
        if args.native_smoke:
            native_smoke(args.pictures)
