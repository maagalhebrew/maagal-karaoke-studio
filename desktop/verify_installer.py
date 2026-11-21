"""Exercise the actual Windows installer and launcher using the Windows accessibility tree."""

import argparse
from pathlib import Path
import hashlib
import os
import subprocess
import tempfile
import time
import zipfile
import zlib

from build import CACHE, DESKTOP, RELEASE, SETUP_FILENAME, TARGETS


def check(private_qa=False, recording=False):
    import psutil
    from pywinauto import Desktop

    if os.name != "nt":
        raise OSError("Run the installer check on Windows x64.")
    release, archive_name, setup_name = RELEASE, TARGETS["win64"], SETUP_FILENAME
    if private_qa:
        from private_qa import PRIVATE_ARCHIVE, PRIVATE_SETUP
        release, archive_name, setup_name = RELEASE / "private-qa", PRIVATE_ARCHIVE, PRIVATE_SETUP
    setup = release / setup_name
    sums = dict(line.split("  ")[::-1] for line in (release / "SHA256SUMS.txt").read_text().splitlines())
    slices = sorted(release.glob(setup.stem + "-*.bin"))
    if private_qa:
        assert slices, "The private installer needs its companion payload."
    for artifact in (setup, *slices):
        with artifact.open("rb") as f:
            assert hashlib.file_digest(f, "sha256").hexdigest() == sums[artifact.name], artifact.name
    with tempfile.TemporaryDirectory(prefix="qa-", dir=None if private_qa else CACHE.parent) as temp:
        root = Path(temp)
        appdir = root / "Karaoke IL"
        # The QA switch skips real account registration and shortcuts. It installs the release payload.
        subprocess.run(
            [
                str(setup),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/NOICONS",
                "/NOCLOSEAPPLICATIONS",
                "/KaraokeTest=1",
                "/DIR=" + str(appdir),
                "/LOG=" + str(root / "setup.log"),
            ],
            check=True,
            timeout=900 if private_qa else 360,
        )
        assert (appdir / "Karaoke IL.exe").is_file()
        with zipfile.ZipFile(release / archive_name) as archive:
            for item in archive.infolist():
                actual = appdir / item.filename.removeprefix("Karaoke IL/")
                assert actual.stat().st_size == item.file_size, item.filename
                with actual.open("rb") as stream:
                    crc = 0
                    while block := stream.read(1024 * 1024):
                        crc = zlib.crc32(block, crc)
                    assert crc == item.CRC, item.filename
        print("Every installed payload file matches the verified Windows ZIP.", flush=True)
        studio = appdir / "Studio"
        env = dict(
            os.environ,
            KARAOKE_HOME=str(root / "Listener"),
            PATH=str(Path(os.environ["SystemRoot"]) / "System32"),
            PYTHONNOUSERSITE="1",
            QT_QPA_PLATFORM="windows",
        )
        exe = subprocess.Popen([str(appdir / "Karaoke IL.exe")], env=env, cwd=root)
        try:
            parent = psutil.Process(exe.pid)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                descendants = parent.children(recursive=True)
                runtime = next((p for p in descendants if p.name().lower() == "python.exe"), None)
                if runtime:
                    break
                time.sleep(0.15)
            else:
                raise RuntimeError("The installed native launcher did not start its Python runtime.")
            window = Desktop(backend="uia").window(process=runtime.pid, title="Maagal Karaoke Studio")
            window.wait("exists visible", timeout=80)
            for title in ("Play Hatikva", "Play Lecha Dodi", "Play Shalom Aleichem"):
                window.child_window(title=title, control_type="Button").wait("enabled", timeout=30)
            window.child_window(title="Play Hatikva", control_type="Button").invoke()
            window.child_window(title="Pause", control_type="Button").wait("enabled", timeout=20)
            backing = window.child_window(title="Backing only", control_type="CheckBox")
            backing.toggle()
            time.sleep(0.6)
            assert backing.get_toggle_state() == 1
            window.child_window(title="Pause", control_type="Button").invoke()
            window.child_window(title="Play", control_type="Button").wait("enabled", timeout=15)
            assert len(list((root / "Listener/songs").glob("*/song.json"))) == 3
            for proc in [parent, *parent.children(recursive=True)]:
                assert proc.name().lower() in {"karaoke il.exe", "python.exe", "conhost.exe"}, proc.name()
                assert not any(c.status == psutil.CONN_LISTEN for c in proc.net_connections(kind="inet")), (
                    proc.name()
                )
            window.close()
            assert exe.wait(15) == 0
            print(
                "Installed Windows application opened from its launcher. Windows UI Automation played and paused Hatikva, switched backing, and found all three songs. No browser child or listening TCP socket.",
                flush=True,
            )
        finally:
            if exe.poll() is None:
                children = psutil.Process(exe.pid).children(recursive=True)
                for child in children:
                    child.terminate()
                psutil.wait_procs(children, timeout=8)
                exe.terminate()
                exe.wait(10)
        env["KARAOKE_HOME"] = str(root / "Fresh library")
        env["QT_QPA_PLATFORM"] = "offscreen"
        shots = CACHE / "verify/screens"
        subprocess.run(
            [
                str(studio / "python/python.exe"),
                "-I",
                "-B",
                "-u",
                str(DESKTOP / "smoke.py"),
                str(studio),
                str(shots),
            ],
            env=env,
            cwd=root,
            timeout=180,
            check=True,
        )
        print("Installed runtime passed the offline playback and editing checks.", flush=True)
        if recording:
            from verify import check_recording
            check_recording(studio, root, dict(env, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-qa", action="store_true")
    parser.add_argument("--recording", action="store_true")
    args = parser.parse_args()
    if args.recording and not args.private_qa:
        parser.error("--recording requires --private-qa")
    check(args.private_qa, args.recording)
