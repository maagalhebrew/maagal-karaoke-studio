"""Build the standalone Qt application for Windows and for both Mac architectures."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import stat
import subprocess
import sys
import tarfile
import time
import zipfile

import fetch_runtimes
from fetch_wheels import requirements
from qt_bundle import include_qt
from reading_assets import include_reading_assets, include_windows_language_packages
import shutil


DESKTOP = Path(__file__).resolve().parent
ROOT = DESKTOP.parent
CACHE = ROOT / ".build" / "desktop"
RELEASE = ROOT / "release"
TARGETS = {
    "win64": "Maagal-Karaoke-Studio-Windows-x64.zip",
    "mac-arm64": "Maagal-Karaoke-Studio-Mac-Apple-Silicon.zip",
    "mac-intel": "Maagal-Karaoke-Studio-Mac-Intel.zip",
}
SETUP_FILENAME = "Maagal-Karaoke-Studio-Windows-Setup.exe"
MAC_CAPTURE = "SystemAudioCapture"
MAC_CAPTURE_MINIMUM = "13.0"
MAC_ARCHITECTURES = {"mac-arm64": "arm64", "mac-intel": "x86_64"}


def path_key(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def zip_info(name, mode=0o644):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = ((mode if stat.S_IFMT(mode) else stat.S_IFREG | mode) & 0xFFFF) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def contents(out, name, data, mode=0o644):
    out.writestr(zip_info(name, mode), data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=4)


def include_file(out, prefix, path: Path, name=None):
    contents(out, prefix + (name or path.name), path.read_bytes())


def include_python(out, base, archive):
    # Preserve symbolic links and executable bits in Mac ZIPs even while building on Windows.
    with tarfile.open(archive, mode="r|gz") as tar:
        for item in tar:
            if not item.name.startswith("python/") or ".." in PurePosixPath(item.name).parts:
                raise ValueError(f"Unexpected Python archive member {item.name}")
            name = base + item.name
            if item.issym():
                contents(out, name, item.linkname.encode("utf-8"), stat.S_IFLNK | 0o777)
            elif item.isfile():
                with tar.extractfile(item) as source:
                    contents(out, name, source.read(), item.mode)
            elif not item.isdir():
                raise ValueError(f"Unsupported Python archive member {item.name}")


def include_audio_tools(out, base, target, archive):
    exe = ".exe" if target == "win64" else ""
    wanted = {"ffmpeg" + exe, "ffprobe" + exe}
    seen = set()
    with zipfile.ZipFile(archive) as source:
        for item in source.infolist():
            leaf = PurePosixPath(item.filename).name
            if leaf in wanted:
                contents(out, base + "tools/" + leaf, source.read(item), 0o755)
                seen.add(leaf)
    if seen != wanted:
        raise ValueError(f"Missing FFmpeg tool(s): {wanted - seen}")


def include_wheels(out, base, target):
    pins = dict(
        line.split("==")
        for path in requirements(target)
        for line in path.read_text().splitlines()
        if line and not line.startswith("#")
    )
    installed = {}
    wheel_cache = CACHE / "wheels" / target
    for wheel in sorted(wheel_cache.glob("*.whl")):
        name, version, _ = wheel.name.split("-", 2)
        name = path_key(name)
        if pins.get(name) != version:
            continue
        if name in installed:
            raise ValueError(f"Ambiguous wheels for {name} in {wheel_cache}")
        installed[name] = version
        with zipfile.ZipFile(wheel) as package:
            for item in package.infolist():
                path = PurePosixPath(item.filename)
                if item.is_dir():
                    continue
                if path.parts[0].endswith(".data"):
                    if path.parts[1] not in {"platlib", "purelib"}:
                        continue
                    path = PurePosixPath(*path.parts[2:])
                contents(out, base + "packages/" + str(path), package.read(item))
    if installed != {path_key(k): v for k, v in pins.items()}:
        raise RuntimeError(f"Missing locked wheels for {target}. Run python desktop/fetch_wheels.py {target}")


def extra_licenses(out, base, target):
    media_version = "7.0" if target == "mac-arm64" else "8.0.1"
    notices = [
        "Maagal Karaoke Studio by Maagal Hebrew",
        "https://maagalhebrew.com/",
        "",
        "Recording credits and adaptation notices are in catalog/CREDITS.txt and in Song tools.",
        "Nunito, Nunito Sans and Rubik are under the SIL Open Font License. See brand/OFL-*.txt.",
        "Qt, PySide6 and shiboken6 6.8.3 are dynamically linked. LGPLv3 and Qt notices are included.",
        "You may replace or relink these libraries and reverse engineer for debugging those modifications.",
        "Qt sources: https://download.qt.io/archive/qt/6.8/6.8.3/single/",
        "Qt for Python sources: https://download.qt.io/official_releases/QtForPython/pyside6/",
        "Qt Multimedia uses its separately licensed FFmpeg libraries. See Qt's included notices.",
        f"FFmpeg and FFprobe {media_version} command-line tools are GPL builds.",
        f"https://github.com/zackees/ffmpeg_bins/tree/{fetch_runtimes.FFMPEG_COMMIT}/v8.0",
        f"https://ffmpeg.org/releases/ffmpeg-{media_version}.tar.xz",
        "CPython 3.11: https://github.com/astral-sh/python-build-standalone",
        "Python packages retain their licenses under packages. CPython retains its own notices under python.",
    ]
    for path in (DESKTOP / "licenses").glob("*"):
        include_file(out, base + "notices/", path)
    contents(out, base + "THIRD-PARTY-NOTICES.txt", "\n".join(notices) + "\n")


def include_studio(out, base, target, capture_helper):
    for path in sorted((ROOT / "backend/karaoke").glob("*")):
        if path.suffix in (".py", ".json") and path.name != "api.py":
            include_file(out, base + "backend/karaoke/", path)
    for name in ("presets.json", "guard.json"):
        include_file(out, base + "data/", ROOT / "data" / name)
    for folder in ("native", "catalog", "brand"):
        for path in sorted((DESKTOP / folder).rglob("*")):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix not in {".pyc", ".swift"}
                and path.name != MAC_CAPTURE
            ):
                include_file(out, base, path, path.relative_to(DESKTOP).as_posix())
    if capture_helper:
        contents(out, base + "native/" + MAC_CAPTURE, capture_helper.read_bytes(), 0o755)
    include_file(out, base, DESKTOP / "launch.py")
    include_qt(out, base, CACHE, target, contents)
    extra_licenses(out, base, target)


def build_windows_launcher():
    compiler = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    exe = CACHE / "Karaoke IL.exe"
    if not compiler.is_file():
        raise RuntimeError("Build the Windows launcher with the .NET Framework C# compiler on Windows.")
    stamp = CACHE / "launcher-inputs.sha256"
    fingerprint = hashlib.sha256(
        (DESKTOP / "WindowsLauncher.cs").read_bytes()
        + (DESKTOP / "icon.ico").read_bytes()
        + compiler.read_bytes()
    ).hexdigest()
    if stamp.is_file() and exe.is_file() and stamp.read_text("ascii") == fingerprint:
        return exe
    subprocess.run(
        [
            str(compiler),
            "/nologo",
            "/target:winexe",
            "/platform:x64",
            "/optimize+",
            "/r:System.Windows.Forms.dll",
            f"/win32icon:{DESKTOP / 'icon.ico'}",
            f"/out:{exe}",
            str(DESKTOP / "WindowsLauncher.cs"),
        ],
        check=True,
    )
    stamp.write_text(fingerprint, encoding="ascii")
    return exe


def mac_entry(out, target):
    launcher = CACHE / (target + "-launch")
    zig = shutil.which("zig") or str(ROOT / ".venv/Lib/site-packages/ziglang/zig.exe")
    if not launcher.exists() or launcher.stat().st_mtime < (DESKTOP / "mac_launcher.c").stat().st_mtime:
        arch = "aarch64" if target == "mac-arm64" else "x86_64"
        subprocess.run(
            [
                zig,
                "cc",
                "-target",
                arch + "-macos.12.0",
                "-Os",
                str(DESKTOP / "mac_launcher.c"),
                "-o",
                str(launcher),
            ],
            check=True,
        )
    prefix = "Karaoke IL.app/Contents/"
    contents(
        out,
        prefix + "Info.plist",
        plistlib.dumps(
            {
                "CFBundleInfoDictionaryVersion": "6.0",
                # Match the on-disk bundle basename for Finder name localization.
                "CFBundleName": "Karaoke IL",
                "CFBundleDisplayName": "Maagal Karaoke Studio",
                "CFBundleIdentifier": "app.karaokeil.studio",
                "CFBundleVersion": "2",
                "CFBundleShortVersionString": "2.0",
                "CFBundlePackageType": "APPL",
                "CFBundleExecutable": "KaraokeIL",
                "CFBundleIconFile": "KaraokeIL.icns",
                "LSMinimumSystemVersion": "12.0",
                "NSHighResolutionCapable": True,
                "NSPrincipalClass": "NSApplication",
            }
        ),
    )
    contents(out, prefix + "MacOS/KaraokeIL", launcher.read_bytes(), 0o755)
    include_file(out, prefix + "Resources/", DESKTOP / "icon.icns", "KaraokeIL.icns")
    return prefix + "Resources/Studio/"


def prepare_mac_capture(target):
    source = DESKTOP / "native" / (MAC_CAPTURE + ".swift")
    folder = CACHE / "mac-capture" / target
    helper = folder / MAC_CAPTURE
    stamp = folder / "inputs.sha256"
    flags = [
        "-O", "-parse-as-library", "-target",
        f"{MAC_ARCHITECTURES[target]}-apple-macos{MAC_CAPTURE_MINIMUM}",
        "-Xlinker", "-rpath", "-Xlinker", "/usr/lib/swift",
    ]
    fingerprint = hashlib.sha256(source.read_bytes() + "\0".join(flags).encode()).hexdigest()
    if helper.is_file() and stamp.is_file() and stamp.read_text("ascii") == fingerprint:
        return helper
    if sys.platform != "darwin":
        raise RuntimeError(
            f"Build {target} capture on a Mac with python desktop/build.py --mac-capture-only {target} "
            f"and copy .build/desktop/mac-capture/{target}/ into this checkout."
        )
    folder.mkdir(parents=True, exist_ok=True)
    pending = helper.with_suffix(".partial")
    try:
        subprocess.run(["xcrun", "swiftc", *flags, str(source), "-o", str(pending)], check=True)
        pending.replace(helper)
        stamp.write_text(fingerprint, encoding="ascii")
    finally:
        pending.unlink(missing_ok=True)
    return helper


def build(target, *, destination=None, private_inputs=None):
    runtimes = []
    if private_inputs:
        from private_qa import runtime_packages
        runtimes.append(runtime_packages(private_inputs[0]))
    capture_helper = prepare_mac_capture(target) if target in MAC_ARCHITECTURES else None
    dest = destination or RELEASE / TARGETS[target]
    work = dest.with_suffix(".partial")
    downloads = CACHE / "downloads"
    for filename, _, expected in fetch_runtimes.inputs([target]):
        if fetch_runtimes.digest(downloads / filename) != expected:
            raise RuntimeError(
                f"{filename} failed its checksum. Run python desktop/fetch_runtimes.py {target}"
            )
    try:
        with zipfile.ZipFile(work, "w", zipfile.ZIP_DEFLATED, compresslevel=4) as out:
            if target == "win64":
                include_file(out, "Karaoke IL/", build_windows_launcher())
                base = "Karaoke IL/Studio/"
            else:
                base = mac_entry(out, target)
            include_studio(out, base, target, capture_helper)
            include_python(out, base, downloads / f"{target}-python.tar.gz")
            include_audio_tools(out, base, target, downloads / f"{target}-ffmpeg.zip")
            include_wheels(out, base, target)
            include_reading_assets(out, base)
            if target == "win64":
                include_windows_language_packages(out, base, *runtimes)
            if private_inputs:
                from private_qa import include_private_models
                include_private_models(out, base, private_inputs[1])
        # Windows readers can briefly hold the previous archive open during verification.
        deadline = time.monotonic() + 120
        while True:
            try:
                work.replace(dest)
                break
            except PermissionError:
                if os.name != "nt" or time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)
    finally:
        work.unlink(missing_ok=True)
    print(f"Built {dest.name} ({dest.stat().st_size:,} bytes)", flush=True)
    return dest


def checksums():
    lines = []
    for name in [*TARGETS.values(), SETUP_FILENAME]:
        path = RELEASE / name
        if path.is_file():
            with path.open("rb") as f:
                lines.append(f"{hashlib.file_digest(f, 'sha256').hexdigest()}  {name}")
    (RELEASE / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="ascii")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="*", metavar="TARGET", help=", ".join(TARGETS))
    parser.add_argument("--mac-capture-only", action="store_true",
                        help="Compile the macOS capture helper without building the rest of the app.")
    parser.add_argument("--private-qa-python", type=Path, help="Python in the Windows CPU timing environment.")
    parser.add_argument("--private-qa-hub", type=Path, help="Source Hugging Face cache for private model bundling.")
    args = parser.parse_args()
    for target in args.targets:
        if target not in TARGETS:
            parser.error(f"unknown target {target!r}")
    if args.private_qa_python or args.private_qa_hub:
        if not (
            args.private_qa_python and args.private_qa_hub and not args.mac_capture_only
            and args.targets in ([], ["win64"]) and os.name == "nt"
        ):
            parser.error("Private QA requires both input paths and Windows x64.")
        from private_qa import PRIVATE_ARCHIVE
        location = RELEASE / "private-qa"
        location.mkdir(parents=True, exist_ok=True)
        CACHE.mkdir(parents=True, exist_ok=True)
        archive = build("win64", destination=location / PRIVATE_ARCHIVE,
                        private_inputs=(args.private_qa_python, args.private_qa_hub))
        with archive.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        (location / "SHA256SUMS.txt").write_text(f"{sha}  {archive.name}\n", encoding="ascii")
    elif args.mac_capture_only:
        for target in args.targets or MAC_ARCHITECTURES:
            if target not in MAC_ARCHITECTURES:
                parser.error("--mac-capture-only requires a macOS target")
            print(prepare_mac_capture(target), flush=True)
    else:
        RELEASE.mkdir(exist_ok=True)
        CACHE.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(build, args.targets or TARGETS))
        checksums()
