"""Download the locked, platform-appropriate wheels without executing their contents."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys


DESKTOP = Path(__file__).resolve().parent
CACHE = DESKTOP.parent / ".build" / "desktop"
PLATFORMS = {"win64": "win_amd64", "mac-arm64": "macosx_12_0_arm64", "mac-intel": "macosx_12_0_x86_64"}

def requirements(target):
    files = [DESKTOP / "base-wheels.txt"]
    if target == "win64":
        files.append(DESKTOP / "windows-wheels.txt")
    return files


def download(target):
    destination = CACHE / "wheels" / target
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        sys.executable, "-m", "pip", "download", "--disable-pip-version-check",
        "--cache-dir", str(CACHE / "pip-cache" / target), "--dest", str(destination),
        "--only-binary", ":all:", "--no-deps", "--python-version", "3.11",
        "--platform", PLATFORMS[target], "--implementation", "cp", "--abi", "cp311",
        *[arg for path in requirements(target) for arg in ("-r", str(path))],
    ], check=True)


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(download, sys.argv[1:] or PLATFORMS))
