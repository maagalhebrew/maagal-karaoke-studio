"""Package the installed Windows processing runtime and verified model cache for private QA."""
import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from karaoke.desktop_models import FILES, REVISIONS  # noqa: E402

PRIVATE_ARCHIVE = "Maagal-Karaoke-Studio-Windows-x64-PRIVATE-QA.zip"
PRIVATE_SETUP = "Maagal-Karaoke-Studio-Windows-Setup-PRIVATE-QA.exe"
PRIVATE_NOTICE = """Private Maagal Karaoke Studio QA bundle. Do not redistribute.

Helsinki-NLP OPUS-MT Hebrew to English and Phonikud pronunciation at the
revisions listed in their bundled model notices.
Hebrew timing weights: ivrit.ai, Apache-2.0.
Spanish timing weights: Mobius Labs, Whisper large-v3-turbo conversion.
Stem separation weights: Alexandre Défossez, HTDemucs. Weight redistribution
remains pending review. These publisher model files are included unchanged.
"""


def model_entries(hub):
    for repo, assets in FILES.items():
        name = "models--" + repo.replace("/", "--")
        revision = REVISIONS[repo]
        prefix = f"models/hub/{name}"
        for asset, expected in assets.items():
            relative = f"snapshots/{revision}/{asset}"
            source = hub / name / relative
            if source.stat().st_size != expected[0]:
                raise ValueError(f"Unexpected size for QA model {source}")
            with source.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected[1]:
                    raise ValueError(f"Checksum mismatch for QA model {source}")
            yield f"{prefix}/{relative}", source
        yield f"{prefix}/refs/main", revision.encode("ascii")


def runtime_packages(python):
    check = """
import platform, sys, sysconfig
assert sys.version_info[:2] == (3, 11) and sys.platform == "win32"
assert platform.machine().lower() == "amd64"
assert sys.prefix != sys.base_prefix
import torch, torchaudio, demucs.hf, faster_whisper, stable_whisper
assert torch.version.cuda is None
print(sysconfig.get_path("purelib"))
"""
    result = subprocess.run([str(python), "-I", "-B", "-c", check], text=True,
                            capture_output=True, check=True, timeout=90)
    return Path(result.stdout.splitlines()[-1])


def include_private_models(out, base, hub):
    for relative, source in model_entries(hub):
        if isinstance(source, bytes):
            out.writestr(base + relative, source)
        else:
            out.write(source, base + relative, compress_type=zipfile.ZIP_STORED)
    out.writestr("PRIVATE-QA.txt", PRIVATE_NOTICE)
