"""Fetch the pinned official Qt wheels for offline distribution and their published digests."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import shutil
import tempfile
import urllib.request

from fetch_runtimes import digest

TARGET = Path(__file__).resolve().parents[1] / ".build/desktop/qt"
VERSION = "6.8.3"


def download(package):
    with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/{VERSION}/json", timeout=45) as src:
        meta = json.load(src)
    for target, platform in (("win64", "win_amd64"), ("mac", "macosx_12_0_universal2")):
        (item,) = [f for f in meta["urls"] if f["filename"].endswith(platform + ".whl")]
        dest = TARGET / target / item["filename"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        want = item["digests"]["sha256"]
        if not dest.exists() or digest(dest) != want:
            with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as pending:
                tmp = Path(pending.name)
                try:
                    with urllib.request.urlopen(item["url"], timeout=90) as source:
                        shutil.copyfileobj(source, pending)
                except BaseException:
                    pending.close()
                    tmp.unlink(missing_ok=True)
                    raise
            if digest(tmp) != want:
                tmp.unlink(missing_ok=True)
                raise ValueError(f"Unexpected checksum for {dest.name}")
            tmp.replace(dest)
        print(target, dest.name, flush=True)


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(download, ["shiboken6", "PySide6-Essentials", "PySide6-Addons"]))
