"""Download and verify the six redistributable runtime archives used by the desktop build."""
import argparse
import hashlib
import shutil
import tempfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PYTHON_RELEASE = "20261021"
PYTHON_VERSION = "3.11.17"
FFMPEG_COMMIT = "df95abcb0ce6efff710dda5ef28a2f6f1dc21493"
CACHE = Path(__file__).resolve().parents[1] / ".build" / "desktop" / "downloads"
# Python digests are from the python-build-standalone release asset manifest.
# The FFmpeg digests are the Git LFS object identities at FFMPEG_COMMIT.
PLATFORMS = {
    "win64": ("x86_64-pc-windows-msvc", "7222d3245519b9f2e786b085af65a3fac06dffa1ddfbe27821ad9b75f2d98c62",
              "win32", "92662c2241e93fe71b3f3a01e94a0b0dc8cfad726019f96b83bc109ce44c5d0b"),
    "mac-arm64": ("aarch64-apple-darwin", "1d1335d9d526bc37061af3fe72b0edd88056d7e7d9488eb631946b10b4ab97bb",
                  "darwin_arm64", "b2da44a8169c4d09a97db996250690c3346f72e4795521d23d3dbb1e72421207"),
    "mac-intel": ("x86_64-apple-darwin", "2a9df73aa8f6ff595f912dfb642c7933f604f5c6e24234fd524cb77b2629b9fc",
                  "darwin", "70fd5b21cb37b6ea97c8b584cf76b3cc6a90179831c9c269811b9716c28605fb"),
}


def inputs(platforms):
    for platform in platforms:
        triple, python_sum, ffmpeg_name, ffmpeg_sum = PLATFORMS[platform]
        archive = f"cpython-{PYTHON_VERSION}%2B{PYTHON_RELEASE}-{triple}-install_only_stripped.tar.gz"
        yield (f"{platform}-python.tar.gz",
               f"https://releases.astral.sh/github/python-build-standalone/releases/download/{PYTHON_RELEASE}/{archive}",
               python_sum)
        yield (f"{platform}-ffmpeg.zip",
               f"https://media.githubusercontent.com/media/zackees/ffmpeg_bins/{FFMPEG_COMMIT}/v8.0/{ffmpeg_name}.zip",
               ffmpeg_sum)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(item):
    name, url, expected = item
    target = CACHE / name
    if target.is_file() and digest(target) == expected:
        return f"Verified {name} (cached)"
    with tempfile.NamedTemporaryFile(dir=CACHE, delete=False) as temp:
        pending = Path(temp.name)
    try:
        urls = [url]
        if url.startswith("https://releases.astral.sh/github/"):
            urls.append(url.replace("https://releases.astral.sh/github/", "https://github.com/astral-sh/"))
        for location in urls:
            request = urllib.request.Request(location, headers={"User-Agent": "Karaoke-IL-Desktop-Builder/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=90) as response, pending.open("wb") as out:
                    shutil.copyfileobj(response, out, length=1024 * 1024)
                break
            except urllib.error.URLError as exc:
                if location == urls[-1]:
                    raise RuntimeError(f"Could not fetch {name} from {location}: {exc}") from exc
        if digest(pending) != expected:
            raise ValueError(f"Checksum mismatch for {name}")
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)
    return f"Verified {name}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platforms", nargs="*", metavar="PLATFORM", help="win64, mac-arm64 or mac-intel; defaults to all")
    selected = parser.parse_args().platforms or list(PLATFORMS)
    if any(name not in PLATFORMS for name in selected):
        parser.error("Unknown platform")
    CACHE.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(fetch, inputs(selected)):
            print(result, flush=True)
