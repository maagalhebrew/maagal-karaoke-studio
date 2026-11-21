"""Wrap the verified Windows ZIP in the Maagal per-user installer using Inno Setup 6."""

import argparse
import errno
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from build import CACHE, DESKTOP, RELEASE, SETUP_FILENAME, TARGETS, checksums


def build_installer(compiler=None, *, private_qa=False):
    folder, archive_name, setup_name = RELEASE, TARGETS["win64"], SETUP_FILENAME
    if private_qa:
        from private_qa import PRIVATE_ARCHIVE, PRIVATE_SETUP
        folder, archive_name, setup_name = RELEASE / "private-qa", PRIVATE_ARCHIVE, PRIVATE_SETUP
    archive = folder / archive_name
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    maybe = [
        compiler,
        os.environ.get("ISCC"),
        shutil.which("ISCC"),
        CACHE.parent / "installer/compiler/ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", ".")) / "Programs/Inno Setup 6/ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", ".")) / "Inno Setup 6/ISCC.exe",
    ]
    compiler = next((Path(p) for p in maybe if p and Path(p).is_file()), None)
    if not compiler:
        raise SystemExit("Install Inno Setup 6 or supply the ISCC.exe path with --compiler.")
    sums = dict(line.split("  ")[::-1] for line in (folder / "SHA256SUMS.txt").read_text().splitlines())
    if sums.get(archive.name) != digest:
        raise ValueError("The Windows ZIP does not match the build checksum.")
    # Inno and older Windows tools have a 260-character path limit. Keep their source tree short.
    with tempfile.TemporaryDirectory(prefix="kil-", ignore_cleanup_errors=True) as temp:
        extracted = Path(temp)
        with zipfile.ZipFile(archive) as package:
            package.extractall(extracted)
        result = subprocess.run(
            [
                str(compiler),
                "/O" + temp,
                "/DStudioPayload=" + str(extracted / "Karaoke IL"),
                *(["/DPrivateQA=1"] if private_qa else []),
                str(DESKTOP / "installer.iss"),
            ],
            capture_output=True,
            text=True,
            errors="replace",
        )
        if result.returncode:
            raise RuntimeError("\n".join((result.stdout + "\n" + result.stderr).splitlines()[-20:]))
        slices = sorted(extracted.glob(Path(setup_name).stem + "-*.bin"))
        if private_qa and not slices:
            raise RuntimeError("The private installer is missing its companion payload.")
        files = [extracted / setup_name, *slices]
        for source in files:
            destination = folder / source.name
            try:
                os.replace(source, destination)
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise
                pending = destination.with_suffix(destination.suffix + ".partial")
                try:
                    shutil.copyfile(source, pending)
                    os.replace(pending, destination)
                finally:
                    pending.unlink(missing_ok=True)
    if private_qa:
        lines = [f"{digest}  {archive.name}"]
        for path in files:
            with (folder / path.name).open("rb") as stream:
                lines.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {path.name}")
        (folder / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="ascii")
    else:
        checksums()
    print(folder / setup_name, flush=True)
    for path in slices:
        print(folder / path.name, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler")
    parser.add_argument("--private-qa", action="store_true")
    args = parser.parse_args()
    build_installer(args.compiler, private_qa=args.private_qa)
